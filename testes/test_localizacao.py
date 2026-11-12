"""Plus Code e link do Organic Maps (raiz/localizacao.py). Os casos do Organic Maps são os da suíte dele
(libs/ge0/ge0_tests/url_generator_tests.cpp); os do Plus Code, os exemplos da especificação aberta."""

import pytest

from raiz import localizacao as L


@pytest.mark.parametrize(
    ("lat", "lon", "esperado"),
    [
        (-90, -180, "AAAAAAAAA"),
        (90, -180, "qqqqqqqqq"),
        (90, 179.999999, "_________"),
        (-90, 179.999999, "VVVVVVVVV"),
        (0.0, 0.0, "wAAAAAAAA"),
        (90.0, 0.0, "6qqqqqqqq"),
        (-0.000001, -0.000001, "P________"),
    ],
)
def test_coordenada_ge0_igual_a_do_organic_maps(lat, lon, esperado):
    assert L._coordenada_ge0(lat, lon) == esperado


def test_link_omaps_com_zoom_e_nome():
    assert L.link_omaps(0, 0, 19, "Name") == "https://omaps.app/8wAAAAAAAA/Name"
    assert L.link_omaps(0, 0, 19) == "https://omaps.app/8wAAAAAAAA"
    assert L.link_omaps(0, 0, 2, "Name") == "https://omaps.app/AwAAAAAAAA/Name"
    assert L.link_omaps(0, 0, 20, "Name") == "https://omaps.app/_wAAAAAAAA/Name"
    # espaço vira "_", reservado vira %XX, acento fica como está (o link continua curto e legível)
    assert L.link_omaps(-2.3, -47.3, 15, "Raíz K7M2(9)").endswith("/Raíz_K7M2%289%29")


def test_arredondamentos_do_organic_maps():
    assert [L._lat_int(x, 2) for x in (-90, -45.1, -45, 0, 44.9, 45, 90)] == [0, 0, 1, 1, 1, 2, 2]
    assert [L._lon_int(x, 3) for x in (-180, -135.1, -135, -90, -45.1, -45, 0, 44.9, 45, 134.9, 135)] == [
        0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 0
    ]  # fmt: skip
    assert [L._lat_int(0, m) for m in (998, 999, 1000, 1001)] == [499, 500, 500, 501]
    assert [L._lon_int(360, m) for m in (997, 998, 999, 1000, 1001)] == [499, 500, 500, 501, 501]


@pytest.mark.parametrize(
    ("lat", "lon", "esperado"),
    [
        (47.365590, 8.524997, "8FVC9G8F+6X"),
        (20.3700625, 2.7821875, "7FG49QCJ+2V"),
        (47.0000625, 8.0000625, "8FVC2222+22"),
    ],
)
def test_plus_code(lat, lon, esperado):
    assert L.plus_code(lat, lon) == esperado


def test_ponto_dentro_do_imovel():
    # um "U": o centro cai fora do polígono, então o ponto vem da superfície
    u = {"type": "Polygon", "coordinates": [[[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3], [0, 0]]]}
    from shapely.geometry import Point, shape

    lon, lat = L.ponto_dentro(u)
    assert shape(u).contains(Point(lon, lat))
    loc = L.localizacao(u, "Raíz K7M2Q9X")
    assert loc["plus_code"] == L.plus_code(lat, lon) and loc["omaps"].endswith("/Raíz_K7M2Q9X")
    assert L.localizacao(None) is None
