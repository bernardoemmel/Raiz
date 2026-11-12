"""Chave de API por empresa (só na API REST; o MCP remoto usa OAuth) e o registro de cada chamada (empresa,
ferramenta, pedido, alcance, preço, versão do modelo e das premissas, modelo do agente). Só o hash da chave fica
guardado; a chave aparece uma vez, na criação. Nenhum dado pessoal entra no registro (o texto passa pelo filtro de
dados pessoais antes de gravar)."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass

from sqlalchemy import Engine, text

PREFIXO = "raiz_"


def _hash(chave: str) -> str:
    return hashlib.sha256(chave.encode()).hexdigest()


@dataclass(frozen=True)
class Acesso:
    cliente_id: int
    chave_id: int | None
    via: str  # api (chave), sessao (login por e-mail), mcp (OAuth)
    escopos: frozenset = frozenset({"consultar", "pedir", "reservar"})


def criar(engine: Engine, cliente_id: int, rotulo: str | None = None) -> dict:
    """Cria a chave da empresa (que já abriu a conta com o CNPJ). A chave inteira não aparece de novo."""
    from raiz.publica import conta as CT

    CT.exigir(engine, cliente_id)
    chave = f"{PREFIXO}{secrets.token_urlsafe(32)}"
    prefixo = chave[: len(PREFIXO) + 8]
    with engine.begin() as con:
        kid = con.execute(
            text("""insert into negocio.chave_api (cliente_id, prefixo, hash, rotulo) values (:c, :p, :h, :r)
                    returning id"""),
            {"c": cliente_id, "p": prefixo, "h": _hash(chave), "r": rotulo},
        ).scalar_one()
    return {"id": kid, "chave": chave, "prefixo": prefixo, "rotulo": rotulo}


def listar(engine: Engine, cliente_id: int) -> list[dict]:
    with engine.connect() as con:
        return [{**dict(r), **{k: (v.isoformat() if v else None) for k, v in dict(r).items() if k.endswith("_em")}}
                for r in con.execute(text("""select prefixo, rotulo, criada_em, usada_em, revogada_em
                                              from negocio.chave_api where cliente_id = :c order by criada_em desc"""),
                                     {"c": cliente_id}).mappings()]  # fmt: skip


def revogar(engine: Engine, cliente_id: int, prefixo: str) -> bool:
    with engine.begin() as con:
        r = con.execute(
            text("""update negocio.chave_api set revogada_em = now()
                    where cliente_id = :c and prefixo = :p and revogada_em is null returning id"""),
            {"c": cliente_id, "p": prefixo},
        ).first()
    return r is not None


def acesso_da_chave(engine: Engine, chave: str) -> Acesso | None:
    if not chave or not chave.startswith(PREFIXO):
        return None
    with engine.begin() as con:
        r = con.execute(
            text("""update negocio.chave_api k set usada_em = now() from negocio.cliente c
                    where k.hash = :h and k.revogada_em is null and c.id = k.cliente_id and c.ativo
                    returning k.id, k.cliente_id"""),
            {"h": _hash(chave)},
        ).first()
    return None if r is None else Acesso(int(r.cliente_id), int(r.id), "api")


def registrar(engine: Engine, *, cliente_id: int | None, chave_id: int | None, via: str, ferramenta: str,
              metodo: str, rota: str, pedido_id: str | None = None, cod_imovel: str | None = None,
              alcance: dict | None = None, status: int, ms: int, preco_rs: float | None = None,
              versao_modelo: str | None = None, versao_premissas: str | None = None, agente_modelo: str | None = None,
              atributos: dict | None = None) -> int | None:  # fmt: skip
    """Grava a chamada para o limite, a auditoria e o aprendizado. Devolve o id."""
    import uuid

    from raiz.publica.privacidade import limpar

    try:
        pid = str(uuid.UUID(str(pedido_id))) if pedido_id else None
    except ValueError:
        pid = None
    with engine.begin() as con:
        return con.execute(
            text("""insert into negocio.chamada_api (cliente_id, chave_id, via, ferramenta, metodo, rota, pedido_id,
                    cod_imovel, alcance, status, ms, preco_rs, versao_modelo, versao_premissas, agente_modelo,
                    atributos) values (:c, :k, :v, :f, :m, :r, :p, :i, cast(:al as jsonb), :s, :ms, :pr, :vm, :vp,
                    :am, cast(:at as jsonb)) returning id"""),
            {"c": cliente_id, "k": chave_id, "v": via, "f": ferramenta[:80], "m": metodo, "r": rota[:200], "p": pid,
             "i": (cod_imovel or None) and cod_imovel[:80], "al": json.dumps(alcance) if alcance else None,
             "s": status, "ms": ms, "pr": preco_rs, "vm": versao_modelo, "vp": versao_premissas,
             "am": (agente_modelo or None) and limpar(agente_modelo)[:120],
             "at": json.dumps(limpar(atributos)) if atributos else None},
        ).scalar_one()  # fmt: skip


def chamadas(engine: Engine, cliente_id: int | None = None, pedido_id: str | None = None) -> list[dict]:
    """As chamadas gravadas (para o aprendizado e para a empresa ver o que o agente dela fez)."""
    filtros, par = ["true"], {}
    if cliente_id is not None:
        filtros.append("cliente_id = :c")
        par["c"] = cliente_id
    if pedido_id is not None:
        filtros.append("pedido_id = cast(:p as uuid)")
        par["p"] = pedido_id
    with engine.connect() as con:
        out = []
        for r in con.execute(
            text(f"""select id, via, ferramenta, metodo, rota, pedido_id, cod_imovel, alcance, status, ms, preco_rs,
                     versao_modelo, versao_premissas, agente_modelo, atributos, criada_em from negocio.chamada_api
                     where {' and '.join(filtros)} order by id"""), par).mappings():  # fmt: skip
            d = dict(r)
            d["pedido_id"] = str(d["pedido_id"]) if d["pedido_id"] else None
            d["preco_rs"] = float(d["preco_rs"]) if d["preco_rs"] is not None else None
            d["criada_em"] = d["criada_em"].isoformat()
            out.append(d)
        return out
