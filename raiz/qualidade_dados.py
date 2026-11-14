"""Portão de publicação: contratos Pandera, privacidade e anomalias municipais.

Não corrige nem descarta linhas: qualquer violação impede o lote inteiro de sair.
Os erros nunca incluem os valores das células. Colunas numéricas novas são aceitas;
texto novo precisa entrar no contrato para não publicar identificação por acidente.
"""

from __future__ import annotations

import copy
import csv
import gzip
import io
import json
import math
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import numpy as np
import pandas as pd
import pandera.pandas as pa

from raiz.pacotes_seguros import abrir_tar_seguro
from raiz.privacidade import colunas_pessoais, mascarar


class ErroQualidade(ValueError):
    """Violação segura para os logs: regra, nunca o valor pessoal encontrado."""


# Contrato do produtor, docs/colunas.md. Fonte ausente é nulo, nunca coluna ausente.
CONTRATO_VERSAO = "colunas-2026-11-12"
_UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
OBRIGATORIAS = {
    "imoveis": (
        "cod_imovel",
        "id",
        "status_imovel",
        "dat_criacao",
        "data_atualizacao",
        "area",
        "condicao",
        "uf",
        "municipio",
        "cod_municipio_ibge",
        "m_fiscal",
        "tipo_imovel",
        "ha",
        "desm_pos2008_ha",
        "desm_pos2020_ha",
        "desm_pos2016_ha",
        "embargo_ha",
        "ti_ha",
        "uc_ha",
        "desm_total_ha",
        "nao_floresta_ha",
        "sigef_ha",
        "matricula_ha",
        "assentamento_ha",
        "projeto_carbono_ha",
        "alerta_ha",
        "alerta_pos2020_ha",
        "alerta_ultimo_ano",
        "app_desmatada_ha",
        "floresta_rem_ha",
        "deficit_RL80_ha",
        "deficit_RL50_ha",
        "bioma",
        "pct_RL",
        "pct_RL_alem",
        "deficit_RL_ha",
        "deficit_RL_alem_ha",
        "problema",
        "alem_RL_ha",
        "f_matricula",
        "frente",
        "cota_reserva",
        "redd_excedente_ha",
        "frigorifico_remocao_ha",
        "compensacao_restauravel_ha",
        "eudr_ok",
        "credito_rural_ok",
        "compra_arrendamento",
        "cacau_aptidao",
        "carbono_solo_ha",
        "rebanho_cabecas",
        "psa_elegivel",
        "biodiversidade_score",
        "pasto_ha",
        "secundaria_ha",
        "pasto_ate1km_ha",
        "carbono_ha",
        "regiao_carbono",
        "taxa_tco2_ha_ano",
        "carbono_tco2_ano",
        "app_escadinha_ha",
        "app_recompor_ha",
    ),
    "direto": ("cod_imovel", "sec_area_ha", "sec_idade_media", "sec_nova_ha", "gpw_altura_m", "gpw_ugpp"),
    "extras": (
        "cod_imovel",
        "yb_idade_media",
        "yb_idade_max",
        "yb_perdas_media",
        "yb_perdas_max",
        "fogo_anos_media",
        "fogo_anos_max",
        "pasto_vigor_media",
        "pasto_vigor_max",
        "pasto_idade_anos_max",
        "persistencia_nota",
    ),
    "extras_direto": ("cod_imovel", "tmf_classe", "tmf_floresta_pct", "tmf_regeneracao_pct", "causa_perda"),
    "filtros": (
        "cod_imovel",
        "quilombo_ha",
        "ti_funai_ha",
        "ti_fase",
        "uc_protecao_integral_ha",
        "uc_uso_sustentavel_ha",
        "uc_apa_ha",
        "filtro_territorial",
    ),
    "mapbiomas": (
        "cod_imovel",
        "mb_floresta_2025_ha",
        "mb_pasto_2025_ha",
        "mb_agricultura_2025_ha",
        "mb_silvicultura_2025_ha",
        "mb_classe_principal_2025",
        "mb_supressao_primaria_2025_ha",
        "mb_supressao_secundaria_2025_ha",
        "mb_recuperacao_secundaria_2025_ha",
        "mb_veg_secundaria_2025_ha",
        "mb_fogo_2025_ha",
        "mb_fogo_mes_principal_2025",
        "mb_pasto_idade_anos_media",
        "mb_pasto_vigor_principal",
    ),
    "certidoes": ("cod_imovel", "registro_cns", "registro_matricula", "ha_sobre_car", "parcelas"),
    "flag": (
        "cod_imovel",
        "flag_silvipastoril_ha",
        "flag_silvipastoril_degradado_ha",
        "flag_cacau_ha",
        "flag_cacau_viavel",
        "flag_plano_silvipastoril_ha",
        "flag_plano_cacau_ha",
        "flag_tco2_ano",
        "flag_tco2_ano_min",
        "flag_tco2_ano_max",
        "credito_alem_rl_ha",
        "credito_tco2_ano",
        "rl_restauracao_ha",
        "app_restauracao_ha",
        "capoeira_ha",
        "flag_regra_versao",
    ),
    "ficha": (
        "cod_imovel",
        "porte",
        "etapa_funil",
        "motivo_saida",
        "motivo_saida_texto",
        "carbono_tco2_ano_p10",
        "carbono_tco2_ano_p50",
        "carbono_tco2_ano_p90",
        "receita_ano_p10",
        "receita_ano_p50",
        "receita_ano_p90",
        "receita_moeda",
        "faixas_versao",
        "faixas_regra",
        "comp_mata_em_pe_ha",
        "comp_pasto_ha",
        "comp_para_restaurar_ha",
        "comp_lavoura_ha",
        "comp_agua_ha",
        "comp_outros_ha",
        "comp_sem_dado_ha",
        "pode_voltar_ha",
        "cidade_proxima",
        "cidade_proxima_km",
        "cidade_proxima_direcao",
        "estrada_acesso",
        "estrada_acesso_km",
    ),
    "terra": (
        "cod_imovel",
        "caminho_terra",
        "caminho_terra_rotulo",
        "caminho_terra_situacao",
        "caminho_terra_motivo",
        "caminho_terra_aviso",
        "risco_terra",
        "risco_terra_motivo",
        "profloresta_fase1",
        "terra_concessao",
        "terra_concessao_situacao",
        "terra_concessao_data",
        "terra_concessao_link",
        "terra_fonte",
        "terra_regra_versao",
        "terra_sigef_registrada_ha",
        "terra_sigef_titulacao_ha",
        "terra_sigef_posse_ha",
        "terra_sigef_assentamento_ha",
        "terra_sigef_assentamento_titulado_ha",
        "terra_publica_ha",
        "terra_uc_publica_ha",
        "terra_tradicional_ha",
    ),
    "desenvolvedor": (
        "cod_imovel",
        "pasto_d0_ha",
        "pasto_d1_ha",
        "pasto_d2_ha",
        "pasto_d3_ha",
        "declividade_media_pct",
        "chuva_mm_ano",
        "solo_cec_cmolc_kg",
        "estrada_acesso_km",
        "cidade_proxima_km",
        "restauracao_area_ha",
        "modo_restauracao",
        "modo_restauracao_pontos",
        "modo_restauracao_regra",
        "restauracao_regeneracao_assistida_ha",
        "restauracao_semeadura_direta_ha",
        "restauracao_plantio_total_ha",
        "distancia_fonte",
        "metodo_escolhido",
        "metodo_regra_preco_equilibrio_usd",
        "metodo_plantio_preco_equilibrio_usd",
        "metodo_regeneracao_e_plantio_preco_equilibrio_usd",
        "custo_restauracao_ha_p10",
        "custo_restauracao_ha_p50",
        "custo_restauracao_ha_p90",
        "custo_implantacao_ha_p50",
        "custo_fator_ajuste",
        "captura_modelo",
        "captura_tco2_ha_ano_p10",
        "captura_tco2_ha_ano_p50",
        "captura_tco2_ha_ano_p90",
        "captura_total_tco2_ha_p50",
        "captura_fator_ajuste",
        "desconto_linha_base",
        "desconto_linha_base_pct",
        "linha_base_medida_pct",
        "linha_base_regenera_pct",
        "linha_base_fonte",
        "vazamento_pct",
        "reserva_risco_pct",
        "reserva_risco_fonte",
        "fogo_risco_ano_pct",
        "derrubada_risco_ano_pct",
        "perda_natural_40a_pct",
        "taxa_supressao_secundaria_municipio",
        "incerteza_pct",
        "fator_liquido",
        "vazamento_motivo",
        "vazamento_mitigacao_imovel",
        "cabecas_deslocadas",
        "rebanho_fonte",
        "credito_liquido_tco2_ha_ano",
        "credito_liquido_tco2_ha_ano_p10",
        "credito_liquido_tco2_ha_ano_p90",
        "credito_liquido_tco2_ano",
        "credito_liquido_tco2_ha_contrato_p10",
        "credito_liquido_tco2_ha_contrato_p50",
        "credito_liquido_tco2_ha_contrato_p90",
        "credito_liquido_tco2_contrato",
        "credito_liquido_tco2_ha_horizonte",
        "volume_contratado_tco2_ha",
        "marco_7_chance_pct",
        "marco_12_chance_pct",
        "marco_17_chance_pct",
        "marco_22_chance_pct",
        "marco_25_chance_pct",
        "marcos_todos_chance_pct",
        "multa_esperada_rs_ha",
        "rescisao_chance_pct",
        "vpl_rs_ha_p10",
        "vpl_rs_ha_p50",
        "vpl_rs_ha_p90",
        "tir_projeto_pct_p10",
        "tir_projeto_pct_p50",
        "tir_projeto_pct_p90",
        "tir_alavancada_pct_p10",
        "tir_alavancada_pct_p50",
        "tir_alavancada_pct_p90",
        "pico_capital_proprio_rs_ha_p10",
        "pico_capital_proprio_rs_ha_p50",
        "pico_capital_proprio_rs_ha_p90",
        "divida_fracao",
        "divida_rs_ha",
        "divida_limitada_icsd",
        "pagamento_dono",
        "dono_rs_ha_ano",
        "arrendamento_referencia_rs_ha_ano",
        "pecuaria_receita_bruta_rs_ha_ano",
        "pecuaria_lotacao_cab_ha",
        "arrendamento_referencia_fonte",
        "tir_projeto_pct_arrendamento",
        "tir_projeto_pct_duas_fases",
        "custo_credito_usd",
        "preco_equilibrio_usd_t",
        "valor_desenvolvedor_rs",
        "restauracao_faltou",
        "restauracao_cenario",
        "restauracao_versao",
        "linha_base_taxa_d0",
        "linha_base_taxa_d1",
        "linha_base_taxa_d2",
        "linha_base_taxa_d3",
        "grupo_id",
        "grupo_imoveis",
        "grupo_ha",
        "grupo_credito_tco2_ano",
        "grupo_creditos_prazo",
        "grupo_fecha_contrato",
        "grupo_ha_para_contrato",
        "restauracao_area_situacao",
        "preco_minimo_tir_12_projeto_usd_t",
        "preco_minimo_tir_12_alavancada_usd_t",
        "preco_minimo_tir_15_projeto_usd_t",
        "preco_minimo_tir_15_alavancada_usd_t",
    ),
    "rebanho": (
        "cod_imovel",
        "rebanho_cab_p10",
        "rebanho_cab_p50",
        "rebanho_cab_p90",
        "rebanho_lotacao_cab_ha",
        "rebanho_pasto_ha",
        "rebanho_produtividade",
        "rebanho_produtividade_fonte",
        "rebanho_fonte",
        "rebanho_municipio_ppm",
        "rebanho_municipio_lotacao_cab_ha",
        "rebanho_censo_sobre_ppm_2017",
        "metano_tco2e_ano_p10",
        "metano_tco2e_ano_p50",
        "metano_tco2e_ano_p90",
        "rebanho_versao",
    ),
    "serie_uso": ("cod_imovel", "ano", "mata_pct", "pasto_pct", "lavoura_pct", "agua_pct"),
    "regularizacao": (
        "cod_imovel",
        "regularizacao_regra_versao",
        "regularizacao_classe",
        "regularizacao_classe_rotulo",
        "regularizacao_orgao",
        "regularizacao_proximo_passo",
        "regularizacao_pendencias",
        "regularizacao_requisitos_ok",
        "regularizacao_requisitos_falta",
        "regularizacao_requisitos_conferir",
        "ocupacao_ate_2008_ha",
        "ocupacao_ate_2008_pct",
        "regularizacao_gratuita",
        "regularizacao_usucapiao_especial",
        "regularizacao_usucapiao_10anos",
        "regularizacao_chance_12m",
        "regularizacao_prazo_meses_p10",
        "regularizacao_prazo_meses_p50",
        "regularizacao_prazo_meses_p90",
    ),
    "achados": (
        "registro",
        "cod_imovel",
        "fase",
        "regra",
        "campo",
        "valor",
        "situacao",
        "gravidade",
        "mensagem",
        "fonte",
        "base",
        "regra_versao",
    ),
    "titulo": (
        "cod_imovel",
        "titulo_nota",
        "titulo_decisao",
        "titulo_decisao_texto",
        "titulo_bandeiras",
        "titulo_condicoes",
        "titulo_reprova",
        "titulo_confirmar",
        "titulo_nota_versao",
        "titulo_triagem",
        "titulo_triagem_motivos",
        "titulo_triagem_pedir",
        "titulo_triagem_chance_problema",
        "titulo_triagem_versao",
        "titulo_versao",
    ),
    "matricula": (
        "cod_imovel",
        "matricula_conferida",
        "matricula_situacao",
        "matriculas_total",
        "matriculas_lidas",
        "matriculas_conferidas",
        "matricula_area_ha",
        "matricula_onus_ativos",
        "matricula_onus_graves",
        "matricula_quebra_cadeia",
        "matricula_precisa_confirmar",
        "matricula_motivo",
        "matricula_lido_em",
        "matricula_modelo",
        "matricula_leitor_versao",
    ),
    "matricula_conferencia": (
        "cod_imovel",
        "registro_cns",
        "registro_matricula",
        "situacao",
        "precisa_confirmar",
        "motivo",
        "area_matricula_ha",
        "ha_sobre_car",
        "onus_ativos",
        "onus_graves",
        "quebra_cadeia",
        "n_transmissoes",
        "matricula_destino",
        "leitura_id",
        "lido_em",
        "modelo",
        "leitor_versao",
        "regras_versao",
        "motivos_json",
    ),
    "cadeia": (
        "cod_imovel",
        "registro_cns",
        "registro_matricula",
        "leitura_hash",
        "leitura_id",
        "lido_em",
        "modelo",
        "leitor_versao",
        "regras_versao",
        "matricula_situacao",
        "conferencia",
        "origem",
        "origem_referencia",
        "origem_matricula",
        "data_abertura",
        "area_matricula_ha",
        "matricula_destino",
        "georreferenciado",
        "n_transmissoes",
        "quebras",
        "onus_graves",
        "proprietarios_json",
        "ordem",
        "ato_numero",
        "ato_tipo",
        "natureza",
        "afeta",
        "data",
        "fracao_pct",
        "pagina",
        "transmissao",
        "anterior_numero",
        "cancelado_por",
        "quebra",
        "quebra_motivo",
        "resumo",
        "transmitentes_json",
        "adquirentes_json",
    ),
    "jurisdicional": (
        "cod_imovel",
        "jurisdicional_situacao",
        "jurisdicional_programa",
        "jurisdicional_sobreposicao_ha",
        "jurisdicional_fonte",
        "jurisdicional_evidencia",
        "jurisdicional_exclusao_em",
        "creditos_inicio_em",
    ),
    "resumo": (
        "cod_ibge",
        "municipio",
        "imoveis",
        "sem_problema",
        "def_RL",
        "aptas_carbono",
        "ha_carbono",
        "tco2_ano_aptas",
        "aptas_com_matricula",
        "ha_carbono_matricula",
        "cota_reserva",
        "redd_imoveis",
        "redd_ha",
        "app_imoveis",
        "app_ha",
        "frigorifico_imoveis",
        "frigorifico_ha",
        "compensacao_ha",
        "eudr_ok",
        "credito_rural_ok",
        "compra_arrendamento",
        "alerta_pos2020_imoveis",
        "frente_regularizar_antes",
        "frente_carbono",
        "frente_silvipastoril",
        "frente_desbloqueio",
        "frente_carbono_revisar_desm10anos",
        "frente_assentamento_agrupado",
        "frente_carbono_so_plantio",
        "frente_fora_TI",
        "frente_ja_tem_projeto",
    ),
    "sem_imoveis": ("cod_ibge", "municipio", "verificado_em"),
    "alertas": ("alerta_id", "alvo_tipo", "alvo_id", "alvo_ha", "area_sobreposta_ha"),
    "ibama_espelho": ("SEQ_TAD", "hash", "ativo", "cancelado", "desembargado"),
    "geo": ("cod_imovel", "geometry"),
    "camadas": ("cod_imovel", "camada", "ha", "geometry"),
}
TEXTOS = set(
    """
cod_imovel id status_imovel dat_criacao data_atualizacao condicao uf municipio tipo_imovel bioma frente
regiao_carbono ti_fase filtro_territorial registro_cns registro_matricula flag_regra_versao porte etapa_funil
motivo_saida motivo_saida_texto receita_moeda faixas_versao faixas_regra cidade_proxima cidade_proxima_direcao
estrada_acesso camada colecao rebanho_produtividade_fonte rebanho_fonte rebanho_versao modo_restauracao
modo_restauracao_regra distancia_fonte captura_modelo linha_base_fonte reserva_risco_fonte vazamento_motivo
vazamento_mitigacao_imovel arrendamento_referencia_fonte pagamento_dono metodo_escolhido restauracao_faltou
restauracao_cenario restauracao_versao restauracao_area_situacao grupo_id caminho_terra caminho_terra_rotulo
caminho_terra_situacao caminho_terra_motivo caminho_terra_aviso risco_terra risco_terra_motivo terra_concessao
terra_concessao_situacao terra_concessao_data terra_concessao_link terra_fonte terra_regra_versao
regularizacao_regra_versao regularizacao_classe regularizacao_classe_rotulo regularizacao_orgao
regularizacao_proximo_passo regularizacao_pendencias regularizacao_requisitos_ok regularizacao_requisitos_falta
regularizacao_requisitos_conferir fase regra valor gravidade fonte registro confirmado_em autor_regra evidencia
texto observacao achado_id data versao campo mensagem base titulo_decisao titulo_decisao_texto
titulo_bandeiras titulo_condicoes
titulo_nota_versao titulo_triagem titulo_triagem_motivos titulo_triagem_pedir titulo_triagem_versao titulo_versao
matricula_situacao matricula_motivo matricula_lido_em matricula_modelo matricula_leitor_versao situacao motivo
matricula_destino leitura_id lido_em modelo leitor_versao regras_versao motivos_json leitura_hash conferencia
origem origem_referencia origem_matricula data_abertura proprietarios_json ato_numero ato_tipo natureza afeta
anterior_numero cancelado_por quebra_motivo resumo transmitentes_json adquirentes_json jurisdicional_situacao
jurisdicional_programa jurisdicional_fonte jurisdicional_evidencia jurisdicional_exclusao_em creditos_inicio_em
clpi_situacao clpi_evidencia reparticao_evidencia verificado_em alerta_id chave classe tipo alvo_tipo alvo_id
publicado_em visto_em data_evento papel estrato confianca regra_versao link atributos geometria classes_ha
hash SEQ_TAD
""".split()
)
LIVRES = re.compile(r"motivo|texto|resumo|observacao|erro|nota$|evidencia|atributos|_json$")
PESSOAL = re.compile(
    r"(^|_)(proprietario|titular|contato|contact|owner|full_name|embargado|dono_nome|segredo|senha|token|password)($|_)",
    re.I,
)
CONTATO = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|(?:\+55\s*)?\(\d{2}\)\s*\d{4,5}[- ]\d{4}")
SEGREDO = re.compile(r"(?i)(?:bearer\s+[\w.-]{12,}|(?:token|api_key|secret|password|senha)\s*[=:]\s*[^\s\"',}]+)")
# TIR é uma taxa de retorno (pode ser negativa, inclusive −100); declividade é razão de distâncias.
NAO_PERCENTUAL = re.compile(r"^tir_|declividade")
# São áreas de outro objeto/agregado, ou valores por hectare, não uma parcela do CAR.
NAO_AREA_CAR = re.compile(
    r"^grupo_|^area_matricula_ha$|^matricula_area_ha$|^area_ocorrencia_ha$|^area_projeto_ha$|"
    r"^custo_|(?:_rs|_usd|_tco2|_cab|_custo|_credito|_taxa)_ha$"
)
INTENSIVAS = {
    "taxa_tco2_ha_ano",
    "credito_liquido_tco2_ha_ano",
    "custo_restauracao_ha_p50",
    "rebanho_lotacao_cab_ha",
    "captura_tco2_ha_ano_p50",
    "gpw_altura_m",
    "gpw_ugpp",
}


def _falhar(regra: str) -> None:
    raise ErroQualidade(f"publicação bloqueada: {regra}; valores omitidos") from None


@lru_cache(maxsize=20000)
def _texto(texto: str, livre: bool = False) -> None:
    texto = unquote(texto)
    if mascarar(texto) != texto or CONTATO.search(texto) or SEGREDO.search(texto):
        _falhar("dado pessoal ou segredo")
    if livre and texto:
        from raiz.logs_seguros import sanitizar_log

        if sanitizar_log(texto) != texto:
            _falhar("texto livre não aprovado pela privacidade")


def _normalizar_lugar(nome: str) -> str:
    return " ".join(
        "".join(c for c in unicodedata.normalize("NFKD", nome) if not unicodedata.combining(c)).casefold().split()
    )


@lru_cache(maxsize=1)
def _municipios() -> dict[str, str]:
    with (Path(__file__).parent / "executor" / "municipios.csv").open(encoding="utf-8") as f:
        return {r["codigo_ibge"]: _normalizar_lugar(r["nome"]) for r in csv.DictReader(f)}


def _carregar_json(dados):
    def pares(itens):
        resultado = {}
        for chave, valor in itens:
            if chave in resultado:
                _falhar("chave JSON duplicada")
            resultado[chave] = valor
        return resultado

    return json.loads(dados, object_pairs_hook=pares)


def validar_json(dado, chave: str = "") -> None:
    """Inspeciona estrutura inteira, inclusive strings que carregam JSON de modelos."""
    if isinstance(dado, dict):
        for k, v in dado.items():
            k = str(k)
            if colunas_pessoais([k]) or PESSOAL.search(k):
                _falhar("chave proibida no JSON")
            _texto(k)
            validar_json(v, k)
    elif isinstance(dado, list | tuple):
        for item in dado:
            validar_json(item, chave)
    elif isinstance(dado, str):
        if dado.lstrip().startswith(("{", "[")):
            try:
                interno = _carregar_json(dado)
            except ErroQualidade:
                raise
            except (ValueError, TypeError):
                pass
            else:
                validar_json(interno, chave)
                return
        tecnico = bool(
            re.fullmatch(
                r"(?:[a-fA-F0-9]{8,64}|[A-Z]{2}-\d{7}-[A-Fa-f0-9]{32}|"
                r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.+-]+Z?)?)",
                dado,
            )
        )
        if chave == "chave" and re.fullmatch(
            r"(?:N20|N21|SuomiNPP|S-NPP|1|2)\|\d{4}-\d{2}-\d{2}\|\d{4}(?:\|-?\d+(?:\.\d+)?\|-?\d+(?:\.\d+)?)?", dado
        ):
            tecnico = True
        if "versao" in chave and re.fullmatch(r"[a-z][a-z0-9_.+:-]*[0-9][a-z0-9_.+:-]*", dado):
            tecnico = True
        if chave == "municipio":
            normalizado = _normalizar_lugar(dado)
            if normalizado not in _municipios().values() and dado not in _municipios():
                _falhar("município fora do cadastro IBGE")
            tecnico = True
        _texto(dado, bool(LIVRES.search(chave)) or not tecnico)
    elif isinstance(dado, int | float) and not isinstance(dado, bool):
        if not math.isfinite(dado):
            _falhar("JSON com número não finito")
        if float(dado).is_integer():
            _texto(str(int(dado)))
    elif isinstance(dado, bytes | bytearray):
        _falhar("texto binário fora do contrato")


def _tipo(nome: str) -> str:
    if re.fullmatch(r"alertas_\d{4}-\d{2}\.parquet", nome):
        return "alertas"
    if nome == "ibama_espelho.parquet":
        return "ibama_espelho"
    m = re.fullmatch(r"([a-z_]+)_(?:\d{7}|[A-Z]{2})\.(csv|parquet|pmtiles)", nome)
    if not m or m[1] not in OBRIGATORIAS:
        _falhar("arquivo sem contrato público")
    return m[1]


def _area(c: str) -> bool:
    c = re.sub(r"_p(?:10|50|90)$", "", c)
    return (c == "ha" or c.endswith("_ha") or c == "ha_sobre_car") and not NAO_AREA_CAR.search(c)


def validar_tabela(df: pd.DataFrame, tipo: str, areas: pd.Series | None = None) -> None:
    """Pandera valida o contrato; nulos de fontes opcionais não viram zeros."""
    if tipo == "alertas":
        from raiz.vigilancia.cruzamento import COLUNAS_ALERTA

        if set(df) != set(COLUNAS_ALERTA) or not df["alvo_tipo"].eq("imovel").all():
            _falhar("alerta privado ou coluna fora do contrato")
        if (df["area_sobreposta_ha"] > df["alvo_ha"] + 1e-6).any():
            _falhar("área de alerta maior que CAR")
        for c in ("fracao_alvo", "fracao_ocorrencia"):
            if not df[c].dropna().between(0, 1).all():
                _falhar("fração do alerta fora de zero a um")
    if tipo == "ibama_espelho" and set(df) != set(OBRIGATORIAS[tipo]):
        _falhar("espelho do Ibama fora do contrato")
    if df.columns.duplicated().any():
        _falhar("colunas duplicadas")
    if colunas_pessoais(df.columns) or any(PESSOAL.search(str(c)) for c in df):
        _falhar("coluna proibida")
    dominios = {
        "uf": _UFS,
        "status_imovel": {"AT", "PE", "SU", "CA"},
        "tipo_imovel": {"IRU", "AST", "PCT"},
        "filtro_territorial": {"bloqueio", "atencao", "ok"},
    }
    for c, permitidos in dominios.items():
        if c in df and not df[c].dropna().isin(permitidos).all():
            _falhar("valor fora do domínio de " + c)
    for c in ("dat_criacao", "data_atualizacao", "verificado_em"):
        if c in df and pd.to_datetime(df[c].dropna(), errors="coerce", format="mixed", utc=True).isna().any():
            _falhar("data inválida")
    if "municipio" in df and "cod_municipio_ibge" in df:
        for nome, codigo in zip(df["municipio"], df["cod_municipio_ibge"], strict=True):
            if pd.notna(nome) and pd.notna(codigo):
                esperado = _municipios().get(str(int(codigo)))
                if esperado != _normalizar_lugar(str(nome)):
                    _falhar("nome e código municipal divergentes")
    obrigatorias = OBRIGATORIAS[tipo]
    colunas = {c: pa.Column(nullable=c not in {"cod_imovel", "ha", "cod_ibge"}) for c in obrigatorias}
    for c in df:
        _texto(str(c))
        if c in {"geometry", "geometria"}:
            continue
        s = df[c].dropna()
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            if not pd.api.types.is_bool_dtype(s) and len(s) and not np.isfinite(s.astype(float)).all():
                _falhar("número não finito")
        elif c not in TEXTOS:
            # Colunas novas são permitidas se de fato forem numéricas, não texto disfarçado.
            try:
                numeros = pd.to_numeric(s, errors="raise")
                if len(numeros) and not np.isfinite(numeros.astype(float)).all():
                    _falhar("número não finito")
            except (ValueError, TypeError):
                _falhar("coluna textual sem contrato")
        if _area(c) or re.search(r"(^pct_|_pct(?:_|$))", c) and not NAO_PERCENTUAL.search(c):
            checks = [pa.Check.ge(0)]
            if not _area(c):
                checks.append(pa.Check.le(100))
            colunas[c] = pa.Column(float, checks=checks, nullable=c not in {"ha"}, coerce=True)
        for valor in s.unique() if not s.map(lambda v: isinstance(v, dict | list)).any() else s:
            if isinstance(valor, dict | list):
                validar_json(valor, c)
            elif isinstance(valor, str | int | float | bytes | bytearray | np.integer | np.floating):
                validar_json(valor.item() if isinstance(valor, np.generic) else valor, c)
    try:
        pa.DataFrameSchema(colunas, strict=False).validate(df, lazy=True)
    except (pa.errors.SchemaError, pa.errors.SchemaErrors):
        _falhar("colunas obrigatórias, tipos ou faixas inválidos")
    for c in df:
        if not re.search(r"_p(?:10|50|90)$", c):
            continue
        if c in {"captura_total_tco2_ha_p50", "custo_implantacao_ha_p50"}:
            continue  # docs/colunas declara somente o caminho central dessas duas métricas
        base = c[:-4]
        centro = base + "_p50" if base + "_p50" in df else base
        alto = base + "_p90"
        baixo = base + "_p10"
        if baixo not in df or centro not in df or alto not in df:
            _falhar("faixa P10/P50/P90 incompleta")
        faixa = df[[baixo, centro, alto]].apply(pd.to_numeric, errors="coerce")
        completa = faixa.notna().all(axis=1)
        if (faixa.notna().any(axis=1) != completa).any():
            _falhar("faixa P10/P50/P90 parcialmente nula")
        f = faixa[completa]
        if ((f.iloc[:, 0] > f.iloc[:, 1]) | (f.iloc[:, 1] > f.iloc[:, 2])).any():
            _falhar("P10 ≤ P50 ≤ P90")
    if "cod_imovel" in df and tipo not in {
        "certidoes",
        "serie_uso",
        "achados",
        "matricula_conferencia",
        "cadeia",
        "camadas",
    }:
        if df["cod_imovel"].duplicated().any():
            _falhar("CAR duplicado na tabela de imóvel")
    if "cod_imovel" in df:
        componentes = [c for c in df if _area(c) and c != "ha"]
        if tipo == "imoveis":
            limite = pd.to_numeric(df["ha"], errors="raise")
        elif areas is not None:
            limite = df["cod_imovel"].astype(str).map(areas)
            if limite.isna().any():
                _falhar("CAR sem referência de área")
            if tipo == "camadas":
                componentes.append("ha")
        elif componentes:
            _falhar("área do CAR ausente para comparação")
        else:
            return
        # Somente tolerância de serialização em hectares, nunca uma margem percentual.
        for c in componentes:
            if (pd.to_numeric(df[c], errors="raise") > limite + 1e-6).any():
                _falhar("área de componente maior que área do CAR (" + c + ")")


def _saltos(tabelas: dict[str, tuple[str, pd.DataFrame]]) -> None:
    grupos: dict[tuple[str, str], list[float]] = defaultdict(list)
    for nome, (tipo, df) in tabelas.items():
        if not re.search(r"_\d{7}\.", nome):
            continue
        for c in INTENSIVAS.intersection(df.columns):
            valores = pd.to_numeric(df[c], errors="coerce").dropna()
            if len(valores):
                grupos[tipo, c].append(float(valores.median()))
    for valores in grupos.values():
        if len(valores) < 5:
            continue
        mediana = float(np.median(valores))
        mad = float(np.median(np.abs(np.asarray(valores) - mediana)))
        # Controle de erro de unidade/escala, não inferência de equivalência científica entre municípios.
        if any(
            (v > 10 * mediana or v < mediana / 10) and abs(v - mediana) > max(8 * 1.4826 * mad, 1e-6) for v in valores
        ):
            _falhar("salto municipal de escala em indicador intensivo")


def _metadados_parquet(dado, campos: set[str], chave="") -> None:
    """Metadados técnicos têm domínios próprios; nenhum texto de usuário é dispensado por ser metadado."""
    if isinstance(dado, dict):
        if dado.get("type") == "GeographicCRS" or dado.get("type") == "ProjectedCRS":
            from pyproj import CRS

            crs = CRS.from_json_dict(dado)
            autoridade = crs.to_authority()
            if autoridade is None:
                _falhar("CRS sem autoridade conhecida")
            esperado = CRS.from_authority(*autoridade).to_json_dict()
            recebido = copy.deepcopy(dado)
            for referencia in (recebido, esperado):
                for membro in referencia.get("datum_ensemble", {}).get("members", []):
                    ident = membro.pop("id", None)
                    if ident is not None and (
                        set(ident) != {"authority", "code"}
                        or ident["authority"] != "EPSG"
                        or type(ident["code"]) is not int
                        or not 0 < ident["code"] < 10000000
                    ):
                        _falhar("identificador de datum fora do contrato")
            if recebido != esperado:
                _falhar("CRS divergente do registro de autoridade")
            return
        for k, v in dado.items():
            _texto(str(k))
            if colunas_pessoais([str(k)]) or PESSOAL.search(str(k)):
                _falhar("chave proibida em metadado")
            _metadados_parquet(v, campos, str(k))
    elif isinstance(dado, list):
        for v in dado:
            _metadados_parquet(v, campos, chave)
    elif isinstance(dado, str):
        # Nomes de campos são conferidos na tabela, tipos são descritores da biblioteca.
        tecnico = chave in {"name", "field_name", "primary_column"} and dado in campos
        tecnico |= chave in {"pandas_type", "numpy_type"} and bool(
            re.fullmatch(
                r"(?:u?int(?:8|16|32|64)|float(?:16|32|64)|unicode|bytes|object|bool|empty|date|datetime|"
                r"datetimetz|datetime64\[ns(?:, UTC)?\]|string)",
                dado,
            )
        )
        tecnico |= chave in {"version", "pandas_version"} and bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", dado))
        tecnico |= chave == "library" and dado in {"pyarrow", "fastparquet", "geopandas"}
        tecnico |= chave == "encoding" and dado == "WKB"
        if not tecnico:
            validar_json(dado, chave)
    else:
        validar_json(dado, chave)


def _kml(dados: bytes) -> None:
    """Fonte pública URTX: XML sem entidades, anexos ou campos pessoais."""
    from xml.etree.ElementTree import TreeBuilder

    from defusedxml.ElementTree import DefusedXMLParser

    parser = DefusedXMLParser(target=TreeBuilder(insert_comments=True, insert_pis=True))
    parser.feed(dados)
    raiz = parser.close()
    permitidas = set(
        "kml Document Folder Placemark Polygon MultiGeometry LinearRing outerBoundaryIs innerBoundaryIs "
        "coordinates name open Style BalloonStyle PolyStyle text colorMode styleUrl ExtendedData Schema "
        "SchemaData SimpleField SimpleData displayName balloonVisibility link".split()
    )
    for elemento in raiz.iter():
        if elemento.tail and elemento.tail.strip():
            validar_json(elemento.tail.strip(), "texto")
        if not isinstance(elemento.tag, str):
            validar_json(elemento.text or "", "texto")
            continue
        tag = elemento.tag.split("}")[-1]
        if tag not in permitidas:
            _falhar("elemento KML fora do contrato")
        for chave, valor in elemento.attrib.items():
            validar_json(valor, chave)
        conteudo = (elemento.text or "").strip()
        if tag == "coordinates":
            for ponto in conteudo.split():
                valores = [float(v) for v in ponto.split(",")]
                if len(valores) not in {2, 3} or not all(math.isfinite(v) for v in valores):
                    _falhar("coordenada KML inválida")
                if not -180 <= valores[0] <= 180 or not -90 <= valores[1] <= 90:
                    _falhar("coordenada KML fora de faixa")
        elif conteudo:
            # Classe cartográfica explícita da fonte URTX, confundida com pessoa pelo NER português.
            aceiro = tag == "name" or (tag == "SimpleData" and elemento.attrib.get("name") == "Class_Refl")
            if aceiro and re.fullmatch(r"Aceiro [0-9]{1,4}(?:\.[0-9]+)? ?m", conteudo):
                _texto(conteudo)
            else:
                validar_json(conteudo, "texto")


def _pmtiles(dados: bytes, areas: pd.Series | None) -> None:
    import mapbox_vector_tile
    from pmtiles.reader import Reader, all_tiles
    from pmtiles.tile import Compression, TileType

    def get(offset, length):
        return dados[offset : offset + length]

    leitor = Reader(get)
    cab = leitor.header()
    if cab["tile_type"] != TileType.MVT:
        _falhar("PMTiles sem contrato vetorial")
    meta = get(cab["metadata_offset"], cab["metadata_length"])
    if cab["internal_compression"] == Compression.GZIP:
        meta = gzip.decompress(meta)
    validar_json(_carregar_json(meta))
    for _, bloco in all_tiles(get):
        if cab["tile_compression"] == Compression.GZIP:
            bloco = gzip.decompress(bloco)
        elif cab["tile_compression"] != Compression.NONE:
            _falhar("compressão PMTiles não suportada")
        from mapbox_vector_tile.Mapbox import vector_tile_pb2

        mensagem = vector_tile_pb2.tile()
        mensagem.ParseFromString(bloco)
        antes = mensagem.SerializeToString()
        mensagem.DiscardUnknownFields()
        if mensagem.SerializeToString() != antes:
            _falhar("campo protobuf desconhecido no vetor")
        for camada_proto in mensagem.layers:
            for chave in camada_proto.keys:
                if chave not in {"cod_imovel", "camada", "ha"}:
                    _falhar("atributo vetorial sem contrato")
            for valor in camada_proto.values:
                for _, conteudo in valor.ListFields():
                    validar_json(conteudo)
        for camada, conteudo in mapbox_vector_tile.decode(bloco).items():
            if camada not in {"imoveis", "camadas"}:
                _falhar("camada vetorial sem contrato")
            for feature in conteudo["features"]:
                p = feature["properties"]
                if not set(p) <= {"cod_imovel", "camada", "ha"} or "cod_imovel" not in p:
                    _falhar("atributo vetorial sem contrato")
                validar_json(p)
                if "ha" in p:
                    if areas is None or str(p["cod_imovel"]) not in areas.index:
                        _falhar("PMTiles sem área do CAR de referência")
                    if not 0 <= float(p["ha"]) <= areas.loc[str(p["cod_imovel"])] + 1e-6:
                        _falhar("área vetorial fora do CAR")


def _validar_arquivos(arquivos: dict[str, bytes]) -> dict[str, int]:
    """Valida todos os bytes antes do primeiro upload; retorna apenas contagens públicas."""
    tabelas = {}
    tiles = {}
    for nome, dados in arquivos.items():
        if Path(nome).name != nome:
            _falhar("caminho de publicação inválido")
        if nome.endswith((".csv", ".parquet", ".pmtiles")):
            tipo = _tipo(nome)
            if nome.endswith(".pmtiles"):
                tiles[nome] = dados
                continue
            if nome.endswith(".csv"):
                # dtype de IDs preserva zeros à esquerda e impede código virar número de contato.
                cab = next(csv.reader(io.StringIO(dados.decode("utf-8-sig"))))
                if len(cab) != len(set(cab)):
                    _falhar("colunas CSV duplicadas")
                df = pd.read_csv(io.BytesIO(dados), dtype={"cod_imovel": str}, low_memory=False)
            else:
                import pyarrow.parquet as pq

                esquema_arrow = pq.read_schema(io.BytesIO(dados))
                for campo in esquema_arrow:
                    if not campo.metadata:
                        continue
                    meta_campo = campo.metadata
                    if campo.name != "geometry" or set(meta_campo) != {
                        b"ARROW:extension:name",
                        b"ARROW:extension:metadata",
                    }:
                        _falhar("metadado de campo Parquet fora do contrato")
                    if meta_campo[b"ARROW:extension:name"] != b"geoarrow.wkb":
                        _falhar("extensão Parquet fora do contrato")
                    _metadados_parquet(
                        _carregar_json(meta_campo[b"ARROW:extension:metadata"]), set(esquema_arrow.names)
                    )
                meta = esquema_arrow.metadata or {}
                if set(meta) - {b"ARROW:schema", b"geo", b"pandas"}:
                    _falhar("metadado Parquet fora do contrato")
                for chave, valor in meta.items():
                    if chave != b"ARROW:schema":
                        _metadados_parquet(_carregar_json(valor), set(esquema_arrow.names))
                df = pd.read_parquet(io.BytesIO(dados))
                if tipo in {"geo", "camadas"} and "geometry" in df:
                    import shapely

                    geometria = shapely.from_wkb(df.geometry.to_numpy())
                    if not shapely.is_valid(geometria).all() or shapely.is_empty(geometria).any():
                        _falhar("geometria inválida ou vazia")
            tabelas[nome] = (tipo, df)
        elif re.fullmatch(r"(?:_versoes|estados|raiz_controle(?:_[A-Z]{2})?|fontes|vigilancia)\.json", nome):
            validar_json(_carregar_json(dados))
        elif nome == "URTX.kml":
            _kml(dados)
        elif re.fullmatch(r"geo_\d{7}\.geojson", nome):
            objeto = _carregar_json(dados)
            if set(objeto) != {"type", "features"} or objeto["type"] != "FeatureCollection":
                _falhar("GeoJSON fora do contrato")
            import shapely

            linhas = []
            for feature in objeto["features"]:
                if set(feature) != {"type", "properties", "geometry"} or feature["type"] != "Feature":
                    _falhar("feição GeoJSON fora do contrato")
                if set(feature["properties"]) != {"cod_imovel"}:
                    _falhar("propriedade GeoJSON fora do contrato")
                geom_json = feature["geometry"]
                if set(geom_json) != {"type", "coordinates"} or geom_json["type"] not in {"Polygon", "MultiPolygon"}:
                    _falhar("geometria GeoJSON fora do contrato")
                geom = shapely.from_geojson(json.dumps(geom_json))
                if geom.is_empty or not geom.is_valid:
                    _falhar("GeoJSON com geometria inválida")
                linhas.append({**feature["properties"], "geometry": geom.wkb})
            tabelas[nome] = ("geo", pd.DataFrame(linhas, columns=["cod_imovel", "geometry"]))
        elif nome == "rodadas.jsonl":
            for linha in dados.decode("utf-8").splitlines():
                validar_json(_carregar_json(linha))
        else:
            _falhar("arquivo sem contrato público")
    referencias = {}
    for nome, (tipo, df) in tabelas.items():
        if tipo == "imoveis":
            try:
                validar_tabela(df, tipo)
            except ErroQualidade as exc:
                raise ErroQualidade(f"{nome}: {exc}") from None
            referencias[nome.removeprefix("imoveis_").split(".")[0]] = df.set_index("cod_imovel")["ha"].astype(float)
    for nome, (tipo, df) in tabelas.items():
        mun = re.search(r"(\d{7})\.", nome)
        if tipo != "imoveis":
            try:
                validar_tabela(df, tipo, referencias.get(mun[1]) if mun else None)
            except ErroQualidade as exc:
                raise ErroQualidade(f"{nome}: {exc}") from None
    for nome, dados in tiles.items():
        mun = re.search(r"(\d{7})\.", nome)
        _pmtiles(dados, referencias.get(mun[1]) if mun else None)
    _saltos(tabelas)
    return {"arquivos": len(arquivos), "tabelas": len(tabelas), "linhas": sum(len(df) for _, df in tabelas.values())}


def validar_arquivos(arquivos: dict[str, bytes]) -> dict[str, int]:
    """Nunca deixa exceção do parser expor células ou bytes privados em logs."""
    try:
        return _validar_arquivos(arquivos)
    except ErroQualidade:
        raise
    except Exception:
        raise ErroQualidade("publicação bloqueada: formato ou conteúdo ilegível; valores omitidos") from None


def _validar_pacotes(caminhos: list[Path]) -> dict[str, int]:
    """Entrada CLI para Releases prontos; lê TAR sem extrair caminhos do arquivo."""
    arquivos = {}
    for caminho in caminhos:
        if caminho.name.endswith(".tar.gz"):
            with abrir_tar_seguro(caminho) as tar:
                for membro in tar:
                    p = PurePosixPath(membro.name)
                    if membro.isdir():
                        if membro.name not in _UFS or membro.size:
                            _falhar("diretório TAR fora do contrato")
                        continue
                    if not membro.isfile() or len(p.parts) != 2 or p.parts[0] not in _UFS:
                        _falhar("membro TAR fora do contrato")
                    if membro.size > 2 * 1024**3:
                        _falhar("membro TAR acima de 2 GiB")
                    nome = p.name
                    dado = tar.extractfile(membro).read()
                    if nome == "_versoes.json":
                        validar_json(_carregar_json(dado))
                        # Um manifesto por UF; não confundir isso com tabela duplicada.
                        continue
                    if nome in arquivos:
                        _falhar("arquivo duplicado nos pacotes")
                    arquivos[nome] = dado
        else:
            if caminho.name in arquivos:
                _falhar("arquivo duplicado nos pacotes")
            arquivos[caminho.name] = caminho.read_bytes()
    return validar_arquivos(arquivos)


def validar_pacotes(caminhos: list[Path]) -> dict[str, int]:
    """Também confere contêiner/metadados, sem ecoar caminhos ou erros de parsers."""
    try:
        return _validar_pacotes(caminhos)
    except ErroQualidade:
        raise
    except Exception:
        raise ErroQualidade("publicação bloqueada: contêiner TAR/gzip inválido; valores omitidos") from None


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta", type=Path)
    args = parser.parse_args()
    try:
        caminhos = sorted(args.pasta.iterdir())
        if not caminhos or any(not p.is_file() or p.is_symlink() for p in caminhos):
            _falhar("lote vazio, diretório extra ou link simbólico")
        resultado = validar_pacotes(caminhos)
    except Exception as exc:
        # O erro de um parser pode ecoar conteúdo privado; a CLI só mostra regras conhecidas.
        parser.exit(1, f"{exc if isinstance(exc, ErroQualidade) else 'publicação bloqueada: arquivo ilegível'}\n")
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main()
