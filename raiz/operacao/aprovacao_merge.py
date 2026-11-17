"""Trava de merge em áreas críticas (política em `docs/politica-de-merge.md`).

Roda no check `aprovacao` (`.github/workflows/aprovacao.yml`, evento `pull_request_target`, sempre com o código
da main, nunca com o do PR). Regras:

    PR sem arquivo crítico   passa sozinho (documentação, testes, telas, correções pontuais de CI fora da lista)
    PR com arquivo crítico   só passa com o rótulo `aprovado-bernardo` posto por um aprovador humano pela página
                             do GitHub, depois do último push. Push novo no PR tira o rótulo e o check volta a falhar.

Enquanto falta a aprovação, o PR recebe o rótulo `aguardando-bernardo` (lista única do que espera o fundador).

Os agentes usam a mesma conta do fundador no GitHub, então o rótulo posto por eles só é recusado quando o GitHub
registra o app que agiu (`performed_via_github_app`). A regra que vale para todos está no CLAUDE.md: agente nunca
põe nem tira `aprovado-bernardo`.

Uso local (sem rede): `python -m raiz.operacao.aprovacao_merge --arquivos motor/x.py docs/y.md`.
Só biblioteca padrão: roda no runner sem instalar nada.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

ROTULO_APROVADO = "aprovado-bernardo"
ROTULO_AGUARDANDO = "aguardando-bernardo"
APROVADORES_PADRAO = ("bernardoemmel",)

# Caminhos críticos (padrões fnmatch sobre o caminho no repositório). Mudar esta lista é, ela mesma, crítico.
CRITICOS: tuple[tuple[str, str], ...] = (
    ("motor/*", "motor de dados"),
    (".github/*", "workflows, ações e configuração do CI"),
    ("raiz/funil/*", "funil (regras científicas)"),
    ("raiz/comprometida/*", "terra já comprometida"),
    ("raiz/ambiental/*", "triagem ambiental"),
    ("raiz/coleta/*", "coleta de dados públicos"),
    ("raiz/operacao/aprovacao_merge.py", "esta trava"),
    ("raiz/catalogo_publico.py", "dados publicados"),
    ("raiz/potencial_publico.py", "dados publicados"),
    ("raiz/lotes_publicos.py", "dados publicados"),
    ("raiz/lote_publicado.py", "dados publicados"),
    ("raiz/metadados.py", "dados publicados"),
    ("raiz/metadados_lote.py", "dados publicados"),
    ("raiz/pacotes_seguros.py", "dados publicados"),
    ("raiz/privacidade.py", "proteção de CPF/CNPJ"),
    ("scripts/publicar_*", "publicação de dados"),
    ("scripts/migrar_*", "migração de dados"),
    ("scripts/aliviar_dados_privados.py", "arquivo privado"),
    ("scripts/atualizar_fila_privada.py", "fila de processamento"),
    ("scripts/reservar_lote.py", "fila de processamento"),
    ("scripts/verificar_release_dados.py", "dados publicados"),
    ("front/scripts/construir-site.sh", "publicação do site"),
    ("front/scripts/baixar-*", "publicação do site"),
    ("front/scripts/configurar-publicacao.mjs", "publicação do site"),
    ("front/scripts/servidor-publicacao.mjs", "publicação do site"),
    ("front/scripts/geo.py", "publicação do site"),
    ("migracoes/*", "banco de dados"),
    ("docs/colunas.md", "contrato de dados"),
    ("docs/politica-de-merge.md", "regra de merge"),
    ("docs/protecao-main.md", "regra de merge"),
    ("CLAUDE.md", "regras dos agentes"),
    ("AGENTS.md", "regras dos agentes"),
)


def motivo_critico(caminho: str) -> str | None:
    """Devolve por que o arquivo é crítico, ou None se for de baixo risco."""
    for padrao, motivo in CRITICOS:
        if fnmatch.fnmatchcase(caminho, padrao):
            return motivo
    return None


def arquivos_criticos(arquivos: list[str]) -> dict[str, str]:
    return {a: m for a in arquivos if (m := motivo_critico(a))}


@dataclass(frozen=True)
class Decisao:
    passa: bool
    criticos: dict[str, str]
    motivo: str


def aprovacao_valida(eventos: list[dict], rotulos_atuais: list[str], aprovadores: set[str]) -> tuple[bool, str]:
    """Confere se o rótulo de aprovação está no PR e se o último que o pôs é um aprovador humano."""
    if ROTULO_APROVADO not in rotulos_atuais:
        return False, f"falta o rótulo `{ROTULO_APROVADO}`"
    postos = [
        e for e in eventos if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == ROTULO_APROVADO
    ]
    if not postos:
        return False, "não achei quem pôs o rótulo"
    ultimo = postos[-1]
    quem = (ultimo.get("actor") or {}).get("login", "")
    app = (ultimo.get("performed_via_github_app") or {}).get("slug")
    if quem not in aprovadores:
        return False, f"o rótulo foi posto por `{quem}`, que não é aprovador"
    if app:
        return False, f"o rótulo foi posto pelo app `{app}` (agente), não pela página do GitHub"
    return True, f"aprovado por `{quem}`"


def decidir(
    arquivos: list[str],
    eventos: list[dict],
    rotulos_atuais: list[str],
    aprovadores: set[str],
    acao: str,
) -> Decisao:
    criticos = arquivos_criticos(arquivos)
    if not criticos:
        return Decisao(True, {}, "nenhum arquivo crítico: merge livre com o CI verde")
    if acao == "synchronize":
        return Decisao(False, criticos, "push novo em área crítica: a aprovação anterior caiu, aprovar de novo")
    ok, motivo = aprovacao_valida(eventos, rotulos_atuais, aprovadores)
    return Decisao(ok, criticos, motivo)


def resumo(decisao: Decisao, repo: str, numero: int | str) -> str:
    linhas = ["## Aprovação de áreas críticas", ""]
    if not decisao.criticos:
        return "\n".join([*linhas, "Passou: " + decisao.motivo + ".", ""])
    linhas.append(("Passou: " if decisao.passa else "**Bloqueado:** ") + decisao.motivo + ".")
    linhas += ["", "Arquivos críticos neste PR:", ""]
    linhas += [f"- `{a}` ({m})" for a, m in sorted(decisao.criticos.items())]
    if not decisao.passa:
        linhas += [
            "",
            f"Para liberar: abra https://github.com/{repo}/pull/{numero}, clique em **Labels** na coluna da direita "
            f"e marque `{ROTULO_APROVADO}`. O check roda de novo sozinho.",
        ]
    return "\n".join(linhas) + "\n"


# --- GitHub (só no Actions) -------------------------------------------------------------------------------------


class GitHub:
    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.token = token

    def _pedir(self, metodo: str, caminho: str, corpo: dict | None = None) -> tuple[object, dict]:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(self.base + caminho, data=dados, method=metodo)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if dados is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as r:
            texto = r.read().decode() or "null"
            return json.loads(texto), dict(r.headers)

    def lista(self, caminho: str) -> list[dict]:
        itens: list[dict] = []
        pagina = 1
        while True:
            sep = "&" if "?" in caminho else "?"
            parte, _ = self._pedir("GET", f"{caminho}{sep}per_page=100&page={pagina}")
            assert isinstance(parte, list)
            itens += parte
            if len(parte) < 100:
                return itens
            pagina += 1

    def por_rotulo(self, numero: int, rotulo: str) -> None:
        self._pedir("POST", f"/issues/{numero}/labels", {"labels": [rotulo]})

    def tirar_rotulo(self, numero: int, rotulo: str) -> None:
        try:
            self._pedir("DELETE", f"/issues/{numero}/labels/{urllib.parse.quote(rotulo)}")
        except urllib.error.HTTPError as erro:
            if erro.code != 404:
                raise


def _tentar(descricao: str, funcao, *args) -> None:
    """Mexer em rótulo é ajuda visual; se o token não deixar (ex.: PR do Dependabot), a decisão não muda."""
    try:
        funcao(*args)
    except urllib.error.HTTPError as erro:
        print(f"aviso: não consegui {descricao} (HTTP {erro.code})", file=sys.stderr)


def rodar_no_actions() -> int:
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        evento = json.load(f)
    repo = os.environ["GITHUB_REPOSITORY"]
    gh = GitHub(repo, os.environ["GITHUB_TOKEN"])
    pr = evento["pull_request"]
    numero = int(pr["number"])
    acao = evento.get("action", "")
    extras = {a.strip() for a in os.environ.get("RAIZ_APROVADORES", "").split(",") if a.strip()}
    aprovadores = set(APROVADORES_PADRAO) | extras

    mudados = gh.lista(f"/pulls/{numero}/files")
    # Arquivo renomeado: o caminho antigo também conta (tirar algo do motor é mexer no motor).
    arquivos = [f["filename"] for f in mudados]
    arquivos += [f["previous_filename"] for f in mudados if f.get("previous_filename")]
    rotulos = [r["name"] for r in gh.lista(f"/issues/{numero}/labels")]
    eventos = gh.lista(f"/issues/{numero}/events")

    decisao = decidir(arquivos, eventos, rotulos, aprovadores, acao)

    if decisao.criticos and acao == "synchronize" and ROTULO_APROVADO in rotulos:
        _tentar("tirar o rótulo de aprovação", gh.tirar_rotulo, numero, ROTULO_APROVADO)
    if decisao.criticos and not decisao.passa:
        _tentar("pôr o rótulo de espera", gh.por_rotulo, numero, ROTULO_AGUARDANDO)
    elif ROTULO_AGUARDANDO in rotulos:
        _tentar("tirar o rótulo de espera", gh.tirar_rotulo, numero, ROTULO_AGUARDANDO)

    texto = resumo(decisao, repo, numero)
    print(texto)
    if caminho := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(texto)
    return 0 if decisao.passa else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--arquivos", nargs="*", help="simula: diz quais arquivos seriam críticos, sem rede")
    args = p.parse_args(argv)
    if args.arquivos is not None:
        criticos = arquivos_criticos(args.arquivos)
        for a in args.arquivos:
            print(f"{'CRÍTICO' if a in criticos else 'livre  '}  {a}  {criticos.get(a, '')}")
        return 0
    return rodar_no_actions()


if __name__ == "__main__":
    raise SystemExit(main())
