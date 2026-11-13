from datetime import timedelta

import numpy as np
import pytest

from raiz.avaliacao.contratos import ObservacaoTemporal
from raiz.avaliacao.metricas import crps, crps_distribuicao
from raiz.avaliacao.tempo import avaliar
from testes.avaliacao_modelos.fixtures import DIA, digest, id_


def test_crps_tem_formula_independente_e_penaliza_falsa_certeza():
    y, xs = 5.0, np.array([1.0, 4.0, 6.0, 10.0])
    esperado = np.abs(xs - y).mean() - 0.5 * np.abs(xs[:, None] - xs).mean()
    assert crps(y, xs) == pytest.approx(esperado)
    assert crps(0, [0, 0]) == 0
    assert crps(10, [0, 0]) > crps(10, [0, 10, 20])
    assert crps(0, [-100, 0, 100]) > crps(0, [-1, 0, 1])


@pytest.mark.parametrize("xs", [[], [1], [1, np.nan], [1, np.inf], [[1, 2]]])
def test_crps_nao_silencia_amostra_invalida(xs):
    with pytest.raises(ValueError):
        crps(1, xs)


def test_tres_quantis_nao_sao_uma_distribuicao_empirica():
    with pytest.raises(ValueError):
        crps_distribuicao(5, {"p10": 1, "p50": 5, "p90": 10})
    assert crps_distribuicao(5, {"tipo": "empirica", "sorteios": [1, 5, 10]}) > 0


def test_origem_movel_nao_enxerga_fato_antigo_registrado_depois_nem_entrada_tardia():
    datas = [DIA + timedelta(days=i) for i in range(8)]
    obs = [
        ObservacaoTemporal(
            caso_id=id_(i), evento_em=d, conhecido_em=d, entradas_disponiveis_em=d, entradas_sha256=digest(i), valor=i
        )
        for i, d in enumerate(datas)
    ]
    obs[0] = obs[0].model_copy(update={"conhecido_em": datas[6]})
    obs[1] = obs[1].model_copy(update={"entradas_disponiveis_em": datas[5]})
    chamados = []

    def modelo(treino, corte, horizontes):
        assert isinstance(treino, tuple)
        assert all(
            x.evento_em <= corte and x.conhecido_em <= corte and x.entradas_disponiveis_em <= corte for x in treino
        )
        assert all(h > corte for h in horizontes)
        chamados.append({x.caso_id for x in treino})
        # Previsão ingênua treinada só no passado recebido.
        valores = [x.valor for x in treino]
        return {h: [min(valores), max(valores)] for h in horizontes}

    r = avaliar(obs, datas, modelo, janela_inicial=3)
    assert len(r) == 5
    assert chamados[0] == {id_(2)}
    assert id_(0) not in chamados[3] and id_(0) in chamados[4]
    assert all(x["crps"] >= 0 for x in r)
    # Adulterar um futuro muda a nota, não a previsão da origem anterior.
    obs[-1] = obs[-1].model_copy(update={"valor": 1000})
    r2 = avaliar(obs, datas, modelo, janela_inicial=3)
    assert r2[:-1] == r[:-1] and r2[-1]["crps"] > r[-1]["crps"]


def test_horizonte_sem_real_nao_e_avaliacao_aprovada():
    o = ObservacaoTemporal(
        caso_id=id_(1), evento_em=DIA, conhecido_em=DIA, entradas_disponiveis_em=DIA, entradas_sha256=digest(1), valor=1
    )
    with pytest.raises(ValueError, match="sem gabarito"):
        avaliar([o], [DIA + timedelta(days=i) for i in range(4)], lambda t, c, hs: {h: [1, 2] for h in hs})


def test_crps_com_todos_os_sorteios_nao_aloca_matriz_quadratica(monkeypatch):
    from properscoring import _crps

    assert _crps._crps_ensemble_core is not _crps._crps_ensemble_vectorized
    assert crps(0, np.linspace(-1, 1, 20000)) == pytest.approx(1 / 6, abs=1e-4)
    monkeypatch.setattr(_crps, "_crps_ensemble_core", _crps._crps_ensemble_vectorized)
    with pytest.raises(RuntimeError, match="quadrático recusado"):
        crps(0, np.linspace(-1, 1, 20000))


def test_crps_rejeita_overflow_mesmo_com_entradas_finitas():
    with pytest.raises(ValueError, match="faixa numérica"):
        crps(-1e308, [1e308, 1e308])
