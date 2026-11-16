"""Previsões congeladas no formato do hub (hubverse) e painel de acerto (E7 passo 5).

`exportar(engine, pasta)` grava uma pasta de hub que as ferramentas do hubverse leem (hubData, hubEvals,
hubPredEvalsData e o hub-dashboard, o mesmo do painel do FluSight):

    hub-config/admin.json, tasks.json, model-metadata-schema.json   (esquemas v6.0.0 do hubverse)
    model-metadata/<model_id>.yml                                   um modelo por (modelo, versão) da Raíz
    model-output/<model_id>/<data_corte>-<model_id>.parquet          previsões de cada rodada
    target-data/oracle-output.csv                                   gabaritos no formato oracle output
    site-config.yml, predevals-config.yml, predtimechart-config.yml  painel no molde do flusight-dashboard (CC0)

Tarefa de previsão (task ids): reference_date = data de corte (a rodada), location = código do CAR, target = alvo,
horizon = horizonte em dias, target_end_date = data em que o resultado amadurece. Saídas:
    quantile  0.1, 0.5 e 0.9 quando a previsão tem P10, P50 e P90
    pmf       categorias (verdadeiro/falso para chance; as categorias vistas para texto)
    mean      número sem faixa
O model_id é raiz-<modelo>_<versão>, para comparar versões como modelos diferentes (campeão e desafiante).

As previsões e os gabaritos são da Raíz e podem dizer quem aceitou (aceite_dono): a pasta fica no servidor (fora do
git) e o painel é servido pela API com token (/painel/acerto). Sem nome, CPF ou contato: só código do CAR e números.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Engine, text

from raiz.aprendizado import acerto as AC

ESQUEMAS = "https://raw.githubusercontent.com/hubverse-org/schemas/main/v6.0.0"
PREDEVALS = "https://raw.githubusercontent.com/hubverse-org/hubPredEvalsData/main/inst/schema/v1.1.0/config_schema.json"
QUANTIS = (0.1, 0.5, 0.9)
COLS_SAIDA = ["reference_date", "location", "target", "horizon", "target_end_date", "output_type", "output_type_id",
              "value"]  # fmt: skip


def _slug(s: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^0-9a-z]+", "_", str(s).lower())).strip("_") or "x"


def model_id(modelo: str, versao: str) -> str:
    """team_abbr-model_abbr, só letras, números e sublinhado (regra do hubverse)."""
    v = _slug(versao)
    if len(v) > 32:
        v = v[:24] + "_" + hashlib.sha1(str(versao).encode()).hexdigest()[:7]
    return f"raiz-{_slug(modelo)[:40]}_{v}"


def _cat(v) -> str:
    return str(v).strip().lower()


def linhas_previsao(p: dict, categorias: list[str] | None = None) -> list[dict]:
    """Uma previsão congelada nas linhas do model output."""
    base = {
        "reference_date": str(p["data_corte"]),
        "location": p["cod_imovel"],
        "target": p["alvo"],
        "horizon": int(p["horizonte_dias"]),
        "target_end_date": str(p["horizonte_em"]),
    }
    if AC.e_probabilidade(p["alvo"]) and p.get("valor_num") is not None:
        x = min(max(float(p["valor_num"]), 0.0), 1.0)
        return [
            {**base, "output_type": "pmf", "output_type_id": "verdadeiro", "value": x},
            {**base, "output_type": "pmf", "output_type_id": "falso", "value": 1.0 - x},
        ]
    if all(p.get(k) is not None for k in ("p10", "p50", "p90")):
        vals = sorted(float(p[k]) for k in ("p10", "p50", "p90"))
        return [
            {**base, "output_type": "quantile", "output_type_id": str(q), "value": v}
            for q, v in zip(QUANTIS, vals, strict=True)
        ]
    if p.get("valor_num") is not None:
        return [{**base, "output_type": "mean", "output_type_id": None, "value": float(p["valor_num"])}]
    if p.get("valor_texto") is not None:
        escolhida = _cat(p["valor_texto"])
        cats = categorias or [escolhida]
        return [
            {**base, "output_type": "pmf", "output_type_id": c, "value": 1.0 if c == escolhida else 0.0} for c in cats
        ]
    return []


def linhas_gabarito(r: dict, categorias: list[str] | None = None) -> list[dict]:
    """O gabarito pareado com uma previsão (visão previsao_contra_gabarito) no formato oracle output."""
    base = {"location": r["cod_imovel"], "target": r["alvo"], "target_end_date": str(r["horizonte_em"])}
    if r.get("real_num") is None and r.get("real_texto") is None:
        return []
    if AC.e_probabilidade(r["alvo"]):
        y = AC._verdade(r.get("real_num"), r.get("real_texto"))
        return [
            {**base, "output_type": "pmf", "output_type_id": "verdadeiro", "oracle_value": float(y)},
            {**base, "output_type": "pmf", "output_type_id": "falso", "oracle_value": float(1 - y)},
        ]
    if r.get("valor_texto") is not None and r.get("real_texto") is not None:
        real = _cat(r["real_texto"])
        return [
            {**base, "output_type": "pmf", "output_type_id": c, "oracle_value": 1.0 if c == real else 0.0}
            for c in (categorias or [real])
        ]
    if r.get("real_num") is None:
        return []
    tipo = "quantile" if r.get("p50") is not None else "mean"
    return [{**base, "output_type": tipo, "output_type_id": None, "oracle_value": float(r["real_num"])}]


def _ler(engine: Engine, desde: dt.date | None):
    filtro, par = ("where p.data_corte >= :d", {"d": desde}) if desde else ("", {})
    with engine.connect() as con:
        prev = [
            dict(r)
            for r in con.execute(
                text(f"""select p.cod_imovel, p.alvo, p.modelo, p.modelo_versao, p.entradas_versao, p.regras_versao,
                         p.data_corte, p.horizonte_dias, p.horizonte_em, p.valor_num, p.valor_texto, p.p10, p.p50,
                         p.p90, p.tipo from aprendizado.previsao p {filtro}"""),
                par,
            ).mappings()
        ]
        pares = [
            dict(r)
            for r in con.execute(
                text(f"""select v.* from aprendizado.previsao_contra_gabarito v
                         {filtro.replace("p.", "v.")} """),
                par,
            ).mappings()
            if r["gabarito_id"] is not None
        ]
    return prev, pares


def _categorias(prev: list[dict], pares: list[dict]) -> dict[str, list[str]]:
    cats: dict[str, set[str]] = defaultdict(set)
    for p in prev:
        if p.get("valor_texto") is not None and not AC.e_probabilidade(p["alvo"]):
            cats[p["alvo"]].add(_cat(p["valor_texto"]))
    for r in pares:
        if r.get("real_texto") is not None and r.get("valor_texto") is not None:
            cats[r["alvo"]].add(_cat(r["real_texto"]))
    return {k: sorted(v) for k, v in cats.items()}


def _tipo_alvo(linhas: list[dict]) -> dict[str, set[str]]:
    t: dict[str, set[str]] = defaultdict(set)
    for li in linhas:
        t[li["target"]].add(li["output_type"])
    return t


def _tasks(saida: pd.DataFrame, cats: dict[str, list[str]]) -> dict:
    tarefas = []
    metas = []
    for alvo, g in saida.groupby("target", sort=True):
        tipos = set(g["output_type"])
        ot = {}
        if "quantile" in tipos:
            ot["quantile"] = {"output_type_id": {"required": list(QUANTIS)}, "value": {"type": "double"}}
        if "mean" in tipos:
            ot["mean"] = {"output_type_id": {"required": None}, "value": {"type": "double"}}
        if "pmf" in tipos:
            ids = ["verdadeiro", "falso"] if AC.e_probabilidade(alvo) else cats.get(alvo, [])
            ot["pmf"] = {"output_type_id": {"required": ids}, "value": {"type": "double", "minimum": 0, "maximum": 1}}
        for k in ot:
            ot[k]["is_required"] = False
        tarefas.append(
            {
                "task_ids": {
                    "reference_date": {"required": None, "optional": sorted(set(g["reference_date"]))},
                    "target": {"required": [alvo], "optional": None},
                    "horizon": {"required": None, "optional": sorted({int(h) for h in g["horizon"]})},
                    "location": {"required": None, "optional": sorted(set(g["location"]))},
                    "target_end_date": {"required": None, "optional": sorted(set(g["target_end_date"]))},
                },
                "output_type": ot,
                "target_metadata": [
                    {
                        "target_id": alvo,
                        "target_name": alvo.replace("_", " "),
                        "target_units": "conforme o alvo (ha, tCO2e, R$, chance ou categoria)",
                        "target_keys": {"target": alvo},
                        "description": f"Previsão congelada da Raíz para {alvo.replace('_', ' ')}, por imóvel do CAR.",
                        "target_type": "binary"
                        if AC.e_probabilidade(alvo)
                        else ("nominal" if "pmf" in tipos else "continuous"),
                        "is_step_ahead": True,
                        "time_unit": "day",
                    }
                ],
            }
        )
        metas.append(alvo)
    return {
        "schema_version": f"{ESQUEMAS}/tasks-schema.json",
        "rounds": [
            {
                "round_id_from_variable": True,
                "round_id": "reference_date",
                "model_tasks": tarefas,
                "submissions_due": {"relative_to": "reference_date", "start": -3650, "end": 3650},
            }
        ],
    }


def _predevals(tipos: dict[str, set[str]]) -> dict:
    alvos = []
    for alvo, ts in sorted(tipos.items()):
        if "quantile" in ts:
            m = ["wis", "ae_median", "interval_coverage_80"]
        elif "pmf" in ts:
            m = ["log_score"]
        else:
            m = ["se_point"]
        alvos.append({"target_id": alvo, "metrics": m, "disaggregate_by": ["reference_date", "horizon"]})
    return {
        "schema_version": PREDEVALS,
        "rounds_idx": 0,
        "targets": alvos,
        "eval_sets": [
            {"eval_set_name": "Todas as rodadas"},
            {"eval_set_name": "Últimas 4 rodadas", "round_filters": {"n_last": 4}},
        ],
    }


def exportar(engine: Engine, pasta: str | Path, desde: dt.date | None = None) -> dict:
    """Grava a pasta do hub. Devolve as contagens."""
    pasta = Path(pasta)
    prev, pares = _ler(engine, desde)
    cats = _categorias(prev, pares)
    por_modelo: dict[str, list[dict]] = defaultdict(list)
    meta: dict[str, dict] = {}
    todas = []
    for p in prev:
        mid = model_id(p["modelo"], p["modelo_versao"])
        meta.setdefault(mid, {"modelo": p["modelo"], "versao": p["modelo_versao"],
                              "entradas": set(), "regras": p.get("regras_versao")})  # fmt: skip
        meta[mid]["entradas"].add(p["entradas_versao"])
        ls = linhas_previsao(p, cats.get(p["alvo"]))
        por_modelo[mid] += ls
        todas += ls
    arquivos = 0
    for mid, ls in por_modelo.items():
        df = pd.DataFrame(ls, columns=COLS_SAIDA)
        df["output_type_id"] = df["output_type_id"].astype("string")
        for rodada, g in df.groupby("reference_date"):
            destino = pasta / "model-output" / mid / f"{rodada}-{mid}.parquet"
            destino.parent.mkdir(parents=True, exist_ok=True)
            g.reset_index(drop=True).to_parquet(destino, index=False)
            arquivos += 1
        m = meta[mid]
        md = {
            "team_name": "Raíz",
            "team_abbr": "raiz",
            "model_name": f"{m['modelo']} {m['versao']}",
            "model_abbr": mid.split("-", 1)[1],
            "designated_model": True,
            "methods": f"Previsão congelada pelo produto da Raíz (modelo {m['modelo']}, versão {m['versao']}).",
            "raiz_modelo": m["modelo"],
            "raiz_modelo_versao": m["versao"],
            "raiz_regras_versao": m["regras"],
            "raiz_entradas_versao": sorted(x for x in m["entradas"] if x)[:20],
        }
        (pasta / "model-metadata").mkdir(parents=True, exist_ok=True)
        (pasta / "model-metadata" / f"{mid}.yml").write_text(
            yaml.safe_dump(md, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
    oraculo = pd.DataFrame(
        [li for r in pares for li in linhas_gabarito(r, cats.get(r["alvo"]))],
        columns=["location", "target", "target_end_date", "output_type", "output_type_id", "oracle_value"],
    ).drop_duplicates()
    (pasta / "target-data").mkdir(parents=True, exist_ok=True)
    oraculo.to_csv(pasta / "target-data" / "oracle-output.csv", index=False, na_rep="NA")
    saida = pd.DataFrame(todas, columns=COLS_SAIDA)
    cfg = pasta / "hub-config"
    cfg.mkdir(parents=True, exist_ok=True)
    admin = {
        "schema_version": f"{ESQUEMAS}/admin-schema.json",
        "name": "Raíz: previsões congeladas",
        "maintainer": "Raíz",
        "contact": {"name": "Raíz", "email": "operacao@raiz.invalid"},
        "repository": {"host": "github", "owner": "bernardoemmel", "name": "raiz"},
        "file_format": ["parquet"],
        "timezone": "America/Sao_Paulo",
    }
    (cfg / "admin.json").write_text(json.dumps(admin, ensure_ascii=False, indent=2), encoding="utf-8")
    (cfg / "tasks.json").write_text(json.dumps(_tasks(saida, cats), ensure_ascii=False, indent=1), encoding="utf-8")
    esquema_meta = {
        "$schema": "http://json-schema.org/draft-07/schema",
        "title": "Metadados de modelo da Raíz",
        "type": "object",
        "properties": {
            "team_name": {"type": "string"},
            "team_abbr": {"type": "string", "pattern": "^[a-zA-Z0-9_+]+$"},
            "model_name": {"type": "string"},
            "model_abbr": {"type": "string", "pattern": "^[a-zA-Z0-9_+]+$"},
            "designated_model": {"type": "boolean"},
            "methods": {"type": "string"},
        },
        "additionalProperties": True,
        "required": ["team_name", "team_abbr", "model_name", "model_abbr", "designated_model", "methods"],
    }
    (cfg / "model-metadata-schema.json").write_text(json.dumps(esquema_meta, ensure_ascii=False, indent=2), "utf-8")
    tipos = _tipo_alvo(todas)
    (pasta / "predevals-config.yml").write_text(
        yaml.safe_dump(_predevals(tipos), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (pasta / "site-config.yml").write_text(
        yaml.safe_dump({"hub": "bernardoemmel/raiz", "title": "Raíz: acerto das previsões"}, allow_unicode=True),
        encoding="utf-8",
    )
    rodadas = sorted(set(saida["reference_date"])) if len(saida) else []
    ptc = {
        "rounds_idx": 0,
        "reference_date_col_name": "reference_date",
        "target_date_col_name": "target_end_date",
        "horizon_col_name": "horizon",
        "initial_checked_models": sorted(por_modelo)[:3],
        "initial_xaxis_range": [rodadas[0], rodadas[-1]] if rodadas else None,
    }
    (pasta / "predtimechart-config.yml").write_text(yaml.safe_dump(ptc, allow_unicode=True), encoding="utf-8")
    return {
        "previsoes": len(prev),
        "linhas_model_output": len(todas),
        "modelos": len(por_modelo),
        "arquivos": arquivos,
        "gabaritos": len(oraculo),
        "pasta": str(pasta),
    }


def placar(engine: Engine, desde: dt.date | None = None) -> dict:
    """Painel de acerto: notas por modelo, versão e alvo, quem está na frente por alvo e o acerto da vigilância."""
    with engine.connect() as con:
        filtro, par = ("where data_corte >= :d", {"d": desde}) if desde else ("", {})
        linhas = [
            dict(r)
            for r in con.execute(text(f"select * from aprendizado.previsao_contra_gabarito {filtro}"), par).mappings()
        ]
    pl = AC.placar(linhas)
    out = {"previsoes": pl, "campeoes": AC.campeoes(pl), "vigilancia": []}
    try:
        from raiz.vigilancia.servico import Vigilancia

        out["vigilancia"] = Vigilancia().acerto()
    except Exception as ex:  # noqa: BLE001 (sem o estado da vigilância, o painel mostra o resto)
        out["vigilancia_erro"] = type(ex).__name__
    return out


# --------------------------------------------------------------------------- rotas do painel de acerto


def roteador(engine_de):
    """GET /acerto/placar (com token): o mesmo de `placar()`. ?desde=AAAA-MM-DD filtra as rodadas."""
    r = APIRouter(tags=["aprendizado"])

    @r.get("/acerto/placar")
    def get_placar(request: Request, desde: dt.date | None = None):
        return Response(json.dumps(placar(engine_de(request), desde), ensure_ascii=False, default=str),
                        media_type="application/json")  # fmt: skip

    return r


def roteador_publico():
    r = APIRouter(tags=["aprendizado"])

    @r.get("/painel/acerto", response_class=HTMLResponse)
    def pagina() -> HTMLResponse:
        return HTMLResponse(PAGINA)

    return r


PAGINA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Acerto das previsões da Raíz</title>
<style>body{font:16px/1.5 system-ui,sans-serif;margin:24px;color:#15231B;background:#FAFAF7;max-width:1200px}
h2{margin-top:28px;font-size:20px}table{border-collapse:collapse;width:100%}th,td{padding:6px 10px;
border-bottom:1px solid #E7EAE4;text-align:left}td.n{text-align:right;font-variant-numeric:tabular-nums}
input,button{font:inherit;padding:6px 10px}.nota{color:#555D56;font-size:14px}</style></head><body>
<h1>Acerto das previsões</h1><p id="msg">Informe o token da API para ver o acerto (só leitura).</p>
<form id="f"><input id="t" type="password" placeholder="token da API" autocomplete="off"> <button>Ver</button></form>
<div id="conteudo" hidden><h2>Quem está na frente</h2><table id="camp"><thead><tr><th>Modelo</th><th>Alvo</th>
<th>Versão na frente</th><th>Nota</th><th>Versões</th></tr></thead><tbody></tbody></table>
<h2>Por modelo, versão e alvo</h2><p class="nota">Faixa: WIS, erro da mediana e cobertura do P10 a P90 (devia ficar
perto de 80%). Chance: Brier e log score. Categoria: acerto. Número: erro absoluto. Nota menor é melhor.</p>
<table id="tab"><thead><tr><th>Modelo</th><th>Versão</th><th>Alvo</th><th>Previsões</th><th>Com gabarito</th>
<th>Notas</th></tr></thead><tbody></tbody></table><h2>Vigilância</h2><table id="vig"><thead><tr><th>Fonte</th>
<th>Estrato</th><th>Versão da regra</th><th>Marcados</th><th>Precisão</th><th>Brier</th></tr></thead><tbody></tbody>
</table></div>
<script>
let TOK="";const $=s=>document.querySelector(s);const f=v=>v==null?"":Number(v).toFixed(3);
function linhas(sel,itens,cols){const tb=$(sel+" tbody");tb.innerHTML="";for(const i of itens){
const tr=document.createElement("tr");for(const[v,cls]of cols(i)){const td=document.createElement("td");
td.textContent=v??"";if(cls)td.className=cls;tr.appendChild(td)}tb.appendChild(tr)}}
const NOTAS=["wis","ae_mediana","cobertura_80","brier","log_score","acerto","ae"];
async function ver(){const r=await fetch("../acerto/placar",{headers:{Authorization:"Bearer "+TOK}});
if(!r.ok){$("#msg").textContent="Não deu para ler ("+r.status+").";return}const d=await r.json();
linhas("#camp",d.campeoes,c=>[[c.modelo],[c.alvo],[c.versao],[c.metrica+" "+f(c.nota),"n"],[c.versoes_comparadas,"n"]]);
linhas("#tab",d.previsoes,p=>[[p.modelo],[p.modelo_versao],[p.alvo],[p.previsoes,"n"],[p.com_gabarito,"n"],
[NOTAS.filter(k=>p[k]!=null).map(k=>k+" "+f(p[k])).join("; ")]]);
linhas("#vig",d.vigilancia||[],v=>[[v.fonte],[v.estrato],[v.regra_versao],[v.marcados,"n"],[f(v.precisao),"n"],
[f(v.brier),"n"]]);$("#msg").textContent="Notas só das previsões que já têm gabarito.";$("#conteudo").hidden=false}
$("#f").onsubmit=e=>{e.preventDefault();TOK=$("#t").value;try{sessionStorage.setItem("raiz:token",TOK)}catch(_){}
ver()};try{const t=sessionStorage.getItem("raiz:token");if(t){TOK=t;ver()}}catch(_){}
</script></body></html>"""
