"""A carga privada gera fichas e histórico para qualquer UF, sem consulta individual."""

import datetime as dt

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box
from sqlalchemy import create_engine, text

from raiz.executor.armazem import ArmazemLocal, ArmazemRelease
from raiz.executor.sincronizar import carregar, sincronizar
from raiz.prospeccao_cobertura import reindexar
from testes.conftest import AMOSTRA


@pytest.fixture
def eng(banco_url):
    engine = create_engine(banco_url)
    with engine.begin() as con:
        con.execute(
            text("""truncate funil.rodada,funil.imovel,funil.arquivo_visto,
            funil.terra_comprometida,coleta.compromisso_fonte,geo.redd_programa,
            negocio.prospeccao_ficha_versao cascade""")
        )
    yield engine
    engine.dispose()


def _publicar(arm, pasta, uf, mun, *, perda=0, quantidade=2, geo=True):
    df = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", nrows=quantidade)
    df["uf"], df["cod_municipio_ibge"], df["municipio"] = uf, mun, "Município de teste"
    df["cod_imovel"] = [f"{uf}-{mun}-{i:032X}" for i in range(1, quantidade + 1)]
    df["ha"], df["area"], df["desm_pos2020_ha"] = 1.0, 1.0, perda
    arq = pasta / f"imoveis_{mun}.csv"
    df.to_csv(arq, index=False)
    arm.por(f"saida/{uf}/{arq.name}", arq, {"data": "2026-11-12"})
    if geo:
        arq = pasta / f"geo_{mun}.parquet"
        gpd.GeoDataFrame(
            {"cod_imovel": df.cod_imovel}, geometry=[box(-47.3, -2.3, -47.29, -2.29)] * quantidade, crs=4674
        ).to_parquet(arq)
        arm.por(f"saida/{uf}/{arq.name}", arq)
    return df.cod_imovel.tolist()


def _contar(engine, tabela):
    with engine.connect() as con:
        return con.execute(text(f"select count(*) from {tabela}")).scalar()


@pytest.mark.banco
def test_todas_ufs_nova_uf_e_atualizacao_sem_consulta(eng, tmp_path):
    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    pa = _publicar(arm, tmp_path, "PA", 1504950)
    mt = _publicar(arm, tmp_path, "MT", 5100102, geo=False)
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert not r["falhas"] and len(r["carregados"]) == 2
    with eng.connect() as con:
        atuais = con.execute(text("select documento from negocio.prospeccao_ficha_versao")).scalars().all()
        assert {d["codigo_car"] for d in atuais} == set(pa + mt)
        assert all(d["terra_comprometida"]["area_confirmada"]["valor"] is None for d in atuais)
        assert all(d["area_total"]["valor"] == 1 for d in atuais)  # pequena também tem ficha
    versoes = _contar(eng, "negocio.prospeccao_ficha_versao")
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert not r["carregados"] and not r["falhas"]
    assert _contar(eng, "negocio.prospeccao_ficha_versao") == versoes
    _publicar(arm, tmp_path, "RN", 2400109)
    _publicar(arm, tmp_path, "PA", 1504950, perda=2, quantidade=1)
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert len(r["carregados"]) == 2 and not r["falhas"]
    with eng.connect() as con:
        assert con.execute(text("select count(distinct uf) from funil.vigente")).scalar() == 3
        antes = (
            con.execute(
                text("select documento from negocio.prospeccao_ficha_versao where cod_imovel=:c order by id"),
                {"c": pa[0]},
            )
            .scalars()
            .all()
        )
        assert len(antes) == 2 and antes[0]["perdas"] != antes[1]["perdas"]
        removido = con.execute(
            text("""select v.documento from negocio.prospeccao_ficha_atual a
            join negocio.prospeccao_ficha_versao v on v.id=a.versao_id where a.cod_imovel=:c"""),
            {"c": pa[1]},
        ).scalar()
        assert removido == {"codigo_car": pa[1], "disponivel": False}


@pytest.mark.banco
def test_falha_pos_carga_repete_mesma_rodada(eng, tmp_path, monkeypatch):
    import raiz.carga_continua as C

    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    _publicar(arm, tmp_path, "RN", 2400109)
    original = C.depois_da_carga
    monkeypatch.setattr(C, "depois_da_carga", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("segredo")))
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert r["falhas"] == [{"chave": "RN/2400109", "erro": "RuntimeError"}]
    assert _contar(eng, "funil.rodada") == 1
    with eng.connect() as con:
        assert not con.execute(text("select 1 from funil.arquivo_visto where chave='RN/2400109'")).scalar()
    monkeypatch.setattr(C, "depois_da_carga", original)
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert not r["falhas"] and _contar(eng, "funil.rodada") == 1
    with eng.connect() as con:
        assert con.execute(text("select 1 from funil.arquivo_visto where chave='RN/2400109'")).scalar()


@pytest.mark.banco
def test_backfill_de_rodada_existente_inclui_complementos_sem_recalcular(eng, tmp_path):
    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    cars = _publicar(arm, tmp_path, "RN", 2400109)
    for tipo in ("rebanho", "jurisdicional"):
        arq = tmp_path / f"{tipo}_2400109.csv"
        pd.DataFrame({"cod_imovel": cars, "referencia_teste": [1, 2]}).to_csv(arq, index=False)
        arm.por(f"saida/RN/{arq.name}", arq)
    carregar(eng, arm, destino=destino, congelar=False)
    with eng.begin() as con:
        tipos = con.execute(text("select distinct tipo from funil.complemento_imovel")).scalars().all()
        assert set(tipos) == {"rebanho", "jurisdicional"}
        # Simula banco anterior à migração de versões, conservando rodada/arquivos.
        con.execute(text("truncate negocio.prospeccao_ficha_versao cascade"))
        con.execute(text("truncate funil.terra_comprometida"))
        con.execute(text("delete from funil.arquivo_visto where chave='prospeccao/compromissos'"))
        con.execute(text("update funil.arquivo_visto set assinatura=assinatura-'_pipeline_ficha'"))
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert not r["falhas"] and not r["carregados"] and r["baixados"] == 0
    assert _contar(eng, "funil.rodada") == 1
    assert _contar(eng, "negocio.prospeccao_ficha_versao") == 2
    assert _contar(eng, "funil.terra_comprometida") == 2


@pytest.mark.banco
def test_fonte_nova_reindexa_sem_mudar_csv_e_preserva_transicao(eng, tmp_path):
    from raiz.carga_continua import varrer
    from raiz.terra_comprometida import ingerir

    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    _publicar(arm, tmp_path, "PA", 1504950)
    _publicar(arm, tmp_path, "MT", 5100102)
    carregar(eng, arm, destino=destino, congelar=False)
    inicial = _contar(eng, "negocio.prospeccao_ficha_observacao")
    coleta = {
        "cobertura": {
            "fonte_id": "verra",
            "estado": "consultado",
            "escopo": "brasil",
            "consultado_em": dt.date.today().isoformat(),
        },
        "registros": [
            {
                "fonte_id": "verra",
                "objeto_id": "VCS-1",
                "registro": "VCS",
                "tipo": "projeto_carbono",
                "certeza": "poligono_oficial",
                "situacao": "ativo",
                "fonte_url": "https://registry.verra.org/app/projectDetail/VCS/1",
                "observado_em": dt.date.today().isoformat(),
                "geometry": box(-47.31, -2.31, -47.28, -2.28),
            }
        ],
    }
    with eng.begin() as con:
        ingerir(con, coleta)
    r = varrer(eng, destino / "saida", congelar=False, estavel_s=0)
    assert not r["carregados"] and r["fichas"]["municipios"] == 2 and not r["fichas"]["pendente"]
    assert _contar(eng, "negocio.prospeccao_ficha_observacao") == inicial + 4
    with eng.connect() as con:
        atual = con.execute(text("select dados from funil.terra_comprometida")).scalars().all()
        assert all(d["situacao"] == "sobreposicao_confirmada" for d in atual)
    assert not reindexar(eng)["alterado"]
    reindexar(eng, forcar=True)
    assert _contar(eng, "negocio.prospeccao_ficha_observacao") == inicial + 4
    # Uma coleta parcial mais antiga pode trazer objeto inédito. Ela também
    # invalida o checkpoint, embora não seja a última cobertura da fonte.
    ontem = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    historica = {
        "cobertura": {**coleta["cobertura"], "consultado_em": ontem},
        "registros": [{**coleta["registros"][0], "objeto_id": "VCS-2", "observado_em": ontem}],
    }
    with eng.begin() as con:
        ingerir(con, historica)
    r = varrer(eng, destino / "saida", congelar=False, estavel_s=0)
    assert r["fichas"]["alterado"] and not r["fichas"]["pendente"]
    with eng.connect() as con:
        atuais = con.execute(text("select dados from funil.terra_comprometida")).scalars().all()
        assert all(len(d["evidencias"]) == 2 for d in atuais)
    assert _contar(eng, "negocio.prospeccao_ficha_observacao") == inicial + 8


def test_espelho_confere_bytes_e_falha_sem_substituir_anterior(tmp_path, monkeypatch):
    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    chave = "saida/RN/imoveis_2400109.csv"
    arm.por_bytes(chave, b"original")
    sincronizar(arm, destino)
    (destino / chave).write_bytes(b"adulterado")
    assert sincronizar(arm, destino) == [chave]
    assert (destino / chave).read_bytes() == b"original"
    arm.por_bytes(chave, b"nova rodada")

    def corromper(chave, arq):
        arq.write_bytes(b"incompleto")
        return True

    monkeypatch.setattr(arm, "baixar", corromper)
    with pytest.raises(ValueError, match="SHA256"):
        sincronizar(arm, destino)
    assert (destino / chave).read_bytes() == b"original"


@pytest.mark.banco
def test_falha_de_uma_uf_nao_carrega_parcial_nem_bloqueia_as_demais(eng, tmp_path, monkeypatch):
    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    _publicar(arm, tmp_path, "PA", 1504950)
    _publicar(arm, tmp_path, "RN", 2400109)
    baixar = arm.baixar
    monkeypatch.setattr(arm, "baixar", lambda c, p: False if "/PA/" in c else baixar(c, p))
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert r["falhas"] == [{"chave": "PA", "erro": "FileNotFoundError"}]
    assert [c["chave"] for c in r["carregados"]] == ["RN/2400109"]
    monkeypatch.setattr(arm, "baixar", baixar)
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert not r["falhas"] and [c["chave"] for c in r["carregados"]] == ["PA/1504950"]


@pytest.mark.banco
def test_reindexacao_falha_retomavel_sem_apagar_versoes(eng, tmp_path, monkeypatch):
    import raiz.prospeccao_cobertura as C

    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    _publicar(arm, tmp_path, "PA", 1504950)
    _publicar(arm, tmp_path, "RN", 2400109)
    carregar(eng, arm, destino=destino, congelar=False)
    original = C.fotografar_municipio

    def falhar(con, cod, **kw):
        if cod == 1504950 and kw.get("atualizar"):
            raise RuntimeError("não deve entrar no retorno")
        return original(con, cod, **kw)

    with eng.begin() as con:
        con.execute(text("delete from funil.arquivo_visto where chave=:c"), {"c": C.CHAVE})
    monkeypatch.setattr(C, "fotografar_municipio", falhar)
    r = C.reindexar(eng)
    assert r["pendente"] and r["municipios"] == 1
    assert r["falhas"] == [{"municipio": 1504950, "erro": "RuntimeError"}]
    assert _contar(eng, "negocio.prospeccao_ficha_versao") == 4
    monkeypatch.setattr(C, "fotografar_municipio", original)
    r = C.reindexar(eng)
    assert r["municipios"] == 2 and not r["pendente"]
    assert _contar(eng, "negocio.prospeccao_ficha_versao") == 4


def test_manifesto_privado_e_pacotes_sao_refrescados_a_cada_volta(tmp_path, monkeypatch):
    import raiz.aprendizado.importacao as I
    import raiz.carga_continua as C
    import raiz.prospeccao_cobertura as P

    arm = ArmazemRelease("teste/repo", "dados-privados", espelho=tmp_path, privado=True, token="teste")
    estados, frescos, pacotes = {"PA": {}}, [], []
    monkeypatch.setattr(arm, "_exigir_privado", lambda: {})
    monkeypatch.setattr(arm, "manifesto", lambda fresco: frescos.append(fresco) or {"estados": estados})
    monkeypatch.setattr(arm, "garantir_uf", lambda uf, forcar: pacotes.append((uf, forcar)))
    monkeypatch.setattr(arm, "listar", lambda prefixo: [])
    monkeypatch.setattr(C, "varrer", lambda *a, **kw: {})
    monkeypatch.setattr(I, "receber", lambda *a, **kw: {})
    monkeypatch.setattr(P, "reindexar", lambda *a: {})
    carregar(None, arm, destino=tmp_path / "espelho")
    estados["RN"] = {}
    carregar(None, arm, destino=tmp_path / "espelho")
    assert frescos == [True, True]
    assert pacotes == [("PA", True), ("PA", True), ("RN", True)]


@pytest.mark.banco
def test_contexto_redd_novo_e_retirado_reindexa_sem_comprometer_area(eng, tmp_path):
    arm, destino = ArmazemLocal(tmp_path / "privado"), tmp_path / "espelho"
    _publicar(arm, tmp_path, "PA", 1504950)
    carregar(eng, arm, destino=destino, congelar=False)
    with eng.begin() as con:
        con.execute(
            text("""insert into geo.redd_programa(id,uf,inicio,fim,fonte,evidencia,geom)
            values('PA-teste','PA','2020-01-01','2030-12-31','https://www.pa.gov.br/redd',
                '{"data":"2026-11-12"}',ST_MakeEnvelope(-47.31,-2.31,-47.28,-2.28,4674))""")
        )
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert not r["carregados"] and r["fichas"]["alterado"] and not r["fichas"]["pendente"]
    with eng.connect() as con:
        atuais = con.execute(text("select dados from funil.terra_comprometida")).scalars().all()
        assert all(d["contexto_jurisdicional"] for d in atuais)
        assert all(d["area_confirmada"]["valor"] is None for d in atuais)
        assert all(d["situacao"] == "nao_verificado" for d in atuais)
    n = _contar(eng, "negocio.prospeccao_ficha_observacao")
    with eng.begin() as con:
        con.execute(text("delete from geo.redd_programa where id='PA-teste'"))
    r = carregar(eng, arm, destino=destino, congelar=False)
    assert r["fichas"]["alterado"] and not r["fichas"]["pendente"]
    assert _contar(eng, "negocio.prospeccao_ficha_observacao") == n + 2
    assert _contar(eng, "negocio.prospeccao_ficha_versao") == 4  # A→B→A reutiliza A e registra nova transição


def test_release_publico_nao_alimenta_ficha(tmp_path):
    arm = ArmazemRelease("teste/repo", "dados", espelho=tmp_path)
    with pytest.raises(PermissionError, match="dados completos"):
        carregar(None, arm, destino=tmp_path)
