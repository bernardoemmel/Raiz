"""Comando `raiz`: cada trabalho do produto é um subcomando (roda por cron hoje; vira asset do Dagster depois)."""

import subprocess
import sys
from typing import Annotated

import typer

from raiz import RAIZ_REPO
from raiz.privacidade import configurar_log, varrer

app = typer.Typer(help="Raíz: coleta, funil, título, agentes e aprendizado em cima do motor.", no_args_is_help=True)
privacidade = typer.Typer(help="Guarda de CPF/CNPJ.", no_args_is_help=True)
banco = typer.Typer(help="Banco PostgreSQL + PostGIS.", no_args_is_help=True)
app.add_typer(privacidade, name="privacidade")
app.add_typer(banco, name="banco")


@app.callback()
def _inicio() -> None:
    configurar_log()


@privacidade.command("varrer")
def privacidade_varrer(
    caminhos: Annotated[list[str] | None, typer.Argument(help="arquivos; sem nada, todo o git")] = None,
) -> None:
    """Procura CPF e CNPJ em arquivos. Sai com erro se achar algum."""
    if not caminhos:
        saida = subprocess.run(["git", "ls-files"], cwd=RAIZ_REPO, capture_output=True, text=True, check=True).stdout
        caminhos = [str(RAIZ_REPO / a) for a in saida.split()]
    achados = varrer(caminhos)
    for a in achados:
        typer.echo(f"{a.arquivo}:{a.linha}: {a.tipo} {a.trecho}")
    if achados:
        typer.echo(f"{len(achados)} documento(s) encontrado(s). Tire do arquivo antes do commit.", err=True)
        sys.exit(1)
    typer.echo(f"{len(caminhos)} arquivo(s) sem CPF/CNPJ.")


@app.command("carregar")
def carregar(
    pasta: Annotated[str, typer.Argument(help="pasta saida/<UF>/ do motor (ou dados/amostra)")],
    data_corte: Annotated[str | None, typer.Option(help="AAAA-MM-DD; dados como estavam até esta data")] = None,
) -> None:
    """Carrega as saídas do motor no banco pelo contrato de colunas (idempotente)."""
    import datetime as dt

    from raiz.banco import engine
    from raiz.carga import carregar_pasta

    corte = dt.date.fromisoformat(data_corte) if data_corte else None
    for r in carregar_pasta(engine(), pasta, corte):
        onde = r.cod_municipio or f"resumo {r.uf}"
        estado = "nova" if r.nova else "já carregada"
        typer.echo(f"{onde}: rodada {r.rodada_id} ({estado}), {r.imoveis} linhas")
        for c in r.colunas_novas:
            typer.echo(f"  coluna nova (em atributos; documentar em docs/colunas.md): {c}")
        for c in r.colunas_faltando:
            typer.echo(f"  coluna do contrato ausente (fica nula): {c}")


@banco.command("migrar")
def banco_migrar(alvo: str = "head") -> None:
    """Aplica as migrações (Alembic) no banco de RAIZ_BANCO_URL."""
    from raiz.banco import migrar

    migrar(alvo=alvo)
    typer.echo(f"banco migrado até {alvo}")


if __name__ == "__main__":
    app()
