"""APP de relevo pelo ANADEM: encosta com mais de 45 graus (Lei 12.651/2012, art. 4º, V) e topo de morro (art. 4º, IX).

Topo de morro, pela lei: morro ou montanha com altura mínima de 100 m e inclinação média maior que 25 graus; a APP
fica acima da curva de nível de 2/3 da altura, contada da base, que é a planície ou espelho d'água adjacente ou, no
relevo ondulado, a cota do ponto de sela mais próximo da elevação.

Como se calcula (sem código de terceiros): inundação de cima para baixo com união de conjuntos. As células são
visitadas da mais alta para a mais baixa; cada cume começa um conjunto. Quando dois conjuntos se tocam numa célula,
essa célula é o ponto de sela do conjunto de cume mais baixo, que termina ali: altura = cume - sela; domínio do morro =
as células que já eram dele. Morro que não termina dentro do bloco (encosta até a planície ou até a borda) usa como
base a cota mais baixa do próprio domínio. Um morro pequeno em cima de outro grande conta para os dois (a APP do
grande inclui o terço de cima, onde estiver o pequeno).

Leitura: o ANADEM v1 (Laipelt et al. 2024; ANA/UFRGS) é um GeoTIFF em blocos por zona UTM e faixa de latitude, lido
por janela via HTTP (só os blocos que tocam os imóveis). Sem ANADEM, usa o Copernicus GLO-30, que é superfície (com a
copa) e marca relevo_fonte = copernicus_dsm.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

COPERNICUS = (
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/"
    "Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
)
_BANDAS = "CDEFGHJKLMNPQRSTUVWX"
GDAL_HTTP = dict(
    GDAL_HTTP_MAX_RETRY="4",
    GDAL_HTTP_RETRY_DELAY="2",
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MULTIPLEX="YES",
    GDAL_HTTP_VERSION="2",
)


def tile_anadem(lon: float, lat: float) -> str:
    """Nome do bloco do ANADEM (zona UTM + faixa de latitude do MGRS), ex.: -51.9, -6.6 -> 22M."""
    zona = int(math.floor((lon + 180) / 6)) + 1
    banda = _BANDAS[min(max(int(math.floor((lat + 80) / 8)), 0), len(_BANDAS) - 1)]
    return f"{zona}{banda}"


# --- geometria do terreno ---------------------------------------------------------------------------------------


def tamanho_celula(transform, linhas: int) -> tuple[np.ndarray, float]:
    """(dx em metros por linha, dy em metros) de um raster em graus."""
    lat = transform.f + transform.e * (np.arange(linhas) + 0.5)
    dx = abs(transform.a) * 111320.0 * np.cos(np.radians(lat))
    dy = abs(transform.e) * 110574.0
    return dx, dy


def declividade_graus(z: np.ndarray, dx: np.ndarray, dy: float) -> np.ndarray:
    """Declividade (graus) por diferenças centradas; dx varia por linha (graus -> metros)."""
    gy, gx = np.gradient(z, axis=(0, 1))
    gx = gx / dx[:, None]
    gy = gy / dy
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def _njit(f):
    try:
        from numba import njit

        return njit(cache=False)(f)
    except ImportError:  # pragma: no cover
        return f


@_njit
def _inundar(zf, valido, nl, nc):  # pragma: no cover - compilado
    n = nl * nc
    ordem = np.argsort(-zf)
    pai_uf = np.full(n, -1, np.int64)  # união de conjuntos sobre células (raiz = célula do cume)
    folha = np.full(n, -1, np.int64)  # conjunto (cume) a que a célula se juntou ao ser visitada
    sela = np.full(n, np.nan)  # por cume: cota onde o conjunto terminou
    pai = np.full(n, -1, np.int64)  # por cume: conjunto que o absorveu
    ordem_fim = np.full(n, -1, np.int64)
    nfim = 0
    raizes = np.empty(8, np.int64)
    for k in range(n):
        c = ordem[k]
        if not valido[c]:
            continue
        i = c // nc
        j = c % nc
        nr = 0
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if di == 0 and dj == 0:
                    continue
                ii = i + di
                jj = j + dj
                if ii < 0 or jj < 0 or ii >= nl or jj >= nc:
                    continue
                v = ii * nc + jj
                if pai_uf[v] < 0:
                    continue
                r = v
                while pai_uf[r] != r:
                    pai_uf[r] = pai_uf[pai_uf[r]]
                    r = pai_uf[r]
                novo = True
                for q in range(nr):
                    if raizes[q] == r:
                        novo = False
                if novo:
                    raizes[nr] = r
                    nr += 1
        if nr == 0:
            pai_uf[c] = c
            folha[c] = c
            continue
        # sobrevive o conjunto de cume mais alto; os outros terminam nesta célula (ponto de sela)
        melhor = raizes[0]
        for q in range(1, nr):
            if zf[raizes[q]] > zf[melhor]:
                melhor = raizes[q]
        for q in range(nr):
            r = raizes[q]
            if r != melhor:
                sela[r] = zf[c]
                pai[r] = melhor
                pai_uf[r] = melhor
                ordem_fim[nfim] = r
                nfim += 1
        pai_uf[c] = melhor
        folha[c] = melhor
    return folha, sela, pai, ordem_fim[:nfim]


def app_relevo(z: np.ndarray, dx: np.ndarray, dy: float, regra: dict):
    """(máscara de declividade > 45°, máscara de topo de morro) num bloco de elevação em graus.
    z: elevação (nan = sem dado). O morro que não fecha dentro do bloco usa a cota mais baixa do domínio como base
    (a borda de contexto em volta do bloco serve para isso)."""
    rr = regra["relevo"]
    valido = np.isfinite(z)
    decl = declividade_graus(np.where(valido, z, np.nanmean(z) if valido.any() else 0.0), dx, dy)
    mdecl = valido & (decl > rr["declividade_graus"])
    nl, nc = z.shape
    topo = np.zeros(z.shape, bool)
    if not valido.any() or np.nanmax(z) - np.nanmin(z) < rr["topo_altura_m"]:
        return mdecl, topo
    zf = np.where(valido, z, -1e9).ravel().astype(np.float64)
    folha, sela, pai, ordem_fim = _inundar(zf, valido.ravel(), nl, nc)
    ok = folha >= 0
    n = nl * nc
    # somas por conjunto (folha), depois sobe a árvore na ordem em que os conjuntos terminaram
    cnt = np.bincount(folha[ok], minlength=n).astype(np.float64)
    sd = np.bincount(folha[ok], weights=decl.ravel()[ok], minlength=n)
    zmin = np.full(n, np.inf)
    np.minimum.at(zmin, folha[ok], zf[ok])
    for r in ordem_fim:
        p = pai[r]
        cnt[p] += cnt[r]
        sd[p] += sd[r]
        zmin[p] = min(zmin[p], zmin[r])
    cumes = np.unique(folha[ok])
    base = np.where(np.isnan(sela), zmin, sela)
    altura = zf - base
    media = np.divide(sd, cnt, out=np.zeros(n), where=cnt > 0)
    # morro que não fechou (raiz da árvore): a planície em volta, na cota da base, não é morro; a inclinação média
    # conta só o que está acima dela
    topo_de = np.arange(n)
    for r in ordem_fim[::-1]:
        topo_de[r] = topo_de[pai[r]]
    raiz_cel = np.full(n, -1)
    raiz_cel[ok] = topo_de[folha[ok]]
    for r in cumes[np.isnan(sela[cumes])]:
        m = (raiz_cel == r) & (zf > base[r] + 1.0)
        media[r] = decl.ravel()[m].mean() if m.any() else 0.0
    qualifica = np.zeros(n, bool)
    qualifica[cumes] = (altura[cumes] >= rr["topo_altura_m"]) & (media[cumes] > rr["topo_inclinacao_graus"])
    limiar = np.full(n, np.inf)
    limiar[qualifica] = base[qualifica] + rr["topo_fracao"] * altura[qualifica]
    # de cima para baixo: o limiar de um conjunto é o menor entre o dele e o dos que o absorveram
    for r in ordem_fim[::-1]:
        limiar[r] = min(limiar[r], limiar[pai[r]])
    t = np.zeros(n, bool)
    t[ok] = zf[ok] >= limiar[folha[ok]]
    topo = t.reshape(z.shape)
    return mdecl, topo


# --- leitura por blocos ------------------------------------------------------------------------------------------


def _abrir(url: str):
    import rasterio

    try:
        with rasterio.Env(**GDAL_HTTP):
            return rasterio.open(url)
    except rasterio.errors.RasterioIOError:
        return None


def ler_elevacao(caixa, regra: dict, fonte: str = "anadem"):
    """(z float64 com nan, transform, fonte) da caixa (lon0, lat0, lon1, lat1). Junta blocos vizinhos do ANADEM
    (ou do GLO-30) quando a caixa cruza a divisa deles. None quando nenhuma fonte responde."""
    import rasterio
    from rasterio.merge import merge

    x0, y0, x1, y1 = caixa
    if fonte == "anadem":
        nomes = {tile_anadem(x, y) for x in (x0, x1) for y in (y0, y1)}
        urls = ["/vsicurl/" + regra["relevo"]["anadem_url"].format(tile=t) for t in sorted(nomes)]
    else:
        urls = []
        for la in range(math.floor(y0), math.floor(y1) + 1):
            for lo in range(math.floor(x0), math.floor(x1) + 1):
                ns, ew = ("N" if la >= 0 else "S"), ("E" if lo >= 0 else "W")
                urls.append("/vsicurl/" + COPERNICUS.format(lat=f"{ns}{abs(la):02d}", lon=f"{ew}{abs(lo):03d}"))
    srcs = [s for s in (_abrir(u) for u in urls) if s is not None]
    if not srcs:
        return None
    try:
        with rasterio.Env(**GDAL_HTTP):
            mos, tr = merge(srcs, bounds=(x0, y0, x1, y1), nodata=-9999.0, dtype="float32")
    finally:
        for s in srcs:
            s.close()
    z = mos[0].astype(np.float64)
    z[(z <= -9000) | (z > 9000)] = np.nan
    return z, tr, fonte


def blocos(caixa, passo: float) -> list[tuple[float, float, float, float]]:
    x0, y0, x1, y1 = caixa
    out = []
    for i in range(max(1, math.ceil((x1 - x0) / passo))):
        for j in range(max(1, math.ceil((y1 - y0) / passo))):
            out.append((x0 + i * passo, y0 + j * passo, min(x0 + (i + 1) * passo, x1), min(y0 + (j + 1) * passo, y1)))
    return out


def _aberto_mapbiomas(cobertura_tif, tr, forma, classes) -> np.ndarray | None:
    """Máscara 'aberto' do MapBiomas reamostrada (vizinho mais próximo) na grade do bloco."""
    if not cobertura_tif:
        return None
    import rasterio
    from rasterio.warp import Resampling, reproject

    destino = np.zeros(forma, np.uint8)
    with rasterio.open(cobertura_tif) as src:
        reproject(rasterio.band(src, 1), destino, dst_transform=tr, dst_crs="EPSG:4326",
                  resampling=Resampling.nearest)  # fmt: skip
    return np.isin(destino, list(classes))


def por_imovel(car, regra: dict, cobertura_tif=None, leitor=None) -> pd.DataFrame:
    """Hectares de APP de declividade, de topo de morro, da união das duas e da parte aberta (MapBiomas) por imóvel.
    leitor(caixa) -> (z, transform, fonte) | None; padrão: ANADEM com o GLO-30 de reserva."""
    import shapely
    from rasterio.features import geometry_mask

    rr = regra["relevo"]
    g = car[["cod_imovel", "geometry"]].to_crs(4326).reset_index(drop=True)
    cods = g.cod_imovel.astype(str).values
    soma = {k: np.zeros(len(g)) for k in ("app_declividade_ha", "app_topo_morro_ha", "app_relevo_ha",
                                          "app_relevo_aberta_ha")}  # fmt: skip
    coberto = np.zeros(len(g), bool)
    fontes: set[str] = set()
    if not len(g):
        return pd.DataFrame({"cod_imovel": cods, **soma})
    if leitor is None:

        def leitor(cx):
            return ler_elevacao(cx, regra, "anadem") or ler_elevacao(cx, regra, "copernicus")

    sidx = g.sindex
    passo, borda = float(rr["bloco_graus"]), float(rr["borda_graus"])
    aberto_ok = cobertura_tif is not None
    for b in blocos(tuple(g.total_bounds), passo):
        nucleo = shapely.box(*b)
        dentro = sidx.query(nucleo, predicate="intersects")
        if not len(dentro):
            continue
        cx = (b[0] - borda, b[1] - borda, b[2] + borda, b[3] + borda)
        lido = leitor(cx)
        if lido is None:
            continue
        z, tr, fonte = lido
        fontes.add(fonte)
        nl, nc = z.shape
        dx, dy = tamanho_celula(tr, nl)
        md, mt = app_relevo(z, dx, dy, regra)
        ab = _aberto_mapbiomas(cobertura_tif, tr, z.shape, rr["mapbiomas_aberto"]) if aberto_ok else None
        area_cel = (dx * dy / 1e4)[:, None] * np.ones((1, nc))
        # só o núcleo do bloco conta (a borda é contexto e é núcleo do vizinho)
        nuc = ~geometry_mask([nucleo], out_shape=z.shape, transform=tr, all_touched=False)
        for i in dentro:
            geom = g.geometry.values[i]
            if geom is None or geom.is_empty:
                continue
            m = ~geometry_mask([geom], out_shape=z.shape, transform=tr, all_touched=False) & nuc
            if not m.any():
                continue
            coberto[i] = True
            a = area_cel[m]
            soma["app_declividade_ha"][i] += float(a[md[m]].sum())
            soma["app_topo_morro_ha"][i] += float(a[mt[m]].sum())
            uni = (md | mt)[m]
            soma["app_relevo_ha"][i] += float(a[uni].sum())
            if ab is not None:
                soma["app_relevo_aberta_ha"][i] += float(a[uni & ab[m]].sum())
    out = pd.DataFrame({"cod_imovel": cods, **{k: np.round(v, 4) for k, v in soma.items()}})
    for k in soma:
        out.loc[~coberto, k] = np.nan
    if not aberto_ok:
        out["app_relevo_aberta_ha"] = np.nan
    out["relevo_fonte"] = ("anadem_v1" if fontes == {"anadem"} else "copernicus_dsm" if fontes == {"copernicus"}
                           else "anadem_v1+copernicus_dsm" if fontes else None)  # fmt: skip
    out.loc[~coberto, "relevo_fonte"] = None
    return out
