"""Premissas do pedido de lote (raiz/regras/padroes/pedidos.yaml), com versão + hash, como as do valor para quem
restaura. A versão do modelo de um lote sugerido junta as duas."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import yaml

ARQ = Path(__file__).resolve().parents[1] / "regras" / "padroes" / "pedidos.yaml"


@lru_cache
def _ler(arq: Path, _marca: tuple) -> dict:
    b = arq.read_bytes()
    p = yaml.safe_load(b)
    p["versao_completa"] = f"{p['versao']}+{hashlib.sha256(b).hexdigest()[:8]}"
    return p


def premissas(arq: Path | None = None) -> dict:
    arq = Path(arq or ARQ)
    st = arq.stat()
    return _ler(arq, (st.st_mtime_ns, st.st_size))


def versao_modelo() -> str:
    """Versão das premissas do pedido, do otimizador e do valor para quem restaura (guardada em cada sugestão)."""
    from raiz import restauracao as R

    p = premissas()
    return f"{p['versao_completa']}+{p['otimizador']['versao']}+{R.versao()}"
