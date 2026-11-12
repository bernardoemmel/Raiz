"""Salvaguardas verificáveis de originação e revisão humana (Lei 15.042 e LGPD).

Os documentos ficam fora do banco: aqui só há hash de evidência, datas, área e decisões
estruturadas. Ausência de evidência não significa ausência de sobreposição.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, text

from raiz.pedidos.servico import ErroPedido

VERSAO = "salvaguardas-2026a"


class ErroSalvaguarda(ErroPedido):
    """Evidência pendente: o trabalho deve devolver input-required, sem aprovar ou gerar Pix."""


class ErroAcessoRevisao(ErroPedido):
    """Detalhe de decisão segue a mesma liberação comercial da ficha e do lote."""

    status = 403


class Evidencia(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Hash do documento em cofre privado, nunca texto, nome ou contato de participantes.
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    data: dt.date

    @model_validator(mode="after")
    def nao_futura(self):
        if self.data > dt.datetime.now(dt.UTC).date():
            raise ValueError("evidência não pode ter data futura")
        return self


class Verificacao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verificacao: Evidencia
    territorio_tradicional: bool | None = None
    clpi: Evidencia | None = None
    consentimento: bool = False
    inicio_previsto: dt.date | None = None
    atividade: Literal["remocao", "redd_mercado"] = "remocao"
    fracao_comunidade: float | None = Field(default=None, ge=0, le=1)
    contrato_beneficios: Evidencia | None = None
    conta_especifica: bool = False
    gestao_participativa: bool = False
    # Protocolo por programa e período; não vale uma exclusão genérica da UF.
    exclusoes_conaredd: dict[str, Evidencia] = Field(default_factory=dict)


class Cobertura(BaseModel):
    model_config = ConfigDict(extra="forbid")
    uf: str = Field(pattern=r"^[A-Z]{2}$")
    evidencia: Evidencia
    valida_ate: dt.date

    @model_validator(mode="after")
    def periodo(self):
        if not self.evidencia.data <= self.valida_ate <= self.evidencia.data + dt.timedelta(days=365):
            raise ValueError("cobertura exige reverificação em até um ano")
        return self


class Programa(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    uf: str = Field(pattern=r"^[A-Z]{2}$")
    inicio: dt.date
    fim: dt.date
    fonte: str
    evidencia: Evidencia
    geometria: dict

    @model_validator(mode="after")
    def validar(self):
        from shapely.geometry import shape

        url = urlsplit(self.fonte)
        if url.scheme != "https" or not url.netloc or url.username or url.query or url.fragment:
            raise ValueError("fonte deve ser URL HTTPS pública sem credenciais, query ou fragmento")
        if self.fim < self.inicio:
            raise ValueError("período contábil inválido")
        geom = shape(self.geometria)
        if geom.geom_type not in ("Polygon", "MultiPolygon") or geom.is_empty or not geom.is_valid:
            raise ValueError("a camada precisa de polígono válido")
        if not all(math.isfinite(x) for x in geom.bounds):
            raise ValueError("coordenadas inválidas")
        minx, miny, maxx, maxy = geom.bounds
        if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
            raise ValueError("coordenadas fora de EPSG:4674")
        return self


def _bool(x) -> bool:
    return str(x).lower() in ("true", "1", "sim")


def _positivo(x) -> bool:
    try:
        return float(x) > 0
    except (ValueError, TypeError):
        return False


def avaliar(linha: dict, verificacao: Verificacao | dict | None = None, programas: list[dict] | None = None) -> dict:
    """Avalia dados estruturados; bloqueios conhecidos valem também para a pré-seleção.

    Não converte texto de terceiro em instrução. Sem verificação, a estimativa continua
    identificada como preliminar e a reserva é impedida por exigir_para_reserva().
    """
    v = Verificacao.model_validate(verificacao) if isinstance(verificacao, dict) else verificacao
    tradicional = (
        linha.get("caminho_terra") == "terra_indigena_ou_tradicional"
        or _positivo(linha.get("ti_ha"))
        or _positivo(linha.get("ti_funai_ha"))
        or _positivo(linha.get("quilombo_ha"))
        or _bool(linha.get("territorio_tradicional"))
        or bool((linha.get("salvaguardas") or {}).get("territorio_tradicional"))
        or bool(v and v.territorio_tradicional)
    )
    programas = programas if programas is not None else linha.get("redd_programas") or []
    conhecidos = [p for p in programas if isinstance(p, dict) and p.get("id")]
    motivos = []
    pendencias = []
    if v is None:
        pendencias.append("verificacao_documental_pendente")
    elif v.territorio_tradicional is None:
        pendencias.append("territorio_tradicional_nao_verificado")
    if linha.get("redd_cobertura_verificada") is not True:
        pendencias.append("cobertura_redd_nao_verificada")
    sem_exclusao = [str(p["id"]) for p in conhecidos if not v or str(p["id"]) not in v.exclusoes_conaredd]
    if sem_exclusao:
        motivos.append("sobreposicao_redd_sem_exclusao_conaredd")
    minimo = 0.70 if v and v.atividade == "redd_mercado" else 0.50
    if tradicional:
        if not v or not v.clpi or not v.consentimento:
            motivos.append("consentimento_clpi_pendente")
        if not v or not v.inicio_previsto or (v.clpi and v.clpi.data > v.inicio_previsto):
            motivos.append("consulta_previa_nao_comprovada")
        if not v or v.fracao_comunidade is None or v.fracao_comunidade < minimo:
            motivos.append("participacao_comunidade_insuficiente")
        if not v or not (v.contrato_beneficios and v.conta_especifica and v.gestao_participativa):
            motivos.append("garantias_comunitarias_pendentes")
    return {
        "versao": VERSAO,
        "redd": {
            "estado": "sobreposicao"
            if conhecidos
            else (
                "sem_sobreposicao_verificada" if linha.get("redd_cobertura_verificada") is True else "nao_verificado"
            ),
            "programas": [{k: p.get(k) for k in ("id", "uf", "inicio", "fim", "area_ha", "fonte")} for p in conhecidos],
            "exclusao_pendente": sem_exclusao,
        },
        "territorio_tradicional": tradicional,
        "clpi": "comprovada"
        if tradicional and v and v.clpi and v.consentimento
        else ("pendente" if tradicional else "nao_identificado"),
        "fracao_minima_comunidade": minimo if tradicional else None,
        "bloqueios": motivos,
        "pendencias": pendencias,
        "pode_originar": not motivos,
        "pode_reservar": not motivos and not pendencias,
        "revisao_humana": {
            "direito": "LGPD art. 20; revisão por pessoa, compromisso Raíz",
            "rota": "/pedidos/{pedido_id}/revisoes",
        },
    }


def registrar_programa(engine: Engine, programa: Programa) -> None:
    """Camada de período contábil declarado; cada id é imutável para preservar evidências."""
    with engine.begin() as con:
        con.execute(
            text("""insert into geo.redd_programa (id, uf, inicio, fim, fonte, evidencia, geom)
            values (:id, :uf, :inicio, :fim, :fonte, cast(:ev as jsonb),
            ST_SetSRID(ST_GeomFromGeoJSON(:g), 4674))"""),
            {
                "id": programa.id,
                "uf": programa.uf,
                "inicio": programa.inicio,
                "fim": programa.fim,
                "fonte": programa.fonte,
                "ev": programa.evidencia.model_dump_json(),
                "g": json.dumps(programa.geometria),
            },
        )
        # O catálogo da UF mudou: mantém o certificado e exige nova conferência
        # mesmo quando o programa recém-cadastrado não intercepta esta fazenda.
        con.execute(
            text("update geo.redd_cobertura set revalidacao_pendente = true where uf = :uf"),
            {"uf": programa.uf},
        )


def registrar_cobertura(engine: Engine, cobertura: Cobertura) -> None:
    with engine.begin() as con:
        con.execute(
            text("""insert into geo.redd_cobertura (uf, verificada_em, valida_ate, evidencia)
            values (:uf, :d, :v, cast(:e as jsonb)) on conflict (uf) do update set
            verificada_em = excluded.verificada_em, valida_ate = excluded.valida_ate,
            evidencia = excluded.evidencia, revalidacao_pendente = false"""),
            {
                "uf": cobertura.uf,
                "d": cobertura.evidencia.data,
                "v": cobertura.valida_ate,
                "e": cobertura.evidencia.model_dump_json(),
            },
        )


def camada(engine: Engine) -> dict:
    with engine.connect() as con:
        linhas = con.execute(
            text("""select id, uf, inicio, fim, fonte, ST_AsGeoJSON(geom) as geometria
            from geo.redd_programa order by id""")
        ).mappings()
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": json.loads(li["geometria"]),
                    "properties": {
                        "id": li["id"],
                        "uf": li["uf"],
                        "inicio": li["inicio"].isoformat(),
                        "fim": li["fim"].isoformat(),
                        "fonte": li["fonte"],
                    },
                }
                for li in linhas
            ],
        }


def registrar_verificacao(engine: Engine, cod_imovel: str, verificacao: Verificacao) -> None:
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.salvaguarda_evento (cod_imovel, evidencia)
            values (:cod, cast(:ev as jsonb))"""),
            {"cod": cod_imovel, "ev": verificacao.model_dump_json()},
        )
        con.execute(
            text("""insert into negocio.salvaguarda (cod_imovel, evidencia) values (:cod, cast(:ev as jsonb))
            on conflict (cod_imovel) do update set evidencia = excluded.evidencia, atualizada_em = now()"""),
            {"cod": cod_imovel, "ev": verificacao.model_dump_json()},
        )


def do_banco(engine: Engine, cods: list[str]) -> dict[str, dict]:
    """Sobrepõe polígonos reais, não centroides; qualquer período cadastrado deve ser conciliado.

    A cobertura é atestada explicitamente por UF (geo.redd_cobertura); tabela vazia não é
    prova de ausência. O atestado expira; novos períodos exigem recertificação.
    """
    if not cods:
        return {}
    with engine.connect() as con:
        evidencias = {
            r.cod_imovel: r.evidencia
            for r in con.execute(
                text("select cod_imovel, evidencia from negocio.salvaguarda where cod_imovel = any(:cods)"),
                {"cods": cods},
            )
        }
        linhas = (
            con.execute(
                text("""select i.cod_imovel, i.uf,
            coalesce(c.valida_ate >= current_date and not c.revalidacao_pendente, false) as cobertura,
            i.geom is not null as tem_geometria,
            p.id, p.inicio, p.fim, p.fonte,
            case when p.id is not null then ST_Area(ST_Intersection(i.geom, p.geom)::geography) / 10000 end as area_ha
            from funil.imovel i
            left join geo.redd_cobertura c on c.uf = i.uf
            left join geo.redd_programa p on p.uf = i.uf and i.geom && p.geom
                and ST_Intersects(i.geom, p.geom)
                and ST_Area(ST_Intersection(i.geom, p.geom)::geography) > 0
            where i.cod_imovel = any(:cods)"""),
                {"cods": cods},
            )
            .mappings()
            .all()
        )
    out = {}
    for li in linhas:
        x = out.setdefault(
            li["cod_imovel"],
            {
                "verificacao": evidencias.get(li["cod_imovel"]),
                "redd_programas": [],
                "redd_cobertura_verificada": bool(li["cobertura"] and li["tem_geometria"]),
            },
        )
        if li["id"]:
            x["redd_programas"].append(
                {
                    "id": li["id"],
                    "uf": li["uf"],
                    "inicio": li["inicio"].isoformat(),
                    "fim": li["fim"].isoformat(),
                    "fonte": li["fonte"],
                    "area_ha": float(li["area_ha"]),
                }
            )
    return out


def exigir_para_reserva(engine: Engine, cods: list[str]) -> None:
    dados = do_banco(engine, cods)
    with engine.connect() as con:
        attrs = {
            r.cod_imovel: r.atributos
            for r in con.execute(
                text("select cod_imovel, atributos from negocio.oferta where cod_imovel = any(:cods)"), {"cods": cods}
            )
        }
    for cod in cods:
        li = {**(attrs.get(cod) or {}), **(dados.get(cod) or {})}
        v = avaliar(li, li.get("verificacao"))
        if not v["pode_reservar"]:
            raise ErroSalvaguarda("reserva aguarda verificação humana das salvaguardas territoriais e de carbono")


def _exigir_liberacao_revisao(con, cliente_id: int) -> None:
    liberada = con.execute(
        text("""select contrato_aceito_em is not null and sinal_pago_em is not null
        and bloqueada_em is null from negocio.conta_api where cliente_id = :c"""),
        {"c": cliente_id},
    ).scalar_one_or_none()
    if liberada is not True:
        raise ErroAcessoRevisao("o detalhe da decisão exige conta liberada, sinal pago e contrato aceito")


def _exigir_imovel_do_pedido(con, pedido_id: str, cliente_id: int, cod_imovel: str) -> None:
    # Não há candidatos excluídos persistidos antes de uma sugestão: até haver esse registro,
    # um código arbitrário da base não pode ser usado para consultar detalhe pela revisão.
    vinculado = con.execute(
        text("""select exists (
            select 1 from negocio.pedido_fazenda where pedido_id = :p and cod_imovel = :cod
        ) or exists (
            select 1 from (
                select opcoes from negocio.pedido_sugestao where pedido_id = :p order by id desc limit 1
            ) s cross join lateral jsonb_array_elements(s.opcoes) o(opcao)
            cross join lateral jsonb_array_elements(coalesce(o.opcao->'itens', '[]'::jsonb)) i(item)
            where i.item->>'cod_imovel' = :cod
        )"""),
        {"p": pedido_id, "cod": cod_imovel},
    ).scalar_one()
    reservada = con.execute(
        text("""select exists (select 1 from negocio.reserva_fazenda rf
        join negocio.reserva r on r.id = rf.reserva_id
        where rf.cod_imovel = :cod and rf.ativa and r.cliente_id <> :c)"""),
        {"cod": cod_imovel, "c": cliente_id},
    ).scalar_one()
    if not vinculado or reservada:
        raise ErroPedido("fazenda não encontrada neste pedido")


def solicitar_revisao(engine: Engine, pedido_id: str, cliente_id: int, cod_imovel: str, motivo: str) -> dict:
    """Guarda critérios da oferta no instante da contestação. Não muda elegibilidade."""
    from raiz.pedidos.servico import ErroPedido, _linha_pedido

    if motivo not in ("exclusao_automatica", "nota_de_risco", "salvaguarda"):
        raise ErroPedido("motivo de revisão inválido")
    with engine.begin() as con:
        _linha_pedido(con, pedido_id, cliente_id)
        _exigir_liberacao_revisao(con, cliente_id)
        _exigir_imovel_do_pedido(con, pedido_id, cliente_id, cod_imovel)
        oferta = con.execute(
            text("select atributos from negocio.oferta where cod_imovel = :cod"), {"cod": cod_imovel}
        ).scalar()
        if oferta is None:
            raise ErroPedido("fazenda não encontrada")
        criterios = {
            k: oferta.get(k)
            for k in ("elegivel", "caminho_terra", "risco_terra", "bloqueio", "problema", "restauracao_versao")
        }
        criterios["regra"] = VERSAO
        rid = (
            con.execute(
                text("""insert into negocio.revisao_humana
            (pedido_id, cliente_id, cod_imovel, motivo, criterios) values (:p, :c, :cod, :m, cast(:cr as jsonb))
            on conflict (pedido_id, cod_imovel, motivo) where estado = 'pendente'
            do update set motivo = excluded.motivo returning id, criterios"""),
                {"p": pedido_id, "c": cliente_id, "cod": cod_imovel, "m": motivo, "cr": json.dumps(criterios)},
            )
            .mappings()
            .one()
        )
    return {"revisao_id": rid["id"], "estado": "pendente", "criterios": rid["criterios"]}


def listar_revisoes(engine: Engine, pedido_id: str, cliente_id: int) -> list[dict]:
    from raiz.pedidos.servico import _linha_pedido

    with engine.connect() as con:
        _linha_pedido(con, pedido_id, cliente_id)
        _exigir_liberacao_revisao(con, cliente_id)
        rs = con.execute(
            text("""select h.id, h.cod_imovel, h.motivo, h.criterios, h.estado, h.decisao, h.criada_em, h.resolvida_em
            from negocio.revisao_humana h where h.pedido_id = :p and h.cliente_id = :c
            and not exists (select 1 from negocio.reserva_fazenda rf
                join negocio.reserva r on r.id = rf.reserva_id
                where rf.cod_imovel = h.cod_imovel and rf.ativa and r.cliente_id <> :c)
            order by h.id"""),
            {"p": pedido_id, "c": cliente_id},
        ).mappings()
        return [{k: v.isoformat() if isinstance(v, dt.datetime) else v for k, v in row.items()} for row in rs]


def resolver_revisao(engine: Engine, revisao_id: int, revisor_id: str, decisao: str, evidencia: Evidencia) -> dict:
    """Somente rota com credencial humana separada; evidência é obrigatória e não desfaz bloqueio legal."""
    from raiz.pedidos.servico import ErroPedido

    if decisao not in ("mantida", "corrigir_dados", "recalcular"):
        raise ErroPedido("decisão de revisão inválida")
    with engine.begin() as con:
        row = con.execute(
            text("""update negocio.revisao_humana set estado = 'resolvida', decisao = :d,
            revisor_id = cast(:r as uuid), evidencia = cast(:e as jsonb), resolvida_em = now()
            where id = :id and estado = 'pendente' returning id"""),
            {"d": decisao, "r": revisor_id, "e": evidencia.model_dump_json(), "id": revisao_id},
        ).first()
        if row is None:
            raise ErroPedido("revisão não encontrada ou já resolvida")
    return {"revisao_id": revisao_id, "estado": "resolvida", "decisao": decisao}
