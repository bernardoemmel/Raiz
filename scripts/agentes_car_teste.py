"""Entrada exclusiva da pilha descartável: CAR sintético para as 60 ofertas do gabarito."""

import datetime as dt
import json

import geopandas as gpd
from sqlalchemy import text
from sqlalchemy.engine import make_url


def validar_url(url) -> None:
    destino = make_url(url)
    if destino.host not in {"localhost", "127.0.0.1", "banco"} or destino.database != "raiz_agentes_teste":
        raise ValueError("CAR sintético só existe na base descartável raiz_agentes_teste")


def conferir_amostra(engine, selecionadas) -> None:
    """Simula a fonte externa da fixture; compara e grava a prova usada pelo serviço real."""
    from raiz.coleta.car_conferencia import comparar
    from scripts.cenarios_agentes import _ofertas

    banco = getattr(engine, "conexao", engine)
    validar_url(banco.engine.url)
    codigos = set(selecionadas.cod_imovel)
    if not codigos <= {o["cod_imovel"] for o in _ofertas()}:
        raise ValueError("A conferência sintética não aceita CAR fora do gabarito")
    base = gpd.read_postgis(
        text("select cod_imovel, geom from funil.imovel where cod_imovel=any(:codigos)"),
        banco,
        params={"codigos": sorted(codigos)},
        crs=4674,
    ).rename_geometry("geometry")
    if set(base.cod_imovel) != codigos:
        raise ValueError("CAR sintético ausente no banco descartável")
    base["status_imovel"], base["tipo_imovel"], base["m_fiscal"] = "AT", "IRU", 1
    _, marcas, mudou = comparar(base, base.copy(), codigos, dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
    if mudou or any(m["car_situacao"] != "conferido" for m in marcas.values()):
        raise ValueError("Geometria sintética não conferida")
    with engine.begin() as con:
        for cod, marca in marcas.items():
            con.execute(
                text("""update negocio.oferta set atributos=atributos || cast(:marca as jsonb)
                        where cod_imovel=:cod"""),
                {"cod": cod, "marca": json.dumps(marca)},
            )


if __name__ == "__main__":
    from raiz.cli import app
    from raiz.coleta import car_conferencia
    from raiz.config import config

    validar_url(config().banco_url)
    car_conferencia.conferir_banco = conferir_amostra
    app()
