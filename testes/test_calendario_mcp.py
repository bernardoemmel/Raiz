"""MCP corporativo reaproveita o Calendário público com identidade, limites e projeção segura."""

import copy
import datetime as dt
import json
from zoneinfo import ZoneInfo

import anyio
import pytest
from fastapi.testclient import TestClient
from mcp.client.client import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from sqlalchemy import text

from raiz.calendario import banco
from raiz.calendario.modelos import Evento, FonteEstado
from raiz.publica import chaves as K
from raiz.publica import conta as CT
from raiz.publica import telemetria as O
from raiz.publica.servidor_mcp import ApiRaiz, criar_servidor
from testes.test_publica_banco import _app, _h, cl, cofre, empresa, eng  # noqa: F401
from testes.test_publica_telemetria import coletor  # noqa: F401

pytestmark = pytest.mark.banco
CAR = "PA-1504950-" + "A" * 32


@pytest.fixture
def calendario(eng):  # noqa: F811
    agora = dt.datetime.now(ZoneInfo("America/Sao_Paulo"))
    e = Evento(
        id="0" * 24,
        tipo="leilao_imovel",
        data=agora.date() + dt.timedelta(days=5),
        uf="PA",
        codigos_car=[CAR],
        fonte_id="djen",
        fonte_nome="texto externo que nunca deve sair",
        fonte_url="https://comunicaapi.pje.jus.br/ato/NAO-PUBLICAR",
        coletado_em=agora,
        confianca=0.85,
    )
    fonte = FonteEstado(
        id="djen", nome="NAO-PUBLICAR", coletado_em=agora, situacao="parcial", erro="NAO-PUBLICAR", eventos=1
    )
    with eng.begin() as con:
        con.execute(text("delete from calendario.evento"))
        con.execute(text("delete from calendario.fonte_estado"))
        banco.gravar(con, [e], [fonte])
    return e


async def chamar(app, cid, escopos, argumentos):
    token = AccessToken(token="oauth-teste", client_id="agente", scopes=escopos, claims={"empresa_id": cid})
    marcador = auth_context_var.set(AuthenticatedUser(token))
    try:
        async with Client(criar_servidor(ApiRaiz(app=app))) as cliente:
            return await cliente.call_tool("proximos_eventos", argumentos)
    finally:
        auth_context_var.reset(marcador)


def problema(resposta):
    texto = resposta.content[0].text
    return json.loads(texto[texto.index("{") :])


def test_calendario_real_por_mcp_preserva_filtros_sem_cobrar_expor_texto_ou_perder_telemetria(
    eng,  # noqa: F811
    empresa,  # noqa: F811
    calendario,
    coletor,  # noqa: F811
    monkeypatch,
):
    tracer, exportador = coletor
    monkeypatch.setattr(O, "_tracer", lambda escolhido=None: escolhido or tracer)
    app, cid = _app(eng), empresa["cliente_id"]
    r = anyio.run(chamar, app, cid, ["consultar"], {"estado": "pa", "dias": 10, "cod_imovel": CAR})
    assert not r.is_error
    out = r.structured_content
    assert out["total"] == 1
    evento = out["eventos"][0]
    assert evento["evento_id"] == calendario.id
    assert evento["data"] == calendario.data.isoformat() and evento["confianca"] == 0.85
    assert evento["codigos_car"] == [CAR]
    assert evento["fonte_portal_url"] == "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
    assert "NAO-PUBLICAR" not in json.dumps(out) and "texto externo" not in json.dumps(out)
    assert all("erro" not in f and "nome" not in f for f in out["fontes"])
    assert CT.ver(eng, cid)["testes_restantes"] == 3  # não libera nem consome o produto pago
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.lancamento_api where cliente_id=:c"), {"c": cid}
            ).scalar_one()
            == 0
        )
        assert con.execute(
            text("""select via,status,preco_rs from negocio.chamada_api
                where cliente_id=:c and ferramenta='proximos_eventos' order by id desc limit 1"""),
            {"c": cid},
        ).one() == ("mcp", 200, 0)
    assert any(s.attributes.get("gen_ai.tool.name") == "proximos_eventos" for s in exportador.get_finished_spans())
    filtrado = anyio.run(chamar, app, cid, ["consultar"], {"dias": 1})
    assert not filtrado.is_error and filtrado.structured_content["total"] == 0


def test_calendario_exige_oauth_escopo_e_conta_ativa_e_erros_nao_ecoam_filtros(eng, empresa, cl):  # noqa: F811
    assert cl.get("/v1/eventos").status_code == 401
    app, cid = _app(eng), empresa["cliente_id"]
    negado = anyio.run(chamar, app, cid, ["pedir"], {})
    assert negado.is_error and problema(negado)["status"] == 403
    invalido = cl.get("/v1/eventos", params={"cod_imovel": "NAO-PUBLICAR"}, headers=_h(empresa))
    assert invalido.status_code == 422 and "NAO-PUBLICAR" not in invalido.text
    assert invalido.headers["content-type"].startswith("application/problem+json")
    with eng.begin() as con:
        con.execute(
            text("update negocio.conta_api set bloqueada_em=now(),bloqueio_motivo='limite' where cliente_id=:c"),
            {"c": cid},
        )
    bloqueado = anyio.run(chamar, app, cid, ["consultar"], {})
    assert bloqueado.is_error and problema(bloqueado)["status"] == 403


def test_limite_calendario_compartilhado_com_rest_outra_rota_e_chave(eng, empresa, monkeypatch):  # noqa: F811
    premissas = copy.deepcopy(CT.premissas())
    premissas["limites"]["por_minuto"] = 2
    monkeypatch.setattr(CT, "premissas", lambda: premissas)
    outra_chave = K.criar(eng, empresa["cliente_id"])
    app = _app(eng)
    with TestClient(app) as cliente:
        assert cliente.get("/v1/conta", headers=_h(empresa)).status_code == 200
        r = anyio.run(chamar, app, empresa["cliente_id"], ["consultar"], {})
        assert not r.is_error
        excedente = cliente.get("/v1/eventos", headers=_h(outra_chave))
        assert excedente.status_code == 429 and int(excedente.headers["Retry-After"]) > 0
    assert CT.ver(eng, empresa["cliente_id"])["testes_restantes"] == 3
