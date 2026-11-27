"""Coleta das fontes nacionais de restrição, sem download manual e sem dado pessoal na saída.

Fontes:
  sigmine      processos minerários da ANM (SIGMINE, shapefile por UF no portal de dados abertos da ANM; reserva: o
               serviço ArcGIS do SIGMINE). Sai o titular (NOME); ficam processo, fase, substância, uso, UF e polígono.
  ibama_autos  autos de infração do Ibama (dados abertos do SIFISC, um CSV por ano). Ficam só os não cancelados desde
               2008, com o polígono da área autuada quando existe e, senão, o ponto do auto. Saem nome e CPF/CNPJ.
  lista_suja   Cadastro de Empregadores que submeteram trabalhadores a condições análogas à escravidão (MTE, PDF
               público). O documento de cada empregador é comparado, só em memória, com os documentos dos autos e
               embargos do Ibama: o que sai é o polígono ou ponto do auto/embargo do infrator listado (um vínculo
               geográfico) e a contagem por município. Nunca nome, CPF, CNPJ ou endereço.
  car_temas    reserva legal e APP declaradas no CAR (shapefiles da base de downloads do SICAR). A base fica atrás
               de captcha e o pedido de LAI 02303.031114/2026-60 ao SFB pede a coleta automática: até lá a fonte
               fica "indisponivel" e status.py marca a parte RL/APP como não verificada. converter_car_temas() já
               lê os shapefiles quando a fonte abrir.
Saída (pasta que o workflow publica no Release "insumos"; status.py lê de RAIZ_RESTRICOES_DIR ou cache/restricoes):
  restricoes_sigmine.parquet, restricoes_ibama_autos.parquet, restricoes_lista_suja_vinculos.parquet,
  restricoes_lista_suja_municipios.csv e restricoes_cobertura.json (estado de cada fonte, data, contagens).
Uma fonte que falha vira "indisponivel": quem consome nunca lê isso como terra livre.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import tempfile
import unicodedata
import zipfile
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

VERSAO = "restricoes-coleta-2026a"
FONTES = ("sigmine", "ibama_autos", "lista_suja", "car_temas")
NOMES = {
    "sigmine": "restricoes_sigmine.parquet",
    "ibama_autos": "restricoes_ibama_autos.parquet",
    "lista_suja_vinculos": "restricoes_lista_suja_vinculos.parquet",
    "lista_suja_municipios": "restricoes_lista_suja_municipios.csv",
    "cobertura": "restricoes_cobertura.json",
}
URL_SIGMINE_UF = "https://app.anm.gov.br/dadosabertos/SIGMINE/PROCESSOS_MINERARIOS/{uf}.zip"
URL_SIGMINE_ARCGIS = "https://geo.anm.gov.br/arcgis/rest/services/SIGMINE/dados_anm/MapServer/0/query"
URL_IBAMA_AUTOS = "https://dadosabertos.ibama.gov.br/dados/SIFISC/auto_infracao/auto_infracao/auto_infracao_csv.zip"
URL_IBAMA_EMBARGOS = (
    "https://stibamadadosabertosprd.blob.core.windows.net/dados-abertos/dados/TERMOS_DE_EMBARGO/"
    "TERMO_EMBARGO/termo_de_embargo.csv"
)
URL_LISTA_SUJA = (
    "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/"
    "cadastro_de_empregadores.pdf"
)
UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
BBOX_BRASIL = (-74.5, -34.5, -28.5, 5.6)
COLUNAS_SIGMINE = ["processo", "fase", "substancia", "uso", "uf", "area_ha", "ultimo_evento", "geometry"]
COLUNAS_AUTOS = ["auto_id", "ano", "data", "tipo_infracao", "gravidade", "cod_municipio", "uf", "geometria_tipo",
                 "lista_suja", "geometry"]  # fmt: skip
COLUNAS_VINCULOS = ["fonte", "objeto_id", "ano", "geometry"]
log = logging.getLogger(__name__)


# --- utilidades --------------------------------------------------------------------------------------------------


def normalizar_nome(s: str) -> str:
    """Maiúsculas sem acento e sem pontuação (para casar nome de município)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def chave_documento(doc) -> str | None:
    """Chave de comparação, só em memória: CPF inteiro (11) ou a raiz do CNPJ (8 primeiros, pega as filiais)."""
    if not isinstance(doc, str):
        return None
    s = re.sub(r"[^0-9A-Z]", "", doc.upper())
    if len(s) == 11 and s.isdigit():
        return "F" + s
    if len(s) == 14:
        return "J" + s[:8]
    return None


@lru_cache(maxsize=1)
def _municipios() -> pd.DataFrame:
    from raiz.executor.tarefas import COD_UF, LISTA

    m = pd.read_csv(LISTA, dtype={"codigo_ibge": int})
    uf_de = {v: k for k, v in COD_UF.items()}
    m["uf"] = m.codigo_uf.map(uf_de)
    m["chave"] = m.nome.map(normalizar_nome)
    return m[["codigo_ibge", "uf", "chave"]]


def municipio_do_texto(texto: str, uf: str) -> int | None:
    """Código IBGE do município cujo nome encerra o texto (o endereço do estabelecimento termina em 'CIDADE/UF')."""
    t = normalizar_nome(texto)
    cands = _municipios()
    cands = cands[cands.uf == uf]
    melhor = None
    for cod, chave in zip(cands.codigo_ibge, cands.chave, strict=True):
        if chave and (t == chave or t.endswith(" " + chave)) and (melhor is None or len(chave) > len(melhor[1])):
            melhor = (int(cod), chave)
    return melhor[0] if melhor else None


def _no_brasil(g) -> bool:
    if g is None or g.is_empty:
        return False
    x0, y0, x1, y1 = g.bounds
    return BBOX_BRASIL[0] <= x0 and x1 <= BBOX_BRASIL[2] and BBOX_BRASIL[1] <= y0 and y1 <= BBOX_BRASIL[3]


def _wkt(v):
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        g = shapely.from_wkt(v)
    except shapely.errors.GEOSException:
        return None
    if g is None or g.is_empty:
        return None
    g = shapely.make_valid(g)
    return g if _no_brasil(g) else None


def _numero(v) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


# --- SIGMINE -----------------------------------------------------------------------------------------------------


def normalizar_sigmine(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Colunas do shapefile da ANM (PROCESSO, FASE, SUBS, USO, UF, AREA_HA, ULT_EVENTO) sem o titular (NOME)."""
    cols = {c.upper(): c for c in g.columns}

    def col(nome):
        c = cols.get(nome)
        return g[c] if c is not None else pd.Series([None] * len(g), index=g.index)

    g = g.set_crs(4674) if g.crs is None else g
    out = gpd.GeoDataFrame(
        {
            "processo": col("PROCESSO").astype("string"),
            "fase": col("FASE").map(lambda v: str(v).strip().upper() if isinstance(v, str) else None),
            "substancia": col("SUBS").astype("string"),
            "uso": col("USO").astype("string"),
            "uf": col("UF").astype("string"),
            "area_ha": col("AREA_HA").map(_numero),
            "ultimo_evento": col("ULT_EVENTO").map(
                lambda v: re.sub(r"\s+", " ", str(v))[:160] if isinstance(v, str) else None
            ),
        },
        geometry=g.geometry.values,
        crs=g.crs,
    ).to_crs(4674)
    out = out[out.geometry.notna() & ~out.geometry.is_empty].copy()
    out["geometry"] = shapely.make_valid(out.geometry.values)
    return out[COLUNAS_SIGMINE].reset_index(drop=True)


def _erro_de_conexao(ex: Exception) -> bool:
    """Falha do servidor ou da rede (recusa, reset, certificado), não de uma UF: as outras UFs vão falhar igual."""
    import requests

    return isinstance(ex, requests.exceptions.ConnectionError | requests.exceptions.SSLError)


def cadeia_com_intermediario(url: str, pasta: Path) -> str | None:
    """Pacote de CAs (certifi + certificado intermediário que o servidor deixou de mandar) para verificar o TLS.

    O geo.anm.gov.br manda só o certificado final, sem o intermediário ("unable to get local issuer certificate").
    O navegador completa a cadeia pelo endereço do emissor gravado no próprio certificado (AIA, caIssuers); aqui é o
    mesmo: o intermediário é baixado desse endereço e a verificação continua ligada, contra as raízes do certifi.
    Devolve o caminho do pacote, ou None se não houver o que completar.
    """
    import socket
    import ssl
    from urllib.parse import urlsplit

    import certifi
    import requests
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    host = urlsplit(url).hostname
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE  # só para LER o certificado; nada é enviado
    with socket.create_connection((host, 443), timeout=30) as sock, ctx.wrap_socket(sock, server_hostname=host) as t:
        folha = x509.load_der_x509_certificate(t.getpeercert(binary_form=True))
    try:
        aia = folha.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
    except x509.ExtensionNotFound:
        return None
    pems = []
    for d in aia:
        if d.access_method != AuthorityInformationAccessOID.CA_ISSUERS:
            continue
        r = requests.get(d.access_location.value, timeout=60)
        r.raise_for_status()
        try:
            certs = [x509.load_der_x509_certificate(r.content)]
        except ValueError:
            certs = x509.load_pem_x509_certificates(r.content)
        pems += [c.public_bytes(Encoding.PEM) for c in certs]
    if not pems:
        return None
    pasta.mkdir(parents=True, exist_ok=True)
    pacote = pasta / f"ca_{host}.pem"
    pacote.write_bytes(Path(certifi.where()).read_bytes() + b"\n" + b"".join(pems))
    return str(pacote)


def baixar_sigmine(s, ufs=UFS, *, pasta_tmp: Path | None = None) -> tuple[gpd.GeoDataFrame, dict]:
    """Shapefile por UF do portal da ANM; a UF que falhar tenta o serviço ArcGIS. Devolve (camada, cobertura).

    Servidor que cai por conexão (reset, recusa, certificado) em duas UFs seguidas é dado como fora para as demais:
    sem isso, 27 UFs x 2 servidores x 5 tentativas levavam 85 minutos para dizer "indisponível". Certificado sem o
    intermediário no ArcGIS da ANM é completado pelo AIA (cadeia_com_intermediario), com verificação ligada."""
    partes, ok, falhas = [], [], []
    erros = {"portal": 0, "arcgis": 0}
    verificar = None  # pacote de CAs do ArcGIS, quando a cadeia precisar ser completada
    for uf in ufs:
        if erros["portal"] < 2:
            try:
                r = s.get(URL_SIGMINE_UF.format(uf=uf), timeout=900)
                r.raise_for_status()
                with tempfile.TemporaryDirectory(dir=pasta_tmp) as d:
                    f = Path(d) / f"{uf}.zip"
                    f.write_bytes(r.content)
                    partes.append(normalizar_sigmine(gpd.read_file(f"zip://{f}")))
                ok.append(uf)
                erros["portal"] = 0
                continue
            except Exception as ex:  # noqa: BLE001 - qualquer falha da fonte vira reserva/indisponível
                erros["portal"] += _erro_de_conexao(ex)
                log.warning("SIGMINE %s pelo portal falhou (%s); tentando o ArcGIS", uf, type(ex).__name__)
        if erros["arcgis"] >= 2:
            falhas.append(uf)
            continue
        try:
            try:
                partes.append(_sigmine_arcgis(s, uf, verificar=verificar))
            except Exception as ex:  # noqa: BLE001
                if verificar is not None or "CERTIFICATE_VERIFY_FAILED" not in str(ex):
                    raise
                verificar = cadeia_com_intermediario(URL_SIGMINE_ARCGIS, Path(pasta_tmp or tempfile.gettempdir()))
                if verificar is None:
                    raise
                log.warning("SIGMINE: cadeia do certificado do ArcGIS completada pelo AIA")
                partes.append(_sigmine_arcgis(s, uf, verificar=verificar))
            ok.append(uf)
            erros["arcgis"] = 0
        except Exception as ex:  # noqa: BLE001
            erros["arcgis"] += _erro_de_conexao(ex)
            log.warning("SIGMINE %s indisponível (%s)", uf, type(ex).__name__)
            falhas.append(uf)
    g = (
        gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=4674)
        if partes
        else gpd.GeoDataFrame(columns=COLUNAS_SIGMINE, geometry="geometry", crs=4674)
    )
    estado = "consultado" if ok and not falhas else ("parcial" if ok else "indisponivel")
    return g, {"estado": estado, "ufs": ok, "ufs_falharam": falhas, "n": int(len(g)), "url": URL_SIGMINE_UF}


def _sigmine_arcgis(s, uf: str, pagina: int = 1000, verificar: str | None = None) -> gpd.GeoDataFrame:
    partes, inicio = [], 0
    while True:
        r = s.get(
            URL_SIGMINE_ARCGIS,
            params={
                "where": f"UF='{uf}'",
                "outFields": "PROCESSO,FASE,SUBS,USO,UF,AREA_HA,ULT_EVENTO",
                "returnGeometry": "true",
                "outSR": 4674,
                "f": "geojson",
                "resultOffset": inicio,
                "resultRecordCount": pagina,
            },  # fmt: skip
            timeout=300,
            **({"verify": verificar} if verificar else {}),
        )
        r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content))
        partes.append(g)
        if len(g) < pagina:
            break
        inicio += pagina
    return normalizar_sigmine(gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=4674))


# --- Lista Suja --------------------------------------------------------------------------------------------------

_LINHA = re.compile(r"(?m)^(\d{1,5}) ((?:19|20)\d{2}) ([A-Z]{2}) ")
_DOC = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}|[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}")
_FIM = re.compile(r"\s(\d+)\s+(\d{4}-\d/\d{2})\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})")
_RURAL = re.compile(r"\b(FAZENDA|FAZ\.|SITIO|SÍTIO|ZONA RURAL|CHACARA|CHÁCARA|GLEBA|ESTANCIA|ESTÂNCIA|LOTE|RAMAL)\b")


def ler_lista_suja_texto(texto: str) -> list[dict]:
    """Uma linha por empregador do cadastro. O documento fica só como chave em memória (chave_documento) e o endereço
    só serve para achar o município; nada disso é gravado."""
    inicios = list(_LINHA.finditer(texto))
    out = []
    for i, m in enumerate(inicios):
        bloco = texto[m.start() : inicios[i + 1].start() if i + 1 < len(inicios) else len(texto)]
        bloco = re.sub(r"\s+", " ", bloco)
        doc = _DOC.search(bloco)
        fim = _FIM.search(bloco, doc.end() if doc else 0)
        if not doc or not fim:
            continue
        uf = m.group(3)
        # o endereço termina em "CIDADE/UF", "CIDADE-UF" ou "CIDADE/UF." (às vezes nem tem cidade: residência)
        endereco = re.sub(r"\s*[/-]\s*" + uf + r"\.?\s*$", "", bloco[doc.end() : fim.start()].rstrip())
        cnae = fim.group(2)
        inclusao = dt.datetime.strptime(fim.group(4), "%d/%m/%Y").date().isoformat()
        out.append(
            {
                "chave": chave_documento(doc.group(0)),
                "ano_acao": int(m.group(2)),
                "uf": uf,
                "cod_ibge": municipio_do_texto(endereco, uf),
                "trabalhadores": int(fim.group(1)),
                "rural": cnae[:2] in ("01", "02", "03") or bool(_RURAL.search(endereco.upper())),
                "inclusao": inclusao,
            }
        )
    return out


def ler_lista_suja_pdf(conteudo: bytes) -> list[dict]:
    import pypdf

    r = pypdf.PdfReader(io.BytesIO(conteudo))
    return ler_lista_suja_texto("\n".join((p.extract_text() or "") for p in r.pages))


def lista_suja_por_municipio(linhas: list[dict]) -> pd.DataFrame:
    """Agregado público por município: quantos empregadores, quantos rurais, trabalhadores e a inclusão mais nova."""
    cols = ["cod_ibge", "uf", "empregadores", "rurais", "trabalhadores", "inclusao_mais_recente"]
    df = pd.DataFrame([x for x in linhas if x.get("cod_ibge")])
    if df.empty:
        return pd.DataFrame(columns=cols)
    a = df.groupby(["cod_ibge", "uf"], as_index=False).agg(
        empregadores=("ano_acao", "size"),
        rurais=("rural", "sum"),
        trabalhadores=("trabalhadores", "sum"),
        inclusao_mais_recente=("inclusao", "max"),
    )
    a["rurais"] = a.rurais.astype(int)
    return a[cols].sort_values("cod_ibge").reset_index(drop=True)


# --- Ibama: autos de infração e embargos -------------------------------------------------------------------------


def _coluna_documento(colunas) -> str | None:
    return next((c for c in colunas if "CPF" in c.upper() or "CNPJ" in c.upper()), None)


def ler_autos_csv(arquivo, chaves_lista: set[str], ano_minimo: int = 2008) -> gpd.GeoDataFrame:
    """Um CSV anual do SIFISC (sep ';'). Saem cancelados, excluídos e substituídos; sai todo dado pessoal."""
    try:
        df = pd.read_csv(arquivo, sep=";", dtype=str, encoding="utf-8", on_bad_lines="skip", low_memory=False)
    except UnicodeDecodeError:
        if hasattr(arquivo, "seek"):
            arquivo.seek(0)
        df = pd.read_csv(arquivo, sep=";", dtype=str, encoding="latin1", on_bad_lines="skip", low_memory=False)
    if df.empty:
        return gpd.GeoDataFrame(columns=COLUNAS_AUTOS, geometry="geometry", crs=4674)
    status = df.get("DES_STATUS_FORMULARIO", pd.Series("", index=df.index)).fillna("").map(normalizar_nome)
    cancelado = df.get("SIT_CANCELADO", pd.Series("N", index=df.index)).fillna("N").str.upper().eq("S")
    df = df[~cancelado & ~status.str.contains("CANCEL|EXCLU|SUBSTITU", regex=True)]
    data = pd.to_datetime(df.get("DAT_HORA_AUTO_INFRACAO"), errors="coerce", dayfirst=False)
    ano = data.dt.year
    df, data, ano = df[ano >= ano_minimo], data[ano >= ano_minimo], ano[ano >= ano_minimo]
    col_doc = _coluna_documento(df.columns)
    chaves = df[col_doc].map(chave_documento) if col_doc else pd.Series(None, index=df.index)
    geoms, tipos = [], []
    for area, lon, lat in zip(
        df.get("WKT_GE_AREA_AUTUADA", pd.Series(None, index=df.index)),
        df.get("NUM_LONGITUDE_AUTO", pd.Series(None, index=df.index)),
        df.get("NUM_LATITUDE_AUTO", pd.Series(None, index=df.index)),
        strict=True,
    ):
        g = _wkt(area)
        if g is not None and g.area > 0:
            geoms.append(g)
            tipos.append("area")
            continue
        x, y = _numero(lon), _numero(lat)
        p = shapely.Point(x, y) if x is not None and y is not None else None
        geoms.append(p if _no_brasil(p) else None)
        tipos.append("ponto" if _no_brasil(p) else None)
    out = gpd.GeoDataFrame(
        {
            "auto_id": df.get("SEQ_AUTO_INFRACAO").astype("string").values,
            "ano": ano.astype("Int64").values,
            "data": data.dt.date.map(lambda d: d.isoformat() if pd.notna(d) else None).values,
            "tipo_infracao": df.get("TIPO_INFRACAO", pd.Series(None, index=df.index)).values,
            "gravidade": df.get("GRAVIDADE_INFRACAO", pd.Series(None, index=df.index)).values,
            "cod_municipio": pd.to_numeric(df.get("COD_MUNICIPIO"), errors="coerce").astype("Int64").values,
            "uf": df.get("UF", pd.Series(None, index=df.index)).values,
            "geometria_tipo": tipos,
            "lista_suja": chaves.map(lambda k: bool(k) and k in chaves_lista).values,
        },
        geometry=geoms,
        crs=4674,
    )
    return out[out.geometry.notna()][COLUNAS_AUTOS].reset_index(drop=True)


def ler_autos_zip(conteudo_ou_caminho, chaves_lista: set[str], ano_minimo: int = 2008) -> gpd.GeoDataFrame:
    z = zipfile.ZipFile(conteudo_ou_caminho if not isinstance(conteudo_ou_caminho, bytes)
                        else io.BytesIO(conteudo_ou_caminho))  # fmt: skip
    partes = []
    for nome in sorted(z.namelist()):
        m = re.search(r"(\d{4})\.csv$", nome)
        if not m or int(m.group(1)) < ano_minimo:
            continue
        with z.open(nome) as f:
            partes.append(ler_autos_csv(io.BytesIO(f.read()), chaves_lista, ano_minimo))
    if not partes:
        return gpd.GeoDataFrame(columns=COLUNAS_AUTOS, geometry="geometry", crs=4674)
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=4674)


def embargos_da_lista(arquivo, chaves_lista: set[str], pedaco: int = 50_000) -> gpd.GeoDataFrame:
    """Polígonos dos embargos do Ibama cujo embargado está na Lista Suja (lido em pedaços; documento só em memória)."""
    partes = []
    leitor = pd.read_csv(arquivo, sep=";", dtype=str, chunksize=pedaco, on_bad_lines="skip", encoding="utf-8")
    for df in leitor:
        col_doc = _coluna_documento(df.columns)
        if not col_doc or "GEOM_AREA_EMBARGADA" not in df.columns:
            continue
        if "SIT_CANCELADO" in df.columns:
            df = df[df.SIT_CANCELADO.fillna("N").str.upper() != "S"]
        sel = df[df[col_doc].map(chave_documento).isin(chaves_lista)]
        for _, r in sel.iterrows():
            g = _wkt(r["GEOM_AREA_EMBARGADA"])
            if g is None:
                continue
            ano = pd.to_datetime(r.get("DAT_EMBARGO"), errors="coerce", dayfirst=True)
            partes.append({"fonte": "ibama_embargo", "objeto_id": str(r.get("SEQ_TAD")),
                           "ano": int(ano.year) if pd.notna(ano) else None, "geometry": g})  # fmt: skip
    return gpd.GeoDataFrame(partes, columns=COLUNAS_VINCULOS, geometry="geometry", crs=4674)


def vinculos_lista_suja(autos: gpd.GeoDataFrame, embargos: gpd.GeoDataFrame | None) -> gpd.GeoDataFrame:
    a = autos[autos.lista_suja.fillna(False).astype(bool)]
    a = gpd.GeoDataFrame(
        {"fonte": "ibama_auto", "objeto_id": a.auto_id.astype(str).values, "ano": a.ano.values},
        geometry=a.geometry.values,
        crs=4674,
    )
    partes = [a] + ([embargos.to_crs(4674)] if embargos is not None and len(embargos) else [])
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=4674)[COLUNAS_VINCULOS]


# --- RL e APP declaradas no CAR ----------------------------------------------------------------------------------

TEMAS_SICAR = {"RESERVA_LEGAL": "reserva_legal", "APP": "app", "AREA_PRESERVACAO_PERMANENTE": "app"}


def converter_car_temas(zips: list[Path]) -> gpd.GeoDataFrame:
    """Shapefiles da base de downloads do SICAR (um zip por município, com RESERVA_LEGAL.shp e APP.shp) para
    cod_imovel, tema (reserva_legal | app) e polígono. Só lê; quem coleta é a fonte quando abrir (ver o topo)."""
    partes = []
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            for nome in zf.namelist():
                base = Path(nome).stem.upper()
                if not nome.lower().endswith(".shp") or base not in TEMAS_SICAR:
                    continue
                g = gpd.read_file(f"zip://{z}!{nome}")
                cod = next((c for c in g.columns if c.upper() in ("COD_IMOVEL", "COD_IMOVEL_RURAL")), None)
                if cod is None:
                    continue
                g = g.set_crs(4674) if g.crs is None else g.to_crs(4674)
                partes.append(gpd.GeoDataFrame({"cod_imovel": g[cod].astype(str), "tema": TEMAS_SICAR[base]},
                                               geometry=g.geometry.values, crs=4674))  # fmt: skip
    if not partes:
        return gpd.GeoDataFrame(columns=["cod_imovel", "tema", "geometry"], geometry="geometry", crs=4674)
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), crs=4674)


# --- orquestração ------------------------------------------------------------------------------------------------


def coletar(saida: str | Path, fontes=FONTES, ufs=UFS, s=None, hoje: str | None = None) -> dict:
    """Coleta as fontes pedidas e grava a pasta de saída. Devolve o manifesto (o mesmo do restricoes_cobertura.json).

    A Lista Suja vem antes dos autos: o cruzamento por documento acontece aqui, em memória, e não sai daqui."""
    from raiz.coleta.http import sessao

    s = s or sessao()
    hoje = hoje or dt.date.today().isoformat()
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    cob: dict[str, dict] = {}
    chaves: set[str] = set()

    if "lista_suja" in fontes or "ibama_autos" in fontes:
        try:
            r = s.get(URL_LISTA_SUJA, timeout=300)
            r.raise_for_status()
            linhas = ler_lista_suja_pdf(r.content)
            if not linhas:
                raise ValueError("PDF sem linhas reconhecidas")
            chaves = {x["chave"] for x in linhas if x["chave"]}
            mun = lista_suja_por_municipio(linhas)
            mun.to_csv(saida / NOMES["lista_suja_municipios"], index=False)
            cob["lista_suja"] = {"estado": "consultado", "url": URL_LISTA_SUJA, "n": len(linhas),
                                 "sem_municipio": sum(1 for x in linhas if not x["cod_ibge"]),
                                 "municipios": int(len(mun))}  # fmt: skip
        except Exception as ex:  # noqa: BLE001
            cob["lista_suja"] = {"estado": "indisponivel", "url": URL_LISTA_SUJA, "erro": type(ex).__name__}

    if "ibama_autos" in fontes:
        try:
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "autos.zip"
                with s.get(URL_IBAMA_AUTOS, stream=True, timeout=1800) as r:
                    r.raise_for_status()
                    with f.open("wb") as w:
                        for b in r.iter_content(1 << 20):
                            w.write(b)
                autos = ler_autos_zip(f, chaves)
            autos.to_parquet(saida / NOMES["ibama_autos"])
            cob["ibama_autos"] = {"estado": "consultado", "url": URL_IBAMA_AUTOS, "n": int(len(autos)),
                                  "areas": int((autos.geometria_tipo == "area").sum())}  # fmt: skip
        except Exception as ex:  # noqa: BLE001
            autos = None
            cob["ibama_autos"] = {"estado": "indisponivel", "url": URL_IBAMA_AUTOS, "erro": type(ex).__name__}
        if cob.get("lista_suja", {}).get("estado") == "consultado" and autos is not None:
            embargos, emb_ok = None, False
            try:
                with tempfile.TemporaryDirectory() as d:
                    f = Path(d) / "embargos.csv"
                    with s.get(URL_IBAMA_EMBARGOS, stream=True, timeout=1800) as r:
                        r.raise_for_status()
                        with f.open("wb") as w:
                            for b in r.iter_content(1 << 20):
                                w.write(b)
                    embargos, emb_ok = embargos_da_lista(f, chaves), True
            except Exception as ex:  # noqa: BLE001
                log.warning("embargos do Ibama indisponíveis para a Lista Suja (%s)", type(ex).__name__)
            v = vinculos_lista_suja(autos, embargos)
            v.to_parquet(saida / NOMES["lista_suja_vinculos"])
            cob["lista_suja"].update(vinculos=int(len(v)), embargos_cruzados=emb_ok)
        elif "lista_suja" in cob:
            # sem os autos não há vínculo geográfico: a Lista Suja vale só pelo agregado do município
            cob["lista_suja"]["estado"] = "parcial" if cob["lista_suja"]["estado"] == "consultado" else "indisponivel"

    if "sigmine" in fontes:
        g, c = baixar_sigmine(s, ufs)
        if len(g):
            g.to_parquet(saida / NOMES["sigmine"])
        cob["sigmine"] = c

    if "car_temas" in fontes:
        pendente = "base de downloads do SICAR atrás de captcha; LAI 02303.031114/2026-60"
        cob["car_temas"] = {"estado": "indisponivel", "pendente": pendente}

    for f in cob.values():
        f.setdefault("consultado_em", hoje)
    manifesto = {"versao": VERSAO, "coletado_em": hoje, "fontes": cob}
    (saida / NOMES["cobertura"]).write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifesto


def conferir_sem_documento(pasta: str | Path) -> list:
    """Guarda antes de publicar: procura CPF ou CNPJ em todo arquivo da coleta (parquet lido sem a geometria)."""
    from raiz.protecao.privacidade import varrer_texto

    achados = []
    for f in sorted(Path(pasta).glob("restricoes_*")):
        if f.suffix == ".parquet":
            texto = pd.read_parquet(f).drop(columns="geometry", errors="ignore").to_csv(index=False)
        else:
            texto = f.read_text(encoding="utf-8", errors="ignore")
        achados += varrer_texto(texto, f.name)
    return achados
