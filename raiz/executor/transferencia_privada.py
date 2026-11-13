"""Transporta entradas, resultados e checkpoints de jobs só no arquivo autenticado.

Não usa artifacts nem caches do Actions para dados completos. Release em
rascunho nunca deve ser publicado; a visibilidade é conferida em cada acesso.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from raiz.executor.armazem import ArmazemRelease, destino_privado

MAX_ASSET_BYTES = 2_000_000_000  # margem conservadora para o limite de um asset no GitHub


def arquivo_privado() -> ArmazemRelease:
    destino = destino_privado()
    if not destino:
        raise PermissionError("transferência de dados completos exige RAIZ_DADOS_PRIVADOS_URL")
    arm = ArmazemRelease(
        *destino,
        espelho=Path(tempfile.gettempdir()) / "raiz-transferencia-privada",
        token=os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN", ""),
        privado=True,
    )
    arm._exigir_privado()
    return arm


def _nome(nome: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", nome):
        raise ValueError("nome inválido para o arquivo privado")
    return nome


def enviar_arquivo(nome: str, caminho: Path, *, imutavel: bool = False, arm: ArmazemRelease | None = None) -> None:
    arm = arm or arquivo_privado()
    arm._exigir_privado()
    nome = _nome(nome)
    if caminho.stat().st_size > MAX_ASSET_BYTES:
        raise ValueError("pacote privado excede o limite de 2 GB por asset; não será enviado nem truncado")
    dados = caminho.read_bytes()
    trava = "trava-transferencia-" + hashlib.sha256(nome.encode()).hexdigest()[:20]
    with arm._trava(trava, 1800):
        anterior = arm._baixar_asset(nome)
        if anterior == dados:
            return
        if imutavel and anterior is not None:
            raise ValueError(f"o asset imutável {nome} já existe com outro conteúdo")
        arm._subir(arm._release(), nome, dados)


def baixar_arquivo(nome: str, caminho: Path, *, opcional: bool = False, arm: ArmazemRelease | None = None) -> bool:
    arm = arm or arquivo_privado()
    dados = arm._baixar_asset(_nome(nome))
    if dados is None:
        if opcional:
            return False
        raise FileNotFoundError(f"asset privado ausente: {nome}")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_name(caminho.name + f".{os.getpid()}.tmp")
    temporario.write_bytes(dados)
    temporario.replace(caminho)
    return True


def empacotar(
    pasta: Path,
    destino: Path,
    *,
    prefixo: str = "",
    excluir: tuple[str, ...] = (),
    incluir: tuple[str, ...] = (),
) -> None:
    """Pacote determinístico, sem links, permissões ou nomes de usuários do runner."""
    if not pasta.is_dir():
        raise FileNotFoundError(pasta)
    selecionados = set()
    for padrao in incluir:
        if Path(padrao).is_absolute() or ".." in Path(padrao).parts:
            raise ValueError("seleção de cache deve ficar dentro da pasta de trabalho")
        for p in pasta.glob(padrao):
            selecionados.add(p)
            if p.is_dir() and not p.is_symlink():
                selecionados.update(p.rglob("*"))
    arquivos = selecionados if incluir else pasta.rglob("*")
    with destino.open("wb") as saida, gzip.GzipFile(fileobj=saida, mode="wb", mtime=0, filename="") as comprimido:
        with tarfile.open(fileobj=comprimido, mode="w") as tar:
            for f in sorted(arquivos):
                relativo = f.relative_to(pasta)
                if relativo.parts[0] in excluir:
                    continue
                if f.is_symlink() or not (f.is_file() or f.is_dir()):
                    raise ValueError("checkpoint não aceita links nem arquivos especiais")
                if not f.is_file():
                    continue
                info = tarfile.TarInfo((PurePosixPath(prefixo) / relativo.as_posix()).as_posix())
                info.size, info.mode = f.stat().st_size, 0o600
                with f.open("rb") as entrada:
                    tar.addfile(info, entrada)


def extrair(pacote: Path, destino: Path) -> None:
    """Valida todos os membros antes de escrever; nunca segue links do pacote ou do destino."""
    with tarfile.open(pacote, "r:gz") as tar:
        nomes = set()
        membros = tar.getmembers()
        raiz = destino.resolve()
        for m in membros:
            p = PurePosixPath(m.name)
            if (
                not m.isfile()
                or p.is_absolute()
                or ".." in p.parts
                or "\\" in m.name
                or m.name in nomes
                or p.as_posix() != m.name
                or not p.parts
                or any((destino / Path(*p.parts[:i])).is_symlink() for i in range(1, len(p.parts) + 1))
                or not (destino / m.name).resolve().is_relative_to(raiz)
            ):
                raise ValueError("caminho inválido no checkpoint privado")
            nomes.add(m.name)
        for m in membros:
            f = destino / m.name
            f.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(m) as entrada, f.open("wb") as saida:
                shutil.copyfileobj(entrada, saida)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acao", choices=("enviar-pasta", "baixar-pasta", "enviar-arquivo", "baixar-arquivo", "existe"))
    parser.add_argument("--nome", required=True)
    parser.add_argument("--caminho", type=Path)
    parser.add_argument("--selecao-env", help="variável com os caminhos relativos/globs permitidos, um por linha")
    parser.add_argument("--dia", help="em existe, exige atualização nesse dia UTC, no formato AAAAMMDD")
    parser.add_argument("--opcional", action="store_true")
    parser.add_argument("--imutavel", action="store_true")
    args = parser.parse_args()
    if args.acao == "existe":
        arm = arquivo_privado()
        nome = _nome(args.nome)
        if args.dia and not re.fullmatch(r"\d{8}", args.dia):
            raise ValueError("dia inválido")
        print(
            str(
                any(
                    a["name"] == nome and (not args.dia or a.get("updated_at", "")[:10].replace("-", "") == args.dia)
                    for a in arm._assets()
                )
            ).lower()
        )
        return
    if args.caminho is None:
        parser.error("--caminho é obrigatório para transferir arquivos")
    incluir = tuple(os.environ[args.selecao_env].splitlines()) if args.selecao_env else ()
    incluir = tuple(p.strip() for p in incluir if p.strip())
    if args.selecao_env and not incluir:
        raise ValueError("seleção de cache vazia")
    if args.acao == "enviar-arquivo":
        enviar_arquivo(args.nome, args.caminho, imutavel=args.imutavel)
    elif args.acao == "baixar-arquivo":
        baixar_arquivo(args.nome, args.caminho, opcional=args.opcional)
    else:
        with tempfile.TemporaryDirectory() as td:
            pacote = Path(td) / "pacote.tar.gz"
            if args.acao == "enviar-pasta":
                empacotar(args.caminho, pacote, incluir=incluir)
                enviar_arquivo(args.nome, pacote, imutavel=args.imutavel)
            elif baixar_arquivo(args.nome, pacote, opcional=args.opcional):
                extrair(pacote, args.caminho)


if __name__ == "__main__":
    main()
