"""Apoio dos testes da vigilância: tudo sem rede. Polígonos falsos no lugar do Release dados, projeto de teste em KML
gravado na hora e um Release do GitHub falso em memória."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

RAIZ_REPO = Path(__file__).resolve().parents[3]
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

from raiz.vigilancia import fontes, kml  # noqa: E402
from raiz.vigilancia.config import Config  # noqa: E402
from raiz.vigilancia.regras import carregar  # noqa: E402

HOJE = dt.date(2026, 11, 12)


# documentos de teste gerados por cálculo: nenhum CPF ou CNPJ válido fica escrito no repositório (a varredura do CI
# do back-end acusaria), como em testes/test_privacidade.py do back-end
def gerar_cpf(base9: str) -> str:
    d = [int(x) for x in base9]
    for n in (9, 10):
        d.append(sum(d[i] * (n + 1 - i) for i in range(n)) * 10 % 11 % 10)
    return "".join(map(str, d))


def gerar_cnpj(base12: str) -> str:
    s = base12
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        r = sum((ord(c) - 48) * p for c, p in zip(s, pesos, strict=True)) % 11
        s += str(0 if r < 2 else 11 - r)
    return s


def fmt_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def fmt_cnpj(s: str) -> str:
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


CPF = gerar_cpf("529982247")
CNPJ = gerar_cnpj("112223330001")
CNPJ_ALFA = gerar_cnpj("12ABC34501DE")
CPF_MASCARADO = f"***.{CPF[3:6]}.{CPF[6:9]}-**"
UF, MUN = "PA", 1507300
# origem em metros (EPSG:5880) perto de São Félix do Xingu
_O = gpd.GeoSeries([Point(-53.0, -6.0)], crs=4674).to_crs(5880).iloc[0]
OX, OY = _O.x, _O.y
COD_A = "PA-1507300-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # 100 ha
COD_B = "PA-1507300-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"  # 0,5 ha (pequena: nunca sai por tamanho)


def quadrado_m(x0: float, y0: float, lado: float):
    """Quadrado em metros (EPSG:5880) a partir do canto (relativo à origem)."""
    return box(OX + x0, OY + y0, OX + x0 + lado, OY + y0 + lado)


def em_graus(g):
    return gpd.GeoSeries([g], crs=5880).to_crs(4674).iloc[0]


class PoligonosFalsos:
    """Mesma interface de poligonos.Poligonos, com dois imóveis: A (1.000 m x 1.000 m = 100 ha) e B (≈0,5 ha)."""

    def __init__(self):
        self.g = gpd.GeoDataFrame(
            {
                "cod_imovel": [COD_A, COD_B],
                "uf": [UF, UF],
                "municipio": ["São Félix do Xingu", "São Félix do Xingu"],
                "cod_municipio_ibge": [MUN, MUN],
                "ha": [100.0, 0.5],
            },
            geometry=[quadrado_m(0, 0, 1000), quadrado_m(1100, 0, 70.71)],
            crs=5880,
        )
        self.g["alvo_ha"] = self.g.area / 1e4

    def ufs(self):
        return [UF]

    def versoes(self):
        return {UF: "teste+1"}

    def indice(self, uf):
        return {MUN: list(self.g.to_crs(4674).total_bounds)}

    def imoveis(self, uf, cod):
        return self.g.copy()

    def info_imovel(self, cod):
        r = self.g[self.g.cod_imovel == cod]
        if not len(r):
            return None
        d = r.drop(columns=["geometry"]).iloc[0].to_dict()
        return d

    def geometria_imoveis(self, cods):
        return self.g[self.g.cod_imovel.isin(cods)][["cod_imovel", "geometry"]]


@pytest.fixture
def regras():
    return carregar()


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config(estado=tmp_path / "estado", cache=tmp_path / "cache", repo="teste/raiz", tag_vigilancia="vigilancia")
    c.chave = None
    c.token_github = None
    return c


@pytest.fixture
def poligonos():
    return PoligonosFalsos()


@pytest.fixture
def projeto_kml(tmp_path) -> Path:
    """Projeto de teste sobre o imóvel A: Plantio (área de carbono), Aceiro (entorno) e Excluída (fora)."""
    pms = [
        {"nome": "Plantio", "geometria": em_graus(quadrado_m(0, 0, 600)), "campos": {"classe": "Plantio"}},
        {"nome": "Aceiro", "geometria": em_graus(quadrado_m(600, 0, 100)), "campos": {"classe": "Aceiro"}},
        {"nome": "Excluída", "geometria": em_graus(quadrado_m(700, 0, 300)), "campos": {"classe": "Excluída"}},
    ]
    p = tmp_path / "projeto_teste.kml"
    p.write_text(kml.escrever("teste", pms), encoding="utf-8")
    return p


@pytest.fixture
def lista_projetos(projeto_kml):
    from raiz.vigilancia.projetos import Projeto

    return [
        Projeto(
            "PTESTE",
            {
                "id": "PTESTE",
                "nome_projeto": "Projeto Teste",
                "padrao": "VCS",
                "verra_id": "9999",
                "inicio": "2020-01-01",
                "poligono": {"caminho": str(projeto_kml), "campo_classe": "classe"},
                "classes_projeto": ["Plantio"],
                "classes_entorno": ["Aceiro"],
                "vcus_emitidos": True,
                "cliente": "C-0001",
                "verificado_tco2e": 1000,
                "estoque_tco2e_ha": {"Plantio": 100},
            },
            privado=True,
        )
    ]


def ocorrencia(fonte: str, chave: str, classe: str, geo_m, data_evento: dt.date, publicado_em=None, **extra) -> dict:
    """Uma ocorrência no formato das fontes, com a geometria dada em metros."""
    g = em_graus(geo_m)
    d = {
        "fonte": fonte,
        "chave": chave,
        "classe": classe,
        "data_evento": data_evento,
        "publicado_em": publicado_em,
        "area_ha": float(geo_m.area) / 1e4,
        "uf": UF,
        "cod_municipio_ibge": MUN,
        "link": None,
        "atributos": {},
        "car_fonte": None,
        "geometry": g,
    }
    d.update(extra)
    return d


def ocorrencias(*linhas) -> gpd.GeoDataFrame:
    return fontes.montar(list(linhas))


class ReleaseFalso:
    """Release do GitHub em memória: guarda nome -> bytes e registra a ordem das subidas."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.repo = cfg.repo
        self.tag = cfg.tag_vigilancia
        self.arquivos: dict[str, bytes] = {}
        self.ordem: list[str] = []
        self._ids: dict[str, int] = {}

    def id(self, criar: bool = False):
        return 1 if (self.arquivos or criar) else None

    def ativos(self):
        return {n: {"id": self._ids.setdefault(n, len(self._ids) + 1), "name": n} for n in self.arquivos}

    def baixar(self, ativo):
        return self.arquivos[ativo["name"]]

    def subir(self, nome, dado, tipo="application/octet-stream"):
        self.arquivos[nome] = bytes(dado)
        self.ordem.append(nome)

    def apagar(self, ativo):
        self.arquivos.pop(ativo["name"], None)
