"""Calendário pelo SDK MCP real, com OAuth, filtros públicos e identificadores íntegros."""

import datetime as dt
from types import SimpleNamespace

import anyio
import pytest
from fastapi import FastAPI, Request
from mcp.client.client import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from raiz.calendario import banco
from raiz.calendario import mcp as calendario_mcp
from raiz.calendario.mcp import resposta_publica
from raiz.calendario.modelos import FonteEstado
from raiz.publica import apresentacao as AP
from raiz.publica import servidor_mcp as M
from testes.test_calendario import AGORA, CAR, evento
from testes.test_privacidade import CPF
from testes.test_publica_banco import _app, cofre, empresa, eng  # noqa: F401


@pytest.fixture
def relogio(monkeypatch):
    class Relogio:
        @classmethod
        def now(cls, tz):
            return dt.datetime(2026, 11, 13, 1, tzinfo=dt.UTC).astimezone(tz)

    monkeypatch.setattr(calendario_mcp, "dt", SimpleNamespace(datetime=Relogio, timedelta=dt.timedelta))


def test_mcp_registrado_exige_escopo_e_preserva_projecao_publica(relogio):
    app = FastAPI()
    chamadas = []
    car = "PA-1504950-A12345678901" + "B" * 20
    e = evento(id="a12345678901" + "b" * 12, codigos_car=[car], cns="123456", matricula="987")
    estado = FonteEstado(id="djen", nome="Não deve sair", coletado_em=AGORA, situacao="parcial", erro=CPF)

    @app.get("/v1/eventos")
    def resposta(request: Request):
        chamadas.append(dict(request.query_params))
        return AP.eventos(
            {
                "eventos": [e.model_dump(mode="json") | {"nome_proprietario": "Não deve sair", "cpf": CPF}],
                "fontes": [estado.model_dump(mode="json")],
                "total": 5,  # total maior que a página deve sobreviver à projeção
                "relatorio_privado": "Não deve sair",
            }
        )

    async def executar():
        async with Client(M.criar_servidor(M.ApiRaiz(app=app))) as c:
            tool = next(t for t in (await c.list_tools()).tools if t.name == "proximos_eventos")
            assert tool.annotations.read_only_hint and tool.annotations.idempotent_hint
            sem_oauth = await c.call_tool("proximos_eventos", {})
            assert sem_oauth.is_error and "401" in sem_oauth.content[0].text
        for escopos in (["pedir"], ["consultar"]):
            token = AccessToken(token="interno", client_id="agente", scopes=escopos, claims={"empresa_id": 42})
            marcador = auth_context_var.set(AuthenticatedUser(token))
            try:
                async with Client(M.criar_servidor(M.ApiRaiz(app=app))) as c:
                    r = await c.call_tool("proximos_eventos", {"estado": "pa", "dias": 20, "limite": 1})
                    if "consultar" not in escopos:
                        assert r.is_error and "403" in r.content[0].text
                        continue
                    assert not r.is_error
                    dados = r.structured_content
                    assert dados["total"] == 5 and dados["eventos"][0]["evento_id"] == e.id
                    assert dados["eventos"][0]["codigos_car"] == [car]
                    assert dados["eventos"][0]["fonte_id"] == "djen"
                    assert "nome" not in dados["fontes"][0]
                    assert not {"cns", "matricula", "cpf", "nome_proprietario"} & dados["eventos"][0].keys()
                    assert "Não deve sair" not in str(dados) and CPF not in str(dados)
                    for argumentos in ({"dias": 0}, {"limite": 1001}, {"tipo": "desconhecido"}):
                        assert (await c.call_tool("proximos_eventos", argumentos)).is_error
            finally:
                auth_context_var.reset(marcador)

    anyio.run(executar)
    assert chamadas == [{"dias": "20", "limite": "1", "estado": "pa"}]


@pytest.mark.banco
def test_mcp_consulta_banco_e_nunca_expoe_car_inferido(con, banco_url, relogio, empresa):  # noqa: F811
    con.execute(text("delete from calendario.evento"))
    aberto = evento(data=dt.date(2026, 11, 20), vinculo="car", uf="PA")
    interno = evento(id="a" * 24, data=dt.date(2026, 11, 21), vinculo="cns_matricula", cns="123456", matricula="987")
    passado = evento(id="b" * 24, data=dt.date(2026, 11, 11), vinculo="car")
    banco.gravar(con, [aberto, interno, passado], [], cruzar_imoveis=False)
    con.commit()
    engine = create_engine(banco_url)
    app = _app(engine)

    async def executar():
        token = AccessToken(
            token="interno", client_id="agente", scopes=["consultar"], claims={"empresa_id": empresa["cliente_id"]}
        )
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with Client(M.criar_servidor(M.ApiRaiz(app=app))) as c:
                r = await c.call_tool("proximos_eventos", {"cod_imovel": CAR, "dias": 30})
                assert not r.is_error and r.structured_content["total"] == 1
                assert r.structured_content["eventos"][0]["evento_id"] == aberto.id
                r = await c.call_tool("proximos_eventos", {"dias": 30})
                assert r.structured_content["total"] == 2
                privado = next(e for e in r.structured_content["eventos"] if e["evento_id"] == interno.id)
                assert privado["codigos_car"] == [] and privado["vinculo"] == "pendente"
                assert not {"cns", "matricula", "sigef"} & privado.keys()
        finally:
            auth_context_var.reset(marcador)

    try:
        anyio.run(executar)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "dados", [{}, {"eventos": [], "fontes": [], "total": True}, {"eventos": [], "fontes": [], "total": -1}]
)
def test_resposta_malformada_nao_vira_calendario_vazio(dados):
    with pytest.raises(ValueError):
        resposta_publica(dados)


def test_numero_de_edital_nao_pode_ser_documento_pessoal():
    with pytest.raises(ValidationError, match="documento pessoal"):
        evento(referencia=f"{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}")
