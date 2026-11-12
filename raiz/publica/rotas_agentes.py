"""Rotas curtas de submissão, acompanhamento e administração da plataforma de agentes."""

import hashlib
import json
import os
import re
import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

import anyio
from fastapi import Body, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from raiz.publica import chaves as K
from raiz.publica import conta as CT
from raiz.publica import trabalhos as T
from raiz.publica.oauth import ESCOPOS, administrador_da_empresa
from raiz.publica.privacidade import para_resposta

ESCOPOS_ACAO = {
    "consultar_disponibilidade": "consultar",
    "pedir_lote": "pedir",
    "comparar_lotes": "consultar",
    "acompanhar_contato": "consultar",
    "preparar_reserva": "reservar",
    "cancelar": "pedir",
}
Acao = Literal["consultar_disponibilidade", "pedir_lote", "comparar_lotes", "acompanhar_contato", "preparar_reserva"]


class PermissaoReserva(BaseModel):
    habilitado: bool


def base_publica() -> str:
    url = os.environ.get("RAIZ_API_PUBLICA_URL") or os.environ.get("RAIZ_MCP_RESOURCE", "").removesuffix("/mcp")
    u = urlsplit(url)
    if not u.hostname or u.username or u.password or u.query or u.fragment:
        raise CT.ErroConta("origem_indisponivel", "origem pública não configurada", "avise a Raíz", 503)
    if u.scheme != "https" and not (u.scheme == "http" and u.hostname in {"localhost", "127.0.0.1"}):
        raise CT.ErroConta("origem_indisponivel", "origem pública deve usar HTTPS", "avise a Raíz", 503)
    return url.rstrip("/") + "/v1"


def exigir_escopo(engine, acesso: K.Acesso, ferramenta: str) -> None:
    escopo = ESCOPOS_ACAO[ferramenta]
    if acesso.via == "mcp" and (escopo not in acesso.escopos or not acesso.escopos <= ESCOPOS):
        raise CT.ErroConta(
            "escopo_insuficiente", f"a operação exige {escopo}", "peça autorização ao administrador", 403
        )
    if escopo == "reservar" and acesso.via != "sessao":
        with engine.connect() as con:
            pode = con.execute(
                text("select reservar_habilitado from negocio.conta_api where cliente_id=:c"), {"c": acesso.cliente_id}
            ).scalar()
        if not pode:
            raise CT.ErroConta(
                "reservar_desligado",
                "reservar está desabilitado na empresa",
                "o administrador da empresa deve habilitar a permissão",
                403,
            )


def instalar(app, engine_de, acesso, limiter, limite: str, verificador=None) -> None:
    Acesso = Annotated[K.Acesso, Depends(acesso)]

    @app.post("/agentes/{ferramenta}", status_code=202, tags=["Operações dos agentes"])
    @limiter.shared_limit(limite, scope="empresa")
    def submeter(
        ferramenta: Acao,
        request: Request,
        a: Acesso,
        corpo: Annotated[dict, Body()],
        idempotency_key: Annotated[str | None, Header()] = None,
    ):
        eng = engine_de(request)
        exigir_escopo(eng, a, ferramenta)
        if ferramenta in {"pedir_lote", "preparar_reserva"} and not idempotency_key:
            raise CT.ErroConta(
                "idempotencia_obrigatoria", "falta Idempotency-Key", "gere uma chave para a intenção", 422
            )
        if ferramenta == "preparar_reserva":
            if set(corpo) != {"pedido_id"}:
                raise CT.ErroConta("corpo_invalido", "informe somente pedido_id", "corrija o corpo", 422)
            corpo = {**corpo, "base_url": base_publica()}
        request.state.ferramenta = ferramenta
        resultado = T.submeter(eng, a.cliente_id, ferramenta, corpo, idempotency_key or str(uuid.uuid4()))
        request.state.pedido_id = resultado["pedido_id"]
        return JSONResponse(
            para_resposta(resultado),
            status_code=202,
            headers={"Location": f"/v1/operacoes/{resultado['pedido_id']}"},
        )

    @app.get("/operacoes/{pedido_id}", tags=["Operações dos agentes"])
    @limiter.shared_limit(limite, scope="empresa")
    def operacao(pedido_id: uuid.UUID, request: Request, a: Acesso):
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        r = T.obter(eng, a.cliente_id, str(pedido_id))
        ferramenta = r.get("ferramenta", "pedir_lote")
        exigir_escopo(eng, a, ferramenta)
        if ferramenta != "consultar_disponibilidade":
            CT.exigir_liberacao(eng, a.cliente_id)
        if (
            ferramenta == "preparar_reserva"
            and r.get("negocio_pedido_id")
            and r["estado"] in {"completed", "input-required"}
        ):
            from raiz.pedidos import servico as S

            r["resultado"] = S.cobranca_do_pedido(eng, r["negocio_pedido_id"], a.cliente_id, base_url=base_publica())
            if r["resultado"].get("estado") in {"ativa", "convertida"}:
                r["estado"] = "completed"
            else:
                r["estado"] = "input-required"
        return JSONResponse(para_resposta(r))

    @app.post("/pedidos/{pedido_id}/cancelar", tags=["Operações dos agentes"])
    @limiter.shared_limit(limite, scope="empresa")
    def cancelar(
        pedido_id: uuid.UUID,
        request: Request,
        a: Acesso,
        idempotency_key: Annotated[str, Header(min_length=8, max_length=200)],
    ):
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        exigir_escopo(eng, a, "cancelar")
        request.state.ferramenta = "cancelar"
        return cancelar_idempotente(eng, a.cliente_id, str(pedido_id), idempotency_key)

    async def administrador(request: Request, authorization: Annotated[str, Header()]):
        if verificador is None:
            raise HTTPException(503, "Keycloak não configurado")
        token = await verificador.verify_token(authorization.removeprefix("Bearer ").strip())
        cid = (token.claims or {}).get("empresa_id") if token else None
        if cid is None or not administrador_da_empresa(token, cid):
            raise HTTPException(403, "somente o administrador da própria empresa habilita reservar")
        request.state.acesso = K.Acesso(cid, None, "mcp", frozenset(token.scopes))
        request.state.cliente_id = cid
        if not getattr(request.state, "_rate_limiting_complete", False):
            await anyio.to_thread.run_sync(limiter._check_request_limit, request, request.scope.get("endpoint"), False)
            request.state._rate_limiting_complete = True
        return token

    @app.put("/conta/permissoes/reservar", tags=["Conta da empresa"])
    @limiter.shared_limit(limite, scope="empresa")
    def permissao(request: Request, corpo: PermissaoReserva, token: Annotated[object, Depends(administrador)]):
        cid = token.claims["empresa_id"]
        eng = engine_de(request)
        CT.exigir(eng, cid)
        try:
            with eng.begin() as con:
                con.execute(text("set local lock_timeout='500ms'"))
                con.execute(text("set local statement_timeout='3s'"))
                con.execute(
                    text("update negocio.conta_api set reservar_habilitado=:h where cliente_id=:c"),
                    {"h": corpo.habilitado, "c": cid},
                )
                con.execute(
                    text("""insert into negocio.permissao_reserva_evento
                    (cliente_id, habilitado, administrador_hash) values (:c,:h,:a)"""),
                    {
                        "c": cid,
                        "h": corpo.habilitado,
                        "a": hashlib.sha256((token.subject or token.client_id).encode()).hexdigest(),
                    },
                )
        except DBAPIError:
            raise CT.ErroConta(
                "permissao_ocupada", "uma operação da empresa está em andamento", "repita a alteração", 503
            ) from None
        return {"reservar_habilitado": corpo.habilitado}


def cancelar_idempotente(engine, cliente_id: int, pedido_id: str, chave: str) -> dict:
    """A mesma intenção nunca repete estorno/evento nem passa a cancelar outro pedido.

    A chave é por empresa e ação, e o identificador da URL faz parte do corpo lógico.
    Livro-caixa, estado, outbox e recibo de idempotência confirmam juntos.
    """
    if not isinstance(chave, str) or not re.fullmatch(r"[\x21-\x7e]{8,200}", chave):
        raise CT.ErroConta("idempotencia_obrigatoria", "Idempotency-Key inválida", "use 8 a 200 caracteres ASCII", 422)
    try:
        pedido_id = str(uuid.UUID(pedido_id))
    except (ValueError, TypeError, AttributeError) as ex:
        raise CT.ErroConta("pedido", "pedido não encontrado", "confira o identificador", 404) from ex
    chave_hash = hashlib.sha256(chave.encode()).hexdigest()
    try:
        with engine.begin() as con:
            con.execute(text("set local lock_timeout='500ms'"))
            con.execute(text("set local statement_timeout='3s'"))
            # Serializa somente a intenção, sem travar todas as operações da empresa.
            con.execute(
                text("select pg_advisory_xact_lock(hashtextextended(:s,0))"),
                {"s": f"cancelar:{cliente_id}:{chave_hash}"},
            )
            anterior = (
                con.execute(
                    text("""select pedido_id, resposta from negocio.cancelamento_api
                where cliente_id=:c and chave_hash=:h"""),
                    {"c": cliente_id, "h": chave_hash},
                )
                .mappings()
                .first()
            )
            if anterior is not None:
                if str(anterior["pedido_id"]) != pedido_id:
                    raise CT.ErroConta(
                        "idempotencia_conflito",
                        "essa chave já identifica outro cancelamento",
                        "use uma nova chave somente para uma nova intenção",
                        409,
                    )
                return anterior["resposta"]
            vinculo = T.ConexaoVinculada(con)
            try:
                resultado = T.cancelar(vinculo, cliente_id, pedido_id)
            except T.ErroTrabalho as ex:
                if ex.status == 404:
                    resultado = cancelar_pedido(vinculo, cliente_id, pedido_id)
                elif ex.status == 409:
                    resultado = {
                        "pedido_id": pedido_id,
                        "estado": "input-required",
                        "acao": "a operação já iniciou; acompanhe o resultado e solicite revisão do cancelamento",
                    }
                else:
                    raise
            con.execute(
                text("""insert into negocio.cancelamento_api (cliente_id,chave_hash,pedido_id,resposta)
                values (:c,:h,:p,cast(:r as jsonb))"""),
                {"c": cliente_id, "h": chave_hash, "p": pedido_id, "r": json.dumps(resultado)},
            )
            return resultado
    except DBAPIError as ex:
        raise CT.ErroConta(
            "cancelamento_ocupado", "a operação está ocupada", "repita com a mesma Idempotency-Key", 503
        ) from ex


def cancelar_pedido(engine, cliente_id: int, pedido_id: str) -> dict:
    from raiz.publica.webhooks import enfileirar

    with engine.begin() as con:
        con.execute(text("set local lock_timeout='500ms'"))
        con.execute(text("set local statement_timeout='3s'"))
        p = con.execute(
            text("select estado from negocio.pedido where id=:p and cliente_id=:c for update"),
            {"p": pedido_id, "c": cliente_id},
        ).first()
        if p is None:
            raise CT.ErroConta("pedido", "pedido não encontrado", "confira o identificador", 404)
        reservas = con.execute(
            text("""select id, estado from negocio.reserva
            where pedido_id=:p order by id for update"""),
            {"p": pedido_id},
        ).all()
        # Uma cobrança emitida já deriva de decisão humana: nem o Pix pendente é cancelado
        # pelo agente. A trava da reserva impede aprovação simultânea da pré-reserva.
        cobranca = con.execute(
            text("""select 1 from negocio.cobranca c
            join negocio.reserva r on r.id=c.reserva_id where r.pedido_id=:p limit 1"""),
            {"p": pedido_id},
        ).first()
        if (
            cobranca
            or any(r.estado in {"ativa", "convertida", "conflito"} for r in reservas)
            or p.estado in {"reservado", "contrato"}
        ):
            return {
                "pedido_id": pedido_id,
                "estado": "input-required",
                "acao": "uma pessoa deve tratar a cobrança Pix, a reserva paga ou o contrato com a Raíz",
            }
        con.execute(
            text("update negocio.pedido set estado='cancelado', atualizado_em=now() where id=:p"), {"p": pedido_id}
        )
        con.execute(
            text(
                "update negocio.contato_fila set estado='cancelado' where pedido_id=:p "
                "and estado in ('na_fila','enviado')"
            ),
            {"p": pedido_id},
        )
        con.execute(
            text("""update negocio.reserva set estado='cancelada', confirmacao_hash=null,
            confirmacao_token_cifrado=null where pedido_id=:p
            and estado in ('aguardando_confirmacao','aguardando_pagamento')"""),
            {"p": pedido_id},
        )
        if p.estado != "cancelado":
            enfileirar(con, cliente_id, "pedido.atualizado", pedido_id, "cancelado")
    return {"pedido_id": pedido_id, "estado": "canceled"}
