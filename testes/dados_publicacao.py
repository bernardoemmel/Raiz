"""Fixtures com todas as colunas do contrato de publicação, fontes opcionais nulas."""

import pandas as pd

from raiz.qualidade_dados import OBRIGATORIAS


def csv_contrato(tipo, valores):
    return pd.DataFrame([{**dict.fromkeys(OBRIGATORIAS[tipo]), **valores}]).to_csv(index=False).encode()
