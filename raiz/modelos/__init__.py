"""Modelos de linguagem da Raíz atrás de uma interface única (E7).

    from raiz.modelos import Pedido, chamar, modelo_conversa, modelo_triagem, modelo_local

Todo uso de modelo passa por `chamar`, que mede custo, manda o rastro ao Langfuse e grava em
operacao.chamada_modelo (custo por tarefa e por fazenda).
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from raiz.config import config
from raiz.modelos import rastro
from raiz.modelos.base import Modelo, Pedido, Resposta, Uso
from raiz.modelos.claude import Claude
from raiz.modelos.local import LlamaCpp
from raiz.privacidade import mascarar

__all__ = [
    "Claude",
    "LlamaCpp",
    "Modelo",
    "Pedido",
    "Resposta",
    "Uso",
    "chamar",
    "modelo_conversa",
    "modelo_local",
    "modelo_triagem",
    "registrar_chamada",
]


def modelo_conversa() -> Claude:
    return Claude(config().modelo_conversa)


def modelo_triagem() -> Claude:
    return Claude(config().modelo_triagem)


def modelo_local() -> LlamaCpp:
    return LlamaCpp()


def registrar_chamada(con: Connection, pedido: Pedido, resp: Resposta, papel: str, rastro_id: str | None) -> None:
    con.execute(
        text("""insert into operacao.chamada_modelo (tarefa, cod_imovel, cod_municipio, provedor, modelo, papel,
                tokens_entrada, tokens_saida, tokens_cache_leitura, tokens_cache_escrita, custo_usd, custo_fonte,
                duracao_ms, ok, erro, rastro_id)
                values (:t, :ci, :cm, :p, :m, :pa, :te, :ts, :tcl, :tce, :c, :cf, :d, :ok, :e, :r)"""),
        dict(
            t=pedido.tarefa,
            ci=pedido.cod_imovel,
            cm=pedido.cod_municipio,
            p=resp.provedor,
            m=resp.modelo,
            pa=papel,
            te=resp.uso.entrada,
            ts=resp.uso.saida,
            tcl=resp.uso.cache_leitura,
            tce=resp.uso.cache_escrita,
            c=resp.custo_usd,
            cf=resp.custo_fonte,
            d=resp.duracao_ms,
            ok=resp.ok,
            e=mascarar(resp.erro) if resp.erro else None,
            r=rastro_id,
        ),
    )


def chamar(modelo: Modelo, pedido: Pedido, papel: str = "unico", con: Connection | None = None) -> Resposta:
    with rastro.geracao(pedido, modelo.nome, papel) as g:
        resp = modelo.responder_json(pedido)
        rid = rastro.fechar(g, pedido, resp)
    if con is not None:
        registrar_chamada(con, pedido, resp, papel, rid)
    return resp
