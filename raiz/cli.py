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


pessoal = typer.Typer(help="Dado pessoal cifrado (telefone e BSUID).", no_args_is_help=True)
app.add_typer(pessoal, name="pessoal")


@pessoal.command("gerar-chave")
def pessoal_gerar_chave() -> None:
    """Gera uma chave nova para RAIZ_CHAVE_PESSOAL (guarde no .env e num cofre fora do servidor)."""
    from raiz.pessoal import gerar_chave

    typer.echo(gerar_chave())


funil = typer.Typer(help="Motor por município, com lotes vigiados (Healthchecks).", no_args_is_help=True)
app.add_typer(funil, name="funil")


@funil.command("rodar")
def funil_rodar(
    uf: str,
    municipios: Annotated[list[int] | None, typer.Argument(help="códigos IBGE; sem nada, a UF inteira")] = None,
    tarefas: Annotated[
        str, typer.Option(help="separadas por vírgula")
    ] = "funil,filtros,direto,mapbiomas,extras_direto,flag,carga",
    lanes: Annotated[int, typer.Option(help="municípios ao mesmo tempo")] = 3,
    refazer: bool = False,
    data_corte: Annotated[str | None, typer.Option(help="AAAA-MM-DD; padrão: hoje")] = None,
) -> None:
    """Roda o motor (sem editá-lo) com CAR e SIGEF do espelho local e um lote vigiado por tarefa e município."""
    import datetime as dt

    from raiz.funil.rodar import TAREFAS, Opcoes, rodar

    ts = tuple(t.strip() for t in tarefas.split(",") if t.strip())
    if desconhecidas := set(ts) - set(TAREFAS):
        raise typer.BadParameter(f"tarefas desconhecidas: {sorted(desconhecidas)}")
    corte = dt.date.fromisoformat(data_corte) if data_corte else dt.date.today()
    res = rodar(Opcoes(uf, ts, refazer, corte), municipios or None, lanes)
    falhas = {c: r for c, r in res.items() if any(v.startswith("falha") for v in r.values())}
    typer.echo(f"{len(res)} município(s), {len(falhas)} com falha")
    for c, r in sorted(falhas.items()):
        typer.echo(f"  {c}: {r}")
    if falhas:
        sys.exit(1)


operacao = typer.Typer(help="Operação: custo dos modelos e lotes.", no_args_is_help=True)
app.add_typer(operacao, name="operacao")


@operacao.command("custo")
def operacao_custo(
    por: Annotated[str, typer.Option(help="tarefa, fazenda, municipio ou modelo")] = "tarefa",
    desde: Annotated[str | None, typer.Option(help="AAAA-MM-DD; padrão: início do mês")] = None,
) -> None:
    """Custo dos modelos agrupado e gasto do mês contra o orçamento (RAIZ_ORCAMENTO_MENSAL_USD)."""
    import datetime as dt

    from raiz.banco import engine
    from raiz.config import config
    from raiz.operacao.custo import custo_por, gasto_do_mes

    d = dt.date.fromisoformat(desde) if desde else dt.date.today().replace(day=1)
    with engine().connect() as con:
        linhas = custo_por(con, por, d)
        mes = gasto_do_mes(con)
    for r in linhas:
        aviso = f", {r.sem_preco} sem preço" if r.sem_preco else ""
        typer.echo(
            f"{r.chave or '-'}: US$ {float(r.custo_usd):.4f} em {r.chamadas} chamadas ({r.falhas} falhas{aviso})"
        )
    orc = config().orcamento_mensal_usd
    uso = f" de US$ {orc:.2f} ({100 * mes / orc:.0f}%)" if orc else " (sem orçamento definido)"
    typer.echo(f"gasto do mês: US$ {mes:.4f}{uso}")


coleta = typer.Typer(help="Coleta de dados públicos (E1).", no_args_is_help=True)
app.add_typer(coleta, name="coleta")


@coleta.command("fontes")
def coleta_fontes(dia: Annotated[str | None, typer.Option(help="AAAA-MM-DD; padrão: hoje")] = None) -> None:
    """Grava o manifesto no banco e mostra o que deve ser olhado no dia e o que está pendente."""
    import datetime as dt

    from raiz.banco import engine
    from raiz.coleta.manifesto import carregar
    from raiz.coleta.replicacao import devidas, sincronizar_fontes

    m = carregar()
    with engine().begin() as con:
        n = sincronizar_fontes(con, m)
    d = dt.date.fromisoformat(dia) if dia else dt.date.today()
    typer.echo(f"manifesto {m.versao}: {n} fontes")
    for fid, ufs in devidas(m, d):
        typer.echo(f"  hoje: {fid}" + (f" ({', '.join(ufs)})" if ufs else ""))
    for f in m.fontes:
        if f.pendente:
            typer.echo(f"  pendente: {f.id}: {f.pendente}")


@coleta.command("checar")
def coleta_checar() -> None:
    """HEAD em cada arquivo do manifesto: grava bytes, ETag e Last-Modified e avisa no Healthchecks se algo sumiu
    ou mudou. Rodar no servidor (este ambiente de desenvolvimento bloqueia os buckets)."""
    from raiz.banco import engine
    from raiz.coleta.checagem import checar
    from raiz.coleta.http import sessao
    from raiz.operacao.healthchecks import Healthchecks

    with engine().begin() as con:
        res = checar(con, sessao(), hc=Healthchecks())
    for r in res:
        marca = "FALTA" if r.faltando else ("MUDOU" if r.mudou else "ok")
        typer.echo(f"{marca:5} {r.fonte} {r.status or r.erro} {r.bytes or '-'} {r.url}")
    if any(r.faltando for r in res):
        sys.exit(1)


@coleta.command("car")
def coleta_car(
    ufs: Annotated[list[str] | None, typer.Argument(help="UFs; sem nada, as do rodízio de hoje")] = None,
    municipio: Annotated[list[int] | None, typer.Option(help="só estes municípios (repita a opção)")] = None,
    historico: Annotated[bool, typer.Option(help="gravar o histórico scd2 no PostGIS")] = True,
) -> None:
    """Rodada do CAR (e do SIGEF dos municípios que mudaram): assinatura, fila, espelho por município, histórico."""
    import datetime as dt

    from raiz.banco import engine
    from raiz.coleta.espelho import Espelho
    from raiz.coleta.http import sessao
    from raiz.coleta.manifesto import ufs_do_dia
    from raiz.coleta.municipios import da_uf
    from raiz.coleta.rodada import rodada_car
    from raiz.funil.ponte import espelho_padrao

    ufs = [u.upper() for u in (ufs or ufs_do_dia(dt.date.today()))]
    s_car, s_outros = sessao(tls_legado=True), sessao()
    muns = {uf: (municipio or da_uf(uf, s_outros)) for uf in ufs}
    r = rodada_car(engine(), s_car, Espelho(espelho_padrao()), muns, historico=historico, s_sigef=s_outros)
    typer.echo(
        f"verificados {r['verificados']}, baixados {r['baixados']}, falhas {r['falhas']}, "
        f"mudaram {len(r['mudaram'])}, cargas no histórico {r['historico']}"
    )
    for uf, modo in r["modo"].items():
        typer.echo(f"  {uf}: {modo}")
    if r["falhas"]:
        sys.exit(1)


@coleta.command("liberar")
def coleta_liberar(fonte: str, recorte: str) -> None:
    """Libera a próxima versão travada (mudou mais de 25% do arquivo do município, ou 15% dos municípios da UF).
    Ex.: raiz coleta liberar sicar_imoveis PA/1504950   ou   raiz coleta liberar sicar_imoveis PA"""
    from raiz.banco import engine
    from raiz.coleta.replicacao import atualizar

    with engine().begin() as con:
        atualizar(con, fonte, recorte, liberado=True)
    typer.echo(f"{fonte} {recorte}: liberado para a próxima rodada")


@coleta.command("ibama")
def coleta_ibama() -> None:
    """Embargos do Ibama: pedido condicional, sem dado pessoal, espelho por município e CSV limpo para o motor."""
    from raiz import MOTOR_DIR
    from raiz.banco import engine
    from raiz.coleta.espelho import Espelho
    from raiz.coleta.http import sessao
    from raiz.coleta.ibama import coletar
    from raiz.funil.ponte import espelho_padrao

    with engine().begin() as con:
        r = coletar(sessao(), con, Espelho(espelho_padrao()), MOTOR_DIR / "cache")
    typer.echo(
        f"{r.acao}: {r.linhas} termos, {len(r.municipios)} municípios mudaram; "
        f"colunas pessoais removidas: {', '.join(r.removidas) or 'nenhuma'}"
    )


@coleta.command("indice")
def coleta_indice(endereco: str, destino: str) -> None:
    """Índice de blocos de um GeoTIFF na nuvem (só o cabeçalho é lido) gravado em Parquet."""
    from pathlib import Path

    from raiz.coleta import blocos

    origem = blocos.ArquivoRemoto(endereco) if endereco.startswith("http") else endereco
    ind = blocos.indice(origem, Path(endereco).name)
    blocos.salvar_indice(ind, Path(destino))
    typer.echo(f"{len(ind)} blocos, {ind.nivel.nunique()} níveis, {ind.bytes.sum() / 1e9:.2f} GB -> {destino}")


modelos = typer.Typer(help="Modelos de linguagem (E7).", no_args_is_help=True)
app.add_typer(modelos, name="modelos")


@modelos.command("testar")
def modelos_testar(modelo: Annotated[str, typer.Option(help="ex.: claude-haiku-5-5")] = "claude-haiku-5-5") -> None:
    """Chamada curta pela interface única (saída estruturada, custo, rastro). Mostra de onde veio a chave, nunca o
    valor. A chave é lida de ANTHROPIC_API_KEY (ou RAIZ_ANTHROPIC_API_KEY), no ambiente ou no .env."""
    import os

    from raiz.config import config
    from raiz.modelos import Claude, LlamaCpp, Pedido, chamar

    origem = next((n for n in ("RAIZ_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(n)), None)
    if origem is None and config().anthropic_api_key:
        origem = ".env"
    typer.echo(f"chave da Anthropic: {'lida de ' + origem if origem else 'não encontrada'}")
    esquema = {
        "type": "object",
        "properties": {"resposta": {"type": "string", "enum": ["ok"]}},
        "required": ["resposta"],
        "additionalProperties": False,
    }
    p = Pedido("teste.conexao", "Responda só com o JSON pedido.", "Diga ok.", esquema, max_tokens=64)
    m = LlamaCpp() if modelo.startswith("qwen") else Claude(modelo)
    r = chamar(m, p)
    if r.ok:
        typer.echo(
            f"ok: {r.modelo} respondeu {r.dados} em {r.duracao_ms} ms; {r.uso.entrada}+{r.uso.saida} tokens; "
            f"US$ {r.custo_usd} ({r.custo_fonte})"
        )
    else:
        typer.echo(f"falhou: {r.erro}", err=True)
        sys.exit(1)


regras_cli = typer.Typer(help="Parâmetros legais versionados (E2).", no_args_is_help=True)
app.add_typer(regras_cli, name="regras")


@regras_cli.command("gerar")
def regras_gerar(
    testar: Annotated[bool, typer.Option(help="Rodar os testes em Catala (clerk test) antes de gerar.")] = True,
) -> None:
    """Compila as regras em Catala (raiz/regras/catala/) para Python em raiz/regras/gerado/. Precisa do opam."""
    from raiz.regras.catala_gerar import gerar

    info = gerar(testar=testar)
    typer.echo(f"{info['catala']}: {len(info['arquivos'])} arquivos em raiz/regras/gerado/")


@regras_cli.command("validar")
def regras_validar(
    arquivo: Annotated[str, typer.Argument(help="tabela da outra fonte por imóvel (CSV ou Parquet)")],
    fonte: Annotated[str, typer.Option(help="sicar | geocar | landschaft")],
    pasta: Annotated[str, typer.Option(help="pasta com imoveis_<município>.csv do motor")],
    municipio: Annotated[int, typer.Option(help="código IBGE do município piloto")],
    n: Annotated[int, typer.Option(help="quantas diferenças explicar")] = 10,
) -> None:
    """Validação cruzada (E2 passo 4): o laudo da Raíz contra outra fonte, imóvel a imóvel."""
    from pathlib import Path

    import pandas as pd

    from raiz import RAIZ_REPO
    from raiz.regras import validacao

    im = pd.read_csv(Path(pasta) / f"imoveis_{municipio}.csv")
    ext = pd.read_parquet(arquivo) if arquivo.endswith(".parquet") else pd.read_csv(arquivo)
    rel = validacao.comparar(im, ext, fonte)
    if validacao.FONTES[fonte].get("provisorio"):
        typer.echo(f"atenção: o mapa de colunas de {fonte} é provisório; confira com o arquivo (validacao.FONTES)")
    typer.echo(rel.resumo.to_string())
    for k, v in rel.sem_par.items():
        typer.echo(f"{k}: {len(v)} imóveis")
    saida = RAIZ_REPO / "dados" / "validacao" / f"{fonte}_{municipio}.csv"
    saida.parent.mkdir(parents=True, exist_ok=True)
    rel.linhas.to_csv(saida, index=False)
    for linha in validacao.explicar_diferencas(rel, im, n):
        typer.echo(linha)
    typer.echo(f"todas as linhas em {saida}")


@regras_cli.command("publicar")
def regras_publicar() -> None:
    """Grava no banco a versão atual dos parâmetros legais (raiz/regras/parametros/*.yaml) e lista as pendências."""
    from raiz.banco import engine
    from raiz.regras import parametros, publicar

    with engine().begin() as con:
        v, nova = publicar(con)
    typer.echo(f"{v}: {'publicada' if nova else 'já estava publicada'}")
    for x in parametros().valores:
        if x.pendente:
            typer.echo(f"  pendente: {x.parametro} {x.rotulos}: {x.pendente}")


@funil.command("bancada")
def funil_bancada(uf: str, municipio: int, camada: str = "accumulated_deforestation_2007") -> None:
    """GEOS (motor) contra iOverlay (caminho novo) nos mesmos pares imóvel x camada, com o cache do funil."""
    from raiz.funil.bancada import bancada

    r = bancada(uf, municipio, camada)
    typer.echo(f"{r['camada']}: {r['imoveis']} imóveis, {r['poligonos']} polígonos, {r['pares']} pares")
    typer.echo(
        f"  GEOS {r['geos_s']} s, iOverlay {r['iov_s']} s ({r['vezes']}x); área {r['area_geos_ha']} ha contra "
        f"{r['area_iov_ha']} ha; maior diferença por par {r['maior_dif_m2']} m², pares com mais de 1 m²: "
        f"{r['pares_dif_1m2']}"
    )
    typer.echo(
        f"  pares: índice espacial {r['pares_indice_s']} s, DuckDB (SPATIAL_JOIN) {r['pares_duckdb_s']} s; "
        f"{'iguais' if r['pares_iguais'] else 'DIFERENTES'}"
    )


@banco.command("migrar")
def banco_migrar(alvo: str = "head") -> None:
    """Aplica as migrações (Alembic) no banco de RAIZ_BANCO_URL."""
    from raiz.banco import migrar
    from raiz.config import config

    migrar(alvo=alvo)
    typer.echo(f"banco migrado até {alvo}")
    if config().chave_pessoal and alvo == "head":
        from raiz.agentes.memoria import preparar

        preparar()
        typer.echo("tabelas de conversa (LangGraph, cifradas) prontas no esquema pessoal")
    else:
        typer.echo("sem RAIZ_CHAVE_PESSOAL: tabelas de conversa não criadas")


@app.command("api")
def api(porta: int = 8000, host: str = "127.0.0.1") -> None:
    """Sobe a API (aceites, mensagens a aprovar, revisões e webhook do WhatsApp em /whatsapp)."""
    import uvicorn

    from raiz.api import criar_app

    uvicorn.run(criar_app(), host=host, port=porta)


if __name__ == "__main__":
    app()


geo_cli = typer.Typer(help="Camadas geográficas do front no PostGIS (rotas /geo da API).", no_args_is_help=True)
app.add_typer(geo_cli, name="geo")


@geo_cli.command("carregar")
def geo_carregar(
    municipios: Annotated[list[int], typer.Argument(help="códigos IBGE")],
    pasta: Annotated[
        str | None, typer.Option(help="saída do front/scripts/geo.py; padrão RAIZ_GEO_DIR ou front/geo")
    ] = None,
) -> None:
    """Grava no PostGIS a divisa, as TIs, as UCs e os rios que front/scripts/geo.py gerou para cada município."""
    from pathlib import Path

    from raiz.banco import engine
    from raiz.geo import arquivo_base, carregar

    p = Path(pasta) if pasta else None
    with engine().begin() as con:
        for cod in municipios:
            n = carregar(con, cod, p)
            base = "com mapa base" if arquivo_base(cod, p) else "sem mapa base"
            typer.echo(f"{cod}: {n or 'nenhum arquivo'} ({base})")


@app.command("vigiar")
def vigiar_saida(
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    intervalo: Annotated[int, typer.Option(help="segundos entre uma volta e outra")] = 300,
    uma_vez: Annotated[bool, typer.Option(help="dá uma volta só e sai (para cron)")] = False,
    ufs: Annotated[str | None, typer.Option(help="só estas UFs, separadas por vírgula")] = None,
    congelar: Annotated[bool, typer.Option(help="congelar as previsões de cada rodada nova (E8)")] = True,
) -> None:
    """Carga contínua: leva ao banco cada município que o motor terminar em saida/<UF>/ (só o que mudou)."""
    from pathlib import Path

    from raiz.banco import engine
    from raiz.carga_continua import varrer, vigiar
    from raiz.funil.rodar import dir_trabalho

    pasta = Path(saida) if saida else dir_trabalho() / "saida"
    lista = [u.strip().upper() for u in ufs.split(",")] if ufs else None
    if uma_vez:
        r = varrer(engine(), pasta, ufs=lista, congelar=congelar)
        typer.echo(
            f"{len(r['carregados'])} municípios carregados, "
            f"{r['pulados']} sem mudança, {len(r['esperando'])} esperando o motor terminar, {len(r['falhas'])} falhas"
        )
        for f in r["falhas"]:
            typer.echo(f"  falha {f['chave']}: {f['erro']}")
        raise typer.Exit(1 if r["falhas"] else 0)
    vigiar(engine(), pasta, intervalo, ufs=lista, congelar=congelar)


flag_cli = typer.Typer(
    help="Meta FLAG pela GHG Protocol LSR (regra versionada em raiz/regras/padroes/).", no_args_is_help=True
)
app.add_typer(flag_cli, name="flag")


@flag_cli.command("recalcular")
def flag_recalcular(
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    ufs: Annotated[str | None, typer.Option(help="só estas UFs, separadas por vírgula")] = None,
) -> None:
    """Refaz flag_<mun>.csv que falta ou que foi calculado com outra versão da regra."""
    from pathlib import Path

    from raiz import flag as F
    from raiz.funil.rodar import dir_trabalho

    pasta = Path(saida) if saida else dir_trabalho() / "saida"
    lista = [u.strip().upper() for u in ufs.split(",")] if ufs else None
    r = F.recalcular(pasta, lista, cache_motor=dir_trabalho() / "cache")
    typer.echo(f"regra {F.versao()}: {len(r['refeitos'])} municípios refeitos, {r['em_dia']} já em dia")
