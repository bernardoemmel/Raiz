"""Ficha de cada fazenda gravada em lote (raiz/fichas_lote.py): igual à da rota da API, rows.json do cartão sem código
do CAR antes do aceite, manifesto, índice e regravação só do município que mudou."""

import datetime as dt
import json

import pytest
from sqlalchemy import create_engine, text

from raiz import fichas_lote
from raiz import front_api as api
from raiz.busca import normalizar_codigo
from raiz.carga import carregar_pasta
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
COD = 1504950


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, geo.camada cascade"))
        c.execute(text("truncate negocio.aceite, negocio.codigo_curto cascade"))
    carregar_pasta(e, AMOSTRA, dt.date(2026, 11, 12))
    with e.begin() as c:
        alvo = c.execute(
            text("select min(cod_imovel) from funil.vigente where cod_municipio_ibge = :m"), {"m": COD}
        ).scalar()
        c.execute(
            text("""update funil.imovel set geom = ST_Multi(ST_GeomFromText(
                    'POLYGON((-47.30 -2.30, -47.29 -2.30, -47.29 -2.29, -47.30 -2.29, -47.30 -2.30))', 4674))
                    where cod_imovel = :c"""),
            {"c": alvo},
        )
        # a carga já sorteia o código curto de cada fazenda
        codigo = c.execute(text("select codigo from negocio.codigo_curto where cod_imovel = :c"), {"c": alvo})
        e.codigo = codigo.scalar()
    e.alvo = alvo
    return e


def test_ficha_do_lote_igual_a_da_rota(eng, tmp_path):
    r = fichas_lote.gravar(eng, tmp_path, cods=[COD])
    assert r["gravados"] == 1 and r["fichas"] > 1
    pasta = tmp_path / "PA" / str(COD)
    gravada = json.loads((pasta / "fichas" / f"{normalizar_codigo(eng.alvo)}.json").read_text(encoding="utf-8"))
    # a mesma ficha que GET /imoveis/{cod}/ficha monta, fazenda por fazenda
    alvo = api.imoveis_do_municipio(eng, cod_imovel=eng.alvo)[0]
    todos = api.linhas_para_contexto(eng, COD)
    with eng.connect() as c:
        g = c.execute(
            text("""select ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :t), 6) from funil.imovel
                    where cod_imovel = :c"""),
            {"c": eng.alvo, "t": api.SIMPLIFICAR_GRAUS},
        ).scalar()
    rota = api.montar_ficha(alvo, todos, json.loads(g), api.versao(eng, eng.alvo), api.do_banco(eng, eng.alvo))
    assert json.loads(json.dumps(rota, default=str)) == gravada
    assert gravada["perimetro"] and eng.codigo and gravada["codigo_curto"] == eng.codigo
    n = len(list((pasta / "fichas").glob("*.json")))
    man = json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))
    assert man["imoveis"] == n and man["com_contorno"] == 1 and man["versao_fichas"] == fichas_lote.VERSAO_FICHAS
    indice = json.loads((tmp_path / "indice.json").read_text(encoding="utf-8"))
    assert [m["cod_ibge"] for m in indice["municipios"]] == [COD]


def test_rows_do_cartao_sem_codigo_do_car_antes_do_aceite(eng, tmp_path):
    fichas_lote.gravar(eng, tmp_path, cods=[COD])
    rows = json.loads((tmp_path / "PA" / str(COD) / "rows.json").read_text(encoding="utf-8"))
    linha = next(r for r in rows if r["_cod_imovel"] == eng.alvo)
    assert linha["codigo"] == eng.codigo and linha["selo"] in ("bronze", "prata") and "cod_imovel" not in linha
    # o ponto exato (Plus Code e Organic Maps) só fica no campo interno antes do aceite
    assert linha["_plus_code"] and linha["_omaps"].startswith("https://omaps.app/") and "plus_code" not in linha
    assert {"municipio", "uf", "hectares", "frase", "frase_curta", "selo"} <= set(linha)
    # o que vai a público não traz o código do CAR nem nada com cara de documento
    publico = json.dumps([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows], ensure_ascii=False)
    assert eng.alvo not in publico and "PA-15" not in publico
    with eng.begin() as c:
        c.execute(text("insert into negocio.aceite (cod_imovel, estado) values (:c, 'aceito')"), {"c": eng.alvo})
    try:
        fichas_lote.gravar(eng, tmp_path, cods=[COD], refazer=True)
        rows = json.loads((tmp_path / "PA" / str(COD) / "rows.json").read_text(encoding="utf-8"))
        linha = next(r for r in rows if r["_cod_imovel"] == eng.alvo)
        assert linha["selo"] == "ouro" and linha["cod_imovel"] == eng.alvo
        assert linha["plus_code"] and linha["omaps"] and "_plus_code" not in linha
    finally:
        with eng.begin() as c:
            c.execute(text("delete from negocio.aceite where cod_imovel = :c"), {"c": eng.alvo})


def test_so_regrava_o_que_mudou(eng, tmp_path):
    assert fichas_lote.gravar(eng, tmp_path, cods=[COD])["gravados"] == 1
    assert fichas_lote.gravar(eng, tmp_path, cods=[COD]) | {"destino": ""} == {
        "gravados": 0, "iguais": 1, "fichas": 0, "destino": ""
    }  # fmt: skip
    assert fichas_lote.gravar(eng, tmp_path, cods=[COD], refazer=True)["gravados"] == 1


def test_contexto_uma_vez_igual_ao_de_cada_ficha():
    todos = [{"ha": 10, "carbono_ha": c, "problema": False} for c in (0, 2, 2, 5, 9)]
    ctx = api.contexto_municipio(todos)
    for alvo in todos:
        assert api.montar_ficha(alvo, todos, None, contexto=ctx) == api.montar_ficha(alvo, todos, None)
    assert api.montar_ficha(todos[3], todos, None)["contexto"]["posicao_carbono"] == 3 / 5
