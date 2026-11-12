"""Polígonos, isolamento por empresa e revisão sem contornar salvaguardas."""

import datetime as dt
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from raiz import salvaguardas as SG
from raiz.pedidos import api, oferta
from raiz.pedidos import servico as S

pytestmark = pytest.mark.banco
EV = {"sha256": "b" * 64, "data": "2026-01-01"}
COD = "PA-SALVAGUARDA-TESTE"


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as con:
        con.execute(
            text("""insert into funil.imovel (cod_imovel, uf, geom) values (:c, 'PA',
            ST_Multi(ST_GeomFromText('POLYGON((-50 -3,-49 -3,-49 -2,-50 -2,-50 -3))', 4674)))"""),
            {"c": COD},
        )
        linha = oferta.de_linha(
            {
                "cod_imovel": COD,
                "caminho_terra": "privada_matricula",
                "uf": "PA",
                "restauracao_area_ha": 2,
                "modo_restauracao": "plantio_total",
            }
        )
        con.execute(
            text("""insert into negocio.oferta (cod_imovel, atributos) values (:c, cast(:a as jsonb))"""),
            {"c": COD, "a": json.dumps(linha)},
        )
    yield e
    e.dispose()


def test_sobreposicao_real_e_reverificacao_da_oferta(eng):
    SG.registrar_programa(
        eng,
        SG.Programa(
            id="pa-contabil-2020",
            uf="PA",
            inicio="2020-01-01",
            fim="2025-12-31",
            fonte="https://exemplo.gov.br/redd",
            evidencia=EV,
            geometria={"type": "Polygon", "coordinates": [[[-50, -3], [-49.5, -3], [-49.5, -2], [-50, -2], [-50, -3]]]},
        ),
    )
    dados = SG.do_banco(eng, [COD])[COD]
    assert dados["redd_programas"][0]["area_ha"] > 0
    assert not dados["redd_cobertura_verificada"]
    assert not oferta.do_banco(eng).set_index("cod_imovel").loc[COD, "elegivel"]
    with pytest.raises(S.ErroPedido, match="salvaguardas"):
        SG.exigir_para_reserva(eng, [COD])
    ev = {**EV, "data": dt.date.today().isoformat()}
    SG.registrar_cobertura(eng, SG.Cobertura(uf="PA", evidencia=ev, valida_ate=dt.date.today()))
    SG.registrar_verificacao(
        eng,
        COD,
        SG.Verificacao(
            verificacao=ev,
            territorio_tradicional=False,
            exclusoes_conaredd={"pa-contabil-2020": ev},
        ),
    )
    assert oferta.do_banco(eng).set_index("cod_imovel").loc[COD, "elegivel"]
    SG.exigir_para_reserva(eng, [COD])
    geo = SG.camada(eng)
    assert geo["features"][0]["properties"]["inicio"] == "2020-01-01"


def test_revisao_tem_protocolo_criterios_e_credencial_humana(eng, monkeypatch):
    cid, sessao = S.criar_cliente(eng, "empresa de teste")
    _, sessao_outro = S.criar_cliente(eng, "outra empresa")
    pid = str(uuid.uuid4())
    with eng.begin() as con:
        con.execute(
            text("""insert into negocio.pedido (id, cliente_id, estado, campos, premissas_versao)
            values (:p, :c, 'lote_montado', '{}', 'teste')"""),
            {"p": pid, "c": cid},
        )
    app = FastAPI()
    app.include_router(api.roteador_cliente(lambda r: eng))
    app.include_router(api.roteador_interno(lambda r: eng))
    with TestClient(app) as cl:
        h = {"Authorization": f"Bearer {sessao}"}
        corpo = {"cod_imovel": COD, "motivo": "nota_de_risco"}
        r = cl.post(f"/pedidos/{pid}/revisoes", headers=h, json=corpo)
        assert r.status_code == 200
        rid = r.json()["revisao_id"]
        assert r.json()["criterios"]["regra"] == SG.VERSAO
        assert cl.post(f"/pedidos/{pid}/revisoes", headers=h, json=corpo).json()["revisao_id"] == rid
        assert (
            cl.get(f"/pedidos/{pid}/revisoes", headers={"Authorization": f"Bearer {sessao_outro}"}).status_code == 404
        )
        resolucao = {"revisor_id": str(uuid.uuid4()), "decisao": "corrigir_dados", "evidencia": EV}
        rota = f"/salvaguardas/revisoes/{rid}/resolver"
        assert cl.post(rota, json=resolucao).status_code == 403
        monkeypatch.setenv("RAIZ_REVISAO_HUMANA_TOKEN", "credencial-humana-teste")
        assert cl.post(rota, json=resolucao).status_code == 403
        assert cl.post(rota, json=resolucao, headers={"X-Revisao-Humana": "credencial-humana-teste"}).status_code == 200
        lista = cl.get(f"/pedidos/{pid}/revisoes", headers=h).json()
        assert lista[0]["estado"] == "resolvida" and lista[0]["decisao"] == "corrigir_dados"
        assert "revisor_id" not in lista[0]  # cliente não recebe identidade do revisor
