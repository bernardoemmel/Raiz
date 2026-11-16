"""Teste próprio em português e calibração do corte de confiança da cascata (E7 passo 10).

    from raiz.modelos.avaliacao import carregar, avaliar, resumo, calibrar
    meta, tarefas = carregar()                       # 120 tarefas, 15% sem resposta válida
    linhas = avaliar(modelo, tarefas, tentativas=3)  # 3 tentativas seguidas por tarefa
    resumo(linhas)                                   # acerto, acerto nas 3, consistência, abstenção, custo
    calibrar(linhas)                                 # corte por tarefa: 20 a 30% menos confiantes sobem

Cada tarefa usa o prompt de produção do agente de aceite. O relatório guarda a versão do banco, o modelo que
respondeu e cada resposta, para comparar versões do modelo e do prompt (a Raíz aprende com os próprios erros).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from raiz.modelos.base import Modelo, Pedido, Resposta
from raiz.privacidade import mascarar

BANCO = Path(__file__).with_name("banco.yaml")
CAMPOS_EXPLICACAO = ("entendeu_area", "entendeu_prazo", "entendeu_pagamento", "desistiu")


@dataclass(frozen=True)
class Tarefa:
    id: str
    tarefa: str  # nome da tarefa de produção (aceite.intencao, aceite.explicacao)
    mensagem: str
    esperado: dict
    sem_resposta: bool = False
    proposta: dict | None = None


def carregar(caminho: Path | None = None) -> tuple[dict, list[Tarefa]]:
    bruto = Path(caminho or BANCO).read_bytes()
    d = yaml.safe_load(bruto)
    meta = {"nome": d["nome"], "versao": f"{d['nome']}+{hashlib.sha256(bruto).hexdigest()[:8]}"}
    tarefas: list[Tarefa] = []
    for rotulo, msgs in (d.get("intencao") or {}).items():
        sem = rotulo == "sem_resposta"
        for k, m in enumerate(msgs, 1):
            tarefas.append(
                Tarefa(
                    f"intencao-{rotulo}-{k:02d}",
                    "aceite.intencao",
                    str(m or ""),
                    {"intencao": "outro" if sem else rotulo},
                    sem,
                )
            )
    for k, e in enumerate(d.get("explicacao") or [], 1):
        bits = str(e["esperado"])
        esperado = {c: b == "1" for c, b in zip(CAMPOS_EXPLICACAO, bits, strict=True)}
        tarefas.append(
            Tarefa(
                f"explicacao-{k:02d}",
                "aceite.explicacao",
                str(e["mensagem"]),
                esperado,
                bool(e.get("sem_resposta")),
                d["propostas"][e["proposta"]],
            )
        )
    return meta, tarefas


def pedido(t: Tarefa) -> Pedido:
    """O mesmo pedido que o agente de aceite manda em produção."""
    from raiz.agentes import aceite

    if t.tarefa == "aceite.intencao":
        return aceite.pedido_intencao(t.mensagem)
    if t.tarefa == "aceite.explicacao":
        return aceite.pedido_explicacao(t.proposta or {}, t.mensagem)
    raise ValueError(f"tarefa sem pedido no teste: {t.tarefa}")


def acertou(t: Tarefa, dados: dict | None) -> bool:
    if not dados:
        return False
    return all(dados.get(k) == v for k, v in t.esperado.items())


def _resposta_curta(t: Tarefa, dados: dict | None) -> str | None:
    if not dados:
        return None
    if t.tarefa == "aceite.intencao":
        return str(dados.get("intencao"))
    return "".join("1" if dados.get(c) else "0" for c in CAMPOS_EXPLICACAO)


def avaliar(
    modelo: Modelo,
    tarefas: list[Tarefa],
    tentativas: int = 3,
    chamar: Callable[[Modelo, Pedido], Resposta] | None = None,
    progresso: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """Roda cada tarefa `tentativas` vezes seguidas. Uma linha por tentativa (sem o texto da mensagem)."""
    from raiz.modelos import chamar as chamar_padrao

    fn = chamar or (lambda m, p: chamar_padrao(m, p, "avaliacao"))
    linhas = []
    for i, t in enumerate(tarefas, 1):
        p = pedido(t)
        for k in range(1, tentativas + 1):
            r = fn(modelo, p)
            linhas.append(
                {
                    "id": t.id,
                    "tarefa": t.tarefa,
                    "tentativa": k,
                    "sem_resposta": t.sem_resposta,
                    "esperado": _resposta_curta(t, t.esperado),
                    "resposta": _resposta_curta(t, r.dados if r.ok else None),
                    "acerto": acertou(t, r.dados if r.ok else None),
                    "confianca": r.confianca,
                    "modelo": r.modelo,
                    "custo_usd": float(r.custo_usd or 0),
                    "duracao_ms": r.duracao_ms,
                    "erro": mascarar(r.erro) if r.erro else ("recusou" if r.recusou else None),
                }
            )
        if progresso:
            progresso(i, len(tarefas))
    return linhas


def _media(xs) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 4) if xs else None


def resumo(linhas: list[dict]) -> dict:
    """Por tarefa: acerto por tentativa, acerto nas 3 tentativas, consistência, abstenção e custo."""
    por: dict[str, list[dict]] = defaultdict(list)
    for r in linhas:
        por[r["tarefa"]].append(r)
    out = {}
    for tarefa, rs in sorted(por.items()):
        por_id: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            por_id[r["id"]].append(r)
        sem = [r for r in rs if r["sem_resposta"]]
        com = [r for r in rs if not r["sem_resposta"]]
        out[tarefa] = {
            "tarefas": len(por_id),
            "respostas": len(rs),
            "acerto": _media(r["acerto"] for r in rs),
            "acerto_com_resposta": _media(r["acerto"] for r in com),
            # o modelo disse que não sabe quando não havia resposta válida
            "abstencao_correta": _media(r["acerto"] for r in sem),
            "acerto_nas_tentativas": _media(all(x["acerto"] for x in v) for v in por_id.values()),
            "consistencia": _media(len({x["resposta"] for x in v}) == 1 for v in por_id.values()),
            "falhas": sum(1 for r in rs if r["erro"]),
            "custo_usd": round(sum(r["custo_usd"] for r in rs), 6),
            "duracao_ms_mediana": int(statistics.median([r["duracao_ms"] for r in rs])) if rs else None,
            "com_confianca": sum(1 for r in rs if r["confianca"] is not None),
        }
    return out


def calibrar(
    linhas: list[dict],
    faixa: tuple[float, float] = (0.20, 0.30),
    acerto_minimo: float = 0.95,
    minimo: int = 30,
) -> dict:
    """Corte de confiança por tarefa. Abaixo do corte (ou sem resposta válida) a pergunta sobe de modelo.

    Entre os cortes que fazem subir de 20 a 30% das respostas, fica o de maior acerto nas respostas que não sobem
    (empate: o que sobe menos). Sem corte na faixa que chegue ao acerto mínimo, a tarefa fica na votação A+B."""
    por: dict[str, list[dict]] = defaultdict(list)
    for r in linhas:
        por[r["tarefa"]].append(r)
    out = {}
    for tarefa, rs in sorted(por.items()):
        n = len(rs)
        validas = sorted(
            (r["confianca"], bool(r["acerto"])) for r in rs if r["confianca"] is not None and not r["erro"]
        )
        base = {"respostas": n, "acerto_do_modelo": _media(r["acerto"] for r in rs)}
        if n < minimo or not validas:
            motivo = f"poucas respostas ({n} < {minimo})" if n < minimo else "sem confiança nas respostas (logprobs)"
            out[tarefa] = {**base, "corte": None, "motivo": motivo}
            continue
        candidatos = []
        for c in sorted({v for v, _ in validas}):
            ficam = [ok for v, ok in validas if v >= c]
            sobe = (n - len(ficam)) / n
            candidatos.append((c, sobe, sum(ficam) / len(ficam) if ficam else 0.0))
        na_faixa = [x for x in candidatos if faixa[0] <= x[1] <= faixa[1]]
        if na_faixa:
            c, sobe, acc = max(na_faixa, key=lambda x: (x[2], -x[1]))
        else:  # os empates de confiança pulam a faixa: o primeiro corte que sobe ao menos o mínimo da faixa
            acima = [x for x in candidatos if x[1] >= faixa[0]]
            if not acima:
                out[tarefa] = {**base, "corte": None, "motivo": "nenhum corte faz subir o mínimo da faixa"}
                continue
            c, sobe, acc = min(acima, key=lambda x: x[1])
        info = {**base, "subida": round(sobe, 4), "acerto_que_fica": round(acc, 4), "corte_achado": round(c, 6)}
        if acc < acerto_minimo:
            out[tarefa] = {**info, "corte": None, "motivo": f"acerto que fica {acc:.0%} abaixo de {acerto_minimo:.0%}"}
        elif sobe > faixa[1]:
            out[tarefa] = {**info, "corte": None, "motivo": f"o menor corte possível sobe {sobe:.0%}, acima da faixa"}
        else:
            out[tarefa] = {**info, "corte": round(c, 6), "motivo": None}
    return out


def relatorio(meta: dict, modelo: Modelo, linhas: list[dict], tentativas: int) -> dict:
    return {
        "banco": meta["versao"],
        "modelo": modelo.nome,
        "provedor": modelo.provedor,
        "tentativas": tentativas,
        "rodado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "resumo": resumo(linhas),
        "linhas": linhas,
    }


def gravar_relatorio(rel: dict, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    nome = "".join(ch if ch.isalnum() or ch in "-." else "_" for ch in rel["modelo"])
    arq = pasta / f"{rel['rodado_em'][:19].replace(':', '')}_{nome}.json"
    arq.write_text(json.dumps(rel, ensure_ascii=False, indent=1))
    return arq


def gravar_cortes(cal: dict, rel: dict, politica_versao: str, caminho: Path) -> dict:
    """Escreve os cortes que passaram (tarefa sem corte fica de fora e segue na votação)."""
    cortes = {
        t: {k: v for k, v in c.items() if k not in ("motivo",)} for t, c in cal.items() if c.get("corte") is not None
    }
    doc = {
        "nome": "cortes",
        "gerado_em": rel["rodado_em"],
        "modelo_local": rel["modelo"],
        "banco": rel["banco"],
        "politica": politica_versao,
        "cortes": cortes,
    }
    cab = (
        "# Cortes de confiança da cascata, gerados por `raiz modelos calibrar` com o teste próprio em português\n"
        "# (raiz/modelos/avaliacao/banco.yaml) rodado no modelo local de verdade. Não editar à mão.\n"
        "# Tarefa sem corte fica na votação A+B (Qwen e Haiku), como antes.\n"
    )
    caminho.write_text(cab + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
    return doc
