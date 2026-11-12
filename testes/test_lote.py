"""Lote do ProFloresta+ (raiz/lote.py): um só cálculo da fazenda ao lote, reserva pela chance alvo, preço mínimo para
12% e 15%, o que destrava o lote, certidões para os 5% homologados, regeneração antes do plantio que o preço não paga,
checklist do edital, relatório e folha do dono. A amostra roda no CI; o Pará inteiro, quando os dados estão na
máquina."""

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from raiz import lote as L
from raiz import lote_relatorio as LR
from raiz import restauracao as R
from testes.conftest import AMOSTRA

RAIZ = Path(__file__).resolve().parents[1]
PA_REAL = RAIZ / "dados" / "armazem_local" / "saida" / "PA"


@pytest.fixture(scope="module")
def amostra():
    return L.ler_pasta(AMOSTRA, "PA")


@pytest.fixture(scope="module")
def lote(amostra):
    return L.montar(amostra)


def test_um_so_calculo_da_fazenda_ao_lote(amostra):
    """Fluxo do lote e ficha usam a mesma versão; a amostra histórica não incorpora o novo piso de 20%."""
    dv = pd.read_csv(AMOSTRA / "desenvolvedor_1504950.csv", low_memory=False, dtype={"cod_imovel": str})
    dv = dv[dv.restauracao_area_ha > 0].head(80)
    linhas = R.linhas_para_refazer(AMOSTRA, 1504950, set(dv.cod_imovel))
    c = R.cenario()
    for li in linhas.values():
        x = R.fluxo_p50(li, c)
        g = R.por_imovel(li, c)
        assert x["area_ha"] == pytest.approx(g["restauracao_area_ha"], abs=1e-3)
        if g["preco_equilibrio_usd_t"] is not None:
            assert x["preco_equilibrio_usd"] == pytest.approx(g["preco_equilibrio_usd_t"], abs=0.01)
    # a oferta não descarta ninguém por tamanho: toda fazenda com área para restaurar entra
    assert len(amostra["oferta"]) == int(
        (pd.read_csv(AMOSTRA / "desenvolvedor_1504950.csv").restauracao_area_ha > 0).sum()
    )
    assert amostra["oferta"].pequena.sum() > 0.8 * len(amostra["oferta"])


def test_fluxo_do_lote_preco_minimo_e_credito_alem_do_contrato():
    c = R.cenario()
    H = int(c["horizonte_anos"])
    v = np.zeros(H + 1)
    v[[7, 12, 17, 22, 25]] = [10, 30, 40, 50, 70]  # créditos por ha vendidos em cada entrega
    ganho = float(c["cambio_brl_usd"]) * 0.6
    K = np.zeros(H + 1)
    K[0] = 15000
    F = -K + v * float(c["preco_usd_t"]) * ganho
    parte = {"area_ha": 100.0, "F": F, "K": K, "B": v * ganho, "vendidos": v}
    fl = R.fluxo_lote([parte, parte], c)
    assert fl["creditos_contrato"] == pytest.approx(2 * 100 * 200) and fl["excesso_creditos"] == 0
    t55, t90 = R.tir_lote(fl, c), R.tir_lote(fl, c, 90)
    assert t90["tir_projeto"] > t55["tir_projeto"] and t90["vpl_rs"] > t55["vpl_rs"]
    p12 = R.preco_para_tir(fl, c, 0.12)
    assert R.tir_lote(fl, c, p12)["tir_alavancada"] == pytest.approx(0.12, abs=1e-3)
    assert R.preco_para_tir(fl, c, 0.15) > p12
    # contrato de 30 mil: os 10 mil a mais saem do preço do contrato e vão ao preço depois do contrato
    fl2 = R.fluxo_lote([parte, parte], c, volume=30_000)
    assert fl2["excesso_creditos"] == pytest.approx(10_000)
    assert fl2["F"].sum() < fl["F"].sum() and fl2["B"].sum() == pytest.approx(
        30_000
        * ganho
        / 0.6
        * (1 - float(c["tributos_receita"]) - float(c["registro_venda_receita"]) - float(c["participacao_dono"]))
    )
    # a multa esperada entra no ano do pagamento
    assert R.fluxo_lote([parte], c, {8: 1000.0})["F"][8] == pytest.approx(parte["area_ha"] * F[8] - 1000.0)


def test_lote_da_amostra_fecha_no_p50_e_diz_o_que_falta_para_a_reserva(lote):
    r = lote["resumo"]
    assert r["cenario"] == "central_r11" and r["versao_premissas"].startswith("restauracao-2026d+")
    assert r["volume_creditos"] == 1_000_000 and r["chance_alvo"] == 0.9
    # quantos municípios entraram (a amostra tem 2 com imóveis, 1 com o valor para quem restaura)
    assert r["municipios"]["no_estado"] == 2 and r["municipios"]["lidos"] == 1 and r["municipios"]["no_lote"] == 1
    assert r["municipios"]["sem_calculo"] == [1507300]
    # titulares cumprem os marcos no P50; a reserva pela chance alvo de 90% não fecha só com a terra pronta
    assert r["fecha_no_p50"] and r["creditos_titulares"] >= r["creditos_precisa_p50"]
    assert r["creditos_precisa_com_reserva"] > r["creditos_precisa_p50"] > r["volume_creditos"]
    assert not r["fecha_com_reserva"]
    assert r["falta_reserva"] == pytest.approx(r["creditos_precisa_com_reserva"] - r["creditos_lote"], abs=1)
    falta = " ".join(r["o_que_falta"])
    assert f"{r['falta_reserva']:,.0f}".replace(",", ".") in falta and "terra em espera destravar" in falta
    assert "1 município do estado" in falta
    # marcos no lote inteiro: com a reserva a chance sobe
    ct, cl = r["cronograma_titulares"], r["cronograma_lote"]
    assert [m["ano"] for m in cl["marcos"]] == [7, 12, 17, 22, 25]
    assert cl["chance_todos"] >= ct["chance_todos"] and cl["marcos"][-1]["limiar"] == pytest.approx(1_000_000)
    # tabela: titulares, reserva, mitigação e em espera; nunca descarta por tamanho
    t = lote["tabela"]
    assert set(t.papel) >= {"titular", "reserva", "em_espera"}
    assert (t.papel == "titular").sum() == r["titulares"] and (t.papel == "reserva").sum() == r["reservas"]
    assert t.cod_imovel.is_unique
    assert not any(re.search(r"nome|cpf|cnpj|telefone", c_, re.I) for c_ in t.columns)


def test_preco_minimo_para_12_e_15_por_cento(lote):
    eco = lote["resumo"]["economia"]
    pm = eco["preco_minimo_usd"]
    assert eco["fazendas_com_fluxo"] == lote["resumo"]["titulares"] + lote["resumo"]["reservas"]
    assert pm["15"]["alavancada"] > pm["12"]["alavancada"] > 0
    assert pm["12"]["projeto"] > pm["12"]["alavancada"]  # o Fundo Clima barato baixa o preço que dá a TIR
    assert eco["tir_alavancada_pct"] < 12  # a US$ 55 o lote fica abaixo de 12%
    assert eco["preco_equilibrio_usd"] > lote["resumo"]["preco_contrato_usd"]


def test_o_que_destrava_o_lote(lote):
    r = lote["resumo"]
    esp, td = r["em_espera"], r["terra_destravada"]
    pt = esp["por_caminho"]["posse_em_titulacao"]
    assert set(esp["por_caminho"]) == {"posse_em_titulacao", "assentamento"}
    assert pt["fazendas"] > 500 and pt["ha_regeneracao"] > 0 and 0 < pt["creditos_regeneracao"] < pt["creditos"]
    assert esp["ha_regeneracao"] == pytest.approx(sum(x["ha_regeneracao"] for x in esp["por_caminho"].values()))
    # se a posse virar título e o assentamento virar parceria, o lote fecha com reserva, mais barato e com TIR maior
    assert td["fecha_com_reserva"] and td["fazendas_destravadas_no_lote"] > 0
    assert td["custo_credito_usd_medio"] < r["custo_credito_usd_medio"]
    assert td["economia"]["tir_alavancada_pct"] > r["economia"]["tir_alavancada_pct"]
    assert td["cronograma_lote"]["chance_todos"] >= 0.88


def test_certidoes_para_os_5_por_cento_homologados(lote):
    ce = lote["resumo"]["certidoes"]
    t = lote["tabela"]
    assert ce["fracao_exigida"] == 0.05 and ce["ha_exigidos"] == pytest.approx(0.05 * ce["ha_lote"], abs=0.1)
    assert ce["por_caminho"]["matricula_conferida"]["fazendas"] == 0  # nenhuma certidão conferida ainda
    assert ce["por_caminho"]["matricula_a_conferir"]["fazendas"] > 0 and ce["falta_ha"] > 0
    assert ce["cumpre_com_pedidos"] and ce["ha_cobertos"] >= ce["falta_ha"]
    assert int(t.pedir_certidao.sum()) == ce["fazendas_a_pedir"] and ce["certidoes_a_pedir"] >= ce["fazendas_a_pedir"]
    assert ce["matriculas_conhecidas"] > 0  # cartório e matrícula do SIGEF (certidoes_<mun>.csv)
    # com a certidão conferida a fazenda já conta como homologada
    o = lote["resumo"]
    x = L._certidoes(t[t.papel.isin(["titular", "reserva"])].assign(caminho="matricula_conferida"), {}, 0.05)
    assert x["falta_ha"] == 0 and x["certidoes_a_pedir"] == 0 and o["certidoes"]["ha_lote"] == x["ha_lote"]


def test_avisa_quando_so_fecha_abaixo_do_equilibrio(lote):
    ab = lote["resumo"]["abaixo_equilibrio"]
    assert ab["preco_usd"] == 55 and ab["fazendas"] > 0 and ab["so_fecha_com_elas"]
    assert "só fecha com" in ab["aviso"] and "abaixo do equilíbrio" in ab["aviso"]
    t = lote["tabela"]
    no_lote = t[t.papel.isin(["titular", "reserva"])]
    assert int(no_lote.abaixo_equilibrio.sum()) == ab["fazendas"]


def test_checklist_do_edital(lote):
    ck = lote["resumo"]["checklist"]
    ed = L.edital()
    assert len(ck) == len(ed["itens"]) == 62
    assert {i["situacao"] for i in ck} <= {"ok", "falha", "pendente", "a_conferir"}
    por = {i["id"]: i for i in ck}
    assert por["pelo_menos_5_da_area"]["situacao"] == "pendente" and "certid" in por["pelo_menos_5_da_area"]["detalhe"]
    assert por["area_de_pelo_menos_3"]["situacao"] == "ok"  # mais de 3 mil ha
    assert sum(i["situacao"] != "a_conferir" for i in ck) >= 20


def test_relatorio_e_folha_do_dono(lote, tmp_path):
    out = LR.gravar_lote(lote, tmp_path)
    r = lote["resumo"]
    assert int(out["folhas_dono"]) == r["titulares"] + r["reservas"]
    html = Path(out["relatorio"]).read_text(encoding="utf-8")
    for trecho in ("Lote pronto para proposta: PA", "1 de 2 do estado", "Mínimo para TIR de 12%",
                   "Mínimo para TIR de 15%", "O que destrava o lote", "matrícula com certidão conferida",
                   "matrícula a conferir", "certidões de matrícula" if r["certidoes"]["certidoes_a_pedir"] != 1
                   else "certidão de matrícula", "Checklist do edital", "abaixo do equilíbrio"):  # fmt: skip
        assert trecho in html, trecho
    resumo = json.loads(Path(out["json"]).read_text(encoding="utf-8"))
    assert resumo["municipios"]["lidos"] == 1 and resumo["economia"]["preco_minimo_usd"]["12"]["alavancada"]
    tab = pd.read_csv(out["csv"])
    assert len(tab) == len(lote["tabela"])
    folha = sorted((tmp_path / "folhas_dono").glob("folha_dono_*.html"))[0].read_text(encoding="utf-8")
    assert "Todo o contato passa pela Raíz" in folha and "a assinatura" in folha
    assert "no total, em 40 anos" in folha and "Gado na mesma área" in folha and "Arrendar a terra" in folha
    # nada de CPF ou CNPJ em nenhum arquivo do lote
    cpf = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
    for f in tmp_path.rglob("*.*"):
        assert not cpf.search(f.read_text(encoding="utf-8")), f


def test_numeros_do_dono_comparam_com_o_gado_e_o_aluguel():
    c, r = R.cenario(), R.regra()
    linha = {"cod_imovel": "PA-1", "cod_municipio_ibge": 1507300, "uf": "PA", "restauracao_area_ha": 100,
             "dono_rs_ha_ano": 300}  # fmt: skip
    x = LR.numeros_dono(linha, c, r)
    assert x["por_ha_ano"][1] == 300 and x["por_ha_ano"][0] < 300 < x["por_ha_ano"][2]
    assert x["por_ha_ano"][0] >= x["piso"] == 24  # o piso não cai com a floresta
    assert x["total_40_anos"][1] == pytest.approx(300 * 100 * 40)
    assert x["aluguel_rs_ha_ano"] == 532 and x["aluguel_fonte"] == "municipio"
    assert x["pecuaria"]["receita_bruta_rs_ha_ano"] > x["pecuaria"]["sobra_referencia_rs_ha_ano"] > 0


@pytest.mark.skipif(len(list(PA_REAL.glob("desenvolvedor_*.csv"))) < 100,
                    reason="dados do Pará inteiro não estão na máquina (Release dados)")  # fmt: skip
def test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta():
    dados = L.ler_uf(PA_REAL.parent, "PA")
    lote = L.montar(dados)
    r = lote["resumo"]
    assert r["municipios"]["no_estado"] == 144 and r["municipios"]["lidos"] == 144
    if r["fecha_com_reserva"]:
        assert r["creditos_lote"] >= r["creditos_precisa_com_reserva"] and not r["o_que_falta"]
        assert r["cronograma_lote"]["chance_todos"] >= 0.88
    else:
        assert r["o_que_falta"] and r["falta_reserva"] > 0


def test_faixa_do_lote_soma_e_carteira_mme102():
    """Portaria MME 102/2016 e PRMS: a faixa do conjunto, não a soma das faixas. Com todo o erro comum, a carteira é
    a soma; com parte própria de cada fazenda, ela fica mais estreita e a soma segue como a régua prudente."""
    p50 = np.full(300, 4000.0)
    x = R.faixa_lote(p50 * 0.6, p50, p50 * 1.3)
    assert x["soma"] == {"p10": pytest.approx(720_000), "p50": 1_200_000, "p90": pytest.approx(1_560_000)}
    assert x["soma"]["p10"] < x["carteira"]["p10"] < x["carteira"]["p50"] < x["carteira"]["p90"] < x["soma"]["p90"]
    assert x["fracao_comum"] == R.regra()["carteira"]["fracao_comum"] and x["sorteios"] == 2**13
    um = R.faixa_lote(p50 * 0.6, p50, p50 * 1.3, fracao_comum=1.0)
    assert um["carteira"]["p10"] == pytest.approx(720_000, rel=0.01)
    assert um["carteira"]["p90"] == pytest.approx(1_560_000, rel=0.01)
    assert R.faixa_lote(p50 * 0.6, p50, p50 * 1.3)["carteira"] == x["carteira"]  # Sobol com semente: reproduz
    assert R.faixa_lote([], [], [])["fazendas"] == 0
    # o pedido usa a mesma premissa em conta fechada
    from raiz.pedidos import otimizador as Z

    fz = Z.faixa_soma(p50 * 0.6, p50, p50 * 1.3)
    assert fz["p10"] == pytest.approx(x["carteira"]["p10"], rel=0.03)
    assert fz["p90"] == pytest.approx(x["carteira"]["p90"], rel=0.03)


def test_parcelas_de_campo_pelo_ar_tool03():
    pc = R.parcelas_campo({"regeneracao_assistida": 2000, "plantio_total": 2000})
    t = 1.6448536269514722
    n = (t / 0.10) ** 2 * (0.5 * 0.6 + 0.5 * 0.4) ** 2
    assert pc["t"] == pytest.approx(t, abs=1e-3) and pc["total"] >= int(np.ceil(n))
    assert pc["por_metodo"]["regeneracao_assistida"] > pc["por_metodo"]["plantio_total"]  # mais heterogênea
    pequeno = R.parcelas_campo({"plantio_total": 10})
    assert pequeno["total"] >= 30  # mínimo do lote (MDL)
    assert R.parcelas_campo({})["total"] == 0


def test_lote_traz_faixa_mme102_parcelas_e_sensibilidade(lote):
    r = lote["resumo"]
    fl, mm = r["faixa"], r["mme102"]
    assert fl["soma"]["p10"] <= fl["carteira"]["p10"] <= fl["carteira"]["p50"] == fl["soma"]["p50"]
    assert mm["p90_excedencia"] == fl["carteira"]["p10"] and mm["revisor_independente"] == "pendente"
    assert 0 < mm["incerteza_padrao_pct"] < 50
    assert r["parcelas"]["total"] >= 30 and set(r["parcelas"]["por_metodo"]) <= set(L.METODOS)
    s = r["sensibilidade"]
    assert {x["entrada"] for x in s} == {"captura", "custo", "preco", "cambio"}
    assert [x["amplitude"] for x in s] == sorted([x["amplitude"] for x in s], reverse=True)
    por = {x["entrada"]: x for x in s}
    assert por["captura"]["tir_baixo"] < por["captura"]["tir_base"] < por["captura"]["tir_alto"]
    assert por["custo"]["tir_baixo"] > por["custo"]["tir_alto"]  # custo no P10 dá TIR maior
    assert por["preco"]["tir_baixo"] == pytest.approx(r["economia"]["tir_alavancada_pct"], abs=0.1)  # US$ 55
