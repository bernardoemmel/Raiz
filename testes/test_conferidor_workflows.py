"""Conferidor de etapas: uma issue por workflow, sem spam, fecha quando volta a passar, registra em arquivo."""

import base64
import datetime as dt
import json
from pathlib import Path

import httpx
import yaml

from raiz.operacao import conferidor_workflows as C

RAIZ = Path(__file__).resolve().parents[1]
AGORA = dt.datetime(2026, 11, 17, 3, 0, tzinfo=dt.UTC)


class FalsoGitHub:
    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.comentarios: list[tuple[int, str]] = []
        self.arquivo: str | None = None
        self.sha = 0
        self.branch = False
        self.rotulos = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        caminho = req.url.path.split("/repos/exemplo/raiz", 1)[1]
        corpo = json.loads(req.content) if req.content else {}
        m = req.method
        if m == "POST" and caminho == "/labels":
            self.rotulos += 1
            return httpx.Response(201 if self.rotulos == 1 else 422, json={})
        if m == "GET" and caminho == "/issues":
            abertas = [i for i in self.issues.values() if i["state"] == "open"]
            return httpx.Response(200, json=abertas)
        if m == "POST" and caminho == "/issues":
            n = len(self.issues) + 1
            self.issues[n] = {"number": n, "state": "open", **corpo}
            return httpx.Response(201, json=self.issues[n])
        if caminho.startswith("/issues/") and caminho.endswith("/comments"):
            self.comentarios.append((int(caminho.split("/")[2]), corpo["body"]))
            return httpx.Response(201, json={})
        if m == "PATCH" and caminho.startswith("/issues/"):
            self.issues[int(caminho.split("/")[2])].update(corpo)
            return httpx.Response(200, json={})
        if caminho.startswith("/actions/runs/"):
            return httpx.Response(
                200,
                json={
                    "jobs": [
                        {
                            "name": "UF PA",
                            "conclusion": "failure",
                            "html_url": "https://x/job",
                            "steps": [
                                {"name": "Rodar motor", "conclusion": "failure"},
                                {"name": "ok", "conclusion": "success"},
                            ],
                        },
                        {"name": "UF AC", "conclusion": "success", "steps": []},
                    ]
                },
            )
        if caminho == f"/git/ref/heads/{C.BRANCH_REGISTRO}":
            return httpx.Response(200 if self.branch else 404, json={})
        if m == "POST" and caminho == "/git/trees":
            self.arquivo = corpo["tree"][0]["content"]
            return httpx.Response(201, json={"sha": "t"})
        if m == "POST" and caminho == "/git/commits":
            assert corpo["parents"] == []
            return httpx.Response(201, json={"sha": "c"})
        if m == "POST" and caminho == "/git/refs":
            self.branch = True
            return httpx.Response(201, json={})
        if caminho == f"/contents/{C.ARQUIVO_REGISTRO}":
            if m == "GET":
                return httpx.Response(
                    200, json={"sha": str(self.sha), "content": base64.b64encode(self.arquivo.encode()).decode()}
                )
            assert corpo["branch"] == C.BRANCH_REGISTRO and corpo["sha"] == str(self.sha)
            self.arquivo = base64.b64decode(corpo["content"]).decode()
            self.sha += 1
            return httpx.Response(200, json={})
        raise AssertionError(f"rota inesperada {m} {caminho}")


def _ex(conclusao: str, run_id: int = 10, nome: str = "Vigilância diária", caminho="vigilancia.yml"):
    return C.Execucao.do_evento(
        {
            "workflow_run": {
                "name": nome,
                "path": f".github/workflows/{caminho}",
                "conclusion": conclusao,
                "id": run_id,
                "run_number": run_id,
                "run_attempt": 1,
                "html_url": f"https://x/runs/{run_id}",
                "head_branch": "main",
                "event": "schedule",
                "head_sha": "abcdef123",
                "updated_at": "2026-11-17T09:30:00Z",
            }
        }
    )


def _gh():
    falso = FalsoGitHub()
    return falso, C.GitHub("exemplo/raiz", "token-sintetico", httpx.Client(transport=httpx.MockTransport(falso)))


def test_falha_abre_uma_issue_e_repeticao_nao_vira_spam():
    falso, gh = _gh()
    assert C.conferir(_ex("failure", 10), gh, AGORA)["acao"] == "abriu"
    issue = falso.issues[1]
    assert issue["labels"] == [C.ROTULO] and "Vigilância diária" in issue["title"]
    assert "UF PA" in issue["body"] and "Rodar motor" in issue["body"] and "UF AC" not in issue["body"]
    assert "06:30 (Brasília)" in issue["body"]

    r = C.conferir(_ex("failure", 11), gh, AGORA + dt.timedelta(hours=1))
    assert r == {"acao": "atualizou", "issue": 1, "falhas": 2}
    assert len(falso.issues) == 1 and falso.comentarios == []
    assert "#11" in falso.issues[1]["body"]

    assert C.conferir(_ex("failure", 11), gh, AGORA + dt.timedelta(hours=2))["acao"] == "nada"

    r = C.conferir(_ex("timed_out", 12), gh, AGORA + dt.timedelta(hours=25))
    assert r["acao"] == "comentou" and r["falhas"] == 3 and len(falso.comentarios) == 1


def test_sucesso_fecha_e_cancelado_e_ignorado():
    falso, gh = _gh()
    assert C.conferir(_ex("success"), gh, AGORA)["acao"] == "nada"
    C.conferir(_ex("failure", 20), gh, AGORA)
    assert C.conferir(_ex("cancelled", 21), gh, AGORA)["acao"] == "ignorado"
    assert falso.issues[1]["state"] == "open"
    assert C.conferir(_ex("success", 22), gh, AGORA)["acao"] == "fechou"
    assert falso.issues[1]["state"] == "closed" and "Voltou a passar" in falso.comentarios[-1][1]
    assert C.conferir(_ex("failure", 23), gh, AGORA)["acao"] == "abriu"
    assert len(falso.issues) == 2


def test_issues_separadas_por_workflow():
    falso, gh = _gh()
    C.conferir(_ex("failure", 1), gh, AGORA)
    C.conferir(_ex("failure", 2, "Publicar o site", "publicar-site.yml"), gh, AGORA)
    assert len(falso.issues) == 2
    C.conferir(_ex("success", 3, "Publicar o site", "publicar-site.yml"), gh, AGORA)
    assert falso.issues[1]["state"] == "open" and falso.issues[2]["state"] == "closed"


def test_registro_em_arquivo_cria_branch_e_anexa():
    falso, gh = _gh()
    ex = _ex("failure", 30)
    gh.anexar_registro(C.linha_registro(ex, {"acao": "abriu", "issue": 1}, AGORA))
    gh.anexar_registro(C.linha_registro(_ex("success", 31), {"acao": "fechou", "issue": 1}, AGORA))
    linhas = [json.loads(x) for x in falso.arquivo.splitlines()]
    assert [x["acao"] for x in linhas] == ["abriu", "fechou"]
    assert linhas[0]["workflow"] == "Vigilância diária" and linhas[0]["execucao"] == 30


def test_workflow_confere_os_criticos_pelo_nome_exato():
    wf = yaml.safe_load((RAIZ / ".github/workflows/conferir-workflows.yml").read_text())
    conferidos = set(wf[True]["workflow_run"]["workflows"])
    for arquivo in ("processar-estados", "coletar-comprometida", "vigilancia", "calendario", "publicar-site"):
        nome = yaml.safe_load((RAIZ / f".github/workflows/{arquivo}.yml").read_text())["name"]
        assert nome in conferidos, arquivo
