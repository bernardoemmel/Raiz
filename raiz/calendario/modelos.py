"""Contrato único da coleta, do banco, da API e do feed. Texto de edital nunca é persistido."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from raiz.privacidade import cnpj_valido, cpf_valido, mascarar
from raiz.qualidade_calendario import validar_url_publica

Tipo = Literal[
    "leilao_imovel",
    "penhora",
    "edital_bndes",
    "profloresta",
    "fundo_amazonia",
    "concessao",
    "leilao_credito",
    "sbce",
    "verra",
    "icvcm",
    "sbti",
    "eudr",
]

TITULOS = {
    "leilao_imovel": "Leilão de imóvel rural",
    "penhora": "Penhora de imóvel rural",
    "edital_bndes": "Edital do BNDES",
    "profloresta": "ProFloresta+",
    "fundo_amazonia": "Fundo Amazônia",
    "concessao": "Concessão florestal",
    "leilao_credito": "Leilão de créditos de carbono",
    "sbce": "SBCE",
    "verra": "Verra",
    "icvcm": "ICVCM",
    "sbti": "SBTi",
    "eudr": "EUDR",
}
MARCOS = {
    "evento": "data do evento",
    "propostas": "entrega de propostas",
    "inscricoes": "inscrições",
    "consulta": "fim da consulta",
    "vigencia": "início da aplicação",
    "penhora": "registro da penhora",
}
UFS = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
CAR = re.compile(r"\b([A-Z]{2})[-.\s]?(\d{7})[-.\s]?((?:[A-F0-9][.\s]?){32})(?![A-F0-9])", re.I)
SIGEF = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def normalizar_car(codigo: str) -> str:
    m = CAR.fullmatch(codigo.strip())
    if not m or m[1].upper() not in UFS:
        raise ValueError("código do CAR inválido")
    return f"{m[1].upper()}-{m[2]}-{re.sub(r'[^A-F0-9]', '', m[3].upper())}"


def url_publica(url: str) -> str:
    """Recusa documento, contato e credencial antes de persistir o link ou expô-lo.

    O coletor e a importação conferem o host contra a fonte do manifesto. Aqui
    aplica-se a mesma validação de privacidade do Release, inclusive codificação
    repetida, nomes de parâmetros e fragmentos, sem depender do front.
    """
    host = urlsplit(url).hostname
    return validar_url_publica(url, [host] if host else [])


class Evento(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    id: str = Field(pattern=r"^[a-f0-9]{24}$")
    tipo: Tipo
    marco: Literal["evento", "propostas", "inscricoes", "consulta", "vigencia", "penhora"] = "evento"
    referencia: str | None = None
    data: dt.date
    prazo: dt.date | None = None
    uf: str | None = None
    municipio: str | None = Field(default=None, pattern=r"^\d{7}$")
    codigos_car: list[str] = Field(default_factory=list)
    fonte_id: str = Field(pattern=r"^[a-z0-9_]+$")
    fonte_nome: str
    fonte_url: str
    # Documento público ligado ao mesmo bem, quando o CAR está no anexo e não no aviso.
    car_fonte_url: str | None = Field(default=None, max_length=2048)
    coletado_em: dt.datetime
    confianca: float = Field(ge=0, le=1)
    situacao: Literal["previsto", "cancelado", "adiado"] = "previsto"
    # Só identificadores de imóvel; nunca o titular, CPF/CNPJ ou texto bruto.
    cns: str | None = Field(default=None, pattern=r"^\d{6}$")
    matricula: str | None = Field(default=None, pattern=r"^[0-9A-Z]{1,25}$")
    sigef: list[str] = Field(default_factory=list)
    vinculo: Literal["car", "cns_matricula", "sigef", "pendente"] = "pendente"
    sequencia: int = Field(default=0, ge=0)
    atualizado_em: dt.datetime | None = None

    @field_validator("fonte_url", "car_fonte_url")
    @classmethod
    def validar_url(cls, v):
        return url_publica(v) if v is not None else None

    @field_validator("uf")
    @classmethod
    def validar_uf(cls, v):
        if v is not None and v not in UFS:
            raise ValueError("UF inválida")
        return v

    @field_validator("referencia")
    @classmethod
    def validar_referencia(cls, v):
        if v and not re.fullmatch(r"\d{1,5}(?:[/.-]\d{1,4}){0,3}", v):
            raise ValueError("referência deve conter só o número do edital")
        if v and (mascarar(v) != v or cpf_valido(v) or cnpj_valido(v)):
            raise ValueError("referência não pode conter documento pessoal")
        return v

    @field_validator("codigos_car")
    @classmethod
    def validar_car(cls, v):
        return sorted({normalizar_car(x) for x in v})

    @field_validator("sigef")
    @classmethod
    def validar_sigef(cls, v):
        if any(not SIGEF.fullmatch(x) for x in v):
            raise ValueError("parcela SIGEF inválida")
        return sorted({x.lower() for x in v})

    @field_validator("coletado_em", "atualizado_em")
    @classmethod
    def validar_instante(cls, v):
        if v is not None and v.tzinfo is None:
            raise ValueError("instante precisa de fuso horário")
        return v

    @model_validator(mode="after")
    def conferir(self):
        if self.prazo and self.prazo < self.data:
            raise ValueError("prazo anterior ao início")
        if self.car_fonte_url and (not self.codigos_car or self.vinculo not in ("car", "pendente")):
            raise ValueError("fonte pública do CAR exige código explícito no documento")
        return self

    @property
    def titulo(self) -> str:
        ref = f", edital {self.referencia}" if self.referencia else ""
        return f"{TITULOS[self.tipo]}: {MARCOS[self.marco]}{ref}"

    @property
    def dia(self) -> dt.date:
        return self.prazo or self.data

    @property
    def codigos_car_publicos(self) -> list[str]:
        # Só o CAR explícito no ato público. Enriquecimento de título/SIGEF
        # pertence aos pedidos e à ficha autenticada, nunca ao calendário aberto.
        return self.codigos_car if self.vinculo in ("car", "pendente") else []

    def publico(self) -> dict:
        d = self.model_dump(mode="json", exclude={"cns", "matricula", "sigef"})
        return {
            **d,
            "titulo": self.titulo,
            "codigos_car": self.codigos_car_publicos,
            "car_fonte_url": self.car_fonte_url if self.codigos_car_publicos else None,
            "vinculo": "car" if self.codigos_car_publicos else "pendente",
        }


def identificador(fonte_id: str, url: str, tipo: str, chave: str) -> str:
    """Data fica fora da identidade: retificação muda SEQUENCE, não duplica o evento."""
    return hashlib.sha256(f"{fonte_id}|{url}|{tipo}|{chave}".encode()).hexdigest()[:24]


class FonteEstado(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    nome: str
    coletado_em: dt.datetime
    situacao: Literal["ok", "parcial", "erro", "sem_data"]
    erro: str | None = None
    paginas: int = 0
    eventos: int = 0
    sem_data: int = 0


def filtrar(eventos: list[Evento], *, tipo=None, estado=None, inicio=None, fim=None, cod_imovel=None):
    if tipo is not None and tipo not in TITULOS:
        raise ValueError("tipo de evento inválido")
    if estado is not None and estado not in UFS:
        raise ValueError("estado inválido")
    if inicio and fim and inicio > fim:
        raise ValueError("início posterior ao fim")
    cod = normalizar_car(cod_imovel) if cod_imovel else None
    return sorted(
        (
            e
            for e in eventos
            if (tipo is None or e.tipo == tipo)
            and (estado is None or e.uf in (estado, None))
            and (cod is None or cod in e.codigos_car_publicos)
            and (inicio is None or e.dia >= inicio)
            and (fim is None or e.dia <= fim)
        ),
        key=lambda e: (e.dia, e.id),
    )
