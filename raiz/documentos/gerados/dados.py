"""Junta, por imóvel, o que o motor e o produto já calcularam (sempre pelo nome das colunas, tolerando falta):

imoveis_<mun>.csv (motor), filtros_<mun>.csv (motor), ficha_<mun>.csv, terra_<mun>.csv, desenvolvedor_<mun>.csv
(produto, quando existem) e matricula_<mun>.csv (conferência das certidões, raiz/documentos).
"""

from __future__ import annotations

from raiz.documentos import tabelas
from raiz.documentos.config import municipio_do_imovel
from raiz.documentos.formato import fmt_data, fmt_moeda, fmt_num  # noqa: F401 (usados pelos documentos)

TABELAS_IMOVEL = ["imoveis", "filtros", "ficha", "terra", "desenvolvedor", "matricula"]


def _limpo(v):
    if isinstance(v, float) and v != v:
        return None
    return v


def _municipio_com_imovel(cod_imovel: str, candidatos: list[int], cache: dict) -> int | None:
    for mun in candidatos:
        chave = ("imoveis", mun)
        if chave not in cache:
            cache[chave] = tabelas.ler("imoveis", mun)
        df = cache[chave]
        if df is not None and "cod_imovel" in df.columns and (df.cod_imovel == cod_imovel).any():
            return mun
    return None


def linha_imovel(cod_imovel: str, cache: dict | None = None, cod_municipio: int | None = None) -> dict:
    """Uma linha com as colunas de todas as tabelas do imóvel (a primeira tabela que tem a coluna vence).
    O CAR que cruza divisa aparece no arquivo de outro município: passe cod_municipio (o do arquivo) nesse caso."""
    cache = cache if cache is not None else {}
    candidatos = [m for m in (cod_municipio, municipio_do_imovel(cod_imovel)) if m]
    if not candidatos:
        raise ValueError(f"código do CAR sem município: {cod_imovel}")
    mun = _municipio_com_imovel(cod_imovel, candidatos, cache) or candidatos[0]
    linha: dict = {"cod_imovel": cod_imovel, "cod_municipio": mun, "_tabelas": []}
    for t in TABELAS_IMOVEL:
        chave = (t, mun)
        if chave not in cache:
            cache[chave] = tabelas.ler(t, mun)
        df = cache[chave]
        if df is None or "cod_imovel" not in df.columns:
            continue
        r = df[df.cod_imovel == cod_imovel]
        if r.empty:
            continue
        linha["_tabelas"].append(t)
        for k, v in r.iloc[0].to_dict().items():
            if k not in linha or linha[k] is None:
                linha[k] = _limpo(v)
    if "imoveis" not in linha["_tabelas"]:
        raise LookupError(f"imóvel {cod_imovel} não está no imoveis_{mun}.csv das pastas de entrada")
    return linha


def imoveis_do_grupo(grupo_id: str, cod_municipio: int) -> list[str]:
    df = tabelas.ler("desenvolvedor", cod_municipio)
    if df is None or "grupo_id" not in df.columns:
        raise LookupError(f"desenvolvedor_{cod_municipio}.csv com grupo_id não encontrado")
    return sorted(df[df.grupo_id.astype(str) == str(grupo_id)].cod_imovel.unique())


def imoveis_do_municipio(cod_municipio: int, frentes: list[str] | None = None) -> list[str]:
    df = tabelas.ler("imoveis", cod_municipio)
    if df is None:
        raise LookupError(f"imoveis_{cod_municipio}.csv não encontrado")
    if frentes and "frente" in df.columns:
        df = df[df.frente.isin(frentes)]
    return sorted(df.cod_imovel.unique())


def num(linha: dict, *colunas, padrao=None):
    for c in colunas:
        v = _limpo(linha.get(c))
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return padrao


def verdadeiro(v) -> bool | None:
    if v is None or (isinstance(v, float) and v != v):
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "yes")
    return bool(v)


def porte(linha: dict) -> str:
    """pequeno até 4, médio até 15, grande acima de 15 módulos fiscais (Lei 8.629/1993)."""
    if linha.get("porte"):
        return str(linha["porte"])
    mf = num(linha, "m_fiscal")
    if mf is None:
        return "—"
    return "pequeno" if mf <= 4 else ("médio" if mf <= 15 else "grande")


def data_dos_dados(linha: dict) -> str:
    v = linha.get("data_atualizacao") or linha.get("dat_criacao")
    try:
        return fmt_data(str(v)[:10]) if v else "—"
    except ValueError:
        return str(v)[:10]
