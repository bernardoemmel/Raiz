"""Administração de webhooks pela pessoa da empresa; segredo só na resposta de criação."""

import hashlib
import re
import uuid
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from raiz.pessoal import Cofre, SemChavePessoal
from raiz.publica import chaves as K
from raiz.publica import conta as CT
from raiz.publica import webhooks as W


class NovoWebhook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048, description="URL HTTPS em host aprovado pela Raíz.")


def _erro(slug: str, detalhe: str, status: int = 422):
    return CT.ErroConta(slug, detalhe, "entre como pessoa da empresa e confira o destino aprovado", status)


def _pessoa(a: K.Acesso) -> None:
    if a.via != "sessao":
        raise _erro("so_pessoa", "apenas uma pessoa da empresa administra webhooks", 403)


def _cofre() -> Cofre:
    try:
        return Cofre()
    except (SemChavePessoal, ValueError):
        raise _erro("cofre_indisponivel", "cofre de webhooks não configurado; avise a Raíz", 503) from None


@contextmanager
def _transacao(engine):
    try:
        with engine.begin() as con:
            con.execute(text("select set_config('lock_timeout', '500ms', true)"))
            con.execute(text("select set_config('statement_timeout', '3000ms', true)"))
            yield con
    except DBAPIError:
        raise _erro("webhook_indisponivel", "a configuração está ocupada; repita a mesma solicitação", 503) from None


def instalar(app, engine_de, pessoa, limiter, limite: str) -> None:
    Pessoa = Annotated[K.Acesso, Depends(pessoa)]

    @app.post("/webhooks", status_code=201, tags=["Conta da empresa"], summary="Cadastrar destino de eventos")
    @limiter.shared_limit(limite, scope="empresa")
    def cadastrar(
        request: Request,
        corpo: NovoWebhook,
        a: Pessoa,
        idempotency_key: Annotated[str, Header()],
    ):
        _pessoa(a)
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        if not re.fullmatch(r"[\x21-\x7e]{8,200}", idempotency_key):
            raise _erro("idempotencia_invalida", "Idempotency-Key exige 8 a 200 caracteres ASCII sem espaços")
        try:
            W.validar_destino(corpo.url)
        except ValueError:
            raise _erro("webhook_destino_invalido", "destino HTTPS não autorizado") from None
        cofre = _cofre()
        digest = hashlib.sha256(f"raiz-webhook|{a.cliente_id}|{idempotency_key}".encode()).digest()
        inscricao_id = str(uuid.UUID(bytes=digest[:16], version=4))
        # Trava por empresa torna replay/capacidade atômicos sem guardar a chave recebida.
        with _transacao(eng) as con:
            con.execute(
                text("select cliente_id from negocio.conta_api where cliente_id=:c for update"), {"c": a.cliente_id}
            )
            existente = (
                con.execute(
                    text("SELECT id, url_cifrada, ativa FROM negocio.webhook_inscricao WHERE id=:id AND cliente_id=:c"),
                    {"id": inscricao_id, "c": a.cliente_id},
                )
                .mappings()
                .first()
            )
            if existente:
                if cofre.decifrar(existente["url_cifrada"]) != corpo.url:
                    raise _erro("idempotencia_conflito", "essa chave já cadastrou outro destino", 409)
                return JSONResponse(
                    {
                        "id": inscricao_id,
                        "ativa": existente["ativa"],
                        "segredo": None,
                        "aviso": "O segredo foi exibido na criação e não é retornado novamente.",
                    },
                    headers={"Cache-Control": "no-store"},
                )
            total = con.execute(
                text("SELECT count(*) FROM negocio.webhook_inscricao WHERE cliente_id=:c AND ativa"),
                {"c": a.cliente_id},
            ).scalar_one()
            if total >= 5:
                raise _erro("webhook_limite", "a empresa já tem cinco destinos ativos", 409)
            segredo = W.gerar_segredo()
            W.cadastrar_inscricao(con, a.cliente_id, corpo.url, segredo, cofre=cofre, inscricao_id=inscricao_id)
        return JSONResponse(
            {"id": inscricao_id, "ativa": True, "segredo": segredo},
            status_code=201,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/webhooks", tags=["Conta da empresa"], summary="Listar inscrições sem revelar destinos ou segredos")
    @limiter.shared_limit(limite, scope="empresa")
    def listar(request: Request, a: Pessoa):
        _pessoa(a)
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        with _transacao(eng) as con:
            linhas = con.execute(
                text(
                    "SELECT id, ativa, criada_em FROM negocio.webhook_inscricao "
                    "WHERE cliente_id=:c ORDER BY criada_em,id LIMIT 100"
                ),
                {"c": a.cliente_id},
            ).mappings()
            itens = [{"id": str(r["id"]), "ativa": r["ativa"], "criada_em": r["criada_em"].isoformat()} for r in linhas]
        return JSONResponse({"inscricoes": itens}, headers={"Cache-Control": "no-store"})

    @app.delete(
        "/webhooks/{inscricao_id}", tags=["Conta da empresa"], summary="Desativar destino e cancelar entregas pendentes"
    )
    @limiter.shared_limit(limite, scope="empresa")
    def excluir(inscricao_id: uuid.UUID, request: Request, a: Pessoa):
        _pessoa(a)
        eng = engine_de(request)
        CT.exigir(eng, a.cliente_id)
        with _transacao(eng) as con:
            r = con.execute(
                text("UPDATE negocio.webhook_inscricao SET ativa=false WHERE id=:id AND cliente_id=:c RETURNING id"),
                {"id": inscricao_id, "c": a.cliente_id},
            ).first()
            if r is None:
                raise _erro("webhook_nao_encontrado", "inscrição não encontrada", 404)
            con.execute(
                text("""UPDATE negocio.webhook_entrega SET estado='cancelada',lease_id=null,lease_ate=null
                WHERE inscricao_id=:id AND cliente_id=:c AND estado IN ('pendente','enviando')"""),
                {"id": inscricao_id, "c": a.cliente_id},
            )
        return JSONResponse({"id": str(inscricao_id), "ativa": False}, headers={"Cache-Control": "no-store"})
