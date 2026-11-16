"""Transporte em memória: nenhum evento de teste é enviado para serviço externo."""

import contextlib
import io
import json
import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from raiz.observabilidade import Erros, do_config, evento_seguro
from raiz.privacidade import FormatadorJSON
from testes.test_seguranca_api import app_teste


class TransporteMemoria(Transport):
    def __init__(self):
        super().__init__()
        self.eventos = []

    def capture_envelope(self, envelope):
        self.eventos.extend(item.payload.json for item in envelope.items)


def test_json_em_uma_linha_sanitiza_mensagem_traceback_e_descarta_extras():
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(FormatadorJSON())
    log = logging.Logger("teste")
    log.addHandler(handler)
    try:
        raise ValueError("nome=Pessoa Sintética, pessoa@example.invalid")
    except ValueError:
        log.exception("falha %s\nsegunda linha", "token=segredo", extra={"dono": "Pessoa Sintética", "status": 500})
    linhas = saida.getvalue().splitlines()
    assert len(linhas) == 1
    dado = json.loads(linhas[0])
    assert dado["status"] == 500 and dado["nivel"] == "ERROR"
    assert "ValueError" in dado["excecao"]
    for pessoal in ("Pessoa Sintética", "pessoa@example.invalid", "segredo", "dono"):
        assert pessoal not in linhas[0]


def test_falha_de_formatacao_nao_dispara_logging_com_original_em_claro():
    record = logging.LogRecord("teste", logging.ERROR, "", 1, "nome=%s", (), None)
    record.duracao_ms = float("nan")
    dado = json.loads(FormatadorJSON().format(record))
    assert dado["mensagem"] == "[log suprimido: formatação indisponível]"
    assert "nome" not in json.dumps(dado)


def test_evento_descarta_todos_os_campos_de_conteudo_e_preserva_local_da_falha():
    pessoal = "nome=Pessoa Sintética, contato@example.invalid, token=segredo"
    evento = {
        "message": pessoal,
        "request": {"headers": {"Authorization": pessoal}, "url": pessoal, "data": pessoal},
        "user": {"id": pessoal, "ip_address": "192.0.2.1"},
        "breadcrumbs": [{"message": pessoal}],
        "extra": {"documento": pessoal},
        "contexts": {"trace": {"data": pessoal}},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": pessoal,
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "raiz/api.py",
                                "lineno": 100,
                                "vars": {"dono": pessoal},
                                "context_line": pessoal,
                            },
                            {"filename": "/tmp/" + pessoal, "lineno": 1},
                        ]
                    },
                }
            ]
        },
    }
    limpo = evento_seguro(evento)
    assert limpo["exception"]["values"][0]["stacktrace"]["frames"] == [
        {"filename": "raiz/api.py", "lineno": 100, "in_app": True}
    ]
    for palavra in ("Pessoa", "contato@", "segredo", "192.0.2.1", "request", "breadcrumbs", "vars", "contexts"):
        assert palavra not in json.dumps(limpo)


def test_sdk_transporta_apenas_evento_filtrado_e_erro_http_continua_generico():
    transporte = TransporteMemoria()
    erros = Erros("http://somente-teste@localhost:9999/1", transporte=transporte)
    try:
        cliente = TestClient(app_teste(erros=erros), raise_server_exceptions=False)
        resposta = cliente.get("/erro?token=segredo", headers={"Authorization": "Bearer segredo"})
        assert resposta.status_code == 500
        assert resposta.json() == {
            "type": "about:blank",
            "title": "Erro interno",
            "status": 500,
            "detail": "erro interno",
        }
        assert resposta.headers["content-type"].startswith("application/problem+json")
        assert len(transporte.eventos) == 1
        evento = transporte.eventos[0]
        assert evento["exception"]["values"][0]["type"] == "ValueError"
        assert "conteúdo desta exceção" not in json.dumps(evento)
        assert "segredo" not in json.dumps(evento)
        assert set(evento) == {"exception", "platform", "level", "event_id"}
    finally:
        erros.fechar()


def test_sem_dsn_nao_cria_cliente_nem_envia():
    assert do_config(SimpleNamespace()) is None


@pytest.mark.parametrize("banco_ok", [True, False])
def test_saude_mantem_contrato_e_nao_expoe_erro_de_banco(banco_ok):
    from raiz.api import criar_app

    class Banco:
        @contextlib.contextmanager
        def connect(self):
            if not banco_ok:
                raise RuntimeError("postgres://contato@example.invalid:segredo@localhost")
            yield self

        def execute(self, _sql):
            pass

    cliente = TestClient(criar_app(engine=Banco(), grafo=object(), whatsapp=False))
    resposta = cliente.get("/saude")
    assert resposta.status_code == (200 if banco_ok else 503)
    if banco_ok:
        assert resposta.json() == {"ok": True}
    assert "segredo" not in resposta.text and "contato@" not in resposta.text


def test_log_http_usa_rota_parametrizada_sem_query_corpo_ou_cabecalho(caplog):
    from fastapi import FastAPI

    from raiz.seguranca_api import SegurancaAPI

    app = FastAPI()

    @app.get("/arquivo/{nome}")
    def arquivo(nome: str):
        return {"ok": True}

    app.add_middleware(SegurancaAPI)
    with caplog.at_level(logging.INFO, logger="raiz.seguranca_api"):
        resposta = TestClient(app).get("/arquivo/pessoa@example.invalid?token=segredo")
    registros = [r for r in caplog.records if getattr(r, "evento", None) == "http"]
    assert len(registros) == 1
    dado = json.loads(FormatadorJSON().format(registros[0]))
    assert dado["rota"] == "/arquivo/{nome}"
    assert dado["requisicao_id"] == resposta.headers["x-request-id"]
    assert "pessoa@example.invalid" not in json.dumps(dado) and "segredo" not in json.dumps(dado)


def test_lifespan_fecha_contador_e_transporte(monkeypatch):
    from raiz.api import criar_app

    fechados = []

    class Contador:
        async def espera(self, *args):
            return 0

        async def fechar(self):
            fechados.append("valkey")

    class Monitor:
        def fechar(self):
            fechados.append("glitchtip")

    monkeypatch.setattr("raiz.limites.do_config", lambda _cfg: Contador())
    monkeypatch.setattr("raiz.observabilidade.do_config", lambda _cfg: Monitor())
    with TestClient(criar_app(grafo=object(), whatsapp=False)) as cliente:
        assert cliente.get("/rota-ausente").status_code == 404
    assert fechados == ["valkey", "glitchtip"]
