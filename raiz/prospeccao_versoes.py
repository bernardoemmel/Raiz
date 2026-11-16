"""Histórico imutável da terra e comparação com a última leitura autorizada da conta.

A carga registra transições em lotes. Consultar não é necessário para preservar o
passado; somente uma consulta concluída avança o baseline privado do cliente.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from contextlib import contextmanager

from sqlalchemy import Engine, text

from raiz import contrato, front_api
from raiz.ficha_prospeccao_dados import ficha
from raiz.prospeccao_acesso import ErroAcesso, _car_visivel, _liberada
from raiz.prospeccao_contrato import filtrar_mudancas, projetar_ficha

_CAMPOS = frozenset(
    "versao codigo_car municipio cod_ibge uf bioma data_corte area_total area_restauravel caminho_terra "
    "pendencias sobreposicoes embargos serie_uso perdas credito tir risco agrupamento terra_comprometida "
    "disponivel".split()
)
_VOLATEIS = frozenset(
    "carregada_em consultada_em consultado_em observado_em gerado_em registrada_em atualizado_em "
    "verificada_em versao_ficha o_que_mudou".split()
)
LOTES_SQL = """select pf.cod_imovel, jsonb_agg(pf.pedido_id::text order by pf.pedido_id) as lotes
    from negocio.pedido_fazenda pf join negocio.pedido p on p.id=pf.pedido_id
    where p.cliente_id=:cliente_id and pf.papel='lote' and p.estado not in ('cancelado','reserva_vencida')
    group by pf.cod_imovel"""


def _limpar(valor):
    if isinstance(valor, dict):
        return {k: _limpar(v) for k, v in sorted(valor.items()) if k not in _VOLATEIS}
    if isinstance(valor, list):
        return [_limpar(v) for v in valor]
    if isinstance(valor, float) and not math.isfinite(valor):
        return None
    return valor


def documento(dado: dict) -> dict:
    """Somente o contrato fechado da terra; metadados da conta não entram no hash."""
    fechado = projetar_ficha(dado)
    if dado.get("disponivel") is False:
        fechado["disponivel"] = False
    return {k: v for k, v in fechado.items() if k in _CAMPOS}


def _json(dado) -> str:
    return json.dumps(dado, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(dado: dict) -> str:
    return hashlib.sha256(_json(_limpar(documento(dado))).encode()).hexdigest()


def diferencas(antes: dict | None, depois: dict) -> list[dict]:
    if antes is None:
        return []
    saida = []
    campos = {
        k: k
        for k in (
            "pendencias",
            "embargos",
            "caminho_terra",
            "terra_comprometida",
            "sobreposicoes",
            "serie_uso",
            "credito",
            "tir",
            "risco",
            "area_total",
            "area_restauravel",
            "disponivel",
        )
    }
    a, d = documento(antes), documento(depois)
    for tipo in ("fogo", "desmatamento"):
        campos[tipo] = tipo
        for origem in (a, d):
            origem[tipo] = [x for x in origem.get("perdas", []) if (x.get("tipo") == "fogo") == (tipo == "fogo")]
    for campo, tipo in campos.items():
        antigo, novo = a.get(campo), d.get(campo)
        if _limpar(antigo) == _limpar(novo):
            continue
        meta = novo if isinstance(novo, dict) else {}
        medida = meta.get("area", meta)
        saida.append(
            {
                "tipo": tipo,
                "campo": campo,
                "antes": antigo,
                "depois": novo,
                "fonte": medida.get("fonte") or "Raíz, comparação entre versões; fontes nas medidas",
                "data_referencia": medida.get("data_referencia"),
                "data_corte": depois.get("data_corte"),
            }
        )
    return saida


def _guardar(con, dados: list[dict]) -> dict[str, dict]:
    if not dados:
        return {}
    itens = [{"car": d["codigo_car"], "hash": _hash(d), "documento": documento(d)} for d in dados]
    con.execute(
        text("""insert into negocio.prospeccao_ficha_versao(cod_imovel,hash_conteudo,documento)
        select x.car,x.hash,x.documento from jsonb_to_recordset(cast(:itens as jsonb))
        as x(car text, hash text, documento jsonb) order by x.car,x.hash on conflict do nothing"""),
        {"itens": _json(itens)},
    )
    rows = con.execute(
        text("""select v.* from negocio.prospeccao_ficha_versao v
        join jsonb_to_recordset(cast(:itens as jsonb)) as x(car text,hash text)
        on v.cod_imovel=x.car and v.hash_conteudo=x.hash"""),
        {"itens": _json(itens)},
    ).mappings()
    return {r["cod_imovel"]: dict(r) for r in rows}


def _montar_lote(con, codigos: list[str]) -> list[dict]:
    """Consultas em lote por PK vigente, sem uma consulta por CAR."""
    principais = [
        dict(r)
        for r in con.execute(
            text("""select r.* from funil.vigente v
        join funil.resultado_imovel r on (r.rodada_id,r.cod_imovel)=(v.rodada_id,v.cod_imovel)
        where v.cod_imovel=any(:cs) order by v.cod_imovel"""),
            {"cs": codigos},
        ).mappings()
    ]
    if not principais:
        return [{"codigo_car": c, "disponivel": False} for c in codigos]
    rodadas = {
        r["id"]: dict(r)
        for r in con.execute(
            text("select * from funil.rodada where id=any(:rs)"), {"rs": list({p["rodada_id"] for p in principais})}
        ).mappings()
    }
    comp = defaultdict(dict)
    for r in con.execute(
        text("""select f.* from funil.vigente v join funil.filtro_imovel f
        on (f.rodada_id,f.cod_imovel)=(v.rodada_id,v.cod_imovel) where v.cod_imovel=any(:cs)"""),
        {"cs": codigos},
    ).mappings():
        comp[r["cod_imovel"]].update(front_api._linha_banco(dict(r)))
    for r in con.execute(
        text("""select c.cod_imovel,c.atributos from funil.vigente v join funil.complemento_imovel c
        on (c.rodada_id,c.cod_imovel)=(v.rodada_id,v.cod_imovel) where v.cod_imovel=any(:cs) order by c.tipo"""),
        {"cs": codigos},
    ):
        comp[r.cod_imovel].update(r.atributos or {})
    for r in con.execute(
        text("""select m.* from funil.vigente v join funil.mapbiomas_imovel m
        on (m.rodada_id,m.cod_imovel)=(v.rodada_id,v.cod_imovel) where v.cod_imovel=any(:cs)"""),
        {"cs": codigos},
    ):
        comp[r.cod_imovel][contrato.coluna_mb(r.indicador, r.ano)] = (
            r.valor_num if r.valor_texto is None else r.valor_texto
        )
    series = defaultdict(list)
    for r in con.execute(
        text("select * from funil.serie_uso where cod_imovel=any(:cs) order by ano"), {"cs": codigos}
    ).mappings():
        series[r["cod_imovel"]].append(dict(r))
    from raiz.terra_comprometida import por_codigos

    comprometidas = por_codigos(con, codigos)
    montadas = {}
    for p in principais:
        car, rodada = p["cod_imovel"], rodadas[p["rodada_id"]]
        faltando = {c.split(".", 1)[1] for c in rodada["colunas_faltando"] if "." in c}
        linha = dict(comp[car])
        linha.update(front_api._linha_banco(p, faltando))
        serie = series[car]
        banco = {
            "terra_comprometida": comprometidas.get(car),
            "serie_uso": {
                "anos": [r["ano"] for r in serie],
                **{f"{uso}_pct": [r[f"{uso}_pct"] for r in serie] for uso in ("mata", "pasto", "lavoura", "agua")},
            }
            if serie
            else {},
        }
        montadas[car] = ficha(front_api._limpa(linha), {"data_corte": rodada["data_corte"]}, banco)
    return [montadas.get(c, {"codigo_car": c, "disponivel": False}) for c in codigos]


def registrar_versoes(con, codigos: list[str], *, origem: str = "rodada") -> dict[str, int]:
    """Hook antes/depois da escrita, mesma conexão/transação; não faz commit."""
    codigos = sorted(set(codigos))
    if not codigos:
        return {}
    if len(codigos) > 500:
        raise ValueError("Registre as versões em lotes de até 500 CARs.")
    if origem not in {"carga_antes", "carga_depois", "cadastro", "rodada", "consulta", "monitoramento"}:
        raise ValueError("Origem de versão desconhecida.")
    # A linha leve existe antes do lock; ordenação consistente evita deadlock entre cargas e leituras.
    con.execute(
        text("""insert into negocio.prospeccao_ficha_atual(cod_imovel)
        select unnest(cast(:cs as text[])) order by 1 on conflict do nothing"""),
        {"cs": codigos},
    )
    atuais = {
        r["cod_imovel"]: dict(r)
        for r in con.execute(
            text("""select a.*,v.documento
        from negocio.prospeccao_ficha_atual a left join negocio.prospeccao_ficha_versao v on v.id=a.versao_id
        where a.cod_imovel=any(:cs) order by a.cod_imovel for update of a"""),
            {"cs": codigos},
        ).mappings()
    }
    dados = _montar_lote(con, codigos)
    versoes = _guardar(con, dados)
    eventos = [
        {
            "car": c,
            "versao": versoes[c]["id"],
            "anterior": atuais[c]["versao_id"],
            "mudancas": diferencas(atuais[c]["documento"], versoes[c]["documento"]),
        }
        for c in codigos
        if atuais[c]["versao_id"] != versoes[c]["id"]
    ]
    if eventos:
        con.execute(
            text("""with inseridas as (
            insert into negocio.prospeccao_ficha_observacao(cod_imovel,versao_id,anterior_id,origem,mudancas)
            select x.car,x.versao,x.anterior,:origem,x.mudancas
            from jsonb_to_recordset(cast(:eventos as jsonb))
            as x(car text,versao bigint,anterior bigint,mudancas jsonb) order by x.car
            returning id,cod_imovel,versao_id)
            update negocio.prospeccao_ficha_atual a set versao_id=i.versao_id,observacao_id=i.id
            from inseridas i where i.cod_imovel=a.cod_imovel"""),
            {"eventos": _json(eventos), "origem": origem},
        )
    return {c: versoes[c]["id"] for c in codigos}


def _autorizar(con, cliente_id: int, codigos: list[str]) -> None:
    if con.execute(text("select id from negocio.cliente where id=:c and ativo"), {"c": cliente_id}).scalar() is None:
        raise ErroAcesso(401, "Entre novamente para continuar.")
    for car in codigos:  # Consulta interativa limitada a cinco, nunca utilizada na varredura nacional.
        canonico = _car_visivel(con, cliente_id, car)
        if canonico != car or not _liberada(con, cliente_id, car):
            raise ErroAcesso(402, "Libere a ficha com um crédito de consulta.")


def _mudancas_lotes(antes: list, depois: list) -> list[dict]:
    return [
        {
            "tipo": tipo,
            "campo": "lotes_da_conta",
            "antes": antes,
            "depois": depois,
            "fonte": "Raíz, pedidos da própria conta",
            "data_referencia": None,
            "data_corte": None,
        }
        for tipo, xs in (("entrou_lote", set(depois) - set(antes)), ("saiu_lote", set(antes) - set(depois)))
        if xs
    ]


@contextmanager
def consultas(engine: Engine, cliente_id: int, fichas: list[dict]):
    """Renderize JSON/PDF dentro do contexto: falha desfaz baseline e registros desta consulta."""
    if not 1 <= len(fichas) <= 5 or len({f["codigo_car"] for f in fichas}) != len(fichas):
        raise ErroAcesso(422, "Consulte de uma a cinco fichas diferentes.")
    codigos = sorted(f["codigo_car"] for f in fichas)
    with engine.begin() as con:
        con.execute(
            text("select pg_advisory_xact_lock(hashtextextended('prospeccao_consulta:'||cast(:c as text),0))"),
            {"c": cliente_id},
        )
        _autorizar(con, cliente_id, codigos)
        # A observação global vem da base vigente na transação, jamais de uma montagem anterior possivelmente velha.
        registrar_versoes(con, codigos, origem="consulta")
        versoes = _guardar(con, fichas)
        anteriores = {
            r["cod_imovel"]: dict(r)
            for r in con.execute(
                text("""select c.*,v.documento
            from negocio.prospeccao_ficha_consulta c join negocio.prospeccao_ficha_versao v on v.id=c.versao_id
            where c.cliente_id=:c and c.cod_imovel=any(:cs)"""),
                {"c": cliente_id, "cs": codigos},
            ).mappings()
        }
        lotes = {
            r.cod_imovel: r.lotes
            for r in con.execute(
                text("select * from (" + LOTES_SQL + ") l where l.cod_imovel=any(:cs)"),
                {"cliente_id": cliente_id, "cs": codigos},
            )
        }
        saida = []
        for f in fichas:
            car = f["codigo_car"]
            v, anterior = versoes[car], anteriores.get(car)
            mudancas = diferencas(anterior["documento"] if anterior else None, v["documento"])
            if anterior:
                mudancas += _mudancas_lotes(anterior["lotes"], lotes.get(car, []))
            saida.append(
                {
                    **projetar_ficha(f),
                    "versao_ficha": {
                        "id": v["id"],
                        "hash": v["hash_conteudo"],
                        "registrada_em": v["registrada_em"].isoformat(),
                    },
                    "o_que_mudou": {
                        "primeira_consulta": anterior is None,
                        "consulta_anterior_em": anterior["consultada_em"].isoformat() if anterior else None,
                        "versao_anterior_id": anterior["versao_id"] if anterior else None,
                        "versao_atual_id": v["id"],
                        "mudancas": mudancas,
                    },
                }
            )
        yield saida
        # Também detecta perda de autorização ocorrida enquanto o chamador renderizava a resposta.
        _autorizar(con, cliente_id, codigos)
        con.execute(
            text("""insert into negocio.prospeccao_ficha_consulta(cliente_id,cod_imovel,versao_id,lotes)
            select :c,x.car,x.versao,x.lotes from jsonb_to_recordset(cast(:itens as jsonb))
            as x(car text,versao bigint,lotes jsonb)
            on conflict(cliente_id,cod_imovel) do update set versao_id=excluded.versao_id,
                lotes=excluded.lotes,consultada_em=clock_timestamp()"""),
            {
                "c": cliente_id,
                "itens": _json([{"car": c, "versao": versoes[c]["id"], "lotes": lotes.get(c, [])} for c in codigos]),
            },
        )


def historico(engine: Engine, cliente_id: int, codigo_car: str, *, limite: int = 20) -> dict:
    if type(limite) is not int or not 1 <= limite <= 100:
        raise ErroAcesso(422, "Limite de histórico inválido.")
    with engine.begin() as con:
        car = _car_visivel(con, cliente_id, codigo_car)
        _autorizar(con, cliente_id, [car])
        rows = con.execute(
            text("""select o.id,o.origem,o.registrada_em,o.versao_id,o.anterior_id,o.mudancas,v.hash_conteudo
            from negocio.prospeccao_ficha_observacao o join negocio.prospeccao_ficha_versao v on v.id=o.versao_id
            where o.cod_imovel=:car order by o.id desc limit :limite"""),
            {"car": car, "limite": limite},
        ).mappings()
        return {
            "codigo_car": car,
            "historico": [
                {
                    **dict(r),
                    "mudancas": filtrar_mudancas(r["mudancas"]),
                    "registrada_em": r["registrada_em"].isoformat(),
                }
                for r in rows
            ],
        }
