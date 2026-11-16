"""Rota da cascata (E7 passo 10): o que pode ir ao modelo local e o corte de confiança de cada tarefa.

    from raiz.modelos.rota import politica, cortes, cabe_no_local
    ok, motivo = cabe_no_local(pedido, politica())

O Qwen3-4B só faz classificação curta: saída com poucos campos, todos de lista fechada (enum) ou sim/não, resposta
curta e sem chamada de ferramenta. Tarefa que não cabe vai para a nuvem (Haiku, e o Sonnet de reserva).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

from raiz import RAIZ_REPO
from raiz.modelos.base import Pedido

PASTA = RAIZ_REPO / "raiz" / "regras" / "padroes"
POLITICA = PASTA / "cascata.yaml"
CORTES = PASTA / "cascata_cortes.yaml"


@lru_cache(maxsize=8)
def _ler(caminho: str, _mtime: int) -> dict:
    bruto = Path(caminho).read_bytes()
    d = yaml.safe_load(bruto) or {}
    d["versao"] = f"{d.get('nome', Path(caminho).stem)}+{hashlib.sha256(bruto).hexdigest()[:8]}"
    return d


def _carregar(p: Path) -> dict:
    return _ler(str(p), p.stat().st_mtime_ns)


def politica(caminho: Path | None = None) -> dict:
    return _carregar(Path(caminho or POLITICA))


def cortes(caminho: Path | None = None) -> dict:
    """{"versao": ..., "cortes": {tarefa: {"corte": 0.83, ...}}}; sem arquivo, nenhum corte."""
    p = Path(caminho or CORTES)
    if not p.exists():
        return {"versao": "sem-cortes", "cortes": {}}
    d = _carregar(p)
    d["cortes"] = d.get("cortes") or {}
    return d


def tipo_do_campo(sub: dict) -> str:
    if "enum" in sub:
        return "enum"
    t = sub.get("type")
    return t if isinstance(t, str) else "outro"


def cabe_no_local(pedido: Pedido, pol: dict) -> tuple[bool, str]:
    """Se o pedido é classificação curta (vai ao Qwen) e, se não, por quê."""
    regra = pol.get("local") or {}
    if pedido.tarefa in set(regra.get("so_nuvem") or []):
        return False, "tarefa marcada só para a nuvem"
    if pedido.ferramentas > 0:
        return False, f"{pedido.ferramentas} chamada(s) de ferramenta"
    if pedido.max_tokens > int(regra.get("max_tokens", 400)):
        return False, f"resposta longa (max_tokens {pedido.max_tokens})"
    if len(pedido.sistema) + len(pedido.mensagem) > int(regra.get("max_caracteres_entrada", 4000)):
        return False, "entrada longa"
    esq = pedido.esquema or {}
    props = esq.get("properties") or {}
    if esq.get("type") != "object" or not props:
        return False, "saída não é um objeto com campos"
    if len(props) > int(regra.get("max_campos", 6)):
        return False, f"{len(props)} campos na saída"
    aceitos = set(regra.get("campos_aceitos") or ["enum", "boolean"])
    for nome, sub in props.items():
        if tipo_do_campo(sub) not in aceitos:
            return False, f"campo {nome} não é de lista fechada nem sim/não"
    return True, "classificação curta"


def corte_da_tarefa(tarefa: str, cs: dict, modelo: str | None = None) -> float | None:
    """Corte calibrado da tarefa. Se os cortes foram calibrados com outro modelo local, não valem (None)."""
    if modelo and cs.get("modelo_local") and cs["modelo_local"] != modelo:
        return None
    c = (cs.get("cortes") or {}).get(tarefa)
    if isinstance(c, dict):
        c = c.get("corte")
    return None if c is None else float(c)
