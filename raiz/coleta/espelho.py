"""Espelho local da coleta em Parquet POR MUNICÍPIO (nunca um arquivo único: com 1% dos imóveis mudando, um arquivo
único regrava 99,9% dos bytes; por município, só os municípios que mudaram são regravados).

    <raiz>/<camada>/<UF>/<cod_municipio>.parquet      (GeoParquet, ordenado pela chave)

Gravar = MERGE do DuckDB (1.4+) entre o que está no arquivo e o que acabou de chegar, comparando um hash por linha
(hash() do DuckDB sobre os campos estáveis e a geometria normalizada em WKB). O RETURNING diz quem entrou, mudou ou
saiu; se nada mudou, o arquivo não é tocado. O hash é recalculado dos dois lados a cada gravação, então não depende
de a função hash() do DuckDB ser igual entre versões.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import shapely

from raiz.privacidade import remover_colunas_pessoais

GEOM = "geometry"


@dataclass
class Diferenca:
    novos: list[str] = field(default_factory=list)
    mudaram: list[str] = field(default_factory=list)
    sumiram: list[str] = field(default_factory=list)
    total: int = 0
    escreveu: bool = False
    removidas_pessoais: list[str] = field(default_factory=list)

    @property
    def mudou(self) -> bool:
        return bool(self.novos or self.mudaram or self.sumiram)


class Espelho:
    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def caminho(self, camada: str, uf: str, cod: int) -> Path:
        return self.raiz / camada / uf.upper() / f"{int(cod)}.parquet"

    def ler(self, camada: str, uf: str, cod: int) -> gpd.GeoDataFrame | None:
        f = self.caminho(camada, uf, cod)
        return gpd.read_parquet(f) if f.exists() else None

    def gravar(
        self, camada: str, uf: str, cod: int, novo: gpd.GeoDataFrame, chave: str, volateis: tuple[str, ...] = ()
    ) -> Diferenca:
        """Substitui o conteúdo do município por `novo` (o retrato completo) e devolve a diferença."""
        novo, pessoais = remover_colunas_pessoais(novo)
        novo = novo.drop_duplicates(chave)
        if novo.crs is not None:
            novo = novo.to_crs(4674)
        atual = self.ler(camada, uf, cod)
        dif = Diferenca(removidas_pessoais=pessoais)
        cols = [c for c in novo.columns if c != GEOM]
        if atual is not None:
            cols = cols + [c for c in atual.columns if c != GEOM and c not in cols]
        estaveis = [c for c in cols if c != chave and c not in volateis]

        con = duckdb.connect()
        con.register("_novo", _tabela(novo, cols))
        con.execute("create table novo as select * from _novo")
        if atual is not None:
            con.register("_atual", _tabela(atual.to_crs(4674) if atual.crs else atual, cols))
            con.execute("create table atual as select * from _atual")
        else:
            con.execute("create table atual as select * from novo where false")

        def h(lado: str) -> str:
            return "hash(" + ", ".join([f"{lado}._wkb"] + [f'cast({lado}."{c}" as varchar)' for c in estaveis]) + ")"

        try:
            acoes = self._merge(con, chave, h)
        except duckdb.Error:
            # tipo de coluna mudou na fonte: troca o arquivo inteiro e conta todos os que ficaram como "mudaram"
            con.execute("drop table atual")
            antes = set() if atual is None else set(atual[chave].astype(str))
            agora = set(novo[chave].astype(str))
            acoes = [("INSERT", k) for k in agora - antes] + [("DELETE", k) for k in antes - agora]
            acoes += [("UPDATE", k) for k in agora & antes]
            con.execute("create table atual as select * from novo")
        for acao, k in acoes:
            {"INSERT": dif.novos, "UPDATE": dif.mudaram, "DELETE": dif.sumiram}[acao].append(str(k))
        dif.total = con.execute("select count(*) from atual").fetchone()[0]
        if dif.mudou or atual is None:
            final = con.execute(f'select * from atual order by "{chave}"').fetch_df()
            self._escrever(camada, uf, cod, _geodf(final))
            dif.escreveu = True
        con.close()
        return dif

    @staticmethod
    def _merge(con, chave: str, h) -> list:
        return con.execute(f"""
            merge into atual using novo on atual."{chave}" = novo."{chave}"
            when matched and {h("atual")} <> {h("novo")} then update set *
            when not matched then insert *
            when not matched by source then delete
            returning merge_action, "{chave}" """).fetchall()

    def _escrever(self, camada: str, uf: str, cod: int, g: gpd.GeoDataFrame) -> None:
        f = self.caminho(camada, uf, cod)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(f".{os.getpid()}.tmp")
        g.to_parquet(tmp, index=False)
        os.replace(tmp, f)


def _tabela(g: gpd.GeoDataFrame, cols: list[str]) -> pd.DataFrame:
    """Colunas na mesma ordem dos dois lados (faltando = nulo) e geometria normalizada em WKB."""
    df = pd.DataFrame({c: (g[c] if c in g.columns else pd.Series([None] * len(g), index=g.index)) for c in cols})
    geoms = g.geometry.values if GEOM in g.columns else [None] * len(g)
    df["_wkb"] = [
        None if x is None or x is pd.NA else shapely.to_wkb(shapely.normalize(x), output_dimension=2) for x in geoms
    ]
    return df.reset_index(drop=True)


def _geodf(df: pd.DataFrame) -> gpd.GeoDataFrame:
    geom = [
        None if b is None or b is pd.NA or (isinstance(b, float) and b != b) else shapely.from_wkb(bytes(b))
        for b in df.pop("_wkb")
    ]
    return gpd.GeoDataFrame(df, geometry=geom, crs=4674)
