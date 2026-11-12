"""Tempo até o aceite: incidência cumulativa com recusa como evento competitivo.

O relógio começa no envio real ao imóvel para um pedido. Sem resposta é censura
administrativa na data do corte, nunca recusa. Somente eventos ocorridos E
registrados até o corte entram; a oferta e o interesse atuais não são lidos.

O KaplanMeierFitter do lifelines calcula a sobrevivência sem nenhum desfecho.
A incidência de aceite soma S(t-) * aceites(t) / em_risco(t), preservando empates
entre aceite e recusa sem o jitter aleatório do AalenJohansenFitter. É um modelo
agrupado: não promete calibração por perfil sem retratos históricos do perfil.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from bisect import bisect_right
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter
from sqlalchemy import Connection, text

from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote

MODELO = "sobrevivencia_aceite"
ALVO = "aceite_dono_no_prazo"
ALGORITMO = "incidencia-competitiva-2026a"


def _utc(v: dt.datetime) -> dt.datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("a data do corte precisa de fuso horário")
    return v.astimezone(dt.UTC)


@dataclass(frozen=True)
class Observacao:
    pedido_id: str
    cod_imovel: str
    enviado_em: dt.datetime
    fim: dt.datetime
    desfecho: int  # 0: ainda sem desfecho; 1: aceite; 2: recusa

    @property
    def dias(self) -> float:
        return (_utc(self.fim) - _utc(self.enviado_em)).total_seconds() / 86400


def historico(con: Connection, corte: dt.datetime) -> list[Observacao]:
    """Um episódio por pedido e CAR, só envios reais conhecidos até o corte.

    Eventos sem pedido não são atribuídos a vários pedidos por suposição. O
    primeiro aceite/recusa encerra o episódio; contrato depois do aceite não o
    conta duas vezes. O estado atual da fila não permite espiar o futuro.
    """
    corte = _utc(corte)
    rs = con.execute(
        text("""select f.pedido_id, f.cod_imovel, f.enviado_em,
                       coalesce(e.ocorrido_em, :corte) as fim,
                       case when e.nivel in ('aceite_fase1', 'contrato_firme') then 1
                            when e.nivel = 'recusou' then 2 else 0 end as desfecho
                from negocio.contato_fila f
                join negocio.onda o on o.id = f.onda_id
                left join lateral (
                    select nivel, ocorrido_em from negocio.interesse_evento e
                    where e.pedido_id = f.pedido_id and e.cod_imovel = f.cod_imovel
                      and e.nivel in ('aceite_fase1', 'contrato_firme', 'recusou')
                      and e.ocorrido_em >= f.enviado_em and e.ocorrido_em <= :corte
                      and e.registrado_em <= :corte
                    order by e.ocorrido_em, e.id limit 1
                ) e on true
                where f.simulado = false and f.enviado_em <= :corte and o.criada_em <= :corte
                order by f.pedido_id, f.cod_imovel"""),
        {"corte": corte},
    )
    return [Observacao(str(r.pedido_id), r.cod_imovel, r.enviado_em, r.fim, r.desfecho) for r in rs]


@dataclass(frozen=True)
class Curva:
    corte: dt.datetime
    versao: str
    entradas_hash: str
    contatos: int
    aceites: int
    recusas: int
    tempos: tuple[float, ...]
    incidencia: tuple[float, ...]
    sobrevivencia: tuple[float, ...]
    limite_dias: float

    def _em(self, valores: tuple[float, ...], dias: float, antes: float) -> float:
        i = bisect_right(self.tempos, dias) - 1
        return valores[i] if i >= 0 else antes

    def chance(self, horizonte_dias: float, espera_dias: float = 0) -> float | None:
        """Chance de aceitar nos próximos dias, dado que ainda não teve desfecho.

        Não extrapola além do seguimento disponível. None distingue falta de
        suporte de chance zero. No instante inicial, inclui aceites imediatos.
        """
        if not all(math.isfinite(x) and x >= 0 for x in (horizonte_dias, espera_dias)):
            raise ValueError("horizonte e espera precisam ser dias finitos e não negativos")
        if horizonte_dias == 0:
            return 0.0
        fim = espera_dias + horizonte_dias
        if fim > self.limite_dias:
            return None
        f0 = self._em(self.incidencia, espera_dias, 0) if espera_dias else 0.0
        s0 = self._em(self.sobrevivencia, espera_dias, 1) if espera_dias else 1.0
        if s0 <= 0:
            return None
        return float(np.clip((self._em(self.incidencia, fim, 0) - f0) / s0, 0, 1))

    @property
    def mediana_dias(self) -> float | None:
        """Tempo para metade de todos os contatados aceitar; pode não ser atingido."""
        return next((t for t, f in zip(self.tempos, self.incidencia, strict=True) if f >= 0.5), None)


def ajustar(
    observacoes: list[Observacao], corte: dt.datetime, minimo_contatos: int = 30, minimo_aceites: int = 5
) -> Curva | None:
    """Ajusta somente com seguimento até o corte; pouco dado deixa o modelo ausente."""
    corte = _utc(corte)
    if minimo_contatos < 1 or minimo_aceites < 1:
        raise ValueError("os mínimos precisam ser positivos")
    chaves = set()
    for o in observacoes:
        if o.desfecho not in (0, 1, 2) or o.dias < 0 or _utc(o.fim) > corte:
            raise ValueError("observação inválida ou posterior ao corte")
        if o.desfecho == 0 and _utc(o.fim) != corte:
            raise ValueError("observação aberta precisa ser censurada na data do corte")
        chave = o.pedido_id, o.cod_imovel
        if chave in chaves:
            raise ValueError("episódio de contato repetido")
        chaves.add(chave)
    aceites = sum(o.desfecho == 1 for o in observacoes)
    recusas = sum(o.desfecho == 2 for o in observacoes)
    if len(observacoes) < minimo_contatos or aceites < minimo_aceites:
        return None
    dados = pd.DataFrame({"dias": [o.dias for o in observacoes], "desfecho": [o.desfecho for o in observacoes]})
    km = KaplanMeierFitter().fit(dados.dias, event_observed=dados.desfecho.ne(0))
    eventos = km.event_table
    s_antes = km.survival_function_.iloc[:, 0].shift(fill_value=1)
    n_aceites = dados.loc[dados.desfecho.eq(1)].groupby("dias").size().reindex(eventos.index, fill_value=0)
    incidencia = (s_antes * n_aceites / eventos.at_risk).cumsum()
    canonico = sorted(
        (o.pedido_id, o.cod_imovel, _utc(o.enviado_em).isoformat(), _utc(o.fim).isoformat(), o.desfecho)
        for o in observacoes
    )
    eh = hashlib.sha256(json.dumps(canonico, ensure_ascii=False).encode()).hexdigest()
    # A versão muda junto com código/dependência, mesmo sem atualizar a etiqueta manual.
    codigo = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receita = f"{ALGORITMO}|{codigo}|lifelines:{version('lifelines')}|{eh}|{corte.isoformat()}"
    versao = hashlib.sha256(receita.encode()).hexdigest()[:16]
    return Curva(
        corte,
        f"{ALGORITMO}+{versao}",
        eh,
        len(observacoes),
        aceites,
        recusas,
        tuple(float(v) for v in eventos.index),
        tuple(float(v) for v in incidencia),
        tuple(float(v) for v in km.survival_function_.iloc[:, 0]),
        float(dados.dias.max()),
    )


def congelar_pendentes(
    con: Connection,
    observacoes: list[Observacao],
    curva: Curva,
    horizonte_dias: int = 14,
    tipo: str = "ao_vivo",
) -> dict:
    """Registra por pedido a chance no prazo dos contatos ainda sem desfecho.

    A distribuição conserva a curva, a espera e o pedido para conferir depois
    exatamente a mesma pergunta. Sem suporte temporal, não inventa previsão.
    """
    if horizonte_dias < 1 or tipo not in ("ao_vivo", "backtest"):
        raise ValueError("horizonte ou tipo de previsão inválido")
    lotes: dict[str, list[Previsao]] = {}
    sem_suporte = 0
    for o in observacoes:
        if o.desfecho != 0:
            continue
        if _utc(o.fim) != curva.corte:
            raise ValueError("contato e curva precisam ter o mesmo corte")
        espera = o.dias
        chance = curva.chance(horizonte_dias, espera)
        if chance is None:
            sem_suporte += 1
            continue
        distribuicao = {
            "pedido_id": o.pedido_id,
            "enviado_em": _utc(o.enviado_em).isoformat(),
            "corte_em": curva.corte.isoformat(),
            "limite_em": (curva.corte + dt.timedelta(days=horizonte_dias)).isoformat(),
            "espera_dias": espera,
            "tempos_dias": curva.tempos,
            "incidencia_aceite": curva.incidencia,
            "sobrevivencia_sem_desfecho": curva.sobrevivencia,
            "mediana_dias": curva.mediana_dias,
            "contatos_treino": curva.contatos,
            "recusa_competitiva": True,
        }
        lotes.setdefault(o.pedido_id, []).append(
            Previsao(o.cod_imovel, ALVO, horizonte_dias, valor_num=chance, distribuicao=distribuicao)
        )
    novos, previsoes = 0, 0
    for pedido, ps in lotes.items():
        # Hash de receita também inclui o instante exato, pois data_corte no banco é só uma data.
        receita = hashlib.sha256(f"{curva.versao}|{curva.corte.isoformat()}|{horizonte_dias}".encode()).hexdigest()
        _, novo = registrar_lote(
            con,
            ps,
            Versoes(
                MODELO,
                curva.versao,
                f"{curva.entradas_hash}:pedido:{pedido}",
                curva.corte.date(),
                receita_hash=receita,
                tipo=tipo,
            ),
            f"tempo até o aceite; recusa competitiva; horizonte {horizonte_dias} dias",
        )
        novos += int(novo)
        previsoes += len(ps) if novo else 0
    return {"lotes_novos": novos, "previsoes_novas": previsoes, "sem_suporte": sem_suporte}


def avaliar(con: Connection, ate: dt.datetime) -> dict:
    """Confere previsões maturadas contra o mesmo pedido e prazo, sem juntar pedidos.

    A visão genérica de gabaritos casa somente CAR/alvo; aqui o vínculo inclui o
    pedido e o instante congelados. Desfechos anteriores ao corte conhecidos
    tardiamente são contados à parte, porque não eram contatos abertos de fato.
    """
    ate = _utc(ate)
    rs = con.execute(
        text("""select p.modelo_versao, p.valor_num, p.distribuicao->>'corte_em' as corte_em,
                       p.distribuicao->>'limite_em' as limite_em, e.nivel, e.ocorrido_em
                from aprendizado.previsao p
                left join lateral (
                    select nivel, ocorrido_em from negocio.interesse_evento e
                    where e.cod_imovel = p.cod_imovel
                      and e.pedido_id::text = p.distribuicao->>'pedido_id'
                      and e.nivel in ('aceite_fase1', 'contrato_firme', 'recusou')
                      and e.ocorrido_em >= (p.distribuicao->>'enviado_em')::timestamptz
                      and e.ocorrido_em <= (p.distribuicao->>'limite_em')::timestamptz
                      and e.registrado_em <= :ate
                    order by e.ocorrido_em, e.id limit 1
                ) e on true
                where p.modelo = :m and p.alvo = :a
                  and (p.distribuicao->>'limite_em')::timestamptz <= :ate
                order by p.id"""),
        {"m": MODELO, "a": ALVO, "ate": ate},
    )
    por_versao: dict[str, dict] = {}
    tardios = 0
    for r in rs:
        if r.ocorrido_em is not None and r.ocorrido_em <= dt.datetime.fromisoformat(r.corte_em):
            tardios += 1
            continue
        y = int(r.nivel in ("aceite_fase1", "contrato_firme"))
        v = por_versao.setdefault(r.modelo_versao, {"previsoes": 0, "aceites_no_prazo": 0, "brier": 0.0})
        v["previsoes"] += 1
        v["aceites_no_prazo"] += y
        v["brier"] += (float(r.valor_num) - y) ** 2
    for v in por_versao.values():
        v["brier"] /= v["previsoes"]
    return {"ate": ate.isoformat(), "por_versao": por_versao, "desfechos_anteriores_conhecidos_tardiamente": tardios}
