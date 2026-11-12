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
    congelar: Annotated[bool, typer.Option(help="congelar as previsões do motor (E8)")] = True,
) -> None:
    """Carrega as saídas do motor no banco pelo contrato de colunas (idempotente) e congela as previsões."""
    import datetime as dt

    from raiz.banco import engine
    from raiz.carga import carregar_pasta

    corte = dt.date.fromisoformat(data_corte) if data_corte else None
    for r in carregar_pasta(engine(), pasta, corte, congelar=congelar):
        onde = r.cod_municipio or f"resumo {r.uf}"
        estado = "nova" if r.nova else "já carregada"
        typer.echo(f"{onde}: rodada {r.rodada_id} ({estado}), {r.imoveis} linhas")
        if r.lote_previsoes:
            typer.echo(f"  previsões congeladas: {r.previsoes_novas} novas (lote {r.lote_previsoes[:12]})")
        for c in r.colunas_novas:
            typer.echo(f"  coluna nova (em atributos; documentar em docs/colunas.md): {c}")
        for c in r.colunas_faltando:
            typer.echo(f"  coluna do contrato ausente (fica nula): {c}")


aprendizado = typer.Typer(help="Previsões congeladas e gabaritos (E8).", no_args_is_help=True)
app.add_typer(aprendizado, name="aprendizado")


@aprendizado.command("gabarito")
def aprendizado_gabarito(
    cod_imovel: str,
    alvo: str,
    valor: str,
    observado_em: Annotated[str, typer.Option(help="AAAA-MM-DD em que o resultado real foi observado")],
    fonte: Annotated[str, typer.Option(help="ex.: certidao, aceite, campo, sicar_analise, prodes")],
    referencia: Annotated[str | None, typer.Option(help="documento de origem (sem dado pessoal)")] = None,
) -> None:
    """Registra um resultado real (gabarito) para comparar com as previsões congeladas."""
    import datetime as dt

    from raiz.aprendizado.registro import registrar_gabarito
    from raiz.banco import engine
    from raiz.privacidade import mascarar

    if referencia and mascarar(referencia) != referencia:
        raise typer.BadParameter("a referência tem CPF/CNPJ; use o número do documento, não o da pessoa")
    try:
        vn, vt = float(valor.replace(",", ".")), None
    except ValueError:
        vn, vt = None, valor
    with engine().begin() as con:
        gid = registrar_gabarito(con, cod_imovel, alvo, dt.date.fromisoformat(observado_em), fonte, vn, vt, referencia)
    typer.echo(f"gabarito {gid} registrado")


@aprendizado.command("placar")
def aprendizado_placar() -> None:
    """Acerto por modelo, versão e alvo."""
    from raiz.aprendizado.registro import placar
    from raiz.banco import engine

    with engine().connect() as con:
        linhas = placar(con)
    if not linhas:
        typer.echo("nenhuma previsão congelada ainda")
    for r in linhas:
        acerto = "-" if r.taxa_acerto is None else f"{100 * r.taxa_acerto:.0f}%"
        erro = "-" if r.erro_abs_medio is None else f"{r.erro_abs_medio:.2f}"
        typer.echo(
            f"{r.modelo} {r.modelo_versao} {r.alvo}: {r.previsoes} previsões, {r.com_gabarito} com gabarito, "
            f"{r.maturadas} maturadas, acerto {acerto}, erro médio {erro}"
        )


@banco.command("migrar")
def banco_migrar(alvo: str = "head") -> None:
    """Aplica as migrações (Alembic) no banco de RAIZ_BANCO_URL."""
    from raiz.banco import migrar

    migrar(alvo=alvo)
    typer.echo(f"banco migrado até {alvo}")


if __name__ == "__main__":
    app()
