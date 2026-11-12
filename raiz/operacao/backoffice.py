"""Backoffice do fundador (E7 passo 6), só leitura: saúde, custo do mês contra o orçamento, filas e logs por fazenda.

    GET /backoffice/resumo             saúde (banco, lotes das últimas 24 h, travados, vigilância, alertas abertos),
                                       custo do mês contra o orçamento (com projeção) e filas esperando o fundador
    GET /backoffice/custos             custo por tarefa, fazenda, município ou modelo (?por=&desde=)
    GET /backoffice/lotes              últimos lotes (?estado=falha&tarefa=funil), com o fim do log mascarado
    GET /backoffice/alertas            alertas de operação (?abertos=false para ver também os resolvidos)
    GET /backoffice/fazenda/{cod}      tudo o que aconteceu com uma fazenda: chamadas de modelo e custo, decisões da
                                       cascata, revisões, aceite, mensagens (sem o texto), pedidos, lotes do município
                                       e alertas da vigilância
    GET /painel/backoffice             página simples (sem dado nela: pede o token e lê as rotas acima)

    POST /operacao/alertas/{id}/reconhecer e /resolver   param a escada do alerta (raiz/operacao/alertas.py)

Nada pessoal sai: mensagens só com tipo e estado, textos livres mascarados, nenhum nome, telefone ou e-mail.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, text

from raiz.config import config
from raiz.logs_seguros import sanitizar_estrutura, sanitizar_log
from raiz.operacao import alertas as A
from raiz.operacao.custo import custo_por, gasto_do_mes

log = logging.getLogger(__name__)
LOG_FIM = 2000


def _json(dado) -> Response:
    return Response(
        json.dumps(sanitizar_estrutura(dado), ensure_ascii=False, default=str), media_type="application/json"
    )


def _texto(v, limite: int = 500):
    return sanitizar_log(str(v))[-limite:] if v is not None else None


def _talvez(f: Callable, padrao=None):
    """Uma parte do painel que falha (tabela ainda não migrada, estado da vigilância ausente) não derruba o resto."""
    try:
        return f()
    except Exception as ex:  # noqa: BLE001
        log.warning("backoffice: %s", sanitizar_log(str(ex))[:200])
        return padrao if padrao is not None else {"erro": type(ex).__name__}


def custo_do_mes(con: Connection, hoje: dt.date) -> dict:
    gasto = gasto_do_mes(con, hoje)
    orc = config().orcamento_mensal_usd
    inicio = hoje.replace(day=1)
    dias_mes = ((inicio + dt.timedelta(days=32)).replace(day=1) - inicio).days
    projecao = gasto / hoje.day * dias_mes if hoje.day else gasto
    linhas = lambda por: [  # noqa: E731
        {"chave": r.chave, "chamadas": int(r.chamadas), "falhas": int(r.falhas), "custo_usd": float(r.custo_usd),
         "sem_preco": int(r.sem_preco)}
        for r in custo_por(con, por, inicio, limite=10)
    ]  # fmt: skip
    return {
        "mes": inicio.strftime("%Y-%m"),
        "gasto_usd": round(gasto, 4),
        "orcamento_usd": orc,
        "pct": round(100 * gasto / orc, 1) if orc else None,
        "projecao_mes_usd": round(projecao, 4),
        "projecao_pct": round(100 * projecao / orc, 1) if orc else None,
        "por_tarefa": linhas("tarefa"),
        "por_modelo": linhas("modelo"),
    }


def _lotes_24h(con: Connection, agora: dt.datetime) -> dict:
    rs = con.execute(
        text("""select tarefa, estado, count(*) as n from operacao.lote where iniciado_em >= :d
                group by tarefa, estado order by tarefa, estado"""),
        {"d": agora - dt.timedelta(hours=24)},
    ).all()
    out: dict[str, dict] = {}
    for r in rs:
        out.setdefault(r.tarefa, {})[r.estado] = int(r.n)
    return out


def _filas(con: Connection) -> dict:
    def um(sql: str):
        return con.execute(text(sql)).one()

    rev = um("""select count(*) as n, min(criado_em) as antiga from operacao.fila_revisao where estado = 'aberta'""")
    msg = um("""select count(*) as n, min(criado_em) as antiga from pessoal.mensagem_saida
                where estado = 'aguardando_aprovacao'""")
    al = um("""select count(*) as n from negocio.alerta_pedido where visto_em is null""")
    ped = con.execute(text("select estado, count(*) as n from negocio.pedido group by estado")).all()
    return {
        "revisoes_abertas": int(rev.n),
        "revisao_mais_antiga": rev.antiga,
        "mensagens_aguardando_aprovacao": int(msg.n),
        "mensagem_mais_antiga": msg.antiga,
        "alertas_de_pedido_nao_vistos": int(al.n),
        "pedidos_por_estado": {r.estado: int(r.n) for r in ped},
    }


def alertas_operacao(con: Connection, abertos: bool = True, limite: int = 100) -> list[dict]:
    filtro = "where resolvido_em is null" if abertos else ""
    rs = con.execute(
        text(f"""select id, origem, chave, gravidade, titulo, texto, detalhe, nivel, envios, criado_em,
                 ultimo_envio_em, reconhecido_em, reconhecido_por, resolvido_em, resolucao, regra_versao
                 from operacao.alerta {filtro} order by resolvido_em is not null, id desc limit :l"""),
        {"l": limite},
    ).mappings()
    return [dict(r) for r in rs]


def resumo(engine: Engine, agora: dt.datetime | None = None, vigilancia=None) -> dict:
    agora = agora or dt.datetime.now(dt.UTC)
    hoje = agora.date()
    with engine.connect() as con:
        banco = _talvez(lambda: con.execute(text("select 1")).scalar() == 1, False)
        travados = _talvez(
            lambda: int(
                con.execute(
                    text("select count(*) from operacao.lote where estado = 'iniciado' and iniciado_em < :l"),
                    {"l": agora - dt.timedelta(hours=float(A.politica()["regras"]["lote_travado"]["horas"]))},
                ).scalar()
            ),
            0,
        )
        out = {
            "gerado_em": agora.isoformat(timespec="seconds"),
            "saude": {
                "banco": banco,
                "lotes_24h": _talvez(lambda: _lotes_24h(con, agora), {}),
                "lotes_travados": travados,
                "alertas_abertos": _talvez(
                    lambda: {
                        g: n
                        for g, n in con.execute(
                            text("""select gravidade, count(*) from operacao.alerta where resolvido_em is null
                                    group by gravidade""")
                        ).all()
                    },
                    {},
                ),
            },
            "custo": _talvez(lambda: custo_do_mes(con, hoje)),
            "filas": _talvez(lambda: _filas(con)),
            "alertas": _talvez(lambda: alertas_operacao(con, True, 20), []),
        }
    if vigilancia is None:
        vigilancia = _talvez(lambda: __import__("raiz.vigilancia.servico", fromlist=["Vigilancia"]).Vigilancia(), None)
    if vigilancia is not None:
        out["saude"]["vigilancia"] = _talvez(lambda: vigilancia.saude(hoje))
        out["filas"]["avisos_vigilancia_aguardando"] = _talvez(
            lambda: len(vigilancia.avisos("aguardando_aprovacao", hoje)), None
        )
    return out


def fazenda(engine: Engine, cod: str, vigilancia=None, limite: int = 50) -> dict:
    """Logs de uma fazenda, do mais novo para o mais velho."""
    cod = cod.strip()
    partes = cod.split("-")
    mun = int(partes[1]) if len(partes) >= 2 and partes[1].isdigit() else None
    with engine.connect() as con:

        def lista(sql: str, **par):
            return [dict(r) for r in con.execute(text(sql), {"c": cod, "l": limite, **par}).mappings()]

        chamadas = _talvez(
            lambda: lista("""select tarefa, provedor, modelo, papel, ok, erro, custo_usd, tokens_entrada, tokens_saida,
                             duracao_ms, rastro_id, criado_em from operacao.chamada_modelo where cod_imovel = :c
                             order by id desc limit :l"""),
            [],
        )
        for c in chamadas:
            c["erro"] = _texto(c["erro"])
        custo = _talvez(
            lambda: float(
                con.execute(
                    text("select coalesce(sum(custo_usd), 0) from operacao.chamada_modelo where cod_imovel = :c"),
                    {"c": cod},
                ).scalar()
            ),
            0.0,
        )
        out = {
            "cod_imovel": cod,
            "custo_modelos_usd": round(custo, 6),
            "chamadas_modelo": chamadas,
            "decisoes_cascata": _talvez(
                lambda: lista("""select tarefa, via, custo_usd, criado_em from operacao.decisao_cascata
                                 where chave = :c order by id desc limit :l"""),
                [],
            ),
            "revisoes": _talvez(
                lambda: [
                    {**r, "motivo": _texto(r["motivo"], 300)}
                    for r in lista("""select id, tarefa, motivo, estado, resolvida_por, criado_em, resolvida_em
                                      from operacao.fila_revisao where chave = :c order by id desc limit :l""")
                ],
                [],
            ),
            "aceite": _talvez(
                lambda: next(
                    iter(
                        lista("""select estado, etapa, motivo, iniciado_em, atualizado_em, encerrado_em
                                  from negocio.aceite where cod_imovel = :c""")
                    ),
                    None,
                ),
                None,
            ),
            # só tipo e estado: o texto da mensagem fala com o dono e fica no esquema pessoal
            "mensagens": _talvez(
                lambda: lista("""select id, tipo, estado, aprovada_em, enviada_em, criado_em from pessoal.mensagem_saida
                                 where cod_imovel = :c order by id desc limit :l"""),
                [],
            ),
            "pedidos": _talvez(
                lambda: lista("""select f.pedido_id, f.papel, f.trocou, p.estado as estado_pedido, f.atualizado_em
                                 from negocio.pedido_fazenda f join negocio.pedido p on p.id = f.pedido_id
                                 where f.cod_imovel = :c order by f.atualizado_em desc limit :l"""),
                [],
            ),
            "interesse": _talvez(
                lambda: next(
                    iter(lista("select nivel, atualizado_em from negocio.interesse_dono where cod_imovel = :c")), None
                ),
                None,
            ),
            "lotes_do_municipio": _talvez(
                lambda: (
                    [
                        {**r, "log_final": _texto(r["log_final"], LOG_FIM)}
                        for r in lista(
                            """select tarefa, estado, rid, iniciado_em, terminado_em, duracao_s, log_final
                           from operacao.lote where cod_municipio = :m order by id desc limit :l""",
                            m=mun,
                        )
                    ]
                    if mun
                    else []
                ),
                [],
            ),
        }
    if vigilancia is None:
        vigilancia = _talvez(lambda: __import__("raiz.vigilancia.servico", fromlist=["Vigilancia"]).Vigilancia(), None)
    if vigilancia is not None:

        def vig():
            al = vigilancia.arm.alertas("imovel", cod)
            if not len(al):
                return {"alertas": 0}
            return {
                "alertas": int(len(al)),
                "por_fonte": {str(k): int(v) for k, v in al["fonte"].value_counts().items()},
                "ultimo_evento": max((d for d in al["data_evento"] if d is not None), default=None),
                "rota": f"/vigilancia/imovel/{cod}",
            }

        out["vigilancia"] = _talvez(vig)
    return out


def lotes(engine: Engine, estado: str | None = None, tarefa: str | None = None, limite: int = 100) -> list[dict]:
    filtros, par = ["true"], {"l": limite}
    if estado:
        filtros.append("estado = :e")
        par["e"] = estado
    if tarefa:
        filtros.append("tarefa = :t")
        par["t"] = tarefa
    with engine.connect() as con:
        rs = con.execute(
            text(f"""select id, tarefa, uf, cod_municipio, rid, estado, detalhe, iniciado_em, terminado_em, duracao_s,
                     log_final from operacao.lote where {" and ".join(filtros)} order by id desc limit :l"""),
            par,
        ).mappings()
        return [{**dict(r), "log_final": _texto(r["log_final"], LOG_FIM)} for r in rs]


class Decisao(BaseModel):
    quem: str = "fundador"
    nota: str = ""


def roteador(engine_de: Callable[[Request], Engine]) -> APIRouter:
    """Rotas com token (o include no raiz/api.py põe a dependência)."""
    r = APIRouter(tags=["backoffice"])

    @r.get("/backoffice/resumo")
    def get_resumo(request: Request):
        return _json(resumo(engine_de(request)))

    @r.get("/backoffice/custos")
    def get_custos(
        request: Request, por: str = "tarefa", desde: dt.date | None = None, limite: int = Query(50, le=500)
    ):
        if por not in ("tarefa", "fazenda", "municipio", "modelo"):
            raise HTTPException(422, "por: tarefa, fazenda, municipio ou modelo")
        with engine_de(request).connect() as con:
            rs = custo_por(con, por, desde or dt.date.today().replace(day=1), limite)
        return _json([{**r._mapping, "custo_usd": float(r.custo_usd)} for r in rs])

    @r.get("/backoffice/lotes")
    def get_lotes(request: Request, estado: str | None = None, tarefa: str | None = None,
                  limite: int = Query(100, le=1000)):  # fmt: skip
        return _json(lotes(engine_de(request), estado, tarefa, limite))

    @r.get("/backoffice/alertas")
    def get_alertas(request: Request, abertos: bool = True, limite: int = Query(100, le=1000)):
        with engine_de(request).connect() as con:
            return _json(alertas_operacao(con, abertos, limite))

    @r.get("/backoffice/fazenda/{cod_imovel}")
    def get_fazenda(cod_imovel: str, request: Request):
        return _json(fazenda(engine_de(request), cod_imovel))

    @r.post("/operacao/alertas/{alerta_id}/reconhecer")
    def post_reconhecer(alerta_id: int, corpo: Decisao, request: Request):
        with engine_de(request).begin() as con:
            if not A.reconhecer(con, alerta_id, corpo.quem):
                raise HTTPException(404, "alerta aberto não encontrado")
        return {"reconhecido": alerta_id}

    @r.post("/operacao/alertas/{alerta_id}/resolver")
    def post_resolver(alerta_id: int, corpo: Decisao, request: Request):
        with engine_de(request).begin() as con:
            if not A.resolver(con, alerta_id, corpo.quem, corpo.nota):
                raise HTTPException(404, "alerta aberto não encontrado")
        return {"resolvido": alerta_id}

    return r


def roteador_publico() -> APIRouter:
    r = APIRouter(tags=["backoffice"])

    @r.get("/painel/backoffice", response_class=HTMLResponse)
    def pagina() -> HTMLResponse:
        return HTMLResponse(PAGINA)

    return r


PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Backoffice da Raíz</title>
<style>body{font:16px/1.5 system-ui,sans-serif;margin:24px;color:#15231B;background:#FAFAF7;max-width:1100px}
h2{margin-top:28px;font-size:20px}table{border-collapse:collapse;width:100%}th,td{padding:6px 10px;
border-bottom:1px solid #E7EAE4;text-align:left;vertical-align:top}td.n{text-align:right;font-variant-numeric:
tabular-nums}.critico,.falha{color:#9E3F0E}.urgente{color:#7E5510}.aviso{color:#555D56}.ok{color:#1D6B44}
input,button{font:inherit;padding:6px 10px}pre{white-space:pre-wrap;font-size:13px;background:#F1F3EE;padding:8px}
</style></head><body><h1>Backoffice</h1><p id="msg">Informe o token da API para ver a operação (só leitura).</p>
<form id="f"><input id="t" type="password" placeholder="token da API" autocomplete="off"> <button>Ver</button></form>
<div id="conteudo" hidden><h2>Saúde</h2><p id="saude"></p><h2>Custo do mês</h2><p id="custo"></p>
<table id="custos"><thead><tr><th>Tarefa</th><th>Chamadas</th><th>Falhas</th><th>US$</th></tr></thead><tbody></tbody>
</table><h2>Filas</h2><p id="filas"></p><h2>Alertas abertos</h2><table id="alertas"><thead><tr><th>Gravidade</th>
<th>Alerta</th><th>Nível</th><th>Desde</th></tr></thead><tbody></tbody></table><h2>Fazenda</h2>
<form id="ff"><input id="cod" placeholder="código do CAR" size="50"> <button>Ver logs</button></form>
<pre id="fazenda"></pre></div>
<script>
let TOK="";const $=s=>document.querySelector(s);
const pega=async c=>{const r=await fetch("../"+c,{headers:{Authorization:"Bearer "+TOK}});
if(!r.ok)throw new Error(r.status);return r.json()};
const us=v=>v==null?"sem orçamento":"US$ "+Number(v).toFixed(2);
const data=v=>(v||"").replace("T"," ").slice(0,16);
function linhas(sel,itens,cols){const tb=$(sel+" tbody");tb.innerHTML="";for(const i of itens){
const tr=document.createElement("tr");for(const[v,cls]of cols(i)){const td=document.createElement("td");
td.textContent=v??"";if(cls)td.className=cls;tr.appendChild(td)}tb.appendChild(tr)}}
async function ver(){try{const d=await pega("backoffice/resumo");const s=d.saude,c=d.custo||{},f=d.filas||{};
const lotes=Object.entries(s.lotes_24h||{}).map(([t,e])=>`${t}: ${e.sucesso||0} ok, ${e.falha||0} falhas`).join("; ");
const v=s.vigilancia||{};$("#saude").textContent=`Banco ${s.banco?"no ar":"fora do ar"}. Lotes em 24 h: `+
`${lotes||"nenhum"}. Parados: ${s.lotes_travados}. Vigilância: última rodada ${data(v.ultima_rodada)||"nunca"}`+
`${v.atrasada?" (atrasada)":""}.`;$("#custo").textContent=`${c.mes||""}: gasto ${us(c.gasto_usd)} de `+
`${us(c.orcamento_usd)}${c.pct!=null?" ("+c.pct+"%)":""}; projeção do mês ${us(c.projecao_mes_usd)}.`;
linhas("#custos",c.por_tarefa||[],i=>[[i.chave],[i.chamadas,"n"],[i.falhas,"n"],[i.custo_usd.toFixed(4),"n"]]);
$("#filas").textContent=`Revisões abertas: ${f.revisoes_abertas??"?"}. Mensagens esperando aprovação: `+
`${f.mensagens_aguardando_aprovacao??"?"}. Avisos da vigilância esperando: ${f.avisos_vigilancia_aguardando??"?"}. `+
`Alertas de pedido não vistos: ${f.alertas_de_pedido_nao_vistos??"?"}.`;
linhas("#alertas",d.alertas||[],a=>[[a.gravidade,a.gravidade],[a.titulo],[a.nivel,"n"],[data(a.criado_em)]]);
$("#msg").textContent="Atualizado em "+data(d.gerado_em)+" (UTC).";$("#conteudo").hidden=false}
catch(e){$("#msg").textContent="Não deu para ler ("+e.message+")."}}
$("#f").onsubmit=e=>{e.preventDefault();TOK=$("#t").value;try{sessionStorage.setItem("raiz:token",TOK)}catch(_){}
ver()};$("#ff").onsubmit=async e=>{e.preventDefault();try{$("#fazenda").textContent=JSON.stringify(
await pega("backoffice/fazenda/"+encodeURIComponent($("#cod").value.trim())),null,1)}catch(x){
$("#fazenda").textContent="Não deu para ler ("+x.message+")."}};
try{const t=sessionStorage.getItem("raiz:token");if(t){TOK=t;ver()}}catch(_){}
</script></body></html>"""
