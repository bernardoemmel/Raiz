"""A releitura corporativa usa o DTO pago comum, sem nova compra ou cobrança da análise."""

import json

import anyio
import pytest
from mcp.client.client import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken
from sqlalchemy import text

from raiz import prospeccao_acesso as acesso
from raiz import prospeccao_servico as servico
from raiz.pedidos import servico as pedidos
from raiz.publica import conta
from raiz.publica.servidor_mcp import ApiRaiz, criar_servidor
from testes.test_publica_banco import _app, _h, cl, cofre, empresa, eng  # noqa: F401

pytestmark = pytest.mark.banco


def _car(engine):
    with engine.connect() as con:
        return con.execute(text("select cod_imovel from funil.vigente order by cod_imovel limit 1")).scalar_one()


def _habilitar(engine, cliente):
    with engine.begin() as con:
        con.execute(
            text("""update negocio.conta_api set contrato_aceito_em=now(), sinal_pago_em=now()
            where cliente_id=:c"""),
            {"c": cliente},
        )


def _liberar_car(engine, cliente, car):
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.prospeccao_carteira(cliente_id,creditos) values (:c,1)
            on conflict(cliente_id) do update set creditos=1"""),
            {"c": cliente},
        )
    assert acesso.desbloquear(engine, cliente, car)["cobrado"] is True


def _sem_cobranca_nova(engine, cliente):
    with engine.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.lancamento_api where cliente_id=:c"), {"c": cliente}
            ).scalar_one()
            == 0
        )
        assert con.execute(
            text("select quantidade from negocio.prospeccao_movimento where cliente_id=:c"), {"c": cliente}
        ).scalars().all() == [-1]
    assert conta.ver(engine, cliente)["testes_restantes"] == 3
    assert acesso.saldo(engine, cliente)["creditos"] == 0


def test_releitura_exige_gates_e_liberacao_propria_preserva_dto_sem_nova_tarifa(eng, cl, empresa):  # noqa: F811
    car, cid = _car(eng), empresa["cliente_id"]
    rota = f"/v1/fazendas/{car}/ficha"
    assert cl.get(rota).status_code == 401
    assert cl.get(rota, headers=_h(empresa)).status_code == 403
    conta.aceitar_contrato(eng, cid)
    assert cl.get(rota, headers=_h(empresa)).status_code == 403  # sinal ainda ausente
    _habilitar(eng, cid)
    assert cl.get(rota, headers=_h(empresa)).status_code == 402
    outro = pedidos.criar_cliente(eng, "Outra empresa da ficha")[0]
    _liberar_car(eng, outro, car)
    assert cl.get(rota, headers=_h(empresa)).status_code == 402  # pagamento de outra empresa não serve
    _liberar_car(eng, cid, car)
    esperado = servico.consultar_ficha(eng, cid, car)
    for _ in range(2):
        r = cl.get(rota, headers=_h(empresa))
        assert r.status_code == 200, r.text
        assert r.json() == esperado  # fontes, datas e nulls permanecem iguais ao DTO da interface
        assert r.headers["cache-control"] == "private, no-store"
        assert "X-Chave-API" in r.headers["vary"]
    _sem_cobranca_nova(eng, cid)
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.exposicao_api where cliente_id=:c and cod_imovel=:car"),
                {"c": cid, "car": car},
            ).scalar_one()
            == 2
        )
    with eng.begin() as con:
        con.execute(
            text("update negocio.conta_api set bloqueada_em=now(),bloqueio_motivo='limite' where cliente_id=:c"),
            {"c": cid},
        )
    assert cl.get(rota, headers=_h(empresa)).status_code == 403


def test_ferramenta_real_oauth_chama_mesmo_servico_e_recusa_escopo_ou_car_fechado(eng, empresa):  # noqa: F811
    cid, car = empresa["cliente_id"], _car(eng)
    _habilitar(eng, cid)
    app = _app(eng)

    async def chamar(escopos):
        token = AccessToken(token="oauth-teste", client_id="agente", scopes=escopos, claims={"empresa_id": cid})
        marcador = auth_context_var.set(AuthenticatedUser(token))
        try:
            async with Client(criar_servidor(ApiRaiz(app=app))) as cliente:
                return await cliente.call_tool("consultar_ficha", {"codigo_car": car})
        finally:
            auth_context_var.reset(marcador)

    negado = anyio.run(chamar, ["pedir"])
    assert negado.is_error and json.loads(negado.content[0].text[negado.content[0].text.index("{") :])["status"] == 403
    fechado = anyio.run(chamar, ["consultar"])
    assert (
        fechado.is_error and json.loads(fechado.content[0].text[fechado.content[0].text.index("{") :])["status"] == 402
    )
    _liberar_car(eng, cid, car)
    resposta = anyio.run(chamar, ["consultar"])
    assert not resposta.is_error
    assert resposta.structured_content == servico.consultar_ficha(eng, cid, car)
    assert resposta.structured_content["codigo_car"] == car
    _sem_cobranca_nova(eng, cid)
    with eng.connect() as con:
        assert con.execute(
            text("""select via,status,preco_rs from negocio.chamada_api
            where cliente_id=:c and ferramenta='consultar_ficha' order by id desc limit 1"""),
            {"c": cid},
        ).one() == ("mcp", 200, 0)


def test_limite_compartilhado_da_ficha_preserva_retry_after(eng, cl, empresa, monkeypatch):  # noqa: F811
    _habilitar(eng, empresa["cliente_id"])

    def negar(*_):
        raise acesso.ErroAcesso(429, "Limite de consultas atingido.", retry_after=17)

    monkeypatch.setattr(servico, "limitar_consulta", negar)
    resposta = cl.get(f"/v1/fazendas/{_car(eng)}/ficha", headers=_h(empresa))
    assert resposta.status_code == 429 and resposta.headers["Retry-After"] == "17"
    assert resposta.headers["content-type"].startswith("application/problem+json")
