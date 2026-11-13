import datetime as dt
from dataclasses import replace

import numpy as np
import psycopg
import pytest
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LogisticRegression

from raiz.aprendizado.acerto import nota, placar
from raiz.aprendizado.registro import Previsao, Versoes, conferir_lote, hash_lote, registrar_lote
from raiz.avaliacao.treino import caudas, classificador_balanceado, variancia_floresta


def test_reamostragem_e_normalizacao_so_veem_treino():
    x = np.arange(40).reshape(-1, 1)
    y = np.array([0] * 35 + [1] * 5)
    teste = np.array([[1000], [2000], [3000]])
    copia = teste.copy()
    p = classificador_balanceado(LogisticRegression())
    p.fit(x, y)
    antes = p.named_steps["balanceamento"].sample_indices_.copy()
    assert len(antes) == 70 and max(antes) < len(x)
    assert p.named_steps["escala"].mean_[0] == x.mean()
    assert len(p.predict(teste)) == len(teste)
    np.testing.assert_array_equal(teste, copia)
    np.testing.assert_array_equal(p.named_steps["balanceamento"].sample_indices_, antes)


def test_forestci_e_caudas_de_erros(tmp_path):
    rng = np.random.default_rng(12)
    x = rng.normal(size=(200, 3))
    y = x[:, 0] * 5 + rng.normal(size=200)
    f = RandomForestRegressor(n_estimators=500, random_state=12, n_jobs=1).fit(x, y)
    xt = rng.normal(size=(30, 3))
    v = variancia_floresta(f, x, xt)
    assert v.shape == (30,) and (v > 0).all()
    erro = f.predict(xt) - xt[:, 0] * 5
    erro[0], erro[-1] = -100, 100
    arquivo = tmp_path / "caudas.png"
    r = caudas(erro, arquivo)
    assert arquivo.read_bytes().startswith(b"\x89PNG")
    assert r["p01"] < 0 < r["p99"] and r["n"] == 30


def test_hash_autentica_distribuicao_e_preserva_ordem_canonica():
    p = Previsao(
        "sintetico",
        "carbono_tco2_ano",
        365,
        p10=1,
        p50=2,
        p90=3,
        distribuicao={"tipo": "empirica", "sorteios": [1.0, 2.0, 3.0]},
    )
    v = Versoes("sintetico", "v1", "e1", dt.date(2026, 1, 1))
    h = hash_lote([p], v)
    assert h != hash_lote([replace(p, distribuicao={"tipo": "empirica", "sorteios": [1.0, 2.0, 4.0]})], v)
    assert h == hash_lote([replace(p, distribuicao={"sorteios": [1.0, 2.0, 3.0], "tipo": "empirica"})], v)
    # Sem distribuição mantém o identificador legado: não renumera o arquivo antigo.
    legado = replace(p, distribuicao=None)
    import hashlib

    linha = "ao_vivo|sintetico|carbono_tco2_ano|||1.0|2.0|3.0|2026-01-01|365|sintetico|v1|e1||\n"
    assert hash_lote([legado], v) == hashlib.sha256(linha.encode()).hexdigest()


@pytest.mark.banco
def test_distribuicoes_distintas_nao_sao_descartadas_como_lote_repetido(con):
    v = Versoes("teste-crps", "v1", "e1", dt.date(2026, 1, 1))
    p = Previsao(
        "sintetico", "carbono_tco2_ano", 365, p50=2, distribuicao={"tipo": "empirica", "sorteios": [1.0, 2.0, 3.0]}
    )
    a, novo_a = registrar_lote(con, [p], v)
    alterada = replace(p, distribuicao={"tipo": "empirica", "sorteios": [0.0, 2.0, 4.0]})
    with pytest.raises(psycopg.errors.UniqueViolation), con.begin_nested():
        registrar_lote(con, [alterada], v)
    b, novo_b = registrar_lote(con, [alterada], replace(v, modelo_versao="v2"))
    assert novo_a and novo_b and a != b
    assert conferir_lote(con, a) and conferir_lote(con, b)


def test_placar_real_expoe_crps_e_seu_denominador_sem_imputar_quantis():
    r = {
        "modelo": "carbono",
        "modelo_versao": "v1",
        "alvo": "carbono_tco2_ano",
        "real_num": 2,
        "p10": 1,
        "p50": 2,
        "p90": 3,
        "maturou": True,
    }
    assert "crps" not in nota(r)
    com = {**r, "distribuicao": {"tipo": "empirica", "sorteios": [1.0, 2.0, 3.0]}}
    assert nota(com)["crps"] == pytest.approx(2 / 9)
    relatorio = placar([r, com])[0]
    assert relatorio["crps_n"] == 1 and relatorio["com_gabarito"] == 2


def test_crps_opcional_nao_quebra_painel_publico_das_faixas_legadas():
    from raiz.aprendizado import painel
    from testes.test_aprendizado_painel import AGORA, linhas

    xs = linhas(alvo="carbono_tco2_ano", p10=1, p50=10, p90=20)
    xs[0]["distribuicao"] = {"tipo": "empirica", "sorteios": [1.0, 10.0, 20.0]}
    r = painel.resumir(xs, AGORA)["versoes"][0]
    assert r["comparacoes"] == 5
    assert set(r["metricas"]) == {"wis", "ae_mediana", "cobertura_80"}
    # O CRPS interno tem denominador próprio; a amostra individual não é exposta no resumo público.
    assert placar(xs)[0]["crps_n"] == 1
