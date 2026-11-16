"""Entrega de login humano por SMTP com TLS. Nenhuma mensagem de dono passa por este módulo."""

import os
import smtplib
import ssl
from email.headerregistry import Address
from email.message import EmailMessage
from urllib.parse import unquote, urlsplit


class ErroEnvioLogin(RuntimeError):
    """Falha operacional genérica: não leva endereço, link, segredo ou resposta do SMTP ao cliente."""


def origem_front() -> str:
    url = os.environ.get("RAIZ_FRONT_URL", "").rstrip("/")
    if any(c.isspace() or c == "\\" for c in unquote(url)):
        raise ValueError("defina RAIZ_FRONT_URL com a URL pública do painel")
    u = urlsplit(url)
    # A leitura da porta também valida formatos como :texto e valores fora do intervalo TCP.
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.port == 0:
        raise ValueError("defina RAIZ_FRONT_URL com a URL pública do painel")
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("o painel precisa de HTTPS")
    return url


def enviador():
    """Retorna o enviador configurado; ausente, o login permanece indisponível, sem simular envio."""
    host = os.environ.get("RAIZ_SMTP_HOST")
    if not host:
        return None
    modo = os.environ.get("RAIZ_SMTP_TLS", "ssl")
    porta = int(os.environ.get("RAIZ_SMTP_PORT", "465" if modo == "ssl" else "587"))
    remetente = os.environ.get("RAIZ_SMTP_FROM", "")
    usuario = os.environ.get("RAIZ_SMTP_USER")
    senha = os.environ.get("RAIZ_SMTP_PASSWORD")
    if modo not in {"ssl", "starttls"} or not remetente or any(c in remetente for c in "\n\r"):
        raise ValueError("configure remetente e TLS do SMTP (ssl ou starttls)")
    if not 0 < porta < 65536 or any(c.isspace() for c in host) or "://" in host:
        raise ValueError("configure host e porta do SMTP")
    if bool(usuario) != bool(senha):
        raise ValueError("configure usuário e senha do SMTP juntos")
    teste = EmailMessage()
    teste["From"] = remetente
    enderecos = teste["From"].addresses
    if teste["From"].defects or len(enderecos) != 1 or not enderecos[0].domain:
        raise ValueError("configure um único endereço remetente do SMTP")

    def enviar(email: str, link: str) -> None:
        try:
            # Só um destinatário; strings de cabeçalho injetadas não podem abrir uma conexão SMTP.
            destinatario = Address(addr_spec=email)
            if not destinatario.domain:
                raise ValueError("destinatário inválido")
            mensagem = EmailMessage()
            mensagem["From"], mensagem["To"] = remetente, destinatario
            mensagem["Subject"] = "Seu link de entrada na Raíz"
            mensagem.set_content(
                "Abra este link para entrar na Raíz. Ele vence em 30 minutos e só pode ser usado uma vez.\n\n"
                f"{link}\n\nEntrar não aprova uma reserva nem faz pagamento."
            )
            contexto = ssl.create_default_context()
            if modo == "ssl":
                conexao = smtplib.SMTP_SSL(host, porta, timeout=3, context=contexto)
            else:
                conexao = smtplib.SMTP(host, porta, timeout=3)
            with conexao as smtp:
                if modo == "starttls":
                    smtp.ehlo()
                    smtp.starttls(context=contexto)
                    smtp.ehlo()
                if usuario:
                    smtp.login(usuario, senha)
                recusados = smtp.send_message(mensagem)
                if recusados:
                    raise ErroEnvioLogin("envio de login por e-mail indisponível")
        except (smtplib.SMTPException, OSError, ValueError):
            # Uma resposta SMTP pode conter destinatário ou segredo. Não a incluir nem como causa da exceção.
            raise ErroEnvioLogin("envio de login por e-mail indisponível") from None

    return enviar
