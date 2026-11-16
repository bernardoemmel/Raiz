"""Publica só o calendário público, pela API REST, conservando cópias até a promoção."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

import requests

from raiz.calendario.arquivos import MAX_ESTADO, validar
from raiz.calendario.modelos import Evento, FonteEstado
from raiz.privacidade import mascarar

ARQUIVOS = ("estado.json", "eventos.json", "eventos.ics")


def publicar_release(pasta: Path, repositorio: str, token: str) -> None:
    """Envia e confere os três arquivos antes de renomear qualquer arquivo vigente."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repositorio) or not token:
        raise ValueError("repositório ou credencial do calendário ausente")
    base = f"https://api.github.com/repos/{repositorio}"
    cabecalhos = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    rodada = uuid4().hex
    novos, reservas, promovidos = {}, {}, []

    def api(metodo, url, **kw):
        headers = {**cabecalhos, **({"Content-Type": "application/octet-stream"} if "data" in kw else {})}
        with requests.request(metodo, url, headers=headers, timeout=(10, 60), **kw) as r:
            r.raise_for_status()
            return None if r.status_code == 204 else r.json()

    def renomear(identificador, nome):
        api("PATCH", f"{base}/releases/assets/{identificador}", json={"name": nome})

    try:
        conteudos = {}
        for nome in ARQUIVOS:
            arquivo = pasta / nome
            if arquivo.stat().st_size > MAX_ESTADO:
                raise ValueError
            bruto = arquivo.read_bytes()
            texto = bruto.decode("utf-8")
            if mascarar(texto) != texto:
                raise ValueError
            if nome.endswith(".json"):
                dados = json.loads(texto)
                decodificado = json.dumps(dados, ensure_ascii=False)
                if mascarar(decodificado) != decodificado:
                    raise ValueError
                eventos, fontes = validar(dados)
                if (
                    type(dados.get("total")) is not int
                    or dados["total"] != len(eventos)
                    or len({e.id for e in eventos}) != len(eventos)
                    or set(dados) != {"eventos", "fontes", "total", "coletado_em"}
                    or any(e.codigos_car and e.vinculo not in ("car", "pendente") for e in eventos)
                ):
                    raise ValueError
                permitidos = set(Evento.model_fields)
                if nome == "eventos.json":
                    permitidos = (permitidos - {"cns", "matricula", "sigef"}) | {"titulo"}
                if any(
                    set(item) - permitidos
                    or item.get("fonte_nome") != evento.fonte_nome
                    or (nome == "eventos.json" and item.get("titulo") != evento.titulo)
                    for item, evento in zip(dados["eventos"], eventos, strict=True)
                ) or any(
                    set(item) - set(FonteEstado.model_fields) or item.get("nome") != fonte.nome
                    for item, fonte in zip(dados["fontes"], fontes, strict=True)
                ):
                    raise ValueError
            conteudos[nome] = bruto
        release = api("GET", f"{base}/releases/tags/calendario")
        if release.get("draft") is not False or release.get("tag_name") != "calendario":
            raise ValueError
        release_id = release["id"]
        existentes = api("GET", f"{base}/releases/{release_id}/assets", params={"per_page": 100})
        antigos = {a["name"]: a["id"] for a in existentes if a["name"] in ARQUIVOS}
        if len(existentes) >= 100 or set(antigos) != set(ARQUIVOS):
            raise ValueError
        # Não usar gh release upload --clobber: ele apaga a versão vigente antes do upload.
        for nome, bruto in conteudos.items():
            temporario = f"calendario-novo-{rodada}-{nome}"
            resultado = api(
                "POST",
                f"https://uploads.github.com/repos/{repositorio}/releases/{release_id}/assets",
                params={"name": temporario},
                data=bruto,
            )
            novos[nome] = resultado["id"]
            if (
                resultado.get("name") != temporario
                or resultado.get("state") != "uploaded"
                or resultado.get("size") != len(bruto)
                or resultado.get("digest") != "sha256:" + hashlib.sha256(bruto).hexdigest()
            ):
                raise ValueError
        for nome, identificador in antigos.items():
            renomear(identificador, f"calendario-reserva-{rodada}-{nome}")
            reservas[nome] = identificador
        for nome, identificador in novos.items():
            renomear(identificador, nome)
            promovidos.append(nome)
    except (OSError, ValueError, KeyError, TypeError, requests.RequestException):
        # Renomear conserva os bytes antigos mesmo se a conexão cair na promoção.
        # Se a restauração também falhar, as reservas continuam no Release para recuperação.
        for nome in promovidos:
            try:
                renomear(novos[nome], f"calendario-novo-{rodada}-{nome}")
            except requests.RequestException:
                pass
        for nome, identificador in reservas.items():
            try:
                renomear(identificador, nome)
            except requests.RequestException:
                pass
        raise ValueError("publicação do calendário interrompida; arquivos anteriores preservados") from None
    # Só após os três arquivos promovidos as cópias anteriores podem ser removidas.
    for identificador in reservas.values():
        try:
            api("DELETE", f"{base}/releases/assets/{identificador}")
        except requests.RequestException:
            raise ValueError("calendário publicado; limpeza das cópias anteriores pendente") from None
