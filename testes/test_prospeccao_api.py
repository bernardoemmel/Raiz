"""Fronteira HTTP: identidade, cobrança, privacidade, limites e filtros inválidos."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz import prospeccao_api as api

CAR = "PA-1504950-" + "A" * 32


@pytest.fixture
def cliente(monkeypatch):
    eng = SimpleNamespace(connect=lambda: nullcontext(None))
    eventos = []
    monkeypatch.setattr(api.servico.pedidos, "cliente_da_sessao", lambda _eng, t: 7 if t == "sessao-cliente" else None)
    monkeypatch.setattr(api.acesso, "limitar", lambda *args: eventos.append(("limite", args[1:])))
    monkeypatch.setattr(api.servico.front_api, "imoveis_do_municipio", lambda *a, **kw: [{"cod_imovel": CAR}])
    monkeypatch.setattr(api.servico.front_api, "versao", lambda *a: {"data_corte": "2026-11-12"})
    monkeypatch.setattr(api.servico.front_api, "do_banco", lambda *a: {})
    monkeypatch.setattr(api.servico.imovel_dados, "ficha_prospeccao", lambda *a: {"codigo_car": CAR, "area_total": 10})
    monkeypatch.setattr(api.servico.terra_comprometida, "por_codigos", lambda *_: {})
    monkeypatch.setattr(api.servico.prospeccao_versoes, "consultas", lambda _eng, _cid, fichas: nullcontext(fichas))
    monkeypatch.setattr(
        api.servico.prospeccao_protecao, "operacao_vigiada", lambda *args, **kwargs: nullcontext(lambda *_: None)
    )
    app = FastAPI()
    app.include_router(api.roteador(lambda _: eng))
    with TestClient(app) as cl:
        yield cl, eventos


@pytest.mark.parametrize(
    "metodo,rota,corpo",
    [
        ("GET", "/busca", None),
        ("GET", "/saldo", None),
        ("GET", f"/fichas/{CAR}/pdf", None),
        ("GET", f"/fichas/{CAR}/exportar?formato=csv", None),
        ("GET", f"/fichas/{CAR}/historico", None),
        ("POST", "/comparar", {"codigos_car": [CAR, CAR + "B"]}),
        ("GET", "/buscas-salvas", None),
        ("POST", "/buscas-salvas", {"nome": "Pará", "filtros": {"uf": "PA"}}),
        ("DELETE", "/buscas-salvas/qualquer", None),
        ("GET", "/avisos", None),
        ("POST", "/avisos/1/ler", None),
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
    monkeypatch.setattr(api.servico.front_api, "imoveis_do_municipio", lambda *a, **kw: [])
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


def test_comparar_e_pdf_usam_identidade_da_sessao(cliente, monkeypatch):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    chamadas = []

    def comparar(_engine, cid, cars):
        chamadas.append((cid, cars))
        return {"fichas": []}

    monkeypatch.setattr(api.servico, "comparar_fichas", comparar)
    assert cl.post("/prospeccao/comparar", json={"codigos_car": [CAR, CAR + "B"]}).status_code == 200
    assert chamadas == [(7, [CAR, CAR + "B"])]
    assert cl.post("/prospeccao/comparar", json={"codigos_car": [CAR] * 6}).status_code == 422
    assert cl.post("/prospeccao/comparar", json={"codigos_car": [CAR, CAR], "cliente_id": 8}).status_code == 422

    def pdf(_engine, cid, car):
        assert (cid, car) == (7, CAR)
        return b"%PDF-1.4"

    monkeypatch.setattr(api.servico, "exportar_ficha_pdf", pdf)
    resposta = cl.get(f"/prospeccao/fichas/{CAR}/pdf")
    assert resposta.status_code == 200 and resposta.content == b"%PDF-1.4"
    assert resposta.headers["Content-Type"] == "application/pdf"
    assert resposta.headers["Cache-Control"] == "private, no-store"
    assert resposta.headers["Vary"] == "Authorization"
    assert "attachment" in resposta.headers["Content-Disposition"]


def test_busca_salva_e_avisos_nao_aceitam_outra_identidade(cliente, monkeypatch):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"
    chamadas = []

    def salvar(_engine, cid, nome, filtros):
        chamadas.append((cid, nome, filtros.uf))
        return {"id": "busca-1"}

    monkeypatch.setattr(api.buscas_salvas, "salvar", salvar)
    corpo = {"nome": "Pará", "filtros": {"uf": "PA"}}
    assert cl.post("/prospeccao/buscas-salvas", json=corpo).status_code == 200
    assert chamadas == [(7, "Pará", "PA")]
    assert cl.post("/prospeccao/buscas-salvas", json={**corpo, "cliente_id": 8}).status_code == 422
    assert cl.get("/prospeccao/avisos?depois=-1").status_code == 422
    assert cl.get("/prospeccao/avisos?limite=101").status_code == 422

    def negar(_engine, cid, ident):
        assert cid == 7 and ident == "de-outra-conta"
        raise api.acesso.ErroAcesso(404, "Busca salva não encontrada.")

    monkeypatch.setattr(api.buscas_salvas, "excluir", negar)
    assert cl.delete("/prospeccao/buscas-salvas/de-outra-conta").status_code == 404


def test_filtros_premium_sem_pagamento_retornam_402(cliente, monkeypatch):
    cl, _ = cliente
    cl.headers["Authorization"] = "Bearer sessao-cliente"

    def negar(*args, **kwargs):
        raise api.acesso.ErroAcesso(402, "Filtros avançados exigem crédito pago.")

    monkeypatch.setattr(api.busca, "buscar_prospeccao", negar)
    resposta = cl.get("/prospeccao/busca?credito_min=10")
    assert resposta.status_code == 402
    assert "crédito pago" in resposta.text and "imoveis" not in resposta.text


@pytest.mark.parametrize("sufixo", ["visual", "visual/satelite", "visual/satelite.webp"])
def test_visual_exige_sessao_e_desbloqueio_antes_de_ler_dados(cliente, monkeypatch, sufixo):
    cl, _ = cliente
    lidas = []
    monkeypatch.setattr(api.prospeccao_visual, "consultar", lambda *a: lidas.append("mapa"))
    monkeypatch.setattr(api.prospeccao_visual, "satelite_disponivel", lambda *a: lidas.append("satelite"))
    monkeypatch.setattr(api.servico.front_api, "_imagem", lambda *a: lidas.append("imagem"))
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
    monkeypatch.setattr(api.servico.front_api, "_imagem", lambda *a: ({}, arq))
    r = cl.get(f"/prospeccao/fichas/{CAR}/visual/satelite.webp")
    assert r.status_code == 200 and r.content == b"imagem-de-teste"
    assert r.headers["Cache-Control"] == "private, no-store"
    assert r.headers["Vary"] == "Authorization"
    assert checks == [(7, CAR)]
