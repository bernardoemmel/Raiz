"""Coletar, importar e consultar o calendário; sem qualquer envio externo."""

import datetime as dt
import json
import os
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from sqlalchemy import text

from raiz.calendario import arquivos, banco, coleta
from raiz.calendario.modelos import Evento, FonteEstado

app = typer.Typer(
    help="Calendário da Raíz: fontes oficiais, eventos e prazos.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


def _ler_snapshot(caminho: Path):
    try:
        return arquivos.ler(caminho)
    except arquivos.ErroSnapshot as erro:
        raise typer.BadParameter(str(erro)) from None


@app.command("coletar")
def coletar(
    saida: Annotated[Path, typer.Option(help="pasta de saída, fora do git")] = Path("dados/calendario"),
    anterior: Annotated[Path | None, typer.Option(help="estado.json da rodada anterior")] = None,
    fontes: Annotated[str | None, typer.Option(help="IDs de fontes, separados por vírgula")] = None,
    sem_banco: Annotated[bool, typer.Option(help="somente snapshot público, para o GitHub Actions")] = False,
) -> None:
    """Busca prazos explícitos, preserva o estado anterior e publica JSON/.ics."""
    lista = coleta.fontes()
    if fontes:
        ids = set(fontes.split(","))
        if ids - {f["id"] for f in lista}:
            raise typer.BadParameter("fonte desconhecida")
        lista = [f for f in lista if f["id"] in ids]
    if sem_banco:
        antigos, fontes_antigas = _ler_snapshot(anterior) if anterior else ([], [])
    else:
        from raiz.banco import engine

        with engine().connect() as con:
            antigos = [Evento.model_validate(r[0]) for r in con.execute(text("select conteudo from calendario.evento"))]
    eventos, estados = coleta.coletar(lista, anteriores=antigos)
    avisos = 0
    if sem_banco:
        eventos = banco.combinar(antigos, eventos)
        por_id = {f.id: f for f in fontes_antigas}
        por_id.update({f.id: f for f in estados})
        fontes_publicadas = sorted(por_id.values(), key=lambda x: x.id)
    else:
        from raiz.banco import engine

        with engine().begin() as con:
            banco.gravar(con, eventos, estados)
            avisos = banco.avisar_pedidos(con, dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date())
            eventos = [Evento.model_validate(r[0]) for r in con.execute(text("select conteudo from calendario.evento"))]
            fontes_publicadas = [
                FonteEstado.model_validate(r[0])
                for r in con.execute(text("select conteudo from calendario.fonte_estado order by id"))
            ]
    arquivos.publicar(saida, eventos, fontes_publicadas)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write("gerado=1\n")
    typer.echo(f"{len(eventos)} eventos guardados; {avisos} avisos preparados (envio externo simulado).")
    for estado in estados:
        typer.echo(f"{estado.id}: {estado.situacao}, {estado.eventos} eventos, {estado.paginas} páginas")
    # Snapshot útil é salvo antes de deixar o job vermelho por fonte quebrada.
    if any(s.situacao == "erro" for s in estados):
        raise typer.Exit(1)


@app.command("importar")
def importar(arquivo: Annotated[Path, typer.Argument(help="estado.json do Release calendario")]) -> None:
    """Carrega a coleta publicada, cruza CAR/SIGEF e prepara os avisos dos lotes."""
    from raiz.banco import engine

    eventos, estados = _ler_snapshot(arquivo)
    with engine().begin() as con:
        alterados = banco.gravar(con, eventos, estados)
        avisos = banco.avisar_pedidos(con, dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date())
    typer.echo(f"{alterados} eventos novos ou alterados; {avisos} avisos preparados.")


@app.command("proximos")
def proximos(tipo: str | None = None, estado: str | None = None, dias: int = 90, cod_imovel: str | None = None) -> None:
    """A mesma consulta somente leitura da ferramenta MCP proximos_eventos."""
    from raiz.calendario.mcp import proximos_eventos

    typer.echo(json.dumps(proximos_eventos(tipo, estado, dias, cod_imovel), ensure_ascii=False, indent=2))
