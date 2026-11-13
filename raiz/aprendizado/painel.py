"""Resumo público do aprendizado, sem linhas, imóveis ou detalhes pagos.

As notas usam somente previsões maturadas, com gabarito na data-alvo e
cronologia imutável comprovada. Sem período estruturado no gabarito, outra data
não comprova o horizonte. Horizontes e tipos de nota não são misturados. Um grupo só aparece
com cinco imóveis distintos observados; nenhuma contagem de grupos suprimidos
é divulgada. O placar interno e o hub completo continuam autenticados.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from raiz.aprendizado import acerto
from raiz.privacidade import documento_em_identificador

MINIMO_IMOVEIS = 5
IDENTIFICADOR = re.compile(r"[A-Za-z][A-Za-z0-9_.+:-]{0,119}\Z")
VERSAO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+:-]{0,119}\Z")


def _versao_valida(modelo: str, valor: str) -> bool:
    if VERSAO.fullmatch(valor):
        return True
    # O exportador documental registra modelo|prompt_versao. Mantém duas partes técnicas e o limite total.
    partes = valor.split("|")
    return (
        modelo == "leitor_certidao"
        and len(valor) <= 120
        and len(partes) == 2
        and all(VERSAO.fullmatch(p) for p in partes)
    )


def _dia(valor) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(valor))
    except ValueError:
        return None


def _instante(valor) -> dt.datetime | None:
    try:
        instante = dt.datetime.fromisoformat(str(valor))
        return instante.astimezone(dt.UTC) if instante.tzinfo else None
    except ValueError:
        return None


FALSOS = {"0", "0.0", "false", "falso", "não", "nao", "recusou", "recusado", "não aceitou", "nao aceitou"}
AUSENTES = {
    "",
    "desconhecido",
    "desconhecida",
    "pendente",
    "indisponivel",
    "indisponível",
    "não informado",
    "nao informado",
    "sem informação",
    "sem informacao",
    "null",
    "none",
    "n/a",
}


def _linha_valida(r: Mapping) -> dict | None:
    """Valida somente a projeção; nunca modifica os registros congelados ou o cálculo histórico de notas."""
    numeros = [r.get(k) for k in ("valor_num", "real_num", "p10", "p50", "p90")]
    if any(
        v is not None and (not isinstance(v, int | float) or isinstance(v, bool) or not math.isfinite(v))
        for v in numeros
    ):
        return None
    if all(r.get(k) is not None for k in ("p10", "p50", "p90")) and not r["p10"] <= r["p50"] <= r["p90"]:
        return None
    if acerto.e_probabilidade(r["alvo"]):
        previsto = r.get("valor_num")
        if previsto is None or not 0 <= previsto <= 1:
            return None  # o clamp do placar legado não é evidência válida
        real = r.get("real_num")
        if real is not None and real not in (0, 1):
            return None
        if r.get("real_texto") is not None:
            texto = str(r["real_texto"]).strip().lower()
            if texto in acerto.VERDADE:
                do_texto = 1
            elif texto in FALSOS:
                do_texto = 0
            else:
                return None  # ausência/desconhecimento nunca vira falso, mesmo com zero numérico
            if real is not None and real != do_texto:
                return None  # gabarito contraditório também não comprova resultado
            real = do_texto
        if real is None:
            return None
        return {**r, "real_num": real, "real_texto": None}
    for campo in ("valor_texto", "real_texto"):
        if r.get(campo) is not None and str(r[campo]).strip().lower() in AUSENTES:
            return None
    return dict(r)


def resumir(linhas: Iterable[Mapping], agora: dt.datetime | None = None) -> dict:
    """Allowlist positiva: só métricas agregadas, versões e datas do grupo."""
    agora = agora or dt.datetime.now(dt.UTC)
    grupos: dict[tuple, list] = defaultdict(list)
    for r in linhas:
        ids = tuple(r.get(k) for k in ("modelo", "modelo_versao", "alvo"))
        if not all(isinstance(v, str) for v in ids):
            continue
        # Versões podem começar por dígitos, mas não recebem texto livre.
        if not IDENTIFICADOR.fullmatch(ids[0]) or not IDENTIFICADOR.fullmatch(ids[2]):
            continue
        if not _versao_valida(ids[0], ids[1]):
            continue
        if any(documento_em_identificador(v) for v in ids):
            continue
        avaliacao = r.get("tipo")
        if avaliacao not in {"ao_vivo", "backtest"}:
            continue
        horizonte = r.get("horizonte_dias")
        corte, fim, observado = (_dia(r.get(k)) for k in ("data_corte", "horizonte_em", "observado_em"))
        if (
            not isinstance(horizonte, int)
            or isinstance(horizonte, bool)
            or horizonte <= 0
            or not corte
            or not fim
            or fim > agora.date()
        ):
            continue
        # Gabaritos não têm início/fim do período medido. Só a data-alvo exata comprova a mesma referência;
        # evento antecipado ou medição tardia não recebe uma janela inventada pelo painel.
        if (fim - corte).days != horizonte or observado != fim or not r.get("gabarito_id"):
            continue
        criada = _instante(r.get("previsao_criada_em"))
        registrada = _instante(r.get("gabarito_registrado_em"))
        if (
            not criada
            or not registrada
            or criada > agora
            or registrada > agora
            or criada.date() < corte
            or registrada.date() < observado
        ):
            continue
        # observado_em só tem o dia. Mesmo dia não comprova que a previsão antecedeu o resultado.
        # Falta de prova não transforma um registro ao vivo em backtest válido.
        if avaliacao == "ao_vivo" and (criada.date() >= observado or criada > registrada):
            continue
        if not r.get("cod_imovel") or not str(r.get("gabarito_fonte") or "").strip():
            continue
        validada = _linha_valida(r)
        if validada is None:
            continue
        nota = acerto.nota(validada)
        if nota is None or any(not math.isfinite(v) for k, v in nota.items() if k != "tipo"):
            continue
        grupos[(*ids, horizonte, nota["tipo"], avaliacao)].append((r, nota))
    versoes = []
    for (modelo, versao, alvo, horizonte, tipo, avaliacao), pares in sorted(grupos.items()):
        if len({r["cod_imovel"] for r, _ in pares}) < MINIMO_IMOVEIS:
            continue
        metricas = {m: round(sum(n[m] for _, n in pares) / len(pares), 6) for m in acerto.METRICAS[tipo]}
        versoes.append(
            {
                "modelo": modelo,
                "versao": versao,
                "alvo": alvo,
                "horizonte_dias": horizonte,
                "tipo": tipo,
                "avaliacao": avaliacao,
                "criterio_temporal": "observacao_na_data_alvo",
                "cronologia": ("congelada_antes_da_observacao" if avaliacao == "ao_vivo" else "backtest_declarado"),
                "comparacoes": len(pares),
                "imoveis_observados": len({r["cod_imovel"] for r, _ in pares}),
                "primeiro_corte": str(min(_dia(r["data_corte"]) for r, _ in pares)),
                "ultimo_corte": str(max(_dia(r["data_corte"]) for r, _ in pares)),
                "ultima_observacao": str(max(_dia(r["observado_em"]) for r, _ in pares)),
                "metricas": metricas,
            }
        )
    return {
        "schema": "raiz.acerto.publico.v1",
        "gerado_em": agora.isoformat(),
        "fonte": "Banco de aprendizado da Raíz",
        "minimo_imoveis": MINIMO_IMOVEIS,
        "versoes": versoes,
    }


def ler(engine: Engine) -> dict:
    with engine.connect() as con:
        # Empurra o corte para o banco antes de parear/materializar previsões ainda sem resultado.
        linhas = con.execute(
            text("""
            select v.modelo, v.modelo_versao, v.alvo, v.tipo, v.horizonte_dias, v.cod_imovel,
                   v.data_corte, v.horizonte_em, v.observado_em, v.gabarito_id, v.gabarito_fonte,
                   v.valor_num, v.valor_texto, v.real_num, v.real_texto, v.p10, v.p50, v.p90,
                   p.criada_em as previsao_criada_em, g.registrado_em as gabarito_registrado_em
            from aprendizado.previsao_contra_gabarito v
            join aprendizado.previsao p on p.id = v.previsao_id
            join aprendizado.gabarito g on g.id = v.gabarito_id
            where v.horizonte_em <= current_date and v.observado_em = v.horizonte_em
              and v.gabarito_fonte is not null and trim(v.gabarito_fonte) <> ''
              and v.tipo in ('ao_vivo', 'backtest')
        """)
        ).mappings()
        return resumir(linhas)


def exportar(engine: Engine, destino: str | Path) -> None:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(ler(engine), ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def roteador(engine_de):
    r = APIRouter(tags=["aprendizado"])
    cache = {}
    trava = threading.Lock()

    @r.get("/acerto/resumo")
    def resumo(request: Request):
        # Guarda apenas a projeção pública por cinco minutos; concorrência não repete a varredura.
        engine = engine_de(request)
        with trava:
            if cache.get("engine") is not engine or time.monotonic() >= cache.get("expira", 0):
                dado = ler(engine)
                cache.update(engine=engine, dado=dado, expira=time.monotonic() + 300)
            return JSONResponse(cache["dado"], headers={"Cache-Control": "public, max-age=300"})

    return r
