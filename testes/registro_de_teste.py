"""Cartório e matrícula do imóvel usado nos testes de certidão.

A amostra pública não traz esses números: eles identificam o dono. Os testes que
conferem a leitura de exemplo recebem uma cópia temporária, só desse imóvel, com
os mesmos valores que o PDF simulado já usa (5178 e 5177).
"""

import shutil
from pathlib import Path

import pandas as pd

from testes.conftest import AMOSTRA

IMOVEL = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"
CNS = "06.842-9"
MATRICULAS = ("5178", "5177")


def preencher_registro_de_teste(pasta: Path) -> None:
    for arq in Path(pasta).glob("certidoes_*.csv"):
        df = pd.read_csv(arq, dtype=str)
        if "registro_cns" not in df.columns:
            df["registro_cns"] = ""
        if "registro_matricula" not in df.columns:
            df["registro_matricula"] = ""
        for i, idx in enumerate(df.index[df.cod_imovel == IMOVEL]):
            df.at[idx, "registro_cns"] = CNS
            df.at[idx, "registro_matricula"] = MATRICULAS[i] if i < len(MATRICULAS) else ""
        df.to_csv(arq, index=False)


def entrada_com_registro_de_teste(destino: Path) -> Path:
    destino = Path(destino)
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(AMOSTRA, destino)
    preencher_registro_de_teste(destino)
    return destino
