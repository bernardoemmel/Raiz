"""SIGEF por município (parcelas que tocam o retângulo do município no CAR), gravado no espelho por município.

Mesmo recorte que o motor usa (retângulo do CAR, eixo lat/lon com urn no WFS 2.0). A coleta incremental por
data_aprovacao e a anti-junção semanal das canceladas são o passo 6 da E1; aqui o município é baixado inteiro quando o
CAR dele mudou ou quando ainda não há espelho.
"""

from __future__ import annotations

import requests

from raiz.coleta import wfs
from raiz.coleta.espelho import Diferenca, Espelho
from raiz.coleta.manifesto import carregar

FONTE = "sigef_parcelas"


def camada() -> wfs.Camada:
    f = carregar().fonte(FONTE)
    return wfs.Camada(f.url, f.model_extra["camada"], f.model_extra.get("versao_wfs", "2.0.0"))


def coletar_municipio(s: requests.Session, espelho: Espelho, uf: str, cod: int) -> Diferenca | None:
    car = espelho.ler("car", uf, cod)
    if car is None or not len(car):
        return None
    x0, y0, x1, y1 = car.to_crs(4674).total_bounds
    bbox = f"{y0},{x0},{y1},{x1},urn:ogc:def:crs:EPSG::4674"
    pagina = carregar().fonte(FONTE).model_extra.get("pagina", 5000)
    g = wfs.ler(s, camada(), "parcela_codigo", None, pagina, bbox=bbox)
    return espelho.gravar("sigef", uf, cod, g, "parcela_codigo")
