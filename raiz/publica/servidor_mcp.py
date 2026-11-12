"""O adaptador MCP antigo foi retirado na migração paga.

A próxima entrega publica o SDK v2 com OAuth. Não há caminho alternativo gratuito
nem autenticação por chave na URL durante a migração.
"""


def ApiRaiz(*args, **kwargs):  # noqa: N802
    raise RuntimeError("MCP em migração: use a API REST paga /v1; o MCP volta com OAuth 2.1.")


def criar_servidor(*args, **kwargs):
    raise RuntimeError("MCP em migração: exige OAuth 2.1 antes da reabertura.")
