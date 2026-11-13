"""Upload por pessoa autenticada; leitura e gabarito somente pela operação interna.

O corpo do upload é o PDF, sem nome de arquivo. Todas as respostas são privadas;
a credencial de uma empresa jamais escolhe o identificador de outra empresa.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from raiz.documentos import aprendizado
from raiz.documentos.certidao.entrada import MAX_BYTES, EntradaCertidao, ErroEntrada, capturar_previsao_banco
from raiz.pedidos import servico as pedidos
from raiz.pessoal import SemChavePessoal
from raiz.prospeccao_acesso import ErroAcesso, limitar
from raiz.publica import conta

PRIVADO = {"Cache-Control": "private, no-store", "Vary": "Authorization", "X-Content-Type-Options": "nosniff"}


class RotaCertidao(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def tratar(request):
            try:
                resposta = await original(request)
            except RequestValidationError:
                # O padrão do FastAPI ecoa o valor inválido, que pode ser pessoal.
                resposta = JSONResponse({"detail": "parametros_da_certidao_invalidos"}, status_code=422)
            except HTTPException as exc:
                resposta = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
            resposta.headers.update(PRIVADO)
            return resposta

        return tratar


class Revisao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fonte: Literal["conferencia_humana", "cartorio", "onr"]
    observado_em: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    situacao_real: Literal["conferida", "divergente", "cancelada", "revisar"] | None = None
    campos: dict[str, str] = Field(default_factory=dict, max_length=8)
    leitura_integral: bool | None = None
    conferido_por_pessoa: Literal[True]


def _executar(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ErroEntrada as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    except SemChavePessoal as exc:
        raise HTTPException(503, "armazenamento_privado_indisponivel") from exc
    except conta.ErroConta as exc:
        raise HTTPException(exc.status, "conta_aguarda_liberacao") from exc
    except ErroAcesso as exc:
        raise HTTPException(
            exc.status, "limite_de_documentos", headers={"Retry-After": str(exc.retry_after or 60)}
        ) from exc
    except pedidos.ErroPedido as exc:
        raise HTTPException(404, "pedido_nao_encontrado") from exc
    except ValueError as exc:
        raise HTTPException(422, "dados_da_conferencia_invalidos") from exc


def autorizar_car(engine, cliente_id: int, pedido_id: str, cod_imovel: str) -> None:
    """Pertencer ao pedido é obrigatório, mesmo com a conta comercial liberada."""
    conta.exigir_liberacao(engine, cliente_id)
    with engine.connect() as con:
        pedido = pedidos._linha_pedido(con, pedido_id, cliente_id)
        if pedido["estado"] in {"cancelado", "reserva_vencida"}:
            raise ErroEntrada(404, "pedido_nao_encontrado")
        sugestao = pedidos._ultima_sugestao(con, pedido_id)
    codigos = {i.get("cod_imovel") for o in sugestao["opcoes"] for i in o.get("itens", [])}
    if cod_imovel not in codigos:
        raise ErroEntrada(404, "imovel_nao_pertence_ao_pedido")


def roteador(engine_de: Callable, exigir_operador: Callable, entrada_de: Callable = EntradaCertidao) -> APIRouter:
    r = APIRouter(prefix="/documentos", tags=["certidões privadas"], route_class=RotaCertidao)

    def privado(response: Response):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization"
        response.headers["X-Content-Type-Options"] = "nosniff"

    def pessoa(request: Request, response: Response, authorization: str | None = Header(default=None)) -> int:
        privado(response)
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "entre_com_a_sessao_da_empresa")
        token = authorization[7:].strip()
        if token.startswith("raiz_"):
            raise HTTPException(403, "upload_exige_sessao_de_pessoa")
        cid = pedidos.cliente_da_sessao(engine_de(request), token)
        if cid is None:
            raise HTTPException(401, "sessao_invalida")
        _executar(conta.exigir_liberacao, engine_de(request), cid)
        _executar(limitar, engine_de(request), f"cliente:{cid}", "certidoes", 30)
        return int(cid)

    @r.post("/certidoes", status_code=201)
    async def enviar(
        request: Request,
        pedido_id: UUID,
        cod_imovel: Annotated[str, Query(pattern=r"^[A-Z]{2}-[0-9]{7}-[0-9A-F]{32}$")],
        idempotency_key: Annotated[UUID, Header()],
        cid: int = Depends(pessoa),
    ):
        _executar(autorizar_car, engine_de(request), cid, str(pedido_id), cod_imovel)
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/pdf":
            raise HTTPException(415, "envie_o_pdf_como_application_pdf")
        tamanho = request.headers.get("content-length")
        if tamanho and (not tamanho.isdecimal() or int(tamanho) > MAX_BYTES):
            raise HTTPException(413, "pdf_acima_de_20_mb")
        conteudo = bytearray()
        async for bloco in request.stream():
            if len(conteudo) + len(bloco) > MAX_BYTES:
                raise HTTPException(413, "pdf_acima_de_20_mb")
            conteudo.extend(bloco)
        entrada = _executar(entrada_de, cid)
        previsao = await run_in_threadpool(capturar_previsao_banco, engine_de(request), cod_imovel)
        return await run_in_threadpool(
            _executar,
            entrada.receber,
            bytes(conteudo),
            pedido_id=str(pedido_id),
            cod_imovel=cod_imovel,
            chave=str(idempotency_key),
            previsao=previsao,
        )

    @r.get("/certidoes/{documento_id}")
    def consultar(documento_id: UUID, request: Request, cid: int = Depends(pessoa)):
        resultado = _executar(_executar(entrada_de, cid).obter, str(documento_id))
        _executar(autorizar_car, engine_de(request), cid, resultado["pedido_id"], resultado["cod_imovel"])
        return resultado

    interno = [Depends(exigir_operador), Depends(privado)]

    @r.get("/operacao/{cliente_id}/certidoes/{documento_id}", dependencies=interno)
    def consultar_operacao(cliente_id: int, documento_id: UUID):
        return _executar(_executar(entrada_de, cliente_id).obter, str(documento_id))

    @r.post("/operacao/{cliente_id}/certidoes/{documento_id}/ler", dependencies=interno)
    def ler(cliente_id: int, documento_id: UUID, idempotency_key: Annotated[UUID, Header()]):
        return _executar(_executar(entrada_de, cliente_id).processar, str(documento_id), chave=str(idempotency_key))

    @r.post("/operacao/{cliente_id}/certidoes/{documento_id}/gabarito", dependencies=interno)
    def gabaritar(cliente_id: int, documento_id: UUID, corpo: Revisao, idempotency_key: Annotated[UUID, Header()]):
        return _executar(
            _executar(entrada_de, cliente_id).revisar,
            str(documento_id),
            chave=str(idempotency_key),
            **corpo.model_dump(exclude={"conferido_por_pessoa"}),
        )

    @r.post("/operacao/{cliente_id}/aprendizado/sincronizar", dependencies=interno)
    def sincronizar(cliente_id: int, request: Request):
        entrada = _executar(entrada_de, cliente_id)
        with engine_de(request).begin() as con:
            # Chaves da referência precisam continuar únicas entre armazéns das empresas.
            return json.loads(
                _executar(
                    aprendizado.enviar_ao_banco, entrada.armazem, con, referencia_prefixo=f"empresa:{cliente_id}:"
                )
            )

    return r
