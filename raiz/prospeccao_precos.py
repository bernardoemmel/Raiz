"""Catálogo proposto e simulação de receita; não cria cobrança nem altera a carteira.

Um crédito de consulta libera a ficha de um CAR. As quantidades 1/10/50 e o ciclo
mensal são hipóteses comerciais do YAML, não toneladas de carbono ou preços aprovados.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

PRECOS_PADRAO = Path(__file__).parent / "regras" / "padroes" / "precos.yaml"
MODALIDADES = ("por_ficha", "por_lote", "assinatura")
Modalidade = Literal["por_ficha", "por_lote", "assinatura"]


def carregar_catalogo(caminho: Path | None = None, *, usar_ambiente: bool = True) -> dict:
    """Lê propostas novas e envelopes antigos sem reinterpretar compras já gravadas."""
    try:
        override = os.environ.get("RAIZ_PROSPECCAO_PLANOS") if usar_ambiente else None
        arquivo = os.environ.get("RAIZ_PRECOS_ARQUIVO") if usar_ambiente else None
        bruto = (
            json.loads(override)
            if override
            else yaml.safe_load(Path(arquivo or caminho or PRECOS_PADRAO).read_text("utf-8"))
        )
        if isinstance(bruto, list):
            bruto = {"versao": "proposta-ambiente", "status": "provisorio", "planos": bruto}
        if not isinstance(bruto, dict) or not isinstance(bruto.get("planos"), list):
            raise ValueError
        if type(bruto.get("formato", 1)) is not int or bruto.get("formato", 1) not in (1, 2):
            raise ValueError
        versao, status = bruto.get("versao"), bruto.get("status")
        if not isinstance(versao, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]{1,80}", versao):
            raise ValueError
        if status not in ("provisorio", "aprovado") or bruto.get("moeda", "BRL") != "BRL":
            raise ValueError
        aprovado_em = dt.date.fromisoformat(str(bruto.get("aprovado_em"))) if status == "aprovado" else None
        planos, ids = [], set()
        for item in bruto["planos"]:
            ident, nome, quantidade = item["id"], item["nome"], item["creditos"]
            modalidade = item.get(
                "modalidade", ident if ident in MODALIDADES else "por_ficha" if quantidade == 1 else "por_lote"
            )
            valor = Decimal(str(item["valor_rs"])) if item.get("valor_rs") is not None else None
            if (
                not isinstance(ident, str)
                or not re.fullmatch(r"[a-z0-9_-]{1,40}", ident)
                or ident in ids
                or not isinstance(nome, str)
                or not nome.strip()
                or len(nome) > 80
                or modalidade not in MODALIDADES
                or (ident in MODALIDADES and modalidade != ident)
                or type(quantidade) is not int
                or not 1 <= quantidade <= 100_000
                or (modalidade == "por_ficha" and quantidade != 1)
                or (status == "aprovado" and valor is None and modalidade != "assinatura")
                or (
                    valor is not None
                    and (
                        not valor.is_finite()
                        or not Decimal("0.01") <= valor <= Decimal("99999999.99")
                        or valor != valor.quantize(Decimal("0.01"))
                    )
                )
            ):
                raise ValueError
            ids.add(ident)
            plano = {
                "id": ident,
                "modalidade": modalidade,
                "nome": nome,
                "creditos": quantidade,
                "status_quantidade": item.get("status_quantidade", "definida_no_catalogo"),
                "valor_rs": float(valor) if valor is not None else None,
                "status": status if valor is not None else "provisorio",
                "aviso_preco": "Preço aprovado pelo fundador"
                if status == "aprovado" and valor is not None
                else "a definir pelo fundador",
                # Nenhum campo do YAML consegue declarar implementada uma recorrência inexistente.
                "cobranca_implementada": modalidade != "assinatura",
                "renovacao_automatica": False,
            }
            if modalidade == "assinatura":
                ciclo = item.get("ciclo_meses", 1)
                creditos_ciclo = item.get("creditos_por_ciclo", quantidade)
                if (
                    type(ciclo) is not int
                    or not 1 <= ciclo <= 120
                    or type(creditos_ciclo) is not int
                    or creditos_ciclo != quantidade
                ):
                    raise ValueError
                plano.update(
                    creditos_por_ciclo=quantidade,
                    ciclo_meses=ciclo,
                    status_ciclo="proposta",
                    validade_creditos_dias=None,
                    acumula_creditos=None,
                    regra_excedentes="a definir pelo fundador",
                    regra_cancelamento="a definir pelo fundador",
                    regra_reembolso="a definir pelo fundador",
                    aviso_modalidade="Proposta de assinatura. Cobrança por ciclo ainda não implementada.",
                )
            planos.append(plano)
        if bruto.get("formato") == 2 and (len(planos) != 3 or {p["modalidade"] for p in planos} != set(MODALIDADES)):
            raise ValueError
        return {
            "planos": planos,
            "versao": versao,
            "status": status,
            "aprovado_em": aprovado_em.isoformat() if aprovado_em else None,
        }
    except (OSError, yaml.YAMLError, ValueError, TypeError, KeyError, InvalidOperation) as ex:
        raise ValueError("Catálogo de créditos de consulta inválido ou indisponível.") from ex


Quantidade = Annotated[Decimal, Field(ge=0, le=1_000_000, decimal_places=6, allow_inf_nan=False)]
Valor = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=6, allow_inf_nan=False)]


class CustosReceita(BaseModel):
    """Todos os componentes precisam ser declarados; zero é uma hipótese explícita."""

    model_config = ConfigDict(extra="forbid")
    por_credito_consumido_rs: Valor
    fixo_por_cliente_mes_rs: Valor
    taxa_sobre_receita_pct: Annotated[Decimal, Field(ge=0, le=100, decimal_places=6, allow_inf_nan=False)]


class CenarioReceita(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clientes: int = Field(default=1, ge=1, le=1_000_000, strict=True)
    preco_unitario_rs: Valor | None = None
    unidades_por_cliente_mes: Quantidade | None = None
    consumo_creditos_por_cliente_mes: Quantidade | None = None
    creditos_por_unidade: int | None = Field(default=None, ge=1, le=100_000, strict=True)
    ciclo_meses: int | None = Field(default=None, ge=1, le=120, strict=True)
    custos: CustosReceita | None = None


def _dinheiro(valor: Decimal | None) -> float | None:
    if valor is None:
        return None
    # Receita pequena pode produzir percentuais de margem grandes dentro dos limites permitidos.
    with localcontext() as contexto:
        contexto.prec = 50
        return float(valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def simular_receita(modalidade: Modalidade, cenario: CenarioReceita | dict | None = None) -> dict:
    """Projeção média por competência. Não persiste hipóteses nem consulta o provedor Pix.

    A assinatura considera um plano por cliente e a duração declarada do ciclo.
    Ano significa doze meses com os mesmos parâmetros, não um calendário de caixa.
    Preço vem somente da entrada explícita; não é copiado de um catálogo de venda.
    """
    if modalidade not in MODALIDADES:
        raise ValueError("Modalidade deve ser por_ficha, por_lote ou assinatura.")
    c = (
        cenario
        if isinstance(cenario, CenarioReceita)
        else CenarioReceita.model_validate({} if cenario is None else cenario)
    )
    catalogo = carregar_catalogo(usar_ambiente=False)
    proposta = next(p for p in catalogo["planos"] if p["modalidade"] == modalidade)
    quantidade = c.creditos_por_unidade or proposta["creditos"]
    if modalidade == "por_ficha" and quantidade != 1:
        raise ValueError("Por ficha corresponde a um crédito de consulta por unidade.")
    ciclo = c.ciclo_meses or proposta.get("ciclo_meses")
    if modalidade != "assinatura" and c.ciclo_meses is not None:
        raise ValueError("Duração de ciclo só se aplica à assinatura.")
    unidades = c.unidades_por_cliente_mes
    if modalidade == "assinatura":
        esperadas = Decimal(1) / ciclo
        if unidades is not None and unidades != esperadas:
            raise ValueError("Na assinatura, as unidades mensais devem corresponder a um ciclo por cliente.")
        unidades = esperadas
    receita = c.preco_unitario_rs * unidades if c.preco_unitario_rs is not None and unidades is not None else None
    concedidos = unidades * quantidade if unidades is not None else None
    consumo = c.consumo_creditos_por_cliente_mes
    variavel = fixo = proporcional = custo = margem = percentual = None
    if c.custos:
        variavel = consumo * c.custos.por_credito_consumido_rs if consumo is not None else None
        fixo = c.custos.fixo_por_cliente_mes_rs
        proporcional = receita * c.custos.taxa_sobre_receita_pct / 100 if receita is not None else None
        if receita is None and c.custos.taxa_sobre_receita_pct == 0:
            proporcional = Decimal(0)
        if variavel is not None and proporcional is not None:
            custo = variavel + fixo + proporcional
    if receita is not None and custo is not None:
        margem = receita - custo
        percentual = margem / receita * 100 if receita else None

    def periodo(fator):
        return {
            "unidades_vendidas": float(unidades * fator) if unidades is not None else None,
            "creditos_concedidos": float(concedidos * fator) if concedidos is not None else None,
            "creditos_consumidos": float(consumo * fator) if consumo is not None else None,
            "receita_bruta_rs": _dinheiro(receita * fator) if receita is not None else None,
            "custo_variavel_rs": _dinheiro(variavel * fator) if variavel is not None else None,
            "custo_fixo_rs": _dinheiro(fixo * fator) if fixo is not None else None,
            "custo_proporcional_rs": _dinheiro(proporcional * fator) if proporcional is not None else None,
            "custo_total_informado_rs": _dinheiro(custo * fator) if custo is not None else None,
            "margem_rs": _dinheiro(margem * fator) if margem is not None else None,
            "margem_pct": _dinheiro(percentual),
        }

    pendencias = []
    if c.preco_unitario_rs is None:
        pendencias.append("preco_unitario_rs")
    if unidades is None:
        pendencias.append("unidades_por_cliente_mes")
    if consumo is None:
        pendencias.append("consumo_creditos_por_cliente_mes")
    if c.custos is None:
        pendencias.append("custos")
    avisos = [
        "Simulação hipotética; não aprova preços nem ativa vendas.",
        "Créditos de consulta são acessos a fichas de CAR, não créditos de carbono.",
        "Margem considera somente os custos declarados; não representa lucro líquido auditado.",
    ]
    if consumo is not None and concedidos is not None and consumo > concedidos:
        avisos.append(
            "Consumo supera os créditos incluídos; saldo anterior ou regra de excedentes ainda precisam ser definidos."
        )
    if modalidade == "assinatura":
        avisos.append("Assinatura é proposta; cobrança e direitos por ciclo ainda não foram implementados.")
    simbolos = {
        "por_ficha": "P_ficha × n_fichas_mês",
        "por_lote": "P_lote × n_lotes_mês",
        "assinatura": "P_assinatura ÷ ciclo_meses",
    }
    return {
        "tipo": "simulacao_hipotetica",
        "modalidade": modalidade,
        "moeda": "BRL",
        "unidade_credito": "crédito de consulta",
        "base_temporal": "Média mensal por competência e anualização em 12 meses; não é calendário de recebimentos.",
        "parametros": c.model_dump(mode="json"),
        "hipotese_quantidade": {
            "creditos_por_unidade": quantidade,
            "ciclo_meses": ciclo,
            "status": "hipotese_explicita" if c.creditos_por_unidade or c.ciclo_meses else "proposta_do_catalogo",
            "versao_catalogo": catalogo["versao"],
        },
        "formulas": {
            "receita_por_cliente_mes": simbolos[modalidade],
            "receita_por_cliente_ano": "receita_por_cliente_mes × 12",
            "receita_carteira_mes": "receita_por_cliente_mes × clientes",
            "custo_por_cliente_mes": "créditos_consumidos × custo_por_crédito + custo_fixo + receita × taxa_pct ÷ 100",
            "margem_rs": "receita − custos informados",
            "margem_pct": "margem_rs ÷ receita × 100; indefinida quando receita é zero",
        },
        "por_cliente": {"mes": periodo(1), "ano": periodo(12)},
        "carteira": {"clientes": c.clientes, "mes": periodo(c.clientes), "ano": periodo(c.clientes * 12)},
        "pendencias": pendencias,
        "avisos": avisos,
    }


def simular_modalidades(cenarios: dict[str, dict] | None = None) -> dict:
    """Compara as três modalidades sem assumir preço, volume ou custo ausente."""
    cenarios = {} if cenarios is None else cenarios
    if not isinstance(cenarios, dict):
        raise ValueError("Cenários devem ser um objeto por modalidade.")
    if set(cenarios) - set(MODALIDADES):
        raise ValueError("Cenário contém modalidade desconhecida.")
    return {m: simular_receita(m, cenarios.get(m)) for m in MODALIDADES}
