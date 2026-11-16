"""Preserva artifacts históricos de dados em Release privado antes de removê-los do Actions.

Somente entradas-congeladas, calculado-* e github-pages são selecionados. Evidências
CI permanecem intactas. Nenhum ZIP é extraído e nenhum valor de dados é registrado.
Copiar exige --executar; remover exige --executar-remocao e reconfere o lote inteiro.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts import migrar_dados_privados as releases

VERSAO = 1


def selecionado(nome: str) -> bool:
    return nome in {"entradas-congeladas", "github-pages"} or bool(re.fullmatch(r"calculado-[A-Za-z0-9_-]+", nome))


def fingerprint(artifact: dict) -> dict:
    return {
        k: artifact.get(k)
        for k in ("id", "name", "size_in_bytes", "created_at", "updated_at", "expired", "digest", "workflow_run")
    }


def digest_oficial(artifact: dict) -> str | None:
    valor = artifact.get("digest")
    if valor is None:
        return None
    if not isinstance(valor, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", valor):
        raise ValueError("Artifact sem digest SHA256 oficial válido.")
    return valor.removeprefix("sha256:")


class GitHubActions(releases.GitHub):
    def listar(self, repo: str, recurso: str, campo: str) -> list[dict]:
        texto = self.comando(
            [
                "api",
                f"repos/{releases.repositorio(repo)}/actions/{recurso}?per_page=100",
                "--paginate",
                "--jq",
                f".{campo}",
            ]
        ).decode()
        itens = []
        decoder = json.JSONDecoder()
        while texto.strip():
            pagina, fim = decoder.raw_decode(texto.lstrip())
            if not isinstance(pagina, list):
                raise ValueError("Resposta paginada do Actions não é uma lista.")
            itens.extend(pagina)
            texto = texto.lstrip()[fim:]
        return itens

    def baixar_artifact(self, repo: str, artifact_id: int, arquivo: Path) -> None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = arquivo.with_suffix(".download")
        try:
            with temporario.open("wb") as destino:
                self.comando(
                    ["api", f"repos/{releases.repositorio(repo)}/actions/artifacts/{int(artifact_id)}/zip"],
                    saida=destino,
                )
            temporario.replace(arquivo)
        finally:
            temporario.unlink(missing_ok=True)

    def apagar_artifact(self, repo: str, artifact_id: int) -> None:
        self.comando(
            ["api", "--method", "DELETE", f"repos/{releases.repositorio(repo)}/actions/artifacts/{int(artifact_id)}"]
        )


def listar(gh: GitHubActions, repo: str, diretorio: Path) -> dict:
    todos = gh.listar(repo, "artifacts", "artifacts")
    caches = gh.listar(repo, "caches", "actions_caches")
    rel = {
        "versao": VERSAO,
        "gerado_em": releases.agora(),
        "origem": repo,
        "artifacts": [{**fingerprint(a), "selecionado": selecionado(a["name"])} for a in todos],
    }
    releases.gravar_json(diretorio / "artifacts-listados.json", rel)
    releases.gravar_json(
        diretorio / "caches-listados.json",
        [
            {
                **{k: c.get(k) for k in ("id", "key", "ref", "size_in_bytes", "created_at", "last_accessed_at")},
                "revisar_dados": c["key"].startswith(("motor-", "lote-", "geo-")),
            }
            for c in caches
        ],
    )
    return rel


def conferir_zip(arquivo: Path) -> int:
    # Não usar extract/extractall: o snapshot é preservado opaco. Nomes inseguros
    # ou links recusam a operação, mesmo que este processo nunca os extraia.
    with zipfile.ZipFile(arquivo) as pacote:
        for membro in pacote.infolist():
            releases.caminho_membro(membro.filename)
            modo = membro.external_attr >> 16
            if stat.S_ISLNK(modo):
                raise ValueError("Artifact contém link simbólico; nenhum arquivo foi extraído.")
        if pacote.testzip() is not None:
            raise ValueError("Artifact ZIP com CRC inválido.")
        return len(pacote.infolist())


def inventariar(gh: GitHubActions, repo: str, diretorio: Path, *, paralelos: int = 3) -> dict:
    lista = listar(gh, repo, diretorio)
    escolhidos = [a for a in lista["artifacts"] if a["selecionado"]]
    if any(a["expired"] for a in escolhidos):
        raise ValueError("Há artifact selecionado expirado; não é possível garantir cópia integral.")

    def uma(artifact):
        nome = releases.nome_seguro(f"actions-{int(artifact['id'])}-{artifact['name']}.zip")
        local = diretorio / "artifacts" / nome
        oficial = digest_oficial(artifact)
        # Sem digest oficial, um ZIP local não prova a origem: rebaixar sempre.
        # Com digest, só reutilizar o snapshot se ele for exatamente o original.
        if oficial is None or not local.is_file() or releases.sha256(local) != oficial:
            gh.baixar_artifact(repo, artifact["id"], local)
        digest = releases.sha256(local)
        if oficial is not None and digest != oficial:
            raise ValueError("ZIP baixado diverge do SHA256 oficial do artifact; migração recusada.")
        membros = conferir_zip(local)
        # O tamanho declarado pelo Actions é o armazenamento do artifact; não é
        # uma garantia do tamanho do ZIP de download. O backup preserva esse ZIP.
        return {
            "artifact": fingerprint(artifact),
            "arquivo_local": str(local),
            "nome_backup": nome,
            "sha256": digest,
            "membros_zip": membros,
            "origem": {
                "id": artifact["id"],
                "name": artifact["name"],
                "size": local.stat().st_size,
                "digest": "sha256:" + digest,
            },
        }

    with ThreadPoolExecutor(max_workers=max(1, min(paralelos, 6))) as executor:
        assets = list(executor.map(uma, escolhidos))
    rel = {
        "versao": VERSAO,
        "tipo": "actions_artifacts",
        "gerado_em": releases.agora(),
        "origem": repo,
        "assets": assets,
        "bytes": sum(a["origem"]["size"] for a in assets),
    }
    releases.gravar_json(diretorio / "inventario-artifacts.json", rel)
    return rel


def ler_inventario(arquivo: Path) -> dict:
    rel = releases.ler_inventario(arquivo)
    if rel.get("tipo") != "actions_artifacts":
        raise ValueError("Não é um inventário de artifacts do Actions.")
    for item in rel["assets"]:
        a = item["artifact"]
        oficial = digest_oficial(a)
        if oficial is not None and item["sha256"] != oficial:
            raise ValueError("Inventário diverge do SHA256 oficial do artifact.")
        if (
            not selecionado(a["name"])
            or a["expired"]
            or a["id"] != item["origem"]["id"]
            or item["nome_backup"] != f"actions-{a['id']}-{a['name']}.zip"
        ):
            raise ValueError("Inventário contém artifact fora da seleção autorizada.")
    return rel


def remover(gh: GitHubActions, rel: dict, repo: str, tag: str, diretorio: Path, *, executar: bool = False) -> dict:
    # Rebaixa e verifica TODOS os backups e prova 404 anônimo antes do primeiro DELETE.
    prova = releases.verificar(gh, rel, repo, tag, diretorio)
    vivos = {a["id"]: a for a in gh.listar(rel["origem"], "artifacts", "artifacts") if selecionado(a["name"])}
    ids = {i["artifact"]["id"] for i in rel["assets"]}
    if set(vivos) - ids:
        raise ValueError("Surgiram artifacts selecionados novos; atualizar inventário antes de remover.")
    plano = []
    for item in rel["assets"]:
        anterior = item["artifact"]
        if not selecionado(anterior["name"]):
            raise ValueError("Artifact fora da seleção autorizada; remoção recusada.")
        atual = vivos.get(anterior["id"])
        if atual is not None and fingerprint(atual) != anterior:
            raise ValueError("Artifact mudou desde o inventário; remoção recusada.")
        plano.append(
            {
                "artifact_id": anterior["id"],
                "nome": anterior["name"],
                "acao": "remover_original" if atual else "original_ja_ausente",
                "sha256": item["sha256"],
            }
        )
    resposta = {
        "executado": False,
        "execucao_solicitada": executar,
        "origem": rel["origem"],
        "destino": repo,
        "tag": tag,
        "backup_verificado_em": prova["verificado_em"],
        "acoes": plano,
    }
    releases.gravar_json(diretorio / "plano-remocao-artifacts.json", resposta)
    if executar:
        for acao in plano:
            if acao["acao"] != "remover_original":
                continue
            releases.destino_privado(gh, repo, tag, rel["origem"])
            atual = gh.json(f"repos/{rel['origem']}/actions/artifacts/{acao['artifact_id']}")
            esperado = next(i["artifact"] for i in rel["assets"] if i["artifact"]["id"] == acao["artifact_id"])
            if fingerprint(atual) != esperado:
                raise ValueError("Artifact mudou durante a remoção; execução interrompida.")
            gh.apagar_artifact(rel["origem"], acao["artifact_id"])
            acao["removido"] = True
            releases.gravar_json(diretorio / "remocao-artifacts-progresso.json", resposta)
        resposta["executado"] = True
        releases.gravar_json(diretorio / "remocao-artifacts-progresso.json", resposta)
    return resposta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fase", choices=("listar", "inventariar", "copiar", "verificar", "remover"))
    parser.add_argument("--origem", default="bernardoemmel/Raiz")
    parser.add_argument("--diretorio", type=Path, default=Path("/tmp/raiz-artifacts-privados"))
    parser.add_argument("--inventario", type=Path)
    parser.add_argument("--destino")
    parser.add_argument("--tag", default="dados-privados")
    parser.add_argument("--paralelos", type=int, default=3)
    parser.add_argument("--executar", action="store_true", help="Executa somente a cópia para o Release privado.")
    parser.add_argument(
        "--executar-remocao", action="store_true", help="Executa remoção após conferir todos os backups."
    )
    args = parser.parse_args()
    if args.executar and args.fase != "copiar":
        parser.error("--executar só se aplica à fase copiar.")
    if args.executar_remocao and args.fase != "remover":
        parser.error("--executar-remocao só se aplica à fase remover.")
    gh = GitHubActions()
    releases.repositorio(args.origem)
    args.diretorio.mkdir(parents=True, exist_ok=True)
    args.diretorio.chmod(0o700)
    if args.fase == "listar":
        resultado = listar(gh, args.origem, args.diretorio)
        print(
            json.dumps(
                {
                    "artifacts": len(resultado["artifacts"]),
                    "selecionados": sum(a["selecionado"] for a in resultado["artifacts"]),
                }
            )
        )
        return
    if args.fase == "inventariar":
        resultado = inventariar(gh, args.origem, args.diretorio, paralelos=args.paralelos)
        print(json.dumps({"artifacts": len(resultado["assets"]), "bytes": resultado["bytes"]}))
        return
    if not args.destino:
        parser.error("--destino é obrigatório para copiar, verificar ou remover.")
    rel = ler_inventario(args.inventario or args.diretorio / "inventario-artifacts.json")
    if args.fase == "copiar":
        resultado = releases.copiar(gh, rel, args.destino, args.tag, args.diretorio, executar=args.executar)
        releases.gravar_json(args.diretorio / "plano-copia-artifacts.json", resultado)
    elif args.fase == "verificar":
        resultado = releases.verificar(gh, rel, args.destino, args.tag, args.diretorio)
    else:
        resultado = remover(gh, rel, args.destino, args.tag, args.diretorio, executar=args.executar_remocao)
    print(
        json.dumps({"fase": args.fase, "executado": resultado.get("executado", False), "artifacts": len(rel["assets"])})
    )


if __name__ == "__main__":
    main()
