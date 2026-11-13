"""Índice privado e incremental do lote: preserva as previsões, sem recalcular municípios.

Cada partição representa as entradas efetivas de um município. Ausência, versão
incompatível e área zero permanecem no índice e na trilha revisável. O catálogo
é imutável; não depende dos nomes canônicos mutáveis do armazém para uma consulta.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from raiz.contrato import COMPLEMENTOS
from raiz.pedidos import oferta as O
from raiz.privacidade import remover_colunas_pessoais
from raiz.regras import salvaguardas_lote as S

ESQUEMA = "oferta-nacional-1"
TOLERANCIA_AREA_HA = 0.000050001  # previsão original arredondada a quatro casas; não muda o valor
PRECOS = tuple(f"preco_minimo_tir_{a}_{t}_usd_t" for a in (12, 15) for t in ("projeto", "alavancada"))
TEXTOS = (
    "cod_imovel",
    "uf",
    "municipio",
    "bioma",
    "modo",
    "caminho",
    "caminho_terra",
    "risco_terra",
    "restauracao_versao",
    "restauracao_cenario",
    "entradas_versao",
    "situacao_previsao",
    "pendencias",
    "consulta_livre_previa_informada",
    "nivel_interesse",
)
REAIS = (
    "lon",
    "lat",
    "ha",
    "area_ha",
    "m_fiscal",
    "credito_p10",
    "credito_p50",
    "credito_p90",
    "credito_ano",
    "flag_t_ano",
    "custo_credito_usd",
    "preco_equilibrio_usd",
    "tir_p10",
    "tir_p50",
    "tir_p90",
    "tir_projeto",
    "marcos_todos",
    "reserva_risco_pct",
    "regeneracao_ha",
    "semeadura_ha",
    "plantio_ha",
    "fracao_creditos_comunidade_minima",
    *PRECOS,
)
BOOLEANOS = (
    "pequena",
    "local_aproximado",
    "elegivel",
    "problema",
    "embargo",
    "terra_indigena",
    "uc_protecao_integral",
    "projeto_carbono",
    "bloqueio",
    "salvaguardas_planejamento",
    "salvaguardas_comercializavel",
)
SCHEMA = pa.schema(
    [(c, pa.string()) for c in TEXTOS]
    + [("cod_ibge", pa.int64())]
    + [(c, pa.float64()) for c in REAIS]
    + [(c, pa.bool_()) for c in BOOLEANOS]
    + [("metodos", pa.list_(pa.string()))],
    metadata={b"acesso": b"privado", b"esquema": ESQUEMA.encode()},
)


def sha256(arquivo: str | Path) -> str:
    with Path(arquivo).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _json(valor) -> bytes:
    return (json.dumps(valor, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()


def _diretorio(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    pasta.chmod(0o700)


def gravar_json(arquivo: Path, valor) -> None:
    """Publicação local atômica, privada; não expõe arquivos intermediários."""
    _diretorio(arquivo.parent)
    with tempfile.NamedTemporaryFile(dir=arquivo.parent, delete=False) as f:
        temporario = Path(f.name)
        f.write(_json(valor))
    os.replace(temporario, arquivo)


def versao_indice() -> str:
    h = hashlib.sha256(Path(__file__).read_bytes() + Path(O.__file__).read_bytes())
    h.update(S.regra()["versao_completa"].encode())
    return f"{ESQUEMA}+{h.hexdigest()[:12]}"


def _fontes(pasta: Path, cod: int) -> list[Path]:
    nomes = dict.fromkeys(("imoveis", "filtros", *COMPLEMENTOS, "jurisdicional"))
    arquivos = [pasta / f"{nome}_{cod}.csv" for nome in nomes]
    arquivos.append(pasta / f"geo_{cod}.parquet")
    return [p for p in arquivos if p.exists()]


def _ler_linhas(pasta: Path, cod: int) -> pd.DataFrame:
    def ler(arquivo):
        t, _ = remover_colunas_pessoais(pd.read_csv(arquivo, dtype={"cod_imovel": str}, low_memory=False))
        if (
            "cod_imovel" not in t
            or t.cod_imovel.isna().any()
            or not t.cod_imovel.is_unique
            or t.cod_imovel.str.strip().eq("").any()
        ):
            raise ValueError(f"Identificador ausente/duplicado no arquivo {arquivo.name}; conciliar antes de indexar.")
        return t

    t = ler(pasta / f"imoveis_{cod}.csv")
    for arquivo in _fontes(pasta, cod):
        if arquivo.suffix != ".csv" or arquivo.name.startswith("imoveis_"):
            continue
        extra = ler(arquivo)
        if arquivo.name.startswith("desenvolvedor_") and not extra.cod_imovel.isin(t.cod_imovel).all():
            raise ValueError("Previsão contém imóvel ausente da fonte municipal; conciliar a origem.")
        novas = [c for c in extra if c == "cod_imovel" or c not in t]
        t = t.merge(extra[novas], on="cod_imovel", how="left", validate="one_to_one")
    return t.replace({np.nan: None})


def _numero(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _registro(li, uf, cod, pontos, modelo, cenario):
    car = str(li["cod_imovel"])
    origem = str(li.get("restauracao_versao") or "")
    cen = str(li.get("restauracao_cenario") or "")
    o = O.de_linha(li, *pontos.get(car, (None, None)))
    disponivel = o is not None and bool(origem) and bool(cen)
    situacao = (
        "compativel"
        if disponivel and origem == modelo and cen == cenario
        else ("modelo_incompativel" if disponivel else "previsao_ausente")
    )
    aval = S.avaliar({**li, "uf": uf}, origem or modelo)
    if o is None:
        o = {
            "cod_imovel": car,
            "ha": _numero(li.get("ha")),
            "area_ha": None,
            "bioma": li.get("bioma"),
            "municipio": li.get("municipio"),
            "metodos": [],
            "pequena": li.get("porte") == "pequeno"
            or (_numero(li.get("m_fiscal")) is not None and float(li["m_fiscal"]) <= 4),
            "local_aproximado": car not in pontos,
            "lon": pontos.get(car, (None, None))[0],
            "lat": pontos.get(car, (None, None))[1],
        }
    if disponivel:
        # Zero observado não é ausência: a conversão histórica usa "or p50".
        for q in ("p10", "p50", "p90"):
            v = _numero(li.get(f"credito_liquido_tco2_ha_contrato_{q}"))
            o[f"credito_{q}"] = v * o["area_ha"] if v is not None else None
        v = _numero(li.get("marcos_todos_chance_pct"))
        o["marcos_todos"] = v / 100 if v is not None else None
    pendencias = [p["codigo"] for p in aval["pendencias"]]
    motivos = []
    if situacao != "compativel":
        pendencias.append(situacao)
        motivos.append("Previsão ausente ou incompatível com o modelo/cenário pedido; valores de origem preservados.")
    area, ha = _numero(o.get("area_ha")), _numero(o.get("ha"))
    if area is None or area <= 0:
        pendencias.append("area_sem_estimativa_positiva")
        motivos.append("Sem estimativa positiva de área restaurável; ausência de dado não comprova falta de potencial.")
    if area is not None and (area < 0 or (ha is not None and area > ha + TOLERANCIA_AREA_HA)):
        raise ValueError("Área da previsão excede limite físico ou é negativa; preservar fonte e revisar o modelo.")
    if disponivel and all(o.get(f"credito_{q}") is not None for q in ("p10", "p50", "p90")):
        if not 0 <= o["credito_p10"] <= o["credito_p50"] <= o["credito_p90"]:
            raise ValueError("Faixa de créditos inválida; não ordenar nem corrigir a previsão no índice.")
    registro = {c: o.get(c) for c in TEXTOS + REAIS + BOOLEANOS}
    registro.update({c: _numero(li.get(c)) for c in PRECOS})
    registro.update(
        cod_imovel=car,
        uf=uf,
        cod_ibge=cod,
        metodos=list(o.get("metodos") or []),
        restauracao_versao=origem,
        restauracao_cenario=cen,
        entradas_versao=str(li.get("entradas_versao") or ""),
        situacao_previsao=situacao,
        pendencias=";".join(sorted(set(pendencias))),
        m_fiscal=_numero(li.get("m_fiscal")),
        reserva_risco_pct=_numero(li.get("reserva_risco_pct")),
        elegivel=bool(o.get("elegivel")) and situacao == "compativel",
        salvaguardas_planejamento=aval["elegivel_planejamento"],
        salvaguardas_comercializavel=aval["comercializavel"],
        consulta_livre_previa_informada=aval["consulta_livre_previa_informada"]["situacao"],
        fracao_creditos_comunidade_minima=aval["fracao_creditos_comunidade_minima"],
        nivel_interesse=str(li.get("nivel_interesse") or "sem_contato"),
    )
    for c in TEXTOS:
        registro[c] = str(registro[c]) if registro[c] is not None else None
    for c in REAIS:
        registro[c] = _numero(registro[c])
    for c in BOOLEANOS:
        registro[c] = bool(registro[c]) if registro[c] is not None else False
    decisoes = aval["decisoes"]
    if motivos or not registro["elegivel"]:
        motivos = motivos or [
            "Critérios de terra, bloqueio ou elegibilidade recebidos da fonte não permitem este lote."
        ]
        decisoes.append(
            S.decisao(
                car,
                "exclusao",
                "Elegibilidade do índice, sem piso de tamanho.",
                " ".join(motivos),
                origem or modelo,
                cenario_origem=cen,
            )
        )
    return registro, decisoes


def indexar_municipio(
    pasta: str | Path,
    uf: str,
    cod_municipio: int,
    destino: str | Path,
    *,
    modelo: str,
    cenario: str,
    proveniencia: dict | None = None,
) -> dict:
    """Indexação com trava por município: concorrência não publica arquivos pela metade."""
    trava = Path(destino) / "travas" / f"{uf.upper()}-{int(cod_municipio)}.lock"
    _diretorio(trava.parent)
    with trava.open("a") as f:
        trava.chmod(0o600)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return _indexar_municipio(
            pasta, uf, cod_municipio, destino, modelo=modelo, cenario=cenario, proveniencia=proveniencia
        )


def _indexar_municipio(
    pasta: str | Path,
    uf: str,
    cod_municipio: int,
    destino: str | Path,
    *,
    modelo: str,
    cenario: str,
    proveniencia: dict | None = None,
) -> dict:
    """Uma partição privada; cache por conteúdo. Nunca chama calcular/calcular_municipio.

    `pasta` contém fontes congeladas, incluindo previsões existentes. Modelo/cenário
    são um filtro de compatibilidade; não substituem as versões gravadas nas linhas.
    """
    pasta, destino = Path(pasta), Path(destino)
    uf, cod = uf.upper(), int(cod_municipio)
    if not modelo or not cenario or len(uf) != 2 or not uf.isalpha():
        raise ValueError("Informe UF, modelo e cenário explícitos.")
    if not (pasta / f"imoveis_{cod}.csv").exists():
        raise ValueError("Fonte municipal ausente; ausência não equivale a município vazio.")
    fontes = {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in _fontes(pasta, cod)}
    entrada = {
        "fontes": fontes,
        "uf": uf,
        "municipio": cod,
        "modelo": modelo,
        "cenario": cenario,
        "indice_versao": versao_indice(),
        "proveniencia": proveniencia or {},
    }
    chave = hashlib.sha256(_json(entrada)).hexdigest()
    relativa = Path("particoes") / uf / str(cod) / chave
    pasta_saida = destino / relativa
    manifesto = pasta_saida / "particao.json"
    if manifesto.exists():
        publicado = json.loads(manifesto.read_text())
        conferir_particao(publicado, destino)
        return {**publicado, "cache_reutilizado": True}
    _diretorio(pasta_saida)
    pontos = O.pontos_da_pasta(pasta, cod)
    contagens, modelos, cenarios, biomas = Counter(), Counter(), Counter(), Counter()
    arquivos = {"oferta": pasta_saida / "oferta.parquet", "decisoes": pasta_saida / "decisoes.jsonl"}
    buffer = []
    try:
        with (
            pq.ParquetWriter(arquivos["oferta"], SCHEMA, compression="zstd") as escritor,
            arquivos["decisoes"].open("w", encoding="utf-8") as trilha,
        ):
            fonte = _ler_linhas(pasta, cod)
            if "uf" in fonte and any(v is not None and str(v).upper() != uf for v in fonte.uf):
                raise ValueError("UF da entrada diverge do município declarado.")
            if "cod_municipio_ibge" in fonte:
                cs = pd.to_numeric(fonte.cod_municipio_ibge, errors="coerce").dropna()
                if not cs.eq(cod).all():
                    raise ValueError("Código municipal da entrada diverge da partição declarada.")
            for li in fonte.to_dict("records"):
                registro, decisoes = _registro(li, uf, cod, pontos, modelo, cenario)
                buffer.append(registro)
                contagens["imoveis"] += 1
                contagens[registro["situacao_previsao"]] += 1
                contagens["pequenas"] += int(registro["pequena"])
                contagens["area_positiva"] += int((registro["area_ha"] or 0) > 0)
                modelos[registro["restauracao_versao"]] += 1
                cenarios[registro["restauracao_cenario"]] += 1
                biomas[registro["bioma"] or "nao_informado"] += 1
                for decisao in decisoes:
                    trilha.write(_json(decisao).decode())
                    contagens["decisoes"] += 1
                if len(buffer) >= 4096:
                    escritor.write_table(pa.Table.from_pylist(buffer, schema=SCHEMA))
                    buffer.clear()
            if buffer:
                escritor.write_table(pa.Table.from_pylist(buffer, schema=SCHEMA))
        for p in arquivos.values():
            p.chmod(0o600)
        if {p.name: sha256(p) for p in _fontes(pasta, cod)} != {n: x["sha256"] for n, x in fontes.items()}:
            raise ValueError("Fontes mudaram durante a indexação; congele novamente o município.")
        particao = {
            **entrada,
            "acesso": "privado",
            "esquema": ESQUEMA,
            "id": chave,
            "contagens": dict(contagens),
            "modelos": dict(modelos),
            "cenarios": dict(cenarios),
            "biomas": dict(biomas),
            "arquivos": {
                k: {"caminho": str(p.relative_to(destino)), "sha256": sha256(p), "bytes": p.stat().st_size}
                for k, p in arquivos.items()
            },
        }
        gravar_json(manifesto, particao)
        return {**particao, "cache_reutilizado": False}
    except BaseException:
        for p in arquivos.values():
            p.unlink(missing_ok=True)
        raise


def caminho_privado(raiz: Path, relativo: str) -> Path:
    p = (raiz / relativo).resolve()
    if not p.is_relative_to(raiz.resolve()):
        raise ValueError("Arquivo fora do catálogo privado.")
    return p


def conferir_particao(particao: dict, raiz: str | Path, *, hashes: bool = True) -> None:
    if particao.get("acesso") != "privado" or particao.get("esquema") != ESQUEMA:
        raise ValueError("Partição sem contrato privado compatível.")
    for arquivo in particao["arquivos"].values():
        p = caminho_privado(Path(raiz), arquivo["caminho"])
        if not p.exists() or p.stat().st_size != arquivo["bytes"] or (hashes and sha256(p) != arquivo["sha256"]):
            raise ValueError("Partição incompleta ou divergente do SHA-256 publicado.")


def consolidar_catalogo(
    particoes: list[dict],
    destino: str | Path,
    *,
    municipios_esperados: dict[str, list[int]],
    sem_imoveis: dict[str, list[int]] | None = None,
    proveniencia: dict | None = None,
) -> Path:
    """Valida unicidade global e publica snapshot privado. Não deduplica créditos silenciosamente."""
    destino = Path(destino)
    _diretorio(destino)
    partes = [{k: v for k, v in p.items() if k != "cache_reutilizado"} for p in particoes]
    vistos, caminhos = set(), []
    esperados = {u.upper(): sorted(set(map(int, cs))) for u, cs in municipios_esperados.items()}
    vazios = {u.upper(): sorted(set(map(int, cs))) for u, cs in (sem_imoveis or {}).items()}
    for p in partes:
        conferir_particao(p, destino)
        par = (p["uf"], p["municipio"])
        if par in vistos:
            raise ValueError("Mais de uma partição para o mesmo município; escolher a fonte explicitamente.")
        if p["municipio"] not in esperados.get(p["uf"], []):
            raise ValueError("Partição fora da cobertura municipal declarada.")
        if p["municipio"] in vazios.get(p["uf"], []):
            raise ValueError("Município com partição não pode ser declarado sem imóveis.")
        vistos.add(par)
        caminhos.append(str(caminho_privado(destino, p["arquivos"]["oferta"]["caminho"])))
    for u, cs in vazios.items():
        if not set(cs) <= set(esperados.get(u, [])):
            raise ValueError("Município vazio fora da cobertura esperada.")
    if caminhos:
        with duckdb.connect(config={"memory_limit": "1GB", "threads": 2}) as con:
            con.from_parquet(caminhos).create_view("oferta")
            n, distintos = con.sql("select count(*), count(distinct cod_imovel) from oferta").fetchone()
            if n != distintos:
                raise ValueError("CAR repetido entre partições; conciliar fontes antes de somar créditos.")
    else:
        n = 0
    cobertura = {}
    for uf, cs in sorted(esperados.items()):
        presentes = sorted(c for u, c in vistos if u == uf)
        vazio = vazios.get(uf, [])
        faltantes = sorted(set(cs) - set(presentes) - set(vazio))
        cobertura[uf] = {
            "esperados": cs,
            "presentes": presentes,
            "sem_imoveis": vazio,
            "faltantes": faltantes,
            "completo": not faltantes,
        }
    corpo = {
        "acesso": "privado",
        "esquema": ESQUEMA,
        "particoes": sorted(partes, key=lambda p: (p["uf"], p["municipio"])),
        "cobertura": cobertura,
        "imoveis": n,
        "proveniencia": proveniencia or {},
    }
    chave = hashlib.sha256(_json(corpo)).hexdigest()
    arquivo = destino / f"catalogo_lote_{chave}.json"
    gravar_json(arquivo, {**corpo, "id": chave})
    return arquivo


def abrir_catalogo(arquivo: str | Path, *, conferir_hashes: bool = True) -> tuple[dict, list[str]]:
    arquivo = Path(arquivo)
    catalogo = json.loads(arquivo.read_text())
    corpo = {k: v for k, v in catalogo.items() if k != "id"}
    if hashlib.sha256(_json(corpo)).hexdigest() != catalogo.get("id"):
        raise ValueError("Manifesto do catálogo divergente de sua identidade.")
    if catalogo.get("acesso") != "privado" or catalogo.get("esquema") != ESQUEMA:
        raise ValueError("Catálogo não é privado ou tem esquema incompatível.")
    caminhos = []
    for p in catalogo["particoes"]:
        conferir_particao(p, arquivo.parent, hashes=conferir_hashes)
        caminhos.append(str(caminho_privado(arquivo.parent, p["arquivos"]["oferta"]["caminho"])))
    return catalogo, caminhos
