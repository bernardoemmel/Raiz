"""Regras versionadas da vigilância (regras.yaml).

A versão é o nome da regra mais os 8 primeiros caracteres do sha256 do arquivo (ex.: vigilancia-2026.11a+1a2b3c4d).
Ela é gravada em cada alerta, marcação automática e evento de perda, para comparar depois o acerto de cada versão.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from raiz.vigilancia import PASTA

ARQUIVO = PASTA / "regras.yaml"


@dataclass(frozen=True)
class Regras:
    dados: dict
    versao: str

    def __getitem__(self, k: str):
        return self.dados[k]

    def get(self, k: str, padrao=None):
        return self.dados.get(k, padrao)

    def fonte(self, nome: str) -> dict:
        return self.dados.get("fontes", {}).get(nome, {})

    @property
    def verra(self) -> dict:
        return self.dados["verra"]

    def tipo(self, fonte: str, classe: str | None) -> str:
        """Tipo do alerta (desmatamento, degradacao, fogo, embargo) pela classe da fonte."""
        t = self.dados.get("tipos", {})
        if classe and classe in t.get(fonte, {}):
            return t[fonte][classe]
        return t.get("padrao", {}).get(fonte, "desmatamento")

    def prior(self, estrato: str) -> tuple[float, float]:
        c = self.dados.get("confianca_inicial", {})
        a, b = c.get(estrato) or c.get("padrao") or (1, 1)
        return float(a), float(b)


def carregar(caminho: str | os.PathLike | None = None) -> Regras:
    p = Path(caminho or os.environ.get("RAIZ_VIGILANCIA_REGRAS") or ARQUIVO)
    return _carregar(str(p.resolve()), p.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _carregar(caminho: str, _mtime: int) -> Regras:
    bruto = Path(caminho).read_bytes()
    dados = yaml.safe_load(bruto)
    versao = f"{dados['nome']}+{hashlib.sha256(bruto).hexdigest()[:8]}"
    return Regras(dados=dados, versao=versao)
