"""Adaptador do requests que responde sem rede: cada teste dá uma função (método, url, params, cabeçalhos) ->
(status, cabeçalhos, corpo). Guarda os pedidos feitos."""

from urllib.parse import parse_qsl, urlsplit

import requests
from requests.adapters import BaseAdapter
from requests.structures import CaseInsensitiveDict


class ServidorFalso(BaseAdapter):
    def __init__(self, responder):
        super().__init__()
        self.responder = responder
        self.pedidos = []

    def send(self, request, **kw):
        partes = urlsplit(request.url)
        params = dict(parse_qsl(partes.query, keep_blank_values=True))
        base = f"{partes.scheme}://{partes.netloc}{partes.path}"
        self.pedidos.append((request.method, base, params, dict(request.headers)))
        status, cabecalhos, corpo = self.responder(request.method, base, params, request.headers)
        r = requests.Response()
        r.status_code = status
        r.headers = CaseInsensitiveDict(cabecalhos or {})
        r._content = corpo.encode() if isinstance(corpo, str) else (corpo or b"")
        r._content_consumed = True
        r.url = request.url
        r.request = request
        r.encoding = "utf-8"
        return r

    def close(self):
        pass


def sessao_falsa(responder) -> tuple[requests.Session, ServidorFalso]:
    s = requests.Session()
    f = ServidorFalso(responder)
    s.mount("https://", f)
    s.mount("http://", f)
    return s, f
