"""Sorteio das conferências (E8): metade aleatória e metade dirigida às previsões mais duvidosas, a chance de escolha
no gabarito e as estimativas pesadas (Hájek e Olofsson). As simulações usam semente fixa."""

import datetime as dt
import random
import uuid

import pytest
from sqlalchemy import create_engine, text

from raiz.aprendizado import sorteio as S
from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote

CORTE = dt.date(2026, 1, 15)
OBS = dt.date(2026, 6, 1)


def test_pps_reparte_e_respeita_o_teto():
    p = S.pps([10, 1, 1, 1], 2)
    assert p[0] == 1.0 and abs(sum(p) - 2) < 1e-9 and all(abs(x - 1 / 3) < 1e-9 for x in p[1:])
    assert S.pps([1, 1], 0) == [0.0, 0.0] and S.pps([], 3) == []
    assert S.pps([5, 5, 5], 5) == [1.0, 1.0, 1.0]  # pede mais do que há: todos entram


def test_incerteza():
    c = lambda **kw: S.Candidato(1, "X", kw.get("v"), kw.get("t"), kw.get("p10"), kw.get("p50"), kw.get("p90"))  # noqa: E731
    assert S.incerteza(c(v=0.5)) == 1.0 and abs(S.incerteza(c(v=0.95)) - 0.19) < 1e-9
    assert S.incerteza(c(v=0.0)) == S.PISO_INCERTEZA  # ninguém fica com chance zero
    assert S.incerteza(c(t="carbono")) == 1.0  # sem medida de dúvida
    assert abs(S.incerteza(c(v=10.0, p10=8.0, p50=10.0, p90=14.0)) - 0.3) < 1e-9


def _previsoes(con, alvo, valores, cods, modelo="teste_sorteio"):
    ps = [
        Previsao(c, alvo, 180, valor_num=v if isinstance(v, float) else None,
                 valor_texto=v if isinstance(v, str) else None)
        for c, v in zip(cods, valores, strict=True)
    ]  # fmt: skip
    registrar_lote(con, ps, Versoes(modelo, "v1", f"entradas-{alvo}", CORTE))


@pytest.mark.banco
def test_peso_corrige_o_vies_do_dirigido(con):
    alvo = f"teste_sorteio_{uuid.uuid4().hex[:8]}"
    rnd = random.Random(7)
    cods = [f"PA-1504950-S{i:05d}{alvo[-4:]}" for i in range(600)]
    # 80% previsões seguras (p = 0,05, quase nunca acontece) e 20% duvidosas (p = 0,5, acontece metade das vezes)
    ps = [0.05 if i % 5 else 0.5 for i in range(600)]
    real = {c: float(rnd.random() < (0.04 if p < 0.1 else 0.6)) for c, p in zip(cods, ps, strict=True)}
    _previsoes(con, alvo, ps, cods)
    r = S.sortear(con, alvo, 160, "fundador", semente=11)
    assert r["populacao"] == 600 and 120 <= len(r["itens"]) <= 200
    dirigidos = [i for i in r["itens"] if i["desenho"] == "dirigido"]
    duvidosos = sum(ps[cods.index(i["cod_imovel"])] == 0.5 for i in dirigidos)
    assert duvidosos > 0.4 * len(dirigidos)  # o dirigido vai atrás da dúvida: 20% da população, 40%+ do dirigido
    for i in r["itens"]:
        registrar_gabarito(con, i["cod_imovel"], alvo, OBS, "conferencia", valor_num=real[i["cod_imovel"]])
    g = con.execute(
        text("select desenho_amostral, probabilidade_escolha from aprendizado.gabarito where alvo = :a"), {"a": alvo}
    ).all()
    assert {x.desenho_amostral for x in g} == {"aleatorio", "dirigido"} and all(x.probabilidade_escolha for x in g)
    e = S.estimar(con, r["sorteio_id"])
    verdade = sum(real.values()) / len(real)
    tr = e["taxa_real"]
    assert tr["ic95"][0] - 0.02 <= verdade <= tr["ic95"][1] + 0.02
    assert abs(e["taxa_real_sem_peso"]["valor"] - verdade) > abs(tr["valor"] - verdade)  # sem peso, viés
    assert e["brier"]["valor"] > 0 and e["com_gabarito"] == len(r["itens"])
    # quem já foi sorteado não volta no próximo sorteio do mesmo alvo
    r2 = S.sortear(con, alvo, 50, "fundador", semente=12)
    assert not {i["cod_imovel"] for i in r2["itens"]} & {i["cod_imovel"] for i in r["itens"]}
    with pytest.raises(ValueError, match="nunca nome"):
        S.sortear(con, alvo, 5, "Fulano de Tal")
    with pytest.raises(Exception, match="congelada"):
        con.execute(text("update aprendizado.sorteio_item set incerteza = 0 where sorteio_id = :s"),
                    {"s": r["sorteio_id"]})  # fmt: skip


@pytest.mark.banco
def test_olofsson_area_apta_com_intervalo(banco_url):
    """Oito sorteios simulados: a área apta estimada sai sem viés e o intervalo de 95% cobre a verdade na maioria.
    Áreas de fazenda têm cauda pesada (poucas muito grandes), por isso a cobertura fica abaixo dos 95% nominais."""
    from raiz.carga import carregar_pasta
    from testes.conftest import AMOSTRA

    eng = create_engine(banco_url)
    carregar_pasta(eng, AMOSTRA, dt.date(2026, 11, 12), congelar=False)
    erros, cobre = [], 0
    with eng.begin() as con:
        im = con.execute(
            text("""select cod_imovel, ha from funil.resultado_vigente where ha > 0
                    and split_part(cod_imovel, '-', 2) in ('1504950', '1507300') order by cod_imovel""")
        ).all()
        cods = [c for c, _ in im]
        ha = dict(im)
        for k in range(8):
            alvo = f"teste_apta_{uuid.uuid4().hex[:8]}"
            rnd = random.Random(100 + k)
            mapa = ["apta" if rnd.random() < 0.7 else "nao_apta" for _ in cods]
            real = {c: ("apta" if rnd.random() < (0.8 if m == "apta" else 0.1) else "nao_apta")
                    for c, m in zip(cods, mapa, strict=True)}  # fmt: skip
            _previsoes(con, alvo, mapa, cods)
            r = S.sortear(con, alvo, len(cods) // 4, "fundador", semente=200 + k)
            for i in r["itens"]:
                registrar_gabarito(con, i["cod_imovel"], alvo, OBS, "conferencia", valor_texto=real[i["cod_imovel"]])
            o = S.olofsson(con, r["sorteio_id"])
            verdade = sum(ha[c] for c in cods if real[c] == "apta")
            apta = o["classes"]["apta"]
            erros.append((apta["area_ha"] - verdade) / verdade)
            cobre += apta["ic95_ha"][0] <= verdade <= apta["ic95_ha"][1]
            assert apta["area_prevista_ha"] == pytest.approx(sum(ha[c] for c, m in zip(cods, mapa, strict=True)
                                                                 if m == "apta"))  # fmt: skip
            assert 0.6 <= apta["acerto_usuario"] <= 0.95 and o["fracao_area_coberta"] == pytest.approx(1.0)
        e = S.estimar(con, r["sorteio_id"])
    assert abs(sum(erros) / len(erros)) < 0.08 and cobre >= 6
    assert 0.6 <= e["acerto"]["valor"] <= 0.95
    eng.dispose()
