"""Publicação autenticada no arquivo privado da Raíz.

- Alertas de imóvel, espelho do Ibama, fontes e rodadas também ficam no Release privado: são histórico por CAR.
- Parte privada (alertas de projeto, perdas, marcações, eventos): um pacote só, `privado.tar.gz.cifrado`, cifrado com
  Fernet (AES-128 + HMAC-SHA256, biblioteca cryptography) com a chave de RAIZ_VIGILANCIA_CHAVE. Sem a chave, a parte
  privada não sai da máquina (e a rodada avisa).
- Marcações e eventos que chegam pela API viram `entrada_*.cifrado` no Release; a rodada diária junta e apaga.
- `vigilancia.json` (manifesto) sobe por último, com o sha256 de cada arquivo: quem baixa só pega o que mudou.

Gerar a chave: python -m raiz.vigilancia chave (guardar como segredo RAIZ_VIGILANCIA_CHAVE no GitHub e no servidor).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
from pathlib import Path

from raiz.vigilancia import rede
from raiz.vigilancia.armazem import Armazem
from raiz.vigilancia.config import Config, config

log = logging.getLogger(__name__)

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
MANIFESTO = "vigilancia.json"
DESCRICAO_RELEASE = (
    "Alertas diários por imóvel do CAR (MapBiomas Alerta, FIRMS NOAA-20/21, embargos do Ibama, DETER e PRODES), só "
    "de fontes públicas, sem nome, CPF ou CNPJ. A parte de projetos, perdas e marcações vai cifrada. Gerado por "
    "raiz/vigilancia (GitHub Actions). Não editar à mão."
)
PRIVADO = "privado.tar.gz.cifrado"


# ------------------------------------------------------------------ cifra


def gerar_chave() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def cifrar(dado: bytes, chave: str) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(chave.encode()).encrypt(dado)


def decifrar(dado: bytes, chave: str) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(chave.encode()).decrypt(dado)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def empacotar(pasta: Path) -> bytes:
    """tar.gz determinístico (mesma pasta, mesmos bytes): ordem fixa, data zero, sem dono."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        for f in sorted(p for p in pasta.rglob("*") if p.is_file() and not p.name.endswith(".tmp")):
            info = tar.gettarinfo(str(f), arcname=str(f.relative_to(pasta)))
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with open(f, "rb") as fh:
                tar.addfile(info, fh)
    # o gzip grava data no cabeçalho: zera para o pacote ser determinístico
    b = bytearray(buf.getvalue())
    b[4:8] = b"\x00\x00\x00\x00"
    return bytes(b)


def desempacotar(dado: bytes, destino: Path) -> None:
    tmp = destino.with_name(destino.name + ".novo")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(dado), mode="r:gz") as tar:
        tar.extractall(tmp, filter="data")
    shutil.rmtree(destino, ignore_errors=True)
    tmp.rename(destino)


# ------------------------------------------------------------------ Release do GitHub (API REST)


class Release:
    def __init__(self, cfg: Config | None = None, tag: str | None = None):
        from raiz.executor.armazem import ArmazemRelease, destino_privado

        self.cfg = cfg or config()
        destino = destino_privado()
        self.repo, self.tag = destino or (self.cfg.repo, tag or self.cfg.tag_vigilancia)
        self.token = os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN") or self.cfg.token_github
        self._arm = (
            ArmazemRelease(
                self.repo, self.tag, espelho=self.cfg.cache / "release_privado", token=self.token or "", privado=True
            )
            if destino
            else None
        )
        self._id: int | None = None

    def _exigir_privado(self):
        if self._arm is None:
            raise PermissionError("a vigilância exige RAIZ_DADOS_PRIVADOS_URL e acesso autenticado ao arquivo privado")
        self._arm._exigir_privado()
        return self._arm

    def _h(self, extra: dict | None = None) -> dict:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(extra or {})
        return h

    def id(self, criar: bool = False) -> int | None:
        # Nunca cria ou publica automaticamente um Release: rascunho que virou público fecha o acesso.
        self._id = int(self._exigir_privado()._release()["id"])
        return self._id

    def ativos(self) -> dict[str, dict]:
        rid = self.id()
        if rid is None:
            return {}
        out, pagina = {}, 1
        while True:
            r = rede.pedir(
                "GET",
                f"{API}/repos/{self.repo}/releases/{rid}/assets",
                headers=self._h(),
                params={"per_page": 100, "page": pagina},
            )
            lote = r.json()
            for a in lote:
                out[a["name"]] = a
            if len(lote) < 100:
                return out
            pagina += 1

    def baixar(self, ativo: dict) -> bytes:
        self._exigir_privado()
        r = rede.pedir(
            "GET",
            f"{API}/repos/{self.repo}/releases/assets/{ativo['id']}",
            headers=self._h({"Accept": "application/octet-stream"}),
            timeout=900,
        )
        return r.content

    def subir(self, nome: str, dado: bytes, tipo: str = "application/octet-stream") -> None:
        """Sobe com nome provisório, apaga o antigo e renomeia (o arquivo nunca fica faltando por muito tempo)."""
        if not self.token:
            raise RuntimeError("sem token do GitHub (RAIZ_GITHUB_TOKEN, GITHUB_TOKEN ou GH_TOKEN) para publicar")
        rid = self.id(criar=True)
        atuais = self.ativos()
        provisorio = f"{nome}.subindo"
        if provisorio in atuais:
            self.apagar(atuais[provisorio])
        r = rede.pedir(
            "POST",
            f"{UPLOADS}/repos/{self.repo}/releases/{rid}/assets",
            ok=(201,),
            headers=self._h({"Content-Type": tipo}),
            params={"name": provisorio},
            data=dado,
            timeout=1800,
        )
        novo = r.json()
        if nome in atuais:
            self.apagar(atuais[nome])
        rede.pedir(
            "PATCH",
            f"{API}/repos/{self.repo}/releases/assets/{novo['id']}",
            headers=self._h(),
            json={"name": nome},
        )

    def apagar(self, ativo: dict) -> None:
        self._exigir_privado()
        rede.pedir("DELETE", f"{API}/repos/{self.repo}/releases/assets/{ativo['id']}", ok=(204, 404), headers=self._h())


# ------------------------------------------------------------------ baixar e publicar o estado


def _publicos(arm: Armazem) -> dict[str, Path]:
    """Nome no Release -> arquivo local."""
    out = {f.name: f for f in sorted((arm.publico / "alertas").glob("alertas_*.parquet"))}
    for nome in ("ibama_espelho.parquet", "fontes.json", "rodadas.jsonl"):
        if (arm.publico / nome).exists():
            out[nome] = arm.publico / nome
    return out


def baixar_estado(arm: Armazem, rel: Release, chave: str | None) -> dict:
    """Traz para a pasta local o estado publicado (só o que mudou) e as entradas pendentes da API."""
    ativos = rel.ativos()
    if MANIFESTO not in ativos:
        return {"manifesto": False}
    manifesto = json.loads(rel.baixar(ativos[MANIFESTO]))
    baixados = 0
    for nome, info in manifesto.get("arquivos", {}).items():
        destino = (arm.publico / "alertas" / nome) if nome.startswith("alertas_") else arm.publico / nome
        if destino.exists() and _sha(destino.read_bytes()) == info.get("sha256"):
            continue
        if nome not in ativos:
            log.warning("o manifesto cita %s, mas o arquivo não está no Release", nome)
            continue
        dado = rel.baixar(ativos[nome])
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dado)
        baixados += 1
    privado = "sem chave"
    marca = arm.pasta / ".privado_versao"
    pv = manifesto.get("privado", {}).get("versao")
    if chave and PRIVADO in ativos:
        if not (marca.exists() and marca.read_text() == pv):
            desempacotar(decifrar(rel.baixar(ativos[PRIVADO]), chave), arm.privado)
            (arm.privado / "alertas").mkdir(parents=True, exist_ok=True)
            marca.write_text(pv or "")
            privado = "baixado"
        else:
            privado = "igual"
    entradas = []
    if privado == "baixado":
        arm.limpar_entradas_incorporadas()
    if chave:
        for nome, a in ativos.items():
            if nome.startswith("entrada_") and nome.endswith(".cifrado"):
                try:
                    reg = json.loads(decifrar(rel.baixar(a), chave))
                except Exception as ex:  # noqa: BLE001 (entrada ilegível não pode travar a rodada)
                    log.warning("entrada %s ilegível: %s", nome, type(ex).__name__)
                    continue
                destino = arm.entrada_dir / nome.replace(".cifrado", ".json")
                destino.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
                entradas.append(nome)
    arm._cache = None
    return {"manifesto": True, "baixados": baixados, "privado": privado, "entradas": entradas}


def publicar(
    arm: Armazem, rel: Release, chave: str | None, resumo: dict | None = None, entradas_lidas: list[str] | None = None
) -> dict:
    """Sobe o que mudou; manifesto por último; apaga as entradas da API que já entraram no estado."""
    ativos = rel.ativos() if rel.id() is not None else {}
    antigo = json.loads(rel.baixar(ativos[MANIFESTO])) if MANIFESTO in ativos else {}
    arquivos, subidos = {}, []
    for nome, caminho in _publicos(arm).items():
        b = caminho.read_bytes()
        info = {"sha256": _sha(b), "tamanho": len(b)}
        arquivos[nome] = info
        if antigo.get("arquivos", {}).get(nome, {}).get("sha256") != info["sha256"] or nome not in ativos:
            tipo = "application/json" if nome.endswith((".json", ".jsonl")) else "application/vnd.apache.parquet"
            rel.subir(nome, b, tipo)
            subidos.append(nome)
    privado = antigo.get("privado", {})
    if chave:
        pacote = empacotar(arm.privado)
        versao = _sha(pacote)[:16]
        if privado.get("versao") != versao or PRIVADO not in ativos:
            rel.subir(PRIVADO, cifrar(pacote, chave))
            subidos.append(PRIVADO)
        privado = {"versao": versao, "cifrado": True, "tamanho_aberto": len(pacote)}
        (arm.pasta / ".privado_versao").write_text(versao)
    else:
        log.warning("sem RAIZ_VIGILANCIA_CHAVE: projetos, perdas e marcações não foram publicados")
    agora = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    manifesto = {
        "gerado_em": agora,
        "repo": rel.repo,
        "tag": rel.tag,
        "arquivos": arquivos,
        "privado": privado,
        **({"resumo": resumo} if resumo else {}),
    }
    rel.subir(MANIFESTO, json.dumps(manifesto, ensure_ascii=False, indent=1).encode(), "application/json")
    apagadas = 0
    if entradas_lidas:
        atuais = rel.ativos()
        for nome in entradas_lidas:
            if nome in atuais:
                rel.apagar(atuais[nome])
                apagadas += 1
    return {"subidos": subidos, "entradas_apagadas": apagadas}


def enviar_entrada(rel: Release, chave: str | None, caminho: Path) -> bool:
    """Manda para o Release uma entrada da API (cifrada), para a rodada diária juntar. Sem chave ou token, fica só
    local (o servidor já mostra a entrada; a rodada não vê)."""
    if not (chave and rel.cfg.token_github):
        return False
    dado = cifrar(caminho.read_bytes(), chave)
    rel.subir(caminho.name.replace(".json", ".cifrado"), dado)
    return True
