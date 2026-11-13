import copy

import numpy as np
import pytest

from raiz import restauracao as R
from raiz import restauracao_sensibilidade as S
from testes.test_restauracao import _linha


def test_avaliacao_rapida_preserva_creditos_e_tir_central_sem_copiar_quantis():
    c = R.cenario("central_r12")
    li = _linha(ha=100, cod_municipio_ibge=1507300)
    a, _ = R.calcular(li, c)
    b, _ = R.calcular(li, c, financeiro_p50=True)
    for q in ("p10", "p50", "p90"):
        k = f"credito_liquido_tco2_ha_contrato_{q}"
        assert a[k] == b[k]
    for tipo in ("projeto", "alavancada"):
        assert a[f"tir_{tipo}_pct_p50"] == b[f"tir_{tipo}_pct_p50"]
        assert b[f"tir_{tipo}_pct_p10"] is None
        assert b[f"tir_{tipo}_pct_p90"] is None
        assert b[f"preco_minimo_tir_12_{tipo}_usd_t"] is None
    assert b["restauracao_tipo_calculo"] == "sensibilidade_financeira_p50"


def test_reserva_maiore_preco_recalculam_previsao_sem_mudar_entrada():
    c = R.cenario("central_r12", reserva_por_fazenda=False)
    li = _linha(ha=100)
    antes = copy.deepcopy(li)
    a, _ = R.calcular(li, c, financeiro_p50=True)
    b, _ = R.calcular(li, {**c, "reserva_risco": 0.4}, financeiro_p50=True)
    d, _ = R.calcular(li, {**c, "preco_usd_t": 73.82}, financeiro_p50=True)
    assert b["credito_liquido_tco2_ha_contrato_p50"] == pytest.approx(
        a["credito_liquido_tco2_ha_contrato_p50"] * 0.75, abs=0.1
    )
    assert d["tir_projeto_pct_p50"] > a["tir_projeto_pct_p50"]
    assert li == antes
    assert S.versao(c) != S.versao({**c, "preco_usd_t": 73.82})
    assert len(S.cenarios()) == 9
    assert all(x[1]["reserva_risco"] >= 0.2 for x in S.cenarios())
    assert np.isfinite(b["credito_liquido_tco2_ha_contrato_p50"])


def test_estudo_refaz_as_tres_selecoes_e_reusa_checkpoint_sem_perder_pequenas(tmp_path, monkeypatch):
    import gzip
    import json

    from raiz import lote as L
    from raiz.pedidos import oferta as O

    c = R.cenario("central_r12")
    entradas = {}
    registros = []
    for cod, area in [("PEQUENA", 0.1), ("MAIOR", 10)]:
        li = _linha(
            cod_imovel=cod,
            ha=area,
            alem_RL_ha=area,
            pasto_ha=area,
            cod_municipio_ibge=1507300,
            caminho_terra="privada_matricula",
            risco_terra="medio",
            porte="pequeno",
            grupo_id="grupo-sintetico",
        )
        entradas[cod] = li
        calc, _ = R.calcular(li, c, financeiro_p50=True)
        registros.append(O.de_linha({**li, **calc}, -52.5, -6.5))
    oferta = O.tabela(registros)
    oferta["elegivel"] = True
    dados = dict(oferta=oferta, uf="PA", pasta=tmp_path)
    monkeypatch.setattr(L.Linhas, "entradas", lambda self, cods: {str(k): entradas[str(k)] for k in cods})
    vistas = []
    selecionar = L._selecionar

    def observar(oferta, *args, **kw):
        vistas.append(set(oferta.cod_imovel))
        return selecionar(oferta, *args, **kw)

    monkeypatch.setattr(L, "_selecionar", observar)
    casos = [("central", c), ("reserva_40", {**c, "reserva_risco": 0.4})]
    resultado = S.executar(dados, tmp_path / "estudo", casos=casos, volume=1)
    assert len(vistas) == 6 and all(x == {"PEQUENA", "MAIOR"} for x in vistas)
    assert len(resultado["resultados"]) == 6
    for prova in resultado["provas"]:
        with gzip.open(tmp_path / "estudo" / prova["previsoes"], "rt") as f:
            previsoes = [json.loads(x) for x in f]
        assert {x["cod_imovel"] for x in previsoes} == {"PEQUENA", "MAIOR"}
        assert all(x["entradas_sha256"] and x["estudo_versao"] for x in previsoes)
    assert len(list((tmp_path / "estudo").glob("decisoes_*.jsonl.gz"))) == 6
    monkeypatch.setattr(R, "calcular", lambda *a, **k: pytest.fail("checkpoint não deve recalcular"))
    assert S.executar(dados, tmp_path / "estudo", casos=casos, volume=1) == resultado
