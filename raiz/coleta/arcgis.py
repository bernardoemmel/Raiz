"""Fonte ArcGIS REST (Ibama, SFB, IPAAM, ANA), no molde do ArcGISFeatureServerSpider (desenho):

- lê os detalhes da camada (?f=json): campo de id, maxRecordCount e editingInfo.lastEditDate;
- se lastEditDate não mudou desde a última coleta, pula a camada inteira (nada é baixado);
- pagina por OBJECTID crescente (where id > último, orderByFields), não por offset, e confere o total com
  returnCountOnly: camada pela metade falha em vez de ser gravada.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import re
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
import requests
from sqlalchemy import Connection

from raiz.coleta.espelho import Diferenca, Espelho
from raiz.coleta.manifesto import UFS, Fonte, carregar
from raiz.coleta.replicacao import atualizar, estado, evento
from raiz.coleta.wfs import LeituraIncompleta
from raiz.privacidade import colunas_pessoais, mascarar


def detalhes(s: requests.Session, url: str, timeout: int = 60) -> dict:
    r = s.get(url, params={"f": "json"}, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"ArcGIS: {j['error']}")
    return j


def ultima_edicao(d: dict) -> int | None:
    edicao = (d.get("editingInfo") or {}).get("lastEditDate")
    if edicao is not None and (isinstance(edicao, bool) or not isinstance(edicao, int) or edicao < 0):
        raise LeituraIncompleta("ArcGIS informou lastEditDate inválido")
    return edicao


def _contrato(d: dict) -> dict:
    """Metadados que afetam a leitura; mudanças de esquema invalidam também camadas sem lastEditDate."""
    return {k: d.get(k) for k in ("objectIdField", "fields", "geometryType", "spatialReference", "hasZ", "hasM")}


def _bbox(bbox, srid: int = 4674) -> dict:
    if bbox is None:
        return {}
    if len(bbox) != 4 or not all(math.isfinite(float(v)) for v in bbox):
        raise ValueError("bbox precisa de quatro coordenadas finitas: oeste,sul,leste,norte")
    x0, y0, x1, y1 = map(float, bbox)
    if not (-180 <= x0 < x1 <= 180 and -90 <= y0 < y1 <= 90):
        raise ValueError("bbox inválida em longitude/latitude (EPSG:4674)")
    return {"geometry": ",".join(map(str, (x0, y0, x1, y1))), "geometryType": "esriGeometryEnvelope",
            "inSR": srid, "spatialRel": "esriSpatialRelIntersects"}  # fmt: skip


def contar(s: requests.Session, url: str, where: str = "1=1", timeout: int = 120, bbox=None) -> int:
    p = {"where": where, "returnCountOnly": "true", "f": "json", **_bbox(bbox)}
    r = s.get(f"{url}/query", params=p, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if "error" in j or "count" not in j:
        raise LeituraIncompleta("ArcGIS não informou a contagem da camada")
    n = int(j["count"])
    if n < 0:
        raise LeituraIncompleta("ArcGIS informou contagem negativa")
    return n


def ler(
    s: requests.Session,
    url: str,
    where: str = "1=1",
    ultima_edicao_conhecida: int | None = None,
    srid: int = 4674,
    timeout: int = 600,
    bbox=None,
    campos: list[str] | None = None,
) -> tuple[gpd.GeoDataFrame | None, int | None]:
    """Devolve (camada, lastEditDate). Sem edição conhecida, sempre lê. `bbox` está em EPSG:4674.

    O padrão sem `campos` preserva o leitor legado. A coleta do manifesto exige allowlist e descarta campos
    extras mesmo se o servidor ignorar outFields. Nenhuma página é persistida antes da conferência final.
    """
    filtro_espacial = _bbox(bbox)
    d = detalhes(s, url)
    edicao = ultima_edicao(d)
    if ultima_edicao_conhecida is not None and edicao == ultima_edicao_conhecida:
        return None, edicao
    oid = d.get("objectIdField") or next(
        (f["name"] for f in d.get("fields", []) if f.get("type") == "esriFieldTypeOID"), "OBJECTID"
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", oid):
        raise ValueError("ArcGIS informou campo OBJECTID inválido")
    permitidos = None if campos is None else list(dict.fromkeys([oid, *campos]))
    if permitidos is not None:
        if colunas_pessoais(permitidos) or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c) for c in permitidos):
            raise ValueError("allowlist ArcGIS contém campo pessoal ou identificador inválido")
        conhecidos = {f["name"] for f in d.get("fields", [])}
        if conhecidos and set(permitidos) - conhecidos:
            raise LeituraIncompleta("a camada ArcGIS perdeu campos previstos na allowlist")
    passo = int(d.get("maxRecordCount") or 1000)
    if passo <= 0:
        raise ValueError("ArcGIS informou tamanho de página inválido")
    total = contar(s, url, where, bbox=bbox)
    partes, ultimo = [], -1
    recebidas = 0
    while recebidas < total:
        r = s.get(
            f"{url}/query",
            params={
                "where": f"({where}) AND {oid} > {ultimo}",
                "orderByFields": f"{oid} ASC",
                "resultRecordCount": passo,
                "outFields": "*" if permitidos is None else ",".join(permitidos),
                "outSR": srid,
                "f": "geojson",
                **filtro_espacial,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        j = r.json()
        if "error" in j or "features" not in j:
            raise LeituraIncompleta("ArcGIS não devolveu uma página de feições válida")
        feats = j["features"]
        if not feats:
            break
        g = gpd.read_file(io.BytesIO(r.content), engine="pyogrio").set_crs(srid, allow_override=True)
        if oid not in g:
            raise LeituraIncompleta("página ArcGIS sem OBJECTID")
        ids = pd.to_numeric(g[oid], errors="raise")
        if (
            ids.isna().any()
            or not ids.is_unique
            or not ids.is_monotonic_increasing
            or not (ids > ultimo).all()
            or not (ids % 1 == 0).all()
        ):
            raise LeituraIncompleta("paginação ArcGIS repetiu ou não avançou OBJECTID")
        if permitidos is not None:
            if set(permitidos) - set(g.columns):
                raise LeituraIncompleta("página ArcGIS sem todos os campos públicos solicitados")
            g = g[[*permitidos, "geometry"]].copy()
            for c in permitidos:
                g[c] = g[c].map(lambda v: mascarar(v) if isinstance(v, str) else v)
        partes.append(g)
        ultimo = int(ids.max())
        recebidas += len(g)
        if len(feats) < passo:
            break
    g = (
        gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=srid)
        if partes
        else gpd.GeoDataFrame(columns=permitidos or [oid], geometry=[], crs=srid)
    )
    if len(g) != total:
        raise LeituraIncompleta(f"{url}: recebidas {len(g)} de {total} feições")
    depois = detalhes(s, url)
    if ultima_edicao(depois) != edicao:
        raise LeituraIncompleta("a edição ArcGIS mudou durante a leitura; o cursor não avança")
    if _contrato(depois) != _contrato(d):
        raise LeituraIncompleta("os metadados ArcGIS mudaram durante a leitura; o cursor não avança")
    if contar(s, url, where, bbox=bbox) != total:
        raise LeituraIncompleta("a contagem ArcGIS mudou durante a leitura; o cursor não avança")
    return g, edicao


@dataclass
class ResultadoArcGIS:
    fonte: str
    recorte: str
    acao: str  # atualizado | sem_mudanca | travado | falha
    linhas: int = 0
    edicao: int | None = None
    diferenca: Diferenca | None = None
    erro: str | None = None


def coletar_municipio(
    s: requests.Session,
    con: Connection,
    espelho: Espelho,
    fonte: str | Fonte,
    uf: str,
    cod: int,
    bbox: tuple[float, float, float, float],
    forcar: bool = False,
    hc=None,
) -> ResultadoArcGIS:
    """Retrato público no retângulo informado para um município; não recorta pela divisa administrativa.

    Guarda em <espelho>/<fonte>/<UF>/<cod>.parquet. O recorte e a allowlist entram na assinatura, evitando pular uma
    coleta quando o usuário muda a caixa, a fonte ou os campos. Falha/trava mantém cursor e assinatura aceitos.
    """
    from raiz.coleta.espelho import registrar_alertas
    from raiz.versoes import sha256_arquivo

    f = carregar().fonte(fonte) if isinstance(fonte, str) else fonte
    uf = uf.upper()
    if uf not in UFS or not re.fullmatch(r"\d{7}", str(cod)):
        raise ValueError("informe UF válida e código IBGE municipal de sete dígitos")
    if f.tipo != "arcgis" or not f.url or f.recorte != "municipio":
        raise ValueError("fonte precisa ser ArcGIS ativa com recorte municipal")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", f.id):
        raise ValueError("id da fonte ArcGIS inválido para o espelho")
    extra = f.model_extra or {}
    campos, chave = extra.get("campos_publicos"), extra.get("chave")
    if not campos or not chave or chave not in campos or colunas_pessoais(campos):
        raise ValueError("fonte ArcGIS sem allowlist pública e chave válidas")
    selecao = {"url": f.url, "bbox": _bbox(bbox), "campos": sorted(campos), "chave": chave}
    assinatura = hashlib.sha256(json.dumps(selecao, sort_keys=True).encode()).hexdigest()
    recorte, agora = f"{uf}/{cod}", dt.datetime.now(dt.UTC)
    e = estado(con, f.id, recorte)
    try:
        conhecido = None
        if not forcar and e is not None and e.assinatura == assinatura and espelho.caminho(f.id, uf, cod).exists():
            conhecido = int(e.cursor) if e.cursor else None
        g, ed = ler(s, f.url, ultima_edicao_conhecida=conhecido, bbox=bbox, campos=campos)
        if g is None:
            atualizar(con, f.id, recorte, sujo=False, tentativas=0, ultimo_erro=None, verificado_em=agora)
            return ResultadoArcGIS(f.id, recorte, "sem_mudanca", int(e.contagem or 0), ed)
        if g[chave].isna().any() or not g[chave].is_unique:
            raise LeituraIncompleta("a chave pública ArcGIS está vazia ou repetida")
        dif = espelho.gravar(f.id, uf, cod, g, chave, liberar=bool(e is not None and e.liberado))
        registrar_alertas(con, f.id, recorte, dif, hc)
        if dif.travado:
            msg = f"versão travada: conferir e liberar com raiz coleta liberar {f.id} {recorte}"
            atualizar(con, f.id, recorte, sujo=True, ultimo_erro=msg, verificado_em=agora)
            return ResultadoArcGIS(f.id, recorte, "travado", len(g), ed, dif, msg)
        atualizar(con, f.id, recorte, cursor=str(ed) if ed is not None else None, assinatura=assinatura,
                  hash_conteudo=sha256_arquivo(espelho.caminho(f.id, uf, cod)), contagem=len(g), sujo=False,
                  liberado=False, tentativas=0, ultimo_erro=None, verificado_em=agora, coletado_em=agora)  # fmt: skip
        evento(con, f.id, recorte, "mudaram" if dif.mudou else "sem_mudanca", len(g),
               {"lastEditDate": ed, "recorte": "retangulo", "bbox": list(bbox)})  # fmt: skip
        return ResultadoArcGIS(f.id, recorte, "atualizado", len(g), ed, dif)
    except Exception as ex:  # noqa: BLE001 - a próxima rodada repete; o cursor aceito não muda
        # Mensagens externas (servidor, parser, banco) podem conter valores pessoais. Só as mensagens controladas
        # de leitura incompleta são públicas; nas demais falhas registramos a classe, nunca o conteúdo recebido.
        detalhe = str(ex) if isinstance(ex, LeituraIncompleta) else "falha na coleta ArcGIS; repetir o recorte"
        msg = mascarar(f"{type(ex).__name__}: {detalhe}")[:500]
        atualizar(con, f.id, recorte, sujo=True, tentativas=(e.tentativas if e else 0) + 1,
                  ultimo_erro=msg, verificado_em=agora)  # fmt: skip
        evento(con, f.id, recorte, "falha", detalhe={"erro": msg})
        return ResultadoArcGIS(f.id, recorte, "falha", erro=msg)
