"""Proveniência do código antigo e distribuição do P50 sem recalcular o imóvel."""

import copy
import hashlib
import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest

from raiz import cadt, lote, restauracao
from testes.conftest import AMOSTRA

CATALOGO = "release-github://bernardoemmel/Raiz/dados-privados/cadt_lotes.json"
TAREFA = "desenvolvedor-4e142d4bfca2"


@pytest.fixture
def fonte_2026b(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for origem in AMOSTRA.glob("*.csv"):
        shutil.copyfile(origem, pasta / origem.name)
    manifesto = {}
    for p in pasta.glob("desenvolvedor_*.csv"):
        t = pd.read_csv(p)
        t["restauracao_versao"] = cadt.HISTORICA_2026B
        t.to_csv(p, index=False)
        manifesto[p.name] = {
            "tarefa": "desenvolvedor",
            "versao": TAREFA,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
    (pasta / "_versoes.json").write_text(json.dumps(manifesto))
    return pasta


def test_p50_historico_preservado_com_selecao_atual_e_sem_probabilidade(fonte_2026b, monkeypatch):
    from raiz.regras import historico

    antes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fonte_2026b.iterdir()}
    publicados = {}
    for arquivo in fonte_2026b.glob("desenvolvedor_*.csv"):
        tabela = pd.read_csv(arquivo, dtype={"cod_imovel": str})
        publicados.update(zip(tabela.cod_imovel, tabela.credito_liquido_tco2_contrato, strict=True))
    selecionados = []
    original = lote._selecionar

    def selecionar(*args, **kwargs):
        sel = original(*args, **kwargs)
        carteira = pd.concat([sel["tit"], sel["res"]])
        for codigo, credito in zip(carteira.cod_imovel, carteira.credito_p50, strict=True):
            assert credito == publicados[codigo]
        selecionados.append(sum(publicados[codigo] for codigo in carteira.cod_imovel))
        return sel

    monkeypatch.setattr(lote, "_selecionar", selecionar)
    monkeypatch.setattr(restauracao, "fluxo_p50", lambda *a, **k: pytest.fail("não recalcular previsão"))
    monkeypatch.setattr(restauracao, "cronograma_lote", lambda *a, **k: pytest.fail("não inventar chance histórica"))
    out = cadt.cadt_uf(fonte_2026b, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO)
    assert not out["diagnosticos"] and out["projeto"]
    m = out["metadados"]
    assert m["credito_contrato_p50"] == pytest.approx(selecionados[-1])
    assert m["versoes"]["versao_premissas"] == cadt.HISTORICA_2026B
    assert m["versoes"]["versao_premissas_selecao"] == restauracao.versao()
    assert m["versoes"]["versao_metodo_cronograma"] == m["metodo_cronograma"] == cadt.METODO_2026B
    assert m["probabilidade_historica_lote"] == "nao_disponivel"
    assert m["descontos_reaplicados_ao_p50"] is False
    assert m["versao_tarefa_fonte_verificada"] == TAREFA
    assert m["previsoes_individuais_recalculadas"] is False
    r, _ = historico.carregar(cadt.HISTORICA_2026B)
    forma = historico.forma_curva_2026b(r)
    acumulados = np.cumsum(forma) / np.cumsum(forma)[25] * selecionados[-1]
    for marco in m["marcos"]:
        assert marco["acumulado_p50"] == pytest.approx(acumulados[marco["ano"]])
    assert sum(e["unitCount"] for e in out["projeto"]["estimations"]) == math.floor(selecionados[-1] + 0.5)
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in fonte_2026b.iterdir()} == antes


def test_total_literal_nao_e_reconstruido_do_p50_por_hectare(tmp_path):
    arquivo = tmp_path / "desenvolvedor_1500000.csv"
    pd.DataFrame(
        {
            "cod_imovel": ["sintetico"],
            "credito_liquido_tco2_contrato": [12344],
            "credito_liquido_tco2_ha_contrato_p50": [123.4],
            "restauracao_area_ha": [100],
        }
    ).to_csv(arquivo, index=False)
    oferta = pd.DataFrame({"cod_imovel": ["sintetico"], "credito_p10": [10000], "credito_p50": [12340]})
    corrigida = cadt._oferta_p50_publicado(tmp_path, oferta)
    assert corrigida.credito_p50.tolist() == [12344]
    assert oferta.credito_p50.tolist() == [12340]
    assert corrigida.credito_p10.equals(oferta.credito_p10)


@pytest.mark.parametrize("valor", [None, "ausente", float("inf"), -1, 12.3])
def test_total_literal_invalido_nao_recebe_fallback(tmp_path, valor):
    pd.DataFrame({"cod_imovel": ["sintetico"], "credito_liquido_tco2_contrato": [valor]}).to_csv(
        tmp_path / "desenvolvedor_1500000.csv", index=False
    )
    oferta = pd.DataFrame({"cod_imovel": ["sintetico"], "credito_p50": [12340]})
    with pytest.raises(cadt.CronogramaInvalido, match="total_p50_publicado_nao_comprovado"):
        cadt._oferta_p50_publicado(tmp_path, oferta)


@pytest.mark.parametrize("defeito", ["coluna_ausente", "imovel_ausente", "imovel_duplicado"])
def test_total_literal_exige_correspondencia_unica(tmp_path, defeito):
    tabela = pd.DataFrame({"cod_imovel": ["sintetico"], "credito_liquido_tco2_contrato": [12344]})
    if defeito == "coluna_ausente":
        tabela = tabela.drop(columns="credito_liquido_tco2_contrato")
    elif defeito == "imovel_ausente":
        tabela["cod_imovel"] = "outro_sintetico"
    else:
        tabela = pd.concat([tabela, tabela])
    tabela.to_csv(tmp_path / "desenvolvedor_1500000.csv", index=False)
    oferta = pd.DataFrame({"cod_imovel": ["sintetico"], "credito_p50": [12340]})
    with pytest.raises(cadt.CronogramaInvalido, match="total_p50_publicado_nao_comprovado"):
        cadt._oferta_p50_publicado(tmp_path, oferta)


@pytest.mark.parametrize("defeito", [None, "negativa", "soma", "nao_finita", "zero_com_credito"])
def test_areas_historicas_so_toleram_arredondamento_publicado(tmp_path, defeito):
    linha = {
        "cod_imovel": "sintetico",
        "credito_liquido_tco2_contrato": 1,
        "restauracao_area_ha": 0.1002,
        "restauracao_regeneracao_assistida_ha": 0.1,
        "restauracao_semeadura_direta_ha": 0,
        "restauracao_plantio_total_ha": 0,
        "credito_liquido_tco2_ha_contrato_p50": 10,
        "credito_liquido_tco2_ha_horizonte": 12,
    }
    if defeito == "negativa":
        linha["restauracao_semeadura_direta_ha"] = -0.0001
    elif defeito == "soma":
        linha["restauracao_area_ha"] = 0.1003
    elif defeito == "nao_finita":
        linha["restauracao_area_ha"] = float("inf")
    elif defeito == "zero_com_credito":
        linha["restauracao_area_ha"] = linha["restauracao_regeneracao_assistida_ha"] = 0
    pd.DataFrame([linha]).to_csv(tmp_path / "desenvolvedor_1500000.csv", index=False)
    oferta = pd.DataFrame({"cod_imovel": ["sintetico"], "credito_p50": [1]})
    if defeito:
        with pytest.raises(cadt.CronogramaInvalido, match="areas_historicas_incompativeis"):
            cadt._oferta_p50_publicado(tmp_path, oferta, versao=cadt.HISTORICA_2026B)
    else:
        assert cadt._oferta_p50_publicado(tmp_path, oferta, versao=cadt.HISTORICA_2026B).credito_p50.iloc[0] == 1


@pytest.mark.parametrize("horizonte", [10, 10.1, 10.2, float("inf"), None])
def test_curva_exige_prova_observavel_de_que_teto_nao_atingiu_25(tmp_path, horizonte):
    linha = {
        "cod_imovel": "sintetico",
        "credito_liquido_tco2_contrato": 1,
        "restauracao_area_ha": 0.1,
        "restauracao_regeneracao_assistida_ha": 0.1,
        "restauracao_semeadura_direta_ha": 0,
        "restauracao_plantio_total_ha": 0,
        "credito_liquido_tco2_ha_contrato_p50": 10,
        "credito_liquido_tco2_ha_horizonte": horizonte,
    }
    pd.DataFrame([linha]).to_csv(tmp_path / "desenvolvedor_1500000.csv", index=False)
    oferta = pd.DataFrame({"cod_imovel": ["sintetico"], "credito_p50": [1]})
    if horizonte == 10.2:
        assert cadt._oferta_p50_publicado(tmp_path, oferta, versao=cadt.HISTORICA_2026B).credito_p50.iloc[0] == 1
    else:
        with pytest.raises(cadt.CronogramaInvalido, match="curva_historica_nao_comprovada"):
            cadt._oferta_p50_publicado(tmp_path, oferta, versao=cadt.HISTORICA_2026B)


@pytest.mark.parametrize("defeito", ["ausente", "tarefa_atual", "hash", "lateral_divergente"])
def test_sem_prova_do_codigo_original_bloqueia_antes_da_selecao(fonte_2026b, monkeypatch, defeito):
    manifesto = fonte_2026b / "_versoes.json"
    dados = json.loads(manifesto.read_text())
    nome = next(iter(dados))
    if defeito == "ausente":
        manifesto.unlink()
    elif defeito == "lateral_divergente":
        (fonte_2026b / (nome + ".meta.json")).write_text(json.dumps({**dados[nome], "versao": "adotado-atual"}))
    else:
        dados[nome]["versao" if defeito == "tarefa_atual" else "sha256"] = (
            "adotado-atual" if defeito == "tarefa_atual" else "a" * 64
        )
        manifesto.write_text(json.dumps(dados))
    monkeypatch.setattr(lote, "ler_uf", lambda *a, **k: pytest.fail("não selecionar fonte ambígua"))
    out = cadt.cadt_uf(fonte_2026b, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO)
    assert out["projeto"] is None
    assert out["diagnosticos"] == [{"codigo": "codigo_historico_da_fonte_nao_comprovado"}]


def test_lateral_original_com_hash_substitui_manifesto_de_transporte(fonte_2026b):
    manifesto = fonte_2026b / "_versoes.json"
    dados = json.loads(manifesto.read_text())
    for nome, meta in dados.items():
        (fonte_2026b / (nome + ".meta.json")).write_text(json.dumps(meta))
    manifesto.unlink()
    assert cadt._conferir_tarefa_historica(fonte_2026b, TAREFA)["arquivos_fonte_verificados"] == len(dados)


def test_metodo_e_politica_selecao_mudam_identidade_sem_alterar_p50():
    from raiz.regras import historico

    r, _ = historico.carregar(cadt.HISTORICA_2026B)
    c = historico.cenario("central_r11", r)
    resumo = {
        "data": "2026-11-12",
        "cenario": "central_r11",
        "versao_premissas": cadt.HISTORICA_2026B,
        "versao_otimizador": "selecao-1",
        "versao_premissas_selecao": "premissas-1",
        "versao_metodo_cronograma": cadt.METODO_2026B,
        "cronograma_lote": cadt._cronograma_2026b(1234.5, c, r),
    }
    out = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO, r=r, c=c)
    alterado = copy.deepcopy(resumo)
    alterado["versao_premissas_selecao"] = "premissas-2"
    novo = cadt.projeto_do_resumo(alterado, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO, r=r, c=c)
    assert novo["projeto"]["projectId"] != out["projeto"]["projectId"]
    assert novo["projeto"]["estimations"] == out["projeto"]["estimations"]
    alterado["versao_metodo_cronograma"] = "metodo_inventado"
    with pytest.raises(cadt.CronogramaInvalido, match="metodo_historico_nao_identificado"):
        cadt.projeto_do_resumo(alterado, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO, r=r, c=c)


def test_normalizacao_atual_nao_substitui_cenario_historico(fonte_2026b, monkeypatch):
    from raiz.regras import historico

    r, _ = historico.carregar(cadt.HISTORICA_2026B)
    atual = restauracao.cenario("central_r11", r=r)
    assert atual["reserva_risco"] >= 0.20
    monkeypatch.setattr(lote, "ler_uf", lambda *a, **k: pytest.fail("não selecionar cenário reinterpretado"))
    out = cadt.cadt_uf(fonte_2026b, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO, r=r, c=atual)
    assert out["projeto"] is None
    assert out["diagnosticos"] == [{"codigo": "cenario_historico_nao_comprovado"}]


def test_ausencia_de_caminho_pronto_preserva_prova_sem_fabricar_cronograma(fonte_2026b):
    for arquivo in fonte_2026b.glob("terra_*.csv"):
        tabela = pd.read_csv(arquivo)
        tabela["caminho_terra"] = "posse_em_titulacao"
        tabela.to_csv(arquivo, index=False)
    out = cadt.cadt_uf(fonte_2026b, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO)
    assert out["projeto"] is None
    assert out["diagnosticos"] == [{"codigo": "sem_lote_elegivel"}]
    m = out["metadados"]
    assert m["regra_source_versao"] == m["versoes"]["versao_premissas"] == cadt.HISTORICA_2026B
    assert m["versao_tarefa_fonte_verificada"] == TAREFA
    assert m["versoes"]["versao_metodo_cronograma"] == m["metodo_cronograma"] == cadt.METODO_2026B
    assert m["diagnostico_selecao"]["oferta_com_estimativa"] > 0
    assert m["diagnostico_selecao"]["caminho_pronto"] == m["diagnostico_selecao"]["elegiveis_pedido"] == 0
    assert m["coluna_total_p50"] == "credito_liquido_tco2_contrato"
    assert "cod_imovel" not in json.dumps(out)
