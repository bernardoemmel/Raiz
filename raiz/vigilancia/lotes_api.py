"""Rascunhos de vigilância: somente a pessoa autenticada da empresa dona do pedido."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response


def registrar(app, engine_de, pessoa):
    from raiz.pedidos.servico import ErroPedido
    from raiz.publica.conta import exigir_liberacao
    from raiz.publica.privacidade import para_resposta
    from raiz.vigilancia.lotes import relatorios_do_pedido

    Identidade = Annotated[Any, Depends(pessoa)]

    def consultar(request, pedido_id, identidade):
        eng = engine_de(request)
        exigir_liberacao(eng, identidade.cliente_id)
        try:
            return relatorios_do_pedido(eng, pedido_id, identidade.cliente_id)
        except ErroPedido:
            raise HTTPException(404, "pedido não encontrado") from None

    @app.get("/pedidos/{pedido_id}/vigilancia/relatorios", tags=["Pedido de lote"])
    def relatorios(request: Request, pedido_id: str, identidade: Identidade):
        return JSONResponse(
            para_resposta(consultar(request, pedido_id, identidade)), headers={"Cache-Control": "no-store"}
        )

    @app.get("/pedidos/{pedido_id}/vigilancia/relatorios/{relatorio_id}.md", tags=["Pedido de lote"])
    def relatorio(request: Request, pedido_id: str, relatorio_id: str, identidade: Identidade):
        documento = next((d for d in consultar(request, pedido_id, identidade) if d["id"] == relatorio_id), None)
        if documento is None:
            raise HTTPException(404, "rascunho não encontrado")
        return Response(
            documento["relatorio"], media_type="text/markdown; charset=utf-8", headers={"Cache-Control": "no-store"}
        )
