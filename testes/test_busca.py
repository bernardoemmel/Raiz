"""Busca nacional pelo código do CAR, ficha que explica e carga contínua incremental.

- carga contínua: carrega o que o motor terminou, pula o que não mudou, espera arquivo sendo escrito, recarrega só o
  município reprocessado e guarda a versão anterior;
- código aceito com ou sem pontos e traços, em qualquer caixa; busca pelo começo do código e pelo nome do município;
- imóvel não apto: a ficha diz por quê, item por item; código desconhecido: 404 que explica;
- escala: 20 códigos sorteados de municípios diferentes respondem em menos de 2 s. Com RAIZ_TESTE_ESCALA=1 o banco
  de teste recebe um Brasil sintético (5.570 municípios, ~6,7 milhões de imóveis); sem ela, 40 municípios.
"""

import json
import os
import random
import shutil
import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz.busca import normalizar_codigo, normalizar_nome, parece_codigo
from raiz.carga_continua import varrer
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
TOKEN = "t"


def test_normalizar():
    c = "PA-1504950-00162AB1E0B34E339E65946061393F10"
    assert normalizar_codigo(c) == normalizar_codigo(c.lower()) == normalizar_codigo(c.replace("-", ""))
    pontos = "PA-1504950-0016.2AB1.E0B3.4E33.9E65.9460.6139.3F10"  # como o SICAR mostra
    assert normalizar_codigo(pontos) == normalizar_codigo(c) == "PA150495000162AB1E0B34E339E65946061393F10"
    assert normalizar_nome("  São Félix   do Xingu ") == "sao felix do xingu"
    assert parece_codigo("pa-1504") and parece_codigo("1504950") and not parece_codigo("Pará")


def _envelhecer(pasta, segundos=1000):
    antes = time.time() - segundos
    for f in pasta.rglob("*"):
        if f.is_file():
            os.utime(f, (antes, antes))


@pytest.fixture
def engine(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca cascade"))
        c.execute(text("truncate funil.arquivo_visto, operacao.lote cascade"))
    yield eng
    eng.dispose()


@pytest.fixture
def saida(tmp_path):
    pa = tmp_path / "saida" / "PA"
    pa.mkdir(parents=True)
    for f in AMOSTRA.glob("*.csv"):
        shutil.copy(f, pa / f.name)
    _envelhecer(pa)
    return tmp_path / "saida"


def _cliente(eng):
    import raiz.api as api_mod
    from raiz.api import criar_app

    cfg = type("C", (), {"api_token": SecretStr(TOKEN), "api_origens": ""})()
    mp = pytest.MonkeyPatch()
    mp.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    return TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}), mp


def test_carga_continua_incremental_com_versao(engine, saida):
    r = varrer(engine, saida, congelar=False)
    assert sorted(x["chave"] for x in r["carregados"]) == ["PA/1504950", "PA/1507300"] and not r["falhas"]
    assert [x["uf"] for x in r["resumos"]] == ["PA"]
    r2 = varrer(engine, saida, congelar=False)
    assert r2["pulados"] == 2 and not r2["carregados"]

    # o motor reprocessa só 1504950: um imóvel sai e um valor muda
    f = saida / "PA" / "imoveis_1504950.csv"
    df = pd.read_csv(f)
    saiu = df.cod_imovel.iloc[-1]
    df = df.iloc[:-1].copy()
    df.loc[df.index[0], "carbono_tco2_ano"] = 12345.0
    df.to_csv(f, index=False)
    r3 = varrer(engine, saida, congelar=False)
    assert r3["esperando"] == ["PA/1504950"] and not r3["carregados"]  # arquivo recém-escrito: espera
    _envelhecer(saida)
    r4 = varrer(engine, saida, congelar=False)
    assert [x["chave"] for x in r4["carregados"]] == ["PA/1504950"]  # 1507300: só a data mudou, conteúdo igual
    assert r4["pulados"] == 1
    with engine.connect() as c:
        rodadas = (
            c.execute(text("select id from funil.rodada where cod_municipio = 1504950 order by id")).scalars().all()
        )
        assert len(rodadas) == 2  # a versão anterior continua guardada
        vig = c.execute(text("select distinct rodada_id from funil.vigente where cod_municipio_ibge = 1504950"))
        assert vig.scalars().all() == [rodadas[-1]]
        assert c.execute(text("select count(*) from funil.vigente where cod_imovel = :c"), {"c": saiu}).scalar() == 0
        n = c.execute(text("select count(*) from funil.vigente where cod_municipio_ibge = 1507300")).scalar()
        assert n == 9703  # o outro município não foi tocado
        assert (
            c.execute(
                text("select carbono_tco2_ano from funil.resultado_vigente where cod_imovel = :c"),
                {"c": df.cod_imovel.iloc[0]},
            ).scalar()
            == 12345.0
        )


def test_busca_ficha_e_404(engine, saida):
    varrer(engine, saida, congelar=False)
    cl, mp = _cliente(engine)
    with cl:
        df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
        cod = df.cod_imovel.iloc[0]
        cauda = cod.split("-")[2]
        pontos = f"{cod[:11]}{'.'.join(cauda[i : i + 4] for i in range(0, len(cauda), 4))}"
        for variante in (cod, cod.lower(), cod.replace("-", ""), pontos):
            r = cl.get(f"/imoveis/{variante}")
            assert r.status_code == 200 and r.json()["cod_imovel"] == cod, variante
        f = cl.get(f"/imoveis/{cod.lower().replace('-', '')}/ficha").json()
        assert f["versao"] == 1 and f["versao_dado"]["rodada"] and f["situacao"]["categoria"]

        # não apta: diz por quê, item por item
        from raiz import motivos

        nao = next(x["cod_imovel"] for x in df.to_dict("records") if not motivos.ler(x)["apta"])
        fn = cl.get(f"/imoveis/{nao}/ficha").json()
        assert fn["situacao"]["apta"] is False and fn["situacao"]["porque_nao_apta"]
        assert any(m["bloqueia"] and not m["ok"] for m in fn["motivos"])
        assert all({"id", "ok", "texto", "detalhe", "bloqueia"} <= set(m) for m in fn["motivos"])

        # 404 que explica
        r = cl.get("/imoveis/PA-1504950-FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF")
        assert r.status_code == 404 and "Nova Esperança do Piriá" in r.json()["detail"]["mensagem"]
        r = cl.get("/imoveis/AM-1300029-FFFF")
        assert r.status_code == 404 and "ainda não foi processado" in r.json()["detail"]["mensagem"]

        # busca no contrato do front (front/compartilhado/dados/busca.ts)
        b = cl.get("/busca", params={"q": cod[:12].lower()}).json()
        assert b["tipo"] == "car" and b["situacao"] == "ok" and b["mensagem"] is None
        assert 0 < len(b["imoveis"]) <= 8 and all(i["cod_imovel"].startswith(cod[:12]) for i in b["imoveis"])
        i0 = b["imoveis"][0]
        assert {"cod_imovel", "municipio", "cod_ibge", "uf", "ha", "carbono_ha", "apta", "categoria"} <= set(i0)
        assert i0["municipio"] == "Nova Esperança do Piriá" and i0["uf"] == "PA"
        cs = [i["carbono_ha"] for i in b["imoveis"]]
        assert cs == sorted(cs, reverse=True)  # maior área de carbono primeiro
        assert cl.get("/busca", params={"q": pontos}).json()["imoveis"][0]["cod_imovel"] == cod
        m = cl.get("/busca", params={"q": "sao felix"}).json()
        assert m["tipo"] == "texto" and m["municipios"][0]["municipio"] == "São Félix do Xingu"
        assert m["municipios"][0]["imoveis"] == 9703 and m["municipios"][0]["tem_imoveis"]
        belem = cl.get("/busca", params={"q": "Belém"}).json()["municipios"][0]
        assert belem["municipio"] == "Belém" and not belem["tem_imoveis"] and belem["imoveis"] > 0
        assert cl.get("/busca", params={"q": "1507300"}).json()["municipios"][0]["cod_ibge"] == "1507300"
        sit = lambda q: cl.get("/busca", params={"q": q}).json()["situacao"]  # noqa: E731
        assert sit("ab") == "curta" and sit("PA-15") == "curta"
        assert sit("XX-1504950") == "formato_invalido" and sit("AM-1300029") == "estado_nao_processado"
        assert sit("PA-1501402-FFFF") == "municipio_sem_imoveis"  # Belém: só o resumo
        assert sit("PA-1599999") == "nao_encontrado" and sit("Atlântida") == "nao_encontrado"
        assert sit("PA-1504950-FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF") == "nao_encontrado"
    mp.undo()


def _brasil_sintetico(eng, municipios: int, por_municipio: int) -> None:
    """Municípios e imóveis sintéticos direto no banco (sem CSV), com códigos no formato do CAR."""
    with eng.begin() as c:
        c.execute(
            text("""
            insert into funil.rodada (tipo, uf, cod_municipio, origem, arquivos, hash_entradas, motor_versao,
                                      regras_versao, data_corte, imoveis)
            select 'municipio', 'MT', 5100000 + m, 'sintético', '{}', 'sintetico-' || m, 'teste', 'teste',
                   date '2026-11-12', :n
            from generate_series(1, :m) m"""),
            {"m": municipios, "n": por_municipio},
        )
        c.execute(
            text("""
            insert into funil.resultado_imovel (rodada_id, cod_imovel, uf, municipio, cod_municipio_ibge, ha,
                                                carbono_ha, alem_rl_ha, problema, desm_pos2016_ha, frente)
            select ro.id, 'MT-' || ro.cod_municipio || '-' || upper(md5(ro.cod_municipio || '-' || i)),
                   'MT', 'Município ' || ro.cod_municipio, ro.cod_municipio, 10 + (i % 500), (i % 7) * 3.5,
                   (i % 11) * 2.0, (i % 13) = 0, (i % 9), case when i % 5 = 0 then 'carbono' else 'desbloqueio' end
            from funil.rodada ro, generate_series(1, :n) i
            where ro.origem = 'sintético'"""),
            {"n": por_municipio},
        )
        c.execute(
            text("""
            insert into funil.vigente (cod_imovel, rodada_id, cod_municipio_ibge, uf, cod_busca)
            select r.cod_imovel, r.rodada_id, r.cod_municipio_ibge, r.uf,
                   upper(regexp_replace(r.cod_imovel, '[^0-9A-Za-z]', '', 'g'))
            from funil.resultado_imovel r join funil.rodada ro on ro.id = r.rodada_id where ro.origem = 'sintético'
            on conflict do nothing""")
        )
        c.execute(
            text("""
            insert into funil.municipio_busca (cod_ibge, municipio, uf, nome_busca, imoveis)
            select cod_municipio, 'Município ' || cod_municipio, 'MT', 'municipio ' || cod_municipio, :n
            from funil.rodada where origem = 'sintético' on conflict do nothing"""),
            {"n": por_municipio},
        )
        c.execute(text("analyze funil.vigente; analyze funil.resultado_imovel"))


def test_20_codigos_de_municipios_diferentes_em_menos_de_2s(engine):
    escala = os.environ.get("RAIZ_TESTE_ESCALA") == "1"
    municipios, por = (5570, 1200) if escala else (40, 150)
    t0 = time.perf_counter()
    _brasil_sintetico(engine, municipios, por)
    carga = time.perf_counter() - t0
    with engine.connect() as c:
        total = c.execute(text("select count(*) from funil.vigente")).scalar()
        sorteio = random.Random(7).sample(range(1, municipios + 1), 20)
        codigos = [
            c.execute(
                text("select cod_imovel from funil.vigente where cod_municipio_ibge = :m order by cod_busca limit 1"),
                {"m": 5100000 + m},
            ).scalar()
            for m in sorteio
        ]
    assert total == municipios * por and len(set(c.split("-")[1] for c in codigos)) == 20
    cl, mp = _cliente(engine)
    tempos = []
    with cl:
        for cod in codigos:
            for url, params in (
                (f"/imoveis/{cod.lower()}", None),
                (f"/imoveis/{cod.replace('-', '')}/ficha", None),
                ("/busca", {"q": cod[:14]}),
            ):
                t = time.perf_counter()
                r = cl.get(url, params=params)
                tempos.append(time.perf_counter() - t)
                assert r.status_code == 200, (url, r.text[:200])
            assert r.json()["imoveis"][0]["cod_imovel"].startswith(cod[:14]), r.json()
    mp.undo()
    pior = max(tempos)
    print(json.dumps({"imoveis": total, "carga_s": round(carga, 1), "pior_s": round(pior, 3),
                      "mediana_s": round(sorted(tempos)[len(tempos) // 2], 3)}))  # fmt: skip
    assert pior < 2.0, f"resposta mais lenta: {pior:.2f} s com {total} imóveis"
