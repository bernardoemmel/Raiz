"""Coleta das fontes complementares da triagem, sem download manual e sem dado pessoal na saída.

Fontes abertas (coleta semanal, workflow coletar-complementares.yml):
  sicor             Crédito rural do Banco Central (microdados do SICOR, ODbL). Três arquivos: operações por ano
                    (SICOR_OPERACAO_BASICA_ESTADO_<ano>), o vínculo operação → imóvel (SICOR_PROPRIEDADES, com o CAR)
                    e as glebas financiadas (SICOR_GLEBAS_WKT_<ano>). O SICOR_PROPRIEDADES traz CPF/CNPJ do tomador:
                    a coluna nem é lida (usecols). Saem só o código do CAR, datas, finalidade, área financiada e o
                    polígono da gleba. Nunca valor em reais nem documento.
  ibge_quilombolas  Localidades quilombolas do Censo 2022 (IBGE): um ponto por localidade, com o território
                    quilombola oficial (CD_TQ) quando existe e o processo de certificação na Fundação Palmares
                    (P_FCP). Sai o nome da comunidade (só códigos e marcações).
  palmares          Comunidades certificadas pela Fundação Cultural Palmares (planilha oficial, atualizada todo
                    mês; link na página "Certificação Quilombola" da FCP). Vira contagem por município: certificadas e
                    certificadas sem título. Nomes e números de processo não saem.

Fontes que dependem de autorização (importação de um arquivo recebido, `raiz complementares importar`):
  mpf_territorios   Plataforma de Territórios Tradicionais (MPF/CNPCT). O acesso aos dados é decidido pelo Conselho
                    Gestor; não há download público. Ficam id, segmento, situação e polígono.
  observatorio      Observatório da Restauração e Reflorestamento (Coalizão Brasil): shapefile pedido por e-mail.
  restor            Restor (restor.eco): os termos de uso proíbem copiar os dados sem permissão; API só no plano
                    Enterprise. Entra só com autorização por escrito (fica registrada no arquivo de metadados).
  Observatório e Restor viram "projetos de restauração fora dos registros de carbono": ficam id, categoria, ano de
  início, área e polígono; nomes de responsáveis, e-mails e telefones nunca são lidos.

Saída (pasta que o workflow publica no Release "insumos"; status.py lê de RAIZ_COMPLEMENTARES_DIR ou
cache/complementares): ver NOMES. Uma fonte que falha vira "indisponivel"; quem consome nunca lê isso como livre.
"""

from __future__ import annotations

import datetime as dt
import gzip
import io
import json
import logging
import re
import tempfile
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

VERSAO = "complementares-coleta-2026a"
FONTES_ABERTAS = ("sicor", "ibge_quilombolas", "palmares")
FONTES_IMPORTADAS = ("mpf_territorios", "observatorio", "restor")
FONTES = FONTES_ABERTAS + FONTES_IMPORTADAS
NOMES = {
    "sicor_car": "complementares_sicor_car.parquet",
    "ibge_quilombolas": "complementares_ibge_quilombolas.parquet",
    "palmares": "complementares_palmares_municipios.csv",
    "mpf_territorios": "complementares_mpf_territorios.parquet",
    "observatorio": "complementares_restauracao_observatorio.parquet",
    "restor": "complementares_restauracao_restor.parquet",
    "cobertura": "complementares_cobertura.json",
}
GLEBAS = "complementares_sicor_glebas_{uf}.parquet"
META_IMPORTADA = "complementares_{fonte}_meta.json"

URL_SICOR = "https://www.bcb.gov.br/htms/sicor/DadosBrutos/{arquivo}"
URL_SICOR_EMPREENDIMENTO = "https://www.bcb.gov.br/htms/sicor/Empreendimento.csv"
URL_IBGE_QUILOMBOLAS = (
    "https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/"
    "localidades_quilombolas_2022/Arquivos_vetoriais/csv/BR/BR_LQs_CD2022.csv"
)
# planilha oficial da FCP (gov.br/palmares > Certificação Quilombola > "Comunidades certificadas")
URL_PALMARES = "https://docs.google.com/spreadsheets/d/1WBjixnnjJWrDXsA2WvElj65rrZ4nkNM-u5LclRV0lGs/export?format=csv&gid=680278480"
UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
BBOX_BRASIL = (-74.5, -34.5, -28.5, 5.6)
# Operações de investimento duram até ~12 anos: lê os anos de emissão que ainda podem estar ativos.
ANOS_OPERACOES = 10
# Glebas: só as emitidas nos últimos anos (uso agrícola recente) e as de operações ainda ativas.
ANOS_GLEBAS = 3
# Modalidade/produto do SICOR que indicam floresta, recuperação ou integração com floresta (Empreendimento.csv).
# (texto já sem acento)
FLORESTA = re.compile(
    r"FLORESTAMENTO|RECUPERACAO AMBIENTAL|LAVOURA-PECUARIA-FLORESTA|EXTRATIVISMO|AGROFLORESTAL|"
    r"ESPECIES NATIVAS"
)
COLUNAS_SICOR_CAR = [
    "cod_imovel",
    "operacoes_n",
    "vencimento_max",
    "emissao_ultima",
    "area_financiada_ha",
    "area_financiada_ativa_ha",
    "finalidades",
    "floresta",
    "floresta_vencimento_max",
]
COLUNAS_GLEBAS = ["emissao", "vencimento", "finalidade", "floresta", "geometry"]
COLUNAS_IBGE = ["cd_lq", "cod_ibge", "uf", "territorio_oficial", "certificada_fcp", "geometry"]
COLUNAS_PALMARES = ["cod_ibge", "uf", "certificadas_n", "certificadas_sem_titulo_n", "ultima_certificacao"]
COLUNAS_IMPORTADAS = ["fonte", "objeto_id", "categoria", "situacao", "ano_inicio", "area_ha", "geometry"]
log = logging.getLogger(__name__)


# --- utilidades --------------------------------------------------------------------------------------------------


def _sem_acento(s) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()


def _data(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie, format="%d/%m/%Y", errors="coerce")


def _numero(serie: pd.Series) -> pd.Series:
    return pd.to_numeric(serie.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def normalizar_car(v) -> str | None:
    """Código do CAR como o funil grava (UF-IBGE-HASH, maiúsculas). O SICOR grava sem hífens; -1 e lixo viram None."""
    if not isinstance(v, str):
        return None
    s = re.sub(r"[^0-9A-Z]", "", v.upper())
    m = re.fullmatch(r"([A-Z]{2})(\d{7})([0-9A-F]{32})", s)
    return f"{m[1]}-{m[2]}-{m[3]}" if m else None


def _no_brasil(g) -> bool:
    if g is None or g.is_empty:
        return False
    x0, y0, x1, y1 = g.bounds
    return BBOX_BRASIL[0] <= x0 and x1 <= BBOX_BRASIL[2] and BBOX_BRASIL[1] <= y0 and y1 <= BBOX_BRASIL[3]


def _baixar(s, url: str, destino: Path, timeout: int = 3600) -> Path:
    with s.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with destino.open("wb") as w:
            for b in r.iter_content(1 << 20):
                w.write(b)
    # o BCB responde 200 com uma página "Requisição inválida!" quando recusa: não é gzip, é falha da fonte
    with destino.open("rb") as f:
        inicio = f.read(2)
    if destino.suffix == ".gz" and inicio != b"\x1f\x8b":
        raise OSError(f"{url.rsplit('/', 1)[-1]}: resposta não é gzip")
    return destino


# --- SICOR -------------------------------------------------------------------------------------------------------


def _abrir(arquivo):
    """Caminho (.gz detectado pelo nome) ou arquivo em memória (gzip detectado pelos primeiros bytes)."""
    if hasattr(arquivo, "read"):
        inicio = arquivo.read(2)
        arquivo.seek(0)
        if inicio == b"\x1f\x8b":
            return gzip.GzipFile(fileobj=arquivo)
    return arquivo


def ler_empreendimentos(arquivo) -> pd.DataFrame:
    """Tabela de empreendimentos do SICOR: código → finalidade e se é floresta/recuperação."""
    e = pd.read_csv(arquivo, sep=";", dtype=str, encoding="latin1")
    e.columns = [c.lstrip("#").strip().upper() for c in e.columns]
    texto = (e.get("MODALIDADE", "").fillna("") + " " + e.get("PRODUTO", "").fillna("")).map(_sem_acento)
    return pd.DataFrame(
        {
            "cd_empreendimento": e.CODIGO.str.strip(),
            "finalidade": e.FINALIDADE.fillna("").str.strip(),
            "floresta": texto.str.contains(FLORESTA),
        }
    ).drop_duplicates("cd_empreendimento")


def ler_operacoes(arquivo, empreendimentos: pd.DataFrame | None = None, pedaco: int = 500_000) -> pd.DataFrame:
    """Operações de um arquivo SICOR_OPERACAO_BASICA_ESTADO_<ano>: chave, UF, datas, finalidade e área financiada.
    Não lê CNPJ da instituição, valores, juros nem qualquer documento."""
    cols = ["#REF_BACEN", "NU_ORDEM", "DT_EMISSAO", "DT_VENCIMENTO", "CD_ESTADO", "CD_EMPREENDIMENTO", "VL_AREA_FINANC"]
    partes = []
    for p in pd.read_csv(
        _abrir(arquivo),
        sep=";",
        dtype=str,
        usecols=lambda c: c in cols,
        chunksize=pedaco,
        encoding="latin1",
        on_bad_lines="skip",
    ):
        partes.append(
            pd.DataFrame(
                {
                    "ref": pd.to_numeric(p["#REF_BACEN"], errors="coerce"),
                    "ordem": pd.to_numeric(p.NU_ORDEM, errors="coerce"),
                    "uf": p.CD_ESTADO.str.strip().str.upper(),
                    "emissao": _data(p.DT_EMISSAO),
                    "vencimento": _data(p.DT_VENCIMENTO),
                    "cd_empreendimento": p.CD_EMPREENDIMENTO.str.strip(),
                    "area_ha": _numero(p.VL_AREA_FINANC),
                }
            )
        )
    op = pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["ref", "ordem"])
    op = op.dropna(subset=["ref", "ordem"])
    op["ref"], op["ordem"] = op.ref.astype("int64"), op.ordem.astype("int32")
    if empreendimentos is not None and len(op):
        op = op.merge(empreendimentos, on="cd_empreendimento", how="left")
    else:
        op["finalidade"], op["floresta"] = None, False
    op["floresta"] = op.floresta.fillna(False).astype(bool)
    return op.drop(columns="cd_empreendimento")


def chave(ref, ordem) -> np.ndarray:
    """Chave única da operação (REF_BACEN, NU_ORDEM) num int64: comparar milhões de chaves fica barato."""
    return np.asarray(ref, dtype="int64") * 1000 + np.asarray(ordem, dtype="int64")


def ler_propriedades(arquivo, chaves: np.ndarray | None = None, pedaco: int = 1_000_000) -> pd.DataFrame:
    """Vínculo operação → CAR. A coluna CD_CNPJ_CPF (documento do tomador) não é lida: usecols a deixa de fora.
    `chaves` (de `chave()`) limita às operações lidas."""
    cols = ["#REF_BACEN", "NU_ORDEM", "CD_CAR"]
    partes = []
    for p in pd.read_csv(
        _abrir(arquivo),
        sep=";",
        dtype=str,
        usecols=lambda c: c in cols,
        chunksize=pedaco,
        encoding="latin1",
        on_bad_lines="skip",
    ):
        assert "CD_CNPJ_CPF" not in p.columns
        p = p[p.CD_CAR.str.len().fillna(0) > 30]  # -1 = sem CAR (a maioria das operações antigas)
        car = p.CD_CAR.map(normalizar_car)
        p = p[car.notna()]
        if not len(p):
            continue
        d = pd.DataFrame(
            {
                "ref": pd.to_numeric(p["#REF_BACEN"], errors="coerce"),
                "ordem": pd.to_numeric(p.NU_ORDEM, errors="coerce"),
                "cod_imovel": car[car.notna()],
            }
        )
        d = d.dropna(subset=["ref", "ordem"])
        d["ref"], d["ordem"] = d.ref.astype("int64"), d.ordem.astype("int32")
        if chaves is not None:
            d = d[np.isin(chave(d.ref, d.ordem), chaves)]
        partes.append(d)
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame(columns=["ref", "ordem", "cod_imovel"])


def sicor_por_car(op: pd.DataFrame, prop: pd.DataFrame, hoje: str) -> pd.DataFrame:
    """Uma linha por CAR com as operações ligadas a ele (sem valor em reais nem documento)."""
    if not len(prop) or not len(op):
        return pd.DataFrame(columns=COLUNAS_SICOR_CAR)
    t = prop.merge(op, on=["ref", "ordem"], how="inner")
    if not len(t):
        return pd.DataFrame(columns=COLUNAS_SICOR_CAR)
    h = pd.Timestamp(hoje)
    t["ativa"] = t.vencimento >= h
    t["area_ativa"] = t.area_ha.where(t.ativa, 0.0)
    t["venc_floresta"] = t.vencimento.where(t.floresta)
    g = t.groupby("cod_imovel")
    out = pd.DataFrame(
        {
            "operacoes_n": g.size(),
            "vencimento_max": g.vencimento.max().dt.strftime("%Y-%m-%d"),
            "emissao_ultima": g.emissao.max().dt.strftime("%Y-%m-%d"),
            "area_financiada_ha": g.area_ha.sum().round(2),
            "area_financiada_ativa_ha": g.area_ativa.sum().round(2),
            "finalidades": g.finalidade.agg(lambda s: "|".join(sorted({x for x in s.dropna() if x})) or None),
            "floresta": g.floresta.any(),
            "floresta_vencimento_max": g.venc_floresta.max().dt.strftime("%Y-%m-%d"),
        }
    ).reset_index()
    return out[COLUNAS_SICOR_CAR]


def ler_glebas(
    arquivo, op: pd.DataFrame, hoje: str, anos: int = ANOS_GLEBAS, pedaco: int = 200_000, simplificar: float = 0.00005
) -> dict[str, gpd.GeoDataFrame]:
    """Glebas das operações recentes (emitidas nos últimos `anos`) ou ainda ativas, por UF. Uma linha por operação
    (as partes da gleba unidas), geometria simplificada em ~5 m. Sem chave da operação na saída."""
    h = pd.Timestamp(hoje)
    corte = h - pd.DateOffset(years=anos)
    alvo = op[(op.emissao >= corte) | (op.vencimento >= h)].copy()
    alvo.index = chave(alvo.ref, alvo.ordem)
    alvo = alvo[~alvo.index.duplicated()]
    por_uf: dict[str, list] = {}
    for p in pd.read_csv(_abrir(arquivo), sep=";", dtype=str, chunksize=pedaco, encoding="latin1", on_bad_lines="skip"):
        p.columns = [c.lstrip("#").strip().upper() for c in p.columns]
        k = chave(
            pd.to_numeric(p.REF_BACEN, errors="coerce").fillna(-1), pd.to_numeric(p.NU_ORDEM, errors="coerce").fillna(0)
        )
        dentro = np.isin(k, alvo.index.values)
        if not dentro.any():
            continue
        p, k = p[dentro], k[dentro]
        geo = shapely.from_wkt(p.GT_GEOMETRIA.values, on_invalid="ignore")
        geo = shapely.force_2d(geo)
        ok = ~shapely.is_missing(geo)
        d = alvo.loc[k[ok]].reset_index(drop=True)
        d["geometry"] = geo[ok]
        # a maioria das glebas tem uma parte só: caminho vetorizado; as de várias partes são unidas por operação
        dup = d.duplicated(["ref", "ordem"], keep=False).values
        unidas = [
            (grupo.iloc[:1].drop(columns="geometry"), shapely.union_all(grupo.geometry.values))
            for _, grupo in d[dup].groupby(["ref", "ordem"], sort=False)
        ]
        partes = [d[~dup]]
        if unidas:
            m = pd.concat([u[0] for u in unidas], ignore_index=True)
            m["geometry"] = [u[1] for u in unidas]
            partes.append(m)
        d = pd.concat(partes, ignore_index=True)
        g = shapely.make_valid(d.geometry.values)
        if simplificar:
            g = shapely.simplify(g, simplificar, preserve_topology=True)
        tipo = shapely.get_type_id(g)
        outros = ~np.isin(tipo, (3, 6))  # nem Polygon nem MultiPolygon: fica só a parte com área
        if outros.any():
            g[outros] = [_so_poligonos(x) for x in g[outros]]
        x0, y0, x1, y1 = shapely.bounds(g).T if len(g) else (np.array([]),) * 4
        no_br = (
            ~shapely.is_missing(g)
            & (x0 >= BBOX_BRASIL[0])
            & (x1 <= BBOX_BRASIL[2])
            & (y0 >= BBOX_BRASIL[1])
            & (y1 <= BBOX_BRASIL[3])
        )
        d, g = d[no_br], g[no_br]
        out = pd.DataFrame(
            {
                "uf": d.uf.values,
                "emissao": d.emissao.dt.strftime("%Y-%m-%d").values,
                "vencimento": d.vencimento.dt.strftime("%Y-%m-%d").values,
                "finalidade": d.finalidade.values,
                "floresta": d.floresta.astype(bool).values,
                "geometry": g,
            }
        )
        for uf, grupo in out.groupby("uf"):
            por_uf.setdefault(uf, []).append(grupo.drop(columns="uf"))
    return {
        uf: gpd.GeoDataFrame(pd.concat(linhas, ignore_index=True)[COLUNAS_GLEBAS], geometry="geometry", crs=4674)
        for uf, linhas in por_uf.items()
        if uf in UFS
    }


def coletar_sicor(
    s, saida: Path, hoje: str, anos_operacoes: int = ANOS_OPERACOES, anos_glebas: int = ANOS_GLEBAS, ufs=UFS
) -> dict:
    ano = int(hoje[:4])
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        emp = ler_empreendimentos(_baixar(s, URL_SICOR_EMPREENDIMENTO, d / "emp.csv"))
        ops, anos_ok, anos_falha = [], [], []
        for a in range(ano - anos_operacoes + 1, ano + 1):
            nome = f"SICOR_OPERACAO_BASICA_ESTADO_{a}.gz"
            try:
                f = _baixar(s, URL_SICOR.format(arquivo=nome), d / nome)
                ops.append(ler_operacoes(f, emp))
                f.unlink()
                anos_ok.append(a)
            except Exception as ex:  # noqa: BLE001 - ano que falta (o do ano corrente sai em janeiro) não para tudo
                log.warning("SICOR operações %s indisponível (%s)", a, type(ex).__name__)
                anos_falha.append(a)
        if not ops:
            raise RuntimeError("nenhum arquivo de operações do SICOR")
        op = pd.concat(ops, ignore_index=True)
        op = op[op.uf.isin(ufs)]
        chaves = chave(op.ref, op.ordem)
        f = _baixar(s, URL_SICOR.format(arquivo="SICOR_PROPRIEDADES.gz"), d / "prop.gz")
        prop = ler_propriedades(f, chaves)
        f.unlink()
        por_car = sicor_por_car(op, prop, hoje)
        por_car.to_parquet(saida / NOMES["sicor_car"], index=False)
        glebas: dict[str, list] = {}
        glebas_falha = []
        for a in range(ano - anos_glebas, ano + 1):
            nome = f"SICOR_GLEBAS_WKT_{a}.gz"
            try:
                f = _baixar(s, URL_SICOR.format(arquivo=nome), d / nome)
                for uf, g in ler_glebas(f, op, hoje, anos_glebas).items():
                    glebas.setdefault(uf, []).append(g)
                f.unlink()
            except Exception as ex:  # noqa: BLE001
                log.warning("SICOR glebas %s indisponível (%s)", a, type(ex).__name__)
                glebas_falha.append(a)
        n_glebas = 0
        for uf, partes in glebas.items():
            g = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=4674)
            g.to_parquet(saida / GLEBAS.format(uf=uf))
            n_glebas += len(g)
    estado = "consultado" if not anos_falha[1:] and not glebas_falha[1:] else "parcial"
    return {
        "estado": estado,
        "url": URL_SICOR.format(arquivo=""),
        "licenca": "ODbL (dados abertos do BCB)",
        "anos_operacoes": anos_ok,
        "anos_falharam": anos_falha + glebas_falha,
        "operacoes": int(len(op)),
        "car_vinculados": int(len(por_car)),
        "glebas": n_glebas,
        "ufs": sorted(glebas),
    }


# --- quilombos ---------------------------------------------------------------------------------------------------


def ler_ibge_quilombolas(arquivo) -> gpd.GeoDataFrame:
    """Localidades quilombolas do Censo 2022: ponto, município, território oficial e certificação na FCP."""
    d = pd.read_csv(arquivo, sep=";", dtype=str, encoding="utf-8-sig")
    d.columns = [c.strip().upper() for c in d.columns]
    lat, lon = _numero(d.LAT_D), _numero(d.LONG_D)
    ok = lat.notna() & lon.notna()
    d, lat, lon = d[ok], lat[ok], lon[ok]
    g = gpd.GeoDataFrame(
        {
            "cd_lq": d.CD_LQ.str.strip(),
            "cod_ibge": pd.to_numeric(d.CD_MUNIC, errors="coerce").astype("Int64"),
            "uf": d.SG_UF.str.strip(),
            "territorio_oficial": d.CD_TQ.fillna("").str.strip().ne(""),
            "certificada_fcp": d.P_FCP.fillna("").str.strip().ne(""),
        },
        geometry=gpd.points_from_xy(lon, lat),
        crs=4674,
    )
    g = g[[_no_brasil(x) for x in g.geometry]]
    return g.drop_duplicates("cd_lq").reset_index(drop=True)[COLUNAS_IBGE]


_TITULADA = re.compile(r"TITULAD[OA]|^TITULACAO TOTAL")


def ler_palmares(arquivo) -> pd.DataFrame:
    """Planilha da FCP → contagem por município (comunidade em mais de um município conta em cada um)."""
    d = pd.read_csv(arquivo, dtype=str)
    d.columns = [_sem_acento(c).replace("\n", " ") for c in d.columns]
    cod = next(c for c in d.columns if c.startswith("CODIGO DO IBGE"))
    etapa = next((c for c in d.columns if c.startswith("ETAPA")), None)
    ano = next((c for c in d.columns if c.startswith("ANO CERTIFICACAO")), None)
    uf = next(c for c in d.columns if c.strip() == "UF")
    linhas = []
    for _, r in d.iterrows():
        titulada = bool(_TITULADA.search(_sem_acento(r.get(etapa) or ""))) if etapa else False
        a = pd.to_numeric(r.get(ano), errors="coerce") if ano else None
        for c in re.split(r"[|;,/ ]+", str(r.get(cod) or "")):
            if re.fullmatch(r"\d{7}", c):
                linhas.append((int(c), str(r.get(uf) or "").strip(), titulada, a))
    t = pd.DataFrame(linhas, columns=["cod_ibge", "uf", "titulada", "ano"])
    if not len(t):
        return pd.DataFrame(columns=COLUNAS_PALMARES)
    g = t.groupby("cod_ibge")
    out = pd.DataFrame(
        {
            "uf": g.uf.first(),
            "certificadas_n": g.size(),
            "certificadas_sem_titulo_n": g.titulada.agg(lambda s: int((~s).sum())),
            "ultima_certificacao": g.ano.max().astype("Int64"),
        }
    ).reset_index()
    return out[COLUNAS_PALMARES]


# --- importação (fontes com autorização) -------------------------------------------------------------------------

# nomes de coluna aceitos para cada campo (o arquivo recebido pode vir de versões diferentes)
_CAMPOS = {
    "objeto_id": ("id", "fid", "objectid", "codigo", "cod", "id_territorio", "id_iniciativa", "site_id", "uuid"),
    "categoria": ("categoria", "tipo", "segmento", "tipo_restauracao", "metodo", "modalidade", "type", "category"),
    "situacao": ("situacao", "status", "validacao", "estado", "fase"),
    "ano_inicio": ("ano_inicio", "ano", "inicio", "start_year", "data_inicio", "ano_implantacao", "year"),
}


def _so_poligonos(g):
    if g is None or g.is_empty:
        return None
    partes = [p for p in shapely.get_parts(g) if p.geom_type == "Polygon"]
    return shapely.union_all(partes) if partes else None


def _campo(cols_norm: dict[str, str], nomes) -> str | None:
    for n in nomes:
        if n in cols_norm:
            return cols_norm[n]
    return None


def ler_importada(arquivo: str | Path, fonte: str) -> gpd.GeoDataFrame:
    """Shapefile (zip), GeoPackage, GeoJSON ou KML recebido com autorização → só id, categoria, situação, ano,
    área e polígono. Nenhuma outra coluna é copiada (responsáveis, e-mails e telefones ficam de fora)."""
    if fonte not in FONTES_IMPORTADAS:
        raise ValueError(f"fonte sem importação: {fonte}")
    arquivo = Path(arquivo)
    g = gpd.read_file(f"zip://{arquivo}" if arquivo.suffix.lower() == ".zip" else arquivo)
    g = g.set_crs(4674) if g.crs is None else g.to_crs(4674)
    norm = {re.sub(r"[^a-z0-9]+", "_", _sem_acento(c).lower()).strip("_"): c for c in g.columns if c != "geometry"}
    out = pd.DataFrame(index=g.index)
    for campo, nomes in _CAMPOS.items():
        c = _campo(norm, nomes)
        out[campo] = g[c].astype(str).str.strip() if c else None
    if out.objeto_id.isna().all():
        out["objeto_id"] = [f"{fonte}-{i + 1}" for i in range(len(g))]
    out["ano_inicio"] = pd.to_numeric(out.ano_inicio.astype(str).str.extract(r"((?:19|20)\d{2})")[0], errors="coerce")
    geo = shapely.make_valid(shapely.force_2d(g.geometry.values))
    geo = [_so_poligonos(x) for x in geo]
    out["fonte"] = fonte
    r = gpd.GeoDataFrame(out, geometry=list(geo), crs=4674)
    r = r[r.geometry.notna() & ~r.geometry.is_empty]
    r = r[[_no_brasil(x) for x in r.geometry]]
    r["area_ha"] = (r.to_crs(5880).area / 1e4).round(2)
    return r.reset_index(drop=True)[COLUNAS_IMPORTADAS]


def importar(
    arquivo: str | Path,
    fonte: str,
    saida: str | Path,
    autorizacao: str,
    licenca: str | None = None,
    hoje: str | None = None,
) -> dict:
    """Converte o arquivo recebido e grava a camada e o meta (quem autorizou, quando, licença). Sem autorização
    escrita a importação não acontece."""
    if not autorizacao or len(autorizacao.strip()) < 10:
        raise ValueError("descreva a autorização (quem, quando e por qual meio) para importar esta fonte")
    hoje = hoje or dt.date.today().isoformat()
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    g = ler_importada(arquivo, fonte)
    g.to_parquet(saida / NOMES[fonte])
    meta = {
        "fonte": fonte,
        "estado": "consultado",
        "importado_em": hoje,
        "n": int(len(g)),
        "area_ha": float(g.area_ha.sum()),
        "autorizacao": autorizacao.strip(),
        "licenca": licenca,
        "versao": VERSAO,
    }
    (saida / META_IMPORTADA.format(fonte=fonte)).write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    return meta


# --- orquestração ------------------------------------------------------------------------------------------------


PENDENTE = {
    "mpf_territorios": "acesso decidido pelo Conselho Gestor da Plataforma de Territórios Tradicionais (MPF/CNPCT); "
    "pedir a 6ccr-plataformaterritorios@mpf.mp.br e importar com `raiz complementares importar`",
    "observatorio": "shapefile do Observatório da Restauração pedido por e-mail à Coalizão Brasil; quando chegar, "
    "importar com `raiz complementares importar --fonte observatorio`",
    "restor": "termos de uso da Restor proíbem copiar os dados sem permissão (API só no plano Enterprise); importar só "
    "com autorização escrita",
}


def coletar(saida: str | Path, fontes=FONTES, ufs=UFS, s=None, hoje: str | None = None) -> dict:
    """Coleta as fontes abertas pedidas e grava a pasta de saída. As importadas entram pelo meta já existente na
    pasta (o workflow baixa o Release antes) ou ficam "indisponivel" com o que falta fazer."""
    from raiz.coleta.http import sessao

    s = s or sessao()
    hoje = hoje or dt.date.today().isoformat()
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    cob: dict[str, dict] = {}

    if "sicor" in fontes:
        try:
            cob["sicor"] = coletar_sicor(s, saida, hoje, ufs=ufs)
        except Exception as ex:  # noqa: BLE001
            cob["sicor"] = {"estado": "indisponivel", "url": URL_SICOR.format(arquivo=""), "erro": type(ex).__name__}

    if "ibge_quilombolas" in fontes:
        try:
            r = s.get(URL_IBGE_QUILOMBOLAS, timeout=300)
            r.raise_for_status()
            g = ler_ibge_quilombolas(io.BytesIO(r.content))
            if not len(g):
                raise ValueError("arquivo sem localidades")
            g.to_parquet(saida / NOMES["ibge_quilombolas"])
            cob["ibge_quilombolas"] = {
                "estado": "consultado",
                "url": URL_IBGE_QUILOMBOLAS,
                "n": int(len(g)),
                "fora_de_territorio": int((~g.territorio_oficial).sum()),
                "licenca": "IBGE, uso livre com citação da fonte",
            }
        except Exception as ex:  # noqa: BLE001
            cob["ibge_quilombolas"] = {"estado": "indisponivel", "url": URL_IBGE_QUILOMBOLAS, "erro": type(ex).__name__}

    if "palmares" in fontes:
        try:
            r = s.get(URL_PALMARES, timeout=300)
            r.raise_for_status()
            p = ler_palmares(io.StringIO(r.content.decode("utf-8-sig")))
            if not len(p):
                raise ValueError("planilha sem comunidades")
            p.to_csv(saida / NOMES["palmares"], index=False)
            cob["palmares"] = {
                "estado": "consultado",
                "url": URL_PALMARES,
                "municipios": int(len(p)),
                "certificadas": int(p.certificadas_n.sum()),
                "sem_titulo": int(p.certificadas_sem_titulo_n.sum()),
            }
        except Exception as ex:  # noqa: BLE001
            cob["palmares"] = {"estado": "indisponivel", "url": URL_PALMARES, "erro": type(ex).__name__}

    for fonte in FONTES_IMPORTADAS:
        if fonte not in fontes:
            continue
        m = saida / META_IMPORTADA.format(fonte=fonte)
        if m.exists() and (saida / NOMES[fonte]).exists():
            meta = json.loads(m.read_text(encoding="utf-8"))
            cob[fonte] = {k: meta.get(k) for k in ("estado", "importado_em", "n", "licenca")}
            cob[fonte]["consultado_em"] = meta.get("importado_em")
        else:
            cob[fonte] = {"estado": "indisponivel", "pendente": PENDENTE[fonte]}

    for f in cob.values():
        f.setdefault("consultado_em", hoje)
    manifesto = {"versao": VERSAO, "coletado_em": hoje, "fontes": cob}
    (saida / NOMES["cobertura"]).write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifesto


def conferir_sem_documento(pasta: str | Path) -> list:
    """Guarda antes de publicar: procura CPF ou CNPJ em todo arquivo da coleta (parquet lido sem a geometria)."""
    from raiz.privacidade import varrer_texto

    achados = []
    for f in sorted(Path(pasta).glob("complementares_*")):
        if f.suffix == ".parquet":
            texto = pd.read_parquet(f).drop(columns="geometry", errors="ignore").to_csv(index=False)
        else:
            texto = f.read_text(encoding="utf-8", errors="ignore")
        achados += varrer_texto(texto, f.name)
    return achados


def ler_gz_parcial(caminho: str | Path, bytes_max: int) -> io.StringIO:
    """Para testes e conferência: os primeiros bytes de um .gz do SICOR, sem a última linha (que fica cortada)."""
    with gzip.open(caminho, "rt", encoding="latin1") as f:
        try:
            texto = f.read(bytes_max)
        except EOFError:
            texto = ""
    return io.StringIO(texto[: texto.rfind("\n") + 1])
