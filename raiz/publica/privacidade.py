"""Filtro de dados pessoais antes de gravar o registro das chamadas e de devolver qualquer resposta pública.

`sem_dado_pessoal` tira das respostas as chaves com cara de dado pessoal (nome, CPF, CNPJ, contato do dono).
`limpar` troca no texto CPF, CNPJ, telefone e e-mail por marcadores (<CPF>, <CNPJ>, <TELEFONE>, <EMAIL>) antes de
gravar o registro (o mesmo papel do Presidio; os reconhecedores brasileiros ficam aqui, em expressões regulares).
"""

from __future__ import annotations

import re
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
UUID_CANONICO = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)


def sem_dado_pessoal(x: Any) -> Any:
    """Tira de qualquer resposta as chaves com cara de dado pessoal, por garantia (as respostas já não trazem)."""
    if isinstance(x, dict):
        return {k: sem_dado_pessoal(v) for k, v in x.items() if not CHAVES_PESSOAIS.search(str(k))}
    if isinstance(x, list):
        return [sem_dado_pessoal(v) for v in x]
    return x


def limpar(x: Any) -> Any:
    """Troca CPF, CNPJ, e-mail e telefone por marcadores em textos (também dentro de dicionários e listas)."""
    if isinstance(x, str):
        # Um UUID completo é identificador de protocolo. Seus trechos numéricos podem parecer um telefone;
        # alterá-los quebra o acompanhamento do pedido. Texto livre ao redor continua passando pelo filtro.
        if UUID_CANONICO.fullmatch(x):
            return x
        for marca, padrao in PADROES:
            x = padrao.sub(marca, x)
        return x
    if isinstance(x, dict):
        return {k: limpar(v) for k, v in sem_dado_pessoal(x).items()}
    if isinstance(x, list):
        return [limpar(v) for v in x]
    return x
