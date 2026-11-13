"""Premissas por operação e custos auditáveis da rodada 12."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

ARQUIVO = Path(__file__).parent / "regras/padroes/rodada12_financeiro.json"


def regra() -> dict:
    return json.loads(ARQUIVO.read_text())


def versao() -> str:
    return "financeiro-r12-2026a+" + hashlib.sha256(Path(__file__).read_bytes() + ARQUIVO.read_bytes()).hexdigest()[:12]


def operacao(nome: str, *, estresse: bool = False) -> dict:
    r = regra()
    if nome not in r["operacoes"]:
        raise ValueError("indique a operação de referência; não há taxa universal do Fundo Clima")
    return {
        **r["operacoes"][nome],
        "nome": nome,
        "estresse": estresse,
        "juros_ano": r["estresse_juros_ano"] if estresse else r["operacoes"][nome]["juros_ano"],
        "modelo_versao": versao(),
        "fonte": r["fonte_operacoes"],
    }


def aluguel_sfx() -> dict:
    r = regra()["aluguel_sfx"]
    fator = r["ipca_destino"] / r["ipca_origem"]
    return {
        **r,
        "brl_ha_ano": r["despesa_2017_brl"] / r["area_arrendada_ha"] * fator,
        "fator_ipca": fator,
        "modelo_versao": versao(),
    }


def referencias_comprador() -> dict:
    r = regra()
    p = r["profloresta_1"]
    h = r["hectares_milhao"]
    return {
        "profloresta_1": {**p, "media_ponderada_usd_t": float(np.average(p["precos_usd_t"], weights=p["volumes_t"]))},
        "hectares_por_milhao": {**h, "min": h["raiz"], "max": h["regreen_hectares"] / h["regreen_creditos"] * 1e6},
        "modelo_versao": versao(),
    }


def custos_terra(*, matriculas: int, tipo_certidao: str, area_georreferenciar_ha: float) -> dict:
    if isinstance(matriculas, bool) or matriculas < 0 or int(matriculas) != matriculas:
        raise ValueError("matriculas deve ser contagem não negativa")
    if not math.isfinite(area_georreferenciar_ha) or area_georreferenciar_ha < 0:
        raise ValueError("área a georreferenciar inválida")
    if tipo_certidao not in ("inteiro_teor", "conjunta"):
        raise ValueError("escolha inteiro_teor ou conjunta; não somar duas vezes a mesma certidão")
    r = regra()["custos"]
    cert = matriculas * r[tipo_certidao + "_pa_brl"]
    geo = area_georreferenciar_ha * r["georreferenciamento_brl_ha"]
    return {
        "matriculas": matriculas,
        "tipo_certidao": tipo_certidao,
        "certidoes_brl": cert,
        "area_georreferenciar_ha": area_georreferenciar_ha,
        "georreferenciamento_brl": geo,
        "total_brl": cert + geo,
        "modelo_versao": versao(),
        "limite": r["georreferenciamento_limite"],
        "fontes": [r["cartorio_fonte"], r["georreferenciamento_fonte"]],
    }


def provisao_terra(linha: dict, area_restaurada_ha: float) -> dict:
    """Provisão explícita para o CAR inteiro; cadastro não prova matrícula.

    Sem contagem registral, uma certidão é o mínimo orçado, não uma matrícula
    comprovada. Sem escopo de levantamento, provisiona a área inteira do CAR;
    a área restaurada só é usada quando o cadastro omite a área total.
    """

    def numero(chave):
        try:
            x = float(linha.get(chave))
            return x if math.isfinite(x) and x >= 0 else None
        except (TypeError, ValueError):
            return None

    area = numero("area_georreferenciar_ha")
    mats = numero("matriculas_referenciadas")
    pendencias = []
    if area is None:
        area = max(numero("area_ha") or numero("ha") or 0, area_restaurada_ha)
        pendencias.append("confirmar escopo do georreferenciamento; provisão sobre a área integral disponível")
    if mats is None or int(mats) != mats:
        mats = 1
        pendencias.append("contar matrículas; uma certidão por CAR é somente provisão mínima")
    resultado = custos_terra(matriculas=int(mats), tipo_certidao="conjunta", area_georreferenciar_ha=area)
    resultado["pendencias"] = pendencias
    resultado["natureza"] = "provisão de custo; não comprova título nem dispensa georreferenciamento"
    if linha.get("uf") != "PA":
        pendencias.append("emolumentos do PA usados como referência; conferir tabela do estado do imóvel")
    return resultado


def taxas_verra(emissoes_por_ano: list[float], anos_verificacao: list[int]) -> dict:
    """Taxas por projeto, não por fazenda; abate adiantamento de US$2.500.

    O vetor é de créditos líquidos da reserva requeridos na emissão, não de
    receita contratada. Crédito antecipado de uma verificação não paga emissão
    de um ano anterior. Saldo não usado fica explicitamente identificado.
    """
    emitidos = np.asarray(emissoes_por_ano, dtype=float)
    if emitidos.ndim != 1 or not len(emitidos) or not np.isfinite(emitidos).all() or (emitidos < 0).any():
        raise ValueError("emissões anuais inválidas")
    if len(set(anos_verificacao)) != len(anos_verificacao) or any(
        isinstance(a, bool) or int(a) != a or not 0 <= a < len(emitidos) for a in anos_verificacao
    ):
        raise ValueError("anos de verificação inválidos ou repetidos")
    r = regra()["custos"]
    caixa = np.zeros(len(emitidos))
    caixa[0] = r["verra_registro_usd"] + r["verra_listagem_usd"]
    saldo = 0.0
    ledger = []
    verificado = False
    for ano, t in enumerate(emitidos):
        if ano in anos_verificacao:
            verificado = True
            caixa[ano] += r["verra_verificacao_usd"]
            saldo += r["verra_adiantamento_emissao_usd"]
        if t and not verificado:
            raise ValueError("emissão sem verificação anterior")
        taxa = t * r["verra_emissao_usd_t"]
        abatido = min(saldo, taxa)
        saldo -= abatido
        caixa[ano] += taxa - abatido
        ledger.append(
            {
                "ano": ano,
                "toneladas_liquidas_buffer": float(t),
                "taxa_emissao_usd": taxa,
                "adiantamento_abatido_usd": abatido,
                "adiantamento_saldo_usd": saldo,
                "caixa_usd": float(caixa[ano]),
            }
        )
    return {
        "modelo_versao": versao(),
        "fluxo_usd": caixa.tolist(),
        "total_usd": float(caixa.sum()),
        "adiantamento_saldo_usd": saldo,
        "memoria": ledger,
        "fonte": r["verra_fonte"],
    }


def orcamento_mudas(area_plantio_ha: float, mudas_ha: float = 1667) -> dict:
    if any(not math.isfinite(x) or x < 0 for x in (area_plantio_ha, mudas_ha)):
        raise ValueError("área e densidade de mudas inválidas")
    r = regra()["custos"]
    n = area_plantio_ha * mudas_ha
    return {
        "mudas": n,
        "min_brl": n * r["muda_brl_min"],
        "max_brl": n * r["muda_brl_max"],
        "quantis": False,
        "fonte": r["muda_fonte"],
        "somar_ao_sfb": False,
        "modelo_versao": versao(),
    }
