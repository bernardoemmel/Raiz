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

CATALOGO_PRIVADO = "release-github://bernardoemmel/Raiz/dados-privados/cadt_lotes.json"


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
    out = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
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
    out = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2028-02-29", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
    estimativas = out["projeto"]["estimations"]
    assert estimativas[0]["creditingPeriodEnd"] == "2029-02-27"
    assert estimativas[-1]["creditingPeriodEnd"] == "2032-02-28"
    for anterior, proximo in zip(estimativas, estimativas[1:], strict=False):
        assert dt.date.fromisoformat(anterior["creditingPeriodEnd"]) + dt.timedelta(days=1) == dt.date.fromisoformat(
            proximo["creditingPeriodStart"]
        )


def test_versao_e_hipotese_temporal_definem_identidade_e_data_simulacao_nao(pequeno):
    resumo, r, c = pequeno
    a = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
    b = cadt.projeto_do_resumo(
        resumo, "PA", data_inicio="2027-01-01", data_referencia="2026-11-13", r=r, c=c, url_catalogo=CATALOGO_PRIVADO
    )
    assert a["projeto"]["projectId"] == b["projeto"]["projectId"]
    assert b["projeto"]["projectStatusDate"] == "2026-11-13"
    alterado = {**resumo, "versao_premissas": "restauracao-2"}
    novo = cadt.projeto_do_resumo(alterado, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
    assert novo["projeto"]["projectId"] != a["projeto"]["projectId"]
    outro_inicio = cadt.projeto_do_resumo(
        resumo, "PA", data_inicio="2028-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO
    )
    assert outro_inicio["projeto"]["projectId"] != a["projeto"]["projectId"]


@pytest.mark.parametrize("total", [0, -1, float("nan"), float("inf")])
def test_recusa_total_sem_significado(pequeno, total):
    resumo, r, c = pequeno
    resumo["cronograma_lote"]["credito_contrato_p50"] = total
    with pytest.raises(cadt.CronogramaInvalido, match="credito_nao_positivo"):
        cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)


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
        cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)


@pytest.mark.parametrize("prazo", [None, float("nan"), float("inf"), 0, 1.5, True])
def test_prazo_invalido_vira_erro_explicito(pequeno, prazo):
    resumo, r, _ = pequeno
    with pytest.raises(cadt.CronogramaInvalido, match="prazo_invalido"):
        cadt.estimativas_anuais(resumo["cronograma_lote"], "2027-01-01", prazo, R.forma_curva(r))


def test_cenario_divergente_nao_recebe_rotulo_do_padrao(pequeno):
    resumo, r, c = pequeno
    with pytest.raises(cadt.CronogramaInvalido, match="cenario_diverge"):
        cadt.projeto_do_resumo(
            {**resumo, "cenario": "outro"}, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO
        )
    with pytest.raises(cadt.CronogramaInvalido, match="cenario_nao_suportado"):
        cadt.projeto_do_resumo(
            {**resumo, "cenario": "outro"},
            "PA",
            data_inicio="2027-01-01",
            r=r,
            c={**c, "cenario": "outro"},
            url_catalogo=CATALOGO_PRIVADO,
        )


def test_ausencia_de_ancora_ou_produto_nao_invoca_otimizador(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: pytest.fail("não deve ler produto ausente"))
    sem_data = cadt.cadt_uf(pasta, "PA", data_inicio=None, url_catalogo=CATALOGO_PRIVADO)
    assert sem_data["projeto"] is None
    assert sem_data["diagnosticos"] == [{"codigo": "inicio_de_cenario_nao_informado"}]
    sem_produto = cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)
    assert sem_produto["projeto"] is None
    assert sem_produto["diagnosticos"] == [{"codigo": "sem_tabelas_do_produto"}]


def test_sem_fazendas_ou_lote_elegivel_publica_diagnostico(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for nome in ("imoveis_1504950.csv", "desenvolvedor_1504950.csv"):
        (pasta / nome).write_text("cod_imovel,restauracao_versao,restauracao_cenario\n")
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: {"oferta": pd.DataFrame()})
    assert cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)["diagnosticos"] == [
        {"codigo": "sem_fazendas_com_estimativa"}
    ]
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: {"oferta": pd.DataFrame({"cod_imovel": ["nao_publicar"]})})
    monkeypatch.setattr(cadt, "_oferta_p50_publicado", lambda p, oferta, **kw: oferta)
    monkeypatch.setattr(cadt, "_resumo_cronograma", lambda *a, **kw: {"cronograma_lote": None})
    assert cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)["diagnosticos"] == [
        {"codigo": "sem_lote_elegivel"}
    ]


@pytest.mark.parametrize("misturado", [False, True])
@pytest.mark.parametrize(
    "campo,valor,diagnostico",
    [
        ("restauracao_versao", "regra_antiga", "versao_da_fonte_incompativel"),
        ("restauracao_versao", "", "versao_da_fonte_ausente"),
        ("restauracao_versao", None, "versao_da_fonte_ausente"),
        ("restauracao_cenario", "outro_cenario", "cenario_da_fonte_incompativel"),
        ("restauracao_cenario", "", "cenario_da_fonte_ausente"),
        ("restauracao_cenario", None, "cenario_da_fonte_ausente"),
    ],
)
def test_fontes_incompativeis_ou_ausentes_nao_reinterpretam_historico(
    tmp_path, monkeypatch, campo, valor, diagnostico, misturado
):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    (pasta / "imoveis_1504950.csv").write_text("cod_imovel\n")
    tabela = pd.DataFrame(
        [{"cod_imovel": "NAO_PUBLICAR", "restauracao_versao": R.versao(), "restauracao_cenario": "central_r11"}]
    )
    if misturado:
        tabela.to_csv(pasta / "desenvolvedor_1504950.csv", index=False)
    if valor is None:
        tabela = tabela.drop(columns=campo)
    else:
        tabela[campo] = valor
    tabela.to_csv(pasta / "desenvolvedor_1505007.csv", index=False)
    monkeypatch.setattr(L, "ler_uf", lambda *a, **kw: pytest.fail("não deve montar oferta incompatível"))
    out = cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)
    assert out["projeto"] is None
    assert out["diagnosticos"] == [{"codigo": diagnostico}]
    assert "NAO_PUBLICAR" not in json.dumps(out)


def test_mistura_de_versoes_no_mesmo_arquivo_nao_publica_parte_da_uf(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    (pasta / "imoveis_1504950.csv").write_text("cod_imovel\n")
    pd.DataFrame(
        {
            "cod_imovel": ["NAO_PUBLICAR_A", "NAO_PUBLICAR_B"],
            "restauracao_versao": [R.versao(), "regra_antiga"],
            "restauracao_cenario": ["central_r11", "central_r11"],
        }
    ).to_csv(pasta / "desenvolvedor_1504950.csv", index=False)
    monkeypatch.setattr(L, "montar", lambda *a, **kw: pytest.fail("não deve montar lote com versões mistas"))
    out = cadt.cadt_uf(pasta, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)
    assert out["projeto"] is None
    assert out["diagnosticos"] == [{"codigo": "versao_da_fonte_incompativel"}]
    assert "NAO_PUBLICAR" not in json.dumps(out)


def test_catalogo_reune_resultados_ja_persistidos_sem_mutar(pequeno):
    resumo, r, c = pequeno
    pa = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
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


@pytest.fixture(scope="module")
def amostra_atual(tmp_path_factory):
    """O CI compara o lote atual usando cálculo atual em cópia temporária; fixtures históricas ficam intactas."""
    pasta = tmp_path_factory.mktemp("cadt_atual") / "PA"
    pasta.mkdir()
    for arquivo in AMOSTRA.glob("*.csv"):
        shutil.copyfile(arquivo, pasta / arquivo.name)
    R.calcular_municipio(pasta, 1504950, fontes_geo=()).to_csv(pasta / "desenvolvedor_1504950.csv", index=False)
    return pasta


def test_cenario_da_amostra_passando_pelo_lote_real(amostra_atual, monkeypatch):
    pasta = amostra_atual
    totais = {}
    for arquivo in pasta.glob("desenvolvedor_*.csv"):
        tabela = pd.read_csv(arquivo, dtype={"cod_imovel": str})
        totais.update(zip(tabela.cod_imovel, tabela.credito_liquido_tco2_contrato, strict=True))
    original, selecionados = L._selecionar, []

    def selecionar(*args, **kwargs):
        sel = original(*args, **kwargs)
        carteira = pd.concat([sel["tit"], sel["res"]])
        assert carteira.credito_p50.tolist() == [totais[codigo] for codigo in carteira.cod_imovel]
        selecionados.append(sum(totais[codigo] for codigo in carteira.cod_imovel))
        return sel

    monkeypatch.setattr(L, "_selecionar", selecionar)
    out = cadt.cadt_uf(
        pasta, "PA", data_inicio="2027-01-01", data_referencia="2026-11-12", url_catalogo=CATALOGO_PRIVADO
    )
    assert not out["diagnosticos"]
    assert len(out["projeto"]["estimations"]) == 25
    total = out["metadados"]["credito_contrato_p50"]
    assert total == selecionados[-1]
    assert sum(e["unitCount"] for e in out["projeto"]["estimations"]) == math.floor(total + 0.5)
    assert [m["ano"] for m in out["metadados"]["marcos"]] == [7, 12, 17, 22, 25]
    assert out["metadados"]["fazendas"]["pequenas"] > 0
    assert out["metadados"]["cobertura_municipios"]["lidos"] == 1
    assert out["metadados"]["cobertura_municipios"]["no_estado"] == 2
    assert "cod_imovel" not in json.dumps(out)


def test_resumo_cadt_preserva_selecao_p50_e_marcos_do_lote_atual(monkeypatch, amostra_atual):
    selecionar, selecoes = L._selecionar, []

    def registrar(*args, **kwargs):
        sel = selecionar(*args, **kwargs)
        selecoes.append((set(sel["tit"].cod_imovel), set(sel["res"].cod_imovel)))
        return sel

    monkeypatch.setattr(L, "_selecionar", registrar)
    dados = L.ler_pasta(amostra_atual, "PA")
    r, c = R.regra(), R.cenario("central_r11")
    completo = L.montar(dados, r=r, c=c, sensibilidade_ligada=False)["resumo"]
    simples = cadt._resumo_cronograma(dados, r, c)
    assert selecoes[0] == selecoes[-1]
    for campo in ("titulares", "reservas", "pequenas", "versao_premissas", "versao_otimizador", "versao_edital"):
        assert simples[campo] == completo[campo]
    assert simples["cronograma_lote"] == completo["cronograma_lote"]
    assert all(simples["municipios"][k] == completo["municipios"][k] for k in simples["municipios"])


HISTORICA = "restauracao-2026c+421970fd"
COMMIT_HISTORICO = "8eebc6a90bc20bce585520cee81bbebdd1ff93df"
SHA_HISTORICO = "421970fd238e3771fb423b808dca31eadf9efee51a14bd7ded6e98d1d6b49edd"


@pytest.fixture
def fonte_historica(tmp_path):
    """Fixture sintética de proveniência; os créditos da amostra são mantidos literalmente."""
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for arquivo in AMOSTRA.glob("*.csv"):
        shutil.copyfile(arquivo, pasta / arquivo.name)
    for arquivo in pasta.glob("desenvolvedor_*.csv"):
        tabela = pd.read_csv(arquivo)
        tabela["restauracao_versao"] = HISTORICA
        tabela.to_csv(arquivo, index=False)
    return pasta


def test_regra_historica_uniforme_gera_cronograma_sem_recalcular_previsoes(fonte_historica, monkeypatch):
    from raiz.regras.historico import carregar

    r, proveniencia = carregar(HISTORICA)
    assert r["versao_completa"] == HISTORICA
    assert "carteira" not in r and "parcelas" not in r  # sem completar a regra antiga com ciência atual
    assert proveniencia["regra_source_commit"] == COMMIT_HISTORICO
    assert proveniencia["regra_source_sha256"] == SHA_HISTORICO
    assert carregar("regra_inventada") is None
    monkeypatch.setattr(R, "fluxo_p50", lambda *a, **kw: pytest.fail("previsão individual não deve ser refeita"))
    monkeypatch.setattr(L, "montar", lambda *a, **kw: pytest.fail("relatório econômico não deve ser calculado"))
    totais = {}
    for arquivo in fonte_historica.glob("desenvolvedor_*.csv"):
        tabela = pd.read_csv(arquivo, dtype={"cod_imovel": str})
        totais.update(zip(tabela.cod_imovel, tabela.credito_liquido_tco2_contrato, strict=True))
    original, selecionados = L._selecionar, []

    def selecionar(*args, **kwargs):
        sel = original(*args, **kwargs)
        carteira = pd.concat([sel["tit"], sel["res"]])
        assert carteira.credito_p50.tolist() == [totais[codigo] for codigo in carteira.cod_imovel]
        selecionados.append(sum(totais[codigo] for codigo in carteira.cod_imovel))
        return sel

    monkeypatch.setattr(L, "_selecionar", selecionar)
    out = cadt.cadt_uf(
        fonte_historica, "PA", data_inicio="2027-01-01", data_referencia="2026-11-12", url_catalogo=CATALOGO_PRIVADO
    )
    assert not out["diagnosticos"] and len(out["projeto"]["estimations"]) == 25
    m = out["metadados"]
    assert m["credito_contrato_p50"] == selecionados[-1]
    assert m["regra_source_commit"] == COMMIT_HISTORICO and m["regra_source_sha256"] == SHA_HISTORICO
    assert m["regra_source_versao"] == m["versoes"]["versao_premissas"] == HISTORICA
    assert m["versoes"]["versao_otimizador"] == L.versao_modelo()
    assert m["versoes"]["versao_salvaguardas"] == L.S.regra()["versao_completa"]
    assert m["comercializacao"]["situacao"] == "pendente"
    assert m["previsoes_individuais_recalculadas"] is False
    assert m["selecao_lote"] == "otimizador atual aplicado aos créditos publicados"
    assert "cod_imovel" not in json.dumps(out)
    assert sum(e["unitCount"] for e in out["projeto"]["estimations"]) == math.floor(m["credito_contrato_p50"] + 0.5)
    for marco in m["marcos"]:
        assert sum(e["unitCount"] for e in out["projeto"]["estimations"][: marco["ano"]]) == marco["acumulado_inteiro"]


def test_regra_explicita_nunca_eh_substituida_pelo_registro_historico(fonte_historica, monkeypatch):
    import raiz.regras.historico

    monkeypatch.setattr(raiz.regras.historico, "carregar", lambda *a: pytest.fail("regra explícita é estrita"))
    out = cadt.cadt_uf(fonte_historica, "PA", data_inicio="2027-01-01", r=R.regra(), url_catalogo=CATALOGO_PRIVADO)
    assert out["projeto"] is None and out["diagnosticos"] == [{"codigo": "versao_da_fonte_incompativel"}]


def test_versoes_conhecidas_mistas_tambem_recusadas(fonte_historica, monkeypatch):
    arquivo = next(fonte_historica.glob("desenvolvedor_*.csv"))
    tabela = pd.read_csv(arquivo)
    tabela.loc[0, "restauracao_versao"] = R.versao()
    tabela.to_csv(arquivo, index=False)
    monkeypatch.setattr(L, "ler_uf", lambda *a: pytest.fail("não pode selecionar parte da UF"))
    out = cadt.cadt_uf(fonte_historica, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)
    assert out["projeto"] is None and out["diagnosticos"] == [{"codigo": "versao_da_fonte_incompativel"}]


@pytest.mark.parametrize(
    "nome",
    [
        "manifesto.json",
        "restauracao.yaml",
        "restauracao_cambio.yaml",
        "edital_profloresta.yaml",
        "restauracao_calibracao.yaml",
    ],
)
def test_registro_historico_adulterado_nao_publica_cronograma(fonte_historica, tmp_path, monkeypatch, nome):
    from raiz.regras import historico

    pasta = tmp_path / "registro"
    shutil.copytree(historico.PASTA / HISTORICA, pasta / HISTORICA)
    arquivo = pasta / HISTORICA / nome
    arquivo.write_bytes((arquivo.read_bytes() if arquivo.exists() else b"") + b"\n# NAO_PUBLICAR\n")
    monkeypatch.setattr(historico, "PASTA", pasta)
    with pytest.raises(ValueError, match="registro histórico de restauração inválido"):
        historico.carregar(HISTORICA)
    out = cadt.cadt_uf(fonte_historica, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)
    assert out["projeto"] is None and out["diagnosticos"] == [{"codigo": "registro_historico_invalido"}]
    assert "NAO_PUBLICAR" not in json.dumps(out)


def test_cenario_historico_preserva_reserva_original_sem_normalizador_atual():
    from raiz.regras import historico

    r, _ = historico.carregar(HISTORICA)
    c = historico.cenario("central_r11", r)
    assert c["reserva_risco"] == 0.12
    assert R.cenario("central_r11")["reserva_risco"] >= 0.20
    assert c["prazo_anos"] == 25 and c["horizonte_anos"] == 40
    assert c["entregas_anos"] == [7, 12, 17, 22, 25]
    assert c["cambio_brl_usd"] == r["cambio"]["ptax"]


@pytest.mark.parametrize(
    "campos",
    [
        {"jurisdicional_situacao": "sobreposicao", "jurisdicional_sobreposicao_ha": 1.0},
        {"territorio_tradicional": True, "clpi_situacao": "recusada"},
    ],
)
def test_salvaguardas_atuais_bloqueiam_lote_de_creditos_historicos(fonte_historica, campos):
    for arquivo in fonte_historica.glob("desenvolvedor_*.csv"):
        ids = pd.read_csv(arquivo, usecols=["cod_imovel"], dtype=str)
        for campo, valor in campos.items():
            ids[campo] = valor
        ids.to_csv(fonte_historica / arquivo.name.replace("desenvolvedor_", "jurisdicional_"), index=False)
    out = cadt.cadt_uf(fonte_historica, "PA", data_inicio="2027-01-01", url_catalogo=CATALOGO_PRIVADO)
    assert out["projeto"] is None
    assert out["diagnosticos"] == [{"codigo": "sem_lote_elegivel"}]


def test_oferta_sem_avaliacao_de_salvaguardas_nao_burla_guardas(amostra_atual):
    dados = L.ler_pasta(amostra_atual, "PA")
    dados["oferta"] = dados["oferta"].drop(columns=["salvaguardas_planejamento"])
    with pytest.raises(cadt.CronogramaInvalido, match="salvaguardas_da_oferta_ausentes"):
        cadt._resumo_cronograma(dados, R.regra(), R.cenario("central_r11"))


def test_identidade_cadt_inclui_versao_do_lote_e_salvaguardas(pequeno):
    resumo, r, c = pequeno
    base = {**resumo, "versao_modelo_lote": "lote-a", "versao_salvaguardas": "salvaguardas-a"}
    original = cadt.projeto_do_resumo(base, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
    for campo in ("versao_modelo_lote", "versao_salvaguardas"):
        novo = cadt.projeto_do_resumo(
            {**base, campo: "versao-b"}, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO
        )
        assert novo["projeto"]["projectId"] != original["projeto"]["projectId"]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/bernardoemmel/Raiz/releases/download/dados/cadt_lotes.json",
        "release-github://segredo@bernardoemmel/Raiz/dados-privados/cadt_lotes.json",
        CATALOGO_PRIVADO + "?token=NAO_PUBLICAR",
        CATALOGO_PRIVADO + "#fragmento",
        CATALOGO_PRIVADO.replace("cadt_lotes.json", "estados.json"),
    ],
)
def test_catalogo_cadt_exige_destino_privado_sem_credenciais(pequeno, url):
    resumo, r, c = pequeno
    with pytest.raises(cadt.CronogramaInvalido, match="catalogo_privado_invalido"):
        cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=url)


def test_mudar_destino_privado_nao_muda_identidade_cientifica(pequeno):
    resumo, r, c = pequeno
    a = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=CATALOGO_PRIVADO)
    outro = "release-github://raiz/arquivo-restrito/dados/cadt_lotes.json"
    b = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", r=r, c=c, url_catalogo=outro)
    assert a["projeto"]["projectId"] == b["projeto"]["projectId"]
    assert b["projeto"]["projectLink"] == outro + "#" + b["projeto"]["projectId"]
    assert b["metadados"]["escopo"] == "privado"
