"""Título (E5): chave do registro, achados, regularização da posse e as ligações com a carga, a terra, a oferta e o
lote. Os testes marcados com banco rodam no PostgreSQL do CI."""

import datetime as dt
import json
import shutil

import pandas as pd
import pytest
from sqlalchemy import text

from raiz import terra
from raiz.pedidos import oferta as O
from raiz.titulo import regularizacao as RG
from raiz.titulo.achados import COLUNAS, Achado, chave_registro, da_certidao
from testes.conftest import AMOSTRA

COD = 1504950


@pytest.fixture(autouse=True)
def _documentos_isolados(tmp_path, monkeypatch):
    # a saída de raiz/documentos (certidões conferidas) nunca vem da máquina de quem roda o teste
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs_isolados"))


def linha(**kw):
    base = dict(
        cod_imovel="PA-1504950-AAAA", uf="PA", ha=100.0, m_fiscal=1.5, status_imovel="AT",
        caminho_terra="posse_em_titulacao", desm_total_ha=60.0, desm_pos2008_ha=5.0, desm_pos2016_ha=2.0,
        desm_pos2020_ha=0.0, embargo_ha=0.0, ti_ha=0.0, uc_protecao_integral_ha=0.0, terra_sigef_titulacao_ha=0.0,
        terra_sigef_posse_ha=0.0, terra_publica_ha=0.0, terra_uc_publica_ha=0.0,
    )  # fmt: skip
    base.update(kw)
    return base


def _req(achados, nome):
    return next(a for a in achados if a.regra == f"regularizacao.{nome}")


# --- regras da regularização --------------------------------------------------------------------------------------


def test_so_falta_o_georreferenciamento():
    lo, ac = RG.avaliar(linha())
    assert lo["regularizacao_classe"] == "falta_georreferenciamento"
    assert "georreferenciamento" in lo["regularizacao_proximo_passo"]
    assert lo["regularizacao_orgao"] == "INCRA ou Iterpa"
    assert lo["ocupacao_ate_2008_ha"] == 55.0 and lo["ocupacao_ate_2008_pct"] == 55.0
    assert lo["regularizacao_chance_12m"] == 0.04 and lo["regularizacao_prazo_meses_p50"] == 36
    geo = _req(ac, "georreferenciamento")
    assert geo.situacao == "falta" and geo.gravidade == "reprova" and geo.fase == "regularizacao"
    assert "Lei 10.267/2001" in geo.base
    assert _req(ac, "ocupacao_antes_marco").situacao == "ok"


def test_pronta_em_titulacao_e_impedida():
    assert RG.avaliar(linha(terra_sigef_posse_ha=90.0))[0]["regularizacao_classe"] == "pronta_para_pedir"
    assert RG.avaliar(linha(terra_sigef_titulacao_ha=50.0))[0]["regularizacao_classe"] == "em_titulacao"
    lo, ac = RG.avaliar(linha(ti_ha=5.0, terra_sigef_titulacao_ha=50.0))
    assert lo["regularizacao_classe"] == "impedida" and "terra indígena" in lo["regularizacao_proximo_passo"]
    assert _req(ac, "sobreposicao_tradicional").situacao == "impede"
    assert RG.avaliar(linha(terra_publica_ha=3.0))[0]["regularizacao_classe"] == "impedida"


def test_pendencias_que_seguram_e_as_que_nao_seguram():
    lo, _ = RG.avaliar(linha(terra_sigef_posse_ha=90.0, desm_pos2020_ha=3.0))
    assert lo["regularizacao_classe"] == "pendente" and "depois de 2020" in lo["regularizacao_proximo_passo"]
    # CAR pendente no SICAR não segura; suspenso segura
    lo, ac = RG.avaliar(linha(terra_sigef_posse_ha=90.0, status_imovel="PE"))
    assert lo["regularizacao_classe"] == "pronta_para_pedir" and _req(ac, "car_ativo").situacao == "conferir"
    assert RG.avaliar(linha(terra_sigef_posse_ha=90.0, status_imovel="SU"))[0]["regularizacao_classe"] == "pendente"
    # sem área aberta antes de 2008 no satélite: a prova vem de documentos, e a classe não diz "pronta"
    lo, ac = RG.avaliar(linha(terra_sigef_posse_ha=90.0, desm_total_ha=0.0))
    assert lo["regularizacao_classe"] == "pendente" and _req(ac, "ocupacao_antes_marco").situacao == "conferir"
    # acima de 2.500 ha: só a parte até o limite
    lo, ac = RG.avaliar(linha(ha=3000.0, terra_sigef_posse_ha=2900.0, desm_total_ha=1500.0, desm_pos2008_ha=0.0))
    assert lo["regularizacao_classe"] == "pendente" and _req(ac, "area_limite").situacao == "conferir"
    # os requisitos pessoais nunca se conferem por dado: a Raíz não usa CPF
    assert _req(ac, "requisitos_pessoais").situacao == "conferir"


def test_usucapiao_gratuidade_e_assentamento():
    lo, _ = RG.avaliar(linha(ha=40.0, m_fiscal=0.8, desm_total_ha=30.0))
    assert lo["regularizacao_usucapiao_especial"] and lo["regularizacao_usucapiao_10anos"]
    assert lo["regularizacao_gratuita"] is True
    assert not RG.avaliar(linha())[0]["regularizacao_usucapiao_especial"]  # 100 ha: acima de 50
    lo, _ = RG.avaliar(linha(caminho_terra="assentamento", terra_sigef_assentamento_titulado_ha=20.0))
    assert lo["regularizacao_classe"] == "em_titulacao"
    assert lo["regularizacao_proximo_passo"].startswith("Lote de assentamento")
    assert not lo["regularizacao_usucapiao_especial"]  # assentamento não usucape


def test_fora_da_posse_nao_se_aplica():
    lo, ac = RG.avaliar(linha(caminho_terra="privada_matricula"))
    assert lo["regularizacao_classe"] == "nao_se_aplica" and ac == []
    # sem caminho na linha, calcula das colunas do motor
    lo, _ = RG.avaliar({k: v for k, v in linha().items() if k != "caminho_terra"})
    assert lo["regularizacao_classe"] != "nao_se_aplica"


def test_municipio_da_amostra_e_versao(tmp_path):
    reg, ach = RG.calcular_municipio(AMOSTRA, COD)
    t = pd.read_csv(AMOSTRA / f"terra_{COD}.csv")
    alvo = t.caminho_terra.isin(RG.CAMINHOS_ALVO).sum()
    assert (reg.regularizacao_classe != "nao_se_aplica").sum() == alvo
    assert set(reg.regularizacao_classe) <= set(RG.CLASSES)
    assert list(ach.columns) == COLUNAS and (ach.fase == "regularizacao").all()
    assert ach.registro.str.startswith("car:").all()
    # a amostra que vai no repositório está em dia com a regra
    no_repo = pd.read_csv(AMOSTRA / f"regularizacao_{COD}.csv")
    assert no_repo.regularizacao_regra_versao.iloc[0] == RG.versao()
    assert (no_repo.regularizacao_classe.value_counts() == reg.regularizacao_classe.value_counts()).all()
    # escrever e recalcular
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"terra_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    r = RG.escrever_municipio(pasta, COD)
    assert r["imoveis"] == len(reg) and r["achados"] == len(ach)
    assert RG.versao_do_arquivo(pasta / f"regularizacao_{COD}.csv") == RG.versao()
    assert RG.recalcular(tmp_path) == {"refeitos": [], "em_dia": 1, "erros": []}
    resumo = {x["classe"]: x for x in RG.resumo(pasta, COD)}
    assert sum(x["imoveis"] for x in resumo.values()) == len(reg)


def test_mutiroes_de_georreferenciamento_por_grupo_de_vizinhas():
    m = RG.mutiroes(AMOSTRA, COD)
    reg = pd.read_csv(AMOSTRA / f"regularizacao_{COD}.csv")
    assert sum(x["imoveis"] for x in m) == (reg.regularizacao_classe == "falta_georreferenciamento").sum()
    assert m[0]["imoveis"] > 1 and m[0]["carbono_tco2_ano"] >= m[-1]["carbono_tco2_ano"]
    assert all(len(x["cod_imoveis"]) == x["imoveis"] for x in m)


# --- achados ------------------------------------------------------------------------------------------------------


def test_chave_do_registro_e_achado():
    a = chave_registro("PA-1-X", [("06.842-9", "5.178"), ("068429", "005177")], ["p2", "p1"])
    assert a == "car:PA-1-X|sigef:p1,p2|mat:68429/5177,68429/5178"
    assert chave_registro("PA-1-X", [("068429", "5177"), ("06.842-9", "5.178")], ["p1", "p2"]) == a
    with pytest.raises(ValueError):
        Achado("r", "c", "fase_errada", "x", "ok", "info", "m")
    cpf = "123.456.789-" + "09"  # montado na hora: nenhum arquivo tem CPF por extenso
    ach = Achado("r", "c", "cadeia", "x", "conferir", "confirmar", f"documento {cpf}", valor=cpf)
    assert cpf not in ach.mensagem and cpf not in ach.valor


def test_achados_da_certidao_entram_no_arquivo(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    motivos = [
        {"codigo": "area_menor", "gravidade": "reprova", "texto": "a matrícula tem 100,0 ha"},
        {"codigo": "quebra_cadeia", "gravidade": "confirmar", "texto": "quebra no R-6"},
    ]
    conf = pd.DataFrame([dict(cod_imovel="PA-1504950-AAAA", registro_cns="06.842-9", registro_matricula="5178",
                              situacao="divergente", lido_em="2026-11-12T10:00:00", modelo="claude-opus-5-5",
                              regras_versao="conferencia-2026a+x", motivos_json=json.dumps(motivos))])  # fmt: skip
    ach = da_certidao(conf.iloc[0].to_dict())
    assert [(a.fase, a.situacao, a.gravidade) for a in ach] == [
        ("coerencia", "falta", "reprova"),
        ("cadeia", "conferir", "confirmar"),
    ]
    # a saída de raiz/documentos (outra pasta) entra no achados_<mun>.csv do município
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"terra_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    doc = tmp_path / "docs" / "saida" / "PA"
    doc.mkdir(parents=True)
    conf.to_csv(doc / f"matricula_conferencia_{COD}.csv", index=False)
    RG.escrever_municipio(pasta, COD)
    a = pd.read_csv(pasta / f"achados_{COD}.csv")
    assert set(a[a.fase != "regularizacao"].regra) == {"certidao.area_menor", "certidao.quebra_cadeia"}


# --- ligações: terra, oferta e lote --------------------------------------------------------------------------------


@pytest.fixture
def municipio_com_matricula_a_conferir(tmp_path):
    # Caso real da amostra do motor: matrícula cobre 100% dos 300,397519 ha.
    # Fixar o imóvel e conferir a entrada impede que a cobertura suma por um skip
    # quando a amostra mudar; a certidão abaixo é a única entrada simulada.
    cod = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for tabela in ("imoveis", "filtros"):
        dados = pd.read_csv(AMOSTRA / f"{tabela}_{COD}.csv")
        caso = dados[dados.cod_imovel == cod]
        assert len(caso) == 1, "o caso real de matrícula precisa continuar na amostra"
        caso.to_csv(pasta / f"{tabela}_{COD}.csv", index=False)
        if tabela == "imoveis":
            im = caso.iloc[0]
            assert im.f_matricula >= 0.9 and im.sigef_ha >= 0.5 * im.ha
    return pasta, cod


def test_matricula_conferida_baixa_o_risco_da_terra(tmp_path, monkeypatch, municipio_com_matricula_a_conferir):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    pasta, cod = municipio_com_matricula_a_conferir
    antes = terra.calcular_municipio(pasta, COD).set_index("cod_imovel")
    assert antes.loc[cod, "caminho_terra"] == "privada_matricula"
    assert antes.loc[cod, "risco_terra"] == "medio"
    assert "não conferida" in antes.loc[cod, "risco_terra_motivo"]
    doc = tmp_path / "docs" / "saida" / "PA"  # na saída de raiz/documentos, não na pasta do motor
    doc.mkdir(parents=True)
    pd.DataFrame([dict(cod_imovel=cod, matricula_conferida=True)]).to_csv(doc / f"matricula_{COD}.csv", index=False)
    depois = terra.calcular_municipio(pasta, COD).set_index("cod_imovel")
    assert depois.loc[cod, "risco_terra"] == "baixo"
    assert terra.selo_prata({**depois.loc[cod].to_dict(), "matricula_conferida": True})


def test_oferta_leva_a_classe_e_a_matricula_conferida():
    li = pd.read_csv(AMOSTRA / f"imoveis_{COD}.csv").iloc[0].to_dict()
    t = pd.read_csv(AMOSTRA / f"terra_{COD}.csv")
    cod_priv = t[t.caminho_terra == "privada_matricula"].cod_imovel.iloc[0]
    li.update(
        cod_imovel=cod_priv, caminho_terra="privada_matricula", risco_terra="medio",
        modo_restauracao="regeneracao_assistida", restauracao_area_ha=10.0, regularizacao_classe=None,
    )  # fmt: skip
    o = O.de_linha(li, -47.0, -2.0)
    assert o["caminho"] == "matricula_a_conferir"
    assert O.de_linha({**li, "matricula_conferida": True}, -47.0, -2.0)["caminho"] == "matricula_conferida"
    o = O.de_linha({**li, "caminho_terra": "posse_em_titulacao", "regularizacao_classe": "em_titulacao"}, -47, -2)
    assert o["regularizacao_classe"] == "em_titulacao" and "regularizacao_classe" in O.COLUNAS


def test_lote_diz_quao_perto_do_titulo_esta_a_terra_em_espera():
    from raiz import lote as L

    dados = L.ler_pasta(AMOSTRA, "PA")
    of = dados["oferta"]
    assert "regularizacao_classe" in of.columns and of.regularizacao_classe.notna().any()
    r = L.R.regra()
    esp = L._em_espera(of, "PA", L.R.cenario(r=r), r)
    pr = esp["por_regularizacao"]
    assert sum(x["fazendas"] for x in pr.values()) == esp["fazendas"]
    assert "falta_georreferenciamento" in pr


# --- banco ---------------------------------------------------------------------------------------------------------


def _pasta_com_titulo(tmp_path, caminho_novo: dict | None = None, marca: str | None = None):
    """Pasta do município com regularização e achados. `marca` vira uma coluna a mais em imoveis: muda o hash das
    entradas, para a carga não devolver a rodada que outro teste já carregou com os mesmos arquivos."""
    pasta = tmp_path / "PA"
    pasta.mkdir(exist_ok=True)
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"terra_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    if marca:
        im = pd.read_csv(pasta / f"imoveis_{COD}.csv", low_memory=False)
        im["teste_marca"] = marca
        im.to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    if caminho_novo:
        t = pd.read_csv(pasta / f"terra_{COD}.csv")
        for cod, cam in caminho_novo.items():
            t.loc[t.cod_imovel == cod, "caminho_terra"] = cam
        t.to_csv(pasta / f"terra_{COD}.csv", index=False)
    RG.escrever_municipio(pasta, COD)
    return pasta


@pytest.mark.banco
def test_carga_achados_confirmacao_e_previsao(con, tmp_path, monkeypatch):
    from raiz.aprendizado.congelar import congelar_rodada
    from raiz.carga import carregar_municipio
    from raiz.titulo import banco as TB

    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    pasta = _pasta_com_titulo(tmp_path, marca="carga")
    r = carregar_municipio(con, pasta, COD, dt.date(2026, 11, 1))
    assert r.nova
    n_ach = len(pd.read_csv(pasta / f"achados_{COD}.csv"))
    assert con.execute(text("select count(*) from titulo.achado where rodada_id = :r"), {"r": r.rodada_id}).scalar() \
        == n_ach  # fmt: skip
    classe = con.execute(
        text("""select count(*) from funil.complemento_imovel where rodada_id = :r and tipo = 'regularizacao'
                and atributos->>'regularizacao_classe' = 'falta_georreferenciamento'"""),
        {"r": r.rodada_id},
    ).scalar()
    assert classe > 0
    congelar_rodada(con, r.rodada_id)
    prev = con.execute(
        text("""select count(*), min(horizonte_dias), max(modelo_versao) from aprendizado.previsao
                where modelo = 'regularizacao' and alvo = 'titulo_regularizado_12m' and rodada_id = :r"""),
        {"r": r.rodada_id},
    ).first()
    assert prev[0] > 0 and prev[1] == 365 and prev[2].startswith("regularizacao-2026a+")
    # confirmação: quem é identificador de operador, nunca nome
    p = TB.pendentes(con, limite=5)
    assert p and p[0].gravidade == "reprova"
    with pytest.raises(ValueError):
        TB.confirmar(con, p[0].id, "Fulano de Tal", "confirmado")
    TB.confirmar(con, p[0].id, "fundador", "confirmado", "visto no SIGEF")
    vig = TB.do_imovel(con, p[0].cod_imovel)
    conf = next(a for a in vig if a.id == p[0].id)
    assert conf.confirmado_por == "fundador" and conf.confirmacao_decisao == "confirmado"
    assert p[0].id not in {a.id for a in TB.pendentes(con, p[0].cod_imovel)}
    with pytest.raises(Exception, match="só recebe linhas novas"):
        con.execute(text("update titulo.confirmacao set quem = 'outro'"))


@pytest.mark.banco
def test_gabarito_do_titulo_vem_da_rodada_seguinte(con, tmp_path, monkeypatch):
    from raiz.aprendizado.congelar import congelar_rodada
    from raiz.carga import carregar_municipio

    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    pasta = _pasta_com_titulo(tmp_path, marca="gabarito")
    r1 = carregar_municipio(con, pasta, COD, dt.date(2030, 3, 1))
    assert r1.nova
    congelar_rodada(con, r1.rodada_id)
    reg = pd.read_csv(pasta / f"regularizacao_{COD}.csv")
    titulado = reg[reg.regularizacao_classe == "em_titulacao"].cod_imovel.iloc[0]
    # o título saiu: o imóvel passou a ter matrícula na rodada seguinte
    _pasta_com_titulo(tmp_path, {titulado: "privada_matricula"}, marca="gabarito")
    r2 = carregar_municipio(con, pasta, COD, dt.date(2030, 9, 1))
    assert r2.nova
    g = RG.gabaritar(con, dt.date(2030, 9, 2))
    assert g["titulados"] >= 1
    um = con.execute(
        text("""select valor_num from aprendizado.gabarito where cod_imovel = :c and alvo = :a"""),
        {"c": titulado, "a": RG.ALVO},
    ).scalar()
    assert um == 1.0
    # depois do prazo de 12 meses, quem não titulou recebe 0, e não repete
    g2 = RG.gabaritar(con, dt.date(2031, 3, 5))
    assert g2["sem_titulo_no_prazo"] > 0
    assert RG.gabaritar(con, dt.date(2031, 3, 6))["sem_titulo_no_prazo"] == 0
