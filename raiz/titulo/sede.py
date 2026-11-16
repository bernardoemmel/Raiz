"""Localização da sede (E5 passo 6): o dono manda a localização pelo WhatsApp e a Raíz testa se o ponto cai dentro do
polígono do CAR. É uma prova de posse que não depende de documento: quem está na sede, está na terra.

- O robô de aceite pede a localização logo depois do aceite (tipo "pedido_sede", com o botão "Enviar localização"
  do WhatsApp); `raiz titulo pedir-sede` pede de novo para um imóvel.
- Só o resultado fica guardado (dentro, na divisa ou fora, e a distância até a borda em metros, arredondada), como
  achado de título da fase geometria (regra "sede.dentro_do_imovel"). O ponto não é gravado nem vai para o log: a
  localização da casa de alguém é dado pessoal.
- O pedido ao dono sai como mensagem para aprovação (pessoal.mensagem_saida), como toda mensagem da Raíz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Point

from raiz.titulo.achados import Achado, chave_registro

VERSAO = "sede-2026a"
TOLERANCIA_M = 50.0  # GPS de celular e polígono declarado: até 50 m fora ainda conta como "na divisa"
ORDEM = {"dentro": 0, "divisa": 1, "fora": 2, "sem_poligono": 3}


@dataclass
class ResultadoSede:
    cod_imovel: str
    dentro: bool
    distancia_borda_m: float  # positiva fora do polígono, zero dentro
    situacao: str  # dentro | divisa | fora | sem_poligono

    def achado(self) -> Achado:
        ok = self.situacao in ("dentro", "divisa")
        d = 0 if math.isnan(self.distancia_borda_m) else self.distancia_borda_m
        texto = {
            "dentro": "a localização da sede, mandada pelo dono, cai dentro do polígono do CAR",
            "divisa": f"a localização da sede cai a {d:.0f} m do polígono do CAR (na divisa)",
            "fora": f"a localização da sede cai a {d:,.0f} m do polígono do CAR".replace(",", "."),
            "sem_poligono": "sem o polígono do CAR para conferir a localização da sede",
        }[self.situacao]
        return Achado(
            chave_registro(self.cod_imovel), self.cod_imovel, "geometria", "sede.dentro_do_imovel",
            "ok" if ok else "conferir", "info" if ok else "confirmar", texto, "sede", self.situacao,
            "localização mandada pelo dono (WhatsApp)", regra_versao=VERSAO,
        )  # fmt: skip


def conferir_ponto(cod_imovel: str, poligono, lon: float, lat: float) -> ResultadoSede:
    """poligono em graus (SIRGAS 2000). A distância é medida num plano local (equidistante no ponto), em metros."""
    if poligono is None or poligono.is_empty:
        return ResultadoSede(cod_imovel, False, float("nan"), "sem_poligono")
    p = Point(lon, lat)
    if poligono.covers(p):
        return ResultadoSede(cod_imovel, True, 0.0, "dentro")
    from pyproj import CRS, Transformer
    from shapely.ops import transform

    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +ellps=GRS80 +units=m +no_defs")
    ida = Transformer.from_crs(4674, crs, always_xy=True)
    d = transform(ida.transform, poligono).distance(Point(0, 0))
    return ResultadoSede(cod_imovel, False, round(d, 0), "divisa" if d <= TOLERANCIA_M else "fora")


def poligono_do_banco(con, cod_imovel: str):
    from shapely import wkb
    from sqlalchemy import text

    r = con.execute(
        text("select ST_AsBinary(geom) from funil.imovel where cod_imovel = :c and geom is not null"), {"c": cod_imovel}
    ).scalar()
    return wkb.loads(bytes(r)) if r is not None else None


def registrar(con, cod_imovel: str, lon: float, lat: float) -> ResultadoSede:
    """Confere o ponto contra o polígono do banco e grava só o achado (sem o ponto)."""
    return registrar_varios(con, [cod_imovel], lon, lat)


def registrar_varios(con, cods: list[str], lon: float, lat: float) -> ResultadoSede:
    """Dono com mais de um imóvel: vale o que contém o ponto (ou o mais perto, na divisa). Se nenhum contém, o
    resultado fica no primeiro da lista (o do pedido mais recente). Grava um achado só."""
    from raiz.titulo.conferir import gravar_achados

    rs = [conferir_ponto(c, poligono_do_banco(con, c), lon, lat) for c in cods]
    bons = sorted(
        (r for r in rs if r.situacao in ("dentro", "divisa")), key=lambda r: (ORDEM[r.situacao], r.distancia_borda_m)
    )
    r = bons[0] if bons else rs[0]
    gravar_achados(con, [r.achado()])
    return r


def pedir(con, cod_imovel: str) -> int | None:
    """Põe o pedido de localização na fila de aprovação, para o contato da conversa de aceite do imóvel."""
    from psycopg.types.json import Jsonb
    from sqlalchemy import text

    from raiz.agentes import textos
    from raiz.legibilidade import medir

    c = con.execute(
        text("select contato_id from negocio.aceite where cod_imovel = :c and contato_id is not null"),
        {"c": cod_imovel},
    ).first()
    if c is None:
        return None
    x = textos.pedido_sede()
    return con.execute(
        text("""insert into pessoal.mensagem_saida (contato_id, cod_imovel, tipo, texto, legibilidade)
                values (:c, :i, 'pedido_sede', :x, :l) returning id"""),
        dict(c=c.contato_id, i=cod_imovel, x=x, l=Jsonb(medir(x))),
    ).scalar_one()


def ultima(con, cod_imovel: str) -> dict | None:
    """O último resultado da sede do imóvel (do banco), para o laudo."""
    from sqlalchemy import text

    r = con.execute(
        text("""select valor, mensagem, criado_em from titulo.achado
                where cod_imovel = :c and regra = 'sede.dentro_do_imovel' order by id desc limit 1"""),
        {"c": cod_imovel},
    ).first()
    return dict(r._mapping) if r else None
