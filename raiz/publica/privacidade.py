"""Filtro de dados pessoais antes de gravar o registro das chamadas e de devolver qualquer resposta pública.

`sem_dado_pessoal` tira das respostas as chaves com cara de dado pessoal (nome, CPF, CNPJ, contato do dono).
`limpar` troca no texto CPF, CNPJ, telefone e e-mail por marcadores (<CPF>, <CNPJ>, <TELEFONE>, <EMAIL>) antes de
gravar o registro (o mesmo papel do Presidio; os reconhecedores brasileiros ficam aqui, em expressões regulares).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CHAVES_PESSOAIS = re.compile(
    r"(^|_)(nome|cpf|cnpj|telefone|celular|email|e_mail|contato|proprietario|whatsapp|endereco)($|_)", re.I
)
PADROES = [
    ("<CNPJ>", re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")),
    ("<CPF>", re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")),
    ("<EMAIL>", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("<TELEFONE>", re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}(?!\d)")),
]


def chave_pessoal(chave: str) -> bool:
    """Normaliza aliases de entrada, inclusive camelCase e acentos, antes de aplicar a lista de campos pessoais."""
    chave = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", chave)
    chave = unicodedata.normalize("NFKD", chave).encode("ascii", "ignore").decode().lower()
    chave = re.sub(r"[^a-z0-9]+", "_", chave).strip("_")
    return bool(
        CHAVES_PESSOAIS.search(chave)
        or re.search(r"(^|_)(owner|dono|name|fone|fones|proprietaria|titular|tax_id|documento_pessoal)($|_)", chave)
    )


def sem_dado_pessoal(x: Any) -> Any:
    """Tira de qualquer resposta as chaves com cara de dado pessoal, por garantia (as respostas já não trazem)."""
    if isinstance(x, dict):
        return {k: sem_dado_pessoal(v) for k, v in x.items() if not chave_pessoal(str(k))}
    if isinstance(x, list):
        return [sem_dado_pessoal(v) for v in x]
    return x


def limpar(x: Any) -> Any:
    """Troca CPF, CNPJ, e-mail e telefone por marcadores em textos (também dentro de dicionários e listas)."""
    if isinstance(x, str):
        for marca, padrao in PADROES:
            x = padrao.sub(marca, x)
        return x
    if isinstance(x, dict):
        return {k: limpar(v) for k, v in sem_dado_pessoal(x).items()}
    if isinstance(x, list):
        return [limpar(v) for v in x]
    return x


# A limpeza de logs continua deliberadamente conservadora. Respostas públicas, porém, carregam identificadores,
# assinaturas e códigos de pagamento que não podem sofrer substituição parcial por regex. Só formatos fechados
# gerados pelo serviço são preservados; isso não autoriza devolver documentos/textos arbitrários de terceiros.
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_CAR = re.compile(r"[A-Z]{2}-[0-9]{7}-[0-9A-Fa-f]{32}\Z")
_IDS = {"id", "pedido", "pedido_id", "negocio_pedido_id", "operacao_id", "evento_id", "inscricao_id"}
_LINKS = {"aprovacao_url", "link_para_uma_pessoa"}


def _uuid(valor: str) -> bool:
    return bool(_UUID.fullmatch(valor))


def _link_pagamento(valor: str) -> bool:
    from urllib.parse import urlsplit

    try:
        url = urlsplit(valor)
        if url.username or url.password or url.query or url.fragment or any(c.isspace() for c in valor):
            return False
        if url.scheme or url.netloc:
            if not url.hostname or not (
                url.scheme == "https"
                or (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "testserver"})
            ):
                return False
        return bool(re.fullmatch(r"/(?:v1/)?(?:reservas/confirmar|cobrancas)/[A-Za-z0-9_-]{24,128}", url.path))
    except ValueError:
        return False


def _data(valor) -> bool:
    import datetime as dt

    try:
        return isinstance(valor, str) and dt.datetime.fromisoformat(valor).tzinfo is not None
    except ValueError:
        return False


def _recibo_publico(valor: str) -> bool:
    """Confere a projeção sem dados pessoais; autenticidade continua sendo verificada pelo consumidor do JWS."""
    import base64
    import json
    from binascii import Error

    def b64(parte):
        return base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4))

    def unico(pares):
        resultado = {}
        for chave, valor in pares:
            if chave in resultado:
                raise ValueError("campo duplicado no JWS")
            resultado[chave] = valor
        return resultado

    if len(valor) > 8192 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{86}", valor):
        return False
    try:
        cab, corpo, assinatura = valor.split(".")
        h, p = json.loads(b64(cab), object_pairs_hook=unico), json.loads(b64(corpo), object_pairs_hook=unico)
        if not isinstance(h, dict) or not isinstance(p, dict):
            return False
        if set(h) != {"alg", "typ", "kid"} or h["alg"] != "EdDSA" or h["typ"] != "raiz-aprovacao+jwt":
            return False
        if not isinstance(h["kid"], str) or not re.fullmatch(r"[a-f0-9]{20}", h["kid"]):
            return False
        if len(b64(assinatura)) != 64 or set(p) != {
            "tipo",
            "pagamento_confirmado",
            "iat",
            "exp",
            "empresa",
            "reserva",
            "pedido",
            "valor",
            "currency",
            "preco_valido_ate",
            "exclusividade",
            "condicoes",
        }:
            return False
        return (
            p["tipo"] == "aprovacao_humana_reserva"
            and p["pagamento_confirmado"] is False
            and all(type(p[k]) is int and p[k] > 0 for k in ("iat", "exp", "empresa", "reserva"))
            and isinstance(p["pedido"], str)
            and _uuid(p["pedido"])
            and isinstance(p["valor"], str)
            and bool(re.fullmatch(r"[0-9]{1,12}\.[0-9]{2}", p["valor"]))
            and p["currency"] == "BRL"
            and _data(p["preco_valido_ate"])
            and isinstance(p["exclusividade"], dict)
            and set(p["exclusividade"]) == {"dias", "inicio"}
            and type(p["exclusividade"]["dias"]) is int
            and 0 < p["exclusividade"]["dias"] <= 3650
            and p["exclusividade"]["inicio"] == "apos_pagamento_confirmado"
            and p["condicoes"]
            == {
                "acao": "gerar_cobranca_pix",
                "pagador": "pessoa",
                "agente_pode_pagar": False,
                "reserva_depende_pagamento": True,
                "abatimento_na_conexao": True,
            }
        )
    except (ValueError, TypeError, KeyError, Error):
        return False


def _pix(valor: str) -> bool:
    """Aceita o simulador explícito ou BR Code com campos Pix e CRC íntegros; nunca texto livre."""
    import binascii

    if re.fullmatch(r"RAIZ-TESTE-PIX-teste_[0-9a-f]{16}-NAO-E-CODIGO-DE-BANCO", valor):
        return True
    if not 20 <= len(valor) <= 4096 or not valor.isascii() or not re.search(r"6304[0-9A-Fa-f]{4}\Z", valor):
        return False
    campos = {}
    pos = 0
    try:
        while pos < len(valor):
            tag, tamanho = valor[pos : pos + 2], int(valor[pos + 2 : pos + 4])
            fim = pos + 4 + tamanho
            if not tag.isdigit() or tag in campos or fim > len(valor):
                return False
            campos[tag] = valor[pos + 4 : fim]
            pos = fim
        crc = binascii.crc_hqx(valor[:-4].encode(), 0xFFFF)
        return (
            campos.get("00") == "01"
            and campos.get("53") == "986"
            and campos.get("58") == "BR"
            and "BR.GOV.BCB.PIX" in campos.get("26", "").upper()
            and int(campos["63"], 16) == crc
        )
    except (ValueError, KeyError):
        return False


def _qr(valor: str) -> bool:
    """Somente o subconjunto SVG geométrico produzido localmente pelo qrcode; nunca texto, script ou links."""
    import xml.etree.ElementTree as ET

    if len(valor) > 200_000 or "<!" in valor:
        return False
    try:
        raiz = ET.fromstring(valor)
    except ET.ParseError:
        return False
    ns = "{http://www.w3.org/2000/svg}"
    if raiz.tag != ns + "svg":
        return False
    for no in raiz.iter():
        if no.tag not in {ns + "svg", ns + "path"} or (no.text or "").strip() or (no.tail or "").strip():
            return False
        for chave, texto in no.attrib.items():
            if chave in {"width", "height", "viewBox", "version"}:
                if not re.fullmatch(r"[0-9. mm]+", texto):
                    return False
            elif chave == "d":
                if not re.fullmatch(r"[MmLlHhVvZz0-9., \n\t-]+", texto):
                    return False
            elif (chave, texto) not in {
                ("id", "qr-path"),
                ("fill", "#000000"),
                ("fill-opacity", "1"),
                ("fill-rule", "nonzero"),
                ("stroke", "none"),
            }:
                return False
    return True


def para_resposta(x: Any, *, _campo: str = "", _pai: str = "") -> Any:
    """Filtra a projeção pública sem corromper valores de protocolo válidos.

    Não é extrator de entidades nem torna uma certidão bruta publicável. Nomes em textos arbitrários devem ser
    excluídos na projeção positiva do domínio. Campos opacos inválidos viram null, nunca texto parcialmente alterado.
    """
    if isinstance(x, dict):
        return {k: para_resposta(v, _campo=str(k), _pai=_campo) for k, v in x.items() if not chave_pessoal(str(k))}
    if isinstance(x, (list, tuple)):
        return [para_resposta(v, _campo=_campo, _pai=_pai) for v in x]
    if not isinstance(x, str):
        return x
    if _campo in _IDS and _uuid(x):
        return x
    if _campo == "cod_imovel" and _CAR.fullmatch(x):
        return x
    if (_campo.endswith("_sha256") or _campo in {"hash", "leitura_hash"}) and re.fullmatch(r"[a-fA-F0-9]{64}", x):
        return x
    if _campo in _LINKS:
        return x if _link_pagamento(x) else None
    if _campo == "recibo_aprovacao":
        return x if _recibo_publico(x) else None
    if _campo in {"copia_e_cola", "qr_svg"}:
        valida = _pix(x) if _campo == "copia_e_cola" else _qr(x)
        return x if _pai == "pix" and valida else None
    if _campo == "proximo_token":
        return x if re.fullmatch(r"[a-f0-9]{64}", x) else None
    return limpar(x)
