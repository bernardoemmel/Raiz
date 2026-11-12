"""Calibração por UF e porte, teste por tempo (folds anuais) e campeão e desafiante (E8 passos 5 e 6). Um modelo
simulado e mal calibrado (acontece p², não p) em três safras anuais: a calibração aprendida só com o passado ganha
no ano seguinte e o portão promove; trava, intervalo e volta atrás funcionam."""

import datetime as dt
import random
import uuid

import pytest
from sqlalchemy import text

from raiz.aprendizado import calibracao as C
from raiz.aprendizado import campeao as K
from raiz.aprendizado import folds as F
from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote


def test_isotonica_e_calibrar():
    mapa = C.pav([0.1, 0.2, 0.3, 0.4], [0.0, 1.0, 0.0, 1.0], [1, 1, 1, 1])
    ys = [y for _, y in mapa]
    assert ys == sorted(ys) and abs(ys[0] - 0.0) < 1e-9 and abs(ys[-1] - 1.0) < 1e-9
    m = {"global": [[0.2, 0.1], [0.8, 0.6]], "segmentos": {"PA|pequena": {"n": 50, "mapa": [[0.2, 0.3], [0.8, 0.9]]}},
         "k": 50}  # fmt: skip
    assert C.calibrar(m, 0.5) == pytest.approx(0.35)
    assert C.calibrar(m, 0.5, "PA", "pequena") == pytest.approx(0.5 * 0.6 + 0.5 * 0.35)  # metade segmento, metade total
    assert C.calibrar(m, 0.0) == pytest.approx(0.1) and C.calibrar(m, 1.0) == pytest.approx(0.6)
    assert (
        C.porte(3) == "pequena" and C.porte(15) == "media" and C.porte(40) == "grande" and C.porte(None) == "sem_porte"
    )
    assert C.ece([0.25, 0.25, 0.75, 0.75], [0, 1, 1, 1], [1, 1, 1, 1]) == pytest.approx(0.5 * 0.25 + 0.5 * 0.25)
    assert F.cortes_anuais(dt.date(2022, 12, 31), dt.date(2024, 12, 31)) == [
        dt.date(2022, 12, 31), dt.date(2023, 12, 31), dt.date(2024, 12, 31)]  # fmt: skip
    assert "_dlt_valid_to > :corte" in F.como_estava("car_imovel")
    with pytest.raises(ValueError):
        F.como_estava("car; drop table x")


def _safras(con, alvo, modelo, n=700):
    rnd = random.Random(42)
    for ano in (2022, 2023, 2024):
        corte = dt.date(ano, 1, 15)
        ps, reais = [], {}
        for i in range(n):
            cod = f"PA-1504950-K{ano}{i:04d}{alvo[-4:]}"
            p = rnd.uniform(0.05, 0.95)
            ps.append(Previsao(cod, alvo, 180, valor_num=p))
            reais[cod] = float(rnd.random() < p * p)  # o modelo superestima: acontece p², não p
        registrar_lote(con, ps, Versoes(modelo, "v1", f"entradas-{ano}", corte))
        for cod, y in reais.items():
            registrar_gabarito(con, cod, alvo, corte + dt.timedelta(days=150), "simulado", valor_num=y)


@pytest.mark.banco
def test_calibracao_por_tempo_e_promocao(con):
    alvo = f"teste_cal_{uuid.uuid4().hex[:8]}"
    modelo = f"teste_modelo_{alvo[-4:]}"
    _safras(con, alvo, modelo)
    todos = C.pontos(con, modelo, alvo)
    m = C.medir(todos)
    assert m["total"]["fora"] and m["total"]["diferenca"] < -0.1  # mal calibrado: prevê mais do que acontece
    assert set(m["segmentos"]) == {"PA|sem_porte"}
    folds = F.calibracao_por_tempo(con, modelo, alvo, [dt.date(2022, 12, 31), dt.date(2023, 12, 31)])
    assert [f["situacao"] for f in folds] == ["ok", "ok"]
    assert folds[0]["n_treino"] == 700 and folds[1]["n_treino"] == 1400 and folds[1]["n_teste"] == 700
    for f in folds:  # treinada só com o passado, ganha no ano seguinte
        assert f["brier_calibrado"] < f["brier_base"] and f["ece_calibrado"] < f["ece_base"]
    n_bt = con.execute(
        text("select count(*) from aprendizado.previsao where modelo = :m and tipo = 'backtest'"),
        {"m": f"{modelo}+calibracao"},
    ).scalar()
    assert n_bt == 1400
    # campeão e desafiante
    K.definir_inicial(con, alvo, modelo, "v1", "fundador")
    desafiante = (f"{modelo}+calibracao", folds[1]["versao"])
    K.travar(con, alvo, "fundador", "olhar antes")
    r = K.promover(con, alvo, desafiante)
    assert not r["promovido"] and any("travado" in x for x in r["motivos"])
    assert r["comparacao"]["pares"] == 700 and r["comparacao"]["ic95"][1] < 0  # o desafiante ganha com folga
    K.travar(con, alvo, "fundador", "pode", travar_=False)
    r = K.promover(con, alvo, desafiante)
    assert r["promovido"]
    atual = K.campeao_atual(con, alvo)
    assert atual.modelo == desafiante[0] and atual.automatico and atual.medidas["pares"] == 700
    # volta atrás é à mão; logo depois, nova troca automática esbarra no intervalo
    v = K.voltar(con, alvo, "fundador", "conferir a calibração em campo")
    assert v == {"modelo": modelo, "modelo_versao": "v1"} and K.campeao_atual(con, alvo).acao == "volta_atras"
    r = K.promover(con, alvo, desafiante)
    assert not r["promovido"] and any("última troca" in x for x in r["motivos"])
    with pytest.raises(ValueError, match="nunca nome"):
        K.promover(con, alvo, desafiante, quem="Fulano de Tal")
    with pytest.raises(Exception, match="congelada"):
        con.execute(text("update aprendizado.campeao set quem = 'x' where alvo = :a"), {"a": alvo})


@pytest.mark.banco
def test_portao_recusa_desafiante_pior_ou_com_pouco_dado(con):
    alvo = f"teste_pior_{uuid.uuid4().hex[:8]}"
    modelo = f"teste_modelo_{alvo[-4:]}"
    _safras(con, alvo, modelo, n=40)
    # desafiante que piora: chance invertida, nos mesmos imóveis e cortes
    for ano in (2022, 2023, 2024):
        rs = con.execute(
            text("select cod_imovel, valor_num from aprendizado.previsao where modelo = :m and data_corte = :d"),
            {"m": modelo, "d": dt.date(ano, 1, 15)},
        ).all()
        v = Versoes(modelo, "invertido", f"entradas-{ano}", dt.date(ano, 1, 15), tipo="backtest")
        registrar_lote(con, [Previsao(c, alvo, 180, valor_num=1 - p) for c, p in rs], v)
    cmp = K.comparar(con, alvo, (modelo, "v1"), (modelo, "invertido"))
    assert cmp["pares"] == 120 and cmp["diferenca"] > 0
    ok, motivos = K.portao(cmp)
    assert not ok and "não ganha" in motivos[0]
    ok, motivos = K.portao({**cmp, "pares": 10})
    assert not ok and "poucos pares" in motivos[0]
