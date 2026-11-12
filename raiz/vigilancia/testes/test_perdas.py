"""Regra da Verra: prazo de 30 dias e de 2 anos a partir da descoberta, agrupamento dos alertas no mesmo evento, número
fixo, descarte, magnitude, rascunho do relatório no modelo v5.0, KML e aviso ao cliente."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from raiz.vigilancia import aprendizado, aviso, cruzamento, kml, perdas, projetos, relatorio
from raiz.vigilancia.testes.conftest import HOJE, ocorrencia, ocorrencias, quadrado_m


def _alertas_projeto(oc, regras, areas, hoje=HOJE, poligonos=None):
    pares = [cruzamento.cruzar_projetos(oc, areas)]
    if poligonos is not None:
        pares.append(cruzamento.cruzar_imoveis(oc, poligonos))
    pares = pd.concat([p for p in pares if len(p)], ignore_index=True)
    return cruzamento.montar_alertas(oc, pares, regras, hoje)


def _perdas(proj, alertas, regras, areas, marcacoes=None, eventos=None, registro=None, hoje=HOJE):
    return perdas.calcular(
        proj,
        alertas,
        marcacoes if marcacoes is not None else pd.DataFrame(columns=aprendizado.COLUNAS_MARCACAO),
        eventos,
        registro
        if registro is not None
        else pd.DataFrame(columns=["projeto_id", "numero", "alerta_raiz", "criado_em"]),
        regras,
        hoje,
        areas=areas,
        alertas_imoveis=alertas[alertas.alvo_tipo == "imovel"],
    )


def test_somar_anos_e_situacao():
    assert perdas.somar_anos(dt.date(2024, 2, 29), 2) == dt.date(2026, 2, 28)
    assert perdas.somar_anos(dt.date(2026, 11, 12), 2) == dt.date(2028, 11, 12)
    s = perdas.situacao_prazo
    assert s(dt.date(2026, 12, 1), None, HOJE, 180, 30) == "urgente"
    assert s(dt.date(2027, 3, 1), None, HOJE, 180, 30) == "atencao"
    assert s(dt.date(2028, 3, 1), None, HOJE, 180, 30) == "no_prazo"
    assert s(dt.date(2026, 11, 1), None, HOJE, 180, 30) == "vencido"
    assert s(dt.date(2026, 11, 1), dt.date(2026, 10, 1), HOJE, 180, 30) == "cumprido"


def test_evento_de_perda_com_prazos_relatorio_kml_e_aviso(regras, lista_projetos, cfg, poligonos):
    proj = lista_projetos[0]
    areas = projetos.areas(proj, cfg)
    pub = dt.date(2026, 11, 5)
    oc = ocorrencias(
        ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 100), dt.date(2026, 10, 30), pub),
        # a 200 m e 10 dias depois: mesmo evento
        ocorrencia("mapbiomas_alerta", "m1", "agriculture", quadrado_m(300, 100, 100), dt.date(2026, 11, 8), HOJE),
        # longe no tempo (antes do início do projeto): não conta
        ocorrencia("deter", "velho", "desmatamento_cr", quadrado_m(100, 400, 100), dt.date(2019, 5, 1)),
        # embargo dentro do plantio: alerta, mas não evento de perda sozinho
        ocorrencia("ibama_embargo", "e1", "embargo", quadrado_m(400, 400, 50), dt.date(2026, 10, 1)),
    )
    al = _alertas_projeto(oc, regras, areas, poligonos=poligonos)
    lista, registro = _perdas(proj, al, regras, areas)
    assert len(lista) == 1
    p = lista[0]
    assert p["perda_id"] == "PTESTE_LE1" and p["numero"] == 1
    assert p["estado"] == "suspeita" and set(p["fontes"]) == {"deter", "mapbiomas_alerta"}
    assert p["descoberta_em"] == pub  # a mais cedo entre publicação e primeira leitura
    assert abs(p["area_ha"] - 2.0) < 0.05 and abs(p["classes_ha"]["Plantio"] - 2.0) < 0.05
    pr = p["prazo"]
    assert pr["aviso_verra_ate"] == dt.date(2026, 12, 5) and pr["relatorio_ate"] == dt.date(2028, 11, 5)
    assert pr["aviso_verra_dias_restantes"] == 23 and pr["relatorio_situacao"] == "no_prazo"
    assert pr["relatorio_obrigatorio"] is True
    # magnitude: 2 ha x 100 tCO2e/ha = 200 de 1.000 verificados = 20% > 5%
    assert p["magnitude"]["perda_tco2e"] == 200.0 and p["magnitude"]["pct"] == 20.0
    assert p["magnitude"]["evento_de_perda"] is True
    assert 0.97 < p["confianca"] < 1.0  # 1 - (1-0,85)(1-0,95)
    assert p["imoveis"] and p["imoveis"][0]["cod_imovel"].startswith("PA-1507300-")
    assert registro["numero"].tolist() == [1]

    pt = relatorio.rascunho(proj, p, regras, HOJE, "pt")
    en = relatorio.rascunho(proj, p, regras, HOJE, "en")
    for secao in ("1.1", "1.2", "1.3", "1.4", "2.1", "2.2", "3.1", "3.2", "3.3", "## 4"):
        assert secao in en and secao in pt
    assert "Loss Event Report: 9999, 9999_LE1" in en and "05-Nov-2026" in en and "05-Dec-2026" not in en
    assert "registry@verra.org" in pt and "05/12/2026" in pt and "05/11/2028" in pt
    assert "Magnitude of loss (%) | 20.000" in en
    k = kml.ler(relatorio.kml_da_perda(proj, p))  # duas manchas separadas: um polígono para cada uma
    assert len(k) == len(p["partes"]) == 2 and k[0]["campos"]["loss_event_id"] == "9999_LE1"

    avs = aviso.avisos(p, proj, regras, None, {}, HOJE)
    assert [a["marco"] for a in avs] == ["nova_perda"]
    t = avs[0]["texto"].splitlines()
    assert [x.split(":")[0] for x in t] == ["Fonte", "Fato", "Fazenda", "Prazo", "O que fazer"]
    assert avs[0]["estado"] == "aguardando_aprovacao" and avs[0]["cliente"] == "C-0001"
    assert "PTESTE_LE1" in t[1] and "05/12/2026" in t[3]


def test_numero_fixo_descarte_eventos_e_lembrete(regras, lista_projetos, cfg):
    proj = lista_projetos[0]
    areas = projetos.areas(proj, cfg)
    oc1 = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 100), dt.date(2026, 8, 1)))
    al1 = _alertas_projeto(oc1, regras, areas, hoje=dt.date(2026, 8, 3))
    l1, reg = _perdas(proj, al1, regras, areas, hoje=dt.date(2026, 8, 3))
    assert l1[0]["perda_id"] == "PTESTE_LE1"
    # três meses depois aparece outro evento (novo número) e o primeiro continua LE1
    oc2 = ocorrencias(ocorrencia("deter", "d2", "desmatamento_cr", quadrado_m(450, 450, 100), dt.date(2026, 11, 10)))
    al = pd.concat([al1, _alertas_projeto(oc2, regras, areas)], ignore_index=True)
    l2, reg = _perdas(proj, al, regras, areas, registro=reg)
    ids = {p["perda_id"]: p for p in l2}
    assert set(ids) == {"PTESTE_LE1", "PTESTE_LE2"}
    # LE1: descoberta em 2026-08-03 -> aviso à Verra até 2026-09-02, já vencido sem registro
    le1 = ids["PTESTE_LE1"]
    assert le1["prazo"]["aviso_verra_situacao"] == "vencido"
    assert "lembrete_aviso_verra" in aviso.marcos(le1, regras)
    # fundador registra que avisou a Verra e o campo diz que LE2 é falso
    ev = pd.DataFrame(
        [
            {
                "evento_id": "e1",
                "alvo": "perda",
                "alvo_id": "PTESTE_LE1",
                "tipo": "verra_avisada",
                "data": "2026-10-20",
                "quem": "fundador",
                "nota": "",
                "registrado_em": "2026-10-20T10:00:00",
            }
        ]
    )
    a2 = al[al.chave == "d2"].iloc[0]["alerta_id"]
    m = pd.DataFrame([aprendizado.marcacao(a2, False, "campo", "fundador")])
    l3, reg = _perdas(proj, al, regras, areas, marcacoes=m, eventos=ev, registro=reg)
    ids = {p["perda_id"]: p for p in l3}
    assert ids["PTESTE_LE1"]["prazo"]["aviso_verra_situacao"] == "cumprido"
    assert (
        ids["PTESTE_LE2"]["estado"] == "descartada" and ids["PTESTE_LE2"]["prazo"]["relatorio_situacao"] == "suspenso"
    )
    assert aviso.marcos(ids["PTESTE_LE2"], regras) == []
    assert perdas.situacao_projeto(l3) == "perda_suspeita"
    assert sorted(reg["numero"]) == [1, 2]  # número dado não muda nem se repete


def test_sem_estoque_a_magnitude_diz_o_que_falta(regras, lista_projetos, cfg):
    proj = lista_projetos[0]
    proj.dados.pop("estoque_tco2e_ha")
    proj.dados["vcus_emitidos"] = False
    areas = projetos.areas(proj, cfg)
    oc = ocorrencias(ocorrencia("firms", "N20|2026-11-11|0400", "foco_alta", quadrado_m(200, 200, 375), HOJE))
    lista, _ = _perdas(proj, _alertas_projeto(oc, regras, areas), regras, areas)
    mag = lista[0]["magnitude"]
    assert mag["perda_tco2e"] is None and mag["evento_de_perda"] is None and mag["falta"]
    assert lista[0]["prazo"]["relatorio_situacao"] == "nao_obrigatorio"
    en = relatorio.rascunho(proj, lista[0], regras, HOJE, "en")
    assert "[to be completed" in en and "unavoidable" in en  # fogo: lembra de checar se a reversão é evitável
