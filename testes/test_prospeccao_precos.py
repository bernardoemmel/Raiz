"""Receita hipotética por modalidade, sem preços implícitos ou cobranças recorrentes."""

import json
import math

import pytest
from pydantic import ValidationError

from raiz import prospeccao_acesso as A
from raiz import prospeccao_precos as P
from raiz.pedidos import pix


def test_tres_modalidades_propostas_sem_preco_e_assinatura_sem_cobranca(monkeypatch):
    monkeypatch.delenv("RAIZ_PROSPECCAO_PLANOS", raising=False)
    monkeypatch.delenv("RAIZ_PRECOS_ARQUIVO", raising=False)
    monkeypatch.setenv("RAIZ_PIX_MODO", "producao")
    monkeypatch.setattr(pix, "chave", lambda: "chave-do-teste")
    catalogo = A.planos()
    assert [p["modalidade"] for p in catalogo["planos"]] == list(P.MODALIDADES)
    assert [p["creditos"] for p in catalogo["planos"]] == [1, 10, 50]
    assert all(p["valor_rs"] is None and not p["pagamento_disponivel"] for p in catalogo["planos"])
    assert all(p["status_quantidade"] == "proposta" for p in catalogo["planos"])
    assinatura = catalogo["planos"][2]
    assert assinatura["creditos_por_ciclo"] == 50 and assinatura["ciclo_meses"] == 1
    assert assinatura["status_ciclo"] == "proposta" and not assinatura["renovacao_automatica"]
    assert not assinatura["cobranca_implementada"] and not catalogo["pagamento_disponivel"]
    assert assinatura["acumula_creditos"] is None and assinatura["validade_creditos_dias"] is None


def test_preco_aprovado_e_flag_do_yaml_nao_implementam_assinatura(monkeypatch):
    proposta = P.carregar_catalogo(usar_ambiente=False)
    proposta.update(status="aprovado", aprovado_em="2026-11-12")
    for p in proposta["planos"]:
        p.update(valor_rs=1, cobranca_implementada=True, renovacao_automatica=True)
    monkeypatch.setenv("RAIZ_PROSPECCAO_PLANOS", json.dumps(proposta))
    monkeypatch.setenv("RAIZ_PIX_MODO", "producao")
    monkeypatch.setattr(pix, "chave", lambda: "chave-do-teste")
    catalogo = A.planos()
    assert catalogo["pagamento_disponivel"]
    assert [p["pagamento_disponivel"] for p in catalogo["planos"]] == [True, True, False]
    assert not catalogo["planos"][2]["renovacao_automatica"]


def test_configuracao_v2_exige_exatamente_tres_modalidades(monkeypatch):
    proposta = P.carregar_catalogo(usar_ambiente=False)
    proposta["formato"] = 2
    proposta["planos"].pop()
    monkeypatch.setenv("RAIZ_PROSPECCAO_PLANOS", json.dumps(proposta))
    with pytest.raises(A.ErroAcesso) as erro:
        A.planos()
    assert erro.value.status == 503


def test_assinatura_sem_modalidade_explicita_nao_vira_pacote_pontual(monkeypatch):
    monkeypatch.setenv(
        "RAIZ_PROSPECCAO_PLANOS",
        json.dumps(
            {
                "versao": "teste",
                "status": "provisorio",
                "planos": [{"id": "assinatura", "nome": "Assinatura", "creditos": 50, "valor_rs": None}],
            }
        ),
    )
    assert not A.planos()["planos"][0]["cobranca_implementada"]


def test_cenarios_padrao_sao_simbolicos_sem_buscar_preco_ou_gravar_configuracao(monkeypatch):
    original = P.PRECOS_PADRAO.read_bytes()
    monkeypatch.setenv("RAIZ_PROSPECCAO_PLANOS", "json-invalido-ignorado-pela-simulacao")
    cenarios = P.simular_modalidades()
    assert list(cenarios) == list(P.MODALIDADES)
    for modalidade, c in cenarios.items():
        assert c["tipo"] == "simulacao_hipotetica" and c["modalidade"] == modalidade
        assert c["por_cliente"]["mes"]["receita_bruta_rs"] is None
        assert c["por_cliente"]["ano"]["margem_rs"] is None
        assert "preco_unitario_rs" in c["pendencias"] and "custos" in c["pendencias"]
        assert c["formulas"]["receita_por_cliente_mes"]
        assert "não créditos de carbono" in " ".join(c["avisos"])
    assert cenarios["assinatura"]["por_cliente"]["mes"]["creditos_concedidos"] == 50
    assert cenarios["assinatura"]["por_cliente"]["mes"]["creditos_consumidos"] is None
    assert P.PRECOS_PADRAO.read_bytes() == original


def test_por_ficha_separa_receita_consumo_custo_e_margem_por_cliente_e_carteira():
    c = P.simular_receita(
        "por_ficha",
        {
            "clientes": 3,
            "preco_unitario_rs": "10",
            "unidades_por_cliente_mes": 4,
            "consumo_creditos_por_cliente_mes": 3,
            "custos": {"por_credito_consumido_rs": "2", "fixo_por_cliente_mes_rs": "1", "taxa_sobre_receita_pct": "5"},
        },
    )
    mes, ano = c["por_cliente"]["mes"], c["por_cliente"]["ano"]
    assert (mes["receita_bruta_rs"], mes["creditos_concedidos"], mes["creditos_consumidos"]) == (40, 4, 3)
    assert (mes["custo_total_informado_rs"], mes["margem_rs"], mes["margem_pct"]) == (9, 31, 77.5)
    assert ano["receita_bruta_rs"] == 480 and ano["margem_rs"] == 372
    assert c["carteira"]["mes"]["receita_bruta_rs"] == 120
    assert c["carteira"]["ano"]["margem_rs"] == 1116


def test_por_lote_conta_pacotes_e_creditos_separadamente_sem_assumir_consumo():
    c = P.simular_receita("por_lote", {"preco_unitario_rs": "30", "unidades_por_cliente_mes": "2.5"})
    assert c["por_cliente"]["mes"]["receita_bruta_rs"] == 75
    assert c["por_cliente"]["mes"]["creditos_concedidos"] == 25
    assert c["por_cliente"]["mes"]["creditos_consumidos"] is None
    assert c["por_cliente"]["mes"]["custo_total_informado_rs"] is None
    assert c["por_cliente"]["mes"]["margem_rs"] is None


def test_assinatura_anualiza_por_competencia_e_permite_hipotese_explicita_de_ciclo():
    c = P.simular_receita("assinatura", {"preco_unitario_rs": "90", "ciclo_meses": 3, "creditos_por_unidade": 60})
    assert c["hipotese_quantidade"]["status"] == "hipotese_explicita"
    assert c["por_cliente"]["mes"]["receita_bruta_rs"] == 30
    assert c["por_cliente"]["ano"]["receita_bruta_rs"] == 360
    assert c["por_cliente"]["mes"]["creditos_concedidos"] == 20
    assert "não é calendário" in c["base_temporal"]


def test_receita_zero_nao_vira_divisao_por_zero_nem_margem_percentual_inventada():
    c = P.simular_receita(
        "por_ficha",
        {
            "preco_unitario_rs": 0,
            "unidades_por_cliente_mes": 0,
            "consumo_creditos_por_cliente_mes": 0,
            "custos": {"por_credito_consumido_rs": 0, "fixo_por_cliente_mes_rs": 2, "taxa_sobre_receita_pct": 0},
        },
    )
    assert c["por_cliente"]["mes"]["margem_rs"] == -2
    assert c["por_cliente"]["mes"]["margem_pct"] is None


def test_arredondamento_so_na_exibicao_nao_multiplica_total_ja_arredondado():
    c = P.simular_receita("por_lote", {"clientes": 3, "preco_unitario_rs": "0.01", "unidades_por_cliente_mes": "0.5"})
    assert c["por_cliente"]["mes"]["receita_bruta_rs"] == 0.01
    assert c["carteira"]["mes"]["receita_bruta_rs"] == 0.02
    assert c["por_cliente"]["ano"]["receita_bruta_rs"] == 0.06


def test_receita_pequena_com_custo_alto_permitido_mantem_margem_finita():
    c = P.simular_receita(
        "por_lote",
        {
            "preco_unitario_rs": "0.000001",
            "unidades_por_cliente_mes": "0.000001",
            "consumo_creditos_por_cliente_mes": 1_000_000,
            "custos": {
                "por_credito_consumido_rs": "99999999",
                "fixo_por_cliente_mes_rs": 0,
                "taxa_sobre_receita_pct": 0,
            },
        },
    )
    margem = c["por_cliente"]["mes"]["margem_pct"]
    assert math.isfinite(margem) and margem < 0


def test_consumo_excedente_e_sinalizado_sem_inventar_preco_de_excedente():
    c = P.simular_receita("assinatura", {"consumo_creditos_por_cliente_mes": 51})
    assert any("Consumo supera" in a for a in c["avisos"])
    assert c["por_cliente"]["mes"]["receita_bruta_rs"] is None


@pytest.mark.parametrize(
    "cenario",
    [
        {"preco_unitario_rs": "NaN"},
        {"preco_unitario_rs": "Infinity"},
        {"preco_unitario_rs": -1},
        {"clientes": True},
        {"clientes": 0},
        {"unidades_por_cliente_mes": -1},
        {"consumo_creditos_por_cliente_mes": -1},
        {"creditos_por_unidade": 0},
        {"ciclo_meses": 0},
        {"custos": {"por_credito_consumido_rs": 1}},
        {"custos": {"por_credito_consumido_rs": 1, "fixo_por_cliente_mes_rs": 0, "taxa_sobre_receita_pct": 101}},
        {"preco_unitario_rs": "1e-100000"},
        {"campo_inesperado": 1},
        [],
    ],
)
def test_parametros_invalidos_ou_custos_incompletos_nao_sao_aceitos(cenario):
    with pytest.raises(ValidationError):
        P.simular_receita("por_lote", cenario)


@pytest.mark.parametrize(
    "modalidade,cenario",
    [
        ("por_ficha", {"creditos_por_unidade": 2}),
        ("por_lote", {"ciclo_meses": 1}),
        ("assinatura", {"unidades_por_cliente_mes": 2}),
        ("inexistente", {}),
    ],
)
def test_unidades_incompativeis_nao_mudam_silenciosamente_a_modalidade(modalidade, cenario):
    with pytest.raises(ValueError):
        P.simular_receita(modalidade, cenario)
