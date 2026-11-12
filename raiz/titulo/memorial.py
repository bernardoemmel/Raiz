"""Memorial descritivo (E5 passos 1 e 2): gerar no padrão do SIGEF e ler de volta em duas camadas.

1. Regras em português (sem modelo): vértice (código do SIGEF ou "M-01", "P1"), coordenadas geográficas
   (graus, minutos e segundos) ou UTM (E, N, fuso ou meridiano central), azimute ou rumo e distância de cada lado,
   área e perímetro declarados.
2. Modelo da Anthropic (raiz/documentos/claude.py) só quando a NOTA DE CONFIANÇA da leitura fica abaixo do mínimo
   (não quando "a regex falhou": uma leitura pode achar tudo e mesmo assim não fechar). Abaixo do mínimo nas duas, a
   leitura vai para a fila de revisão (achado "confirmar").
Fechamento e contagem de vértices são sempre alarme. Nome de confrontante nunca é guardado: só números e códigos.

gerar() escreve o memorial de um polígono (para o conjunto de teste: o par polígono e texto, como o LFTools e o
GeoPlanta fazem; eles são GPL e não entram na Raíz, o gerador é próprio).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from shapely.geometry import Polygon

from raiz.titulo import geometria as G
from raiz.titulo.achados import Achado, chave_registro

CONFIANCA_MINIMA = 0.8
PRECISAO_MINIMA = 5000  # 1:5.000: abaixo disso o polígono não fecha

# --- gerar -------------------------------------------------------------------------------------------------------


def _num_br(x: float, casas: int = 2) -> str:
    return f"{x:,.{casas}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def gerar(vertices: list[tuple[str, float, float]], municipio: str = "", uf: str = "", estilo: str = "sigef") -> str:
    """Memorial de um polígono. vertices = [(código, lon, lat), ...] sem repetir o primeiro no fim.
    estilo: sigef (geográficas e azimute) ou rumo (estilo antigo: só o primeiro vértice com coordenadas, rumos)."""
    n = len(vertices)
    poly = Polygon([(lo, la) for _, lo, la in vertices])
    area, perim = G.area_perimetro(poly)
    partes = [f"Imóvel rural em {municipio}{' - ' + uf if uf else ''}." if municipio else "Imóvel rural."]
    for i, (cod, lo, la) in enumerate(vertices):
        prox_cod, plo, pla = vertices[(i + 1) % n]
        az, d = G.azimute_distancia(lo, la, plo, pla)
        if estilo == "rumo":
            coords = (
                f", de coordenadas Longitude {G.graus_para_dms(lo)} e Latitude {G.graus_para_dms(la)}" if i == 0 else ""
            )
            q = az % 360
            if q <= 90:
                rumo, ns, ew = q, "N", "E"
            elif q <= 180:
                rumo, ns, ew = 180 - q, "S", "E"
            elif q <= 270:
                rumo, ns, ew = q - 180, "S", "W"
            else:
                rumo, ns, ew = 360 - q, "N", "W"
            lado = f"rumo {G.graus_para_dms(rumo)} {ns}{ew} e distância de {_num_br(d)} metros"
        else:
            coords = (
                f", de coordenadas Longitude: {G.graus_para_dms(lo, 3)}, Latitude: {G.graus_para_dms(la, 3)} "
                "e Altitude: 0,00 m"
            )
            lado = f"com os seguintes azimute e distância: {G.graus_para_dms(az)} e {_num_br(d)} m"
        abertura = "Inicia-se a descrição deste perímetro no vértice" if i == 0 else "até o vértice"
        fim = ", ponto inicial da descrição deste perímetro." if i == n - 1 else ""
        partes.append(f"{abertura} {cod}{coords}; deste, segue confrontando com o imóvel vizinho, {lado}")
        if i == n - 1:
            partes.append(f"até o vértice {vertices[0][0]}{fim}")
    partes.append(
        "Todas as coordenadas aqui descritas estão georreferenciadas ao Sistema Geodésico Brasileiro e representadas "
        "no SIRGAS 2000. Azimutes e distâncias calculados no elipsoide."
    )
    partes.append(f"Área: {_num_br(area, 4)} ha. Perímetro: {_num_br(perim)} m.")
    return " ".join(partes)


# --- ler ---------------------------------------------------------------------------------------------------------

_VERTICE = re.compile(
    r"(?:v[ée]rtice|marco|ponto)\s+(?P<cod>[A-Z0-9]{2,6}-[A-Z]-\d{1,6}|[A-Z]{1,3}-?\d{1,4}[A-Z]?)", re.IGNORECASE
)
_ANG = r"-?\s*\d{1,3}\s*[°º]\s*\d{1,2}\s*['’′]\s*(?:\d{1,2}(?:[.,]\d+)?)?\s*(?:\"|”|″|'')?"
_DEC = r"-?\d{1,3}[.,]\d{4,}"
_LON = re.compile(rf"long(?:itude)?\.?\s*[:=]?\s*(?P<v>{_ANG}\s*[WOEL]?|{_DEC})", re.IGNORECASE)
_LAT = re.compile(rf"lat(?:itude)?\.?\s*[:=]?\s*(?P<v>{_ANG}\s*[NS]?|{_DEC})", re.IGNORECASE)
_NUM_GRANDE = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d{6,7}(?:[.,]\d+)?"
_N = re.compile(rf"(?<![A-Za-z])N\s*[:=]?\s*(?P<v>{_NUM_GRANDE})\s*m?")
_E = re.compile(rf"(?<![A-Za-z])E\s*[:=]?\s*(?P<v>{_NUM_GRANDE})\s*m?")
_AZ = re.compile(
    rf"azimute[s]?(?:\s+e\s+dist[âa]ncia[s]?)?(?:\s+[^\W\d]+){{0,2}}\s*[:=]?\s*(?:de\s*)?(?P<v>{_ANG})", re.I
)  # palavras puladas sem dígito: senão "de 90°" vira "0°"
_RUMO = re.compile(rf"rumo\s*(?:de\s*)?(?P<v>{_ANG})\s*(?P<ns>[NS])\s*(?P<ew>[EWLO])", re.IGNORECASE)
_DIST = re.compile(r"(?P<v>\d{1,3}(?:\.\d{3})+,\d+|\d+(?:[.,]\d+)?)\s*(?:m(?:etros)?)\b", re.IGNORECASE)
_AREA = re.compile(r"[áa]rea[^\d]{0,25}?(?P<v>\d{1,3}(?:\.\d{3})*,\d+|\d+(?:,\d+)?)\s*(?P<u>ha|hectares?|m²|m2)", re.I)
_PERIM = re.compile(r"per[íi]metro[^\d]{0,25}?(?P<v>\d{1,3}(?:\.\d{3})*,\d+|\d+(?:,\d+)?)\s*m\b", re.I)
_FUSO = re.compile(r"(?:fuso|zona)\s*(?P<f>\d{2})\s*(?P<h>sul|norte|S|N)?", re.IGNORECASE)
_MC = re.compile(r"(?:MC|meridiano\s+central)\s*[:=]?\s*(?P<s>[-−])?\s*(?P<g>\d{2})\s*[°º]?\s*(?P<h>W|O|Gr)?", re.I)


def _br(s: str) -> float:
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return float(s)


@dataclass
class Vertice:
    codigo: str
    lon: float | None = None
    lat: float | None = None


@dataclass
class Lado:
    de: str
    para: str
    azimute: float | None
    distancia_m: float | None


@dataclass
class LeituraMemorial:
    vertices: list[Vertice] = field(default_factory=list)
    lados: list[Lado] = field(default_factory=list)
    sistema: str | None = None  # geo | utm | so_primeiro
    area_declarada_ha: float | None = None
    perimetro_declarado_m: float | None = None
    fonte: str = "regras"  # regras | modelo
    problemas: list[str] = field(default_factory=list)
    fechamento: G.Fechamento | None = None
    poligono: Polygon | None = None
    area_ha: float | None = None
    confianca: float = 0.0

    @property
    def revisar(self) -> bool:
        return self.confianca < CONFIANCA_MINIMA

    def achados(self, cod_imovel: str, regra_versao: str = "memorial-2026a") -> list[Achado]:
        reg = chave_registro(cod_imovel)
        out = []

        def add(regra, situacao, gravidade, msg, campo=None, valor=None):
            out.append(
                Achado(
                    reg,
                    cod_imovel,
                    "geometria" if regra != "leitura" else "formato",
                    f"memorial.{regra}",
                    situacao,
                    gravidade,
                    msg,
                    campo,
                    valor,
                    f"memorial ({self.fonte})",
                    regra_versao=regra_versao,
                )
            )

        if self.revisar:
            add(
                "leitura",
                "conferir",
                "confirmar",
                f"leitura do memorial com confiança {self.confianca:.0%}: "
                "conferir à mão; " + "; ".join(self.problemas[:3]),
                "confianca",
                f"{self.confianca:.2f}",
            )
        else:
            add(
                "leitura",
                "ok",
                "info",
                f"memorial lido com confiança {self.confianca:.0%}",
                "confianca",
                f"{self.confianca:.2f}",
            )
        f = self.fechamento
        if f is not None:
            ok = f.precisao is None or f.precisao >= PRECISAO_MINIMA
            add(
                "fechamento",
                "ok" if ok else "falta",
                "info" if ok else "reprova",
                f"erro de fechamento de {f.erro_m:.2f} m em {f.perimetro_m:,.0f} m ({f.texto_precisao})",
                "precisao",
                f.texto_precisao,
            )
        if self.area_ha is not None and self.area_declarada_ha:
            dif = abs(self.area_ha - self.area_declarada_ha) / self.area_declarada_ha * 100
            add(
                "area_declarada",
                "ok" if dif <= 1 else "conferir",
                "info" if dif <= 1 else "confirmar",
                f"área calculada {self.area_ha:,.4f} ha contra {self.area_declarada_ha:,.4f} ha declarados "
                f"({dif:.2f}%)",
                "area_ha",
                f"{self.area_ha:.4f}",
            )
        return out


def _coord_geo(trecho: str) -> tuple[float | None, float | None]:
    lo, la = _LON.search(trecho), _LAT.search(trecho)
    if not (lo and la):
        return None, None

    def v(m, eixo):
        s = m.group("v")
        if "°" in s or "º" in s:
            g = G.dms_para_graus(s)
        else:
            g = _br(s)
        # no Brasil a longitude é oeste e quase toda latitude é sul: sem sinal nem hemisfério, assume
        if g is not None and g > 0 and not re.search(r"[NEL]\s*$", s.strip()):
            if eixo == "lon" or re.search(r"[S]\s*$", s.strip()) or g > 5.3:
                g = -g
        return g

    return v(lo, "lon"), v(la, "lat")


def _fuso(texto: str) -> tuple[int | None, bool]:
    m = _FUSO.search(texto)
    if m:
        return int(m.group("f")), not (m.group("h") or "S").upper().startswith("N")
    m = _MC.search(texto)
    if m:
        return G.fuso_do_meridiano(-float(m.group("g"))), True
    return None, True


def ler_regras(texto: str) -> LeituraMemorial:
    t = " ".join(str(texto).replace("’", "'").replace("”", '"').split())
    lt = LeituraMemorial()
    mencoes = list(_VERTICE.finditer(t))
    if len(mencoes) < 3:
        lt.problemas.append(f"só {len(mencoes)} vértices achados")
        return _avaliar(lt)
    codigos = [m.group("cod").upper() for m in mencoes]
    fecha = codigos[-1] == codigos[0]
    if fecha:
        mencoes, codigos = mencoes[:-1], codigos[:-1]
    else:
        lt.problemas.append("a descrição não volta ao vértice inicial")
    fuso, sul = _fuso(t)
    for i, m in enumerate(mencoes):
        fim = mencoes[i + 1].start() if i + 1 < len(mencoes) else len(t)
        janela = t[m.end() : fim]
        corte = re.search(r"\bsegue\b|\bdeste\b", janela, re.IGNORECASE)
        coord_txt = janela[: corte.start()] if corte else janela
        lado_txt = janela[corte.start() :] if corte else janela
        lo, la = _coord_geo(coord_txt)
        if lo is None:
            n, e = _N.search(coord_txt), _E.search(coord_txt)
            if n and e and fuso:
                lo, la = G.utm_para_geo(_br(e.group("v")), _br(n.group("v")), fuso, sul)
                lt.sistema = lt.sistema or "utm"
        elif lt.sistema is None:
            lt.sistema = "geo"
        lt.vertices.append(Vertice(codigos[i], lo, la))
        az = None
        ma = _AZ.search(lado_txt)
        mr = _RUMO.search(lado_txt)
        if ma:
            az = G.dms_para_graus(ma.group("v"))
            resto = lado_txt[ma.end() :]
        elif mr:
            az = G.rumo_para_azimute(abs(G.dms_para_graus(mr.group("v")) or 0), mr.group("ns"), mr.group("ew"))
            resto = lado_txt[mr.end() :]
        else:
            resto = lado_txt
        md = _DIST.search(resto)
        d = _br(md.group("v")) if md else None
        para = codigos[(i + 1) % len(codigos)]
        lt.lados.append(Lado(codigos[i], para, None if az is None else az % 360, d))
    ma = _AREA.search(t)
    if ma:
        v = _br(ma.group("v"))
        lt.area_declarada_ha = v / 1e4 if ma.group("u").lower() in ("m²", "m2") else v
    mp = _PERIM.search(t)
    if mp:
        lt.perimetro_declarado_m = _br(mp.group("v"))
    if sum(v.lon is not None for v in lt.vertices) == 1 and len(lt.vertices) > 1:
        lt.sistema = "so_primeiro"  # estilo antigo: coordenada só no vértice inicial, o resto pelos lados
    return _avaliar(lt)


def _avaliar(lt: LeituraMemorial) -> LeituraMemorial:
    """Monta o polígono, fecha os lados e dá a nota de confiança (0 a 1)."""
    nv = len(lt.vertices)
    pontos = []
    if nv >= 3:
        com = [v for v in lt.vertices if v.lon is not None]
        lados_ok = [x for x in lt.lados if x.azimute is not None and x.distancia_m is not None]
        if len(lados_ok) == nv and lt.vertices[0].lon is not None:
            lt.fechamento = G.fechar(
                lt.vertices[0].lon, lt.vertices[0].lat, [(x.azimute, x.distancia_m) for x in lt.lados]
            )
        if len(com) == nv:
            pontos = [(v.lon, v.lat) for v in lt.vertices]
        elif lt.fechamento is not None:  # estilo antigo: só o primeiro vértice tem coordenada
            pontos = lt.fechamento.ajustados
            lt.problemas.append("polígono montado pelos lados, a partir do primeiro vértice")
        if len(pontos) >= 3:
            p = Polygon(pontos)
            if not p.is_valid:
                lt.problemas.append("polígono se cruza")
            lt.poligono = p
            lt.area_ha = G.area_perimetro(p)[0]
        if len(com) < nv and lt.fechamento is None:
            lt.problemas.append(f"{nv - len(com)} de {nv} vértices sem coordenada")
        if len(lados_ok) < nv:
            lt.problemas.append(f"{nv - len(lados_ok)} de {nv} lados sem azimute ou distância")
    notas = []
    if nv >= 3:
        notas.append(sum(v.lon is not None for v in lt.vertices) / nv if lt.sistema != "so_primeiro" else 1.0)
        notas.append(sum(x.azimute is not None and x.distancia_m is not None for x in lt.lados) / nv)
        f = lt.fechamento
        notas.append(1.0 if f is not None and (f.precisao is None or f.precisao >= PRECISAO_MINIMA) else 0.0)
        if lt.area_ha is not None and lt.area_declarada_ha:
            dif = abs(lt.area_ha - lt.area_declarada_ha) / lt.area_declarada_ha
            notas.append(1.0 if dif <= 0.01 else (0.5 if dif <= 0.05 else 0.0))
        if lt.poligono is not None and not lt.poligono.is_valid:
            notas.append(0.0)
    lt.confianca = round(sum(notas) / len(notas), 3) if notas else 0.0
    if lt.fechamento is not None and lt.fechamento.precisao is not None and lt.fechamento.precisao < PRECISAO_MINIMA:
        lt.problemas.append(f"não fecha: {lt.fechamento.erro_m:.2f} m ({lt.fechamento.texto_precisao})")
    return lt


# --- modelo (segunda camada) -------------------------------------------------------------------------------------

ESQUEMA_MODELO = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vertices", "lados", "fuso", "hemisferio_sul", "area_ha", "perimetro_m"],
    "properties": {
        "vertices": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["codigo", "longitude", "latitude", "e", "n"],
                "properties": {
                    "codigo": {"type": "string"},
                    "longitude": {"type": ["number", "null"]},
                    "latitude": {"type": ["number", "null"]},
                    "e": {"type": ["number", "null"]},
                    "n": {"type": ["number", "null"]},
                },
            },
        },
        "lados": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["de", "para", "azimute_graus", "distancia_m"],
                "properties": {
                    "de": {"type": "string"},
                    "para": {"type": "string"},
                    "azimute_graus": {"type": ["number", "null"]},
                    "distancia_m": {"type": ["number", "null"]},
                },
            },
        },
        "fuso": {"type": ["integer", "null"]},
        "hemisferio_sul": {"type": ["boolean", "null"]},
        "area_ha": {"type": ["number", "null"]},
        "perimetro_m": {"type": ["number", "null"]},
    },
}
SISTEMA_MODELO = """Você lê memoriais descritivos de imóveis rurais brasileiros e devolve os números no JSON pedido.
- Vértices na ordem da descrição, sem repetir o inicial no fim. Coordenadas geográficas em graus decimais (oeste e
  sul negativos) em longitude e latitude; UTM em e e n (metros), com o fuso.
- Lados: de cada vértice para o seguinte, azimute em graus decimais a partir do norte (converta rumo para azimute) e
  distância em metros.
- Nunca escreva nome de confrontante, de dono ou de qualquer pessoa: só códigos e números.
- Se um número não está no texto, use null. Não invente."""


def ler_modelo(texto: str, leitor) -> LeituraMemorial:
    r = leitor.ler_texto(texto, SISTEMA_MODELO, "Leia este memorial e devolva o JSON do esquema.", ESQUEMA_MODELO)
    lt = LeituraMemorial(fonte="modelo")
    if not r.ok:
        lt.problemas.append(f"modelo não leu: {r.erro}")
        return lt
    d = r.dados
    fuso, sul = d.get("fuso"), d.get("hemisferio_sul") is not False
    for v in d.get("vertices") or []:
        lo, la = v.get("longitude"), v.get("latitude")
        if (lo is None or la is None) and v.get("e") and v.get("n") and fuso:
            lo, la = G.utm_para_geo(v["e"], v["n"], fuso, sul)
            lt.sistema = "utm"
        lt.vertices.append(Vertice(str(v.get("codigo") or "?"), lo, la))
    lt.sistema = lt.sistema or "geo"
    for x in d.get("lados") or []:
        az = x.get("azimute_graus")
        lt.lados.append(
            Lado(str(x.get("de")), str(x.get("para")), None if az is None else az % 360, x.get("distancia_m"))
        )
    lt.area_declarada_ha, lt.perimetro_declarado_m = d.get("area_ha"), d.get("perimetro_m")
    return _avaliar(lt)


def ler(texto: str, leitor=None, minimo: float = CONFIANCA_MINIMA) -> LeituraMemorial:
    """Regras primeiro; o modelo só quando a nota de confiança das regras fica abaixo do mínimo. Vale a leitura de
    nota maior; abaixo do mínimo, ela pede revisão (LeituraMemorial.revisar)."""
    lt = ler_regras(texto)
    if lt.confianca >= minimo or leitor is None:
        return lt
    lm = ler_modelo(texto, leitor)
    return lm if lm.confianca > lt.confianca else lt
