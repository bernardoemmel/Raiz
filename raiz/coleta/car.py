"""CAR incremental por município (E1 passo 3), gravado no espelho por município e no PostGIS com histórico.

Por UF, o DescribeFeatureType diz se a camada tem data_atualizacao (15 UFs têm, 12 não):
- com o campo: assinatura = contagem + data_atualizacao mais nova. Se mudou, baixa só o que tem
  data_atualizacao > cursor - 2 dias e junta com o espelho; se a contagem do espelho não bater com a do servidor
  (imóvel cancelado some da camada sem mudar data), baixa o município inteiro.
- sem o campo: assinatura = contagem + dat_criacao mais nova; se mudou, baixa o município inteiro.
- forcar=True (reconciliação mensal): baixa inteiro, sem olhar assinatura.
Toda gravação passa pelo espelho (MERGE com hash por imóvel) e só o que mudou vai para o histórico (scd2).
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field

import geopandas as gpd
import pandas as pd
import requests
from sqlalchemy import Connection

from raiz.coleta import wfs
from raiz.coleta.espelho import Diferenca, Espelho
from raiz.coleta.manifesto import carregar
from raiz.coleta.replicacao import atualizar, estado, evento

log = logging.getLogger(__name__)
FONTE = "sicar_imoveis"
VOLATEIS = ("id",)  # id da feição no GeoServer muda entre publicações; não é mudança do imóvel


@dataclass
class ResultadoCAR:
    uf: str
    cod: int
    acao: str  # sem_mudanca | incremental | completo
    diferenca: Diferenca | None = None
    contagem: int | None = None
    erro: str | None = None
    campo_data: str = ""
    detalhe: dict = field(default_factory=dict)


def camada(uf: str) -> wfs.Camada:
    f = carregar().fonte(FONTE)
    return wfs.Camada(f.url, f.model_extra["camada"].format(uf=uf.lower()), f.model_extra.get("versao_wfs", "2.0.0"))


def campo_data(s: requests.Session, con: Connection, uf: str) -> str:
    """data_atualizacao se a camada da UF tem o campo; senão dat_criacao. Guardado em coleta.replicacao (recorte UF)."""
    e = estado(con, FONTE, uf.upper())
    if e is not None and e.cursor in ("data_atualizacao", "dat_criacao"):
        return e.cursor
    campos = wfs.campos(s, camada(uf))
    escolhido = "data_atualizacao" if "data_atualizacao" in campos else "dat_criacao"
    atualizar(con, FONTE, uf.upper(), cursor=escolhido, sujo=False, verificado_em=dt.datetime.now(dt.UTC))
    return escolhido


def _maior_data(g: gpd.GeoDataFrame, campo: str) -> str | None:
    if campo not in g or not len(g):
        return None
    v = pd.to_datetime(g[campo], errors="coerce", utc=True).max()
    return None if pd.isna(v) else v.isoformat()


def coletar_municipio(
    s: requests.Session,
    con: Connection,
    espelho: Espelho,
    uf: str,
    cod: int,
    forcar: bool = False,
    pagina: int | None = None,
) -> ResultadoCAR:
    uf = uf.upper()
    recorte = f"{uf}/{cod}"
    c = camada(uf)
    pagina = pagina or carregar().fonte(FONTE).model_extra.get("pagina", 10000)
    agora = dt.datetime.now(dt.UTC)
    campo = campo_data(s, con, uf)
    cql = f"cod_municipio_ibge={cod}"
    try:
        ass = wfs.assinatura(s, c, campo, cql)
        n_servidor = int(ass.split("|")[0])
        e = estado(con, FONTE, recorte)
        tem_espelho = espelho.caminho("car", uf, cod).exists()
        if not forcar and e is not None and e.assinatura == ass and tem_espelho:
            atualizar(con, FONTE, recorte, verificado_em=agora, sujo=False, tentativas=0, ultimo_erro=None)
            return ResultadoCAR(uf, cod, "sem_mudanca", contagem=n_servidor, campo_data=campo)

        acao, novo = "completo", None
        if not forcar and campo == "data_atualizacao" and e is not None and e.cursor and tem_espelho:
            desde = (pd.Timestamp(e.cursor) - pd.Timedelta(days=2)).strftime("%Y-%m-%d")
            delta = wfs.ler(s, c, "cod_imovel", f"{cql} AND data_atualizacao > '{desde}'", pagina)
            atual = espelho.ler("car", uf, cod)
            junto = pd.concat([atual[~atual.cod_imovel.isin(delta.cod_imovel)], delta], ignore_index=True)
            if len(junto) == n_servidor:
                acao, novo = "incremental", gpd.GeoDataFrame(junto, geometry="geometry", crs=4674)
        if novo is None:
            novo = wfs.ler(s, c, "cod_imovel", cql, pagina)
        dif = espelho.gravar("car", uf, cod, novo, "cod_imovel", VOLATEIS)
        maior = _maior_data(novo, "data_atualizacao") if campo == "data_atualizacao" else None
        atualizar(
            con,
            FONTE,
            recorte,
            assinatura=ass,
            contagem=n_servidor,
            cursor=maior,
            sujo=False,
            tentativas=0,
            ultimo_erro=None,
            verificado_em=agora,
            coletado_em=agora,
        )
        for tipo, chaves in (("novos", dif.novos), ("mudaram", dif.mudaram), ("sumiram", dif.sumiram)):
            if chaves:
                evento(con, FONTE, recorte, tipo, len(chaves), {"exemplos": chaves[:20], "acao": acao})
        return ResultadoCAR(uf, cod, acao, dif, n_servidor, campo_data=campo)
    except Exception as ex:  # noqa: BLE001 - fica sujo, com nova tentativa na próxima rodada
        e = estado(con, FONTE, recorte)
        atualizar(
            con,
            FONTE,
            recorte,
            sujo=True,
            tentativas=(e.tentativas if e else 0) + 1,
            ultimo_erro=f"{type(ex).__name__}: {ex}",
            verificado_em=agora,
        )
        evento(con, FONTE, recorte, "falha", detalhe={"erro": f"{type(ex).__name__}: {str(ex)[:200]}"})
        return ResultadoCAR(uf, cod, "falha", erro=f"{type(ex).__name__}: {ex}", campo_data=campo)


def verificar_municipio(s: requests.Session, con: Connection, espelho: Espelho, uf: str, cod: int) -> bool:
    """Só a assinatura (2 pedidos pequenos). Marca o município como sujo se mudou. Devolve se está sujo."""
    uf = uf.upper()
    recorte = f"{uf}/{cod}"
    agora = dt.datetime.now(dt.UTC)
    try:
        ass = wfs.assinatura(s, camada(uf), campo_data(s, con, uf), f"cod_municipio_ibge={cod}")
    except Exception as ex:  # noqa: BLE001
        e = estado(con, FONTE, recorte)
        atualizar(
            con,
            FONTE,
            recorte,
            sujo=True,
            tentativas=(e.tentativas if e else 0) + 1,
            ultimo_erro=f"{type(ex).__name__}: {ex}",
            verificado_em=agora,
        )
        return True
    e = estado(con, FONTE, recorte)
    sujo = e is None or e.assinatura != ass or not espelho.caminho("car", uf, cod).exists()
    atualizar(con, FONTE, recorte, sujo=sujo or bool(e and e.sujo), verificado_em=agora)
    return sujo
