"""Calendário no Postgres. Retificações preservam histórico e UID do calendário."""

from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import text

from raiz.calendario.modelos import Evento, FonteEstado, filtrar, normalizar_car


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, sort_keys=True)


def _conteudo(evento: Evento) -> dict:
    return evento.model_dump(mode="json", exclude={"coletado_em", "atualizado_em", "sequencia"})


def combinar(anteriores: list[Evento], novos: list[Evento]) -> list[Evento]:
    """Mesmo comportamento no banco e no snapshot: ausência não significa cancelamento."""
    por_id = {e.id: e for e in anteriores}
    for novo in novos:
        antes = por_id.get(novo.id)
        if antes and novo.coletado_em < antes.coletado_em:
            continue  # importar snapshot antigo não desfaz uma retificação mais recente
        if (
            antes
            and antes.situacao == "cancelado"
            and novo.situacao == "previsto"
            and novo.fonte_url != antes.fonte_url
        ):
            continue  # revisitar o edital original não desfaz o cancelamento em outra publicação
        if antes:
            mudou = _conteudo(novo) != _conteudo(antes)
            novo = novo.model_copy(
                update={
                    "sequencia": antes.sequencia + int(mudou),
                    "atualizado_em": novo.coletado_em if mudou else antes.atualizado_em,
                }
            )
        else:
            novo = novo.model_copy(update={"atualizado_em": novo.atualizado_em or novo.coletado_em})
        por_id[novo.id] = novo
    return sorted(por_id.values(), key=lambda e: (e.dia, e.id))


def cruzar(con, evento: Evento) -> Evento:
    """CAR explícito, CNS+matrícula ou parcela SIGEF com interseção de área positiva.

    Nunca usa só o número da matrícula (que se repete entre cartórios), nomes ou
    CPF. Fazendas pequenas não recebem corte de hectares.
    """
    cods, vinculo = set(evento.codigos_car), evento.vinculo
    if cods:
        vinculo = "car"
    elif evento.cns and evento.matricula:
        rows = con.execute(
            text("""
            select cod_imovel from titulo.matricula_imovel
            where cns = :cns and matricula = :matricula
        """),
            {"cns": evento.cns, "matricula": evento.matricula},
        )
        cods.update(normalizar_car(r[0]) for r in rows)
        if cods:
            vinculo = "cns_matricula"
    if not cods and evento.sigef:
        existe = con.execute(text("select to_regclass('bruto.sigef_parcela_vigente')")).scalar()
        if existe:
            rows = con.execute(
                text("""
                select distinct i.cod_imovel from bruto.sigef_parcela_vigente s
                join funil.imovel i on ST_Intersects(i.geom, s.geom)
                join funil.vigente v on v.cod_imovel=i.cod_imovel
                where s.parcela_codigo = any(:parcelas)
                  and not ST_IsEmpty(ST_Intersection(i.geom, s.geom))
                  and ST_Dimension(ST_Intersection(i.geom, s.geom)) = 2
            """),
                {"parcelas": evento.sigef},
            )
            cods.update(normalizar_car(r[0]) for r in rows)
            if cods:
                vinculo = "sigef"
    return evento.model_copy(update={"codigos_car": sorted(cods), "vinculo": vinculo})


def gravar(con, eventos: list[Evento], fontes: list[FonteEstado], *, cruzar_imoveis: bool = True) -> int:
    # A trava evita que duas coletas gerem a mesma sequência/histórico e dois avisos.
    con.execute(text("select pg_advisory_xact_lock(hashtext('calendario:coleta'))"))
    alterados = 0
    for novo in eventos:
        if cruzar_imoveis:
            novo = cruzar(con, novo)
        row = con.execute(text("select conteudo from calendario.evento where id = :id"), {"id": novo.id}).first()
        antes = Evento.model_validate(row[0]) if row else None
        final = combinar([antes] if antes else [], [novo])[0]
        mudou = antes is None or final.sequencia != antes.sequencia
        d = final.model_dump(mode="json")
        params = {**d, "conteudo": _json(d)}
        con.execute(
            text("""
            insert into calendario.evento
              (id,tipo,data,prazo,uf,municipio,fonte_id,fonte_url,coletado_em,atualizado_em,sequencia,situacao,confianca,conteudo)
            values (:id,:tipo,:data,:prazo,:uf,:municipio,:fonte_id,:fonte_url,:coletado_em,:atualizado_em,
                    :sequencia,:situacao,:confianca,cast(:conteudo as jsonb))
            on conflict (id) do update set tipo=excluded.tipo,data=excluded.data,prazo=excluded.prazo,
              uf=excluded.uf,municipio=excluded.municipio,fonte_id=excluded.fonte_id,fonte_url=excluded.fonte_url,
              coletado_em=excluded.coletado_em,atualizado_em=excluded.atualizado_em,sequencia=excluded.sequencia,
              situacao=excluded.situacao,confianca=excluded.confianca,conteudo=excluded.conteudo
        """),
            params,
        )
        con.execute(text("delete from calendario.evento_imovel where evento_id=:id"), {"id": final.id})
        for cod in final.codigos_car:
            con.execute(
                text("""insert into calendario.evento_imovel (evento_id,cod_imovel,vinculo)
                values (:id,:cod,:vinculo)"""),
                {"id": final.id, "cod": cod, "vinculo": final.vinculo},
            )
        if mudou:
            alterados += 1
            con.execute(
                text("""insert into calendario.evento_historico (evento_id,sequencia,conteudo,em)
                values (:id,:sequencia,cast(:conteudo as jsonb),:atualizado_em)"""),
                params,
            )
    for fonte in fontes:
        con.execute(
            text("""insert into calendario.fonte_estado (id,coletado_em,conteudo)
            values (:id,:em,cast(:conteudo as jsonb)) on conflict (id) do update
            set coletado_em=excluded.coletado_em,conteudo=excluded.conteudo
            where calendario.fonte_estado.coletado_em <= excluded.coletado_em"""),
            {"id": fonte.id, "em": fonte.coletado_em, "conteudo": fonte.model_dump_json()},
        )
    return alterados


def consultar(con, *, limite=100, deslocamento=0, **filtros) -> dict:
    # A validação é a mesma usada pelo snapshot e pelo MCP. Predicados SQL mantêm
    # o índice por data útil; o filtro de CAR usa a tabela de vínculo indexada.
    filtrar([], **filtros)
    if not 1 <= limite <= 20000 or deslocamento < 0:
        raise ValueError("paginação inválida")
    regras, params = [], {"limite": limite, "deslocamento": deslocamento}
    for nome, expressao in (
        ("tipo", "e.tipo=:tipo"),
        ("estado", "(e.uf=:estado or e.uf is null)"),
        ("inicio", "coalesce(e.prazo,e.data)>=:inicio"),
        ("fim", "coalesce(e.prazo,e.data)<=:fim"),
        (
            "cod_imovel",
            "exists(select 1 from calendario.evento_imovel i where i.evento_id=e.id and i.cod_imovel=:cod_imovel)",
        ),
    ):
        valor = filtros.get(nome)
        if valor is not None:
            regras.append(expressao)
            params[nome] = normalizar_car(valor) if nome == "cod_imovel" else valor
    where = " where " + " and ".join(regras) if regras else ""
    total = con.execute(text("select count(*) from calendario.evento e" + where), params).scalar_one()
    rows = con.execute(
        text(
            "select e.conteudo from calendario.evento e"
            + where
            + " order by coalesce(e.prazo,e.data),e.id limit :limite offset :deslocamento"
        ),
        params,
    )
    eventos = [Evento.model_validate(r[0]).publico() for r in rows]
    estados = [
        FonteEstado.model_validate(r[0]).model_dump(mode="json")
        for r in con.execute(text("select conteudo from calendario.fonte_estado order by id"))
    ]
    return {
        "eventos": eventos,
        "total": total,
        "fontes": estados,
        "coletado_em": max((e["coletado_em"] for e in estados), default=None),
    }


def avisar_pedidos(con, hoje: dt.date) -> int:
    """Avisa uma vez por versão do evento/CAR em cada lote ativo, nos canais existentes."""
    from raiz.pedidos.servico import (
        CANAIS_PROBLEMA_GRUPO,
        CANAIS_PROBLEMA_LOTE,
        ESTADOS_COM_GRUPO,
        _alerta,
    )

    rows = con.execute(
        text("""
        select distinct p.id,p.cliente_id,p.estado,f.cod_imovel,e.conteudo
        from negocio.pedido p join negocio.pedido_fazenda f on f.pedido_id=p.id and f.papel<>'fora'
        join calendario.evento_imovel i on replace(i.cod_imovel,'-','') =
             upper(regexp_replace(f.cod_imovel,'[^0-9A-Za-z]','','g'))
        join calendario.evento e on e.id=i.evento_id
        where p.estado in ('lote_montado','buscando_interesse','grupo_pronto','reservado','faltou','contrato')
          and e.tipo in ('leilao_imovel','penhora')
          and (coalesce(e.prazo,e.data)>=:hoje or e.tipo='penhora')
    """),
        {"hoje": hoje},
    ).mappings()
    total = 0
    for r in rows:
        evento = Evento.model_validate(r["conteudo"])
        tx = (
            f"{evento.titulo}: fazenda {r['cod_imovel']}, {evento.dia:%d/%m/%Y}. "
            f"Situação: {evento.situacao}. Fonte: {evento.fonte_nome}. Confira o edital antes de negociar."
        )
        chave = f"calendario:{evento.id}:{evento.sequencia}:{r['cod_imovel']}"
        detalhe = {
            "motivo": "em_leilao" if evento.tipo == "leilao_imovel" else "penhora",
            "fonte": evento.fonte_nome,
            "link": evento.fonte_url,
            "evento_id": evento.id,
            "data": evento.dia.isoformat(),
            "situacao": evento.situacao,
        }
        if _alerta(con, r["id"], "fazenda_com_problema", r["cod_imovel"], tx, detalhe, chave):
            canais = CANAIS_PROBLEMA_GRUPO if r["estado"] in ESTADOS_COM_GRUPO else CANAIS_PROBLEMA_LOTE
            # O calendário prepara os avisos; envio externo continua simulado por
            # decisão do fundador, mesmo se outro módulo tiver enviador configurado.
            for canal in canais:
                con.execute(
                    text("""insert into negocio.notificacao
                    (cliente_id,pedido_id,tipo,canal,texto,estado)
                    values (:cliente,:pedido,'fazenda_com_problema',:canal,:texto,:estado)"""),
                    {
                        "cliente": r["cliente_id"],
                        "pedido": r["id"],
                        "canal": canal,
                        "texto": tx,
                        "estado": "enviada" if canal == "painel" else "simulada",
                    },
                )
            total += 1
    return total
