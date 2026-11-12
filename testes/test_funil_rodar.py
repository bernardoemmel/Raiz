"""Invólucro do motor: ponte CAR/SIGEF com o espelho local e lotes vigiados pelo Healthchecks (E7 passo 4).
Sem rede: o motor de verdade é importado, mas municipio() é trocado por um falso que usa a ponte."""

import datetime as dt
import sys
from types import SimpleNamespace

import geopandas as gpd
import httpx
import pandas as pd
import pytest
from shapely.geometry import box
from sqlalchemy import create_engine, text

from raiz import MOTOR_DIR
from raiz.funil import rodar as RD
from raiz.funil.ponte import arquivo, ponte
from raiz.operacao.healthchecks import Healthchecks
from testes.conftest import AMOSTRA
from testes.test_privacidade import CPF

COD = 1504950


@pytest.fixture
def motor(tmp_path, monkeypatch):
    """Importa o motor de verdade numa pasta de trabalho temporária (ele cria cache/ ao importar)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(MOTOR_DIR))
    sys.modules.pop("raiz_estado", None)
    import raiz_estado as R

    yield R
    sys.modules.pop("raiz_estado", None)


def _espelho(tmp_path, n=3):
    cods = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", usecols=["cod_imovel"]).cod_imovel.head(n).tolist()
    car = gpd.GeoDataFrame({"cod_imovel": cods + [cods[0]], "status_imovel": "AT", "tipo_imovel": "IRU"},
                           geometry=[box(-47.3, -2.3, -47.29, -2.29)] * (n + 1), crs=4674)  # fmt: skip
    sig = gpd.GeoDataFrame({"parcela_codigo": ["p1", "p2", "p2"], "natureza": "Particular"},
                           geometry=[box(-47.3, -2.3, -47.2, -2.2), box(10, 10, 11, 11), box(10, 10, 11, 11)],
                           crs=4674)  # fmt: skip
    esp = tmp_path / "espelho"
    for camada, g in (("car", car), ("sigef", sig)):
        f = arquivo(esp, camada, "PA", COD)
        f.parent.mkdir(parents=True, exist_ok=True)
        g.to_parquet(f)
    return esp, cods


def test_ponte_le_do_espelho_e_restaura(motor, tmp_path):
    R = motor
    esp, cods = _espelho(tmp_path)
    original = R.car_mun
    with ponte(R, "PA", COD, esp) as origem:
        g = R.car_mun("PA", COD)
        assert sorted(g.cod_imovel) == sorted(cods)  # sem duplicata
        s = R.sigef((-47.31, -2.31, -47.0, -2.0))
        assert list(s.parcela_codigo) == ["p1"]  # só o que cai no retângulo do município
        # quem chama car_mun por dentro do motor (raiz_extras.geometria) também recebe o espelho
        import raiz_extras

        geo = raiz_extras.geometria("PA", COD, str(tmp_path))
        assert len(geo) == len(cods)
    assert origem == {"car": "espelho", "sigef": "espelho"}
    assert R.car_mun is original


def test_ponte_sem_espelho_cai_no_download(motor, tmp_path, monkeypatch):
    R = motor
    chamado = []
    monkeypatch.setattr(R, "car_mun", lambda uf, cod: chamado.append((uf, cod)) or "baixado")
    with ponte(R, "PA", COD, tmp_path / "vazio") as origem:
        assert R.car_mun("PA", COD) == "baixado"
    assert origem == {"car": "download"} and chamado == [("PA", COD)]


class Pings:
    def __init__(self):
        self.lista = []

    def cliente(self):
        def h(req):
            self.lista.append((req.url.path, dict(req.url.params), req.content.decode()))
            return httpx.Response(200, text="OK")

        return httpx.Client(transport=httpx.MockTransport(h))


@pytest.mark.banco
def test_rodar_municipio_com_lotes(motor, tmp_path, monkeypatch, banco_url):
    R = motor
    esp, _ = _espelho(tmp_path)
    amostra = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", index_col=0)

    def municipio_falso(uf, cod, EMB, out="."):
        g = R.car_mun(uf, cod)  # passa pela ponte
        assert len(g) == 3
        return amostra, "Nova Esperança do Piriá"

    monkeypatch.setattr(R, "municipio", municipio_falso)
    monkeypatch.setattr(RD, "_R", R)
    monkeypatch.setattr(RD, "_EMB", pd.DataFrame())
    monkeypatch.setattr(RD, "_ENGINE", None)
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, operacao.lote cascade"))
    pings = Pings()
    hc = Healthchecks("chave-ping", "https://hc.exemplo", "raiz-{tarefa}", pings.cliente())
    op = RD.Opcoes("pa", tarefas=("funil", "carga"), data_corte=dt.date(2026, 11, 20), espelho=str(esp),
                   banco_url=banco_url)  # fmt: skip

    assert RD.rodar_municipio(COD, op, hc) == {"funil": "sucesso", "carga": "sucesso"}
    assert (tmp_path / "saida" / "PA" / f"imoveis_{COD}.csv").exists()
    with eng.connect() as c:
        ro = c.execute(text("select * from funil.rodada where cod_municipio = :c"), {"c": COD}).one()
        assert ro.motor_versao_confirmada and ro.imoveis == 880
        v = c.execute(text("select distinct modelo_versao from aprendizado.previsao where rodada_id = :r"),
                      {"r": ro.id}).scalars().all()  # fmt: skip
        assert v and not any(x.endswith("-suposta") for x in v)
        lotes = c.execute(text("select tarefa, estado, rid, detalhe from operacao.lote order by id")).all()
        assert [(lt.tarefa, lt.estado) for lt in lotes] == [("funil", "sucesso"), ("carga", "sucesso")]
        assert lotes[0].detalhe["origem"] == {"car": "espelho"}
    # Healthchecks: início e sucesso de cada tarefa, com o mesmo rid do banco e criação automática do check
    caminhos = [(p, q["rid"]) for p, q, _ in pings.lista]
    rid_funil = str(lotes[0].rid)
    assert ("/chave-ping/raiz-funil/start", rid_funil) in caminhos and ("/chave-ping/raiz-funil", rid_funil) in caminhos
    assert all(q["create"] == "1" for _, q, _ in pings.lista)

    # segunda vez: o funil pula (arquivo pronto) e a carga não duplica
    assert RD.rodar_municipio(COD, op, hc)["funil"] == "pulado"
    with eng.connect() as c:
        assert c.execute(text("select count(*) from funil.rodada where cod_municipio = :c"), {"c": COD}).scalar() == 1
    eng.dispose()


@pytest.mark.banco
def test_falha_vai_para_o_healthchecks_mascarada(motor, tmp_path, monkeypatch, banco_url):
    R = motor

    def quebra(uf, cod, EMB, out="."):
        print("baixando PRODES...")
        raise RuntimeError(f"servidor caiu no imóvel do CPF {CPF}")

    monkeypatch.setattr(R, "municipio", quebra)
    monkeypatch.setattr(RD, "_R", R)
    monkeypatch.setattr(RD, "_EMB", pd.DataFrame())
    monkeypatch.setattr(RD, "_ENGINE", None)
    pings = Pings()
    hc = Healthchecks("k", "https://hc.exemplo", "raiz-{tarefa}-{uf}", pings.cliente())
    op = RD.Opcoes("PA", tarefas=("funil", "carga"), espelho=str(tmp_path), banco_url=banco_url)
    res = RD.rodar_municipio(9999999, op, hc)
    assert res == {"funil": "falha: RuntimeError"}  # carga nem tenta
    path, _, corpo = pings.lista[-1]
    assert path == "/k/raiz-funil-pa/fail"
    assert "servidor caiu" in corpo and "baixando PRODES" in corpo and CPF not in corpo
    eng = create_engine(banco_url)
    with eng.connect() as c:
        lt = c.execute(text("select estado, log_final from operacao.lote where cod_municipio = 9999999")).one()
        assert lt.estado == "falha" and CPF not in lt.log_final
    eng.dispose()


def test_healthchecks_desligado_e_fora_do_ar():
    assert not Healthchecks(None, cliente=httpx.Client()).inicio("x", "rid")

    def cai(req):
        raise httpx.ConnectError("sem rede")

    hc = Healthchecks("k", "https://hc.exemplo", cliente=httpx.Client(transport=httpx.MockTransport(cai)))
    assert hc.sucesso("raiz-funil", "rid") is False  # não levanta: alerta nunca derruba o lote
    assert SimpleNamespace(slug=hc.slug("funil", "PA", 1))  # modelo padrão
    assert (
        Healthchecks("k", modelo_slug="raiz-{tarefa}-{uf}-{cod}").slug("funil", "PA", 1504950)
        == "raiz-funil-pa-1504950"
    )
