"""Eventos mínimos para o GlitchTip, sem conteúdo de requisição, exceção ou variáveis locais.

A lista de campos é reconstruída antes do transporte: filtros de chave e NER não são
uma autorização para enviar texto livre de documentos ou dados do dono ao monitoramento.
"""

from __future__ import annotations

import re
import traceback
from pathlib import Path

from raiz import RAIZ_REPO

_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z0-9_.<>-]{0,150}\Z")
_ARQUIVO = re.compile(r"(?:raiz|motor)/[a-zA-Z0-9_/.-]+\.py\Z")


def evento_seguro(evento: dict, _hint: dict | None = None) -> dict:
    """Ignora request, user, extra, contexts, breadcrumbs, mensagens e locais, mesmo adicionados pelo SDK."""
    valores = []
    for valor in evento.get("exception", {}).get("values", [])[-5:]:
        tipo = str(valor.get("type", "Erro"))
        if not _IDENTIFICADOR.fullmatch(tipo):
            tipo = "Erro"
        frames = []
        for frame in valor.get("stacktrace", {}).get("frames", [])[-30:]:
            arquivo = str(frame.get("filename", ""))
            if not _ARQUIVO.fullmatch(arquivo) or ".." in Path(arquivo).parts:
                continue
            numero = frame.get("lineno")
            if not isinstance(numero, int) or numero <= 0:
                continue
            frames.append({"filename": arquivo, "lineno": numero, "in_app": True})
        valores.append({"type": tipo, "value": "conteúdo omitido por privacidade", "stacktrace": {"frames": frames}})
    seguro = {"level": "error", "platform": "python", "exception": {"values": valores}}
    identificador = evento.get("event_id", "")
    if isinstance(identificador, str) and re.fullmatch(r"[0-9a-f]{32}", identificador):
        seguro["event_id"] = identificador
    return seguro


class Erros:
    def __init__(self, dsn: str, *, transporte=None):
        from sentry_sdk import Client

        self.cliente = Client(
            dsn=dsn,
            transport=transporte,
            default_integrations=False,
            auto_enabling_integrations=False,
            data_collection={
                "user_info": False,
                "cookies": {"mode": "off"},
                "http_headers": {"request": {"mode": "off"}},
                "http_bodies": [],
                "url_query_params": {"mode": "off"},
                "graphql": {"document": False, "variables": False},
                "gen_ai": {"inputs": False, "outputs": False},
                "database_query_data": False,
                "queues": False,
                "stack_frame_variables": False,
                "frame_context_lines": 0,
            },
            include_local_variables=False,
            include_source_context=False,
            max_request_body_size="never",
            auto_session_tracking=False,
            send_client_reports=False,
            traces_sample_rate=0,
            profiles_sample_rate=0,
            before_send=evento_seguro,
        )

    def capturar(self, erro: Exception) -> str | None:
        frames = []
        for frame in traceback.extract_tb(erro.__traceback__):
            try:
                caminho = Path(frame.filename).resolve().relative_to(RAIZ_REPO).as_posix()
            except ValueError:
                continue
            frames.append({"filename": caminho, "lineno": frame.lineno})
        # Não chamar capture_exception: ele primeiro coleta a mensagem, o fonte e os locais.
        evento = {"exception": {"values": [{"type": type(erro).__name__, "stacktrace": {"frames": frames}}]}}
        return self.cliente.capture_event(evento_seguro(evento))

    def fechar(self) -> None:
        self.cliente.close(timeout=2)


def do_config(cfg) -> Erros | None:
    dsn = getattr(cfg, "glitchtip_dsn", None)
    return Erros(dsn.get_secret_value()) if dsn else None
