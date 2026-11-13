"""Contrato fechado da pasta: fatos da terra, nunca pessoas ou modelos executáveis."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Codigo = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,119}$")]
Hash = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Car = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}-[0-9]{7}-[A-F0-9]{32}$")]
Numero = Annotated[Decimal, Field(allow_inf_nan=False, max_digits=24, decimal_places=8)]
TipoDocumento = Literal["titularidade", "garantia", "area_elegivel", "previsao", "preco", "dispensa", "complementar"]
Metodo = Literal["regeneracao_assistida", "semeadura_direta", "plantio_total", "agrofloresta", "silvipastoril"]


class Fechado(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Documento(Fechado):
    id: UUID
    tipo: TipoDocumento
    referencia: Annotated[str, StringConstraints(pattern=r"^DOC-[A-F0-9]{12,64}$")]
    sha256: Hash | None = None
    emitido_em: dt.date | None = None
    valido_ate: dt.date | None = None
    sem_vencimento: bool = False
    conferido_em: dt.datetime | None = None
    estado: Literal["apresentado", "conferido", "dispensado", "substituido", "revogado"] = "apresentado"
    substituido_por: UUID | None = None
    dispensa_documento_id: UUID | None = None
    motivo: Literal["nao_aplicavel", "exigencia_alternativa", "correcao", "nova_via", "revogacao"] | None = None

    @field_validator("conferido_em")
    @classmethod
    def com_fuso(cls, valor):
        if valor is not None and valor.tzinfo is None:
            raise ValueError("Conferência exige data com fuso")
        return valor


class FonteCampo(Fechado):
    documento_id: UUID
    # Localizador fechado: não recebe comentário, URL, credencial ou texto da certidão.
    localizador: Annotated[
        str,
        StringConstraints(
            pattern=r"^(pagina:[1-9][0-9]{0,4}|campo:(area|titularidade|garantia|preco|periodo|modelo|p10|p50|p90))$"
        ),
    ]
    data_referencia: dt.date


class Medida(Fechado):
    valor: Numero | None = None
    unidade: Literal["ha", "tCO2e", "%"]
    natureza: Literal["realizado", "estimado"]
    fontes: list[FonteCampo] = Field(default_factory=list, max_length=20)


class Periodo(Fechado):
    inicio: dt.date
    fim: dt.date

    @model_validator(mode="after")
    def ordenado(self):
        if self.fim < self.inicio:
            raise ValueError("Período invertido")
        return self


class Preco(Fechado):
    valor: Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=24, decimal_places=8)] | None = None
    moeda: Literal["BRL", "USD", "EUR"] | None = None
    unidade: Literal["ha", "tCO2e", "lote"] | None = None
    periodo: Periodo | None = None
    natureza: Literal["realizado", "estimado"] | None = None
    fontes: list[FonteCampo] = Field(default_factory=list, max_length=20)


class CreditoMetodo(Fechado):
    metodo: Metodo
    area: Medida | None = None
    p10: Medida | None = None
    p50: Medida | None = None
    p90: Medida | None = None
    periodo: Periodo | None = None
    modelo_versao: Codigo | None = None
    fontes: list[FonteCampo] = Field(default_factory=list, max_length=20)
    # Identidade da série é estável; cada revisão persistida recebe referência própria.
    previsao_id: UUID


class Titulo(Fechado):
    nivel: Literal["nao_verificado", "cadastro", "documento_apresentado", "conferencia_concluida"]
    situacao: Literal["pendente", "conferida", "contestada", "cancelada"]
    fontes: list[FonteCampo] = Field(default_factory=list, max_length=20)


class Garantia(Fechado):
    situacao: Literal["pendente", "conferida", "recusada"]
    fontes: list[FonteCampo] = Field(default_factory=list, max_length=20)


class ImovelPasta(Fechado):
    codigo_car: Car
    area_elegivel: Medida | None = None
    titulo: Titulo | None = None
    garantia: Garantia | None = None
    creditos: list[CreditoMetodo] = Field(default_factory=list, max_length=5)
    preco: Preco | None = None


class Pasta(Fechado):
    pedido_id: UUID
    opcao: Literal["barata", "segura", "compacta"]
    data_corte: dt.date
    documentos: list[Documento] = Field(default_factory=list, max_length=10000)
    imoveis: list[ImovelPasta] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def identidades_unicas(self):
        if len({d.id for d in self.documentos}) != len(self.documentos):
            raise ValueError("Documento repetido")
        if len({i.codigo_car for i in self.imoveis}) != len(self.imoveis):
            raise ValueError("CAR repetido")
        for imovel in self.imoveis:
            if len({m.metodo for m in imovel.creditos}) != len(imovel.creditos):
                raise ValueError("Método repetido no imóvel")
        ids = [m.previsao_id for i in self.imoveis for m in i.creditos]
        if len(set(ids)) != len(ids):
            raise ValueError("Identidade de previsão repetida")
        return self


class Retificacao(Fechado):
    tipo: Literal["inclusao", "correcao", "substituicao", "retirada", "nova_previsao"]
    motivo: Literal["entrada_conferida", "erro_material", "documento_atualizado", "perda_validade", "modelo_atualizado"]
    versao_anterior_id: UUID | None = None
    dados: Pasta
