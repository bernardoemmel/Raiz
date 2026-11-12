import geopandas as gpd
import pytest
import shapely
from shapely.geometry import box

from raiz.funil.restricoes import limpar, por_imovel, subdividir


def _g(*geoms):
    return gpd.GeoDataFrame(geometry=list(geoms), crs=5880)


def test_prioridade_apaga_sobreposicao():
    camadas = {
        "embargo": _g(box(0, 0, 300, 100)),  # cobre TI e UC
        "uc_uso_sustentavel": _g(box(100, 0, 300, 100)),
        "ti": _g(box(0, 0, 150, 100), box(50, 0, 120, 100)),  # sobreposição dentro da classe
    }
    L = limpar(camadas)
    area = L.dissolve("restricao").area
    assert area["ti"] == pytest.approx(150 * 100)
    assert area["uc_uso_sustentavel"] == pytest.approx(150 * 100)  # perdeu 50 m para a TI
    assert "embargo" not in area  # tudo já estava em classe de prioridade maior
    assert L.area.sum() == pytest.approx(shapely.union_all([g.geometry.iloc[0] for g in camadas.values()]).area)


def test_geometria_invalida_e_classe_desconhecida():
    borboleta = shapely.Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])  # inválida (auto-interseção)
    L = limpar({"ti": _g(borboleta)})
    assert L.is_valid.all() and L.area.sum() == pytest.approx(50)
    with pytest.raises(ValueError, match="sem prioridade"):
        limpar({"quilombo": _g(box(0, 0, 1, 1))})


def test_subdividir_mantem_area():
    circulo = shapely.Point(0, 0).buffer(1000, quad_segs=500)  # ~2000 vértices
    partes = subdividir(circulo, 200)
    assert len(partes) > 4 and all(shapely.get_num_coordinates(p) <= 200 for p in partes)
    assert sum(p.area for p in partes) == pytest.approx(circulo.area, rel=1e-9)


def test_soma_por_imovel_nao_passa_da_area():
    camadas = {"ti": _g(box(0, 0, 100, 100)), "embargo": _g(box(0, 0, 100, 100))}  # mesmo lugar nas duas
    base = gpd.GeoDataFrame(
        {"cod_imovel": ["A", "B"]}, geometry=[box(0, 0, 100, 100), box(500, 500, 600, 600)], crs=5880
    )
    t = por_imovel(base, limpar(camadas))
    assert t.loc["A"].sum() == pytest.approx(1.0) and t.loc["A", "ti_ha"] == pytest.approx(1.0)
    assert t.loc["B"].sum() == 0
