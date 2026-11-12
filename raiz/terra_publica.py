"""Camada "Terra pública para restaurar", por estado.

Áreas candidatas a concessão de restauração:
  - glebas públicas federais e estaduais não destinadas: Cadastro Nacional de Florestas Públicas (SFB, CNFP tipo B);
  - glebas públicas do SIGEF (natureza "Gleba Pública"), quando não repetem uma gleba do CNFP;
  - unidades de conservação de uso sustentável de domínio público: florestas nacionais e estaduais, reservas
    extrativistas, reservas de desenvolvimento sustentável e reservas de fauna (CNUC). APA, ARIE e RPPN ficam de fora
    porque admitem terra privada. Reserva extrativista e de desenvolvimento sustentável levam o aviso do art. 47 da
    Lei 15.042/2024 (consulta e no mínimo 50% dos créditos para as comunidades).
Para cada área: hectares desmatados e de pasto (MapBiomas cobertura do motor), custo, captura e crédito líquido
estimados (raiz/restauracao.py, as mesmas premissas da fazenda) e se já há concessão ou edital (concessoes.yaml,
com data e link). Grava dados/terra_publica/terra_publica_<UF>.parquet e carrega em geo.terra_publica.
"""

from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CNFP_URL = "https://mapas.florestal.gov.br/portal/sharing/rest/content/items/2b752dfbf9254920bf8990ce363918af/data"
CNFP_PAGINA = (
    "https://www.gov.br/florestal/pt-br/assuntos/cadastro-nacional-de-florestas-publicas/"
    "cadastro-nacional-de-florestas-publicas-atualizacao-2025"
)
UC_USO_SUSTENTAVEL_PUBLICA = ("Floresta", "Reserva Extrativista", "Reserva de Desenvolvimento Sustentável",
                              "Reserva de Fauna")  # fmt: skip
UC_TRADICIONAL = ("Reserva Extrativista", "Reserva de Desenvolvimento Sustentável")
# classes do MapBiomas que contam como área desmatada (aberta pelo uso): pasto, agricultura, mosaico, silvicultura,
# área não vegetada, mineração
DESMATADO = (15, 9, 18, 19, 20, 21, 25, 30, 35, 36, 39, 40, 41, 46, 47, 48, 62)
PASTO = (15,)
MATA = (3, 4, 5, 6, 49)
TAXA_C = {"amz_oeste": 3.0, "amz_leste": 1.3, "amz_sudeste": 1.8, "Cerrado": 1.0, "Mata Atlântica": 2.5,
          "Caatinga": 0.6, "Pantanal": 1.0, "Pampa": 0.8}  # fmt: skip  # igual ao motor (raiz_estado.py)
BIOMAS = {"AMAZÔNIA": "Amazônia", "CERRADO": "Cerrado", "MATA ATLÂNTICA": "Mata Atlântica", "CAATINGA": "Caatinga",
          "PANTANAL": "Pantanal", "PAMPA": "Pampa"}  # fmt: skip


def pasta() -> Path:
    from raiz import RAIZ_REPO
    from raiz.config import config

    p = Path(getattr(config(), "terra_publica_dir", None) or RAIZ_REPO / "dados" / "terra_publica")
    p.mkdir(parents=True, exist_ok=True)
    return p


# --- Cadastro Nacional de Florestas Públicas -----------------------------------------------------------------------


def baixar_cnfp(destino: Path | None = None) -> Path:
    import httpx

    destino = Path(destino or pasta() / "CNFP_2025.zip")
    if destino.exists():
        return destino
    tmp = destino.with_suffix(".parcial")
    with httpx.stream("GET", CNFP_URL, follow_redirects=True, timeout=600) as r, tmp.open("wb") as f:
        r.raise_for_status()
        for parte in r.iter_bytes(1 << 20):
            f.write(parte)
    tmp.replace(destino)
    return destino


def preparar_cnfp(zip_: Path | None = None, saida: Path | None = None) -> dict[str, int]:
    """Lê o shapefile do CNFP uma vez e grava um GeoParquet por estado (cnfp_<UF>.parquet), em SIRGAS 2000."""
    import pyogrio

    zip_ = Path(zip_ or pasta() / "CNFP_2025.zip")
    saida = Path(saida or pasta())
    nome = "CNFP_2025.shp"
    g = pyogrio.read_dataframe(f"/vsizip/{zip_}/{nome}")
    g = g.set_crs(4674) if g.crs is None else g.to_crs(4674)
    g["tipo"] = g["tipo"].astype(str).str.replace("TIPO ", "", regex=False).str.strip().str.upper()
    cols = [c for c in ("nome", "categoria", "protecao", "tipo", "governo", "comunitari", "orgao", "estagio", "uf",
                        "municipio", "geocodigo", "area_ha", "bioma", "anocriacao") if c in g.columns]  # fmt: skip
    g = g[[*cols, "geometry"]]
    out = {}
    for uf in sorted(set(x for v in g.uf.dropna().astype(str) for x in v.split("/"))):
        parte = g[g.uf.astype(str).str.split("/").apply(lambda xs, u=uf: u in xs)]
        parte.to_parquet(saida / f"cnfp_{uf}.parquet")
        out[uf] = len(parte)
    return out


# --- áreas candidatas -------------------------------------------------------------------------------------------


def areas_da_uf(uf: str, cache_motor: Path | None, espelho: Path | None = None, cnfp: Path | None = None):
    """GeoDataFrame das áreas públicas candidatas a restaurar no estado, uma linha por área, com a origem."""
    import geopandas as gpd
    import pandas as pd

    from raiz import terra as T
    from raiz.funil import ponte

    uf = uf.upper()
    partes = []
    cnfp = Path(cnfp) if cnfp else T.cnfp_da_uf(uf)
    if cnfp and cnfp.exists():
        c = gpd.read_parquet(cnfp)
        b = c[c["tipo"].astype(str).str.upper().isin(["B", "C"])]
        for _, x in b.iterrows():
            partes.append({"fonte": "cnfp", "chave": f"{x.get('nome')}|{x.get('geocodigo')}|{x.get('governo')}",
                           "nome": x.get("nome"), "destinacao": "sem_destinacao", "categoria": x.get("categoria"),
                           "esfera": str(x.get("governo") or "").capitalize(), "orgao": x.get("orgao"),
                           "bioma": BIOMAS.get(str(x.get("bioma") or "").split("/")[0], None),
                           "tradicional": False, "geometry": x.geometry})  # fmt: skip
    ucf = sorted(Path(cache_motor).glob("conservationunits_*.parquet")) if cache_motor else []
    if ucf:
        u = gpd.read_parquet(ucf[-1])
        u = u.set_crs(4674) if u.crs is None else u.to_crs(4674)
        u = u[u["categoria"].isin(UC_USO_SUSTENTAVEL_PUBLICA) & u["uf"].astype(str).str.upper().str.contains(
            _nome_uf(uf).upper(), regex=False)]  # fmt: skip
        for _, x in u.iterrows():
            partes.append({"fonte": "cnuc", "chave": str(x.get("cd_cnuc") or x.get("uc_id")), "nome": x.get("nome_uc"),
                           "destinacao": "uc_uso_sustentavel", "categoria": x.get("categoria"),
                           "esfera": x.get("esfera"), "orgao": x.get("org_gestor"), "bioma": None,
                           "tradicional": x.get("categoria") in UC_TRADICIONAL, "geometry": x.geometry})  # fmt: skip
    # área exata das concessões do estado (ex.: URTX, união das áreas de restauração)
    from raiz import terra as T2

    exatas = T2.poligonos_concessoes()
    if exatas is not None:
        for _, x in exatas.iterrows():
            c = T2.concessao(x.concessao) or {}
            if str(c.get("uf", "")).upper() == uf:
                partes.append({"fonte": "concessao", "chave": x.concessao, "nome": c.get("nome"),
                               "destinacao": "concessao", "categoria": c.get("tipo"), "esfera": None,
                               "orgao": c.get("orgao"), "bioma": None, "tradicional": False,
                               "geometry": x.geometry})  # fmt: skip
    base = gpd.GeoDataFrame(partes, geometry="geometry", crs=4674) if partes else None
    # glebas públicas do SIGEF do espelho (só as que não repetem uma gleba do CNFP)
    esp = Path(espelho or ponte.espelho_padrao()) / "sigef" / uf
    glebas = []
    for f in sorted(esp.glob("*.parquet")) if esp.exists() else []:
        s = gpd.read_parquet(f)
        if "natureza" not in s:
            continue
        s = s[s["natureza"].astype(str).str.lower().isin(["gleba pública", "gleba publica"])]
        if len(s):
            glebas.append(s.set_crs(4674) if s.crs is None else s.to_crs(4674))
    if glebas:
        s = pd.concat(glebas).drop_duplicates("parcela_codigo" if "parcela_codigo" in glebas[0] else "id")
        if base is not None and len(base):
            cobertas = T.area_sobreposta(
                s.assign(cod_imovel=s["parcela_codigo"].astype(str)), base[base.fonte == "cnfp"]
            )
            area = s.to_crs(5880).area / 1e4
            fica = [cobertas.get(str(k), 0.0) < 0.5 * a for k, a in zip(s["parcela_codigo"], area, strict=True)]
            s = s[fica]
        for _, x in s.iterrows():
            partes.append({"fonte": "sigef", "chave": str(x.get("parcela_codigo")), "nome": "Gleba pública (SIGEF)",
                           "destinacao": "sem_destinacao", "categoria": "GLEBA PÚBLICA", "esfera": None, "orgao": None,
                           "bioma": None, "tradicional": False, "geometry": x.geometry})  # fmt: skip
    if not partes:
        return None
    g = gpd.GeoDataFrame(partes, geometry="geometry", crs=4674)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].reset_index(drop=True)
    g["id"] = [  # a mesma gleba pode vir em várias partes: a geometria entra no id
        f"{uf}-{f}-{hashlib.sha1(str(k).encode() + geom.wkb[:4096]).hexdigest()[:12]}"
        for f, k, geom in zip(g.fonte, g.chave, g.geometry, strict=True)
    ]
    g["uf"] = uf
    g["ha"] = (g.to_crs(5880).area / 1e4).round(2)
    return g


def _nome_uf(uf: str) -> str:
    from raiz.front_api import UFS

    return UFS.get(uf.upper(), uf)


def concessao_da_area(linha: dict, r: dict | None = None) -> dict | None:
    """Concessão ou edital ligado à área pelo nome da UC ou da gleba (concessoes.yaml)."""
    from raiz import terra as T

    r = r or T.regra()
    if linha.get("fonte") == "concessao":
        return T.concessao(linha.get("chave") or linha.get("concessao_id"), r)
    nome = str(linha.get("nome") or "").upper()
    for c in r["concessoes"]["concessoes"]:
        v = c.get("vinculo") or {}
        if (v.get("uc") and linha.get("fonte") == "cnuc" and v["uc"].upper() == nome) or (
            v.get("cnfp") and linha.get("fonte") == "cnfp" and v["cnfp"].upper() in nome
        ):
            return c
    return None


# --- cruzamento com o MapBiomas e estimativa para quem restaura ------------------------------------------------


def _regiao(uf: str, bioma: str, lat: float) -> str:
    if bioma == "Amazônia":
        if uf in ("AC", "AM", "RR", "RO"):
            return "amz_oeste"
        if uf in ("MT", "TO") or (uf in ("PA", "MA") and lat < -5):
            return "amz_sudeste"
        return "amz_leste"
    return bioma


def cruzar(areas, cobertura_tif: Path | None, cache: Path | None = None, reducao: int = 4,
           fontes_geo: tuple[str, ...] = ("faixas", "chuva", "solo")):  # fmt: skip
    """Desmatado, pasto e mata por área (MapBiomas) e a estimativa de custo, captura e crédito líquido."""
    import pandas as pd
    import rasterio
    import shapely

    from raiz import restauracao as RS
    from raiz import restauracao_geo as G
    from raiz.funil.novo import zonal

    a = areas.copy()
    a["cod_imovel"] = a["id"]
    classes = {}
    if cobertura_tif and Path(cobertura_tif).exists():
        with rasterio.open(cobertura_tif) as ras:
            d = zonal(ras, a[["cod_imovel", "geometry"]], ("classes",), include_cols=["cod_imovel"]).reset_index(
                drop=True
            )
            res = abs(ras.res[0])
        lat = a.geometry.centroid.y.values
        hp = (res * 111320.0) ** 2 * np.cos(np.radians(lat)) / 1e4
        for i, row in d.iterrows():
            conta = {int(k[1:]): float(v or 0) for k, v in row.items() if isinstance(k, str) and k[:1] == "c"
                     and k[1:].isdigit()}  # fmt: skip
            classes[str(row["cod_imovel"])] = {
                "desmatado_ha": round(sum(conta.get(c, 0) for c in DESMATADO) * hp[i], 2),
                "pasto_ha": round(sum(conta.get(c, 0) for c in PASTO) * hp[i], 2),
                "mata_ha": round(sum(conta.get(c, 0) for c in MATA) * hp[i], 2),
            }
    a["desmatado_ha"] = [classes.get(i, {}).get("desmatado_ha") for i in a.id]
    a["pasto_ha"] = [classes.get(i, {}).get("pasto_ha") for i in a.id]
    a["mata_ha"] = [classes.get(i, {}).get("mata_ha") for i in a.id]
    # entradas geográficas só onde há o que restaurar (a grade mais grossa basta para uma área pública inteira)
    com = a[(a.desmatado_ha.fillna(0) >= 1)]
    por, mun = {}, {}
    if len(com):
        cache = Path(cache or G.pasta_cache())
        pts = shapely.point_on_surface(com.geometry.values)
        pontos = {i: (float(p.x), float(p.y)) for i, p in zip(com.id, pts, strict=True)}
        por = {i: {} for i in com.id}
        if "faixas" in fontes_geo and cobertura_tif:
            try:
                pi, mun = G.faixas_e_linha_base(com[["cod_imovel", "geometry"]], cobertura_tif, pasta_tmp=cache,
                                                reducao=reducao)  # fmt: skip
                for i, v in pi.items():
                    por.setdefault(i, {}).update(v)
            except Exception as e:  # noqa: BLE001
                log.warning("faixas de distância da terra pública falharam: %s", e)
        for nome, col, fn in (("chuva", "chuva_mm_ano", lambda: G.chuva(pontos, cache)),
                              ("solo", "solo_cec_cmolc_kg", lambda: G.solo_cec(pontos, f"terra_{com.uf.iloc[0]}",
                                                                                cache))):  # fmt: skip
            if nome in fontes_geo:
                try:
                    for i, v in fn().items():
                        por.setdefault(i, {})[col] = v
                except Exception as e:  # noqa: BLE001
                    log.warning("%s da terra pública falhou: %s", nome, e)
    r = RS.regra()
    c = RS.cenario(r=r)
    linhas = []
    for x in a.itertuples():
        desm = x.desmatado_ha or 0.0
        lat = float(shapely.point_on_surface(x.geometry).y)
        bioma = x.bioma or "Amazônia"
        taxa = TAXA_C.get(_regiao(x.uf, bioma, lat), 1.0) * (1 + RS.RAIZ) * RS.C2CO2
        conc = concessao_da_area({"nome": x.nome, "fonte": x.fonte, "chave": x.chave})
        conc = conc or {}
        base = {"id": x.id, "desmatado_ha": x.desmatado_ha, "pasto_ha": x.pasto_ha, "mata_ha": x.mata_ha,
                "concessao": conc.get("id"), "concessao_situacao": conc.get("situacao"),
                "concessao_data": conc.get("data"), "concessao_link": conc.get("link")}  # fmt: skip
        if desm >= 1:
            linha = {"uf": x.uf, "bioma": bioma, "alem_RL_ha": desm, "pasto_ha": desm, "app_recompor_ha": 0.0,
                     "taxa_tco2_ha_ano": taxa, **por.get(x.id, {}),
                     **{k: v for k, v in mun.items() if k.startswith("linha_base_")}}  # fmt: skip
            calc = RS.por_imovel(linha, c, r)
            base.update({k: calc[k] for k in COLUNAS_ESTIMATIVA})
        linhas.append(base)
    return a.drop(columns="cod_imovel").merge(pd.DataFrame(linhas), on="id", how="left", suffixes=("", "_x"))


def gerar_uf(uf: str, cache_motor: Path, espelho: Path | None = None, cache: Path | None = None,
             reducao: int = 4, fontes_geo: tuple[str, ...] = ("faixas", "chuva", "solo")) -> Path | None:  # fmt: skip
    """terra_publica_<UF>.parquet com as áreas e os números; devolve o arquivo (None se o estado não tem área)."""
    from raiz import terra as T

    uf = uf.upper()
    a = areas_da_uf(uf, cache_motor, espelho)
    if a is None or not len(a):
        return None
    cob = sorted((Path(cache_motor) / "mapbiomas" / uf).glob(f"{uf}_cobertura_2*.tif"))
    cob = [f for f in cob if f.stem.count("_") == 2]
    t = cruzar(a, cob[-1] if cob else None, cache, reducao, fontes_geo)
    t["terra_regra_versao"] = T.versao()
    f = pasta() / f"terra_publica_{uf}.parquet"
    tmp = f.with_suffix(".tmp")
    t.to_parquet(tmp)
    tmp.replace(f)
    return f


COLUNAS_ESTIMATIVA = (
    "modo_restauracao", "custo_restauracao_ha_p10", "custo_restauracao_ha_p50", "custo_restauracao_ha_p90",
    "captura_tco2_ha_ano_p10", "captura_tco2_ha_ano_p50", "captura_tco2_ha_ano_p90", "desconto_linha_base_pct",
    "credito_liquido_tco2_ha_ano", "credito_liquido_tco2_ano", "vpl_rs_ha_p50", "tir_alavancada_pct_p50",
    "restauracao_faltou", "restauracao_versao",
)  # fmt: skip
COLUNAS_BANCO = (
    "id", "uf", "fonte", "nome", "destinacao", "categoria", "esfera", "orgao", "tradicional", "ha", "desmatado_ha",
    "pasto_ha", "mata_ha", "modo_restauracao", "custo_restauracao_ha_p10", "custo_restauracao_ha_p50",
    "custo_restauracao_ha_p90", "captura_tco2_ha_ano_p10", "captura_tco2_ha_ano_p50", "captura_tco2_ha_ano_p90",
    "desconto_linha_base_pct", "credito_liquido_tco2_ha_ano", "credito_liquido_tco2_ano", "vpl_rs_ha_p50",
    "tir_alavancada_pct_p50", "concessao", "concessao_situacao", "concessao_data", "concessao_link",
    "restauracao_faltou", "restauracao_versao", "terra_regra_versao",
)  # fmt: skip


def carregar(engine, arquivo: Path) -> int:
    """Troca as áreas do estado em geo.terra_publica (o estado inteiro de uma vez, numa transação)."""
    import geopandas as gpd
    from sqlalchemy import text

    t = gpd.read_parquet(arquivo)
    uf = str(t.uf.iloc[0])
    t = t.to_crs(4674)
    # id único mesmo em arquivo antigo (gleba em várias partes com o mesmo nome)
    vistos: dict[str, int] = {}
    ids = []
    for i in t["id"]:
        vistos[i] = vistos.get(i, 0) + 1
        ids.append(i if vistos[i] == 1 else f"{i}-{vistos[i]}")
    t["id"] = ids
    with engine.begin() as con:
        con.execute(text("delete from geo.terra_publica where uf = :u"), {"u": uf})
        for x in t.to_dict("records"):
            vals = {c: _limpo(x.get(c)) for c in COLUNAS_BANCO}
            vals["wkb"] = x["geometry"].wkb
            con.execute(
                text(f"""insert into geo.terra_publica ({", ".join(COLUNAS_BANCO)}, geom)
                         values ({", ".join(":" + c for c in COLUNAS_BANCO)},
                                 ST_Multi(ST_CollectionExtract(ST_MakeValid(
                                     ST_Force2D(ST_GeomFromWKB(:wkb, 4674))), 3)))"""),
                vals,
            )
    return len(t)


def _limpo(v):
    if v is None:
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


# --- editais: SFB e Ideflor-Bio --------------------------------------------------------------------------------

# só o que é concessão (não pregão de compra): concessão, recuperação, restauração, unidade de manejo, floresta
# nacional ou estadual, gleba
PADRAO_EDITAL = r"concess|recupera|restaura|unidade[ -_]de[ -_]manejo|flona|flota|floresta[ -_]nacional|gleba"


def conferir_editais(estado: Path | None = None, cliente=None) -> dict:
    """Lê as páginas de editais e contratos das duas fontes (concessoes.yaml: fontes), guarda os links com a data em
    que apareceram (dados/terra_publica/editais_vistos.json) e devolve os novos, para conferir e registrar em
    concessoes.yaml com data e link."""
    import datetime as dt
    import html as html_mod
    import json
    import re
    from urllib.parse import urljoin

    import httpx

    from raiz import terra as T

    estado = Path(estado or pasta() / "editais_vistos.json")
    vistos = json.loads(estado.read_text(encoding="utf-8")) if estado.exists() else {}
    hoje = dt.date.today().isoformat()
    novos, erros = [], {}
    cli = cliente or httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "raiz-editais/1"})
    try:
        for fonte, url in T.regra()["concessoes"]["fontes"].items():
            try:
                html = cli.get(url).text
            except httpx.HTTPError as e:
                erros[fonte] = str(e)
                continue
            for href, txt in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
                texto = " ".join(html_mod.unescape(re.sub(r"<[^>]+>", " ", txt)).split())
                alvo = f"{href} {texto}".lower()
                if not re.search(PADRAO_EDITAL, alvo):
                    continue
                link = urljoin(url, href)
                if link not in vistos:
                    vistos[link] = {"fonte": fonte, "texto": texto[:200], "visto_em": hoje}
                    novos.append({"link": link, **vistos[link]})
    finally:
        if cliente is None:
            cli.close()
    estado.write_text(json.dumps(vistos, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"novos": novos, "total": len(vistos), "erros": erros}
