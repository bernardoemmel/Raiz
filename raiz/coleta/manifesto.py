"""Manifesto de camadas (manifesto.yaml): validação e calendário.

O manifesto é a única lista de fontes da Raíz: endereço, recorte, como saber que mudou (sinal), quando olhar
(calendário), licença e se pode entrar em treino. É sincronizado com coleta.fonte a cada `raiz coleta fontes`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator

ARQUIVO = Path(__file__).with_name("manifesto.yaml")
UFS = [
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
]
TIPOS = Literal["wfs", "arcgis", "arquivo", "cog", "api_mapbiomas", "graphql", "sidra", "parquet"]


class Fonte(BaseModel):
    model_config = ConfigDict(extra="allow")  # campos próprios de cada tipo (camada, subtemas, produtos...)

    id: str
    nome: str
    orgao: str
    tipo: TIPOS
    url: str | None
    recorte: Literal["municipio", "uf", "bbox", "brasil"]
    sinal: dict[str, Any]
    calendario: str | dict[str, Any]
    licenca: str
    pode_treinar: bool
    pendente: str | None = None

    @field_validator("pode_treinar")
    @classmethod
    def _licenca_conferida(cls, v: bool, info) -> bool:
        lic = (info.data.get("licenca") or "").lower()
        if v and ("não comercial" in lic or "nao comercial" in lic or "-nc" in lic):
            raise ValueError("licença não comercial não pode entrar em treino")
        return v

    @property
    def ativa(self) -> bool:
        """Sem endereço não há o que coletar (fica só a pendência)."""
        return self.url is not None

    def devida(self, dia: dt.date) -> bool | list[str]:
        """Se a fonte deve ser olhada no dia. Para rodízio de UF, devolve as UFs do dia."""
        cal = self.calendario
        if cal == "diario":
            return True
        if cal == "gatilho_ibge":
            return False  # quem decide é o calendário do IBGE (raiz.coleta.ppm)
        if isinstance(cal, dict):
            if cal.get("rodizio_uf"):
                return ufs_do_dia(dia)
            if "dias_semana" in cal:
                return dia.weekday() in cal["dias_semana"]
            if "meses" in cal:
                return dia.month in cal["meses"] and dia.day == 1
        return False


class Referencia(BaseModel):
    id: str
    nome: str
    licenca: str
    pode_treinar: bool
    uso: str


class Manifesto(BaseModel):
    versao: str
    fontes: list[Fonte]
    referencias: list[Referencia] = []

    def fonte(self, id_: str) -> Fonte:
        for f in self.fontes:
            if f.id == id_:
                return f
        raise KeyError(id_)

    def pode_treinar(self, id_: str) -> bool:
        for x in [*self.fontes, *self.referencias]:
            if x.id == id_:
                return x.pode_treinar
        return False


# Ordem aproximada de número de imóveis no CAR (maior primeiro), para o rodízio repartir a carga: cada dia da semana
# recebe 3 ou 4 UFs, alternando grandes e pequenas. Ajustar quando a coleta tiver as contagens reais.
UFS_POR_TAMANHO = [
    "BA",
    "MG",
    "RS",
    "PR",
    "SP",
    "SC",
    "CE",
    "PE",
    "MA",
    "PA",
    "PI",
    "GO",
    "PB",
    "RO",
    "RN",
    "AL",
    "MT",
    "ES",
    "SE",
    "TO",
    "MS",
    "RJ",
    "AM",
    "AC",
    "RR",
    "AP",
    "DF",
]


def dia_da_uf(uf: str) -> int:
    """Dia fixo da semana de cada UF no rodízio do CAR (0 = segunda)."""
    i = UFS_POR_TAMANHO.index(uf.upper())
    volta, pos = divmod(i, 7)
    return pos if volta % 2 == 0 else 6 - pos  # vai e volta: a maior da 2ª volta cai com a menor da 1ª


def ufs_do_dia(dia: dt.date) -> list[str]:
    return [uf for uf in UFS if dia_da_uf(uf) == dia.weekday()]


def hash_manifesto(arquivo: Path = ARQUIVO) -> str:
    return hashlib.sha256(arquivo.read_bytes()).hexdigest()


@lru_cache
def carregar(arquivo: Path = ARQUIVO) -> Manifesto:
    m = Manifesto.model_validate(yaml.safe_load(arquivo.read_text(encoding="utf-8")))
    ids = [f.id for f in m.fontes]
    if len(ids) != len(set(ids)):
        raise ValueError("id de fonte repetido no manifesto")
    return m
