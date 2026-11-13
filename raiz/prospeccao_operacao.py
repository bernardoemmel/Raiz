"""Comandos administrativos da ficha; não abrem rotas públicas nem ativam cobranças."""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer


def _mostrar(resultado) -> None:
    def valor(v):
        if isinstance(v, (dt.date, dt.datetime)):
            return v.isoformat()
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, Decimal):
            return float(v)
        raise TypeError("Tipo fora do relatório operacional")

    typer.echo(json.dumps(resultado, ensure_ascii=False, indent=2, allow_nan=False, default=valor))


def registrar(app: typer.Typer) -> None:
    @app.command("simular-receita")
    def simular_receita(
        cenario: Annotated[
            Path | None,
            typer.Option(exists=True, dir_okay=False, readable=True, help="JSON com hipóteses por modalidade."),
        ] = None,
    ) -> None:
        """Compara ficha, lote e assinatura por cliente/mês e ano; não salva preços nem cobra."""
        from raiz.prospeccao_precos import simular_modalidades

        try:
            if cenario and cenario.stat().st_size > 65_536:
                raise ValueError("Cenário excede o limite")
            entradas = json.loads(cenario.read_text(encoding="utf-8")) if cenario else None
            resultado = simular_modalidades(entradas)
        except (ValueError, TypeError, OSError) as exc:
            typer.echo(
                "Cenário inválido. Confira as modalidades, valores e custos em docs/precos-e-receita.md.", err=True
            )
            raise typer.Exit(1) from exc
        _mostrar(resultado)

    @app.command("atualizar-base")
    def atualizar_base(
        ufs: Annotated[
            str | None, typer.Option(help="UFs separadas por vírgula; padrão: manifesto privado inteiro.")
        ] = None,
        destino: Annotated[Path | None, typer.Option(help="Espelho privado local, fora do diretório do site.")] = None,
        reprocessar: Annotated[
            bool, typer.Option(help="Refazer a carga das rodadas já presentes, sem rodar o motor.")
        ] = False,
    ) -> None:
        """Carrega as UFs já processadas e descobre novas no manifesto privado."""
        from raiz.banco import engine
        from raiz.prospeccao_cobertura import atualizar_base as atualizar

        lista = None
        if ufs is not None:
            lista = list(dict.fromkeys(u.strip().upper() for u in ufs.split(",")))
            validas = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
            if not lista or any(u not in validas for u in lista):
                typer.echo("Informe siglas válidas de estados separadas por vírgula.", err=True)
                raise typer.Exit(1)
        resultado = atualizar(engine(), ufs=lista, destino=destino, reprocessar=reprocessar)
        _mostrar(resultado)
        if resultado.get("falhas") or (resultado.get("fichas") or {}).get("pendente"):
            raise typer.Exit(1)

    @app.command("reindexar")
    def reindexar(
        forcar: Annotated[
            bool, typer.Option(help="Conferir todos os municípios mesmo sem mudança no catálogo.")
        ] = False,
    ) -> None:
        """Atualiza compromissos e versões de todas as UFs carregadas, sem recalcular o motor."""
        from raiz.banco import engine
        from raiz.prospeccao_cobertura import reindexar as atualizar

        resultado = atualizar(engine(), forcar=forcar)
        _mostrar(resultado)
        if resultado.get("pendente"):
            raise typer.Exit(1)

    @app.command("coletar-compromissos")
    def coletar_compromissos(
        fontes: Annotated[
            list[str] | None,
            typer.Option("--fonte", help="Fonte repetível; opções em docs/terra-comprometida.md."),
        ] = None,
        bbox: Annotated[
            str | None,
            typer.Option(help="Recorte SFB: oeste,sul,leste,norte; padrão: limites do Brasil."),
        ] = None,
        projetos_verra: Annotated[
            list[str] | None,
            typer.Option(
                "--projeto-verra", help="ID repetível. Sem IDs, descobre os projetos brasileiros no catálogo."
            ),
        ] = None,
        limite_verra: Annotated[
            int | None, typer.Option(min=1, help="Projetos por execução, para carga em etapas.")
        ] = None,
        retomar_desde: Annotated[
            str | None,
            typer.Option(help="AAAA-MM-DD: pula projetos Verra com coleta bem-sucedida desde esse dia UTC."),
        ] = None,
    ) -> None:
        """Persiste fontes públicas no banco privado e atualiza as fichas e os avisos.

        Cada projeto é confirmado separadamente; uma falha posterior não perde
        coletas anteriores. Sem --retomar-desde, consulta novamente os registros.
        Verra é uma fase explícita (--fonte verra) para controlar o tráfego nacional.
        """
        from sqlalchemy import text

        from raiz.banco import engine
        from raiz.coleta.compromissos_registros import iterar_compromissos
        from raiz.prospeccao_buscas import verificar_todas
        from raiz.prospeccao_cobertura import reindexar as atualizar
        from raiz.terra_comprometida import ingerir

        try:
            desde = dt.date.fromisoformat(retomar_desde) if retomar_desde else None
            recorte = [float(n) for n in bbox.split(",")] if bbox else None
            if recorte is not None and (
                len(recorte) != 4
                or not (-180 <= recorte[0] < recorte[2] <= 180 and -90 <= recorte[1] < recorte[3] <= 90)
            ):
                raise ValueError("Recorte inválido")
            permitidas = {"berkeley", "art_jurisdicional", "sfb_concessoes", "verra", "limites_pesquisa"}
            if fontes and set(fontes) - permitidas:
                raise ValueError("Fonte inválida")
            if projetos_verra and (not fontes or "verra" not in fontes):
                raise ValueError("Informe --fonte verra ao selecionar projetos")
        except ValueError as exc:
            typer.echo("Confira a fonte, o recorte e a data de retomada em docs/terra-comprometida.md.", err=True)
            raise typer.Exit(1) from exc
        eng = engine()
        concluidos = []
        if desde is not None:
            with eng.connect() as con:
                concluidos = (
                    con.execute(
                        text("""select distinct cobertura->>'recorte' from coleta.compromisso_fonte
                        where fonte_id='verra' and consultado_em>=:desde
                        and cobertura->>'estado' in ('consultado','parcial')"""),
                        {"desde": desde},
                    )
                    .scalars()
                    .all()
                )
        coletas, indisponiveis, parciais = 0, [], []
        interrompida = False
        try:
            for coleta in iterar_compromissos(
                fontes=fontes,
                bbox=recorte,
                projetos_verra=projetos_verra,
                concluidos_verra=concluidos,
                limite_verra=limite_verra,
            ):
                with eng.begin() as con:
                    ingerir(con, coleta)
                coletas += 1
                if coleta["cobertura"]["estado"] == "indisponivel":
                    indisponiveis.append(coleta["cobertura"]["fonte_id"])
                if coleta["cobertura"]["estado"] == "parcial":
                    parciais.append(coleta["cobertura"]["fonte_id"])
        except Exception:  # noqa: BLE001 - não imprime respostas remotas; conserva commits já concluídos.
            interrompida = True
        fichas = atualizar(eng)
        avisos = verificar_todas(eng)
        _mostrar(
            {
                "coletas_persistidas": coletas,
                "fontes_indisponiveis": sorted(set(indisponiveis)),
                "fontes_com_cobertura_parcial": sorted(set(parciais)),
                "limite_verra_nesta_execucao": limite_verra,
                "interrompida": interrompida,
                "fichas": fichas,
                "avisos": avisos,
            }
        )
        if interrompida or indisponiveis or fichas.get("pendente"):
            raise typer.Exit(1)

    @app.command("alertas-protecao")
    def alertas_protecao(
        limite: Annotated[int, typer.Option(min=1, max=1000, help="Quantidade máxima de alertas internos.")] = 100,
        apenas_ativos: Annotated[bool, typer.Option(help="Só critérios ainda atingidos após reavaliação.")] = False,
    ) -> None:
        """Consulta indícios de varredura, regras e métricas; não envia mensagens externas."""
        from raiz.banco import engine
        from raiz.prospeccao_protecao import alertas

        _mostrar(alertas(engine(), limite=limite, apenas_ativos=apenas_ativos))

    @app.command("rastrear-marca")
    def rastrear_marca(
        codigo: Annotated[str, typer.Argument(help="Marca pseudônima encontrada em um PDF ou exportação.")],
    ) -> None:
        """Consulta a correspondência interna da marca, sem nomes ou contatos."""
        from raiz.banco import engine
        from raiz.prospeccao_protecao import rastrear_marca as rastrear

        resultado = rastrear(engine(), codigo)
        if resultado is None:
            typer.echo("Marca não encontrada no registro interno.", err=True)
            raise typer.Exit(1)
        _mostrar(resultado)

    @app.command("limpar-eventos-protecao")
    def limpar_eventos_protecao() -> None:
        """Aplica a retenção aos eventos brutos; preserva marcas e alertas auditados."""
        from raiz.banco import engine
        from raiz.prospeccao_protecao import limpar_eventos

        _mostrar({"eventos_antigos_removidos": limpar_eventos(engine())})
