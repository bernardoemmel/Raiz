"""Evidência territorial versionada, cruzada com o CAR e mantida no armazenamento privado.

Confirma sobreposição geométrica, não exclusividade de direitos de carbono. O catálogo
sem polígono e programas jurisdicionais nunca constituem prova de compromisso do CAR.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import shapely
from pyproj import Transformer
from shapely.ops import transform
from sqlalchemy import text

FONTES = {
    "berkeley",
    "verra",
    "sfb_concessoes",
    "art_jurisdicional",
    "redd_estadual",
    "ideflor_concessoes",
    "limites_pesquisa",
}
REGISTROS = {"REDD_ESTADUAL", "VCS", "ACR", "CAR", "ART", "GS", "ISO", "SFB", "IDEFLOR", "BIOCARBON", "ECOREGISTRY"}
TIPOS = {"projeto_carbono", "concessao_florestal", "concessao_restauracao", "programa_jurisdicional"}
SITUACOES = {"ativo", "em_validacao", "retirado", "inativo", "desconhecido"}
CERTEZAS = {"poligono_oficial", "poligono_secundario", "catalogo_sem_geometria", "contexto_jurisdicional"}
AVISO = (
    "Ausência de sobreposição nas fontes consultadas não comprova terra livre. "
    "Polígonos confirmam interseção com o registro observado, não exclusividade de carbono. "
    "Concessões florestais exigem conferir o contrato; programa estadual de REDD+ não compromete cada CAR."
)
_AREA = Transformer.from_crs(4326, 5880, always_xy=True).transform


@lru_cache(maxsize=1)
def catalogo_fontes() -> dict:
    return json.loads(Path(__file__).with_name("terra_comprometida_fontes.json").read_text())


def _data(v):
    if isinstance(v, dt.datetime):
        v = v.date()
    if isinstance(v, dt.date):
        return v.isoformat()
    try:
        return dt.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        return None


def _id(v):
    from raiz.privacidade import documento_em_identificador

    return (
        v
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", v) and not documento_em_identificador(v)
        else None
    )


def _url(v):
    if not isinstance(v, str):
        return None
    try:
        p = urlsplit(v)
    except ValueError:
        return None
    hosts = (
        "verra.org",
        "platts.com",
        "berkeley.edu",
        "florestal.gov.br",
        "gov.br",
        "artredd.org",
        "art-redd.org",
        "apx.com",
        "zenodo.org",
        "doi.org",
        "goldstandard.org",
        "climateactionreserve.org",
        "acrcarbon.org",
        "isometric.com",
    )
    if (
        p.scheme != "https"
        or p.username
        or not any(p.hostname == h or (p.hostname or "").endswith("." + h) for h in hosts)
    ):
        return None
    from raiz.qualidade_calendario import validar_url_publica

    try:
        return validar_url_publica(urlunsplit((p.scheme, p.netloc, p.path, "", "")), [p.hostname])
    except ValueError:
        return None


def _numero(v):
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
        return n if math.isfinite(n) and n >= 0 else None
    except (TypeError, ValueError):
        return None


def medida(v, fonte="Raíz, união espacial das evidências territoriais", data=None, corte=None):
    return {
        "valor": _numero(v),
        "unidade": "ha",
        "fonte": fonte,
        "data_referencia": _data(data),
        "data_corte": _data(corte),
        "estimado": True,
    }


def normalizar(registro: dict) -> dict:
    """Allowlist desde a entrada: descarta nomes, proponentes, textos e quaisquer extras."""
    fonte, oid = registro.get("fonte_id"), _id(registro.get("objeto_id"))
    if fonte not in FONTES or not oid or registro.get("tipo") not in TIPOS or registro.get("registro") not in REGISTROS:
        raise ValueError("Evidência territorial sem identificadores reconhecidos")
    out = {
        "fonte_id": fonte,
        "objeto_id": oid,
        "registro": registro["registro"],
        "tipo": registro["tipo"],
        "situacao": registro.get("situacao") if registro.get("situacao") in SITUACOES else "desconhecido",
        "certeza": registro.get("certeza") if registro.get("certeza") in CERTEZAS else "catalogo_sem_geometria",
        "uf": registro.get("uf") if registro.get("uf") in _UFS else None,
        "fonte_url": _url(registro.get("fonte_url")),
        **{k: _data(registro.get(k)) for k in ("data_referencia", "observado_em", "inicio", "fim")},
        "evidencia_status_url": _url(registro.get("evidencia_status_url")),
    }
    geom = registro.get("geometry")
    if geom is not None:
        if not isinstance(geom, shapely.Geometry):
            geom = shapely.from_geojson(json.dumps(geom))
        geom = shapely.make_valid(geom)
        if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty:
            raise ValueError("Evidência requer polígono válido, nunca ponto ou centroide")
        if not (-180 <= geom.bounds[0] <= geom.bounds[2] <= 180 and -90 <= geom.bounds[1] <= geom.bounds[3] <= 90):
            raise ValueError("Polígono deve usar coordenadas EPSG:4326")
    if out["tipo"] == "programa_jurisdicional":
        geom, out["certeza"] = None, "contexto_jurisdicional"
    if geom is None and out["certeza"] in ("poligono_oficial", "poligono_secundario"):
        out["certeza"] = "catalogo_sem_geometria"
    if out["certeza"] == "poligono_oficial" and (
        out["fonte_id"] not in ("verra", "sfb_concessoes", "ideflor_concessoes")
        or not out["fonte_url"]
        or not out["observado_em"]
    ):
        out["certeza"] = "poligono_secundario"
    out["geometry"] = geom
    return out


_UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())


def cobertura_segura(c: dict) -> dict:
    fonte = c.get("fonte_id")
    if fonte not in FONTES:
        raise ValueError("Fonte territorial desconhecida")
    bbox = c.get("bbox")
    if not (
        isinstance(bbox, (list, tuple))
        and len(bbox) == 4
        and all(isinstance(n, (int, float)) and math.isfinite(n) for n in bbox)
    ):
        bbox = None
    elif not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90):
        bbox = None
    # Licença vem do catálogo controlado, nunca de texto livre de um registro.
    fonte_meta = catalogo_fontes()["fontes"].get(fonte, {})
    return {
        "fonte_id": fonte,
        "estado": c.get("estado") if c.get("estado") in ("consultado", "parcial", "indisponivel") else "parcial",
        "escopo": c.get("escopo") if c.get("escopo") in ("brasil", "uf", "bbox", "projeto") else "projeto",
        "recorte": _id(c.get("recorte")) or hashlib.sha256(json.dumps(bbox).encode()).hexdigest()[:16],
        "bbox": list(bbox) if bbox else None,
        "url": _url(c.get("url")),
        "licenca": fonte_meta.get("licenca", "A conferir"),
        "data_referencia": _data(c.get("data_referencia")),
        "consultado_em": _data(c.get("consultado_em")),
    }


def vazio() -> dict:
    return {
        "versao": 1,
        "situacao": "nao_verificado",
        "area_confirmada": medida(None),
        "area_indicio": medida(None),
        "evidencias": [],
        "contexto_jurisdicional": [],
        "cobertura": [],
        "aviso": AVISO,
    }


def fechar_dto(valor) -> dict:
    """Revalida o JSON persistido na fronteira da ficha; nunca repassa objetos aninhados abertos."""
    if not isinstance(valor, dict):
        return vazio()
    out = vazio()
    status = valor.get("situacao")
    if status in ("sobreposicao_confirmada", "indicio", "sem_sobreposicao_identificada", "nao_verificado"):
        out["situacao"] = status
    for campo in ("area_confirmada", "area_indicio"):
        m = valor.get(campo)
        if isinstance(m, dict):
            out[campo] = medida(m.get("valor"), data=m.get("data_referencia"), corte=m.get("data_corte"))
    for campo in ("evidencias", "contexto_jurisdicional"):
        for item in valor.get(campo, []) if isinstance(valor.get(campo), list) else []:
            if not isinstance(item, dict):
                continue
            try:
                reg = normalizar({**item, "geometry": None})
            except ValueError:
                continue
            # Ausência de geometria no DTO não rebaixa a certeza do resultado calculado.
            reg["certeza"] = item.get("certeza") if item.get("certeza") in CERTEZAS else "catalogo_sem_geometria"
            reg.pop("geometry")
            reg.pop("uf")
            reg.pop("evidencia_status_url")
            m = item.get("area") if isinstance(item.get("area"), dict) else {}
            reg["area"] = medida(
                m.get("valor"), fonte=reg["fonte_id"], data=reg["data_referencia"], corte=reg["observado_em"]
            )
            out[campo].append(reg)
    for c in valor.get("cobertura", []) if isinstance(valor.get("cobertura"), list) else []:
        try:
            safe = cobertura_segura(c)
        except (ValueError, AttributeError):
            continue
        out["cobertura"].append(
            {
                k: safe[k]
                for k in (
                    "fonte_id",
                    "estado",
                    "escopo",
                    "recorte",
                    "url",
                    "licenca",
                    "data_referencia",
                    "consultado_em",
                )
            }
        )
    return out


def cruzar(
    geometria,
    uf: str,
    registros: list[dict],
    coberturas: list[dict],
    *,
    em: str | None = None,
    _normalizados: bool = False,
) -> dict:
    """Um CAR, geometrias WGS84. Áreas por união em EPSG5880, sem duplicar registros."""
    hoje = _data(em) or dt.date.today().isoformat()
    cob = [cobertura_segura(c) for c in coberturas]
    cob = [c for c in cob if not c["consultado_em"] or c["consultado_em"] <= hoje]
    out = vazio()
    out["cobertura"] = cob
    corte = max((c["consultado_em"] for c in cob if c["consultado_em"]), default=None)
    confirmadas, indicios = [], []
    verificou = False
    if geometria is not None and not geometria.is_empty:
        geometria = shapely.make_valid(geometria)
        verificou = any(
            c["estado"] in ("consultado", "parcial")
            and c["fonte_id"] != "berkeley"
            and c["escopo"] == "bbox"
            and c["bbox"] is not None
            and shapely.box(*c["bbox"]).covers(geometria)
            for c in cob
        )
    # A observação mais recente de cada fonte/objeto vence, inclusive retirada posterior.
    atuais = {}
    for raw in registros:
        r = dict(raw) if _normalizados else normalizar(raw)
        if r["observado_em"] and r["observado_em"] > hoje:
            continue
        chave = (r["fonte_id"], r["objeto_id"])
        if chave not in atuais or (r["observado_em"] or "") >= (atuais[chave]["observado_em"] or ""):
            atuais[chave] = r
    for r in atuais.values():
        g = r.pop("geometry")
        if r["tipo"] == "programa_jurisdicional" and r["uf"] == uf:
            out["contexto_jurisdicional"].append(
                {**r, "area": medida(None, r["fonte_id"], r["data_referencia"], r["observado_em"])}
            )
            continue
        if g is None or geometria is None or geometria.is_empty or not g.intersects(geometria):
            continue
        inter = shapely.intersection(geometria, g)
        area = transform(_AREA, inter).area / 10000
        if area <= 0:
            continue
        ativa = (
            r["situacao"] == "ativo" and (not r["inicio"] or r["inicio"] <= hoje) and (not r["fim"] or hoje < r["fim"])
        )
        if ativa and r["certeza"] == "poligono_oficial":
            confirmadas.append(inter)
        elif r["situacao"] not in ("retirado", "inativo") and (not r["fim"] or hoje < r["fim"]):
            indicios.append(inter)
        out["evidencias"].append({**r, "area": medida(area, r["fonte_id"], r["data_referencia"], r["observado_em"])})

    def area_unida(gs):
        return transform(_AREA, shapely.union_all(gs)).area / 10000 if gs else 0.0

    c_area = area_unida(confirmadas)
    # Faixas disjuntas: uma área confirmada não volta a ser contada como indício.
    indicio_exclusivo = shapely.difference(shapely.union_all(indicios), shapely.union_all(confirmadas))
    i_area = transform(_AREA, indicio_exclusivo).area / 10000

    out["area_confirmada"] = medida(c_area if verificou or out["evidencias"] else None, corte=corte)
    out["area_indicio"] = medida(i_area if verificou or out["evidencias"] else None, corte=corte)
    out["situacao"] = (
        "sobreposicao_confirmada"
        if c_area
        else "indicio"
        if i_area
        else "sem_sobreposicao_identificada"
        if verificou
        else "nao_verificado"
    )
    out["evidencias"].sort(key=lambda x: (x["fonte_id"], x["objeto_id"]))
    out["contexto_jurisdicional"].sort(key=lambda x: (x["fonte_id"], x["objeto_id"]))
    return fechar_dto(out)


def ingerir(con, coleta: dict) -> int:
    """Persiste snapshot imutável allowlist. O orquestrador registra versões antes/depois de atualizar CARs."""
    c = cobertura_segura(coleta["cobertura"])
    if c["consultado_em"] is None:
        raise ValueError("Consulta territorial precisa de data observada")
    registros = [normalizar(r) for r in coleta["registros"]]
    if len({r["objeto_id"] for r in registros}) != len(registros):
        raise ValueError("Objeto territorial duplicado na mesma observação")
    serial = []
    for r in registros:
        if r["fonte_id"] != c["fonte_id"]:
            raise ValueError("Fonte do objeto difere da cobertura")
        d = {k: v for k, v in r.items() if k != "geometry"}
        d["wkb"] = shapely.to_wkb(shapely.normalize(r["geometry"]), hex=True) if r["geometry"] is not None else None
        serial.append(d)
    assinatura = hashlib.sha256(
        json.dumps([c, sorted(serial, key=lambda r: r["objeto_id"])], sort_keys=True).encode()
    ).hexdigest()
    fid = con.execute(
        text("""INSERT INTO coleta.compromisso_fonte(fonte_id,assinatura,cobertura,consultado_em)
        VALUES(:f,:h,CAST(:c AS jsonb),:d) ON CONFLICT(fonte_id,assinatura)
        DO UPDATE SET assinatura=excluded.assinatura RETURNING id"""),
        {"f": c["fonte_id"], "h": assinatura, "c": json.dumps(c), "d": c["consultado_em"]},
    ).scalar_one()
    for r in serial:
        wkb = r.pop("wkb")
        con.execute(
            text("""INSERT INTO coleta.compromisso_objeto(fonte_versao,objeto_id,dados,geom)
            VALUES(:v,:o,CAST(:d AS jsonb),ST_Multi(ST_GeomFromWKB(decode(:g,'hex'),4326)))
            ON CONFLICT(fonte_versao,objeto_id) DO NOTHING"""),
            {"v": fid, "o": r["objeto_id"], "d": json.dumps(r), "g": wkb},
        )
    return fid


def atualizar(con, codigos: list[str]) -> int:
    """Batch privado. Quatro leituras SQL por lote, sem download/requisição por CAR."""
    if not codigos:
        return 0
    fontes = (
        con.execute(
            text("""SELECT DISTINCT ON (fonte_id,cobertura->>'recorte') id,cobertura
        FROM coleta.compromisso_fonte ORDER BY fonte_id,cobertura->>'recorte',consultado_em DESC,id DESC""")
        )
        .mappings()
        .all()
    )
    imoveis = (
        con.execute(
            text("""SELECT cod_imovel,uf,ST_AsBinary(ST_Transform(geom,4326)) AS wkb
        FROM funil.imovel WHERE cod_imovel=ANY(:cods)"""),
            {"cods": codigos},
        )
        .mappings()
        .all()
    )
    rows = (
        con.execute(
            text("""WITH atuais AS (
            SELECT DISTINCT ON (f.fonte_id,o.objeto_id) o.dados,o.geom
            FROM coleta.compromisso_objeto o JOIN coleta.compromisso_fonte f ON f.id=o.fonte_versao
            ORDER BY f.fonte_id,o.objeto_id,f.consultado_em DESC,f.id DESC)
        SELECT o.dados,ST_AsBinary(o.geom) AS wkb FROM atuais o
        WHERE o.geom IS NULL OR EXISTS (
            SELECT 1 FROM funil.imovel i WHERE i.cod_imovel=ANY(:cods)
            AND ST_Intersects(o.geom,ST_Transform(i.geom,4326)))"""),
            {"cods": codigos},
        )
        .mappings()
        .all()
    )
    registros = [
        normalizar({**r["dados"], "geometry": shapely.from_wkb(bytes(r["wkb"])) if r["wkb"] else None}) for r in rows
    ]
    contextos = {}
    for p in con.execute(
        text("""SELECT i.cod_imovel,p.id,p.uf,p.inicio,p.fim,p.fonte,
        p.evidencia->>'data' AS data_referencia
        FROM funil.imovel i JOIN geo.redd_programa p ON i.uf=p.uf AND ST_Intersects(i.geom,p.geom)
        WHERE i.cod_imovel=ANY(:cods)"""),
        {"cods": codigos},
    ).mappings():
        contextos.setdefault(p["cod_imovel"], []).append(
            normalizar(
                {
                    "fonte_id": "redd_estadual",
                    "objeto_id": p["id"],
                    "registro": "REDD_ESTADUAL",
                    "tipo": "programa_jurisdicional",
                    "situacao": "desconhecido",
                    "certeza": "contexto_jurisdicional",
                    "uf": p["uf"],
                    "geometry": None,
                    "fonte_url": p["fonte"],
                    "data_referencia": p["data_referencia"],
                    "inicio": p["inicio"],
                    "fim": p["fim"],
                    "observado_em": None,
                }
            )
        )
    resultados = []
    for im in imoveis:
        geom = shapely.from_wkb(bytes(im["wkb"])) if im["wkb"] else None
        dto = cruzar(
            geom,
            im["uf"],
            registros + contextos.get(im["cod_imovel"], []),
            [f["cobertura"] for f in fontes],
            _normalizados=True,
        )
        resultados.append({"cod_imovel": im["cod_imovel"], "dados": dto})
    if resultados:
        con.execute(
            text("""INSERT INTO funil.terra_comprometida(cod_imovel,dados)
            SELECT cod_imovel,dados FROM jsonb_to_recordset(CAST(:resultados AS jsonb))
            AS x(cod_imovel text,dados jsonb)
            ON CONFLICT(cod_imovel) DO UPDATE SET dados=excluded.dados,atualizado_em=now()
            WHERE funil.terra_comprometida.dados IS DISTINCT FROM excluded.dados"""),
            {"resultados": json.dumps(resultados)},
        )
    return len(imoveis)


def por_codigos(con, codigos: list[str]) -> dict[str, dict]:
    if not codigos:
        return {}
    rows = con.execute(
        text("SELECT cod_imovel,dados FROM funil.terra_comprometida WHERE cod_imovel=ANY(:cods)"), {"cods": codigos}
    )
    return {r.cod_imovel: fechar_dto(r.dados) for r in rows}
