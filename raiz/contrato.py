"""Contrato com o motor (docs/colunas.md): ler cada saída pelo NOME da coluna e tolerar colunas novas.

- Colunas conhecidas viram colunas tipadas no banco (nome em minúsculas: pct_RL -> pct_rl).
- Coluna que o contrato não conhece vai para `atributos` (JSON) da mesma linha e aparece em `colunas_novas`.
- Coluna conhecida que não converte para o tipo esperado também vai para `atributos`, com aviso (não derruba a carga).
- Coluna conhecida que falta fica nula e aparece em `colunas_faltando`.
- Colunas com cara de dado pessoal são tiradas na entrada (defesa extra: o motor já não grava CPF, CNPJ nem nome).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from raiz.privacidade import remover_colunas_pessoais

TEXTO, NUM, INT, BOOL, DATA_HORA = "texto", "num", "int", "bool", "data_hora"

# saida/<UF>/imoveis_<mun>.csv
IMOVEIS: dict[str, str] = {
    "cod_imovel": TEXTO,
    "id": TEXTO,
    "status_imovel": TEXTO,
    "dat_criacao": DATA_HORA,
    "data_atualizacao": DATA_HORA,
    "area": NUM,
    "condicao": TEXTO,
    "uf": TEXTO,
    "municipio": TEXTO,
    "cod_municipio_ibge": INT,
    "m_fiscal": NUM,
    "tipo_imovel": TEXTO,
    "ha": NUM,
    "desm_pos2008_ha": NUM,
    "desm_pos2016_ha": NUM,
    "desm_pos2020_ha": NUM,
    "desm_total_ha": NUM,
    "nao_floresta_ha": NUM,
    "floresta_rem_ha": NUM,
    "embargo_ha": NUM,
    "ti_ha": NUM,
    "uc_ha": NUM,
    "sigef_ha": NUM,
    "matricula_ha": NUM,
    "assentamento_ha": NUM,
    "f_matricula": NUM,
    "projeto_carbono_ha": NUM,
    "alerta_ha": NUM,
    "alerta_pos2020_ha": NUM,
    "alerta_ultimo_ano": NUM,
    "app_desmatada_ha": NUM,
    "app_escadinha_ha": NUM,
    "app_recompor_ha": NUM,
    "bioma": TEXTO,
    "pct_RL": NUM,
    "pct_RL_alem": NUM,
    "deficit_RL_ha": NUM,
    "deficit_RL_alem_ha": NUM,
    "deficit_RL80_ha": NUM,
    "deficit_RL50_ha": NUM,
    "alem_RL_ha": NUM,
    "problema": BOOL,
    "frente": TEXTO,
    "cota_reserva": BOOL,
    "redd_excedente_ha": NUM,
    "frigorifico_remocao_ha": NUM,
    "compensacao_restauravel_ha": NUM,
    "eudr_ok": BOOL,
    "credito_rural_ok": BOOL,
    "compra_arrendamento": BOOL,
    "pasto_ha": NUM,
    "secundaria_ha": NUM,
    "pasto_ate1km_ha": NUM,
    "carbono_ha": NUM,
    "regiao_carbono": TEXTO,
    "taxa_tco2_ha_ano": NUM,
    "carbono_tco2_ano": NUM,
    "cacau_aptidao": TEXTO,
    "carbono_solo_ha": NUM,
    "rebanho_cabecas": NUM,
    "psa_elegivel": BOOL,
    "biodiversidade_score": NUM,
}

# saida/<UF>/filtros_<mun>.csv
FILTROS: dict[str, str] = {
    "cod_imovel": TEXTO,
    "quilombo_ha": NUM,
    "ti_funai_ha": NUM,
    "ti_fase": TEXTO,
    "uc_protecao_integral_ha": NUM,
    "uc_uso_sustentavel_ha": NUM,
    "uc_apa_ha": NUM,
    "filtro_territorial": TEXTO,
}

# saida/<UF>/resumo_<UF>.csv (as colunas frente_<nome> mudam com as frentes e ficam em atributos)
RESUMO: dict[str, str] = {
    "cod_ibge": INT,
    "municipio": TEXTO,
    "imoveis": NUM,
    "sem_problema": NUM,
    "def_RL": NUM,
    "aptas_carbono": NUM,
    "ha_carbono": NUM,
    "tco2_ano_aptas": NUM,
    "aptas_com_matricula": NUM,
    "ha_carbono_matricula": NUM,
    "cota_reserva": NUM,
    "redd_imoveis": NUM,
    "redd_ha": NUM,
    "app_imoveis": NUM,
    "app_ha": NUM,
    "frigorifico_imoveis": NUM,
    "frigorifico_ha": NUM,
    "compensacao_ha": NUM,
    "eudr_ok": NUM,
    "credito_rural_ok": NUM,
    "compra_arrendamento": NUM,
    "alerta_pos2020_imoveis": NUM,
}

# saida/<UF>/certidoes_<mun>.csv (várias linhas por imóvel)
CERTIDOES: dict[str, str] = {
    "cod_imovel": TEXTO,
    "registro_cns": TEXTO,
    "registro_matricula": TEXTO,
    "ha_sobre_car": NUM,
    "parcelas": NUM,
}

# arquivos sem contrato tipado ainda: tudo vai para atributos, uma linha por imóvel
# (extras = histórico fixo exportado uma vez do Earth Engine; extras_direto = TMF e causa da perda, sem Earth Engine;
#  flag = meta FLAG pela GHG LSR, calculada pelo produto em raiz/flag.py; ficha = colunas do design v1 do front,
#  raiz/imovel_dados.py; desenvolvedor = valor para quem restaura com crédito de carbono, raiz/restauracao.py;
#  terra = caminho da terra e risco, raiz/terra.py)
COMPLEMENTOS = (
    "extras",
    "extras_direto",
    "direto",
    "ajustes",
    "alertas",
    "flag",
    "ficha",
    "desenvolvedor",
    "terra",
    "rebanho",
)

CONTRATOS: dict[str, dict[str, str]] = {
    "imoveis": IMOVEIS,
    "filtros": FILTROS,
    "resumo": RESUMO,
    "certidoes": CERTIDOES,
}
CONTRATOS.update({k: {"cod_imovel": TEXTO} for k in COMPLEMENTOS})


def coluna_banco(nome: str) -> str:
    return nome.lower()


def _bool(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, bool | np.bool_):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"true", "1", "1.0", "sim", "s", "t"}:
        return True
    if s in {"false", "0", "0.0", "nao", "não", "n", "f"}:
        return False
    if s in {"", "nan", "none"}:
        return None
    raise ValueError(f"não é booleano: {v!r}")


def converter(s: pd.Series, tipo: str) -> pd.Series:
    """Converte para o tipo do contrato; levanta ValueError se algum valor não converter."""
    if tipo == TEXTO:
        return s.astype(object).where(s.notna(), None).map(lambda v: None if v is None else str(v))
    if tipo == NUM:
        return pd.to_numeric(s, errors="raise").astype(float)
    if tipo == INT:
        x = pd.to_numeric(s, errors="raise")
        if (x.dropna() % 1 != 0).any():
            raise ValueError("valor não inteiro")
        return x.astype("Int64")
    if tipo == BOOL:
        return s.map(_bool).astype(object)
    if tipo == DATA_HORA:
        return pd.to_datetime(s, errors="raise", utc=True, format="ISO8601")
    raise ValueError(f"tipo desconhecido no contrato: {tipo}")


def _json_valor(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, np.generic):
        v = v.item()
        return None if isinstance(v, float) and math.isnan(v) else v
    if isinstance(v, pd.Timestamp | datetime | date):
        return None if pd.isna(v) else v.isoformat()
    return v


@dataclass
class Leitura:
    tipo: str
    arquivo: str
    tipadas: pd.DataFrame  # colunas do contrato (nomes do banco), já convertidas
    atributos: list[dict]  # uma entrada por linha: colunas fora do contrato ou que não converteram
    colunas_novas: list[str] = field(default_factory=list)
    colunas_faltando: list[str] = field(default_factory=list)
    colunas_pessoais_removidas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.tipadas)


def tipo_do_arquivo(arquivo: str | Path) -> str | None:
    nome = Path(arquivo).name
    # o tipo mais longo primeiro: extras_direto_<mun>.csv não é extras_<mun>.csv
    for tipo in sorted(CONTRATOS, key=len, reverse=True):
        if nome.startswith(tipo + "_") and nome.endswith(".csv"):
            return tipo
    return None


def ler(arquivo: str | Path, tipo: str | None = None) -> Leitura:
    arquivo = Path(arquivo)
    tipo = tipo or tipo_do_arquivo(arquivo)
    if tipo not in CONTRATOS:
        raise ValueError(f"arquivo sem contrato: {arquivo.name}")
    contrato = CONTRATOS[tipo]
    df = pd.read_csv(arquivo, low_memory=False, dtype=str, keep_default_na=True)
    df, pessoais = remover_colunas_pessoais(df)
    avisos = [f"coluna pessoal removida na entrada: {c}" for c in pessoais]

    tipadas = pd.DataFrame(index=df.index)
    extras_cols = [c for c in df.columns if c not in contrato]
    nao_converteram = []
    for nome, tipo_col in contrato.items():
        if nome not in df:
            tipadas[coluna_banco(nome)] = pd.Series([None] * len(df), index=df.index, dtype=object)
            continue
        try:
            tipadas[coluna_banco(nome)] = converter(df[nome], tipo_col)
        except (ValueError, TypeError) as ex:
            nao_converteram.append(nome)
            avisos.append(f"coluna {nome} não converteu para {tipo_col} ({str(ex)[:80]}); guardada em atributos")
            tipadas[coluna_banco(nome)] = pd.Series([None] * len(df), index=df.index, dtype=object)
    chave = next(iter(contrato))
    if chave in nao_converteram or chave not in df:
        raise ValueError(f"{arquivo.name}: falta a chave {chave}")

    cols_attr = extras_cols + nao_converteram
    if cols_attr:
        bruto = df[cols_attr]
        # números chegam como texto (dtype=str); devolve número quando a coluna inteira é numérica
        conv = {}
        for c in cols_attr:
            n = pd.to_numeric(bruto[c], errors="coerce")
            conv[c] = n if n.notna().sum() == bruto[c].notna().sum() else bruto[c]
        atributos = [
            {c: _json_valor(v) for c, v in linha.items()}
            for linha in pd.DataFrame(conv, index=df.index).astype(object).to_dict("records")
        ]
    else:
        atributos = [{} for _ in range(len(df))]

    return Leitura(
        tipo=tipo,
        arquivo=str(arquivo),
        tipadas=tipadas,
        atributos=atributos,
        colunas_novas=_novas(tipo, extras_cols),
        colunas_faltando=[c for c in contrato if c not in df],
        colunas_pessoais_removidas=pessoais,
        avisos=avisos,
    )


def _novas(tipo: str, extras_cols: list[str]) -> list[str]:
    if tipo in COMPLEMENTOS:  # ainda sem contrato tipado: nada é "novo"
        return []
    if tipo == "resumo":  # frente_<nome> varia com as frentes por desenho
        return [c for c in extras_cols if not c.startswith("frente_")]
    return extras_cols


def atributos_json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, allow_nan=False, default=str)


# --- mapbiomas_<mun>.csv (motor/raiz_mapbiomas.py): colunas mb_*, todas opcionais ----------------------------------
# O ano vem no nome (mb_floresta_2025_ha) e muda a cada coleção: a Raíz guarda em formato longo
# (cod_imovel, indicador, ano, valor), e coluna mb_* nova ou de outro ano entra sem migração.
MB_CONHECIDOS = {
    "floresta_ha",
    "pasto_ha",
    "agricultura_ha",
    "silvicultura_ha",
    "classe_principal",
    "supressao_primaria_ha",
    "supressao_secundaria_ha",
    "recuperacao_secundaria_ha",
    "veg_secundaria_ha",
    "fogo_ha",
    "fogo_mes_principal",
    "pasto_idade_anos_media",
    "pasto_vigor_principal",
}


def indicador_mb(coluna: str) -> tuple[str, int | None] | None:
    """mb_floresta_2025_ha -> ('floresta_ha', 2025); mb_pasto_idade_anos_media -> ('pasto_idade_anos_media', None)."""
    if not coluna.startswith("mb_"):
        return None
    m = re.match(r"^mb_(.+?)_((?:19|20)\d{2})(_.+)?$", coluna)
    if m:
        return m.group(1) + (m.group(3) or ""), int(m.group(2))
    return coluna[3:], None


def coluna_mb(indicador: str, ano: int | None) -> str:
    """Volta do formato longo ao nome do CSV: ('floresta_ha', 2025) -> mb_floresta_2025_ha;
    ('classe_principal', 2025) -> mb_classe_principal_2025; ('pasto_idade_anos_media', None) -> o mesmo com mb_."""
    if ano is None:
        return f"mb_{indicador}"
    if indicador.endswith("_ha"):
        return f"mb_{indicador[:-3]}_{ano}_ha"
    return f"mb_{indicador}_{ano}"


@dataclass
class LeituraMapBiomas:
    arquivo: str
    longa: pd.DataFrame  # cod_imovel, indicador, ano, valor_num, valor_texto
    indicadores_novos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)


def ler_mapbiomas(arquivo: str | Path) -> LeituraMapBiomas:
    df = pd.read_csv(arquivo, dtype=str, low_memory=False)
    if "cod_imovel" not in df:
        raise ValueError(f"{Path(arquivo).name}: falta a chave cod_imovel")
    df, pessoais = remover_colunas_pessoais(df)
    avisos = [f"coluna pessoal removida na entrada: {c}" for c in pessoais]
    partes, novos = [], []
    for c in df.columns:
        if c == "cod_imovel":
            continue
        ind = indicador_mb(c)
        if ind is None:
            avisos.append(f"coluna sem prefixo mb_ ignorada: {c}")
            continue
        nome, ano = ind
        if nome not in MB_CONHECIDOS:
            novos.append(c)
        num = pd.to_numeric(df[c], errors="coerce")
        numerica = num.notna().sum() == df[c].notna().sum()
        partes.append(
            pd.DataFrame(
                {
                    "cod_imovel": df["cod_imovel"],
                    "indicador": nome,
                    "ano": ano,
                    "valor_num": num if numerica else None,
                    "valor_texto": None if numerica else df[c],
                }
            )
        )
    longa = (
        pd.concat(partes, ignore_index=True)
        if partes
        else pd.DataFrame(columns=["cod_imovel", "indicador", "ano", "valor_num", "valor_texto"])
    )
    longa = longa[longa.valor_num.notna() | longa.valor_texto.notna()].reset_index(drop=True)
    return LeituraMapBiomas(str(arquivo), longa, novos, avisos)


# --- extras_direto_<mun>.csv (motor/raiz_extras_direto.py, sem Earth Engine): colunas opcionais ----------------------
# JRC TMF 2025 (classe dominante e % por imóvel) e causa dominante da perda de floresta (WRI/Google DeepMind v1.2).
EXTRAS_DIRETO_CONHECIDAS = ("tmf_classe", "tmf_floresta_pct", "tmf_regeneracao_pct", "causa_perda")
TMF_CLASSES = {
    1: "floresta intacta",
    2: "floresta degradada",
    3: "desmatada",
    4: "em regeneração",
    5: "água",
    6: "outro uso",
}
CAUSAS_PERDA = {
    1: "agricultura permanente",
    2: "commodities",
    3: "agricultura itinerante",
    4: "extração de madeira",
    5: "incêndio",
    6: "assentamento e infraestrutura",
    7: "perturbação natural",
}
SEM_PERDA = 255


def ler_extras_direto(arquivo: str | Path) -> pd.DataFrame:
    """Lê pelo nome as colunas conhecidas que existirem (todas opcionais), como número, e acrescenta o texto da classe
    do TMF e da causa da perda. causa_perda 255 (sem perda) vira vazio. Coluna desconhecida passa como veio."""
    df = pd.read_csv(arquivo, dtype=str, low_memory=False)
    if "cod_imovel" not in df:
        raise ValueError(f"{Path(arquivo).name}: falta a chave cod_imovel")
    df, _ = remover_colunas_pessoais(df)
    for c in EXTRAS_DIRETO_CONHECIDAS:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "causa_perda" in df:
        df["causa_perda"] = df["causa_perda"].where(df["causa_perda"] != SEM_PERDA)
        df["causa_perda_texto"] = df["causa_perda"].map(CAUSAS_PERDA)
    if "tmf_classe" in df:
        df["tmf_classe_texto"] = df["tmf_classe"].map(TMF_CLASSES)
    return df
