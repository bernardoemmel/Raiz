"""Evidência privada da opção, vinculada à composição atual; resumo não vira ficha.

O produtor publica <pedido UUID>/<revisao_lote>/<opcao>.json em
RAIZ_FICHAS_CREDITO_DIRETORIO. Ler somente após autorizar a conta dona do pedido.
O hash identifica exatamente o documento validado; não substitui o histórico
imutável da ficha individual, mantido no serviço de prospecção.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from raiz.pedidos.resultados_graficos import ResultadosGraficos

Numero = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]
Texto = Annotated[str, Field(min_length=1, max_length=1200)]
Identificador = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:+/-]{0,119}$")]
Revisao = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
IdOpcao = Literal["barata", "segura", "compacta"]
SECOES = ("titulo", "metodo", "perdas", "garantias", "risco_nao_entrega")
FONTES = {
    "Raíz, motor de lotes",
    "Raíz, revisão técnica",
    "SICAR, polígono do CAR",
    "Ibama, embargos",
    "Funai, terras indígenas",
    "CNUC, unidades de conservação",
    "Registro de projeto de carbono",
    "Registro de emissão",
    "Registro de entrega",
    "Contrato assinado",
}
TEXTOS_SECAO = {
    "titulo": {
        "Documentação da terra ainda não conferida.",
        "Documentação da terra conferida; acompanhar a validade das certidões.",
        "Há pendências documentais no lote.",
    },
    "metodo": {
        "Estimativa agregada do motor para a composição e o horizonte desta ficha.",
        "Resultado verificado para a composição e o horizonte desta ficha.",
    },
    "perdas": {
        "Perdas incorporadas na estimativa do motor; conferir as premissas na fonte.",
        "Perdas ainda não documentadas para este horizonte.",
    },
    "garantias": {
        "Garantias ainda não documentadas.",
        "Garantias documentadas; conferir escopo, validade e condições na fonte.",
    },
    "risco_nao_entrega": {
        "Risco de não entrega ainda não avaliado.",
        "Risco de não entrega avaliado; conferir as condições e limitações na fonte.",
    },
}


class Fechado(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Faixa(Fechado):
    p10: Numero
    p50: Numero
    p90: Numero

    @model_validator(mode="after")
    def ordenada(self):
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("quantis fora de ordem")
        return self


class BaseCredito(Fechado):
    horizonte_anos: Annotated[int, Field(strict=True, gt=0, le=100)]
    unidade: Literal["tCO2e"]
    escopo_carteira: Literal["titulares", "titulares_e_reservas"]
    inicio: dt.date | None
    fim: dt.date | None
    classe_ativo: Literal["credito_carbono", "flag"]
    classe_evidencia: Literal["estimativa_modelo", "verificado", "emitido", "entregue"]
    metodo: Identificador
    modelo_versao: Identificador
    fonte: Texto
    data_referencia: dt.date
    evidencia_id: Identificador

    @model_validator(mode="after")
    def periodo(self):
        if (self.inicio is None) != (self.fim is None):
            raise ValueError("o período precisa das duas datas ou de horizonte sem calendário")
        if self.inicio is not None:
            try:
                fim = self.inicio.replace(year=self.inicio.year + self.horizonte_anos)
            except ValueError:  # aniversário de 29/02 em ano não bissexto
                fim = self.inicio.replace(year=self.inicio.year + self.horizonte_anos, day=28)
            if self.fim != fim:
                raise ValueError("horizonte incompatível com as datas")
        if self.classe_ativo == "flag" and self.classe_evidencia in {"emitido", "entregue"}:
            raise ValueError("resultado FLAG não é crédito emitido ou entregue")
        if self.classe_evidencia != "estimativa_modelo" and (self.fim is None or self.fim > self.data_referencia):
            raise ValueError("resultado realizado exige período completo anterior à evidência")
        return self


class Exclusao(Fechado):
    motivo: Literal[
        "embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono", "inelegivel_metodo", "outra"
    ]
    hectares: Numero | None
    fonte: Texto | None
    data_referencia: dt.date | None

    @model_validator(mode="after")
    def origem(self):
        if self.hectares is not None and (self.fonte is None or self.data_referencia is None):
            raise ValueError("área excluída exige fonte e data")
        return self


class Secao(Fechado):
    texto: Texto | None
    fonte: Texto | None
    data_referencia: dt.date | None
    revisado_em: dt.date | None

    @model_validator(mode="after")
    def origem(self):
        if self.texto is not None and self.fonte is None:
            raise ValueError("afirmação da ficha exige fonte")
        return self


class Secoes(Fechado):
    titulo: Secao
    metodo: Secao
    perdas: Secao
    garantias: Secao
    risco_nao_entrega: Secao


class DocumentoFichaCredito(Fechado):
    contrato: Literal["ficha_credito"]
    versao: Literal[1]
    pedido_id: uuid.UUID
    revisao_lote: Revisao
    opcao_id: IdOpcao
    publicada_em: dt.datetime
    base: BaseCredito
    creditos_lote: Faixa
    area_total_ha: Numero | None
    area_elegivel_ha: Numero | None
    fonte_area: Texto | None
    data_referencia_area: dt.date | None
    evidencia_area_id: Identificador | None
    exclusoes: Annotated[list[Exclusao], Field(max_length=100)] | None
    secoes: Secoes
    resultados: ResultadosGraficos | None = None

    @model_validator(mode="after")
    def coerente(self):
        if self.publicada_em.tzinfo is None or self.publicada_em > dt.datetime.now(dt.UTC):
            raise ValueError("publicação exige instante passado com fuso")
        if self.base.data_referencia > self.publicada_em.date():
            raise ValueError("a referência não pode ser posterior à publicação")
        if self.area_elegivel_ha is not None:
            if self.area_elegivel_ha <= 0:
                raise ValueError("a ficha exige área elegível positiva ou desconhecida")
            if self.area_total_ha is not None and self.area_elegivel_ha > self.area_total_ha:
                raise ValueError("área elegível maior que a área total")
            if any(not math.isfinite(v / self.area_elegivel_ha) for v in self.creditos_lote.model_dump().values()):
                raise ValueError("a divisão por hectare não é um número finito")
        if self.area_total_ha is not None or self.area_elegivel_ha is not None:
            if not self.fonte_area or not self.data_referencia_area or not self.evidencia_area_id:
                raise ValueError("área exige fonte, referência e evidência próprias")
        elif any(x is not None for x in (self.fonte_area, self.data_referencia_area, self.evidencia_area_id)):
            raise ValueError("metadados de área sem área")
        datas = [self.data_referencia_area]
        for e in self.exclusoes or []:
            datas.append(e.data_referencia)
            if e.hectares is not None and self.area_total_ha is not None and e.hectares > self.area_total_ha:
                raise ValueError("exclusão maior que a área total")
        for nome in SECOES:
            s = getattr(self.secoes, nome)
            if s.texto is not None and s.texto not in TEXTOS_SECAO[nome]:
                raise ValueError("a seção aceita somente conclusões controladas, sem texto de certidão")
            datas.extend((s.data_referencia, s.revisado_em))
            if s.revisado_em is not None and s.data_referencia is not None and s.revisado_em < s.data_referencia:
                raise ValueError("revisão anterior à evidência desta seção")
        if any(d is not None and d > self.publicada_em.date() for d in datas):
            raise ValueError("referência ou revisão posterior à publicação")
        # O documento é editorial e agregado: jamais uma certidão bruta ou contato do dono.
        from raiz.publica.privacidade import limpar

        for s in self._textos():
            if limpar(s) != s or re.search(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f]", s):
                raise ValueError("texto fora do contrato agregado")
        fontes = [self.base.fonte, self.fonte_area, *(e.fonte for e in self.exclusoes or [])]
        fontes.extend(getattr(self.secoes, nome).fonte for nome in SECOES)
        if any(f is not None and f not in FONTES for f in fontes):
            raise ValueError("fonte fora do catálogo; não publicar nomes livres")
        if self.resultados is not None and self.resultados.origem != "real":
            raise ValueError("demonstrações não entram em fichas de pedidos reais")
        return self

    def _textos(self):
        yield self.base.fonte
        if self.fonte_area:
            yield self.fonte_area
        for e in self.exclusoes or []:
            if e.fonte:
                yield e.fonte
        for nome in SECOES:
            s = getattr(self.secoes, nome)
            yield from (v for v in (s.texto, s.fonte) if v is not None)


def indisponivel(opcao_id: str, revisao_lote: str | None = None) -> dict:
    revisao_lote = (
        revisao_lote if isinstance(revisao_lote, str) and re.fullmatch(r"[a-f0-9]{64}", revisao_lote) else None
    )
    return {
        "contrato": "ficha_credito",
        "versao": 1,
        "estado": "indisponivel",
        "documento_versao": None,
        "publicada_em": None,
        "revisao_lote": revisao_lote,
        "opcao_id": opcao_id if opcao_id in {"barata", "segura", "compacta"} else None,
        "exemplo": False,
        "aviso": "O motor ainda não publicou uma ficha com horizonte, evidência e área elegível compatíveis. "
        "Os totais disponíveis não foram convertidos em créditos por hectare.",
        "base": None,
        "creditos_lote": None,
        "creditos_por_ha": None,
        "area_total_ha": None,
        "area_elegivel_ha": None,
        "fonte_area": None,
        "data_referencia_area": None,
        "evidencia_area_id": None,
        "exclusoes": None,
        "secoes": {n: {"texto": None, "fonte": None, "data_referencia": None, "revisado_em": None} for n in SECOES},
        "resultados": None,
    }


def consultar(pedido: dict, opcao_id: str) -> dict:
    """Falha fechada, depois da autorização. Não usa os hectares do pedido como área elegível."""
    revisao = pedido.get("revisao_lote")
    ausente = indisponivel(opcao_id, revisao)
    pasta = os.environ.get("RAIZ_FICHAS_CREDITO_DIRETORIO")
    if not pasta or not isinstance(revisao, str) or not re.fullmatch(r"[a-f0-9]{64}", revisao):
        return ausente
    if opcao_id not in {o.get("id") for o in pedido.get("opcoes", [])} or opcao_id not in {
        "barata",
        "segura",
        "compacta",
    }:
        return ausente
    try:
        pid = uuid.UUID(str(pedido["id"]))
        arquivo = Path(pasta) / str(pid) / revisao / f"{opcao_id}.json"
        if arquivo.stat().st_size > 2_000_000:
            return ausente
        dado = DocumentoFichaCredito.model_validate_json(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, ValidationError):
        return ausente
    if (
        dado.pedido_id != pid
        or dado.opcao_id != opcao_id
        or dado.revisao_lote != revisao
        or dado.base.modelo_versao != pedido.get("versao_modelo")
    ):
        return ausente
    return _resposta(dado)


def _resposta(dado: DocumentoFichaCredito) -> dict:
    documento = dado.model_dump(mode="json", by_alias=True)
    versao = hashlib.sha256(
        json.dumps(documento, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    # A mesma base e o mesmo denominador fixo valem para todos os quantis.
    por_ha = (
        {q: v / dado.area_elegivel_ha for q, v in dado.creditos_lote.model_dump().items()}
        if dado.area_elegivel_ha is not None
        else None
    )
    return {
        **indisponivel(dado.opcao_id, dado.revisao_lote),
        **{k: documento[k] for k in documento if k != "pedido_id"},
        "estado": "disponivel",
        "documento_versao": versao,
        "creditos_por_ha": por_ha,
        "aviso": "Mesma base temporal e de evidência nas duas colunas. Por hectare = total dividido pela área "
        "elegível documentada; exclusões podem se sobrepor e não devem ser somadas. Estimativa não é emissão."
        if por_ha is not None
        else "A área elegível não foi documentada; créditos por hectare continuam desconhecidos.",
    }


def projetar_resposta(valor, pedido: dict, opcao_id: str) -> dict:
    """A projeção HTTP confere novamente o contrato; não ecoa anexos de sugestões antigas."""
    ausente = indisponivel(opcao_id, pedido.get("revisao_lote"))
    if not isinstance(valor, dict) or valor.get("estado") != "disponivel" or valor.get("exemplo") is not False:
        return ausente
    metadados = {"estado", "documento_versao", "exemplo", "aviso", "creditos_por_ha"}
    try:
        dado = DocumentoFichaCredito.model_validate(
            {**{k: v for k, v in valor.items() if k not in metadados}, "pedido_id": pedido["id"]}
        )
    except (ValueError, KeyError, ValidationError):
        return ausente
    if (
        dado.opcao_id != opcao_id
        or dado.revisao_lote != pedido.get("revisao_lote")
        or dado.base.modelo_versao != pedido.get("versao_modelo")
    ):
        return ausente
    resposta = _resposta(dado)
    if valor.get("documento_versao") != resposta["documento_versao"]:
        return ausente
    return resposta
