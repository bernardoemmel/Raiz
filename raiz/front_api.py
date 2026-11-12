"""Rotas que o front espera (front/README.md, "Depois (API)"; front/compartilhado/dados/fonte-api.ts), servidas do
PostGIS que a carga do motor já preenche. Mesmo contrato da amostra: as colunas saem com os nomes dos CSV do motor
(docs/colunas.md), não com os nomes em minúsculas do banco, para as telas não saberem de onde veio o dado.

    GET /municipios                         uma linha por município (resumo da UF vigente) mais uf
    GET /municipios/{cod_ibge}/imoveis      imoveis_ + filtros_ + complementos + mb_* (404 se ainda não rodou)
    GET /imoveis/{cod_imovel}               um imóvel
    GET /imoveis/{cod_imovel}/ficha         FichaJson (front/compartilhado/dados/ficha.ts)
    GET /imoveis/{cod_imovel}/certidoes     cartório (CNS) e matrícula das parcelas SIGEF
    GET /geo/{cod_ibge}/{camada}.geojson    municipio | imoveis | ti | uc | rios
    GET /geo/{cod_ibge}/base.pmtiles        mapa base, com Range

Privacidade: coluna com cara de dado pessoal não sai, e todo texto passa pela máscara de CPF/CNPJ (a mesma de
raiz/privacidade.py). A ficha segue as regras do funil do front (front/compartilhado/dados/funil.ts), que são as do
motor: apta = sem problema, área de carbono > 0 e até 5 ha desmatados depois de 2016.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import Engine, text

from raiz import contrato
from raiz.privacidade import colunas_pessoais, mascarar

# nome no banco (minúsculo) -> nome no CSV do motor
_ORIGINAL = {
    contrato.coluna_banco(k): k
    for d in (contrato.IMOVEIS, contrato.FILTROS, contrato.RESUMO, contrato.CERTIDOES)
    for k in d
}
_INTERNAS = {"rodada_id", "atributos", "bloco", "data_corte", "motor_versao", "regras_versao"}
SIMPLIFICAR_GRAUS = 0.00002  # a mesma tolerância de front/scripts/geo.py para os polígonos do CAR


# só texto com número de cara de documento passa pela máscara completa (mesma ideia do limpar() do front)
_TALVEZ_DOC = re.compile(r"\d{11}|\d{3}\.\d{3}|[0-9A-Z]{2}\.[0-9A-Z]{3}\.|[0-9A-Z]{12}\d{2}")


@lru_cache(maxsize=4096)
def _pessoal(coluna: str, permitir: tuple[str, ...]) -> bool:
    return bool(colunas_pessoais([coluna], permitir=permitir))


def _valor(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, str):
        return mascarar(v) if _TALVEZ_DOC.search(v) else v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _limpa(d: dict, permitir: tuple[str, ...] = ()) -> dict:
    return {k: _valor(v) for k, v in d.items() if not _pessoal(k, permitir)}


def _json(dado) -> Response:
    """JSON direto (sem o codificador genérico do FastAPI, lento em listas de 10 mil imóveis)."""
    return Response(json.dumps(dado, ensure_ascii=False, separators=(",", ":")), media_type="application/json")


def _linha_banco(m: dict, faltando: set[str] = frozenset()) -> dict:
    """Linha tipada do banco nos nomes do CSV, mais os atributos (colunas sem contrato, já com o nome original).
    Coluna do contrato que não veio no arquivo do motor não aparece (como no CSV)."""
    out = {}
    for k, v in m.items():
        if k in _INTERNAS:
            continue
        nome = _ORIGINAL.get(k, k)
        if nome in faltando:
            continue
        out[nome] = v
    out.update(m.get("atributos") or {})
    return out


def _faltando(con, rodadas: set[int]) -> dict[int, set[str]]:
    if not rodadas:
        return {}
    rs = con.execute(
        text("select id, colunas_faltando from funil.rodada where id = any(:ids)"), {"ids": list(rodadas)}
    ).all()
    return {r.id: {c.split(".", 1)[1] for c in r.colunas_faltando if "." in c} for r in rs}


def imoveis_do_municipio(engine: Engine, cod_ibge: int | None = None, cod_imovel: str | None = None) -> list[dict]:
    """Uma linha por imóvel, como o front monta da amostra: complementos primeiro, a linha principal ganha."""
    filtro = "cod_imovel = :ci" if cod_imovel else "cod_municipio_ibge = :c"
    with engine.connect() as con:
        principais = [
            dict(r._mapping)
            for r in con.execute(
                text(f"select * from funil.resultado_vigente where {filtro} order by cod_imovel"),
                {"c": cod_ibge, "ci": cod_imovel},
            )
        ]
        if not principais:
            return []
        chaves = [(p["rodada_id"], p["cod_imovel"]) for p in principais]
        rodadas = {r for r, _ in chaves}
        cods = [c for _, c in chaves]
        faltando = _faltando(con, rodadas)
        comp: dict[str, dict] = defaultdict(dict)
        par = {"r": list(rodadas), "cs": cods}
        for r in con.execute(
            text("select * from funil.filtro_imovel where rodada_id = any(:r) and cod_imovel = any(:cs)"), par
        ):
            comp[r.cod_imovel].update(_linha_banco(dict(r._mapping)))
        for r in con.execute(
            text("""select cod_imovel, atributos from funil.complemento_imovel
                    where rodada_id = any(:r) and cod_imovel = any(:cs) order by tipo"""),
            par,
        ):
            comp[r.cod_imovel].update(r.atributos or {})
        for r in con.execute(
            text("""select cod_imovel, indicador, ano, valor_num, valor_texto from funil.mapbiomas_imovel
                    where rodada_id = any(:r) and cod_imovel = any(:cs)"""),
            par,
        ):
            v = r.valor_num if r.valor_texto is None else r.valor_texto
            comp[r.cod_imovel][contrato.coluna_mb(r.indicador, r.ano)] = v
    out = []
    for p in principais:
        linha = dict(comp.get(p["cod_imovel"], {}))
        linha.update(_linha_banco(p, faltando.get(p["rodada_id"], set())))
        out.append(_limpa(linha))
    return out


# --- regras do funil do front (front/compartilhado/dados/funil.ts), para a ficha ------------------------------------


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    if v is None or isinstance(v, bool):
        return None if v is None else float(v)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _n0(linha: dict, c: str, padrao: float = 0.0) -> float:
    x = _num(linha, c)
    return padrao if x is None else x


def _bool(linha: dict, c: str) -> bool | None:
    v = linha.get(c)
    if isinstance(v, bool) or v is None:
        return v
    s = str(v).strip().lower()
    if s in {"true", "1", "sim", "s", "yes"}:
        return True
    if s in {"false", "0", "não", "nao", "n", "no"}:
        return False
    return None


def ler_imovel(linha: dict) -> dict:
    """ha, carbono_ha e apta, com as mesmas regras de lerImovel do front."""
    ha = _n0(linha, "ha", _n0(linha, "area"))
    carbono_ha = _n0(linha, "carbono_ha") if "carbono_ha" in linha else _n0(linha, "alem_RL_ha")
    problema = _bool(linha, "problema")
    if problema is None:
        problema = any(_n0(linha, c) > 1 for c in ("embargo_ha", "ti_ha", "desm_pos2020_ha", "alerta_pos2020_ha"))
    desm16 = _num(linha, "desm_pos2016_ha")
    apta = (not problema) and carbono_ha > 0 and (desm16 or 0) <= 5
    return {"ha": ha, "carbono_ha": carbono_ha, "apta": apta}


def mediana(xs: list[float]) -> float:
    if not xs:
        return 0
    s = sorted(xs)
    m = len(s) >> 1
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _arredonda_js(x: float) -> int:
    return math.floor(x + 0.5)  # Math.round do JavaScript (meio sobe), não o arredondamento bancário do Python


def polyline(pontos: list[tuple[float, float]], casas: int = 6) -> str:
    """Mesmo algoritmo de front/compartilhado/polyline.ts (pares [lon, lat], 6 casas)."""
    fator = 10**casas
    saida, lat0, lon0 = [], 0, 0

    def parte(v: int) -> str:
        n = ~(v << 1) if v < 0 else v << 1
        s = []
        while n >= 0x20:
            s.append(chr((0x20 | (n & 0x1F)) + 63))
            n >>= 5
        s.append(chr(n + 63))
        return "".join(s)

    for lon, lat in pontos:
        la, lo = _arredonda_js(lat * fator), _arredonda_js(lon * fator)
        saida.append(parte(la - lat0) + parte(lo - lon0))
        lat0, lon0 = la, lo
    return "".join(saida)


def _aneis_externos(geojson: dict | None) -> list[list[tuple[float, float]]]:
    if not geojson:
        return []
    if geojson["type"] == "Polygon":
        return [geojson["coordinates"][0]]
    if geojson["type"] == "MultiPolygon":
        return [p[0] for p in geojson["coordinates"]]
    return []


_COLUNAS_CONTEXTO = (
    "rodada_id, ha, area, carbono_ha, alem_rl_ha, problema, embargo_ha, ti_ha, desm_pos2020_ha, "
    "alerta_pos2020_ha, desm_pos2016_ha"
)


def linhas_para_contexto(engine: Engine, cod_ibge: int) -> list[dict]:
    """Só as colunas que o contexto da ficha usa, de todos os imóveis do município (rápido em São Félix)."""
    with engine.connect() as con:
        rs = [
            dict(r._mapping)
            for r in con.execute(
                text(f"select {_COLUNAS_CONTEXTO} from funil.resultado_vigente where cod_municipio_ibge = :c"),
                {"c": cod_ibge},
            )
        ]
        faltando = _faltando(con, {r["rodada_id"] for r in rs})
    return [_linha_banco(r, faltando.get(r["rodada_id"], set())) for r in rs]


def montar_ficha(alvo: dict, todos: list[dict], geometria: dict | None) -> dict:
    """FichaJson: a linha, o contexto do município e o perímetro em polyline (front/compartilhado/dados/ficha.ts)."""
    lidos = [ler_imovel(i) for i in todos]
    eu = ler_imovel(alvo)
    meu = eu["carbono_ha"] if eu["apta"] else 0
    carbonos = [x["carbono_ha"] if x["apta"] else 0 for x in lidos]
    aneis = _aneis_externos(geometria)
    xs = [p[0] for a in aneis for p in a]
    ys = [p[1] for a in aneis for p in a]
    n = len(todos)
    return {
        "versao": 1,
        "imovel": alvo,
        "contexto": {
            "cod_ibge": str(alvo.get("cod_municipio_ibge") or ""),
            "municipio": alvo.get("municipio") or "",
            "uf": alvo.get("uf") or "",
            "n_imoveis": n,
            "posicao_carbono": sum(c < meu for c in carbonos) / n if n else 0,
            "mediana_carbono_ha_aptas": mediana([x["carbono_ha"] for x in lidos if x["apta"]]),
            "mediana_ha": mediana([x["ha"] for x in lidos]),
        },
        "perimetro": [polyline(a) for a in aneis] if aneis else None,
        "caixa": [min(xs), min(ys), max(xs), max(ys)] if xs else None,
    }


# --- rotas --------------------------------------------------------------------------------------------------------


def roteador(engine_de) -> APIRouter:
    """engine_de(request) devolve o Engine (o da aplicação)."""
    r = APIRouter()

    @r.get("/municipios")
    def municipios(request: Request) -> list[dict]:
        eng = engine_de(request)
        with eng.connect() as con:
            linhas = con.execute(
                text("""
                select ro.uf, m.* from funil.resumo_municipio m
                join funil.rodada ro on ro.id = m.rodada_id
                where ro.id in (select distinct on (uf) id from funil.rodada where tipo = 'resumo_uf'
                                order by uf, data_corte desc, id desc)
                order by ro.uf, m.cod_ibge""")
            ).all()
        out = []
        for x in linhas:
            m = dict(x._mapping)
            d = _linha_banco(m)
            d["uf"] = m["uf"]
            out.append(_limpa(d))
        return out

    @r.get("/municipios/{cod_ibge}/imoveis")
    def imoveis(cod_ibge: int, request: Request) -> Response:
        lista = imoveis_do_municipio(engine_de(request), cod_ibge=cod_ibge)
        if not lista:
            raise HTTPException(404, "município ainda sem imóveis carregados")
        return _json(lista)

    @r.get("/imoveis/{cod_imovel}")
    def imovel(cod_imovel: str, request: Request) -> dict:
        lista = imoveis_do_municipio(engine_de(request), cod_imovel=cod_imovel)
        if not lista:
            raise HTTPException(404, "imóvel não encontrado")
        return lista[0]

    @r.get("/imoveis/{cod_imovel}/ficha")
    def ficha(cod_imovel: str, request: Request) -> Response:
        eng = engine_de(request)
        alvo = imoveis_do_municipio(eng, cod_imovel=cod_imovel)
        if not alvo:
            raise HTTPException(404, "imóvel não encontrado")
        cod_ibge = alvo[0].get("cod_municipio_ibge")
        todos = linhas_para_contexto(eng, int(cod_ibge)) if cod_ibge else alvo
        with eng.connect() as con:
            g = con.execute(
                text("""select ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :t), 6) from funil.imovel
                        where cod_imovel = :c and geom is not null"""),
                {"c": cod_imovel, "t": SIMPLIFICAR_GRAUS},
            ).scalar()
        return _json(montar_ficha(alvo[0], todos, json.loads(g) if g else None))

    @r.get("/imoveis/{cod_imovel}/certidoes")
    def certidoes(cod_imovel: str, request: Request) -> list[dict]:
        with engine_de(request).connect() as con:
            linhas = con.execute(
                text("""select c.* from titulo.certidao_alvo c
                        where c.cod_imovel = :c and c.rodada_id = (
                            select rodada_id from funil.resultado_vigente where cod_imovel = :c)
                        order by c.registro_cns, c.registro_matricula"""),
                {"c": cod_imovel},
            ).all()
        return [_limpa(_linha_banco(dict(x._mapping))) for x in linhas]

    @r.get("/geo/{cod_ibge}/base.pmtiles")
    def base(cod_ibge: int) -> Response:
        from raiz.geo import arquivo_base

        f = arquivo_base(cod_ibge)
        if f is None:
            raise HTTPException(404, "mapa base ainda não gerado (front/scripts/geo.py)")
        # FileResponse do Starlette responde a Range (206) e manda Accept-Ranges, como o PMTiles precisa
        return FileResponse(f, media_type="application/vnd.pmtiles")

    @r.get("/geo/{cod_ibge}/{camada}.geojson")
    def geo(cod_ibge: int, camada: str, request: Request) -> Response:
        eng = engine_de(request)
        with eng.connect() as con:
            if camada == "imoveis":
                fc = con.execute(
                    text("""
                    select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                        json_build_object(
                            'type', 'Feature',
                            'properties', json_build_object('cod_imovel', i.cod_imovel, 'area', v.area,
                                                            'm_fiscal', v.m_fiscal, 'status_imovel', v.status_imovel),
                            'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(i.geom, :t), 6)::json)
                        order by i.cod_imovel), '[]'::json))
                    from funil.imovel i join funil.resultado_vigente v on v.cod_imovel = i.cod_imovel
                    where v.cod_municipio_ibge = :c and i.geom is not null"""),
                    {"c": cod_ibge, "t": SIMPLIFICAR_GRAUS},
                ).scalar()
            elif camada in ("municipio", "ti", "uc", "rios"):
                fc = con.execute(
                    text("""
                    select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                        json_build_object('type', 'Feature', 'properties', propriedades,
                                          'geometry', ST_AsGeoJSON(geom, 6)::json) order by id), '[]'::json))
                    from geo.camada where cod_ibge = :c and camada = :k"""),
                    {"c": cod_ibge, "k": camada},
                ).scalar()
            else:
                raise HTTPException(404, f"camada desconhecida: {camada}")
        if not fc or not fc["features"]:
            raise HTTPException(404, f"sem {camada} para {cod_ibge}")
        lugar = ("nome",) if camada != "imoveis" else ()  # nome de TI, UC e município é nome de lugar
        for f in fc["features"]:
            f["properties"] = _limpa(f["properties"] or {}, lugar)
        return Response(json.dumps(fc, separators=(",", ":")), media_type="application/geo+json")

    return r
