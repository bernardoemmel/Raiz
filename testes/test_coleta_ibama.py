import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from raiz.coleta.espelho import Espelho
from raiz.coleta.ibama import coletar
from raiz.coleta.replicacao import sincronizar_fontes
from testes.servidor_falso import sessao_falsa
from testes.test_privacidade import CNPJ, CPF, fmt_cpf

pytestmark = pytest.mark.banco
URL = "https://ibama.exemplo/termo_de_embargo.csv"


def _csv(linhas):
    cab = (
        "SEQ_TAD;NUM_TAD;NOME_PESSOA_EMBARGADA;CPF_CNPJ_EMBARGADO;NOME_IMOVEL;UF;COD_MUNICIPIO;MUNICIPIO;"
        "DES_TAD;DAT_ULT_ALTERACAO;DAT_ULT_ALTER_GEOM;SIT_CANCELADO;SIT_DESEMBARGO;GEOM_AREA_EMBARGADA"
    )
    return "﻿" + cab + "\n" + "\n".join(linhas) + "\n"


def _linha(seq, cod, alt="2026-01-01", desc="Desmatar floresta"):
    return (
        f"{seq};{seq}0;Fulano de Tal;{fmt_cpf(CPF)};Fazenda Boa Vista;PA;{cod};Município;{desc} (ref {CNPJ});"
        f"{alt};{alt};N;N;POLYGON((-47.3 -2.3,-47.29 -2.3,-47.29 -2.29,-47.3 -2.29,-47.3 -2.3))"
    )


def test_ibama_condicional_e_sem_dado_pessoal(banco_url, tmp_path):
    publicado = {"etag": '"v1"', "csv": _csv([_linha(1, 1504950), _linha(2, 1504950), _linha(3, 1500107)])}

    def responder(metodo, base, p, h):
        if h.get("If-None-Match") == publicado["etag"]:
            return 304, {}, ""
        return 200, {"ETag": publicado["etag"]}, publicado["csv"]

    s, srv = sessao_falsa(responder)
    eng = create_engine(banco_url)
    esp = Espelho(tmp_path / "espelho")
    cache = tmp_path / "motor_cache"
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento cascade"))
        sincronizar_fontes(c)
        r = coletar(s, c, esp, cache, URL)
        assert r.acao == "atualizado" and r.linhas == 3
        assert {"NOME_PESSOA_EMBARGADA", "CPF_CNPJ_EMBARGADO", "NOME_IMOVEL"} <= set(r.removidas)
        assert set(r.municipios) == {1504950, 1500107}
        # nada pessoal no espelho nem no cache do motor
        for arq in [*tmp_path.rglob("*.parquet"), cache / "termo_de_embargo.csv"]:
            conteudo = arq.read_bytes()
            assert b"Fulano" not in conteudo and CPF.encode() not in conteudo and CNPJ.encode() not in conteudo
        motor = pd.read_csv(cache / "termo_de_embargo.csv", sep=";", dtype=str, encoding="utf-8-sig")
        assert {"SEQ_TAD", "COD_MUNICIPIO", "SIT_CANCELADO", "GEOM_AREA_EMBARGADA"} <= set(motor.columns)
        assert (cache / "termo_de_embargo.etag").read_text() == '"v1"'

        # mesma versão publicada: 304, nada baixado
        assert coletar(s, c, esp, cache, URL).acao == "sem_mudanca"
        assert srv.pedidos[-1][3]["If-None-Match"] == '"v1"'

        # nova versão: termo 2 alterado e termo 3 retirado; só o que mudou aparece
        publicado.update(etag='"v2"', csv=_csv([_linha(1, 1504950), _linha(2, 1504950, alt="2026-11-01")]))
        r = coletar(s, c, esp, cache, URL)
        assert r.municipios[1504950].mudaram == ["2"] and r.municipios[1500107].sumiram == ["3"]
        assert esp.ler("ibama", "PA", 1504950).crs.to_epsg() == 4674
    eng.dispose()


def test_termo_sem_geometria_nao_derruba(tmp_path):
    import geopandas as gpd

    from raiz.coleta.espelho import Espelho

    g = gpd.GeoDataFrame({"SEQ_TAD": ["1", "2"], "UF": ["PA", "PA"]}, geometry=[None, None], crs=4674)
    esp = Espelho(tmp_path)
    assert esp.gravar("ibama", "PA", 1, g, "SEQ_TAD").novos == ["1", "2"]
    assert esp.ler("ibama", "PA", 1).geometry.isna().all()
    assert not esp.gravar("ibama", "PA", 1, g, "SEQ_TAD").mudou


def test_trava_preserva_etag_cache_e_permite_liberar(banco_url, tmp_path):
    from raiz.coleta.replicacao import atualizar, estado

    publicado = {"etag": '"v1"', "csv": _csv([_linha(i, 1504950) for i in range(40)])}
    s, _ = sessao_falsa(lambda *a: (200, {"ETag": publicado["etag"]}, publicado["csv"]))
    eng = create_engine(banco_url)
    esp, cache = Espelho(tmp_path / "espelho"), tmp_path / "cache"
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento cascade"))
        sincronizar_fontes(c)
        coletar(s, c, esp, cache, URL)
        anterior = (cache / "termo_de_embargo.csv").read_bytes()
        publicado.update(etag='"v2"', csv=_csv([_linha(i, 1504950) for i in range(20)]))
        r = coletar(s, c, esp, cache, URL)
        assert r.acao == "travado" and r.travados == [1504950]
        assert not r.municipios and len(esp.ler("ibama", "PA", 1504950)) == 40
        assert estado(c, "ibama_embargos", "BR").etag == '"v1"'
        assert estado(c, "ibama_embargos", "BR").sujo
        assert (cache / "termo_de_embargo.csv").read_bytes() == anterior
        assert (cache / "termo_de_embargo.etag").read_text() == '"v1"'
        detalhe = c.execute(text("select detalhe from coleta.evento where tipo = 'alerta'")).scalars().all()
        assert any(d.get("qualidade", {}).get("tipo") == "queda_contagem" for d in detalhe)
        atualizar(c, "ibama_embargos", "PA/1504950", liberado=True)
        r = coletar(s, c, esp, cache, URL)
        assert r.acao == "atualizado" and len(esp.ler("ibama", "PA", 1504950)) == 20
        assert estado(c, "ibama_embargos", "BR").etag == '"v2"'
        assert not estado(c, "ibama_embargos", "PA/1504950").liberado
    eng.dispose()


def test_csv_malformado_falha_sem_avancar_etag(banco_url, tmp_path):
    from raiz.coleta.replicacao import estado

    publicado = {"etag": '"v1"', "csv": _csv([_linha(1, 1504950)])}
    s, _ = sessao_falsa(lambda *a: (200, {"ETag": publicado["etag"]}, publicado["csv"]))
    eng = create_engine(banco_url)
    esp, cache = Espelho(tmp_path / "espelho"), tmp_path / "cache"
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento cascade"))
        sincronizar_fontes(c)
        coletar(s, c, esp, cache, URL)
        antes = (cache / "termo_de_embargo.csv").read_bytes()
        publicado.update(etag='"v2"', csv=_csv([_linha(1, 1504950), _linha(2, 1504950) + ";campo_extra"]))
        with pytest.raises(ValueError, match="leitura integral exigida"):
            coletar(s, c, esp, cache, URL)
        assert estado(c, "ibama_embargos", "BR").etag == '"v1"'
        assert (cache / "termo_de_embargo.csv").read_bytes() == antes
    eng.dispose()


@pytest.mark.parametrize("campo", ["SIT_CANCELADO", "SIT_DESEMBARGO", "GEOM_AREA_EMBARGADA"])
def test_primeira_carga_exige_colunas_usadas_no_motor(banco_url, tmp_path, campo):
    import io

    from raiz.coleta.replicacao import estado

    df = pd.read_csv(io.StringIO(_csv([_linha(1, 1504950)])), sep=";", dtype=str)
    csv = df.drop(columns=campo).to_csv(sep=";", index=False)
    s, _ = sessao_falsa(lambda *a: (200, {"ETag": '"v1"'}, csv))
    eng, esp = create_engine(banco_url), Espelho(tmp_path / "espelho")
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento cascade"))
        sincronizar_fontes(c)
        with pytest.raises(ValueError, match="colunas obrigatórias"):
            coletar(s, c, esp, tmp_path / "cache", URL)
        assert estado(c, "ibama_embargos", "BR") is None
    assert not list(tmp_path.rglob("*.parquet")) and not (tmp_path / "cache").exists()
    eng.dispose()


@pytest.mark.parametrize(
    "linha",
    [_linha(" ", 1504950), _linha(1, "1504950.5"), _linha(1, "150495"), _linha(1, 1504950).replace(";PA;", ";ZZ;")],
    ids=["chave-branca", "codigo-fracionario", "codigo-curto", "uf-inexistente"],
)
def test_primeira_carga_rejeita_chave_ou_recorte_corrompido(banco_url, tmp_path, linha):
    from raiz.coleta.replicacao import estado

    s, _ = sessao_falsa(lambda *a: (200, {"ETag": '"v1"'}, _csv([linha])))
    eng, esp = create_engine(banco_url), Espelho(tmp_path / "espelho")
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento cascade"))
        sincronizar_fontes(c)
        with pytest.raises(ValueError, match="chave SEQ_TAD|recorte municipal"):
            coletar(s, c, esp, tmp_path / "cache", URL)
        assert estado(c, "ibama_embargos", "BR") is None
    assert not list(tmp_path.rglob("*.parquet")) and not (tmp_path / "cache").exists()
    eng.dispose()


def test_ibama_scd2_retry_304_e_ultimo_termo_sem_afetar_outro_municipio(banco_url, tmp_path, monkeypatch):
    import datetime as dt

    from raiz.coleta import bruto
    from raiz.coleta.rodada import sincronizar_historico
    from raiz.operacao.healthchecks import Healthchecks

    monkeypatch.setattr(bruto, "PASTA_DLT", tmp_path / "dlt")
    publicado = {"etag": '"v1"', "csv": _csv([_linha(1, 1504950), _linha(2, 1500107)])}

    def responder(metodo, base, p, h):
        if h.get("If-None-Match") == publicado["etag"]:
            return 304, {}, ""
        return 200, {"ETag": publicado["etag"]}, publicado["csv"]

    s, _ = sessao_falsa(responder)
    eng, esp, hc = create_engine(banco_url), Espelho(tmp_path / "espelho"), Healthchecks()
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento, operacao.lote cascade"))
        c.execute(text("drop schema bruto cascade"))
        c.execute(text("create schema bruto"))
        sincronizar_fontes(c)
        coletar(s, c, esp, url=URL)
    t1 = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    original = bruto.carregar
    monkeypatch.setattr(bruto, "carregar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("falha simulada")))
    assert sincronizar_historico(eng, esp, "PA", [1504950, 1500107], hc, t1, banco_url) == 0
    monkeypatch.setattr(bruto, "carregar", original)
    with eng.begin() as c:
        assert coletar(s, c, esp, url=URL).acao == "sem_mudanca"
    assert sincronizar_historico(eng, esp, "PA", [1504950, 1500107], hc, t1, banco_url) == 2
    with eng.connect() as c:
        assert c.execute(text("select count(*) from bruto.ibama_embargo_vigente")).scalar() == 2
        assert c.execute(text("select distinct st_srid(geom) from bruto.ibama_embargo_vigente")).scalar() == 4674
    publicado.update(etag='"v2"', csv=_csv([_linha(2, 1500107)]))
    with eng.begin() as c:
        r = coletar(s, c, esp, url=URL)
        assert r.municipios[1504950].sumiram == ["1"]
    t2 = t1 + dt.timedelta(days=1)
    vazio = bruto.linhas(esp.ler("ibama", "PA", 1504950), "SEQ_TAD", 1504950)
    with pytest.raises(ValueError, match="cod_municipio explícito"):
        bruto.carregar("ibama_embargo", vazio, t2, "SEQ_TAD", banco_url)
    with pytest.raises(ValueError, match="anterior à versão vigente"):
        bruto.carregar("ibama_embargo", vazio, t1 - dt.timedelta(days=1), "SEQ_TAD", banco_url, cod_municipio=1504950)
    assert sincronizar_historico(eng, esp, "PA", [1504950, 1500107], hc, t2, banco_url) == 1
    assert sincronizar_historico(eng, esp, "PA", [1504950, 1500107], hc, t2, banco_url) == 0
    with eng.connect() as c:
        rows = c.execute(
            text("select seq_tad, _dlt_valid_from, _dlt_valid_to from bruto.ibama_embargo order by seq_tad")
        ).all()
        assert rows == [("1", t1, t2), ("2", t1, None)]
        assert c.execute(text("select seq_tad from bruto.ibama_embargo_vigente")).scalar() == "2"
    eng.dispose()
