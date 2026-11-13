"""Séries privadas da ficha: fatos documentados e previsão pareada, nunca valores inventados.

Não há série de emissão/entrega no banco atual. O arquivo autenticado pode fornecer
este subcontrato quando houver evidência. Ausência continua nula, não vira zero.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identificador = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:+/-]{0,119}$")]
Numero = Annotated[float, Field(ge=0)]
Dia = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


def _dia(valor: str) -> dt.date:
    return dt.date.fromisoformat(valor)


def _instante(valor: str) -> dt.datetime:
    instante = dt.datetime.fromisoformat(valor)
    if "T" not in valor or instante.tzinfo is None:
        raise ValueError("O registro precisa de data, hora e fuso.")
    return instante


class Fechado(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ReferenciaResultado(Fechado):
    classe: Literal["credito_carbono", "flag"]
    metrica: Identificador
    unidade: Literal["tCO2e", "tCO2e/ha", "tCO2e/ha/ano", "tCO2e/ano"]
    escala: Literal["por_hectare", "lote"]
    area_base_ha: Annotated[float, Field(gt=0)]
    area_elegivel_carteira_ha: Annotated[float, Field(gt=0)]
    escopo_carteira: Literal["titulares", "titulares_e_reservas"]
    inicio: Dia
    fim: Dia
    horizonte_dias: Annotated[int, Field(gt=0)]

    @model_validator(mode="after")
    def conferir(self) -> Self:
        if (_dia(self.fim) - _dia(self.inicio)).days != self.horizonte_dias:
            raise ValueError("O horizonte não corresponde ao período informado.")
        if (self.escala == "por_hectare") != ("/ha" in self.unidade):
            raise ValueError("Unidade e escala não correspondem.")
        if self.escala == "lote" and self.area_base_ha != self.area_elegivel_carteira_ha:
            raise ValueError("A base do lote precisa corresponder à área elegível da carteira.")
        if self.escala == "por_hectare" and self.area_base_ha != 1:
            raise ValueError("A base por hectare precisa ser um hectare.")
        return self


class FonteResultado(Fechado):
    nome: Literal[
        "Registro de contratos da Raíz",
        "Registro de emissão de créditos",
        "Comprovante de entrega de créditos",
        "Banco de aprendizado da Raíz",
        "Observação de campo registrada",
        "Registro Verra",
        "Registro Gold Standard",
        "Relatório de monitoramento verificado",
        "Demonstração sintética",
    ]
    registro_id: Identificador
    data: Dia

    @field_validator("data")
    @classmethod
    def conferir_dia(cls, valor: str) -> str:
        _dia(valor)
        return valor


class MedidaConfirmada(Fechado):
    natureza: Literal["contrato_assinado", "emissao_registrada", "entrega_comprovada"]
    valor: Numero
    fonte: FonteResultado


class MarcoContrato(Fechado):
    data: Dia
    contratado: MedidaConfirmada | None
    emitido: MedidaConfirmada | None
    entregue: MedidaConfirmada | None

    @model_validator(mode="after")
    def conferir(self) -> Self:
        _dia(self.data)
        for campo, natureza in (
            (self.contratado, "contrato_assinado"),
            (self.emitido, "emissao_registrada"),
            (self.entregue, "entrega_comprovada"),
        ):
            if campo is not None and campo.natureza != natureza:
                raise ValueError("Cada etapa exige sua própria evidência documental.")
        return self


class SerieContrato(Fechado):
    id: Identificador
    metodo: Identificador
    referencia: ReferenciaResultado
    regime: Literal["acumulado"]
    marcos: Annotated[list[MarcoContrato], Field(max_length=100)]

    @model_validator(mode="after")
    def conferir(self) -> Self:
        datas = [m.data for m in self.marcos]
        if datas != sorted(set(datas)):
            raise ValueError("Os marcos precisam de datas únicas e crescentes.")
        return self


class PrevisaoResultado(Fechado):
    referencia: ReferenciaResultado
    corte: Dia
    congelada_em: str
    p10: Numero
    p50: Numero
    p90: Numero
    fonte: FonteResultado


class ObservacaoResultado(Fechado):
    referencia: ReferenciaResultado
    data: Dia
    registrado_em: str
    valor: Numero
    fonte: FonteResultado


class ComparacaoMetodo(Fechado):
    id: Identificador
    metodo: Identificador
    modelo: Identificador
    versao: Identificador
    avaliacao: Literal["ao_vivo", "backtest"]
    previsao: PrevisaoResultado
    observado: ObservacaoResultado

    @model_validator(mode="after")
    def conferir(self) -> Self:
        p, o = self.previsao, self.observado
        congelada, registrada = _instante(p.congelada_em), _instante(o.registrado_em)
        if p.referencia != o.referencia or not p.p10 <= p.p50 <= p.p90:
            raise ValueError("Faixas e referências precisam ser compatíveis.")
        if p.corte != p.referencia.inicio or o.data != p.referencia.fim:
            raise ValueError("Só a observação na data-alvo comprova o mesmo horizonte.")
        if p.congelada_em[:10] < p.corte or o.registrado_em[:10] < o.data:
            raise ValueError("A cronologia dos registros não corresponde às datas informadas.")
        if self.avaliacao == "ao_vivo" and (p.congelada_em[:10] >= o.data or congelada > registrada):
            raise ValueError("Uma previsão ao vivo precisa anteceder o dia observado.")
        return self


class ResultadosGraficos(Fechado):
    esquema: Literal["raiz.resultados.graficos.v1"] = Field(alias="schema")
    origem: Literal["real", "demonstracao"]
    gerado_em: str
    contratos: Annotated[list[SerieContrato], Field(max_length=100)]
    comparacoes: Annotated[list[ComparacaoMetodo], Field(max_length=100)]

    @model_validator(mode="after")
    def conferir(self) -> Self:
        gerado = _instante(self.gerado_em)
        fontes = []
        for serie in self.contratos:
            for marco in serie.marcos:
                if marco.data > self.gerado_em[:10]:
                    raise ValueError("O retrato ainda não foi observado.")
                fontes.extend(m.fonte for m in (marco.contratado, marco.emitido, marco.entregue) if m)
        for c in self.comparacoes:
            p, o = c.previsao, c.observado
            if o.data > self.gerado_em[:10] or max(_instante(p.congelada_em), _instante(o.registrado_em)) > gerado:
                raise ValueError("Há resultado ou registro posterior à publicação.")
            fontes.extend([p.fonte, o.fonte])
        if any((f.nome == "Demonstração sintética") != (self.origem == "demonstracao") for f in fontes):
            raise ValueError("Fontes sintéticas e reais precisam permanecer separadas.")
        if any(f.data > self.gerado_em[:10] for f in fontes):
            raise ValueError("Há fonte posterior à publicação.")
        for registros in (self.contratos, self.comparacoes):
            if len({r.id for r in registros}) != len(registros):
                raise ValueError("Identificadores de registros precisam ser únicos.")
        return self
