"""Login humano com SMTP completamente simulado: TLS obrigatório e origem definida pelo operador."""

import smtplib
import ssl

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.pedidos import servico as S
from raiz.pedidos.api import roteador_cliente
from raiz.publica import email_login as E
from raiz.publica.pagina_aprovacao import pagina


@pytest.fixture(autouse=True)
def sem_rede_e_configuracao_isolada(monkeypatch):
    for chave in ("HOST", "PORT", "FROM", "USER", "PASSWORD", "TLS"):
        monkeypatch.delenv("RAIZ_SMTP_" + chave, raising=False)
    monkeypatch.delenv("RAIZ_FRONT_URL", raising=False)
    monkeypatch.setattr(S, "ENVIO_LINK", None)

    def proibido(*args, **kwargs):
        pytest.fail("teste tentou abrir conexão SMTP não simulada")

    monkeypatch.setattr(smtplib, "SMTP", proibido)
    monkeypatch.setattr(smtplib, "SMTP_SSL", proibido)


def configurar(monkeypatch, modo="ssl"):
    for chave, valor in {
        "HOST": "smtp.example.test",
        "FROM": "Raíz <login@raiz.example>",
        "USER": "conta-de-teste",
        "PASSWORD": "segredo-sintetico",
        "TLS": modo,
    }.items():
        monkeypatch.setenv("RAIZ_SMTP_" + chave, valor)


@pytest.mark.parametrize(
    "modo,porta,ordem",
    [
        ("ssl", 465, ["conectar_ssl", "login", "enviar"]),
        ("starttls", 587, ["conectar", "ehlo", "tls", "ehlo", "login", "enviar"]),
    ],
)
def test_smtp_valida_certificado_e_autentica_so_depois_de_tls(monkeypatch, modo, porta, ordem):
    configurar(monkeypatch, modo)
    eventos, mensagens = [], []

    def conferir(contexto):
        assert contexto.check_hostname and contexto.verify_mode == ssl.CERT_REQUIRED

    class SMTP:
        def __init__(self, host, porta_recebida, timeout, context=None):
            assert host == "smtp.example.test" and porta_recebida == porta and timeout == 3
            if modo == "ssl":
                conferir(context)
            eventos.append("conectar_ssl" if context else "conectar")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            eventos.append("ehlo")

        def starttls(self, context):
            conferir(context)
            eventos.append("tls")

        def login(self, usuario, senha):
            assert usuario == "conta-de-teste" and senha == "segredo-sintetico"
            eventos.append("login")

        def send_message(self, mensagem):
            eventos.append("enviar")
            mensagens.append(mensagem)
            return {}

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    link = "https://painel.raiz.example/#/entrar/token-sintetico"
    E.enviador()("pessoa@empresa.example", link)
    assert eventos == ordem
    m = mensagens[0]
    assert str(m["To"]) == "pessoa@empresa.example"
    assert m["Bcc"] is None and m["Cc"] is None
    assert link in m.get_content() and "não aprova uma reserva nem faz pagamento" in m.get_content()


def test_smtp_ausente_nao_simula_envio():
    assert E.enviador() is None


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("TLS", "plain"),
        ("TLS", "none"),
        ("PORT", "0"),
        ("PORT", "texto"),
        ("PORT", "65536"),
        ("HOST", "smtp.example\r\nmalicioso"),
        ("FROM", "a@example.test\r\nBcc: outro@example.test"),
        ("FROM", "a@example.test, b@example.test"),
        ("PASSWORD", ""),
    ],
)
def test_configuracao_smtp_invalida_falha_antes_da_conexao(monkeypatch, campo, valor):
    configurar(monkeypatch)
    monkeypatch.setenv("RAIZ_SMTP_" + campo, valor)
    with pytest.raises(ValueError):
        E.enviador()


@pytest.mark.parametrize(
    "endereco", ["sem-arroba", "a@example.test\r\nBcc: outro@example.test", "a@example.test, outro@example.test"]
)
def test_destinatario_nao_pode_injetar_cabecalho_ou_adicionar_pessoa(monkeypatch, endereco):
    configurar(monkeypatch)
    with pytest.raises(E.ErroEnvioLogin, match="indisponível"):
        E.enviador()(endereco, "https://painel.raiz.example/#/entrar/teste")


def test_erro_smtp_nao_reproduz_endereco_link_ou_segredo(monkeypatch):
    configurar(monkeypatch)

    def falhar(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"conta-privada@example.test segredo-do-provedor")

    monkeypatch.setattr(smtplib, "SMTP_SSL", falhar)
    with pytest.raises(E.ErroEnvioLogin) as erro:
        E.enviador()("pessoa@empresa.example", "https://painel.raiz.example/#/entrar/token-sensivel")
    assert str(erro.value) == "envio de login por e-mail indisponível"
    assert erro.value.__suppress_context__


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://painel.example",
        "https://usuario:senha@painel.example",
        "https://painel.example?destino=externo",
        "https://painel.example/#externo",
        "https://painel.example:porta",
        "https://painel.example:0",
        "https://painel.example/%0d%0aoutro",
        "https://painel.example\\outro",
    ],
)
def test_origem_configurada_invalida_e_rejeitada(monkeypatch, url):
    monkeypatch.setenv("RAIZ_FRONT_URL", url)
    with pytest.raises(ValueError):
        E.origem_front()


@pytest.mark.parametrize(
    "url", ["https://painel.raiz.example/Raiz/", "http://localhost:5173/", "http://127.0.0.1:8000/"]
)
def test_origem_https_ou_local_preserva_caminho_do_painel(monkeypatch, url):
    monkeypatch.setenv("RAIZ_FRONT_URL", url)
    assert E.origem_front() == url.rstrip("/")


def cliente():
    app = FastAPI()
    app.include_router(roteador_cliente(lambda _: object()))
    return TestClient(app)


def test_entrar_nao_usa_origin_host_ou_forwarded_do_solicitante(monkeypatch):
    monkeypatch.setenv("RAIZ_FRONT_URL", "https://painel.raiz.example/Raiz/")
    monkeypatch.setattr(S, "ENVIO_LINK", lambda *args: None)
    chamadas = []
    monkeypatch.setattr(S, "pedir_link", lambda eng, email, base: chamadas.append((email, base)))
    with cliente() as cl:
        r = cl.post(
            "/entrar",
            json={"email": "pessoa@empresa.example"},
            headers={
                "Origin": "https://invasor.example",
                "Host": "invasor.example",
                "X-Forwarded-Host": "invasor.example",
                "X-Forwarded-Proto": "http",
            },
        )
    assert r.status_code == 200 and r.json() == {"enviado": True}
    assert chamadas == [("pessoa@empresa.example", "https://painel.raiz.example/Raiz")]


@pytest.mark.parametrize("falha", ["sem_smtp", "sem_origem", "origem_invalida", "smtp_recusou"])
def test_login_indisponivel_retorna_503_generico_sem_stack(monkeypatch, falha):
    chamadas = []
    monkeypatch.setattr(S, "pedir_link", lambda *args: chamadas.append(args))
    if falha != "sem_smtp":
        monkeypatch.setattr(S, "ENVIO_LINK", lambda *args: None)
    if falha != "sem_origem":
        monkeypatch.setenv("RAIZ_FRONT_URL", "https://painel.raiz.example")
    if falha == "origem_invalida":
        monkeypatch.setenv("RAIZ_FRONT_URL", "https://segredo:privado@invasor.example")
    if falha == "smtp_recusou":

        def falhar(*args):
            raise E.ErroEnvioLogin("resposta sensível simulada")

        monkeypatch.setattr(S, "pedir_link", falhar)
    with cliente() as cl:
        r = cl.post("/entrar", json={"email": "pessoa@empresa.example"})
    assert r.status_code == 503
    assert r.json() == {"detail": "envio de login por e-mail indisponível"}
    assert not chamadas


def test_pagina_de_aprovacao_nao_cacheia_nem_compartilha_referer():
    r = pagina("token-sintetico-de-aprovacao")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    assert "connect-src 'self'" in r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "Aprovar e gerar Pix" in r.body.decode()


def test_starttls_falho_nunca_tenta_autenticar_ou_enviar(monkeypatch):
    configurar(monkeypatch, "starttls")
    eventos = []

    class SemTLS:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def ehlo(self):
            eventos.append("ehlo")

        def starttls(self, context):
            eventos.append("tls_recusado")
            raise smtplib.SMTPNotSupportedError("TLS indisponível")

        def login(self, *args):
            pytest.fail("tentou autenticar sem TLS")

        def send_message(self, *args):
            pytest.fail("tentou enviar sem TLS")

    monkeypatch.setattr(smtplib, "SMTP", SemTLS)
    with pytest.raises(E.ErroEnvioLogin):
        E.enviador()("pessoa@empresa.example", "https://painel.raiz.example/#/entrar/teste")
    assert eventos == ["ehlo", "tls_recusado"]
