"""Cache estadual, contrato de colunas, divisas e reserva sem chamadas à internet."""

import geopandas as gpd
import pytest
from shapely.geometry import box

from raiz.coleta import car_nacional as C


@pytest.fixture
def fonte(tmp_path):
    cache = tmp_path / "cache"
    pasta = cache / "car_nacional"
    pasta.mkdir(parents=True)
    gpd.GeoDataFrame(
        {"code_muni": [2100001, 2100002], "name_muni": ["Oeste", "Leste"], "abbrev_state": ["MA", "MA"]},
        geometry=[box(-45, -4, -44, -3), box(-44, -4, -43, -3)],
        crs=4326,
    ).to_parquet(pasta / C.GEOBR_ARQUIVO)
    cods = ["MA-2100001-A", "MA-2100001-A", "MA-2100001-B", "MA-2100002-C", "TO-1700001-D"]
    g = gpd.GeoDataFrame(
        {
            "cod_imovel": cods,
            "mod_fiscal": [1, 2, 0.001, 3, 4],
            "num_area": 10,
            "ind_status": "AT",
            "ind_tipo": "IRU",
            "des_condic": "Em análise",
            "municipio": "declarado",
            "cod_estado": ["MA"] * 4 + ["TO"],
            "dat_criaca": "2020-01-01",
            "dat_atuali": ["31/12/2025", "01/07/2026", None, None, None],
        },
        geometry=[box(-44.9, -3.9, -44.8, -3.8)] * 2
        + [box(-44.1, -3.8, -43.9, -3.7), box(-43.5, -3.5, -43.49, -3.49), box(-44.8, -3.5, -44.7, -3.4)],
        crs=4326,
    )
    arquivo = tmp_path / "fonte.parquet"
    g.to_parquet(arquivo, write_covering_bbox=True)
    return cache, arquivo


def test_uma_leitura_estadual_deduplica_e_mapeia_sem_cortar_fazenda(fonte):
    cache, fonte = fonte
    arquivo = C.estado("MA", cache, fonte=str(fonte))
    fonte.unlink()  # as próximas leituras só usam o cache estadual íntegro
    assert C.estado("MA", cache, fonte=str(fonte)) == arquivo
    g = C.municipio("MA", 2100001, cache)
    assert list(g.cod_imovel) == ["MA-2100001-A", "MA-2100001-B"]
    assert g.m_fiscal.tolist() == [2, 0.001]  # duplicata mais atual; não descarta pequena
    assert g.id.isna().all() and g.car_base.eq("2026-07").all()
    assert g.crs.to_epsg() == 4326 and g.cod_municipio_ibge.eq(2100001).all()
    assert g.loc[g.cod_imovel.eq("MA-2100001-B"), "geometry"].iloc[0].bounds[2] == -43.9
    leste = C.municipio("MA", 2100002, cache)
    assert not set(g.cod_imovel) & set(leste.cod_imovel)
    assert set(leste.cod_imovel) == {"MA-2100002-C"}


def test_falha_nao_deixa_cache_parcial_e_permite_retomar(fonte, monkeypatch):
    cache, origem = fonte
    original = gpd.GeoDataFrame.to_parquet

    def falhar(self, destino, **kwargs):
        destino.write_bytes(b"interrompido")
        raise OSError("disco indisponível")

    monkeypatch.setattr(gpd.GeoDataFrame, "to_parquet", falhar)
    with pytest.raises(OSError):
        C.estado("MA", cache, fonte=str(origem))
    assert not C.arquivo_estado("MA", cache).exists()
    assert not list(C.arquivo_estado("MA", cache).parent.glob("*.tmp"))
    monkeypatch.setattr(gpd.GeoDataFrame, "to_parquet", original)
    assert C.estado("MA", cache, fonte=str(origem)).exists()


def test_wfs_so_como_reserva(monkeypatch, tmp_path):
    vazio = gpd.GeoDataFrame(geometry=[], crs=4674)
    chamadas = []
    monkeypatch.setattr(C, "preparar", lambda *a: True)
    monkeypatch.setattr(C, "municipio", lambda *a: vazio)

    def reserva(*a):
        chamadas.append(a)
        return vazio.copy()

    assert C.ler("MA", 2100001, reserva, tmp_path).empty
    assert chamadas == []  # município vazio na base não dispara outro download
    monkeypatch.setattr(C, "preparar", lambda *a: False)
    assert C.ler("MA", 2100001, reserva, tmp_path).empty
    assert chamadas == [("MA", 2100001)]


def test_espelho_implicito_nao_sobrepoe_base_nacional(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from raiz.funil import ponte as P

    monkeypatch.setattr(P, "espelho_padrao", lambda: tmp_path)
    monkeypatch.setattr(P, "ler_local", lambda *a: pytest.fail("CAR legado não deve substituir a base"))
    motor = SimpleNamespace(car_mun=lambda *a: "nacional", sigef=lambda *a: None)
    with P.ponte(motor, "MA", 2100001):
        assert motor.car_mun("MA", 2100001) == "nacional"
