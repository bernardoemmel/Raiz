"""Armazenamento dos arquivos do motor: compatível com S3 (Cloudflare R2 em produção, SeaweedFS para hospedar) ou uma
pasta local (desenvolvimento e testes). Cada arquivo leva metadados: sha256, versão da tarefa que o gerou, data e
município. As credenciais vêm só de variáveis de ambiente (RAIZ_S3_*, ou AWS_* do padrão do boto3).

Chaves:
  saida/<UF>/<tipo>_<mun>.<ext>   arquivos do motor e do produto (o mesmo nome da pasta saida/ do motor)
  saida/<UF>/resumo_<UF>.csv      resumo do estado, refeito a cada rodada
  marcas/<UF>/<mun>.json          marca de concluído por município: versão, assinatura e saídas de cada tarefa
  estado/<UF>.json                andamento do estado (painel)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while bloco := f.read(1 << 20):
            h.update(bloco)
    return h.hexdigest()


class Armazem(Protocol):
    descricao: str

    def por(self, chave: str, arquivo: Path, meta: dict[str, str] | None = None) -> dict: ...
    def por_bytes(self, chave: str, dados: bytes, meta: dict[str, str] | None = None) -> dict: ...
    def baixar(self, chave: str, destino: Path) -> bool: ...
    def ler(self, chave: str) -> bytes | None: ...
    def meta(self, chave: str) -> dict | None: ...
    def listar(self, prefixo: str) -> list[str]: ...
    def apagar(self, chave: str) -> None: ...


def ler_json(a: Armazem, chave: str) -> dict | None:
    b = a.ler(chave)
    return json.loads(b) if b else None


def por_json(a: Armazem, chave: str, dado: dict) -> None:
    a.por_bytes(chave, json.dumps(dado, ensure_ascii=False, indent=1, default=str).encode("utf-8"),
                {"tipo": "json"})  # fmt: skip


class ArmazemLocal:
    """Pasta local com o mesmo leiaute das chaves; metadados num arquivo .meta.json ao lado."""

    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.descricao = f"pasta {self.raiz}"

    def _p(self, chave: str) -> Path:
        p = (self.raiz / chave).resolve()
        if self.raiz.resolve() not in p.parents and p != self.raiz.resolve():
            raise ValueError(f"chave fora do armazém: {chave}")
        return p

    def _gravar(self, chave: str, escrever, sha: str, tamanho: int, meta: dict | None) -> dict:
        p = self._p(chave)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        escrever(tmp)
        m = {**(meta or {}), "sha256": sha, "tamanho": str(tamanho)}
        mt = p.with_name(p.name + ".meta.json")
        mtmp = mt.with_name(mt.name + f".{os.getpid()}.tmp")
        mtmp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
        os.replace(mtmp, mt)
        return m

    def por(self, chave, arquivo, meta=None):
        import shutil

        arquivo = Path(arquivo)
        return self._gravar(chave, lambda t: shutil.copyfile(arquivo, t), sha256_arquivo(arquivo),
                            arquivo.stat().st_size, meta)  # fmt: skip

    def por_bytes(self, chave, dados, meta=None):
        return self._gravar(chave, lambda t: t.write_bytes(dados), sha256_bytes(dados), len(dados), meta)

    def baixar(self, chave, destino):
        import shutil

        p = self._p(chave)
        if not p.exists():
            return False
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + f".{os.getpid()}.tmp")
        shutil.copyfile(p, tmp)
        os.replace(tmp, destino)
        return True

    def ler(self, chave):
        p = self._p(chave)
        return p.read_bytes() if p.exists() else None

    def meta(self, chave):
        p = self._p(chave)
        mt = p.with_name(p.name + ".meta.json")
        if not p.exists():
            return None
        return json.loads(mt.read_text(encoding="utf-8")) if mt.exists() else {"tamanho": str(p.stat().st_size)}

    def listar(self, prefixo):
        base = self._p(prefixo) if prefixo else self.raiz
        alvo = base if base.is_dir() else base.parent
        if not alvo.exists():
            return []
        out = []
        for p in alvo.rglob("*"):
            if p.is_file() and not p.name.endswith((".meta.json", ".tmp")) and ".tmp" not in p.suffixes:
                k = str(p.relative_to(self.raiz)).replace(os.sep, "/")
                if k.startswith(prefixo):
                    out.append(k)
        return sorted(out)

    def apagar(self, chave):
        p = self._p(chave)
        for q in (p, p.with_name(p.name + ".meta.json")):
            q.unlink(missing_ok=True)


class ArmazemS3:
    """Balde compatível com S3 (Cloudflare R2, SeaweedFS, AWS). Metadados no próprio objeto (x-amz-meta-*)."""

    def __init__(self, balde: str, prefixo: str = "", endpoint: str | None = None, regiao: str = "auto",
                 chave: str | None = None, segredo: str | None = None, cliente=None):  # fmt: skip
        import boto3

        self.balde = balde
        self.prefixo = prefixo.strip("/") + "/" if prefixo.strip("/") else ""
        self.cli = cliente or boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            region_name=regiao or "auto",
            aws_access_key_id=chave,
            aws_secret_access_key=segredo,
        )
        self.descricao = f"s3://{balde}/{self.prefixo}" + (f" em {endpoint}" if endpoint else "")

    def _k(self, chave: str) -> str:
        return self.prefixo + chave

    @staticmethod
    def _meta_s3(meta: dict) -> dict[str, str]:
        # metadados S3 são ASCII: valores com acento vão em percent-encoding
        from urllib.parse import quote

        return {str(k).lower().replace("_", "-"): quote(str(v), safe=" ,.:;/+=@-_") for k, v in meta.items()}

    @staticmethod
    def _meta_py(meta: dict) -> dict[str, str]:
        from urllib.parse import unquote

        return {k.replace("-", "_"): unquote(v) for k, v in (meta or {}).items()}

    def por(self, chave, arquivo, meta=None):
        arquivo = Path(arquivo)
        m = {**(meta or {}), "sha256": sha256_arquivo(arquivo), "tamanho": str(arquivo.stat().st_size)}
        self.cli.upload_file(str(arquivo), self.balde, self._k(chave), ExtraArgs={"Metadata": self._meta_s3(m)})
        return m

    def por_bytes(self, chave, dados, meta=None):
        m = {**(meta or {}), "sha256": sha256_bytes(dados), "tamanho": str(len(dados))}
        self.cli.put_object(Bucket=self.balde, Key=self._k(chave), Body=dados, Metadata=self._meta_s3(m))
        return m

    def _nao_existe(self, e) -> bool:
        cod = str(getattr(e, "response", {}).get("Error", {}).get("Code", ""))
        return cod in ("404", "NoSuchKey", "NotFound")

    def baixar(self, chave, destino):
        from botocore.exceptions import ClientError

        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + f".{os.getpid()}.tmp")
        try:
            self.cli.download_file(self.balde, self._k(chave), str(tmp))
        except ClientError as e:
            if self._nao_existe(e):
                return False
            raise
        os.replace(tmp, destino)
        return True

    def ler(self, chave):
        from botocore.exceptions import ClientError

        try:
            return self.cli.get_object(Bucket=self.balde, Key=self._k(chave))["Body"].read()
        except ClientError as e:
            if self._nao_existe(e):
                return None
            raise

    def meta(self, chave):
        from botocore.exceptions import ClientError

        try:
            r = self.cli.head_object(Bucket=self.balde, Key=self._k(chave))
        except ClientError as e:
            if self._nao_existe(e):
                return None
            raise
        return self._meta_py(r.get("Metadata", {}))

    def listar(self, prefixo):
        out = []
        pag = self.cli.get_paginator("list_objects_v2")
        for p in pag.paginate(Bucket=self.balde, Prefix=self._k(prefixo)):
            out += [o["Key"][len(self.prefixo) :] for o in p.get("Contents", [])]
        return sorted(out)

    def apagar(self, chave):
        self.cli.delete_object(Bucket=self.balde, Key=self._k(chave))


def do_config(url: str | None = None) -> Armazem:
    """O armazém configurado: RAIZ_ARMAZEM_URL = s3://balde/prefixo (com RAIZ_S3_ENDPOINT para R2 ou SeaweedFS) ou
    uma pasta; sem nada, dados/armazem."""
    from raiz import RAIZ_REPO
    from raiz.config import config

    c = config()
    url = url or getattr(c, "armazem_url", None)
    if url and url.startswith("s3://"):
        resto = url[len("s3://") :]
        balde, _, prefixo = resto.partition("/")
        k = getattr(c, "s3_access_key_id", None)
        s = getattr(c, "s3_secret_access_key", None)
        return ArmazemS3(balde, prefixo, getattr(c, "s3_endpoint", None), getattr(c, "s3_regiao", "auto"),
                         k.get_secret_value() if k else None, s.get_secret_value() if s else None)  # fmt: skip
    if url and url.startswith("file://"):
        url = url[len("file://") :]
    return ArmazemLocal(Path(url) if url else RAIZ_REPO / "dados" / "armazem")
