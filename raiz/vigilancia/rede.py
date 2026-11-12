"""HTTP da vigilância: sessão com novas tentativas, pedido condicional (ETag) e download em disco sem estourar memória.

Nenhum dado do usuário vai no pedido: o User-Agent é genérico.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

log = logging.getLogger(__name__)

AGENTE = "raiz-vigilancia/0.1 (+https://github.com/bernardoemmel/raiz)"


_SEGREDOS = ("FIRMS_MAP_KEY", "MAPBIOMAS_ALERTA_SENHA", "RAIZ_VIGILANCIA_CHAVE", "RAIZ_GITHUB_TOKEN", "GITHUB_TOKEN")


def limpo(texto: str) -> str:
    """Tira a parte de consulta da URL e qualquer segredo do ambiente (a chave do FIRMS vai no caminho da URL)."""
    texto = str(texto).split("?")[0]
    for nome in _SEGREDOS:
        v = os.environ.get(nome)
        if v and len(v) >= 6:
            texto = texto.replace(v, "***")
    return texto


def sessao() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = AGENTE
    return s


_S: requests.Session | None = None


def s() -> requests.Session:
    global _S
    if _S is None:
        _S = sessao()
    return _S


def pedir(metodo: str, url: str, tentativas: int = 4, espera: float = 5.0, ok=(200,), **kw) -> requests.Response:
    """Pedido com novas tentativas (erro de rede, 429 e 5xx). Devolve a resposta com status em `ok` ou levanta."""
    kw.setdefault("timeout", 300)
    ultimo: Exception | None = None
    for i in range(tentativas):
        try:
            r = s().request(metodo, url, **kw)
            if r.status_code in ok:
                return r
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = RuntimeError(f"{r.status_code} em {limpo(url)}")
            else:
                raise RuntimeError(f"{r.status_code} em {limpo(url)}: {limpo(r.text[:200])}")
        except requests.RequestException as ex:
            ultimo = RuntimeError(limpo(str(ex)))
        if i < tentativas - 1:
            time.sleep(espera * (2**i))
    raise RuntimeError(f"falhou depois de {tentativas} tentativas: {limpo(url)}: {limpo(str(ultimo))}")


def baixar(url: str, destino: Path, condicional: bool = True, cabecalhos: dict | None = None) -> bool:
    """Baixa para `destino` (escrita atômica). Com `condicional`, manda o ETag guardado em `destino.etag` e não baixa
    de novo se não mudou. Devolve True se o arquivo mudou."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    meta = destino.with_name(destino.name + ".etag")
    h = dict(cabecalhos or {})
    if condicional and destino.exists() and meta.exists():
        h["If-None-Match"] = meta.read_text().strip()
    r = pedir("GET", url, ok=(200, 304), headers=h, stream=True, timeout=1800)
    if r.status_code == 304:
        return False
    tmp = destino.with_name(f"{destino.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as f:
        for pedaco in r.iter_content(1 << 20):
            f.write(pedaco)
    os.replace(tmp, destino)
    if r.headers.get("ETag"):
        meta.write_text(r.headers["ETag"])
    return True


def json_get(url: str, **kw):
    return pedir("GET", url, **kw).json()


def graphql(url: str, consulta: str, variaveis: dict | None = None, token: str | None = None) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    r = pedir("POST", url, data=json.dumps({"query": consulta, "variables": variaveis or {}}), headers=h, timeout=180)
    d = r.json()
    if d.get("errors"):
        raise RuntimeError("GraphQL: " + "; ".join(str(e.get("message")) for e in d["errors"]))
    return d["data"]
