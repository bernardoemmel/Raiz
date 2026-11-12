"""Erros no padrão RFC 9457 (application/problem+json): type, title, status, detail e instance, mais `corrigir`
(o que o cliente ou o agente dele precisa fazer) e campos próprios de cada erro (ex.: a recarga por Pix no 402)."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

TIPO = "https://github.com/bernardoemmel/Raiz/blob/main/docs/agentes-ia.md#erro-"
TITULOS = {
    400: "Pedido malformado", 401: "Sem credencial válida", 402: "Pagamento necessário", 403: "Não liberado",
    404: "Não encontrado", 409: "Conflito", 410: "Não vale mais", 422: "Dados para corrigir",
    429: "Limite de chamadas", 500: "Erro da Raíz",
}  # fmt: skip


def problema(status: int, slug: str, detalhe: str, corrigir: str, instance: str | None = None,
             headers: dict | None = None, **extra: Any) -> JSONResponse:  # fmt: skip
    corpo = {"type": TIPO + slug, "title": TITULOS.get(status, "Erro"), "status": status, "detail": detalhe,
             "corrigir": corrigir, **({"instance": instance} if instance else {}), **extra}  # fmt: skip
    return JSONResponse(corpo, status_code=status, media_type="application/problem+json", headers=headers)


EXEMPLO = {
    "type": TIPO + "saldo_insuficiente", "title": "Pagamento necessário", "status": 402,
    "detail": "a chamada consultar_disponibilidade custa R$ 40.00 e o saldo é R$ 0.00 (os créditos de teste acabaram)",
    "corrigir": "uma pessoa da empresa paga a recarga pelo link (o agente não paga) e a chamada pode ser repetida",
    "instance": "/v1/disponibilidade",
    "recarga": {"valor_rs": 500.0, "link_para_uma_pessoa": "https://api.raiz.exemplo/v1/cobrancas/AbC...",
                "modo_teste": True},
}  # fmt: skip


def resposta(status: int, descricao: str, slug: str, detalhe: str, corrigir: str) -> dict:
    """Exemplo de erro para a OpenAPI."""
    return {status: {"description": descricao, "content": {"application/problem+json": {"example": {
        "type": TIPO + slug, "title": TITULOS.get(status, "Erro"), "status": status, "detail": detalhe,
        "corrigir": corrigir}}}}}  # fmt: skip


ERROS_COMUNS = {
    **resposta(401, "Sem chave ou sessão válida", "sem_credencial", "faltou a chave de API da empresa",
               "mande a chave em X-Chave-API (ou Authorization: Bearer raiz_...)"),
    402: {"description": "Sem crédito de teste nem saldo: link de recarga por Pix para uma pessoa pagar",
          "content": {"application/problem+json": {"example": EXEMPLO}}},
    **resposta(403, "Conta bloqueada ou não liberada", "liberacao_pendente", "montar lote pede o sinal e o contrato",
               "uma pessoa aceita o contrato (POST /v1/conta/contrato) e paga o sinal (POST /v1/conta/sinal)"),
    **resposta(429, "Passou do limite da empresa", "limite", "limite de 30 por minuto da empresa",
               "espere o tempo de Retry-After e repita"),
}  # fmt: skip
