"""Sessão, vínculo ao pedido e previsão vigente usam PostGIS real; PDFs são só fixtures funcionais."""

import datetime as dt
import json
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from raiz.carga import carregar_pasta
from raiz.documentos.certidao import api
from raiz.documentos.certidao import entrada as E
from raiz.pedidos import servico as S
from raiz.pessoal import Cofre, gerar_chave
from testes.conftest import AMOSTRA
from testes.test_primeira_certidao import PDF, chave, modelo

pytestmark = pytest.mark.banco
CAR = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"


@pytest.fixture
def eng(banco_url):
    real = create_engine(banco_url)
    with real.connect() as con:
        transacao = con.begin()
        try:
            # O teste HTTP é sequencial. Todas as conexões usam a mesma transação
            # real, revertida ao terminar; previsões imutáveis não vazam à suíte.
            yield SimpleNamespace(begin=lambda: nullcontext(con), connect=lambda: nullcontext(con))
        finally:
            transacao.rollback()
    real.dispose()


def test_sessao_real_nao_acessa_pedido_alheio_e_snapshot_nao_muda(eng, tmp_path, monkeypatch):
    carregar_pasta(eng, AMOSTRA, dt.date(2026, 11, 12))
    cf = Cofre(gerar_chave())
    a, sa = S.criar_cliente(eng, "Teste funcional primeira certidão A")
    b, sb = S.criar_cliente(eng, "Teste funcional primeira certidão B")
    pedido = str(uuid.uuid4())
    with eng.begin() as con:
        for cid in (a, b):
            con.execute(
                text("""insert into negocio.conta_api (cliente_id, cnpj_hmac, cnpj_mascarado, termos_versao,
                contrato_versao, contrato_aceito_em, sinal_pago_em)
                values (:c, :h, '***', 'teste', 'teste', now(), now())"""),
                {"c": cid, "h": f"primeira-certidao-teste:{cid}"},
            )
        con.execute(
            text("insert into negocio.pedido (id, cliente_id, campos) values (:p, :c, '{}')"), {"p": pedido, "c": a}
        )
        con.execute(
            text("""insert into negocio.pedido_sugestao
            (pedido_id, motivo, otimizador_versao, premissas_versao, base, opcoes)
            values (:p, 'teste', 'teste', 'teste', '{}', cast(:o as jsonb))"""),
            {"p": pedido, "o": json.dumps([{"itens": [{"cod_imovel": CAR}]}])},
        )

    def entrada(cid):
        return E.EntradaCertidao(cid, pasta=tmp_path, cofre=cf)

    def operador(authorization: str | None = Header(default=None)):
        if authorization != "Bearer operador-teste":
            raise HTTPException(401)

    app = FastAPI()
    app.include_router(api.roteador(lambda _: eng, operador, entrada))
    monkeypatch.setattr(E, "LeitorClaude", modelo)
    with TestClient(app) as cl:
        h = {"Authorization": f"Bearer {sa}", "Content-Type": "application/pdf", "Idempotency-Key": chave()}
        params = {"pedido_id": pedido, "cod_imovel": CAR}
        alheio = cl.post(
            "/documentos/certidoes", params=params, content=PDF, headers={**h, "Authorization": f"Bearer {sb}"}
        )
        assert alheio.status_code == 404
        r = cl.post("/documentos/certidoes", params=params, content=PDF, headers=h)
        assert r.status_code == 201 and r.json()["previsao"]["disponivel"]
        doc = r.json()["id"]
        snapshot = entrada(a)._abrir(entrada(a)._linha(doc))["previsao"]
        assert {m["cod_imovel"] for m in snapshot["motor"]} == {CAR}
        with eng.begin() as con:
            con.execute(
                text("update titulo.certidao_alvo set ha_sobre_car=ha_sobre_car+1 where cod_imovel=:car"), {"car": CAR}
            )
        assert entrada(a)._abrir(entrada(a)._linha(doc))["previsao"] == snapshot
        with eng.begin() as con:
            con.execute(
                text("update titulo.certidao_alvo set ha_sobre_car=ha_sobre_car-1 where cod_imovel=:car"), {"car": CAR}
            )
        op = {"Authorization": "Bearer operador-teste", "Idempotency-Key": chave()}
        r = cl.post(f"/documentos/operacao/{a}/certidoes/{doc}/ler", headers=op)
        assert r.status_code == 200 and r.json()["estado"] == "lida"
        assert cl.get(f"/documentos/certidoes/{doc}", headers={"Authorization": f"Bearer {sb}"}).status_code == 404
        corpo = {
            "fonte": "conferencia_humana",
            "observado_em": dt.date.today().isoformat(),
            "situacao_real": "divergente",
            "conferido_por_pessoa": True,
        }
        assert cl.post(f"/documentos/operacao/{a}/certidoes/{doc}/gabarito", headers=op, json=corpo).status_code == 200
        sync = cl.post(f"/documentos/operacao/{a}/aprendizado/sincronizar", headers=op)
        assert sync.status_code == 200 and sync.json()["gabaritos"] >= 1
        repetida = cl.post(f"/documentos/operacao/{a}/aprendizado/sincronizar", headers=op)
        assert repetida.json() == {"previsoes": 0, "gabaritos": 0}
        with eng.connect() as con:
            referencias = (
                con.execute(
                    text("select referencia from aprendizado.gabarito where referencia like :p"),
                    {"p": f"empresa:{a}:%"},
                )
                .scalars()
                .all()
            )
        assert referencias and all(r.startswith(f"empresa:{a}:leitura:") for r in referencias)
        with eng.begin() as con:
            con.execute(
                text("update negocio.sessao set expira_em=now()-interval '1 minute' where cliente_id=:c"), {"c": a}
            )
        assert cl.get(f"/documentos/certidoes/{doc}", headers=h).status_code == 401
