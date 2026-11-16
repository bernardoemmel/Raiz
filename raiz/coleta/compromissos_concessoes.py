"""Concessões federais e contexto REDD, sem dados de pessoas.

O SFB publica separadamente contratos e limites de UMFs. A correspondência exata
entre floresta e UMF permite usar o polígono; o cadastro de florestas públicas,
uma Flona inteira ou um programa estadual nunca substitui esse limite. Há
contratos sem geometria no serviço: cobertura parcial não significa terra livre.

Verificado em 2026-11-12: 29 contratos e 22 limites no serviço. Nenhum desses
totais é fixado na coleta. A edição da camada não é data de validade contratual.
Geometrias e cruzamentos resultantes destinam-se ao armazenamento privado.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import UTC, date, datetime

import requests
from bs4 import BeautifulSoup
from shapely.errors import GEOSException
from shapely.geometry import box, shape

from raiz.coleta.http import sessao as criar_sessao

SFB_CONTRATOS = (
    "https://www.gov.br/florestal/pt-br/assuntos/concessoes-e-monitoramento/concessoes-florestais-em-andamento"
)
SFB_LIMITES = "https://smapas.florestal.gov.br/server/rest/services/Hosted/Limites_UMFs/FeatureServer/1"
ART_BOLETIM = "https://artredd.org/art-september-2026-newsletter/"
ART_RELATORIO = "https://artredd.org/wp-content/uploads/2024/12/ART-2023-Annual-Report.pdf"
ART_MT = "https://www.artredd.org/art-publishes-trees-concept-for-mato-grosso-brazil-on-the-art-registry/"
VERSAO_CATALOGO_ART = "2026-11-12"
LIMITE_BYTES = 20 * 1024 * 1024


def _texto(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto)
    return re.sub(r"[^a-z0-9]", "", normal.encode("ascii", "ignore").decode().lower())


def _chave(floresta: str, umf: str) -> str:
    # O serviço omite o sufixo Lote Sul; IA e IB distinguem essas duas unidades.
    floresta = re.sub(r"\s*\([A-Z]{2}\)\s*$", "", floresta)
    floresta = re.sub(r"lote\s+sul", "", floresta, flags=re.I)
    floresta = re.split(r"\s+UMF\s+", floresta, flags=re.I)[0]
    return f"{_texto(floresta)}:{_texto(re.sub(r'^UMF\s*', '', umf, flags=re.I))}"


def _baixar(s, url: str, *, params: dict | None = None) -> bytes:
    with s.get(url, params=params, timeout=45, stream=True) as resposta:
        resposta.raise_for_status()
        partes, tamanho = [], 0
        for parte in resposta.iter_content(64 * 1024):
            tamanho += len(parte)
            if tamanho > LIMITE_BYTES:
                raise ValueError("Resposta da fonte excede o limite de coleta.")
            partes.append(parte)
        return b"".join(partes)


def _json(s, params: dict) -> dict:
    resultado = json.loads(_baixar(s, SFB_LIMITES + "/query", params=params))
    if not isinstance(resultado, dict) or resultado.get("error"):
        raise ValueError("A consulta geográfica não foi concluída pelo SFB.")
    if resultado.get("exceededTransferLimit"):
        # Falhar evita publicar consulta truncada como ausência de sobreposição.
        raise ValueError("A consulta do SFB foi truncada; reduza o recorte.")
    if not isinstance(resultado.get("features"), list):
        raise ValueError("A resposta do SFB não contém a lista de unidades.")
    return resultado


def contratos_sfb(html: bytes, *, observado_em: str) -> dict[str, dict]:
    """Lê apenas floresta, UMF, UF e data; descarta concessionário na entrada.

    Floresta e UMF são usados somente como chave local da junção. O registro de
    saída tem identificador opaco, sem copiar células livres da tabela.
    """
    soup = BeautifulSoup(html, "html.parser")
    tabela = None
    for candidata in soup.select("table"):
        primeira = candidata.select_one("tr")
        cabecalho = [_texto(c.get_text(" ", strip=True)) for c in primeira.select("th,td")] if primeira else []
        if {"flona", "umf", "datadeassinaturadocontrato"}.issubset(cabecalho):
            tabela = candidata
            break
    if tabela is None:
        raise ValueError("A tabela oficial de contratos do SFB mudou de formato.")
    pos = {nome: i for i, nome in enumerate(cabecalho)}
    resultado, floresta = {}, ""
    for linha in tabela.select("tr")[1:]:
        celulas = linha.select("th,td")
        if len(celulas) != len(cabecalho):
            raise ValueError("Linha contratual com estrutura desconhecida.")
        valor_floresta = celulas[pos["flona"]].get_text(" ", strip=True)
        if _texto(valor_floresta) == "total":
            continue
        floresta = valor_floresta or floresta
        uf = re.search(r"\(([A-Z]{2})\)\s*$", floresta)
        umf = celulas[pos["umf"]].get_text(" ", strip=True)
        if not uf or not re.fullmatch(r"[IVX]+[AB]?", umf):
            raise ValueError("Unidade de manejo sem identificador territorial reconhecido.")
        inicio = (
            datetime.strptime(celulas[pos["datadeassinaturadocontrato"]].get_text(" ", strip=True), "%d/%m/%Y")
            .date()
            .isoformat()
        )
        chave = _chave(floresta, umf)
        if chave in resultado:
            raise ValueError("Unidade de manejo duplicada na relação contratual.")
        resultado[chave] = {
            "fonte_id": "sfb_concessoes",
            "objeto_id": "sfb-" + hashlib.sha256(chave.encode()).hexdigest()[:20],
            "registro": "SFB",
            "tipo": "concessao_florestal",
            "situacao": "ativo" if inicio <= observado_em else "desconhecido",
            "certeza": "catalogo_sem_geometria",
            "uf": uf[1],
            "geometry": None,
            "fonte_url": SFB_CONTRATOS,
            "data_referencia": None,
            "observado_em": observado_em,
            "inicio": inicio,
            "fim": None,
            "evidencia_status_url": SFB_CONTRATOS,
        }
    if not resultado:
        raise ValueError("A tabela oficial não retornou contratos reconhecidos.")
    return resultado


def coletar_sfb(bbox: tuple[float, float, float, float], *, sessao=None, observado_em: str | None = None) -> dict:
    """Consulta limites no recorte WGS84; não baixa a camada nacional completa.

    O índice nacional contém apenas identificadores territoriais. Assim, uma
    geometria conhecida fora do recorte não reaparece como indício sem geometria.
    Retornos parciais conservam os contratos; falhas nunca viram cobertura vazia.
    """
    if (
        len(bbox) != 4
        or not all(math.isfinite(v) for v in bbox)
        or not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90)
    ):
        raise ValueError("Recorte WGS84 inválido.")
    observado_em = date.fromisoformat(observado_em or datetime.now(UTC).date().isoformat()).isoformat()
    cobertura = {
        "fonte_id": "sfb_concessoes",
        "consultado_em": observado_em,
        "data_referencia": None,
        "estado": "indisponivel",
        "escopo": "bbox",
        "bbox": list(bbox),
        "recorte": ",".join(str(float(v)) for v in bbox),
        "url": SFB_LIMITES,
        "licenca": "Contratos: CC BY-ND 3.0; camada geométrica: licença não informada pelo SFB.",
    }
    s = sessao or criar_sessao()
    contratos = {}
    try:
        contratos = contratos_sfb(_baixar(s, SFB_CONTRATOS), observado_em=observado_em)
        campos = {"where": "1=1", "outFields": "fid,umf,nome", "resultRecordCount": 2000}
        indice = _json(s, {**campos, "f": "json", "returnGeometry": "false"})
        chaves_com_limite = set()
        for item in indice["features"]:
            atr = item.get("attributes", {})
            if not isinstance(atr.get("nome"), str) or not isinstance(atr.get("umf"), str):
                raise ValueError("Identificador da camada do SFB ausente.")
            chaves_com_limite.add(_chave(atr["nome"], atr["umf"]))
        geometrico = _json(
            s,
            {
                **campos,
                "f": "geojson",
                "geometry": ",".join(str(v) for v in bbox),
                "geometryType": "esriGeometryEnvelope",
                "spatialRel": "esriSpatialRelIntersects",
                "inSR": 4326,
                "outSR": 4326,
                "returnGeometry": "true",
            },
        )
        registros = [dict(v) for k, v in contratos.items() if k not in chaves_com_limite]
        vistos, sem_contrato = set(), False
        recorte = box(*bbox)
        for item in geometrico["features"]:
            atr = item.get("properties", {})
            chave = _chave(atr.get("nome", ""), atr.get("umf", ""))
            if chave not in contratos:
                sem_contrato = True
                continue  # Limite sem contrato não prova comprometimento atual.
            geom = shape(item["geometry"])
            if geom.is_empty or not geom.is_valid or geom.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError("Geometria oficial ausente ou inválida.")
            minx, miny, maxx, maxy = geom.bounds
            if not (-180 <= minx <= maxx <= 180 and -90 <= miny <= maxy <= 90):
                raise ValueError("A fonte não retornou coordenadas WGS84.")
            if chave in vistos:
                raise ValueError("Unidade repetida; não é seguro omitir partes do limite.")
            if not geom.intersects(recorte):
                continue
            vistos.add(chave)
            registros.append(
                {**contratos[chave], "geometry": geom, "certeza": "poligono_oficial", "fonte_url": SFB_LIMITES}
            )
        cobertura["estado"] = "parcial" if sem_contrato or set(contratos) - chaves_com_limite else "consultado"
        return {"registros": registros, "cobertura": cobertura}
    except (requests.RequestException, ValueError, KeyError, TypeError, GEOSException):
        cobertura["estado"] = "parcial" if contratos else "indisponivel"
        return {"registros": list(contratos.values()), "cobertura": cobertura}
    finally:
        if sessao is None:
            s.close()


def catalogo_art() -> dict:
    """Fatos datados verificados, sem simular consulta atual nem vínculo com CAR.

    AC/PA/TO estavam em validação/verificação no boletim de 17/09/2026. A lista
    de AP/MA no relatório de 2023 e o conceito de MT não permitem inferir etapa
    atual. Os períodos de creditação não são vigência de um ônus sobre imóveis.
    """
    registros = []
    for uf in ("AC", "AP", "MA", "MT", "PA", "TO"):
        validacao = uf in {"AC", "PA", "TO"}
        url = ART_BOLETIM if validacao else ART_MT if uf == "MT" else ART_RELATORIO
        referencia = "2026-09-17" if validacao else "2023-12-09" if uf == "MT" else None
        registros.append(
            {
                "fonte_id": "art_jurisdicional",
                "objeto_id": f"art-br-{uf.lower()}",
                "registro": "ART",
                "tipo": "programa_jurisdicional",
                "situacao": "em_validacao" if validacao else "desconhecido",
                "certeza": "contexto_jurisdicional",
                "uf": uf,
                "geometry": None,
                "fonte_url": url,
                "data_referencia": referencia,
                "observado_em": VERSAO_CATALOGO_ART,
                "inicio": None,
                "fim": None,
                "evidencia_status_url": url,
            }
        )
    return {
        "registros": registros,
        "cobertura": {
            "fonte_id": "art_jurisdicional",
            "consultado_em": VERSAO_CATALOGO_ART,
            "data_referencia": "2026-09-17",
            "estado": "parcial",
            "escopo": "uf",
            "recorte": "BR",
            "url": ART_BOLETIM,
            "licenca": "Fatos de comunicados públicos da ART; textos e geometrias não redistribuídos.",
        },
    }
