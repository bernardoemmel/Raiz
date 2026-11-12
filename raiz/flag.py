"""Remoções para meta FLAG pela regra GHG Protocol LSR v1.1 (raiz/regras/padroes/ghg_lsr.yaml), por imóvel.

Na meta FLAG da empresa só conta remoção em terra agrícola produtiva: silvipastoril (árvore no pasto) e
agrofloresta de cacau. Restauração (área além da reserva legal, reserva legal, APP) e capoeira vão para crédito
Verra ou compensação voluntária. A mesma área nunca entra nos dois: o plano padrão dá ao crédito a regeneração que
o motor já mede (carbono_ha) e à meta FLAG o resto do pasto e da agricultura livres; o simulador muda essa divisão
sem deixar um hectare nos dois lados. As toneladas dos dois blocos nunca são somadas.

Colunas (flag_<mun>.csv, docs/colunas.md): flag_silvipastoril_ha, flag_silvipastoril_degradado_ha, flag_cacau_ha,
flag_cacau_viavel, flag_plano_silvipastoril_ha, flag_plano_cacau_ha, flag_tco2_ano (central), flag_tco2_ano_min,
flag_tco2_ano_max, credito_alem_rl_ha, credito_tco2_ano, rl_restauracao_ha, app_restauracao_ha, capoeira_ha,
flag_regra_versao.
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from pathlib import Path

import yaml

ARQUIVO = Path(__file__).parent / "regras" / "padroes" / "ghg_lsr.yaml"


@lru_cache
def _ler(arquivo: Path) -> dict:
    texto = arquivo.read_bytes()
    r = yaml.safe_load(texto)
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(texto).hexdigest()[:8]}"
    return r


def regra(arquivo: Path | None = None) -> dict:
    """A tabela da regra (por padrão raiz/regras/padroes/ghg_lsr.yaml), com versao_completa = versão + hash."""
    return _ler(Path(arquivo or ARQUIVO))


def versao() -> str:
    return regra()["versao_completa"]


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _n0(linha: dict, c: str) -> float:
    x = _num(linha, c)
    return 0.0 if x is None else x


def _mb(linha: dict, indicador: str) -> float | None:
    """Coluna mb_<indicador>_<ano>_ha mais recente que existir (lida pelo nome; o ano muda a cada coleção)."""
    anos = []
    for c in linha:
        m = re.fullmatch(rf"mb_{indicador}_((?:19|20)\d{{2}})_ha", c)
        if m and _num(linha, c) is not None:
            anos.append((int(m.group(1)), c))
    return _num(linha, max(anos)[1]) if anos else None


def cacau_viavel(linha: dict, r: dict | None = None) -> bool:
    r = r or regra()
    cv = r["cacau_viavel"]
    apt = _num(linha, "cacau_aptidao")
    if apt is not None:  # o motor manda quando entregar a aptidão por imóvel
        return apt >= cv["cacau_aptidao_minima"]
    bioma, uf = linha.get("bioma"), str(linha.get("uf") or "").upper()
    return bioma in cv["biomas"] or (bioma == "Mata Atlântica" and uf in cv["ufs_mata_atlantica"])


def por_imovel(linha: dict, pasto_baixo_vigor_ha: float | None = None, r: dict | None = None) -> dict:
    """Colunas flag_* de um imóvel a partir das colunas do motor (lidas pelo nome; as que faltarem contam como 0)."""
    r = r or regra()
    alem = _n0(linha, "alem_RL_ha")
    app = _num(linha, "app_recompor_ha")
    app = _n0(linha, "app_desmatada_ha") if app is None else app
    livre = max(alem - app, 0.0)  # aberto, fora da reserva legal e da APP
    pasto = _num(linha, "pasto_ha")
    pasto = _mb(linha, "pasto") if pasto is None else pasto
    agri = _mb(linha, "agricultura") or 0.0
    pasto_livre = min(pasto or 0.0, livre)
    agri_livre = min(agri, max(livre - pasto_livre, 0.0))
    if pasto_baixo_vigor_ha is None:  # sem a área por classe de vigor: vale a classe principal do imóvel
        vig = _num(linha, "mb_pasto_vigor_principal")
        pasto_baixo_vigor_ha = pasto_livre if vig is not None and int(vig) in r["pasto_vigor_baixo"] else 0.0
    viavel = cacau_viavel(linha, r)
    # crédito: a regeneração que o motor mede na área além da reserva (pasto perto de floresta). Ela ocupa primeiro o
    # pasto livre e, se passar dele, a agricultura livre; a meta FLAG fica só com o que sobra (nenhum hectare nos dois)
    carbono_ha = _n0(linha, "carbono_ha")
    credito_alem = min(carbono_ha, livre)
    credito_tco2 = _n0(linha, "carbono_tco2_ano") * (credito_alem / carbono_ha if carbono_ha > 0 else 0.0)
    credito_no_pasto = min(credito_alem, pasto_livre)
    credito_fora = credito_alem - credito_no_pasto
    plano_silvi = pasto_livre - credito_no_pasto  # silvipastoril no pasto que sobrou (o degradado primeiro)
    plano_cacau = max(agri_livre - credito_fora, 0.0) if viavel else 0.0  # cacau na agricultura livre que sobrou
    taxa = r["remocao_tco2_ha_ano"]
    tco2 = {
        k: plano_silvi * taxa["silvipastoril"][k] + plano_cacau * taxa["agrofloresta_cacau"][k]
        for k in ("minimo", "central", "maximo")
    }
    capoeira = _num(linha, "secundaria_ha")
    capoeira = _mb(linha, "veg_secundaria") if capoeira is None else capoeira
    return {
        "flag_silvipastoril_ha": round(pasto_livre, 4),
        "flag_silvipastoril_degradado_ha": round(min(pasto_baixo_vigor_ha, pasto_livre), 4),
        "flag_cacau_ha": round(pasto_livre + agri_livre, 4) if viavel else 0.0,
        "flag_cacau_viavel": viavel,
        "flag_plano_silvipastoril_ha": round(plano_silvi, 4),
        "flag_plano_cacau_ha": round(plano_cacau, 4),
        "flag_tco2_ano": round(tco2["central"], 2),
        "flag_tco2_ano_min": round(tco2["minimo"], 2),
        "flag_tco2_ano_max": round(tco2["maximo"], 2),
        "credito_alem_rl_ha": round(credito_alem, 4),
        "credito_tco2_ano": round(credito_tco2, 2),
        "rl_restauracao_ha": round(_n0(linha, "deficit_RL_ha"), 4),
        "app_restauracao_ha": round(app, 4),
        "capoeira_ha": round(capoeira or 0.0, 4),
        "flag_regra_versao": r["versao_completa"],
    }


def simular(linha: dict, silvipastoril_ha: float, cacau_ha: float, r: dict | None = None) -> dict:
    """Simulador: o dono escolhe quantos hectares vão para silvipastoril e cacau (meta FLAG). A regeneração do crédito
    fica com o que sobrar da área livre; o que passar do disponível é cortado. Os dois blocos nunca se somam."""
    r = r or regra()
    base = por_imovel(linha, r=r)
    pasto_livre = base["flag_silvipastoril_ha"]
    agri_livre = max(base["flag_cacau_ha"] - pasto_livre, 0.0) if base["flag_cacau_viavel"] else 0.0
    cacau = min(max(cacau_ha, 0.0), base["flag_cacau_ha"])
    cacau_no_agri = min(cacau, agri_livre)
    cacau_no_pasto = cacau - cacau_no_agri
    silvi = min(max(silvipastoril_ha, 0.0), max(pasto_livre - cacau_no_pasto, 0.0))
    # a regeneração do crédito fica onde o motor a mediu (pasto perto de floresta, e o que passou dele) e só com o
    # que a meta FLAG não usou
    credito_base = base["credito_alem_rl_ha"]
    no_pasto = min(credito_base, pasto_livre)
    fora = credito_base - no_pasto
    credito_alem = min(no_pasto, max(pasto_livre - silvi - cacau_no_pasto, 0.0)) + min(
        fora, max(agri_livre - cacau_no_agri, 0.0) + max(fora - agri_livre, 0.0)
    )
    taxa = r["remocao_tco2_ha_ano"]
    carbono_ha = _n0(linha, "carbono_ha")
    credito_tco2 = _n0(linha, "carbono_tco2_ano") * (credito_alem / carbono_ha if carbono_ha > 0 else 0.0)
    meta = {
        k: silvi * taxa["silvipastoril"][k] + cacau * taxa["agrofloresta_cacau"][k]
        for k in ("minimo", "central", "maximo")
    }
    return {
        "meta_flag": {
            "silvipastoril_ha": round(silvi, 2),
            "cacau_ha": round(cacau, 2),
            "tco2_ano": round(meta["central"], 1),
            "tco2_ano_min": round(meta["minimo"], 1),
            "tco2_ano_max": round(meta["maximo"], 1),
        },
        "credito_ou_compensacao": {
            "regeneracao_alem_rl_ha": round(credito_alem, 2),
            "regeneracao_tco2_ano": round(credito_tco2, 1),
            "reserva_legal_ha": base["rl_restauracao_ha"],
            "app_ha": base["app_restauracao_ha"],
            "capoeira_ha": base["capoeira_ha"],
        },
        "cortado": {
            "silvipastoril_ha": round(max(silvipastoril_ha - silvi, 0.0), 2),
            "cacau_ha": round(max(cacau_ha - cacau, 0.0), 2),
        },
        "regra": r["versao_completa"],
    }


def requisitos(linha: dict, calc: dict | None = None, r: dict | None = None) -> list[dict]:
    """Checklist dos requisitos do padrão para a remoção entrar no inventário, com o que já se sabe da fazenda."""
    r = r or regra()
    calc = calc or por_imovel(linha, r=r)
    fogo = _mb(linha, "fogo") or 0.0
    corte = (_mb(linha, "supressao_primaria") or 0.0) + (_mb(linha, "supressao_secundaria") or 0.0)
    projeto = _n0(linha, "projeto_carbono_ha")
    req = r["requisitos"]
    return [
        {
            "id": "rastreio",
            "texto": req["rastreio"],
            "status": "pendente",
            "detalhe": "Falta o vínculo da fazenda com o frigorífico comprador (fornecedor direto).",
        },
        {
            "id": "medicao",
            "texto": req["medicao"],
            "status": "pendente",
            "detalhe": "Sem medição de campo ainda; depois da primeira, nova amostragem a cada "
            f"{r['anos_reamostragem']} anos. Até lá vale a faixa provisória.",
        },
        {
            "id": "incerteza",
            "texto": req["incerteza"],
            "status": "ok",
            "detalhe": f"{calc['flag_tco2_ano_min']:g} a {calc['flag_tco2_ano_max']:g} tCO2 por ano "
            f"(central {calc['flag_tco2_ano']:g}; faixa provisória até a medição).",
        },
        {
            "id": "perdas",
            "texto": req["perdas"],
            "status": "atencao" if fogo > 0 or corte > 0 else "ok",
            "detalhe": (
                f"No último ano do MapBiomas: {fogo:g} ha de fogo e {corte:g} ha de corte de vegetação; entram como "
                "perda e são abatidos da remoção."
                if fogo > 0 or corte > 0
                else "Sem fogo nem corte de vegetação no último ano do MapBiomas; vigiado a cada ano."
            ),
        },
        {
            "id": "dupla_contagem",
            "texto": req["dupla_contagem"],
            "status": "bloqueia" if projeto > 1 else "ok",
            "detalhe": (
                f"{projeto:g} ha sobrepõem projeto de carbono já registrado: essa área não entra na meta FLAG."
                if projeto > 1
                else "Nenhum projeto de carbono registrado na área. O contrato precisa trazer o direito de reportar."
            ),
        },
    ]


def requirement_7(linha: dict, r: dict | None = None) -> dict:
    """Reserva legal, APP e capoeira modeladas com os critérios do Requirement 7, desligadas na v1.1."""
    r = r or regra()
    c = r["requirement_7"]["criterios"]
    return {
        "status": "aguardando regra",
        "ativo": r["requirement_7"]["ativo"],
        "explicacao": f"A {r['versao']} não deixa floresta contar na meta FLAG. Quando uma versão futura deixar, estas "
        "áreas entram se os quatro critérios forem cumpridos.",
        "criterios": [
            {"id": "mesmo_dono", "texto": c["mesmo_dono"], "status": "ok", "detalhe": "mesmo imóvel no CAR"},
            {"id": "mesmo_plano_de_manejo", "texto": c["mesmo_plano_de_manejo"], "status": "pendente", "detalhe": ""},
            {
                "id": "vizinha_ou_proxima",
                "texto": c["vizinha_ou_proxima"],
                "status": "ok",
                "detalhe": "dentro do imóvel",
            },
            {"id": "ligada_a_producao", "texto": c["ligada_a_producao"], "status": "pendente", "detalhe": ""},
        ],
    }


def bloco_ficha(linha: dict, r: dict | None = None) -> dict:
    """O que a ficha mostra: meta FLAG e crédito/compensação em blocos separados (sem total), requisitos e
    Requirement 7, com a versão da regra."""
    r = r or regra()
    calc = por_imovel(linha, r=r)
    return {
        "regra": calc["flag_regra_versao"],
        "padrao": r["padrao"],
        "vigencia_inicio": r["vigencia_inicio"],
        "meta_flag": {
            "conta_na_meta": True,
            "silvipastoril_ha": calc["flag_plano_silvipastoril_ha"],
            "silvipastoril_potencial_ha": calc["flag_silvipastoril_ha"],
            "silvipastoril_degradado_ha": calc["flag_silvipastoril_degradado_ha"],
            "cacau_ha": calc["flag_plano_cacau_ha"],
            "cacau_potencial_ha": calc["flag_cacau_ha"],
            "cacau_viavel": calc["flag_cacau_viavel"],
            "tco2_ano": calc["flag_tco2_ano"],
            "tco2_ano_min": calc["flag_tco2_ano_min"],
            "tco2_ano_max": calc["flag_tco2_ano_max"],
            "faixa_provisoria": bool(r["remocao_tco2_ha_ano"]["silvipastoril"].get("provisorio")),
        },
        "credito_ou_compensacao": {
            "conta_na_meta": False,
            "destino": "crédito Verra (desenvolvedor) ou compensação voluntária",
            "regeneracao_alem_rl_ha": calc["credito_alem_rl_ha"],
            "regeneracao_tco2_ano": calc["credito_tco2_ano"],
            "reserva_legal_ha": calc["rl_restauracao_ha"],
            "app_ha": calc["app_restauracao_ha"],
            "capoeira_ha": calc["capoeira_ha"],
        },
        "nao_somar": "As toneladas da meta FLAG e as do crédito ou compensação vêm de áreas diferentes e não se somam.",
        "requisitos": requisitos(linha, calc, r),
        "requirement_7": requirement_7(linha, r),
    }


# --- por município (saida/<UF>/flag_<mun>.csv) -------------------------------------------------------------------


def _ha_pixel(lat, res: float) -> object:
    import numpy as np

    m = res * 111320.0
    return m * m * np.cos(np.radians(lat)) / 1e4


def pasto_baixo_vigor(pasta: Path, cod: int, vigor_raster: str | Path, r: dict | None = None) -> dict[str, float]:
    """Hectares de pasto de baixo vigor por imóvel, pela soma por janela do motor (zonal_janela) sobre o raster de
    condição de vigor do MapBiomas. Vazio se faltar a geometria."""
    import geopandas as gpd
    import rasterio

    from raiz.funil.novo import zonal

    r = r or regra()
    geo = pasta / f"geo_{cod}.parquet"
    if not geo.exists():
        return {}
    g = gpd.read_parquet(geo).to_crs(4326).reset_index(drop=True)
    with rasterio.open(vigor_raster) as ras:
        d = zonal(ras, g, ("classes",), include_cols=["cod_imovel"])
        res = abs(ras.res[0])
    hp = _ha_pixel(g.geometry.centroid.y.values, res)
    out = {}
    for i, row in d.reset_index(drop=True).iterrows():
        n = sum((row.get(f"c{k}", 0) or row.get(f"band_1_c{k}", 0) or 0) for k in r["pasto_vigor_baixo"])
        out[str(row["cod_imovel"])] = float(n * hp[i])
    return out


def calcular_municipio(pasta: str | Path, cod: int, vigor_raster: str | Path | None = None):
    """flag_<mun>.csv a partir das saídas do motor do município (todas lidas pelo nome; complementos opcionais)."""
    import pandas as pd

    from raiz.privacidade import remover_colunas_pessoais

    pasta = Path(pasta)
    im, _ = remover_colunas_pessoais(pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False))
    for tipo in ("mapbiomas", "direto"):
        f = pasta / f"{tipo}_{cod}.csv"
        if f.exists():
            extra = pd.read_csv(f, low_memory=False)
            novas = [c for c in extra.columns if c == "cod_imovel" or c not in im.columns]
            im = im.merge(extra[novas], on="cod_imovel", how="left")
    vigor = pasto_baixo_vigor(pasta, cod, vigor_raster) if vigor_raster and Path(vigor_raster).exists() else {}
    linhas = []
    for linha in im.to_dict("records"):
        calc = por_imovel(linha, vigor.get(str(linha["cod_imovel"])))
        linhas.append({"cod_imovel": linha["cod_imovel"], **calc})
    return pd.DataFrame(linhas)


def versao_do_arquivo(f: Path) -> str | None:
    import pandas as pd

    if not f.exists():
        return None
    v = pd.read_csv(f, usecols=lambda c: c == "flag_regra_versao", nrows=1)
    return str(v.flag_regra_versao.iloc[0]) if len(v) and "flag_regra_versao" in v else None


def vigor_do_estado(uf: str, cache_motor: Path) -> Path | None:
    fs = sorted((cache_motor / "mapbiomas" / uf.upper()).glob(f"{uf.upper()}_pasto_vigor_*.tif"))
    return fs[-1] if fs else None


def recalcular(saida: str | Path, ufs: list[str] | None = None, cache_motor: Path | None = None) -> dict:
    """Refaz flag_<mun>.csv onde falta ou foi calculado com outra versão da regra (o padrão mudou). A carga contínua
    leva a versão nova ao banco na volta seguinte."""
    from raiz.carga import municipios_na_pasta

    saida = Path(saida)
    atual = versao()
    out = {"refeitos": [], "em_dia": 0}
    for uf in ufs or sorted(p.name for p in saida.iterdir() if p.is_dir() and len(p.name) == 2):
        pasta = saida / uf
        vig = vigor_do_estado(uf, cache_motor) if cache_motor else None
        for cod in municipios_na_pasta(pasta):
            f = pasta / f"flag_{cod}.csv"
            if versao_do_arquivo(f) == atual:
                out["em_dia"] += 1
                continue
            t = calcular_municipio(pasta, cod, vig)
            tmp = f.with_suffix(".tmp")
            t.to_csv(tmp, index=False)
            tmp.replace(f)
            out["refeitos"].append(f"{uf}/{cod}")
    return out
