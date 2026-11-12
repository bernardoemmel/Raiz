"""Arquivo scd2 de retratos completos para os folds, separado da coleta em bruto.

Importa somente as colunas públicas do contrato; mantém versões fechadas e usa
o relógio do banco como conhecimento da Raíz. Não aceita retrodatação de arquivos
baixados hoje. Um conjunto incompleto ou inválido não publica nenhuma fonte.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
from sqlalchemy import Connection, text

from raiz.aprendizado.reexecucao import FONTES, Fonte, HistoricoInsuficiente
from raiz.privacidade import mascarar

ESQUEMA = "historico_modelos"
NUMEROS = {"m_fiscal", "year", "anodetec", "pasto_ha", "secundaria_ha", "pasto_ate1km_ha"}


def ler_pasta(pasta: Path) -> dict[str, pd.DataFrame]:
    """Um <fonte>.parquet por fonte; colunas extras nem chegam à memória."""
    out = {}
    for nome, esp in FONTES.items():
        arquivo = pasta / f"{nome}.parquet"
        if not arquivo.is_file():
            raise HistoricoInsuficiente(f"retrato incompleto: falta {nome}.parquet")
        campos = [*esp.campos, *(["geometry"] if esp.geometria else [])]
        out[nome] = (
            gpd.read_parquet(arquivo, columns=campos) if esp.geometria else pd.read_parquet(arquivo, columns=campos)
        )
    return out


def _normalizar(dados: dict[str, pd.DataFrame]) -> dict[str, list[dict]]:
    if set(dados) != set(FONTES):
        raise HistoricoInsuficiente("o arquivo exige todas as fontes do motor")
    normalizados = {}
    for nome, esp in FONTES.items():
        df = dados[nome]
        if not set(esp.campos) <= set(df.columns):
            raise HistoricoInsuficiente(f"{nome}: faltam colunas do contrato")
        if esp.geometria:
            if not isinstance(df, gpd.GeoDataFrame) or df.crs is None:
                raise HistoricoInsuficiente(f"{nome}: geometria sem sistema de coordenadas")
            df = df.to_crs(4674)
            if df.geometry.isna().any() or df.geometry.is_empty.any() or not df.geometry.is_valid.all():
                raise HistoricoInsuficiente(f"{nome}: geometria ausente ou inválida")
        chaves, linhas = set(), []
        for row in df.to_dict("records"):
            li = {}
            for c in esp.campos:
                v = row[c]
                if pd.isna(v):
                    li[c] = None
                elif c in NUMEROS:
                    li[c] = float(v)
                    if not math.isfinite(li[c]):
                        raise HistoricoInsuficiente(f"{nome}: número inválido em {c}")
                else:
                    li[c] = mascarar(str(v))
            if esp.geometria:
                li["geom"] = row["geometry"].normalize().wkt
            h = hashlib.sha256(json.dumps(li, sort_keys=True, allow_nan=False).encode()).hexdigest()
            chave = li[esp.chave] if esp.chave else h
            if chave is None or chave in chaves:
                raise HistoricoInsuficiente(f"{nome}: chave ausente ou repetida")
            chaves.add(chave)
            linhas.append({**li, "_chave": str(chave), "_linha_hash": h})
        normalizados[nome] = linhas
    if not normalizados["car"] or not normalizados["biomas"]:
        raise HistoricoInsuficiente("CAR e biomas precisam ter linhas no retrato")
    car = {
        r["cod_imovel"]: r["_hash"]
        for r in normalizados["car"]
        if r["status_imovel"] != "CA" and r["tipo_imovel"] == "IRU"
    }
    reg = {r["cod_imovel"]: r for r in normalizados["regeneracao"]}
    for cod, h in car.items():
        if not h or cod not in reg or reg[cod]["car_hash"] != h:
            raise HistoricoInsuficiente("o zonal precisa estar vinculado ao hash da mesma versão do CAR")
    for r in reg.values():
        for c in ("pasto_ha", "secundaria_ha", "pasto_ate1km_ha"):
            if r[c] is None or r[c] < 0:
                raise HistoricoInsuficiente("zonal incompleto ou com área negativa")
    return normalizados


def arquivar(con: Connection, dados: dict[str, pd.DataFrame], uf: str, cod_municipio: int) -> dict:
    """Publica o conjunto de fontes na transação do chamador, sem tocar o bruto.

    Fonte vazia fecha as linhas vigentes daquele município. Repetição com os
    mesmos valores registra a conferência, mas não duplica versões dos dados.
    """
    normalizados = _normalizar(dados)
    # Serializa duas capturas do mesmo município; a segunda terá instante depois
    # da primeira mesmo que as transações tenham começado em ordem diferente.
    con.execute(text("select pg_advisory_xact_lock(823008, 0)"))
    agora = con.execute(text("select clock_timestamp()")).scalar_one()
    con.execute(text(f"create schema if not exists {ESQUEMA}"))
    con.execute(
        text(f"""create table if not exists {ESQUEMA}.coleta (
        cod_municipio integer not null, uf text not null, observado_em timestamptz not null,
        manifesto_hash text not null, contagens jsonb not null,
        primary key (cod_municipio, observado_em))""")
    )
    hashes = {}
    for nome, esp in FONTES.items():
        tabela = f"{ESQUEMA}.{esp.tabela}"
        campos = [f"{c} {'double precision' if c in NUMEROS else 'text'}" for c in esp.campos]
        if esp.geometria:
            campos.append("geom geometry(Geometry,4674)")
        campos.extend(
            [
                "cod_municipio_ibge integer not null",
                "_chave text not null",
                "_linha_hash text not null",
                "_dlt_valid_from timestamptz not null",
                "_dlt_valid_to timestamptz",
                "primary key (cod_municipio_ibge, _chave, _dlt_valid_from)",
            ]
        )
        con.execute(text(f"create table if not exists {tabela} ({', '.join(campos)})"))
        con.execute(
            text(
                f"create unique index if not exists {esp.tabela}_atual on {tabela} "
                "(cod_municipio_ibge, _chave) where _dlt_valid_to is null"
            )
        )
        atuais = dict(
            con.execute(
                text(f"select _chave, _linha_hash from {tabela} where cod_municipio_ibge=:m and _dlt_valid_to is null"),
                {"m": cod_municipio},
            ).all()
        )
        novas = {r["_chave"]: r for r in normalizados[nome]}
        fecham = [k for k, h in atuais.items() if k not in novas or novas[k]["_linha_hash"] != h]
        if fecham:
            con.execute(
                text(
                    f"update {tabela} set _dlt_valid_to=:a where cod_municipio_ibge=:m "
                    "and _dlt_valid_to is null and _chave = any(:chaves)"
                ),
                {"a": agora, "m": cod_municipio, "chaves": fecham},
            )
        for k, li in novas.items():
            if atuais.get(k) == li["_linha_hash"]:
                continue
            li = {**li, "cod_municipio_ibge": cod_municipio, "_dlt_valid_from": agora}
            valores = [f"ST_GeomFromText(:{c},4674)" if c == "geom" else f":{c}" for c in li]
            con.execute(text(f"insert into {tabela} ({', '.join(li)}) values ({', '.join(valores)})"), li)
        hashes[nome] = sorted(r["_linha_hash"] for r in novas.values())
    manifesto = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    contagens = {n: len(rs) for n, rs in normalizados.items()}
    con.execute(
        text(f"insert into {ESQUEMA}.coleta values (:m, :uf, :a, :h, cast(:c as jsonb))"),
        {"m": cod_municipio, "uf": uf.upper(), "a": agora, "h": manifesto, "c": json.dumps(contagens)},
    )
    return {"observado_em": agora.isoformat(), "manifesto_hash": manifesto, "contagens": contagens}


def catalogo(con: Connection, cod_municipio: int) -> dict[str, Fonte]:
    """Cobertura comprovada pelo arquivo; uma captura incompleta nunca entra aqui."""
    r = con.execute(
        text(
            f"select min(observado_em) as desde, max(observado_em) as ate from {ESQUEMA}.coleta where cod_municipio=:m"
        ),
        {"m": cod_municipio},
    ).one()
    if r.desde is None:
        raise HistoricoInsuficiente("município sem captura histórica completa")
    ref = f"{ESQUEMA}.coleta:{cod_municipio}"
    return {n: Fonte(r.desde, r.ate, ref, esquema=ESQUEMA, por_municipio=True) for n in FONTES}


def salvar_catalogo(con: Connection, cod_municipio: int, caminho: Path) -> None:
    fontes = catalogo(con, cod_municipio)
    corpo = {
        n: {
            "desde": f.desde.isoformat(),
            "ate": f.ate.isoformat(),
            "referencia": f.referencia,
            "esquema": f.esquema,
            "por_municipio": f.por_municipio,
        }
        for n, f in fontes.items()
    }
    caminho.write_text(json.dumps({"fontes": corpo}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
