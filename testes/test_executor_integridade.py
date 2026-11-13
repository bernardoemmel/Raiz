"""Partições íntegras, invalidação e interrupção real de um filho local de teste."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from raiz.executor.armazem import ArmazemLocal, por_json, sha256_arquivo
from raiz.executor.executor import Executor, Tarefa


def executor(tmp_path, *, versao="v1", fonte="f1", falhar=False):
    def rodar(uf, cod, pasta):
        if falhar:
            raise RuntimeError("falha controlada")
        (pasta / f"imoveis_{cod}.csv").write_text("cod_imovel,area\nsintetico,1\n")

    tarefa = Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: versao, rodar, lambda *_: {"fonte": fonte})
    return Executor(ArmazemLocal(tmp_path / "arm"), tmp_path / "motor", [tarefa])


@pytest.mark.parametrize("dano", ["bytes", "versao", "fonte", "erro"])
def test_marcador_so_sela_versoes_fontes_e_bytes_conferidos(tmp_path, dano):
    cod = 1400100
    ex = executor(tmp_path)
    ex.rodar_uf("RR", [cod])
    antes = ex.marca("RR", cod)
    assert antes["integridade"]["situacao"] == "integro"
    assert len(antes["integridade"]["sha256"]) == 64
    assert ex.confirmar_integridade("RR", cod)
    assert ex.marca("RR", cod) == antes
    if dano == "bytes":
        ex.a._p(f"saida/RR/imoveis_{cod}.csv").write_text("corrompido\n")
    elif dano == "versao":
        ex = executor(tmp_path, versao="v2")
    elif dano == "fonte":
        ex = executor(tmp_path, fonte="f2")
    else:
        antes["tarefas"]["funil"]["erro"] = "incompleto"
        por_json(ex.a, ex.chave_marca("RR", cod), antes)
    assert not ex.confirmar_integridade("RR", cod)
    assert "integridade" not in ex.marca("RR", cod)
    assert ex.plano("RR", cod) == ["funil"]
    ex.rodar_uf("RR", [cod])
    assert ex.confirmar_integridade("RR", cod)


def test_marca_legada_integra_recebe_selo_sem_recalcular_ou_trocar_proveniencia(tmp_path):
    ex = executor(tmp_path)
    ex.rodar_uf("RR", [1400100])
    marca = ex.marca("RR", 1400100)
    marca.pop("integridade")
    por_json(ex.a, ex.chave_marca("RR", 1400100), marca)
    estado = ex.rodar_uf("RR", [1400100])
    assert estado["rodados"] == 0
    depois = ex.marca("RR", 1400100)
    assert depois["tarefas"] == marca["tarefas"]
    assert depois["integridade"]["situacao"] == "integro"


def test_tarefa_falha_nao_deixa_selo_antigo(tmp_path):
    ex = executor(tmp_path)
    ex.rodar_uf("RR", [1400100])
    ex = executor(tmp_path, versao="v2", falhar=True)
    assert ex.rodar_uf("RR", [1400100])["situacao"] == "com_erro"
    assert "integridade" not in ex.marca("RR", 1400100)


# Códigos dos 15 municípios de RR; as propriedades/geometrias são sintéticas.
# O ensaio usa processos locais e não tem qualquer acesso à API do Actions.
CODS = [1400027, 1400050, 1400100, 1400159, 1400175, 1400209, 1400233, 1400282,
        1400308, 1400407, 1400456, 1400472, 1400506, 1400605, 1400704]  # fmt: skip
PROGRAMA = """
import json, os, sys, time
from pathlib import Path
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from raiz.executor.armazem import ArmazemLocal
from raiz.executor.executor import Executor, Tarefa
base=Path(sys.argv[1]); cods=json.loads(sys.argv[2])
def fonte(uf,cod,pasta):
    with (base/'chamadas').open('a') as f: f.write(str(cod)+'\\n')
    pd.DataFrame({'cod_imovel':[f'sintetico-{cod}-{i}' for i in range(3)],
                  'area':[1.0,None,0.0]}).to_csv(pasta/f'imoveis_{cod}.csv',index=False)
    gpd.GeoDataFrame({'cod_imovel':[f'sintetico-{cod}-{i}' for i in range(3)]},
        geometry=[Polygon([(0,0),(1,0),(1,1),(0,0)]), None, Polygon()],
        crs='EPSG:4326').to_parquet(pasta/f'geo_{cod}.parquet')
def conferir(uf,cod,pasta):
    if str(cod)==os.environ.get('RAIZ_TESTE_PARAR_EM'):
        (base/'interromper').touch()
        while True: time.sleep(0.1)
    d=pd.read_csv(pasta/f'imoveis_{cod}.csv')
    g=gpd.read_parquet(pasta/f'geo_{cod}.parquet')
    (pasta/f'qualidade_{cod}.json').write_text(json.dumps({
        'imoveis':len(d),'nulos':{k:int(v) for k,v in d.isna().sum().items()},
        'geometrias_nulas':int(g.geometry.isna().sum()),
        'geometrias_sem_area':sum(x is not None and x.area==0 for x in g.geometry)},sort_keys=True))
tarefas=[Tarefa('funil',(),('imoveis_{cod}.csv','geo_{cod}.parquet'),lambda:'fixture-v1',fonte),
         Tarefa('qualidade',('funil',),('qualidade_{cod}.json',),lambda:'fixture-v1',conferir)]
ex=Executor(ArmazemLocal(base/'arm'),base/'trabalho',tarefas)
r=ex.rodar_uf('RR',cods)
(base/'resultado.json').write_text(json.dumps(r))
"""


def test_rr_interrompido_retomado_igual_inteiro_em_imoveis_nulos_e_geometrias(tmp_path):
    script = tmp_path / "ensaio.py"
    script.write_text(PROGRAMA)
    raiz = Path(__file__).resolve().parents[1]
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(raiz), "OMP_NUM_THREADS": "1"}
    inteiro, retomado = tmp_path / "inteiro", tmp_path / "retomado"
    inteiro.mkdir()
    retomado.mkdir()
    cmd = lambda pasta: [sys.executable, str(script), str(pasta), json.dumps(CODS)]  # noqa: E731
    subprocess.run(cmd(inteiro), env=env, check=True, timeout=60, capture_output=True)
    child = subprocess.Popen(
        cmd(retomado),
        env={**env, "RAIZ_TESTE_PARAR_EM": str(CODS[6])},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        prazo = time.monotonic() + 30
        while not (retomado / "interromper").exists() and child.poll() is None and time.monotonic() < prazo:
            time.sleep(0.02)
        assert (retomado / "interromper").exists()
        os.kill(child.pid, signal.SIGKILL)
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    marcas = retomado / "arm" / "marcas" / "RR"
    salvas = {cod: (marcas / f"{cod}.json").read_bytes() for cod in CODS[:6]}
    assert all(json.loads(b)["integridade"]["situacao"] == "integro" for b in salvas.values())
    assert "integridade" not in json.loads((marcas / f"{CODS[6]}.json").read_text())
    subprocess.run(cmd(retomado), env=env, check=True, timeout=60, capture_output=True)
    assert salvas == {cod: (marcas / f"{cod}.json").read_bytes() for cod in CODS[:6]}
    # A fonte do município interrompido também já estava íntegra: não é refeita.
    chamadas = (retomado / "chamadas").read_text().splitlines()
    assert chamadas == list(map(str, CODS))
    for cod in CODS:
        assert json.loads((marcas / f"{cod}.json").read_text())["integridade"]["situacao"] == "integro"
        for padrao in ("imoveis_{}.csv", "geo_{}.parquet", "qualidade_{}.json"):
            relativo = Path("arm/saida/RR") / padrao.format(cod)
            assert sha256_arquivo(inteiro / relativo) == sha256_arquivo(retomado / relativo)
        qualidade = json.loads((retomado / f"arm/saida/RR/qualidade_{cod}.json").read_text())
        assert qualidade == {
            "imoveis": 3,
            "nulos": {"cod_imovel": 0, "area": 1},
            "geometrias_nulas": 1,
            "geometrias_sem_area": 1,
        }
    assert json.loads((retomado / "resultado.json").read_text())["feitos"] == 15


def test_fonte_muda_durante_calculo_nao_declara_municipio_pronto(tmp_path):
    fonte = {"versao": "antes"}

    def rodar(uf, cod, pasta):
        (pasta / f"imoveis_{cod}.csv").write_text("cod_imovel\nsintetico\n")
        fonte["versao"] = "depois"

    ex = Executor(
        ArmazemLocal(tmp_path / "arm"),
        tmp_path / "motor",
        [Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: "v1", rodar, lambda *_: dict(fonte))],
    )
    r = ex.rodar_uf("RR", [1400100])
    assert r["situacao"] == "com_erro"
    assert r["processamento"]["municipios"]["com_erro"] == 1
    assert r["processamento"]["municipios"]["prontos"] == 0
    assert "integridade" not in ex.marca("RR", 1400100)
    assert ex.rodar_uf("RR", [1400100])["situacao"] == "pronto"
