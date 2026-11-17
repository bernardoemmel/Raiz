"""Copia os dados guardados em Releases do GitHub para o balde S3 privado, sem apagar nada do GitHub.

Destino (RAIZ_DADOS_PRIVADOS_URL=s3://balde/prefixo), com o mesmo nome de cada arquivo:

  dados-privados               -> s3://balde/prefixo/<nome>                      (arquivo completo vivo)
  dados-privados-checkpoints   -> s3://balde/prefixo-checkpoints/<nome>          (checkpoints dos jobs)
  historico-AAAA-MM-DD         -> s3://balde/prefixo/historico/UF/mun/hash.json.gz (um objeto por retrato)
  Releases públicos            -> s3://balde/releases-publicos/<tag>/<nome>       (cópia de segurança)

Fases repetíveis (retomam do ponto em que pararam; nada é sobrescrito com conteúdo diferente sem conferência):

  inventariar   lista todos os Releases (inclusive rascunhos) e grava o plano em --diretorio
  copiar        baixa cada asset pela API autenticada, confere SHA-256 e sobe; sem --executar só mostra o plano
  verificar     confere no balde tamanho e SHA-256 de cada arquivo e a presença de cada retrato

A remoção dos Releases NÃO é feita por este script: depende da decisão do fundador depois da validação
(docs/armazenamento.md, "Plano de migração").
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import httpx

API = "https://api.github.com"
HISTORICO = re.compile(r"historico-\d{4}-\d{2}-\d{2}")
PACOTE_HISTORICO = re.compile(r"historico_([A-Z]{2})_([a-f0-9]{64})\.tar\.gz")
NOME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}")


def _cabecalhos() -> dict:
    token = os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise PermissionError("sem token do GitHub para ler os Releases (inclusive rascunhos)")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _paginas(cli: httpx.Client, url: str) -> list[dict]:
    itens = []
    for pagina in range(1, 1000):
        r = cli.get(url, headers=_cabecalhos(), params={"per_page": 100, "page": pagina})
        r.raise_for_status()
        lote = r.json()
        itens += lote
        if len(lote) < 100:
            return itens
    raise RuntimeError("paginação excedida")


def destino(tag: str, nome: str, prefixo: str) -> dict:
    """Para onde vai cada asset. `prefixo` é o prefixo vivo do arquivo privado (ex.: 'dados')."""
    if not NOME.fullmatch(nome):
        raise ValueError(f"nome de asset inesperado: {nome!r}")
    if tag == "dados-privados":
        return {"tipo": "arquivo", "chave": f"{prefixo}/{nome}"}
    if tag == "dados-privados-checkpoints":
        return {"tipo": "arquivo", "chave": f"{prefixo}-checkpoints/{nome}"}
    if HISTORICO.fullmatch(tag):
        if not PACOTE_HISTORICO.fullmatch(nome):
            return {"tipo": "arquivo", "chave": f"releases-privados/{tag}/{nome}"}
        return {"tipo": "historico", "chave": f"{prefixo}/historico/"}
    return {"tipo": "arquivo", "chave": f"releases-publicos/{tag}/{nome}"}


def inventariar(repo: str, prefixo: str, pasta: Path) -> dict:
    with httpx.Client(timeout=120, follow_redirects=True) as cli:
        releases = _paginas(cli, f"{API}/repos/{repo}/releases")
        plano = {"repo": repo, "prefixo": prefixo, "releases": []}
        for rel in releases:
            assets = _paginas(cli, f"{API}/repos/{repo}/releases/{rel['id']}/assets")
            plano["releases"].append({
                "id": rel["id"],
                "tag": rel["tag_name"],
                "rascunho": bool(rel.get("draft")),
                "assets": [
                    {"id": a["id"], "nome": a["name"], "tamanho": a["size"], "digest": a.get("digest") or "",
                     "atualizado_em": a.get("updated_at", ""), **destino(rel["tag_name"], a["name"], prefixo)}
                    for a in assets
                ],
            })  # fmt: skip
    total = sum(a["tamanho"] for r in plano["releases"] for a in r["assets"])
    plano["total_bytes"] = total
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "plano-balde.json").write_text(json.dumps(plano, ensure_ascii=False, indent=1))
    for r in plano["releases"]:
        soma = sum(a["tamanho"] for a in r["assets"])
        print(f"{r['tag']:32} {'rascunho' if r['rascunho'] else 'PÚBLICO ':8} {len(r['assets']):5} arquivos "
              f"{soma / 1e9:8.2f} GB")  # fmt: skip
    print(f"total: {total / 1e9:.2f} GB")
    return plano


def _sha_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


def _cliente_balde():
    from raiz.executor.armazem_balde import _cliente_s3_config, partes_s3

    url = os.environ.get("RAIZ_DADOS_PRIVADOS_URL", "").strip()
    balde, prefixo = partes_s3(url)
    import boto3

    endpoint, regiao, chave, segredo = _cliente_s3_config()
    s3 = boto3.client("s3", endpoint_url=endpoint, region_name=regiao, aws_access_key_id=chave,
                      aws_secret_access_key=segredo)  # fmt: skip
    return s3, balde, prefixo


def _sha_no_balde(s3, balde: str, chave: str) -> tuple[str, int] | None:
    from botocore.exceptions import ClientError

    try:
        r = s3.head_object(Bucket=balde, Key=chave)
    except ClientError as ex:
        if str(ex.response.get("Error", {}).get("Code")) in ("404", "NoSuchKey", "NotFound"):
            return None
        raise
    return (r.get("Metadata") or {}).get("sha256", ""), int(r.get("ContentLength", -1))


def _baixar(cli: httpx.Client, repo: str, asset: dict, destino_local: Path) -> str:
    h = hashlib.sha256()
    with cli.stream("GET", f"{API}/repos/{repo}/releases/assets/{asset['id']}",
                    headers={**_cabecalhos(), "Accept": "application/octet-stream"}) as r:  # fmt: skip
        r.raise_for_status()
        with destino_local.open("wb") as f:
            for bloco in r.iter_bytes(1 << 20):
                h.update(bloco)
                f.write(bloco)
    if destino_local.stat().st_size != asset["tamanho"]:
        raise ValueError(f"{asset['nome']}: tamanho divergente no download")
    sha = h.hexdigest()
    if asset.get("digest", "").startswith("sha256:") and asset["digest"] != f"sha256:{sha}":
        raise ValueError(f"{asset['nome']}: SHA-256 diverge do informado pelo GitHub")
    return sha


def _copiar_arquivo(s3, balde, cli, repo, asset, executar: bool) -> str:
    atual = _sha_no_balde(s3, balde, asset["chave"])
    esperado = asset["digest"].removeprefix("sha256:") if asset["digest"].startswith("sha256:") else None
    if atual and atual[1] == asset["tamanho"] and (esperado is None or atual[0] == esperado) and atual[0]:
        return "ja-copiado"
    if not executar:
        return "copiaria"
    with tempfile.TemporaryDirectory(prefix="raiz-balde-") as td:
        local = Path(td) / "asset"
        sha = _baixar(cli, repo, asset, local)
        if atual and atual[0] and atual[0] != sha:
            # O asset mudou no Release desde a última cópia (arquivo vivo): a cópia mais nova prevalece.
            print(f"  {asset['nome']}: conteúdo novo no Release; atualizando a cópia", flush=True)
        s3.upload_file(str(local), balde, asset["chave"],
                       ExtraArgs={"Metadata": {"sha256": sha, "tamanho": str(asset["tamanho"]),
                                               "origem": f"release:{asset['id']}"}})  # fmt: skip
    conferido = _sha_no_balde(s3, balde, asset["chave"])
    if not conferido or conferido != (sha, asset["tamanho"]):
        raise RuntimeError(f"{asset['nome']}: conferência após upload falhou")
    return "copiado"


def _marca(tag: str, asset: dict) -> str:
    """Recibo de pacote histórico expandido, fora de historico/ (lá só pode haver retratos)."""
    return f"migracao/historico/{tag}/{asset['nome']}.ok"


def _copiar_historico(s3, balde, cli, repo, asset, executar: bool, tag: str) -> str:
    from botocore.exceptions import ClientError

    from raiz.aprendizado.transporte import _abrir_pacote, _validar_bytes

    marca = _marca(tag, asset)
    if _sha_no_balde(s3, balde, marca):
        return "ja-copiado"
    if not executar:
        return "copiaria"
    uf = PACOTE_HISTORICO.fullmatch(asset["nome"])[1]
    with tempfile.TemporaryDirectory(prefix="raiz-balde-") as td:
        local = Path(td) / "pacote"
        _baixar(cli, repo, asset, local)
        membros = _abrir_pacote(local.read_bytes(), uf)
    novos = 0
    for relativo, dados in sorted(membros.items()):
        _validar_bytes(dados, relativo)  # o nome do retrato é o próprio hash: o conteúdo se confere sozinho
        sha = hashlib.sha256(dados).hexdigest()
        try:
            s3.put_object(Bucket=balde, Key=asset["chave"] + relativo, Body=dados, IfNoneMatch="*",
                          Metadata={"sha256": sha, "retrato-sha256": relativo.split("/")[-1][:64]})  # fmt: skip
            novos += 1
        except ClientError as ex:
            if str(ex.response.get("Error", {}).get("Code")) not in {"PreconditionFailed", "412"}:
                raise
            if _sha_no_balde(s3, balde, asset["chave"] + relativo)[0] not in ("", sha):
                raise RuntimeError(f"retrato {relativo} já existe no balde com outro conteúdo") from None
    corpo = json.dumps({"membros": sorted(membros), "novos": novos}).encode()
    s3.put_object(Bucket=balde, Key=marca, Body=corpo, Metadata={"sha256": hashlib.sha256(corpo).hexdigest()})
    return "copiado"


def _selecionado(tag: str, grupos: set[str]) -> bool:
    if not grupos:
        return True
    grupo = "historico" if HISTORICO.fullmatch(tag) else tag
    if tag not in {"dados-privados", "dados-privados-checkpoints"} and not HISTORICO.fullmatch(tag):
        grupo = "publicos"
    return grupo in grupos


def copiar(pasta: Path, executar: bool, grupos: set[str]) -> dict:
    plano = json.loads((pasta / "plano-balde.json").read_text())
    s3, balde, _ = _cliente_balde()
    contagem: dict[str, int] = {}
    with httpx.Client(timeout=900, follow_redirects=True) as cli:
        for rel in plano["releases"]:
            if not _selecionado(rel["tag"], grupos):
                continue
            for asset in rel["assets"]:
                if asset["tipo"] == "historico":
                    resultado = _copiar_historico(s3, balde, cli, plano["repo"], asset, executar, rel["tag"])
                else:
                    resultado = _copiar_arquivo(s3, balde, cli, plano["repo"], asset, executar)
                contagem[resultado] = contagem.get(resultado, 0) + 1
                if resultado == "copiado":
                    print(f"{rel['tag']}/{asset['nome']}: copiado", flush=True)
    print(json.dumps(contagem))
    return contagem


def verificar(pasta: Path, grupos: set[str]) -> dict:
    plano = json.loads((pasta / "plano-balde.json").read_text())
    s3, balde, _ = _cliente_balde()
    faltando, conferidos = [], 0
    for rel in plano["releases"]:
        if not _selecionado(rel["tag"], grupos):
            continue
        for asset in rel["assets"]:
            if asset["tipo"] == "historico":
                if not _sha_no_balde(s3, balde, _marca(rel["tag"], asset)):
                    faltando.append(f"{rel['tag']}/{asset['nome']}")
                    continue
                corpo = json.loads(s3.get_object(Bucket=balde, Key=_marca(rel["tag"], asset))["Body"].read())
                ausentes = [m for m in corpo["membros"] if not _sha_no_balde(s3, balde, asset["chave"] + m)]
                if ausentes:
                    faltando.append(f"{rel['tag']}/{asset['nome']} ({len(ausentes)} retratos)")
                    continue
            else:
                atual = _sha_no_balde(s3, balde, asset["chave"])
                esperado = asset["digest"].removeprefix("sha256:") if asset["digest"] else None
                if not atual or atual[1] != asset["tamanho"] or (esperado and atual[0] != esperado):
                    faltando.append(f"{rel['tag']}/{asset['nome']}")
                    continue
            conferidos += 1
    resultado = {"conferidos": conferidos, "faltando": faltando}
    (pasta / "verificado-balde.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1))
    corpo = json.dumps(resultado, ensure_ascii=False).encode()
    sufixo = "-".join(sorted(grupos)) or "todos"
    s3.put_object(Bucket=balde, Key=f"migracao/verificado-{sufixo}.json", Body=corpo,
                  Metadata={"sha256": hashlib.sha256(corpo).hexdigest()})  # fmt: skip
    print(f"conferidos: {conferidos}; faltando: {len(faltando)}")
    for f in faltando[:50]:
        print("  falta:", f)
    return resultado


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("fase", choices=("inventariar", "copiar", "verificar"))
    p.add_argument("--origem", default=os.environ.get("GITHUB_REPOSITORY", "bernardoemmel/Raiz"))
    p.add_argument("--diretorio", type=Path, default=Path(tempfile.gettempdir()) / "raiz-balde")
    p.add_argument("--grupo", action="append", default=[],
                   choices=("dados-privados", "dados-privados-checkpoints", "historico", "publicos"))  # fmt: skip
    p.add_argument("--executar", action="store_true", help="sem isso, copiar só mostra o que faria")
    a = p.parse_args(argv)
    if a.fase == "inventariar":
        from raiz.executor.armazem_balde import partes_s3

        _, prefixo = partes_s3(os.environ.get("RAIZ_DADOS_PRIVADOS_URL", "").strip())
        if not prefixo:
            raise ValueError("RAIZ_DADOS_PRIVADOS_URL precisa de prefixo (ex.: s3://raiz-privado/dados)")
        inventariar(a.origem, prefixo, a.diretorio)
    elif a.fase == "copiar":
        copiar(a.diretorio, a.executar, set(a.grupo))
    else:
        return 1 if verificar(a.diretorio, set(a.grupo))["faltando"] else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
