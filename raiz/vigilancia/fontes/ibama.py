"""Embargos do Ibama (dados abertos, CSV de ~200 MB), com pedido condicional pelo ETag.

Privacidade: o CSV traz nome e CPF/CNPJ do embargado, nome do imóvel e textos livres. Só as colunas de LISTA_COLUNAS
são lidas (as outras nem entram na memória) e todo texto que sobra passa pela máscara de CPF/CNPJ. Nada pessoal chega
ao disco da vigilância: o CSV bruto fica só no cache e é apagado depois de lido, sobrando a versão limpa em Parquet.

Cada termo ativo com polígono (ou só com o ponto do termo) é uma ocorrência; o espelho (SEQ_TAD, hash, ativo) mostra
o que entrou, mudou, foi cancelado ou desembargado desde a última leitura. Termo cancelado marca o alerta como falso
(fonte oficial); desembargo encerra o alerta, que continua verdadeiro.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely
from shapely.geometry import Point

from raiz.vigilancia import rede
from raiz.vigilancia.fontes import Contexto, Leitura, caixa_toca, data, montar, so_area, vazio
from raiz.vigilancia.privacidade import colunas_pessoais, mascarar

log = logging.getLogger(__name__)

# só estas colunas são lidas do CSV (lidas pelo nome; coluna nova do Ibama é ignorada)
LISTA_COLUNAS = [
    "SEQ_TAD",
    "NUM_TAD",
    "SER_TAD",
    "SIT_CANCELADO",
    "DAT_EMBARGO",
    "NUM_PROCESSO",
    "COD_MUNICIPIO",
    "UF",
    "NUM_LONGITUDE_TAD",
    "NUM_LATITUDE_TAD",
    "DETER_PRODES",
    "QTD_AREA_EMBARGADA",
    "TIPO_AREA",
    "GEOM_AREA_EMBARGADA",
    "DAT_ULT_ALTER_GEOM",
    "SIT_DESEMBARGO",
    "TIPO_DESEMBARGO",
    "DAT_DESEMBARGO",
    "DAT_ULT_ALTERACAO",
]
LINK = "https://servicos.ibama.gov.br/ctf/publico/areasembargadas/ConsultaPublicaAreasEmbargadas.php"


def ler_csv(caminho: Path) -> pd.DataFrame:
    cab = pd.read_csv(caminho, sep=";", nrows=0, encoding="utf-8-sig").columns
    usar = [c for c in LISTA_COLUNAS if c in cab]
    assert not colunas_pessoais(usar), "coluna pessoal na lista do Ibama"
    df = pd.read_csv(caminho, sep=";", usecols=usar, dtype=str, encoding="utf-8-sig", on_bad_lines="skip")
    for c in df.columns:
        if c != "GEOM_AREA_EMBARGADA":
            df[c] = df[c].map(mascarar)
    return df


def _geometria(wkt, lon, lat):
    if isinstance(wkt, str) and wkt.strip():
        try:
            g = shapely.from_wkt(wkt)
            g = so_area(g) if g is not None else None
            if g is not None and not g.is_empty:
                return g, False
        except shapely.errors.GEOSException:
            pass
    try:
        x, y = float(str(lon).replace(",", ".")), float(str(lat).replace(",", "."))
        if -75 < x < -28 and -35 < y < 6:
            return Point(x, y), True
    except (TypeError, ValueError):
        pass
    return None, False


def _hash(r: pd.Series) -> str:
    campos = ("SIT_CANCELADO", "SIT_DESEMBARGO", "DAT_ULT_ALTERACAO", "DAT_ULT_ALTER_GEOM", "DAT_DESEMBARGO")
    return hashlib.sha1("|".join(str(r.get(c, "")) for c in campos).encode()).hexdigest()[:12]


def _col(df: pd.DataFrame, c: str) -> pd.Series:
    return df[c] if c in df else pd.Series(None, index=df.index, dtype=object)


def espelho(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por termo: SEQ_TAD, hash, ativo, cancelado, desembargado, datas (sem nada pessoal)."""
    e = pd.DataFrame(
        {
            "seq_tad": df["SEQ_TAD"].astype(str),
            "hash": df.apply(_hash, axis=1),
            "cancelado": _col(df, "SIT_CANCELADO").fillna("").eq("S"),
            "desembargado": _col(df, "SIT_DESEMBARGO").fillna("").eq("S"),
            "dat_desembargo": _col(df, "DAT_DESEMBARGO").map(data),
            "dat_ult_alteracao": _col(df, "DAT_ULT_ALTERACAO").map(data),
        }
    )
    e["ativo"] = ~e["cancelado"] & ~e["desembargado"]
    return e.drop_duplicates("seq_tad", keep="last")


def ocorrencias(df: pd.DataFrame, ctx: Contexto, so: set[str] | None = None) -> gpd.GeoDataFrame:
    """Termos ativos (só os de `so`, quando dado) como ocorrências."""
    ativos = df[(_col(df, "SIT_CANCELADO").fillna("") != "S") & (_col(df, "SIT_DESEMBARGO").fillna("") != "S")]
    if so is not None:
        ativos = ativos[ativos["SEQ_TAD"].astype(str).isin(so)]
    linhas = []
    for _, r in ativos.iterrows():
        geo, so_ponto = _geometria(r.get("GEOM_AREA_EMBARGADA"), r.get("NUM_LONGITUDE_TAD"), r.get("NUM_LATITUDE_TAD"))
        if geo is None:
            continue
        if not caixa_toca(ctx.caixas, *geo.bounds):
            continue
        try:
            area = float(str(r.get("QTD_AREA_EMBARGADA") or "").replace(",", "."))
        except ValueError:
            area = None
        cod = str(r.get("COD_MUNICIPIO") or "")
        linhas.append(
            {
                "fonte": "ibama_embargo",
                "chave": str(r["SEQ_TAD"]),
                "classe": "embargo_ponto" if so_ponto else "embargo",
                "data_evento": data(r.get("DAT_EMBARGO")),
                "publicado_em": data(r.get("DAT_ULT_ALTERACAO")) or data(r.get("DAT_EMBARGO")),
                "area_ha": area,
                "uf": r.get("UF"),
                "cod_municipio_ibge": int(cod) if cod.isdigit() else None,
                "link": LINK,
                "atributos": {
                    "num_tad": r.get("NUM_TAD"),
                    "serie_tad": r.get("SER_TAD"),
                    "processo": r.get("NUM_PROCESSO"),
                    "origem_deter_prodes": r.get("DETER_PRODES"),
                    "tipo_area": r.get("TIPO_AREA"),
                    "so_ponto": so_ponto,
                },
                "car_fonte": None,
                "geometry": geo,
            }
        )
    return montar(linhas) if linhas else vazio()


def baixar_limpo(url: str, limpo: Path, etag: Path) -> bool:
    """Baixa o CSV (só se o ETag mudou) para uma pasta temporária fora do cache, lê só as colunas permitidas, grava
    a versão limpa em Parquet e apaga o bruto. O CSV com nome e CPF/CNPJ nunca fica no cache nem no estado."""
    h = {"If-None-Match": etag.read_text().strip()} if limpo.exists() and etag.exists() else {}
    r = rede.pedir("GET", url, ok=(200, 304), headers=h, stream=True, timeout=1800)
    if r.status_code == 304:
        return False
    with tempfile.TemporaryDirectory(prefix="raiz_ibama_") as tmp:
        bruto = Path(tmp) / "termo_de_embargo.csv"
        with open(bruto, "wb") as f:
            for pedaco in r.iter_content(1 << 20):
                f.write(pedaco)
        df = ler_csv(bruto)
    novo = limpo.with_name(limpo.name + ".tmp")
    df.to_parquet(novo, index=False)
    os.replace(novo, limpo)
    if r.headers.get("ETag"):
        etag.write_text(r.headers["ETag"])
    return True


def ler(ctx: Contexto, estado: dict, espelho_antigo: pd.DataFrame | None = None, refazer: bool = False) -> Leitura:
    """Lê o CSV (só se mudou, a não ser que `refazer`), devolve as ocorrências novas ou alteradas e o espelho novo.

    `refazer` (polígonos do Release mudaram) devolve todos os termos ativos para cruzar de novo."""
    url = ctx.regras.fonte("ibama_embargo")["url"]
    pasta = ctx.cfg.cache / "ibama"
    pasta.mkdir(parents=True, exist_ok=True)
    limpo = pasta / "termo_de_embargo_limpo.parquet"
    etag = pasta / "termo_de_embargo.etag"
    mudou = baixar_limpo(url, limpo, etag)
    if mudou:
        df = pd.read_parquet(limpo)
    elif not refazer and espelho_antigo is not None and len(espelho_antigo):
        return Leitura("ibama_embargo", vazio(), cursor=dict(estado.get("cursor") or {}), nota="sem mudança (304)")
    else:
        df = pd.read_parquet(limpo)
    novo = espelho(df)
    if refazer or espelho_antigo is None or not len(espelho_antigo):
        alvo = set(novo.loc[novo.ativo, "seq_tad"])
    else:
        antes = dict(zip(espelho_antigo["seq_tad"], espelho_antigo["hash"], strict=False))
        alvo = {s for s, h, a in zip(novo.seq_tad, novo.hash, novo.ativo, strict=True) if a and antes.get(s) != h}
    oc = ocorrencias(df, ctx, so=alvo)
    cancelados = set(novo.loc[novo.cancelado, "seq_tad"])
    desembargados = set(novo.loc[novo.desembargado & ~novo.cancelado, "seq_tad"])
    if espelho_antigo is not None and len(espelho_antigo):
        ja_cancelados = set(espelho_antigo.loc[espelho_antigo.cancelado, "seq_tad"])
        ja_desembargados = set(espelho_antigo.loc[espelho_antigo.desembargado, "seq_tad"])
        cancelados -= ja_cancelados
        desembargados -= ja_desembargados
    return Leitura(
        "ibama_embargo",
        oc,
        cursor={"termos": int(len(novo)), "ativos": int(novo.ativo.sum())},
        extras={"espelho": novo, "cancelados": cancelados, "desembargados": desembargados},
        nota=f"{len(novo)} termos, {int(novo.ativo.sum())} ativos, {len(alvo)} para cruzar",
    )
