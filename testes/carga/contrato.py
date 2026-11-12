"""Critérios da carga: falha explícita, sem guardar corpos, cabeçalhos ou credenciais."""

from __future__ import annotations

from urllib.parse import urlsplit

ROTAS_API = ("/saude", "/municipios", "/municipios/1504950/imoveis")


def exigir_local(url: str) -> None:
    destino = urlsplit(url)
    if (
        destino.scheme not in {"http", "https"}
        or destino.hostname not in {"localhost", "127.0.0.1", "::1"}
        or destino.username
        or destino.password
        or destino.query
        or destino.fragment
    ):
        raise ValueError("A carga só pode usar servidor local descartável, sem credencial na URL")


def retry_after_valido(valor: str | None) -> bool:
    """Nosso contrato usa delta em segundos, inteiro positivo e limitado a uma janela."""
    return bool(valor and valor.isascii() and valor.isdecimal() and 1 <= int(valor) <= 60)


def conferir_relatorio(dado: dict, esperadas: set[str]) -> list[str]:
    erros = []
    if dado.get("requisicoes", 0) < 20:
        erros.append("menos de 20 requisições")
    if dado.get("falhas", 0):
        erros.append("requisições com erro")
    if dado.get("max_ms", 0) >= 5000:
        erros.append("resposta demorou 5 segundos ou mais")
    if dado.get("fase") == "limite":
        if not dado.get("limitadas", 0):
            erros.append("limite não devolveu 429")
        if dado.get("retry_after_invalidos", 0):
            erros.append("429 sem Retry-After válido")
    elif dado.get("fase") == "normal":
        if dado.get("limitadas", 0):
            erros.append("429 inesperado na carga abaixo do orçamento")
    else:
        erros.append("fase desconhecida")
    atendidas = {nome for nome, qtd in dado.get("sucessos", {}).items() if qtd > 0}
    if esperadas - atendidas:
        erros.append("nem todas as rotas/ferramentas tiveram resposta válida")
    return erros
