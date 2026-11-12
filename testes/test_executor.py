"""Agente Dados: o motor dentro do produto. Retoma depois de matar o processo no meio de um estado sem refazer o que
terminou; mudou a versão de uma tarefa, refaz só ela e só onde a saída dela mudou; fonte de um município mudou, só ele;
cada arquivo no armazém leva versão e data; armazém S3 (moto); agenda completa x parcial; painel."""

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from raiz.executor.armazem import ArmazemLocal, ler_json
from raiz.executor.executor import Executor, Tarefa

RAIZ = Path(__file__).resolve().parents[1]

# tarefas de mentira: escrevem arquivos pequenos, registram cada chamada num log e leem uma "fonte" por município
STUB = textwrap.dedent("""
    import os, time
    from pathlib import Path
    from raiz.executor.executor import Tarefa

    def tarefas(base: Path):
        log = base / "chamadas.log"
        fontes = base / "fontes"
        versoes = base / "versoes.json"

        def ver(nome):
            import json
            v = json.loads(versoes.read_text()) if versoes.exists() else {}
            return v.get(nome, nome + "-1")

        def anota(nome, cod):
            with open(log, "a") as f:
                f.write(f"{nome} {cod}\\n")

        def funil(uf, cod, pasta):
            anota("funil", cod)
            trava = os.environ.get("TRAVAR_EM")
            if trava and int(trava) == cod:
                (base / "travado").write_text("1")
                time.sleep(600)
            fonte = fontes / f"{cod}.txt"
            if cod == 99:
                return  # município sem imóvel rural: fica vazio
            corpo = fonte.read_text() if fonte.exists() else "x,1\\n"
            (pasta / f"imoveis_{cod}.csv").write_text("cod_imovel,ha\\n" + corpo)

        def filtros(uf, cod, pasta):
            anota("filtros", cod)
            v = ver("filtros")
            # a versão nova só muda a saída do município 2 (correção que afeta só ele)
            extra = v if cod == 2 else "igual"
            (pasta / f"filtros_{cod}.csv").write_text(f"cod_imovel,filtro\\nx,{extra}\\n")

        def flag(uf, cod, pasta):
            anota("flag", cod)
            (pasta / f"flag_{cod}.csv").write_text("cod_imovel,flag\\nx,1\\n")

        def terra(uf, cod, pasta):
            anota("terra", cod)
            assert (pasta / f"filtros_{cod}.csv").exists()
            (pasta / f"terra_{cod}.csv").write_text("cod_imovel,caminho\\nx,posse\\n")

        def externas_funil(uf, cod, marca):
            f = fontes / f"{cod}.txt"
            return {"fonte": f.read_text() if f.exists() else None}

        return [
            Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: ver("funil"), funil, externas_funil, True),
            Tarefa("filtros", ("funil",), ("filtros_{cod}.csv",), lambda: ver("filtros"), filtros),
            Tarefa("flag", ("funil",), ("flag_{cod}.csv",), lambda: ver("flag"), flag),
            Tarefa("terra", ("funil", "filtros"), ("terra_{cod}.csv",), lambda: ver("terra"), terra),
        ]
""")

SCRIPT = textwrap.dedent("""
    import sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    import stub
    from raiz.executor.armazem import ArmazemLocal
    from raiz.executor.executor import Executor
    base = Path(sys.argv[2])
    ex = Executor(ArmazemLocal(base / "armazem"), base / "trabalho", stub.tarefas(base))
    ex.rodar_uf("PA", [1, 2, 3, 4, 5])
""")


@pytest.fixture
def base(tmp_path):
    (tmp_path / "stub.py").write_text(STUB)
    (tmp_path / "rodar.py").write_text(SCRIPT)
    (tmp_path / "fontes").mkdir()
    sys.path.insert(0, str(tmp_path))
    import importlib

    import stub  # noqa: F401

    importlib.reload(sys.modules["stub"])
    yield tmp_path
    sys.path.remove(str(tmp_path))


def _executor(base: Path, trabalho: str = "trabalho") -> Executor:
    import stub

    return Executor(ArmazemLocal(base / "armazem"), base / trabalho, stub.tarefas(base))


def _chamadas(base: Path) -> list[tuple[str, int]]:
    f = base / "chamadas.log"
    if not f.exists():
        return []
    return [(a, int(b)) for a, b in (x.split() for x in f.read_text().splitlines())]


def _limpa_log(base: Path):
    (base / "chamadas.log").unlink(missing_ok=True)


def test_matar_no_meio_do_estado_e_retomar_sem_refazer(base):
    env = {**os.environ, "TRAVAR_EM": "3", "PYTHONPATH": str(RAIZ)}
    p = subprocess.Popen([sys.executable, str(base / "rodar.py"), str(base), str(base)], env=env, cwd=RAIZ)
    try:
        for _ in range(600):
            if (base / "travado").exists() or p.poll() is not None:
                break
            time.sleep(0.05)
        assert (base / "travado").exists(), "o processo não chegou ao município 3"
        os.kill(p.pid, signal.SIGKILL)  # mata no meio do município 3
        p.wait(10)
    finally:
        if p.poll() is None:
            p.kill()
    antes = _chamadas(base)
    assert ("terra", 2) in antes and ("funil", 3) in antes and ("filtros", 3) not in antes
    estado = ler_json(ArmazemLocal(base / "armazem"), "estado/PA.json")
    assert estado["situacao"] == "em_andamento"  # morreu sem fechar
    _limpa_log(base)
    # a máquina "reiniciou": pasta de trabalho nova, vazia; o que terminou está no armazém
    r = _executor(base, "trabalho_nova").rodar_uf("PA", [1, 2, 3, 4, 5])
    depois = _chamadas(base)
    assert not [c for c in depois if c[1] in (1, 2)], depois  # 1 e 2 já tinham terminado: nada refeito
    assert {t for t, c in depois if c == 3} == {"funil", "filtros", "flag", "terra"}
    assert {c for _, c in depois} == {3, 4, 5}
    assert r["situacao"] == "pronto" and r["feitos"] == 5 and r["retomado_de"]
    # e numa terceira volta, nada roda
    _limpa_log(base)
    r = _executor(base).rodar_uf("PA", [1, 2, 3, 4, 5])
    assert _chamadas(base) == [] and r["rodados"] == 0


def test_mudar_versao_refaz_so_o_que_a_mudanca_afeta(base):
    ex = _executor(base)
    ex.rodar_uf("PA", [1, 2, 3])
    _limpa_log(base)
    (base / "versoes.json").write_text(json.dumps({"filtros": "filtros-2"}))
    r = _executor(base).rodar_uf("PA", [1, 2, 3])
    ch = _chamadas(base)
    assert sorted(c for t, c in ch if t == "filtros") == [1, 2, 3]  # a tarefa da versão nova roda em todos
    assert not [c for c in ch if c[0] in ("funil", "flag")]  # o que não depende dela fica
    assert [c for t, c in ch if t == "terra"] == [2]  # só onde a saída de filtros mudou
    assert r["situacao"] == "pronto"
    m = ler_json(ex.a, "marcas/PA/2.json")
    assert m["tarefas"]["filtros"]["versao"] == "filtros-2" and m["tarefas"]["funil"]["versao"] == "funil-1"


def test_mudar_versao_do_motor_so_os_municipios_afetados(base):
    """O motor muda e só o município cuja saída muda propaga para as tarefas seguintes; a fonte de um município muda
    e só ele roda."""
    for c in (1, 2, 3):
        (base / "fontes" / f"{c}.txt").write_text(f"im{c},10\n")
    _executor(base).rodar_uf("PA", [1, 2, 3])
    _limpa_log(base)
    (base / "fontes" / "3.txt").write_text("im3,10\nnovo,5\n")  # CAR do município 3 mudou
    _executor(base).rodar_uf("PA", [1, 2, 3])
    ch = _chamadas(base)
    assert {c for _, c in ch} == {3} and {t for t, _ in ch} == {"funil", "filtros", "flag", "terra"}


def test_municipio_vazio_e_erro(base, monkeypatch):
    ex = _executor(base)
    r = ex.rodar_uf("PA", [99, 1])
    assert r["vazios"] == 1 and r["situacao"] == "pronto"
    m = ler_json(ex.a, "marcas/PA/99.json")
    assert m["tarefas"]["funil"]["vazio"] and "filtros" not in m["tarefas"]  # nada depois do funil vazio
    # uma tarefa que quebra: registra o erro, segue para o próximo município e refaz na próxima volta
    import stub

    ts = stub.tarefas(base)
    quebra = ts[1]
    ts[1] = Tarefa(quebra.nome, quebra.depende, quebra.saidas, lambda: "filtros-quebrada",
                   lambda uf, cod, pasta: (_ for _ in ()).throw(ValueError("sem rede")))  # fmt: skip
    ex2 = Executor(ArmazemLocal(base / "armazem"), base / "trabalho", ts)
    r = ex2.rodar_uf("PA", [1, 2])
    assert r["situacao"] == "com_erro" and {e["cod"] for e in r["erros"]} == {1, 2}
    assert ex2.plano("PA", 1)[0] == "filtros"  # fica pendente
    assert "terra" not in ler_json(ex2.a, "marcas/PA/2.json")["tarefas"]  # não roda em cima de um erro


def test_arquivo_no_armazem_leva_versao_e_data(base):
    ex = _executor(base)
    ex.rodar_uf("PA", [1])
    meta = ex.a.meta("saida/PA/imoveis_1.csv")
    assert meta["versao"] == "funil-1" and meta["tarefa"] == "funil" and meta["data"].startswith("20")
    assert meta["sha256"] and meta["cod_municipio"] == "1"
    assert sorted(ex.a.listar("saida/PA/")) == ["saida/PA/filtros_1.csv", "saida/PA/flag_1.csv",
                                                 "saida/PA/imoveis_1.csv", "saida/PA/terra_1.csv"]  # fmt: skip


def test_armazem_s3_com_moto(tmp_path, monkeypatch):
    import boto3
    from moto import mock_aws

    from raiz.executor.armazem import ArmazemS3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "teste")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "teste")
    with mock_aws():
        cli = boto3.client("s3", region_name="us-east-1")
        cli.create_bucket(Bucket="raiz")
        a = ArmazemS3("raiz", "producao", cliente=cli)
        f = tmp_path / "imoveis_1.csv"
        f.write_text("cod_imovel\nx\n")
        m = a.por("saida/PA/imoveis_1.csv", f, {"versao": "funil-1", "municipio": "São Félix"})
        assert a.meta("saida/PA/imoveis_1.csv")["versao"] == "funil-1"
        assert a.meta("saida/PA/imoveis_1.csv")["municipio"] == "São Félix"  # acento sobrevive
        assert a.meta("saida/PA/imoveis_1.csv")["sha256"] == m["sha256"]
        assert a.listar("saida/") == ["saida/PA/imoveis_1.csv"]
        assert (
            a.baixar("saida/PA/imoveis_1.csv", tmp_path / "x.csv")
            and (tmp_path / "x.csv").read_text() == "cod_imovel\nx\n"
        )
        assert a.meta("nao/existe") is None and a.ler("nao/existe") is None and not a.baixar("nao", tmp_path / "y")
        # o executor roda igual sobre o S3
        (tmp_path / "stub.py").write_text(STUB)
        sys.path.insert(0, str(tmp_path))
        try:
            import importlib

            import stub

            importlib.reload(stub)
            ex = Executor(a, tmp_path / "trabalho", stub.tarefas(tmp_path))
            assert ex.rodar_uf("PA", [1, 2])["situacao"] == "pronto"
            assert ler_json(a, "marcas/PA/2.json")["tarefas"]["terra"]["saidas"]
        finally:
            sys.path.remove(str(tmp_path))


def test_agenda_completa_uma_vez_por_colecao(base, monkeypatch):
    from raiz.executor import agenda

    ex = _executor(base)
    monkeypatch.setenv("RAIZ_MB_ANO", "2025")
    r = agenda.ciclo(ex, ["PA"])  # primeira vez: coleção nova para o armazém, rodada completa
    assert r["completa"] and r["colecao"] == "2025"
    _limpa_log(base)
    r = agenda.ciclo(_executor(base), ["PA"])  # sem municípios pedidos: usa a lista do executor (vazia aqui)
    assert not r["completa"]
    monkeypatch.setenv("RAIZ_MB_ANO", "2026")  # coleção nova do MapBiomas
    assert agenda.precisa_completa(ex.a)


def test_producao_tem_todas_as_tarefas_em_ordem():
    from raiz.executor import tarefas as T
    from raiz.executor.executor import ordenar
    from raiz.funil.rodar import TAREFAS

    nomes = [t.nome for t in ordenar(T.tarefas_producao())]
    assert set(nomes) == set(TAREFAS) - {"carga"}  # a carga é do back-end, a partir do armazém
    assert nomes.index("funil") == 0 and nomes.index("terra") < nomes.index("ficha") < nomes.index("desenvolvedor")
    v = {t.nome: t.versao() for t in T.tarefas_producao()}
    assert all(x.startswith(n + "-") for n, x in v.items())
    assert len(T.municipios_da_uf("PA")) == 144 and sum(len(T.municipios_da_uf(u)) for u in T.UFS) == 5571
