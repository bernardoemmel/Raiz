"""Consultas públicas de cada laudo gravadas em WARC (E5 passo 2): a página como estava no dia, para quem audita
o laudo conferir depois o que a Raíz viu.

- Pedido e resposta HTTP vão para um WARC (warcio, Apache-2.0), montado a partir da resposta do requests: o corpo
  vai já decodificado (sem Content-Encoding). O capture_http do warcio não serve aqui: ele só grava se for importado
  antes do requests no processo, o que não dá para garantir.
- Página pública do SIGEF ou do CAR pode trazer nome e CPF do detentor. Por isso o WARC é cifrado com a chave
  pessoal (RAIZ_CHAVE_PESSOAL, raiz/pessoal.py) antes de ir para o disco; sem a chave, só os hashes ficam.
- O índice (consultas.jsonl, na pasta do imóvel) guarda só URL, motivo, situação HTTP, tamanho, hash SHA-256 da
  resposta e do WARC e a data; é o que o laudo mostra. URL com CPF ou CNPJ é recusada.
- Fica em dados/documentos/warc/<imóvel>/ (fora do git), ou em RAIZ_DOCUMENTOS_DIR/warc.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

VERSAO = "warc-2026a"
AGENTE = "raiz-titulo/1.0 (consulta publica para laudo de titulo)"


@dataclass
class Consulta:
    url: str
    motivo: str
    em: str
    status: int | None
    bytes: int
    sha256_resposta: str | None
    sha256_warc: str
    arquivo: str | None  # nome do WARC cifrado; None quando não havia chave
    versao: str = VERSAO
    erro: str | None = None


def _registros(url: str, r, corpo: bytes) -> bytes:
    """WARC (gzip) com o registro do pedido e o da resposta; sem resposta, só o pedido."""
    from urllib.parse import urlsplit

    from warcio.statusandheaders import StatusAndHeaders
    from warcio.warcwriter import WARCWriter

    buf = io.BytesIO()
    w = WARCWriter(buf, gzip=True)
    u = urlsplit(url)
    caminho = (u.path or "/") + (f"?{u.query}" if u.query else "")
    cab_pedido = list(r.request.headers.items()) if r is not None else [("User-Agent", AGENTE)]
    w.write_record(
        w.create_warc_record(
            url,
            "request",
            http_headers=StatusAndHeaders(f"GET {caminho} HTTP/1.1", [("Host", u.netloc), *cab_pedido],
                                          is_http_request=True),
        )
    )  # fmt: skip
    if r is not None:
        fora = {"content-encoding", "transfer-encoding", "content-length"}
        cab = [(k, v) for k, v in r.headers.items() if k.lower() not in fora] + [("Content-Length", str(len(corpo)))]
        w.write_record(
            w.create_warc_record(
                url,
                "response",
                payload=io.BytesIO(corpo),
                http_headers=StatusAndHeaders(f"{r.status_code} {r.reason or ''}".strip(), cab, protocol="HTTP/1.1"),
            )
        )
    return buf.getvalue()


def pasta(cod_imovel: str, base: Path | None = None) -> Path:
    from raiz.documentos.config import pasta_dados

    seguro = re.sub(r"[^A-Za-z0-9_-]", "_", cod_imovel)
    p = (base or pasta_dados() / "warc") / seguro
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cofre(cofre):
    if cofre is not None:
        return cofre
    try:
        from raiz.pessoal import Cofre

        return Cofre()
    except Exception:  # noqa: BLE001 - sem chave pessoal: guarda só os hashes
        return None


def consultar(url: str, cod_imovel: str, motivo: str, cofre=None, base: Path | None = None, timeout: int = 30):
    """Faz a consulta gravando o WARC; devolve a Consulta (também anotada no índice) e o corpo da resposta."""
    from raiz.privacidade import mascarar

    if mascarar(url) != url:
        raise ValueError("URL com CPF ou CNPJ não é consultada")
    import requests

    status, corpo, erro, r = None, b"", None, None
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": AGENTE})
        status, corpo = r.status_code, r.content
    except requests.RequestException as ex:
        erro = type(ex).__name__
    warc = _registros(url, r, corpo)
    em = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    h_warc = hashlib.sha256(warc).hexdigest()
    c = _cofre(cofre)
    nome = None
    p = pasta(cod_imovel, base)
    if c is not None and warc:
        nome = f"{em[:19].replace(':', '').replace('-', '')}-{h_warc[:12]}.warc.gz.cifrado"
        (p / nome).write_bytes(c.cifrar_bytes(warc))
    reg = Consulta(
        url=url,
        motivo=motivo,
        em=em,
        status=status,
        bytes=len(corpo),
        sha256_resposta=hashlib.sha256(corpo).hexdigest() if status is not None else None,
        sha256_warc=h_warc,
        arquivo=nome,
        erro=erro,
    )
    with (p / "consultas.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(reg), ensure_ascii=False) + "\n")
    return reg, corpo


def consultas(cod_imovel: str, base: Path | None = None) -> list[dict]:
    f = pasta(cod_imovel, base) / "consultas.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def abrir(cod_imovel: str, arquivo: str, cofre=None, base: Path | None = None) -> list[dict]:
    """Decifra um WARC e devolve os registros (tipo, URL, situação HTTP, tamanho), para auditoria."""
    from warcio.archiveiterator import ArchiveIterator

    c = _cofre(cofre)
    if c is None:
        raise RuntimeError("defina RAIZ_CHAVE_PESSOAL para abrir o WARC")
    dado = c.decifrar_bytes((pasta(cod_imovel, base) / arquivo).read_bytes())
    out = []
    for rec in ArchiveIterator(io.BytesIO(dado)):
        out.append(
            dict(
                tipo=rec.rec_type,
                url=rec.rec_headers.get_header("WARC-Target-URI"),
                status=rec.http_headers.get_statuscode() if rec.http_headers else None,
                bytes=len(rec.content_stream().read()),
            )
        )
    return out
