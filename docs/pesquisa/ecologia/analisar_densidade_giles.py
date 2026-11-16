"""Referência regional de fustes; cálculo próprio, sem código de terceiros.

Executar com Python 3.11+. Não faz rede. Dados: Giles et al., Zenodo 13970371,
CC BY 4.0. Escopo: BR_Jakovac_Tefe, regeneração após agricultura itinerante.
"""

from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "giles2024_CC-BY4.csv"
EXPECTED_SHA = "977eb5df8e0b71854877103de7d22d9897981fffd2025d89b182d2801d8d88b0"
assert hashlib.sha256(DATA.read_bytes()).hexdigest() == EXPECTED_SHA
MODEL = "ecologia-fustes-tefe-2026a+" + hashlib.sha256(
    Path(__file__).read_bytes() + DATA.read_bytes()
).hexdigest()[:12]
SEED = 20261113
BOOTSTRAPS = 5000
Q = (0.1, 0.5, 0.9)


def quantile(values, p):
    values = sorted(values)
    pos = (len(values) - 1) * p
    lower = math.floor(pos)
    upper = math.ceil(pos)
    return values[lower] + (values[upper] - values[lower]) * (pos - lower)


def quantiles(values):
    return {f"p{int(p * 100)}": round(quantile(values, p), 4) for p in Q}


def density(rows):
    return [row["densidade_fustes_ha"] for row in rows]


source = list(csv.DictReader(DATA.open(encoding="utf-8"), delimiter=";"))
rows = []
for line, row in enumerate(source, start=2):
    if row["site"] != "BR_Jakovac_Tefe":
        continue
    area = float(row["area_plot_ha"])
    n = float(row["stem.dens_ha"]) * area
    assert area == 0.05 and abs(n - round(n)) < 1e-9
    rows.append({
        "linha_csv_original": line,
        "sitio_fonte": row["site"],
        "parcela_id": row["plot_ID"],
        "grupo_comunidade": row["plot_ID"].split("_")[0],
        "idade_anos": float(row["Age"]),
        "ano_inventario": int(row["year_sample"]),
        "area_parcela_ha": area,
        "densidade_fustes_ha": float(row["stem.dens_ha"]),
        "fustes_reconstruidos": round(n),
    })
assert len(rows) == 35
assert len({r["parcela_id"] for r in rows}) == 35
groups = defaultdict(list)
for row in rows:
    groups[row["grupo_comunidade"]].append(row)
assert {g: len(v) for g, v in groups.items()} == {"AG": 10, "NG": 11, "SF": 3, "SS": 5, "VS": 6}
assert sum(row["fustes_reconstruidos"] for row in rows) == 3262

bootstrap = {f"p{int(q * 100)}": [] for q in Q}
rng = random.Random(SEED)
group_ids = sorted(groups)
for _ in range(BOOTSTRAPS):
    sample = []
    for group in rng.choices(group_ids, k=len(group_ids)):
        sample.extend(rng.choices(groups[group], k=len(groups[group])))
    for key, value in quantiles(density(sample)).items():
        bootstrap[key].append(value)
ci = {key: [round(quantile(values, 0.025), 4), round(quantile(values, 0.975), 4)]
      for key, values in bootstrap.items()}

left_out = []
holdout = []
for group in group_ids:
    train = [r for r in rows if r["grupo_comunidade"] != group]
    ranges = quantiles(density(train))
    left_out.append({"comunidade_retirada": group, "n_treino": len(train), **ranges})
    for row in groups[group]:
        measured = row["densidade_fustes_ha"]
        holdout.append({
            "modelo_versao": MODEL,
            "parcela_id": row["parcela_id"],
            "grupo_fora_do_treino": group,
            "observado_fustes_ha": measured,
            "previsao_regional": ranges,
            "erro_absoluto_mediana": abs(measured - ranges["p50"]),
            "dentro_p10_p90": ranges["p10"] <= measured <= ranges["p90"],
        })

ages = []
for target in (3, 5, 10, 15):
    support = [row for row in rows if abs(row["idade_anos"] - target) <= 2]
    observed = [r["idade_anos"] for r in support]
    supported = bool(observed) and min(observed) <= target <= max(observed) and len(support) >= 20
    ages.append({
        "idade_alvo_anos": target,
        "janela_anos": [target - 2, target + 2],
        "n_parcelas": len(support),
        "n_grupos_comunidade": len({r["grupo_comunidade"] for r in support}),
        "idades_observadas": [min(observed), max(observed)] if observed else None,
        "status": "referencia_regional_descritiva" if supported else "pendente_sem_suporte",
        "densidade_fustes_ha": quantiles(density(support)) if supported else None,
        "motivo": None if supported else (
            "Idade-alvo fora do intervalo observado; não extrapolar a partir da janela."
            if observed else "Não há parcela nesta janela de idade."
        ),
    })

result = {
    "modelo_versao": MODEL,
    "rotulo": "estimativa regional, não medida na fazenda",
    "tipo": "referencia_regional_descritiva",
    "bioma": "Amazônia",
    "recorte": "Terra firme em Tefé e Alvarães, AM; agricultura itinerante de mandioca",
    "metodo": "regeneracao_natural",
    "aplicabilidade": "Referência contextual local; não calibrada para qualquer fazenda do bioma ou do Pará.",
    "protocolo": {
        "dap_cm": 5,
        "operador_dap_original": ">",
        "operador_sintese_giles": ">=",
        "ambiguidade_limiar": "Não há dados individuais para reconciliar observações exatamente a 5 cm.",
        "area_parcela_ha": 0.05,
        "unidade_amostral": "Uma parcela de 10 × 50 m por capoeira",
        "objeto": "fustes de árvores, arbustos e palmeiras",
        "campo": "densidade_fustes_ha",
        "conversao_para_arvores_distintas": None,
        "protocolo_url": "https://doi.org/10.1111/1365-2745.12298",
        "protocolo_espelho_institucional": "https://wiki.dpi.inpe.br/lib/exe/fetch.php?media=ser301:wiki_pessoal_mikha:jakovac_et_al-2015-journal_of_ecology.pdf",
    },
    "fonte": {
        "autores": "Giles et al. (2024), dados de Jakovac et al. (2015)",
        "doi": "10.5281/zenodo.13970371",
        "url": "https://zenodo.org/api/records/13970371/files/data_plot.csv/content",
        "licenca": "CC-BY-4.0",
        "sha256": EXPECTED_SHA,
        "filtro": "site == BR_Jakovac_Tefe; todas as 35 linhas disponíveis, sem seleção por resultado",
        "n_csv_completo": len(source),
        "n_reconstruido_fustes": 3262,
        "diferenca_coorte": "Estudo original tem 38 capoeiras; CSV público tem 35, incluindo somente 3 das 6 de São Francisco. Motivo da ausência não documentado; referência condicionada às disponíveis.",
    },
    "quantis": "Empíricos, interpolação linear tipo 7; não são intervalos de confiança ou modelo de crescimento.",
    "suporte_por_idade": ages,
    "incerteza_quantile_5_anos_ic95": ci,
    "bootstrap": {"n": BOOTSTRAPS, "semente": SEED, "unidade_primaria": "5 grupos/comunidades inferidos do prefixo de parcela e conferidos com o protocolo", "metodo": "Reamostrar comunidades, depois parcelas dentro da comunidade; preservar n original de cada comunidade sorteada."},
    "sensibilidade_remover_comunidade": left_out,
    "validacao_interna": {
        "metodo": "Deixar uma comunidade inteira fora, prever pela distribuição das outras quatro",
        "n_comunidades": 5,
        "n_parcelas": len(holdout),
        "cobertura_p10_p90": round(sum(h["dentro_p10_p90"] for h in holdout) / len(holdout), 6),
        "mae_mediana_fustes_ha": round(sum(h["erro_absoluto_mediana"] for h in holdout) / len(holdout), 4),
        "limite": "Diagnóstico de transferência entre comunidades deste estudo; não valida extrapolação para outro sítio, bioma, método ou idade.",
    },
    "observacoes": rows,
    "comparacoes_holdout": holdout,
}
(ROOT / "densidade_giles_tefe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
with (ROOT / "giles_tefe_observacoes.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print(json.dumps({key: result[key] for key in ("modelo_versao", "suporte_por_idade", "incerteza_quantile_5_anos_ic95", "validacao_interna")}, ensure_ascii=False, indent=2))
