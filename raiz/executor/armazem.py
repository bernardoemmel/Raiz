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

import contextlib
import contextvars
import hashlib
import json
import logging
import os
import random
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


_REDE_PRIVADA = contextvars.ContextVar("raiz_rede_privada", default=False)


class _SemLogsDeRedePrivada(logging.Filter):
    def filter(self, record) -> bool:
        # HTTPX registra a URL final assinada em INFO; httpcore pode registrar headers em DEBUG.
        return not _REDE_PRIVADA.get()


for _logger_http in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"):
    logging.getLogger(_logger_http).addFilter(_SemLogsDeRedePrivada())


def _erro_http_privado(operacao: str):
    def decorar(funcao):
        @wraps(funcao)
        def executar(self, *args, **kwargs):
            with self._erros_privados(operacao):
                return funcao(self, *args, **kwargs)

        return executar

    return decorar


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
        if destino.resolve() == p:  # o espelho é o próprio destino (Release lido para o espelho local)
            return True
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


PADRAO = "release-github://bernardoemmel/raiz/dados"


def destino_privado() -> tuple[str, str] | None:
    """Destino completo por variável; nunca deriva um destino privado do Release aberto."""
    url = os.environ.get("RAIZ_DADOS_PRIVADOS_URL", "").strip()
    repo = os.environ.get("RAIZ_DADOS_PRIVADOS_REPO", "").strip()
    tag = os.environ.get("RAIZ_DADOS_PRIVADOS_TAG", "dados").strip()
    if url:
        if not url.startswith("release-github://"):
            raise ValueError("RAIZ_DADOS_PRIVADOS_URL deve usar release-github://dono/repositorio/tag")
        partes = url.removeprefix("release-github://").strip("/").split("/")
        if len(partes) not in (2, 3) or not all(partes):
            raise ValueError("destino privado inválido")
        repo, tag = "/".join(partes[:2]), partes[2] if len(partes) == 3 else tag
    if not repo:
        return None
    import re

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
        raise ValueError("repositório ou tag privados inválidos")
    return repo, tag


def do_config(url: str | None = None) -> Armazem:
    """O armazém configurado em RAIZ_ARMAZEM_URL:
    release-github://dono/repo/tag   o Release do GitHub (padrão: o Release "dados" deste repositório);
    s3://balde/prefixo               compatível com S3 (opção futura: Cloudflare R2; ou SeaweedFS);
    uma pasta                        local (desenvolvimento e testes)."""
    from raiz import RAIZ_REPO
    from raiz.config import config

    c = config()
    url = url or getattr(c, "armazem_url", None) or PADRAO
    if url.startswith("release-github://"):
        dono, repo, *resto = url[len("release-github://") :].strip("/").split("/")
        aberto = ArmazemRelease(f"{dono}/{repo}", resto[0] if resto else "dados")
        privado = destino_privado()
        if privado:
            if privado[0].lower() == aberto.repo.lower() and privado[1] == aberto.tag:
                raise ValueError("o Release privado deve ser separado do aberto")
            return ArmazemRelease(
                *privado, token=os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN", ""), privado=True, publico=aberto
            )
        return aberto  # sem configuração privada, leitura básica; publicar detalhamento é proibido
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


# --- Release do GitHub (armazém de produção agora) ---------------------------------------------------------------

TOTAL_IBGE = {
    "AC": 22, "AL": 102, "AP": 16, "AM": 62, "BA": 417, "CE": 184, "DF": 1, "ES": 78, "GO": 246, "MA": 217, "MT": 142,
    "MS": 79, "MG": 853, "PA": 144, "PB": 223, "PR": 399, "PE": 185, "PI": 224, "RJ": 92, "RN": 167, "RS": 497,
    "RO": 52, "RR": 15, "SC": 295, "SP": 645, "SE": 75, "TO": 139,
}  # fmt: skip  # o mesmo de motor/publicar_dados.py
TABELAS = ["imoveis", "direto", "filtros", "extras", "extras_direto", "mapbiomas", "certidoes"]
TABELAS_TODAS = [*TABELAS, "flag", "terra", "ficha", "desenvolvedor"]
PROIBIDAS = r"(^|_)(cpf|cnpj|nome|proprietario|titular|email|telefone)($|_)"  # a mesma conferência do publicar_dados


class ArmazemRelease:
    """Arquivo completo autenticado e projeção básica pública, sempre separados.

    Formato reservado ao arquivo privado (repositório privado ou Release em rascunho):

      raiz_<UF>.tar.gz          todos os CSV do estado, em <UF>/, mais <UF>/_versoes.json (tarefa, versão, data,
                                município e sha256 de cada arquivo)
      raiz_geo_<UF>.tar.gz      geo_<mun>.parquet
      raiz_camadas_<UF>.tar.gz  camadas_<mun>.parquet e .pmtiles (camadas dentro do imóvel)
      raiz_controle_<UF>.json   marcas de concluído por município e o estado do processamento (retomada)
      raiz_controle.json        o que não é de um estado (coleção do MapBiomas da última rodada completa)
      estados.json              manifesto (por último), com versão do motor e de cada tarefa por estado

    Trabalha sobre um espelho local (ArmazemLocal): ler um estado baixa os pacotes dele uma vez; gravar fica no
    espelho, e `publicar(uf)` confirma os originais privados antes de projetar a saída aberta.
    O privado exige token e verificação da visibilidade em cada acesso remoto. Sem destino privado,
    apenas os arquivos básicos validados podem ser lidos; publicação completa falha fechada."""

    API = "https://api.github.com"
    UPLOADS = "https://uploads.github.com"

    def __init__(self, repo: str = "bernardoemmel/raiz", tag: str = "dados", espelho: Path | None = None,
                 token: str | None = None, cliente=None, intervalo_s: float | None = None,
                 a_cada: int = 20, *, privado: bool = False,
                 publico: ArmazemRelease | None = None):  # fmt: skip
        import httpx

        self.repo, self.tag = repo, tag
        self.privado, self.publico = privado, publico
        raiz_espelho = espelho or _espelho_padrao()
        if privado and espelho is None:
            raiz_espelho = raiz_espelho.with_name(raiz_espelho.name + "_privado")
        self.local = ArmazemLocal(espelho or raiz_espelho)
        self.token = token if token is not None else (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
        self.cli = cliente or httpx.Client(timeout=300, follow_redirects=True,
                                            headers={"User-Agent": "raiz-executor"})  # fmt: skip
        self.descricao = f"Release {tag} de {repo}"
        # de quanto em quanto tempo publica no meio da rodada (RAIZ_PUBLICAR_MIN; fatias de estado grande: 60)
        if intervalo_s is None:
            intervalo_s = float(os.environ.get("RAIZ_PUBLICAR_MIN", 15)) * 60
        self.intervalo_s, self.a_cada = intervalo_s, a_cada
        self._ufs: set[str] = set()
        self._travas: set[str] = set()
        self._global = False
        self._sujos: dict[str, int] = {}
        self._ultima: dict[str, float] = {}
        self._quantis: dict[str, dict] = {}

    @contextlib.contextmanager
    def _erros_privados(self, operacao: str):
        """Não deixa URL assinada, token, headers ou corpo chegarem aos logs do Actions."""
        import httpx

        if not self.privado:
            yield
            return
        marca = _REDE_PRIVADA.set(True)
        try:
            yield
        except httpx.HTTPStatusError as ex:
            raise RuntimeError(f"falha HTTP {ex.response.status_code} no arquivo privado ({operacao})") from None
        except httpx.HTTPError:
            raise RuntimeError(f"falha de comunicação com o arquivo privado ({operacao})") from None
        finally:
            _REDE_PRIVADA.reset(marca)

    # --- leitura -------------------------------------------------------------------------------------------------

    def url(self, nome: str) -> str:
        return f"https://github.com/{self.repo}/releases/download/{self.tag}/{nome}"

    def url_metadados(self, nome: str) -> str:
        """URI lógica privada: o leitor autorizado resolve o nome pela API, sem URL assinada."""
        if self.privado:
            return f"release-github://{self.repo}/{self.tag}/{nome}"
        return self.url(nome)

    @property
    def escopo_metadados(self) -> str:
        return "privado" if self.privado else "publico_basico"

    @property
    def repo_codigo(self) -> str:
        return os.environ.get("GITHUB_REPOSITORY", "bernardoemmel/Raiz")

    @_erro_http_privado("leitura")
    def _baixar_asset(self, nome: str, fresco: bool = False) -> bytes | None:
        if self.privado:
            rel = self._exigir_privado()
            for ativo in self._assets(rel):
                if ativo.get("name") == nome:
                    return self._baixar_ativo(ativo)
            return None
        r = self.cli.get(self.url(nome), params={"t": str(time.time_ns())} if fresco else None)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        from raiz.executor.publicacao_aberta import validar_asset_publico

        validar_asset_publico(nome, r.content, repo=self.repo, tag=self.tag)
        return r.content

    @_erro_http_privado("listar arquivos")
    def _assets(self, rel: dict | None = None) -> list[dict]:
        """Lista todas as páginas, inclusive snapshots e checkpoints no arquivo privado."""
        rel = rel or self._release()
        ativos, nomes = [], set()
        for pagina in range(1, 1001):
            r = self.cli.get(
                f"{self.API}/repos/{self.repo}/releases/{rel['id']}/assets",
                headers=self._cabecalhos(),
                params={"per_page": 100, "page": pagina},
            )
            r.raise_for_status()
            itens = r.json()
            if not isinstance(itens, list):
                raise RuntimeError("resposta inválida ao listar os arquivos do Release")
            for ativo in itens:
                if ativo["name"] in nomes:
                    raise RuntimeError("arquivos mudaram durante a paginação do Release; tente novamente")
                nomes.add(ativo["name"])
                ativos.append(ativo)
            if len(itens) < 100:
                return ativos
        raise RuntimeError("Release excedeu a paginação de assets")

    @_erro_http_privado("download")
    def _baixar_ativo(self, ativo: dict) -> bytes:
        """Baixa o ID congelado pela API autenticada; não segue browser_download_url."""
        self._exigir_privado()
        r = self.cli.get(
            f"{self.API}/repos/{self.repo}/releases/assets/{int(ativo['id'])}",
            headers={**self._cabecalhos(), "Accept": "application/octet-stream"},
        )
        r.raise_for_status()
        if ativo.get("size") is not None and len(r.content) != ativo["size"]:
            raise ValueError("tamanho divergente no download do asset privado")
        return r.content

    def manifesto(self, fresco: bool = False) -> dict:
        b = self._baixar_asset("estados.json", fresco=fresco)
        return json.loads(b) if b else {"repo": self.repo, "tag": self.tag, "estados": {}}

    @_erro_http_privado("verificar acesso")
    def _exigir_privado(self) -> dict:
        if not self.privado:
            raise PermissionError("dados completos exigem RAIZ_DADOS_PRIVADOS_URL e RAIZ_DADOS_PRIVADOS_TOKEN")
        r = self.cli.get(f"{self.API}/repos/{self.repo}", headers=self._cabecalhos())
        r.raise_for_status()
        rel = self._release(listar_assets=False)
        if r.json().get("private") is not True and rel.get("draft") is not True:
            raise PermissionError("dados completos exigem repositório privado ou Release em rascunho não publicado")
        return rel

    def verificar_publicacao(self) -> None:
        """Pré-requisito da rodada: falha antes de processar se o arquivo privado não está disponível."""
        self._exigir_privado()
        self._release()
        if self.publico:
            self.publico._cabecalhos()
            self.publico._release()

    @staticmethod
    def _uf_da_chave(chave: str) -> str | None:
        partes = chave.split("/")
        if len(partes) >= 2 and partes[0] in ("saida", "marcas") and len(partes[1]) == 2:
            return partes[1].upper()
        if len(partes) == 2 and partes[0] == "estado" and partes[1][:2].isalpha() and partes[1][2:] == ".json":
            return partes[1][:2].upper()
        return None

    def garantir(self, chave: str) -> None:
        uf = self._uf_da_chave(chave)
        if uf:
            self.garantir_uf(uf)
        elif not self._global and self.privado:
            self._global = True
            b = self._baixar_asset("raiz_controle.json")
            for k, v in (json.loads(b) if b else {}).items():
                if not self.local.meta(k):
                    self.local.por_bytes(k, json.dumps(v, ensure_ascii=False).encode("utf-8"), {"tipo": "json"})

    def garantir_uf(self, uf: str, forcar: bool = False) -> None:
        """Baixa os pacotes do estado para o espelho (uma vez por sessão, ou de novo com forcar). O que esta máquina
        gravou e ainda não publicou fica; o resto vem do Release (ex.: municípios de outra fatia do mesmo estado, que
        roda em outro job). Lê dentro da trava do estado, para não pegar pacote no meio da publicação de outro job."""
        uf = uf.upper()
        if uf in self._ufs and not forcar:
            return
        trava = self._trava(f"trava-publicar-{uf}", 1800) if self.token else contextlib.nullcontext()
        with trava:
            self._baixar_uf(uf)
        self._ufs.add(uf)

    def _baixar_uf(self, uf: str) -> None:
        import io
        import tarfile

        nomes = (f"raiz_{uf}.tar.gz", f"raiz_geo_{uf}.tar.gz")
        if self.privado:
            nomes += (f"raiz_camadas_{uf}.tar.gz",)
        for nome in nomes:
            b = self._baixar_asset(nome)
            if not b:
                continue
            with tarfile.open(fileobj=io.BytesIO(b), mode="r:gz") as tar:
                membros = {m.name: m for m in tar.getmembers() if m.isfile()}
                vers = {}
                if f"{uf}/_versoes.json" in membros:
                    vers = json.loads(tar.extractfile(membros.pop(f"{uf}/_versoes.json")).read())
                for nome_m, m in membros.items():
                    arq = Path(nome_m).name
                    if "/" in arq or arq.startswith(".") or Path(nome_m).parent.name != uf:
                        continue  # só arquivos diretos da pasta do estado (nada de caminho estranho no pacote)
                    chave = f"saida/{uf}/{arq}"
                    dados = tar.extractfile(m).read()
                    atual = self.local.meta(chave)
                    if atual and atual.get("gravado_aqui") == "sim":
                        continue  # o que esta máquina gravou e ainda não publicou fica (a marca local fica também)
                    meta = {k: str(v) for k, v in (vers.get(arq) or {"versao": "publicado"}).items() if k != "sha256"}
                    if (
                        atual
                        and atual.get("sha256") == sha256_bytes(dados)
                        and all(atual.get(k) == v for k, v in meta.items())
                        and set(atual) - {"sha256", "tamanho"} == set(meta)
                    ):
                        continue
                    # CSV idêntico pode vir de outra execução/versão. Seus metadados
                    # também são dados: jamais conservar a data anterior por comparar só bytes.
                    self.local.por_bytes(chave, dados, meta)
        b = self._baixar_asset(f"raiz_controle_{uf}.json") if self.privado else None
        if b:
            ctl = json.loads(b)
            for cod, marca in (ctl.get("marcas") or {}).items():
                k = f"marcas/{uf}/{int(cod)}.json"
                dados = json.dumps(marca, ensure_ascii=False).encode("utf-8")
                atual = self.local.meta(k)
                if atual and (atual.get("gravado_aqui") == "sim" or atual.get("sha256") == sha256_bytes(dados)):
                    continue  # a marca que esta máquina gravou fica (e só ela sabe das saídas que gravou)
                self.local.por_bytes(k, dados, {"tipo": "json"})
            if ctl.get("estado") and not self.local.meta(f"estado/{uf}.json"):
                self.local.por_bytes(f"estado/{uf}.json", json.dumps(ctl["estado"], ensure_ascii=False).encode("utf-8"))

    def ler(self, chave):
        self.garantir(chave)
        return self.local.ler(chave)

    def meta(self, chave):
        self.garantir(chave)
        return self.local.meta(chave)

    def baixar(self, chave, destino):
        self.garantir(chave)
        return self.local.baixar(chave, destino)

    def listar(self, prefixo):
        uf = self._uf_da_chave(prefixo if prefixo.count("/") >= 2 else prefixo.rstrip("/") + "/x")
        if uf:
            self.garantir_uf(uf)
        elif prefixo.rstrip("/") in ("saida", "marcas", ""):
            for u in self.manifesto().get("estados", {}):
                self.garantir_uf(u)
        return self.local.listar(prefixo)

    # --- escrita -------------------------------------------------------------------------------------------------

    def _anota(self, chave: str) -> None:
        uf = self._uf_da_chave(chave)
        if uf:
            self._sujos[uf] = self._sujos.get(uf, 0) + 1
        else:
            self._sujos["_global"] = self._sujos.get("_global", 0) + 1

    def por(self, chave, arquivo, meta=None):
        self.garantir(chave)
        m = self.local.por(chave, arquivo, {**(meta or {}), "gravado_aqui": "sim"})
        self._anota(chave)
        return m

    def por_bytes(self, chave, dados, meta=None):
        self.garantir(chave)
        m = self.local.por_bytes(chave, dados, {**(meta or {}), "gravado_aqui": "sim"})
        self._anota(chave)
        return m

    def apagar(self, chave):
        self.local.apagar(chave)
        self._anota(chave)

    @_erro_http_privado("consultar Release")
    def _release(self, *, listar_assets: bool = True) -> dict:
        h = self._cabecalhos()
        r = self.cli.get(f"{self.API}/repos/{self.repo}/releases/tags/{self.tag}", headers=h)
        if r.status_code == 404 and self.privado:
            # Rascunhos podem não ter referência de tag publicada; continuam listados para o token autorizado.
            for pagina in range(1, 100):
                pagina_r = self.cli.get(
                    f"{self.API}/repos/{self.repo}/releases", headers=h, params={"per_page": 100, "page": pagina}
                )
                pagina_r.raise_for_status()
                releases = pagina_r.json()
                for release in releases:
                    if release.get("tag_name") == self.tag:
                        if listar_assets:
                            release["assets"] = self._assets(release)
                        return release
                if len(releases) < 100:
                    break
        r.raise_for_status()
        rel = r.json()
        if listar_assets:
            rel["assets"] = self._assets(rel)
        return rel

    def _cabecalhos(self) -> dict:
        if not self.token:
            raise PermissionError(
                "sem token do GitHub (GH_TOKEN ou GITHUB_TOKEN): o Release só é gravado de dentro do GitHub Actions"
            )
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    @_erro_http_privado("upload")
    def _subir(self, rel: dict, nome: str, dados: bytes, tipo: str = "application/octet-stream") -> None:
        if self.privado:
            verificado = self._exigir_privado()
            if rel.get("id") != verificado.get("id"):
                raise PermissionError("upload deve usar somente o Release privado configurado")
        else:
            from raiz.executor.publicacao_aberta import validar_asset_publico

            validar_asset_publico(nome, dados, repo=self.repo, tag=self.tag)
        h = self._cabecalhos()
        for a in self._assets(rel):
            if a["name"] == nome:  # o Release não troca asset: apaga e sobe de novo
                self.cli.delete(f"{self.API}/repos/{self.repo}/releases/assets/{a['id']}", headers=h).raise_for_status()
        r = self.cli.post(f"{self.UPLOADS}/repos/{self.repo}/releases/{rel['id']}/assets", params={"name": nome},
                          headers={**h, "Content-Type": tipo}, content=dados)  # fmt: skip
        r.raise_for_status()
        from raiz.atestacao import registrar

        registrar(nome, dados, privado=self.privado)

    def _publicar_auxiliar(self, rel: dict, nome: str, dados: bytes, tipo: str) -> dict:
        """Publica artefato global e ficha; o chamador deve manter a trava do índice."""
        from raiz.metadados import ficha_arquivo, validar

        self._exigir_privado()
        digest = sha256_bytes(dados)
        ficha = ficha_arquivo(
            nome, self.url_metadados(nome), digest, len(dados), formato=tipo, repo=self.repo_codigo, escopo="privado"
        )
        validar(ficha)
        dados_ficha = json.dumps(ficha, ensure_ascii=False, indent=2).encode()
        nome_ficha = f"croissant_{nome}.json"
        assets = {a["name"]: a for a in rel.get("assets", [])}
        for arquivo, conteudo, mime in ((nome, dados, tipo), (nome_ficha, dados_ficha, "application/ld+json")):
            if assets.get(arquivo, {}).get("digest") != "sha256:" + sha256_bytes(conteudo):
                self._subir(rel, arquivo, conteudo, mime)
        return {"url": self.url_metadados(nome_ficha), "sha256": sha256_bytes(dados_ficha), "arquivo_sha256": digest}

    @staticmethod
    def _tar(uf: str, arquivos: dict[str, bytes]) -> bytes:
        import gzip
        import io
        import tarfile

        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6, mtime=0) as comprimido:
            with tarfile.open(fileobj=comprimido, mode="w") as tar:
                for nome in sorted(arquivos):
                    info = tarfile.TarInfo(f"{uf}/{nome}")
                    info.size, info.mtime = len(arquivos[nome]), 0
                    tar.addfile(info, io.BytesIO(arquivos[nome]))
        return buf.getvalue()

    def talvez_publicar(self, uf: str) -> bool:
        """Publica de tempos em tempos durante a rodada (para a retomada em outra máquina não perder muito)."""
        import time

        uf = uf.upper()
        n = self._sujos.get(uf, 0)
        if not n or not self.token:
            return False
        if n >= self.a_cada * 4 or time.time() - self._ultima.get(uf, 0) >= self.intervalo_s:
            self.publicar(uf)
            return True
        return False

    TRAVA = "trava-publicar-dados"  # a mesma de motor/publicar_dados.py

    @contextlib.contextmanager
    def _trava(self, nome: str | None = None, velha_s: float = 600):
        with self._erros_privados("trava"):
            with self._trava_impl(nome, velha_s):
                yield

    @contextlib.contextmanager
    def _trava_impl(self, nome: str | None = None, velha_s: float = 600):
        """Só um job por vez relê e regrava o estados.json (trava-publicar-dados) ou o pacote de um estado
        (trava-publicar-<UF>: fatias do mesmo estado rodam em jobs diferentes). A trava é uma tag: criar uma referência
        que já existe dá erro na API, então só um consegue. Esperar não prova que o dono morreu: ao atingir
        velha_s, falha sem apagar a trava. Erros da API impedem publicação. Reentrante no mesmo processo."""
        nome = nome or self.TRAVA
        if self.privado:
            nome = f"{nome}-{self.tag}"
        if nome in self._travas:
            yield
            return
        h = self._cabecalhos()
        # O SHA do workflow pertence ao repositório público, não ao privado de armazenamento.
        sha = None if self.privado else os.environ.get("GITHUB_SHA")
        if not sha:
            r = self.cli.get(f"{self.API}/repos/{self.repo}/commits/HEAD", headers=h)
            r.raise_for_status()
            sha = r.json().get("sha")
        if not sha:
            raise RuntimeError("não consegui identificar o commit para adquirir a trava de publicação")
        t0 = time.monotonic()
        while True:
            r = self.cli.post(f"{self.API}/repos/{self.repo}/git/refs", headers=h,
                              json={"ref": f"refs/tags/{nome}", "sha": sha})  # fmt: skip
            if r.status_code == 201:
                break
            if r.status_code == 422 and "already exists" in r.text.lower():
                if time.monotonic() - t0 >= velha_s:
                    raise TimeoutError(f"trava {nome} ocupada; não publico nem removo uma trava sem confirmar seu dono")
                time.sleep(random.uniform(5, 15))
                continue
            r.raise_for_status()
            raise RuntimeError(f"resposta inesperada ao adquirir {nome}: HTTP {r.status_code}")
        self._travas.add(nome)
        try:
            yield
        finally:
            self._travas.discard(nome)
            self.cli.delete(f"{self.API}/repos/{self.repo}/git/refs/tags/{nome}", headers=h).raise_for_status()

    def publicar(self, uf: str | None = None, extra: dict | None = None) -> dict:
        """Empacota o estado a partir do espelho e sobe: pacotes, controle e por último o estados.json. O estados.json
        é relido do Release e regravado dentro da trava, trocando só as entradas destes estados (vários jobs publicam
        ao mesmo tempo no GitHub Actions). extra: campos a mais por estado ({uf: {...}}), ex.: a rodada e os erros que
        o motor/rodar_estado.py anota."""
        self.verificar_publicacao()
        ufs = [uf.upper()] if uf else sorted(u for u in self._sujos if u != "_global")
        feito = {}
        for u in ufs:
            with self._trava(f"trava-publicar-{u}", 1800):
                self.garantir_uf(u, forcar=True)  # junta o que outras fatias do estado já publicaram
                from raiz.executor.snapshot_publicacao import congelar

                # Outras lanes escrevem no espelho original. Pacote, metadados
                # e projeção básica precisam ler os mesmos bytes já capturados.
                original = self.local
                with congelar(original, u) as copia:
                    self.local = copia
                    try:
                        feito[u] = self._publicar_uf(u, (extra or {}).get(u, {}))
                        self._gravar_indice({u: feito[u]})
                        if self.publico:
                            self._publicar_aberto(u, feito[u])
                    finally:
                        self.local = original
        if self._sujos.pop("_global", 0) or not uf:
            glob = {k: json.loads(self.local.ler(k)) for k in self.local.listar("estado/")
                    if self._uf_da_chave(k) is None}  # fmt: skip
            if glob:
                self.catalogar_arquivo("raiz_controle.json", json.dumps(glob, ensure_ascii=False).encode(),
                                       "application/json")  # fmt: skip
        return feito

    def _publicar_aberto(self, uf: str, info: dict, *, catalogar: bool = True) -> None:
        from raiz.executor.publicacao_aberta import ESCOPO, entrada_publica, projetar_csvs, projetar_geo

        aberto = self.publico
        if aberto is None or aberto.privado:
            raise ValueError("destino aberto inválido")
        csvs, geos = {}, {}
        for chave in self.local.listar(f"saida/{uf}/"):
            nome = chave.rsplit("/", 1)[1]
            if nome.endswith(".csv"):
                csvs[nome] = self.local.ler(chave)
            elif nome.startswith("geo_") and nome.endswith(".parquet"):
                geos[nome] = projetar_geo(self.local.ler(chave))
        basicos = projetar_csvs(uf, csvs)
        pacote = self._tar(uf, basicos)
        entrada = entrada_publica(info, uf=uf)
        entrada.update(url=aberto.url(f"raiz_{uf}.tar.gz"), tamanho=len(pacote), versao=sha256_bytes(pacote)[:16])
        with aberto._trava(f"trava-publicar-{uf}", 1800):
            aberto._subir(aberto._release(), f"raiz_{uf}.tar.gz", pacote, "application/gzip")
            if geos:
                geo = self._tar(uf, geos)
                nome = f"raiz_geo_{uf}.tar.gz"
                aberto._subir(aberto._release(), nome, geo, "application/gzip")
                entrada["geo"] = {
                    "url": aberto.url(nome),
                    "versao": sha256_bytes(geo)[:16],
                    "tamanho": len(geo),
                    "municipios": len(geos),
                    "escopo": ESCOPO,
                }
            aberto._gravar_indice({uf: entrada})
            if catalogar:
                from raiz.catalogo_publico import catalogar_publico

                catalogar_publico(aberto, uf)

    def _publicar_uf(self, u: str, extra: dict) -> dict:
        import datetime as dt
        import re

        from raiz.metadados import croissant_uf, ficha_arquivo, validar

        self._exigir_privado()
        rel = self._release()
        estados = self.manifesto().get("estados", {})
        agora = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        chaves = self.local.listar(f"saida/{u}/")
        csvs, geos, camadas, vers = {}, {}, {}, {}
        for k in chaves:
            arq = k.rsplit("/", 1)[1]
            dados = self.local.ler(k)
            meta = self.local.meta(k) or {}
            vers[arq] = {x: meta[x] for x in ("tarefa", "versao", "data", "cod_municipio", "sha256") if x in meta}
            if arq.endswith(".csv"):
                cab = dados.split(b"\n", 1)[0].decode("utf-8", "replace").split(",")
                ruins = [c for c in cab if re.search(PROIBIDAS, c.strip().strip('"'), re.I)]
                if ruins:
                    raise ValueError(f"{arq} tem coluna proibida {ruins}: não publico")
                csvs[arq] = dados
            elif arq.startswith("geo_"):
                geos[arq] = dados
            elif arq.startswith("camadas_"):
                camadas[arq] = dados
        info = dict(estados.get(u, {}))
        assets = {a["name"]: a for a in rel.get("assets", [])}
        # Jobs iniciados antes dos metadados ainda podem publicar: o digest do asset prevalece sobre o índice antigo.
        for asset in rel.get("assets", []):
            digest = asset.get("digest") or ""
            if asset.get("name") == f"raiz_{u}.tar.gz" and re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
                info["sha256"] = digest.split(":", 1)[1]
        versao = hashlib.sha256(b"".join(n.encode() + csvs[n] for n in sorted(csvs))).hexdigest()[:16]
        dados_versoes = json.dumps(vers, ensure_ascii=False, sort_keys=True).encode()
        proveniencia = sha256_bytes(dados_versoes)
        pendentes = []
        if csvs and (
            f"raiz_{u}.tar.gz" not in assets
            or info.get("versao") != versao
            or not info.get("sha256")
            or info.get("proveniencia_sha256") != proveniencia
        ):
            pacote = self._tar(u, {**csvs, "_versoes.json": dados_versoes})
            pendentes.append((f"raiz_{u}.tar.gz", pacote, "application/gzip"))
            info.update(tamanho=len(pacote), atualizado_em=agora, sha256=sha256_bytes(pacote),
                        proveniencia_sha256=proveniencia)  # fmt: skip
        for nome, grupo, campo in ((f"raiz_geo_{u}.tar.gz", geos, "geo"), (f"raiz_camadas_{u}.tar.gz", camadas,
                                                                             "camadas")):  # fmt: skip
            if not grupo:
                continue
            digest = assets.get(nome, {}).get("digest") or ""
            if re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest) and info.get(campo):
                info[campo] = {**info[campo], "sha256": digest.split(":", 1)[1]}
            vg = hashlib.sha256(b"".join(n.encode() + grupo[n] for n in sorted(grupo))).hexdigest()[:16]
            precisa_ficha = f"croissant_{nome}.json" not in assets or ((info.get("fichas") or {}).get(nome) or {}).get(
                "arquivo_sha256"
            ) != (info.get(campo) or {}).get("sha256")
            if (
                nome not in assets
                or (info.get(campo) or {}).get("versao") != vg
                or not (info.get(campo) or {}).get("sha256")
                or precisa_ficha
            ):
                p = self._tar(u, grupo)
                pendentes.append((nome, p, "application/gzip"))
                info[campo] = {"versao": vg, "tamanho": len(p), "url": self.url(nome), "municipios": len(grupo),
                               "sha256": sha256_bytes(p)}  # fmt: skip
            else:
                info[campo]["url"] = self.url(nome)
        marcas = {k.rsplit("/", 1)[1][:-5]: json.loads(self.local.ler(k)) for k in self.local.listar(f"marcas/{u}/")}
        est = json.loads(self.local.ler(f"estado/{u}.json") or b"{}")
        controle = json.dumps({"marcas": marcas, "estado": est}, ensure_ascii=False).encode()
        pendentes.append((f"raiz_controle_{u}.json", controle, "application/json"))
        nomes = list(csvs)
        cont = {t: sum(1 for n in nomes if re.fullmatch(rf"{t}_\d{{7}}\.csv", n)) for t in TABELAS_TODAS}
        vazios = {c for c, m in marcas.items() if ((m.get("tarefas") or {}).get("funil") or {}).get("vazio")}
        sit = _situacao(self.local.raiz / "saida" / u, u, vazios)
        info.update(sit)
        info.update(
            tabelas={**cont, "app": sit["tabelas"]["app"]},
            versao=versao,
            url=self.url(f"raiz_{u}.tar.gz"),
            motor_versao=est.get("motor_versao"),
            versoes=est.get("versoes"),
            situacao=est.get("situacao"),
            controle=self.url(f"raiz_controle_{u}.json"),
        )
        info.update(extra)
        if isinstance(est.get("processamento"), dict):
            info["processamento"] = est["processamento"]
        else:
            info.pop("processamento", None)
        from raiz.quantis import quantis_uf

        quantis = quantis_uf(self.local.raiz / "saida" / u, u, vers)
        self._quantis[u] = quantis
        for nome, dados in quantis["arquivos"].items():
            tipo = "application/json" if nome.endswith(".json") else "application/octet-stream"
            pendentes.append((nome, dados, tipo))
        info["quantis"] = {
            "url": self.url_metadados(f"quantis_{u}.parquet"),
            "linhas": quantis["linhas"],
            "modelos": sorted(quantis["modelos"]),
            "diagnosticos": len(quantis["diagnosticos"]),
        }
        from raiz.cadt import cadt_uf

        cadt = cadt_uf(self.local.raiz / "saida" / u, u,
                       data_inicio=os.environ.get("RAIZ_CADT_INICIO_CENARIO"), data_referencia=agora[:10],
                       url_catalogo=self.url_metadados("cadt_lotes.json"))  # fmt: skip
        cadt["metadados"]["entradas"] = {
            "pacote_sha256": info.get("sha256"),
            "proveniencia_sha256": proveniencia,
            "url": self.url_metadados(f"raiz_{u}.tar.gz"),
        }
        info["cadt"] = cadt
        pendentes.append(
            (f"cadt_{u}.json", json.dumps(cadt, ensure_ascii=False, indent=2).encode(), "application/json")
        )
        fichas = dict(info.get("fichas") or {})
        for nome, dados, tipo in list(pendentes):
            if nome == f"raiz_{u}.tar.gz":
                continue  # a ficha tabular abaixo descreve este pacote
            ficha = ficha_arquivo(
                nome,
                self.url_metadados(nome),
                sha256_bytes(dados),
                len(dados),
                formato=tipo,
                repo=self.repo_codigo,
                atualizado_em=agora,
                escopo="privado",
            )
            validar(ficha)
            dados_ficha = json.dumps(ficha, ensure_ascii=False, indent=2).encode()
            nome_ficha = f"croissant_{nome}.json"
            pendentes.append((nome_ficha, dados_ficha, "application/ld+json"))
            fichas[nome] = {"url": self.url_metadados(nome_ficha), "sha256": sha256_bytes(dados_ficha),
                           "arquivo_sha256": sha256_bytes(dados)}  # fmt: skip
        info["fichas"] = fichas
        if csvs:
            ficha = croissant_uf(
                self.local.raiz / "saida" / u,
                u,
                {
                    **info,
                    "repo": self.repo,
                    "tag": self.tag,
                    "repo_codigo": self.repo_codigo,
                    "url": self.url_metadados(f"raiz_{u}.tar.gz"),
                },
                escopo="privado",
            )
            dados_ficha = json.dumps(ficha, ensure_ascii=False, indent=2).encode()
            nome_ficha = f"croissant_{u}.json"
            pendentes.append((nome_ficha, dados_ficha, "application/ld+json"))
            info["croissant"] = {"url": self.url_metadados(nome_ficha), "sha256": sha256_bytes(dados_ficha)}
        # Prepara e valida a ficha antes de alterar qualquer arquivo remoto. A trava da UF abrange tudo.
        for nome, dados, tipo in pendentes:
            self._subir(rel, nome, dados, tipo)
        self._sujos.pop(u, None)
        self._ultima[u] = time.time()
        return info

    def catalogar_arquivo(self, nome: str, dados: bytes, tipo: str = "application/octet-stream") -> dict:
        """Completa a ficha de um arquivo global existente, sob a trava do índice.

        O chamador baixa os bytes sob a mesma trava se o arquivo puder mudar.
        Fichas não recebem fichas de si próprias.
        """
        if nome == "croissant.json" or nome.startswith("croissant_"):
            raise ValueError("a catalogação não cria fichas de fichas")
        if not nome or any(c in nome for c in "\r\n\x00\\/") or nome in {".", ".."}:
            raise ValueError("nome de arquivo inválido para o catálogo")
        with self._trava():
            referencia = self._publicar_auxiliar(self._release(), nome, dados, tipo)
            self._gravar_indice({}, fichas_adicionais={nome: referencia})
        return referencia

    def _gravar_indice(self, feito: dict, fichas_adicionais: dict | None = None) -> None:
        """Relê o estados.json, troca só as entradas destes estados e regrava, dentro da trava; confere depois. O
        campo motor.fatias (a rodada de cada fatia de um estado grande) é juntado, não trocado."""
        import datetime as dt

        from raiz import RAIZ_REPO
        from raiz.cadt import combinar_estados
        from raiz.metadados import croissant_release, ficha_arquivo, validar
        from raiz.quantis import combinar_tasks, esquema_modelos

        agora = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        for _ in range(3):
            with self._trava():
                fresco = self.manifesto(fresco=True)
                est_f = fresco.setdefault("estados", {})
                if not self.privado:
                    from raiz.executor.publicacao_aberta import ESCOPO, VERSAO_PUBLICACAO

                    # Não rotular pacotes legados como básicos só porque outra UF já migrou.
                    est_f = {
                        u: i
                        for u, i in est_f.items()
                        if i.get("escopo") == ESCOPO and i.get("versao_publicacao") == VERSAO_PUBLICACAO
                    }
                    fresco = {"versao_publicacao": VERSAO_PUBLICACAO, "escopo": ESCOPO, "estados": est_f}
                for u, info in feito.items():
                    est_f[u] = _juntar_entrada(est_f.get(u, {}), info)
                fresco.update(gerado_em=agora, repo=self.repo, tag=self.tag, estados=dict(sorted(est_f.items())))
                rel = self._release()
                if self.privado:
                    fichas = fresco.setdefault("fichas", {})
                    fichas.update(fichas_adicionais or {})
                    cartao = (RAIZ_REPO / "docs" / "modelo" / "cartao.md").read_bytes()
                    fichas["cartao_modelo.md"] = self._publicar_auxiliar(
                        rel, "cartao_modelo.md", cartao, "text/markdown"
                    )
                    lotes = combinar_estados({u: e["cadt"] for u, e in est_f.items() if e.get("cadt")})
                    fichas["cadt_lotes.json"] = self._publicar_auxiliar(
                        rel,
                        "cadt_lotes.json",
                        json.dumps(lotes, ensure_ascii=False, indent=2).encode(),
                        "application/json",
                    )
                    atuais = [self._quantis[u] for u in feito if u in self._quantis]
                    if atuais:
                        tasks_antes = json.loads(self._baixar_asset("tasks.json", fresco=True) or b"{}")
                        configuracoes = ([tasks_antes] if tasks_antes else []) + [q["tasks"] for q in atuais]
                        tarefas = combinar_tasks(configuracoes)
                        modelos = json.loads(self._baixar_asset("modelos.json", fresco=True) or b'{"modelos":{}}')
                        for q in atuais:
                            modelos.setdefault("modelos", {}).update(q["modelos"])
                        for nome, objeto in (
                            ("tasks.json", tarefas),
                            ("modelos.json", modelos),
                            ("model-metadata-schema.json", esquema_modelos()),
                        ):
                            conteudo = json.dumps(objeto, ensure_ascii=False, indent=2).encode()
                            fichas[nome] = self._publicar_auxiliar(rel, nome, conteudo, "application/json")
                    dados = json.dumps(fresco, ensure_ascii=False, indent=1).encode()
                    ficha_indice = ficha_arquivo(
                        "estados.json",
                        self.url_metadados("estados.json"),
                        sha256_bytes(dados),
                        len(dados),
                        formato="application/json",
                        repo=self.repo_codigo,
                        escopo=self.escopo_metadados,
                        atualizado_em=agora,
                    )
                    validar(ficha_indice)
                    ficha_indice = json.dumps(ficha_indice, ensure_ascii=False, indent=2).encode()
                    nome_ficha = "croissant_estados.json"
                    self._subir(rel, nome_ficha, ficha_indice, "application/ld+json")
                    # A ficha do índice entra só no catálogo: seu hash no índice criaria autorreferência.
                    fichas = {**fresco.get("fichas", {}), "estados.json": {"url": self.url_metadados(nome_ficha),
                               "sha256": sha256_bytes(ficha_indice)}}  # fmt: skip
                    catalogo = croissant_release(
                        {**fresco, "fichas": fichas},
                        self.repo,
                        self.tag,
                        escopo=self.escopo_metadados,
                        repo_codigo=self.repo_codigo,
                    )
                    validar(catalogo)
                    ficha = json.dumps(catalogo, ensure_ascii=False, indent=2).encode()
                    self._subir(rel, "croissant.json", ficha, "application/ld+json")
                else:
                    if fichas_adicionais:
                        raise ValueError("fichas públicas ficam no catálogo, nunca no manifesto básico")
                    dados = json.dumps(fresco, ensure_ascii=False, indent=1).encode()
                self._subir(rel, "estados.json", dados, "application/json")
            conferido = self.manifesto(fresco=True).get("estados", {})
            if all((conferido.get(u) or {}).get("versao") == info.get("versao") for u, info in feito.items()):
                for u in feito:
                    self._quantis.pop(u, None)
                return
            log.warning("estados.json sem a entrada de %s (outro job regravou junto); refaço", list(feito))
            time.sleep(random.uniform(5, 20))
        raise RuntimeError("não consegui gravar o estados.json com as entradas deste job")


def _juntar_entrada(antiga: dict, nova: dict) -> dict:
    """Entrada nova por cima da antiga; motor.fatias junta as fatias (cada job publica só a sua)."""
    out = {**antiga, **nova}
    ma, mn = antiga.get("motor"), nova.get("motor")
    if isinstance(ma, dict) and isinstance(mn, dict):
        out["motor"] = {**ma, **mn, "fatias": {**(ma.get("fatias") or {}), **(mn.get("fatias") or {})}}
        if not out["motor"]["fatias"]:
            del out["motor"]["fatias"]
    return out


def _situacao(pasta: Path, uf: str, vazios: set[str]) -> dict:
    """completo, faltam, sem_imoveis... pela conta do motor (motor/raiz_situacao.py), com as tarefas do produto."""
    from raiz import MOTOR_DIR

    if str(MOTOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOTOR_DIR))
    import raiz_situacao

    return raiz_situacao.situacao(Path(pasta), uf, vazios=vazios, produto=True)


def _espelho_padrao() -> Path:
    from raiz import RAIZ_REPO
    from raiz.config import config

    return Path(getattr(config(), "armazem_espelho_dir", None) or RAIZ_REPO / "dados" / "armazem_local")
