"""Entradas fechadas: sem texto livre, identificação civil ou contato de proprietário."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Positivo = Annotated[FiniteFloat, Field(gt=0)]
NaoNegativo = Annotated[FiniteFloat, Field(ge=0)]
Municipio = Annotated[int, Field(ge=1000000, le=9999999)]
Porte = Literal["pequena", "media", "grande"]
Aptidao = Literal["baixa", "media", "alta"]


class Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Estrato(Contrato):
    municipio: Municipio
    porte: Porte
    aptidao: Aptidao

    @property
    def chave(self) -> tuple:
        return self.municipio, self.porte, self.aptidao


class PrevisaoCarbono(Contrato):
    caso_id: UUID
    modelo_sha256: Hash
    entradas_sha256: Hash
    receita_sha256: Hash
    tipo: Literal["ao_vivo", "backtest"] = "ao_vivo"
    emitida_em: AwareDatetime
    decisao_em: AwareDatetime
    entradas_disponiveis_em: AwareDatetime
    horizonte_em: AwareDatetime
    unidade: Literal["tco2e_ha_ano"] = "tco2e_ha_ano"
    sorteios: Annotated[tuple[FiniteFloat, ...], Field(min_length=2, max_length=100000)]

    @model_validator(mode="after")
    def tempo(self):
        if not (
            self.entradas_disponiveis_em <= self.decisao_em < self.horizonte_em
            and self.emitida_em >= self.decisao_em
            and (self.tipo == "backtest" or self.emitida_em < self.horizonte_em)
        ):
            raise ValueError("cronologia da previsão inválida")
        return self


class GabaritoCego(Contrato):
    caso_id: UUID
    estrato: Estrato
    unidade: Literal["tco2e_ha_ano"] = "tco2e_ha_ano"
    valor: FiniteFloat
    incerteza_padrao: NaoNegativo
    horizonte_em: AwareDatetime
    medido_em: AwareDatetime
    registrado_em: AwareDatetime
    revelado_em: AwareDatetime
    laboratorio_id: UUID
    amostra_cega_id: UUID
    procedimento_sha256: Hash
    evidencia_sha256: Hash
    metodo: Literal["campo_independente", "laboratorio_independente"]
    controle_id: UUID

    @model_validator(mode="after")
    def tempo(self):
        if not self.horizonte_em <= self.medido_em <= self.registrado_em <= self.revelado_em:
            raise ValueError("cronologia do gabarito inválida")
        return self


class Inclusao(Contrato):
    caso_id: UUID
    decisao_id: UUID
    municipio: Municipio
    modulos_fiscais: Positivo
    aptidao: Aptidao
    entrou: bool = Field(strict=True)

    @property
    def porte(self) -> Porte:
        return "pequena" if self.modulos_fiscais <= 4 else "media" if self.modulos_fiscais <= 15 else "grande"


class Tolerancia(Contrato):
    estrato: Estrato
    minimo: int = Field(ge=2)
    aumento_crps_max: NaoNegativo
    crps_max: NaoNegativo


class PlanoMudanca(Contrato):
    plano_id: UUID
    fixado_em: AwareDatetime
    inicio_treino_em: AwareDatetime
    modelo_anterior_sha256: Hash
    receita_candidata_sha256: Hash
    previsoes_anteriores_sha256: Hash
    conjunto_cego_sha256: Hash
    controle_sha256: Hash
    politica_equidade_sha256: Hash
    coorte_inclusao_sha256: Hash
    mudancas: Annotated[tuple[Literal["calibracao", "pesos", "variaveis"], ...], Field(min_length=1)]
    tolerancias: Annotated[tuple[Tolerancia, ...], Field(min_length=1)]
    condicao_retorno: Literal["qualquer_subgrupo_ou_controle_fora_da_tolerancia"]

    @model_validator(mode="after")
    def anterior_ao_treino(self):
        if self.fixado_em >= self.inicio_treino_em:
            raise ValueError("plano precisa anteceder o treino de uma versão diferente")
        if len({x.estrato.chave for x in self.tolerancias}) != len(self.tolerancias):
            raise ValueError("tolerância duplicada")
        return self


class ControleEstavel(Contrato):
    controle_id: UUID
    fixado_em: AwareDatetime
    procedimento_sha256: Hash
    referencia_sha256: Hash
    centro: FiniteFloat
    desvio_padrao: Positivo
    multiplicador: Positivo
    minimo_referencia: int = Field(ge=20)
    referencia_n: int = Field(ge=20)

    @model_validator(mode="after")
    def suficiente(self):
        if self.referencia_n < self.minimo_referencia:
            raise ValueError("controle sem referência suficiente")
        return self


class MedicaoControle(Contrato):
    controle_id: UUID
    procedimento_sha256: Hash
    medido_em: AwareDatetime
    valor: FiniteFloat


class MembroFunil(Contrato):
    caso_id: UUID
    estrato: Estrato
    elegibilidade: Literal["elegivel", "inelegivel", "desconhecida"]
    disposicao: Literal["nao_abordado", "incluido", "recusa", "sem_resposta", "perda", "inelegivel"]
    motivo: Literal["nenhum", "titulo", "ambiental", "aptidao", "indisponivel", "desconhecido"]

    @model_validator(mode="after")
    def coerente(self):
        if (self.elegibilidade == "inelegivel") != (self.disposicao == "inelegivel"):
            raise ValueError("inelegibilidade inconsistente")
        if self.disposicao == "incluido" and self.elegibilidade != "elegivel":
            raise ValueError("inclusão sem elegibilidade")
        return self


class FunilFixo(Contrato):
    """Só esquema de contagem. Não consulta, solicita nem guarda contatos."""

    coorte_id: UUID
    fixado_em: AwareDatetime
    corte_em: AwareDatetime
    manifesto_ids_sha256: Hash
    denominador: int = Field(gt=0)
    membros: Annotated[tuple[MembroFunil, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def denominador_fixo(self):
        from raiz.avaliacao.integridade import resumo_hash

        ids = sorted(str(x.caso_id) for x in self.membros)
        if self.fixado_em > self.corte_em or len(ids) != self.denominador or len(set(ids)) != len(ids):
            raise ValueError("coorte ou denominador inválido")
        if resumo_hash(ids) != self.manifesto_ids_sha256:
            raise ValueError("coorte mudou desde a fixação")
        return self


class ObservacaoTemporal(Contrato):
    caso_id: UUID
    evento_em: AwareDatetime
    conhecido_em: AwareDatetime
    entradas_disponiveis_em: AwareDatetime
    entradas_sha256: Hash
    valor: FiniteFloat

    @model_validator(mode="after")
    def cronologia(self):
        if self.conhecido_em < self.evento_em:
            raise ValueError("resultado conhecido antes do evento")
        return self


def instante(valor: datetime) -> datetime:
    if valor.tzinfo is None or valor.utcoffset() is None:
        raise ValueError("data sem fuso")
    return valor
