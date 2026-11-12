"""O catálogo CADT é uma simulação explícita, com fluxos anuais e sem dados pessoais."""

import copy
import datetime as dt
import json
import math
import shutil

import numpy as np
import pandas as pd
import pytest

from raiz import cadt
from raiz import lote as L
from raiz import restauracao as R
from testes.conftest import AMOSTRA


@pytest.fixture
def pequeno():
    r = {"captura_curva": {"anos": 4, "pontos": [[0, 0], [1, 0], [4, 3]]}}
    c = {"cenario": "central_r11", "prazo_anos": 4}
    forma = R.forma_curva(r)
    total = 10.5
    acum = np.cumsum(forma) * total
    resumo = {
        "data": "2026-11-12",
        "cenario": "central_r11",
        "versao_premissas": "restauracao-1+abc",
        "versao_otimizador": "lote-2+def",
        "versao_edital": "edital-3",
        "municipios": {"no_estado": 2, "lidos": 1, "com_fazenda_elegivel": 1, "no_lote": 1},
        "titulares": 3,
        "reservas": 2,
        "pequenas": 4,
        "cronograma_lote": {
            "credito_contrato_p50": total,
            "marcos": [{"ano": ano, "acumulado_p50": float(acum[ano])} for ano in [2, 4]],
        },
        "nome_proprietario": "NAO_COPIAR",
        "certidoes": {"dados_privados": "NAO_COPIAR"},
    }
    return resumo, r, c


def test_fluxos_anuais_preservam_total_e_marcos_sem_somar_acumulados(pequeno):
    resumo, r, c = pequeno
    out = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c)
    projeto = out["projeto"]
    estimativas = projeto["estimations"]
    assert [e["unitCount"] for e in estimativas] == [0, 2, 3, 6]
    assert sum(e["unitCount"] for e in estimativas) == 11  # 10,5 arredondado, sem somar marcos
    assert estimativas[0]["creditingPeriodStart"] == "2027-01-01"
    assert estimativas[-1]["creditingPeriodEnd"] == "2030-12-31"
    for marco in out["metadados"]["marcos"]:
        assert sum(e["unitCount"] for e in estimativas[: marco["ano"]]) == marco["acumulado_inteiro"]
        assert abs(marco["acumulado_inteiro"] - marco["acumulado_p50"]) <= 0.5
    assert projeto["unitMetric"] == "tCO2e"
    assert projeto["projectStatusDate"] == "2026-11-12"
    assert projeto["registryOfOrigin"] == "Raíz — catálogo de cenários"
    assert projeto["projectStatus"] == "Listed"
    assert "sem registro" in projeto["description"]
    assert "hipotético" in projeto["projectName"]
    assert out["metadados"]["data_inicio_contratada"] is False
    assert out["metadados"]["data_historica_das_fontes"] is None
    assert out["metadados"]["fazendas"]["pequenas"] == 4
    assert "NAO_COPIAR" not in json.dumps(out)
    assert "nome_proprietario" not in json.dumps(out)
    assert set(estimativas[0]) == {"creditingPeriodStart", "creditingPeriodEnd", "unitCount"}


def test_periodos_contiguos_com_ancora_em_ano_bissexto(pequeno):
    resumo, r, c = pequeno
    out = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2028-02-29", r=r, c=c)
    estimativas = out["projeto"]["estimations"]
    assert estimativas[0]["creditingPeriodEnd"] == "2029-02-27"
    assert estimativas[-1]["creditingPeriodEnd"] == "2032-02-28"
    for anterior, proximo in zip(estimativas, estimativas[1:], strict=False):
        assert dt.date.fromisoformat(anterior["creditingPeriodEnd"]) + dt.timedelta(days=1) == dt.date.fromisoformat(
            proximo["creditingPeriodStart"]
        )


def test_versao_e_hipotese_temporal_definem_identidade_e_data_simulacao_nao(pequeno):
    resumo, r, c = pequeno
    a = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c)
    b = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", data_referencia="2026-11-13", r=r, c=c)
    assert a["projeto"]["projectId"] == b["projeto"]["projectId"]
    assert b["projeto"]["projectStatusDate"] == "2026-11-13"
    alterado = {**resumo, "versao_premissas": "restauracao-2"}
    novo = cadt.projeto_do_resumo(alterado, "PA", data_inicio="2027-01-01", r=r, c=c)
    assert novo["projeto"]["projectId"] != a["projeto"]["projectId"]
    outro_inicio = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2028-01-01", r=r, c=c)
    assert outro_inicio["projeto"]["projectId"] != a["projeto"]["projectId"]


@pytest.mark.parametrize("total", [0, -1, float("nan"), float("inf")])
def test_recusa_total_sem_significado(pequeno, total):
    resumo, r, c = pequeno
    resumo["cronograma_lote"]["credito_contrato_p50"] = total
    with pytest.raises(cadt.CronogramaInvalido, match="credito_nao_positivo"):
        cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c)


def test_recusa_curva_e_marcos_inconsistentes(pequeno):
    resumo, r, c = pequeno
    cronograma = resumo["cronograma_lote"]
    with pytest.raises(cadt.CronogramaInvalido, match="captura_no_ano_zero"):
        cadt.estimativas_anuais(cronograma, "2027-01-01", 4, [1, 1, 1, 1, 1])
    with pytest.raises(cadt.CronogramaInvalido, match="curva_invalida"):
        cadt.estimativas_anuais(cronograma, "2027-01-01", 4, [0, 1, -1, 1, 1])
    with pytest.raises(cadt.CronogramaInvalido, match="curva_sem_captura"):
        cadt.estimativas_anuais(cronograma, "2027-01-01", 4, [0, 0, 0, 0, 0])
    cronograma["marcos"][0]["acumulado_p50"] += 1
    with pytest.raises(cadt.CronogramaInvalido, match="marco_diverge_da_curva"):
        cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c)


@pytest.mark.parametrize("prazo", [None, float("nan"), float("inf"), 0, 1.5, True])
def test_prazo_invalido_vira_erro_explicito(pequeno, prazo):
    resumo, r, _ = pequeno
    with pytest.raises(cadt.CronogramaInvalido, match="prazo_invalido"):
        cadt.estimativas_anuais(resumo["cronograma_lote"], "2027-01-01", prazo, R.forma_curva(r))


def test_cenario_divergente_nao_recebe_rotulo_do_padrao(pequeno):
    resumo, r, c = pequeno
    with pytest.raises(cadt.CronogramaInvalido, match="cenario_diverge"):
        cadt.projeto_do_resumo({**resumo, "cenario": "outro"}, "PA", data_inicio="2027-01-01", r=r, c=c)
    with pytest.raises(cadt.CronogramaInvalido, match="cenario_nao_suportado"):
        cadt.projeto_do_resumo(
            {**resumo, "cenario": "outro"}, "PA", data_inicio="2027-01-01", r=r, c={**c, "cenario": "outro"}
        )


def test_ausencia_de_ancora_ou_produto_nao_invoca_otimizador(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: pytest.fail("não deve ler produto ausente"))
    sem_data = cadt.cadt_uf(pasta, "PA", data_inicio=None)
    assert sem_data["projeto"] is None
    assert sem_data["diagnosticos"] == [{"codigo": "inicio_de_cenario_nao_informado"}]
    sem_produto = cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01")
    assert sem_produto["projeto"] is None
    assert sem_produto["diagnosticos"] == [{"codigo": "sem_tabelas_do_produto"}]


def test_sem_fazendas_ou_lote_elegivel_publica_diagnostico(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for nome in ("imoveis_1504950.csv", "desenvolvedor_1504950.csv"):
        (pasta / nome).write_text("cod_imovel\n")
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: {"oferta": pd.DataFrame()})
    assert cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01")["diagnosticos"] == [
        {"codigo": "sem_fazendas_com_estimativa"}
    ]
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: {"oferta": pd.DataFrame({"cod_imovel": ["nao_publicar"]})})
    monkeypatch.setattr(L, "montar", lambda *a, **kw: {"resumo": {"cronograma_lote": None}})
    assert cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01")["diagnosticos"] == [{"codigo": "sem_lote_elegivel"}]


def test_catalogo_reune_resultados_ja_persistidos_sem_mutar(pequeno):
    resumo, r, c = pequeno
    pa = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c)
    ac = {"uf": "AC", "projeto": None, "diagnosticos": [{"codigo": "sem_lote_elegivel"}]}
    estados = {"PA": pa, "AC": ac}
    anterior = copy.deepcopy(estados)
    catalogo = cadt.combinar_estados(estados)
    assert estados == anterior
    assert len(catalogo["projetos"]) == 1
    assert set(catalogo["estados"]) == {"AC", "PA"}
    assert catalogo["estados"]["AC"]["projectId"] is None
    assert catalogo["estados"]["PA"]["projectId"] == pa["projeto"]["projectId"]
    assert "sem registro" in catalogo["aviso"]
    with pytest.raises(ValueError, match="UF diferente"):
        cadt.combinar_estados({"AC": pa})


def test_cenario_da_amostra_passando_pelo_lote_real(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for arquivo in AMOSTRA.glob("*.csv"):
        shutil.copyfile(arquivo, pasta / arquivo.name)
    out = cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01", data_referencia="2026-11-12")
    assert not out["diagnosticos"]
    assert len(out["projeto"]["estimations"]) == 25
    total = out["metadados"]["credito_contrato_p50"]
    assert sum(e["unitCount"] for e in out["projeto"]["estimations"]) == math.floor(total + 0.5)
    assert [m["ano"] for m in out["metadados"]["marcos"]] == [7, 12, 17, 22, 25]
    assert out["metadados"]["fazendas"]["pequenas"] > 0
    assert out["metadados"]["cobertura_municipios"]["lidos"] == 1
    assert out["metadados"]["cobertura_municipios"]["no_estado"] == 2
    assert "cod_imovel" not in json.dumps(out)
