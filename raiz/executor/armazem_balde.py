"""Arquivo da Raíz num balde compatível com S3 (Cloudflare R2 recomendado), no lugar dos Releases do GitHub.

Mantém **o mesmo contrato** do `ArmazemRelease`: os mesmos nomes de arquivo (`raiz_<UF>.tar.gz`, `estados.json`,
controles, fichas), o mesmo `publicar(uf)` / `_publicar_aberto(uf)` / `_gravar_indice` e as mesmas travas por UF.
Só o transporte muda: listar, baixar, subir e conferir que o destino privado continua privado.

Configuração (somente variáveis de ambiente; ver docs/armazenamento.md):

  RAIZ_DADOS_PRIVADOS_URL=s3://raiz-privado/dados        arquivo completo (privado)
  RAIZ_ARMAZEM_URL=release-github://dono/repo/dados       projeção aberta (fase 1: segue no Release público)
  RAIZ_ARMAZEM_URL=s3://raiz-publico/dados                projeção aberta (fase 2: balde público)
  RAIZ_PUBLICO_URL_BASE=https://dados.exemplo/dados       endereço HTTPS de leitura do balde público (fase 2)
  RAIZ_S3_ENDPOINT, RAIZ_S3_ACCESS_KEY_ID, RAIZ_S3_SECRET_ACCESS_KEY

As travas continuam sendo referências git no repositório de código (sem dados), com sufixo próprio do balde, para
nunca disputar a mesma trava com o fluxo antigo do Release durante a migração.
"""

from __future__ import annotations

import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from raiz.executor.armazem import ArmazemRelease, ArmazemS3, FalhaHTTPPrivada

BALDE = re.compile(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]")
PREFIXO = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*")


def partes_s3(url: str) -> tuple[str, str]:
    """`s3://balde/prefixo` -> (balde, prefixo sem barras nas pontas). Recusa credencial ou consulta na URL."""
    if not url.startswith("s3://"):
        raise ValueError("endereço de balde deve começar com s3://")
    resto = url[len("s3://") :].strip("/")
    balde, _, prefixo = resto.partition("/")
    prefixo = prefixo.strip("/")
    if not BALDE.fullmatch(balde) or (prefixo and not PREFIXO.fullmatch(prefixo)) or ".." in prefixo.split("/"):
        raise ValueError("endereço de balde inválido")
    return balde, prefixo


def url_publica_valida(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip().rstrip("/")
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9_.~-]+)*", url):
        raise ValueError("RAIZ_PUBLICO_URL_BASE deve ser HTTPS, sem credencial, consulta ou fragmento")
    return url


def _cliente_s3_config():
    from raiz.config import config

    c = config()
    k = getattr(c, "s3_access_key_id", None)
    s = getattr(c, "s3_secret_access_key", None)
    return (
        getattr(c, "s3_endpoint", None),
        getattr(c, "s3_regiao", "auto") or "auto",
        k.get_secret_value() if k else None,
        s.get_secret_value() if s else None,
    )


class ArmazemBalde(ArmazemRelease):
    """`ArmazemRelease` cujo transporte é um balde S3. Ver o docstring do módulo."""

    e_release_github = False

    def __init__(self, url: str, *, privado: bool, publico: ArmazemRelease | None = None,
                 espelho: Path | None = None, url_publica: str | None = None, cliente_s3=None,
                 token: str | None = None, cliente=None, **kw):  # fmt: skip
        balde, prefixo = partes_s3(url)
        if not privado and publico is not None:
            raise ValueError("só o arquivo privado projeta um destino aberto")
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{balde}-{prefixo}" if prefixo else balde)[:60]
        repo_codigo = os.environ.get("GITHUB_REPOSITORY") or "bernardoemmel/Raiz"
        super().__init__(repo_codigo, f"balde-{slug}", espelho=espelho, token=token, cliente=cliente,
                         privado=privado, publico=publico, **kw)  # fmt: skip
        if cliente_s3 is None:
            endpoint, regiao, chave, segredo = _cliente_s3_config()
            self.cru = ArmazemS3(balde, prefixo, endpoint, regiao, chave, segredo)
            self._endpoint = endpoint
            self._com_credencial = bool(chave and segredo)
        else:
            self.cru = ArmazemS3(balde, prefixo, cliente=cliente_s3)
            self._endpoint = None  # cliente injetado (testes): sem sondagem anônima pela rede
            self._com_credencial = True
        self.balde, self.prefixo_balde = balde, prefixo
        self.url_publica = url_publica_valida(
            url_publica if url_publica is not None else (None if privado else os.environ.get("RAIZ_PUBLICO_URL_BASE"))
        )
        if not privado and not self.url_publica:
            raise ValueError("balde aberto exige RAIZ_PUBLICO_URL_BASE (endereço HTTPS de leitura)")
        self.descricao = f"balde s3://{balde}/{prefixo}"
        self._digests: dict[tuple[str, str], str] = {}
        self._digests_trava = threading.Lock()
        self._privacidade_conferida = False

    # --- endereços -----------------------------------------------------------------------------------------------

    @property
    def base_s3(self) -> str:
        return f"s3://{self.balde}/" + (f"{self.prefixo_balde}/" if self.prefixo_balde else "")

    def url(self, nome: str) -> str:
        if self.privado:
            return self.base_s3 + nome
        return f"{self.url_publica}/{nome}"

    def url_metadados(self, nome: str) -> str:
        return self.url(nome)

    @property
    def base_metadados(self) -> str:
        return self.base_s3 if self.privado else self.url_publica + "/"

    # --- travas: as mesmas refs git, com nome próprio do balde ---------------------------------------------------

    def _trava(self, nome: str | None = None, velha_s: float = 600):
        nome = nome or self.TRAVA
        if not self.privado and not nome.endswith(self.tag):
            nome = f"{nome}-{self.tag}"  # o privado já recebe o sufixo da tag em _trava_impl
        return super()._trava(nome, velha_s)

    # --- privacidade ---------------------------------------------------------------------------------------------

    def _conferir_privacidade(self) -> None:
        """Falha fechada se o balde privado responde a uma leitura anônima ou é o mesmo do aberto."""
        if self._privacidade_conferida:
            return
        aberto = self.publico
        if isinstance(aberto, ArmazemBalde) and (aberto.balde, aberto.prefixo_balde) == (
            self.balde,
            self.prefixo_balde,
        ):
            raise PermissionError("o balde privado deve ser separado do aberto")
        publica = os.environ.get("RAIZ_PUBLICO_URL_BASE", "")
        if publica and self.balde in publica:
            raise PermissionError("o endereço público aponta para o balde privado")
        if self._endpoint and os.environ.get("RAIZ_BALDE_CONFERIR_ANONIMO", "1") != "0":
            import httpx

            try:
                r = httpx.get(f"{self._endpoint.rstrip('/')}/{self.balde}/{self.prefixo_balde}/estados.json",
                              timeout=30, follow_redirects=False)  # fmt: skip
            except httpx.HTTPError:
                r = None  # sem resposta não prova abertura; as operações autenticadas seguem conferidas
            if r is not None and 200 <= r.status_code < 400:
                raise PermissionError("o balde privado respondeu a uma leitura sem credencial: acesso bloqueado")
        self._privacidade_conferida = True

    def _exigir_privado(self) -> dict:
        if not self.privado:
            raise PermissionError("dados completos exigem RAIZ_DADOS_PRIVADOS_URL apontando para o balde privado")
        self._conferir_privacidade()
        return self._release(listar_assets=False)

    def verificar_publicacao(self) -> None:
        self._exigir_privado()
        if self.publico:
            self.publico._cabecalhos()
            self.publico._release(listar_assets=False)

    # --- leitura -------------------------------------------------------------------------------------------------

    def _release(self, *, listar_assets: bool = True) -> dict:
        rel = {"id": self.base_s3, "tag_name": self.tag, "draft": self.privado, "privado": self.privado}
        if listar_assets:
            rel["assets"] = self._assets(rel)
        return rel

    def _digest(self, chave: str, etag: str) -> str | None:
        with self._digests_trava:
            if (chave, etag) in self._digests:
                return self._digests[(chave, etag)]
        try:
            r = self.cru.cli.head_object(Bucket=self.balde, Key=chave)
        except Exception:  # noqa: BLE001 - sem digest o publicador regrava; nunca inventa um
            return None
        sha = (r.get("Metadata") or {}).get("sha256", "")
        valor = f"sha256:{sha}" if re.fullmatch(r"[a-f0-9]{64}", sha) else None
        with self._digests_trava:
            self._digests[(chave, etag)] = valor
        return valor

    def _assets(self, rel: dict | None = None) -> list[dict]:
        """Arquivos do primeiro nível do prefixo (o histórico por CAR fica em subpastas e não entra aqui)."""
        if self.privado:
            self._conferir_privacidade()
        objetos = []
        pag = self.cru.cli.get_paginator("list_objects_v2")
        for p in pag.paginate(Bucket=self.balde, Prefix=self.cru.prefixo, Delimiter="/"):
            objetos += p.get("Contents", [])
        ativos = []
        for o in objetos:
            nome = o["Key"][len(self.cru.prefixo) :]
            if not nome or "/" in nome:
                continue
            quando = o.get("LastModified")
            ativos.append({
                "id": o["Key"],
                "name": nome,
                "size": int(o.get("Size", 0)),
                "updated_at": quando.isoformat().replace("+00:00", "Z") if quando else "",
                "etag": str(o.get("ETag", "")).strip('"'),
            })  # fmt: skip
        with ThreadPoolExecutor(max_workers=16) as ex:
            for ativo, digest in zip(ativos, ex.map(lambda a: self._digest(a["id"], a["etag"]), ativos), strict=True):
                if digest:
                    ativo["digest"] = digest
        return ativos

    def _baixar_ativo(self, ativo: dict) -> bytes:
        if self.privado:
            self._conferir_privacidade()
        dados = self.cru.cli.get_object(Bucket=self.balde, Key=ativo["id"])["Body"].read()
        if ativo.get("size") is not None and len(dados) != ativo["size"]:
            raise ValueError("tamanho divergente no download do balde")
        return dados

    def _baixar_asset(self, nome: str, fresco: bool = False) -> bytes | None:
        if self.privado:
            self._exigir_privado()
            try:
                return self.cru.ler(nome)
            except Exception as ex:  # noqa: BLE001 - não deixa URL assinada ou resposta chegar aos logs
                status = getattr(ex, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
                raise FalhaHTTPPrivada(int(status or 0), "leitura") from None
        if self._com_credencial:  # leitura assinada do aberto (publicador); o site lê por HTTPS
            dados = self.cru.ler(nome)
        else:
            import time

            r = self.cli.get(self.url(nome), params={"t": str(time.time_ns())} if fresco else None)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            dados = r.content
        if dados is None:
            return None
        from raiz.executor.publicacao_aberta import validar_asset_publico

        validar_asset_publico(nome, dados, repo=self.repo, tag=self.tag)
        return dados

    # --- escrita -------------------------------------------------------------------------------------------------

    def _subir(self, rel: dict, nome: str, dados: bytes, tipo: str = "application/octet-stream") -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", nome):
            raise ValueError("nome inválido para o balde")
        if self.privado:
            self._exigir_privado()
            if rel.get("id") != self.base_s3:
                raise PermissionError("upload deve usar somente o balde privado configurado")
        else:
            from raiz.executor.publicacao_aberta import validar_asset_publico

            validar_asset_publico(nome, dados, repo=self.repo, tag=self.tag)
        from raiz.executor.armazem import sha256_bytes

        sha = sha256_bytes(dados)
        extra = {"Metadata": {"sha256": sha, "tamanho": str(len(dados))}, "ContentType": tipo}
        if not self.privado:
            extra["CacheControl"] = "no-cache" if nome == "estados.json" else "public, max-age=300"
        try:
            r = self.cru.cli.put_object(Bucket=self.balde, Key=self.cru.prefixo + nome, Body=dados, **extra)
        except Exception as ex:  # noqa: BLE001
            if not self.privado:
                raise
            status = getattr(ex, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            raise FalhaHTTPPrivada(int(status or 0), "upload") from None
        with self._digests_trava:
            self._digests[(self.cru.prefixo + nome, str(r.get("ETag", "")).strip('"'))] = f"sha256:{sha}"
        from raiz.atestacao import registrar

        registrar(nome, dados, privado=self.privado)

    def apagar_arquivo(self, nome: str) -> None:
        """Remove um arquivo do primeiro nível (uso operacional explícito; o publicador nunca chama)."""
        if self.privado:
            self._exigir_privado()
        self.cru.cli.delete_object(Bucket=self.balde, Key=self.cru.prefixo + nome)


def cru(armazem):
    """O balde S3 por trás de um ArmazemBalde (para quem grava objetos por chave, como o histórico por CAR)."""
    return armazem.cru if isinstance(armazem, ArmazemBalde) else armazem
