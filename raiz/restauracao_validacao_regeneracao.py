"""Controle externo de biomassa aérea com exclusão de municípios inteiros.

Uma cronossequência não mede o crescimento anual de uma mesma fazenda. O alvo
é Mg de biomassa aérea por hectare, antes de baseline, vazamento ou reserva.
Coordenadas servem apenas ao vínculo com a malha municipal, nunca ao ajuste.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

FAIXAS = [(1, 3), (4, 5), (6, 10), (11, 15), (16, 30), (31, 60), (61, 120)]
COLUNAS = ["plot_id", "cod_ibge", "forest_age_years", "biomass_total_Mg_ha"]


def versao() -> str:
    return "regeneracao-lomo-2026a+" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def vincular_municipios(parcelas: pd.DataFrame, municipios) -> pd.DataFrame:
    """Junção espacial estrita: nenhum código é deduzido do nome da parcela."""
    import geopandas as gpd

    if municipios.crs is None:
        raise ValueError("malha municipal sem CRS")
    p = parcelas.drop(columns=["responsible"], errors="ignore").copy()
    if p.plot_id.duplicated().any():
        raise ValueError("parcela duplicada")
    pontos = gpd.GeoDataFrame(p, geometry=gpd.points_from_xy(p.longitude, p.latitude), crs=4326)
    malha = municipios[["CD_MUN", "geometry"]].rename(columns={"CD_MUN": "cod_ibge"}).to_crs(4326)
    j = gpd.sjoin(pontos, malha, how="left", predicate="intersects")
    if j.cod_ibge.isna().any() or j.plot_id.duplicated().any():
        raise ValueError("parcela fora da malha ou com município ambíguo; conferir coordenadas")
    return pd.DataFrame(j.drop(columns=["geometry", "index_right"]))


def _curva(idade, parametros):
    a, b = parametros
    return a * idade / (b + idade)


def _ajustar(treino: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    x, y = treino.forest_age_years.to_numpy(), treino.biomass_total_Mg_ha.to_numpy()
    # Forma e limites fixados antes da avaliação; nenhum ajuste usa o holdout.
    ajuste = least_squares(lambda p: _curva(x, p) - y, [200, 20], bounds=([0, 0.1], [1000, 500]))
    if not ajuste.success:
        raise RuntimeError("ajuste da curva não convergiu")
    return ajuste.x, y - _curva(x, ajuste.x)


def validar_municipios(parcelas: pd.DataFrame, *, fonte_sha256: str) -> dict:
    """LOMO: ajuste e quantis residuais usam só municípios do treinamento."""
    if len(fonte_sha256) != 64 or any(c not in "0123456789abcdef" for c in fonte_sha256):
        raise ValueError("fonte_sha256 inválido")
    t = parcelas[COLUNAS].copy().sort_values(["cod_ibge", "plot_id"]).reset_index(drop=True)
    if t.isna().any().any() or t.plot_id.duplicated().any() or t.cod_ibge.nunique() < 3:
        raise ValueError("exige parcelas únicas, dados completos e pelo menos três municípios")
    valores = t[["forest_age_years", "biomass_total_Mg_ha"]].to_numpy(dtype=float)
    if not np.isfinite(valores).all() or (valores < 0).any() or (t.forest_age_years < 1).any():
        raise ValueError("idade e biomassa devem ser finitas, não negativas e idade >= 1")
    registros = []
    for municipio, fora in t.groupby("cod_ibge", sort=True):
        treino = t[t.cod_ibge != municipio]
        parametros, residuos = _ajustar(treino)
        hash_treino = hashlib.sha256(treino.to_csv(index=False, float_format="%.12g").encode()).hexdigest()
        qs = np.quantile(residuos, [0.1, 0.5, 0.9], method="linear")
        for _, li in fora.iterrows():
            curva = float(_curva(li.forest_age_years, parametros))
            p10, p50, p90 = np.maximum(0.0, curva + qs).tolist()
            observado = float(li.biomass_total_Mg_ha)
            registros.append(
                {
                    "parcela_id": li.plot_id,
                    "municipio_excluido": str(municipio),
                    "idade_anos": float(li.forest_age_years),
                    "observado_Mg_ha": observado,
                    "p10": p10,
                    "p50": p50,
                    "p90": p90,
                    "curva_sem_correcao_residual_Mg_ha": curva,
                    "erro_Mg_ha": p50 - observado,
                    "referencia_constante_treino_Mg_ha": float(treino.biomass_total_Mg_ha.mean()),
                    "treino_sha256": hash_treino,
                    "treino_municipios": sorted(treino.cod_ibge.astype(str).unique()),
                    "parametros": parametros.tolist(),
                    "modelo_versao": versao(),
                    "fonte_sha256": fonte_sha256,
                }
            )
    pred = pd.DataFrame(registros)
    metricas = []
    for minimo, maximo in FAIXAS:
        g = pred[pred.idade_anos.between(minimo, maximo)]
        if g.empty:
            metricas.append({"idade_min": minimo, "idade_max": maximo, "n": 0, "mae_Mg_ha": None})
            continue
        metricas.append(
            {
                "idade_min": minimo,
                "idade_max": maximo,
                "n": len(g),
                "municipios": g.municipio_excluido.nunique(),
                "vies_Mg_ha": float(g.erro_Mg_ha.mean()),
                "mae_Mg_ha": float(g.erro_Mg_ha.abs().mean()),
                "rmse_Mg_ha": float(np.sqrt(np.mean(g.erro_Mg_ha**2))),
                "mae_constante_Mg_ha": float((g.referencia_constante_treino_Mg_ha - g.observado_Mg_ha).abs().mean()),
                "cobertura_p10_p90": float(g.observado_Mg_ha.between(g.p10, g.p90).mean()),
            }
        )
    return {
        "modelo_versao": versao(),
        "fonte_sha256": fonte_sha256,
        "alvo": "biomassa_aerea_Mg_ha",
        "n_parcelas": len(t),
        "n_municipios": t.cod_ibge.nunique(),
        "tipo": "validacao_externa_leave_one_municipality_out",
        "metricas_por_idade": metricas,
        "previsoes": registros,
        "substitui_credito_liquido": False,
        "limites": [
            "Cronossequência regional, não inventário de fazendas Raíz.",
            "Intervalos residuais avaliados fora do município; cobertura empírica é publicada.",
            "Não inclui raízes, solo, serapilheira, baseline, vazamento ou buffer.",
        ],
    }


def gravar(relatorio: dict, pasta: Path) -> Path:
    """Arquivo endereçado pelo conteúdo; comparações anteriores são preservadas."""
    texto = json.dumps(relatorio, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"regeneracao_{hashlib.sha256(texto.encode()).hexdigest()}.json"
    try:
        with arquivo.open("x", encoding="utf-8") as f:
            f.write(texto)
    except FileExistsError:
        if arquivo.read_text(encoding="utf-8") != texto:
            raise ValueError("relatório existente alterado") from None
    return arquivo
