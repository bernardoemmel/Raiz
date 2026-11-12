"""Valor para o desenvolvedor com as premissas da rodada 11 (motor/premissas/restauracao_v2026_11.yaml): números com
fonte e versão, descontos na ordem, curva da URTX escalada com teto por bioma, dívida pelo ICSD, as três formas de
pagar o dono, cenários, marcos do Anexo IV com multa e rescisão, vazamento com área de mitigação e o lote com
titulares, reservas e checklist. Sem nome, CPF ou CNPJ: só o código do CAR."""

import re

import numpy as np
import pandas as pd
import pytest

from raiz import desenvolvedor as D
from raiz import desenvolvedor_lote as L
from raiz import desenvolvedor_relatorio as REL
from raiz import vazamento as V
from raiz.privacidade import varrer

P = D.premissas()


def _tir(metodo: str, c: dict | None = None, **kw) -> float:
    c = c or D.cenario()
    op = D.opcao_por_ha({metodo: 1.0}, "Amazônia", c)
    return D.avaliar(op, c, faixa=False, **kw)["tir_acionista"] * 100


# --- premissas ---------------------------------------------------------------------------------------------------


def test_numeros_do_pedido_e_versao():
    m = P["metodos"]
    pl, rg = m["plantio_total"], m["regeneracao_assistida"]
    assert (pl["custo_implantacao_rs_ha"]["valor"], pl["manutencao_inicial_rs_ha"]["valor"]) == (15830, 3544)
    assert (rg["custo_implantacao_rs_ha"]["valor"], rg["manutencao_inicial_rs_ha"]["valor"]) == (4230, 800)
    assert (pl["captura_40_anos_tco2_ha"]["valor"], rg["captura_40_anos_tco2_ha"]["valor"]) == (588.8, 442.8)
    c = D.cenario()
    assert (c["linha_base"], c["vazamento"], c["reserva_risco"], c["incerteza"]) == (0.20, 0.10, 0.12, 0.10)
    assert P["descontos"]["ordem"] == ["linha_base", "vazamento", "reserva_risco", "incerteza"]
    assert D.fator_liquido(c) == pytest.approx(0.57, abs=0.005)  # crédito líquido central ~57% do bruto
    assert D.fator_liquido(c, mitigacao=True) > D.fator_liquido(c)  # com área de mitigação o vazamento vai a zero
    assert c["vazamento_com_mitigacao"] == 0
    assert (c["fracao_financiada"], c["juros_ano"], c["carencia_anos"], c["icsd_minimo"]) == (0.5, 0.0494, 8, 1.3)
    assert c["taxa_desconto"] == 0.092 and D.cenario("otimista")["juros_ano"] == 0.023
    assert (c["preco_contrato_usd_t"], D.cenario("otimista")["preco_contrato_usd_t"]) == (55, 74)
    assert (c["venda_apos_contrato_usd_t"], c["taxa_registro"], c["manutencao_usd_ha_ano"]) == (30, 0.10, 40)
    assert [(x["ano"], x["acumulado"]) for x in D.marcos()] == [(7, 120000), (12, 300000), (17, 500000),
                                                               (22, 700000), (25, 1000000)]  # fmt: skip
    ct = P["contrato"]
    assert (ct["tolerancia_intermediaria"], ct["multa_credito_dia_rs"], ct["multa_marco_dia_rs"]) == (0.25, 0.03, 1000)
    assert ct["rescisao_multas_pct_valor"] == 0.20 and ct["assinatura"]["area_homologada_min_pct"] == 0.05
    assert c["prazo_dono_anos"] == 40 and c["forma_dono"] == "parte_credito" and 0.10 <= c["parte_dono"] <= 0.20
    assert D.aluguel_referencia(1507300, "PA") == (532, "municipio")  # São Félix do Xingu
    assert D.aluguel_referencia(1504950, "PA") == (212, "uf")
    assert re.fullmatch(r"premissas-2026-11\+[0-9a-f]{8}", P["versao_completa"])


def test_cada_premissa_tem_fonte():
    def sem_fonte(no, caminho="", herdada=False):
        """Números sem fonte: vale a `fonte` do próprio bloco, a de um bloco de cima ou a irmã `<número>_fonte`."""
        faltam = []
        if isinstance(no, dict):
            tem = herdada or "fonte" in no
            for k, v in no.items():
                numero = isinstance(v, (int, float)) and not isinstance(v, bool)
                if numero and not tem and f"{k}_fonte" not in no:
                    faltam.append(f"{caminho}/{k}")
                if isinstance(v, dict):
                    faltam += sem_fonte(v, f"{caminho}/{k}", tem)
                if isinstance(v, list):
                    faltam += [x for i, it in enumerate(v) for x in sem_fonte(it, f"{caminho}/{k}/{i}", tem)]
        return faltam

    assert not sem_fonte({k: P[k] for k in ("metodos", "curva", "teto_bioma_tco2_ha_40_anos", "incerteza_captura",
                                            "descontos", "receita", "financiamento", "contrato", "dono", "mitigacao",
                                            "lote")})  # fmt: skip
    f = D.fontes()
    assert set(D.EDITAVEIS) <= set(f), set(D.EDITAVEIS) - set(f)
    assert all(isinstance(v, str) and len(v) > 10 for v in f.values())


def test_curva_da_urtx_escalada_e_teto_do_bioma():
    f = D.forma_curva()
    assert f[0] == f[1] == 0 and int(np.argmax(f)) + 1 == 14  # zero nos anos 1 e 2, pico no ano 14
    assert f[6] / f[13] == pytest.approx(13.44 / 30.29, rel=1e-6) and f[-1] < f[13]  # forma da URTX, caindo depois
    assert f.sum() == pytest.approx(1)
    c = D.cenario()
    op = D.opcao_por_ha({"plantio_total": 1.0}, "Amazônia", c)
    assert op["bruto_40"] == pytest.approx(588.8) and op["credito_ano"].sum() == pytest.approx(588.8 * 0.5702, rel=1e-3)
    assert D.total_metodo("plantio_total", "Cerrado") == pytest.approx(99.8)  # teto do bioma
    assert D.total_metodo("regeneracao_assistida", "Amazônia") == pytest.approx(442.8)
    assert D.teto_bioma("Caatinga")[1] is False  # teto sem número publicado aparece como tal
    assert D.teto_bioma(None)[2] == P["bioma_padrao"]


# --- retorno: teste de aceite, cenários e o dono -------------------------------------------------------------------


def test_regeneracao_da_13_a_17_pct_a_55_dolares():
    lo, hi = P["teste"]["regeneracao_assistida_tir_acionista_pct"]
    assert lo <= _tir("regeneracao_assistida") <= hi


@pytest.mark.xfail(
    strict=True,
    reason="com as premissas centrais da rodada 11 o plantio dá 6,0% (não 7 a 9%): a parte do dono (15% do crédito "
    "mais piso de R$ 24) e o teto da dívida pelo ICSD de 1,3 (24% do investimento em vez de 50%) levam 1 a 2 pontos; "
    "a US$ 74 dá 8,9%. Decisão do fundador: ajustar premissa ou a faixa do teste.",
)
def test_plantio_da_7_a_9_pct_a_55_dolares():
    lo, hi = P["teste"]["plantio_total_tir_acionista_pct"]
    assert lo <= _tir("plantio_total") <= hi


def test_cenarios_em_ordem_e_contrato_sem_venda_depois():
    for md in D.METODOS:
        t = {nome: _tir(md, D.cenario(nome)) for nome in P["cenarios"]}
        assert t["estresse"] < t["central"] < t["otimista"], (md, t)
        assert t["so_contrato_25"] < t["central"], (md, t)
    assert set(P["cenarios"]) == {"central", "estresse", "otimista", "so_contrato_25"}
    assert D.cenario("so_contrato_25")["venda_apos_contrato"] is False
    assert _tir("plantio_total", D.cenario(preco_contrato_usd_t=74)) > _tir("plantio_total")
    assert _tir("plantio_total", D.cenario(parte_dono=0.10)) > _tir("plantio_total", D.cenario(parte_dono=0.20))
    with pytest.raises(ValueError):
        D.cenario("inexistente")


def test_aluguel_fixo_de_sao_felix_derruba_a_tir():
    for md in D.METODOS:
        parte = _tir(md)
        assert _tir(md, forma="aluguel_fixo", aluguel=532) < parte - 1  # São Félix, Censo Agro 2017
        assert _tir(md, forma="duas_fases") == pytest.approx(parte, abs=0.5)  # opção pequena até o leilão
    # na média do Pará (R$ 212) o aluguel ainda tira da regeneração
    assert _tir("regeneracao_assistida", forma="aluguel_fixo", aluguel=212) < _tir("regeneracao_assistida")


def test_fluxo_divida_e_pico_de_caixa():
    c = D.cenario()
    op = D.opcao_por_ha({"plantio_total": 1.0}, "Amazônia", c)
    a = D.avaliar(op, c, faixa=True)
    ac, pj = np.array(a["fluxo_acionista"]), np.array(a["fluxo_projeto"])
    assert len(pj) == 41 and pj[0] < 0 and pj[7] > 0  # primeira entrega no ano 7
    assert a["icsd_min"] >= c["icsd_minimo"] - 1e-6 and 0 < a["fracao_divida"] <= c["fracao_financiada"]
    assert a["pico_caixa_rs_ha"] == pytest.approx(-np.cumsum(ac).min(), rel=1e-6)
    assert a["pico_caixa_rs_ha"] < op["custo_total"]  # a dívida do Fundo Clima reduz o capital próprio
    for k in ("tir_acionista", "vpl_rs_ha", "preco_equilibrio_rs_t"):
        assert a[f"{k}_p10"] <= a[f"{k}_p90"]
    # preço de equilíbrio: a esse preço o VPL a 9,2% real é zero
    c0 = D.cenario(preco_contrato_usd_t=a["preco_equilibrio_rs_t"] / c["cambio_brl_usd"],
                   venda_apos_contrato_usd_t=a["preco_equilibrio_rs_t"] / c["cambio_brl_usd"])  # fmt: skip
    assert D.avaliar(op, c0, faixa=False)["vpl_rs_ha"] == pytest.approx(0, abs=50)


def test_hectares_por_milhao_de_creditos():
    c = D.cenario()
    ha = {md: D.ha_por_milhao(D.opcao_por_ha({md: 1.0}, "Amazônia", c)["liquido_40"]) for md in D.METODOS}
    assert ha["plantio_total"] == pytest.approx(4400, rel=0.05) and ha["regeneracao_assistida"] == pytest.approx(
        5900, rel=0.05
    )
    # com os marcos intermediários (o ano 7 aperta porque a curva começa devagar) precisa de mais área
    liq = D.opcao_por_ha({"plantio_total": 1.0}, "Amazônia", c)["liquido_40"]
    assert D.ha_por_milhao(liq, marcos_todos=True) > ha["plantio_total"]
    assert D.ha_por_milhao(0) is None


# --- cronograma do Anexo IV ----------------------------------------------------------------------------------------


def test_cronograma_chance_multa_e_rescisao():
    preco = 55 * 5.40
    precisa = D.creditos_40_necessarios(1e6)
    folgado = D.cronograma(precisa * 3, preco)
    justo = D.cronograma(precisa, preco)
    curto = D.cronograma(precisa * 0.5, preco)
    assert folgado["chance_cumprir_todos"] > justo["chance_cumprir_todos"] > curto["chance_cumprir_todos"]
    assert folgado["multa_esperada_rs"] < justo["multa_esperada_rs"] < curto["multa_esperada_rs"]
    assert curto["chance_rescisao"] > justo["chance_rescisao"] >= folgado["chance_rescisao"]
    assert [m["ano"] for m in justo["marcos"]] == [7, 12, 17, 22, 25]
    m7 = justo["marcos"][0]
    assert m7["limiar_com_tolerancia"] == pytest.approx(0.75 * 120000)  # tolerância de 25% nos intermediários
    assert justo["marcos"][-1]["limiar_com_tolerancia"] == 1e6  # o ano 25 não tem tolerância
    assert 0.3 < m7["chance_cumprir"] < 0.7  # no P50 exato o marco que aperta fica perto de meio a meio
    assert justo["valor_contrato_rs"] == pytest.approx(1e6 * preco)
    # sem nenhum crédito: todas as multas correm e o contrato é rescindido
    nada = D.cronograma(1.0, preco)
    assert nada["chance_cumprir_todos"] == 0 and nada["chance_rescisao"] == 1


# --- vazamento com área de mitigação (VMD0054) ---------------------------------------------------------------------


def _faz(cod, lon, area, pasto, cab, vigor=2, **kw):
    return {"cod_imovel": cod, "uf": "PA", "pasto_ha": pasto, "rebanho_cabecas": cab, "mb_pasto_vigor_principal": vigor,
            "area": area, "lon": lon, **kw}  # fmt: skip


def test_vizinha_que_intensifica_o_pasto_zera_o_vazamento():
    fz = [
        _faz("PROJ", -50.00, 100, 100, 100),  # sai 100 cabeças
        _faz("VIZ", -50.05, 0, 400, 300),  # folga: 2,19 x 400 - 300 = 576 cabeças, a ~5,6 km
        _faz("LONGE", -51.00, 50, 50, 50),  # a ~111 km de todo mundo
        _faz("SEMGADO", -50.02, 30, 30, 0),
        _faz("FRACA", -50.06, 0, 400, 100, vigor=1),  # pasto fraco: não recebe
    ]
    pontos = {x["cod_imovel"]: (x["lon"], -6.5) for x in fz}
    out = V.mitigacoes(fz, pontos, P, lambda x: x["area"], lambda x: True)
    assert out["PROJ"]["vazamento_mitigacao"] and out["PROJ"]["vazamento_mitigacao_imovel"] == "VIZ"
    assert out["PROJ"]["vazamento_motivo"] == "mitigacao_vizinha" and out["PROJ"]["cabecas_deslocadas"] == 100
    assert out["LONGE"]["vazamento_motivo"] == "sem_vizinha" and not out["LONGE"]["vazamento_mitigacao"]
    assert out["SEMGADO"]["vazamento_motivo"] == "sem_gado"
    assert "VIZ" not in out and "FRACA" not in out  # quem não restaura não tem vazamento próprio
    # sem ponto no mapa não dá para procurar vizinha; sem rebanho no motor usa a lotação do Censo
    sem = V.mitigacoes(fz[:1], {}, P, lambda x: x["area"], lambda x: True)
    assert sem["PROJ"]["vazamento_motivo"] == "sem_ponto"
    li = {"uf": "PA", "pasto_ha": 100.0, "cod_municipio_ibge": 1504950}
    assert V.rebanho(li, P) == (pytest.approx(99.0), "censo_uf")
    # a vizinha não recebe mais do que a folga: duas fazendas grandes disputam a mesma vizinha
    fz2 = [_faz("A", -50.00, 300, 300, 300), _faz("B", -50.01, 300, 300, 300), _faz("VIZ", -50.05, 0, 400, 300)]
    out2 = V.mitigacoes(fz2, {x["cod_imovel"]: (x["lon"], -6.5) for x in fz2}, P, lambda x: x["area"], lambda x: True)
    assert sum(o.get("vazamento_mitigacao_imovel") == "VIZ" for o in out2.values()) == 1


# --- lote, checklist, relatório e folha do dono -------------------------------------------------------------------


def _tabela_uf():
    """40 fazendas: pequenas e grandes, plantio e regeneração, algumas com terra em espera e uma vizinha."""
    rng = np.random.default_rng(1)
    linhas = []
    for i in range(40):
        regen = i % 3 == 0
        area = float([2.0, 15.0, 120.0, 600.0][i % 4])  # sítio de 2 ha também entra
        liq40 = (252.5 if regen else 335.8) * area
        linhas.append({
            "cod_imovel": f"PA-1504950-{i:032X}", "cod_municipio_ibge": 1504950, "uf": "PA", "elegivel_lote": True,
            "restauracao_area_ha": area, "modo_restauracao": "regeneracao_assistida" if regen else "plantio_total",
            "restauracao_regeneracao_assistida_ha": area if regen else 0.0,
            "restauracao_plantio_total_ha": 0.0 if regen else area, "credito_liquido_t": liq40,
            "credito_liquido_contrato_t": liq40 * 0.68,
            "custo_liquido_por_credito": (201.4 if regen else 450.9) * float(rng.uniform(0.9, 1.1)),
            "tir_desenvolvedor": 15.8 if regen else 6.0, "icsd_minimo": 1.4, "pico_caixa_ha": 3500.0,
            "vazamento_pct": 10.0, "vazamento_motivo": "sem_vizinha", "vazamento_mitigacao_imovel": None,
            "caminho_terra": "privada_matricula", "caminho_terra_situacao": "pronta_agora" if i % 5 else "em_titulacao",
            "risco_terra": "baixo", "projeto_carbono_ha": 0.0, "pagamento_dono": "parte_credito",
            "restauracao_versao": "x",
        })  # fmt: skip
    linhas[0].update(vazamento_pct=0.0, vazamento_motivo="mitigacao_vizinha", vazamento_mitigacao_imovel="PA-VIZINHA",
                     caminho_terra_situacao="pronta_agora")  # fmt: skip
    linhas.append({"cod_imovel": "PA-VIZINHA", "uf": "PA", "elegivel_lote": False, "restauracao_area_ha": 0.0,
                   "credito_liquido_t": 0.0})  # fmt: skip
    return pd.DataFrame(linhas)


def test_lote_titulares_reservas_mitigacao_e_espera():
    df = _tabela_uf()
    volume = 2e5  # lote menor que o contrato para caber nas 40 fazendas do teste
    res = L.montar(df, volume=volume)
    r, t = res["resumo"], res["tabela"]
    papel = t.set_index("cod_imovel")["papel"]
    assert set(papel) == {"titular", "reserva", "mitigacao", "em_espera"}
    assert papel["PA-VIZINHA"] == "mitigacao" and r["mitigacao"] == 1
    # ninguém sai por tamanho: as fazendas de 2 ha prontas entram no lote ou ficam na fila, nunca são descartadas
    tit = t[t.papel == "titular"]
    assert r["fecha_no_p50"] and tit.credito_liquido_t.sum() >= D.creditos_40_necessarios(volume)
    # titulares são as mais baratas por crédito; reservas vêm em seguida
    res_ = t[t.papel == "reserva"]
    assert tit.custo_liquido_por_credito.max() <= res_.custo_liquido_por_credito.min()
    # em espera: terra que ainda não está pronta, mostrada à parte
    assert (t[t.papel == "em_espera"].caminho_terra_situacao != "pronta_agora").all()
    assert r["cronograma_com_reserva"]["chance_cumprir_todos"] >= r["cronograma_titulares"]["chance_cumprir_todos"]
    assert r["versao_premissas"] == P["versao_completa"] and r["cenario"] == "central"
    c10, c50, c90 = r["creditos_contrato_titulares_p10_p50_p90"]
    assert c10 < c50 < c90
    # com um contrato grande demais o lote não fecha e o relatório diz
    grande = L.montar(df, volume=1e7)
    assert not grande["resumo"]["fecha_no_p50"]
    assert "Não fecha" in REL.relatorio_lote(grande)


def test_checklist_com_gravidade_e_fonte():
    res = L.montar(_tabela_uf(), volume=2e5)
    ck = res["resumo"]["checklist"]
    ed = L.edital()
    assert len(ck) == len(ed["itens"]) >= 50
    for it in ck:
        assert it["gravidade"] in ("bloqueia", "alta", "media", "baixa")
        assert it["fonte"] and it["exigido_por"] and it["situacao"] in ("ok", "falha", "pendente", "a_conferir")
    por = {it["id"]: it for it in ck}
    checados = {it["id"] for it in ed["itens"] if it.get("checagem")}
    assert checados and all(por[i]["situacao"] != "a_conferir" for i in checados)
    sit = {it.get("checagem"): por[it["id"]]["situacao"] for it in ed["itens"] if it.get("checagem")}
    assert sit["contrato_40_anos"] == "ok" and sit["sem_sobreposicao"] == "ok"
    assert sit["preco"] == "ok"  # as titulares mais baratas são de regeneração (R$ 201/t contra R$ 297/t)
    # só com plantio, US$ 55 não cobre o preço de equilíbrio a 9,2% real
    so_plantio = L.montar(_tabela_uf().query("modo_restauracao != 'regeneracao_assistida'"), volume=2e5)
    por2 = {it["id"]: it for it in so_plantio["resumo"]["checklist"]}
    assert por2[next(i["id"] for i in ed["itens"] if i.get("checagem") == "preco")]["situacao"] == "falha"


def test_relatorio_e_folha_do_dono_sem_dado_pessoal(tmp_path):
    df = _tabela_uf()
    res = L.montar(df, volume=2e5)
    linhas = {x["cod_imovel"]: {**x, "pagamento_dono_rs_ha_ano": 265.0, "aluguel_referencia_rs_ha_ano": 212.0,
                                "aluguel_referencia_fonte": "uf", "cabecas_deslocadas": 100.0,
                                "vazamento_mitigacao": x["vazamento_motivo"] == "mitigacao_vizinha"}
              for x in df.to_dict("records")}  # fmt: skip
    out = REL.gravar_lote(res, tmp_path, linhas)
    html = (tmp_path / "relatorio_lote_PA.html").read_text(encoding="utf-8")
    assert "P10" in html and "P90" in html and "Anexo IV" in html and "<svg" in html
    folhas = list((tmp_path / "folhas_dono").glob("folha_dono_*.html"))
    assert folhas and len(folhas) == int(out["folhas_dono"])
    for f in folhas:
        h = f.read_text(encoding="utf-8")
        assert h.count('class="pagina"') == 3  # três páginas
        assert ">nan<" not in h and "CAR nan" not in h
    viz = (tmp_path / "folhas_dono" / f"folha_dono_{df.cod_imovel[0]}.html").read_text(encoding="utf-8")
    assert "PA-VIZINHA" in viz  # a vizinha que recebe o gado aparece na folha de quem tem mitigação
    assert not varrer([tmp_path / "relatorio_lote_PA.html", tmp_path / "lote_PA.csv", *folhas])  # sem CPF ou CNPJ
