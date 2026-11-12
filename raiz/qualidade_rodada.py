"""Portão dos pacotes da rodada de restauração, antes de qualquer upload.

Relatórios HTML e propostas individuais ainda não têm contrato de distribuição
pública/consentimento. Permanecem privados: o portão não transforma ausência de
CPF em autorização para publicar um documento individual.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import tarfile
from pathlib import Path, PurePosixPath

import pandas as pd
import pandera.pandas as pa

from raiz.qualidade_dados import ErroQualidade, validar_arquivos, validar_json

OPCOES = {"barata", "segura", "compacta"}
JSON_RAIZ = {"manifesto.json", "fontes.json", "municipios.json", "comparacao_real_1504950.json", "tres_lotes_PA.json"}


def _falhar(regra: str) -> None:
    raise ErroQualidade(f"publicação da rodada bloqueada: {regra}; valores omitidos") from None


def _json(dados: bytes):
    def pares(itens):
        out = {}
        for k, v in itens:
            if k in out:
                _falhar("chave JSON duplicada")
            out[k] = v
        return out

    return json.loads(dados, object_pairs_hook=pares)


def _numeros(dado, areas: pd.Series, car: str | None = None, campo: str = "") -> None:
    """Faixas aninhadas e áreas por CAR também se aplicam aos registros JSONL."""
    if isinstance(dado, list):
        for item in dado:
            _numeros(item, areas, car, campo)
    elif isinstance(dado, dict):
        car = dado.get("cod_imovel", car)
        if car is not None and car not in areas.index:
            _falhar("CAR sem área de referência")
        for chave, valor in dado.items():
            if chave in {
                "_cod_imovel",
                "_plus_code",
                "_omaps",
                "geometry",
                "geometria",
                "coordinates",
                "perimetro",
                "latitude",
                "longitude",
                "lat",
                "lon",
                "_lat",
                "_lon",
            }:
                _falhar("localização ou exportação administrativa sem contrato público")
            if isinstance(valor, int | float) and not isinstance(valor, bool):
                if re.search(r"(^pct_|_pct(?:_|$))", chave) and not re.search(r"tir|declividade", chave):
                    if not 0 <= valor <= 100:
                        _falhar("porcentagem fora de zero a cem")
                if car is not None and chave in {
                    "area_ha",
                    "ha",
                    "area_segura_ha",
                    "area_restaurada_ha",
                    "restauracao_area_ha",
                    "restauracao_regeneracao_assistida_ha",
                    "restauracao_semeadura_direta_ha",
                    "restauracao_plantio_total_ha",
                    "regeneracao_ha",
                    "semeadura_ha",
                    "plantio_ha",
                }:
                    if valor < 0 or valor > float(areas[car]) + 1e-6:
                        _falhar("área fora dos limites do CAR")
            _numeros(valor, areas, car, chave)
            if re.search(r"(^|_)p(?:10|50|90)$", chave):
                base = chave[:-3]
                # Grandezas centrais isoladas documentadas em docs/colunas.md e
                # indicadores/checklist do produtor raiz/lote.py: não são faixas.
                centrais = {
                    "captura_total_tco2_ha_p50",
                    "custo_implantacao_ha_p50",
                    "fecha_no_p50",
                    "falta_p50",
                    "creditos_precisa_p50",
                    "faixa_p50_p90",
                }
                if chave in centrais and base + "p10" not in dado and base + "p90" not in dado:
                    continue
                if chave == "faixa_p50_p90" and isinstance(valor, dict):
                    continue  # item textual do checklist, não quantil numérico
                if (
                    campo == "mme102"
                    and chave == "p50"
                    and "p10" not in dado
                    and "p90" not in dado
                    and {"p90_excedencia", "p90_excedencia_soma", "incerteza_padrao"} <= set(dado)
                ):
                    # Portaria MME102: P90 de excedência significa nosso P10.
                    if not 0 <= dado["p90_excedencia"] <= valor:
                        _falhar("P90 de excedência maior que P50")
                    continue
                chaves = [base + q for q in ("p10", "p50", "p90")]
                # Algumas saídas do motor chamam o valor central pelo nome sem _p50.
                if chaves[1] not in dado and base.rstrip("_") in dado:
                    chaves[1] = base.rstrip("_")
                if not all(k in dado for k in chaves):
                    _falhar("faixa P10/P50/P90 incompleta")
                valores = [dado[k] for k in chaves]
                if any(v is not None for v in valores):
                    if not all(isinstance(v, int | float) and not isinstance(v, bool) for v in valores):
                        _falhar("faixa P10/P50/P90 parcialmente nula ou não numérica")
                    if not valores[0] <= valores[1] <= valores[2]:
                        _falhar("P10 ≤ P50 ≤ P90")


def _lote_csv(dados: bytes, areas: pd.Series) -> None:
    from raiz.lote import COLUNAS_TABELA

    cabecalho = next(csv.reader(io.StringIO(dados.decode("utf-8-sig"))))
    if len(cabecalho) != len(set(cabecalho)):
        _falhar("colunas CSV duplicadas")
    df = pd.read_csv(io.BytesIO(dados), dtype={"cod_imovel": str})
    if len(df.columns) != len(set(df.columns)) or set(df) - set(COLUNAS_TABELA):
        _falhar("CSV do lote fora do contrato")
    schema = pa.DataFrameSchema(
        {
            "cod_imovel": pa.Column(str, nullable=False, unique=True),
            "papel": pa.Column(str, checks=pa.Check.isin(["titular", "reserva", "mitigacao", "em_espera"])),
            "area_ha": pa.Column(float, checks=pa.Check.ge(0), coerce=True, nullable=True),
            **{f"credito_{q}": pa.Column(float, coerce=True, nullable=True) for q in ("p10", "p50", "p90")},
        },
        strict=False,
    )
    schema.validate(df, lazy=True)
    registros = df.astype(object).where(pd.notna(df), None).to_dict("records")
    validar_json(registros)
    _numeros(registros, areas)


def _validar(pacotes: list[Path], referencias: Path, manifesto: dict) -> dict[str, int]:
    exigidos_manifesto = {
        "cenario",
        "uf",
        "municipios",
        "municipios_calculados",
        "imoveis_calculados",
        "modelo_versao",
        "opcoes",
        "fontes",
        "resumos",
        "arquivos",
    }
    if not exigidos_manifesto <= set(manifesto) or manifesto["uf"] != "PA" or set(manifesto["opcoes"]) != OPCOES:
        _falhar("manifesto sem contrato completo da rodada")
    # Referências vêm do snapshot usado no cálculo, não de hectares declarados pelo próprio lote.
    tabelas = {f.name: f.read_bytes() for f in referencias.glob("imoveis_*.csv")}
    if not tabelas:
        _falhar("snapshot sem referências CAR")
    areas = pd.concat(
        [pd.read_csv(io.BytesIO(b), dtype={"cod_imovel": str}).set_index("cod_imovel")["ha"] for b in tabelas.values()]
    )
    if not areas.index.is_unique:
        _falhar("CAR duplicado no snapshot")
    jsons = []
    csvs_lote = []
    total = 0
    publicados = set()
    for pacote in pacotes:
        with tarfile.open(pacote, "r:gz") as tar:
            vistos = set()
            for membro in tar:
                p = PurePosixPath(membro.name)
                if p.is_absolute() or ".." in p.parts or str(p) != membro.name.rstrip("/"):
                    _falhar("caminho TAR inválido")
                if set(membro.pax_headers) - {"mtime"} or not math.isfinite(float(membro.mtime)):
                    _falhar("metadado TAR sem contrato público")
                if membro.isdir():
                    if str(p) not in OPCOES | {"previsoes", "previsoes/registros"}:
                        _falhar("diretório TAR sem contrato público")
                    continue
                if not membro.isfile() or membro.name in vistos or membro.size > 2 * 1024**3:
                    _falhar("membro TAR inválido, duplicado ou grande demais")
                vistos.add(membro.name)
                if membro.name in publicados:
                    _falhar("membro duplicado entre pacotes")
                publicados.add(membro.name)
                # Propostas individuais e HTML não têm autorização implícita de distribuição pública.
                if "folhas_dono" in p.parts or p.suffix == ".html":
                    _falhar("documento individual ou HTML sem contrato público; separar armazenamento privado")
                dado = tar.extractfile(membro).read()
                total += 1
                if len(p.parts) == 2 and p.parts[0] in OPCOES:
                    if p.name == "lote_PA.csv":
                        csvs_lote.append(dado)
                    elif p.name in {"lote_PA.json", "ecologia_PA.json"}:
                        jsons.append(_json(dado))
                    elif p.name == "decisoes_PA.jsonl":
                        jsons.extend(_json(linha) for linha in dado.splitlines() if linha)
                    else:
                        _falhar("arquivo de opção sem contrato")
                elif len(p.parts) == 1 and p.name in JSON_RAIZ:
                    jsons.append(_json(dado))
                elif str(p) == "decisoes_entrada.jsonl" or re.fullmatch(
                    r"previsoes/(?:validacao_entradas_\d{7}|registros/previsoes_[a-f0-9]{64})\.jsonl", str(p)
                ):
                    jsons.extend(_json(linha) for linha in dado.splitlines() if linha)
                elif (
                    len(p.parts) == 2
                    and p.parts[0] == "previsoes"
                    and re.fullmatch(r"(?:desenvolvedor|terra)_\d{7}\.csv", p.name)
                ):
                    if p.name in tabelas:
                        _falhar("tabela duplicada nos pacotes")
                    tabelas[p.name] = dado
                else:
                    _falhar("arquivo da rodada sem contrato público")
    obrigatorios = (
        JSON_RAIZ
        | {"decisoes_entrada.jsonl"}
        | {
            f"{opcao}/{nome}"
            for opcao in OPCOES
            for nome in ("lote_PA.csv", "lote_PA.json", "ecologia_PA.json", "decisoes_PA.jsonl")
        }
    )
    if not obrigatorios <= publicados or not any(n.startswith("desenvolvedor_") for n in tabelas):
        _falhar("pacote sem arquivos obrigatórios da rodada")
    resultado = validar_arquivos(tabelas)
    for dado in [manifesto, *jsons]:
        _numeros(dado, areas)
        validar_json(dado)
    for dado in csvs_lote:
        _lote_csv(dado, areas)
    return {"arquivos": total + 2, "tabelas": resultado["tabelas"] + len(csvs_lote)}


def validar_publicacao(pacotes: list[Path], referencias: Path, manifesto: dict) -> dict[str, int]:
    """Todos os pacotes e ambos os manifestos (imutável e ponteiro) antes do primeiro upload."""
    try:
        return _validar(pacotes, referencias, manifesto)
    except ErroQualidade:
        raise
    except Exception:
        _falhar("formato, colunas ou conteúdo inválidos")
