"""Arquivo scd2 de fontes históricas para os folds, separado da coleta em bruto.

Importa somente as colunas públicas do contrato e usa o relógio do banco como
conhecimento da Raíz. A importação manual exige o conjunto do motor; capturas
parciais automáticas só declaram cobertura das fontes efetivamente recebidas.
Fonte ausente não fecha versões; fonte presente e vazia registra uma retirada.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator
from pathlib import Path

import geopandas as gpd
import pandas as pd
from sqlalchemy import Connection, text

from raiz.aprendizado.reexecucao import FONTES, FONTES_MOTOR, Fonte, HistoricoInsuficiente
from raiz.privacidade import mascarar

ESQUEMA = "historico_modelos"
NUMEROS = {"m_fiscal", "year", "anodetec", "pasto_ha", "secundaria_ha", "pasto_ate1km_ha"}
TAMANHO_LOTE = 500


def ler_pasta(pasta: Path) -> dict[str, pd.DataFrame]:
    """Base do motor obrigatória; entradas extras são lidas somente se presentes."""
    out = {}
    for nome, esp in FONTES.items():
        arquivo = pasta / f"{nome}.parquet"
        if not arquivo.is_file():
            if nome in FONTES_MOTOR:
                raise HistoricoInsuficiente(f"retrato incompleto: falta {nome}.parquet")
            continue
        campos = [*esp.campos, *(["geometry"] if esp.geometria else [])]
        out[nome] = (
            gpd.read_parquet(arquivo, columns=campos) if esp.geometria else pd.read_parquet(arquivo, columns=campos)
        )
    return out


def _normalizar(dados: dict[str, pd.DataFrame], exigir_completo: bool = True) -> dict[str, list[dict]]:
    if not dados:
        raise HistoricoInsuficiente("a captura não tem nenhuma fonte")
    desconhecidas = set(dados) - set(FONTES)
    if desconhecidas:
        raise HistoricoInsuficiente(f"fontes desconhecidas: {', '.join(sorted(desconhecidas))}")
    if exigir_completo and set(FONTES_MOTOR) - set(dados):
        raise HistoricoInsuficiente("o arquivo exige todas as fontes do motor")
    normalizados = {}
    for nome, df in dados.items():
        esp = FONTES[nome]
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
            if nome.startswith("entrada_"):
                from raiz.aprendizado.captura import sanitizar_entrada

                if not isinstance(row.get("atributos"), dict) or not isinstance(row.get("contexto"), dict):
                    raise HistoricoInsuficiente(f"{nome}: atributos e contexto precisam ser objetos JSON")
                atributos, contexto = sanitizar_entrada(nome, row["atributos"], row["contexto"])
                row = {**row, "atributos": atributos, "contexto": contexto}
            li = {}
            for c in esp.campos:
                v = row[c]
                if c in esp.campos_json:
                    if not isinstance(v, dict):
                        raise HistoricoInsuficiente(f"{nome}: {c} precisa ser um objeto JSON")
                    li[c] = v
                elif pd.isna(v):
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
    if exigir_completo and any(not normalizados[n] for n in ("car", "biomas")):
        raise HistoricoInsuficiente("CAR e biomas precisam ter linhas no retrato completo")
    if "regeneracao" in normalizados:
        if "car" not in normalizados:
            raise HistoricoInsuficiente("o zonal exige o CAR da mesma captura")
        car = {
            r["cod_imovel"]: r["_hash"]
            for r in normalizados["car"]
            if r["status_imovel"] != "CA" and r["tipo_imovel"] == "IRU"
        }
        # O motor mede somente as frentes que pedem regeneração. A falta dos
        # demais imóveis não inventa zonais; os presentes precisam corresponder.
        for r in normalizados["regeneracao"]:
            h = car.get(r["cod_imovel"])
            if not h or r["car_hash"] != h:
                raise HistoricoInsuficiente("o zonal precisa estar vinculado ao hash da mesma versão do CAR")
            for c in ("pasto_ha", "secundaria_ha", "pasto_ate1km_ha"):
                if r[c] is None or r[c] < 0:
                    raise HistoricoInsuficiente("zonal incompleto ou com área negativa")
    return normalizados


def _lotes(linhas: list) -> Iterator[list]:
    for i in range(0, len(linhas), TAMANHO_LOTE):
        yield linhas[i : i + TAMANHO_LOTE]


def arquivar(
    con: Connection,
    dados: dict[str, pd.DataFrame],
    uf: str,
    cod_municipio: int,
    exigir_completo: bool = True,
) -> dict:
    """Publica fontes válidas na transação do chamador, sem tocar o bruto.

    Fonte ausente não recebe cobertura nem altera suas versões vigentes. A fonte
    presente vazia fecha as versões do município. Repetições registram nova
    conferência, mas não duplicam dados. Inserções são agrupadas em lotes de 500.
    """
    normalizados = _normalizar(dados, exigir_completo=exigir_completo)
    # Uma trava também protege a criação inicial das tabelas entre municípios.
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
    for nome, linhas in normalizados.items():
        esp = FONTES[nome]
        tabela = f"{ESQUEMA}.{esp.tabela}"
        tipos = {
            c: "jsonb" if c in esp.campos_json else "double precision" if c in NUMEROS else "text" for c in esp.campos
        }
        campos = [f"{c} {tipos[c]}" for c in esp.campos]
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
        novas = {r["_chave"]: r for r in linhas}
        fecham = [k for k, h in atuais.items() if k not in novas or novas[k]["_linha_hash"] != h]
        for chaves in _lotes(fecham):
            con.execute(
                text(
                    f"update {tabela} set _dlt_valid_to=:a where cod_municipio_ibge=:m "
                    "and _dlt_valid_to is null and _chave = any(:chaves)"
                ),
                {"a": agora, "m": cod_municipio, "chaves": chaves},
            )
        insercoes = []
        for k, li in novas.items():
            if atuais.get(k) == li["_linha_hash"]:
                continue
            params = {**li, "cod_municipio_ibge": cod_municipio, "_dlt_valid_from": agora}
            for campo in esp.campos_json:
                params[campo] = json.dumps(params[campo], sort_keys=True, allow_nan=False)
            insercoes.append(params)
        if insercoes:
            colunas = list(insercoes[0])
            valores = [
                f"ST_GeomFromText(:{c},4674)"
                if c == "geom"
                else f"cast(:{c} as jsonb)"
                if c in esp.campos_json
                else f":{c}"
                for c in colunas
            ]
            inserir = text(f"insert into {tabela} ({', '.join(colunas)}) values ({', '.join(valores)})")
            for lote in _lotes(insercoes):
                con.execute(inserir, lote)
        hashes[nome] = sorted(r["_linha_hash"] for r in novas.values())
    manifesto = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    contagens = {n: len(rs) for n, rs in normalizados.items()}
    con.execute(
        text(f"insert into {ESQUEMA}.coleta values (:m, :uf, :a, :h, cast(:c as jsonb))"),
        {"m": cod_municipio, "uf": uf.upper(), "a": agora, "h": manifesto, "c": json.dumps(contagens)},
    )
    return {
        "observado_em": agora.isoformat(),
        "manifesto_hash": manifesto,
        "contagens": contagens,
        "faltantes": sorted(set(FONTES) - set(normalizados)),
        "motor_completo": not (set(FONTES_MOTOR) - set(normalizados)),
    }


def catalogo(con: Connection, cod_municipio: int) -> dict[str, Fonte]:
    """Cada fonte tem somente a cobertura das capturas que efetivamente a contêm."""
    existe = con.execute(text("select to_regclass(:t)"), {"t": f"{ESQUEMA}.coleta"}).scalar()
    if existe is None:
        raise HistoricoInsuficiente("ainda não há capturas históricas no executor com banco")
    rs = con.execute(
        text(f"""select fonte.nome, min(c.observado_em) as desde, max(c.observado_em) as ate
                 from {ESQUEMA}.coleta c
                 cross join lateral jsonb_object_keys(c.contagens) as fonte(nome)
                 where c.cod_municipio = :m
                 group by fonte.nome order by fonte.nome"""),
        {"m": cod_municipio},
    ).all()
    if not rs:
        raise HistoricoInsuficiente("município sem captura histórica")
    ref = f"{ESQUEMA}.coleta:{cod_municipio}"
    return {
        r.nome: Fonte(r.desde, r.ate, f"{ref}:{r.nome}", esquema=ESQUEMA, por_municipio=True)
        for r in rs
        if r.nome in FONTES
    }


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
