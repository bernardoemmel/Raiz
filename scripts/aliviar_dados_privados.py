"""Mantém o Release privado `dados-privados` abaixo do limite de 1000 arquivos do GitHub.

Com 1000 arquivos o GitHub recusa qualquer upload (HTTP 422) e nenhuma publicação nem checkpoint
passa. Este script MOVE (nunca só apaga) para um Release rascunho `historico-AAAA-MM-DD` o que o
processamento não lê mais:

- relatórios de catálogo (`catalogo-relatorio-*`) e cópias de migração (`historico-*`);
- manifestos versionados de checkpoint que nenhum `checkpoint-<unidade>-latest.json` aponta e
  objetos de checkpoint que nenhum manifesto mantido usa, com mais de IDADE_MIN horas.

Cada arquivo é copiado, conferido pelo SHA-256 no destino e só então removido da origem.
O padrão é só listar; com --executar ele move. Nenhum conteúdo é impresso.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

import httpx

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
LIMITE_DESTINO = 950
PREFIXOS_LIVRES = ("catalogo-relatorio-", "historico-")
VERSAO = re.compile(r"checkpoint-(?P<unidade>[A-Z]{2}(?:-\d+)?)-\d+-\d+-[0-9a-f]+\.json")
OBJETO = re.compile(r"checkpoint-objeto-[0-9a-f]+\.tar\.gz")
LATEST = re.compile(r"checkpoint-[A-Z]{2}(?:-\d+)?-latest\.json")


class GitHub:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        self.cli = httpx.Client(timeout=httpx.Timeout(600, connect=30), follow_redirects=True)

    def releases(self) -> list[dict]:
        r = self.cli.get(f"{API}/repos/{self.repo}/releases", headers=self.h, params={"per_page": 100})
        r.raise_for_status()
        return r.json()

    def estados_publicos(self) -> dict:
        r = self.cli.get(f"https://github.com/{self.repo}/releases/download/dados/estados.json")
        r.raise_for_status()
        return r.json().get("estados", {})

    def assets(self, rel_id: int) -> list[dict]:
        todos = []
        for pagina in range(1, 20):
            r = self.cli.get(f"{API}/repos/{self.repo}/releases/{rel_id}/assets", headers=self.h,
                             params={"per_page": 100, "page": pagina})  # fmt: skip
            r.raise_for_status()
            todos += r.json()
            if len(r.json()) < 100:
                return todos
        return todos

    def baixar(self, asset_id: int, destino: Path) -> str:
        sha = hashlib.sha256()
        with self.cli.stream("GET", f"{API}/repos/{self.repo}/releases/assets/{asset_id}",
                             headers={**self.h, "Accept": "application/octet-stream"}) as r:  # fmt: skip
            r.raise_for_status()
            with destino.open("wb") as f:
                for bloco in r.iter_bytes(1 << 20):
                    sha.update(bloco)
                    f.write(bloco)
        return sha.hexdigest()

    def ler(self, asset_id: int) -> bytes:
        r = self.cli.get(f"{API}/repos/{self.repo}/releases/assets/{asset_id}",
                         headers={**self.h, "Accept": "application/octet-stream"})  # fmt: skip
        r.raise_for_status()
        return r.content

    def subir(self, rel_id: int, nome: str, arquivo: Path) -> dict:
        with arquivo.open("rb") as f:
            r = self.cli.post(f"{UPLOADS}/repos/{self.repo}/releases/{rel_id}/assets", params={"name": nome},
                              headers={**self.h, "Content-Type": "application/octet-stream"}, content=f)  # fmt: skip
        r.raise_for_status()
        return r.json()

    def apagar(self, asset_id: int) -> None:
        self.cli.delete(f"{API}/repos/{self.repo}/releases/assets/{asset_id}", headers=self.h).raise_for_status()

    def criar_rascunho(self, tag: str) -> dict:
        r = self.cli.post(f"{API}/repos/{self.repo}/releases", headers=self.h,
                          json={"tag_name": tag, "name": tag, "draft": True,
                                "body": "Arquivos antigos movidos do dados-privados (limite de 1000)."})  # fmt: skip
        r.raise_for_status()
        return r.json()


def _idade_h(asset: dict, agora: dt.datetime) -> float:
    quando = dt.datetime.fromisoformat(asset["updated_at"].replace("Z", "+00:00"))
    return (agora - quando).total_seconds() / 3600


def _uf(nome: str) -> str | None:
    m = re.match(r"(?:checkpoint-|cache_motor_unidade_)([A-Z]{2})(?:[-.]|$)", nome)
    return m.group(1) if m else None


def escolher(gh: GitHub, assets: list[dict], idade_min: float, agora: dt.datetime,
             prontas: frozenset[str] = frozenset()) -> list[dict]:  # fmt: skip
    """Arquivos que o processamento não lê mais, do mais velho para o mais novo. Estado com o funil
    completo (prontas) não roda mais na conclusão dos 27: seu checkpoint e seu cache (opcionais na
    retomada) também saem. Cada escolhido leva "_livre" quando sai sem esperar a meta de excesso."""
    por_nome = {a["name"]: a for a in assets}
    mantidos: set[str] = set()
    for a in assets:
        if LATEST.fullmatch(a["name"]) and _uf(a["name"]) not in prontas:
            mantidos.add(a["name"])
            manifesto = (json.loads(gh.ler(a["id"])) or {}).get("manifesto")
            if manifesto:
                mantidos.add(manifesto)
    objetos_usados: set[str] = set()
    for nome in list(mantidos):
        if VERSAO.fullmatch(nome) and nome in por_nome:
            conteudo = json.loads(gh.ler(por_nome[nome]["id"]))
            objetos_usados |= {p["nome"] for p in conteudo.get("pacotes", []) if p.get("nome")}
    escolhidos = []
    for a in assets:
        nome = a["name"]
        da_pronta = _uf(nome) in prontas and not OBJETO.fullmatch(nome)
        livre = (nome.startswith(PREFIXOS_LIVRES) or da_pronta) and _idade_h(a, agora) >= 1
        velho = _idade_h(a, agora) >= idade_min
        solto = (VERSAO.fullmatch(nome) and nome not in mantidos) or (OBJETO.fullmatch(nome)
                                                                        and nome not in objetos_usados)  # fmt: skip
        if livre or (solto and velho):
            escolhidos.append({**a, "_livre": livre})
    return sorted(escolhidos, key=lambda a: a["updated_at"])


def destino(gh: GitHub, releases: list[dict], agora: dt.datetime, precisa: int) -> tuple[dict, int]:
    base = f"historico-{agora.date().isoformat()}"
    for n in range(1, 50):
        tag = base if n == 1 else f"{base}-{n}"
        rel = next((r for r in releases if r.get("tag_name") == tag), None)
        if rel is None:
            rel = gh.criar_rascunho(tag)
            releases.append(rel)
            return rel, LIMITE_DESTINO
        livres = LIMITE_DESTINO - len(gh.assets(rel["id"]))
        if livres > 0:
            return rel, livres
    raise RuntimeError("sem Release de histórico com espaço")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "bernardoemmel/Raiz"))
    p.add_argument("--tag", default="dados-privados")
    p.add_argument("--manter-abaixo", type=int, default=800, help="move até a origem ficar com isto")
    p.add_argument("--idade-min", type=float, default=1.5, help="horas mínimas para checkpoint solto")
    p.add_argument("--so-acima", type=int, default=0, help="não faz nada se a origem tiver menos que isto")
    p.add_argument("--executar", action="store_true")
    a = p.parse_args()
    gh = GitHub(a.repo, os.environ["GH_TOKEN"])
    agora = dt.datetime.now(dt.UTC)
    releases = gh.releases()
    origem = next(r for r in releases if r.get("tag_name") == a.tag)
    assets = gh.assets(origem["id"])
    if len(assets) < a.so_acima:
        print(f"origem: {len(assets)} arquivos; abaixo de {a.so_acima}, nada a fazer", flush=True)
        return
    prontas = frozenset(
        uf
        for uf, e in gh.estados_publicos().items()
        if e.get("municipios", 0) + (e.get("sem_imoveis") or 0) >= (e.get("total_ibge") or 10**9)
    )
    print(f"estados com funil completo: {', '.join(sorted(prontas)) or 'nenhum'}", flush=True)
    candidatos = escolher(gh, assets, a.idade_min, agora, prontas)
    # Sempre leva relatórios e cópias de migração; checkpoint solto só até ficar abaixo da meta.
    excesso = max(0, len(assets) - a.manter_abaixo)
    livres = [c for c in candidatos if c["_livre"]]
    soltos = [c for c in candidatos if not c["_livre"]]
    mover = livres + soltos[: max(0, excesso - len(livres))]
    print(f"origem: {len(assets)} arquivos; candidatos: {len(candidatos)}; movendo: {len(mover)}", flush=True)
    if not a.executar or not mover:
        return
    movidos = 0
    with tempfile.TemporaryDirectory(prefix="raiz-alivio-") as tmp:
        rel, vagas = destino(gh, releases, agora, len(mover))
        existentes = {x["name"]: x for x in gh.assets(rel["id"])}
        for asset in mover:
            if vagas <= 0:
                rel, vagas = destino(gh, releases, agora, len(mover) - movidos)
                existentes = {x["name"]: x for x in gh.assets(rel["id"])}
            arquivo = Path(tmp) / "arquivo"
            try:
                digest = gh.baixar(asset["id"], arquivo)
                if asset.get("digest") and asset["digest"] != f"sha256:{digest}":
                    print(f"pulei {asset['name']}: download não confere", flush=True)
                    continue
                feito = existentes.get(asset["name"])
                if not feito or feito.get("digest") != f"sha256:{digest}":
                    if feito:
                        gh.apagar(feito["id"])
                    feito = gh.subir(rel["id"], asset["name"], arquivo)
                    vagas -= 1
                confere = feito.get("digest", f"sha256:{digest}") == f"sha256:{digest}"
                if not confere or int(feito["size"]) != arquivo.stat().st_size:
                    print(f"pulei {asset['name']}: cópia não confere; origem mantida", flush=True)
                    continue
                gh.apagar(asset["id"])
                movidos += 1
            except httpx.HTTPStatusError as ex:
                # Outro planejador pode ter movido o mesmo arquivo ao mesmo tempo: segue com os demais.
                print(f"pulei {asset['name']}: HTTP {ex.response.status_code}", flush=True)
            finally:
                arquivo.unlink(missing_ok=True)
    print(f"movidos para o histórico: {movidos}; origem agora ~{len(assets) - movidos}", flush=True)


if __name__ == "__main__":
    main()
