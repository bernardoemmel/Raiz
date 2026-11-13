"""Acesso pago à ficha da terra: carteira, Pix, desbloqueio e solicitação interna.

Créditos de consulta não são créditos de carbono. Um crédito pago libera um CAR para
o cliente; releitura não debita novamente. Nenhum dado ou canal do dono entra aqui.
O pagamento só é creditado depois de conferir a cobrança de produção no provedor.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid

from sqlalchemy import Engine, text

from raiz import prospeccao_precos as precos
from raiz.busca import normalizar_codigo
from raiz.pedidos import pix

PRECOS_PADRAO = precos.PRECOS_PADRAO


class ErroAcesso(ValueError):
    def __init__(self, status: int, mensagem: str, retry_after: int | None = None):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem
        self.retry_after = retry_after


def planos() -> dict:
    """Três modalidades propostas; a assinatura aguarda implementação do ciclo."""
    try:
        catalogo = precos.carregar_catalogo(PRECOS_PADRAO)
    except ValueError as ex:
        raise ErroAcesso(503, "O catálogo de créditos está temporariamente indisponível.") from ex
    aprovada = catalogo["status"] == "aprovado"
    for oferta in catalogo["planos"]:
        oferta["pagamento_disponivel"] = bool(
            aprovada
            and oferta["status"] == "aprovado"
            and oferta["cobranca_implementada"]
            and pix.producao_habilitada()
        )
    disponivel = any(oferta["pagamento_disponivel"] for oferta in catalogo["planos"])
    return {
        **catalogo,
        "custo_ficha": 1,
        "unidade": "crédito de consulta",
        "pix_modo": pix.modo(),
        "pagamento_disponivel": disponivel,
        "mensagem": "Um crédito pago libera a ficha deste CAR; novas leituras não consomem crédito."
        if disponivel
        else "Preços a definir pelo fundador. Vendas desativadas até aprovar o catálogo e ativar o Pix de produção."
        if not aprovada
        else "Catálogo aprovado. Vendas exigem Pix de produção e uma modalidade com cobrança implementada.",
    }


def _carteira(con, cliente_id: int) -> int:
    """Trava única por cliente: compras, créditos e débitos serializam no banco."""
    if not con.execute(text("select id from negocio.cliente where id = :c and ativo"), {"c": cliente_id}).scalar():
        raise ErroAcesso(401, "Entre novamente para continuar.")
    con.execute(
        text("insert into negocio.prospeccao_carteira(cliente_id) values (:c) on conflict do nothing"),
        {"c": cliente_id},
    )
    return con.execute(
        text("select creditos from negocio.prospeccao_carteira where cliente_id = :c for update"),
        {"c": cliente_id},
    ).scalar_one()


def saldo(engine: Engine, cliente_id: int) -> dict:
    with engine.begin() as con:
        creditos = _carteira(con, cliente_id)
        n = con.execute(
            text("select count(*) from negocio.prospeccao_desbloqueio where cliente_id = :c"), {"c": cliente_id}
        ).scalar_one()
    return {"creditos": creditos, "fichas_desbloqueadas": n}


def _compra_json(compra) -> dict:
    return {
        "id": str(compra.id),
        "plano": compra.plano,
        "creditos": compra.creditos,
        "valor_rs": float(compra.valor_rs),
        "estado": compra.estado,
        "modo": compra.modo,
        "pix_copia_cola": compra.pix_copia_cola,
        "expira_em": compra.expira_em.isoformat(),
    }


def listar_compras(engine: Engine, cliente_id: int) -> list[dict]:
    """Recupera cobranças após sair da tela, sem depender do armazenamento do navegador.

    Pendentes vêm primeiro para que um pagamento ainda não conciliado não suma do
    histórico. Esta leitura não consulta o provedor nem presume pagamento.
    """
    with engine.begin() as con:
        _carteira(con, cliente_id)
        compras = con.execute(
            text("""select * from negocio.prospeccao_compra where cliente_id = :c
                    order by (estado = 'pendente') desc, criada_em desc, id desc limit 20"""),
            {"c": cliente_id},
        ).all()
        return [_compra_json(compra) for compra in compras]


def iniciar_compra(engine: Engine, cliente_id: int, plano: str, chave_idempotencia: str) -> dict:
    """Preço e créditos vêm do catálogo do servidor. Retry retorna a mesma cobrança."""
    if not isinstance(chave_idempotencia, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", chave_idempotencia):
        raise ErroAcesso(422, "Informe uma chave de idempotência válida para a compra.")
    with engine.begin() as con:
        _carteira(con, cliente_id)
        anterior = con.execute(
            text("""select * from negocio.prospeccao_compra
                    where cliente_id = :c and chave_idempotencia = :k"""),
            {"c": cliente_id, "k": chave_idempotencia},
        ).first()
        if anterior:
            if anterior.plano != plano:
                raise ErroAcesso(409, "Esta chave já identifica outra compra.")
            return _compra_json(anterior)
        catalogo = planos()
        oferta = next((p for p in catalogo["planos"] if p["id"] == plano), None)
        if oferta is None:
            raise ErroAcesso(422, "Plano não encontrado.")
        if oferta["modalidade"] == "assinatura":
            raise ErroAcesso(503, "Assinatura em proposta: a cobrança por ciclo ainda não está disponível.")
        if not catalogo["pagamento_disponivel"] or not oferta["pagamento_disponivel"]:
            raise ErroAcesso(503, "O pagamento está indisponível neste momento.")
        cob = pix.criar(oferta["valor_rs"], f"Raíz {oferta['creditos']} consultas", 3600)
        if cob.modo != "producao" or cob.externo_id.startswith("teste_"):
            raise ErroAcesso(503, "O pagamento está em teste. Nenhum crédito de consulta foi liberado.")
        compra = con.execute(
            text("""insert into negocio.prospeccao_compra
                    (id, cliente_id, chave_idempotencia, plano, creditos, valor_rs,
                     externo_id, modo, estado, pix_copia_cola, expira_em)
                    values (:id, :c, :k, :p, :n, :v, :externo, :modo, 'pendente', :pix, :exp)
                    returning *"""),
            {
                "id": uuid.uuid4(),
                "c": cliente_id,
                "k": chave_idempotencia,
                "p": plano,
                "n": oferta["creditos"],
                "v": oferta["valor_rs"],
                "externo": cob.externo_id,
                "modo": cob.modo,
                "pix": cob.copia_e_cola,
                "exp": cob.expira_em,
            },
        ).one()
        return _compra_json(compra)


def conferir_compra(engine: Engine, cliente_id: int, compra_id: str) -> dict:
    """Consulta o provedor; só uma transação confirma e credita cada pagamento."""
    try:
        ident = uuid.UUID(str(compra_id))
    except ValueError as ex:
        raise ErroAcesso(404, "Compra não encontrada.") from ex
    with engine.begin() as con:
        _carteira(con, cliente_id)
        compra = con.execute(
            text("select * from negocio.prospeccao_compra where id = :id and cliente_id = :c for update"),
            {"id": ident, "c": cliente_id},
        ).first()
        if compra is None:
            raise ErroAcesso(404, "Compra não encontrada.")
        if compra.estado == "paga":
            return _compra_json(compra)
        if compra.modo != "producao" or compra.externo_id.startswith("teste_"):
            raise ErroAcesso(409, "Cobranças de teste não liberam fichas pagas.")
        estado = pix.conferir(compra.externo_id)
        if estado not in ("pendente", "paga", "expirada", "cancelada"):
            raise ErroAcesso(502, "Não foi possível confirmar o estado do pagamento.")
        if estado == "paga":
            con.execute(
                text("""insert into negocio.prospeccao_movimento(cliente_id, quantidade, compra_id)
                        values (:c, :n, :id)"""),
                {"c": cliente_id, "n": compra.creditos, "id": ident},
            )
            con.execute(
                text("update negocio.prospeccao_carteira set creditos = creditos + :n where cliente_id = :c"),
                {"c": cliente_id, "n": compra.creditos},
            )
        atual = con.execute(
            text("""update negocio.prospeccao_compra set estado = :s,
                    paga_em = case when :s = 'paga' then now() else paga_em end
                    where id = :id returning *"""),
            {"s": estado, "id": ident},
        ).one()
        return _compra_json(atual)


def _car_visivel(con, cliente_id: int, codigo_car: str) -> str:
    codigo = normalizar_codigo(codigo_car)
    if not codigo or len(codigo) > 64:
        raise ErroAcesso(404, "Fazenda não encontrada.")
    car = con.execute(
        text("""select v.cod_imovel from funil.vigente v where v.cod_busca = :car
                and not exists (
                    select 1 from negocio.reserva_fazenda rf join negocio.reserva r on r.id = rf.reserva_id
                    where rf.cod_imovel = v.cod_imovel and rf.ativa and r.cliente_id <> :c
                ) limit 1"""),
        {"car": codigo, "c": cliente_id},
    ).scalar()
    if car is None:
        raise ErroAcesso(404, "Fazenda não encontrada.")
    return car


def _liberada(con, cliente_id: int, car: str) -> bool:
    return bool(
        con.execute(
            text("select 1 from negocio.prospeccao_desbloqueio where cliente_id = :c and cod_imovel = :car"),
            {"c": cliente_id, "car": car},
        ).scalar()
    )


def desbloquear(engine: Engine, cliente_id: int, codigo_car: str) -> dict:
    """Débito de um crédito, registro e liberação são atômicos; CAR normalizado."""
    with engine.begin() as con:
        creditos = _carteira(con, cliente_id)
        car = _car_visivel(con, cliente_id, codigo_car)
        cobrado = not _liberada(con, cliente_id, car)
        if cobrado:
            if creditos < 1:
                raise ErroAcesso(402, "Compre créditos de consulta para liberar a ficha completa.")
            con.execute(
                text("insert into negocio.prospeccao_desbloqueio(cliente_id, cod_imovel) values (:c, :car)"),
                {"c": cliente_id, "car": car},
            )
            con.execute(
                text("""insert into negocio.prospeccao_movimento(cliente_id, quantidade, cod_imovel)
                        values (:c, -1, :car)"""),
                {"c": cliente_id, "car": car},
            )
            con.execute(
                text("update negocio.prospeccao_carteira set creditos = creditos - 1 where cliente_id = :c"),
                {"c": cliente_id},
            )
            creditos -= 1
    return {"codigo_car": car, "desbloqueada": True, "cobrado": cobrado, "saldo": creditos}


def exigir_desbloqueio(engine: Engine, cliente_id: int, codigo_car: str) -> str:
    """Retorna CAR canônico apenas se pago, ainda vigente e disponível ao cliente."""
    with engine.begin() as con:
        _carteira(con, cliente_id)
        car = _car_visivel(con, cliente_id, codigo_car)
        if not _liberada(con, cliente_id, car):
            raise ErroAcesso(402, "Libere a ficha com um crédito de consulta.")
        return car


def pedir_contato(engine: Engine, cliente_id: int, codigo_car: str) -> dict:
    """Registra na Raíz; não busca, publica nem envia mensagem ao dono."""
    with engine.begin() as con:
        _carteira(con, cliente_id)
        car = _car_visivel(con, cliente_id, codigo_car)
        if not _liberada(con, cliente_id, car):
            raise ErroAcesso(402, "Libere a ficha antes de pedir contato.")
        con.execute(
            text("""insert into negocio.prospeccao_contato(id, cliente_id, cod_imovel)
                    values (:id, :c, :car) on conflict(cliente_id, cod_imovel) do nothing"""),
            {"id": uuid.uuid4(), "c": cliente_id, "car": car},
        )
        pedido = con.execute(
            text("select * from negocio.prospeccao_contato where cliente_id = :c and cod_imovel = :car"),
            {"c": cliente_id, "car": car},
        ).one()
        return {
            "id": str(pedido.id),
            "codigo_car": car,
            "estado": pedido.estado,
            "criado_em": pedido.criado_em.isoformat(),
            "mensagem": "Pedido registrado na Raíz. O contato será tratado depois.",
        }


def limitar(engine: Engine, chave: str, acao: str, limite: int, janela_s: int = 60) -> None:
    """Contador atômico compartilhado entre processos, sem IP ou token em texto.

    Chaves devem distinguir cliente e IP. Na borda HTTP, usar o endereço da conexão,
    nunca aceitar X-Forwarded-For sem um proxy explicitamente confiável.
    """
    if limite < 1 or janela_s < 1:
        raise ValueError("limite e janela devem ser positivos")
    chave_hash = hashlib.sha256(chave.encode()).hexdigest()
    with engine.begin() as con:
        con.execute(text("delete from negocio.prospeccao_limite where expira_em < now() - interval '7 days'"))
        contador = con.execute(
            text("""insert into negocio.prospeccao_limite(chave_hash, acao, janela_s, quantidade, expira_em)
                    values (:h, :a, :j, 1, now() + :j * interval '1 second')
                    on conflict(chave_hash, acao, janela_s) do update set
                        quantidade = case when negocio.prospeccao_limite.expira_em <= now() then 1
                            else negocio.prospeccao_limite.quantidade + 1 end,
                        expira_em = case when negocio.prospeccao_limite.expira_em <= now()
                            then now() + :j * interval '1 second' else negocio.prospeccao_limite.expira_em end
                    returning quantidade, expira_em"""),
            {"h": chave_hash, "a": acao, "j": janela_s},
        ).one()
    # Fora da transação: uma tentativa negada também fica contada.
    if contador.quantidade > limite:
        espera = max(1, int((contador.expira_em - dt.datetime.now(dt.UTC)).total_seconds()) + 1)
        raise ErroAcesso(429, "Limite de consultas atingido. Aguarde antes de tentar novamente.", espera)
