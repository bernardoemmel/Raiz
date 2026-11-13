"""Upload real da aplicação, com autenticação/isolamento e PDF sintético; nenhuma API de modelo é chamada."""

import uuid

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from raiz.documentos.certidao import api
from raiz.documentos.certidao import entrada as E
from raiz.pessoal import Cofre, gerar_chave
from testes.test_primeira_certidao import CAR, PDF, chave, modelo, previsao


@pytest.fixture
def web(tmp_path, monkeypatch):
    cofre = Cofre(gerar_chave())
    stores = {}

    def entrada(cid):
        return stores.setdefault(cid, E.EntradaCertidao(cid, pasta=tmp_path, cofre=cofre))

    def operador(authorization: str | None = Header(default=None)):
        if authorization != "Bearer operador":
            raise HTTPException(401, "operador_nao_autorizado")

    pedido = str(uuid.uuid4())

    def permitir(eng, cid, pid, car):
        if cid != 7 or pid != pedido or car != CAR:
            raise E.ErroEntrada(404, "pedido_nao_encontrado")

    monkeypatch.setattr(api.pedidos, "cliente_da_sessao", lambda eng, token: {"pessoa7": 7, "pessoa8": 8}.get(token))
    monkeypatch.setattr(api.conta, "exigir_liberacao", lambda *args: None)
    monkeypatch.setattr(api, "limitar", lambda *args: None)
    monkeypatch.setattr(api, "autorizar_car", permitir)
    monkeypatch.setattr(api, "capturar_previsao_banco", lambda *args: previsao())
    monkeypatch.setattr(E, "LeitorClaude", modelo)
    app = FastAPI()
    app.include_router(api.roteador(lambda _: object(), operador, entrada))
    with TestClient(app) as c:
        yield c, pedido, entrada


def upload(c, pedido, **kw):
    headers = {"Authorization": "Bearer pessoa7", "Content-Type": "application/pdf", "Idempotency-Key": chave()}
    headers.update(kw.pop("headers", {}))
    return c.post(
        "/documentos/certidoes",
        params={"pedido_id": pedido, "cod_imovel": CAR},
        headers=headers,
        content=kw.pop("pdf", PDF),
        **kw,
    )


def test_upload_consulta_leitura_humana_e_gabarito(web):
    c, pedido, entrada = web
    r = upload(c, pedido)
    assert r.status_code == 201 and r.headers["cache-control"] == "private, no-store"
    d = r.json()
    doc = d["id"]
    assert d["estado"] == "recebida" and d["gabaritos"] == []
    h = {"Authorization": "Bearer pessoa7"}
    assert c.get(f"/documentos/certidoes/{doc}", headers=h).status_code == 200
    assert (
        c.post(f"/documentos/operacao/7/certidoes/{doc}/ler", headers={**h, "Idempotency-Key": chave()}).status_code
        == 401
    )
    op = {"Authorization": "Bearer operador", "Idempotency-Key": chave()}
    lida = c.post(f"/documentos/operacao/7/certidoes/{doc}/ler", headers=op)
    assert lida.status_code == 200 and lida.json()["estado"] == "lida"
    assert c.post(f"/documentos/operacao/7/certidoes/{doc}/ler", headers=op).json() == lida.json()
    pdf = c.get(f"/documentos/operacao/7/certidoes/{doc}/original.pdf", headers=op)
    assert pdf.status_code == 200 and pdf.content == PDF
    assert pdf.headers["content-disposition"].startswith("attachment")
    assert pdf.headers["cache-control"] == "private, no-store"
    assert c.get(f"/documentos/operacao/7/certidoes/{doc}/original.pdf", headers=h).status_code == 401
    corpo = {
        "fonte": "conferencia_humana",
        "observado_em": previsao()["capturada_em"][:10],
        "situacao_real": "divergente",
        "campos": {"area_ha": "250"},
        "conferido_por_pessoa": True,
    }
    revisada = c.post(f"/documentos/operacao/7/certidoes/{doc}/gabarito", json=corpo, headers=op)
    assert revisada.status_code == 200 and revisada.json()["estado"] == "conferida_por_pessoa"
    assert entrada(7).armazem.gabaritos()
    assert (
        c.get(f"/documentos/operacao/7/certidoes/{doc}", headers=op).json()["gabaritos"] == revisada.json()["gabaritos"]
    )


def test_sessao_empresa_car_e_id_sao_verificados(web):
    c, pedido, entrada = web
    assert upload(c, pedido, headers={"Authorization": ""}).status_code == 401
    assert upload(c, pedido, headers={"Authorization": "Bearer raiz_chave-de-agente"}).status_code == 403
    assert upload(c, pedido, headers={"Authorization": "Bearer pessoa8"}).status_code == 404
    assert upload(c, str(uuid.uuid4())).status_code == 404
    doc = upload(c, pedido).json()["id"]
    resposta = c.get(f"/documentos/certidoes/{doc}", headers={"Authorization": "Bearer pessoa8"})
    assert resposta.status_code == 404 and resposta.headers["cache-control"] == "private, no-store"
    assert entrada(8).armazem.leituras() == []
    assert c.get(f"/documentos/certidoes/{doc}").status_code == 401


def test_formatos_invalidos_nao_ecoam_payload_pessoal(web):
    c, pedido, _ = web
    assert upload(c, pedido, headers={"Content-Type": "text/plain"}).status_code == 415
    assert upload(c, pedido, pdf=b"arquivo pessoal invalido").status_code == 422
    assert upload(c, pedido, headers={"Content-Length": str(E.MAX_BYTES + 1)}).status_code == 413
    r = upload(c, pedido, headers={"Idempotency-Key": "texto pessoal inesperado"})
    assert r.status_code == 422 and "pessoal inesperado" not in r.text
    assert r.headers["cache-control"] == "private, no-store"


def test_modelo_cliente_ou_confirmacao_ausente_nao_criam_gabarito(web):
    c, pedido, entrada = web
    doc = upload(c, pedido).json()["id"]
    op = {"Authorization": "Bearer operador", "Idempotency-Key": chave()}
    c.post(f"/documentos/operacao/7/certidoes/{doc}/ler", headers=op)
    corpo = {
        "fonte": "modelo",
        "observado_em": previsao()["capturada_em"][:10],
        "situacao_real": "conferida",
        "conferido_por_pessoa": True,
    }
    assert c.post(f"/documentos/operacao/7/certidoes/{doc}/gabarito", json=corpo, headers=op).status_code == 422
    corpo["fonte"] = "conferencia_humana"
    corpo["conferido_por_pessoa"] = False
    assert c.post(f"/documentos/operacao/7/certidoes/{doc}/gabarito", json=corpo, headers=op).status_code == 422
    corpo["conferido_por_pessoa"] = True
    assert (
        c.post(
            f"/documentos/operacao/7/certidoes/{doc}/gabarito",
            json=corpo,
            headers={"Authorization": "Bearer pessoa7", "Idempotency-Key": chave()},
        ).status_code
        == 401
    )
    assert entrada(7).armazem.gabaritos() == []
