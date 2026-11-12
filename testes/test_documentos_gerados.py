"""Documentos gerados (docxtpl): modelos em dia, faixas P10 a P90, folha do dono em 3 páginas, lote e edital."""

import datetime as dt
import zipfile

import pandas as pd
import pytest
from docx import Document

from raiz import restauracao as R
from raiz.documentos.config import REPO
from raiz.documentos.gerados import checklist_edital, construir_modelos, conversao, folha_dono, relatorio_lote
from raiz.documentos.gerados import faixas as FX
from raiz.documentos.gerados.dados import fmt_moeda, fmt_num, linha_imovel
from raiz.documentos.gerados.edital import ler_edital
from raiz.documentos.simulacao import edital_exemplo, pdf_exemplo

HOJE = dt.date(2026, 11, 12)
AMOSTRA = REPO / "dados" / "amostra"


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("RAIZ_DOCUMENTOS_ENTRADA", str(AMOSTRA))


def _texto(docx) -> str:
    d = Document(str(docx))
    partes = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            partes += [c.text for c in row.cells]
    return "\n".join(partes)


def _imoveis(**filtro):
    df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
    for k, v in filtro.items():
        df = df[df[k] == v]
    return df.cod_imovel.tolist()


def test_modelos_no_git_estao_em_dia(tmp_path):
    novos = construir_modelos.construir(tmp_path)
    for p in novos:
        com_git = construir_modelos.PASTA / p.name
        xml = [zipfile.ZipFile(x).read("word/document.xml") for x in (p, com_git)]
        assert xml[0] == xml[1], f"rode `python -m raiz.documentos modelos`: {p.name} mudou"


def test_formato_brasileiro():
    assert fmt_num(1234.56, 1) == "1.234,6" and fmt_num(None) == "—"
    assert fmt_moeda(956475.4) == "R$ 956.475"


def test_faixas_provisorias_e_da_ficha():
    f = FX.do_imovel({"carbono_tco2_ano": 100.0})
    assert (f.carbono.p10, f.carbono.p50, f.carbono.p90) == (60.0, 100.0, 140.0)
    assert (f.receita.p10, f.receita.p50, f.receita.p90) == (2400.0, 7500.0, 16800.0)
    assert f.fonte == "motor" and f.versao == "faixas-2026a"
    f = FX.do_imovel(
        dict(
            carbono_tco2_ano_p10=1,
            carbono_tco2_ano_p50=2,
            carbono_tco2_ano_p90=5,
            receita_ano_p10=10,
            receita_ano_p50=20,
            receita_ano_p90=50,
            faixas_versao="e3-v1",
            faixas_regra="regra E3",
        )
    )
    assert f.fonte == "ficha" and f.carbono.p90 == 5 and f.versao == "e3-v1"
    assert FX.do_imovel({}).fonte == "sem_dado"
    # com o valor para quem restaura, a faixa é a do Monte Carlo (crédito líquido da área para restaurar)
    vr = {"restauracao_area_ha": 100, "credito_liquido_tco2_ano": 1000, "credito_liquido_tco2_ha_ano_p10": 6,
          "credito_liquido_tco2_ha_ano_p90": 13, "restauracao_cenario": "central_r11",
          "restauracao_versao": "restauracao-x", "carbono_tco2_ano_p50": 2}  # fmt: skip
    f = FX.do_imovel(vr)
    assert f.fonte == "valor_para_quem_restaura" and (f.carbono.p10, f.carbono.p50, f.carbono.p90) == (600, 1000, 1300)
    assert f.receita.p50 == pytest.approx(1000 * 55 * R.cenario()["cambio_brl_usd"]) and f.versao == "restauracao-x"
    # embargo: fica com a conta do motor, que explica por quê
    assert FX.do_imovel({**vr, "embargo_ha": 3}).fonte == "ficha"


def test_carteira_mais_estreita_que_a_soma_e_igual_com_correlacao_1():
    fs = [FX.Faixa(60.0, 100.0, 140.0) for _ in range(30)]
    s = FX.soma(fs)
    c = FX.carteira(fs, rho=0.5)
    assert s.p10 == pytest.approx(1800) and s.p90 == pytest.approx(4200)
    assert s.p10 < c.p10 < c.p50 < c.p90 < s.p90
    assert c.p50 == pytest.approx(3000, rel=0.02)
    c1 = FX.carteira(fs, rho=1.0)
    assert c1.p10 == pytest.approx(s.p10, rel=0.02) and c1.p90 == pytest.approx(s.p90, rel=0.02)
    r = FX.receita_carteira(fs, (40.0, 75.0, 120.0), rho=0.5)
    assert r.p10 < 3000 * 75 < r.p90


def test_imovel_que_cruza_divisa_e_achado_pelo_arquivo_do_municipio():
    li = linha_imovel("PA-1503077-1105FEC8081A45F48E16739A0035CC5E", cod_municipio=1504950)
    assert li["cod_municipio"] == 1504950 and "imoveis" in li["_tabelas"]


def test_folha_do_dono_sem_campo_sobrando_e_sem_cpf():
    from raiz.documentos.gerados.dados import linha_imovel

    # fazenda que pode gerar crédito: a faixa é a do valor para quem restaura (Monte Carlo da E3), a mesma do pedido
    # e do lote; com problema no cadastro, embargo ou bloqueio fica a conta do motor, que explica por quê
    cods = _imoveis(frente="carbono")
    fontes = {c: FX.do_imovel(linha_imovel(c)).fonte for c in cods[:40]}
    cod = next(c for c, f in fontes.items() if f == "valor_para_quem_restaura")
    assert "motor" in fontes.values()  # na amostra também há fazenda com problema no cadastro
    out = folha_dono.gerar(cod, hoje=HOJE)
    t = _texto(out)
    assert "{{" not in t and "{%" not in t
    assert "Sua terra em Nova Esperança do Piriá (PA)" in t and cod in t
    assert "toneladas de gás carbônico por ano" in t and "restauracao-2026c" in t
    assert "CPF" in t  # só na frase de privacidade
    assert "Próximos passos" in t and "Você decide" in t


def test_folha_com_carbono_zero_nao_fala_em_zero_toneladas():
    df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
    cod = df[(df.embargo_ha > 1) & (df.carbono_tco2_ano.fillna(0) == 0)].cod_imovel.iloc[0]
    t = _texto(folha_dono.gerar(cod, hoje=HOJE))
    assert "entre 0 e 0" not in t and "Hoje a conta não mostra área" in t
    assert "embargo do Ibama" in t


@pytest.mark.skipif(conversao.libreoffice() is None, reason="LibreOffice não instalado")
def test_folha_do_dono_tem_tres_paginas():
    for cod in [*_imoveis(frente="carbono")[:2], *_imoveis(frente="desbloqueio")[:1]]:
        pdf = conversao.para_pdf(folha_dono.gerar(cod, hoje=HOJE))
        assert conversao.paginas(pdf) == 3, cod


def test_relatorio_do_lote_mostra_soma_e_carteira():
    cods = _imoveis(frente="carbono")[:8]
    ctx = relatorio_lote.contexto(cods, "teste", cod_municipio=1504950, hoje=HOJE)
    medidas = [f["medida"] for f in ctx["faixas_lote"]]
    assert any("soma" in m for m in medidas) and any("carteira" in m for m in medidas)
    assert len(ctx["imoveis"]) == 8 and "Pequenas entram agrupadas" in ctx["frase_lote"]
    t = _texto(relatorio_lote.gerar(cods, "teste", cod_municipio=1504950, hoje=HOJE))
    assert "{{" not in t and "Carteira = 20.000 sorteios" in t and "correlação 0,6" in t  # a mesma do lote
    with pytest.raises(ValueError):
        relatorio_lote.contexto([], "vazio")


def test_checklist_do_edital_avalia_com_o_motor(tmp_path):
    from raiz.documentos.claude import LeitorClaude
    from raiz.documentos.simulacao import ClienteSimulado

    arq = tmp_path / "edital.pdf"
    arq.write_bytes(pdf_exemplo("EDITAL"))
    lt = ler_edital(arq, leitor=LeitorClaude(cliente=ClienteSimulado([edital_exemplo()])))
    assert lt.erro is None and lt.prompt_versao.startswith("edital-2026a+")
    cods = _imoveis(frente="carbono")[:5]
    ctx = checklist_edital.contexto(lt, cods, cod_municipio=1504950, hoje=HOJE)
    assert [p["faltam"] for p in ctx["prazos"]] == ["8 dias", "33 dias"]
    por_id = {r["descricao"]: r for r in ctx["requisitos"]}
    assert por_id["Área somada do projeto de pelo menos 500 ha"]["situacao"] == "todos atendem"
    assert por_id["Ato constitutivo da empresa ou associação proponente"]["situacao"] == "documento a juntar"
    assert por_id["Imóveis no bioma Amazônia"]["marca"] == "☑"
    assert len(ctx["imoveis"]) == 5
    t = _texto(checklist_edital.gerar(lt, cods, cod_municipio=1504950, hoje=HOJE))
    assert "{{" not in t and "Entrega das propostas" in t
    sem_lote = checklist_edital.contexto(lt, None, hoje=HOJE)
    assert sem_lote["imoveis"] == [] and "Sem lote" in sem_lote["resumo_requisitos"]
