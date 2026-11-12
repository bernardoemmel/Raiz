"""Rodada da coleta do CAR (e do SIGEF dos municípios que mudaram), com fila, histórico e alerta:

1. verifica a assinatura de todos os municípios das UFs do dia (2 pedidos pequenos cada) e marca os sujos;
2. a fila escolhe o que baixar (até 200 sujos; disjuntor >15% roda completo; reconciliação mensal força tudo);
3. cada município baixado vira um lote vigiado (Healthchecks + operacao.lote): espelho por município, histórico
   scd2 no PostGIS (bruto.car_imovel, bruto.sigef_parcela) e SIGEF do município;
4. a lista dos municípios que mudaram sai no resultado (base da fila de recálculo do funil, E8 passo 3).
"""

from __future__ import annotations

import datetime as dt
import logging

import requests
from sqlalchemy import Engine

from raiz.coleta import bruto, car, sigef
from raiz.coleta.espelho import Espelho
from raiz.coleta.fila import planejar, registrar_reconciliacao
from raiz.operacao.healthchecks import Healthchecks
from raiz.operacao.lotes import lote

log = logging.getLogger(__name__)


def rodada_car(
    engine: Engine,
    s: requests.Session,
    espelho: Espelho,
    municipios: dict[str, list[int]],
    hc: Healthchecks | None = None,
    url: str | None = None,
    historico: bool = True,
    s_sigef: requests.Session | None = None,
) -> dict:
    hc = hc or Healthchecks()
    agora = dt.datetime.now(dt.UTC)
    resumo = {"verificados": 0, "baixados": 0, "falhas": 0, "mudaram": [], "modo": {}, "historico": 0}
    for uf, cods in municipios.items():
        uf = uf.upper()
        with engine.begin() as con:
            for cod in cods:
                car.verificar_municipio(s, con, espelho, uf, cod)
                resumo["verificados"] += 1
            plano = planejar(con, car.FONTE, [f"{uf}/{c}" for c in cods])
        resumo["modo"][uf] = f"{plano.modo} ({len(plano.recortes)} de {plano.total}, {plano.sujos} sujos)"
        for recorte in plano.recortes:
            cod = int(recorte.split("/")[1])
            try:
                with lote(engine, hc, "coleta-car", uf, cod) as reg:
                    with engine.begin() as con:
                        r = car.coletar_municipio(s, con, espelho, uf, cod, forcar=plano.modo == "reconciliacao")
                    if r.acao in ("falha", "travado"):
                        raise RuntimeError(r.erro)
                    reg.detalhe.update(acao=r.acao, contagem=r.contagem, campo=r.campo_data)
                    d = r.diferenca
                    if d is not None:
                        reg.detalhe.update(novos=len(d.novos), mudaram=len(d.mudaram), sumiram=len(d.sumiram))
                        if d.mudou:
                            resumo["mudaram"].append(cod)
                    if (d is not None and d.mudou) or not espelho.caminho("sigef", uf, cod).exists():
                        ds = sigef.coletar_municipio(s_sigef or s, espelho, uf, cod)
                        if ds is not None:
                            reg.detalhe.update(sigef_total=ds.total, sigef_mudou=ds.mudou)
                resumo["baixados"] += 1
            except Exception as ex:  # noqa: BLE001 - o lote já registrou e avisou; segue para o próximo município
                resumo["falhas"] += 1
                log.warning("%s %s: %s", uf, cod, ex)
        # município com CAR no espelho e sem SIGEF (rodada anterior falhou antes dele): coleta agora
        for cod in cods:
            if espelho.caminho("car", uf, cod).exists() and not espelho.caminho("sigef", uf, cod).exists():
                try:
                    with lote(engine, hc, "coleta-sigef", uf, cod) as reg:
                        ds = sigef.coletar_municipio(s_sigef or s, espelho, uf, cod)
                        reg.detalhe.update(sigef_total=ds.total if ds else 0)
                except Exception as ex:  # noqa: BLE001
                    resumo["falhas"] += 1
                    log.warning("SIGEF %s %s: %s", uf, cod, ex)
        if plano.modo == "reconciliacao":
            with engine.begin() as con:
                registrar_reconciliacao(con, car.FONTE)
        if historico and not _uf_travada(engine, hc, uf, cods, resumo):
            resumo["historico"] += sincronizar_historico(engine, espelho, uf, cods, hc, agora, url)
    if historico:
        with engine.begin() as con:
            for t in ("car_imovel", "sigef_parcela"):
                if con.exec_driver_sql(f"select to_regclass('bruto.{t}')").scalar():
                    bruto.garantir_view(con, t)
    return resumo


LIMITE_UF = 0.15  # mais que isto dos municípios da UF mudando numa rodada trava a publicação (rodada 10)
MINIMO_UF = 10


def _uf_travada(engine: Engine, hc: Healthchecks, uf: str, cods: list[int], resumo: dict) -> bool:
    """Se mais de 15% dos municípios da UF mudou de uma vez, o histórico (e o funil) não recebe a versão nova até
    alguém liberar (raiz coleta liberar sicar_imoveis <UF>)."""
    from raiz.coleta.replicacao import atualizar, estado, evento

    mudaram = [c for c in resumo["mudaram"] if c in set(cods)]
    if len(cods) < MINIMO_UF or len(mudaram) / len(cods) <= LIMITE_UF:
        return False
    with engine.begin() as con:
        e = estado(con, car.FONTE, uf)
        if e is not None and e.liberado:
            atualizar(con, car.FONTE, uf, liberado=False)
            return False
        evento(
            con, car.FONTE, uf, "alerta", len(mudaram), {"trava": "uf", "fracao": round(len(mudaram) / len(cods), 3)}
        )
    try:
        with lote(engine, hc, "trava", uf, None) as reg:
            reg.detalhe.update(mudaram=len(mudaram), municipios=len(cods))
            raise RuntimeError(
                f"{uf}: {len(mudaram)} de {len(cods)} municípios mudaram; histórico e funil esperam "
                f"liberação (raiz coleta liberar {car.FONTE} {uf})"
            )
    except RuntimeError:
        pass
    resumo.setdefault("travadas", []).append(uf)
    return True


CAMADAS_HISTORICO = (
    ("car", car.FONTE, "car_imovel", "cod_imovel", car.VOLATEIS),
    ("sigef", sigef.FONTE, "sigef_parcela", "parcela_codigo", ()),
)


def sincronizar_historico(
    engine: Engine,
    espelho: Espelho,
    uf: str,
    cods: list[int],
    hc: Healthchecks,
    agora: dt.datetime,
    url: str | None = None,
) -> int:
    """Leva ao histórico (scd2) todo espelho de município diferente do que já está lá (hash do arquivo em
    coleta.replicacao.hash_conteudo). Pega também carga que falhou numa rodada anterior. Devolve quantos carregou."""
    from raiz.coleta.replicacao import atualizar, estado
    from raiz.versoes import sha256_arquivo

    n = 0
    for cod in cods:
        recorte = f"{uf}/{cod}"
        for camada, fonte, tabela, chave, volateis in CAMADAS_HISTORICO:
            f = espelho.caminho(camada, uf, cod)
            if not f.exists():
                continue
            h = sha256_arquivo(f)
            with engine.connect() as con:
                e = estado(con, fonte, recorte)
            if e is not None and e.hash_conteudo == h:
                continue
            try:
                with lote(engine, hc, "historico", uf, cod) as reg:
                    g = espelho.ler(camada, uf, cod)
                    bruto.carregar(tabela, bruto.linhas(g, chave, cod, volateis), agora, chave, url)
                    with engine.begin() as con:
                        extra = {} if e is not None else {"sujo": False}
                        atualizar(con, fonte, recorte, hash_conteudo=h, **extra)
                    reg.detalhe.update(tabela=tabela, linhas=len(g))
                n += 1
            except Exception as ex:  # noqa: BLE001 - fica pendente: o hash não foi gravado, a próxima rodada tenta
                log.warning("histórico %s %s: %s", tabela, recorte, ex)
    return n
