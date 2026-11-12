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
        self.privado = True
        self.rascunho = False
        self.downloads: list[str] = []

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
            assets = [
                {"id": self._ids.setdefault(n, max(self._ids.values(), default=0) + 1), "name": n} for n in self.assets
            ]
            if u.path.endswith("/commits/HEAD"):
                return httpx.Response(200, json={"sha": "a" * 40})
            if "/releases/assets/" in u.path:
                nome = next(a["name"] for a in assets if a["id"] == int(u.path.rsplit("/", 1)[1]))
                assert req.headers.get("accept") == "application/octet-stream"
                self.downloads.append(nome)
                return httpx.Response(200, content=self.assets[nome])
            if u.path.endswith("/releases/7/assets"):
                inicio = (int(u.params.get("page", 1)) - 1) * 100
                return httpx.Response(200, json=assets[inicio : inicio + 100])
            if "/releases/" not in u.path:
                return httpx.Response(200, json={"private": self.privado})
            return httpx.Response(200, json={"id": 7, "assets": assets, "draft": self.rascunho})
        if u.host == "api.github.com" and req.method == "POST" and u.path.endswith("/git/refs"):
            return httpx.Response(201)
        if u.host == "api.github.com" and req.method == "DELETE":
            if "/git/refs/" in u.path:
                return httpx.Response(204)
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
    return ArmazemRelease(REPO, TAG, pasta, token=token, cliente=cli, privado=kw.pop("privado", True), **kw)


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
    a = _armazem(gh, tmp_path / "espelho")
    assert a.ler("saida/PA/imoveis_1504950.csv") == b"cod_imovel,ha\nPA-1,10\n"
    assert a.meta("saida/PA/imoveis_1504950.csv")["versao"] == "publicado"
    assert a.listar("saida/PA/") == ["saida/PA/imoveis_1504950.csv", "saida/PA/resumo_PA.csv"]
    assert a.ler("saida/AC/imoveis_1.csv") is None  # estado ainda não publicado
    # o back-end sincroniza a partir do Release (espelho é o próprio destino: nada é copiado duas vezes)
    from raiz.executor.sincronizar import sincronizar

    assert sincronizar(a, tmp_path / "espelho", ["PA"]) == ["saida/PA/imoveis_1504950.csv", "saida/PA/resumo_PA.csv"]
    with pytest.raises(PermissionError):
        _armazem(gh, tmp_path / "sem_token", token="").ler("saida/PA/imoveis_1504950.csv")
    assert "raiz_PA.tar.gz" in gh.downloads  # endpoint autenticado da API, nunca URL de navegador


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


# --- GitHub Actions: 4 jobs publicando juntos, cache baixado de novo, retomada no mesmo job ------------------------


def test_publicar_mescla_o_estados_json_relido_na_trava(gh, tmp_path, stub, monkeypatch):
    """Outro job publica o RO enquanto este sobe os pacotes do PA: o PA entra sem apagar o RO (o estados.json é relido
    dentro da trava), e a entrada traz completo, faltam e sem_imoveis pela conta do motor (raiz_situacao)."""
    import contextlib

    gh.assets["estados.json"] = json.dumps({"estados": {"AC": {"municipios": 22}}}).encode()
    a = _armazem(gh, tmp_path / "esp")
    trava_original = a._trava

    @contextlib.contextmanager
    def outro_job_publica_antes(nome=None, velha_s=600):
        if nome is None:  # trava do estados.json (a do pacote do estado é trava-publicar-<UF>)
            m = json.loads(gh.assets["estados.json"])
            m["estados"]["RO"] = {"municipios": 52, "versao": "ro"}
            gh.assets["estados.json"] = json.dumps(m).encode()
        with trava_original(nome, velha_s):
            yield

    monkeypatch.setattr(a, "_trava", outro_job_publica_antes)
    ex = Executor(a, tmp_path / "trab", stub.tarefas(tmp_path / "chamadas.log"))
    ex.rodar_uf("PA", [C1, C2])
    est = json.loads(gh.assets["estados.json"])["estados"]
    assert set(est) == {"AC", "RO", "PA"} and est["RO"]["versao"] == "ro"
    pa = est["PA"]
    # códigos de mentira (1500001...): os 144 municípios do PA na lista do IBGE continuam faltando
    assert pa["municipios"] == 2 and pa["completo"] is False and pa["faltam"]["imoveis"] == 144
    assert {"faltam", "sem_imoveis", "funil_completo", "controle", "versoes"} <= set(pa)
    # campos a mais de quem organiza a rodada (motor/rodar_estado.py) entram na mesma gravação
    a.publicar("PA", extra={"PA": {"motor": {"commit": "abc"}}})
    assert json.loads(gh.assets["estados.json"])["estados"]["PA"]["motor"] == {"commit": "abc"}


def test_espelho_nao_sobrescreve_o_que_esta_maquina_gravou(gh, tmp_path):
    """Retomada no mesmo job (outro processo): o pacote publicado é mais velho que o gravado aqui e não o troca."""
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {f"imoveis_{C1}.csv": b"cod_imovel\nvelho\n"})
    a = _armazem(gh, tmp_path / "esp")
    f = tmp_path / "novo.csv"
    f.write_text("cod_imovel\nnovo\n")
    a.por(f"saida/PA/imoveis_{C1}.csv", f, {"versao": "funil-1"})
    b = _armazem(gh, tmp_path / "esp")  # outro processo, mesmo espelho
    assert b.ler(f"saida/PA/imoveis_{C1}.csv") == b"cod_imovel\nnovo\n"
    c = _armazem(gh, tmp_path / "esp2")  # máquina nova: vem do Release
    assert c.ler(f"saida/PA/imoveis_{C1}.csv") == b"cod_imovel\nvelho\n"


def test_adotar_grava_a_caixa_do_municipio(gh, tmp_path, stub):
    """Sem a caixa, a assinatura dos alertas seria a do estado inteiro: todo alerta novo refaria o funil adotado."""
    import geopandas as gpd
    from shapely.geometry import box

    geo = tmp_path / "geo.parquet"
    gpd.GeoDataFrame({"cod_imovel": ["x"]}, geometry=[box(-50, -5, -49, -4)], crs=4674).to_parquet(geo)
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {f"imoveis_{C1}.csv": b"cod_imovel\nx\n"})
    gh.assets["raiz_geo_PA.tar.gz"] = gh.tar("PA", {f"geo_{C1}.parquet": geo.read_bytes()})
    ex = Executor(_armazem(gh, tmp_path / "esp"), tmp_path / "trab", stub.tarefas(tmp_path / "log"))
    ex.adotar("PA")
    assert ler_json(ex.a, f"marcas/PA/{C1}.json")["caixa"] == [-50.0, -5.0, -49.0, -4.0]


def test_assinatura_de_raster_nao_muda_quando_o_cache_e_baixado_de_novo(tmp_path):
    import os

    from raiz.executor.executor import assinatura_arquivo

    f = tmp_path / "PA_cobertura_2025.tif"
    f.write_bytes(b"x" * 100)
    antes = assinatura_arquivo(f)
    os.utime(f, (1, 1))  # o cache do Actions volta com outra data
    assert assinatura_arquivo(f) == antes
    f.write_bytes(b"x" * 101)  # exportação nova
    assert assinatura_arquivo(f) != antes


def test_prazo_corta_municipio_que_nao_termina(tmp_path, monkeypatch):
    """Depois do prazo e da folga, o município em curso é interrompido para o job publicar antes das 6 horas."""
    import time as t

    from raiz.executor.armazem import ArmazemLocal

    def lento(uf, cod, pasta):
        t.sleep(30)
        (pasta / f"imoveis_{cod}.csv").write_text("cod_imovel\nx\n")

    monkeypatch.setenv("RAIZ_GRACA_MIN", "0.02")
    ex = Executor(ArmazemLocal(tmp_path / "arm"), tmp_path / "trab",
                  [Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: "funil-1", lento)])  # fmt: skip
    t0 = t.time()
    r = ex.rodar_uf("PA", [C1, C2], lanes=2, ate_s=0.5)
    assert r["situacao"] == "parado_no_prazo" and t.time() - t0 < 15


def test_fatias_do_mesmo_estado_em_jobs_diferentes_nao_se_apagam(gh, tmp_path, stub):
    """MG em fatias: dois jobs (espelhos diferentes) rodam metade dos municípios cada e publicam um depois do outro. O
    segundo relê o pacote publicado pelo primeiro antes de empacotar: no fim estão os 4 municípios e as 4 marcas, e
    motor.fatias tem as duas fatias."""
    log = tmp_path / "chamadas.log"
    a = _armazem(gh, tmp_path / "job1")
    b = _armazem(gh, tmp_path / "job2")
    ea = Executor(a, tmp_path / "trab1", stub.tarefas(log))
    eb = Executor(b, tmp_path / "trab2", stub.tarefas(log))
    b.garantir_uf("PA")  # os dois jobs começam juntos: o B olha o Release antes de o A publicar
    ea.rodar_uf("PA", [C1, C2])  # o A termina e publica a fatia dele
    eb.rodar_uf("PA", [C3, C4])  # o B termina depois e publica relendo o pacote do A
    a.publicar("PA", extra={"PA": {"motor": {"commit": "x", "fatias": {"1": {"completo": True}}}}})
    b.publicar("PA", extra={"PA": {"motor": {"commit": "x", "fatias": {"2": {"completo": True}}}}})
    pacote = gh.membros("raiz_PA.tar.gz")
    assert {f"PA/imoveis_{c}.csv" for c in (C1, C2, C3, C4)} <= set(pacote)
    assert set(json.loads(gh.assets["raiz_controle_PA.json"])["marcas"]) == {str(c) for c in (C1, C2, C3, C4)}
    pa = json.loads(gh.assets["estados.json"])["estados"]["PA"]
    assert pa["municipios"] == 4 and set(pa["motor"]["fatias"]) == {"1", "2"}
    # o primeiro job publica de novo (fim da rodada dele): nada do segundo some
    a.publicar("PA")
    assert {f"PA/filtros_{c}.csv" for c in (C1, C2, C3, C4)} <= set(gh.membros("raiz_PA.tar.gz"))
