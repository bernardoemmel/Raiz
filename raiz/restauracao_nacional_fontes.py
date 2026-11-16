"""Fontes imutáveis do catálogo nacional, transportadas somente no arquivo privado."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from raiz import restauracao_catalogo as C
from raiz.executor.transferencia_privada import enviar_arquivo


def baixar(arm, ref: dict, destino: Path) -> None:
    nome, sha = ref["nome"], ref["sha256"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", nome) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise ValueError("Referência privada inválida.")
    arm._exigir_privado()
    dados = arm._baixar_asset(nome, fresco=True)
    if dados is None or len(dados) != ref["bytes"] or hashlib.sha256(dados).hexdigest() != sha:
        raise ValueError("Fonte privada ausente ou divergente da referência imutável.")
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destino.write_bytes(dados)
    destino.chmod(0o600)


def publicar(arm, arquivo: Path, prefixo: str, extensao: str) -> dict:
    sha = C.sha256(arquivo)
    ref = {
        "nome": f"{prefixo}_{sha[:24]}{extensao}",
        "sha256": sha,
        "bytes": arquivo.stat().st_size,
        "acesso": "privado",
    }
    enviar_arquivo(ref["nome"], arquivo, imutavel=True, arm=arm)
    arm._exigir_privado()
    recuperado = arm._baixar_asset(ref["nome"], fresco=True)
    if recuperado is None or len(recuperado) != ref["bytes"] or hashlib.sha256(recuperado).hexdigest() != sha:
        raise ValueError("Publicação privada não recuperável; manifesto não será promovido.")
    return ref


def extrair_uf(pacote: Path, uf: str, destino: Path, *, geo: bool = False, municipios: set[int] | None = None) -> None:
    """Aceita só arquivos diretos da UF; separa metadados de base e geometria."""
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF inválida.")
    vistos = set()
    with tarfile.open(pacote, "r:gz") as tar:
        membros = tar.getmembers()
        for m in membros:
            p = PurePosixPath(m.name)
            if m.isdir() and m.name.rstrip("/") == uf:
                continue
            if (
                not m.isfile()
                or len(p.parts) != 2
                or p.parts[0] != uf
                or ".." in p.parts
                or "\\" in m.name
                or p.as_posix() != m.name
                or m.name in vistos
            ):
                raise ValueError("Pacote estadual com caminho, link ou duplicidade inválidos.")
            vistos.add(m.name)
        for m in membros:
            if not m.isfile():
                continue
            nome = PurePosixPath(m.name).name
            cod = re.search(r"_(\d{7})\.(csv|parquet)$", nome)
            if municipios is not None and (cod is None or int(cod[1]) not in municipios):
                continue
            if nome == "_versoes.json":
                nome = "_versoes_geo.json" if geo else "_versoes_base.json"
            alvo = destino / uf / nome
            if alvo.is_symlink() or any(p.is_symlink() for p in alvo.parents):
                raise ValueError("Destino da fonte não aceita links.")
            alvo.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tar.extractfile(m) as entrada, alvo.open("wb") as saida:
                shutil.copyfileobj(entrada, saida)
            alvo.chmod(0o600)


def capturar_uf(arm, uf: str, destino: Path) -> dict:
    """Congela o par base/geometria sob a trava usada pelo publicador estadual.

    A cópia imutável sobrevive à substituição dos nomes canônicos pelo motor.
    O bloqueio dura só a captura; indexação e consultas ocorrem após liberá-lo.
    """
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF inválida.")
    destino.mkdir(mode=0o700, parents=True, exist_ok=True)
    nomes = (f"raiz_{uf}.tar.gz", f"raiz_geo_{uf}.tar.gz")
    fontes = {}
    with arm._trava(f"trava-publicar-{uf}", 1800):
        arm._exigir_privado()
        ativos = {a["name"]: a for a in arm._assets()}
        if any(n not in ativos for n in nomes):
            raise ValueError("UF sem par de fontes publicado; ausência não é oferta zero.")
        for nome in nomes:
            arm._exigir_privado()
            ativo = ativos[nome]
            dados = arm._baixar_ativo(ativo)
            sha = hashlib.sha256(dados).hexdigest()
            if len(dados) != ativo["size"] or (ativo.get("digest") and ativo["digest"] != f"sha256:{sha}"):
                raise ValueError("Fonte canônica diverge do tamanho ou digest do GitHub.")
            arquivo = destino / nome
            arquivo.write_bytes(dados)
            arquivo.chmod(0o600)
            fontes[nome] = {
                "asset_id": ativo["id"],
                "sha256": sha,
                "bytes": len(dados),
                "atualizado_em": ativo["updated_at"],
            }
    for nome, origem in fontes.items():
        arquivo = destino / nome
        origem["copia_imutavel"] = publicar(arm, arquivo, "lote_fonte_" + nome[:-7], ".tar.gz")
        extrair_uf(arquivo, uf, destino / "saida", geo=nome.startswith("raiz_geo_"))
    pasta = destino / "saida" / uf
    for versoes in pasta.glob("_versoes_*.json"):
        for nome, meta in json.loads(versoes.read_text()).items():
            if Path(nome).name != nome:
                raise ValueError("Metadado municipal aponta para fora da UF.")
            if versoes.name == "_versoes_geo.json" and not nome.startswith("geo_"):
                continue  # pacote geométrico pode ser reutilizado quando só os CSV mudam
            arquivo = pasta / nome
            if arquivo.exists() and meta.get("sha256") and C.sha256(arquivo) != meta["sha256"]:
                raise ValueError("Fonte municipal diverge da proveniência do pacote estadual.")
    return {"uf": uf, "acesso": "privado", "fontes": fontes}
