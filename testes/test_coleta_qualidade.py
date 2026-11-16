"""Guardas do espelho: conteúdo degradado não substitui o último retrato aceito."""

import json
from types import SimpleNamespace

import geopandas as gpd
import httpx
import pytest
from shapely.geometry import Polygon, box

from raiz.coleta.espelho import Espelho, registrar_alertas
from raiz.operacao.healthchecks import Healthchecks


def _quadro(n=40):
    return gpd.GeoDataFrame(
        {"chave": [str(i) for i in range(n)], "situacao": ["regular"] * n, "zero": [0] * n},
        geometry=[box(0, 0, 1, 1)] * n,
        crs=4674,
    )


def test_queda_de_contagem_preserva_arquivo_e_resumo(tmp_path):
    esp = Espelho(tmp_path)
    antes = _quadro()
    esp.gravar("camada", "PA", 1, antes, "chave")
    resumo = esp.caminho_resumo("camada", "PA", 1).read_bytes()
    dif = esp.gravar("camada", "PA", 1, antes.iloc[:25], "chave")
    assert dif.travado and not dif.escreveu
    assert dif.alertas == [{"tipo": "queda_contagem", "antes": 40, "depois": 25, "fracao": 0.375}]
    assert len(esp.ler("camada", "PA", 1)) == 40
    assert esp.caminho_resumo("camada", "PA", 1).read_bytes() == resumo


@pytest.mark.parametrize("modo", ["vazia", "removida"])
def test_coluna_perdida_trava_mesmo_poucas_linhas_e_permite_liberar(tmp_path, modo):
    esp = Espelho(tmp_path)
    antes = _quadro(3)
    esp.gravar("camada", "PA", 1, antes, "chave")
    novo = antes.copy()
    if modo == "vazia":
        novo["situacao"] = [None, "", "   "]
    else:
        novo = novo.drop(columns="situacao")
    dif = esp.gravar("camada", "PA", 1, novo, "chave")
    assert dif.travado and not dif.escreveu
    assert dif.alertas == [{"tipo": f"coluna_{modo}", "coluna": "situacao", "antes": 3, "depois": 0}]
    assert esp.ler("camada", "PA", 1).situacao.eq("regular").all()
    assert esp.gravar("camada", "PA", 1, novo, "chave", liberar=True).escreveu


def test_ultimo_registro_pode_sair_sem_excluir_pequenos_por_tamanho(tmp_path):
    esp = Espelho(tmp_path)
    antes = _quadro(1)
    esp.gravar("camada", "PA", 1, antes, "chave")
    dif = esp.gravar("camada", "PA", 1, antes.iloc[:0], "chave")
    assert dif.escreveu and not dif.travado and dif.sumiram == ["0"]
    assert len(dif.alertas) == 1 and dif.alertas[0]["tipo"] == "queda_contagem"
    assert esp.ler("camada", "PA", 1).empty


def test_coluna_volatil_e_nula_desde_origem_nao_geram_alerta(tmp_path):
    esp = Espelho(tmp_path)
    antes = _quadro(3)
    antes["sempre_vazia"] = None
    esp.gravar("camada", "PA", 1, antes, "chave", ("situacao",))
    novo = antes.drop(columns=["situacao", "sempre_vazia"])
    dif = esp.gravar("camada", "PA", 1, novo, "chave", ("situacao",))
    assert not dif.alertas and not dif.travado


def test_alerta_vai_ao_evento_e_healthchecks_sem_valores_da_fonte(tmp_path, monkeypatch):
    esp = Espelho(tmp_path)
    antes = _quadro(3)
    esp.gravar("camada", "PA", 1, antes, "chave")
    dif = esp.gravar("camada", "PA", 1, antes.assign(situacao=None), "chave")
    eventos, pings = [], []
    monkeypatch.setattr("raiz.coleta.replicacao.evento", lambda *a, **k: eventos.append((a, k)))
    hc = Healthchecks(
        "k",
        "https://hc.exemplo",
        "raiz-{tarefa}",
        httpx.Client(
            transport=httpx.MockTransport(
                lambda req: pings.append((req.url.path, req.content.decode())) or httpx.Response(200)
            )
        ),
    )
    registrar_alertas(None, "fonte", "PA/1", dif, hc)
    assert eventos[0][0][3] == "alerta"
    assert pings[0][0] == "/k/raiz-coleta-qualidade/fail"
    assert "regular" not in json.dumps(eventos) + pings[0][1]
    assert json.loads(pings[0][1])["alertas"] == dif.alertas


def test_car_nao_avanca_cursor_ou_assinatura_quando_coluna_fica_vazia(tmp_path, monkeypatch):
    from raiz.coleta import car

    esp = Espelho(tmp_path)
    antes = _quadro(3).rename(columns={"chave": "cod_imovel"})
    esp.gravar("car", "PA", 1504950, antes, "cod_imovel")
    updates = []
    anterior = SimpleNamespace(assinatura="antiga", cursor=None, liberado=False, tentativas=0)
    monkeypatch.setattr(car, "campo_data", lambda *a: "data_atualizacao")
    monkeypatch.setattr(car, "estado", lambda *a: anterior)
    monkeypatch.setattr(car, "atualizar", lambda *a, **k: updates.append(k))
    monkeypatch.setattr(car, "evento", lambda *a, **k: None)
    monkeypatch.setattr(car, "registrar_alertas", lambda *a, **k: None)
    monkeypatch.setattr(car.wfs, "assinatura", lambda *a: "3|2026-11-12")
    monkeypatch.setattr(car.wfs, "ler", lambda *a, **k: antes.assign(situacao=None))
    resultado = car.coletar_municipio(None, None, esp, "PA", 1504950)
    assert resultado.acao == "travado" and resultado.diferenca.alertas
    assert updates[-1]["sujo"]
    assert all("cursor" not in update and "assinatura" not in update for update in updates)
    assert esp.ler("car", "PA", 1504950).situacao.eq("regular").all()


def test_mudanca_uniforme_em_numero_par_nao_cancela_no_resumo(tmp_path):
    esp = Espelho(tmp_path)
    antes = _quadro(40)
    esp.gravar("camada", "PA", 1, antes, "chave")
    novo = antes.assign(zero=20)
    dif = esp.gravar("camada", "PA", 1, novo, "chave")
    assert not dif.pelo_resumo and dif.travado and len(dif.mudaram) == 40
    assert esp.ler("camada", "PA", 1).zero.eq(0).all()
    assert esp.gravar("camada", "PA", 1, novo, "chave", liberar=True).escreveu
    assert esp.gravar("camada", "PA", 1, novo.iloc[::-1], "chave").pelo_resumo


def test_poligonos_empty_disparam_guarda_de_coluna_vazia(tmp_path):
    esp = Espelho(tmp_path)
    antes = _quadro(3)
    esp.gravar("camada", "PA", 1, antes, "chave")
    novo = antes.set_geometry([Polygon()] * 3)
    dif = esp.gravar("camada", "PA", 1, novo, "chave")
    assert dif.travado and not dif.escreveu
    assert dif.alertas == [{"tipo": "coluna_vazia", "coluna": "geometry", "antes": 3, "depois": 0}]
    assert not esp.ler("camada", "PA", 1).geometry.is_empty.any()
