"""Privacidade na vigilância: CPF e CNPJ sempre mascarados, nenhuma coluna pessoal, nenhum nome.

Mesma regra de raiz/privacidade.py (back-end) e de front/compartilhado/privacidade.ts: máscara ***.456.789-** e
**.345.678/****-**, aceita o CNPJ alfanumérico (IN RFB 2.229/2024); sem pontuação, só mascara quando os dígitos
verificadores batem (para não estragar números comuns nem o código do CAR). Na dúvida, a coluna sai.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s)


def cpf_valido(cpf: str) -> bool:
    d = _so_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def cnpj_valido(cnpj: str) -> bool:
    s = re.sub(r"[^0-9A-Z]", "", cnpj.upper())
    if len(s) != 14 or not s[12:].isdigit() or s == s[0] * 14:
        return False
    for n, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        r = sum((ord(s[i]) - 48) * pesos[i] for i in range(n)) % 11
        if (0 if r < 2 else 11 - r) != int(s[n]):
            return False
    return True


def mascara_cpf(cpf: str) -> str:
    d = _so_digitos(cpf)
    return f"***.{d[3:6]}.{d[6:9]}-**"


def mascara_cnpj(cnpj: str) -> str:
    s = re.sub(r"[^0-9A-Z]", "", cnpj.upper())
    return f"**.{s[2:5]}.{s[5:8]}/****-**"


_ANTES = r"(?<![\w./-])"
_DEPOIS = r"(?![\w]|\.\d|[/-]\w)"
_CPF_FMT = re.compile(_ANTES + r"\d{3}\.\d{3}\.\d{3}-\d{2}" + _DEPOIS)
_CNPJ_FMT = re.compile(_ANTES + r"[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}" + _DEPOIS)
_CPF_NU = re.compile(_ANTES + r"\d{11}" + _DEPOIS)
_CNPJ_NU = re.compile(_ANTES + r"[0-9A-Z]{12}\d{2}" + _DEPOIS)


def mascarar(texto):
    """Mascara todo CPF e CNPJ do texto (o resto passa igual; não texto volta como veio)."""
    if not isinstance(texto, str) or not texto:
        return texto
    texto = _CNPJ_FMT.sub(lambda m: mascara_cnpj(m.group(0)), texto)
    texto = _CPF_FMT.sub(lambda m: mascara_cpf(m.group(0)), texto)
    texto = _CNPJ_NU.sub(lambda m: mascara_cnpj(m.group(0)) if cnpj_valido(m.group(0)) else m.group(0), texto)
    texto = _CPF_NU.sub(lambda m: mascara_cpf(m.group(0)) if cpf_valido(m.group(0)) else m.group(0), texto)
    return texto


_PESSOAL = re.compile(
    "cpf|cnpj|nome|^nom_|_nom_|e_?mail|telefone|celular|^fone|_fone|whats|endereco|endereço|logradouro|"
    "^rg$|^rg_|_rg$|^nis|pis_pasep|titulo_eleitor|nasc|^mae|nome_mae|filiacao|^cep$|_cep$|propriet|dono|titular|"
    "embargado|num_pessoa|interessado|autuado|responsavel",
    re.I,
)
# nomes de lugares e de áreas protegidas não são dado pessoal
_LUGAR = re.compile(r"munic|^uf$|estado|bioma|nome_uc|nome_ti|terra_ind|unidade|nome_projeto|camada", re.I)


def coluna_pessoal(coluna: str) -> bool:
    return bool(_PESSOAL.search(coluna)) and not _LUGAR.search(coluna)


def colunas_pessoais(colunas: Iterable[str]) -> list[str]:
    return [c for c in colunas if coluna_pessoal(str(c))]


def limpar_registro(d: dict) -> dict:
    """Tira chaves pessoais e mascara CPF/CNPJ em todo texto (recursivo em dict e lista)."""

    def v(x):
        if isinstance(x, str):
            return mascarar(x)
        if isinstance(x, dict):
            return limpar_registro(x)
        if isinstance(x, list | tuple):
            return [v(i) for i in x]
        return x

    return {k: v(x) for k, x in d.items() if not coluna_pessoal(str(k))}
