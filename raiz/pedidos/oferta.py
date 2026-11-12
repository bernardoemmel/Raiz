"""A oferta: uma linha por fazenda com o que o pedido de lote usa, lida das colunas pelo nome (docs/colunas.md) e
tolerante a colunas novas. Sai do banco (negocio.oferta, refeita a cada carga de município) ou, nos testes e em
máquina sem banco, direto das pastas do motor.

Nunca descarta fazenda por tamanho: pequena (até 4 módulos fiscais) entra e é agrupada com as vizinhas."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

# caminho da terra do produto (raiz/terra.py) -> nome do contrato com o front
CAMINHO_FRONT = {
    "publica_concessao": "concessao",
    "assentamento": "assentamento",
    "posse_em_titulacao": "posse_em_titulacao",
    "privada_matricula": "matricula_a_conferir",  # vira matricula_conferida com o título conferido no cartório
}
NAO_ORIGINA = ("publica_sem_destinacao", "terra_indigena_ou_tradicional")
COLUNAS = (
    "cod_imovel", "cod_ibge", "municipio", "uf", "bioma", "lon", "lat", "local_aproximado", "ha", "pequena",
    "area_ha", "modo", "metodos", "credito_p10", "credito_p50", "credito_p90", "credito_ano", "flag_t_ano",
    "custo_credito_usd", "preco_equilibrio_usd", "tir_p10", "tir_p50", "tir_p90", "tir_projeto", "vpl_rs",
    "pico_rs", "multa_rs", "marcos", "marcos_todos", "caminho_terra", "caminho", "risco_terra", "grupo_id",
    "mitigacao", "embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono", "bloqueio", "problema",
    "elegivel", "restauracao_versao", "cambio", "regeneracao_ha", "semeadura_ha", "plantio_ha", "vazamento_motivo",
    "vazamento_mitigacao_imovel", "regularizacao_classe", "salvaguardas", "elegivel_sem_salvaguardas",
)  # fmt: skip


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _verdade(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


@lru_cache
def sedes() -> dict[int, tuple[float, float, str]]:
    """Ponto da sede de cada município (lon, lat, nome), para quando a fazenda ainda não tem o contorno."""
    f = Path(__file__).resolve().parents[1] / "executor" / "municipios.csv"
    if not f.exists():
        return {}
    t = pd.read_csv(f)
    cols = {c.lower(): c for c in t.columns}
    cod, lon, lat = cols.get("codigo_ibge") or cols.get("cod_ibge"), cols.get("longitude"), cols.get("latitude")
    nome = cols.get("nome")
    if not (cod and lon and lat):
        return {}
    return {int(r[cod]): (float(r[lon]), float(r[lat]), str(r[nome]) if nome else "") for _, r in t.iterrows()}


def de_linha(linha: dict, lon: float | None = None, lat: float | None = None) -> dict | None:
    """A linha da oferta de uma fazenda (None se o valor para quem restaura ainda não foi calculado)."""
    modo = linha.get("modo_restauracao")
    if not isinstance(modo, str) or not modo:
        return None
    cod_ibge = _num(linha.get("cod_municipio_ibge"))
    cod_ibge = int(cod_ibge) if cod_ibge is not None else None
    aproximado = False
    if lon is None or lat is None:
        s = sedes().get(cod_ibge or -1)
        lon, lat, aproximado = (s[0], s[1], True) if s else (None, None, True)
    ha = _num(linha.get("ha")) or _num(linha.get("area")) or 0.0
    mf = _num(linha.get("m_fiscal"))
    porte = linha.get("porte")
    pequena = porte == "pequeno" if isinstance(porte, str) else (mf is not None and mf <= 4)
    area = _num(linha.get("restauracao_area_ha")) or 0.0
    c50 = _num(linha.get("credito_liquido_tco2_ha_contrato_p50"))
    if c50 is not None:
        cr = [(_num(linha.get(f"credito_liquido_tco2_ha_contrato_{q}")) or c50) * area for q in ("p10", "p50", "p90")]
    else:  # arquivo antes da rodada 11: crédito igual todo ano no prazo de 25 anos
        anual = [_num(linha.get(k)) or 0.0 for k in ("credito_liquido_tco2_ha_ano_p10", "credito_liquido_tco2_ha_ano",
                                                       "credito_liquido_tco2_ha_ano_p90")]  # fmt: skip
        cr = [a * 25 * area for a in anual]
    marcos = {int(k.split("_")[1]): _num(v) / 100 for k, v in linha.items()
              if k.startswith("marco_") and k.endswith("_chance_pct") and _num(v) is not None}  # fmt: skip
    caminho_terra = linha.get("caminho_terra") if isinstance(linha.get("caminho_terra"), str) else None
    caminho = CAMINHO_FRONT.get(caminho_terra or "")
    if caminho == "matricula_a_conferir" and (
        str(linha.get("etapa_funil") or "") == "titulo_conferido" or _verdade(linha.get("matricula_conferida"))
    ):
        caminho = "matricula_conferida"
    metodos = [m for m in ("regeneracao_assistida", "semeadura_direta", "plantio_total")
               if (_num(linha.get(f"restauracao_{m}_ha")) or 0) > 0.05] or [modo]  # fmt: skip
    if (_num(linha.get("flag_cacau_ha")) or 0) > 0:
        metodos.append("agrofloresta")
    if (_num(linha.get("flag_silvipastoril_ha")) or 0) > 0:
        metodos.append("silvipastoril")
    bloqueio = str(linha.get("filtro_territorial") or "").lower() == "bloqueio"
    from raiz.salvaguardas import avaliar

    elegivel_sem_salvaguardas = area > 0 and caminho is not None and caminho_terra not in NAO_ORIGINA and not bloqueio
    salvaguardas = avaliar(linha, linha.get("verificacao"))
    bloqueio = bloqueio or not salvaguardas["pode_originar"]
    elegivel = area > 0 and caminho is not None and caminho_terra not in NAO_ORIGINA and not bloqueio
    cambio = _num(linha.get("restauracao_cambio")) or 5.40
    return {
        "cod_imovel": str(linha["cod_imovel"]),
        "cod_ibge": cod_ibge,
        "municipio": linha.get("municipio")
        if isinstance(linha.get("municipio"), str)
        else (sedes().get(cod_ibge or -1, (0, 0, ""))[2]),
        "uf": str(linha.get("uf") or "").upper() or None,
        "bioma": linha.get("bioma") if isinstance(linha.get("bioma"), str) else None,
        "lon": lon,
        "lat": lat,
        "local_aproximado": aproximado,
        "ha": ha,
        "pequena": bool(pequena),
        "area_ha": area,
        "modo": modo,
        "metodos": metodos,
        "credito_p10": cr[0],
        "credito_p50": cr[1],
        "credito_p90": cr[2],
        "credito_ano": _num(linha.get("credito_liquido_tco2_ano")) or 0.0,
        "flag_t_ano": _num(linha.get("flag_tco2_ano")) or 0.0,
        "custo_credito_usd": _num(linha.get("custo_credito_usd")),
        "preco_equilibrio_usd": _num(linha.get("preco_equilibrio_usd_t")),
        "tir_p10": _num(linha.get("tir_alavancada_pct_p10")),
        "tir_p50": _num(linha.get("tir_alavancada_pct_p50")),
        "tir_p90": _num(linha.get("tir_alavancada_pct_p90")),
        "tir_projeto": _num(linha.get("tir_projeto_pct_p50")),
        "vpl_rs": _num(linha.get("valor_desenvolvedor_rs")) or 0.0,
        "pico_rs": (_num(linha.get("pico_capital_proprio_rs_ha_p50")) or 0.0) * area,
        "multa_rs": (_num(linha.get("multa_esperada_rs_ha")) or 0.0) * area,
        "marcos": marcos,
        "marcos_todos": (_num(linha.get("marcos_todos_chance_pct")) or 100.0) / 100,
        "caminho_terra": caminho_terra,
        "caminho": caminho,
        "risco_terra": linha.get("risco_terra") if isinstance(linha.get("risco_terra"), str) else "alto",
        "grupo_id": linha.get("grupo_id") if isinstance(linha.get("grupo_id"), str) else None,
        "mitigacao": _verdade(linha.get("fazenda_mitigacao")) or _verdade(linha.get("mitigacao_vizinha")),
        "embargo": (_num(linha.get("embargo_ha")) or 0) > 0,
        "terra_indigena": (_num(linha.get("ti_ha")) or 0) > 0 or caminho_terra == "terra_indigena_ou_tradicional",
        "uc_protecao_integral": (_num(linha.get("uc_protecao_integral_ha")) or 0) > 0,
        "projeto_carbono": (_num(linha.get("projeto_carbono_ha")) or 0) > 0,
        "bloqueio": bloqueio,
        "salvaguardas": salvaguardas,
        "elegivel_sem_salvaguardas": elegivel_sem_salvaguardas,
        "problema": _verdade(linha.get("problema")),
        "elegivel": bool(elegivel),
        "restauracao_versao": linha.get("restauracao_versao"),
        "cambio": cambio,
        "regeneracao_ha": _num(linha.get("restauracao_regeneracao_assistida_ha")) or 0.0,
        "semeadura_ha": _num(linha.get("restauracao_semeadura_direta_ha")) or 0.0,
        "plantio_ha": _num(linha.get("restauracao_plantio_total_ha")) or 0.0,
        "vazamento_motivo": linha.get("vazamento_motivo") if isinstance(linha.get("vazamento_motivo"), str) else None,
        "vazamento_mitigacao_imovel": str(linha["vazamento_mitigacao_imovel"])
        if isinstance(linha.get("vazamento_mitigacao_imovel"), str) and linha["vazamento_mitigacao_imovel"]
        else None,
        # quão perto do título está a posse ou o assentamento (raiz/titulo/regularizacao.py)
        "regularizacao_classe": linha.get("regularizacao_classe")
        if isinstance(linha.get("regularizacao_classe"), str)
        else None,
    }


def tabela(linhas: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([x for x in linhas if x is not None], columns=list(COLUNAS))
    return df.reset_index(drop=True)


# --- das pastas do motor (testes, máquina sem banco) ------------------------------------------------------------


def linhas_da_pasta(pasta: str | Path, cod: int, so: set[str] | None = None,
                    so_restauracao: bool = False) -> list[dict]:  # fmt: skip
    """imoveis_<mun>.csv com todos os complementos (desenvolvedor, terra, ficha, flag, filtros...), sem colunas
    pessoais; as colunas são lidas pelo nome e as novas vêm junto. `so`: só esses imóveis; `so_restauracao`: só os
    que têm área para restaurar no desenvolvedor_<mun>.csv (para ler um estado inteiro sem estourar a memória)."""
    from raiz.contrato import COMPLEMENTOS
    from raiz.privacidade import remover_colunas_pessoais

    pasta = Path(pasta)
    if so_restauracao:
        f = pasta / f"desenvolvedor_{cod}.csv"
        if not f.exists():
            return []
        d = pd.read_csv(f, usecols=lambda c: c in ("cod_imovel", "restauracao_area_ha"), dtype={"cod_imovel": str})
        com = set(d.cod_imovel[pd.to_numeric(d.get("restauracao_area_ha"), errors="coerce").fillna(0) > 0])
        so = com if so is None else (set(so) & com)
    im, _ = remover_colunas_pessoais(pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False))
    im["cod_imovel"] = im.cod_imovel.astype(str)
    if so is not None:
        im = im[im.cod_imovel.isin(so)]
    for tipo in ("filtros", *COMPLEMENTOS):
        f = pasta / f"{tipo}_{cod}.csv"
        if not f.exists():
            continue
        extra, _ = remover_colunas_pessoais(pd.read_csv(f, low_memory=False))
        extra["cod_imovel"] = extra.cod_imovel.astype(str)
        if so is not None:
            extra = extra[extra.cod_imovel.isin(so)]
        novas = [c for c in extra.columns if c == "cod_imovel" or c not in im.columns]
        im = im.merge(extra[novas].drop_duplicates("cod_imovel"), on="cod_imovel", how="left")
    return im.replace({np.nan: None}).to_dict("records")


def pontos_da_pasta(pasta: str | Path, cod: int) -> dict[str, tuple[float, float]]:
    f = Path(pasta) / f"geo_{cod}.parquet"
    if not f.exists():
        return {}
    import geopandas as gpd
    import shapely

    g = gpd.read_parquet(f)[["cod_imovel", "geometry"]].to_crs(4326)
    pts = shapely.point_on_surface(g.geometry.values)
    return {str(c): (float(p.x), float(p.y)) for c, p in zip(g.cod_imovel, pts, strict=True)}


def da_pasta(pastas: list[tuple[str | Path, int]]) -> pd.DataFrame:
    """Oferta a partir de (pasta do estado, código do município) do motor."""
    out = []
    for pasta, cod in pastas:
        pts = pontos_da_pasta(pasta, cod)
        for li in linhas_da_pasta(pasta, cod):
            p = pts.get(str(li["cod_imovel"]))
            out.append(de_linha(li, *(p if p else (None, None))))
    return tabela(out)


# --- banco (negocio.oferta) ---------------------------------------------------------------------------------------

CAMPOS_BANCO = (
    "cod_municipio_ibge", "uf", "bioma", "lon", "lat", "ha", "area_restauracao_ha", "modo_restauracao", "credito_p10",
    "credito_p50", "credito_p90", "custo_credito_usd", "preco_equilibrio_usd", "tir_alavancada_p50",
    "tir_projeto_p50", "valor_desenvolvedor_rs", "pico_capital_rs", "multa_esperada_rs", "marcos_todos_pct",
    "caminho_terra", "risco_terra", "grupo_id", "bloqueio", "restauracao_versao",
)  # fmt: skip


def atualizar(engine, cod_municipio: int) -> int:
    """Refaz negocio.oferta de um município a partir do banco (rodada vigente, com os complementos)."""
    from sqlalchemy import text

    from raiz.front_api import imoveis_do_municipio

    linhas = imoveis_do_municipio(engine, cod_ibge=int(cod_municipio))
    with engine.connect() as con:
        pts = {r.cod_imovel: (r.x, r.y) for r in con.execute(
            text("""select i.cod_imovel, ST_X(ST_PointOnSurface(i.geom)) as x, ST_Y(ST_PointOnSurface(i.geom)) as y
                    from funil.imovel i join funil.vigente v on v.cod_imovel = i.cod_imovel
                    where v.cod_municipio_ibge = :c and i.geom is not null"""), {"c": int(cod_municipio)})}  # fmt: skip
    from raiz.salvaguardas import do_banco as salvaguardas_do_banco

    verificacoes = salvaguardas_do_banco(engine, [str(li["cod_imovel"]) for li in linhas])
    regs = []
    for li in linhas:
        li = {**li, **verificacoes.get(str(li["cod_imovel"]), {})}
        o = de_linha(li, *pts.get(str(li["cod_imovel"]), (None, None)))
        if o is not None:
            regs.append(o)
    with engine.begin() as con:
        con.execute(text("delete from negocio.oferta where cod_municipio_ibge = :c"), {"c": int(cod_municipio)})
        for o in regs:
            extra = {k: o[k] for k in COLUNAS if k not in ("cod_imovel",)}
            con.execute(
                text("""insert into negocio.oferta (cod_imovel, cod_municipio_ibge, uf, bioma, lon, lat, ha,
                          area_restauracao_ha, modo_restauracao, credito_p10, credito_p50, credito_p90,
                          custo_credito_usd, preco_equilibrio_usd, tir_alavancada_p50, tir_projeto_p50,
                          valor_desenvolvedor_rs, pico_capital_rs, multa_esperada_rs, marcos_todos_pct, caminho_terra,
                          risco_terra, grupo_id, bloqueio, restauracao_versao, atributos)
                        values (:cod, :mun, :uf, :bioma, :lon, :lat, :ha, :area, :modo, :c10, :c50, :c90, :custo, :peq,
                          :tir, :tirp, :vpl, :pico, :multa, :marcos, :caminho, :risco, :grupo, :bloq, :versao,
                          cast(:attr as jsonb))
                        on conflict (cod_imovel) do update set cod_municipio_ibge = excluded.cod_municipio_ibge,
                          uf = excluded.uf, bioma = excluded.bioma, lon = excluded.lon, lat = excluded.lat,
                          ha = excluded.ha, area_restauracao_ha = excluded.area_restauracao_ha,
                          modo_restauracao = excluded.modo_restauracao, credito_p10 = excluded.credito_p10,
                          credito_p50 = excluded.credito_p50, credito_p90 = excluded.credito_p90,
                          custo_credito_usd = excluded.custo_credito_usd,
                          preco_equilibrio_usd = excluded.preco_equilibrio_usd,
                          tir_alavancada_p50 = excluded.tir_alavancada_p50, tir_projeto_p50 = excluded.tir_projeto_p50,
                          valor_desenvolvedor_rs = excluded.valor_desenvolvedor_rs,
                          pico_capital_rs = excluded.pico_capital_rs, multa_esperada_rs = excluded.multa_esperada_rs,
                          marcos_todos_pct = excluded.marcos_todos_pct, caminho_terra = excluded.caminho_terra,
                          risco_terra = excluded.risco_terra, grupo_id = excluded.grupo_id,
                          bloqueio = excluded.bloqueio, restauracao_versao = excluded.restauracao_versao,
                          atributos = excluded.atributos, atualizado_em = now()"""),
                {"cod": o["cod_imovel"], "mun": o["cod_ibge"], "uf": o["uf"], "bioma": o["bioma"], "lon": o["lon"],
                 "lat": o["lat"], "ha": o["ha"], "area": o["area_ha"], "modo": o["modo"], "c10": o["credito_p10"],
                 "c50": o["credito_p50"], "c90": o["credito_p90"], "custo": o["custo_credito_usd"],
                 "peq": o["preco_equilibrio_usd"], "tir": o["tir_p50"], "tirp": o["tir_projeto"], "vpl": o["vpl_rs"],
                 "pico": o["pico_rs"], "multa": o["multa_rs"], "marcos": 100 * o["marcos_todos"],
                 "caminho": o["caminho_terra"], "risco": o["risco_terra"], "grupo": o["grupo_id"],
                 "bloq": o["bloqueio"], "versao": o["restauracao_versao"],
                 "attr": json.dumps({k: v for k, v in extra.items()}, default=str)},
            )  # fmt: skip
    return len(regs)


def do_banco(engine, ufs: list[str] | None = None, municipios: list[int] | None = None) -> pd.DataFrame:
    """A oferta guardada (negocio.oferta), já no formato da tabela."""
    from sqlalchemy import text

    filtros, par = ["true"], {}
    if ufs:
        filtros.append("uf = any(:ufs)")
        par["ufs"] = [u.upper() for u in ufs]
    if municipios:
        filtros.append("cod_municipio_ibge = any(:ms)")
        par["ms"] = [int(m) for m in municipios]
    with engine.connect() as con:
        rs = con.execute(text(f"select cod_imovel, atributos from negocio.oferta where {' and '.join(filtros)}"), par)
        linhas = []
        for r in rs:
            a = dict(r.atributos or {})
            a["cod_imovel"] = r.cod_imovel
            a["marcos"] = {int(k): v for k, v in (a.get("marcos") or {}).items()}
            linhas.append(a)
    from raiz.salvaguardas import avaliar
    from raiz.salvaguardas import do_banco as salvaguardas_do_banco

    verificacoes = salvaguardas_do_banco(engine, [li["cod_imovel"] for li in linhas])
    for li in linhas:
        dados = {**li, **verificacoes.get(li["cod_imovel"], {})}
        dados["territorio_tradicional"] = (li.get("salvaguardas") or {}).get("territorio_tradicional", False)
        li["salvaguardas"] = avaliar(dados, dados.get("verificacao"))
        li["elegivel"] = (
            bool(li.get("elegivel_sem_salvaguardas", li.get("elegivel"))) and li["salvaguardas"]["pode_originar"]
        )
    return tabela(linhas)
