"""Conferidor de etapas: nenhuma falha de workflow crítico passa despercebida.

Roda no GitHub Actions (`.github/workflows/conferir-workflows.yml`) a cada execução concluída dos workflows
críticos na main. Para cada workflow existe no máximo UMA issue aberta com o rótulo `falha-workflow`:

    falhou     abre a issue (ou atualiza a que já está aberta) com o link da execução e os jobs/passos que caíram;
               comenta no máximo uma vez a cada 24 h para não virar spam; o corpo sempre mostra a última falha
    passou     comenta "voltou a passar" e fecha a issue
    cancelado  nada muda (cancelamento por concorrência não é falha)

Cada evento também entra no arquivo `registro/falhas-workflows.jsonl` da branch `registro-workflows`
(branch só de registro, fora da main protegida). Abrir issue já manda e-mail ao dono do repositório pelas
notificações do GitHub. Nada pessoal: só nomes de workflow, job e passo, números de execução e links.

Uso local (simulação, sem rede): `python -m raiz.operacao.conferidor_workflows --evento evento.json --simular`.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
from dataclasses import dataclass

import httpx

ROTULO = "falha-workflow"
BRANCH_REGISTRO = "registro-workflows"
ARQUIVO_REGISTRO = "registro/falhas-workflows.jsonl"
LINHAS_MAX = 5000
INTERVALO_COMENTARIO = dt.timedelta(hours=24)
FALHAS = {"failure", "timed_out", "startup_failure"}
SUCESSO = "success"
_ESTADO = re.compile(r"<!-- conferidor-estado (\{.*?\}) -->")


@dataclass(frozen=True)
class Execucao:
    workflow: str
    caminho: str
    conclusao: str
    url: str
    id: int
    numero: int
    tentativa: int
    branch: str
    evento: str
    sha: str
    quando: str

    @classmethod
    def do_evento(cls, evento: dict) -> Execucao:
        r = evento["workflow_run"]
        return cls(
            workflow=r.get("name") or r.get("path", "?"),
            caminho=r.get("path", ""),
            conclusao=r.get("conclusion") or "",
            url=r.get("html_url", ""),
            id=int(r["id"]),
            numero=int(r.get("run_number") or 0),
            tentativa=int(r.get("run_attempt") or 1),
            branch=r.get("head_branch") or "",
            evento=r.get("event") or "",
            sha=(r.get("head_sha") or "")[:7],
            quando=r.get("updated_at") or r.get("created_at") or "",
        )

    @property
    def marca(self) -> str:
        return f"<!-- conferidor:{self.caminho or self.workflow} -->"

    @property
    def titulo(self) -> str:
        return f"Falha no workflow: {self.workflow}"


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _hora_brasilia(iso: str) -> str:
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    return (t - dt.timedelta(hours=3)).strftime("%d/%m/%Y %H:%M") + " (Brasília)"


def ler_estado(corpo: str) -> dict:
    m = _ESTADO.search(corpo or "")
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def corpo_issue(ex: Execucao, estado: dict, quebras: list[str]) -> str:
    linhas = [
        ex.marca,
        f"<!-- conferidor-estado {json.dumps(estado, separators=(',', ':'), ensure_ascii=False)} -->",
        f"O workflow **{ex.workflow}** (`{ex.caminho}`) falhou na main.",
        "",
        f"- Última falha: [execução #{ex.numero}]({ex.url}) (tentativa {ex.tentativa}), {_hora_brasilia(ex.quando)}",
        f"- Resultado: `{ex.conclusao}` · disparo: `{ex.evento}` · commit `{ex.sha}`",
        f"- Falhas seguidas desde que abriu: **{estado.get('falhas', 1)}**",
    ]
    if quebras:
        linhas += ["", "Onde caiu:", *[f"- {q}" for q in quebras]]
    linhas += [
        "",
        "Esta issue é do conferidor de etapas (`docs/conferidor-workflows.md`). Ela fecha sozinha quando o "
        "workflow voltar a passar. Novas falhas atualizam este texto e comentam no máximo uma vez por dia.",
    ]
    return "\n".join(linhas)


class GitHub:
    def __init__(self, repo: str, token: str, cliente: httpx.Client | None = None):
        self.repo = repo
        self.c = cliente or httpx.Client(timeout=30)
        self.h = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _u(self, caminho: str) -> str:
        return f"https://api.github.com/repos/{self.repo}{caminho}"

    def req(self, metodo: str, caminho: str, **kw) -> httpx.Response:
        return self.c.request(metodo, self._u(caminho), headers=self.h, **kw)

    def ok(self, metodo: str, caminho: str, **kw) -> dict | list:
        r = self.req(metodo, caminho, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    # issues
    def garantir_rotulo(self) -> None:
        r = self.req(
            "POST",
            "/labels",
            json={"name": ROTULO, "color": "C2521A", "description": "Workflow crítico falhando (conferidor de etapas)"},
        )
        if r.status_code not in (201, 422):
            r.raise_for_status()

    def issue_aberta(self, marca: str) -> dict | None:
        for pagina in range(1, 6):
            itens = self.ok(
                "GET", "/issues", params={"labels": ROTULO, "state": "open", "per_page": 100, "page": pagina}
            )
            for i in itens:
                if marca in (i.get("body") or "") and "pull_request" not in i:
                    return i
            if len(itens) < 100:
                return None
        return None

    def quebras(self, run_id: int) -> list[str]:
        try:
            jobs = self.ok("GET", f"/actions/runs/{run_id}/jobs", params={"filter": "latest", "per_page": 100})
        except httpx.HTTPError:
            return []
        saida = []
        for j in jobs.get("jobs", []):
            if j.get("conclusion") not in FALHAS:
                continue
            passos = [s.get("name", "?") for s in j.get("steps", []) if s.get("conclusion") in FALHAS]
            alvo = f"[{j.get('name', '?')}]({j.get('html_url', '')})"
            saida.append(alvo + (f": passo **{', '.join(passos)}**" if passos else ""))
        return saida[:20]

    # registro em arquivo, numa branch só de registro
    def _branch_existe(self) -> bool:
        r = self.req("GET", f"/git/ref/heads/{BRANCH_REGISTRO}")
        if r.status_code == 404:
            return False
        r.raise_for_status()
        return True

    def _criar_branch(self, conteudo: str) -> None:
        arvore = self.ok(
            "POST",
            "/git/trees",
            json={"tree": [{"path": ARQUIVO_REGISTRO, "mode": "100644", "type": "blob", "content": conteudo}]},
        )
        commit = self.ok(
            "POST",
            "/git/commits",
            json={"message": "Registro do conferidor de etapas", "tree": arvore["sha"], "parents": []},
        )
        self.ok("POST", "/git/refs", json={"ref": f"refs/heads/{BRANCH_REGISTRO}", "sha": commit["sha"]})

    def anexar_registro(self, linha: str, tentativas: int = 4) -> None:
        if not self._branch_existe():
            self._criar_branch(linha + "\n")
            return
        for _ in range(tentativas):
            r = self.req("GET", f"/contents/{ARQUIVO_REGISTRO}", params={"ref": BRANCH_REGISTRO})
            sha, atual = None, ""
            if r.status_code == 200:
                d = r.json()
                sha = d["sha"]
                atual = base64.b64decode(d.get("content", "")).decode()
            elif r.status_code != 404:
                r.raise_for_status()
            linhas = [x for x in atual.splitlines() if x.strip()] + [linha]
            novo = "\n".join(linhas[-LINHAS_MAX:]) + "\n"
            corpo = {
                "message": "Registro do conferidor de etapas",
                "branch": BRANCH_REGISTRO,
                "content": base64.b64encode(novo.encode()).decode(),
            }
            if sha:
                corpo["sha"] = sha
            p = self.req("PUT", f"/contents/{ARQUIVO_REGISTRO}", json=corpo)
            if p.status_code in (200, 201):
                return
            if p.status_code not in (409, 422):
                p.raise_for_status()
        raise RuntimeError("registro em arquivo não gravou após várias tentativas (concorrência)")


def conferir(ex: Execucao, gh: GitHub, agora: dt.datetime | None = None) -> dict:
    """Aplica a regra de uma issue por workflow. Devolve o que foi feito (vai para o registro e o resumo)."""
    agora = agora or _agora()
    if ex.conclusao in FALHAS:
        situacao = "falhou"
    elif ex.conclusao == SUCESSO:
        situacao = "passou"
    else:
        return {"acao": "ignorado", "motivo": f"conclusão {ex.conclusao or 'vazia'}"}

    aberta = gh.issue_aberta(ex.marca)
    if situacao == "passou":
        if not aberta:
            return {"acao": "nada", "motivo": "passou e não havia issue aberta"}
        n = aberta["number"]
        gh.ok(
            "POST",
            f"/issues/{n}/comments",
            json={
                "body": (
                    f"Voltou a passar na [execução #{ex.numero}]({ex.url}), {_hora_brasilia(ex.quando)}. "
                    f"Total de falhas seguidas: {ler_estado(aberta.get('body', '')).get('falhas', 1)}. Fechando."
                )
            },
        )
        gh.ok("PATCH", f"/issues/{n}", json={"state": "closed", "state_reason": "completed"})
        return {"acao": "fechou", "issue": n}

    quebras = gh.quebras(ex.id)
    if not aberta:
        gh.garantir_rotulo()
        estado = {"falhas": 1, "comentado": agora.isoformat(timespec="seconds"), "ultima": ex.id}
        nova = gh.ok(
            "POST", "/issues", json={"title": ex.titulo, "labels": [ROTULO], "body": corpo_issue(ex, estado, quebras)}
        )
        return {"acao": "abriu", "issue": nova.get("number")}

    n = aberta["number"]
    estado = ler_estado(aberta.get("body", ""))
    if estado.get("ultima") == ex.id and estado.get("tentativa") == ex.tentativa:
        return {"acao": "nada", "motivo": "execução já registrada", "issue": n}
    estado["falhas"] = int(estado.get("falhas", 1)) + 1
    estado["ultima"], estado["tentativa"] = ex.id, ex.tentativa
    comentar = True
    if estado.get("comentado"):
        try:
            comentar = agora - dt.datetime.fromisoformat(estado["comentado"]) >= INTERVALO_COMENTARIO
        except ValueError:
            comentar = True
    if comentar:
        estado["comentado"] = agora.isoformat(timespec="seconds")
    gh.ok("PATCH", f"/issues/{n}", json={"body": corpo_issue(ex, estado, quebras)})
    if comentar:
        gh.ok(
            "POST",
            f"/issues/{n}/comments",
            json={
                "body": (
                    f"Falhou de novo: [execução #{ex.numero}]({ex.url}), {_hora_brasilia(ex.quando)}. "
                    f"São {estado['falhas']} falhas seguidas. Próximo comentário em no mínimo 24 h; o texto da issue "
                    "sempre mostra a última."
                )
            },
        )
    return {"acao": "comentou" if comentar else "atualizou", "issue": n, "falhas": estado["falhas"]}


def linha_registro(ex: Execucao, resultado: dict, agora: dt.datetime | None = None) -> str:
    return json.dumps(
        {
            "registrado_em": (agora or _agora()).isoformat(timespec="seconds"),
            "workflow": ex.workflow,
            "caminho": ex.caminho,
            "conclusao": ex.conclusao,
            "execucao": ex.numero,
            "tentativa": ex.tentativa,
            "url": ex.url,
            "commit": ex.sha,
            **resultado,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--evento", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    p.add_argument("--simular", action="store_true", help="só mostra o que faria, sem chamar o GitHub")
    a = p.parse_args(argv)
    with open(a.evento, encoding="utf-8") as f:
        ex = Execucao.do_evento(json.load(f))
    print(f"{ex.workflow}: {ex.conclusao} (#{ex.numero}, tentativa {ex.tentativa})")
    if a.simular:
        print("simulação: issue", "abriria/atualizaria" if ex.conclusao in FALHAS else "fecharia se aberta")
        return 0
    gh = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
    resultado = conferir(ex, gh)
    print(json.dumps(resultado, ensure_ascii=False))
    if resultado["acao"] != "ignorado":
        gh.anexar_registro(linha_registro(ex, resultado))
    resumo = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumo:
        with open(resumo, "a", encoding="utf-8") as f:
            f.write(
                f"### Conferidor: {ex.workflow}\n\nResultado `{ex.conclusao}` → **{resultado['acao']}**"
                + (f" (issue #{resultado['issue']})" if resultado.get("issue") else "")
                + "\n"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
