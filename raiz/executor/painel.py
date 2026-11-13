"""Painel do processamento e números do Brasil e dos estados, servidos pela API.

GET /processamento           estados prontos, em andamento e com erro, feitos/total, versão do motor e de cada tarefa
GET /painel/processamento    página simples (sem dado nela: pede o token e lê /processamento)
GET /brasil                  soma nacional do resumo dos estados carregados (imóveis, aptas, ha, tCO2)
GET /estados                 o mesmo por estado, com a situação do processamento
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Engine, text

from raiz.executor.armazem import Armazem, ler_json

SITUACOES = ("pronto", "em_andamento", "com_erro", "nao_iniciado")
NUMEROS = ("municipios", "imoveis", "sem_problema", "aptas_carbono", "ha_carbono", "tco2_ano_aptas")


def processamento(armazem: Armazem, ufs: list[str] | None = None) -> dict:
    from raiz.executor.tarefas import UFS

    estados = []
    for uf in ufs or UFS:
        e = ler_json(armazem, f"estado/{uf}.json")
        if e is None:
            estados.append({"uf": uf, "situacao": "nao_iniciado"})
            continue
        estados.append({
            "uf": uf,
            "situacao": e.get("situacao"),
            "feitos": e.get("feitos"),
            "total": e.get("total"),
            "rodados": e.get("rodados"),
            "erros": len(e.get("erros") or []),
            "ultimos_erros": (e.get("erros") or [])[-5:],
            "motor_versao": e.get("motor_versao"),
            "versoes": e.get("versoes"),
            "inicio": e.get("inicio"),
            "fim": e.get("fim"),
            "atualizado_em": e.get("atualizado_em"),
            "maquina": e.get("maquina"),
        })  # fmt: skip
    cont = {s: sum(1 for e in estados if e["situacao"] == s) for s in SITUACOES}
    from raiz.executor.agenda import CHAVE_COLECAO, colecao_mapbiomas

    return {
        "armazem": armazem.descricao,
        "colecao_mapbiomas": colecao_mapbiomas(),
        "colecao_feita": (ler_json(armazem, CHAVE_COLECAO) or {}).get("colecao"),
        "contagem": cont,
        "estados": estados,
    }


def _resumo_por_uf(engine: Engine) -> list[dict]:
    with engine.connect() as con:
        return [
            dict(r._mapping)
            for r in con.execute(
                text("""
                select ro.uf, count(*) as municipios, sum(m.imoveis) as imoveis, sum(m.sem_problema) as sem_problema,
                       sum(m.aptas_carbono) as aptas_carbono, sum(m.ha_carbono) as ha_carbono,
                       sum(m.tco2_ano_aptas) as tco2_ano_aptas, max(ro.data_corte) as data_corte,
                       max(ro.motor_versao) as motor_versao
                from funil.resumo_municipio m join funil.rodada ro on ro.id = m.rodada_id
                where ro.id in (select distinct on (uf) id from funil.rodada where tipo = 'resumo_uf'
                                order by uf, data_corte desc, id desc)
                group by ro.uf order by ro.uf""")
            )
        ]


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Processamento da Raíz</title>
<style>body{font:16px/1.5 system-ui,sans-serif;margin:24px;color:#15231B;background:#FAFAF7}
table{border-collapse:collapse;width:100%;max-width:1100px}th,td{padding:6px 10px;border-bottom:1px solid #E7EAE4;
text-align:left}td.n{text-align:right;font-variant-numeric:tabular-nums}.pronto{color:#1D6B44}.com_erro{color:#9E3F0E}
.em_andamento{color:#7E5510}.nao_iniciado{color:#555D56}input,button{font:inherit;padding:6px 10px}</style></head>
<body><h1>Processamento do motor</h1><p id="resumo">Informe o token da API para ver o andamento.</p>
<form id="f"><input id="t" type="password" placeholder="token da API" autocomplete="off">
<button>Ver</button></form><table id="tab" hidden><thead><tr><th>Estado</th><th>Situação</th><th>Feitos</th>
<th>Erros</th><th>Versão do motor</th><th>Atualizado</th></tr></thead><tbody></tbody></table>
<script>
const NOMES={pronto:"pronto",em_andamento:"em andamento",com_erro:"com erro",nao_iniciado:"não iniciado"};
async function ver(tok){const r=await fetch("../processamento",{headers:{Authorization:"Bearer "+tok}});
if(!r.ok){document.getElementById("resumo").textContent="Não deu para ler ("+r.status+").";return}
const d=await r.json();const c=d.contagem;document.getElementById("resumo").textContent=
`${c.pronto} prontos, ${c.em_andamento} em andamento, ${c.com_erro} com erro, ${c.nao_iniciado} não iniciados. `+
`Coleção do MapBiomas: ${d.colecao_mapbiomas||"?"} (feita: ${d.colecao_feita||"ainda não"}). Armazém: ${d.armazem}.`;
const tb=document.querySelector("tbody");tb.innerHTML="";
for(const e of d.estados){const tr=document.createElement("tr");
const cel=(v,cls)=>{const td=document.createElement("td");td.textContent=v??"";if(cls)td.className=cls;
tr.appendChild(td)};
cel(e.uf);cel(NOMES[e.situacao]||e.situacao,e.situacao);cel(e.total?`${e.feitos} de ${e.total}`:"","n");
cel(e.erros??"","n");cel(e.motor_versao||"");cel((e.atualizado_em||"").replace("T"," ").slice(0,16));
tb.appendChild(tr)}
document.getElementById("tab").hidden=false}
document.getElementById("f").onsubmit=e=>{e.preventDefault();const t=document.getElementById("t").value;
try{sessionStorage.setItem("raiz:token",t)}catch(_){}ver(t)};
try{const t=sessionStorage.getItem("raiz:token");if(t)ver(t)}catch(_){}
</script></body></html>"""


def roteador(engine_de, armazem_de) -> APIRouter:
    """Rotas com token (montadas junto das outras da API)."""
    r = APIRouter()

    def _json(d) -> Response:
        return Response(json.dumps(d, ensure_ascii=False, default=str), media_type="application/json")

    @r.get("/processamento")
    def proc(request: Request) -> Response:
        return _json(processamento(armazem_de(request)))

    @r.get("/estados")
    def estados(request: Request) -> Response:
        res = {x["uf"]: x for x in _resumo_por_uf(engine_de(request))}
        proc = {e["uf"]: e for e in processamento(armazem_de(request))["estados"]}
        out = []
        for uf, p in proc.items():
            x = res.get(uf, {})
            out.append({
                "uf": uf,
                "situacao_processamento": p["situacao"],
                "feitos": p.get("feitos"),
                "total_municipios": p.get("total"),
                "motor_versao": p.get("motor_versao") or x.get("motor_versao"),
                **{k: _num(x.get(k)) for k in NUMEROS},
                "data_corte": x.get("data_corte"),
            })  # fmt: skip
        return _json(out)

    @r.get("/brasil")
    def brasil(request: Request) -> Response:
        res = _resumo_por_uf(engine_de(request))
        soma = {k: sum(_num(x.get(k)) or 0 for x in res) for k in NUMEROS}
        p = processamento(armazem_de(request))
        return _json({**soma, "estados_com_dado": len(res), "processamento": p["contagem"],
                      "colecao_mapbiomas": p["colecao_mapbiomas"]})  # fmt: skip

    return r


def roteador_publico(armazem_de=None) -> APIRouter:
    r = APIRouter()
    trava = threading.Lock()
    cache: dict = {}

    if armazem_de is not None:

        @r.get("/processamento/publico")
        def processamento_aberto(request: Request) -> Response:
            from raiz.executor.processamento_publico import ler_painel

            # Um GET público não deve multiplicar consultas autenticadas ao Release.
            with trava:
                if time.monotonic() >= cache.get("ate", 0):
                    try:
                        cache["dado"] = ler_painel(armazem_de(request))
                    except Exception:  # noqa: BLE001
                        # A mensagem da origem pode conter caminhos ou identificadores privados.
                        return Response(
                            '{"erro":"observacao_indisponivel"}',
                            status_code=503,
                            media_type="application/json",
                            headers={"Cache-Control": "no-store"},
                        )
                    cache["ate"] = time.monotonic() + 15
                return Response(
                    json.dumps(_expirar_observacoes(cache["dado"]), ensure_ascii=False),
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"},
                )

    @r.get("/painel/processamento", response_class=HTMLResponse)
    def pagina() -> HTMLResponse:
        return HTMLResponse(PAGINA)

    return r


def _expirar_observacoes(dado: dict) -> dict:
    """O cache HTTP não estende a prova de uma execução em andamento."""
    import copy

    out = copy.deepcopy(dado)
    agora = dt.datetime.now(dt.UTC)
    for estado in out["estados"]:
        validade = estado.get("valido_ate")
        if validade and dt.datetime.fromisoformat(validade) <= agora:
            estado["situacao"] = "desatualizado"
            estado["municipios"]["em_execucao"] = None
    return out
