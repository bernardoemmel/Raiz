"""Entradas geográficas do valor para quem restaura (raiz/restauracao.py), por município, fora do motor.

- distância do pasto à mata por faixa (d0 até 100 m, d1 100 a 300 m, d2 300 m a 1 km, d3 acima): MapBiomas
  cobertura do cache do motor (cache/mapbiomas/<UF>/<UF>_cobertura_<ano>.tif);
- linha de base do município: fração do pasto de cada faixa que rebrotou sozinha e segue de pé nos últimos N anos,
  pela idade da vegetação secundária do YbYrá-BR v8.1 (Source Cooperative, leitura por HTTP Range);
- declividade média do imóvel: Copernicus DEM GLO-30 (AWS Open Data), lido a 60 m e guardado por ladrilho de 1 grau;
- chuva: CHIRPS v3, média anual de 2015 a 2024, guardada por faixa de 5 graus de latitude;
- solo: SoilGrids 2.0 (ISRIC, CC BY 4.0), capacidade de troca de cátions de 0 a 30 cm, guardada por município.
Tudo com cache em disco (config cache_restauracao_dir, padrão dados/cache_restauracao). Se uma fonte falhar, a
coluna fica vazia e o cálculo usa a premissa neutra, dizendo em restauracao_faltou o que faltou.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

YBYRA_IDADE = "https://data.source.coop/ybyra-br/secondary-forest/age/ybyra_secondary_forest_age_brazil_v8_1_{ano}.tif"
YBYRA_ANO = 2024
COPERNICUS = (
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
)
CHIRPS = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/annual/global/tifs/chirps-v3.0.{ano}.tif"
CHIRPS_ANOS = tuple(range(2015, 2025))
SOILGRIDS = "https://files.isric.org/soilgrids/latest/data/cec/cec_{prof}_mean.vrt"
SOILGRIDS_PROF = (("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15))  # espessura de cada camada (média ponderada)
BRASIL_LON = (-75.0, -28.0)
LADRILHO = 2048
FAIXAS = ("d0", "d1", "d2", "d3")

os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_LIST")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.vrt")
os.environ.setdefault("GDAL_HTTP_MULTIRANGE", "YES")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_HTTP_MAX_RETRY", "4")
os.environ.setdefault("GDAL_HTTP_RETRY_DELAY", "3")


def pasta_cache() -> Path:
    from raiz.config import config

    p = Path(getattr(config(), "cache_restauracao_dir", None) or "dados/cache_restauracao")
    if not p.is_absolute():  # o invólucro do motor muda de pasta; relativo é sempre à raiz do repositório
        from raiz import RAIZ_REPO

        p = RAIZ_REPO / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ha_pixel(lat, res: float):
    m = res * 111320.0
    return m * m * np.cos(np.radians(lat)) / 1e4


def _zonal_classes(tif: Path, g, ops=("classes",)):
    import rasterio

    from raiz.funil.novo import zonal

    with rasterio.open(tif) as ras:
        return zonal(ras, g, ops, include_cols=["cod_imovel"]).reset_index(drop=True)


# --- distância à mata e linha de base ---------------------------------------------------------------------------


def _ler_janela(fonte, win, shape):
    from rasterio.windows import Window

    w = Window(win.col_off, win.row_off, shape[1], shape[0])
    return fonte.read(1, window=w, boundless=True, fill_value=0)


def faixas_e_linha_base(
    geo,
    cobertura_tif: str | Path,
    r: dict | None = None,
    idade_url: str | None = "padrao",
    pasta_tmp: Path | None = None,
) -> tuple[dict[str, dict], dict]:
    """(por imóvel: pasto_d0_ha..pasto_d3_ha; do município: linha_base_taxa_d0..d3 e linha_base_fonte).

    Lê a cobertura em ladrilhos com borda de ~1,2 km (a distância só importa até 1 km), calcula a distância de
    cada pixel de pasto à mata mais próxima (remanescente = classes de mata do MapBiomas menos a vegetação secundária
    jovem do YbYrá, que é justamente o que rebrotou) e grava um raster de códigos: 1 a 4 = pasto em d0..d3; 11 a 14
    = rebrotou sozinho nos últimos N anos em d0..d3. A soma por imóvel usa a soma por janela do motor."""
    import rasterio
    from rasterio.windows import Window, from_bounds
    from scipy.ndimage import distance_transform_edt

    from raiz.restauracao import regra

    r = r or regra()
    lim = [float(x) for x in r["regra_modo"]["distancia_m"]]
    janela_anos = int(r["linha_base"]["janela_anos"])
    mata = np.array(r["area"]["remanescente_mapbiomas"])
    aberto = np.array(r["area"]["aberto_mapbiomas"])
    g = geo.to_crs(4326).reset_index(drop=True)
    x0, y0, x1, y1 = g.total_bounds
    if idade_url == "padrao":
        idade_url = "/vsicurl/" + YBYRA_IDADE.format(ano=YBYRA_ANO)
    cont_aberto = np.zeros(4)
    cont_rebrota = np.zeros(4)
    tmpdir = Path(tempfile.mkdtemp(prefix="faixas_", dir=pasta_tmp))
    saida = tmpdir / "faixas.tif"
    with rasterio.open(cobertura_tif) as cob:
        res = abs(cob.res[0])
        pad_px = int(math.ceil(lim[-1] * 1.2 / (res * 110574.0))) + 2
        w = from_bounds(x0, y0, x1, y1, cob.transform).round_offsets(op="floor").round_lengths(op="ceil")
        W, H = int(w.width) + 1, int(w.height) + 1
        tr = cob.window_transform(Window(int(w.col_off), int(w.row_off), W, H))
        idade = None
        if idade_url:
            try:
                idade = rasterio.open(idade_url)
            except Exception as e:  # noqa: BLE001 - sem YbYrá: taxas padrão
                log.warning("YbYrá indisponível (%s): linha de base com taxas padrão", e)
        perfil = dict(driver="GTiff", width=W, height=H, count=1, dtype="uint8", crs=cob.crs, transform=tr,
                      nodata=0, tiled=True, blockxsize=512, blockysize=512, compress="deflate")  # fmt: skip
        try:
            with rasterio.open(saida, "w", **perfil) as out:
                for r0 in range(0, H, LADRILHO):
                    for c0 in range(0, W, LADRILHO):
                        h, wd = min(LADRILHO, H - r0), min(LADRILHO, W - c0)
                        jan = Window(int(w.col_off) + c0 - pad_px, int(w.row_off) + r0 - pad_px, wd + 2 * pad_px,
                                     h + 2 * pad_px)  # fmt: skip
                        c = cob.read(1, window=jan, boundless=True, fill_value=0)
                        jovem = np.zeros(c.shape, dtype=bool)
                        if idade is not None:
                            bx = rasterio.windows.bounds(jan, cob.transform)
                            wi = from_bounds(*bx, idade.transform).round_offsets().round_lengths()
                            a = _ler_janela(idade, wi, c.shape)
                            jovem = (a >= 1) & (a <= janela_anos)
                        rem = np.isin(c, mata) & ~jovem
                        pasto = np.isin(c, aberto) & ~jovem
                        if rem.any():
                            lat = rasterio.windows.bounds(jan, cob.transform)
                            latc = (lat[1] + lat[3]) / 2
                            dx = res * 111320.0 * math.cos(math.radians(latc))
                            dy = res * 110574.0
                            dist = distance_transform_edt(~rem, sampling=(dy, dx))
                        else:
                            dist = np.full(c.shape, np.inf)
                        faixa = np.digitize(dist, lim).astype(np.uint8)  # 0..3
                        cod = np.zeros(c.shape, dtype=np.uint8)
                        cod[pasto] = 1 + faixa[pasto]
                        cod[jovem] = 11 + faixa[jovem]
                        miolo = cod[pad_px : pad_px + h, pad_px : pad_px + wd]
                        out.write(miolo, 1, window=Window(c0, r0, wd, h))
                        for k in range(4):
                            cont_aberto[k] += int((miolo == 1 + k).sum())
                            cont_rebrota[k] += int((miolo == 11 + k).sum())
        finally:
            if idade is not None:
                idade.close()
        d = _zonal_classes(saida, g)
    lat = g.geometry.centroid.y.values
    hp = _ha_pixel(lat, res)
    por_imovel = {}
    for i, row in d.iterrows():
        por_imovel[str(row["cod_imovel"])] = {
            f"pasto_{f}_ha": round(float(row.get(f"c{k + 1}", row.get(f"band_1_c{k + 1}", 0)) or 0) * float(hp[i]), 2)
            for k, f in enumerate(FAIXAS)
        }
    municipio = {"linha_base_fonte": "padrao"}
    if idade is not None:
        municipio["linha_base_fonte"] = f"ybyra_{YBYRA_ANO}_municipio"
        for k, f in enumerate(FAIXAS):
            tot = cont_aberto[k] + cont_rebrota[k]
            F = cont_rebrota[k] / tot if tot > 0 else 0.0
            municipio[f"linha_base_taxa_{f}"] = round(1 - (1 - F) ** (1 / janela_anos), 6) if F < 1 else 1.0
            municipio[f"linha_base_amostra_{f}_px"] = int(tot)
    for p in tmpdir.iterdir():
        p.unlink()
    tmpdir.rmdir()
    return por_imovel, municipio


# --- declividade (Copernicus GLO-30) ----------------------------------------------------------------------------


def nome_ladrilho_dem(lat: int, lon: int) -> tuple[str, str]:
    """Canto sudoeste do ladrilho de 1 grau: S02/W048 cobre lat -2 a -1 e lon -48 a -47."""
    return (f"S{-lat:02d}" if lat < 0 else f"N{lat:02d}"), (f"W{-lon:03d}" if lon < 0 else f"E{lon:03d}")


def declividade_ladrilho(lat: int, lon: int, cache: Path) -> Path | None:
    """Declividade em % (uint8, teto 250) de um ladrilho de 1 grau, a 60 m (metade da resolução do GLO-30)."""
    import rasterio
    from rasterio.enums import Resampling

    la, lo = nome_ladrilho_dem(lat, lon)
    f = cache / "dem" / f"declividade_{la}_{lo}.tif"
    vazio = f.with_suffix(".vazio")
    if f.exists():
        return f
    if vazio.exists():  # ladrilho de mar: não existe no GLO-30
        return None
    f.parent.mkdir(parents=True, exist_ok=True)
    url = "/vsicurl/" + COPERNICUS.format(lat=la, lon=lo)
    try:
        src = rasterio.open(url)
    except rasterio.errors.RasterioIOError:
        vazio.touch()
        return None
    with src:
        h, w = src.height // 2, src.width // 2
        z = src.read(1, out_shape=(h, w), resampling=Resampling.average).astype("float64")
        tr = src.transform * src.transform.scale(src.width / w, src.height / h)
    latc = lat + 0.5
    dy = abs(tr.e) * 110574.0
    dx = tr.a * 111320.0 * math.cos(math.radians(latc))
    gy, gx = np.gradient(z, dy, dx)
    decl = np.clip(np.hypot(gx, gy) * 100, 0, 250).astype("uint8")
    tmp = f.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", width=w, height=h, count=1, dtype="uint8", crs="EPSG:4326",
                       transform=tr, compress="deflate", tiled=True) as out:  # fmt: skip
        out.write(decl, 1)
    tmp.replace(f)
    return f


def declividade(geo, cache: Path | None = None) -> dict[str, float]:
    """Declividade média (%) de cada imóvel."""
    import rasterio
    from rasterio.merge import merge

    cache = cache or pasta_cache()
    g = geo.to_crs(4326).reset_index(drop=True)
    x0, y0, x1, y1 = g.total_bounds
    arqs = []
    for la in range(math.floor(y0), math.floor(y1) + 1):
        for lo in range(math.floor(x0), math.floor(x1) + 1):
            f = declividade_ladrilho(la, lo, cache)
            if f:
                arqs.append(f)
    if not arqs:
        return {}
    srcs = [rasterio.open(f) for f in arqs]
    try:
        mos, tr = merge(srcs, bounds=(x0 - 0.01, y0 - 0.01, x1 + 0.01, y1 + 0.01), nodata=255)
    finally:
        for s in srcs:
            s.close()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "decl.tif"
        with rasterio.open(f, "w", driver="GTiff", width=mos.shape[2], height=mos.shape[1], count=1, dtype="uint8",
                           crs="EPSG:4326", transform=tr, nodata=255) as out:  # fmt: skip
            out.write(mos[0], 1)
        d = _zonal_classes(f, g, ("mean",))
    media = d["mean"] if "mean" in d else d["band_1_mean"]
    return {str(c): round(float(v), 1) for c, v in zip(d.cod_imovel, media, strict=True) if v == v}


# --- chuva (CHIRPS v3) e solo (SoilGrids) -----------------------------------------------------------------------


def chuva_faixa(lat_faixa: int, cache: Path) -> Path | None:
    """Média anual (mm) de 2015 a 2024 numa faixa de 5 graus de latitude, só as longitudes do Brasil."""
    import rasterio
    from rasterio.windows import from_bounds

    f = cache / "chirps" / f"chirps3_media_{CHIRPS_ANOS[0]}_{CHIRPS_ANOS[-1]}_lat{lat_faixa}.tif"
    if f.exists():
        return f
    f.parent.mkdir(parents=True, exist_ok=True)
    y0, y1 = lat_faixa * 5, lat_faixa * 5 + 5
    soma, n, tr, shape = None, 0, None, None
    for ano in CHIRPS_ANOS:
        with rasterio.open("/vsicurl/" + CHIRPS.format(ano=ano)) as src:
            w = from_bounds(BRASIL_LON[0], y0, BRASIL_LON[1], y1, src.transform).round_offsets().round_lengths()
            a = src.read(1, window=w).astype("float64")
            a[a < 0] = np.nan
            tr, shape = src.window_transform(w), a.shape
            soma = a if soma is None else soma + a
            n += 1
    media = (soma / n).astype("float32")
    tmp = f.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", driver="GTiff", width=shape[1], height=shape[0], count=1, dtype="float32",
                       crs="EPSG:4326", transform=tr, nodata=np.nan, compress="deflate") as out:  # fmt: skip
        out.write(media, 1)
    tmp.replace(f)
    return f


def chuva(pontos: dict[str, tuple[float, float]], cache: Path | None = None) -> dict[str, float]:
    """mm por ano no ponto de cada imóvel (lon, lat)."""
    import rasterio

    cache = cache or pasta_cache()
    por_faixa: dict[int, list] = {}
    for cod, (lon, lat) in pontos.items():
        por_faixa.setdefault(math.floor(lat / 5), []).append((cod, lon, lat))
    out = {}
    for fx, itens in por_faixa.items():
        f = chuva_faixa(fx, cache)
        with rasterio.open(f) as src:
            for (cod, _, _), v in zip(itens, src.sample([(lo, la) for _, lo, la in itens]), strict=True):
                if np.isfinite(v[0]):
                    out[cod] = round(float(v[0]), 0)
    return out


def solo_cec(pontos: dict[str, tuple[float, float]], chave: str, cache: Path | None = None) -> dict[str, float]:
    """CTC (cmol(c)/kg) média ponderada de 0 a 30 cm no ponto de cada imóvel. O SoilGrids está em Homolosine; lê a
    caixa do município reprojetada para graus a ~250 m e guarda por município (chave)."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    from rasterio.windows import from_bounds

    cache = cache or pasta_cache()
    if not pontos:
        return {}
    xs = [p[0] for p in pontos.values()]
    ys = [p[1] for p in pontos.values()]
    f = cache / "soilgrids" / f"cec_0-30cm_{chave}.tif"
    if not f.exists():
        f.parent.mkdir(parents=True, exist_ok=True)
        b = (min(xs) - 0.02, min(ys) - 0.02, max(xs) + 0.02, max(ys) + 0.02)
        res = 0.0025
        w, h = max(int((b[2] - b[0]) / res), 1), max(int((b[3] - b[1]) / res), 1)
        from rasterio.transform import from_bounds as tfb

        tr = tfb(*b, w, h)
        soma, peso = np.zeros((h, w)), np.zeros((h, w))
        for prof, esp in SOILGRIDS_PROF:
            with (
                rasterio.open("/vsicurl/" + SOILGRIDS.format(prof=prof)) as src,
                WarpedVRT(src, crs="EPSG:4326", transform=tr, width=w, height=h, resampling=Resampling.bilinear) as vrt,
            ):
                a = vrt.read(1, window=from_bounds(*b, vrt.transform)).astype("float64")
                a = a[:h, :w]
                ok = (a > 0) & (a != src.nodata)
                soma[: a.shape[0], : a.shape[1]] += np.where(ok, a, 0) * esp
                peso[: a.shape[0], : a.shape[1]] += ok * esp
        cec = np.where(peso > 0, soma / np.maximum(peso, 1e-9) / 10.0, np.nan).astype("float32")  # mmol -> cmol
        tmp = f.with_suffix(".tmp.tif")
        with rasterio.open(tmp, "w", driver="GTiff", width=w, height=h, count=1, dtype="float32", crs="EPSG:4326",
                           transform=tr, nodata=np.nan, compress="deflate") as out:  # fmt: skip
            out.write(cec, 1)
        tmp.replace(f)
    out = {}
    with rasterio.open(f) as src:
        for cod, v in zip(pontos, src.sample(list(pontos.values())), strict=True):
            if np.isfinite(v[0]):
                out[cod] = round(float(v[0]), 2)
    return out


# --- tudo de um município ---------------------------------------------------------------------------------------


def entradas_municipio(
    geo,
    cod_municipio: int,
    cobertura_tif: Path | None,
    cache: Path | None = None,
    fontes: tuple[str, ...] = ("faixas", "declividade", "chuva", "solo"),
) -> tuple[dict, dict]:
    """(por imóvel, do município). Cada fonte que falhar é registrada no log e fica vazia."""
    import shapely

    cache = Path(cache or pasta_cache()).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    g = geo.to_crs(4326).reset_index(drop=True)
    g["cod_imovel"] = g.cod_imovel.astype(str)
    pts = shapely.point_on_surface(g.geometry.values)
    pontos = {c: (float(p.x), float(p.y)) for c, p in zip(g.cod_imovel, pts, strict=True)}
    por = {c: {} for c in g.cod_imovel}
    mun: dict = {}

    def junta(d: dict[str, object], nome: str | None = None):
        for c, v in d.items():
            if c in por:
                if nome:
                    por[c][nome] = v
                else:
                    por[c].update(v)

    if "faixas" in fontes and cobertura_tif and Path(cobertura_tif).exists():
        try:
            pi, mun = faixas_e_linha_base(g, cobertura_tif, pasta_tmp=cache)
            junta(pi)
        except Exception as e:  # noqa: BLE001
            log.warning("faixas de distância do município %s falharam: %s", cod_municipio, e)
    for nome, col, fn in (
        ("declividade", "declividade_media_pct", lambda: declividade(g, cache)),
        ("chuva", "chuva_mm_ano", lambda: chuva(pontos, cache)),
        ("solo", "solo_cec_cmolc_kg", lambda: solo_cec(pontos, str(cod_municipio), cache)),
    ):
        if nome not in fontes:
            continue
        try:
            junta(fn(), col)
        except Exception as e:  # noqa: BLE001
            log.warning("%s do município %s falhou: %s", nome, cod_municipio, e)
    return por, {**mun, "pontos": pontos}
