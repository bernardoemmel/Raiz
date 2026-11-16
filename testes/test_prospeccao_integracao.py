"""Integração privada de versões, exportações e auditoria, com PostGIS real."""

import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import text

from raiz import prospeccao_api as api
from raiz import prospeccao_servico as servico
from raiz.prospeccao_acesso import ErroAcesso
from testes.test_prospeccao_versoes import alterar, base, escalar, liberar  # noqa: F401

pytestmark = pytest.mark.banco


def test_exportacoes_marcadas_mesmo_cliente_historico_e_rollback(base, monkeypatch):  # noqa: F811
    eng, (cliente, outro), _, adicionar = base
    car = adicionar()
    liberar(eng, cliente, car)
    liberar(eng, outro, car)
    monkeypatch.delenv("RAIZ_PROTECAO_CHAVES", raising=False)
    monkeypatch.delenv("RAIZ_PROTECAO_VERSAO", raising=False)
    with pytest.raises(ErroAcesso) as falha:
        servico.exportar_ficha(eng, cliente, car, formato="json")
    assert falha.value.status == 503
    assert escalar(eng, "select count(*) from negocio.prospeccao_ficha_consulta where cliente_id=:c", c=cliente) == 0
    monkeypatch.setenv("RAIZ_PROTECAO_CHAVES", json.dumps({"ensaio": "chave-apenas-de-teste-" * 3}))
    monkeypatch.setenv("RAIZ_PROTECAO_VERSAO", "ensaio")
    j = json.loads(servico.exportar_ficha(eng, cliente, car, formato="json"))
    marca = j["protecao"]["marca"]
    assert j["ficha"]["o_que_mudou"]["primeira_consulta"] is True
    csv = servico.exportar_ficha(eng, cliente, car, formato="csv").decode()
    pdf = servico.exportar_ficha(eng, cliente, car, formato="pdf")
    assert marca in csv and "sentinela" in csv.lower()
    paginas = PdfReader(io.BytesIO(pdf)).pages
    assert paginas and all(marca in p.extract_text() for p in paginas)
    outra = json.loads(servico.exportar_ficha(eng, outro, car, formato="json"))
    assert outra["protecao"]["marca"] != marca
    alterar(eng, car, embargo_ha=12)
    anterior = escalar(eng, "select versao_id from negocio.prospeccao_ficha_consulta where cliente_id=:c", c=cliente)
    with monkeypatch.context() as mp:

        def falhar(*args, **kwargs):
            raise RuntimeError("falha de renderização")

        mp.setattr("raiz.prospeccao_pdf.gerar_pdf", falhar)
        with pytest.raises(RuntimeError):
            servico.exportar_ficha(eng, cliente, car, formato="pdf")
    assert (
        escalar(eng, "select versao_id from negocio.prospeccao_ficha_consulta where cliente_id=:c", c=cliente)
        == anterior
    )
    historico = servico.historico_ficha(eng, cliente, car)
    assert historico["historico"]
    assert (
        escalar(eng, "select versao_id from negocio.prospeccao_ficha_consulta where cliente_id=:c", c=cliente)
        == anterior
    )
    atual = servico.consultar_ficha(eng, cliente, car)
    assert any(x["tipo"] == "embargos" for x in atual["o_que_mudou"]["mudancas"])
    assert escalar(eng, "select count(*) from negocio.prospeccao_movimento where cliente_id=:c", c=cliente) == 0
    assert (
        escalar(
            eng,
            "select count(*) from negocio.prospeccao_evento_protecao where cliente_id=:c and status>=500",
            c=cliente,
        )
        == 2
    )


def test_http_exportacao_historico_pagos_e_sem_cache(base, monkeypatch):  # noqa: F811
    eng, (cid, _), _, adicionar = base
    car = adicionar()
    monkeypatch.setattr(servico.pedidos, "cliente_da_sessao", lambda _, t: cid if t == "sessao-fixture" else None)
    monkeypatch.setenv("RAIZ_PROTECAO_CHAVES", json.dumps({"ensaio": "chave-apenas-de-teste-" * 3}))
    monkeypatch.setenv("RAIZ_PROTECAO_VERSAO", "ensaio")
    app = FastAPI()
    app.include_router(api.roteador(lambda _: eng))
    with TestClient(app) as cl:
        cl.headers["Authorization"] = "Bearer sessao-fixture"
        rotas = [f"/prospeccao/fichas/{car}/exportar?formato=json", f"/prospeccao/fichas/{car}/historico"]
        for rota in rotas:
            r = cl.get(rota)
            assert r.status_code == 402
            assert r.headers["cache-control"] == "private, no-store"
        liberar(eng, cid, car)
        for rota in rotas:
            r = cl.get(rota)
            assert r.status_code == 200
            assert r.headers["cache-control"] == "private, no-store" and r.headers["vary"] == "Authorization"
            assert "nome_proprietario" not in r.text
        assert cl.get(f"/prospeccao/fichas/{car}/exportar?formato=zip").status_code == 422


def test_historico_reprojeta_observacao_legada(base):  # noqa: F811
    eng, (cid, _), _, adicionar = base
    car = adicionar()
    liberar(eng, cid, car)
    servico.consultar_ficha(eng, cid, car)
    alterar(eng, car, embargo_ha=1)
    # Simula dado legado fora do contrato: a fronteira de leitura também deve fechá-lo.
    mudancas = [
        {
            "tipo": "embargos",
            "campo": "embargos",
            "depois": {"area": {"valor": 1, "unidade": "ha", "contato": "NAO_PUBLICAR"}, "nome": "NAO_PUBLICAR"},
        },
        {"tipo": "nome", "campo": "nome", "depois": "NAO_PUBLICAR"},
    ]
    with eng.begin() as con:
        con.execute(
            text("""insert into negocio.prospeccao_ficha_observacao
            (cod_imovel,versao_id,anterior_id,origem,mudancas)
            select cod_imovel,versao_id,anterior_id,origem,cast(:mudancas as jsonb)
            from negocio.prospeccao_ficha_observacao where cod_imovel=:car order by id desc limit 1"""),
            {"car": car, "mudancas": json.dumps(mudancas)},
        )
    assert "NAO_PUBLICAR" not in json.dumps(servico.historico_ficha(eng, cid, car))
