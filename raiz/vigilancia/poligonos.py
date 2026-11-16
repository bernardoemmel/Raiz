"""Polígonos do CAR publicados pelo motor no Release `dados` (docs/dados-publicados.md).

Lê o estados.json, baixa `raiz_geo_<UF>.tar.gz` (geo_<cod>.parquet: cod_imovel + polígono em EPSG:5880) e
`raiz_<UF>.tar.gz` (imoveis_<cod>.csv) só quando a versão publicada muda, e guarda um índice com a caixa de cada
município. O cruzamento abre só os municípios cuja caixa toca algum alerta, um por vez (memória baixa).

Colunas do imóvel lidas pelo nome (docs/colunas.md), tolerando colunas novas e faltantes. Nenhuma fazenda é
descartada por tamanho: todo imóvel do arquivo entra.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tarfile
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

from raiz.vigilancia import rede
from raiz.vigilancia.config import Config, config

log = logging.getLogger(__name__)

CRS_METROS = 5880
COLUNAS_IMOVEL = [
    "cod_imovel",
    "uf",
    "municipio",
    "cod_municipio_ibge",
    "ha",
    "m_fiscal",
    "tipo_imovel",
    "condicao",
    "status_imovel",
    "frente",
    "projeto_carbono_ha",
]
_COD = re.compile(r"^([A-Z]{2})-(\d{7})-[0-9A-F.]+$", re.I)


def uf_mun_do_codigo(cod_imovel: str) -> tuple[str, int] | None:
    """O código do CAR já traz a UF e o município: PA-1507300-F293... -> (PA, 1507300)."""
    m = _COD.match(str(cod_imovel).strip())
    return (m.group(1).upper(), int(m.group(2))) if m else None


def _extrair(pacote: Path, destino: Path) -> None:
    tmp = destino.with_name(destino.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(pacote) as tar:
        tar.extractall(tmp, filter="data")  # recusa caminho absoluto, '..' e link
    shutil.rmtree(destino, ignore_errors=True)
    tmp.rename(destino)


class Poligonos:
    def __init__(self, cfg: Config | None = None, ufs: list[str] | None = None):
        from raiz.executor.armazem import ArmazemRelease, destino_privado

        self.cfg = cfg or config()
        self.pasta = self.cfg.cache / "poligonos"
        self.pasta.mkdir(parents=True, exist_ok=True)
        self._so = set(ufs) if ufs else None
        destino = destino_privado()
        self._privado = (
            ArmazemRelease(
                *destino,
                espelho=self.pasta / "arquivo_privado",
                privado=True,
                token=os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN") or self.cfg.token_github or "",
            )
            if destino
            else None
        )
        self.manifesto = self._manifesto()

    def _manifesto(self) -> dict:
        if self._privado:
            return self._privado.manifesto(fresco=True)
        local = self.pasta / "estados.json"
        try:
            rede.baixar(self.cfg.url_release(self.cfg.tag_dados, "estados.json"), local, condicional=False)
        except Exception as ex:
            if not local.exists():
                log.warning("sem estados.json do Release dados: %s", ex)
                return {"estados": {}}
            log.warning("estados.json: servidor falhou, usando a cópia guardada")
        return json.loads(local.read_text(encoding="utf-8"))

    def ufs(self) -> list[str]:
        e = self.manifesto.get("estados", {})
        return sorted(uf for uf, i in e.items() if i.get("geo") and (self._so is None or uf in self._so))

    def versao(self, uf: str) -> str:
        i = self.manifesto.get("estados", {}).get(uf, {})
        return f"{i.get('geo', {}).get('versao', '')}+{i.get('versao', '')}"

    def versoes(self) -> dict[str, str]:
        return {uf: self.versao(uf) for uf in self.ufs()}

    def preparar(self, uf: str) -> Path:
        """Pasta com geo_*.parquet e imoveis_*.csv da UF na versão publicada (baixa só se mudou)."""
        i = self.manifesto["estados"][uf]
        pasta = self.pasta / uf
        marca = pasta / ".versao"
        v = self.versao(uf)
        if marca.exists() and marca.read_text() == v:
            return pasta
        baixados = self.pasta / "pacotes"
        geo = baixados / f"raiz_geo_{uf}.tar.gz"
        csv = baixados / f"raiz_{uf}.tar.gz"
        if self._privado:
            baixados.mkdir(parents=True, exist_ok=True)
            for nome, destino in ((f"raiz_geo_{uf}.tar.gz", geo), (f"raiz_{uf}.tar.gz", csv)):
                dados = self._privado._baixar_asset(nome)
                if dados is None:
                    raise FileNotFoundError(f"arquivo privado incompleto: {nome}")
                destino.write_bytes(dados)
        else:
            rede.baixar(i["geo"]["url"], geo, condicional=False)
            if i.get("url"):
                rede.baixar(i["url"], csv, condicional=False)
        tmp = self.pasta / f"{uf}.novo"
        _extrair(geo, tmp)
        if csv.exists():
            with tarfile.open(csv) as tar:
                membros = [m for m in tar.getmembers() if re.search(r"/imoveis_\d{7}\.csv$", m.name) and m.isfile()]
                tar.extractall(tmp, members=membros, filter="data")
        geo.unlink(missing_ok=True)
        csv.unlink(missing_ok=True)
        # os pacotes têm uma pasta <UF>/ dentro
        dentro = tmp / uf if (tmp / uf).is_dir() else tmp
        shutil.rmtree(pasta, ignore_errors=True)
        dentro.rename(pasta)
        shutil.rmtree(tmp, ignore_errors=True)
        (pasta / "indice.json").unlink(missing_ok=True)
        marca.write_text(v)
        self.indice.cache_clear()
        return pasta

    @lru_cache(maxsize=64)  # noqa: B019 (uma instância por rodada)
    def indice(self, uf: str) -> dict[int, list[float]]:
        """Caixa (graus, EPSG:4674) de cada município da UF: {cod_ibge: [x0, y0, x1, y1]}."""
        pasta = self.preparar(uf)
        arq = pasta / "indice.json"
        if arq.exists():
            return {int(k): v for k, v in json.loads(arq.read_text()).items()}
        out = {}
        for f in sorted(pasta.glob("geo_*.parquet")):
            cod = int(re.search(r"geo_(\d{7})", f.name).group(1))
            g = gpd.read_parquet(f, columns=["geometry"])
            if len(g):
                out[cod] = [round(v, 6) for v in g.to_crs(4674).total_bounds.tolist()]
        arq.write_text(json.dumps(out))
        return out

    def imoveis(self, uf: str, cod_ibge: int) -> gpd.GeoDataFrame:
        """Imóveis do município: cod_imovel, colunas de identificação (pelo nome) e polígono em EPSG:5880."""
        pasta = self.preparar(uf)
        f = pasta / f"geo_{cod_ibge}.parquet"
        if not f.exists():
            return gpd.GeoDataFrame({"cod_imovel": []}, geometry=[], crs=CRS_METROS)
        g = gpd.read_parquet(f)
        g = g[["cod_imovel", "geometry"]].to_crs(CRS_METROS)
        g["alvo_ha"] = g.area / 1e4
        info = self._info_municipio(uf, cod_ibge)
        if len(info):
            g = g.merge(info.drop(columns=[c for c in ("geometry",) if c in info]), on="cod_imovel", how="left")
        if "uf" not in g or g["uf"].isna().all():
            g["uf"] = uf
        if "cod_municipio_ibge" not in g or g["cod_municipio_ibge"].isna().all():
            g["cod_municipio_ibge"] = cod_ibge
        return g

    @lru_cache(maxsize=32)  # noqa: B019
    def _info_municipio(self, uf: str, cod_ibge: int) -> pd.DataFrame:
        f = self.pasta / uf / f"imoveis_{cod_ibge}.csv"
        if not f.exists():
            return pd.DataFrame()
        cab = pd.read_csv(f, nrows=0).columns
        usar = [c for c in COLUNAS_IMOVEL if c in cab]
        return pd.read_csv(f, usecols=usar, dtype={"cod_imovel": str}).drop_duplicates("cod_imovel")

    def info_imovel(self, cod_imovel: str) -> dict | None:
        um = uf_mun_do_codigo(cod_imovel)
        if not um or um[0] not in self.ufs():
            return None
        uf, cod = um
        self.preparar(uf)
        info = self._info_municipio(uf, cod)
        linha = info[info["cod_imovel"] == cod_imovel] if len(info) else info
        if not len(linha):
            g = self.imoveis(uf, cod)
            if cod_imovel not in set(g["cod_imovel"]):
                return None
            return {"cod_imovel": cod_imovel, "uf": uf, "cod_municipio_ibge": cod}
        d = {k: (None if pd.isna(v) else v) for k, v in linha.iloc[0].to_dict().items()}
        d.setdefault("uf", uf)
        d.setdefault("cod_municipio_ibge", cod)
        return d

    def geometria_imoveis(self, cods: list[str]) -> gpd.GeoDataFrame:
        """Polígonos de uma lista de imóveis (para projeto que é grupo de fazendas), em EPSG:5880."""
        por_mun: dict[tuple[str, int], list[str]] = {}
        for c in cods:
            um = uf_mun_do_codigo(c)
            if um and um[0] in self.ufs():
                por_mun.setdefault(um, []).append(c)
        partes = []
        for (uf, cod), lista in por_mun.items():
            g = self.imoveis(uf, cod)
            partes.append(g[g["cod_imovel"].isin(lista)][["cod_imovel", "geometry"]])
        if not partes:
            return gpd.GeoDataFrame({"cod_imovel": []}, geometry=[], crs=CRS_METROS)
        return gpd.GeoDataFrame(pd.concat(partes, ignore_index=True), geometry="geometry", crs=CRS_METROS)
