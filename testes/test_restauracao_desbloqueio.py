"""Diligência reproduzível das selecionadas, sem liberação ou recálculo."""

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from raiz import restauracao_desbloqueio as D

MODELO = "restauracao-historica+abc"


def tabela() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cod_imovel": "PA-PEQUENA",
                "papel": "titular",
                "area_ha": 0.01,
                "pequena": True,
                "credito_p10": 0.6,
                "credito_p50": 1.0,
                "credito_p90": 1.3,
                "caminho": "matricula_a_conferir",
                "restauracao_versao": MODELO,
                "salvaguardas_pendencias": "jurisdicional_a_conferir; clpi; reparticao_comunidade",
                "custo_credito_usd": 10.0,
                "preco_equilibrio_usd": 20.0,
                "tir_p50": 10.0,
                "tir_projeto": 8.0,
                "vazamento_motivo": "mitigacao_vizinha",
                "vazamento_mitigacao_imovel": "PA-VIZINHA",
            },
            {
                "cod_imovel": "PA-MEDIA",
                "papel": "reserva",
                "area_ha": 9.0,
                "pequena": True,
                "credito_p10": 54.0,
                "credito_p50": 90.0,
                "credito_p90": 117.0,
                "caminho": "matricula_conferida",
                "restauracao_versao": MODELO,
                "salvaguardas_pendencias": "",
                "custo_credito_usd": 30.0,
                "preco_equilibrio_usd": 40.0,
                "tir_p50": 20.0,
                "tir_projeto": 16.0,
                "vazamento_motivo": "sem_gado",
                "vazamento_mitigacao_imovel": "",
            },
            {
                "cod_imovel": "PA-CONCESSAO",
                "papel": "reserva",
                "area_ha": 4.0,
                "pequena": False,
                "credito_p10": 6.0,
                "credito_p50": 10.0,
                "credito_p90": 13.0,
                "caminho": "concessao",
                "restauracao_versao": MODELO,
                "salvaguardas_pendencias": "criterio_reserva_risco",
                "custo_credito_usd": 50.0,
                "preco_equilibrio_usd": 60.0,
                "tir_p50": 90.0,
                "tir_projeto": 70.0,
                "vazamento_motivo": "sem_gado",
                "vazamento_mitigacao_imovel": "",
            },
            {
                "cod_imovel": "PA-ESPERA",
                "papel": "em_espera",
                "area_ha": 99999.0,
                "credito_p10": 99999.0,
                "credito_p50": 99999.0,
                "credito_p90": 99999.0,
                "caminho": "posse_em_titulacao",
                "restauracao_versao": "versao-outra-fora-da-selecao",
                "salvaguardas_pendencias": "clpi",
                "tir_p50": 999.0,
                "custo_credito_usd": 999.0,
            },
            {
                "cod_imovel": "PA-VIZINHA",
                "papel": "mitigacao",
                "area_ha": 88888.0,
                "credito_p50": 88888.0,
            },
        ]
    )


def resumo() -> dict:
    return {
        "uf": "PA",
        "opcao": "barata",
        "data": "2026-11-12",
        "versao_premissas": MODELO,
        "versao_modelo_lote": "lote-historico+def",
        "volume_creditos": 200.0,
        "titulares": 1,
        "reservas": 2,
        "preco_contrato_usd": 55.0,
        "economia": {
            "preco_equilibrio_usd": 59.0,
            "tir_projeto_pct": 9.5,
            "tir_alavancada_pct": 11.9,
        },
        "checklist": [{"id": "pelo_menos_5_da_area", "situacao": "pendente"}],
        "certidoes": {"fracao_exigida": 0.05, "falta_ha": 0.5},
    }


def por_codigo(rel: dict) -> dict:
    return {t["codigo"]: t for t in rel["travas"]}


def test_selecionadas_preserva_pequena_e_nao_soma_espera_ou_mitigacao():
    t = tabela()
    antes = t.copy(deep=True)
    r = D.relatorio(t, resumo())
    assert r["selecionadas"] == {
        "fazendas": 3,
        "ha_restauracao": 13.01,
        "creditos": {"p10": 60.6, "p50": 101.0, "p90": 131.3},
        "pequenas": 2,
    }
    assert por_codigo(r)["clpi"]["ha_restauracao"] == 0.01
    assert por_codigo(r)["vazamento_mitigacao"]["fazendas"] == 1
    assert r["modelo_versao"] == MODELO
    assert r["proveniencia"]["recalculo_realizado"] is False
    pd.testing.assert_frame_equal(t, antes)


def test_travas_sobrepostas_nao_somam_e_referencia_nao_libera():
    refs = {"PA-PEQUENA": {"clpi": "referencia-externa", "titulo_terra": "numero-do-protocolo"}}
    r = D.relatorio(tabela(), resumo(), evidencias=refs)
    c = por_codigo(r)
    for k in ("titulo_terra", "jurisdicional_a_conferir", "clpi", "reparticao_comunidade"):
        assert c[k]["fazendas"] == 1
        assert c[k]["creditos"]["p50"] == 1.0
        assert c[k]["somavel"] is False
        assert c[k]["liberacao_automatica"] is False
    assert c["clpi"]["referencias_recebidas_sem_conferencia"] == 1
    assert c["clpi"]["situacao"] == "pendente_no_snapshot"
    assert r["uniao_fazendas_com_pendencia"]["fazendas"] == 3
    assert r["uniao_fazendas_com_pendencia"]["creditos"]["p50"] == 101
    assert "referencia-externa" not in json.dumps(r)
    assert r["comercializacao"]["situacao"] == "nao_liberada_por_este_relatorio"


def test_terra_documentada_por_classificacao_nao_inclui_car_matricula_a_conferir():
    r = D.relatorio(tabela(), resumo())
    terra = r["terra_meta"]
    assert terra["documentada"]["fazendas"] == 2
    assert terra["documentada"]["creditos"]["p50"] == 100
    assert terra["documentada"]["fracao_meta_pct"] == 50
    assert terra["pendente"]["fazendas"] == 1
    assert terra["pendente"]["fracao_meta_pct"] == 0.5
    assert terra["fracao_meta_faltante_pct"] == 49.5
    assert "classificação publicada" in terra["criterio"]
    assert "CAR" in terra["criterio"]


def test_meta_limitada_cem_por_cento_e_excedente_separado():
    s = resumo()
    s["volume_creditos"] = 80
    terra = D.relatorio(tabela(), s)["terra_meta"]
    assert terra["documentada"]["fracao_meta_pct"] == 100
    assert terra["documentada"]["credito_p50_excedente"] == 20
    assert terra["pendente"]["fracao_meta_pct"] == 0
    assert terra["pendente"]["credito_p50_excedente"] == 1
    assert terra["credito_p50_faltante_meta"] == 0
    s["volume_creditos"] = 100.5
    terra = D.relatorio(tabela(), s)["terra_meta"]
    assert terra["documentada"]["credito_p50_alocado_meta"] == 100
    assert terra["pendente"]["credito_p50_alocado_meta"] == 0.5
    assert terra["pendente"]["credito_p50_excedente"] == 0.5


def test_preco_cenario_custo_equilibrio_e_tir_sao_metricas_diferentes():
    f = D.relatorio(tabela(), resumo())["financeiro"]
    assert f["preco_contrato_cenario_usd_t"] == 55
    assert f["custo_medio_ponderado_usd_t"]["valor"] == pytest.approx(3210 / 101, abs=0.0001)
    assert f["equilibrio_individual_medio_ponderado_usd_t"]["valor"] == pytest.approx(4220 / 101, abs=0.0001)
    assert f["equilibrio_fluxo_lote_usd_t"] == 59
    assert f["tir_mediana_central_alavancada_pct"]["valor"] == 20
    assert f["tir_mediana_central_projeto_pct"]["valor"] == 16
    assert f["tir_fluxo_lote_alavancada_pct"] == 11.9
    assert "Monte Carlo" in f["tir_mediana_central_alavancada_pct"]["interpretacao"]


@pytest.mark.parametrize("faltante", [None, float("nan"), pd.NA, -100.0])
def test_tir_ausente_ou_sentinela_nao_entra_na_mediana(faltante):
    t = tabela()
    t.loc[0, "tir_p50"] = faltante
    m = D.relatorio(t, resumo())["financeiro"]["tir_mediana_central_alavancada_pct"]
    assert m["valor"] is None
    assert m["fazendas_validas"] == 2
    assert m["fazendas_sem_tir"] == 1
    assert m["situacao"] == "indisponivel"


def test_metricas_incompletas_nao_fazem_media_silenciosa_da_amostra_restante():
    t = tabela()
    t.loc[1, "custo_credito_usd"] = float("nan")
    m = D.relatorio(t, resumo())["financeiro"]["custo_medio_ponderado_usd_t"]
    assert m["valor"] is None
    assert m["credito_p50_sem_valor"] == 90
    assert m["fazendas_sem_valor"] == 1


@pytest.mark.parametrize("coluna", ["area_ha", "credito_p10", "credito_p50", "credito_p90"])
@pytest.mark.parametrize("valor", [None, float("inf"), -1, True])
def test_recusa_area_ou_credito_sem_valor_fisico_valido(coluna, valor):
    t = tabela()
    t[coluna] = t[coluna].astype(object)
    t.loc[0, coluna] = valor
    with pytest.raises(ValueError, match=coluna):
        D.relatorio(t, resumo())


def test_recusa_faixa_creditos_desordenada():
    t = tabela()
    t.loc[0, "credito_p10"] = 2
    with pytest.raises(ValueError, match="fora de ordem"):
        D.relatorio(t, resumo())


@pytest.mark.parametrize("mudanca", ["outro_modelo", "modelo_ausente", "duplicado", "resumo_divergente"])
def test_recusa_identidade_modelo_e_contagem_incompativeis(mudanca):
    t, s = tabela(), resumo()
    if mudanca == "outro_modelo":
        t.loc[0, "restauracao_versao"] = "modelo-diferente"
    elif mudanca == "modelo_ausente":
        t.loc[0, "restauracao_versao"] = pd.NA
    elif mudanca == "duplicado":
        t.loc[0, "cod_imovel"] = t.loc[1, "cod_imovel"]
    else:
        s["titulares"] = 1.1
    with pytest.raises(ValueError):
        D.relatorio(t, s)


def test_colunas_novas_toleradas_e_codigo_pendencia_novo_conservado():
    t = tabela()
    t["coluna_nova"] = "indicador"
    t.loc[1, "salvaguardas_pendencias"] = "regra_nova"
    r = D.relatorio(t, resumo())
    trava = por_codigo(r)["regra_nova"]
    assert trava["fazendas"] == 1
    assert trava["situacao"] == "pendente_no_snapshot"
    assert trava["prazo_dias"] is None
    assert trava["liberacao_automatica"] is False


def test_documentos_de_projeto_nao_comprovados_nao_sao_sobreposicao_confirmada():
    r = D.relatorio(tabela(), resumo())
    c = por_codigo(r)
    for codigo in D.GATES_PROJETO:
        assert c[codigo]["fazendas"] == 3
        assert c[codigo]["situacao"] == "nao_comprovada_no_pacote"
        assert c[codigo]["natureza"] == "evidencia_nao_comprovada"
        assert "não afirma" in c[codigo]["incidencia"]
        assert c[codigo]["prazo_dias"] is None
        assert c[codigo]["fontes"]
    assert c["dupla_contagem_jurisdicional"]["fazendas"] == 0
    assert c["dupla_contagem_jurisdicional"]["situacao"] == "nao_sinalizada_no_snapshot"


def test_checklist_e_homologacao_conservados_sem_alterar_resumo():
    s = resumo()
    antes = copy.deepcopy(s)
    r = D.relatorio(tabela(), s)
    assert r["checklist_origem"] == s["checklist"]
    assert r["homologacao_inicial_edital"] == s["certidoes"]
    assert s == antes
    r["checklist_origem"][0]["situacao"] = "outra"
    assert s == antes
    assert "não corresponde à área inteira" in D.markdown(r)


def test_grava_quatro_formatos_agregados_sem_ids_de_imovel(tmp_path):
    r = D.relatorio(tabela(), resumo())
    arquivos = D.gravar(r, tmp_path)
    assert set(arquivos) == {"json", "csv", "markdown", "html"}
    for arquivo in arquivos.values():
        texto = Path(arquivo).read_text()
        assert "PA-PEQUENA" not in texto
        assert "PA-MEDIA" not in texto
    gravado = json.loads(Path(arquivos["json"]).read_text())
    assert gravado == r
    csv = pd.read_csv(arquivos["csv"])
    assert set(csv.codigo) == set(por_codigo(r))
    assert csv.prazo_dias.isna().all()
    assert not csv.somavel.any()


def test_nome_de_regiao_nao_permite_escrever_fora_da_pasta(tmp_path):
    r = D.relatorio(tabela(), resumo())
    r["uf"] = "../fora"
    with pytest.raises(ValueError, match="Identificador"):
        D.gravar(r, tmp_path)


def test_exigencias_projeto_residuais_preservam_fonte_sem_inventar_sla():
    s = resumo()
    s["checklist"] = [
        {
            "id": "integridade",
            "item": "Declaração de integridade do projeto",
            "gravidade": "bloqueia",
            "situacao": "a_conferir",
            "exigido_por": "Minuta do projeto",
            "fonte": "https://example.org/fonte",
            "detalhe": "Conferir a declaração e o responsável signatário.",
        },
        {"id": "area", "gravidade": "bloqueia", "situacao": "ok"},
        {"id": "formato", "gravidade": "media", "situacao": "a_conferir"},
    ]
    r = D.relatorio(tabela(), s)
    assert len(r["exigencias_projeto_pendentes"]) == 1
    i = r["exigencias_projeto_pendentes"][0]
    assert i["codigo"] == "integridade"
    assert i["fazendas"] == 3
    assert i["ha_restauracao"] == 13.01
    assert i["fontes"] == ["https://example.org/fonte"]
    assert i["prazo_dias"] is None
    assert i["somavel"] is False
    assert "não é uma medição" in i["abrangencia"]
    assert "integridade" in D.markdown(r)


def test_identificador_anulavel_nao_vira_identificador_literal():
    t = tabela()
    t.loc[0, "cod_imovel"] = pd.NA
    with pytest.raises(ValueError, match="identificadores"):
        D.relatorio(t, resumo())
