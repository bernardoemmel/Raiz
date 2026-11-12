"""Chave de API por empresa, limite de chamadas por chave e o registro de cada chamada (para a auditoria e o
aprendizado: empresa, ferramenta, pedido e versão do modelo). Só o hash da chave fica guardado; a chave aparece uma
vez, na criação. Nenhum dado pessoal entra no registro."""

from __future__ import annotations

import hashlib
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
    via: str  # api (chave), sessao (login por e-mail)
    limite_minuto: int | None = None
    limite_dia: int | None = None


def criar(engine: Engine, cliente_id: int, rotulo: str | None = None, limite_minuto: int = 30,
          limite_dia: int = 2000) -> dict:  # fmt: skip
    """Cria a chave da empresa. Devolve {chave, prefixo, ...}; a chave inteira não aparece de novo."""
    corpo = secrets.token_urlsafe(32)
    chave = f"{PREFIXO}{corpo}"
    prefixo = chave[: len(PREFIXO) + 8]
    with engine.begin() as con:
        cid = con.execute(
            text("""insert into negocio.chave_api (cliente_id, prefixo, hash, rotulo, limite_minuto, limite_dia)
                    values (:c, :p, :h, :r, :m, :d) returning id"""),
            {"c": cliente_id, "p": prefixo, "h": _hash(chave), "r": rotulo, "m": limite_minuto, "d": limite_dia},
        ).scalar_one()
    return {"id": cid, "chave": chave, "prefixo": prefixo, "rotulo": rotulo, "limite_minuto": limite_minuto,
            "limite_dia": limite_dia}  # fmt: skip


def listar(engine: Engine, cliente_id: int) -> list[dict]:
    with engine.connect() as con:
        return [dict(r) for r in con.execute(
            text("""select prefixo, rotulo, limite_minuto, limite_dia, criada_em, usada_em, revogada_em
                    from negocio.chave_api where cliente_id = :c order by criada_em desc"""), {"c": cliente_id},
        ).mappings()]  # fmt: skip


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
                    returning k.id, k.cliente_id, k.limite_minuto, k.limite_dia"""),
            {"h": _hash(chave)},
        ).first()
    if r is None:
        return None
    return Acesso(int(r.cliente_id), int(r.id), "api", int(r.limite_minuto), int(r.limite_dia))


def excedeu(engine: Engine, a: Acesso) -> tuple[bool, int]:
    """Passou do limite da chave? Devolve (excedeu, segundos para tentar de novo). Conta no registro de chamadas."""
    if a.chave_id is None:
        return False, 0
    with engine.connect() as con:
        r = con.execute(
            text("""select count(*) filter (where criada_em > now() - interval '1 minute') as minuto,
                           count(*) filter (where criada_em > now() - interval '1 day') as dia
                    from negocio.chamada_api where chave_id = :k and criada_em > now() - interval '1 day'"""),
            {"k": a.chave_id},
        ).first()
    if a.limite_minuto is not None and r.minuto >= a.limite_minuto:
        return True, 60
    if a.limite_dia is not None and r.dia >= a.limite_dia:
        return True, 3600
    return False, 0


def registrar(engine: Engine, *, cliente_id: int | None, chave_id: int | None, via: str, ferramenta: str,
              metodo: str, rota: str, pedido_id: str | None, cod_imovel: str | None, status: int, ms: int,
              versao_modelo: str | None, agente_modelo: str | None) -> None:  # fmt: skip
    """Grava a chamada (empresa, ferramenta, pedido e versão do modelo) para o limite e para o aprendizado."""
    import uuid

    try:
        pid = str(uuid.UUID(str(pedido_id))) if pedido_id else None
    except ValueError:
        pid = None
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.chamada_api (cliente_id, chave_id, via, ferramenta, metodo, rota, pedido_id,
                    cod_imovel, status, ms, versao_modelo, agente_modelo)
                    values (:c, :k, :v, :f, :m, :r, :p, :i, :s, :ms, :vm, :am)"""),
            {"c": cliente_id, "k": chave_id, "v": via, "f": ferramenta[:80], "m": metodo, "r": rota[:200], "p": pid,
             "i": (cod_imovel or None) and cod_imovel[:80], "s": status, "ms": ms, "vm": versao_modelo,
             "am": (agente_modelo or None) and agente_modelo[:120]},
        )  # fmt: skip


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
        return [dict(r) for r in con.execute(
            text(f"""select via, ferramenta, metodo, rota, pedido_id, cod_imovel, status, ms, versao_modelo,
                     agente_modelo, criada_em from negocio.chamada_api where {' and '.join(filtros)}
                     order by id"""), par).mappings()]  # fmt: skip
