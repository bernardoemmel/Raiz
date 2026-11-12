"""Retoma as cinco fatias interrompidas, mantendo os dados completos em Release rascunho.

O workflow executa o motor, a amostra e o lockfile do SHA original e copia somente
este orquestrador para aquele checkout. Nunca chama o publicador aberto da rodada.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from raiz import restauracao_rodada as RR

EXECUCAO_ORIGEM = 43285608189
SHA_ORIGEM = "31990520b842fd665152b2c7931b3556a66ca180"
MODELO = "restauracao-2026d+a84f9789"
RELEASE_ID = 443383695
REPOSITORIO_ID = 1454858834
TAG = "dados-privados"
PRONTAS = frozenset({"03", "04", "06", "07", "08", "09", "10", "11", "13", "14"})
FALTANTES = frozenset({"00", "01", "02", "05", "12"})
PREFIXO = f"retomada_PA_{EXECUCAO_ORIGEM}"
COMPROVANTES_MIGRACAO = {
    "inventario": {
        "nome": "artifacts-inventario-43289212685.json",
        "asset_id": 740830767,
        "sha256": "28870389749999b846045127a975b187f18070a6cf5381d535e6c81fbf646235",
    },
    "backup": {
        "nome": "artifacts-backup-43289212685.json",
        "asset_id": 740830763,
        "sha256": "ca8c4da5009ef966f4c1dbb7b42a20ed2ad8ebe24e8bf6679cf37389e0dff559",
    },
}


def _api_json(argumentos: list[str]):
    return json.loads(subprocess.check_output(["gh", "api", *argumentos], text=True))


def _api_baixar(endpoint: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".download")
    aceita = "application/vnd.github+json" if endpoint.endswith("/zip") else "application/octet-stream"
    with temporario.open("wb") as f:
        try:
            subprocess.run(
                ["gh", "api", endpoint, "-H", f"Accept: {aceita}"], stdout=f, stderr=subprocess.PIPE, check=True
            )
        except subprocess.CalledProcessError as erro:
            # gh pode incluir a URL temporária assinada do armazenamento no stderr.
            raise RuntimeError(f"Falha no download autenticado de {endpoint} (código {erro.returncode}).") from None
    temporario.replace(destino)


def _api_subir(endpoint: str, arquivo: Path) -> dict:
    return _api_json(
        ["--method", "POST", endpoint, "--input", str(arquivo), "-H", "Content-Type: application/octet-stream"]
    )


class Privado:
    """Acesso por ID fixo, sempre autenticado e condicionado ao rascunho ainda ser privado."""

    def __init__(self, repo: str = RR.REPO):
        if repo.lower() != RR.REPO.lower():
            raise ValueError("A retomada pertence ao repositório Raiz da execução original.")
        self.repo = repo
        self.base = f"repos/{repo}"

    def verificar(self) -> dict:
        release = _api_json([f"{self.base}/releases/{RELEASE_ID}"])
        if release.get("id") != RELEASE_ID or release.get("tag_name") != TAG or release.get("draft") is not True:
            raise PermissionError("Dados completos exigem o Release dados-privados ainda em rascunho.")
        return release

    def listar(self) -> dict[str, dict]:
        assets, pagina = {}, 1
        while True:
            self.verificar()
            lote = _api_json([f"{self.base}/releases/{RELEASE_ID}/assets?per_page=100&page={pagina}"])
            for a in lote:
                if a["name"] in assets:
                    raise ValueError("Nome de asset duplicado no arquivo privado.")
                assets[a["name"]] = a
            if len(lote) < 100:
                return assets
            pagina += 1

    def baixar(self, nome: str, destino: Path, sha_esperado: str | None = None) -> Path:
        a = self.listar().get(nome)
        if a is None:
            raise FileNotFoundError(f"Asset privado ausente: {nome}")
        self.verificar()  # revalidar imediatamente antes do download, não somente ao listar
        _api_baixar(f"{self.base}/releases/assets/{a['id']}", destino)
        if destino.stat().st_size != a["size"] or (sha_esperado and RR.sha256(destino) != sha_esperado):
            raise ValueError(f"Integridade inválida no asset privado: {nome}")
        return destino

    def subir(self, arquivo: Path, nome: str) -> dict:
        if Path(nome).name != nome or not nome.startswith((PREFIXO, "lote_PA_central_r11_retomada_")):
            raise ValueError("Nome de publicação fora da retomada.")
        sha = RR.sha256(arquivo)
        existente = self.listar().get(nome)
        if existente:
            # Publicações são imutáveis: repetir só é permitido se o conteúdo já estiver idêntico.
            with tempfile.TemporaryDirectory() as td:
                self.baixar(nome, Path(td) / nome, sha)
            a = existente
        else:
            self.verificar()  # ID exato evita trocar acidentalmente o Release de destino
            endpoint = f"https://uploads.github.com/repos/{self.repo}/releases/{RELEASE_ID}/assets?name={quote(nome)}"
            a = _api_subir(endpoint, arquivo)
            if a.get("name") != nome or a.get("size") != arquivo.stat().st_size:
                raise ValueError("Resposta do upload privado não confere com o arquivo enviado.")
            # Confirma bytes efetivamente recuperáveis antes de referenciá-los no manifesto.
            with tempfile.TemporaryDirectory() as td:
                self.baixar(nome, Path(td) / nome, sha)
        return {
            "nome": nome,
            "asset_id": a["id"],
            "sha256": sha,
            "bytes": arquivo.stat().st_size,
            "api_url": f"https://api.github.com/{self.base}/releases/assets/{a['id']}",
        }


def validar_origem(run: dict) -> None:
    if (
        run.get("id") != EXECUCAO_ORIGEM
        or run.get("head_sha") != SHA_ORIGEM
        or run.get("path") != ".github/workflows/lote-para.yml"
        or run.get("conclusion") != "cancelled"
    ):
        raise ValueError("A origem não corresponde à rodada interrompida e ao SHA autorizado.")


def conferir_modelo() -> None:
    from raiz import restauracao as R

    if R.versao() != MODELO:
        raise ValueError("A retomada exige o mesmo modelo da origem; não misturar previsões de versões diferentes.")


def planejar_retomada(snapshot: dict, prontas: set[str]) -> dict:
    plano = snapshot.get("plano", [])
    fatias = {p["fatia"] for p in plano}
    cods = [int(c) for p in plano for c in p["municipios"]]
    if (
        snapshot.get("cenario") != RR.CENARIO
        or len(plano) != 15
        or fatias != PRONTAS | FALTANTES
        or len(cods) != len(set(cods))
        or set(cods) != RR.municipios_pa()
        or sum(p.get("imoveis", 0) for p in plano) != 345870
    ):
        raise ValueError("O snapshot não cobre exatamente os 144 municípios nas 15 fatias originais.")
    if set(prontas) != PRONTAS:
        raise ValueError("A retomada deve preservar as dez fatias concluídas e calcular somente as cinco faltantes.")
    return {
        "reusadas": sorted(prontas),
        "calcular": sorted(FALTANTES),
        "matriz": {"include": [{"fatia": f} for f in sorted(FALTANTES)]},
    }


def extrair_zip(arquivo: Path, destino: Path) -> None:
    """Artifacts esperados têm apenas arquivos na raiz; links e caminhos externos são rejeitados."""
    vistos = set()
    with zipfile.ZipFile(arquivo) as z:
        for info in z.infolist():
            p = Path(info.filename)
            modo = info.external_attr >> 16
            if (
                info.is_dir()
                or len(p.parts) != 1
                or p.is_absolute()
                or ".." in p.parts
                or stat.S_ISLNK(modo)
                or p in vistos
            ):
                raise ValueError("Caminho inválido no artifact da origem.")
            vistos.add(p)
            destino.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, (destino / p.name).open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _extrair_tar(arquivo: Path, destino: Path, raiz_pa: bool = True) -> None:
    vistos = set()
    with tarfile.open(arquivo) as t:
        for m in t:
            p = Path(m.name)
            if p.is_absolute() or ".." in p.parts or not (m.isdir() or m.isfile()) or p in vistos:
                raise ValueError("Caminho inválido no pacote da retomada.")
            vistos.add(p)
            if raiz_pa and (not p.parts or p.parts[0] != "PA"):
                raise ValueError("Pacote calculado fora da pasta PA.")
            if not raiz_pa and (len(p.parts) != 1 or not m.isfile()):
                raise ValueError("Entrada congelada deve conter apenas os arquivos esperados na raiz.")
            if m.isdir():
                continue
            f = destino / p
            f.parent.mkdir(parents=True, exist_ok=True)
            with t.extractfile(m) as src, f.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def validar_fatia(
    pacote: Path, cods: list[int], snapshot: dict | None = None, fatia: str | None = None, origem: Path | None = None
) -> None:
    import pandas as pd

    with tempfile.TemporaryDirectory() as td:
        _extrair_tar(pacote, Path(td))
        pasta = Path(td) / "PA"
        for cod in cods:
            marca = RR._ler(pasta / f"rodada_{cod}.json")
            for nome in marca["arquivos"]:
                p = Path(nome)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError("Arquivo da marca fora da pasta do município.")
            if snapshot is not None:
                esperado = RR._hash_entradas(snapshot, cod)
                if marca.get("entradas_versao") != esperado:
                    raise ValueError("A previsão não usa as entradas congeladas da execução original.")
                d = pd.read_csv(
                    pasta / f"desenvolvedor_{cod}.csv",
                    usecols=["cod_imovel", "entradas_versao"],
                    dtype={"cod_imovel": str},
                )
                if set(d.entradas_versao) != {esperado}:
                    raise ValueError("O CSV não usa as entradas congeladas da execução original.")
                arquivo = marca["previsoes"]["arquivo"]
                p = Path(arquivo)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError("Registro da previsão fora da pasta do município.")
                codigos_previsao = []
                with (pasta / arquivo).open(encoding="utf-8") as f:
                    for linha in f:
                        previsao = json.loads(linha)
                        codigos_previsao.append(previsao.get("cod_imovel"))
                        if previsao.get("entradas_versao") != esperado or previsao.get("modelo_versao") != MODELO:
                            raise ValueError("Registro imutável diverge das entradas ou do modelo original.")
                if len(codigos_previsao) != len(set(codigos_previsao)) or set(codigos_previsao) != set(d.cod_imovel):
                    raise ValueError("O registro imutável não preserva todas as fazendas do CSV.")
                if origem is not None:
                    bruto = pd.read_csv(
                        origem / f"imoveis_{cod}.csv", usecols=["cod_imovel"], dtype={"cod_imovel": str}
                    )
                    if not bruto.cod_imovel.is_unique or set(bruto.cod_imovel) != set(d.cod_imovel):
                        raise ValueError("O cálculo alterou o conjunto de fazendas da fonte congelada.")
        marcas = RR.conferir_calculos(pasta, {"com_imoveis": cods}, MODELO)
        if snapshot is not None:
            esperado = next(x for x in snapshot["plano"] if x["fatia"] == fatia)
            if sum(m["imoveis"] for m in marcas) != esperado["imoveis"] or set(cods) != set(esperado["municipios"]):
                raise ValueError("A fatia não preserva a contagem ou os municípios da origem.")


def _executar_id() -> str:
    valor = os.environ.get("GITHUB_RUN_ID", "")
    if not valor.isdigit():
        raise ValueError("A retomada deve ser identificada por uma execução do GitHub Actions.")
    return valor


def _nome_conclusao(fatia: str) -> str:
    return f"{PREFIXO}_exec_{_executar_id()}_fatia_{fatia}.json"


def _nome_com_hash(arquivo: Path, tipo: str) -> str:
    return f"{PREFIXO}_{tipo}_{RR.sha256(arquivo)[:16]}{''.join(arquivo.suffixes)}"


def _validar_comprovantes(inventario: dict, backup: dict, assets: dict[str, dict]) -> dict[str, dict]:
    """Liga os ZIPs privados à identidade e ao SHA oficial de cada artifact antes da migração."""
    if (
        inventario.get("versao") != 1
        or inventario.get("tipo") != "actions_artifacts"
        or inventario.get("origem") != RR.REPO
        or backup.get("versao") != 1
        or backup.get("origem") != RR.REPO
        or backup.get("destino") != RR.REPO
        or backup.get("release_id") != RELEASE_ID
        or backup.get("tag") != TAG
    ):
        raise ValueError("Comprovantes de migração pertencem a outra origem ou destino.")
    copias = {}
    for item in backup.get("assets", []):
        if item.get("origem_id") in copias:
            raise ValueError("Artifact duplicado no comprovante de backup.")
        copias[item.get("origem_id")] = item
    out, ids = {}, set()
    for item in inventario.get("assets", []):
        a = item.get("artifact", {})
        run = a.get("workflow_run", {})
        if run.get("id") != EXECUCAO_ORIGEM:
            continue
        if (
            run.get("head_sha") != SHA_ORIGEM
            or run.get("repository_id") != REPOSITORIO_ID
            or run.get("head_repository_id") != REPOSITORIO_ID
            or not isinstance(a.get("id"), int)
            or a.get("id", 0) <= 0
            or not isinstance(a.get("size_in_bytes"), int)
            or a.get("size_in_bytes", 0) <= 0
            or a.get("id") in ids
            or a.get("name") in out
            or a.get("expired") is not False
        ):
            raise ValueError("Artifact migrado não corresponde à execução e ao repositório originais.")
        nome = f"actions-{a['id']}-{a.get('name')}.zip"
        sha = item.get("sha256", "")
        digest = "sha256:" + sha
        origem = item.get("origem", {})
        copia = copias.get(a["id"], {})
        ref = copia.get("backup", {})
        atual = assets.get(nome, {})
        if (
            not re.fullmatch(r"[0-9a-f]{64}", sha)
            or a.get("digest") != digest
            or item.get("nome_backup") != nome
            or origem.get("id") != a["id"]
            or origem.get("name") != a.get("name")
            or origem.get("size") != a.get("size_in_bytes")
            or origem.get("digest") != digest
            or copia.get("sha256") != sha
            or ref.get("digest") != digest
            or ref.get("name") != nome
            or ref.get("size") != a.get("size_in_bytes")
            or not isinstance(ref.get("id"), int)
            or atual.get("id") != ref.get("id")
            or atual.get("name") != nome
            or atual.get("size") != a.get("size_in_bytes")
            or atual.get("digest") != digest
        ):
            raise ValueError("Identidade, tamanho ou SHA do ZIP privado diverge dos comprovantes da migração.")
        ids.add(a["id"])
        out[a["name"]] = {**a, "nome_backup": nome, "sha256": sha, "backup_asset_id": ref["id"]}
    esperados = {"entradas-congeladas", *(f"calculado-{f}" for f in PRONTAS)}
    if set(out) != esperados:
        raise ValueError("Os comprovantes devem conter as entradas e exatamente as dez fatias concluídas.")
    return out


def _artefatos_origem(privado: Privado) -> dict[str, dict]:
    # Os artifacts originais foram removidos depois do backup privado; não há fallback público.
    documentos = {}
    with tempfile.TemporaryDirectory() as td:
        for tipo, ref in COMPROVANTES_MIGRACAO.items():
            a = privado.listar().get(ref["nome"], {})
            if a.get("id") != ref["asset_id"] or a.get("digest") != "sha256:" + ref["sha256"]:
                raise ValueError("Comprovante privado ausente ou diferente do ID e SHA autorizados.")
            local = Path(td) / f"{tipo}.json"
            privado.baixar(ref["nome"], local, ref["sha256"])
            documentos[tipo] = RR._ler(local)
    return _validar_comprovantes(documentos["inventario"], documentos["backup"], privado.listar())


def _baixar_artifact(privado: Privado, a: dict, destino: Path) -> None:
    atual = privado.listar().get(a["nome_backup"], {})
    if atual.get("id") != a["backup_asset_id"]:
        raise ValueError("O ZIP privado não é o asset preservado no comprovante de backup.")
    privado.baixar(a["nome_backup"], destino, a["sha256"])
    if destino.stat().st_size != a["size_in_bytes"]:
        raise ValueError("Tamanho divergente no artifact da origem.")
    if a["digest"] != "sha256:" + RR.sha256(destino):
        raise ValueError("SHA256 divergente no artifact da origem.")


def preparar(destino: Path, privado: Privado) -> dict:
    conferir_modelo()
    privado.verificar()
    run = _api_json([f"{privado.base}/actions/runs/{EXECUCAO_ORIGEM}"])
    validar_origem(run)
    artefatos = _artefatos_origem(privado)
    esperados = {"entradas-congeladas", *(f"calculado-{f}" for f in PRONTAS)}
    if set(artefatos) != esperados:
        raise ValueError("Os artifacts da origem não correspondem às entradas e às dez fatias concluídas.")
    destino.mkdir(parents=True, exist_ok=True)
    entradas = destino / "entradas"
    zip_entrada = destino / "entradas.zip"
    _baixar_artifact(privado, artefatos["entradas-congeladas"], zip_entrada)
    extrair_zip(zip_entrada, entradas)
    if {p.name for p in entradas.iterdir()} != {*RR.PACOTES, "estados.json", "snapshot.json"}:
        raise ValueError("Arquivos inesperados nas entradas congeladas.")
    snapshot = RR._ler(entradas / "snapshot.json")
    plano = planejar_retomada(snapshot, set(PRONTAS))
    for nome in (*RR.PACOTES, "estados.json"):
        if RR.sha256(entradas / nome) != snapshot["fontes"][nome]["sha256"]:
            raise ValueError("As fontes congeladas não conferem com os hashes originais.")
    RR.extrair(entradas / RR.PACOTES[0], destino / "verificacao")
    pacote_entrada = destino / "entradas.tar.gz"
    with tarfile.open(pacote_entrada, "w:gz") as t:
        for f in sorted(entradas.iterdir()):
            info = t.gettarinfo(str(f), arcname=f.name)
            info.mtime = 0
            with f.open("rb") as src:
                t.addfile(info, src)
    plano.update(
        {
            "execucao_origem": EXECUCAO_ORIGEM,
            "sha_origem": SHA_ORIGEM,
            "modelo_versao": MODELO,
            "release_id": RELEASE_ID,
            "draft": True,
            "snapshot_sha256": RR.sha256(entradas / "snapshot.json"),
            "entradas": privado.subir(pacote_entrada, _nome_com_hash(pacote_entrada, "entradas")),
            "fatias": snapshot["plano"],
            "concluidas": {},
            "artifacts_origem": artefatos,
            "comprovantes_migracao": COMPROVANTES_MIGRACAO,
        }
    )
    for fatia in sorted(PRONTAS):
        pasta = destino / fatia
        zip_calc = destino / f"calculado-{fatia}.zip"
        _baixar_artifact(privado, artefatos[f"calculado-{fatia}"], zip_calc)
        extrair_zip(zip_calc, pasta)
        pacote = pasta / f"calculado_{fatia}.tar.gz"
        if {f.name for f in pasta.iterdir()} != {pacote.name}:
            raise ValueError("Conteúdo inesperado no artifact calculado.")
        cods = next(p["municipios"] for p in snapshot["plano"] if p["fatia"] == fatia)
        validar_fatia(pacote, cods, snapshot, fatia, destino / "verificacao/PA")
        plano["concluidas"][fatia] = privado.subir(pacote, _nome_com_hash(pacote, f"calculado_{fatia}"))
    local = destino / "plano.json"
    RR._json(local, plano)
    plano_asset = privado.subir(local, _nome_com_hash(local, "plano"))
    saida = {"plano": plano_asset["nome"], "plano_sha256": plano_asset["sha256"], "matriz": plano["matriz"]}
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as f:
            for k, v in saida.items():
                f.write(f"{k}={json.dumps(v) if isinstance(v, dict) else v}\n")
    return saida


def carregar_plano(privado: Privado, nome: str, sha: str, destino: Path) -> dict:
    conferir_modelo()
    privado.baixar(nome, destino / "plano.json", sha)
    plano = RR._ler(destino / "plano.json")
    if (
        plano.get("execucao_origem") != EXECUCAO_ORIGEM
        or plano.get("sha_origem") != SHA_ORIGEM
        or plano.get("modelo_versao") != MODELO
        or plano.get("release_id") != RELEASE_ID
        or plano.get("comprovantes_migracao") != COMPROVANTES_MIGRACAO
        or set(plano.get("reusadas", [])) != PRONTAS
        or set(plano.get("calcular", [])) != FALTANTES
    ):
        raise ValueError("Manifesto privado não corresponde à retomada autorizada.")
    planejar_retomada({"cenario": RR.CENARIO, "plano": plano["fatias"]}, set(plano["reusadas"]))
    if set(plano["concluidas"]) != PRONTAS:
        raise ValueError("Manifesto privado precisa preservar exatamente as dez fatias prontas.")
    return plano


def baixar_entradas(privado: Privado, plano: dict, destino: Path) -> None:
    entrada = plano["entradas"]
    pacote = destino / "entradas.tar.gz"
    privado.baixar(entrada["nome"], pacote, entrada["sha256"])
    _extrair_tar(pacote, destino / "entradas", raiz_pa=False)
    if RR.sha256(destino / "entradas/snapshot.json") != plano["snapshot_sha256"]:
        raise ValueError("Snapshot privado divergente da origem.")


def restaurar_checkpoint(privado: Privado, destino: Path, fatia: str) -> None:
    prefixo = f"{PREFIXO}_exec_{_executar_id()}_fatia_{fatia}_checkpoint_"
    candidatos = [a for n, a in privado.listar().items() if n.startswith(prefixo)]
    if not candidatos:
        return
    ultimo = max(candidatos, key=lambda a: (a["created_at"], a["id"]))
    pacote = destino / "checkpoint.tar.gz"
    privado.baixar(ultimo["name"], pacote)
    _extrair_tar(pacote, destino / "fatia/resultado")


def calcular(privado: Privado, plano: dict, destino: Path, fatia: str) -> dict:
    if fatia not in FALTANTES:
        raise ValueError("Uma das dez fatias concluídas não pode ser recalculada nesta retomada.")
    privado.verificar()
    conferir_modelo()
    snapshot = RR._ler(destino / "entradas/snapshot.json")
    cods = next(p["municipios"] for p in plano["fatias"] if p["fatia"] == fatia)
    if _nome_conclusao(fatia) in privado.listar():
        arquivo = destino / "conclusao_existente.json"
        privado.baixar(_nome_conclusao(fatia), arquivo)
        fim = RR._ler(arquivo)
        if (
            fim.get("fatia") != fatia
            or fim.get("modelo_versao") != MODELO
            or fim.get("execucao_origem") != EXECUCAO_ORIGEM
            or fim.get("execucao_retomada") != _executar_id()
        ):
            raise ValueError("Conclusão existente incompatível com a retomada.")
        ref = fim["pacote"]
        pacote = destino / "fatia" / f"calculado_{fatia}.tar.gz"
        privado.baixar(ref["nome"], pacote, ref["sha256"])
        RR.extrair(destino / "entradas" / RR.PACOTES[0], destino / "verificacao", set(cods))
        validar_fatia(pacote, cods, snapshot, fatia, destino / "verificacao/PA")
        return {**fim["resumo"], "conclusao_reaproveitada": True}
    restaurar_checkpoint(privado, destino, fatia)
    # RR valida versão, hash das entradas, CSV e registros imutáveis antes de aceitar cada checkpoint.
    resumo = RR.calcular(destino / "entradas", destino / "fatia", fatia)
    pacote = destino / "fatia" / f"calculado_{fatia}.tar.gz"
    validar_fatia(pacote, cods, snapshot, fatia, destino / "fatia/trabalho/PA")
    referencia = privado.subir(pacote, _nome_com_hash(pacote, f"calculado_{fatia}"))
    conclusao = {
        "fatia": fatia,
        "execucao_origem": EXECUCAO_ORIGEM,
        "execucao_retomada": _executar_id(),
        "modelo_versao": MODELO,
        "resumo": resumo,
        "pacote": referencia,
    }
    arquivo = destino / "conclusao.json"
    RR._json(arquivo, conclusao)
    privado.subir(arquivo, _nome_conclusao(fatia))
    return resumo


def checkpoint(privado: Privado, destino: Path, fatia: str) -> None:
    if fatia not in FALTANTES:
        raise ValueError("Fatia fora da retomada.")
    pasta = destino / "fatia/resultado/PA"
    if not pasta.exists():
        return
    privado.verificar()
    arquivo = destino / "checkpoint.tar.gz"
    with tarfile.open(arquivo, "w:gz") as t:
        t.add(pasta, arcname="PA")
    nome = f"{PREFIXO}_exec_{_executar_id()}_fatia_{fatia}_checkpoint_{RR.sha256(arquivo)[:16]}.tar.gz"
    privado.subir(arquivo, nome)


def reunir_publicar(privado: Privado, plano: dict, destino: Path) -> dict:
    conferir_modelo()
    referencias = dict(plano["concluidas"])
    for fatia in sorted(FALTANTES):
        arquivo = destino / f"conclusao_{fatia}.json"
        privado.baixar(_nome_conclusao(fatia), arquivo)
        fim = RR._ler(arquivo)
        if (
            fim.get("fatia") != fatia
            or fim.get("modelo_versao") != MODELO
            or fim.get("execucao_origem") != EXECUCAO_ORIGEM
            or fim.get("execucao_retomada") != _executar_id()
        ):
            raise ValueError("Conclusão de fatia não corresponde à execução de retomada.")
        referencias[fatia] = fim["pacote"]
    if set(referencias) != PRONTAS | FALTANTES:
        raise ValueError("Faltam fatias para reunir os 144 municípios.")
    calculados = destino / "calculados"
    snapshot = RR._ler(destino / "entradas/snapshot.json")
    RR.extrair(destino / "entradas" / RR.PACOTES[0], destino / "verificacao")
    for fatia, ref in sorted(referencias.items()):
        pacote = calculados / f"calculado_{fatia}.tar.gz"
        privado.baixar(ref["nome"], pacote, ref["sha256"])
        cods = next(p["municipios"] for p in plano["fatias"] if p["fatia"] == fatia)
        validar_fatia(pacote, cods, snapshot, fatia, destino / "verificacao/PA")
    entrega = destino / "entrega"
    manifesto = RR.reunir(destino / "entradas", calculados, entrega)
    if manifesto["imoveis_calculados"] != 345870 or manifesto["municipios"] != 144:
        raise ValueError("A reunião não preservou os 345.870 imóveis e os 144 municípios da origem.")
    manifesto["commit"] = SHA_ORIGEM
    manifesto["retomada"] = {
        "execucao_origem": EXECUCAO_ORIGEM,
        "sha_origem": SHA_ORIGEM,
        "execucao_atual": _executar_id(),
        "sha_orquestrador": os.environ.get("GITHUB_SHA"),
        "modelo_versao": MODELO,
        "fatias_reusadas": sorted(PRONTAS),
        "fatias_calculadas": sorted(FALTANTES),
        "quantidade_reusadas": 10,
        "quantidade_calculadas": 5,
        "fontes_privadas": referencias,
        "comprovantes_migracao": plano["comprovantes_migracao"],
        "checkpoints_originais_disponiveis": False,
    }
    manifesto["destino"] = {"tipo": "release_rascunho", "id": RELEASE_ID, "tag": TAG, "publico": False}
    produto = entrega / "produto"
    RR._json(produto / "manifesto.json", manifesto)
    base = f"lote_PA_central_r11_retomada_{_executar_id()}_{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    arquivos = {}
    for nome in (*RR.OPCOES, "previsoes"):
        pacote = entrega / f"{nome}.tar.gz"
        with tarfile.open(pacote, "w:gz") as tar:
            if nome == "previsoes":
                for f in sorted(produto.iterdir()):
                    if f.name not in RR.OPCOES:
                        tar.add(f, arcname=f.name)
            else:
                tar.add(produto / nome, arcname=nome)
        asset = f"{base}_{nome}_{RR.sha256(pacote)[:16]}.tar.gz"
        arquivos[nome] = privado.subir(pacote, asset)
    manifesto["arquivos"] = arquivos
    resumo = entrega / "manifesto_privado.json"
    RR._json(resumo, manifesto)
    manifesto_asset = privado.subir(resumo, f"{base}_{RR.sha256(resumo)[:16]}.json")
    return {
        "manifesto": manifesto_asset,
        "municipios": manifesto["municipios"],
        "imoveis": manifesto["imoveis_calculados"],
        "fatias_reusadas": 10,
        "fatias_calculadas": 5,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("etapa", choices=("verificar", "preparar", "baixar", "calcular", "checkpoint", "publicar"))
    p.add_argument("--destino", type=Path, default=Path("rodada"))
    p.add_argument("--repo", default=RR.REPO)
    p.add_argument("--retomar-execucao", type=int, default=EXECUCAO_ORIGEM)
    p.add_argument("--plano")
    p.add_argument("--plano-sha256")
    p.add_argument("--fatia")
    a = p.parse_args()
    if a.retomar_execucao != EXECUCAO_ORIGEM:
        p.error("Somente a execução original autorizada pode ser retomada.")
    privado = Privado(a.repo)
    if a.etapa == "verificar":
        privado.verificar()
        conferir_modelo()
        print("Destino privado em rascunho e versão original confirmados.")
    elif a.etapa == "preparar":
        print(json.dumps(preparar(a.destino, privado), ensure_ascii=False))
    elif a.etapa == "checkpoint":
        checkpoint(privado, a.destino, a.fatia)
        print("Checkpoint preservado somente no arquivo privado.")
    else:
        plano = carregar_plano(privado, a.plano, a.plano_sha256, a.destino)
        if a.etapa == "baixar":
            baixar_entradas(privado, plano, a.destino)
            print("Entradas congeladas recuperadas do arquivo privado.")
        elif a.etapa == "calcular":
            print(json.dumps(calcular(privado, plano, a.destino, a.fatia)))
        else:
            baixar_entradas(privado, plano, a.destino)
            print(json.dumps(reunir_publicar(privado, plano, a.destino)))


if __name__ == "__main__":
    main()
