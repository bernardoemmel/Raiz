"""Mapa privado da ficha: só geometrias da terra e proveniência, nunca atributos do dono."""

from __future__ import annotations

import json

import shapely
from shapely.geometry import box, mapping, shape
from sqlalchemy import text

from raiz.busca import normalizar_codigo

CAMADAS = {"mata_em_pe", "pode_voltar", "pasto", "lavoura", "agua", "app"}


def _colecao(features=None):
    return {"type": "FeatureCollection", "features": features or []}


def _poligonos(geom):
    g = shapely.make_valid(shape(geom))
    if g.geom_type in {"Polygon", "MultiPolygon"}:
        return g
    return shapely.union_all([p for p in shapely.get_parts(g) if p.geom_type in {"Polygon", "MultiPolygon"}])


def montar(geometria, camadas, data_corte=None):
    """Recorta as camadas medidas ao CAR. Não transforma hectares ou percentuais em desenho."""
    resultado = {
        "imovel": _colecao(),
        "mascara": _colecao(),
        "camadas": _colecao(),
        "fonte_perimetro": "SICAR, limite declarado do CAR",
        "fonte_camadas": "MapBiomas, cobertura da terra; INPE/PRODES, hidrografia; recortes e regra do motor Raíz",
        "data_referencia": None,
        "data_corte": data_corte,
        "avisos": [],
    }
    if not geometria:
        resultado["avisos"].append("O limite deste imóvel ainda não está disponível.")
        return resultado
    g = _poligonos(geometria)
    if g.is_empty:
        resultado["avisos"].append("O limite deste imóvel precisa ser conferido.")
        return resultado
    resultado["imovel"] = _colecao([{"type": "Feature", "properties": {}, "geometry": mapping(g)}])
    resultado["mascara"] = _colecao(
        [{"type": "Feature", "properties": {}, "geometry": mapping(box(-180, -85, 180, 85).difference(g))}]
    )
    for camada in camadas:
        nome = camada.get("camada")
        if nome not in CAMADAS or not camada.get("geometria"):
            continue
        recorte = _poligonos(mapping(_poligonos(camada["geometria"]).intersection(g)))
        if not recorte.is_empty:
            resultado["camadas"]["features"].append(
                {"type": "Feature", "properties": {"camada": nome}, "geometry": mapping(recorte)}
            )
    if not any(f["properties"]["camada"] == "pode_voltar" for f in resultado["camadas"]["features"]):
        resultado["avisos"].append(
            "O desenho da área que pode voltar a ser mata ainda não está disponível. "
            "A área em hectares não permite localizar a restauração dentro da fazenda."
        )
    return resultado


def consultar(engine, car):
    with engine.connect() as con:
        linha = (
            con.execute(
                text("""select ST_AsGeoJSON(ST_Transform(i.geom, 4326)) as geometria, r.data_corte
                    from funil.vigente v join funil.imovel i on i.cod_imovel = v.cod_imovel
                    join funil.rodada r on r.id = v.rodada_id where v.cod_busca = :b"""),
                {"b": normalizar_codigo(car)},
            )
            .mappings()
            .first()
        )
        camadas = (
            con.execute(
                text("""select c.camada, ST_AsGeoJSON(ST_Transform(c.geom, 4326)) as geometria
                    from funil.vigente v join geo.camada_imovel c on c.cod_imovel = v.cod_imovel
                    where v.cod_busca = :b"""),
                {"b": normalizar_codigo(car)},
            )
            .mappings()
            .all()
        )
    return montar(
        json.loads(linha["geometria"]) if linha and linha["geometria"] else None,
        [{"camada": c["camada"], "geometria": json.loads(c["geometria"])} for c in camadas],
        linha["data_corte"].isoformat() if linha and linha["data_corte"] else None,
    )


def satelite_disponivel(engine, car):
    """Reutiliza Sentinel-2 do motor; ausência esperada é um estado da ficha, não um 404 no mapa."""
    from fastapi import HTTPException

    from raiz import front_api

    try:
        meta, _ = front_api._imagem(engine, car, "hoje")
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return {"disponivel": False, "aviso": "Ainda não há uma cena Sentinel-2 adequada para este imóvel."}
    # Não devolver metadados arbitrários nem caminhos locais do armazenamento.
    return {
        "disponivel": True,
        "caixa": meta["caixa"],
        "data_cena": meta["data_cena"],
        "satelite": meta["satelite"],
        "credito": meta["credito"],
        "largura": meta["largura"],
        "altura": meta["altura"],
    }
