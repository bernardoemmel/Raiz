"""Coleta das camadas estaduais do catálogo (raiz/estaduais/fontes/<UF>.yaml), sem dado pessoal na saída.

Para cada fonte com `tipo: wfs` ou `tipo: arcgis` e `acesso: aberto`:
  1. lê a camada inteira da UF (WFS paginado ou ArcGIS por OBJECTID, com conferência da contagem: camada pela
     metade falha em vez de ser gravada), sempre pedida em EPSG:4674;
  2. apaga na entrada os campos de `descartar` e qualquer outro que pareça pessoal (nome, CPF, CNPJ...;
     `raiz.privacidade.colunas_pessoais`), guarda só os de `manter` que existirem (tolera coluna nova ou sumida);
  3. mascara CPF/CNPJ que apareça dentro de texto livre;
  4. calcula `efeito` e `motivo` de cada feição pelas `regra_efeito` (valor de campo, recência);
  5. grava estaduais_<id>.parquet e o estado de cada fonte em estaduais_cobertura.json
     (consultado | parcial | indisponivel | bloqueado_fora_brasil | sem_download).

Fonte bloqueada fora do Brasil fica registrada como tal: a coleta roda de novo a partir do Brasil e, até lá, o
cruzamento marca os imóveis da UF como "nao_verificado" nessa fonte (ausência de dado nunca vira livre).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
import yaml

from raiz.privacidade import colunas_pessoais, mascarar

PASTA_FONTES = Path(__file__).with_name("fontes")
COBERTURA = "estaduais_cobertura.json"
EFEITOS = ("exclusao", "ressalva", "conferir", "informativo")
ACESSOS = ("aberto", "bloqueado_fora_brasil", "sem_download", "pedido", "regra")
# tipos com coleta automática: serviço (wfs, arcgis), arquivo por URL (GeoJSON, shapefile zipado, KML), a Lista de
# Desmatamento Ilegal do Pará (CSV ligado ao CAR) e as florestas públicas estaduais do CNFP (SFB)
TIPOS_AUTOMATICOS = ("wfs", "arcgis", "arquivo", "ldi_pa", "cnfp")
CHAVES_ORDEM = ("fid", "id", "gid", "objectid", "OBJECTID", "ogc_fid", "OID")
CRS_METRICO = 5880
log = logging.getLogger(__name__)
# polígonos estaduais enormes (ex.: área bloqueada das usinas do Madeira, 61 mil ha num só objeto) passam do limite
# padrão do leitor GeoJSON do GDAL (200 MB por objeto)
os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")


# --- catálogo ----------------------------------------------------------------------------------------------------


def catalogo(ufs: Iterable[str] | None = None, pasta: Path = PASTA_FONTES) -> list[dict]:
    """Todas as fontes do catálogo (uma por camada lógica), com a UF preenchida."""
    quer = {u.upper() for u in ufs} if ufs else None
    fontes = []
    for arq in sorted(pasta.glob("*.yaml")):
        d = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        uf = d.get("uf") or arq.stem
        if quer and uf not in quer:
            continue
        for f in d.get("fontes") or []:
            fontes.append({"uf": uf, **f})
    return fontes


def validar(fontes: list[dict]) -> list[str]:
    """Erros do catálogo (vazio = ok). O teste do CI chama isto para cada UF."""
    erros, ids = [], set()
    for f in fontes:
        i = f.get("id") or "?"
        if i in ids:
            erros.append(f"{i}: id repetido")
        ids.add(i)
        for k in ("nome", "tema", "orgao", "acesso", "tipo", "efeito", "motivo", "criterio", "situacao"):
            if not f.get(k):
                erros.append(f"{i}: falta {k}")
        if f.get("efeito") not in EFEITOS:
            erros.append(f"{i}: efeito {f.get('efeito')!r} fora de {EFEITOS}")
        if f.get("acesso") not in ACESSOS:
            erros.append(f"{i}: acesso {f.get('acesso')!r} fora de {ACESSOS}")
        for r in f.get("regra_efeito") or []:
            if r.get("efeito") and r["efeito"] not in EFEITOS:
                erros.append(f"{i}: regra_efeito com efeito {r['efeito']!r}")
            if "campo" not in r or "padrao" not in r:
                erros.append(f"{i}: regra_efeito precisa de campo e padrao")
            else:
                re.compile(r["padrao"])
        if f.get("juncao") in ("cod_imovel", "cod_imovel_ou_geometria") and not f.get("campo_cod_imovel"):
            erros.append(f"{i}: junção pelo CAR precisa de campo_cod_imovel")
        if f.get("acesso") == "aberto" and f.get("tipo") in ("arquivo", "ldi_pa") and not f.get("url"):
            erros.append(f"{i}: fonte aberta sem url")
        if f.get("acesso") == "aberto" and f.get("tipo") in ("wfs", "arcgis"):
            if not f.get("url") or not (f.get("camada") or f.get("camadas") or f["tipo"] == "arcgis"):
                erros.append(f"{i}: fonte aberta sem url/camada")
            pessoais = colunas_pessoais(f.get("manter") or [], permitir=f.get("permitir") or [])
            if pessoais:
                erros.append(f"{i}: manter tem campo pessoal {pessoais}; mova para descartar ou declare em permitir")
    return erros


def camadas_da_fonte(f: dict) -> list[str]:
    """Nomes de camada (WFS) ou URLs de camada (ArcGIS) de uma fonte; expande {ano} e subcamadas."""
    if f["tipo"] in ("arquivo", "ldi_pa", "cnfp"):
        return [f.get("url") or f["tipo"]]
    if f["tipo"] == "arcgis":
        base = f["url"].rstrip("/")
        if f.get("subcamadas"):
            return [f"{base}/{n}" for n in f["subcamadas"]]
        return [base]
    nomes = f.get("camadas") or [f["camada"]]
    if f.get("anos"):
        nomes = [n.format(ano=a) for n in nomes for a in f["anos"]]
    return nomes


# --- leitura -----------------------------------------------------------------------------------------------------


def _wfs(s: requests.Session, url: str, nome: str, cql: str | None) -> gpd.GeoDataFrame:
    from raiz.coleta import wfs

    c = wfs.Camada(url=url, nome=nome, versao="2.0.0", srs="EPSG:4674")
    campos = wfs.campos(s, c)
    sem_geo = sorted(campos - {"geom", "geometry", "the_geom"})
    # camada só com geometria (ex.: áreas autuadas de RO): sem sortBy, o GeoServer pagina na ordem da chave interna
    ordem = next((k for k in CHAVES_ORDEM if k in campos), None) or (sem_geo[0] if sem_geo else None)
    if ordem is None:
        # visão sem chave primária (ex.: áreas autuadas de RO): o GeoServer não pagina; lê tudo de uma vez
        import io

        p = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": nome,
             "outputFormat": "application/json", "srsName": "EPSG:4674"}  # fmt: skip
        if cql:
            p["CQL_FILTER"] = cql
        r = s.get(url, params=p, timeout=900)
        r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content), engine="pyogrio")
        return g.set_crs(4674, allow_override=True)
    return wfs.ler(s, c, ordenar_por=ordem, cql=cql, pagina=5000)


def _arcgis(s: requests.Session, url: str, where: str | None, timeout: int = 600) -> gpd.GeoDataFrame:
    """Leitura por OBJECTID crescente (como raiz.coleta.arcgis), montando as feições pelo JSON: o leitor GDAL
    falha em páginas grandes de alguns MapServer ("URL rejected"). Confere a contagem no fim."""
    from raiz.coleta import arcgis
    from raiz.coleta.wfs import LeituraIncompleta

    where = where or "1=1"
    d = arcgis.detalhes(s, url)
    oid = d.get("objectIdField") or next(
        (f["name"] for f in d.get("fields", []) if f.get("type") == "esriFieldTypeOID"), "OBJECTID"
    )
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", oid):
        raise ValueError("ArcGIS informou campo OBJECTID inválido")
    passo = int(d.get("maxRecordCount") or 1000)
    total = arcgis.contar(s, url, where)
    partes, ultimo, recebidas = [], -1, 0
    while recebidas < total:
        r = s.get(
            f"{url}/query",
            params={
                "where": f"({where}) AND {oid} > {ultimo}",
                "orderByFields": f"{oid} ASC",
                "resultRecordCount": passo,
                "outFields": "*",
                "outSR": 4674,
                "f": "geojson",
            },  # fmt: skip
            timeout=timeout,
        )
        r.raise_for_status()
        feats = r.json().get("features")
        if feats is None:
            raise LeituraIncompleta("ArcGIS não devolveu uma página de feições válida")
        if not feats:
            break
        for f in feats:
            f.setdefault("properties", {})[oid] = f["properties"].get(oid, f.get("id"))
        g = gpd.GeoDataFrame.from_features(feats, crs=4674)
        ids = pd.to_numeric(g[oid], errors="raise")
        if not (ids > ultimo).all():
            raise LeituraIncompleta("paginação ArcGIS não avançou OBJECTID")
        partes.append(g)
        ultimo, recebidas = int(ids.max()), recebidas + len(g)
        if len(feats) < passo:
            break
    if recebidas != total:
        raise LeituraIncompleta(f"{url}: recebidas {recebidas} de {total} feições")
    if not partes:
        return gpd.GeoDataFrame(geometry=[], crs=4674)
    return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=4674)


def limpar(g: gpd.GeoDataFrame, f: dict) -> gpd.GeoDataFrame:
    """Apaga o que é pessoal e fica só com os campos úteis (tolerando campo que não exista)."""
    descartar = {c.lower() for c in f.get("descartar") or []}
    permitir = [*(f.get("permitir") or []), *([f["campo_cod_imovel"]] if f.get("campo_cod_imovel") else [])]
    fora = {c for c in g.columns if c.lower() in descartar} | set(colunas_pessoais(g.columns, permitir))
    fora.discard("geometry")
    g = g.drop(columns=sorted(fora))
    manter = [c for c in (f.get("manter") or []) if c in g.columns]
    extra = [c for c in (f.get("regra_efeito") or []) if c.get("campo") in g.columns and c["campo"] not in manter]
    manter += [r["campo"] for r in extra]
    for c in (f.get("campo_data"), f.get("campo_cod_imovel"), f.get("campo_ha")):
        if c and c in g.columns and c not in manter:
            manter.append(c)
    g = g[[*dict.fromkeys(manter), "geometry"]].copy()
    for c in manter:
        if g[c].dtype == object:
            g[c] = g[c].map(_sem_documento)
    return g


def _sem_documento(v):
    """Máscara de CPF/CNPJ em texto; código que coincide com um CPF ou CNPJ válido (número de processo, auto)
    vira vazio: na dúvida, perde-se o código, nunca se publica um documento."""
    from raiz.privacidade import documento_em_identificador

    if not isinstance(v, str):
        return v
    v = mascarar(v)
    return None if documento_em_identificador(v) else v


def _ano(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return float("nan")
    if isinstance(v, (int, float)):
        if v > 10**11:  # epoch em ms (ArcGIS)
            return float(dt.datetime.fromtimestamp(v / 1000, dt.UTC).year)
        return float(v) if 1900 < v < 2100 else float("nan")
    m = re.search(r"(19|20)\d\d", str(v))
    return float(m.group(0)) if m else float("nan")


def classificar(g: gpd.GeoDataFrame, f: dict, hoje: dt.date | None = None) -> gpd.GeoDataFrame:
    """efeito e motivo por feição: o padrão da fonte e, por cima, a primeira regra_efeito que casar."""
    hoje = hoje or dt.date.today()
    g = g.copy()
    g["efeito"] = f["efeito"]
    g["motivo"] = f["motivo"]
    ano = g[f["campo_data"]].map(_ano) if f.get("campo_data") in g.columns else pd.Series(float("nan"), index=g.index)
    g["ano"] = ano
    casou = pd.Series(False, index=g.index)
    for r in f.get("regra_efeito") or []:
        if r["campo"] not in g.columns:
            continue
        m = g[r["campo"]].astype("string").fillna("").str.contains(r["padrao"], regex=True) & ~casou
        if r.get("recente_anos"):
            m &= ano >= hoje.year - int(r["recente_anos"])
        g.loc[m, "efeito"] = r.get("efeito", f["efeito"])
        g.loc[m, "motivo"] = r.get("motivo", f["motivo"])
        casou |= m
    return g


def _raio(g: gpd.GeoDataFrame, raio_m: float | None) -> gpd.GeoDataFrame:
    if not raio_m or not len(g):
        return g
    g = g.to_crs(CRS_METRICO)
    g["geometry"] = g.geometry.buffer(float(raio_m))
    return g.to_crs(4674)


# --- arquivo por URL, LDI do Pará e CNFP ---------------------------------------------------------------------------

NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) Raiz-coleta/1.0 (+https://github.com/bernardoemmel/raiz)"


def _arquivo(s: requests.Session, f: dict) -> gpd.GeoDataFrame:
    """GeoJSON, shapefile zipado, KML ou GeoPackage baixado por HTTP (SRS do arquivo ou `srs` da fonte)."""
    import io
    import tempfile

    import pyogrio

    r = s.get(f["url"], timeout=900, headers={"User-Agent": NAVEGADOR})
    r.raise_for_status()
    dado = r.content
    inicio = dado[:4000].lstrip()
    if inicio[:1] == b"<" and b"<kml" not in inicio and b"FeatureCollection" not in inicio:
        raise ValueError("a fonte devolveu uma página HTML em vez do arquivo")
    if dado[:2] == b"PK":
        with tempfile.TemporaryDirectory() as d:
            z = Path(d) / "camada.zip"
            z.write_bytes(dado)
            g = pyogrio.read_dataframe(f"/vsizip/{z}")
    else:
        g = pyogrio.read_dataframe(io.BytesIO(dado))
    g = g.set_crs(f.get("srs") or 4674) if g.crs is None else g
    return g.to_crs(4674)


_DMS = re.compile(r"(\d+)\s*[º°]\s*(\d+)\s*'\s*([\d,.]+)\s*\"?\s*([NSLOWE])?", re.IGNORECASE)


def dms(texto) -> float | None:
    """06º13'33,69" S -> -6.226. A LDI escreve a longitude com "S" por engano; no Brasil, fora o extremo norte de
    RR e AP, latitude e longitude são negativas, e só "N" explícito fica positivo."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return None
    m = _DMS.search(str(texto))
    if not m:
        return None
    v = float(m.group(1)) + float(m.group(2)) / 60 + float(m.group(3).replace(",", ".")) / 3600
    return v if (m.group(4) or "").upper() == "N" else -v


def _numero_br(v) -> float | None:
    t = str(v or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _csv_ldi(conteudo: bytes) -> pd.DataFrame:
    """CSV da LDI: 3 linhas de cabeçalho, separador ';'. As colunas de razão social e CPF/CNPJ ficam no fim da linha
    e às vezes têm ';' dentro: a linha é cortada antes da primeira coluna pessoal, que nunca chega a ser lida."""
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")
    linhas = texto.splitlines()
    ini = next(i for i, x in enumerate(linhas) if x.startswith(("Nº do processo", "CodLDI")))
    # split simples: o único campo entre aspas ("Sobreposição CAR-CodList") separa por vírgula, não por ';', e um
    # nome com aspas soltas não pode engolir as linhas seguintes
    leitor = (x.split(";") for x in linhas[ini:])
    cab = next(leitor)
    pessoal = [i for i, c in enumerate(cab) if re.search(r"raz[aã]o social|cpf|cnpj|propriet", c, re.I)]
    corte = min(pessoal) if pessoal else len(cab)
    cab = [c.strip() for c in cab[:corte]]
    dados = [(r[:corte] + [""] * corte)[:corte] for r in leitor if any(x.strip() for x in r)]
    df = pd.DataFrame(dados, columns=cab).apply(lambda c: c.str.strip().str.strip('"'))
    return df.loc[:, [c for c in df.columns if c]]


def ldi_pa(com_car: bytes, sem_car: bytes | None = None) -> gpd.GeoDataFrame:
    """Uma linha por área da LDI: recibo do CAR (quando o órgão ligou), ponto, ano, área e desmate dentro do CAR."""
    a = _csv_ldi(com_car)
    partes = [
        pd.DataFrame(
            {
                "cod_ldi": a.get("CodLDI"),
                "cod_imovel": a["Nº do recibo"].str.strip().replace({"": None, "-": None}),
                "situacao_car": a.get("Situação do CAR"),
                "ano": a.get("Ano Desmatamento"),
                "area_ha": a["Área Desmatamento (ha)"].map(_numero_br),
                "desmate_car_ha": a["Desmate em CAR - APRT(ha)"].map(_numero_br),
                "fonte_alerta": a.get("Fonte"),
                "processo": a.get("Proc. Punitivo com CAR"),
                "lat": a["Latitude"].map(dms),
                "lon": a["Longitude"].map(dms),
            }
        )
    ]
    if sem_car:
        b = _csv_ldi(sem_car)
        partes.append(
            pd.DataFrame(
                {
                    "cod_imovel": None,
                    "ano": b.get("Ano"),
                    "area_ha": b["Área Desmatada"].map(_numero_br),
                    "fonte_alerta": b.get("Fonte"),
                    "processo": b.get("Nº do processo"),
                    "lat": b["Latitude"].map(dms),
                    "lon": b["Longitude"].map(dms),
                }
            )
        )
    t = pd.concat(partes, ignore_index=True)
    ok = t.lat.notna() & t.lon.notna()
    t = t[ok | t.cod_imovel.notna()].reset_index(drop=True)
    geo = [shapely.Point(x, y) if pd.notna(x) and pd.notna(y) else None for x, y in zip(t.lon, t.lat, strict=True)]
    return gpd.GeoDataFrame(t.drop(columns=["lat", "lon"]), geometry=geo, crs=4674)


def _ldi_pa(s: requests.Session, f: dict) -> gpd.GeoDataFrame:
    base = f["url"].rstrip("/")
    com = s.get(f"{base}/regioesdesmatamento/downloadcsvareasfile", timeout=600, headers={"User-Agent": NAVEGADOR})
    com.raise_for_status()
    sem = s.get(f"{base}/regioesdesmatamento/downloadcsvfile", timeout=600, headers={"User-Agent": NAVEGADOR})
    sem.raise_for_status()
    return ldi_pa(com.content, sem.content)


def filtrar_cnfp_estadual(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Florestas públicas estaduais não destinadas: governo estadual e tipo B (glebas arrecadadas, devolutas)."""
    gov = g["governo"].astype(str).str.upper() if "governo" in g.columns else pd.Series("", index=g.index)
    tipo = g["tipo"].astype(str).str.upper().str.replace("TIPO ", "").str.strip() if "tipo" in g.columns else gov
    return g[gov.str.contains("ESTAD") & (tipo == "B")].copy()


def _cnfp(s: requests.Session, f: dict) -> gpd.GeoDataFrame:
    import os
    import tempfile

    from raiz import terra_publica as TP

    pasta = Path(os.environ.get("RAIZ_CNFP_DIR") or Path(tempfile.gettempdir()) / "raiz_cnfp")
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"cnfp_{f['uf']}.parquet"
    if not arq.exists():
        TP.preparar_cnfp(TP.baixar_cnfp(pasta / "CNFP_2025.zip"), pasta)
    if not arq.exists():
        return gpd.GeoDataFrame(geometry=[], crs=4674)
    return filtrar_cnfp_estadual(gpd.read_parquet(arq))


LEITORES = {"arquivo": _arquivo, "ldi_pa": _ldi_pa, "cnfp": _cnfp}


# --- coleta ------------------------------------------------------------------------------------------------------


def coletar_fonte(s: requests.Session, f: dict, hoje: dt.date | None = None) -> tuple[gpd.GeoDataFrame, dict]:
    partes, falhas = [], []
    for camada in camadas_da_fonte(f):
        try:
            if f["tipo"] == "arcgis":
                g = _arcgis(s, camada, f.get("filtro"))
            elif f["tipo"] == "wfs":
                g = _wfs(s, f["url"], camada, f.get("filtro"))
            else:
                g = LEITORES[f["tipo"]](s, f)
        except Exception as e:  # noqa: BLE001 - uma camada fora do ar não derruba as outras
            log.warning("estaduais: %s %s falhou: %s", f["id"], camada, type(e).__name__)
            falhas.append(camada)
            continue
        if len(g):
            g = limpar(g, f)
            g["camada"] = camada.rsplit("/", 2)[-2] if f["tipo"] == "arcgis" else camada.rsplit("/", 1)[-1]
            partes.append(g)
    if partes:
        g = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=4674)
    else:
        g = gpd.GeoDataFrame({"camada": []}, geometry=[], crs=4674)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    for c in g.columns:  # páginas e anos diferentes trazem tipos misturados (data como texto e como data)
        if c != "geometry" and (g[c].dtype == object or str(g[c].dtype).startswith("datetime")):
            g[c] = g[c].map(lambda v: None if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v))
            g[c] = g[c].map(_sem_documento)
    g = _raio(classificar(g, f, hoje), f.get("raio_m"))
    g.insert(0, "fonte_id", f["id"])
    n = len(camadas_da_fonte(f))
    estado = "indisponivel" if len(falhas) == n else ("parcial" if falhas else "consultado")
    return g, {"estado": estado, "uf": f["uf"], "feicoes": int(len(g)), "falhas": falhas}


def aplicar_desembargos(saidas: dict[str, gpd.GeoDataFrame], fontes: list[dict]) -> None:
    """Tira das camadas de embargo os processos que aparecem na camada de desembargo indicada (excluir_se_em)."""
    for f in fontes:
        regra = f.get("excluir_se_em")
        if not regra or f["id"] not in saidas or regra["fonte"] not in saidas:
            continue
        campo, g, d = regra["campo"], saidas[f["id"]], saidas[regra["fonte"]]
        if campo in g.columns and campo in d.columns:
            fora = set(d[campo].dropna().astype(str))
            saidas[f["id"]] = g[~g[campo].astype(str).isin(fora)].copy()


def conferir_sem_documento(pasta: Path) -> list[str]:
    """Arquivos da coleta com CPF/CNPJ em claro (deve voltar vazio antes de publicar)."""
    from raiz.privacidade import documento_em_identificador

    ruins = []
    for arq in pasta.glob("estaduais_*.parquet"):
        g = pd.read_parquet(arq)
        for c in g.columns:
            if c != "geometry" and g[c].dtype == object:
                if g[c].dropna().astype(str).map(documento_em_identificador).any():
                    ruins.append(f"{arq.name}:{c}")
    return ruins


def coletar(destino: Path, ufs: Iterable[str] | None = None, hoje: dt.date | None = None, sessao=None) -> dict:
    """Coleta o catálogo das UFs pedidas para `destino`. Devolve a cobertura (também gravada em JSON)."""
    from raiz.coleta.http import sessao as nova_sessao

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    s = sessao or nova_sessao()
    fontes = catalogo(ufs)
    arq = destino / COBERTURA
    cob = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"fontes": {}}
    saidas: dict[str, gpd.GeoDataFrame] = {}
    for f in fontes:
        base = {"uf": f["uf"], "efeito": f["efeito"], "tema": f["tema"], "acesso": f["acesso"]}
        if f["acesso"] != "aberto" or f["tipo"] not in TIPOS_AUTOMATICOS:
            cob["fontes"][f["id"]] = {**base, "estado": f["acesso"] if f["acesso"] != "regra" else "regra"}
            continue
        g, info = coletar_fonte(s, f, hoje)
        cob["fontes"][f["id"]] = {**base, **info, "coletado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")}
        if info["estado"] != "indisponivel":
            saidas[f["id"]] = g
    aplicar_desembargos(saidas, fontes)
    for i, g in saidas.items():
        g.to_parquet(destino / f"estaduais_{i}.parquet", index=False)
        cob["fontes"][i]["feicoes"] = int(len(g))
    ruins = conferir_sem_documento(destino)
    if ruins:
        for i in saidas:
            (destino / f"estaduais_{i}.parquet").unlink(missing_ok=True)
        raise RuntimeError(f"documento pessoal na coleta estadual: {ruins}")
    cob["gerado_em"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    arq.write_text(json.dumps(cob, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return cob
