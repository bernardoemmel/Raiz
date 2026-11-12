"""Cruzamento: imóvel pequeno nunca sai, borda fica com gravidade baixa, focos de uma passagem viram um alerta,
projeto separa área de carbono do entorno e ignora o que está fora."""

from __future__ import annotations

import json

from shapely.geometry import Point

from raiz.vigilancia import cruzamento, projetos
from raiz.vigilancia.fontes import firms
from raiz.vigilancia.testes.conftest import COD_A, COD_B, HOJE, em_graus, ocorrencia, ocorrencias, quadrado_m


def _alertas(oc, poligonos, regras, areas=None):
    pares = [cruzamento.cruzar_imoveis(oc, poligonos)]
    if areas is not None:
        pares.append(cruzamento.cruzar_projetos(oc, areas))
    import pandas as pd

    pares = pd.concat([p for p in pares if len(p)], ignore_index=True)
    return cruzamento.montar_alertas(oc, pares, regras, HOJE)


def test_derrubada_pega_imovel_grande_e_pequeno(poligonos, regras):
    # 200 m x 1200 m que cobre parte do A e o B inteiro
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(900, -100, 300), HOJE))
    a = _alertas(oc, poligonos, regras)
    assert set(a["alvo_id"]) == {COD_A, COD_B}
    b = a[a.alvo_id == COD_B].iloc[0]
    assert b["fracao_alvo"] > 0.99  # o B (0,5 ha) foi todo atingido: nunca sai por ser pequeno
    assert b["gravidade"] == "alta" and not b["borda"]
    assert b["tipo"] == "desmatamento" and b["estrato"] == "deter_desmatamento"
    assert abs(b["confianca"] - 0.85) < 1e-9
    assert b["regra_versao"] == regras.versao


def test_id_estavel_e_sem_duplicar(poligonos, regras):
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 200), HOJE))
    a1 = _alertas(oc, poligonos, regras)
    a2 = _alertas(oc, poligonos, regras)
    assert list(a1["alerta_id"]) == list(a2["alerta_id"])
    assert a1.iloc[0]["alerta_id"] == cruzamento.alerta_id("deter", "d1", "imovel", COD_A)


def test_borda_fica_mas_com_gravidade_baixa(poligonos, regras):
    # mancha grande que só encosta meio metro no imóvel A (0,05 ha: diferença de traçado)
    oc = ocorrencias(ocorrencia("deter", "d2", "desmatamento_cr", quadrado_m(-999.5, 0, 1000), HOJE))
    a = _alertas(oc, poligonos, regras)
    assert len(a) == 1
    r = a.iloc[0]
    assert r["borda"] and r["gravidade"] == "baixa" and r["area_sobreposta_ha"] < 0.1


def test_focos_da_mesma_passagem_viram_um_alerta(poligonos, regras):
    lon, lat = em_graus(Point(quadrado_m(300, 300, 1).bounds[:2])).coords[0]
    linhas = []
    for k, (dx, conf) in enumerate([(0, "foco_alta"), (0.004, "foco_nominal")]):
        g, ha = firms.pixel(lon + dx, lat, 0.38, 0.36)
        linhas.append(
            {
                "fonte": "firms",
                "chave": f"N20|{HOJE}|0415|{lat:.5f}|{lon + dx:.5f}",
                "classe": conf,
                "data_evento": HOJE,
                "publicado_em": HOJE,
                "area_ha": ha,
                "uf": None,
                "cod_municipio_ibge": None,
                "link": None,
                "atributos": {"satelite": "N20", "hora_utc": "0415", "frp_mw": 3.0 + k, "lon": lon, "lat": lat},
                "car_fonte": None,
                "geometry": g,
            }
        )
    oc = ocorrencias(*linhas)
    a = _alertas(oc, poligonos, regras)
    assert len(a) == 1
    r = a.iloc[0]
    attrs = json.loads(r["atributos"])
    assert attrs["focos"] == 2 and attrs["frp_max_mw"] == 4.0
    assert r["classe"] == "foco_alta" and r["estrato"] == "firms_alta" and r["tipo"] == "fogo"
    assert r["chave"] == f"N20|{HOJE}|0415"
    assert r["gravidade"] in ("media", "alta")


def test_embargo_so_ponto_nao_e_borda(poligonos, regras):
    p = Point(quadrado_m(500, 500, 1).bounds[:2])
    oc = ocorrencias(ocorrencia("ibama_embargo", "123", "embargo_ponto", p, HOJE))
    a = _alertas(oc, poligonos, regras)
    assert len(a) == 1 and not a.iloc[0]["borda"] and a.iloc[0]["gravidade"] == "alta"


def test_projeto_separa_carbono_entorno_e_fora(poligonos, regras, lista_projetos, cfg):
    areas = projetos.areas(lista_projetos[0], cfg)
    oc = ocorrencias(
        ocorrencia("deter", "no_plantio", "desmatamento_cr", quadrado_m(500, 0, 150), HOJE),  # plantio + aceiro
        ocorrencia("firms", "N21|x|1|1|1", "foco_nominal", quadrado_m(610, 0, 50), HOJE),  # só aceiro
        ocorrencia("deter", "fora", "desmatamento_cr", quadrado_m(800, 0, 100), HOJE),  # área excluída
    )
    a = _alertas(oc, poligonos, regras, areas)
    proj = a[a.alvo_tipo == "projeto"].set_index("chave")
    assert "fora" not in proj.index  # área não disponível não é alerta do projeto
    p1 = proj.loc["no_plantio"]
    assert p1["papel"] == "projeto" and p1["gravidade"] == "alta"
    classes = json.loads(p1["classes_ha"])
    assert set(classes) == {"Plantio", "Aceiro"}
    assert abs(p1["area_projeto_ha"] - 1.5) < 0.05  # 100 m x 150 m dentro do plantio
    entorno = proj.loc["N21|x|1"]
    assert entorno["papel"] == "entorno"
    # o imóvel A recebe os três alertas (o cruzamento com o CAR não depende do projeto)
    assert (a[a.alvo_tipo == "imovel"]["alvo_id"] == COD_A).sum() == 3


def test_mapbiomas_com_car_fora_do_release(poligonos, regras):
    longe = quadrado_m(50_000, 50_000, 100)
    oc = ocorrencias(
        ocorrencia("mapbiomas_alerta", "777", "agriculture", longe, HOJE, car_fonte={"MT-5100000-XYZ": 0.8})
    )
    a = _alertas(oc, poligonos, regras)
    assert list(a["alvo_id"]) == ["MT-5100000-XYZ"]
    assert a.iloc[0]["area_sobreposta_ha"] == 0.8 and a.iloc[0]["uf"] == "MT"
