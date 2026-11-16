"""Banco real: donos distintos, CAR compartilhado, retirada do lote e importação concorrente."""

import datetime as dt
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from raiz.pedidos import servico
from raiz.vigilancia import lotes, lotes_api

pytestmark = pytest.mark.banco
COD = "PA-1507300-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
PEQUENA = "PA-1507300-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
HOJE = dt.date(2026, 11, 12)


@pytest.fixture
def cenario(banco_url):
    eng = create_engine(banco_url)
    clientes = [servico.criar_cliente(eng, "teste_vigilancia_lotes")[0] for _ in range(2)]
    pedidos = [str(uuid.uuid4()), str(uuid.uuid4())]
    with eng.begin() as con:
        for cliente, pedido in zip(clientes, pedidos, strict=True):
            con.execute(
                text("""insert into negocio.pedido(id,cliente_id,campos,criado_em)
                values (:p,:c,'{}','2026-11-01')"""),
                {"p": pedido, "c": cliente},
            )
            con.execute(
                text("""insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel)
                values (:p,:cod,'lote')"""),
                {"p": pedido, "cod": COD},
            )
    yield eng, clientes, pedidos
    with eng.begin() as con:
        con.execute(text("delete from negocio.notificacao where cliente_id=any(:c)"), {"c": clientes})
        con.execute(text("delete from negocio.pedido where cliente_id=any(:c)"), {"c": clientes})
        con.execute(text("delete from negocio.cliente where id=any(:c)"), {"c": clientes})
    eng.dispose()


def _documento(cliente, pedido, alerta="evento-teste"):
    lote = lotes.Lote(pedido, cliente, dt.date(2026, 11, 1), (COD,))
    return lotes.rascunho(
        lote,
        {
            "alerta_id": alerta,
            "fonte": "firms",
            "tipo": "fogo",
            "alvo_id": COD,
            "data_evento": HOJE,
            "area_sobreposta_ha": 0.5,
            "regra_versao": "teste",
        },
        HOJE,
    )


def test_catalogo_usa_dono_atual_contrato_e_exclui_cancelado_ou_inativo(cenario):
    eng, clientes, pedidos = cenario
    with eng.begin() as con:
        con.execute(text("update negocio.pedido set estado='contrato' where id=:p"), {"p": pedidos[0]})
        con.execute(
            text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values(:p,:c,'reserva')"),
            {"p": pedidos[0], "c": PEQUENA},
        )
        con.execute(text("update negocio.pedido set estado='cancelado' where id=:p"), {"p": pedidos[1]})
    catalogo = lotes.catalogo_do_banco(eng)
    meus = [p for p in lotes.validar_catalogo(catalogo) if p.pedido_id in pedidos]
    assert len(meus) == 1 and meus[0].cliente_id == clientes[0] and set(meus[0].imoveis) == {COD, PEQUENA}
    with eng.begin() as con:
        con.execute(text("update negocio.cliente set ativo=false where id=:c"), {"c": clientes[0]})
    assert not [p for p in lotes.catalogo_do_banco(eng)["lotes"] if p["pedido_id"] in pedidos]


def test_sugestao_atual_nao_ressuscita_fazenda_retirada(cenario):
    eng, _, pedidos = cenario
    opcoes = [{"id": "barata", "itens": [{"cod_imovel": PEQUENA, "papel": "lote"}]}]
    with eng.begin() as con:
        con.execute(text("delete from negocio.pedido_fazenda where pedido_id=:p"), {"p": pedidos[0]})
        con.execute(
            text("""insert into negocio.pedido_sugestao
            (pedido_id,motivo,otimizador_versao,premissas_versao,base,opcoes)
            values(:p,'teste','teste','teste','{}',cast(:o as jsonb))"""),
            {"p": pedidos[0], "o": json.dumps(opcoes)},
        )
    primeiro = next(p for p in lotes.catalogo_do_banco(eng)["lotes"] if p["pedido_id"] == pedidos[0])
    assert primeiro["imoveis"] == [PEQUENA]
    with eng.begin() as con:
        con.execute(
            text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values(:p,:c,'fora')"),
            {"p": pedidos[0], "c": PEQUENA},
        )
    assert not [p for p in lotes.catalogo_do_banco(eng)["lotes"] if p["pedido_id"] == pedidos[0]]


def test_cada_dono_tem_seu_rascunho_sem_envio_e_sem_duplicar_em_concorrencia(cenario, monkeypatch):
    eng, clientes, pedidos = cenario
    monkeypatch.setattr(
        servico,
        "ENVIADORES",
        {canal: lambda *a: pytest.fail("envio externo proibido") for canal in ("email", "whatsapp", "painel")},
    )
    d1, d2 = [_documento(c, p) for c, p in zip(clientes, pedidos, strict=True)]
    assert d1["id"] != d2["id"] and d1["area_sobreposta_ha"] is None
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(lambda _: lotes.registrar_no_banco(eng, [d1, d2]), range(2)))
    assert sum(resultados) == 2
    assert lotes.registrar_no_banco(eng, [d1, d2]) == 0
    assert lotes.relatorios_do_pedido(eng, pedidos[0], clientes[0])[0]["cliente_id"] == clientes[0]
    with pytest.raises(servico.ErroPedido):
        lotes.relatorios_do_pedido(eng, pedidos[0], clientes[1])
    with eng.connect() as con:
        rows = con.execute(
            text("select canal,estado from negocio.notificacao where cliente_id=any(:c)"), {"c": clientes}
        ).all()
    assert rows == [("painel", "na_fila"), ("painel", "na_fila")]


def test_reconfere_cancelamento_membro_e_titularidade_na_importacao(cenario):
    eng, clientes, pedidos = cenario
    documento = _documento(clientes[0], pedidos[0])
    with eng.begin() as con:
        con.execute(text("update negocio.pedido_fazenda set papel='fora' where pedido_id=:p"), {"p": pedidos[0]})
    assert lotes.registrar_no_banco(eng, [documento]) == 0

    with eng.begin() as con:
        con.execute(text("update negocio.pedido_fazenda set papel='lote' where pedido_id=:p"), {"p": pedidos[0]})
        con.execute(text("update negocio.pedido set estado='cancelado' where id=:p"), {"p": pedidos[0]})
    assert lotes.registrar_no_banco(eng, [documento]) == 0
    with eng.begin() as con:
        con.execute(text("update negocio.pedido set estado='contrato' where id=:p"), {"p": pedidos[0]})
    assert lotes.registrar_no_banco(eng, [documento]) == 1
    with eng.begin() as con:
        con.execute(text("update negocio.pedido set cliente_id=:c where id=:p"), {"p": pedidos[0], "c": clientes[1]})
        assert all("rascunho_vigilancia" not in a["detalhe"] for a in servico._alertas(con, pedidos[0]))
    assert lotes.relatorios_do_pedido(eng, pedidos[0], clientes[1]) == []
    assert lotes.registrar_no_banco(eng, [documento]) == 0


def test_rascunho_complementa_alerta_do_vigia_sem_segundo_aviso(cenario):
    eng, clientes, pedidos = cenario
    documento = _documento(clientes[0], pedidos[0])
    with eng.begin() as con:
        assert servico._alerta(
            con,
            pedidos[0],
            "fazenda_com_problema",
            COD,
            "Foco de calor: indício a conferir.",
            {"motivo": "fogo"},
            documento["chave_fato"],
        )
    assert lotes.registrar_no_banco(eng, [documento]) == 0
    assert len(lotes.relatorios_do_pedido(eng, pedidos[0], clientes[0])) == 1
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.notificacao where pedido_id=:p"), {"p": pedidos[0]}
            ).scalar_one()
            == 0
        )


def test_router_exige_pessoa_liberada_e_dono_do_pedido(cenario, monkeypatch):
    eng, clientes, pedidos = cenario
    documento = _documento(clientes[0], pedidos[0])
    lotes.registrar_no_banco(eng, [documento])
    from raiz.publica import conta

    bloqueados = set()

    def liberar(engine, cliente_id):
        if cliente_id in bloqueados:
            raise HTTPException(402, "liberação pendente")

    def pessoa(x_cliente: int | None = Header(None)):
        if x_cliente is None:
            raise HTTPException(401, "sem sessão")
        return SimpleNamespace(cliente_id=x_cliente)

    monkeypatch.setattr(conta, "exigir_liberacao", liberar)
    app = FastAPI()
    lotes_api.registrar(app, lambda request: eng, pessoa)
    cliente = TestClient(app)
    url = f"/pedidos/{pedidos[0]}/vigilancia/relatorios"
    assert cliente.get(url).status_code == 401
    assert cliente.get(url, headers={"x-cliente": str(clientes[1])}).status_code == 404
    r = cliente.get(url, headers={"x-cliente": str(clientes[0])})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()[0]["estado"] == "rascunho_nao_enviado"
    md = cliente.get(f"{url}/{documento['id']}.md", headers={"x-cliente": str(clientes[0])})
    assert md.status_code == 200 and "Rascunho não enviado" in md.text
    bloqueados.add(clientes[0])
    assert cliente.get(url, headers={"x-cliente": str(clientes[0])}).status_code == 402


def test_revisao_atualiza_rascunho_sem_nova_notificacao(cenario):
    eng, clientes, pedidos = cenario
    documento = _documento(clientes[0], pedidos[0])
    assert lotes.registrar_no_banco(eng, [documento]) == 1
    descartado = {**documento, "estado": "descartado_por_revisao", "relatorio": "Ocorrência descartada."}
    assert lotes.registrar_no_banco(eng, [descartado]) == 0
    assert lotes.relatorios_do_pedido(eng, pedidos[0], clientes[0])[0]["estado"] == "descartado_por_revisao"
    with eng.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.notificacao where pedido_id=:p"), {"p": pedidos[0]}
            ).scalar_one()
            == 1
        )
