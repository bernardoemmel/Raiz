"""Corte verificável para projeções públicas, preservando integralmente os originais.

Sem --executar, somente inventaria, prepara e confere o plano. Antes de qualquer
DELETE, todos os assets públicos têm backup privado rebaixado, SHA256 conferido
e HTTP 404 anônimo. Escritores concorrentes devem estar parados. Em interrupção,
--retomar recebe o nome do inventário guardado no Release privado; nunca refaça
um inventário parcial para substituir os canônicos completos.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import quote

from raiz.executor.armazem import TOTAL_IBGE, ArmazemRelease, do_config
from raiz.executor.publicacao_aberta import ESCOPO, VERSAO_PUBLICACAO, validar_asset_publico
from scripts import migrar_dados_privados as m

_CANONICO = re.compile(r"raiz_(?:(?:geo_|camadas_)?([A-Z]{2})\.tar\.gz|controle(?:_([A-Z]{2}))?\.json)")


def _assets(gh: m.GitHub, repo: str, release_id: int) -> dict[str, dict]:
    lista = gh.json(f"repos/{repo}/releases/{release_id}/assets", paginar=True)
    nomes = [a["name"] for a in lista]
    if len(nomes) != len(set(nomes)):
        raise ValueError("Release com nomes de assets repetidos; corte recusado.")
    return {a["name"]: a for a in lista}


def canonicos(rel: dict, tag: str) -> dict:
    releases = [r for r in rel["releases"] if r["tag"] == tag]
    if len(releases) != 1:
        raise ValueError("Release público canônico ausente ou ambíguo.")
    itens = []
    for item in rel["assets"]:
        nome = item["origem"]["name"]
        if item["release_id"] != releases[0]["id"]:
            continue
        match = _CANONICO.fullmatch(nome)
        if nome != "estados.json" and not match:
            continue  # desconhecido continua somente no backup histórico
        if match and any(u not in TOTAL_IBGE for u in match.groups() if u):
            raise ValueError("Pacote canônico contém UF desconhecida.")
        itens.append({**item, "nome_backup": nome})
    nomes = [i["nome_backup"] for i in itens]
    if "estados.json" not in nomes or len(nomes) != len(set(nomes)):
        raise ValueError("Canônicos sem manifesto ou com nomes repetidos.")
    return {**rel, "assets": itens}


class _Coletor:
    """Interface do publicador, restrita a escrita LOCAL e validação da allowlist."""

    privado = False

    def __init__(self, repo: str, tag: str, diretorio: Path):
        self.repo, self.tag, self.diretorio = repo, tag, diretorio
        self.arquivos: dict[str, Path] = {}
        self.estados: dict = {}
        diretorio.mkdir(parents=True, exist_ok=True)

    def url(self, nome):
        return f"https://github.com/{self.repo}/releases/download/{self.tag}/{nome}"

    def _trava(self, *args):
        return contextlib.nullcontext()

    def _release(self):
        return {}

    def _subir(self, release, nome, dados, tipo=None):
        validar_asset_publico(nome, dados)
        arquivo = self.diretorio / m.nome_seguro(nome)
        arquivo.write_bytes(dados)
        self.arquivos[nome] = arquivo

    def _gravar_indice(self, feito):
        self.estados.update(feito)


class _Snapshot(ArmazemRelease):
    """Usa o parser do armazém sobre o snapshot, sem rede nem trava remota."""

    def __init__(self, rel: dict, tag: str, espelho: Path, publico: _Coletor):
        super().__init__(rel["origem"], tag, espelho=espelho, token="", privado=True, publico=publico)
        self.arquivos = {i["origem"]["name"]: i for i in rel["assets"]}

    def _exigir_privado(self):
        pass  # este adaptador lê exclusivamente arquivos locais já inventariados

    def _baixar_asset(self, nome, fresco=False):
        item = self.arquivos.get(nome)
        if item is None:
            return None
        arquivo = Path(item["arquivo_local"])
        if m.conferir_local(arquivo, item["origem"]) != item["sha256"]:
            raise ValueError("Snapshot local mudou; projeção recusada.")
        return arquivo.read_bytes()


def preparar(rel: dict, tag: str, diretorio: Path) -> dict[str, Path]:
    """Reutiliza a projeção do armazém e valida TODOS os arquivos antes do corte."""
    atuais = canonicos(rel, tag)
    coletor = _Coletor(rel["origem"], tag, diretorio / "publico")
    # Espelho novo evita incorporar sobras de rodadas anteriores ou arquivos locais.
    with tempfile.TemporaryDirectory(prefix="espelho-corte-", dir=diretorio) as pasta:
        arm = _Snapshot(atuais, tag, Path(pasta), coletor)
        try:
            manifesto = arm.manifesto()
            estados = manifesto.get("estados")
            if not isinstance(estados, dict) or not estados or any(u not in TOTAL_IBGE for u in estados):
                raise ValueError("Manifesto canônico sem estados válidos.")
            ufs_pacotes = {
                match.group(1)
                for nome in arm.arquivos
                if (match := re.fullmatch(r"raiz_(?:geo_|camadas_)?([A-Z]{2})\.tar\.gz", nome))
            }
            if ufs_pacotes - estados.keys():
                raise ValueError("Há pacote de UF ausente do manifesto; corrigir antes do corte.")
            for uf, info in sorted(estados.items()):
                if not isinstance(info, dict):
                    raise ValueError("Entrada estadual inválida no manifesto.")
                if f"raiz_{uf}.tar.gz" not in arm.arquivos and info.get("municipios", 0) != 0:
                    raise ValueError("Manifesto declara municípios mas o pacote completo está ausente.")
                arm.garantir_uf(uf)
                # O corte prepara apenas a projeção básica em disco, sem rede.
                # O catálogo descreve os bytes efetivamente publicados depois.
                arm._publicar_aberto(uf, info, catalogar=False)
        finally:
            arm.cli.close()
    indice = {
        "escopo": ESCOPO,
        "versao_publicacao": VERSAO_PUBLICACAO,
        "gerado_em": rel["gerado_em"],  # estável para retomada com os mesmos bytes
        "repo": rel["origem"],
        "tag": tag,
        "estados": coletor.estados,
    }
    coletor._subir({}, "estados.json", json.dumps(indice, ensure_ascii=False, indent=1).encode())
    return coletor.arquivos


def _verificar_publico(gh, repo, asset, arquivo, diretorio):
    m.verificar_asset(gh, repo, asset, m.sha256(arquivo), diretorio)
    validar_asset_publico(asset["name"], arquivo.read_bytes())


def _conferir_origem(gh, rel, tag, arquivos, diretorio, *, ausentes, cache):
    releases = [r for r in gh.json(f"repos/{rel['origem']}/releases", paginar=True) if not r["draft"]]
    if {r["id"]: r["tag_name"] for r in releases} != {r["id"]: r["tag"] for r in rel["releases"]}:
        raise ValueError("Lista de Releases públicos mudou; corte interrompido.")
    originais = {i["origem"]["id"]: i["origem"] for i in rel["assets"]}
    vivos = {}
    for release in releases:
        for asset in _assets(gh, rel["origem"], release["id"]).values():
            asset_id = asset["id"]
            if asset_id in originais:
                if m.fingerprint(asset) != originais[asset_id]:
                    raise ValueError("Asset original mudou após o inventário; corte interrompido.")
            else:
                arquivo = arquivos.get(asset["name"])
                if release["tag_name"] != tag or arquivo is None:
                    raise ValueError("Asset novo não previsto na projeção; corte interrompido.")
                marca = json.dumps(m.fingerprint(asset), sort_keys=True)
                if marca not in cache:
                    _verificar_publico(gh, rel["origem"], asset, arquivo, diretorio)
                    cache.add(marca)
            vivos[asset_id] = asset
    if set(originais) - vivos.keys() - ausentes:
        raise ValueError("Original desapareceu fora desta execução; use o inventário privado para retomar.")
    return vivos


def _preservacao(gh, rel, repo, tag, provas):
    release = m.destino_privado(gh, repo, tag, rel["origem"])
    remotos = _assets(gh, repo, release["id"])
    for prova in provas:
        for registro in prova["assets"]:
            backup = registro["backup"]
            if m.fingerprint(remotos.get(backup["name"], {})) != backup:
                raise ValueError("Backup verificado mudou ou desapareceu; remoção proibida.")


def _guardar_prova(gh, rel, repo, tag, diretorio, nome, prova):
    arquivo = diretorio / m.nome_seguro(nome)
    m.gravar_json(arquivo, prova)
    release = m.destino_privado(gh, repo, tag, rel["origem"])
    remoto = _assets(gh, repo, release["id"]).get(nome)
    if remoto is None:
        gh.subir(repo, tag, arquivo, nome)
        remoto = _assets(gh, repo, release["id"])[nome]
    m.verificar_asset(gh, repo, remoto, m.sha256(arquivo), diretorio)
    gh.conferir_anonimo(repo, remoto)
    return nome


def cortar(gh, rel, repo, tag, tag_publica, diretorio, *, executar=False, retomada=False):
    """Muta somente assets inventariados; novos públicos devem coincidir com a projeção."""
    diretorio.mkdir(parents=True, exist_ok=True)
    if (repo.lower(), tag) == (rel["origem"].lower(), tag_publica):
        raise ValueError("Destino privado deve ser separado do público.")
    arquivos = preparar(rel, tag_publica, diretorio)
    atuais = canonicos(rel, tag_publica)
    historicos = m.copiar(gh, rel, repo, tag, diretorio / "historicos", executar=executar)
    canon = m.copiar(gh, atuais, repo, tag, diretorio / "canonicos", executar=executar)
    inventario_portavel = {
        **rel,
        "assets": [{k: v for k, v in item.items() if k != "arquivo_local"} for item in rel["assets"]],
    }
    identidade = hashlib.sha256(json.dumps(inventario_portavel, sort_keys=True).encode()).hexdigest()[:16]
    nome_inventario = f"corte-{identidade}-inventario.json"
    resultado = {
        "executado": False,
        "origem": rel["origem"],
        "tag_publica": tag_publica,
        "destino": repo,
        "tag_privada": tag,
        "inventario_privado": nome_inventario,
        "originais": len(rel["assets"]),
        "projecoes": [{"nome": n, "sha256": m.sha256(p), "bytes": p.stat().st_size} for n, p in arquivos.items()],
        "removidos": [],
        "publicados": [],
    }
    m.gravar_json(diretorio / "plano-corte.json", resultado)
    if not executar:
        return resultado
    provas = [historicos["verificacao"], canon["verificacao"]]
    _guardar_prova(gh, rel, repo, tag, diretorio, nome_inventario, inventario_portavel)
    prova_backup = {"inventario": nome_inventario, "historicos": provas[0], "canonicos": provas[1]}
    hash_prova = hashlib.sha256(json.dumps(prova_backup, sort_keys=True).encode()).hexdigest()[:16]
    _guardar_prova(gh, rel, repo, tag, diretorio, f"corte-{identidade}-backup-{hash_prova}.json", prova_backup)
    ausentes = {i["origem"]["id"] for i in rel["assets"]} if retomada else set()
    cache: set[str] = set()
    hashes_projecao = {i["nome"]: i["sha256"] for i in resultado["projecoes"]}

    def conferir():
        if any(m.sha256(arquivo) != hashes_projecao[nome] for nome, arquivo in arquivos.items()):
            raise ValueError("Projeção local mudou depois da preparação; corte interrompido.")
        _preservacao(gh, rel, repo, tag, provas)
        return _conferir_origem(gh, rel, tag_publica, arquivos, diretorio, ausentes=ausentes, cache=cache)

    def apagar(asset):
        # Conferência integral e releitura individual imediatamente antes do DELETE.
        conferir()
        atual = gh.json(f"repos/{rel['origem']}/releases/assets/{asset['id']}")
        if m.fingerprint(atual) != m.fingerprint(asset):
            raise ValueError("Original mudou durante o corte; DELETE recusado.")
        gh.apagar(rel["origem"], asset["id"])
        ausentes.add(asset["id"])
        resultado["removidos"].append(asset["id"])
        m.gravar_json(diretorio / "corte-progresso.json", resultado)

    conferir()
    print(
        json.dumps({"fase": "backups_verificados", "inventario_privado": nome_inventario}, ensure_ascii=False),
        flush=True,
    )
    release_publica = next(r["id"] for r in rel["releases"] if r["tag"] == tag_publica)
    preservar = set()
    # Todos os pacotes primeiro; manifesto final só aponta para pacotes já verificados.
    for nome in sorted(arquivos, key=lambda n: (n == "estados.json", n)):
        conferir()
        arquivo = arquivos[nome]
        validar_asset_publico(nome, arquivo.read_bytes())
        existente = _assets(gh, rel["origem"], release_publica).get(nome)
        if existente is not None:
            original = next((i for i in rel["assets"] if i["origem"]["id"] == existente["id"]), None)
            if original and original["sha256"] != m.sha256(arquivo):
                apagar(existente)
                existente = None
            else:
                _verificar_publico(gh, rel["origem"], existente, arquivo, diretorio)
        if existente is None:
            conferir()
            gh.subir(rel["origem"], tag_publica, arquivo, nome)
            existente = _assets(gh, rel["origem"], release_publica)[nome]
            _verificar_publico(gh, rel["origem"], existente, arquivo, diretorio)
        preservar.add(existente["id"])
        resultado["publicados"].append(m.fingerprint(existente))
        m.gravar_json(diretorio / "corte-progresso.json", resultado)
    # Não chama migrar.remover: a origem agora inclui as projeções autorizadas.
    vivos = conferir()
    for item in rel["assets"]:
        asset = vivos.get(item["origem"]["id"])
        if asset is not None and asset["id"] not in preservar:
            apagar(asset)
    finais = conferir()
    if set(finais) != preservar:
        raise ValueError("A conferência final encontrou assets fora da projeção; revisar antes de concluir.")
    indisponiveis = []
    for item in rel["assets"]:
        nome = item["origem"]["name"]
        if item["tag"] == tag_publica and nome in arquivos:
            continue  # a mesma URL agora serve somente a projeção verificada
        url = (
            f"https://github.com/{rel['origem']}/releases/download/{quote(item['tag'], safe='')}/{quote(nome, safe='')}"
        )
        gh.conferir_anonimo(rel["origem"], {**item["origem"], "browser_download_url": url})
        indisponiveis.append(item["origem"]["id"])
    resultado["originais_com_404_anonimo"] = indisponiveis
    resultado.update(executado=True, concluido_em=m.agora())
    hash_resultado = hashlib.sha256(json.dumps(resultado, sort_keys=True).encode()).hexdigest()[:16]
    _guardar_prova(gh, rel, repo, tag, diretorio, f"corte-{identidade}-concluido-{hash_resultado}.json", resultado)
    m.gravar_json(diretorio / "corte-concluido.json", resultado)
    return resultado


def retomar(gh, repo, tag, origem, nome, diretorio):
    """Recupera o inventário e os bytes originais exclusivamente do backup privado."""
    match = re.fullmatch(r"corte-([a-f0-9]{16})-inventario\.json", nome)
    if not match:
        raise ValueError("Nome do inventário de retomada inválido.")
    release = m.destino_privado(gh, repo, tag, origem)
    remotos = _assets(gh, repo, release["id"])
    asset = remotos.get(nome)
    if asset is None:
        raise ValueError("Inventário de retomada ausente do privado.")
    arquivo = diretorio / nome
    gh.baixar(repo, asset["id"], arquivo)
    m.conferir_local(arquivo, asset)
    gh.conferir_anonimo(repo, asset)
    rel = m.ler_inventario(arquivo)
    identidade = hashlib.sha256(json.dumps(rel, sort_keys=True).encode()).hexdigest()[:16]
    if identidade != match.group(1):
        raise ValueError("Conteúdo do inventário não corresponde ao identificador de retomada.")
    if rel["origem"].lower() != origem.lower():
        raise ValueError("Inventário de retomada pertence a outra origem.")
    for item in rel["assets"]:
        backup = remotos.get(item["nome_backup"])
        if backup is None:
            raise ValueError("Backup histórico ausente; retomada recusada.")
        local = (
            diretorio
            / "assets"
            / str(int(item["release_id"]))
            / f"{int(item['origem']['id'])}-{m.nome_seguro(item['origem']['name'])}"
        )
        gh.baixar(repo, backup["id"], local)
        if m.conferir_local(local, backup) != item["sha256"]:
            raise ValueError("Backup histórico mudou; retomada recusada.")
        gh.conferir_anonimo(repo, backup)
        item["arquivo_local"] = str(local.resolve())
    return rel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origem", default="bernardoemmel/Raiz")
    parser.add_argument("--tag-publica", default="dados")
    parser.add_argument("--destino", required=True)
    parser.add_argument("--tag-privada", default="dados-privados")
    parser.add_argument("--diretorio", type=Path, default=Path("/tmp/raiz-corte"))
    parser.add_argument("--paralelos", type=int, default=4)
    parser.add_argument("--retomar", help="Nome do inventário guardado no Release privado na execução interrompida.")
    parser.add_argument("--executar", action="store_true", help="Efetiva cópias, publicação e remoções verificadas.")
    args = parser.parse_args()
    os.umask(0o077)
    # Recusa divergência entre o plano explícito e a configuração dos publicadores.
    arm = do_config()
    try:
        if not isinstance(arm, ArmazemRelease) or not arm.privado or arm.publico is None:
            parser.error("configure RAIZ_ARMAZEM_URL e RAIZ_DADOS_PRIVADOS_URL separados")
        if (arm.repo.lower(), arm.tag, arm.publico.repo.lower(), arm.publico.tag) != (
            args.destino.lower(),
            args.tag_privada,
            args.origem.lower(),
            args.tag_publica,
        ):
            parser.error("os destinos da configuração e dos argumentos precisam coincidir")
    finally:
        if isinstance(arm, ArmazemRelease):
            arm.cli.close()
            if arm.publico:
                arm.publico.cli.close()
    gh = m.GitHub()
    args.diretorio.mkdir(parents=True, exist_ok=True)
    rel = (
        retomar(gh, args.destino, args.tag_privada, args.origem, args.retomar, args.diretorio)
        if args.retomar
        else m.inventariar(gh, args.origem, args.diretorio, paralelos=args.paralelos)
    )
    resultado = cortar(
        gh,
        rel,
        args.destino,
        args.tag_privada,
        args.tag_publica,
        args.diretorio,
        executar=args.executar,
        retomada=bool(args.retomar),
    )
    print(json.dumps({k: resultado[k] for k in ("executado", "inventario_privado", "originais")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
