"""Checagem dos arquivos públicos (E1 passo 2): HEAD em cada endereço do manifesto, grava bytes, ETag e
Last-Modified e avisa no Healthchecks se um arquivo sumiu ou mudou.

Rodar fora deste ambiente de desenvolvimento (que bloqueia os buckets): `raiz coleta checar` no servidor, por cron.
Servidor que não aceita HEAD recebe um GET de 1 byte (Range: bytes=0-0) e o tamanho vem do Content-Range.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import requests
from sqlalchemy import Connection, text

from raiz.coleta.manifesto import Fonte, Manifesto, carregar
from raiz.coleta.replicacao import evento

TIPOS_ARQUIVO = {"arquivo", "cog", "parquet"}


@dataclass
class Resultado:
    fonte: str
    url: str
    status: int | None
    bytes: int | None
    etag: str | None
    last_modified: str | None
    erro: str | None = None
    mudou: bool | None = None

    @property
    def faltando(self) -> bool:
        return self.status is None or self.status >= 400


def urls(f: Fonte) -> list[str]:
    """Expande o modelo de endereço da fonte (produtos x anos, ou lista de arquivos)."""
    if not f.url:
        return []
    extra = f.model_extra or {}
    if "arquivos" in extra:
        return [f.url.format(arquivo=a) for a in extra["arquivos"]]
    if "produtos" in extra:
        return [f.url.format(produto=p, ano=a) for p in extra["produtos"] for a in extra.get("anos", [""])]
    return [f.url]


def checar_url(s: requests.Session, fonte: str, url: str, timeout: int = 30) -> Resultado:
    try:
        r = s.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code in (403, 405, 501):  # há servidor que recusa HEAD mas aceita GET de 1 byte
            r = s.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=timeout)
            r.close()
        tamanho = r.headers.get("Content-Length")
        if "Content-Range" in r.headers and "/" in r.headers["Content-Range"]:
            tamanho = r.headers["Content-Range"].rsplit("/", 1)[1]
        return Resultado(
            fonte,
            url,
            r.status_code,
            int(tamanho) if tamanho and tamanho.isdigit() else None,
            r.headers.get("ETag"),
            r.headers.get("Last-Modified"),
        )
    except requests.RequestException as ex:
        return Resultado(fonte, url, None, None, None, None, erro=type(ex).__name__)


def _ultima(con: Connection, url: str):
    return con.execute(
        text(
            "select etag, last_modified, bytes, status from coleta.checagem_http "
            "where url = :u order by verificado_em desc, id desc limit 1"
        ),
        {"u": url},
    ).first()


def checar(con: Connection, s: requests.Session, m: Manifesto | None = None, hc=None) -> list[Resultado]:
    m = m or carregar()
    res: list[Resultado] = []
    for f in m.fontes:
        if f.tipo not in TIPOS_ARQUIVO:
            continue
        for u in urls(f):
            r = checar_url(s, f.id, u)
            antes = _ultima(con, u)
            if antes is not None and not r.faltando:
                r.mudou = (r.etag, r.last_modified, r.bytes) != (antes.etag, antes.last_modified, antes.bytes)
            con.execute(
                text("""insert into coleta.checagem_http (fonte, url, status, bytes, etag, last_modified,
                                mudou, erro) values (:f, :u, :s, :b, :e, :l, :m, :x)"""),
                dict(f=f.id, u=u, s=r.status, b=r.bytes, e=r.etag, l=r.last_modified, m=r.mudou, x=r.erro),
            )
            if r.faltando:
                evento(con, f.id, u, "alerta", detalhe={"status": r.status, "erro": r.erro})
            elif r.mudou:
                evento(con, f.id, u, "mudaram", detalhe={"etag": r.etag, "bytes": r.bytes})
            res.append(r)
    if hc is not None:
        _avisar(hc, res)
    return res


def _avisar(hc, res: list[Resultado]) -> None:
    faltando = [r for r in res if r.faltando]
    mudaram = [r for r in res if r.mudou]
    linhas = [f"FALTA {r.fonte} {r.status or r.erro} {r.url}" for r in faltando]
    linhas += [f"MUDOU {r.fonte} {r.url} etag={r.etag} bytes={r.bytes}" for r in mudaram]
    corpo = f"{len(res)} arquivos, {len(faltando)} faltando, {len(mudaram)} mudaram\n" + "\n".join(linhas)
    rid = str(uuid.uuid4())
    slug = hc.slug("checagem")
    hc.inicio(slug, rid)
    (hc.falha if faltando else hc.sucesso)(slug, rid, corpo)
