"""Conferência campo a campo antes de gerar; ausência nunca vira zero ou pronto."""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from uuid import UUID

import yaml
from pydantic import Field

from .esquema import Fechado, FonteCampo, Medida, Pasta, TipoDocumento

REGRAS = Path(__file__).parents[1] / "regras" / "padroes" / "pasta_fiador.yaml"


class Regras(Fechado):
    versao: str
    perfil: str
    campos_obrigatorios: list[str]
    documentos_nao_dispensaveis: list[TipoDocumento]
    documentos_dispensaveis: list[TipoDocumento]
    titulo_pronto: dict[str, str]
    garantia_pronta: str
    unidades: dict[str, str]
    previsao_natureza: str
    permitir_area_zero: bool
    somar_creditos_de_metodos_alternativos: bool


def regras() -> tuple[Regras, str]:
    bruto = REGRAS.read_bytes()
    r = Regras.model_validate(yaml.safe_load(bruto))
    if (
        set(r.campos_obrigatorios) != {"area_elegivel", "titulo", "garantia", "creditos", "preco"}
        or r.titulo_pronto != {"nivel": "conferencia_concluida", "situacao": "conferida"}
        or r.garantia_pronta != "conferida"
        or not {"titularidade", "garantia"} <= set(r.documentos_nao_dispensaveis)
        or set(r.documentos_dispensaveis) & set(r.documentos_nao_dispensaveis)
        or r.unidades != {"area_elegivel": "ha", "area_metodo": "ha", "credito": "tCO2e"}
        or r.previsao_natureza != "estimado"
        or r.permitir_area_zero
        or r.somar_creditos_de_metodos_alternativos
    ):
        raise ValueError("Política da pasta incompatível com as garantias do contrato")
    return r, hashlib.sha256(bruto).hexdigest()


class Falha(Fechado):
    codigo: str
    campo: str
    mensagem: str
    documento_id: UUID | None = None


class CampoConferido(Fechado):
    campo: str
    fontes: list[FonteCampo]


class Relatorio(Fechado):
    pronto: bool
    regra_versao: str
    regra_sha256: str
    conferido_em: dt.datetime
    falhas: list[Falha] = Field(default_factory=list)
    campos: list[CampoConferido] = Field(default_factory=list)
    documentos: list[dict] = Field(default_factory=list)


def validar(pasta: Pasta, *, agora: dt.datetime | None = None) -> Relatorio:
    agora = agora or dt.datetime.now(dt.UTC)
    if agora.tzinfo is None:
        raise ValueError("Conferência exige relógio com fuso")
    hoje = agora.date()
    regra, assinatura = regras()
    rel = Relatorio(pronto=False, regra_versao=regra.versao, regra_sha256=assinatura, conferido_em=agora)
    documentos = {d.id: d for d in pasta.documentos}
    estados = {}

    def falhar(codigo, campo, mensagem, doc=None):
        rel.falhas.append(Falha(codigo=codigo, campo=campo, mensagem=mensagem, documento_id=doc))

    if pasta.data_corte > hoje:
        falhar("data_futura", "data_corte", "A data de corte ainda não ocorreu.")
    if not pasta.imoveis:
        falhar("obrigatorio", "imoveis", "O lote precisa conter imóveis conferidos, de qualquer tamanho.")

    for doc in pasta.documentos:
        estado = doc.estado
        if estado == "conferido":
            if not doc.sha256 or not doc.emitido_em or not doc.conferido_em:
                estado = "sem_proveniencia"
            elif doc.emitido_em > hoje or doc.conferido_em > agora or doc.conferido_em.date() < doc.emitido_em:
                estado = "data_invalida"
            elif doc.valido_ate and (doc.valido_ate < doc.emitido_em or doc.sem_vencimento):
                estado = "validade_invalida"
            elif doc.valido_ate and doc.valido_ate < hoje:
                estado = "vencido"
            elif not doc.valido_ate and not doc.sem_vencimento:
                estado = "validade_ausente"
        estados[doc.id] = estado

    for doc in pasta.documentos:
        campo = f"documentos/{doc.id}"
        estado = estados[doc.id]
        if doc.estado == "dispensado":
            dispensa = documentos.get(doc.dispensa_documento_id)
            if (
                doc.tipo not in regra.documentos_dispensaveis
                or not doc.motivo
                or dispensa is None
                or dispensa.tipo != "dispensa"
                or estados[dispensa.id] != "conferido"
            ):
                falhar(
                    "dispensa_invalida",
                    campo,
                    "Dispensa exige previsão na regra e documento válido de autorização.",
                    doc.id,
                )
        elif doc.estado == "substituido":
            vistos, atual = {doc.id}, doc
            while atual.estado == "substituido":
                sucessor = documentos.get(atual.substituido_por)
                if sucessor is None or sucessor.id in vistos or sucessor.tipo != doc.tipo or not atual.motivo:
                    falhar(
                        "substituicao_invalida",
                        campo,
                        "A substituição precisa de sucessor do mesmo tipo e cadeia sem ciclos.",
                        doc.id,
                    )
                    break
                vistos.add(sucessor.id)
                atual = sucessor
            else:
                if estados[atual.id] != "conferido":
                    falhar(
                        "sucessor_invalido", campo, "O documento substituto precisa estar conferido e vigente.", doc.id
                    )
        elif estado != "conferido":
            falhar("documento_" + estado, campo, "O documento não está conferido e vigente para esta entrega.", doc.id)
        rel.documentos.append(
            {
                "id": str(doc.id),
                "tipo": doc.tipo,
                "estado": estado,
                "valido_ate": doc.valido_ate.isoformat() if doc.valido_ate else None,
            }
        )

    def fontes(campo, refs, tipo, subcampos=()):
        if not refs:
            falhar("fonte_ausente", campo, "O campo precisa de referência a documento conferido.")
        for ref in refs:
            doc = documentos.get(ref.documento_id)
            if doc is None:
                falhar("fonte_inexistente", campo, "O documento de origem não consta da pasta.", ref.documento_id)
            elif doc.tipo != tipo or estados[doc.id] != "conferido":
                falhar(
                    "fonte_invalida",
                    campo,
                    "A origem precisa ser do tipo esperado, conferida e vigente; atualize referências substituídas.",
                    doc.id,
                )
            elif ref.data_referencia > pasta.data_corte or ref.data_referencia > doc.conferido_em.date():
                falhar(
                    "referencia_futura",
                    campo,
                    "A data de referência não pode ultrapassar o corte ou a conferência.",
                    doc.id,
                )
        rel.campos.append(CampoConferido(campo=campo, fontes=refs))
        rel.campos.extend(CampoConferido(campo=f"{campo}/{nome}", fontes=refs) for nome in subcampos)

    def medida(campo, dado: Medida | None, unidade, tipo, *, positiva=False, estimada=False):
        if dado is None or dado.valor is None:
            falhar("obrigatorio", campo, "Valor obrigatório ausente; não preencher com zero.")
            return
        if dado.unidade != unidade or dado.valor < 0 or (positiva and dado.valor == 0):
            falhar("valor_ou_unidade", campo, "Confira o valor e a unidade exigida para o campo.")
        if estimada and dado.natureza != regra.previsao_natureza:
            falhar("natureza_invalida", campo, "Previsão de crédito deve estar identificada como estimativa.")
        fontes(campo, dado.fontes, tipo, ("valor", "unidade", "natureza"))

    for idx, imovel in enumerate(pasta.imoveis):
        base = f"imoveis/{idx}"
        for nome in regra.campos_obrigatorios:
            if getattr(imovel, nome) is None or getattr(imovel, nome) == []:
                falhar("obrigatorio", f"{base}/{nome}", "Campo obrigatório ausente.")
        medida(
            f"{base}/area_elegivel",
            imovel.area_elegivel,
            regra.unidades["area_elegivel"],
            "area_elegivel",
            positiva=True,
        )
        fontes(f"{base}/codigo_car", imovel.area_elegivel.fontes if imovel.area_elegivel else [], "area_elegivel")
        if imovel.titulo:
            if any(getattr(imovel.titulo, k) != v for k, v in regra.titulo_pronto.items()):
                falhar(
                    "titularidade_pendente",
                    f"{base}/titulo",
                    "A titularidade precisa de conferência concluída e situação conferida.",
                )
            fontes(f"{base}/titulo", imovel.titulo.fontes, "titularidade", ("nivel", "situacao"))
        if imovel.garantia:
            if imovel.garantia.situacao != regra.garantia_pronta:
                falhar("garantia_pendente", f"{base}/garantia", "A garantia precisa estar conferida.")
            fontes(f"{base}/garantia", imovel.garantia.fontes, "garantia", ("situacao",))
        for pos, credito in enumerate(imovel.creditos):
            caminho = f"{base}/creditos/{pos}"
            fontes(caminho, credito.fontes, "previsao", ("metodo", "periodo/inicio", "periodo/fim", "modelo_versao"))
            medida(caminho + "/area", credito.area, regra.unidades["area_metodo"], "previsao", positiva=True)
            for q in ("p10", "p50", "p90"):
                medida(f"{caminho}/{q}", getattr(credito, q), regra.unidades["credito"], "previsao", estimada=True)
            valores = [getattr(credito, q).valor if getattr(credito, q) else None for q in ("p10", "p50", "p90")]
            if all(v is not None for v in valores) and not valores[0] <= valores[1] <= valores[2]:
                falhar("faixa_invertida", caminho, "A faixa exige P10 menor ou igual a P50, menor ou igual a P90.")
            if (
                credito.area
                and imovel.area_elegivel
                and credito.area.valor is not None
                and imovel.area_elegivel.valor is not None
                and credito.area.valor > imovel.area_elegivel.valor
            ):
                falhar("area_excedida", caminho + "/area", "A área do método ultrapassa a área elegível conferida.")
            for nome in ("periodo", "modelo_versao"):
                if getattr(credito, nome) is None:
                    falhar("obrigatorio", caminho + "/" + nome, "A previsão exige período e versão do modelo.")
        if imovel.preco:
            preco = imovel.preco
            for nome in ("valor", "moeda", "unidade", "periodo", "natureza"):
                if getattr(preco, nome) is None:
                    falhar(
                        "obrigatorio", f"{base}/preco/{nome}", "Preço exige valor, moeda, unidade, período e natureza."
                    )
            fontes(
                f"{base}/preco",
                preco.fontes,
                "preco",
                ("valor", "moeda", "unidade", "periodo/inicio", "periodo/fim", "natureza"),
            )
    rel.falhas = list({(f.codigo, f.campo, f.documento_id): f for f in rel.falhas}.values())
    rel.pronto = not rel.falhas
    return rel
