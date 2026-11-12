"""Comando de reexecução histórica, registrado no grupo aprendizado do terminal."""

import datetime as dt
import json
from pathlib import Path
from typing import Annotated

import typer


def registrar(app: typer.Typer) -> None:
    @app.command("arquivar-fold")
    def arquivar_fold(
        pasta: Annotated[Path, typer.Option(help="Pasta do retrato completo: um Parquet por fonte")],
        catalogo: Annotated[Path, typer.Option(help="JSON de cobertura gerado pelo arquivo")],
        uf: Annotated[str, typer.Option(help="UF do município")],
        municipio: Annotated[int, typer.Option(help="Código IBGE do município")],
    ) -> None:
        """Arquiva as fontes recebidas agora; não atribui datas passadas a arquivos atuais."""
        from raiz.aprendizado.arquivo_historico import arquivar, ler_pasta, salvar_catalogo
        from raiz.banco import engine

        try:
            dados = ler_pasta(pasta)
            with engine().begin() as con:
                resultado = arquivar(con, dados, uf, municipio)
            with engine().connect() as con:
                salvar_catalogo(con, municipio, catalogo)
        except (ValueError, OSError) as ex:
            raise typer.BadParameter(str(ex)) from ex
        typer.echo(json.dumps(resultado, ensure_ascii=False, indent=2))

    @app.command("reexecutar")
    def reexecutar(
        catalogo: Annotated[Path, typer.Option(help="JSON com a cobertura conferida de cada fonte scd2")],
        uf: Annotated[str, typer.Option(help="UF do município")],
        municipio: Annotated[int, typer.Option(help="Código IBGE do município")],
        inicio: Annotated[str, typer.Option(help="Primeiro corte anual (AAAA-MM-DD, às 00:00 UTC)")],
        fim: Annotated[str, typer.Option(help="Último corte anual (AAAA-MM-DD)")],
        modelos: Annotated[
            str, typer.Option(help="motor,flag,restauracao separados por vírgula")
        ] = "motor,flag,restauracao",
        congelar: Annotated[bool, typer.Option(help="Guardar previsões como backtest no registro E8")] = True,
    ) -> None:
        """Refaz os modelos com as fontes do corte; falta de histórico interrompe a rodada."""
        from raiz.aprendizado.folds import cortes_anuais
        from raiz.aprendizado.reexecucao import ler_catalogo
        from raiz.aprendizado.reexecucao import reexecutar as executar
        from raiz.banco import engine

        try:
            de, ate = dt.date.fromisoformat(inicio), dt.date.fromisoformat(fim)
            if de > ate:
                raise ValueError("início depois do fim")
            fontes = ler_catalogo(catalogo)
            cortes = [dt.datetime.combine(c, dt.time(), dt.UTC) for c in cortes_anuais(de, ate)]
            # As fontes de um fold pertencem à mesma visão do banco, mesmo que a
            # coleta diária grave outra versão enquanto o modelo está rodando.
            with engine().connect().execution_options(isolation_level="REPEATABLE READ") as con, con.begin():
                resultado = executar(
                    con, cortes, uf, municipio, fontes, tuple(m.strip() for m in modelos.split(",")), congelar
                )
        except (ValueError, OSError) as ex:
            raise typer.BadParameter(str(ex)) from ex
        typer.echo(json.dumps(resultado, ensure_ascii=False, indent=2))
