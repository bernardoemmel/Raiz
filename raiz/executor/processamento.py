"""Eventos privados do executor; o estado publicado contém somente contagens."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import threading
import uuid
from pathlib import Path

INTERVALO_S = 30
LEASE_S = 120


def agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def contexto(trabalho: Path, uf: str) -> dict:
    unidade = os.environ.get("UNIDADE", uf).upper()
    if not re.fullmatch(rf"{uf}(?:-[1-9]\d*)?", unidade):
        raise ValueError("unidade de processamento não corresponde à UF")
    run = os.environ.get("GITHUB_RUN_ID", "local")
    tentativa = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    if not re.fullmatch(r"\d+|local", run) or not re.fullmatch(r"[1-9]\d*", tentativa):
        raise ValueError("identidade da execução inválida")
    execucao = f"{run}-{tentativa}-{uuid.uuid4().hex}"
    pasta = Path(trabalho) / ".executor" / "processamento" / uf / unidade / execucao
    pasta.mkdir(parents=True, mode=0o700)
    return {"pasta": pasta, "uf": uf, "unidade": unidade, "run": run, "tentativa": tentativa,
            "execucao": execucao, "inicio": agora().isoformat()}  # fmt: skip


def _gravar(ctx: dict, cod: int, evento: dict) -> None:
    destino = ctx["pasta"] / f"{int(cod)}.json"
    tmp = destino.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(evento, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, destino)


@contextlib.contextmanager
def acompanhar(ctx: dict, cod: int):
    inicio = agora()
    evento = {k: ctx[k] for k in ("uf", "unidade", "run", "tentativa", "execucao")}
    evento.update(versao=1, municipio=int(cod), situacao="em_execucao", inicio=inicio.isoformat(),
                  ultima_mudanca_em=inicio.isoformat())  # fmt: skip
    parar = threading.Event()

    def bater():
        instante = agora()
        evento.update(
            observado_em=instante.isoformat(), valido_ate=(instante + dt.timedelta(seconds=LEASE_S)).isoformat()
        )
        _gravar(ctx, cod, evento)

    def manter():
        while not parar.wait(INTERVALO_S):
            try:
                bater()
            except OSError:
                # O lease vencido será desconhecido, nunca execução inventada.
                return

    bater()
    thread = threading.Thread(target=manter, daemon=True)
    thread.start()
    resultado = {"erro": True}
    try:
        yield resultado
    finally:
        parar.set()
        thread.join()
        fim = agora()
        evento.update(situacao="com_erro" if resultado["erro"] else "pronto", fim=fim.isoformat(),
                      ultima_mudanca_em=fim.isoformat())  # fmt: skip
        bater()


def resumir(ctx: dict, cods: list[int], prontos: set[int]) -> dict:
    instante = agora()
    contagens = dict.fromkeys(("prontos", "em_execucao", "com_erro", "pendentes", "desconhecidos"), 0)
    mudanca = dt.datetime.fromisoformat(ctx["inicio"])
    validade_resumo = instante + dt.timedelta(seconds=LEASE_S)
    for cod in set(cods):
        if cod in prontos:
            contagens["prontos"] += 1
            continue
        if cod in ctx.get("nao_comprovados", set()):
            contagens["desconhecidos"] += 1
            continue
        arquivo = ctx["pasta"] / f"{int(cod)}.json"
        if not arquivo.exists():
            contagens["pendentes"] += 1
            continue
        categoria = "desconhecidos"
        try:
            evento = json.loads(arquivo.read_text())
            if evento.get("execucao") == ctx["execucao"] and evento.get("municipio") == cod:
                alterado = dt.datetime.fromisoformat(evento["ultima_mudanca_em"])
                if alterado.tzinfo and alterado <= instante:
                    mudanca = max(mudanca, alterado)
                estado = evento.get("situacao")
                if estado in {"pronto", "com_erro"}:
                    categoria = "prontos" if estado == "pronto" else "com_erro"
                elif estado == "em_execucao":
                    validade = dt.datetime.fromisoformat(evento["valido_ate"])
                    if validade.tzinfo and instante <= validade <= instante + dt.timedelta(seconds=LEASE_S):
                        categoria = "em_execucao"
                        validade_resumo = min(validade_resumo, validade)
        except (OSError, ValueError, TypeError, KeyError):
            pass
        contagens[categoria] += 1
    return {
        "versao": 1, "escopo": "unidade", "unidade": ctx["unidade"], "municipios_total": len(set(cods)),
        "municipios": contagens, "observado_em": instante.isoformat(),
        "ultima_mudanca_em": min(mudanca, instante).isoformat(),
        "valido_ate": validade_resumo.isoformat(),
        "fontes": ["eventos_privados_do_executor"],
    }  # fmt: skip


def encerrar(ctx: dict) -> None:
    """O pai sabe que o pool terminou; não aguarda lease de filhos interrompidos."""
    for arquivo in ctx["pasta"].glob("*.json"):
        try:
            evento = json.loads(arquivo.read_text())
            if evento.get("execucao") == ctx["execucao"] and evento.get("situacao") == "em_execucao":
                instante = agora().isoformat()
                evento.update(situacao="interrompido", observado_em=instante, valido_ate=instante,
                              ultima_mudanca_em=instante)  # fmt: skip
                _gravar(ctx, evento["municipio"], evento)
        except (OSError, ValueError, KeyError, TypeError):
            continue


def eventos_publicos(ctx: dict, cods: list[int], prontos: set[int]) -> list[dict]:
    """Whitelist municipal. `prontos` são os comprovados antes desta execução, imutáveis."""
    if not ctx["run"].isdigit():
        return []
    instante = agora()
    novos = []
    for cod in sorted(set(cods)):
        if not re.fullmatch(r"\d{7}", str(cod)):
            continue
        estado = (
            "pronto" if cod in prontos else "desconhecido" if cod in ctx.get("nao_comprovados", set()) else "pendente"
        )
        observado = instante
        alterado = dt.datetime.fromisoformat(ctx["inicio"])
        validade = instante + dt.timedelta(seconds=LEASE_S)
        arquivo = ctx["pasta"] / f"{cod}.json"
        if arquivo.exists() and cod not in prontos:
            estado = "desconhecido"
            try:
                evento = json.loads(arquivo.read_text())
                if evento["execucao"] == ctx["execucao"] and evento["municipio"] == cod:
                    observado = dt.datetime.fromisoformat(evento["observado_em"])
                    alterado = dt.datetime.fromisoformat(evento["ultima_mudanca_em"])
                    validade = dt.datetime.fromisoformat(evento["valido_ate"])
                    if (
                        not all(t.tzinfo for t in (observado, alterado, validade))
                        or not alterado <= observado <= validade
                    ):
                        raise ValueError
                    candidato = evento["situacao"]
                    if candidato in {"pronto", "com_erro"} or (candidato == "em_execucao" and instante <= validade):
                        estado = candidato
            except (OSError, ValueError, TypeError, KeyError):
                observado = alterado = instante
                validade = instante + dt.timedelta(seconds=LEASE_S)
        if estado == "desconhecido":
            observado = instante
            alterado = min(alterado, instante)
            validade = instante + dt.timedelta(seconds=LEASE_S)
        novos.append(
            {
                "cod_ibge": str(cod),
                "situacao": estado,
                "unidade": ctx["unidade"],
                "run_id": ctx["run"],
                "run_attempt": int(ctx["tentativa"]),
                "observado_em": observado.isoformat(),
                "ultima_mudanca_em": alterado.isoformat(),
                "valido_ate": validade.isoformat(),
            }
        )
    return novos
