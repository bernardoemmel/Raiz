"""Catálogo Berkeley Brasil e documentos geográficos oficiais por projeto.

O XLSX tem proponentes e nomes de projetos: essas colunas jamais saem do leitor.
Catálogo sem limites não comprova que um CAR está comprometido. Nenhum ponto,
centroide ou nome de município é convertido em polígono de projeto.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

import httpx
from shapely import make_valid, union_all
from shapely.geometry import Polygon

from raiz.terra_comprometida import catalogo_fontes, normalizar

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
LIMITE = 40 * 1024 * 1024
_UFS = dict(
    zip(
        (
            "acre alagoas amapa amazonas bahia ceara distrito_federal espirito_santo goias maranhao mato_grosso "
            "mato_grosso_do_sul minas_gerais para paraiba parana pernambuco piaui rio_de_janeiro rio_grande_do_norte "
            "rio_grande_do_sul rondonia roraima santa_catarina sao_paulo sergipe tocantins"
        ).split(),
        "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split(),
        strict=True,
    )
)


def status_registro(s: str) -> str:
    s = str(s).strip().lower()
    if s in ("registered", "gold standard certified project", "verification approval requested", "late to verify"):
        return "ativo"
    if any(t in s for t in ("withdrawn", "canceled", "cancelled", "rejected", "denied")):
        return "retirado"
    if any(t in s for t in ("inactive", "completed", "terminated", "on hold")):
        return "inativo"
    if any(t in s for t in ("validation", "validated", "requested", "pipeline", "listed", "certified design")):
        return "em_validacao"
    return "desconhecido"


def _uf(v):
    if str(v).upper() in _UFS.values():
        return str(v).upper()
    chave = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().strip().lower().replace(" ", "_")
    return _UFS.get(chave)


def _download(client, url: str, *, headers=None) -> bytes:
    try:
        with client.stream("GET", url, headers=headers, follow_redirects=True) as r:
            r.raise_for_status()
            partes, total = [], 0
            for chunk in r.iter_bytes():
                total += len(chunk)
                if total > LIMITE:
                    raise ValueError("Fonte territorial excede o limite de download")
                partes.append(chunk)
            return b"".join(partes)
    except httpx.HTTPError:
        raise ValueError("Fonte territorial indisponível; consulta não concluída") from None


def _linhas(z, caminho, strings):
    with z.open(caminho) as f:
        for _, el in ET.iterparse(f, events=["end"]):
            if el.tag != f"{{{NS['m']}}}row":
                continue
            row = {}
            for c in el:
                col = re.sub(r"\d", "", c.get("r", ""))
                v = c.find("m:v", NS)
                if c.get("t") == "inlineStr":
                    row[col] = "".join(c.find("m:is", NS).itertext())
                elif v is not None:
                    row[col] = strings[int(v.text)] if c.get("t") == "s" else v.text
            yield row
            el.clear()


def ler_berkeley(dados: bytes, *, observado_em: str, versao: str = "v2026-08") -> dict:
    """Lê PROJECTS e Archive por cabeçalho, incluindo somente projetos terrestres no Brasil."""
    meta = catalogo_fontes()["fontes"]["berkeley"]
    if versao != meta["versao"]:
        raise ValueError("Versão Berkeley não consta do catálogo conferido")
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        if sum(i.file_size for i in z.infolist()) > 350 * 1024 * 1024:
            raise ValueError("XLSX expandido excede o limite")
        strings = ["".join(x.itertext()) for x in ET.fromstring(z.read("xl/sharedStrings.xml"))]
        rel = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        sheets = ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS)
        registros = {}
        for sheet in sheets:
            nome = sheet.get("name")
            if nome not in ("PROJECTS", "Archive"):
                continue
            target = rel[sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")]
            path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            header = None
            for row in _linhas(z, path, strings):
                if "Project ID" in row.values():
                    header = {v.strip(): k for k, v in row.items()}
                    required = {"Project ID", "Voluntary Registry", "Voluntary Status", "Scope", "Country", "State"}
                    if not required <= header.keys():
                        raise ValueError("Cabeçalho Berkeley mudou de formato")
                    continue
                if not header:
                    continue

                def get(k, row=row, header=header):
                    return row.get(header[k], "")

                if get("Country").strip().lower() not in ("brazil", "brasil") or get("Scope") != "Forestry & Land Use":
                    continue
                registry = {"Gold Standard": "GS", "GOLD": "GS", "Isometric": "ISO", "Verra": "VCS"}.get(
                    get("Voluntary Registry"), get("Voluntary Registry")
                )
                oid = get("Project ID")
                if registry not in ("VCS", "ACR", "CAR", "ART", "GS", "ISO"):
                    raise ValueError("Registro Berkeley desconhecido")
                # PROJECTS prevalece se um projeto do arquivo voltou ao registro.
                if oid in registros and nome == "Archive":
                    continue
                registros[oid] = normalizar(
                    {
                        "fonte_id": "berkeley",
                        "objeto_id": oid,
                        "registro": registry,
                        "tipo": "programa_jurisdicional" if registry == "ART" else "projeto_carbono",
                        "situacao": "inativo" if nome == "Archive" else status_registro(get("Voluntary Status")),
                        "certeza": "catalogo_sem_geometria",
                        "uf": _uf(get("State")),
                        "geometry": None,
                        "fonte_url": meta["url"],
                        "data_referencia": meta["data_referencia"],
                        "observado_em": observado_em,
                    }
                )
            if header is None:
                raise ValueError("Planilha Berkeley sem cabeçalho reconhecido")
    return {
        "registros": list(registros.values()),
        "cobertura": {
            "fonte_id": "berkeley",
            "estado": "parcial",
            "escopo": "brasil",
            "recorte": "BR",
            "url": meta["url"],
            "licenca": meta["licenca"],
            "data_referencia": meta["data_referencia"],
            "consultado_em": observado_em,
        },
    }


def coletar_berkeley(*, cliente=None, observado_em: str | None = None) -> dict:
    """Um catálogo pequeno versionado (17 MB), sem descarregar geometrias mundiais."""
    hoje = dt.date.fromisoformat(observado_em or dt.date.today().isoformat()).isoformat()
    meta = catalogo_fontes()["fontes"]["berkeley"]
    if cliente is None:
        with httpx.Client(timeout=60) as c:
            return coletar_berkeley(cliente=c, observado_em=hoje)
    return ler_berkeley(_download(cliente, meta["arquivo"]), observado_em=hoje)


def ler_kml(dados: bytes):
    """Somente polígonos explícitos do documento, com furos. Ignora descrições e nomes."""
    if len(dados) > LIMITE or b"<!DOCTYPE" in dados.upper() or b"<!ENTITY" in dados.upper():
        raise ValueError("Documento KML fora do contrato seguro")
    root = ET.fromstring(dados)

    def coords(el):
        if el is None:
            return []
        return [tuple(float(n) for n in c.split(",")[:2]) for c in (el.text or "").split()]

    polys = []
    for p in root.findall(".//{*}Polygon"):
        shell = coords(p.find("{*}outerBoundaryIs/{*}LinearRing/{*}coordinates"))
        holes = [coords(e) for e in p.findall("{*}innerBoundaryIs/{*}LinearRing/{*}coordinates")]
        if len(shell) >= 4:
            polys.append(make_valid(Polygon(shell, holes)))
    if not polys:
        raise ValueError("Documento sem polígono de projeto; pontos não provam área")
    return union_all(polys)


VERRA_API = "https://prod-us.api.platts.com/ci-raas-prod/br-reg/rest"
VERRA_PADRAO = "150000000000001"  # VCS: getStandardList público, conferido 2026-11-12.


def _json_publico(c, url, *, metodo="GET", corpo=None, headers=None):
    try:
        r = c.request(metodo, url, json=corpo, headers=headers)
        r.raise_for_status()
        if len(r.content) > LIMITE:
            raise ValueError("Resposta do registro excede o limite")
        return r.json()
    except (httpx.HTTPError, ValueError):
        raise ValueError("Registro público indisponível ou formato alterado") from None


def coletar_verra(codigo: str, *, cliente=None, observado_em: str | None = None) -> dict:
    """Consulta oficial pequena por ID; mesma rota pública usada pelo Registry, sem login.

    Só aceita projeto brasileiro e arquivos do tipo oficial Project Boundary (KML
    File). Havendo múltiplos limites sem versão comparável, conserva indício em vez
    de escolher arbitrariamente um polígono confirmado. Respeita erros e 429 sem
    contornar controles de acesso. A rotina nacional pode fornecer os IDs Berkeley.
    """
    codigo = str(codigo).removeprefix("VCS")
    if not re.fullmatch(r"\d{1,8}", codigo):
        raise ValueError("Identificador Verra inválido")
    hoje = dt.date.fromisoformat(observado_em or dt.date.today().isoformat()).isoformat()
    if cliente is None:
        with httpx.Client(timeout=45) as c:
            return coletar_verra(codigo, cliente=c, observado_em=hoje)
    url = f"https://registry.verra.org/verra/public/program/VCS/projects/{codigo}"
    coverage = {
        "fonte_id": "verra",
        "estado": "parcial",
        "escopo": "projeto",
        "recorte": f"VCS{codigo}",
        "url": url,
        "licenca": catalogo_fontes()["fontes"]["verra"]["licenca"],
        "data_referencia": None,
        "consultado_em": hoje,
    }
    headers = {"standardId": VERRA_PADRAO, "standardAcronym": "VCS", "registry": "VERRA"}
    payload = _json_publico(
        cliente, f"{VERRA_API}/public-report-manager/getProjectById/{codigo}/Markit", headers=headers
    )
    if not isinstance(payload, dict) or str(payload.get("id")) != codigo:
        raise ValueError("Projeto retornado não corresponde ao identificador pedido")
    unidades = payload.get("mixedUnitList") or []
    brasil = [u for u in unidades if isinstance(u, dict) and u.get("country_name") in ("Brazil", "Brasil")]
    if not brasil:
        raise ValueError("Projeto não confirmado no Brasil pela fonte oficial")
    uf = _uf(str(brasil[0].get("province", "")).removeprefix("State of "))
    documentos = [
        d
        for d in payload.get("documentList", [])
        if isinstance(d, dict)
        and d.get("type_name") == "Project Boundary (KML File)"
        and str(d.get("document_name", "")).lower().endswith(".kml")
        and isinstance(d.get("id"), int)
    ]
    geoms = []
    # Um projeto não deve poder produzir download ilimitado pela lista documental.
    if len(documentos) > 20:
        raise ValueError("Projeto requer revisão dos documentos geográficos")
    for d in documentos:
        try:
            with cliente.stream(
                "POST",
                f"{VERRA_API}/document-manager/public/downloadDocumentById",
                json={"id": d["id"]},
                headers=headers,
            ) as r:
                r.raise_for_status()
                partes, total = [], 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > LIMITE:
                        raise ValueError("Documento territorial excede limite")
                    partes.append(chunk)
            geoms.append(ler_kml(b"".join(partes)))
        except httpx.HTTPError:
            raise ValueError("Documento geográfico público indisponível") from None
    registro = normalizar(
        {
            "fonte_id": "verra",
            "objeto_id": f"VCS{codigo}",
            "registro": "VCS",
            "tipo": "projeto_carbono",
            "situacao": status_registro(payload.get("state_name") or payload.get("status")),
            "certeza": "poligono_oficial"
            if len(geoms) == 1
            else "poligono_secundario"
            if geoms
            else "catalogo_sem_geometria",
            "uf": uf,
            "geometry": union_all(geoms) if geoms else None,
            "fonte_url": url,
            "data_referencia": None,
            "observado_em": hoje,
            "inicio": payload.get("project_start_date"),
            "fim": payload.get("project_end_date"),
            "evidencia_status_url": url,
        }
    )
    return {"registros": [registro], "cobertura": coverage}


def iterar_compromissos(*, fontes=None, bbox=None, projetos_verra=None, concluidos_verra=(), limite_verra=None):
    """Coleta incremental; o chamador confirma cada yield no banco antes de avançar.

    Defaults: catálogo nacional + ART + limites SFB no Brasil. Verra é fase
    explícita, com IDs derivados do catálogo quando omitidos. O checkpoint é o
    conjunto de IDs persistidos pelo chamador, não um arquivo anterior ao commit.
    Um limite permite dividir a atualização em rodadas sem perder os resultados.
    """
    from raiz.coleta.compromissos_concessoes import catalogo_art, coletar_sfb

    fontes = fontes if fontes is not None else ["berkeley", "art_jurisdicional", "sfb_concessoes"]
    bbox = bbox if bbox is not None else (-74, -34, -34, 6)
    validas = {"berkeley", "art_jurisdicional", "sfb_concessoes", "verra", "limites_pesquisa"}
    if not isinstance(fontes, (list, tuple)) or set(fontes) - validas:
        raise ValueError("Fonte de compromisso não reconhecida")
    if limite_verra is not None and (not isinstance(limite_verra, int) or limite_verra <= 0):
        raise ValueError("Limite Verra deve ser inteiro positivo")
    berkeley = None
    for fonte in dict.fromkeys(fontes):
        if fonte == "verra" and projetos_verra is None:
            # Falha no catálogo interrompe a descoberta; não vira uma lista vazia de projetos.
            berkeley = berkeley or coletar_berkeley()
            projetos_verra = [r["objeto_id"] for r in berkeley["registros"] if r["registro"] == "VCS"]
        ids = projetos_verra if fonte == "verra" else [None]
        if fonte == "verra":
            feitos = {str(i).removeprefix("VCS") for i in concluidos_verra}
            ids = list(
                dict.fromkeys(str(i).removeprefix("VCS") for i in ids if str(i).removeprefix("VCS") not in feitos)
            )
            if any(not re.fullmatch(r"\d{1,8}", i) for i in ids):
                raise ValueError("Identificador Verra inválido")
            ids = ids[:limite_verra] if limite_verra else ids
        for oid in ids:
            try:
                if fonte == "berkeley":
                    berkeley = berkeley or coletar_berkeley()
                    result = berkeley
                elif fonte == "art_jurisdicional":
                    result = catalogo_art()
                elif fonte == "sfb_concessoes":
                    result = coletar_sfb(bbox)
                elif fonte == "limites_pesquisa":
                    from raiz.coleta.compromissos_pesquisa import coletar_limites_pesquisa

                    result = coletar_limites_pesquisa(bbox=bbox)
                else:
                    result = coletar_verra(oid)
                yield result
            except (ValueError, httpx.HTTPError):
                meta = catalogo_fontes()["fontes"][fonte]
                yield {
                    "registros": [],
                    "cobertura": {
                        "fonte_id": fonte,
                        "estado": "indisponivel",
                        "escopo": "projeto" if oid else "bbox" if fonte == "sfb_concessoes" else "brasil",
                        "recorte": f"VCS{oid}" if oid else "BR",
                        "bbox": bbox if fonte == "sfb_concessoes" else None,
                        "url": meta["url"],
                        "licenca": meta["licenca"],
                        "data_referencia": None,
                        "consultado_em": dt.date.today().isoformat(),
                    },
                }
                if fonte == "verra":
                    # Não insistir após indisponibilidade/limite do registro. Retomar só os não concluídos.
                    break


def coletar_compromissos(**kwargs) -> list[dict]:
    """Compatibilidade para consumidores pequenos; rotinas nacionais devem consumir o iterador."""
    return list(iterar_compromissos(**kwargs))
