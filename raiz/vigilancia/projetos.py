"""Projetos vigiados: cadastro público (projetos.yaml) mais o arquivo privado (RAIZ_PROJETOS_PRIVADO), e a área de cada
projeto separada por papel: `projeto` (área de carbono: perda aqui é evento de perda da Verra), `entorno` (aceiro,
estrada: só avisa) e `fora` (área não disponível; não conta).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import shapely
import yaml

from raiz.vigilancia import PASTA, kml, rede
from raiz.vigilancia.config import Config, config
from raiz.vigilancia.fontes import so_area_vetor

log = logging.getLogger(__name__)

ARQUIVO = PASTA / "projetos.yaml"
CRS_METROS = 5880  # SIRGAS 2000 / Brazil Polyconic, o mesmo dos polígonos do motor
CRS_GRAUS = 4674  # SIRGAS 2000 em graus


def _data(v) -> dt.date | None:
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


@dataclass
class Projeto:
    id: str
    dados: dict
    privado: bool = False  # só existe no arquivo privado: nada dele vai para o Release aberto

    def get(self, k, padrao=None):
        return self.dados.get(k, padrao)

    @property
    def nome(self) -> str:
        return str(self.dados.get("nome_projeto") or self.id)

    @property
    def inicio(self) -> dt.date | None:
        return _data(self.dados.get("inicio"))

    @property
    def classes_projeto(self) -> list[str]:
        return [str(c) for c in self.dados.get("classes_projeto") or []]

    @property
    def classes_entorno(self) -> list[str]:
        return [str(c) for c in self.dados.get("classes_entorno") or []]

    def papel(self, classe: str) -> str:
        if self.dados.get("imoveis") and not self.dados.get("poligono"):
            return "projeto"  # grupo de imóveis: tudo é área do projeto
        if not self.classes_projeto:
            return "projeto"  # polígono sem classes: o polígono inteiro é o projeto
        if classe in self.classes_projeto:
            return "projeto"
        if classe in self.classes_entorno:
            return "entorno"
        return "fora"

    def estoque(self, classe: str) -> float | None:
        e = self.dados.get("estoque_tco2e_ha")
        if isinstance(e, dict):
            v = e.get(classe, e.get("padrao"))
            return float(v) if v is not None else None
        return float(e) if e is not None else None

    def publico(self) -> dict:
        """O que pode sair no Release aberto (só para projeto que já está no cadastro público)."""
        campos = ("id", "nome_projeto", "padrao", "verra_id", "inicio", "classes_projeto", "classes_entorno")
        return {k: self.dados.get(k) for k in campos if k in self.dados}


def _ler_yaml(texto_ou_caminho: str | None) -> list[dict]:
    if not texto_ou_caminho:
        return []
    t = texto_ou_caminho
    if "\n" not in t and Path(t).exists():
        t = Path(t).read_text(encoding="utf-8")
    d = yaml.safe_load(t) or {}
    return list(d.get("projetos") or []) if isinstance(d, dict) else list(d)


def carregar(arquivo: Path | str | None = None, privado: str | None = None) -> list[Projeto]:
    """Cadastro público mais o privado (o privado completa e sobrescreve pelo id; projeto só privado é privado)."""
    publicos = _ler_yaml(str(arquivo or ARQUIVO))
    extras = _ler_yaml(privado if privado is not None else os.environ.get("RAIZ_PROJETOS_PRIVADO"))
    por_id: dict[str, Projeto] = {}
    for p in publicos:
        por_id[str(p["id"])] = Projeto(str(p["id"]), dict(p), privado=False)
    for p in extras:
        pid = str(p["id"])
        if pid in por_id:
            por_id[pid].dados.update(p)
        else:
            por_id[pid] = Projeto(pid, dict(p), privado=True)
    return list(por_id.values())


def _conteudo_poligono(pol: dict, cfg: Config) -> tuple[bytes, str]:
    if pol.get("caminho"):
        p = Path(pol["caminho"])
        if not p.is_absolute():
            p = PASTA.parents[1] / p
        return p.read_bytes(), p.suffix.lower()
    url = pol.get("url") or cfg.url_release(pol.get("release") or cfg.tag_dados, pol["arquivo"])
    nome = Path(url.split("?")[0]).name
    destino = cfg.cache / "projetos" / nome
    try:
        rede.baixar(url, destino)
    except Exception:
        if not destino.exists():
            raise
        log.warning("polígono %s: servidor falhou, usando a cópia guardada", nome)
    return destino.read_bytes(), Path(nome).suffix.lower()


def areas(
    projeto: Projeto,
    cfg: Config | None = None,
    imoveis: Callable[[list[str]], gpd.GeoDataFrame] | None = None,
) -> gpd.GeoDataFrame:
    """Área do projeto em EPSG:5880, uma linha por classe: projeto_id, classe, papel, geometry."""
    cfg = cfg or config()
    linhas = []
    pol = projeto.get("poligono")
    if pol:
        conteudo, ext = _conteudo_poligono(pol, cfg)
        campo = pol.get("campo_classe")
        if ext in (".geojson", ".json"):
            fc = json.loads(conteudo)
            itens = [
                {
                    "nome": str(f.get("properties", {}).get("name", "")),
                    "campos": f.get("properties") or {},
                    "geometria": shapely.geometry.shape(f["geometry"]),
                }
                for f in fc.get("features", [])
                if f.get("geometry")
            ]
        else:
            itens = kml.ler(conteudo)
        for it in itens:
            classe = str((it["campos"].get(campo) if campo else None) or it["nome"] or "projeto")
            try:
                declarado = float(str(it["campos"].get("area_ha", "")).replace(",", "."))
            except ValueError:
                declarado = None
            linhas.append({"classe": classe, "declarado_ha": declarado, "geometry": it["geometria"]})
        g = gpd.GeoDataFrame(linhas, geometry="geometry", crs=CRS_GRAUS).to_crs(CRS_METROS)
    else:
        cods = [str(c) for c in projeto.get("imoveis") or []]
        if not cods:
            raise ValueError(f"projeto {projeto.id}: sem polígono e sem imóveis")
        if imoveis is None:
            raise ValueError(f"projeto {projeto.id}: precisa dos polígonos do CAR para montar a área")
        g = imoveis(cods)
        faltam = sorted(set(cods) - set(g["cod_imovel"]))
        if faltam:
            log.warning("projeto %s: %d imóveis sem polígono no Release dados", projeto.id, len(faltam))
        g = g.rename(columns={"cod_imovel": "classe"})[["classe", "geometry"]].to_crs(CRS_METROS)
    if "declarado_ha" not in g:
        g["declarado_ha"] = None
    g["geometry"] = so_area_vetor(g.geometry.values)
    g = g[g.geometry.notna()]
    g = g.dissolve("classe", as_index=False, aggfunc={"declarado_ha": lambda s: s.sum(min_count=1)})
    g["papel"] = [projeto.papel(c) for c in g["classe"]]
    g["projeto_id"] = projeto.id
    g["ha"] = g.area / 1e4
    return g[["projeto_id", "classe", "papel", "ha", "declarado_ha", "geometry"]]


def conferir_areas(g: gpd.GeoDataFrame, tolerancia: float = 0.2) -> list[str]:
    """Avisos de qualidade do polígono: classe cuja área medida passa da declarada no arquivo em mais de 20%."""
    avisos = []
    for _, r in g.iterrows():
        d = r.get("declarado_ha")
        if d is not None and d == d and d > 0 and abs(r["ha"] - d) / d > tolerancia:
            avisos.append(
                f"{r['classe']}: o polígono mede {r['ha']:.0f} ha e o arquivo declara {d:.0f} ha; conferir o traçado "
                "(buraco perdido na exportação ou classes sobrepostas)"
            )
    return avisos
