"""Fichas da projeção pública existente, sem modificar pacotes ou manifesto básico."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
import tempfile
from pathlib import Path

from raiz.atestacao import registrar
from raiz.executor.publicacao_aberta import validar_asset_publico
from raiz.metadados import croissant_release, croissant_uf, ficha_arquivo, validar


def _bytes(ficha: dict) -> bytes:
    validar(ficha)
    return json.dumps(ficha, ensure_ascii=False, indent=2).encode()


def catalogar_publico(armazem, uf: str | None = None) -> None:
    """Descreve somente bytes básicos validados; nenhum índice é regravado.

    A trava da UF protege a leitura do pacote. A trava global protege o cartão,
    a ficha do índice e o catálogo separado. As fichas contêm esquemas, não linhas.
    """
    if armazem.privado:
        raise ValueError("catálogo público exige armazém público")
    if uf is not None and not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF inválida para o catálogo público")
    repo_codigo = os.environ.get("GITHUB_REPOSITORY", "bernardoemmel/Raiz")

    def baixar(nome):
        dados = armazem._baixar_asset(nome, fresco=True)
        if dados is None:
            raise RuntimeError("arquivo público desapareceu durante a catalogação")
        validar_asset_publico(nome, dados, repo=armazem.repo, tag=armazem.tag)
        registrar(nome, dados)
        return dados

    def enviar(nome, ficha):
        dados = _bytes(ficha)
        armazem._subir(armazem._release(), nome, dados, "application/ld+json")

    def ficha_simples(nome, dados, formato):
        return ficha_arquivo(
            nome,
            armazem.url(nome),
            hashlib.sha256(dados).hexdigest(),
            len(dados),
            escopo="publico_basico",
            formato=formato,
            repo=repo_codigo,
        )

    if uf is not None:
        with armazem._trava(f"trava-publicar-{uf}", 1800):
            presentes = {a["name"] for a in armazem._assets()}
            nome = f"raiz_{uf}.tar.gz"
            if nome in presentes:
                dados = baixar(nome)
                indice = armazem.manifesto(fresco=True)
                entrada = {
                    **indice.get("estados", {}).get(uf, {}),
                    "url": armazem.url(nome),
                    "sha256": hashlib.sha256(dados).hexdigest(),
                    "tamanho": len(dados),
                    "repo": armazem.repo,
                    "tag": armazem.tag,
                    "repo_codigo": repo_codigo,
                }
                # A validação acima confere caminhos e a allowlist de CSVs.
                with tempfile.TemporaryDirectory(prefix="raiz-croissant-basico-") as pasta:
                    destino = Path(pasta)
                    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
                        for membro in tar.getmembers():
                            if membro.isfile() and membro.name.endswith(".csv"):
                                (destino / Path(membro.name).name).write_bytes(tar.extractfile(membro).read())
                    ficha = (
                        croissant_uf(destino, uf, entrada, escopo="publico_basico")
                        if any(destino.glob("*.csv"))
                        else ficha_simples(nome, dados, ["application/x-tar", "application/gzip"])
                    )
                    enviar(f"croissant_{uf}.json", ficha)
            nome = f"raiz_geo_{uf}.tar.gz"
            if nome in presentes:
                dados = baixar(nome)
                enviar(f"croissant_{nome}.json", ficha_simples(nome, dados, ["application/x-tar", "application/gzip"]))

    with armazem._trava():
        # O manifesto público é fonte imutável nesta operação. As referências
        # de fichas vivem só na cópia em memória e no catálogo Croissant separado.
        dados = baixar("estados.json")
        indice = json.loads(dados)
        enviar("croissant_estados.json", ficha_simples("estados.json", dados, "application/json"))
        cartao = (Path(__file__).parents[1] / "docs/modelo/cartao.md").read_bytes()
        armazem._subir(armazem._release(), "cartao_modelo.md", cartao, "text/markdown")
        enviar("croissant_cartao_modelo.md.json", ficha_simples("cartao_modelo.md", cartao, "text/markdown"))
        referencias = {}
        for asset in armazem._assets():
            nome = asset["name"]
            if nome in {"croissant_estados.json", "croissant_cartao_modelo.md.json"}:
                origem = "estados.json" if nome == "croissant_estados.json" else "cartao_modelo.md"
            elif resultado := re.fullmatch(r"croissant_([A-Z]{2})\.json", nome):
                origem = f"raiz_{resultado[1]}.tar.gz"
            elif resultado := re.fullmatch(r"croissant_(raiz_geo_[A-Z]{2}\.tar\.gz)\.json", nome):
                origem = resultado[1]
            else:
                continue
            ficha = baixar(nome)
            referencias[origem] = {
                "url": armazem.url(nome),
                "sha256": hashlib.sha256(ficha).hexdigest(),
                "tamanho": len(ficha),
            }
        indice["fichas"] = referencias
        enviar(
            "croissant.json",
            croissant_release(
                indice,
                armazem.repo,
                armazem.tag,
                escopo="publico_basico",
                repo_codigo=repo_codigo,
            ),
        )
