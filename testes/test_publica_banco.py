"""Contrato pago da API: conta por empresa, franquia única de teste, cobrança e proteção dos dados.

O PostGIS é real; o Pix usa somente o modo de teste local. Não há chamada a um provedor de pagamento.
Os testes do transporte MCP ficam em test_servidor_mcp.py.
"""

import copy
import datetime as dt
import itertools
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz.carga import carregar_pasta
from raiz.pedidos import servico as S
from raiz.pessoal import gerar_chave
from raiz.publica import api
from raiz.publica import chaves as K
from raiz.publica import conta as CT
from raiz.publica import trabalhos as T
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
TODA_TERRA = ["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]
PEDIDO = {
    "meta": {"tipo": "creditos", "valor": 1_000_000},
    "cronograma": "profloresta",
    "onde": {"ufs": ["PA"], "biomas": ["Amazônia"]},
    "terra": TODA_TERRA,
}
SEQUENCIA = itertools.count(1)
PESSOAL = re.compile(r"'(nome[a-z_]*|cpf[a-z_]*|cnpj[a-z_]*|telefone|email|contato)'", re.I)


def _cnpj(n: int) -> str:
    """Documento sintético calculado em tempo de teste, nunca um documento pessoal no repositório."""
    d = f"12{n:010d}"
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(x) * w for x, w in zip(d, pesos, strict=True)) % 11
        d += str(0 if resto < 2 else 11 - resto)
    return d


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, negocio.oferta, negocio.cliente cascade"))
        c.execute(text("truncate negocio.interesse_dono, negocio.interesse_evento"))
    carregar_pasta(e, AMOSTRA, dt.date(2026, 11, 12))
    yield e
    e.dispose()


@pytest.fixture(scope="module", autouse=True)
def cofre():
    import raiz.pessoal as pessoal

    mp = pytest.MonkeyPatch()
    chave = SecretStr(gerar_chave())
    mp.setattr(pessoal, "config", lambda: type("C", (), {"chave_pessoal": chave})())
    mp.delenv("RAIZ_ABACATEPAY_CHAVE", raising=False)
    yield
    mp.undo()


@pytest.fixture
def empresa(eng):
    n = next(SEQUENCIA)
    cid, sessao = S.criar_cliente(eng, "Empresa de teste", f"compras{n}@empresa.example")
    cnpj = _cnpj(n)
    CT.abrir(eng, cid, cnpj, True)
    chave = K.criar(eng, cid, "agente de teste")
    return {"id": cid, "sessao": sessao, "cnpj": cnpj, **chave, "cliente_id": cid}


def _app(eng):
    app = FastAPI()
    app.mount("/v1", api.criar(lambda _: eng))
    return app


@pytest.fixture
def cl(eng):
    with TestClient(_app(eng)) as cliente:
        yield cliente


def _h(empresa, idempotencia=None):
    h = {"X-Chave-API": empresa["chave"]}
    if idempotencia is not None:
        h["Idempotency-Key"] = idempotencia
    return h


def _pessoa(empresa):
    return {"Authorization": f"Bearer {empresa['sessao']}"}


def _sem_pessoal(obj):
    assert not PESSOAL.search(str(obj))


def _pagar(eng, empresa, finalidade="recarga", valor=5000):
    cob = CT.criar_cobranca(eng, empresa["cliente_id"], finalidade, valor)
    with eng.connect() as c:
        externo = c.execute(
            text("select externo_id from negocio.cobranca_api where id = :i"), {"i": cob["id"]}
        ).scalar()
    assert CT.confirmar_cobranca(eng, externo) == "paga"
    assert CT.confirmar_cobranca(eng, externo) == "ja_paga"
    return cob


def _liberar(eng, empresa):
    CT.aceitar_contrato(eng, empresa["cliente_id"])
    _pagar(eng, empresa, "sinal", 2000)
    _pagar(eng, empresa)


def test_tres_testes_por_empresa_quarta_chamada_402(eng, cl, empresa):
    """Rotacionar chaves ou reabrir a conta não concede novos créditos."""
    h = _h(empresa)
    assert cl.post("/v1/disponibilidade", json=PEDIDO).status_code == 401
    assert cl.post("/v1/disponibilidade", json=PEDIDO, headers={"X-Chave-API": "raiz_invalida"}).status_code == 401
    for restante in (2, 1, 0):
        r = cl.post("/v1/disponibilidade", json=PEDIDO, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["creditos"]["p10"] <= r.json()["creditos"]["p50"]
        _sem_pessoal(r.json())
        assert CT.ver(eng, empresa["cliente_id"])["testes_restantes"] == restante
    r = cl.post("/v1/disponibilidade", json=PEDIDO, headers=h)
    assert r.status_code == 402, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["corrigir"] and r.json()["recarga"]["link_para_uma_pessoa"]
    assert "pix_copia_cola" not in r.text and "RAIZ-TESTE-PIX" not in r.text
    CT.abrir(eng, empresa["cliente_id"], empresa["cnpj"], True)
    segunda = K.criar(eng, empresa["cliente_id"])
    assert cl.post("/v1/disponibilidade", json=PEDIDO, headers=_h(segunda)).status_code == 402
    chamadas = [x for x in K.chamadas(eng, empresa["cliente_id"]) if x["ferramenta"] == "consultar_disponibilidade"]
    assert [x["status"] for x in chamadas] == [200, 200, 200, 402, 402]
    assert all(x["versao_modelo"] and x["versao_premissas"] for x in chamadas)
    assert all(x["preco_rs"] == 0 for x in chamadas)
    assert [x["tipo"] for x in CT.extrato(eng, empresa["cliente_id"])] == ["teste"] * 3


def test_mesmo_cnpj_nao_abre_outra_franquia(eng, empresa):
    cid, _ = S.criar_cliente(eng, "Outra empresa de teste", "outra@empresa.example")
    with pytest.raises(CT.ErroConta) as erro:
        CT.abrir(eng, cid, empresa["cnpj"], True)
    assert erro.value.status == 409
    with eng.connect() as con:
        dados = dict(
            con.execute(text("select * from negocio.conta_api where cliente_id=:c"), {"c": empresa["cliente_id"]})
            .mappings()
            .one()
        )
    assert empresa["cnpj"] not in str(dados)
    assert "*" in dados["cnpj_mascarado"]


def test_raspagem_bloqueia_todas_as_chaves_da_empresa(eng, empresa, monkeypatch):
    p = copy.deepcopy(CT.premissas())
    p["raspagem"]["municipios_consultados_mes_bloqueio"] = 2
    monkeypatch.setattr(CT, "premissas", lambda: p)
    outra = K.criar(eng, empresa["cliente_id"])
    with TestClient(_app(eng)) as cl:
        for cod in ("1500107", "1500206"):
            r = cl.post("/v1/disponibilidade", json={**PEDIDO, "onde": {"municipios": [cod]}}, headers=_h(empresa))
            assert r.status_code == 200, r.text
        for chave in (empresa, outra):
            r = cl.post("/v1/disponibilidade", json=PEDIDO, headers=_h(chave))
            assert r.status_code == 403 and r.json()["type"].endswith("conta_bloqueada"), r.text
            assert cl.get("/v1/pedidos", headers=_h(chave)).status_code == 403
    alertas = CT.alertas(eng, empresa["cliente_id"])
    assert any(a["tipo"] == "raspagem_bloqueio" for a in alertas)
    assert CT.ver(eng, empresa["cliente_id"])["testes_restantes"] == 1
    CT.aprovar_licenca(eng, empresa["cliente_id"])
    assert CT.vigiar_raspagem(eng, empresa["cliente_id"]) == "ok"


def test_limite_por_empresa_entre_chaves_e_rotas_com_retry_after(eng, empresa, monkeypatch):
    p = copy.deepcopy(CT.premissas())
    p["limites"]["por_minuto"] = 2
    monkeypatch.setattr(CT, "premissas", lambda: p)
    outra = K.criar(eng, empresa["cliente_id"])
    with TestClient(_app(eng)) as cl:
        assert cl.post("/v1/disponibilidade", json=PEDIDO, headers=_h(empresa)).status_code == 200
        assert cl.get("/v1/conta", headers=_h(outra)).status_code == 200
        r = cl.post("/v1/disponibilidade", json=PEDIDO, headers=_h(outra))
        assert r.status_code == 429, r.text
        assert int(r.headers["retry-after"]) > 0
        assert r.headers["content-type"].startswith("application/problem+json")
    # SlowAPI rejeita após as dependências: o débito da tentativa excedente é estornado.
    assert CT.ver(eng, empresa["cliente_id"])["testes_restantes"] == 2


@pytest.mark.parametrize("falta", ["contrato", "sinal"])
def test_saldo_nao_pula_sinal_e_contrato(eng, cl, empresa, falta):
    _pagar(eng, empresa)
    if falta == "contrato":
        _pagar(eng, empresa, "sinal", 2000)
    else:
        CT.aceitar_contrato(eng, empresa["cliente_id"])
    for caminho, metodo, corpo in (("/v1/pedidos", "post", PEDIDO), ("/v1/fazendas/PA-TESTE/analise", "get", None)):
        r = cl.request(metodo, caminho, json=corpo, headers=_h(empresa, "liberacao-pendente"))
        assert r.status_code == 403, r.text
        assert r.json()["type"].endswith("liberacao_pendente")
    assert CT.ver(eng, empresa["cliente_id"])["saldo_rs"] == 5000


@pytest.mark.parametrize("falha,status", [(S.ErroPedido("pedido inválido"), 422), (RuntimeError("segredo"), 500)])
def test_falha_estorna_teste_e_registra_erro(eng, cl, empresa, monkeypatch, falha, status):
    def falhar(*args):
        raise falha

    monkeypatch.setattr(S, "base_disponivel", falhar)
    r = cl.post("/v1/disponibilidade", json=PEDIDO, headers=_h(empresa))
    assert r.status_code == status, r.text
    assert "segredo" not in r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert CT.ver(eng, empresa["cliente_id"])["testes_restantes"] == 3
    assert K.chamadas(eng, empresa["cliente_id"])[-1]["status"] == status


def test_estorno_concorrente_de_dinheiro_acontece_uma_vez(eng, empresa):
    _pagar(eng, empresa)
    lanc = CT.cobrar(eng, empresa["cliente_id"], "pedir_lote")
    assert CT.ver(eng, empresa["cliente_id"])["saldo_rs"] == 4600
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: CT.estornar(eng, lanc), range(2)))
    assert CT.ver(eng, empresa["cliente_id"])["saldo_rs"] == 5000
    assert sum(x["tipo"] == "estorno" for x in CT.extrato(eng, empresa["cliente_id"])) == 1


def test_chamadas_concorrentes_nao_multiplicam_os_tres_testes(eng, empresa):
    def chamar(_):
        try:
            CT.cobrar(eng, empresa["cliente_id"], "consultar_disponibilidade")
            return 200
        except CT.ErroConta as ex:
            return ex.status

    with ThreadPoolExecutor(max_workers=8) as executor:
        resultados = list(executor.map(chamar, range(8)))
    assert resultados.count(200) == 3
    assert resultados.count(402) == 5
    assert CT.ver(eng, empresa["cliente_id"])["testes_restantes"] == 0


def test_chave_revogada_e_acoes_so_de_pessoa(eng, cl, empresa):
    assert cl.post("/v1/chaves", json={}, headers=_h(empresa)).status_code == 403
    assert cl.post("/v1/conta/contrato", headers=_h(empresa)).status_code == 403
    r = cl.post("/v1/chaves", json={"rotulo": "segunda chave"}, headers=_pessoa(empresa))
    assert r.status_code == 200 and r.json()["chave"].startswith("raiz_")
    assert "chave" not in cl.get("/v1/chaves", headers=_pessoa(empresa)).json()[0]
    assert cl.delete(f"/v1/chaves/{empresa['prefixo']}", headers=_pessoa(empresa)).status_code == 200
    assert cl.get("/v1/conta", headers=_h(empresa)).status_code == 401


def test_resposta_e_log_nao_expoem_dados_pessoais(eng, cl, empresa, monkeypatch):
    monkeypatch.setattr(
        S,
        "base_disponivel",
        lambda *args: {
            "fazendas": 2,
            "nome_proprietario": "Dono de teste",
            "cpf": "documento",
            "itens": [{"telefone": "telefone", "email": "pessoa@example.test", "hectares": 10}],
            "explicacao": "Consultar pessoa@example.test",
        },
    )
    r = cl.post("/v1/disponibilidade", json=PEDIDO, headers={**_h(empresa), "X-Agente-Modelo": "pessoa@example.test"})
    assert r.status_code == 200
    _sem_pessoal(r.json())
    assert "pessoa@example.test" not in r.text
    assert "Dono de teste" not in r.text
    assert K.chamadas(eng, empresa["cliente_id"])[-1]["agente_modelo"] == "<EMAIL>"


def test_lote_pago_tres_opcoes_e_isolamento_entre_empresas(eng, cl, empresa):
    _liberar(eng, empresa)
    h = _h(empresa, "lote-pago-unico")
    r = cl.post("/v1/pedidos", json=PEDIDO, headers=h)
    assert r.status_code == 202, r.text
    operacao = r.json()
    assert operacao["estado"] == "submitted" and operacao["resultado"] is None
    repetida = cl.post("/v1/pedidos", json=PEDIDO, headers=h)
    assert repetida.status_code == 202 and repetida.json()["pedido_id"] == operacao["pedido_id"]
    assert CT.ver(eng, empresa["cliente_id"])["saldo_rs"] == 4600
    concluida = T.executar_proximo(eng)
    assert concluida["pedido_id"] == operacao["pedido_id"] and concluida["estado"] == "completed"
    protocolo = cl.get(f"/v1/operacoes/{operacao['pedido_id']}", headers=_h(empresa))
    assert protocolo.status_code == 200, protocolo.text
    p = protocolo.json()["resultado"]
    assert set(p) == {"id"}  # snapshot da fila não expõe fazendas cuja exclusividade pode mudar
    r = cl.get(f"/v1/pedidos/{p['id']}/opcoes", headers=_h(empresa))
    assert r.status_code == 200, r.text
    assert {o["id"] for o in r.json()} == {"barata", "segura", "compacta"}
    _sem_pessoal(r.json())
    n = next(SEQUENCIA)
    cid, _ = S.criar_cliente(eng, "Outra empresa", f"isolada{n}@empresa.example")
    CT.abrir(eng, cid, _cnpj(n), True)
    outra = {"cliente_id": cid, **K.criar(eng, cid)}
    _liberar(eng, outra)
    r = cl.get(f"/v1/pedidos/{p['id']}/opcoes", headers=_h(outra))
    assert r.status_code == 404
    assert CT.ver(eng, cid)["testes_restantes"] == 3


def test_pix_de_recarga_vencido_nao_e_exibido(eng, cl, empresa):
    cob = CT.criar_cobranca(eng, empresa["cliente_id"], "recarga", 500)
    with eng.begin() as con:
        con.execute(
            text("update negocio.cobranca_api set expira_em=now()-interval '1 second' where id=:i"), {"i": cob["id"]}
        )
    r = cl.get(cob["link_para_uma_pessoa"])
    assert r.status_code == 404 and "RAIZ-TESTE-PIX" not in r.text


@pytest.mark.parametrize("estado,status", [("sem_saldo", 402), ("sem_liberacao", 403)])
def test_limite_tambem_conta_tentativas_recusadas(eng, empresa, monkeypatch, estado, status):
    p = copy.deepcopy(CT.premissas())
    p["limites"]["por_minuto"] = 2
    monkeypatch.setattr(CT, "premissas", lambda: p)
    with eng.begin() as con:
        con.execute(
            text("update negocio.conta_api set testes_restantes=0 where cliente_id=:c"), {"c": empresa["cliente_id"]}
        )
    rota = "/v1/disponibilidade" if estado == "sem_saldo" else "/v1/pedidos"
    with TestClient(_app(eng)) as cliente:
        assert cliente.post(rota, json=PEDIDO, headers=_h(empresa, "tentativa-recusada")).status_code == status
        assert cliente.post(rota, json=PEDIDO, headers=_h(empresa, "tentativa-recusada")).status_code == status
        assert cliente.post(rota, json=PEDIDO, headers=_h(empresa, "tentativa-recusada")).status_code == 429


def test_alcance_do_log_nao_aceita_texto_arbitrario():
    assert K._alcance_seguro(
        {
            "ufs": ["PA", "nome secreto"],
            "municipios": ["1500107", "telefone"],
            "biomas": ["Amazônia", "contato privado"],
            "meta": "texto",
        }
    ) == {
        "ufs": ["PA"],
        "municipios": ["1500107"],
        "biomas": ["Amazônia"],
        "meta": None,
    }
