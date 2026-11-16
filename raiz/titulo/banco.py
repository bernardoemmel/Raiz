"""Achados e confirmações no banco (titulo.achado, titulo.confirmacao, view titulo.achado_vigente).

- carregar_achados: grava o achados_<mun>.csv de uma rodada (a carga chama, raiz/carga.py);
- confirmar: registra quem confirmou, descartou ou corrigiu um achado (identificador do operador, nunca nome);
- pendentes: achados vigentes de gravidade reprova ou confirmar ainda sem confirmação, os mais graves primeiro;
- carregar_cadeia: grava o cadeia_<mun>.csv (raiz/documentos) em titulo.matricula, titulo.ato e titulo.ato_parte,
  uma vez por leitura (a mesma leitura carregada de novo não duplica);
- cadeia_do_imovel: as matrículas do imóvel com os atos e onde a cadeia para (titulo.cadeia_origem).
"""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import Connection, text

from raiz.titulo.achados import COLUNAS

DECISOES = ("confirmado", "descartado", "corrigido")
# identificador de operador: minúsculas, números e hífen (ex.: fundador, conferente-02); nome de pessoa não passa
_QUEM = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


def carregar_achados(con: Connection, rodada_id: int | None, arquivo: str | Path) -> int:
    import pandas as pd

    df = pd.read_csv(arquivo, dtype=str, keep_default_na=False)
    if df.empty:
        return 0
    faltam = set(COLUNAS) - set(df.columns)
    if faltam:
        raise ValueError(f"achados sem as colunas {sorted(faltam)}")
    linhas = [{**{c: (r[c] or None) for c in COLUNAS}, "rodada_id": rodada_id} for r in df[COLUNAS].to_dict("records")]
    con.execute(
        text(f"""insert into titulo.achado (rodada_id, {", ".join(COLUNAS)})
                 values (:rodada_id, {", ".join(":" + c for c in COLUNAS)})"""),
        linhas,
    )
    return len(linhas)


MATRICULA = [
    "leitura_id", "lido_em", "modelo", "leitor_versao", "regras_versao", "situacao", "conferencia", "origem",
    "origem_referencia", "origem_matricula", "data_abertura", "area_ha", "matricula_destino", "georreferenciado",
    "n_transmissoes", "quebras", "onus_graves",
]  # fmt: skip
ATO = [
    "ordem", "numero", "tipo", "natureza", "afeta", "data", "fracao_pct", "pagina", "transmissao", "anterior_numero",
    "cancelado_por", "quebra", "quebra_motivo", "resumo",
]  # fmt: skip
_DO_CSV = {
    "situacao": "matricula_situacao", "area_ha": "area_matricula_ha", "numero": "ato_numero", "tipo": "ato_tipo",
}  # fmt: skip


def _valor(v):
    import math

    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):  # numpy -> python
        v = v.item()
    return v


def _bool(v):
    v = _valor(v)
    if v is None or isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "sim", "t")


def carregar_cadeia(con: Connection, arquivo: str | Path) -> dict:
    """{"matriculas": novas, "atos": novos}. Matrícula sem CNS ou sem número fica de fora (não há como ligar)."""
    import json

    import pandas as pd

    df = pd.read_csv(arquivo, dtype={"registro_cns": str, "registro_matricula": str, "origem_matricula": str,
                                     "matricula_destino": str, "leitura_hash": str})  # fmt: skip
    if df.empty:
        return {"matriculas": 0, "atos": 0}
    df = df[df.registro_cns.notna() & df.registro_matricula.notna() & df.leitura_hash.notna()]
    n_mat = n_ato = 0
    for (cns, mat, h), g in df.groupby(["registro_cns", "registro_matricula", "leitura_hash"], sort=False):
        r0 = g.iloc[0]
        vals = {c: _valor(r0.get(_DO_CSV.get(c, c))) for c in MATRICULA}
        for c in ("georreferenciado", "onus_graves"):
            vals[c] = _bool(vals[c])
        novo = con.execute(
            text(f"""insert into titulo.matricula (cns, matricula, leitura_hash, {", ".join(MATRICULA)})
                     values (:cns, :mat, :h, {", ".join(":" + c for c in MATRICULA)})
                     on conflict do nothing returning 1"""),
            {"cns": cns, "mat": mat, "h": h, **vals},
        ).first()
        if novo is None:
            continue
        n_mat += 1
        for _, r in g[g.ordem.notna()].iterrows():
            a = {c: _valor(r.get(_DO_CSV.get(c, c))) for c in ATO}
            a["ordem"] = int(a["ordem"])
            a["pagina"] = int(a["pagina"]) if a["pagina"] is not None else None
            for c in ("transmissao", "quebra"):
                a[c] = bool(_bool(a[c]))
            ato_id = con.execute(
                text(f"""insert into titulo.ato (cns, matricula, leitura_hash, {", ".join(ATO)})
                         values (:cns, :mat, :h, {", ".join(":" + c for c in ATO)}) returning id"""),
                {"cns": cns, "mat": mat, "h": h, **a},
            ).scalar_one()
            n_ato += 1
            partes = [
                {"ato": ato_id, "papel": papel, **{k: p.get(k) for k in ("rotulo", "tipo", "documento", "instituicao")}}
                for papel, col in (("transmitente", "transmitentes_json"), ("adquirente", "adquirentes_json"))
                for p in json.loads(_valor(r.get(col)) or "[]")
            ]
            if partes:
                con.execute(
                    text("""insert into titulo.ato_parte (ato_id, papel, rotulo, tipo, documento, instituicao)
                            values (:ato, :papel, :rotulo, :tipo, :documento, :instituicao)"""),
                    partes,
                )
    return {"matriculas": n_mat, "atos": n_ato}


def cadeia_do_imovel(con: Connection, cod_imovel: str) -> list[dict]:
    """Matrículas do imóvel (vigentes), com os atos em ordem e onde a cadeia de origem para."""
    mats = con.execute(
        text("""select mi.cns, mi.matricula, mi.ha_sobre_car, m.situacao, m.conferencia, m.origem, m.area_ha,
                       m.georreferenciado, m.leitura_hash, m.lido_em, m.modelo, co.situacao as origem_situacao,
                       co.para_em as origem_para_em, co.saltos as origem_saltos
                from titulo.matricula_imovel mi
                left join titulo.matricula_vigente m on m.cns = mi.cns and m.matricula = mi.matricula
                left join titulo.cadeia_origem co on co.cns = mi.cns and co.matricula = mi.matricula
                where mi.cod_imovel = :c order by mi.ha_sobre_car desc nulls last, mi.matricula"""),
        {"c": cod_imovel},
    ).mappings()
    out = []
    for m in mats:
        m = dict(m)
        m["atos"] = (
            [
                dict(a)
                for a in con.execute(
                    text("""select a.numero, a.natureza, a.data, a.fracao_pct, a.transmissao, a.anterior_numero,
                               a.cancelado_por, a.quebra, a.quebra_motivo, a.resumo, a.pagina,
                               coalesce(jsonb_agg(jsonb_build_object('papel', p.papel, 'rotulo', p.rotulo,
                                        'tipo', p.tipo, 'documento', p.documento, 'instituicao', p.instituicao))
                                        filter (where p.ato_id is not null), '[]') as partes
                        from titulo.ato a left join titulo.ato_parte p on p.ato_id = a.id
                        where a.cns = :cns and a.matricula = :mat and a.leitura_hash = :h
                        group by a.id order by a.ordem"""),
                    {"cns": m["cns"], "mat": m["matricula"], "h": m["leitura_hash"]},
                ).mappings()
            ]
            if m["leitura_hash"]
            else []
        )
        out.append(m)
    return out


def confirmar(con: Connection, achado_id: int, quem: str, decisao: str, nota: str | None = None) -> int:
    if decisao not in DECISOES:
        raise ValueError(f"decisão deve ser uma de {', '.join(DECISOES)}")
    if not _QUEM.match(quem or ""):
        raise ValueError("quem: identificador do operador (ex.: fundador, conferente-02), nunca nome")
    a = con.execute(text("select cod_imovel, regra, valor from titulo.achado where id = :i"), {"i": achado_id}).first()
    if a is None:
        raise ValueError(f"achado {achado_id} não existe")
    from raiz.privacidade import mascarar

    return con.execute(
        text("""insert into titulo.confirmacao (achado_id, cod_imovel, regra, valor, decisao, quem, nota)
                values (:a, :c, :r, :v, :d, :q, :n) returning id"""),
        dict(a=achado_id, c=a.cod_imovel, r=a.regra, v=a.valor, d=decisao, q=quem, n=mascarar(nota) if nota else None),
    ).scalar_one()


def pendentes(con: Connection, cod_imovel: str | None = None, limite: int = 200) -> list:
    return con.execute(
        text("""select id, cod_imovel, fase, regra, situacao, gravidade, mensagem, valor
                from titulo.achado_vigente
                where gravidade in ('reprova', 'confirmar') and confirmacao_decisao is null
                  and (cast(:c as text) is null or cod_imovel = :c)
                order by case gravidade when 'reprova' then 0 else 1 end, cod_imovel, fase, regra
                limit :l"""),
        {"c": cod_imovel, "l": limite},
    ).all()


def do_imovel(con: Connection, cod_imovel: str) -> list:
    """Todos os achados vigentes do imóvel, com a confirmação que vale (para o laudo)."""
    return con.execute(
        text("select * from titulo.achado_vigente where cod_imovel = :c order by fase, regra"), {"c": cod_imovel}
    ).all()
