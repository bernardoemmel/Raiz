"""Destinos do gado em UA: capacidade no período seco e fluxo sem dupla alocação."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import networkx as nx
import pulp

EMBRAPA = "https://cloud.cnpgc.embrapa.br/sac/2016/06/15/como-se-calcula-a-capacidade-de-suporte-de-uma-pastagem/"
LAND = "https://doi.org/10.3390/land14050963"
PROVAS = ("contrato", "rastreabilidade", "laudo_mes_seco", "sem_desmatamento")


def _prova_valida(receptor, chave):
    prova = receptor.get("evidencias", {}).get(chave, {})
    return (
        receptor.get(chave + "_confirmado") is True
        and isinstance(prova, dict)
        and bool(re.fullmatch(r"[0-9a-f]{64}", str(prova.get("sha256", ""))))
        and bool(prova.get("revisao_id"))
    )


def mitigacao_comprovada(linha: dict) -> bool:
    """Somente plano desta versão, íntegro e com documentos conferidos.

    O hash protege contra alteração acidental; não substitui a conferência
    humana dos documentos referenciados nem certifica o crédito.
    """
    plano = linha.get("vazamento_plano_json")
    if not isinstance(plano, str):
        return False
    try:
        p = json.loads(plano)
        sha = p.pop("sha256")
        integro = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest() == sha
        origem = str(linha.get("cod_imovel"))
        return bool(
            integro
            and p["modelo_versao"] == versao()
            and p["vazamento_pode_zerar"]
            and origem in p["origens_ua"]
            and p["origens_ua"][origem] > 0
            and all(not r["pendencias"] for r in p["receptores"])
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def versao() -> str:
    return "gado-ua-2026a+" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def _positivo(x, nome, *, zero=True):
    if isinstance(x, bool) or not math.isfinite(x) or x < 0 or (not zero and x == 0):
        raise ValueError(f"{nome} inválido")
    return float(x)


def capacidade_seca(materia_seca_kg_ha: float, dias: int, *, oferta_peso_vivo_dia: float = 0.11) -> dict:
    """Oferta total inclui perdas/seleção; 11% não é ingestão de 2,5–3%.

    O chamador fornece MS produzida/disponível na janela seca informada. Não
    divide produção anual por 12 nem confunde biomassa de floresta com forragem.
    """
    ms = _positivo(materia_seca_kg_ha, "matéria seca")
    _positivo(dias, "dias", zero=False)
    if int(dias) != dias or not 0.10 <= oferta_peso_vivo_dia <= 0.12:
        raise ValueError("dias inteiros e oferta Embrapa entre 10% e 12% do peso vivo")
    denominador = 450 * oferta_peso_vivo_dia * dias
    return {
        "ua_ha": ms / denominador,
        "ms_kg_ha": ms,
        "dias": dias,
        "peso_ua_kg": 450,
        "oferta_peso_vivo_dia": oferta_peso_vivo_dia,
        "denominador_kg_ms_ua_periodo": denominador,
        "fonte": EMBRAPA,
        "modelo_versao": versao(),
        "limite": "Exige disponibilidade no mês seco e conferência técnica local.",
    }


def converter_cabecas(cabecas: float, peso_medio_kg: float) -> float:
    return _positivo(cabecas, "cabeças") * _positivo(peso_medio_kg, "peso", zero=False) / 450


def planejar(origens: list[dict], receptores: list[dict], rotas: list[dict], *, raio_km: float = 150) -> dict:
    """Maximiza UA atendida, minimiza receptores (PuLP) e custo (NetworkX).

    Cada receptor declara área, UA presentes e capacidade seca em UA/ha. Mesmo
    destino suficiente não é prova de mitigação: contrato, rastreio, laudo e
    ausência de desmatamento são necessários antes de zerar vazamento.
    """
    _positivo(raio_km, "raio", zero=False)
    o = {x["id"]: x for x in origens}
    r = {x["id"]: x for x in receptores}
    if len(o) != len(origens) or len(r) != len(receptores) or set(o) & set(r):
        raise ValueError("origens/receptores devem ter identificadores únicos e distintos")
    escala = 1000  # milésimos de UA; capacidade arredondada para baixo.
    demanda = {k: math.ceil(_positivo(v["ua"], "UA deslocada") * escala - 1e-9) for k, v in o.items()}
    capacidade = {}
    for k, v in r.items():
        area = _positivo(v["pasto_ha"], "pasto", zero=False)
        antes = _positivo(v["ua_antes"], "UA antes")
        suporte = _positivo(v["capacidade_seca_ua_ha"], "capacidade seca")
        capacidade[k] = max(0, math.floor((area * suporte - antes) * escala + 1e-9))
    arcos = {}
    for arco in rotas:
        a, b = arco["origem"], arco["receptor"]
        if a not in o or b not in r or (a, b) in arcos:
            raise ValueError("rota duplicada ou com origem/receptor desconhecido")
        km = _positivo(arco["distancia_km"], "distância")
        custo = _positivo(arco["custo_por_ua"], "custo por UA")
        if km <= raio_km:
            arcos[a, b] = (km, custo)
    grafo = nx.DiGraph()
    for k, d in demanda.items():
        grafo.add_edge("__fonte", ("o", k), capacity=d, weight=0)
    for k, c in capacidade.items():
        grafo.add_edge(("r", k), "__destino", capacity=c, weight=0)
    for (a, b), (_, custo) in arcos.items():
        grafo.add_edge(("o", a), ("r", b), capacity=demanda[a], weight=round(custo * 1000))
    alvo = nx.maximum_flow_value(grafo, "__fonte", "__destino") if o and r else 0
    escolhidos = []
    fluxo = {}
    if alvo:
        problema = pulp.LpProblem("menor_conjunto_receptores", pulp.LpMinimize)
        usa = {k: pulp.LpVariable(f"receptor_{i}", cat="Binary") for i, k in enumerate(sorted(r))}
        q = {ab: pulp.LpVariable(f"rota_{i}", lowBound=0) for i, ab in enumerate(sorted(arcos))}
        problema += pulp.lpSum(usa.values())
        for a, d in demanda.items():
            problema += pulp.lpSum(v for (i, _), v in q.items() if i == a) <= d
        for b, c in capacidade.items():
            problema += pulp.lpSum(v for (_, j), v in q.items() if j == b) <= c * usa[b]
        problema += pulp.lpSum(q.values()) == alvo
        solver = pulp.PULP_CBC_CMD(msg=False, timeLimit=30, threads=1)
        problema.solve(solver)
        if pulp.LpStatus[problema.status] != "Optimal" or problema.sol_status != pulp.LpSolutionOptimal:
            raise RuntimeError("seleção de receptores não provou ótimo no limite de tempo")
        minimo = round(sum(v.value() for v in usa.values()))
        problema += pulp.lpSum(usa.values()) == minimo
        problema.setObjective(pulp.lpSum(v * arcos[ab][1] for ab, v in q.items()))
        problema.solve(solver)
        if pulp.LpStatus[problema.status] != "Optimal" or problema.sol_status != pulp.LpSolutionOptimal:
            raise RuntimeError("seleção de receptores por custo não provou ótimo")
        escolhidos = sorted(k for k, v in usa.items() if v.value() > 0.5)
        grafo.remove_nodes_from([("r", k) for k in r if k not in escolhidos])
        fluxo = nx.max_flow_min_cost(grafo, "__fonte", "__destino")
    deslocamentos = []
    for (a, b), (km, custo) in arcos.items():
        ua = fluxo.get(("o", a), {}).get(("r", b), 0) / escala
        if ua:
            deslocamentos.append({"origem": a, "receptor": b, "ua": ua, "distancia_km": km, "custo": ua * custo})
    destinos = []
    for k in escolhidos:
        recebido = sum(a["ua"] for a in deslocamentos if a["receptor"] == k)
        destinos.append(
            {
                "id": k,
                "ua_antes": r[k]["ua_antes"],
                "ua_recebidas": recebido,
                "ua_depois": r[k]["ua_antes"] + recebido,
                "lotacao_antes_ua_ha": r[k]["ua_antes"] / r[k]["pasto_ha"],
                "lotacao_depois_ua_ha": (r[k]["ua_antes"] + recebido) / r[k]["pasto_ha"],
                "capacidade_seca_ua_ha": r[k]["capacidade_seca_ua_ha"],
                "pendencias": [p for p in PROVAS if not _prova_valida(r[k], p)],
                "evidencias": r[k].get("evidencias", {}),
            }
        )
    total = sum(demanda.values()) / escala
    atendido = sum(a["ua"] for a in deslocamentos)
    resultado = {
        "modelo_versao": versao(),
        "origens_ua": {k: v / escala for k, v in demanda.items()},
        "ua_deslocadas": total,
        "ua_atendidas": atendido,
        "ua_sem_destino": max(0, total - atendido),
        "receptores": destinos,
        "rotas": deslocamentos,
        "custo_total": sum(a["custo"] for a in deslocamentos),
        "raio_km": raio_km,
        "vazamento_pode_zerar": bool(
            total > 0 and atendido >= total - 0.001 and all(not d["pendencias"] for d in destinos)
        ),
        "precisao_ua": 1 / escala,
        "criterio": "máxima UA, menor número de receptores, menor custo",
    }
    resultado["sha256"] = hashlib.sha256(json.dumps(resultado, sort_keys=True).encode()).hexdigest()
    return resultado


def sensibilidade_regional(area_restaurada_ha: float) -> dict:
    area = _positivo(area_restaurada_ha, "área restaurada")
    return {
        "area_deslocamento_ha": 0.12 * area,
        "fracao_area": 0.12,
        "raio_km": 150,
        "janela_anos": 2,
        "desconto_creditos": None,
        "fonte": LAND,
        "modelo_versao": versao(),
        "limite": "Sensibilidade regional de área; requer estoque e contrafactual para estimar emissões.",
    }
