"""Armazém no Release "dados" do GitHub: lê os pacotes no formato de motor/publicar_dados.py, o executor grava e
publica (pacotes com versão e data de cada arquivo, marcas de retomada, estados.json por último), uma máquina nova
retoma do Release sem refazer o que terminou, o PA publicado antes é adotado, e nada sobe sem token nem com coluna
proibida. O GitHub é simulado (sem rede)."""

import io
import json
import sys
import tarfile
from pathlib import Path

import httpx
import pytest

from raiz.executor.armazem import ArmazemRelease, do_config, ler_json
from raiz.executor.executor import Executor, Tarefa

REPO, TAG = "bernardoemmel/raiz", "dados"


class GitHubFalso:
    """Release com assets em memória: download público, API com token para apagar e subir."""

    def __init__(self):
        self.assets: dict[str, bytes] = {}
        self.uploads: list[str] = []
        self._ids: dict[str, int] = {}

    def tar(self, uf: str, arquivos: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            for n, d in arquivos.items():
                i = tarfile.TarInfo(f"{uf}/{n}")
                i.size = len(d)
                t.addfile(i, io.BytesIO(d))
        return buf.getvalue()

    def membros(self, nome: str) -> dict[str, bytes]:
        with tarfile.open(fileobj=io.BytesIO(self.assets[nome]), mode="r:gz") as t:
            return {m.name: t.extractfile(m).read() for m in t.getmembers() if m.isfile()}

    def __call__(self, req: httpx.Request) -> httpx.Response:
        u = req.url
        if u.host == "github.com":
            nome = u.path.rsplit("/", 1)[1]
            return httpx.Response(200, content=self.assets[nome]) if nome in self.assets else httpx.Response(404)
        tok = req.headers.get("authorization") == "Bearer segredo"
        if not tok:
            return httpx.Response(401)
        if u.host == "api.github.com" and req.method == "GET":
            assets = [{"id": self._ids.setdefault(n, len(self._ids) + 1), "name": n} for n in self.assets]
            return httpx.Response(200, json={"id": 7, "assets": assets})
        if u.host == "api.github.com" and req.method == "DELETE":
            aid = int(u.path.rsplit("/", 1)[1])
            nome = next(n for n, i in self._ids.items() if i == aid)
            self.assets.pop(nome, None)
            self._ids.pop(nome)
            return httpx.Response(204)
        if u.host == "uploads.github.com" and req.method == "POST":
            nome = u.params["name"]
            assert nome not in self.assets, "asset repetido: tinha de apagar antes"
            self.assets[nome] = req.content
            self.uploads.append(nome)
            return httpx.Response(201, json={"name": nome})
        return httpx.Response(400)


@pytest.fixture
def gh():
    return GitHubFalso()


def _armazem(gh, pasta: Path, token="segredo", **kw) -> ArmazemRelease:
    cli = httpx.Client(transport=httpx.MockTransport(gh))
    return ArmazemRelease(REPO, TAG, pasta, token=token, cliente=cli, **kw)


STUB = """
from pathlib import Path
from raiz.executor.executor import Tarefa

def tarefas(log: Path, quebrar_em=None):
    def anota(n, c):
        with open(log, "a") as f:
            f.write(f"{n} {c}\\n")

    def funil(uf, cod, pasta):
        anota("funil", cod)
        if quebrar_em == cod:
            raise KeyboardInterrupt  # a máquina morre no meio (não é erro de tarefa)
        (pasta / f"imoveis_{cod}.csv").write_text("cod_imovel,ha\\nx,1\\n")

    def filtros(uf, cod, pasta):
        anota("filtros", cod)
        (pasta / f"filtros_{cod}.csv").write_text("cod_imovel,filtro\\nx,ok\\n")

    return [Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: "funil-1", funil, pode_ficar_vazio=True),
            Tarefa("filtros", ("funil",), ("filtros_{cod}.csv",), lambda: "filtros-1", filtros)]
"""


@pytest.fixture
def stub(tmp_path):
    (tmp_path / "stub_release.py").write_text(STUB)
    sys.path.insert(0, str(tmp_path))
    import importlib

    import stub_release

    importlib.reload(stub_release)
    yield stub_release
    sys.path.remove(str(tmp_path))


def _chamadas(log: Path):
    return [tuple(x.split()) for x in log.read_text().splitlines()] if log.exists() else []


def test_le_o_pacote_publicado_pelo_motor(gh, tmp_path):
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {"imoveis_1504950.csv": b"cod_imovel,ha\nPA-1,10\n",
                                                "resumo_PA.csv": b"cod_ibge,imoveis\n1504950,1\n"})  # fmt: skip
    gh.assets["estados.json"] = json.dumps({"estados": {"PA": {"municipios": 1, "versao": "x"}}}).encode()
    a = _armazem(gh, tmp_path / "espelho", token="")  # sem token (o do ambiente não vale aqui)
    assert a.ler("saida/PA/imoveis_1504950.csv") == b"cod_imovel,ha\nPA-1,10\n"
    assert a.meta("saida/PA/imoveis_1504950.csv")["versao"] == "publicado"
    assert a.listar("saida/PA/") == ["saida/PA/imoveis_1504950.csv", "saida/PA/resumo_PA.csv"]
    assert a.ler("saida/AC/imoveis_1.csv") is None  # estado ainda não publicado
    # o back-end sincroniza a partir do Release (espelho é o próprio destino: nada é copiado duas vezes)
    from raiz.executor.sincronizar import sincronizar

    assert sincronizar(a, tmp_path / "espelho", ["PA"]) == ["saida/PA/imoveis_1504950.csv", "saida/PA/resumo_PA.csv"]
    with pytest.raises(PermissionError):
        a.publicar("PA")  # sem token, só lê


C1, C2, C3, C4 = 1500001, 1500002, 1500003, 1500004


def test_executor_publica_e_maquina_nova_retoma_do_release(gh, tmp_path, stub):
    log = tmp_path / "chamadas.log"
    a = _armazem(gh, tmp_path / "maquina1", intervalo_s=0)  # publica depois de cada município
    ex = Executor(a, tmp_path / "trabalho1", stub.tarefas(log, quebrar_em=C3))
    with pytest.raises(KeyboardInterrupt):
        ex.rodar_uf("PA", [C1, C2, C3, C4])
    assert {"raiz_PA.tar.gz", "raiz_controle_PA.json", "estados.json"} <= set(gh.assets)
    assert gh.uploads[-1] == "estados.json"  # o manifesto sempre por último
    pacote = gh.membros("raiz_PA.tar.gz")
    vers = json.loads(pacote["PA/_versoes.json"])
    v1 = vers[f"imoveis_{C1}.csv"]
    assert v1["versao"] == "funil-1" and v1["data"].startswith("20") and v1["cod_municipio"] == str(C1)
    ctl = json.loads(gh.assets["raiz_controle_PA.json"])
    assert set(ctl["marcas"]) == {str(C1), str(C2)} and ctl["estado"]["situacao"] == "em_andamento"
    man = json.loads(gh.assets["estados.json"])["estados"]["PA"]
    assert man["municipios"] == 2 and man["versoes"] == {"funil": "funil-1", "filtros": "filtros-1"}
    # outra máquina (espelho e pasta de trabalho vazios): retoma do Release sem refazer 1 e 2
    log.unlink()
    b = _armazem(gh, tmp_path / "maquina2")
    r = Executor(b, tmp_path / "trabalho2", stub.tarefas(log)).rodar_uf("PA", [C1, C2, C3, C4])
    assert {c for _, c in _chamadas(log)} == {str(C3), str(C4)} and r["situacao"] == "pronto"
    man = json.loads(gh.assets["estados.json"])["estados"]["PA"]
    assert man["municipios"] == 4 and man["situacao"] == "pronto" and man["tabelas"]["filtros"] == 4
    assert set(json.loads(gh.assets["raiz_controle_PA.json"])["marcas"]) == {str(c) for c in (C1, C2, C3, C4)}


def test_adotar_o_que_ja_foi_publicado(gh, tmp_path, stub):
    arquivos = {f"imoveis_{C1}.csv": b"cod_imovel\nx\n", f"imoveis_{C2}.csv": b"cod_imovel\ny\n",
                f"filtros_{C1}.csv": b"cod_imovel\nx\n"}  # fmt: skip
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", arquivos)
    log = tmp_path / "chamadas.log"
    ex = Executor(_armazem(gh, tmp_path / "esp"), tmp_path / "trab", stub.tarefas(log))
    r = ex.adotar("PA")
    assert r["adotados"] == 2 and r["tarefas"] == {"funil": 2, "filtros": 1}
    assert ex.plano("PA", C1) == [] and ex.plano("PA", C2) == ["filtros"]  # só o que falta
    ex.rodar_uf("PA", [C1, C2])
    assert _chamadas(log) == [("filtros", str(C2))]
    assert ler_json(ex.a, f"marcas/PA/{C1}.json")["tarefas"]["funil"]["adotado"]


def test_nao_publica_coluna_proibida(gh, tmp_path):
    a = _armazem(gh, tmp_path / "esp")
    f = tmp_path / f"imoveis_{C1}.csv"
    f.write_text("cod_imovel,nome_proprietario\nx,y\n")
    a.por(f"saida/PA/imoveis_{C1}.csv", f, {"versao": "funil-1"})
    with pytest.raises(ValueError, match="proibida"):
        a.publicar("PA")
    assert "raiz_PA.tar.gz" not in gh.assets


def test_armazem_padrao_e_o_release(monkeypatch):
    import raiz.config as C

    cfg = C.Config()
    monkeypatch.setattr(cfg, "armazem_url", None)
    monkeypatch.setattr(C, "config", lambda: cfg)
    a = do_config()
    assert isinstance(a, ArmazemRelease) and a.repo == REPO and a.tag == TAG
    assert isinstance(do_config("release-github://outro/repo/tag2"), ArmazemRelease)


def test_tarefa_sem_banco(monkeypatch):
    """No Actions não há Postgres: o lote só pinga o Healthchecks (a marca do executor guarda o andamento)."""
    from raiz.operacao.healthchecks import Healthchecks
    from raiz.operacao.lotes import lote

    with lote(None, Healthchecks(chave_ping=""), "funil", "PA", 1) as reg:
        reg.nota("ok")
    Tarefa  # noqa: B018 - importada para o leitor achar o contrato
