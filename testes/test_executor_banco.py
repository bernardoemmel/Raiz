"""O back-end serve a partir do armazém: espelha e carrega no banco o que mudou, carrega um município sob demanda
quando pedem um imóvel dele, e mostra o processamento e os números do Brasil e dos estados."""

import shutil

import pytest
from sqlalchemy import create_engine, text

from raiz.executor.armazem import ArmazemLocal, por_json
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
COD = 1504950


@pytest.fixture
def armazem(tmp_path):
    a = ArmazemLocal(tmp_path / "armazem")
    for f in AMOSTRA.glob(f"*_{COD}.csv"):
        a.por(f"saida/PA/{f.name}", f, {"tarefa": "teste", "versao": "teste-1", "data": "2026-11-12"})
    a.por("saida/PA/resumo_PA.csv", AMOSTRA / "resumo_PA.csv", {"tarefa": "resumo"})
    por_json(a, "estado/PA.json", {"uf": "PA", "situacao": "pronto", "feitos": 144, "total": 144, "erros": [],
                                   "motor_versao": "motor-abc", "versoes": {"funil": "funil-1"}})  # fmt: skip
    por_json(a, "estado/MT.json", {"uf": "MT", "situacao": "em_andamento", "feitos": 10, "total": 142, "erros": []})
    return a


@pytest.fixture
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, funil.vigente, funil.municipio_busca cascade"))
        c.execute(text("truncate funil.arquivo_visto"))
    yield e
    e.dispose()


def _cliente(eng, armazem, monkeypatch):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    import raiz.api as api_mod
    from raiz.api import criar_app

    cfg = type("C", (), {"api_token": SecretStr("t"), "api_origens": ""})()
    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False, armazem=armazem)
    return TestClient(app, headers={"Authorization": "Bearer t"})


def test_sincronizar_e_carregar_so_o_que_mudou(eng, armazem, tmp_path):
    from raiz.executor.sincronizar import carregar, sincronizar

    destino = tmp_path / "espelho"
    r = carregar(eng, armazem, ["PA"], destino)
    assert r["baixados"] >= 3 and any(str(COD) in str(x) for x in r["carregados"])
    with eng.connect() as c:
        assert c.execute(text("select count(*) from funil.vigente where cod_municipio_ibge = :m"), {"m": COD}).scalar()
    assert sincronizar(armazem, destino, ["PA"]) == []  # nada mudou, nada baixa
    armazem.por_bytes(f"saida/PA/flag_{COD}.csv", (AMOSTRA / f"filtros_{COD}.csv").read_bytes())
    assert sincronizar(armazem, destino, ["PA"]) == [f"saida/PA/flag_{COD}.csv"]


def test_imovel_sob_demanda_e_painel(eng, armazem, tmp_path, monkeypatch):
    from raiz.executor import sincronizar as S

    monkeypatch.setattr(S, "espelho_local", lambda: tmp_path / "espelho")
    import pandas as pd

    cods = pd.read_csv(AMOSTRA / f"imoveis_{COD}.csv", usecols=["cod_imovel"]).cod_imovel.astype(str)
    cod_imovel = next(c for c in cods if c.startswith(f"PA-{COD}-"))  # o código traz o município do cadastro
    with _cliente(eng, armazem, monkeypatch) as cl:
        r = cl.get(f"/imoveis/{cod_imovel}")  # o banco está vazio: carrega o município do armazém na hora
        assert r.status_code == 200 and r.json()["cod_imovel"] == cod_imovel
        assert cl.get(f"/imoveis/{cod_imovel}/ficha").status_code == 200
        p = cl.get("/processamento").json()
        assert p["contagem"]["pronto"] == 1 and p["contagem"]["em_andamento"] == 1
        pa = next(e for e in p["estados"] if e["uf"] == "PA")
        assert pa["motor_versao"] == "motor-abc" and pa["feitos"] == 144
        assert cl.get("/painel/processamento").text.startswith("<!doctype html>")
        # números do Brasil e dos estados a partir do que o back-end carregou do armazém
        from raiz.carga import carregar_resumo

        shutil.copy(AMOSTRA / "resumo_PA.csv", tmp_path / "resumo_PA.csv")
        with eng.begin() as c:
            carregar_resumo(c, tmp_path / "resumo_PA.csv", "PA")
        b = cl.get("/brasil").json()
        assert b["imoveis"] > 0 and b["estados_com_dado"] == 1 and b["processamento"]["pronto"] == 1
        est = {e["uf"]: e for e in cl.get("/estados").json()}
        assert est["PA"]["imoveis"] == b["imoveis"] and est["MT"]["situacao_processamento"] == "em_andamento"
        assert est["SP"]["situacao_processamento"] == "nao_iniciado"
