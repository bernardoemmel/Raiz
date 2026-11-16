"""Contrato fechado da ficha paga: somente terra, com ausência e proveniência explícitas.

Não reutiliza o dicionário aberto do motor nem textos livres de certidões. A data
de corte da carga fica separada da data da fonte; uma não comprova a outra.
"""

from __future__ import annotations

import datetime as dt
import math
import re

from raiz import terra
from raiz.privacidade import mascarar
from raiz.terra_comprometida import fechar_dto

_ANO = re.compile(r"^mb_(supressao_primaria|supressao_secundaria|fogo)_(\d{4})_ha$")
_PERDAS = {
    "supressao_primaria": "Supressão de vegetação primária",
    "supressao_secundaria": "Supressão de vegetação secundária",
    "fogo": "Área queimada",
}
_SOBREPOSICOES = (
    ("ti_ha", "terra_indigena", "Terra indígena", "INPE/TerraBrasilis"),
    ("ti_funai_ha", "terra_indigena_funai", "Terra indígena (Funai)", "Funai"),
    ("quilombo_ha", "quilombo", "Quilombo", "INCRA"),
    ("uc_ha", "unidade_conservacao", "Unidade de conservação", "INPE/TerraBrasilis"),
    ("uc_protecao_integral_ha", "uc_protecao_integral", "Proteção integral", "CNUC"),
    ("terra_publica_ha", "terra_publica", "Terra pública", "Raíz, SIGEF/CNFP/CNUC"),
    ("matricula_ha", "matricula", "Parcela com matrícula", "INCRA/SIGEF"),
    ("assentamento_ha", "assentamento", "Assentamento", "INCRA/SIGEF"),
    ("projeto_carbono_ha", "projeto_carbono", "Projeto de carbono registrado", "Registros de carbono, motor Raíz"),
)


def _numero(valor) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        n = float(valor)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if math.isfinite(n) else None


def _marcado(valor) -> bool:
    """Indicadores das certidões chegam como booleanos ou texto de CSV, não como medidas."""
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "1", "sim", "t")
    return valor is True or _numero(valor) == 1


def _texto(valor) -> str | None:
    if not isinstance(valor, str) or not valor.strip():
        return None
    return mascarar(valor.strip())


def _codigo(valor) -> str | None:
    s = _texto(valor)
    return s if s and re.fullmatch(r"[A-Za-z0-9_.+:/-]{1,200}", s) else None


def _data(valor) -> str | None:
    if isinstance(valor, dt.datetime):
        return valor.date().isoformat()
    if isinstance(valor, dt.date):
        return valor.isoformat()
    if not isinstance(valor, str):
        return None
    if re.fullmatch(r"(?:19|20)\d{2}", valor):
        return valor
    try:
        return dt.date.fromisoformat(valor).isoformat()
    except ValueError:
        try:
            return dt.datetime.fromisoformat(valor).date().isoformat()
        except ValueError:
            return None


def _medida(valor, unidade: str, fonte: str, corte, data=None, estimado: bool = False) -> dict:
    return {
        "valor": _numero(valor),
        "unidade": unidade,
        "fonte": fonte,
        "data_referencia": _data(data),
        "data_corte": corte,
        "estimado": estimado,
    }


def _credito(linha: dict, corte) -> dict:
    """Só crédito líquido já calculado; nunca converte captura bruta em crédito."""
    area = _numero(linha.get("restauracao_area_ha"))
    total_contrato = _numero(linha.get("credito_liquido_tco2_contrato"))
    contrato = total_contrato is not None or any(
        _numero(linha.get(f"credito_liquido_tco2_ha_contrato_{p}")) is not None for p in ("p10", "p50", "p90")
    )
    anual = any(
        _numero(linha.get(c)) is not None
        for c in (
            "credito_liquido_tco2_ha_ano_p10",
            "credito_liquido_tco2_ha_ano",
            "credito_liquido_tco2_ha_ano_p90",
            "credito_liquido_tco2_ano",
        )
    )
    base = "liquido_contrato" if contrato else "liquido_anual" if anual else "nao_calculado"
    out = {}
    for p in ("p10", "p50", "p90"):
        campo = (
            f"credito_liquido_tco2_ha_contrato_{p}"
            if contrato
            else ("credito_liquido_tco2_ha_ano" if p == "p50" else f"credito_liquido_tco2_ha_ano_{p}")
        )
        v = _numero(linha.get(campo))
        v = v * area if v is not None and area is not None else None
        if p == "p50" and v is None:
            v = total_contrato if contrato else _numero(linha.get("credito_liquido_tco2_ano"))
        out[p] = _medida(
            v,
            "tCO2e/contrato" if contrato else "tCO2e/ano",
            "Raíz, modelo de restauração",
            corte,
            linha.get("restauracao_data_referencia"),
            estimado=True,
        )
    return {
        **out,
        "base": base,
        "metodo": (
            "Faixas do modelo quando disponíveis; P50 do cenário central. A ficha não recalcula nem aplica "
            "fatores padrão. O método de incerteza não vem identificado nesta carga; a versão do modelo "
            "permite conferir a origem das faixas. Estimativa, sem crédito emitido."
        )
        if contrato or anual
        else "Crédito líquido ainda não calculado; captura bruta não é crédito emitível.",
        "versao_modelo": _codigo(linha.get("restauracao_versao")),
    }


def _serie(banco: dict, corte) -> list[dict]:
    serie = banco.get("serie_uso")
    if not isinstance(serie, dict) or not isinstance(serie.get("anos"), list):
        return []
    out = []
    for i, a in enumerate(serie["anos"]):
        ano = _numero(a)
        if ano is None or not ano.is_integer() or not 1985 <= ano <= 2100:
            continue
        valores = {}
        for uso in ("mata", "pasto", "lavoura", "agua"):
            lista = serie.get(f"{uso}_pct")
            v = _numero(lista[i]) if isinstance(lista, list) and i < len(lista) else None
            v = v if v is not None and 0 <= v <= 100 else None
            valores[uso] = _medida(v, "%", "MapBiomas, cobertura anual", corte, str(int(ano)))
        out.append({"ano": int(ano), **valores})
    return sorted(out, key=lambda x: x["ano"])


def _perdas(linha: dict, corte) -> list[dict]:
    out = []
    for campo in sorted(linha):
        m = _ANO.fullmatch(campo)
        if not m:
            continue
        tipo, ano = m.groups()
        out.append(
            {
                "ano": int(ano),
                "tipo": tipo,
                "rotulo": _PERDAS[tipo],
                "area": _medida(linha[campo], "ha", "MapBiomas", corte, ano),
            }
        )
    # Janelas acumuladas do PRODES não viram perdas anuais, nem são somadas entre si.
    for marco in (2008, 2016, 2020):
        campo = f"desm_pos{marco}_ha"
        if campo in linha:
            out.append(
                {
                    "ano": None,
                    "tipo": f"desmatamento_pos{marco}",
                    "rotulo": f"Desmatamento acumulado após {marco}",
                    "area": _medida(linha[campo], "ha", "INPE/PRODES", corte, linha.get("prodes_data_referencia")),
                }
            )
    return out


def _terra(linha: dict) -> dict:
    """Só entradas conhecidas chegam ao classificador; textos livres não saem dele."""
    campos = (
        "ha",
        "area",
        "matricula_ha",
        "f_matricula",
        "assentamento_ha",
        "sigef_ha",
        "ti_ha",
        "ti_funai_ha",
        "quilombo_ha",
        "uc_protecao_integral_ha",
        "terra_sigef_registrada_ha",
        "terra_sigef_titulacao_ha",
        "terra_sigef_posse_ha",
        "terra_sigef_assentamento_ha",
        "terra_sigef_assentamento_titulado_ha",
        "terra_publica_ha",
        "terra_tradicional_ha",
        "terra_concessao_ha",
    )
    d = {k: _numero(linha.get(k)) for k in campos}
    d.update({k: linha.get(k) for k in ("tipo_imovel", "uf", "matricula_conferida")})
    d["terra_concessao"] = _codigo(linha.get("terra_concessao"))
    calculado = terra.caminho(d)
    calculado["origem"] = "derivada"
    # Respeita a classificação vigente, se válida, sem devolver os textos abertos da linha.
    if linha.get("caminho_terra") in terra.CAMINHOS and linha.get("risco_terra") in terra.RISCOS:
        for k in ("caminho_terra", "risco_terra"):
            calculado[k] = linha[k]
        calculado["terra_regra_versao"] = _codigo(linha.get("terra_regra_versao"))
        calculado["origem"] = "processada"
    elif not any(d[k] is not None for k in campos if k not in ("ha", "area")):
        calculado.update(caminho_terra="sem_dados", risco_terra=None, terra_regra_versao=None, origem="sem_dados")
    return calculado


def _pendencias(linha: dict, caminho: str) -> list[dict]:
    out = []
    avisos = terra.regra()["caminhos"].get(caminho, {})
    if caminho == "sem_dados":
        out.append(
            {"codigo": "caminho_sem_dados", "texto": "A classificação do caminho da terra ainda não está disponível."}
        )
    if avisos.get("aviso"):
        out.append({"codigo": caminho, "texto": " ".join(avisos["aviso"].split())})
    conferida = _marcado(linha.get("matricula_conferida"))
    if caminho == "privada_matricula" and not conferida:
        out.append({"codigo": "conferir_matricula", "texto": "Conferir matrícula e cadeia da terra no cartório."})
    for campo, codigo, texto in (
        ("embargo_ha", "embargo", "Conferir e resolver a sobreposição com embargo ativo."),
        ("ti_ha", "terra_indigena", "Conferir a sobreposição com terra indígena."),
        ("quilombo_ha", "quilombo", "Conferir a sobreposição com território quilombola."),
        ("projeto_carbono_ha", "projeto_carbono", "Conferir a sobreposição com projeto de carbono existente."),
        ("desm_pos2020_ha", "desmatamento", "Conferir a conversão de vegetação após 2020."),
        ("deficit_RL_ha", "reserva_legal", "Conferir a recomposição da reserva legal."),
        ("app_recompor_ha", "app", "Conferir a recomposição de APP."),
        ("matricula_onus_graves", "onus", "Conferir os ônus graves da matrícula."),
        ("matricula_quebra_cadeia", "cadeia", "Conferir a continuidade da cadeia da terra."),
        ("matricula_precisa_confirmar", "confirmacao", "A leitura da matrícula requer confirmação humana."),
    ):
        indicador = campo in ("matricula_onus_graves", "matricula_quebra_cadeia", "matricula_precisa_confirmar")
        if (indicador and _marcado(linha.get(campo))) or (_numero(linha.get(campo)) or 0) > 0:
            out.append({"codigo": codigo, "texto": texto})
    if linha.get("matricula_situacao") in ("cancelada", "divergente", "revisar"):
        out.append({"codigo": "matricula_pendente", "texto": "A leitura da matrícula exige revisão."})
    return out


def ficha(linha: dict, versao: dict | None = None, banco: dict | None = None) -> dict:
    versao, banco = versao or {}, banco or {}
    corte = _data(versao.get("data_corte")) or _data(banco.get("data_corte"))
    d = _terra(linha)
    cam = d["caminho_terra"]
    regra_cam = terra.regra()["caminhos"].get(cam, {"nome": "Caminho ainda não classificado", "situacao": "sem_dados"})
    terra_meta = {
        "fonte": "Raíz, regra do caminho da terra",
        "data_referencia": _data(linha.get("terra_data_referencia")),
        "regra_versao": d.get("terra_regra_versao"),
        "origem": d["origem"],
    }
    area_campo = "restauracao_area_ha" if _numero(linha.get("restauracao_area_ha")) is not None else "carbono_ha"
    mf = _numero(linha.get("m_fiscal"))
    pequena = mf <= 4 if mf is not None else (linha.get("porte") == "pequeno" if linha.get("porte") else None)
    embargo = _numero(linha.get("embargo_ha"))
    financiada = any(_numero(linha.get(f"tir_alavancada_pct_{p}")) is not None for p in ("p10", "p50", "p90"))
    prefixo_tir = "tir_alavancada_pct" if financiada else "tir_projeto_pct"
    cod = linha.get("cod_municipio_ibge", linha.get("cod_ibge"))
    codigo_ibge = int(_numero(cod)) if _numero(cod) is not None else None
    return {
        "versao": 1,
        "codigo_car": _codigo(linha.get("cod_imovel")),
        "municipio": _texto(linha.get("municipio")),
        "cod_ibge": codigo_ibge,
        "uf": linha.get("uf") if isinstance(linha.get("uf"), str) and re.fullmatch(r"[A-Z]{2}", linha["uf"]) else None,
        "bioma": _texto(linha.get("bioma")),
        "data_corte": corte,
        "area_total": _medida(
            linha.get("ha", linha.get("area")), "ha", "SICAR, polígono do CAR", corte, linha.get("data_atualizacao")
        ),
        "area_restauravel": _medida(
            linha.get(area_campo),
            "ha",
            "Raíz, modelo de restauração"
            if area_campo == "restauracao_area_ha"
            else "Raíz, motor: regeneração além da reserva legal",
            corte,
            linha.get("restauracao_data_referencia"),
            estimado=True,
        ),
        "caminho_terra": {"codigo": cam, "rotulo": regra_cam["nome"], "situacao": regra_cam["situacao"], **terra_meta},
        "pendencias": _pendencias(linha, cam),
        "terra_comprometida": fechar_dto(banco.get("terra_comprometida")),
        "sobreposicoes": [
            {
                "codigo": codigo,
                "rotulo": rotulo,
                "area": _medida(linha.get(campo), "ha", fonte, corte, linha.get(f"{campo}_data_referencia")),
            }
            for campo, codigo, rotulo, fonte in _SOBREPOSICOES
        ],
        "embargos": {
            "area": _medida(embargo, "ha", "Ibama, embargos ativos", corte, linha.get("ibama_data_referencia")),
            "situacao": "sem_dado"
            if embargo is None
            else "com_embargo"
            if embargo > 0
            else "sem_sobreposicao_identificada",
        },
        "serie_uso": _serie(banco, corte),
        "perdas": _perdas(linha, corte),
        "credito": _credito(linha, corte),
        "tir": {
            **{
                p: _medida(
                    linha.get(f"{prefixo_tir}_{p}"),
                    "%/ano",
                    "Raíz, fluxo de caixa da restauração",
                    corte,
                    linha.get("restauracao_data_referencia"),
                    estimado=True,
                )
                for p in ("p10", "p50", "p90")
            },
            "tipo": "com_financiamento" if financiada else "sem_financiamento",
        },
        "risco": {"nivel": d["risco_terra"], **terra_meta},
        "agrupamento": {
            "pequena": pequena,
            "grupo_id": _codigo(linha.get("grupo_id")),
            "imoveis": _medida(linha.get("grupo_imoveis"), "fazendas", "Raíz, agrupamento espacial", corte),
            "area": _medida(linha.get("grupo_ha"), "ha", "Raíz, agrupamento espacial", corte),
        },
    }
