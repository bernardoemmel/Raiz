"""Coleta das camadas estaduais do catálogo (raiz/estaduais/fontes/<UF>.yaml), sem dado pessoal na saída.

Para cada fonte com `tipo: wfs` ou `tipo: arcgis` e `acesso: aberto`:
  1. lê a camada inteira da UF (WFS paginado ou ArcGIS por OBJECTID, com conferência da contagem: camada pela
     metade falha em vez de ser gravada), sempre pedida em EPSG:4674;
  2. apaga na entrada os campos de `descartar` e qualquer outro que pareça pessoal (nome, CPF, CNPJ...;
     `raiz.privacidade.colunas_pessoais`), guarda só os de `manter` que existirem (tolera coluna nova ou sumida);
  3. mascara CPF/CNPJ que apareça dentro de texto livre;
  4. calcula `efeito` e `motivo` de cada feição pelas `regra_efeito` (valor de campo, recência);
  5. grava estaduais_<id>.parquet e o estado de cada fonte em estaduais_cobertura.json
     (consultado | parcial | indisponivel | bloqueado_fora_brasil | sem_download).

Fonte bloqueada fora do Brasil fica registrada como tal: a coleta roda de novo a partir do Brasil e, até lá, o
cruzamento marca os imóveis da UF como "nao_verificado" nessa fonte (ausência de dado nunca vira livre).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import yaml

from raiz.privacidade import colunas_pessoais, mascarar

PASTA_FONTES = Path(__file__).with_name("fontes")
COBERTURA = "estaduais_cobertura.json"
EFEITOS = ("exclusao", "ressalva", "conferir", "informativo")
ACESSOS = ("aberto", "bloqueado_fora_brasil", "sem_download", "pedido", "regra")
CHAVES_ORDEM = ("fid", "id", "gid", "objectid", "OBJECTID", "ogc_fid", "OID")
CRS_METRICO = 5880
log = logging.getLogger(__name__)


# --- catálogo ----------------------------------------------------------------------------------------------------


def catalogo(ufs: Iterable[str] | None = None, pasta: Path = PASTA_FONTES) -> list[dict]:
    """Todas as fontes do catálogo (uma por camada lógica), com a UF preenchida."""
    quer = {u.upper() for u in ufs} if ufs else None
    fontes = []
    for arq in sorted(pasta.glob("*.yaml")):
        d = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        uf = d.get("uf") or arq.stem
        if quer and uf not in quer:
            continue
        for f in d.get("fontes") or []:
            fontes.append({"uf": uf, **f})
    return fontes


def validar(fontes: list[dict]) -> list[str]:
    """Erros do catálogo (vazio = ok). O teste do CI chama isto para cada UF."""
    erros, ids = [], set()
    for f in fontes:
        i = f.get("id") or "?"
        if i in ids:
            erros.append(f"{i}: id repetido")
        ids.add(i)
        for k in ("nome", "tema", "orgao", "acesso", "tipo", "efeito", "motivo", "criterio", "situacao"):
            if not f.get(k):
                erros.append(f"{i}: falta {k}")
        if f.get("efeito") not in EFEITOS:
            erros.append(f"{i}: efeito {f.get('efeito')!r} fora de {EFEITOS}")
        if f.get("acesso") not in ACESSOS:
            erros.append(f"{i}: acesso {f.get('acesso')!r} fora de {ACESSOS}")
        for r in f.get("regra_efeito") or []:
            if r.get("efeito") and r["efeito"] not in EFEITOS:
                erros.append(f"{i}: regra_efeito com efeito {r['efeito']!r}")
            if "campo" not in r or "padrao" not in r:
                erros.append(f"{i}: regra_efeito precisa de campo e padrao")
            else:
                re.compile(r["padrao"])
        if f.get("acesso") == "aberto" and f.get("tipo") in ("wfs", "arcgis"):
            if not f.get("url") or not (f.get("camada") or f.get("camadas") or f["tipo"] == "arcgis"):
                erros.append(f"{i}: fonte aberta sem url/camada")
            pessoais = colunas_pessoais(f.get("manter") or [], permitir=f.get("permitir") or [])
            if pessoais:
                erros.append(f"{i}: manter tem campo pessoal {pessoais}; mova para descartar ou declare em permitir")
    return erros


def camadas_da_fonte(f: dict) -> list[str]:
    """Nomes de camada (WFS) ou URLs de camada (ArcGIS) de uma fonte; expande {ano} e subcamadas."""
    if f["tipo"] == "arcgis":
        base = f["url"].rstrip("/")
        if f.get("subcamadas"):
            return [f"{base}/{n}" for n in f["subcamadas"]]
        return [base]
    nomes = f.get("camadas") or [f["camada"]]
    if f.get("anos"):
        nomes = [n.format(ano=a) for n in nomes for a in f["anos"]]
    return nomes


# --- leitura -----------------------------------------------------------------------------------------------------


def _wfs(s: requests.Session, url: str, nome: str, cql: str | None) -> gpd.GeoDataFrame:
    from raiz.coleta import wfs

    c = wfs.Camada(url=url, nome=nome, versao="2.0.0", srs="EPSG:4674")
    campos = wfs.campos(s, c)
    ordem = next((k for k in CHAVES_ORDEM if k in campos), None) or sorted(campos - {"geom", "geometry", "the_geom"})[0]
    return wfs.ler(s, c, ordenar_por=ordem, cql=cql, pagina=5000)


def _arcgis(s: requests.Session, url: str, where: str | None, timeout: int = 600) -> gpd.GeoDataFrame:
    """Leitura por OBJECTID crescente (como raiz.coleta.arcgis), montando as feições pelo JSON: o leitor GDAL
    falha em páginas grandes de alguns MapServer ("URL rejected"). Confere a contagem no fim."""
    from raiz.coleta import arcgis
    from raiz.coleta.wfs import LeituraIncompleta

    where = where or "1=1"
    d = arcgis.detalhes(s, url)
    oid = d.get("objectIdField") or next(
        (f["name"] for f in d.get("fields", []) if f.get("type") == "esriFieldTypeOID"), "OBJECTID"
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", oid):
        raise ValueError("ArcGIS informou campo OBJECTID inválido")
    passo = int(d.get("maxRecordCount") or 1000)
    total = arcgis.contar(s, url, where)
    partes, ultimo, recebidas = [], -1, 0
    while recebidas < total:
        r = s.get(
            f"{url}/query",
            params={
                "where": f"({where}) AND {oid} > {ultimo}",
                "orderByFields": f"{oid} ASC",
                "resultRecordCount": passo,
                "outFields": "*",
                "outSR": 4674,
                "f": "geojson",
            },  # fmt: skip
            timeout=timeout,
        )
        r.raise_for_status()
        feats = r.json().get("features")
        if feats is None:
            raise LeituraIncompleta("ArcGIS não devolveu uma página de feições válida")
        if not feats:
            break
        for f in feats:
            f.setdefault("properties", {})[oid] = f["properties"].get(oid, f.get("id"))
        g = gpd.GeoDataFrame.from_features(feats, crs=4674)
        ids = pd.to_numeric(g[oid], errors="raise")
        if not (ids > ultimo).all():
            raise LeituraIncompleta("paginação ArcGIS não avançou OBJECTID")
        partes.append(g)
        ultimo, recebidas = int(ids.max()), recebidas + len(g)
        if len(feats) < passo:
            break
    if recebidas != total:
        raise LeituraIncompleta(f"{url}: recebidas {recebidas} de {total} feições")
    if not partes:
        return gpd.GeoDataFrame(geometry=[], crs=4674)
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=4674)


def limpar(g: gpd.GeoDataFrame, f: dict) -> gpd.GeoDataFrame:
    """Apaga o que é pessoal e fica só com os campos úteis (tolerando campo que não exista)."""
    descartar = {c.lower() for c in f.get("descartar") or []}
    permitir = f.get("permitir") or []
    fora = {c for c in g.columns if c.lower() in descartar} | set(colunas_pessoais(g.columns, permitir))
    fora.discard("geometry")
    g = g.drop(columns=sorted(fora))
    manter = [c for c in (f.get("manter") or []) if c in g.columns]
    extra = [c for c in (f.get("regra_efeito") or []) if c.get("campo") in g.columns and c["campo"] not in manter]
    manter += [r["campo"] for r in extra]
    if f.get("campo_data") in g.columns and f["campo_data"] not in manter:
        manter.append(f["campo_data"])
    g = g[[*dict.fromkeys(manter), "geometry"]].copy()
    for c in manter:
        if g[c].dtype == object:
            g[c] = g[c].map(lambda v: mascarar(v) if isinstance(v, str) else v)
    return g


def _ano(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return float("nan")
    if isinstance(v, (int, float)):
        if v > 10**11:  # epoch em ms (ArcGIS)
            return float(dt.datetime.fromtimestamp(v / 1000, dt.UTC).year)
        return float(v) if 1900 < v < 2100 else float("nan")
    m = re.search(r"(19|20)\d\d", str(v))
    return float(m.group(0)) if m else float("nan")


def classificar(g: gpd.GeoDataFrame, f: dict, hoje: dt.date | None = None) -> gpd.GeoDataFrame:
    """efeito e motivo por feição: o padrão da fonte e, por cima, a primeira regra_efeito que casar."""
    hoje = hoje or dt.date.today()
    g = g.copy()
    g["efeito"] = f["efeito"]
    g["motivo"] = f["motivo"]
    ano = g[f["campo_data"]].map(_ano) if f.get("campo_data") in g.columns else pd.Series(float("nan"), index=g.index)
    g["ano"] = ano
    casou = pd.Series(False, index=g.index)
    for r in f.get("regra_efeito") or []:
        if r["campo"] not in g.columns:
            continue
        m = g[r["campo"]].astype("string").fillna("").str.contains(r["padrao"], regex=True) & ~casou
        if r.get("recente_anos"):
            m &= ano >= hoje.year - int(r["recente_anos"])
        g.loc[m, "efeito"] = r.get("efeito", f["efeito"])
        g.loc[m, "motivo"] = r.get("motivo", f["motivo"])
        casou |= m
    return g


def _raio(g: gpd.GeoDataFrame, raio_m: float | None) -> gpd.GeoDataFrame:
    if not raio_m or not len(g):
        return g
    g = g.to_crs(CRS_METRICO)
    g["geometry"] = g.geometry.buffer(float(raio_m))
    return g.to_crs(4674)


# --- coleta ------------------------------------------------------------------------------------------------------


def coletar_fonte(s: requests.Session, f: dict, hoje: dt.date | None = None) -> tuple[gpd.GeoDataFrame, dict]:
    partes, falhas = [], []
    for camada in camadas_da_fonte(f):
        try:
            g = (
                _arcgis(s, camada, f.get("filtro"))
                if f["tipo"] == "arcgis"
                else _wfs(s, f["url"], camada, f.get("filtro"))
            )
        except Exception as e:  # noqa: BLE001 - uma camada fora do ar não derruba as outras
            log.warning("estaduais: %s %s falhou: %s", f["id"], camada, type(e).__name__)
            falhas.append(camada)
            continue
        if len(g):
            g = limpar(g, f)
            g["camada"] = camada.rsplit("/", 2)[-2] if f["tipo"] == "arcgis" else camada
            partes.append(g)
    if partes:
        g = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=4674)
    else:
        g = gpd.GeoDataFrame({"camada": []}, geometry=[], crs=4674)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    for c in g.columns:  # páginas e anos diferentes trazem tipos misturados (data como texto e como data)
        if c != "geometry" and (g[c].dtype == object or str(g[c].dtype).startswith("datetime")):
            g[c] = g[c].map(lambda v: None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v))
    g = _raio(classificar(g, f, hoje), f.get("raio_m"))
    g.insert(0, "fonte_id", f["id"])
    n = len(camadas_da_fonte(f))
    estado = "indisponivel" if len(falhas) == n else ("parcial" if falhas else "consultado")
    return g, {"estado": estado, "uf": f["uf"], "feicoes": int(len(g)), "falhas": falhas}


def aplicar_desembargos(saidas: dict[str, gpd.GeoDataFrame], fontes: list[dict]) -> None:
    """Tira das camadas de embargo os processos que aparecem na camada de desembargo indicada (excluir_se_em)."""
    for f in fontes:
        regra = f.get("excluir_se_em")
        if not regra or f["id"] not in saidas or regra["fonte"] not in saidas:
            continue
        campo, g, d = regra["campo"], saidas[f["id"]], saidas[regra["fonte"]]
        if campo in g.columns and campo in d.columns:
            fora = set(d[campo].dropna().astype(str))
            saidas[f["id"]] = g[~g[campo].astype(str).isin(fora)].copy()


def conferir_sem_documento(pasta: Path) -> list[str]:
    """Arquivos da coleta com CPF/CNPJ em claro (deve voltar vazio antes de publicar)."""
    from raiz.privacidade import documento_em_identificador

    ruins = []
    for arq in pasta.glob("estaduais_*.parquet"):
        g = pd.read_parquet(arq)
        for c in g.columns:
            if c != "geometry" and g[c].dtype == object:
                if g[c].dropna().astype(str).map(documento_em_identificador).any():
                    ruins.append(f"{arq.name}:{c}")
    return ruins


def coletar(destino: Path, ufs: Iterable[str] | None = None, hoje: dt.date | None = None, sessao=None) -> dict:
    """Coleta o catálogo das UFs pedidas para `destino`. Devolve a cobertura (também gravada em JSON)."""
    from raiz.coleta.http import sessao as nova_sessao

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    s = sessao or nova_sessao()
    fontes = catalogo(ufs)
    arq = destino / COBERTURA
    cob = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"fontes": {}}
    saidas: dict[str, gpd.GeoDataFrame] = {}
    for f in fontes:
        base = {"uf": f["uf"], "efeito": f["efeito"], "tema": f["tema"], "acesso": f["acesso"]}
        if f["acesso"] != "aberto" or f["tipo"] not in ("wfs", "arcgis"):
            cob["fontes"][f["id"]] = {**base, "estado": f["acesso"] if f["acesso"] != "regra" else "regra"}
            continue
        g, info = coletar_fonte(s, f, hoje)
        cob["fontes"][f["id"]] = {**base, **info, "coletado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
        if info["estado"] != "indisponivel":
            saidas[f["id"]] = g
    aplicar_desembargos(saidas, fontes)
    for i, g in saidas.items():
        g.to_parquet(destino / f"estaduais_{i}.parquet", index=False)
        cob["fontes"][i]["feicoes"] = int(len(g))
    ruins = conferir_sem_documento(destino)
    if ruins:
        for i in saidas:
            (destino / f"estaduais_{i}.parquet").unlink(missing_ok=True)
        raise RuntimeError(f"documento pessoal na coleta estadual: {ruins}")
    cob["gerado_em"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    arq.write_text(json.dumps(cob, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cob
