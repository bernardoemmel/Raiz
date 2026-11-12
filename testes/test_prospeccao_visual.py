"""O mapa privado preserva furos, limita a hachura ao CAR e não propaga atributos pessoais."""

import json

import pytest
from fastapi import HTTPException
from shapely.geometry import Polygon, box, mapping, shape

from raiz import front_api
from raiz import prospeccao_visual as visual


def test_mascara_preserva_furo_e_hachura_nunca_sai_do_car():
    imovel = Polygon([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)], holes=[[(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]])
    dado = visual.montar(
        mapping(imovel),
        [
            {"camada": "pode_voltar", "geometria": mapping(box(-1, -1, 3, 3)), "proprietario": "NÃO PUBLICAR"},
            {"camada": "desconhecida", "geometria": mapping(imovel)},
        ],
        "2026-11-12",
    )
    recorte = shape(dado["camadas"]["features"][0]["geometry"])
    mascara = shape(dado["mascara"]["features"][0]["geometry"])
    assert recorte.difference(imovel).is_empty
    assert not recorte.intersects(box(1.1, 1.1, 1.9, 1.9))
    assert mascara.contains(box(1.1, 1.1, 1.9, 1.9))
    assert mascara.intersection(imovel).area == 0
    assert len(dado["camadas"]["features"]) == 1
    assert dado["camadas"]["features"][0]["properties"] == {"camada": "pode_voltar"}
    assert dado["data_referencia"] is None and dado["data_corte"] == "2026-11-12"
    assert "NÃO PUBLICAR" not in json.dumps(dado)


def test_geometria_ausente_e_area_sem_desenho_tem_aviso():
    vazio = visual.montar(None, [])
    assert not vazio["imovel"]["features"] and vazio["avisos"]
    sem_camadas = visual.montar(mapping(box(-50, -10, -49, -9)), [])
    assert not sem_camadas["camadas"]["features"]
    assert "hectares não permite" in sem_camadas["avisos"][0]


def test_sentinel_sem_cena_nao_vira_404(monkeypatch):
    def ausente(*args):
        raise HTTPException(404, "sem cena")

    monkeypatch.setattr(front_api, "_imagem", ausente)
    assert visual.satelite_disponivel(None, "car")["disponivel"] is False


def test_metadados_sentinel_nao_expoem_caminho_ou_dados_arbitrarios(monkeypatch):
    meta = {
        "caixa": [-50, -10, -49, -9],
        "data_cena": "2026-10-10",
        "metodo": "cena",
        "satelite": "Sentinel-2",
        "credito": "Contains modified Copernicus Sentinel data 2026",
        "largura": 1000,
        "altura": 800,
        "arquivo": "/pasta/privada/hoje.webp",
        "nome": "NÃO PUBLICAR",
    }
    monkeypatch.setattr(front_api, "_imagem", lambda *a: (meta, meta["arquivo"]))
    dado = visual.satelite_disponivel(None, "car")
    assert dado["disponivel"] is True
    assert set(dado) == {"disponivel", "caixa", "data_cena", "metodo", "satelite", "credito", "largura", "altura"}


def test_erro_operacional_nao_e_tratado_como_ausencia_de_cena(monkeypatch):
    def falhou(*args):
        raise HTTPException(503, "indisponível")

    monkeypatch.setattr(front_api, "_imagem", falhou)
    with pytest.raises(HTTPException) as exc:
        visual.satelite_disponivel(None, "car")
    assert exc.value.status_code == 503


@pytest.mark.banco
def test_consulta_carrega_geometrias_do_postgis_e_corte_da_carga(banco_url):
    import uuid

    from sqlalchemy import create_engine, text

    from raiz.busca import normalizar_codigo

    engine = create_engine(banco_url)
    car = "PA-1504950-" + uuid.uuid4().hex.upper()
    with engine.begin() as con:
        rodada = con.execute(
            text("""insert into funil.rodada
                (tipo, uf, cod_municipio, origem, arquivos, hash_entradas, motor_versao, regras_versao, data_corte)
                values ('municipio','PA',1504950,'teste','{}',:hash,'teste','teste','2026-11-12') returning id"""),
            {"hash": str(uuid.uuid4())},
        ).scalar_one()
        con.execute(
            text("""insert into funil.imovel (cod_imovel, uf, cod_municipio_ibge, geom)
                values (:car,'PA',1504950,ST_Multi(ST_MakeEnvelope(-50,-10,-49,-9,4674)))"""),
            {"car": car},
        )
        con.execute(
            text("""insert into funil.vigente (cod_imovel,rodada_id,cod_municipio_ibge,uf,cod_busca)
                values (:car,:rodada,1504950,'PA',:busca)"""),
            {"car": car, "rodada": rodada, "busca": normalizar_codigo(car)},
        )
        con.execute(
            text("""insert into geo.camada_imovel (cod_imovel,cod_ibge,camada,geom,rodada_id)
                values (:car,1504950,'pode_voltar',ST_MakeEnvelope(-51,-11,-49.5,-9.5,4674),:rodada)"""),
            {"car": car, "rodada": rodada},
        )
    dado = visual.consultar(engine, car)
    assert dado["data_corte"] == "2026-11-12"
    assert dado["camadas"]["features"][0]["properties"] == {"camada": "pode_voltar"}
    assert shape(dado["camadas"]["features"][0]["geometry"]).bounds == pytest.approx((-50, -10, -49.5, -9.5))
    assert not visual.consultar(engine, "PA-1504950-" + "F" * 32)["imovel"]["features"]
    engine.dispose()


def test_metodo_e_periodo_da_mediana_sao_preservados(monkeypatch):
    meta = {
        "caixa": [-50, -10, -49, -9],
        "data_cena": "2026-09-06 a 2026-10-23",
        "metodo": "mediana",
        "satelite": "Sentinel-2",
        "credito": "Copernicus 2026",
        "largura": 1024,
        "altura": 938,
    }
    monkeypatch.setattr(front_api, "_imagem", lambda *a: (meta, None))
    dado = visual.satelite_disponivel(None, "car")
    assert dado["metodo"] == "mediana"
    assert dado["data_cena"] == "2026-09-06 a 2026-10-23"


def test_leitor_por_blocos_e_opcional_e_restrito_ao_visual(monkeypatch):
    chamadas = []
    monkeypatch.setattr(front_api, "_imagem", lambda *a, **kw: chamadas.append(kw))
    monkeypatch.delenv("RAIZ_SATELITE_LEITOR_HTTP", raising=False)
    visual.imagem(None, "car")
    monkeypatch.setenv("RAIZ_SATELITE_LEITOR_HTTP", "blocos")
    visual.imagem(None, "car")
    assert chamadas == [{}, {"ler": visual._janela_blocos}]
