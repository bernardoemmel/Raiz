"""Guarda de privacidade: CPF e CNPJ sempre mascarados; nome e CPF nunca em log, treino ou repositório.

- mascarar(texto): troca todo CPF e CNPJ por versão mascarada (***.456.789-** e **.345.678/****-**).
  Aceita o CNPJ alfanumérico (IN RFB 2.229/2024, em vigor desde julho de 2026).
- configurar_log(): todo log da Raíz passa pela máscara, inclusive o texto de exceções.
- remover_colunas_pessoais(df): tira na entrada colunas de nome, CPF/CNPJ, contato e endereço.
- varrer(caminhos): procura CPF/CNPJ em arquivos (usado no CI antes de qualquer commit chegar ao main).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# --- validação ---------------------------------------------------------------------------------------------------


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


def _valor_cnpj(c: str) -> int:
    # CNPJ alfanumérico: valor de cada caractere = código ASCII menos 48 (0-9 continuam 0-9; A=17 ... Z=42)
    return ord(c) - 48


def cnpj_valido(cnpj: str) -> bool:
    s = re.sub(r"[^0-9A-Z]", "", cnpj.upper())
    if len(s) != 14 or not s[12:].isdigit() or s == s[0] * 14:
        return False
    for n, pesos in ((12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]), (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])):
        r = sum(_valor_cnpj(s[i]) * pesos[i] for i in range(n)) % 11
        if (0 if r < 2 else 11 - r) != int(s[n]):
            return False
    return True


# --- máscara -----------------------------------------------------------------------------------------------------

# bordas: não pega pedaço de número decimal (189.99087022873272) nem de código maior; vírgula é separador de CSV
_ANTES = r"(?<![\w./-])"
_DEPOIS = r"(?![\w]|\.\d|[/-]\w)"
_CPF_FMT = re.compile(_ANTES + r"\d{3}\.\d{3}\.\d{3}-\d{2}" + _DEPOIS)
_CNPJ_FMT = re.compile(_ANTES + r"[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}" + _DEPOIS)
_CPF_NU = re.compile(_ANTES + r"\d{11}" + _DEPOIS)
_CNPJ_NU = re.compile(_ANTES + r"[0-9A-Z]{12}\d{2}" + _DEPOIS)


def mascara_cpf(cpf: str) -> str:
    d = _so_digitos(cpf)
    return f"***.{d[3:6]}.{d[6:9]}-**"


def mascara_cnpj(cnpj: str) -> str:
    s = re.sub(r"[^0-9A-Z]", "", cnpj.upper())
    return f"**.{s[2:5]}.{s[5:8]}/****-**"


def _troca_cnpj_nu(m: re.Match) -> str:
    s = m.group(0)
    return mascara_cnpj(s) if cnpj_valido(s) else s


def _troca_cpf_nu(m: re.Match) -> str:
    s = m.group(0)
    return mascara_cpf(s) if cpf_valido(s) else s


def mascarar(texto: str) -> str:
    """Mascara todo CPF e CNPJ do texto. Formatados sempre; sem pontuação, só se os dígitos verificadores batem
    (para não estragar números comuns)."""
    if not texto:
        return texto
    texto = _CNPJ_FMT.sub(lambda m: mascara_cnpj(m.group(0)), texto)
    texto = _CPF_FMT.sub(lambda m: mascara_cpf(m.group(0)), texto)
    texto = _CNPJ_NU.sub(_troca_cnpj_nu, texto)
    texto = _CPF_NU.sub(_troca_cpf_nu, texto)
    return texto


def documento_em_identificador(texto: str) -> bool:
    """CPF/CNPJ não vira rótulo público ao receber prefixo de versão e separador."""
    if mascarar(texto) != texto:
        return True
    return any(cpf_valido(p) or cnpj_valido(p) for p in re.split(r"[_.+:/-]", texto))


# --- log ---------------------------------------------------------------------------------------------------------


class FiltroSanitizacao(logging.Filter):
    """Descarta logs internos produzidos pelo NLP enquanto limpa outro registro."""

    def filter(self, record: logging.LogRecord) -> bool:
        from raiz.logs_seguros import sanitizacao_ativa

        return not sanitizacao_ativa()


_FILTRO_SANITIZACAO = FiltroSanitizacao()


class FormatadorSeguro(logging.Formatter):
    """Passa o resultado final pelo Presidio (mensagem, argumentos e traceback)."""

    def format(self, record: logging.LogRecord) -> str:
        from raiz.logs_seguros import sanitizar_log

        return sanitizar_log(super().format(record))


class FormatadorJSON(logging.Formatter):
    """Uma linha JSON válida; campos extras livres não entram no log do servidor."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            return self._formatar(record)
        except Exception:
            # logging.handleError imprimiria record.msg/args em claro se o formatador levantasse erro.
            return '{"nivel":"ERROR","mensagem":"[log suprimido: formatação indisponível]"}'

    def _formatar(self, record: logging.LogRecord) -> str:
        from raiz.logs_seguros import sanitizar_log

        dado = {
            "tempo": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "nivel": record.levelname,
            "logger": sanitizar_log(record.name),
            "mensagem": sanitizar_log(record.getMessage()),
        }
        if record.exc_info:
            dado["excecao"] = sanitizar_log(self.formatException(record.exc_info))
        for chave in ("evento", "metodo", "rota", "status", "duracao_ms", "requisicao_id"):
            valor = getattr(record, chave, None)
            if chave == "requisicao_id":
                # UUID gerado pelo servidor: validar o contrato evita falso PERSON e perda da correlação.
                if isinstance(valor, str) and re.fullmatch(r"[0-9a-f]{32}", valor):
                    dado[chave] = valor
                continue
            if isinstance(valor, str):
                dado[chave] = sanitizar_log(valor)
            elif isinstance(valor, int | float):
                dado[chave] = valor
        return json.dumps(dado, ensure_ascii=False, allow_nan=False)


def configurar_log(nivel: int = logging.INFO) -> None:
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for h in raiz.handlers:
        h.addFilter(_FILTRO_SANITIZACAO)
        h.setFormatter(FormatadorJSON())
    if not raiz.handlers:
        h = logging.StreamHandler()
        h.addFilter(_FILTRO_SANITIZACAO)
        h.setFormatter(FormatadorJSON())
        raiz.addHandler(h)
    # Uvicorn pode ter handlers próprios que não propagam até a raiz.
    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(nome).handlers:
            h.addFilter(_FILTRO_SANITIZACAO)
            h.setFormatter(FormatadorJSON())
    for barulhento in ("alembic", "httpx", "httpx2", "httpcore", "urllib3"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)


# --- colunas pessoais na entrada ---------------------------------------------------------------------------------

_PESSOAL = re.compile(
    r"cpf|cnpj|nome|^nom_|_nom_|e_?mail|telefone|celular|^fone|_fone|whats|endereco|endereço|logradouro|"
    r"^rg$|^rg_|_rg$|^nis|pis_pasep|titulo_eleitor|nasc|^mae|nome_mae|filiacao|^cep$|_cep$",
    re.IGNORECASE,
)
# nomes de lugares e de áreas protegidas não são dado pessoal
_LUGAR = re.compile(r"munic|^uf$|estado|bioma|nome_uc|nome_ti|terra_ind|unidade|nome_projeto|camada", re.IGNORECASE)


def colunas_pessoais(colunas: Iterable[str], permitir: Iterable[str] = ()) -> list[str]:
    ok = {c.lower() for c in permitir}
    return [c for c in colunas if c.lower() not in ok and _PESSOAL.search(c) and not _LUGAR.search(c)]


def remover_colunas_pessoais(df, permitir: Iterable[str] = ()):
    """Devolve (df sem as colunas pessoais, lista das removidas). Na dúvida, remove: é mais barato pedir uma coluna
    de volta do que tirar um CPF de um backup."""
    fora = colunas_pessoais(df.columns, permitir)
    return df.drop(columns=fora), fora


# --- varredura de arquivos ---------------------------------------------------------------------------------------

EXTENSOES_TEXTO = {
    ".py",
    ".md",
    ".csv",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sh",
    ".ini",
    ".cfg",
    ".env",
    ".example",
}


@dataclass
class Achado:
    arquivo: str
    linha: int
    tipo: str
    trecho: str  # já mascarado


def varrer_texto(texto: str, arquivo: str = "") -> list[Achado]:
    achados = []
    for n, linha in enumerate(texto.splitlines(), 1):
        for tipo, rx, valida in (
            ("CNPJ", _CNPJ_FMT, None),
            ("CPF", _CPF_FMT, None),
            ("CNPJ", _CNPJ_NU, cnpj_valido),
            ("CPF", _CPF_NU, cpf_valido),
        ):
            for m in rx.finditer(linha):
                if valida is None or valida(m.group(0)):
                    achados.append(Achado(arquivo, n, tipo, mascarar(m.group(0))))
    return achados


def varrer(caminhos: Iterable[str | Path], ignorar: Iterable[str] = ()) -> list[Achado]:
    ign = set(ignorar)
    achados: list[Achado] = []
    for c in caminhos:
        p = Path(c)
        if str(p) in ign or not p.is_file() or (p.suffix.lower() not in EXTENSOES_TEXTO and p.name != ".env.example"):
            continue
        try:
            texto = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        achados += varrer_texto(texto, str(p))
    return achados
