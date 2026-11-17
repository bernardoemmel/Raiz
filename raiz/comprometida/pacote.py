"""Conferência da camada "já comprometida" contra a lista pública CAR × REDD+ do Pará (Zenodo 23929936, CC BY 4.0).

A lista (`para_redd_car_sobreposicoes.csv` do pacote de limites de 16/11/2026: projeto, CAR, ha de sobreposição) vem de
uma fonte independente do nosso cruzamento geométrico. Aqui ela não vira dado da camada: serve de prova. Para cada CAR
listado que existe em `comprometida_<mun>.csv`, vê se o nosso status concorda; o CAR listado que sai `livre` ou
`nao_verificado` é lacuna (limite que falta na coleta, geometria do CAR diferente ou município não processado).
Só código do CAR, identificador público do projeto e hectares: nada de nome de projeto, CNPJ ou pessoa.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

LIMIAR_HA = 5.0  # a lista tem lascas de digitalização; abaixo disso não conta como lacuna
STATUS_COM_SOBREPOSICAO = ("ja_comprometida", "risco_sobreposicao")


def ler_lista(arquivo: str | Path) -> pd.DataFrame:
    """CAR, projeto (VCS<id>) e ha de sobreposição somados por CAR e projeto. Colunas lidas pelo nome."""
    df = pd.read_csv(arquivo, dtype={"Project_ID": str, "CAR_cod_im": str})
    faltam = {"Project_ID", "CAR_cod_im", "sobreposicao_ha"} - set(df.columns)
    if faltam:
        raise ValueError(f"lista CAR x REDD+ sem as colunas {sorted(faltam)}")
    df = df.rename(columns={"CAR_cod_im": "cod_imovel"})
    df["projeto_id"] = "VCS" + df.Project_ID.str.replace(r"\D", "", regex=True)
    df["sobreposicao_ha"] = pd.to_numeric(df.sobreposicao_ha, errors="coerce")
    return df.groupby(["cod_imovel", "projeto_id"], as_index=False).sobreposicao_ha.sum()


def conferir(lista: str | Path, saida: str | Path) -> tuple[dict, pd.DataFrame]:
    """(resumo, lacunas). saida: pasta do motor com <UF>/comprometida_<mun>.csv. Município sem arquivo fica como
    `sem_arquivo` (não é lacuna da coleta: é município ainda não processado)."""
    saida = Path(saida)
    lis = ler_lista(lista)
    por_car = lis.sort_values("sobreposicao_ha", ascending=False).drop_duplicates("cod_imovel")
    nossos: dict[str, str] = {}
    for f in sorted(saida.glob("*/comprometida_*.csv")) + sorted(saida.glob("comprometida_*.csv")):
        d = pd.read_csv(f, usecols=["cod_imovel", "status_sobreposicao"], dtype=str)
        nossos.update(zip(d.cod_imovel, d.status_sobreposicao, strict=True))
    por_car = por_car.assign(
        status_raiz=por_car.cod_imovel.map(lambda c: nossos.get(c, "sem_arquivo")),
        relevante=por_car.sobreposicao_ha >= LIMIAR_HA,
    )
    rel = por_car[por_car.relevante]
    lacunas = rel[rel.status_raiz.isin(["livre", "nao_verificado"])].copy()
    resumo = {
        "car_na_lista": int(len(por_car)),
        "car_relevantes": int(len(rel)),
        "com_arquivo": int((rel.status_raiz != "sem_arquivo").sum()),
        "concordam": int(rel.status_raiz.isin(STATUS_COM_SOBREPOSICAO).sum()),
        "lacunas": int(len(lacunas)),
        "sem_arquivo": int((rel.status_raiz == "sem_arquivo").sum()),
        "por_status": {k: int(v) for k, v in rel.status_raiz.value_counts().items()},
        "projetos_nas_lacunas": sorted(lacunas.projeto_id.unique().tolist()),
    }
    return resumo, lacunas[["cod_imovel", "projeto_id", "sobreposicao_ha", "status_raiz"]].reset_index(drop=True)
