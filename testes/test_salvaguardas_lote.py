"""Salvaguardas legais nunca se tornam liberação pela falta de informação."""

import datetime as dt
import json
import sqlite3

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from raiz.regras import salvaguardas_lote as S


def linha(**kw):
    return {"cod_imovel": "PA-TESTE-A", "uf": "PA", "ha": 0.2, **kw}


def liberada(**kw):
    return linha(
        jurisdicional_situacao="sem_sobreposicao",
        jurisdicional_evidencia="sha256:documento",
        jurisdicional_fonte="registro-estadual",
        **kw,
    )


def codigos(r):
    return {p["codigo"] for p in r["pendencias"]}


def test_sem_camada_nao_significa_liberacao_e_pequena_continua_no_planejamento():
    r = S.avaliar(linha(), "modelo-1")
    assert r["elegivel_planejamento"] and not r["comercializavel"]
    assert r["jurisdicional"]["programa"] == "SJREDD-PA"
    assert r["jurisdicional"]["situacao"] == "desconhecido"
    assert "jurisdicional_a_conferir" in codigos(r)
    assert r["decisoes"][0]["revisao_humana_disponivel"]


def test_ausencia_de_sobreposicao_exige_evidencia():
    assert S.avaliar(liberada(), "modelo-1")["comercializavel"]
    r = S.avaliar(linha(jurisdicional_situacao="sem_sobreposicao"), "modelo-1")
    assert not r["comercializavel"]


def test_sobreposicao_confirmada_bloqueia_mesmo_que_status_diga_liberada():
    r = S.avaliar(liberada(jurisdicional_sobreposicao_ha=0.001), "modelo-1")
    assert not r["elegivel_planejamento"] and not r["comercializavel"]
    assert "dupla_contagem_jurisdicional" in codigos(r)


@pytest.mark.parametrize(
    "data,geracao,ok",
    [
        ("2026-11-12", "2027-01-01", True),
        ("2027-01-01", "2026-01-01", False),
        (None, "2027-01-01", False),
        ("2026-11-12", None, False),
    ],
)
def test_exclusao_documentada_respeita_periodo(data, geracao, ok):
    r = S.avaliar(
        linha(
            jurisdicional_situacao="exclusao_documentada",
            jurisdicional_sobreposicao_ha=1,
            jurisdicional_evidencia="protocolo-CONAREDD",
            jurisdicional_exclusao_em=data,
            creditos_inicio_em=geracao,
        ),
        "modelo-1",
    )
    assert r["comercializavel"] is ok
    assert r["elegivel_planejamento"] is ok


def test_territorio_tradicional_exige_consulta_e_50_por_cento_mesmo_em_area_minima():
    r = S.avaliar(liberada(quilombo_ha=0.001), "modelo-1")
    assert r["territorio_tradicional"]
    assert r["consulta_livre_previa_informada"]["exigida"]
    assert r["consulta_livre_previa_informada"]["custeio"] == "desenvolvedor"
    assert r["fracao_creditos_comunidade_minima"] == 0.5
    assert {"clpi", "reparticao_comunidade"} <= codigos(r)


@pytest.mark.parametrize("fracao,ok", [(0.49, False), (0.50, True), (0.7, True), (1.1, False)])
def test_contrato_comunidade_nao_confunde_fracao_dos_creditos_com_reserva(fracao, ok):
    r = S.avaliar(
        liberada(
            territorio_tradicional=True,
            clpi_situacao="consentida",
            clpi_evidencia="hash-consulta",
            fracao_creditos_comunidade=fracao,
            reparticao_evidencia="hash-contrato",
        ),
        "modelo-1",
    )
    assert r["comercializavel"] is ok
    assert r["elegivel_planejamento"]


def test_redd_mercado_tem_minimo_70_e_consentimento_recusado_bloqueia():
    r = S.avaliar(
        liberada(
            territorio_tradicional=True,
            tipo_credito="redd_mercado",
            clpi_situacao="recusada",
            fracao_creditos_comunidade=0.5,
            reparticao_evidencia="hash-contrato",
        ),
        "modelo-1",
    )
    assert r["fracao_creditos_comunidade_minima"] == 0.7
    assert not r["elegivel_planejamento"]


def test_consulta_nao_e_comprovada_por_status_sem_evidencia():
    r = S.avaliar(liberada(territorio_tradicional=True, clpi_situacao="consentida"), "modelo-1")
    assert r["consulta_livre_previa_informada"]["situacao"] == "pendente"


@pytest.mark.parametrize("valor", [True, np.bool_(True), 1.0, "sim", "true"])
def test_flag_territorio_vindo_de_dataframe_ou_csv(valor):
    assert S.avaliar(liberada(terra_indigena=valor), "modelo-1")["territorio_tradicional"]


@pytest.mark.parametrize("valor", [False, np.bool_(False), None, np.nan, pd.NA, "false"])
def test_flag_nulo_nao_vira_sobreposicao_confirmada(valor):
    r = S.avaliar(linha(terra_indigena=valor), "modelo-1")
    assert not r["territorio_tradicional"]
    assert r["elegivel_planejamento"] and not r["comercializavel"]


def test_nota_sem_criterio_nao_passa_despercebida():
    r = S.avaliar(liberada(risco_terra="alto", titulo_nota=4), "modelo-1")
    notas = [d for d in r["decisoes"] if d["tipo"] == "nota_risco"]
    assert len(notas) == 2
    assert all("sem justificativa" in d["criterio"] for d in notas)
    assert not r["comercializavel"]
    assert all(d["modelo_versao"] == "modelo-1" for d in notas)


def test_auditoria_preserva_versao_real_do_classificador_de_terra():
    r = S.avaliar(
        liberada(risco_terra="medio", risco_terra_motivo="Matrícula a conferir.", terra_regra_versao="terra-v1"),
        "modelo-1",
    )
    nota = next(d for d in r["decisoes"] if d["tipo"] == "nota_risco")
    assert nota["parametros"]["versao_origem"] == "terra-v1"
    assert nota["criterio"] == "Matrícula a conferir."


def test_reserva_fogo_e_perda_tem_formula_criterio_e_versao():
    from raiz import restauracao as R

    li = liberada(
        fogo_anos_media=12,
        taxa_supressao_secundaria_municipio=0.015,
        restauracao_versao=R.versao(),
        restauracao_cenario="central_r11",
    )
    risco = R.nao_permanencia(li, R.cenario())
    li.update(
        reserva_risco_pct=100 * risco["reserva"],
        reserva_risco_fonte=risco["fonte"],
        fogo_risco_ano_pct=100 * risco["fogo_ano"],
        derrubada_risco_ano_pct=100 * risco["derrubada_ano"],
        perda_natural_40a_pct=100 * risco["perda_40a"],
    )
    r = S.avaliar(li, R.versao())
    nota = next(d for d in r["decisoes"] if d["tipo"] == "nota_risco")
    assert nota["modelo_versao"] == R.versao()
    assert nota["parametros"]["campo"] == "reserva_risco_pct"
    assert nota["parametros"]["fogo_risco_ano_pct"] == pytest.approx(30)
    assert nota["parametros"]["perda_natural_40a_pct"] == pytest.approx(100 * risco["perda_40a"])
    assert "exp(−40" in nota["criterio"] and "mínimo(60%" in nota["criterio"] and "máximo(20%" in nota["criterio"]
    assert nota["revisao_humana_disponivel"] and r["comercializavel"]


def test_reserva_com_historico_ausente_fica_revisavel_e_pendente():
    from raiz import restauracao as R

    r = S.avaliar(
        liberada(reserva_risco_pct=20, reserva_risco_fonte="cenario", restauracao_versao=R.versao()), R.versao()
    )
    assert "criterio_reserva_risco" in codigos(r)
    nota = next(d for d in r["decisoes"] if d["tipo"] == "nota_risco")
    assert "não comprova risco zero" in nota["criterio"]
    assert r["elegivel_planejamento"] and not r["comercializavel"]


def test_reserva_historica_nao_recebe_justificativa_da_regra_atual():
    r = S.avaliar(
        liberada(reserva_risco_pct=12, reserva_risco_fonte="cenario", restauracao_versao="restauracao-antiga"),
        "restauracao-atual",
    )
    nota = next(d for d in r["decisoes"] if d["tipo"] == "nota_risco")
    assert nota["modelo_versao"] == "restauracao-antiga"
    assert "nota histórica" in nota["criterio"]
    assert "criterio_reserva_risco" in codigos(r)


def test_preparar_oferta_preserva_bloqueados_e_pequenos():
    oferta = pd.DataFrame([linha(), linha(cod_imovel="PA-TESTE-B")])
    completas = {"PA-TESTE-B": {"jurisdicional_sobreposicao_ha": 1}}
    nova, decisoes = S.preparar_oferta(oferta, completas, "modelo-1")
    assert len(nova) == 2 and nova.ha.tolist() == [0.2, 0.2]
    assert nova.salvaguardas_planejamento.tolist() == [True, False]
    assert not nova.salvaguardas_comercializavel.any()
    assert len(decisoes) == 2


def test_camada_cruza_em_hectares_sem_contar_poligono_duas_vezes():
    im = gpd.GeoDataFrame(
        {"cod_imovel": ["PA-A", "PA-B"]}, geometry=[box(0, 0, 100, 100), box(300, 300, 400, 400)], crs=5880
    )
    pr = gpd.GeoDataFrame(
        {
            "programa_id": ["p1", "p2", "p3"],
            "fonte": ["f1", "f2", "f3"],
            "inicio_em": ["2026-01-01"] * 3,
            "fim_em": [None, None, "2026-02-01"],
        },
        geometry=[box(0, 0, 50, 100), box(0, 0, 50, 100), box(0, 0, 100, 100)],
        crs=5880,
    )
    r = S.cruzar_jurisdicional(im, pr, dt.date(2026, 11, 12))
    assert r.iloc[0].jurisdicional_sobreposicao_ha == pytest.approx(0.5)
    assert r.iloc[0].jurisdicional_programa == "p1; p2"
    assert r.iloc[1].jurisdicional_situacao == "desconhecido"  # fora desta camada não comprova catálogo completo


def test_decisoes_sao_versionadas_idempotentes_e_aceitam_revisao_persistente(tmp_path):
    d = S.decisao("PA-A", "exclusao", "Embargo ativo acima de zero hectare.", "Embargo: 1 ha.", "modelo-1")
    d2 = S.decisao("PA-A", "exclusao", "Embargo ativo acima de zero hectare.", "Embargo: 1 ha.", "modelo-2")
    assert d["id"] != d2["id"]
    arquivo, banco = tmp_path / "decisoes.jsonl", tmp_path / "revisoes.sqlite"
    assert S.gravar_decisoes(arquivo, [d, d]) == 1
    assert S.gravar_decisoes(arquivo, [d2]) == 1
    pedido = S.pedir_revisao_humana(banco, arquivo, d["id"], "PA-A", "corrigir_dado")
    assert S.pedir_revisao_humana(banco, arquivo, d["id"], "PA-A") == pedido
    assert pedido["situacao"] == "aguardando_pessoa"
    with sqlite3.connect(banco) as con:
        row = con.execute("SELECT decisao_json FROM revisao_humana").fetchone()
    assert json.loads(row[0])["criterio"] == d["criterio"]
    with pytest.raises(ValueError, match="imóvel"):
        S.pedir_revisao_humana(banco, arquivo, d["id"], "PA-B")


def test_trilha_recusa_identidade_e_pedido_nao_guarda_texto_pessoal(tmp_path):
    with pytest.raises(ValueError, match="pessoais"):
        S.decisao("PA-A", "exclusao", "critério", "texto", "modelo-1", nome="pessoa")
    with pytest.raises(ValueError, match="motivo"):
        S.pedir_revisao_humana(tmp_path / "r.sqlite", tmp_path / "decisoes.jsonl", "x", "PA-A", "texto livre")
