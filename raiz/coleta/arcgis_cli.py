"""Comando ArcGIS com recorte explícito; arquivos públicos separados por fonte e município."""

from typing import Annotated

import typer


def coletar_arcgis(
    fonte: Annotated[str, typer.Argument(help="id ArcGIS do manifesto")],
    uf: Annotated[str, typer.Argument(help="sigla da UF do município")],
    municipio: Annotated[int, typer.Argument(help="código IBGE municipal de sete dígitos")],
    bbox: Annotated[str, typer.Option(help="oeste,sul,leste,norte em EPSG:4674; retângulo do recorte")],
    forcar: Annotated[bool, typer.Option(help="reler mesmo quando lastEditDate não mudou")] = False,
) -> None:
    """Coleta feições no retângulo indicado, sem recortar pela divisa municipal; ignora campos pessoais."""
    from raiz.banco import engine
    from raiz.coleta.arcgis import _bbox, coletar_municipio
    from raiz.coleta.espelho import Espelho
    from raiz.coleta.http import sessao
    from raiz.coleta.manifesto import UFS, carregar
    from raiz.coleta.replicacao import sincronizar_fontes
    from raiz.funil.ponte import espelho_padrao
    from raiz.operacao.healthchecks import Healthchecks
    from raiz.operacao.lotes import lote

    try:
        caixa = tuple(float(v.strip()) for v in bbox.split(","))
        _bbox(caixa)
        f = carregar().fonte(fonte)
        if f.tipo != "arcgis":
            raise ValueError("fonte precisa ter tipo arcgis no manifesto")
        if uf.upper() not in UFS or not 1_000_000 <= municipio <= 9_999_999:
            raise ValueError("informe UF válida e código IBGE municipal de sete dígitos")
    except (ValueError, KeyError) as ex:
        raise typer.BadParameter(str(ex)) from ex
    eng, hc = engine(), Healthchecks()
    with lote(eng, hc, "coleta-arcgis", uf.upper(), municipio) as reg:
        with eng.begin() as con:
            sincronizar_fontes(con)
            r = coletar_municipio(sessao(), con, Espelho(espelho_padrao()), f, uf, municipio, caixa, forcar, hc)
        reg.detalhe.update(fonte=r.fonte, acao=r.acao, linhas=r.linhas, lastEditDate=r.edicao)
        if r.acao in {"falha", "travado"}:
            raise RuntimeError(r.erro)
    typer.echo(f"{r.fonte} {r.recorte}: {r.acao}; {r.linhas} feições; lastEditDate={r.edicao}")
