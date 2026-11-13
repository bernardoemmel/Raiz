"""Aprovação humana da reserva: empresa autenticada, prazo, salvaguardas e recibo assinado.

O recibo atesta a autorização humana para gerar a cobrança. Nunca atesta pagamento ou certificação de carbono.
"""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import Engine, text

from raiz.pedidos import servico as S
from raiz.publica import recibos


class ErroAprovacao(S.ErroPedido):
    def __init__(self, mensagem: str, status: int = 422):
        super().__init__(mensagem)
        self.status = status


def ver(engine: Engine, token: str, cliente_id: int) -> dict:
    """Resumo anterior ao clique, só para a pessoa autenticada da empresa da reserva."""
    if not isinstance(cliente_id, int) or isinstance(cliente_id, bool) or cliente_id <= 0:
        raise ErroAprovacao("entre com uma sessão de pessoa da empresa", 401)
    if not isinstance(token, str) or not 24 <= len(token) <= 200:
        raise ErroAprovacao("link de confirmação inválido, usado ou vencido", 410)
    with engine.connect() as con:
        res = (
            con.execute(
                text("""select pedido_id,valor_rs,ha,dias,preco_valido_ate,estado from negocio.reserva
            where cliente_id=:c and confirmacao_hash=:h and estado='aguardando_confirmacao'
              and confirmacao_expira > now() and preco_valido_ate > now()"""),
                {"c": cliente_id, "h": S._hash(token)},
            )
            .mappings()
            .first()
        )
    if res is None:
        raise ErroAprovacao("link de confirmação inválido, usado ou vencido", 410)
    return {
        "pedido": str(res["pedido_id"]),
        "valor_brl": float(res["valor_rs"]),
        "currency": "BRL",
        "hectares": round(res["ha"], 1),
        "preco_valido_ate": res["preco_valido_ate"].isoformat(),
        "exclusividade": {"dias": res["dias"], "inicio": "apos_pagamento_confirmado"},
        "estado": res["estado"],
        "pagamento_confirmado": False,
        "condicoes": "Aprovar gera a cobrança Pix; a exclusividade começa quando o pagamento for confirmado. "
        "O valor da reserva é abatido da conexão quando o contrato fecha.",
    }


def aprovar(engine: Engine, token: str, cliente_id: int) -> dict:
    """Somente pessoa autenticada da empresa; o adaptador HTTP rejeita API keys e OAuth de agente."""
    from raiz import salvaguardas as SG

    if not isinstance(cliente_id, int) or isinstance(cliente_id, bool) or cliente_id <= 0:
        raise ErroAprovacao("entre com uma sessão de pessoa da empresa", 401)
    if not isinstance(token, str) or not 24 <= len(token) <= 200:
        raise ErroAprovacao("link de confirmação inválido, usado ou vencido", 410)
    with engine.begin() as con:
        pedido_id = con.execute(
            text("select pedido_id from negocio.reserva where cliente_id=:c and confirmacao_hash=:h"),
            {"c": cliente_id, "h": S._hash(token)},
        ).scalar()
        if pedido_id is None:
            raise ErroAprovacao("link de confirmação inválido, usado ou vencido", 410)
        # Serializa decisão humana com fechamento, pagamento, cancelamento e expiração do grupo.
        p = S._linha_pedido(con, str(pedido_id), cliente_id, travar=True)
        res = (
            con.execute(
                text("""select * from negocio.reserva
            where cliente_id=:c and confirmacao_hash=:h and estado='aguardando_confirmacao'
              and confirmacao_expira > now() and preco_valido_ate > now() for update"""),
                {"c": cliente_id, "h": S._hash(token)},
            )
            .mappings()
            .first()
        )
        if res is None:
            raise ErroAprovacao("link de confirmação inválido, usado ou vencido", 410)
        if p["estado"] != "grupo_pronto":
            raise ErroAprovacao("o grupo mudou; prepare a reserva novamente")
        cods = [
            r[0]
            for r in con.execute(
                text("select cod_imovel from negocio.reserva_fazenda where reserva_id=:r"), {"r": res["id"]}
            )
        ]
        if not cods or set(cods) != set(S._grupo(con, p["id"])):
            raise ErroAprovacao("as fazendas do grupo mudaram; prepare a reserva novamente")
        ocupadas = con.execute(
            text("select 1 from negocio.reserva_fazenda where cod_imovel=any(:c) and ativa limit 1"), {"c": cods}
        ).first()
        if ocupadas:
            raise ErroAprovacao("uma fazenda já está reservada; refaça o grupo")
        SG.exigir_para_reserva(engine, cods)
        try:
            chave = recibos.chave_privada()
        except (ValueError, TypeError) as ex:
            raise ErroAprovacao("assinatura do recibo indisponível; a reserva ainda não foi aprovada", 503) from ex
        agora = dt.datetime.now(dt.UTC)
        mandato = {
            "tipo": "aprovacao_humana_reserva",
            "pagamento_confirmado": False,
            "iat": int(agora.timestamp()),
            "exp": int(res["preco_valido_ate"].timestamp()),
            "empresa": cliente_id,
            "reserva": res["id"],
            "pedido": str(res["pedido_id"]),
            "valor": f"{res['valor_rs']:.2f}",
            "currency": "BRL",
            "preco_valido_ate": res["preco_valido_ate"].isoformat(),
            "exclusividade": {"dias": res["dias"], "inicio": "apos_pagamento_confirmado"},
            "condicoes": {
                "acao": "gerar_cobranca_pix",
                "pagador": "pessoa",
                "agente_pode_pagar": False,
                "reserva_depende_pagamento": True,
                "abatimento_na_conexao": True,
            },
        }
        recibo = recibos.assinar(mandato, chave)
        # Primeiro validamos assinatura/salvaguardas; só então uma pessoa gera o Pix. Não há pagamento aqui.
        S._cobrar(
            con, res["id"], p, float(res["valor_rs"]), validade_s=int((res["preco_valido_ate"] - agora).total_seconds())
        )
        con.execute(
            text("""update negocio.reserva set estado='aguardando_pagamento', confirmada_em=:ag,
            confirmacao_hash=null, confirmacao_token_cifrado=null, recibo_aprovacao=:rec where id=:id"""),
            {"ag": agora, "rec": recibo, "id": res["id"]},
        )
        con.execute(
            text("""insert into negocio.reserva_evento(reserva_id,evento,quem,valor_rs,detalhe)
            values(:r,'confirmada',:q,:v,cast(:d as jsonb))"""),
            {
                "r": res["id"],
                "q": f"pessoa-empresa:{cliente_id}",
                "v": res["valor_rs"],
                "d": json.dumps({"recibo_assinado": True, "pagamento_confirmado": False}),
            },
        )
    return S.cobranca_do_pedido(engine, str(res["pedido_id"]), cliente_id)
