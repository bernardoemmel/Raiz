"""As tarefas do motor e do produto para o executor, com o que muda cada uma.

versão = hash dos arquivos de código de que a tarefa depende (e da regra, quando há uma: FLAG, caminho da terra,
premissas de restauração). Mexeu em motor/raiz_filtros.py: só filtros (e o que usa a saída de filtros, se ela mudar)
roda de novo; o funil fica.
fontes externas por município (assinatura barata):
  funil      CAR, SIGEF e embargos do espelho do município (sha256), alertas do MapBiomas do estado recortados na caixa
             do município, cobertura e desmatamento do MapBiomas do estado (tamanho e data)
  filtros    terras indígenas, quilombos e unidades de conservação (arquivos nacionais do cache)
  mapbiomas  os GeoTIFFs do estado (coleção nova muda tudo, uma vez por ano)
  terra      SIGEF do espelho, Cadastro Nacional de Florestas Públicas do estado, UC, TI e quilombos
  ficha e desenvolvedor: cobertura do MapBiomas do estado
A tarefa "carga" não entra aqui: o back-end carrega a partir do armazém (raiz/executor/sincronizar.py).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from raiz import MOTOR_DIR, RAIZ_REPO
from raiz.executor.executor import Tarefa, assinatura_arquivo, sha_texto

CODIGO = {
    "funil": (
        "motor/raiz_estado.py",
        "raiz/funil/rodar.py",
        "raiz/funil/ponte.py",
        "raiz/funil/duck.py",
        "raiz/funil/novo.py",
    ),
    "filtros": (
        "motor/raiz_filtros.py",
        "motor/raiz_extras.py",
        "raiz/funil/rodar.py",
        "raiz/funil/filtros.py",
        "raiz/funil/restricoes.py",
        "raiz/funil/ponte.py",
        "raiz/funil/duck.py",
        "raiz/funil/novo.py",
    ),
    "direto": ("motor/raiz_direto.py", "motor/raiz_extras.py", "raiz/funil/ponte.py"),
    "mapbiomas": ("motor/raiz_mapbiomas.py",),
    "extras_direto": ("motor/raiz_extras_direto.py", "motor/raiz_extras.py"),
    "flag": ("raiz/flag.py",),
    "terra": ("raiz/terra.py",),
    "titulo": (
        "raiz/titulo/regularizacao.py",
        "raiz/titulo/achados.py",
        "raiz/titulo/nota.py",
        "raiz/titulo/geometria.py",
        "raiz/titulo/cadeia.py",
        "raiz/titulo/contexto.py",
        "raiz/titulo/triagem.py",
        "raiz/titulo/tarefa.py",
    ),
    "ficha": (
        "raiz/imovel_dados.py",
        "raiz/osm.py",
        "raiz/tiles.py",
        "raiz/motivos.py",
        "raiz/regras/padroes/faixas.yaml",
    ),  # fmt: skip
    "rebanho": ("raiz/rebanho.py",),
    "desenvolvedor": ("raiz/restauracao.py", "raiz/restauracao_geo.py", "raiz/vazamento.py"),
}
DEPENDE = {
    "funil": (),
    "filtros": ("funil",),
    "direto": ("funil",),
    "mapbiomas": ("funil",),
    "extras_direto": ("funil",),
    "flag": ("funil", "mapbiomas", "direto"),
    "terra": ("funil", "filtros"),
    "titulo": ("funil", "filtros", "terra"),
    "ficha": ("funil", "filtros", "mapbiomas", "flag", "terra"),
    "rebanho": ("funil", "mapbiomas", "direto"),
    "desenvolvedor": ("funil", "filtros", "mapbiomas", "direto", "ficha", "terra", "rebanho"),
}
SAIDAS = {
    "funil": ("imoveis_{cod}.csv", "geo_{cod}.parquet", "certidoes_{cod}.csv"),
    "filtros": ("filtros_{cod}.csv",),
    "direto": ("direto_{cod}.csv",),
    "mapbiomas": ("mapbiomas_{cod}.csv",),
    "extras_direto": ("extras_direto_{cod}.csv",),
    "flag": ("flag_{cod}.csv",),
    "terra": ("terra_{cod}.csv",),
    "titulo": ("titulo_{cod}.csv", "regularizacao_{cod}.csv", "achados_{cod}.csv"),
    "ficha": ("ficha_{cod}.csv", "camadas_{cod}.parquet", "camadas_{cod}.pmtiles"),
    "rebanho": ("rebanho_{cod}.csv",),
    "desenvolvedor": ("desenvolvedor_{cod}.csv",),
}


def _hash_codigo(arquivos: tuple[str, ...], extra: str = "") -> str:
    h = hashlib.sha256()
    for a in arquivos:
        p = RAIZ_REPO / a
        h.update(a.encode())
        h.update(p.read_bytes() if p.exists() else b"")
    h.update(extra.encode())
    return h.hexdigest()[:12]


def versao(nome: str) -> str:
    extra = ""
    if nome == "flag":
        from raiz import flag

        extra = flag.versao()
    elif nome == "terra":
        from raiz import terra

        extra = terra.versao()
    elif nome == "rebanho":
        from raiz import rebanho

        extra = rebanho.versao()
    elif nome == "desenvolvedor":
        from raiz import restauracao

        extra = restauracao.versao()
    elif nome == "titulo":
        from raiz.titulo import tarefa

        extra = tarefa.versao()
    # A captura é parte do contrato da tarefa: mudança nela precisa de nova
    # execução, mesmo quando o CSV final teria os mesmos números.
    historico = (
        "raiz/aprendizado/captura.py",
        "raiz/aprendizado/retratos.py",
        "raiz/aprendizado/arquivo_historico.py",
        "raiz/aprendizado/reexecucao.py",
        "raiz/funil/rodar.py",
    )
    return f"{nome}-{_hash_codigo((*CODIGO[nome], *historico), extra)}"


# --- fontes externas ---------------------------------------------------------------------------------------------


def _cache_motor() -> Path:
    from raiz.funil.rodar import dir_trabalho

    return dir_trabalho() / "cache"


def _espelho() -> Path:
    from raiz.funil.ponte import espelho_padrao

    return espelho_padrao()


def _rasters_uf(uf: str, tema: str | None = None) -> dict:
    pasta = _cache_motor() / "mapbiomas" / uf
    fs = sorted(pasta.glob(f"{uf}_{tema}_*.tif" if tema else f"{uf}_*.tif")) if pasta.exists() else []
    return {f.name: assinatura_arquivo(f) for f in fs}


def _documentos(uf: str, cod: int, tabela: str) -> str | None:
    """Assinatura da saída de raiz/documentos (certidões conferidas): refaz terra e título quando muda."""
    from raiz.documentos.config import pasta_dados

    f = pasta_dados() / "saida" / uf / f"{tabela}_{cod}.csv"
    return assinatura_arquivo(f, conteudo=True) if f.exists() else None


def _nacionais() -> dict:
    c = _cache_motor()
    fs = [*c.glob("conservationunits_*.parquet"), *c.glob("indigenouslands_*.parquet"),
          *c.glob("quilombolalands_*.parquet")]  # fmt: skip
    return {f.name: assinatura_arquivo(f) for f in sorted(fs)}


@lru_cache(maxsize=8)
def _alertas(arquivo: str, marca_arquivo: str):
    import geopandas as gpd

    g = gpd.read_parquet(arquivo)
    return g.set_crs(4674) if g.crs is None else g.to_crs(4674)


def _alertas_na_caixa(uf: str, caixa) -> str | None:
    """Assinatura dos alertas do estado que caem na caixa do município (um alerta novo noutro canto do estado não
    refaz este município)."""
    f = _cache_motor() / "alerta" / f"alerta_{uf}.parquet"
    if not f.exists():
        return None
    if not caixa:
        return assinatura_arquivo(f)
    g = _alertas(str(f), assinatura_arquivo(f))
    x0, y0, x1, y1 = caixa
    sub = g.cx[x0:x1, y0:y1]
    return sha_texto(*sorted(sub.geometry.to_wkb().map(lambda b: hashlib.sha256(b).hexdigest())))


def externas(nome: str):
    def f(uf: str, cod: int, marca: dict) -> dict:
        esp = _espelho()
        if nome == "funil":
            return {
                "car": assinatura_arquivo(esp / "car" / uf / f"{cod}.parquet", conteudo=True),
                "sigef": assinatura_arquivo(esp / "sigef" / uf / f"{cod}.parquet", conteudo=True),
                "ibama": assinatura_arquivo(esp / "ibama" / uf / f"{cod}.parquet", conteudo=True),
                "alertas": _alertas_na_caixa(uf, marca.get("caixa")),
                "mapbiomas": {k: v for k, v in _rasters_uf(uf).items() if "_cobertura_" in k or "_desmat_" in k},
            }
        if nome == "filtros":
            local = esp / "ibama" / uf / f"{cod}.parquet"
            if local.exists():
                return {**_nacionais(), "ibama": assinatura_arquivo(local, conteudo=True)}
            return {
                **_nacionais(),
                "ibama_csv": assinatura_arquivo(_cache_motor() / "termo_de_embargo.csv"),
                "ibama_etag": assinatura_arquivo(_cache_motor() / "termo_de_embargo.etag", conteudo=True),
            }
        if nome == "mapbiomas":
            return _rasters_uf(uf)
        if nome == "extras_direto":
            c = _cache_motor()
            return {p.name: assinatura_arquivo(p) for d in ("tmf", "drivers") for p in sorted((c / d).glob("*"))}
        if nome == "terra":
            from raiz import terra

            cnfp = terra.cnfp_da_uf(uf)
            return {"sigef": assinatura_arquivo(esp / "sigef" / uf / f"{cod}.parquet", conteudo=True),
                    "cnfp": assinatura_arquivo(cnfp) if cnfp else None, **_nacionais(),
                    "matricula": _documentos(uf, cod, "matricula")}  # fmt: skip
        if nome == "titulo":
            return {"certidoes": _documentos(uf, cod, "matricula_conferencia"),
                    "matricula": _documentos(uf, cod, "matricula"),
                    "cadeia": _documentos(uf, cod, "cadeia"),
                    "sigef": assinatura_arquivo(esp / "sigef" / uf / f"{cod}.parquet", conteudo=True)}  # fmt: skip
        if nome in ("ficha", "desenvolvedor"):
            return _rasters_uf(uf, "cobertura")
        return {}

    return f


# --- rodar ---------------------------------------------------------------------------------------------------------


def rodar(nome: str):
    """Roda uma tarefa num município pelo invólucro do motor (raiz/funil/rodar.py), sempre refazendo: quem decide se
    precisa é o executor."""

    def f(uf: str, cod: int, pasta: Path) -> None:
        import os

        from raiz.funil import rodar as R

        op = R.Opcoes(uf=uf, tarefas=(nome,), refazer=True, banco=os.environ.get("RAIZ_SEM_BANCO") != "1")
        r = R.rodar_municipio(int(cod), op)
        estado = r.get(nome, "")
        if estado.startswith("falha"):
            raise RuntimeError(f"{nome}: {estado}")

    return f


def tarefas_producao() -> list[Tarefa]:
    return [
        Tarefa(
            nome=n,
            depende=DEPENDE[n],
            saidas=SAIDAS[n],
            versao=lambda n=n: versao(n),
            rodar=rodar(n),
            externas=externas(n),
            pode_ficar_vazio=(n == "funil"),
        )  # fmt: skip
        for n in DEPENDE
    ]


COD_UF = dict(RO=11, AC=12, AM=13, RR=14, PA=15, AP=16, TO=17, MA=21, PI=22, CE=23, RN=24, PB=25, PE=26, AL=27,
              SE=28, BA=29, MG=31, ES=32, RJ=33, SP=35, PR=41, SC=42, RS=43, MS=50, MT=51, GO=52, DF=53)  # fmt: skip
# lista dos 5.571 municípios (código do IBGE, nome, UF), de github.com/kelvins/municipios-brasileiros (MIT, NOTICE.md)
LISTA = Path(__file__).with_name("municipios.csv")


def municipios_da_uf(uf: str) -> list[int]:
    """Os municípios do estado: a lista que vem com o produto, a do cache do motor ou a API do IBGE."""
    import pandas as pd

    uf = uf.upper()
    for f in (LISTA, _cache_motor() / "municipios.csv", MOTOR_DIR / "cache" / "municipios.csv"):
        if f.exists():
            m = pd.read_csv(f)
            return sorted(m[m.codigo_uf == COD_UF[uf]].codigo_ibge.astype(int).tolist())
    import httpx

    r = httpx.get(f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios", timeout=60)
    r.raise_for_status()
    return sorted(int(x["id"]) for x in r.json())


UFS = ("AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ",
       "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO")  # fmt: skip


def resumo_uf(uf: str, pasta: Path, cods: list[int]) -> Path | None:
    """resumo_<UF>.csv a partir dos imoveis_<mun>.csv, com a função resumo do próprio motor (não se edita o motor)."""
    import sys

    import pandas as pd

    if str(MOTOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOTOR_DIR))
    from raiz.funil.rodar import preparar_motor

    R = preparar_motor(carregar_embargos=False)
    linhas = []
    for cod in cods:
        f = pasta / f"imoveis_{cod}.csv"
        if not f.exists():
            continue
        c = pd.read_csv(f, index_col=0, low_memory=False)
        if len(c):
            linhas.append(R.resumo(c, cod, c.municipio.iloc[0]))
    if not linhas:
        return None
    out = pasta / f"resumo_{uf}.csv"
    pd.DataFrame(linhas).sort_values("cod_ibge").to_csv(out, index=False)
    return out


def preparar(uf: str, tarefas: list[str]) -> None:
    """Downloads do estado uma vez, antes de repartir os municípios (os mesmos do invólucro)."""
    from raiz.funil import rodar as R

    R.preparar_motor(carregar_embargos=bool({"funil", "filtros"} & set(tarefas)))
    R.preparar_estado(R.Opcoes(uf=uf, tarefas=tuple(tarefas)))


def executor_producao(armazem=None):
    from raiz.executor.armazem import do_config
    from raiz.executor.executor import Executor
    from raiz.funil.rodar import dir_trabalho
    from raiz.versoes import motor_versao

    return Executor(armazem or do_config(), dir_trabalho(), tarefas_producao(), municipios=municipios_da_uf,
                    resumo=resumo_uf, motor_versao=motor_versao)  # fmt: skip
