"""Planilha ODS do georreferenciamento (a que o profissional credenciado envia ao SIGEF), E5 passo 5.

Lida com zipfile + ElementTree (sem dependência nova). As colunas são achadas pelo nome do cabeçalho, sem acento e em
minúsculas: código do vértice, longitude, latitude, sigma (precisão) de cada uma, altitude, tipo do limite, método,
CNS, matrícula. O formato exato da planilha do SIGEF não foi conferido com um arquivo real: o leitor procura o
cabeçalho em qualquer aba e avisa o que não achou.

Validação (achados da fase "formato" e "geometria"): código do vértice no padrão do SIGEF, coordenada que não lê,
vértice repetido, precisão acima da tolerância do tipo de limite (artificial LA = 0,50 m, natural LN = 3,00 m;
vértice virtual V = 7,50 m), polígono que se cruza, e a área. O polígono sai para comparar com o SIGEF e o CAR.
Nome de confrontante não é lido.
"""

from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from shapely.geometry import Polygon

from raiz.titulo import geometria as G
from raiz.titulo.achados import Achado, chave_registro

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
CODIGO_SIGEF = re.compile(r"^[A-Z0-9]{3,5}-[MPV]-\d{1,6}$")

COLUNAS = {  # nome lógico -> pedaços que o cabeçalho tem (sem acento, minúsculo)
    "codigo": ("codigo", "vertice"),
    "longitude": ("longitude",),
    "sigma_longitude": ("sigma long", "sigma_long", "sigma x", "sigma e", "precisao long"),
    "latitude": ("latitude",),
    "sigma_latitude": ("sigma lat", "sigma_lat", "sigma y", "sigma n", "precisao lat"),
    "altitude": ("altitude",),
    "tipo_limite": ("tipo de limite", "tipo limite", "limite"),
    "metodo": ("metodo",),
    "cns": ("cns",),
    "matricula": ("matricula",),
}


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")
    return " ".join(s.lower().replace("_", " ").split())


def tabelas(arquivo: str | Path | bytes) -> dict[str, list[list[str]]]:
    """{aba: linhas} de um .ods, expandindo células e linhas repetidas."""
    dados = arquivo if isinstance(arquivo, bytes) else Path(arquivo).read_bytes()
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        raiz = ET.fromstring(z.read("content.xml"))
    out = {}
    for t in raiz.iter(f"{_T}table"):
        linhas = []
        for row in t.iter(f"{_T}table-row"):
            celulas = []
            for c in row:
                if c.tag not in (f"{_T}table-cell", f"{_T}covered-table-cell"):
                    continue
                n = int(c.get(f"{_T}number-columns-repeated", "1"))
                texto = " ".join("".join(p.itertext()) for p in c.findall("text:p", NS)).strip()
                celulas += [texto] * min(n, 64)
            while celulas and not celulas[-1]:
                celulas.pop()
            rep = int(row.get(f"{_T}number-rows-repeated", "1"))
            if celulas:
                linhas += [celulas] * min(rep, 10000)
        out[t.get(f"{_T}name") or f"aba{len(out) + 1}"] = linhas
    return out


def _mapa_cabecalho(linha: list[str]) -> dict[str, int]:
    norm = [_norm(c) for c in linha]
    m = {}
    for nome, chaves in COLUNAS.items():
        for i, h in enumerate(norm):
            if i in m.values():
                continue
            if any(k in h for k in chaves) and not (nome in ("longitude", "latitude") and "sigma" in h):
                m[nome] = i
                break
    return m


def _coord(s: str) -> float | None:
    if not s:
        return None
    if "°" in s or "º" in s:
        return G.dms_para_graus(s)
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", ".")) if s not in (None, "") else None
    except ValueError:
        return None


@dataclass
class VerticePlanilha:
    codigo: str
    lon: float | None
    lat: float | None
    sigma_lon: float | None = None
    sigma_lat: float | None = None
    tipo_limite: str | None = None
    linha: int = 0


@dataclass
class Perimetro:
    aba: str
    vertices: list[VerticePlanilha] = field(default_factory=list)
    cns: str | None = None
    matricula: str | None = None
    faltam_colunas: list[str] = field(default_factory=list)

    @property
    def poligono(self) -> Polygon | None:
        pts = [(v.lon, v.lat) for v in self.vertices if v.lon is not None and v.lat is not None]
        return Polygon(pts) if len(pts) >= 3 else None


def _cel(r: list[str], m: dict[str, int], nome: str) -> str:
    k = m.get(nome)
    return r[k].strip() if k is not None and k < len(r) else ""


def perimetros(arquivo: str | Path | bytes) -> list[Perimetro]:
    """Um perímetro por aba que tem cabeçalho com código, longitude e latitude."""
    out = []
    for aba, linhas in tabelas(arquivo).items():
        for i, linha in enumerate(linhas[:30]):
            m = _mapa_cabecalho(linha)
            if {"codigo", "longitude", "latitude"} <= set(m):
                p = Perimetro(aba, faltam_colunas=sorted(set(COLUNAS) - set(m)))
                for j, r in enumerate(linhas[i + 1 :], start=i + 2):
                    cod = _cel(r, m, "codigo").upper()
                    if not cod:
                        continue
                    p.vertices.append(
                        VerticePlanilha(
                            cod,
                            _coord(_cel(r, m, "longitude")),
                            _coord(_cel(r, m, "latitude")),
                            _num(_cel(r, m, "sigma_longitude")),
                            _num(_cel(r, m, "sigma_latitude")),
                            _cel(r, m, "tipo_limite").upper() or None,
                            j,
                        )
                    )
                    p.cns = p.cns or _cel(r, m, "cns") or None
                    p.matricula = p.matricula or _cel(r, m, "matricula") or None
                if p.vertices:
                    out.append(p)
                break
    return out


def tolerancia(v: VerticePlanilha) -> float:
    tipo = (v.tipo_limite or "").upper()
    if "-V-" in v.codigo:
        return G.TOLERANCIA_M["inacessivel"]
    if tipo.startswith("LN"):
        return G.TOLERANCIA_M["natural"]
    return G.TOLERANCIA_M["artificial"]


def validar(p: Perimetro, cod_imovel: str, regra_versao: str = "planilha-2026a") -> list[Achado]:
    mats = [(p.cns, p.matricula)] if p.cns and p.matricula else []
    reg = chave_registro(cod_imovel, mats)
    out = []

    def add(regra, fase, situacao, gravidade, msg, campo=None, valor=None):
        out.append(
            Achado(
                reg,
                cod_imovel,
                fase,
                f"planilha.{regra}",
                situacao,
                gravidade,
                msg,
                campo,
                valor,
                f"planilha ODS ({p.aba})",
                regra_versao=regra_versao,
            )
        )

    if p.faltam_colunas:
        add(
            "colunas",
            "formato",
            "conferir",
            "confirmar",
            f"colunas não achadas: {', '.join(p.faltam_colunas)}",
            "colunas",
            ",".join(p.faltam_colunas),
        )
    ruins = [v.codigo for v in p.vertices if not CODIGO_SIGEF.match(v.codigo)]
    add(
        "codigo_vertice",
        "formato",
        "conferir" if ruins else "ok",
        "confirmar" if ruins else "info",
        f"códigos fora do padrão do SIGEF: {', '.join(ruins[:5])}" if ruins else "códigos no padrão do SIGEF",
        "codigo",
        ",".join(ruins[:5]) or None,
    )
    sem = [v.codigo for v in p.vertices if v.lon is None or v.lat is None]
    add(
        "coordenada",
        "formato",
        "falta" if sem else "ok",
        "reprova" if sem else "info",
        f"vértices sem coordenada legível: {', '.join(sem[:5])}" if sem else "todas as coordenadas leem",
        "coordenada",
        ",".join(sem[:5]) or None,
    )
    vistos, rep = set(), []
    for v in p.vertices:
        if v.codigo in vistos:
            rep.append(v.codigo)
        vistos.add(v.codigo)
    if rep:
        add(
            "vertice_repetido",
            "formato",
            "falta",
            "reprova",
            f"vértices repetidos: {', '.join(rep[:5])}",
            "codigo",
            ",".join(rep[:5]),
        )
    fora = []
    for v in p.vertices:
        s = max(x for x in (v.sigma_lon, v.sigma_lat, 0.0) if x is not None)
        if s > tolerancia(v):
            fora.append(f"{v.codigo} ({s:.2f} m > {tolerancia(v):.2f} m)")
    add(
        "precisao",
        "geometria",
        "falta" if fora else "ok",
        "reprova" if fora else "info",
        f"precisão acima da tolerância do limite: {'; '.join(fora[:5])}"
        if fora
        else "precisão de todos os vértices dentro da tolerância do limite",
        "sigma",
        None,
    )
    poly = p.poligono
    if poly is not None:
        if not poly.is_valid:
            add("poligono", "geometria", "falta", "reprova", "o perímetro se cruza", "poligono", "invalido")
        else:
            a, per = G.area_perimetro(poly)
            add(
                "poligono",
                "geometria",
                "ok",
                "info",
                f"perímetro fechado: {a:,.4f} ha, {per:,.2f} m",
                "area_ha",
                f"{a:.4f}",
            )
    return out
