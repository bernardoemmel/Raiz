"""Reprocessamento progressivo: o site só troca os dados de um estado quando o estado inteiro foi refeito.

Regra (docs/reprocessamento-progressivo.md):
- O site mostra os dados que estão no ar até o estado fechar o reprocessamento com as regras novas.
- "Regras novas" = todas as tarefas do executor (funil, filtros, terra, título, terra já comprometida, ambiental,
  ficha, desenvolvedor...) na versão do código que publica, em TODOS os municípios do estado, sem erro.
- Enquanto o arquivo privado do estado está sendo refeito com versões diferentes das que estão no ar, a projeção
  aberta daquele estado fica congelada: nenhum pacote público do estado é apagado ou trocado.
- Quando fecha (todos os municípios em dia, estado completo e validado), a projeção aberta é trocada de uma vez e o
  estado passa a "atualizado" no reprocessamento.json público.
- Estado que cresce com as MESMAS versões que já estão no ar (o funil de um estado novo avançando) continua
  publicando aos poucos, como antes: não há mistura de regras.

Este módulo não faz rede nem conhece o armazenamento: recebe as marcas e as entradas e devolve a decisão. O armazém
(raiz/executor/armazem.py, ou o que o substituir) chama `avaliar` ao publicar o privado e `decidir` antes de mexer
no aberto.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

ARQUIVO_REGRAS = Path(__file__).with_name("regras_vigentes.json")
NOME_PUBLICO = "reprocessamento.json"
SITUACOES = ("atualizado", "reprocessando", "antigo")
MOTIVOS = (
    "falta_municipio",
    "tarefa_com_erro",
    "tarefa_desatualizada",
    "estado_incompleto",
    "validacao_menos_municipios",
    "sem_avaliacao",
)
_GERACAO = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[a-z0-9.-]{0,20})$")


@lru_cache(maxsize=1)
def regras_vigentes() -> dict:
    """A geração de regras que este código aplica (troque a data ao mudar uma regra de classificação)."""
    dado = json.loads(ARQUIVO_REGRAS.read_text(encoding="utf-8"))
    if not _GERACAO.fullmatch(str(dado.get("geracao", ""))):
        raise ValueError("regras_vigentes.json: geração inválida")
    return dado


def _agora() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def avaliar(
    ler_marca: Callable[[int], dict | None],
    municipios: Iterable[int],
    versoes: dict[str, str],
    completo: bool,
    primeira: str = "funil",
) -> dict:
    """Quantos municípios do estado têm todas as tarefas na versão atual, sem erro.

    ler_marca(cod) devolve a marca do executor (marcas/<UF>/<cod>.json) ou None. Município sem imóvel conta como
    pronto quando a primeira tarefa (funil) rodou na versão atual e ficou vazia."""
    municipios = [int(c) for c in municipios]
    prontos = falta = erro = velho = 0
    for cod in municipios:
        marca = ler_marca(cod)
        if not marca:
            falta += 1
            continue
        tarefas = marca.get("tarefas") or {}
        inicio = tarefas.get(primeira) or {}
        if inicio.get("vazio") and not inicio.get("erro") and inicio.get("versao") == versoes.get(primeira):
            prontos += 1
            continue
        if any((tarefas.get(n) or {}).get("erro") for n in versoes):
            erro += 1
        elif any((tarefas.get(n) or {}).get("versao") != v for n, v in versoes.items()):
            velho += 1
        else:
            prontos += 1
    total = len(municipios)
    atualizado = bool(total) and prontos == total and bool(completo)
    motivo = None
    if not atualizado:
        motivo = (
            "falta_municipio" if falta else
            "tarefa_com_erro" if erro else
            "tarefa_desatualizada" if velho else
            "estado_incompleto"
        )  # fmt: skip
    return {
        "geracao": regras_vigentes()["geracao"],
        "situacao": "atualizado" if atualizado else "reprocessando",
        "prontos": prontos,
        "total": total,
        "motivo": motivo,
        "versoes": dict(sorted(versoes.items())),
        "avaliado_em": _agora(),
    }


def _contagem(entrada: dict | None) -> int:
    e = entrada or {}
    return int(e.get("municipios") or 0) + int(e.get("sem_imoveis") or 0)


def _mesmas_versoes(a: dict | None, b: dict | None) -> bool:
    a, b = a or {}, b or {}
    return a == b  # dois índices antigos sem versões contam como iguais (nada a reprocessar que se saiba)


def decidir(info_privada: dict, entrada_aberta: dict | None, status_aberto: dict | None = None) -> dict:
    """Publicar ou segurar a projeção aberta do estado.

    info_privada: a entrada do estado no índice privado (com "reprocessamento" = resultado de `avaliar`, quando o
    publicador já calcula). entrada_aberta: a entrada do mesmo estado no estados.json público (None se não há nada no
    ar). status_aberto: a entrada do estado no reprocessamento.json público, se houver.

    Devolve {"publicar": bool, "status": {...}} — o status vai para o reprocessamento.json público."""
    av = info_privada.get("reprocessamento") if isinstance(info_privada.get("reprocessamento"), dict) else None
    anterior = status_aberto if isinstance(status_aberto, dict) else {}
    agora = _agora()
    progresso = {"prontos": av["prontos"], "total": av["total"]} if av else {}

    def status(situacao: str, **kw) -> dict:
        s = {"situacao": situacao, **progresso, **kw}
        return {k: v for k, v in s.items() if v is not None}

    no_ar = _contagem(entrada_aberta) > 0
    if av and av.get("situacao") == "atualizado":
        if no_ar and _contagem(info_privada) < _contagem(entrada_aberta):
            # Nunca troca por um conjunto menor do que o que está no ar.
            return {"publicar": False, "status": status(
                "reprocessando", geracao=anterior.get("geracao"), motivo="validacao_menos_municipios",
                desde=anterior.get("desde") or agora)}  # fmt: skip
        return {"publicar": True, "status": status("atualizado", geracao=av.get("geracao"), atualizado_em=agora)}
    if not no_ar:
        # Nada deste estado no ar: publicar aos poucos não apaga nada.
        return {
            "publicar": True,
            "status": status(
                "reprocessando" if av else "antigo",
                motivo=(av or {}).get("motivo"),
                desde=anterior.get("desde") or agora,
            ),
        }
    if _mesmas_versoes(info_privada.get("versoes"), (entrada_aberta or {}).get("versoes")):
        # Mesmas regras do que está no ar: só cresce (funil de estado novo). Mantém o rótulo que já tinha.
        if anterior.get("situacao") == "atualizado":
            return {"publicar": True, "status": {**anterior, **progresso}}
        return {"publicar": True, "status": status("antigo", geracao=anterior.get("geracao"))}
    # Regras diferentes do que está no ar e estado ainda não fechou: segura o aberto.
    # "geracao" continua sendo a das regras que estão no ar (None: regras antigas, anteriores a este controle).
    return {"publicar": False, "status": status(
        "reprocessando", geracao=anterior.get("geracao"), motivo=(av or {}).get("motivo") or "sem_avaliacao",
        desde=anterior.get("desde") if anterior.get("situacao") == "reprocessando" else agora)}  # fmt: skip


# ---------------------------------------------------------------- reprocessamento.json público

CAMPOS_STATUS = {"situacao", "geracao", "prontos", "total", "motivo", "atualizado_em", "desde"}
_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def validar_status_publico(dados: bytes) -> dict:
    """Contrato fechado do reprocessamento.json público: só situação e contagens por UF, nada por imóvel."""
    from raiz.executor.publicacao_aberta import ESCOPO, UF_IBGE, VERSAO_PUBLICACAO

    doc = json.loads(dados)
    if not isinstance(doc, dict) or set(doc) - {"escopo", "versao_publicacao", "gerado_em", "geracao_vigente",
                                                 "estados"}:  # fmt: skip
        raise ValueError("reprocessamento.json: campo desconhecido")
    if doc.get("escopo") != ESCOPO or doc.get("versao_publicacao") != VERSAO_PUBLICACAO:
        raise ValueError("reprocessamento.json sem marca de projeção")
    if not _GERACAO.fullmatch(str(doc.get("geracao_vigente", ""))):
        raise ValueError("reprocessamento.json: geração vigente inválida")
    if "gerado_em" in doc and not _DATA.fullmatch(str(doc["gerado_em"])):
        raise ValueError("reprocessamento.json: data inválida")
    estados = doc.get("estados")
    if not isinstance(estados, dict):
        raise ValueError("reprocessamento.json: estados ausentes")
    for uf, s in estados.items():
        if uf not in UF_IBGE or not isinstance(s, dict) or set(s) - CAMPOS_STATUS:
            raise ValueError("reprocessamento.json: estado com campo desconhecido")
        if s.get("situacao") not in SITUACOES:
            raise ValueError("reprocessamento.json: situação inválida")
        if "geracao" in s and not _GERACAO.fullmatch(str(s["geracao"])):
            raise ValueError("reprocessamento.json: geração inválida")
        if "motivo" in s and s["motivo"] not in MOTIVOS:
            raise ValueError("reprocessamento.json: motivo fora da lista")
        for k in ("prontos", "total"):
            if k in s and (not isinstance(s[k], int) or isinstance(s[k], bool) or s[k] < 0):
                raise ValueError("reprocessamento.json: contagem inválida")
        for k in ("atualizado_em", "desde"):
            if k in s and not _DATA.fullmatch(str(s[k])):
                raise ValueError("reprocessamento.json: data inválida")
    return doc


def montar_status_publico(anterior: dict | None, uf: str, status: dict) -> bytes:
    """Troca só a entrada da UF no documento público, preservando as outras."""
    from raiz.executor.publicacao_aberta import ESCOPO, VERSAO_PUBLICACAO

    estados = dict((anterior or {}).get("estados") or {})
    estados[uf] = {k: v for k, v in status.items() if k in CAMPOS_STATUS}
    doc = {
        "escopo": ESCOPO,
        "versao_publicacao": VERSAO_PUBLICACAO,
        "geracao_vigente": regras_vigentes()["geracao"],
        "gerado_em": _agora(),
        "estados": dict(sorted(estados.items())),
    }
    dados = json.dumps(doc, ensure_ascii=False, indent=1).encode()
    validar_status_publico(dados)
    return dados


def mudou(anterior: dict | None, novo: dict) -> bool:
    """Evita regravar o arquivo público quando só o relógio mudou."""
    ignorar = {"atualizado_em", "desde"}
    a = {k: v for k, v in (anterior or {}).items() if k not in ignorar}
    b = {k: v for k, v in novo.items() if k not in ignorar}
    return a != b


# ---------------------------------------------------------------- acompanhar


def tabela(privado: dict, aberto: dict, status: dict) -> str:
    """Tabela em Markdown para o resumo do Actions e para quem roda `python -m raiz.executor.reprocessamento`."""
    linhas = ["| Estado | No site | Reprocessamento | Municípios em dia | Motivo |", "|---|---|---|---|---|"]
    rotulo = {"atualizado": "regras novas", "reprocessando": "reprocessando", "antigo": "regras antigas"}
    ufs = sorted(set(privado) | set(aberto) | set(status))
    for uf in ufs:
        s = status.get(uf) or {}
        av = (privado.get(uf) or {}).get("reprocessamento") or {}
        no_site = rotulo.get(s.get("situacao"), "regras antigas") if aberto.get(uf) else "nada no ar"
        if s.get("situacao") == "reprocessando" and s.get("geracao"):
            no_site = f"regras de {s['geracao']} (refazendo)"
        prontos = f"{av.get('prontos', '?')}/{av.get('total', '?')}" if av else "—"
        linhas.append(f"| {uf} | {no_site} | {av.get('situacao', 'sem avaliação')} | {prontos} | "
                      f"{av.get('motivo') or s.get('motivo') or ''} |")  # fmt: skip
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    p = argparse.ArgumentParser(description="Situação do reprocessamento estado por estado (só leitura)")
    p.parse_args(argv)
    from raiz.executor.armazem import do_config

    a = do_config()
    privado = a.manifesto(fresco=True).get("estados", {}) if getattr(a, "privado", False) else {}
    aberto_arm = getattr(a, "publico", None) or a
    aberto = aberto_arm.manifesto(fresco=True).get("estados", {})
    status = (getattr(aberto_arm, "status_reprocessamento", lambda: {})() or {}).get("estados", {})
    texto = (f"### Reprocessamento estado por estado (regras {regras_vigentes()['geracao']})\n\n"
             + tabela(privado, aberto, status))  # fmt: skip
    print(texto)
    if caminho := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
