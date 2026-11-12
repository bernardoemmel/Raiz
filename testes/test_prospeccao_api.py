"""Fronteira HTTP: identidade, cobrança, privacidade, limites e filtros inválidos."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz import prospeccao_api as api

CAR = "PA-1504950-" + "A" * 32


@pytest.fixture
def cliente(monkeypatch):
    eng = object()
    eventos = []
    monkeypatch.setattr(api.pedidos, "cliente_da_sessao", lambda _eng, t: 7 if t == "sessao-cliente" else None)
    monkeypatch.setattr(api.acesso, "limitar", lambda *args: eventos.append(("limite", args[1:])))
    monkeypatch.setattr(api.front_api, "imoveis_do_municipio", lambda *a, **kw: [{"cod_imovel": CAR}])
    monkeypatch.setattr(api.front_api, "versao", lambda *a: {"data_corte": "2026-11-12"})
    monkeypatch.setattr(api.front_api, "do_banco", lambda *a: {})
    monkeypatch.setattr(api.imovel_dados, "ficha_prospeccao", lambda *a: {"codigo_car": CAR, "area_total": 10})
    app = FastAPI()
    app.include_router(api.roteador(lambda _: eng))
    with TestClient(app) as cl:
        yield cl, eventos


@pytest.mark.parametrize(
    "metodo,rota,corpo",
    [
        ("GET", "/busca", None),
        ("GET", "/saldo", None),
        ("GET", "/compras", None),
        ("GET", f"/fichas/{CAR}", None),
        ("POST", f"/fichas/{CAR}/desbloquear", None),
        ("POST", "/contatos", {"codigo_car": CAR}),
        ("POST", "/compras", {"plano": "avulsa", "chave_idempotencia": "pedido-123"}),
        ("GET", "/compras/qualquer", None),
    ],
)
def test_sessao_individual_obrigatoria(cliente, metodo, rota, corpo):
    cl, _ = cliente
    for cabecalho in ({}, {"Authorization": "Bearer token-operacional"}):
        assert cl.request(metodo, "/prospeccao" + rota, json=corpo, headers=cabecalho).status_code == 401


def test_ficha_nao_sai_antes_do_debito(cliente, monkeypatch):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"

    def negar(*args):
        raise api.acesso.ErroAcesso(402, "Créditos insuficientes")

    monkeypatch.setattr(api.acesso, "exigir_desbloqueio", negar)
    monkeypatch.setattr(api.acesso, "desbloquear", negar)
    for metodo, rota in (("GET", f"/fichas/{CAR}"), ("POST", f"/fichas/{CAR}/desbloquear")):
        r = cl.request(metodo, "/prospeccao" + rota)
        assert r.status_code == 402
        assert CAR not in r.text and "area_total" not in r.text


def test_ficha_paga_nao_pode_ser_cacheada_publicamente(cliente, monkeypatch):
    cl, eventos = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    monkeypatch.setattr(api.acesso, "exigir_desbloqueio", lambda *a: CAR)
    r = cl.get(f"/prospeccao/fichas/{CAR}")
    assert r.status_code == 200 and r.json()["codigo_car"] == CAR
    assert r.headers["Cache-Control"] == "private, no-store"
    assert r.headers["Vary"] == "Authorization"
    assert eventos[0][1][0] == "cliente:7"


def test_falha_ao_montar_nao_consumiu_credito(cliente, monkeypatch):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    monkeypatch.setattr(api.front_api, "imoveis_do_municipio", lambda *a, **kw: [])
    debitos = []
    monkeypatch.setattr(api.acesso, "desbloquear", lambda *a: debitos.append(a))
    assert cl.post(f"/prospeccao/fichas/{CAR}/desbloquear").status_code == 404
    assert not debitos


@pytest.mark.parametrize(
    "parametros",
    [
        {"uf": "ZZ"},
        {"area_min_ha": 10, "area_max_ha": 1},
        {"credito_min": "NaN"},
        {"bioma": "inexistente"},
        {"limite": 1000},
        {"pagina": 0},
        {"incluir_imoveis": "true"},
    ],
)
def test_filtros_invalidos_devolvem_422(cliente, parametros):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    r = cl.get("/prospeccao/busca", params=parametros)
    assert r.status_code == 422


def test_busca_publica_nunca_pede_lista_e_ignora_ip_falsificado(cliente, monkeypatch):
    cl, eventos = cliente
    chamadas = []

    def buscar(*args, **kwargs):
        chamadas.append(kwargs)
        return {"totais": {"fazendas": 10}}

    monkeypatch.setattr(api.busca, "buscar_prospeccao", buscar)
    assert cl.get("/prospeccao/agregado", headers={"X-Forwarded-For": "192.0.2.1"}).status_code == 200
    assert cl.get("/prospeccao/agregado", headers={"X-Forwarded-For": "192.0.2.2"}).status_code == 200
    assert chamadas == [{"incluir_imoveis": False}] * 2
    assert eventos[0] == eventos[1]


def test_limite_persistido_retorna_retry_after(cliente, monkeypatch):
    cl, _ = cliente

    def negar(*args):
        raise api.acesso.ErroAcesso(429, "Aguarde", retry_after=87)

    monkeypatch.setattr(api.acesso, "limitar", negar)
    r = cl.get("/prospeccao/agregado")
    assert r.status_code == 429 and r.headers["Retry-After"] == "87"


def test_preco_e_identidade_nao_podem_vir_do_cliente(cliente):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    r = cl.post(
        "/prospeccao/compras",
        json={"plano": "avulsa", "chave_idempotencia": "compra-123", "valor_rs": 0, "cliente_id": 99},
    )
    assert r.status_code == 422


def test_contato_so_registra_pedido_da_sessao(cliente, monkeypatch):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    pedidos = []

    def registrar(_engine, cid, car):
        pedidos.append((cid, car))
        return {"id": "pedido-1", "estado": "recebido", "mensagem": "Pedido registrado na Raíz."}

    monkeypatch.setattr(api.acesso, "pedir_contato", registrar)
    r = cl.post("/prospeccao/contatos", json={"codigo_car": CAR})
    assert r.status_code == 200 and pedidos == [(7, CAR)]
    assert "telefone" not in r.text and "email" not in r.text


@pytest.mark.parametrize("sufixo", ["visual", "visual/satelite", "visual/satelite.webp"])
def test_visual_exige_sessao_e_desbloqueio_antes_de_ler_dados(cliente, monkeypatch, sufixo):
    cl, _ = cliente
    lidas = []
    monkeypatch.setattr(api.prospeccao_visual, "consultar", lambda *a: lidas.append("mapa"))
    monkeypatch.setattr(api.prospeccao_visual, "satelite_disponivel", lambda *a: lidas.append("satelite"))
    monkeypatch.setattr(api.front_api, "_imagem", lambda *a: lidas.append("imagem"))
    assert cl.get(f"/prospeccao/fichas/{CAR}/{sufixo}").status_code == 401
    cl.headers["Authorization"] = "Bearer sessao-cliente"

    def negar(*args):
        raise api.acesso.ErroAcesso(402, "Libere a ficha")

    monkeypatch.setattr(api.acesso, "exigir_desbloqueio", negar)
    assert cl.get(f"/prospeccao/fichas/{CAR}/{sufixo}").status_code == 402
    assert not lidas


def test_imagem_privada_tem_headers_e_verifica_exclusividade(cliente, monkeypatch, tmp_path):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    checks = []
    monkeypatch.setattr(api.acesso, "exigir_desbloqueio", lambda *a: checks.append(a[1:]))
    arq = tmp_path / "hoje.webp"
    arq.write_bytes(b"imagem-de-teste")
    monkeypatch.setattr(api.front_api, "_imagem", lambda *a: ({}, arq))
    r = cl.get(f"/prospeccao/fichas/{CAR}/visual/satelite.webp")
    assert r.status_code == 200 and r.content == b"imagem-de-teste"
    assert r.headers["Cache-Control"] == "private, no-store"
    assert r.headers["Vary"] == "Authorization"
    assert checks == [(7, CAR)]
