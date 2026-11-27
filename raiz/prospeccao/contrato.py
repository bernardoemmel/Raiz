"""Projeção positiva recursiva da ficha; conserva integralmente fontes e datas."""

from __future__ import annotations

import uuid

MUDANCAS = object()
# Lista positiva em todos os níveis. Acrescentar dados livres ao dicionário da
# ficha não os inclui no snapshot ou na exportação, mesmo que o chamador erre o contrato.
MEDIDA = dict.fromkeys(("valor", "unidade", "fonte", "data_referencia", "data_corte", "estimado"))
META = dict.fromkeys(("fonte", "data_referencia", "regra_versao", "origem"))
EVIDENCIA_COMPROMISSO = {
    **dict.fromkeys(
        (
            "fonte_id",
            "objeto_id",
            "registro",
            "tipo",
            "situacao",
            "certeza",
            "fonte_url",
            "data_referencia",
            "observado_em",
            "inicio",
            "fim",
        )
    ),
    "area": MEDIDA,
}
ESQUEMA = {
    **dict.fromkeys(("versao", "codigo_car", "municipio", "cod_ibge", "uf", "bioma", "data_corte", "disponivel")),
    "area_total": MEDIDA,
    "area_restauravel": MEDIDA,
    "caminho_terra": {**dict.fromkeys(("codigo", "rotulo", "situacao")), **META},
    "pendencias": [dict.fromkeys(("codigo", "texto"))],
    "sobreposicoes": [{**dict.fromkeys(("codigo", "rotulo")), "area": MEDIDA}],
    "embargos": {"area": MEDIDA, "situacao": None},
    "serie_uso": [{"ano": None, **{uso: MEDIDA for uso in ("mata", "pasto", "lavoura", "agua")}}],
    "perdas": [{**dict.fromkeys(("ano", "tipo", "rotulo")), "area": MEDIDA}],
    "credito": {
        **{p: MEDIDA for p in ("p10", "p50", "p90")},
        **dict.fromkeys(("base", "metodo", "versao_modelo")),
    },
    "tir": {**{p: MEDIDA for p in ("p10", "p50", "p90")}, "tipo": None},
    "risco": {"nivel": None, **META},
    "agrupamento": {"pequena": None, "grupo_id": None, "imoveis": MEDIDA, "area": MEDIDA},
    "terra_comprometida": {
        **dict.fromkeys(("versao", "situacao", "aviso")),
        "area_confirmada": MEDIDA,
        "area_indicio": MEDIDA,
        "evidencias": [EVIDENCIA_COMPROMISSO],
        "contexto_jurisdicional": [EVIDENCIA_COMPROMISSO],
        "cobertura": [
            dict.fromkeys(
                ("fonte_id", "estado", "escopo", "recorte", "url", "licenca", "data_referencia", "consultado_em")
            )
        ],
    },
    "versao_ficha": dict.fromkeys(("id", "hash", "registrada_em")),
    "o_que_mudou": {
        **dict.fromkeys(("primeira_consulta", "consulta_anterior_em", "versao_anterior_id", "versao_atual_id")),
        "mudancas": MUDANCAS,
    },
}


def _filtrar(valor, formato):
    if formato is MUDANCAS:
        return filtrar_mudancas(valor)
    if isinstance(formato, dict):
        return {k: _filtrar(valor[k], v) for k, v in formato.items() if k in valor} if isinstance(valor, dict) else None
    if isinstance(formato, list):
        return [_filtrar(item, formato[0]) for item in valor] if isinstance(valor, list) else None
    return valor if isinstance(valor, (str, int, float, bool)) or valor is None else None


def filtrar_mudancas(mudancas) -> list[dict]:
    """Antes/depois usam o schema do campo alterado; nenhum dicionário livre passa."""
    if not isinstance(mudancas, list):
        return []
    campos = {
        k: ESQUEMA[k]
        for k in (
            "pendencias",
            "embargos",
            "caminho_terra",
            "terra_comprometida",
            "sobreposicoes",
            "serie_uso",
            "credito",
            "tir",
            "risco",
            "area_total",
            "area_restauravel",
            "disponivel",
        )
    }
    campos.update(fogo=ESQUEMA["perdas"], desmatamento=ESQUEMA["perdas"])
    saida = []
    for item in mudancas:
        if not isinstance(item, dict):
            continue
        campo = item.get("campo")
        if campo == "lotes_da_conta" and item.get("tipo") in {"entrou_lote", "saiu_lote"}:
            limpo = {
                k: _filtrar(item.get(k), None) for k in ("tipo", "campo", "fonte", "data_referencia", "data_corte")
            }
            for lado in ("antes", "depois"):
                limpo[lado] = []
                valores = item.get(lado)
                for codigo in valores if isinstance(valores, list) else []:
                    try:
                        limpo[lado].append(str(uuid.UUID(str(codigo))))
                    except (ValueError, TypeError, AttributeError):
                        continue
        elif isinstance(campo, str) and campo in campos and item.get("tipo") == campo:
            limpo = {
                k: _filtrar(item.get(k), None) for k in ("tipo", "campo", "fonte", "data_referencia", "data_corte")
            }
            limpo.update({lado: _filtrar(item.get(lado), campos[campo]) for lado in ("antes", "depois")})
        else:
            continue
        saida.append(limpo)
    return saida


def projetar_ficha(ficha: dict) -> dict:
    """Mantém valores e proveniência; só remove chaves fora do contrato da terra."""
    return _filtrar(ficha, ESQUEMA) or {}
