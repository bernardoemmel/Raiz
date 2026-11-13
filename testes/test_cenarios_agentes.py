"""Os cenários da campanha são dados reais de teste, nunca respostas MCP pré-fabricadas."""

import asyncio
import base64
import hashlib
import uuid
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import create_engine, text

from raiz.pedidos import servico as S
from raiz.pedidos.campos import CamposPedido
from raiz.publica import trabalhos as T
from raiz.publica.avaliacao import carregar_gabarito
from scripts.cenarios_agentes import (
    _conta,
    _ofertas,
    _pedido,
    _semeiar_oferta,
    _snapshot,
    configuracao,
    identificadores,
)
from scripts.oauth_agentes_teste import _local


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://teste:senha@localhost/producao",
        "postgresql+psycopg://teste:senha@servidor/raiz_agentes_teste",
        "postgresql+psycopg://teste:senha@127.0.0.1/raiz",
    ],
)
def test_cenario_recusa_banco_fora_da_pilha_descartavel(tmp_path, url):
    arquivo = tmp_path / ".env"
    arquivo.write_text(f"RAIZ_BANCO_URL_HOST={url}\n")
    with pytest.raises(ValueError, match="descartável"):
        configuracao(arquivo)


def test_ids_deterministicos_distintos_sem_reusar_empresa_entre_96_tentativas():
    gabarito, _ = carregar_gabarito()
    ids = [identificadores(t.id, n) for t in gabarito.tarefas for n in range(1, 5)]
    for campo in ("cliente_id", "pedido_id", "idempotency_key_anterior"):
        assert len({i[campo] for i in ids}) == 96
    assert identificadores("disponibilidade_pa", 1) == identificadores("disponibilidade_pa", 1)


def test_oferta_nao_exclui_pequenas_e_deficit_vem_dos_dados():
    ofertas = _ofertas()
    assert len(ofertas) == 60 and all(o["pequena"] for o in ofertas)
    assert all(o["elegivel_sem_salvaguardas"] for o in ofertas)
    assert sum(o["credito_p50"] for o in ofertas if o["custo_credito_usd"] <= 30) == 600000
    assert all(o["credito_p10"] <= o["credito_p50"] <= o["credito_p90"] for o in ofertas)


@pytest.mark.parametrize("url", ["https://oauth.example", "http://oauth.example", "http://usuario:senha@localhost"])
def test_bootstrap_oauth_recusa_origem_externa_ou_credenciais_na_url(url):
    with pytest.raises(ValueError, match="local"):
        _local(url)


def test_pkce_confere_verificador_e_intercepta_callback_sem_acessar_dominio(monkeypatch):
    from scripts import oauth_agentes_teste as O

    estado = {}
    callback = "https://cliente.raiz.example/callback"

    def responder(req):
        assert req.url.host == "localhost", "O bootstrap não pode navegar ao callback reservado"
        if req.url.path.endswith("/master/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "administracao-sintetica"})
        if req.url.path == "/admin/realms/raiz/users":
            if req.method == "GET":
                return httpx.Response(200, json=[])
            return httpx.Response(201, headers={"Location": "http://localhost/admin/realms/raiz/users/fixture"})
        if req.url.path.endswith("/protocol/openid-connect/auth"):
            params = dict(req.url.params)
            assert params["code_challenge_method"] == "S256" and params["redirect_uri"] == callback
            estado.update(params)
            return httpx.Response(200, text='<form action="/entrar"><input name="username"></form>')
        if req.url.path == "/entrar":
            return httpx.Response(
                200, text='<form action="/consentir"><input type="hidden" name="nonce" value="teste"></form>'
            )
        if req.url.path == "/consentir":
            assert parse_qs(req.content.decode())["accept"] == ["Yes"]
            return httpx.Response(302, headers={"Location": callback + "?code=teste&state=" + estado["state"]})
        if req.url.path.endswith("/raiz/protocol/openid-connect/token"):
            data = parse_qs(req.content.decode())
            assert data["grant_type"] == ["authorization_code"]
            challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"][0].encode()).digest())
            assert challenge.decode().rstrip("=") == estado["code_challenge"]
            return httpx.Response(200, json={"access_token": "sessao-sintetica"})
        raise AssertionError("Requisição OAuth não prevista")

    original = httpx.AsyncClient
    monkeypatch.setattr(O.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(responder), **kw))
    oauth = O.KeycloakTeste(
        {
            "RAIZ_OAUTH_ISSUER": "http://localhost/realms/raiz",
            "RAIZ_OAUTH_REDIRECT_URI": callback,
            "RAIZ_KEYCLOAK_ADMIN": "fixture",
            "RAIZ_KEYCLOAK_ADMIN_SENHA": "senha-sintetica",
        }
    )
    sessao = asyncio.run(oauth.criar_sessao(12, "tarefa:1"))
    assert sessao.access_token == "sessao-sintetica"


@pytest.mark.banco
def test_fixtures_passam_por_servico_e_postgis_reais(banco_url):
    eng = create_engine(banco_url)
    with eng.connect() as con:
        transacao = con.begin()
        try:
            vinculo = T.ConexaoVinculada(con)
            # Outros testes da mesma sessão podem ter programas sintéticos de área ampla.
            # A remoção vale só nesta transação e é revertida ao encerrar o teste.
            con.execute(text("delete from geo.redd_programa where uf='PA'"))
            ofertas = _semeiar_oferta(vinculo)
            cid = identificadores("teste-cenarios", 1)["cliente_id"]
            _conta(con, cid, True, 10000, 0)
            campos = CamposPedido(
                onde={
                    "ufs": ["PA"],
                    "so_fornecedores_cadeia": True,
                    "fornecedores": [o["cod_imovel"] for o in ofertas],
                },
                dinheiro={"custo_max_usd_credito": 30},
            )
            base = S.base_disponivel(vinculo, cid, campos)
            assert base["na_unidade_da_meta"] == 600000
            assert base["falta"] == 400000 and not base["alcanca_meta"]
            pid = str(uuid.uuid4())
            _pedido(con, cid, pid, ofertas, "custo_e_cronograma")
            pedido = S.obter_pedido(vinculo, pid, cid)
            assert len(pedido["opcoes"]) == 3
            assert pedido["opcoes"][0]["custo_usd_credito"] == {"p10": 38, "p50": 43, "p90": 52}
            assert _snapshot(vinculo, cid)["pedidos"] == [{"id": pid, "estado": "lote_montado"}]
        finally:
            transacao.rollback()
    eng.dispose()
