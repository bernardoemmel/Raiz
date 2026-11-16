"""Auditoria própria: dados abertos, sem executar código dos autores.

Executar: python analisar_ecologia.py
O script só calcula quantis descritivos da amostra; não ajusta curva ou prevê fazendas.
"""
from pathlib import Path
import csv
import hashlib
import json
import math
import random
from collections import Counter

ROOT = Path(__file__).resolve().parent
BOES = ROOT / "Boeschoten_etal_2026_GCB_reforestation.csv"
ROZ = ROOT / "rozendaal2019_CC0.csv"
GILES = ROOT / "giles2024_CC-BY4.csv"
IDADE_ALVOS = (3, 5, 10, 15)
JANELA = 2
N_MINIMO = 20  # política conservadora operacional; não garante validade preditiva
BOOTSTRAPS = 5000
SEMENTE = 20261112
HASH_BOES = "54ee5ffe92b95718498a21417bbd7ee5e10295b4d4feaa979d85565b5fb5333b"
HASH_ROZ = "ff060d7f969a1a25882b1f3ee526a4686ebf4e522fdc9bb0945c2763b7ac1201"
AMAZONIA = {
    "Eastern Pará 1", "Eastern Pará 2", "Eastern Pará 3",
    "Manaus (Cecropia pathway)", "Manaus (Vismia pathway)",
    "Middle Madeira River (anthropogenic soil)", "Middle Madeira River (oxisol)",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ler(path, encoding="utf-8", delimiter=","):
    with path.open(encoding=encoding, newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def q(values, prob):
    """Hyndman/Fan tipo 7, igual numpy/pandas linear. Não arredonda contagens cedo."""
    values = sorted(values)
    pos = (len(values) - 1) * prob
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def gravar(nome, objeto):
    (ROOT / nome).write_text(json.dumps(objeto, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def resumo(rows, idade, indicador, agrupado=False):
    elegiveis = [r for r in rows if idade-JANELA <= r["idade"] <= idade+JANELA]
    valores = [r["valor"] for r in elegiveis]
    grupos = sorted({r["sitio"] for r in elegiveis})
    n = len(valores)
    base = {
        "idade_alvo_anos": idade,
        "intervalo_idade_inclusivo_anos": [idade-JANELA, idade+JANELA],
        "idade_observada_min": min((r["idade"] for r in elegiveis), default=None),
        "idade_observada_max": max((r["idade"] for r in elegiveis), default=None),
        "n_parcelas": n, "n_sitios": len(grupos) if agrupado else None,
        "n_por_sitio": dict(Counter(r["sitio"] for r in elegiveis)) if agrupado else {},
        "linhas_fonte_1_based_com_cabecalho": [r["linha_csv"] for r in elegiveis],
        "indicador": indicador,
        "metodo": "quantis_empiricos_tipo7_amostra_em_janela_idade_mais_ou_menos_2",
        "status": "referencia_descritiva_regional" if n >= N_MINIMO else "pendente_amostra_insuficiente",
        "p10": q(valores,.1) if n >= N_MINIMO else None,
        "p50": q(valores,.5) if n >= N_MINIMO else None,
        "p90": q(valores,.9) if n >= N_MINIMO else None,
        "previsao_validada_em_fazenda": False,
        "densidade_arvores_ha": None,
        "riqueza_total_fazenda": None,
    }
    if n >= N_MINIMO:
        rng = random.Random(SEMENTE + idade)
        amostras = [[],[],[]]
        por_grupo = {g: [r["valor"] for r in elegiveis if r["sitio"] == g] for g in grupos}
        for _ in range(BOOTSTRAPS):
            if agrupado:
                escolhidos = rng.choices(grupos, k=len(grupos))
                sorteio = []
                for grupo in escolhidos:
                    x = por_grupo[grupo]
                    sorteio.extend(rng.choices(x, k=len(x)))
            else:
                sorteio = rng.choices(valores, k=n)
            for saida, prob in zip(amostras, (.1,.5,.9)):
                saida.append(q(sorteio, prob))
        base["ic95_amostral_bootstrap_quantis"] = {
            nome: [q(x,.025), q(x,.975)]
            for nome,x in zip(("p10","p50","p90"),amostras)
        }
        base["bootstrap"] = {
            "n": BOOTSTRAPS, "semente": SEMENTE + idade,
            "unidade": "sitio_depois_parcela" if agrupado else "parcela",
            "limite": "Não cobre viés de seleção, erro taxonômico/idade ou transferência para nova região/fazenda. Boeschoten não publica chave geográfica para reamostragem por região.",
        }
        if agrupado:
            sem_um_sitio = {
                grupo:[q([r["valor"] for r in elegiveis if r["sitio"] != grupo],p) for p in (.1,.5,.9)]
                for grupo in grupos
            }
            base["sensibilidade_remocao_um_sitio"] = sem_um_sitio
    return base


assert sha(BOES) == HASH_BOES
assert sha(ROZ) == HASH_ROZ
boes = ler(BOES)
roz = ler(ROZ, encoding="latin1")
assert len(boes) == 519
assert len({r["Plot_ID"] for r in boes}) == 519
conteudo_versao = Path(__file__).read_bytes()+BOES.read_bytes()+ROZ.read_bytes()
versao = "ecologia-referencia-2026c+" + hashlib.sha256(conteudo_versao).hexdigest()[:12]
saida = {
    "versao_modelo": versao,
    "rotulo": "estimativa regional, não medida na fazenda",
    "uso": "Referência descritiva de riqueza com unidade padronizada; não prognóstico validado.",
    "criterio_n_minimo": {"n": N_MINIMO, "natureza": "decisão operacional, não limiar inferencial universal"},
    "nao_somar_riqueza_entre_parcelas": True,
    "nao_multiplicar_riqueza_pela_area": True,
    "estratos": [],
}
for floresta in ("Rainforest", "Seasonally dry forest"):
    for metodo in ("Reg", "Rest"):
        rows = [
            {"linha_csv":i, "sitio":r["Plot_ID"], "idade":float(r["Age"]), "valor":float(r["Hill0"])}
            for i,r in enumerate(boes,2)
            if r["Forest_classification"] == floresta and r["Forest_type"] == metodo
            and r["Age"] not in ("NA", "") and r["Hill0"] not in ("NA", "")
        ]
        saida["estratos"].append({
            "fonte": "boeschoten2026", "bioma": "Mata Atlântica", "uf": "SP",
            "fisionomia": floresta, "metodo_restauracao": "regeneracao" if metodo == "Reg" else "plantio_biodiverso",
            "dap": {"operador": ">", "cm": 5}, "area_amostral_m2": 900,
            "taxa": "Hill0 fornecido pelos autores; não restringir a espécies nativas sem microdados",
            "n_parcelas_estrato_com_idade": len(rows),
            "n_parcelas_estrato_sem_idade": sum(r["Forest_classification"] == floresta and r["Forest_type"] == metodo and r["Age"] in ("NA", "") for r in boes),
            "anos": [resumo(rows,idade,"riqueza_taxonomica_por_900m2") for idade in IDADE_ALVOS],
        })
rows = [
    {"linha_csv":i, "sitio":r["Site"], "idade":float(r["Age"]), "valor":float(r["SPrich_abs"])}
    for i,r in enumerate(roz,2)
    if r["Country"] == "Brazil" and r["Site"] in AMAZONIA
]
saida["estratos"].append({
    "fonte": "rozendaal2019", "bioma": "Amazônia", "uf": ["PA","AM"],
    "fisionomia": "floresta_secundaria", "metodo_restauracao": "regeneracao",
    "dap": {"operador": ">=", "cm": 5}, "esforco_amostral_fustes": 25,
    "area_amostral_m2": None, "n_parcelas_total_estrato": len(rows),
    "taxa": "árvores, palmeiras e arbustos; riqueza rarefeita para25fustes no CSV CC0",
    "anos": [resumo(rows,idade,"riqueza_rarefeita_por_25_fustes",True) for idade in IDADE_ALVOS],
})
gravar("referencias_regionais.json",saida)
giles = ler(GILES, delimiter=";")
por_site = {}
for r in giles:
    idade = float(r["Age"]) if r["Age"] not in ("NA","") else None
    site = r["site"]
    por_site.setdefault(site,Counter())
    por_site[site]["sem_idade" if idade is None else "idade_120" if idade == 120 else "secundaria"] += 1
gravar("auditoria_giles.json",{
    "sha256": sha(GILES), "n_linhas": len(giles), "n_sites_csv":len(por_site),
    "totais":dict(sum(por_site.values(),Counter())), "por_sitio":por_site,
    "conclusao":"514 linhas não conciliam com448 secundárias publicadas apenas removendo80 idades120 e5 semidade. Não combinar protocolos sem mapa verificável.",
})
linhas = []
for e in saida["estratos"]:
    for a in e["anos"]:
        linhas.append({
            "versao_modelo":versao, "fonte":e["fonte"], "bioma":e["bioma"],
            "fisionomia":e["fisionomia"], "metodo":e["metodo_restauracao"],
            "idade_alvo":a["idade_alvo_anos"], "idade_min":a["intervalo_idade_inclusivo_anos"][0],
            "idade_max":a["intervalo_idade_inclusivo_anos"][1], "n":a["n_parcelas"],
            "indicador":a["indicador"], "p10":a["p10"], "p50":a["p50"], "p90":a["p90"],
            "status":a["status"],
        })
with (ROOT/"referencias_regionais.csv").open("w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(linhas[0]));w.writeheader();w.writerows(linhas)
print(json.dumps({"versao_modelo":versao,"faixas_com_suporte":sum(r["status"]=="referencia_descritiva_regional" for r in linhas)},ensure_ascii=False))
