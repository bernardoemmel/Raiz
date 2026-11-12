"""Coleta do CAR de ponta a ponta contra um GeoServer falso que muda entre rodadas: fila, espelho por município,
histórico scd2 no PostGIS, SIGEF do município, Healthchecks, e o espelho lido pela ponte do motor."""

import datetime as dt
import json
import re

import httpx
import pytest
from sqlalchemy import create_engine, text

from raiz.coleta import car
from raiz.coleta.espelho import Espelho
from raiz.coleta.fila import planejar
from raiz.coleta.rodada import rodada_car
from raiz.funil.ponte import ler_local
from raiz.operacao.healthchecks import Healthchecks
from testes.servidor_falso import sessao_falsa

pytestmark = pytest.mark.banco
COD = 1504950


def _poly(i):
    x = -47.3 + i * 0.01
    return {"type": "Polygon", "coordinates": [[[x, -2.3], [x + 0.01, -2.3], [x + 0.01, -2.29], [x, -2.29], [x, -2.3]]]}


class Mundo:
    """O que o servidor tem publicado agora."""

    def __init__(self):
        self.car = {
            "PA-1504950-A": {"m_fiscal": 1.0, "data_atualizacao": "2026-07-01T10:00:00Z", "status_imovel": "AT"},
            "PA-1504950-B": {"m_fiscal": 2.0, "data_atualizacao": "2026-07-02T10:00:00Z", "status_imovel": "AT"},
            "PA-1504950-C": {"m_fiscal": 3.0, "data_atualizacao": "2026-07-03T10:00:00Z", "status_imovel": "PE"},
        }
        self.pedidos_completos = 0
        self.pedidos_delta = 0

    def _feats(self, itens):
        # geometria presa à chave (não à posição na resposta): o delta não pode "mudar a forma" do imóvel
        return [
            {
                "type": "Feature",
                "id": f"sicar_imoveis_pa.{i}",
                "geometry": _poly(ord(k[-1])),
                "properties": {"cod_imovel": k, "cod_municipio_ibge": COD, **v},
            }
            for i, (k, v) in enumerate(itens)
        ]

    def responder(self, metodo, base, p, h):
        if "incra" in base:
            parcelas = [
                {
                    "type": "Feature",
                    "geometry": _poly(i),
                    "properties": {
                        "parcela_codigo": f"P{i}",
                        "natureza": "Particular",
                        "registro_matricula": str(100 + i),
                        "nome_area": "Fazenda de alguém",
                    },
                }
                for i in range(2)
            ]
            assert p["bbox"].endswith("urn:ogc:def:crs:EPSG::4674")
            return 200, {}, json.dumps({"type": "FeatureCollection", "features": parcelas, "numberMatched": 2})
        if p.get("request") == "DescribeFeatureType":
            return (
                200,
                {},
                (
                    '<xsd:element name="cod_imovel" type="xsd:string"/>'
                    '<xsd:element name="data_atualizacao" type="xsd:dateTime"/>'
                ),
            )
        itens = sorted(self.car.items())
        m = re.search(r"data_atualizacao > '([\d-]+)'", p.get("CQL_FILTER", ""))
        if m:
            itens = [(k, v) for k, v in itens if v["data_atualizacao"][:10] > m.group(1)]
        if p.get("resultType") == "hits":
            return 200, {}, f'<x numberMatched="{len(itens)}"/>'
        if p.get("count") == "1":
            mais = max(itens, key=lambda kv: kv[1]["data_atualizacao"])
            return (
                200,
                {},
                json.dumps({"features": [{"properties": {"data_atualizacao": mais[1]["data_atualizacao"]}}]}),
            )
        if m:
            self.pedidos_delta += 1
        else:
            self.pedidos_completos += 1
        return (
            200,
            {},
            json.dumps({"type": "FeatureCollection", "features": self._feats(itens), "numberMatched": len(itens)}),
        )


@pytest.fixture
def ambiente(banco_url, tmp_path, monkeypatch):
    from raiz.coleta import bruto

    monkeypatch.setattr(bruto, "PASTA_DLT", tmp_path / "dlt")  # estado do dlt limpo a cada teste
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento, operacao.lote cascade"))
        c.execute(text("drop schema bruto cascade"))
        c.execute(text("create schema bruto"))
        from raiz.coleta.replicacao import sincronizar_fontes

        sincronizar_fontes(c)
    mundo = Mundo()
    s, _ = sessao_falsa(mundo.responder)
    pings = []
    hc = Healthchecks(
        "k",
        "https://hc.exemplo",
        "raiz-{tarefa}",
        httpx.Client(transport=httpx.MockTransport(lambda req: pings.append(req.url.path) or httpx.Response(200))),
    )
    yield eng, s, Espelho(tmp_path / "espelho"), mundo, hc, pings
    eng.dispose()


def test_coleta_car_tres_rodadas(ambiente, banco_url):
    eng, s, esp, mundo, hc, pings = ambiente
    muns = {"PA": [COD]}

    # 1) primeira vez: reconciliação completa (nunca houve uma)
    r1 = rodada_car(eng, s, esp, muns, hc, banco_url)
    assert r1["modo"]["PA"].startswith("reconciliacao") and r1["baixados"] == 1 and r1["mudaram"] == [COD]
    g = esp.ler("car", "PA", COD)
    assert sorted(g.cod_imovel) == ["PA-1504950-A", "PA-1504950-B", "PA-1504950-C"]
    sig = esp.ler("sigef", "PA", COD)
    assert list(sig.parcela_codigo) == ["P0", "P1"] and "nome_area" not in sig  # nome sai na entrada
    assert "/k/raiz-coleta-car/start" in pings and "/k/raiz-coleta-car" in pings

    # 2) nada mudou: só a assinatura (nenhum download)
    antes = mundo.pedidos_completos + mundo.pedidos_delta
    r2 = rodada_car(eng, s, esp, muns, hc, banco_url)
    assert r2["modo"]["PA"].startswith("incremental (0 de 1") and mundo.pedidos_completos + mundo.pedidos_delta == antes

    # 3) B mudou: baixa só o delta (data_atualizacao > cursor - 2 dias) e grava uma versão nova no histórico
    mundo.car["PA-1504950-B"].update(m_fiscal=2.5, data_atualizacao="2026-11-10T08:00:00Z")
    r3 = rodada_car(eng, s, esp, muns, hc, banco_url)
    assert r3["mudaram"] == [COD] and mundo.pedidos_delta == 1
    assert esp.ler("car", "PA", COD).set_index("cod_imovel").loc["PA-1504950-B", "m_fiscal"] == 2.5

    # 4) C foi cancelado (some da camada sem mudar data): a contagem não bate e o município vem inteiro
    completos = mundo.pedidos_completos
    del mundo.car["PA-1504950-C"]
    rodada_car(eng, s, esp, muns, hc, banco_url)
    assert mundo.pedidos_completos == completos + 1
    assert sorted(esp.ler("car", "PA", COD).cod_imovel) == ["PA-1504950-A", "PA-1504950-B"]

    with eng.connect() as c:
        hist = c.execute(
            text(
                "select cod_imovel, m_fiscal, _dlt_valid_to is null as vigente from bruto.car_imovel "
                "order by cod_imovel, _dlt_valid_from"
            )
        ).all()
        assert [(h.cod_imovel[-1], h.m_fiscal, h.vigente) for h in hist] == [
            ("A", 1.0, True),
            ("B", 2.0, False),
            ("B", 2.5, True),
            ("C", 3.0, False),
        ]
        assert c.execute(text("select count(*) from bruto.car_imovel_vigente")).scalar() == 2
        assert c.execute(text("select bool_and(st_srid(geom) = 4674) from bruto.car_imovel")).scalar()
        ev = dict(
            c.execute(
                text(
                    "select tipo, sum(quantidade) from coleta.evento where fonte = 'sicar_imoveis' "
                    "and tipo in ('novos', 'mudaram', 'sumiram') group by 1"
                )
            ).all()
        )
        assert ev == {"novos": 3, "mudaram": 1, "sumiram": 1}

    # a ponte do motor lê exatamente este espelho
    assert sorted(ler_local(esp.raiz, "car", "PA", COD).cod_imovel) == ["PA-1504950-A", "PA-1504950-B"]


def test_falha_fica_suja_e_tenta_de_novo(ambiente, banco_url):
    eng, _, esp, _, hc, pings = ambiente

    def cai(metodo, base, p, h):
        if p.get("request") == "DescribeFeatureType":
            return 200, {}, '<xsd:element name="data_atualizacao"/>'
        return 503, {}, "fora do ar"

    s, _ = sessao_falsa(cai)
    r = rodada_car(eng, s, esp, {"PA": [COD]}, hc, banco_url, historico=False)
    assert r["falhas"] == 1 and "/k/raiz-coleta-car/fail" in pings
    with eng.connect() as c:
        e = c.execute(
            text("select sujo, tentativas, ultimo_erro from coleta.replicacao where recorte = :r"), {"r": f"PA/{COD}"}
        ).one()
        assert e.sujo and e.tentativas >= 1 and "503" in e.ultimo_erro


def test_fila_disjuntor_e_limite(ambiente):
    eng = ambiente[0]
    recortes = [f"PA/{i}" for i in range(1000)]
    with eng.begin() as c:
        from raiz.coleta.fila import registrar_reconciliacao
        from raiz.coleta.replicacao import atualizar

        registrar_reconciliacao(c, car.FONTE)
        for r in recortes:
            atualizar(c, car.FONTE, r, sujo=False)
        for r in recortes[:100]:  # 10% sujos: incremental, no máximo 200 (aqui 100)
            atualizar(c, car.FONTE, r, sujo=True)
        p = planejar(c, car.FONTE, recortes)
        assert p.modo == "incremental" and len(p.recortes) == 100
        for r in recortes[:400]:  # 40% sujos: disjuntor, roda tudo que está sujo
            atualizar(c, car.FONTE, r, sujo=True)
        p = planejar(c, car.FONTE, recortes)
        assert p.modo == "completo" and len(p.recortes) == 400
        p = planejar(c, car.FONTE, recortes, agora=dt.datetime.now(dt.UTC) + dt.timedelta(days=31))
        assert p.modo == "reconciliacao" and len(p.recortes) == 1000


def test_linhas_do_historico_com_campo_nulo():
    import geopandas as gpd
    from shapely.geometry import box

    from raiz.coleta.bruto import linhas

    g = gpd.GeoDataFrame(
        {"cod_imovel": ["A", "B"], "condicao": [None, "Analisado"], "m_fiscal": [float("nan"), 2.0]},
        geometry=[box(0, 0, 1, 1), box(1, 1, 2, 2)],
        crs=4674,
    )
    df = linhas(g, "cod_imovel", 1)
    assert df._hash.notna().all() and df._hash.is_unique


def test_historico_que_falhou_e_recuperado_na_rodada_seguinte(ambiente, banco_url, monkeypatch):
    from raiz.coleta import bruto

    eng, s, esp, mundo, hc, pings = ambiente
    original = bruto.carregar

    def quebra(*a, **k):
        raise RuntimeError("banco caiu no meio da carga")

    monkeypatch.setattr(bruto, "carregar", quebra)
    r1 = rodada_car(eng, s, esp, {"PA": [COD]}, hc, banco_url)
    assert r1["baixados"] == 1 and r1["historico"] == 0 and "/k/raiz-historico/fail" in pings
    monkeypatch.setattr(bruto, "carregar", original)
    r2 = rodada_car(eng, s, esp, {"PA": [COD]}, hc, banco_url)  # nada mudou na fonte, mas o histórico estava atrasado
    assert r2["baixados"] == 0 and r2["historico"] == 2  # CAR e SIGEF
    with eng.connect() as c:
        assert c.execute(text("select count(*) from bruto.car_imovel_vigente")).scalar() == 3
    assert rodada_car(eng, s, esp, {"PA": [COD]}, hc, banco_url)["historico"] == 0


def test_trava_de_versao_e_resumo(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Polygon, box

    from raiz.coleta.espelho import Espelho

    esp = Espelho(tmp_path)
    cods = [f"I{i:03d}" for i in range(40)]
    g = gpd.GeoDataFrame(
        {"cod_imovel": cods, "m_fiscal": [1.0] * 40}, geometry=[box(i, 0, i + 1, 1) for i in range(40)], crs=4674
    )
    assert esp.gravar("car", "PA", 1, g, "cod_imovel").total == 40  # primeira carga nunca trava
    # mesma forma com vértices noutra ordem e ruído abaixo de 1 cm: o resumo não muda, nada é comparado
    g2 = g.copy()
    g2.loc[0, "geometry"] = Polygon([(1, 0), (1, 1 + 1e-9), (0, 1), (0, 0)])
    d = esp.gravar("car", "PA", 1, g2, "cod_imovel")
    assert d.pelo_resumo and not d.mudou
    # 5 de 40 mudam (12,5%): grava
    g3 = g.copy()
    g3.loc[:4, "m_fiscal"] = 2.0
    d = esp.gravar("car", "PA", 1, g3, "cod_imovel")
    assert len(d.mudaram) == 5 and d.escreveu and not d.travado
    # 15 de 40 mudam (37,5%): trava, o arquivo fica como estava
    g4 = g3.copy()
    g4.loc[10:24, "m_fiscal"] = 9.0
    d = esp.gravar("car", "PA", 1, g4, "cod_imovel")
    assert d.travado and not d.escreveu and esp.ler("car", "PA", 1).m_fiscal.max() == 2.0
    # liberado por um humano: grava
    assert esp.gravar("car", "PA", 1, g4, "cod_imovel", liberar=True).escreveu


def test_trava_da_uf_segura_o_historico(ambiente, banco_url, monkeypatch):
    from raiz.coleta import rodada
    from raiz.coleta.replicacao import atualizar

    eng, s, esp, mundo, hc, pings = ambiente
    resumo = {"mudaram": list(range(5))}
    assert rodada._uf_travada(eng, hc, "PA", list(range(20)), resumo)  # 25% dos municípios mudou
    assert "/k/raiz-trava/fail" in pings and resumo["travadas"] == ["PA"]
    with eng.begin() as c:
        atualizar(c, "sicar_imoveis", "PA", liberado=True)
    assert not rodada._uf_travada(eng, hc, "PA", list(range(20)), {"mudaram": list(range(5))})
    assert not rodada._uf_travada(eng, hc, "PA", list(range(20)), {"mudaram": [1, 2]})  # 10%: não trava
