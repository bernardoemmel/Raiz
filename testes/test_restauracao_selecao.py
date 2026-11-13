"""Pequenas indivisíveis, limites efetivos e forma conferida após fallback."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from raiz import restauracao_selecao as S
from raiz.pedidos.campos import CamposPedido


def pedido(valor=100, **forma):
    return CamposPedido(meta={"tipo": "creditos", "valor": valor}, forma=forma, cronograma="livre")


def grupos(n=20):
    return pd.DataFrame(
        {
            "grupo_id": [f"g{i:04}" for i in range(n)],
            "quantidade": 10.0,
            "credito_p50": 10.0,
            "area_ha": 1.0,
            "membros": 2,
            "custo_total": np.arange(n) + 100.0,
            "risco_total": 10.0,
            "penalidade_total": 0.0,
            "grupo_lon": np.arange(n) * 0.001 - 50,
            "grupo_lat": -4.0,
            "grupo_raio_km": 0.02,
        }
    )


def test_pequenas_nas_divisas_sem_corte_e_grupo_indivisivel():
    f = pd.DataFrame(
        {
            "cod_imovel": ["PA-a", "TO-b", "PA-c", "PA-sem-local"],
            "lon": [-50.00001, -49.99999, -50.00002, np.nan],
            "lat": [-4.0, -4.0, -4.0, np.nan],
            "pequena": True,
            "local_aproximado": False,
        }
    )
    g = S.agrupar_oferta(f, diametro_km=1)
    assert len(g) == 4 and g.cod_imovel.is_unique
    assert g[g.cod_imovel != "PA-sem-local"].grupo_id.nunique() == 1
    assert g.loc[g.cod_imovel == "PA-sem-local", "agrupamento_pendente"].all()
    assert (g.grupo_raio_km <= 0.5 + 1e-9).all()
    assert S.agrupar_oferta(f.sample(frac=1, random_state=3), diametro_km=1).equals(g)


def test_coordenada_aproximada_nao_inventa_vizinhanca():
    f = pd.DataFrame({"cod_imovel": ["a", "b"], "lon": -50.0, "lat": -4.0, "pequena": True, "local_aproximado": True})
    g = S.agrupar_oferta(f)
    assert g.grupo_id.nunique() == 2 and g.agrupamento_pendente.all()


def test_meta_grande_nunca_cai_para_toda_oferta():
    g = grupos(10000)
    r = S.selecionar_grupos(g, pedido(1e9), "barata", limites=S.LimitesSelecao(16, 64, 1))
    assert r["estado"] == "limite_busca" and not r["fecha_meta"]
    assert r["diagnosticos"]["variaveis_milp"] == 64
    assert r["diagnosticos"]["grupos_examinados"] == 64
    assert not r["diagnosticos"]["otimo_global_comprovado"]
    assert r["diagnosticos"]["expansoes"] == [16, 32]


def test_fallback_respeita_donos_e_distancia_inclusive_reserva(monkeypatch):
    monkeypatch.setattr(S, "milp", lambda **kw: SimpleNamespace(x=None, status=1))
    g = grupos()
    g.loc[10:, "grupo_lon"] = -40
    p = pedido(60, max_donos=8, distancia_max_km=1)
    r = S.selecionar_grupos(g, p, "segura", reserva_meta=20)
    ids = r["titulares"] + r["reservas"]
    assert len(ids) == len(set(ids))
    sel = g[g.grupo_id.isin(ids)]
    assert sel.membros.sum() <= 8
    assert not S._validar_forma(sel, p)
    assert r["diagnosticos"]["restricoes_verificadas"]


def test_area_contigua_exige_evidencia_e_nao_soma_de_pontos():
    r = S.selecionar_grupos(grupos(), pedido(100, area_min_contigua_ha=2), "compacta")
    assert not r["titulares"] and r["estado"] == "evidencia_de_forma_pendente"


def test_reserva_busca_fora_da_primeira_lista():
    g = grupos(50)
    p = pedido(10)
    r = S.selecionar_grupos(g, p, "barata", limites=S.LimitesSelecao(2, 20, 1), reserva_meta=150)
    assert r["fecha_meta"] and r["fecha_reserva"]
    assert r["diagnosticos"]["grupos_examinados"] <= 20
    assert not set(r["titulares"]) & set(r["reservas"])


def test_limites_invalidos_nao_autorizam_milhoes_de_variaveis():
    with pytest.raises(ValueError):
        S.LimitesSelecao(128, 7000000)


def test_compacta_prioriza_vizinhanca_mesmo_sem_distancia_obrigatoria():
    g = grupos(500)
    # As mais baratas isoladas não devem impedir a procura de um conjunto vizinho.
    g.loc[:19, "grupo_lon"] = np.linspace(-70, -35, 20)
    r = S.selecionar_grupos(g, pedido(100), "compacta", limites=S.LimitesSelecao(32, 100, 1))
    assert r["fecha_meta"] and r["fecha_reserva"]
    assert r["diagnosticos"]["diametro_limite_superior_km"] < 10
    assert r["diagnosticos"]["ancoras_espaciais_maximas"] == 32
