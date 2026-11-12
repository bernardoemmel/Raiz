"""Identidade automática da extração e da calibração, independente de bumps manuais."""

from __future__ import annotations

import hashlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

PASTA_RAIZ = Path(__file__).resolve().parents[2]
FONTES_EXTRACAO = (
    "documentos/certidao/proveniencia.py",
    "documentos/certidao/cache.py",
    "documentos/certidao/leitor.py",
    "documentos/certidao/esquema.py",
    "documentos/certidao/regras.py",
    "documentos/esquemas.py",
    "documentos/claude.py",
    "documentos/privacidade.py",
    "privacidade.py",
)


def _hash(valor: dict) -> str:
    bruto = json.dumps(valor, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(bruto).hexdigest()


def receita_hash() -> str:
    """Hash dos bytes do código e versões que podem mudar a leitura ou seu escore.

    Caminhos são relativos ao pacote, portanto o mesmo build funciona em outro
    servidor. Não lê configuração privada, PDF, ambiente, caminho absoluto ou .env.
    """
    return _hash(
        dict(
            fontes={p: hashlib.sha256((PASTA_RAIZ / p).read_bytes()).hexdigest() for p in FONTES_EXTRACAO},
            dependencias={p: version(p) for p in ("anthropic", "pypdf")},
            python=list(sys.version_info[:3]),
        )
    )


def calibrador_hash(*, risco: float, confianca: float, cortes: list[float]) -> str:
    """Trocar MAPIE ou sua base numérica exige recalibrar mesmo com os mesmos gabaritos."""
    return _hash(
        dict(
            receita=receita_hash(),
            gabaritos_codigo=hashlib.sha256((PASTA_RAIZ / "documentos/aprendizado.py").read_bytes()).hexdigest(),
            dependencias={p: version(p) for p in ("mapie", "scikit-learn", "numpy", "scipy")},
            risco=risco,
            confianca=confianca,
            cortes=cortes,
            objetivo="precision",
            escolha="predicted_positive_fraction",
            ajuste="bonferroni",
        )
    )
