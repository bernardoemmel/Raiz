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
    resumo = {"verificados": 0, "baixados": 0, "falhas": 0, "mudaram": [], "modo": {}}
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
                    if r.acao == "falha":
                        raise RuntimeError(r.erro)
                    reg.detalhe.update(acao=r.acao, contagem=r.contagem, campo=r.campo_data)
                    if r.diferenca is not None:
                        d = r.diferenca
                        reg.detalhe.update(novos=len(d.novos), mudaram=len(d.mudaram), sumiram=len(d.sumiram))
                        if d.mudou:
                            resumo["mudaram"].append(cod)
                        if historico and (d.mudou or d.escreveu):
                            _historico(espelho, uf, cod, agora, url)
                        if d.mudou or not espelho.caminho("sigef", uf, cod).exists():
                            ds = sigef.coletar_municipio(s_sigef or s, espelho, uf, cod)
                            if ds is not None:
                                reg.detalhe.update(sigef_total=ds.total, sigef_mudou=ds.mudou)
                                if historico and (ds.mudou or ds.escreveu):
                                    g = espelho.ler("sigef", uf, cod)
                                    bruto.carregar(
                                        "sigef_parcela",
                                        bruto.linhas(g, "parcela_codigo", cod),
                                        agora,
                                        "parcela_codigo",
                                        url,
                                    )
                resumo["baixados"] += 1
            except Exception as ex:  # noqa: BLE001 - o lote já registrou e avisou; segue para o próximo município
                resumo["falhas"] += 1
                log.warning("%s %s: %s", uf, cod, ex)
        if plano.modo == "reconciliacao":
            with engine.begin() as con:
                registrar_reconciliacao(con, car.FONTE)
    if historico:
        with engine.begin() as con:
            for t in ("car_imovel", "sigef_parcela"):
                if con.exec_driver_sql(f"select to_regclass('bruto.{t}')").scalar():
                    bruto.garantir_view(con, t)
    return resumo


def _historico(espelho: Espelho, uf: str, cod: int, agora: dt.datetime, url: str | None) -> None:
    g = espelho.ler("car", uf, cod)
    bruto.carregar("car_imovel", bruto.linhas(g, "cod_imovel", cod, car.VOLATEIS), agora, "cod_imovel", url)
