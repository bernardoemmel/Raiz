"""Triagem em lote para o desenvolvedor: lista de códigos do CAR -> ranking com nota e o motivo de cada nota.

A mesma função serve o Actions (CSV e PDF no arquivo privado), a API (POST /triagem/desenvolvedor) e a ferramenta do
MCP (raiz/triagem_desenvolvedor/mcp.py). Fora do escopo: certidão e contato com o dono.
Regra da nota: raiz/regras/padroes/triagem_desenvolvedor.yaml; fazenda pequena nunca é descartada; fazenda da lista que
não está nos dados fica no ranking como nao_encontrada.
"""

from __future__ import annotations

import datetime as dt

from raiz.triagem_desenvolvedor import nota as N

COLUNAS = [
    "posicao", "cod_imovel", "municipio", "uf", "faixa", "nota", "ha", "pequena", "restauracao_area_ha",
    "credito_p50_tco2_ha", "custo_credito_usd", "tir_pct", "caminho_terra", "risco_terra", "embargo_ha", "ti_uc",
    "desmatamento_recente_ha", "alerta_recente_ha", "status_sobreposicao", "projeto_id", "gleba_federal_pct", "motivo",
    "regra_versao",
    "gerado_em",
]  # fmt: skip


def triar(
    codigos: list[str], dados: dict[str, dict], *, hoje: dt.date | None = None, modo_gleba: str | None = None
) -> list[dict]:
    """dados: CAR -> colunas (raiz/triagem_desenvolvedor/dados.py). Devolve uma linha por código da lista, ordenada:
    recomendadas, com ressalvas, travadas, sem dados, não encontradas; dentro de cada grupo, a maior nota primeiro."""
    r = N.regra()
    hoje = (hoje or dt.date.today()).isoformat()
    linhas = []
    for c in codigos:
        d = dados.get(c)
        if d is None:
            x = {"nota": None, "faixa": "nao_encontrada", "motivo": "código não está nos dados processados",
                 "status_sobreposicao": None}  # fmt: skip
        else:
            x = N.avaliar(d, r, modo_gleba=modo_gleba)
            x["municipio"] = d.get("municipio") if isinstance(d.get("municipio"), str) else None
        x.update(cod_imovel=c, uf=c[:2], regra_versao=r["versao_completa"], gerado_em=hoje)
        linhas.append(x)
    ordem = {f: i for i, f in enumerate(N.FAIXAS)}
    linhas.sort(key=lambda x: (ordem[x["faixa"]], -(x["nota"] if x["nota"] is not None else -1), x["cod_imovel"]))
    for i, x in enumerate(linhas, start=1):
        x["posicao"] = i
    return [{k: x.get(k) for k in COLUNAS} for x in linhas]


def resumo(linhas: list[dict]) -> dict:
    out = {f: sum(1 for x in linhas if x["faixa"] == f) for f in N.FAIXAS}
    out["total"] = len(linhas)
    return out
