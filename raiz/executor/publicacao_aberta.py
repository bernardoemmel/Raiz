"""Projeção pública fechada do motor: agregados e apenas situação básica por CAR.

Qualquer tabela, coluna ou asset novo é privado até ser incluído explicitamente
neste contrato. A validação roda antes do upload, inclusive no publicador legado.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import tarfile

import pandas as pd
import pandera.pandas as pa

from raiz.qualidade_dados import (
    ErroQualidade,
    _carregar_json,
    _municipios,
    _normalizar_lugar,
    _saltos,
    validar_arquivos,
    validar_json,
)

VERSAO_PUBLICACAO = 1
ESCOPO = "publico_basico"
COLUNAS_BASICAS = ("cod_imovel", "cod_ibge", "municipio", "uf", "situacao_basica")
COLUNAS_SEM_IMOVEIS = ("cod_ibge", "municipio", "verificado_em")
COLUNAS_RESUMO = (
    "cod_ibge",
    "municipio",
    "imoveis",
    "sem_problema",
    "def_RL",
    "aptas_carbono",
    "ha_carbono",
    "tco2_ano_aptas",
    "aptas_com_matricula",
    "ha_carbono_matricula",
    "cota_reserva",
    "redd_imoveis",
    "redd_ha",
    "app_imoveis",
    "app_ha",
    "frigorifico_imoveis",
    "frigorifico_ha",
    "compensacao_ha",
    "eudr_ok",
    "credito_rural_ok",
    "compra_arrendamento",
    "alerta_pos2020_imoveis",
    "frente_regularizar_antes",
    "frente_carbono",
    "frente_silvipastoril",
    "frente_desbloqueio",
    "frente_carbono_revisar_desm10anos",
    "frente_assentamento_agrupado",
    "frente_carbono_so_plantio",
    "frente_fora_TI",
    "frente_ja_tem_projeto",
)
COLUNAS_GEO = ("cod_imovel", "geometry")
SITUACOES = ("apto", "com_pendencia", "nao_apto")
_CAR = re.compile(r"^[A-Z]{2}-\d{7}-[0-9A-F]{32}$")
_MUN = re.compile(r"^\d{7}$")
_UFS = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
_MEDIDAS_GRUPOS = (
    ("ha_carbono", "aptas_carbono"),
    ("tco2_ano_aptas", "aptas_carbono"),
    ("ha_carbono_matricula", "aptas_com_matricula"),
    ("redd_ha", "redd_imoveis"),
    ("app_ha", "app_imoveis"),
    ("frigorifico_ha", "frigorifico_imoveis"),
)


def _csv(dados: bytes) -> tuple[list[str], list[dict]]:
    leitor = csv.DictReader(io.StringIO(dados.decode("utf-8-sig")))
    return leitor.fieldnames or [], list(leitor)


def _gravar_csv(colunas: tuple | list, linhas: list[dict]) -> bytes:
    out = io.StringIO(newline="")
    escritor = csv.DictWriter(out, fieldnames=colunas, lineterminator="\n")
    escritor.writeheader()
    escritor.writerows(linhas)
    return out.getvalue().encode()


def _numero(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) and n >= 0 else None


def projetar_csvs(uf: str, csvs: dict[str, bytes]) -> dict[str, bytes]:
    """Gera arquivos novos, sem copiar dicionários ou colunas privadas para a saída."""
    from raiz.motivos import ler

    out = {}
    for nome, dados in csvs.items():
        if m := re.fullmatch(r"imoveis_(\d{7})\.csv", nome):
            cod = m.group(1)
            _, linhas = _csv(dados)
            basicas = []
            for linha in linhas:
                car = re.sub(r"[^A-Z0-9]", "", str(linha.get("cod_imovel", "")).upper())
                car = f"{car[:2]}-{car[2:9]}-{car[9:]}"
                if not _CAR.fullmatch(car):
                    raise ValueError(f"{nome}: CAR inválido na projeção pública")
                regra = ler(linha)
                situacao = "com_pendencia" if regra["problema"] else "apto" if regra["apta"] else "nao_apto"
                basicas.append(
                    dict(zip(COLUNAS_BASICAS, (car, cod, linha.get("municipio", ""), uf, situacao), strict=True))
                )
            out[f"imoveis_basicos_{cod}.csv"] = _gravar_csv(COLUNAS_BASICAS, basicas)
        elif nome in (f"resumo_{uf}.csv", f"sem_imoveis_{uf}.csv"):
            colunas, linhas = _csv(dados)
            permitidas = COLUNAS_RESUMO if nome.startswith("resumo_") else COLUNAS_SEM_IMOVEIS
            colunas = [c for c in permitidas if c in colunas]
            projetadas = [{c: r.get(c, "") for c in colunas} for r in linhas]
            if nome.startswith("resumo_"):
                # Uma soma de poucos imóveis não deve revelar a medida de uma fazenda.
                for r in projetadas:
                    n = _numero(r.get("imoveis")) or 0
                    for c in colunas:
                        if c not in ("cod_ibge", "municipio", "imoveis") and n < 5:
                            r[c] = ""
                    for medida, contagem in _MEDIDAS_GRUPOS:
                        if medida in r and (_numero(r.get(contagem)) or 0) < 5:
                            r[medida] = ""
            out[nome] = _gravar_csv(colunas, projetadas)
    return out


def projetar_geo(dados: bytes) -> bytes:
    import geopandas as gpd

    g = gpd.read_parquet(io.BytesIO(dados), columns=list(COLUNAS_GEO))
    # Recriar o objeto remove atributos/índices e metadados herdados.
    limpo = gpd.GeoDataFrame({"cod_imovel": g.cod_imovel.astype(str)}, geometry=g.geometry, crs=g.crs)
    out = io.BytesIO()
    limpo.to_parquet(out, index=False)
    return out.getvalue()


def entrada_publica(info: dict) -> dict:
    """Manifesto sem controle de retomada, erros livres, caminhos privados ou campos comerciais."""
    out = {"versao_publicacao": VERSAO_PUBLICACAO, "escopo": ESCOPO}
    for k in ("municipios", "sem_imoveis", "total_ibge", "completo", "funil_completo", "tamanho"):
        v = info.get(k)
        if isinstance(v, (int, float, bool)) and (isinstance(v, bool) or math.isfinite(v)):
            out[k] = v
    for k in ("versao", "atualizado_em", "motor_versao", "situacao"):
        v = info.get(k)
        if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.:+/-]{1,200}", v):
            out[k] = v
    for k in ("faltam", "tabelas", "versoes"):
        if isinstance(info.get(k), dict):
            out[k] = {
                n: v
                for n, v in info[k].items()
                if re.fullmatch(r"[a-z_]{1,40}", str(n))
                and (isinstance(v, int) or (isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,200}", v)))
            }
    return out


def _validar_csv(nome: str, dados: bytes, uf: str) -> None:
    colunas, linhas = _csv(dados)
    if re.fullmatch(r"imoveis_basicos_\d{7}\.csv", nome):
        if tuple(colunas) != COLUNAS_BASICAS:
            raise ValueError(f"{nome}: colunas fora do contrato básico")
        for r in linhas:
            if not _CAR.fullmatch(r.get("cod_imovel", "")) or not _MUN.fullmatch(r.get("cod_ibge", "")):
                raise ValueError(f"{nome}: identificador inválido")
            if r.get("situacao_basica") not in SITUACOES or r.get("uf") != uf:
                raise ValueError(f"{nome}: situação ou UF inválida")
            # O recorte SICAR inclui imóveis limítrofes cadastrados no município vizinho.
            # cod_ibge identifica o arquivo/recorte processado, não reescreve o município no CAR.
            if r["cod_imovel"][:2] != uf or r["cod_ibge"] != nome.removeprefix("imoveis_basicos_")[:-4]:
                raise ValueError(f"{nome}: UF do CAR ou município do recorte divergente")
    elif nome == f"resumo_{uf}.csv":
        if not colunas or not set(colunas) <= set(COLUNAS_RESUMO):
            raise ValueError(f"{nome}: colunas fora do agregado permitido")
        if any("cod_imovel" in r or not _MUN.fullmatch(r.get("cod_ibge", "")) for r in linhas):
            raise ValueError(f"{nome}: não é agregado municipal")
        if any(
            v not in (None, "") and _numero(v) is None
            for r in linhas
            for k, v in r.items()
            if k not in ("cod_ibge", "municipio")
        ):
            raise ValueError(f"{nome}: agregado contém valor não numérico")
    elif nome == f"sem_imoveis_{uf}.csv":
        if not colunas or not set(colunas) <= set(COLUNAS_SEM_IMOVEIS):
            raise ValueError(f"{nome}: colunas fora do contrato")
    else:
        raise ValueError(f"{nome}: arquivo reservado ao armazenamento privado")
    if len(colunas) != len(set(colunas)) or any(None in r for r in linhas):
        raise ValueError(f"{nome}: CSV ambíguo")
    # O contrato básico tem identidade/situação, sem métricas privadas do contrato completo.
    obrigatorias = (
        COLUNAS_BASICAS
        if nome.startswith("imoveis_basicos_")
        else COLUNAS_SEM_IMOVEIS
        if nome.startswith("sem_imoveis_")
        else ("cod_ibge", "municipio", "imoveis")
    )
    tabela = pd.DataFrame(linhas, columns=colunas)
    schema = pa.DataFrameSchema({c: pa.Column(str, nullable=False) for c in obrigatorias}, strict=False)
    try:
        schema.validate(tabela, lazy=True)
    except (pa.errors.SchemaError, pa.errors.SchemaErrors):
        raise ErroQualidade("publicação aberta bloqueada: colunas obrigatórias ausentes ou nulas") from None
    if "cod_imovel" in tabela and tabela["cod_imovel"].duplicated().any():
        raise ErroQualidade("publicação aberta bloqueada: CAR duplicado")
    for linha in linhas:
        validar_json(linha)
        codigo = linha["cod_ibge"]
        # SICAR conserva o CAR original; o nome pode referir-se à origem ou ao recorte atual.
        municipio_origem = linha["cod_imovel"][3:10] if "cod_imovel" in linha else codigo
        nomes_permitidos = {_municipios().get(codigo), _municipios().get(municipio_origem)}
        if codigo not in _municipios() or _normalizar_lugar(linha["municipio"]) not in nomes_permitidos:
            raise ErroQualidade("publicação aberta bloqueada: município fora do contrato IBGE")
        if nome.startswith("sem_imoveis_") and pd.isna(
            pd.to_datetime(linha["verificado_em"], errors="coerce", utc=True)
        ):
            raise ErroQualidade("publicação aberta bloqueada: data inválida")
    if nome.startswith("resumo_"):
        if tabela["cod_ibge"].duplicated().any():
            raise ErroQualidade("publicação aberta bloqueada: município duplicado no resumo")
        intensidades = {}
        for linha in linhas:
            n = _numero(linha["imoveis"])
            if n is None or not n.is_integer():
                raise ErroQualidade("publicação aberta bloqueada: contagem municipal inválida")
            if n < 5 and any(
                v not in (None, "") for c, v in linha.items() if c not in ("cod_ibge", "municipio", "imoveis")
            ):
                raise ErroQualidade("publicação aberta bloqueada: medida de grupo pequeno não suprimida")
            for medida, contagem in _MEDIDAS_GRUPOS:
                if linha.get(medida) not in (None, "") and (_numero(linha.get(contagem)) or 0) < 5:
                    raise ErroQualidade("publicação aberta bloqueada: medida de grupo pequeno não suprimida")
            area, carbono = _numero(linha.get("ha_carbono")), _numero(linha.get("tco2_ano_aptas"))
            if area is not None and area > 0 and carbono is not None:
                intensidade = carbono / area
                if not math.isfinite(intensidade):
                    raise ErroQualidade("publicação aberta bloqueada: intensidade municipal não finita")
                intensidades[f"resumo_{linha['cod_ibge']}.csv"] = (
                    "resumo",
                    pd.DataFrame({"taxa_tco2_ha_ano": [intensidade]}),
                )
        # Mesma triagem de escala do contrato completo; não compara totais ou tamanhos municipais.
        _saltos(intensidades)


def _validar_asset_publico(nome: str, dados: bytes, *, repo: str, tag: str) -> None:
    """Falha antes do upload se qualquer arquivo/coluna não pertence à projeção pública."""
    if nome == "cartao_modelo.md":
        from raiz import RAIZ_REPO

        if dados != (RAIZ_REPO / "docs" / "modelo" / "cartao.md").read_bytes():
            raise ValueError("cartão público deve corresponder ao texto metodológico revisado")
        return
    if nome == "croissant.json" or nome.startswith("croissant_"):
        from raiz.metadados import validar_ficha_publica

        validar_ficha_publica(nome, dados, repo=repo, tag=tag)
        return
    if nome == "estados.json":
        manifesto = _carregar_json(dados)
        validar_json(manifesto)
        if set(manifesto) - {"escopo", "versao_publicacao", "gerado_em", "repo", "tag", "estados"}:
            raise ValueError("manifesto público contém campo desconhecido")
        if manifesto.get("escopo") != ESCOPO or manifesto.get("versao_publicacao") != VERSAO_PUBLICACAO:
            raise ValueError("manifesto público sem marca de projeção")
        repo, tag = manifesto.get("repo", ""), manifesto.get("tag", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
            raise ValueError("destino do manifesto inválido")
        for uf, info in manifesto.get("estados", {}).items():
            permitidos = set(entrada_publica(info)) | {"url", "geo"}
            if uf not in _UFS or set(info) - permitidos:
                raise ValueError("manifesto público contém detalhe privado")
            if info.get("escopo") != ESCOPO or info.get("versao_publicacao") != VERSAO_PUBLICACAO:
                raise ValueError("estado sem marca de projeção")
            base = f"https://github.com/{repo}/releases/download/{tag}"
            if info.get("url") != f"{base}/raiz_{uf}.tar.gz":
                raise ValueError("pacote deve apontar ao Release público do manifesto")
            if geo := info.get("geo"):
                if set(geo) - {"escopo", "url", "versao", "tamanho", "municipios"} or geo.get("escopo") != ESCOPO:
                    raise ValueError("geometria no manifesto contém detalhe privado")
                if geo.get("url") != f"{base}/raiz_geo_{uf}.tar.gz":
                    raise ValueError("geometria deve apontar ao Release público do manifesto")
        return
    m = re.fullmatch(r"raiz_(geo_)?([A-Z]{2})\.tar\.gz", nome)
    if not m:
        raise ValueError(f"{nome}: asset não permitido no Release aberto")
    geo, uf = m.groups()
    if uf not in _UFS:
        raise ValueError("UF fora do contrato")
    # Gzip também possui campos livres; a projeção gerada não precisa deles.
    if len(dados) < 10 or dados[:2] != b"\x1f\x8b" or dados[3] & 0x1C:
        raise ValueError("cabeçalho gzip fora do contrato")
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tar:
        vistos = set()
        for membro in tar:
            partes = membro.name.split("/")
            if not membro.isfile() or len(partes) != 2 or partes[0] != uf or membro.name in vistos:
                raise ValueError(f"{nome}: membro inválido no pacote")
            vistos.add(membro.name)
            if membro.uname or membro.gname or membro.pax_headers or tar.pax_headers:
                raise ValueError("metadados TAR fora do contrato")
            arq = partes[1]
            conteudo = tar.extractfile(membro).read()
            if geo:
                import pyarrow.parquet as pq

                if not re.fullmatch(r"geo_\d{7}\.parquet", arq):
                    raise ValueError(f"{nome}: camada não é contorno básico")
                schema = pq.read_schema(io.BytesIO(conteudo))
                if set(schema.names) != set(COLUNAS_GEO):
                    raise ValueError(f"{nome}: geometria contém atributos privados")
                if set(schema.metadata or {}) - {b"geo", b"pandas"}:
                    raise ValueError(f"{nome}: geometria contém metadados adicionais")
                pandas = json.loads((schema.metadata or {}).get(b"pandas", b"{}"))
                if pandas.get("attributes"):
                    raise ValueError(f"{nome}: geometria contém atributos em metadados")
                # Inspeção integral das colunas, valores, metadados Arrow/CRS e geometria.
                validar_arquivos({arq: conteudo})
                cars = pq.read_table(io.BytesIO(conteudo), columns=["cod_imovel"])["cod_imovel"].to_pylist()
                if any(not isinstance(car, str) or not _CAR.fullmatch(car) or car[:2] != uf for car in cars):
                    raise ValueError("CAR da geometria fora do contrato")
            else:
                _validar_csv(arq, conteudo, uf)


def validar_asset_publico(nome: str, dados: bytes, *, repo: str = "bernardoemmel/Raiz", tag: str = "dados") -> None:
    """Contrato, Pandera e privacidade sobre os bytes enviados, sem ecoar valores dos parsers."""
    try:
        _validar_asset_publico(nome, dados, repo=repo, tag=tag)
    except ErroQualidade:
        raise
    except Exception:
        raise ErroQualidade(
            "publicação aberta bloqueada: arquivo ou atributos privados fora do contrato; valores omitidos"
        ) from None
