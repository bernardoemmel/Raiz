"""Meta FLAG pela GHG Protocol LSR v1.1: o que conta, sem dupla contagem, simulador, requisitos, Requirement 7 e versão
da regra (recálculo quando o padrão muda)."""

import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from raiz import flag as F
from testes.conftest import AMOSTRA


def _linha(**kw):
    base = {
        "cod_imovel": "PA-1-A",
        "uf": "PA",
        "bioma": "Amazônia",
        "alem_RL_ha": 100.0,
        "app_recompor_ha": 10.0,
        "pasto_ha": 80.0,
        "mb_agricultura_2025_ha": 30.0,
        "carbono_ha": 20.0,
        "carbono_tco2_ano": 200.0,
        "deficit_RL_ha": 50.0,
        "secundaria_ha": 5.0,
    }
    return {**base, **kw}


def test_o_que_conta_e_o_que_vai_para_credito():
    c = F.por_imovel(_linha())
    assert c["flag_silvipastoril_ha"] == 80  # pasto dentro dos 90 ha livres (100 além da RL − 10 de APP)
    assert c["flag_cacau_ha"] == 90 and c["flag_cacau_viavel"]  # 80 de pasto + 10 de agricultura que cabem
    assert c["credito_alem_rl_ha"] == 20 and c["credito_tco2_ano"] == 200  # regeneração fica no crédito
    assert c["flag_plano_silvipastoril_ha"] == 60 and c["flag_plano_cacau_ha"] == 10  # sem área em comum
    t = F.regra()["remocao_tco2_ha_ano"]
    assert c["flag_tco2_ano"] == pytest.approx(
        60 * t["silvipastoril"]["central"] + 10 * t["agrofloresta_cacau"]["central"]
    )
    assert c["flag_tco2_ano_min"] < c["flag_tco2_ano"] < c["flag_tco2_ano_max"]
    assert (c["rl_restauracao_ha"], c["app_restauracao_ha"], c["capoeira_ha"]) == (50, 10, 5)
    assert c["flag_regra_versao"].startswith("ghg-lsr-1.1+")


def test_cacau_so_onde_e_viavel():
    assert not F.por_imovel(_linha(bioma="Caatinga", uf="PI"))["flag_cacau_viavel"]
    assert F.por_imovel(_linha(bioma="Mata Atlântica", uf="BA"))["flag_cacau_viavel"]
    assert not F.por_imovel(_linha(bioma="Mata Atlântica", uf="SP"))["flag_cacau_ha"]
    assert not F.por_imovel(_linha(cacau_aptidao=0.2))["flag_cacau_viavel"]  # aptidão do motor manda


def test_degradado_primeiro():
    assert F.por_imovel(_linha(), pasto_baixo_vigor_ha=30)["flag_silvipastoril_degradado_ha"] == 30
    assert F.por_imovel(_linha(mb_pasto_vigor_principal=1))["flag_silvipastoril_degradado_ha"] == 80
    assert F.por_imovel(_linha(mb_pasto_vigor_principal=3))["flag_silvipastoril_degradado_ha"] == 0


@settings(max_examples=300, deadline=None)
@given(
    alem=st.floats(0, 5000),
    app=st.floats(0, 500),
    pasto=st.floats(0, 5000),
    agri=st.floats(0, 2000),
    carbono=st.floats(0, 5000),
    silvi=st.floats(0, 6000),
    cacau=st.floats(0, 6000),
)
def test_nunca_a_mesma_area_nos_dois_lados(alem, app, pasto, agri, carbono, silvi, cacau):
    linha = _linha(alem_RL_ha=alem, app_recompor_ha=app, pasto_ha=pasto, mb_agricultura_2025_ha=agri,
                   carbono_ha=carbono, carbono_tco2_ano=carbono * 6)  # fmt: skip
    c = F.por_imovel(linha)
    livre = max(alem - app, 0)
    assert c["flag_plano_silvipastoril_ha"] <= c["flag_silvipastoril_ha"] + 1e-6
    assert c["flag_plano_silvipastoril_ha"] + c["flag_plano_cacau_ha"] + c["credito_alem_rl_ha"] <= livre + 1e-3
    s = F.simular(linha, silvi, cacau)
    m, k = s["meta_flag"], s["credito_ou_compensacao"]
    assert m["silvipastoril_ha"] + m["cacau_ha"] + k["regeneracao_alem_rl_ha"] <= livre + 0.05
    assert m["tco2_ano_min"] <= m["tco2_ano"] <= m["tco2_ano_max"]
    assert "total" not in s and "total" not in m and "total" not in k  # nunca somar as duas


def test_simulador_tira_do_credito_o_que_vai_para_a_meta():
    s = F.simular(_linha(), silvipastoril_ha=75, cacau_ha=0)
    assert s["meta_flag"]["silvipastoril_ha"] == 75 and s["credito_ou_compensacao"]["regeneracao_alem_rl_ha"] == 5
    s2 = F.simular(_linha(), silvipastoril_ha=500, cacau_ha=0)
    assert s2["meta_flag"]["silvipastoril_ha"] == 80 and s2["cortado"]["silvipastoril_ha"] == 420


def test_requisitos_e_requirement_7():
    linha = _linha(mb_fogo_2025_ha=3.0, projeto_carbono_ha=12.0)
    req = {r["id"]: r for r in F.requisitos(linha)}
    assert set(req) == {"rastreio", "medicao", "incerteza", "perdas", "dupla_contagem"}
    assert req["perdas"]["status"] == "atencao" and "3 ha de fogo" in req["perdas"]["detalhe"]
    assert req["dupla_contagem"]["status"] == "bloqueia" and req["incerteza"]["status"] == "ok"
    assert req["rastreio"]["status"] == "pendente" and "5 anos" in req["medicao"]["detalhe"]
    r7 = F.requirement_7(linha)
    assert r7["status"] == "aguardando regra" and not r7["ativo"] and len(r7["criterios"]) == 4
    b = F.bloco_ficha(linha)
    assert b["meta_flag"]["conta_na_meta"] and not b["credito_ou_compensacao"]["conta_na_meta"]
    assert b["regra"] == F.versao()


def test_versao_muda_e_recalcula(tmp_path):
    saida = tmp_path / "saida" / "PA"
    saida.mkdir(parents=True)
    for f in ("imoveis_1504950.csv", "mapbiomas_1504950.csv"):
        shutil.copy(AMOSTRA / f, saida / f)
    r1 = F.recalcular(tmp_path / "saida")
    assert r1["refeitos"] == ["PA/1504950"]
    df = pd.read_csv(saida / "flag_1504950.csv")
    assert len(df) == 880 and df.flag_regra_versao.nunique() == 1
    assert F.recalcular(tmp_path / "saida") == {"refeitos": [], "em_dia": 1}
    # o padrão muda (nova versão da tabela): tudo que foi calculado com a anterior é refeito
    nova = tmp_path / "ghg_lsr.yaml"
    doc = yaml.safe_load(Path(F.ARQUIVO).read_text())
    doc["versao"] = "ghg-lsr-1.2"
    nova.write_text(yaml.safe_dump(doc, allow_unicode=True))
    mp = pytest.MonkeyPatch()
    mp.setattr(F, "ARQUIVO", nova)
    try:
        assert F.versao().startswith("ghg-lsr-1.2+")
        assert F.recalcular(tmp_path / "saida")["refeitos"] == ["PA/1504950"]
        assert pd.read_csv(saida / "flag_1504950.csv").flag_regra_versao.iloc[0].startswith("ghg-lsr-1.2+")
    finally:
        mp.undo()
