import io
import json
from unittest.mock import Mock

import h3
import pytest
import shapely
from shapely.geometry import box

from raiz.potencial_publico import Entradas, agregar, detectar_sobreposicoes, ler_privado


def entrada(n=6):
    e = Entradas()
    e.ufs.add("PA")
    lat, lon = h3.cell_to_latlng(h3.latlng_to_cell(-5, -50, 5))
    for i in range(n):
        cod = f"PA-1500000-{i:032X}"
        e.areas[cod] = 0.5 + i / 10
        e.geometrias[cod] = box(lon + i * 0.004, lat, lon + i * 0.004 + 0.001, lat + 0.001)
    return e


def test_celula_parcial_conta_car_unico_e_conserva_massa_sem_identidades():
    e = entrada()
    meta, colecoes, _, auditoria = agregar(e)
    fs = colecoes["PA"]["features"]
    assert len(fs) == 1
    assert fs[0]["properties"] == {
        "h3": h3.latlng_to_cell(
            *reversed(shapely.get_coordinates(e.geometrias[next(iter(e.areas))].representative_point())[0]), 5
        ),
        "fazendas": 6,
        "potencial_ha": 4.5,
    }
    assert meta["contagens"]["incluidas"] == 6
    assert auditoria["ha_publicado"] + auditoria["ha_suprimido"] == pytest.approx(auditoria["ha_sem_sobreposicao"])
    for cod in e.areas:
        assert cod not in json.dumps(colecoes)
    assert "ha_suprimido" not in json.dumps(colecoes)


def test_sobreposicao_usa_todos_os_imoveis_inclusive_sem_medida_e_encostar_nao_conta():
    a, b, c = box(0, 0, 1, 1), box(1, 0, 2, 1), box(0.5, 0.5, 1.5, 1.5)
    assert detectar_sobreposicoes([a, b]).tolist() == [False, False]
    assert detectar_sobreposicoes([a, b, c]).tolist() == [True, True, True]
    e = entrada(7)
    cods = list(e.areas)
    e.geometrias[cods[-1]] = e.geometrias[cods[-2]]
    e.areas[cods[-1]] = None
    meta, cs, sobrepostos, auditoria = agregar(e)
    assert len(sobrepostos) == 2
    assert meta["contagens"]["incluidas"] == 5
    assert meta["contagens"]["sem_medida"] == 1
    assert cs["PA"]["features"][0]["properties"]["potencial_ha"] == 3.5
    assert auditoria["ha_publicado"] == pytest.approx(3.5)


def test_menos_de_cinco_positivos_e_ausencia_nao_viram_zero_nem_revelam_subtotal():
    e = entrada(6)
    cods = list(e.areas)
    e.areas[cods[0]] = None
    e.areas[cods[1]] = 0
    _, cs, _, auditoria = agregar(e)
    assert cs["PA"]["features"][0]["properties"]["potencial_ha"] is None
    assert auditoria["ha_publicado"] == 0
    assert auditoria["ha_suprimido"] > 0
    _, cs, _, _ = agregar(entrada(4))
    assert cs["PA"]["features"] == []


def test_fronteira_publica_mesma_celula_sem_subtotal_de_uf():
    e = entrada(6)
    e.ufs.add("TO")
    cod = list(e.areas)[-1]
    outro = cod.replace("PA-", "TO-")
    e.areas[outro], e.geometrias[outro] = e.areas.pop(cod), e.geometrias.pop(cod)
    _, cs, _, _ = agregar(e)
    assert cs["PA"]["features"] == cs["TO"]["features"]
    assert cs["TO"]["features"][0]["properties"]["fazendas"] == 6


def test_csv_duplicado_divergente_nao_soma_nem_reabre_medida():
    e = Entradas()
    cod = "PA-1500000-" + "A" * 32

    def csv(valor):
        return f"cod_imovel,carbono_ha,nome_proprietario\n{cod},{valor},NUNCA-PUBLICAR\n".encode()

    e.csv(csv(1), "PA")
    e.csv(csv(1), "PA")
    assert len(e.areas) == 1 and e.areas[cod] == 1
    e.csv(csv(2), "PA")
    e.csv(csv(1), "PA")
    assert e.areas[cod] is None


def test_geometria_duplicada_divergente_nao_libera_area():
    import geopandas as gpd

    e = entrada()
    cod = next(iter(e.areas))

    def parquet(g):
        f = io.BytesIO()
        gpd.GeoDataFrame({"cod_imovel": [cod], "geometry": [g], "medida_paga": [99]}, crs=4326).to_parquet(f)
        f.seek(0)
        return f

    e.parquet(parquet(e.geometrias[cod]))
    assert e.areas[cod] == 0.5
    e.parquet(parquet(box(-51, -6, -50, -5)))
    assert e.areas[cod] is None


def test_download_privado_recusa_falta_de_integridade_antes_de_ler_tabelas():
    arm = Mock()
    arm._assets.return_value = [
        {"name": "raiz_PA.tar.gz", "size": 3, "id": 1, "digest": "sha256:incorreto"},
        {"name": "raiz_geo_PA.tar.gz", "size": 3, "id": 2},
    ]
    arm._baixar_ativo.return_value = b"abc"
    with pytest.raises(ValueError, match="SHA-256 divergente"):
        ler_privado(arm)
    assert arm._exigir_privado.call_count >= 2
    arm._exigir_privado.side_effect = PermissionError("aberto")
    with pytest.raises(PermissionError):
        ler_privado(arm)


def test_novo_municipio_sem_coluna_de_area_permanece_desconhecido():
    e = Entradas()
    car = "PA-1500000-" + "A" * 32
    e.csv(f"cod_imovel,ha\n{car},50\n".encode(), "PA")
    assert e.areas[car] is None


def test_prefixo_car_diferente_do_pacote_nao_duplica_ou_exclui_contribuicao():
    e = entrada(6)
    e.ufs = {"PI"}
    for car in e.areas:
        e.ufs_por_car[car] = {"PI"}
    car = next(iter(e.areas))
    e.csv(f"cod_imovel,carbono_ha\n{car},0.5\n".encode(), "PI")
    _, colecoes, _, _ = agregar(e)
    assert colecoes["PI"]["features"][0]["properties"]["potencial_ha"] == 4.5
    assert colecoes["PI"]["features"][0]["properties"]["fazendas"] == 6


def test_publicacao_concorrente_repete_apenas_par_sem_duplicar_medidas(monkeypatch):
    import hashlib

    from raiz import potencial_publico as p

    dados = b"pacote-ficticio"
    digest = "sha256:" + hashlib.sha256(dados).hexdigest()
    ativos = [
        {"name": n, "size": len(dados), "id": i, "digest": digest}
        for i, n in enumerate(["raiz_PA.tar.gz", "raiz_geo_PA.tar.gz"])
    ]
    arm = Mock()
    arm._assets.return_value = ativos
    arm._baixar_ativo.side_effect = [RuntimeError("falha HTTP 404 no arquivo privado"), dados, dados]
    monkeypatch.setattr(p.time, "sleep", lambda _: None)

    def ler(self, dados, uf, *, geometria):
        if not geometria:
            self.csv(("cod_imovel,carbono_ha\nPA-1500000-" + "A" * 32 + ",2\n").encode(), uf)

    monkeypatch.setattr(p.Entradas, "pacote", ler)
    monkeypatch.setattr(p.Entradas, "conferir_par", lambda _: None)
    result = ler_privado(arm)
    assert len(result.areas) == 1
    assert list(result.areas.values()) == [2]
    assert arm._baixar_ativo.call_count == 3


def test_proveniencia_recusa_par_estavel_mas_de_publicacoes_diferentes():
    e = Entradas()
    e.geometrias_esperadas = {"geo_1505536.parquet": "sha-novo"}
    e.geometrias_lidas = {"geo_1505536.parquet": "sha-antigo"}
    with pytest.raises(RuntimeError, match="proveniência"):
        e.conferir_par()
    e.geometrias_lidas = dict(e.geometrias_esperadas)
    e.conferir_par()


def test_area_muito_pequena_nao_arredonda_para_zero():
    e = entrada(5)
    for car in e.areas:
        e.areas[car] = 0.000001
    _, cs, _, _ = agregar(e)
    assert cs["PA"]["features"][0]["properties"]["potencial_ha"] == pytest.approx(0.000005)
