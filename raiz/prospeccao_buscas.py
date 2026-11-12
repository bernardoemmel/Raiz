"""Buscas salvas: snapshot inicial silencioso e diferença idempotente por CAR.

A varredura não depende da data do arquivo/coleta: duas cargas com o mesmo
mtime ainda produzem avisos quando seus CARs diferem. Toda seleção e comparação
ocorre no Postgres; nunca materializa milhões de códigos na memória Python.
Não envia e-mail, WhatsApp nem qualquer mensagem externa.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import Engine, text

from raiz.busca import FiltrosProspeccao, _consulta_prospeccao, exigir_filtros_pagos
from raiz.prospeccao_acesso import ErroAcesso, limitar

_VISIVEL = """exists (
    select 1 from funil.vigente v where v.cod_imovel = a.cod_imovel
    and not exists (select 1 from negocio.reserva_fazenda rf
        join negocio.reserva rs on rs.id = rf.reserva_id
        where rf.cod_imovel = v.cod_imovel and rf.ativa and rs.cliente_id <> :cliente_id)
)"""


def _id(valor: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(valor))
    except ValueError as ex:
        raise ErroAcesso(404, "Busca salva não encontrada.") from ex


def _cliente(con, cliente_id: int, *, travar: bool = False) -> None:
    sql = "select id from negocio.cliente where id = :c and ativo" + (" for update" if travar else "")
    if con.execute(text(sql), {"c": cliente_id}).scalar() is None:
        raise ErroAcesso(401, "Entre novamente para continuar.")


def _json(linha) -> dict:
    return {
        "id": str(linha.id),
        "nome": linha.nome,
        "filtros": linha.filtros,
        "criada_em": linha.criada_em.isoformat(),
        "verificada_em": linha.verificada_em.isoformat(),
    }


def salvar(engine: Engine, cliente_id: int, nome: str, filtros: FiltrosProspeccao | dict) -> dict:
    filtros = filtros if isinstance(filtros, FiltrosProspeccao) else FiltrosProspeccao.model_validate(filtros)
    if not isinstance(nome, str) or not 1 <= len(nome.strip()) <= 80:
        raise ErroAcesso(422, "Dê à busca um nome de até 80 caracteres.")
    limitar(engine, f"cliente:{cliente_id}", "salvar_busca", 10)
    ident = uuid.uuid4()
    sql, parametros = _consulta_prospeccao(filtros, cliente_id)
    with engine.begin() as con:
        _cliente(con, cliente_id, travar=True)
        exigir_filtros_pagos(con, filtros, cliente_id)
        n = con.execute(
            text("select count(*) from negocio.prospeccao_busca where cliente_id = :c"), {"c": cliente_id}
        ).scalar_one()
        if n >= 20:
            raise ErroAcesso(409, "Você já tem 20 buscas salvas. Exclua uma antes de salvar outra.")
        linha = con.execute(
            text("""insert into negocio.prospeccao_busca(id, cliente_id, nome, filtros)
                values (:id, :c, :nome, cast(:f as jsonb)) returning *"""),
            {
                "id": ident,
                "c": cliente_id,
                "nome": nome.strip(),
                "f": json.dumps(filtros.model_dump(exclude_none=True)),
            },
        ).one()
        # O snapshot inicial é silencioso, mesmo para uma busca nacional com milhões de CARs.
        con.execute(
            text(
                sql
                + """insert into negocio.prospeccao_busca_vista(busca_id, cod_imovel)
                select :id, codigo_car from selecionadas on conflict do nothing"""
            ),
            {**parametros, "id": ident},
        )
        return _json(linha)


def listar(engine: Engine, cliente_id: int) -> list[dict]:
    with engine.connect() as con:
        _cliente(con, cliente_id)
        return [
            _json(r)
            for r in con.execute(
                text("select * from negocio.prospeccao_busca where cliente_id = :c order by criada_em desc, id"),
                {"c": cliente_id},
            )
        ]


def excluir(engine: Engine, cliente_id: int, busca_id: str) -> dict:
    with engine.begin() as con:
        _cliente(con, cliente_id)
        apagada = con.execute(
            text("delete from negocio.prospeccao_busca where id = :id and cliente_id = :c returning id"),
            {"id": _id(busca_id), "c": cliente_id},
        ).scalar()
        if apagada is None:
            raise ErroAcesso(404, "Busca salva não encontrada.")
    return {"id": str(apagada), "excluida": True}


def verificar(engine: Engine, busca_id: str) -> dict:
    """Job interno: trava a busca e grava snapshot e avisos na mesma transação."""
    ident = _id(busca_id)
    with engine.begin() as con:
        registro = con.execute(
            text("""select b.* from negocio.prospeccao_busca b
                join negocio.cliente c on c.id = b.cliente_id and c.ativo
                where b.id = :id for update of b"""),
            {"id": ident},
        ).first()
        if registro is None:
            raise ErroAcesso(404, "Busca salva não encontrada.")
        filtros = FiltrosProspeccao.model_validate(registro.filtros)
        exigir_filtros_pagos(con, filtros, registro.cliente_id)
        sql, parametros = _consulta_prospeccao(filtros, registro.cliente_id)
        novas = con.execute(
            text(
                sql
                + """, novas as (
                insert into negocio.prospeccao_busca_vista(busca_id, cod_imovel)
                select :id, codigo_car from selecionadas on conflict do nothing returning cod_imovel
            ), avisos as (
                insert into negocio.prospeccao_busca_aviso(busca_id, cod_imovel)
                select :id, cod_imovel from novas on conflict do nothing returning id
            ) select count(*) from avisos"""
            ),
            {**parametros, "id": ident},
        ).scalar_one()
        con.execute(text("update negocio.prospeccao_busca set verificada_em = now() where id = :id"), {"id": ident})
    return {"id": str(ident), "novas_fazendas": novas}


def verificar_todas(engine: Engine) -> dict:
    """Entrada para o agendador/coleta; sem disparo externo nem concessão de acesso."""
    with engine.connect() as con:
        ids = (
            con.execute(
                text("""select b.id from negocio.prospeccao_busca b
                join negocio.cliente c on c.id = b.cliente_id and c.ativo order by b.id""")
            )
            .scalars()
            .all()
        )
    feitas, novas, sem_acesso = 0, 0, 0
    for ident in ids:
        try:
            resultado = verificar(engine, str(ident))
        except ErroAcesso as ex:
            if ex.status == 404:  # excluída enquanto o job percorria a lista
                continue
            if ex.status == 402:
                sem_acesso += 1
                continue
            raise
        feitas += 1
        novas += resultado["novas_fazendas"]
    return {"buscas_verificadas": feitas, "novas_fazendas": novas, "buscas_sem_habilitacao": sem_acesso}


def avisos(engine: Engine, cliente_id: int, *, depois: int = 0, limite: int = 50) -> dict:
    if type(depois) is not int or depois < 0 or type(limite) is not int or not 1 <= limite <= 100:
        raise ErroAcesso(422, "Cursor ou limite de avisos inválido.")
    with engine.connect() as con:
        _cliente(con, cliente_id)
        linhas = con.execute(
            text(f"""select a.id, a.busca_id, a.cod_imovel, a.criada_em, a.lida_em, b.nome
                from negocio.prospeccao_busca_aviso a
                join negocio.prospeccao_busca b on b.id = a.busca_id
                where b.cliente_id = :cliente_id and a.id > :depois and {_VISIVEL}
                order by a.id limit :limite"""),
            {"cliente_id": cliente_id, "depois": depois, "limite": limite + 1},
        ).all()
    return {
        "avisos": [
            {
                "id": r.id,
                "busca_id": str(r.busca_id),
                "nome_busca": r.nome,
                "codigo_car": r.cod_imovel,
                "criada_em": r.criada_em.isoformat(),
                "lida_em": r.lida_em.isoformat() if r.lida_em else None,
                "mensagem": "Nova fazenda corresponde à sua busca salva. A ficha completa exige liberação.",
            }
            for r in linhas[:limite]
        ],
        "proximo_cursor": linhas[limite - 1].id if len(linhas) > limite else None,
    }


def ler_aviso(engine: Engine, cliente_id: int, aviso_id: int) -> dict:
    if type(aviso_id) is not int or aviso_id < 1:
        raise ErroAcesso(404, "Aviso não encontrado.")
    with engine.begin() as con:
        _cliente(con, cliente_id)
        linha = con.execute(
            text(f"""update negocio.prospeccao_busca_aviso a set lida_em = coalesce(lida_em, now())
                from negocio.prospeccao_busca b where a.busca_id = b.id
                and b.cliente_id = :cliente_id and a.id = :id and {_VISIVEL}
                returning a.id, a.lida_em"""),
            {"cliente_id": cliente_id, "id": aviso_id},
        ).first()
        if linha is None:
            raise ErroAcesso(404, "Aviso não encontrado.")
        return {"id": linha.id, "lida_em": linha.lida_em.isoformat()}
