"""Comando do modelo de tempo até o aceite, registrável no grupo aprendizado."""

import datetime as dt
from typing import Annotated

import typer


def registrar(app: typer.Typer) -> None:
    @app.command("sobrevivencia-aceite")
    def sobrevivencia_aceite(
        corte: Annotated[str | None, typer.Option(help="instante ISO com fuso; omitido usa agora")] = None,
        horizonte: Annotated[int, typer.Option(min=1, help="prazo futuro em dias")] = 14,
        congelar: Annotated[bool, typer.Option(help="gravar previsões dos contatos ainda sem desfecho")] = False,
    ) -> None:
        """Mede tempo até o aceite usando só contatos reais conhecidos no corte."""
        from raiz.banco import engine
        from raiz.pedidos import sobrevivencia as S

        try:
            quando = S._utc(dt.datetime.fromisoformat(corte)) if corte else dt.datetime.now(dt.UTC)
        except ValueError as ex:
            raise typer.BadParameter(str(ex), param_hint="--corte") from ex
        if quando > dt.datetime.now(dt.UTC):
            raise typer.BadParameter("o corte não pode estar no futuro", param_hint="--corte")
        with engine().connect().execution_options(isolation_level="REPEATABLE READ") as con, con.begin():
            obs = S.historico(con, quando)
            curva = S.ajustar(obs, quando)
            if curva is None:
                typer.echo(f"Pouco dado: {len(obs)} contatos reais; precisa de 30 contatos e 5 aceites.")
                return
            chance = curva.chance(horizonte)
            mediana = f"{curva.mediana_dias:g} dias" if curva.mediana_dias is not None else "não atingida"
            typer.echo(
                f"{curva.contatos} contatos, {curva.aceites} aceites, {curva.recusas} recusas; "
                f"mediana até o aceite: {mediana}."
            )
            typer.echo(
                f"Chance de aceite em {horizonte} dias: {chance:.1%}."
                if chance is not None
                else f"Sem seguimento suficiente para estimar {horizonte} dias."
            )
            typer.echo(f"Modelo: {curva.versao}. Estimativa agrupada; ainda requer avaliação com contatos futuros.")
            if congelar:
                r = S.congelar_pendentes(con, obs, curva, horizonte, "backtest" if corte else "ao_vivo")
                typer.echo(f"{r['previsoes_novas']} previsões novas; {r['sem_suporte']} sem suporte temporal.")

    @app.command("sobrevivencia-placar")
    def sobrevivencia_placar() -> None:
        """Confere os aceites que aconteceram dentro dos prazos já maturados."""
        from raiz.banco import engine
        from raiz.pedidos import sobrevivencia as S

        with engine().connect() as con:
            r = S.avaliar(con, dt.datetime.now(dt.UTC))
        if not r["por_versao"]:
            typer.echo("Ainda não há previsões maturadas do tempo até o aceite.")
        for versao, v in r["por_versao"].items():
            typer.echo(
                f"{versao}: {v['previsoes']} previsões, {v['aceites_no_prazo']} aceites no prazo; "
                f"Brier {v['brier']:.4f}."
            )
        if r["desfechos_anteriores_conhecidos_tardiamente"]:
            typer.echo(
                f"{r['desfechos_anteriores_conhecidos_tardiamente']} desfechos anteriores ao corte "
                "só ficaram conhecidos depois; fora do placar."
            )
