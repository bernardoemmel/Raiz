"""Inventário e migração verificável dos Releases públicos para armazenamento privado.

O padrão é somente leitura. Copiar e remover são fases separadas e só executam
mutações com --executar. A remoção exige rebaixar e conferir cada backup privado,
conferir a identidade do asset original e validar novamente que o destino é privado.
Nenhum pacote é extraído no filesystem e nenhum valor de linha é registrado.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from raiz.executor.publicacao_aberta import COLUNAS_BASICAS, COLUNAS_GEO

VERSAO = 1
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_COLUNA = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,100}")
_PAGAS = frozenset(
    "certidoes certidaoIA regularizacao terra desenvolvedor ficha mapbiomas extras extras_direto direto "
    "filtros flag rebanho matricula titulo camadas alertas perdas serie_uso".split()
)
# A origem histórica contém nomes anteriores ao contrato aberto atual. Tudo que
# não passar na allowlist continua privado, inclusive arquivos desconhecidos.
_BASICAS = frozenset(COLUNAS_BASICAS)
_GEO_BASICAS = frozenset(COLUNAS_GEO)
_LIMITE_MEMBRO = 8 * 1024**3


def agora() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def repositorio(nome: str) -> str:
    if not _REPO.fullmatch(nome):
        raise ValueError("Repositório deve ter o formato organização/nome.")
    return nome


def nome_seguro(nome: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", nome) or len(nome.encode()) > 240:
        raise ValueError("Nome de asset inválido.")
    if any(ord(c) < 32 for c in nome):
        raise ValueError("Nome de asset contém caractere de controle.")
    return nome


def caminho_membro(nome: str) -> str:
    partes = PurePosixPath(nome).parts
    if not partes or "\\" in nome or nome.startswith("/") or ".." in partes or any(ord(c) < 32 for c in nome):
        raise ValueError("Pacote contém caminho inseguro; nenhum membro foi extraído.")
    if ":" in partes[0]:
        raise ValueError("Pacote contém caminho absoluto de outra plataforma.")
    return str(PurePosixPath(nome))


def sha256(arquivo: Path) -> str:
    h = hashlib.sha256()
    with arquivo.open("rb") as origem:
        for bloco in iter(lambda: origem.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def gravar_json(arquivo: Path, dado: dict | list) -> None:
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(arquivo.suffix + ".tmp")
    temporario.write_text(json.dumps(dado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(arquivo)


class GitHub:
    """CLI autenticado: nunca registra tokens ou resposta de dados em stdout."""

    def comando(self, argumentos: list[str], *, saida=None) -> bytes:
        processo = subprocess.run(["gh", *argumentos], stdout=saida or subprocess.PIPE, stderr=subprocess.PIPE)
        if processo.returncode:
            # Não ecoar stderr de rede (URLs assinadas e credenciais podem aparecer).
            raise RuntimeError(f"GitHub não concluiu a operação {argumentos[0]} (código {processo.returncode}).")
        return processo.stdout or b""

    def json(self, recurso: str, *, paginar: bool = False):
        args = ["api", recurso]
        if paginar:
            args += ["--paginate"]
        saida = self.comando(args).decode()
        if not paginar:
            return json.loads(saida)
        # gh antigo não oferece --slurp: cada página é outro documento JSON.
        itens = []
        decoder = json.JSONDecoder()
        while saida.strip():
            pagina, fim = decoder.raw_decode(saida.lstrip())
            if not isinstance(pagina, list):
                raise ValueError("Resposta paginada não é uma lista de assets ou Releases.")
            itens.extend(pagina)
            saida = saida.lstrip()[fim:]
        return itens

    def baixar(self, repo: str, asset_id: int, arquivo: Path) -> None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario = arquivo.with_suffix(arquivo.suffix + ".download")
        try:
            with temporario.open("wb") as destino:
                self.comando(
                    [
                        "api",
                        f"repos/{repositorio(repo)}/releases/assets/{int(asset_id)}",
                        "-H",
                        "Accept: application/octet-stream",
                    ],
                    saida=destino,
                )
            temporario.replace(arquivo)
        finally:
            temporario.unlink(missing_ok=True)

    def subir(self, repo: str, tag: str, arquivo: Path, nome: str) -> None:
        nome_seguro(nome)
        # Sem --clobber: um backup já publicado nunca é substituído silenciosamente.
        # '#rótulo' no gh não renomeia o asset: usar o nome certo no filesystem.
        with tempfile.TemporaryDirectory(prefix="raiz-backup-") as pasta:
            pronto = Path(pasta) / nome
            try:
                os.link(arquivo, pronto)
            except OSError:
                shutil.copyfile(arquivo, pronto)
            self.comando(["release", "upload", tag, str(pronto), "--repo", repositorio(repo)])

    def apagar(self, repo: str, asset_id: int) -> None:
        self.comando(["api", "--method", "DELETE", f"repos/{repositorio(repo)}/releases/assets/{int(asset_id)}"])

    def conferir_anonimo(self, repo: str, asset: dict) -> None:
        url = asset.get("browser_download_url", "")
        alvo = urlparse(url)
        if (
            alvo.scheme != "https"
            or alvo.netloc != "github.com"
            or not alvo.path.lower().startswith(f"/{repo.lower()}/releases/download/")
        ):
            raise ValueError("Backup sem endereço de download GitHub verificável.")
        requisicao = Request(url, headers={"User-Agent": "raiz-migracao", "Cache-Control": "no-cache"})
        try:
            with urlopen(requisicao, timeout=60):
                raise ValueError("O backup respondeu ao acesso sem autenticação; remoção recusada.")
        except HTTPError as exc:
            if exc.code != 404:
                raise ValueError("Não foi possível comprovar HTTP 404 no download sem autenticação.") from None


def coluna_segura(nome) -> str:
    texto = str(nome)
    return texto if _COLUNA.fullmatch(texto) else "<coluna fora do formato>"


def classe_membro(nome: str, colunas: list[str]) -> tuple[str, list[str]]:
    base = PurePosixPath(nome).name
    prefixos = sorted(p for p in _PAGAS if base.startswith(p + "_") or base.startswith(p + "."))
    if prefixos:
        return "camada_paga", [max(prefixos, key=len)]
    if re.fullmatch(r"imoveis_basicos_\d{7}\.csv", base):
        return ("mapa_basico" if set(colunas) == _BASICAS else "camada_paga"), ["mapa_basico"]
    if re.fullmatch(r"geo_\d{7}\.parquet", base):
        return ("mapa_basico" if set(colunas) <= _GEO_BASICAS and set(colunas) == _GEO_BASICAS else "camada_paga"), [
            "geometria"
        ]
    if re.fullmatch(r"imoveis_\d{7}\.csv", base):
        return "snapshot_privado_com_projecao_basica", ["motor_completo"]
    if re.fullmatch(r"resumo_[A-Z]{2}\.csv", base):
        # O inventário não certifica um resumo antigo: o publicador aplica
        # allowlist de colunas e supressão, mesmo quando o nome é reconhecido.
        return "agregado_a_sanitizar", ["resumo"]
    if re.fullmatch(r"sem_imoveis_[A-Z]{2}\.csv", base):
        return "agregado_a_sanitizar", ["municipios_sem_imoveis"]
    return "snapshot_privado", ["controle_ou_formato_sem_allowlist"]


def inspecionar_conteudo(origem, nome: str, tamanho: int) -> dict:
    """Lê somente cabeçalho/esquema para o relatório; hash cobre todos os bytes."""
    h = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024**2) as copia:
        lidos = 0
        while bloco := origem.read(1024 * 1024):
            lidos += len(bloco)
            if lidos > _LIMITE_MEMBRO:
                raise ValueError("Membro excede o limite de inspeção; revisão manual necessária.")
            h.update(bloco)
            copia.write(bloco)
        if lidos != tamanho:
            raise ValueError("Tamanho do membro divergiu durante a leitura.")
        copia.seek(0)
        colunas: list[str] = []
        if nome.endswith(".csv"):
            primeira = copia.readline(1024 * 1024).decode("utf-8-sig", errors="replace")
            delimitador = ";" if primeira.count(";") > primeira.count(",") else ","
            colunas = [coluna_segura(c) for c in next(csv.reader([primeira], delimiter=delimitador), [])]
        elif nome.endswith(".parquet"):
            import pyarrow.parquet as pq

            colunas = [coluna_segura(c) for c in pq.read_schema(copia).names]
        classe, camadas = classe_membro(nome, colunas)
    return {
        "caminho": nome,
        "bytes": lidos,
        "sha256": h.hexdigest(),
        "colunas": colunas,
        "classe": classe,
        "camadas": camadas,
    }


def inspecionar(arquivo: Path, nome: str) -> list[dict]:
    if nome.endswith((".tar.gz", ".tgz", ".tar")):
        resultado = []
        with tarfile.open(arquivo, "r|*") as pacote:
            for membro in pacote:
                caminho = caminho_membro(membro.name)
                if membro.isdir():
                    continue
                if not membro.isfile() or membro.size < 0 or membro.size > _LIMITE_MEMBRO:
                    raise ValueError("Pacote contém link, dispositivo ou membro inválido; extração proibida.")
                stream = pacote.extractfile(membro)
                if stream is None:
                    raise ValueError("Não foi possível inspecionar o membro regular do pacote.")
                with stream:
                    resultado.append(inspecionar_conteudo(stream, caminho, membro.size))
        return resultado
    with arquivo.open("rb") as origem:
        return [inspecionar_conteudo(origem, nome, arquivo.stat().st_size)]


def fingerprint(asset: dict) -> dict:
    return {k: asset.get(k) for k in ("id", "name", "size", "updated_at", "digest")}


def conferir_local(arquivo: Path, asset: dict) -> str:
    if not arquivo.is_file() or arquivo.stat().st_size != asset["size"]:
        raise ValueError("O arquivo local está ausente ou tem tamanho diferente do asset inventariado.")
    calculado = sha256(arquivo)
    remoto = asset.get("digest")
    if remoto and remoto != "sha256:" + calculado:
        raise ValueError("SHA256 do arquivo não confere com o digest informado pelo GitHub.")
    return calculado


def inventariar(gh: GitHub, repo: str, diretorio: Path, *, paralelos: int = 4) -> dict:
    repo = repositorio(repo)
    diretorio = diretorio.resolve()
    # Drafts não foram publicados e podem ser o próprio destino do backup.
    releases = [r for r in gh.json(f"repos/{repo}/releases", paginar=True) if not r["draft"]]
    tarefas = []
    for release in releases:
        for asset in gh.json(f"repos/{repo}/releases/{release['id']}/assets", paginar=True):
            tarefas.append((release, asset))

    def uma(tarefa):
        release, asset = tarefa
        nome = nome_seguro(asset["name"])
        local = diretorio / "assets" / str(release["id"]) / f"{asset['id']}-{nome}"
        if local.is_file():
            try:
                conferir_local(local, asset)
            except ValueError:
                gh.baixar(repo, asset["id"], local)
        else:
            gh.baixar(repo, asset["id"], local)
        digest = conferir_local(local, asset)
        membros = inspecionar(local, nome)
        # O snapshot integral vai para o privado, mesmo que permita projeção
        # básica. Não reconstruir histórico descartando colunas antes do backup.
        return {
            "release_id": release["id"],
            "tag": release["tag_name"],
            "origem": fingerprint(asset),
            "sha256": digest,
            "arquivo_local": str(local),
            "nome_backup": f"historico-{release['id']}-{asset['id']}-{nome}",
            "membros": membros,
            "classes": sorted({m["classe"] for m in membros}),
            "camadas": sorted({c for m in membros for c in m["camadas"]}),
            "destino": "snapshot_privado",
        }

    with ThreadPoolExecutor(max_workers=max(1, min(paralelos, 8))) as executor:
        assets = list(executor.map(uma, tarefas))
    rel = {
        "versao": VERSAO,
        "gerado_em": agora(),
        "origem": repo,
        "releases": [{"id": r["id"], "tag": r["tag_name"], "draft": r["draft"]} for r in releases],
        "assets": assets,
        "bytes": sum(a["origem"]["size"] for a in assets),
    }
    gravar_json(diretorio / "inventario.json", rel)
    resumo = [
        {
            "asset_id": a["origem"]["id"],
            "nome": a["origem"]["name"],
            "bytes": a["origem"]["size"],
            "sha256": a["sha256"],
            "membros": len(a["membros"]),
            "classes": a["classes"],
            "camadas": a["camadas"],
        }
        for a in assets
    ]
    gravar_json(diretorio / "resumo.json", resumo)
    return rel


def ler_inventario(arquivo: Path) -> dict:
    rel = json.loads(arquivo.read_text(encoding="utf-8"))
    if rel.get("versao") != VERSAO or not isinstance(rel.get("assets"), list):
        raise ValueError("Versão ou formato de inventário não reconhecido.")
    repositorio(rel["origem"])
    ids = [a["origem"]["id"] for a in rel["assets"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Inventário tem IDs de assets repetidos.")
    for asset in rel["assets"]:
        nome_seguro(asset["nome_backup"])
        if not re.fullmatch(r"[a-f0-9]{64}", asset["sha256"]):
            raise ValueError("Inventário sem SHA256 válido.")
    return rel


def destino_privado(gh: GitHub, repo: str, tag: str, origem: str) -> dict:
    repositorio(repo)
    if not tag or tag.startswith("-") or any(ord(c) < 32 for c in tag):
        raise ValueError("Tag de destino inválida.")
    # O root cria repositório e Release explicitamente antes desta fase.
    privado = gh.json(f"repos/{repo}").get("private") is True
    # /releases/tags/{tag} retorna 404 para draft, mesmo com credencial válida.
    encontrados = [r for r in gh.json(f"repos/{repo}/releases", paginar=True) if r.get("tag_name") == tag]
    if len(encontrados) != 1:
        raise ValueError("Release de destino ausente ou ambíguo; crie-o explicitamente antes de migrar.")
    release = gh.json(f"repos/{repo}/releases/{encontrados[0]['id']}")
    if not privado and release.get("draft") is not True:
        raise ValueError("Destino precisa ser repositório privado ou Release draft; migração recusada.")
    return release


def verificar_asset(gh: GitHub, repo: str, asset: dict, sha_esperado: str, diretorio: Path) -> None:
    arquivo = diretorio / f"verificacao-{asset['id']}.bin"
    try:
        gh.baixar(repo, asset["id"], arquivo)
        calculado = conferir_local(arquivo, asset)
        if calculado != sha_esperado:
            raise ValueError("Backup privado diverge do SHA256 do snapshot original.")
    finally:
        arquivo.unlink(missing_ok=True)


def copiar(gh: GitHub, rel: dict, repo: str, tag: str, diretorio: Path, *, executar: bool = False) -> dict:
    release = destino_privado(gh, repo, tag, rel["origem"])
    remotos = {a["name"]: a for a in gh.json(f"repos/{repo}/releases/{release['id']}/assets", paginar=True)}
    plano = []
    for item in rel["assets"]:
        local = Path(item["arquivo_local"])
        if conferir_local(local, item["origem"]) != item["sha256"]:
            raise ValueError("Snapshot local mudou desde o inventário.")
        nome = nome_seguro(item["nome_backup"])
        remoto = remotos.get(nome)
        if remoto is not None and (
            remoto["size"] != item["origem"]["size"] or remoto.get("digest") not in (None, "sha256:" + item["sha256"])
        ):
            raise ValueError("Já existe backup com este nome e conteúdo diferente; não sobrescrever.")
        plano.append(
            {
                "asset_id": item["origem"]["id"],
                "nome_backup": nome,
                "acao": "verificar_existente" if remoto else "copiar",
                "sha256": item["sha256"],
            }
        )
        if executar and remoto is None:
            destino_privado(gh, repo, tag, rel["origem"])
            gh.subir(repo, tag, local, nome)
    resposta = {"executado": executar, "destino": repo, "tag": tag, "acoes": plano}
    if executar:
        resposta["verificacao"] = verificar(gh, rel, repo, tag, diretorio)
    return resposta


def verificar(gh: GitHub, rel: dict, repo: str, tag: str, diretorio: Path) -> dict:
    release = destino_privado(gh, repo, tag, rel["origem"])
    remotos = {a["name"]: a for a in gh.json(f"repos/{repo}/releases/{release['id']}/assets", paginar=True)}
    registros = []
    for item in rel["assets"]:
        destino_privado(gh, repo, tag, rel["origem"])
        remoto = remotos.get(item["nome_backup"])
        if remoto is None:
            raise ValueError("Backup privado incompleto: falta um asset inventariado.")
        verificar_asset(gh, repo, remoto, item["sha256"], diretorio)
        gh.conferir_anonimo(repo, remoto)
        registros.append({"origem_id": item["origem"]["id"], "backup": fingerprint(remoto), "sha256": item["sha256"]})
    prova = {
        "versao": VERSAO,
        "verificado_em": agora(),
        "destino": repo,
        "release_id": release["id"],
        "tag": tag,
        "origem": rel["origem"],
        "assets": registros,
    }
    gravar_json(diretorio / "backup-verificado.json", prova)
    return prova


def remover(gh: GitHub, rel: dict, repo: str, tag: str, diretorio: Path, *, executar: bool = False) -> dict:
    # Nunca confiar apenas em prova antiga em disco: reconferir o backup de todos
    # os assets e o caráter privado do destino antes de preparar qualquer DELETE.
    prova = verificar(gh, rel, repo, tag, diretorio)
    publicados = [r for r in gh.json(f"repos/{rel['origem']}/releases", paginar=True) if not r["draft"]]
    if {r["id"] for r in publicados} != {r["id"] for r in rel["releases"]}:
        raise ValueError("A lista de Releases publicados mudou; atualizar inventário antes de remover.")
    vivos = {}
    for release in rel["releases"]:
        for asset in gh.json(f"repos/{rel['origem']}/releases/{release['id']}/assets", paginar=True):
            vivos[asset["id"]] = asset
    if set(vivos) - {item["origem"]["id"] for item in rel["assets"]}:
        raise ValueError("A origem recebeu assets novos; atualizar inventário antes de remover qualquer original.")
    plano = []
    for item in rel["assets"]:
        anterior = item["origem"]
        atual = vivos.get(anterior["id"])
        if atual is not None and fingerprint(atual) != anterior:
            raise ValueError("Origem mudou após o inventário. Refazer snapshot antes de remover qualquer asset.")
        plano.append(
            {
                "asset_id": anterior["id"],
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
    gravar_json(diretorio / "plano-remocao.json", resposta)
    if executar:
        for acao in plano:
            if acao["acao"] == "remover_original":
                destino_privado(gh, repo, tag, rel["origem"])
                # Releitura individual estreita a janela entre conferência e DELETE.
                atual = gh.json(f"repos/{rel['origem']}/releases/assets/{acao['asset_id']}")
                esperado = next(a["origem"] for a in rel["assets"] if a["origem"]["id"] == acao["asset_id"])
                if fingerprint(atual) != esperado:
                    raise ValueError("Origem mudou durante a remoção; interrompida antes do próximo asset.")
                gh.apagar(rel["origem"], acao["asset_id"])
                acao["removido"] = True
                gravar_json(diretorio / "remocao-progresso.json", resposta)
        resposta["executado"] = True
        gravar_json(diretorio / "remocao-progresso.json", resposta)
    return resposta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fase", choices=("inventariar", "copiar", "verificar", "remover"))
    parser.add_argument("--origem", default="bernardoemmel/Raiz")
    parser.add_argument("--diretorio", type=Path, default=Path("/tmp/raiz-migracao"))
    parser.add_argument("--inventario", type=Path)
    parser.add_argument("--destino")
    parser.add_argument("--tag", default="dados-historicos")
    parser.add_argument("--paralelos", type=int, default=4)
    parser.add_argument(
        "--executar", action="store_true", help="Efetiva somente a fase copiar ou remover; sem isso, dry-run."
    )
    args = parser.parse_args()
    os.umask(0o077)
    gh = GitHub()
    if args.fase == "inventariar":
        resultado = inventariar(gh, args.origem, args.diretorio, paralelos=args.paralelos)
        print(
            json.dumps(
                {
                    "inventario": str(args.diretorio / "inventario.json"),
                    "assets": len(resultado["assets"]),
                    "bytes": resultado["bytes"],
                },
                ensure_ascii=False,
            )
        )
        return
    if not args.destino:
        parser.error("--destino é obrigatório para copiar, verificar ou remover")
    rel = ler_inventario(args.inventario or args.diretorio / "inventario.json")
    funcao = {"copiar": copiar, "verificar": verificar, "remover": remover}[args.fase]
    extras = {} if args.fase == "verificar" else {"executar": args.executar}
    resultado = funcao(gh, rel, args.destino, args.tag, args.diretorio, **extras)
    gravar_json(args.diretorio / f"resultado-{args.fase}.json", resultado)
    print(
        json.dumps(
            {"fase": args.fase, "executado": args.executar, "relatorio": str(args.diretorio)}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
