"""Projeções REST: evidência de terceiros fica no serviço, nunca vira texto de resposta.

Regex não reconhece nomes de pessoas. Estes apresentadores usam enumerações, números,
identificadores e mensagens do produto; não tentam anonimizar narrativas de documentos.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import re
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from raiz.pedidos.campos import CAMINHOS, METODOS, CamposPedido
from raiz.publica.trabalhos import _resumo_base, _resumo_opcoes

ESTADOS = {
    "lote_montado",
    "buscando_interesse",
    "grupo_pronto",
    "faltou",
    "reservado",
    "contrato",
    "reserva_vencida",
    "cancelado",
}
NIVEIS = {"sem_contato", "contatado", "interessado", "aceite_fase1", "contrato_firme", "recusou", "sem_resposta"}
BIOMAS = {"Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal"}
UFS = set("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())
MENSAGENS = {
    "fazenda_com_problema": "Uma fazenda do lote exige revisão. Consulte os indicadores e peça revisão humana.",
    "lote_melhorou": "O lote tem uma opção melhor. Consulte os indicadores atualizados.",
    "grupo_pronto": "O grupo atingiu a meta de interesse. Uma pessoa pode revisar a proposta de reserva.",
    "faltou": "A busca terminou sem atingir a meta. Revise os filtros do pedido.",
    "reservado": "A reserva foi confirmada. Consulte a situação do pedido.",
    "reserva_revisao": "A reserva exige revisão humana antes de prosseguir.",
    "reserva_vencida": "A reserva venceu. Consulte a disponibilidade atualizada.",
    "atualizacao": "O pedido recebeu uma atualização. Consulte os indicadores ou peça revisão humana.",
}
MOTIVOS_ALERTA = {"desmatamento", "embargo", "matricula_cancelada", "bloqueio", "caminho_terra", "saiu_da_base"}
AFROUXAR = {
    "terra": "Rever os caminhos da terra aceitos.",
    "metodos": "Rever os métodos de restauração aceitos.",
    "interesse": "Rever o nível de interesse exigido.",
    "dinheiro.custo_max_usd_credito": "Rever o custo máximo por crédito.",
    "dinheiro.tir_min": "Rever a TIR mínima.",
    "onde": "Rever o recorte geográfico.",
    "onde.biomas": "Rever os biomas aceitos.",
    "onde.ufs": "Rever os estados aceitos.",
    "onde.so_fornecedores_cadeia": "Rever o filtro de fornecedores da cadeia.",
    "base": "A meta excede a base disponível com estes critérios.",
}


def _obj(x):
    return x if isinstance(x, dict) else {}


def _lista(x):
    return x if isinstance(x, list) else []


def _num(x):
    return x if type(x) in (int, float) and math.isfinite(x) else None


def _numeros(x, campos):
    return {k: _num(_obj(x).get(k)) for k in campos}


def _enum(x, valores):
    return x if isinstance(x, str) and x in valores else None


def _padrao(x, padrao):
    return x if isinstance(x, str) and re.fullmatch(padrao, x) else None


def _id(x):
    return _padrao(x, r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}")


def _car(x):
    return _padrao(x, r"[A-Z]{2}-[0-9]{7}-[a-fA-F0-9]{32}")


def _data(x):
    if not isinstance(x, str):
        return None
    try:
        return dt.datetime.fromisoformat(x).isoformat()
    except ValueError:
        return None


def _versao(x):
    if not isinstance(x, str) or len(x) > 300:
        return None
    partes = x.split("+")
    versao = r"(?:pedidos|restauracao|otimizador|salvaguardas)-[0-9]{4}[a-z0-9.-]{1,20}"
    return (
        x
        if _padrao(partes[0], versao) and all(_padrao(p, versao) or _padrao(p, r"[a-f0-9]{8,64}") for p in partes[1:])
        else None
    )


@lru_cache(maxsize=1)
def _municipios():
    """Rótulos vêm do catálogo versionado, não do texto livre da matrícula/oferta."""
    with (Path(__file__).parents[1] / "executor" / "municipios.csv").open(encoding="utf-8") as f:
        return {m["codigo_ibge"]: m["nome"] for m in csv.DictReader(f)}


def _local(x, chave="cod_ibge"):
    cod = x.get(chave)
    cod = str(cod) if type(cod) is int else cod
    cod = _padrao(cod, r"[0-9]{7}")
    return {chave: cod, "municipio": _municipios().get(cod, ""), "uf": _enum(x.get("uf"), UFS)}


def base(x):
    out = _resumo_base(x)
    for a in out["afrouxar"]:
        a["texto"] = AFROUXAR[a["campo"]]
    if x.get("observacao"):
        out["observacao"] = "A posição de fazendas sem contorno é aproximada pela sede do município."
    return out


def salvaguardas(x):
    x = _obj(x)
    motivos = {
        "sobreposicao_redd_sem_exclusao_conaredd",
        "sobreposicao_catalogo_sem_programa_identificado",
        "consentimento_clpi_pendente",
        "consulta_previa_nao_comprovada",
        "participacao_comunidade_insuficiente",
        "garantias_comunitarias_pendentes",
    }
    pendencias = {
        "verificacao_documental_pendente",
        "territorio_tradicional_nao_verificado",
        "cobertura_redd_nao_verificada",
    }
    out = {k: x.get(k) is True for k in ("pode_originar", "pode_reservar")}
    out["territorio_tradicional"] = (
        x.get("territorio_tradicional") if type(x.get("territorio_tradicional")) is bool else None
    )
    out.update(
        {
            "versao": _versao(x.get("versao")),
            "clpi": _enum(x.get("clpi"), {"comprovada", "pendente", "nao_identificado"}),
            "fracao_minima_comunidade": _num(x.get("fracao_minima_comunidade")),
            "bloqueios": [m if _enum(m, motivos) else "revisao_necessaria" for m in _lista(x.get("bloqueios"))],
            "pendencias": [m if _enum(m, pendencias) else "revisao_necessaria" for m in _lista(x.get("pendencias"))],
            "revisao_humana": {
                "direito": "LGPD art. 20; revisão por pessoa, compromisso Raíz",
                "rota": "/pedidos/{pedido_id}/revisoes",
            },
            "redd": {
                "estado": _enum(
                    _obj(x.get("redd")).get("estado"), {"sobreposicao", "sem_sobreposicao_verificada", "nao_verificado"}
                )
                or "nao_verificado"
            },
        }
    )
    if x.get("estado") == "nao_verificado":
        out["estado"] = "nao_verificado"
    return out


def _geometria(x):
    """Só o contorno 2D já autorizado pelo serviço; nunca busca nem libera geometria.

    O banco usa MultiPolygon e o transporte usa longitude/latitude (EPSG:4326).
    Feature, coleções e membros livres não atravessam esta projeção. Validar o
    formato aqui não substitui a autorização paga feita em obter_pedido.
    """
    if not isinstance(x, dict) or x.get("type") not in ("Polygon", "MultiPolygon"):
        return None

    def poligono(aneis):
        if not isinstance(aneis, list) or not aneis:
            return None
        resultado = []
        for anel in aneis:
            if not isinstance(anel, list) or len(anel) < 4:
                return None
            pontos = []
            for ponto in anel:
                if not isinstance(ponto, list) or len(ponto) != 2:
                    return None
                lon, lat = ponto
                if not (
                    type(lon) in (int, float)
                    and type(lat) in (int, float)
                    and -180 <= lon <= 180
                    and -90 <= lat <= 90
                    and math.isfinite(lon)
                    and math.isfinite(lat)
                ):
                    return None
                pontos.append([lon, lat])
            if pontos[0] != pontos[-1] or len({tuple(p) for p in pontos}) < 3:
                return None
            resultado.append(pontos)
        return resultado

    coords = x.get("coordinates")
    if x["type"] == "Polygon":
        projetadas = poligono(coords)
    else:
        if not isinstance(coords, list) or not coords:
            return None
        projetadas = []
        for item in coords:
            pol = poligono(item)
            if pol is None:
                return None
            projetadas.append(pol)
    return {"type": x["type"], "coordinates": projetadas} if projetadas is not None else None


def fazenda(x):
    out = {
        "cod_imovel": _car(x.get("cod_imovel")),
        **_local(x),
        **_numeros(x, ("hectares", "custo_usd_credito", "lon", "lat")),
        "creditos": _numeros(x["creditos"], ("p10", "p50", "p90")) if isinstance(x.get("creditos"), dict) else None,
        "ficha_liberada": x.get("ficha_liberada") is True,
        "papel": _enum(x.get("papel"), {"lote", "reserva"}),
        "metodo": _enum(x.get("metodo"), METODOS),
        "caminho": _enum(x.get("caminho"), CAMINHOS),
        "interesse": _enum(x.get("interesse"), NIVEIS),
        "pequena": x.get("pequena") is True,
        "local_aproximado": x.get("local_aproximado") is True,
        "trocou": _car(x.get("trocou")),
        "risco_terra": _enum(x.get("risco_terra"), {"baixo", "medio", "alto"}),
        "salvaguardas": salvaguardas(x.get("salvaguardas")),
        "revisao_humana": "/pedidos/{pedido_id}/revisoes",
    }
    if "geometria" in x:
        out["geometria"] = _geometria(x["geometria"])
    return out


def opcoes(xs):
    out = []
    for x in _lista(xs):
        if not isinstance(x, dict):
            continue
        resumo = _resumo_opcoes({"opcoes": [x]})["opcoes"]
        if not resumo:
            continue
        o = resumo[0]
        o["itens"] = [fazenda(i) for i in _lista(x.get("itens")) if isinstance(i, dict)]
        if x.get("observacao"):
            o["observacao"] = "A composição foi atualizada; refaça o pedido para conferir a disponibilidade."
        ab = _obj(x.get("abaixo_equilibrio"))
        if ab:
            o["abaixo_equilibrio"] = {
                **_numeros(
                    ab,
                    ("preco_usd", "fazendas", "creditos", "fracao", "preco_equilibrio_medio_usd", "base_que_se_paga"),
                ),
                "metodos": {m: _num(v) for m, v in _obj(ab.get("metodos")).items() if m in METODOS},
                "so_fecha_com_elas": ab.get("so_fecha_com_elas") is True,
                "aviso": "Há fazendas abaixo do preço de equilíbrio; confira os indicadores antes de contratar."
                if ab.get("aviso")
                else None,
            }
        out.append(o)
    return out


def alertas(xs):
    out = []
    for x in _lista(xs):
        if not isinstance(x, dict):
            continue
        tipo = _enum(x.get("tipo"), MENSAGENS) or "atualizacao"
        detalhe = _obj(x.get("detalhe"))
        out.append(
            {
                "tipo": tipo,
                "texto": MENSAGENS[tipo],
                "data": _data(x.get("data")),
                "cod_imovel": _car(x.get("cod_imovel")),
                "motivo": _enum(x.get("motivo"), MOTIVOS_ALERTA),
                "detalhe": {
                    **_numeros(detalhe, ("area_ha", "falta", "custo_antes_usd", "custo_agora_usd")),
                    "opcao": _enum(detalhe.get("opcao"), {"barata", "segura", "compacta"}),
                    "fecha_meta": detalhe.get("fecha_meta") if type(detalhe.get("fecha_meta")) is bool else None,
                },
            }
        )
    return out


def _campos(x):
    try:
        c = CamposPedido.model_validate(x).model_dump(mode="json")
    except ValidationError:
        return None
    onde = c["onde"]
    onde["ufs"] = [v for v in onde["ufs"] if v in UFS]
    onde["biomas"] = [v for v in onde["biomas"] if v in BIOMAS]
    onde["municipios"] = [v for v in onde["municipios"] if v in _municipios()]
    onde["fornecedores"] = [v for v in onde["fornecedores"] if _car(v)]
    return c


def pedido(x):
    from raiz.pedidos.ficha_credito import projetar_resposta

    out = {
        "id": _id(x.get("id")),
        "criado_em": _data(x.get("criado_em")),
        "campos": _campos(x.get("campos")),
        "status": _enum(x.get("status"), ESTADOS),
        "base": base(_obj(x.get("base"))),
        "opcoes": opcoes(x.get("opcoes")),
        "opcao_escolhida": _enum(x.get("opcao_escolhida"), {"barata", "segura", "compacta"}),
        "reservado_ate": _data(x.get("reservado_ate")),
        "alertas": alertas(x.get("alertas")),
        "versao_modelo": _versao(x.get("versao_modelo")),
        "revisao_lote": x.get("revisao_lote")
        if re.fullmatch(r"[a-f0-9]{64}", str(x.get("revisao_lote", "")))
        else None,
    }
    originais = {o.get("id"): o for o in _lista(x.get("opcoes")) if isinstance(o, dict)}
    for opcao in out["opcoes"]:
        opcao["ficha_credito"] = projetar_resposta(originais.get(opcao["id"], {}).get("ficha_credito"), x, opcao["id"])
    return out


def andamento(x):
    out = {
        "pedido": _id(x.get("pedido")),
        "status": _enum(x.get("status"), ESTADOS),
        **_numeros(
            x, ("meta", "com_interessado", "com_aceite", "com_contrato", "contatados", "recusas", "sem_resposta")
        ),
    }
    # A contagem pode conter a mesma fazenda em mais de um motivo; não somar como se fossem pessoas distintas.
    out["motivos"] = [
        {
            "motivo": "Motivo registrado; detalhes disponíveis somente para revisão humana.",
            "fazendas": _num(m.get("fazendas")),
        }
        for m in _lista(x.get("motivos"))
        if isinstance(m, dict)
    ]
    out["ondas"] = [
        {
            **_numeros(o, ("numero", "contatados")),
            "data": _data(o.get("data")),
            "canais": [
                c
                for c in _lista(o.get("canais"))
                if _enum(c, {"whatsapp", "email", "carta", "visita", "telefone", "parceiro", "painel"})
            ],
        }
        for o in _lista(x.get("ondas"))
        if isinstance(o, dict)
    ]
    out["fazendas"] = [fazenda(f) for f in _lista(x.get("fazendas")) if isinstance(f, dict)]
    out.update({k: _data(x.get(k)) for k in ("grupo_pronto_em", "proxima_onda_em")})
    faltou = _obj(x.get("faltou"))
    out["faltou"] = (
        {
            "falta": _num(faltou.get("falta")),
            "afrouxar": ["Revise os filtros do pedido para ampliar a base disponível."],
        }
        if faltou
        else None
    )
    return out


def notificacoes(xs):
    out = []
    for x in _lista(xs):
        if not isinstance(x, dict):
            continue
        tipo = _enum(x.get("tipo"), MENSAGENS) or "atualizacao"
        out.append(
            {
                "id": _num(x.get("id")),
                "pedido": _id(x.get("pedido")),
                "tipo": tipo,
                "texto": MENSAGENS[tipo],
                "data": _data(x.get("data")),
                "lida": x.get("lida") is True,
            }
        )
    return out


def analise(x):
    from raiz.documentos.certidao.esquema import ONUS

    out = {
        "cod_imovel": _car(x.get("cod_imovel")),
        **_local(x, "cod_municipio_ibge"),
        "bioma": _enum(x.get("bioma"), BIOMAS),
        **_numeros(
            x,
            (
                "hectares",
                "area_para_restaurar_ha",
                "custo_usd_credito",
                "preco_equilibrio_usd",
                "tir_projeto_pct_p50",
                "metano_tco2e_ano_p50",
            ),
        ),
        "metodo": _enum(x.get("metodo"), METODOS),
        "caminho_terra": _enum(
            x.get("caminho_terra"), {*CAMINHOS, "publica_sem_destinacao", "terra_indigena_ou_tradicional"}
        ),
        "risco_terra": _enum(x.get("risco_terra"), {"baixo", "medio", "alto"}),
        "versao": _versao(x.get("versao")),
        "explicacao": "Consulte os indicadores calculados. As evidências documentais exigem conferência humana.",
        "como_falar_com_o_dono": "Pela Raíz: peça o interesse dos donos no pedido de lote (nunca direto).",
    }
    for k in ("pequena", "embargo", "problema_no_cadastro", "simulacao_disponivel"):
        out[k] = x.get(k) if type(x.get(k)) is bool else None
    for k in ("creditos_ate_ano_25", "tir_com_fundo_clima_pct", "rebanho_cabecas"):
        out[k] = _numeros(x.get(k), ("p10", "p50", "p90"))
    out["metodo_area_ha"] = _numeros(x.get("metodo_area_ha"), METODOS)
    out["descontos_pct"] = _numeros(
        x.get("descontos_pct"), ("desconto_linha_base", "vazamento", "reserva_risco", "incerteza")
    )
    out["marcos_chance_pct"] = {
        k: _num(v) for k, v in _obj(x.get("marcos_chance_pct")).items() if _padrao(k, r"[1-9][0-9]?")
    }
    if "salvaguardas" in x:
        out["salvaguardas"] = salvaguardas(x["salvaguardas"])
    cert = _obj(x.get("certidao"))
    out["certidao"] = {
        "estado": _enum(cert.get("estado"), {"leitura_disponivel", "nao_lida"}),
        "arrendamento_ou_contrato_ativo": cert.get("arrendamento_ou_contrato_ativo")
        if type(cert.get("arrendamento_ou_contrato_ativo")) is bool
        else None,
        "aviso": "Leitura registrada pela Raíz; exige conferência humana antes de contratar.",
        "matriculas": [
            {
                "lida": m.get("lida") is True,
                "situacao": _enum(m.get("situacao"), {"ativa", "cancelada", "bloqueada", "ilegivel", "nao_e_certidao"}),
                "conferencia": _enum(
                    m.get("conferencia"), {"a_conferir", "conferida", "divergente", "cancelada", "revisar"}
                ),
                "origem_situacao": _enum(
                    m.get("origem_situacao"), {"chega_a_origem", "falta_ler_origem", "origem_desconhecida"}
                ),
                **_numeros(m, ("area_ha", "area_sobre_car_ha")),
                "onus_ativos": [o for o in _lista(m.get("onus_ativos")) if _enum(o, ONUS)],
            }
            for m in _lista(cert.get("matriculas"))
            if isinstance(m, dict)
        ],
    }
    out["sobreposicoes"] = {
        k: {"area_ha": _num(_obj(v).get("area_ha")), "verificada": _obj(v).get("verificada") is True}
        for k, v in _obj(x.get("sobreposicoes")).items()
        if k
        in {
            "projeto_carbono",
            "terra_publica",
            "terra_indigena",
            "quilombo",
            "territorio_tradicional",
            "unidade_conservacao",
            "redd_jurisdicional",
        }
    }
    comp = _obj(x.get("comprometimento"))
    out["comprometimento"] = {
        "ja_comprometida": comp.get("ja_comprometida") if type(comp.get("ja_comprometida")) is bool else None,
        "estado": _enum(comp.get("estado"), {"indicio_a_conferir", "nao_comprovado"}),
        "motivos": [
            m
            for m in _lista(comp.get("motivos"))
            if _enum(m, {"sobreposicao_com_projeto_carbono", "arrendamento_ou_contrato_averbado_ativo"})
        ],
        "aviso": "Ausência de indício não comprova disponibilidade dos direitos; confirmar documentos e vigência.",
    }
    return out


def revisao(x):
    c = _obj(x.get("criterios"))
    return {
        **_numeros(x, ("id", "revisao_id")),
        "cod_imovel": _car(x.get("cod_imovel")),
        "motivo": _enum(x.get("motivo"), {"exclusao_automatica", "nota_de_risco", "salvaguarda"}),
        "estado": _enum(x.get("estado"), {"pendente", "resolvida"}),
        "decisao": _enum(x.get("decisao"), {"mantida", "corrigir_dados", "recalcular"}),
        "criada_em": _data(x.get("criada_em")),
        "resolvida_em": _data(x.get("resolvida_em")),
        "criterios": {
            **{k: c.get(k) if type(c.get(k)) is bool else None for k in ("elegivel", "bloqueio", "problema")},
            "caminho_terra": _enum(
                c.get("caminho_terra"),
                {
                    "privada_matricula",
                    "posse_em_titulacao",
                    "assentamento",
                    "publica_concessao",
                    "publica_sem_destinacao",
                    "terra_indigena_ou_tradicional",
                },
            ),
            "risco_terra": _enum(c.get("risco_terra"), {"baixo", "medio", "alto"}),
            "restauracao_versao": _versao(c.get("restauracao_versao")),
            "regra": _versao(c.get("regra")),
        },
    }


def _titulo(x):
    if not isinstance(x, str):
        return "Pedido de lote"
    valor, _, onde = x.partition(" em ")
    if _padrao(valor, r"[0-9][0-9.,]*(?: (?:milhão|milhões))? (?:de créditos|de hectares|t FLAG por ano)") and all(
        lugar in UFS | BIOMAS | {"Brasil"} for lugar in onde.split(", ")
    ):
        return x
    return "Pedido de lote"


def resumos(xs):
    """O título persistido é derivado de filtros livres; a lista usa um rótulo controlado."""
    return [
        {
            "id": _id(x.get("id")),
            "criado_em": _data(x.get("criado_em")),
            "titulo": _titulo(x.get("titulo")),
            "status": _enum(x.get("status"), ESTADOS),
            "reservado_ate": _data(x.get("reservado_ate")),
            **_numeros(x, ("com_interesse", "alertas")),
        }
        for x in _lista(xs)
        if isinstance(x, dict)
    ]
