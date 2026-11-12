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
    ] = "funil,filtros,direto,mapbiomas,extras_direto,flag,terra,ficha,desenvolvedor,carga",
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


operacao = typer.Typer(help="Operação: custo dos modelos, lotes, alertas e backoffice.", no_args_is_help=True)
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


@operacao.command("alertas")
def operacao_alertas() -> None:
    """Olha o que está errado (lotes, orçamento, vigilância, prazo da Verra, filas, grupos com problema), abre um
    alerta por problema e sobe a escada do que ninguém reconheceu (ntfy; GoAlert com segunda pessoa). Sem
    RAIZ_NTFY_TOPICO, o envio é simulado e fica registrado. Rodar de 15 em 15 minutos (cron)."""
    from raiz.banco import engine
    from raiz.operacao.alertas import ciclo

    r = ciclo(engine())
    typer.echo(
        f"abertos: {r['abertos']}; fechados sozinhos: {r['fechados_sozinhos']}; envios: {len(r['envios'])} "
        f"({', '.join(sorted({e['estado'] for e in r['envios']})) or 'nenhum'}); olhado: {', '.join(r['olhadas'])}"
    )


@operacao.command("reconhecer")
def operacao_reconhecer(
    alerta: Annotated[int, typer.Argument(help="id do alerta")],
    quem: Annotated[str, typer.Option(help="papel de quem reconhece")] = "fundador",
) -> None:
    """Para a escada de um alerta (alguém já está cuidando)."""
    from raiz.banco import engine
    from raiz.operacao.alertas import reconhecer

    with engine().begin() as con:
        ok = reconhecer(con, alerta, quem)
    typer.echo("reconhecido" if ok else "alerta aberto não encontrado")


@operacao.command("resolver")
def operacao_resolver(
    alerta: Annotated[int, typer.Argument(help="id do alerta")],
    nota: Annotated[str, typer.Option(help="o que foi feito")] = "",
    quem: Annotated[str, typer.Option(help="papel de quem resolve")] = "fundador",
) -> None:
    """Fecha um alerta."""
    from raiz.banco import engine
    from raiz.operacao.alertas import resolver

    with engine().begin() as con:
        ok = resolver(con, alerta, quem, nota)
    typer.echo("resolvido" if ok else "alerta aberto não encontrado")


@operacao.command("painel")
def operacao_painel() -> None:
    """O resumo do backoffice no terminal (saúde, custo do mês, filas e alertas abertos), em JSON."""
    import json

    from raiz.banco import engine
    from raiz.operacao.backoffice import resumo

    typer.echo(json.dumps(resumo(engine()), ensure_ascii=False, indent=1, default=str))


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


restauracao_cli = typer.Typer(
    help="Valor de cada fazenda para quem restaura com crédito de carbono (premissas em raiz/regras/padroes/).",
    no_args_is_help=True,
)
app.add_typer(restauracao_cli, name="restauracao")


@restauracao_cli.command("recalcular")
def restauracao_recalcular(
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    ufs: Annotated[str | None, typer.Option(help="só estas UFs, separadas por vírgula")] = None,
) -> None:
    """Refaz desenvolvedor_<mun>.csv que falta ou foi calculado com outra versão das premissas ou do cenário."""
    from pathlib import Path

    from raiz import restauracao as RS
    from raiz.funil.rodar import dir_trabalho

    pasta = Path(saida) if saida else dir_trabalho() / "saida"
    lista = [u.strip().upper() for u in ufs.split(",")] if ufs else None
    r = RS.recalcular(pasta, lista, cache_motor=dir_trabalho() / "cache")
    typer.echo(f"versão {RS.versao()}: {len(r['refeitos'])} municípios refeitos, {r['em_dia']} já em dia")
    for e in r["erros"]:
        typer.echo(f"  erro {e}")


rebanho_cli = typer.Typer(help="Rebanho por fazenda pela PPM e metano do gado (E4).", no_args_is_help=True)
app.add_typer(rebanho_cli, name="rebanho")


@rebanho_cli.command("recalcular")
def rebanho_recalcular(
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    ufs: Annotated[str | None, typer.Option(help="só estas UFs, separadas por vírgula")] = None,
) -> None:
    """Grava rebanho_<mun>.csv onde falta ou foi feito com outra versão da PPM ou das premissas."""
    from pathlib import Path

    from raiz import rebanho as RB
    from raiz.funil.rodar import dir_trabalho

    base = Path(saida) if saida else dir_trabalho() / "saida"
    lista = [u.strip().upper() for u in ufs.split(",")] if ufs else sorted(p.name for p in base.iterdir() if p.is_dir())
    feitos = em_dia = 0
    for uf in lista:
        for f in sorted((base / uf).glob("imoveis_*.csv")):
            cod = int(f.stem.split("_")[-1])
            if RB.versao_do_arquivo(base / uf / f"rebanho_{cod}.csv") == RB.versao():
                em_dia += 1
                continue
            RB.escrever_municipio(base / uf, cod)
            feitos += 1
    typer.echo(f"versão {RB.versao()}: {feitos} municípios refeitos, {em_dia} já em dia")


@restauracao_cli.command("cambio")
def restauracao_cambio(
    gravar: Annotated[
        bool, typer.Option(help="gravar a PTAX nas premissas (muda a versão; o recalcular refaz)")
    ] = False,
) -> None:
    """PTAX de venda do dólar no Banco Central. Com --gravar, os cenários com cambio_ptax passam a usá-la."""
    from raiz import restauracao as RS

    try:
        c = RS.ptax()
    except Exception as e:  # noqa: BLE001 - sem rede, segue o câmbio fixo do cenário
        typer.echo(f"não consegui a PTAX ({e}); segue o câmbio do cenário")
        raise typer.Exit(1) from e
    typer.echo(f"PTAX de venda de {c['data']}: R$ {c['ptax']:.4f}")
    if gravar:
        f = RS.gravar_cambio(c)
        typer.echo(f"gravada em {f}; versão das premissas agora {RS.versao()}")


@restauracao_cli.command("informar")
def restauracao_informar(
    cod_imovel: Annotated[str, typer.Argument(help="código do CAR (com ou sem pontos e traços)")],
    fonte: Annotated[str, typer.Option(help="quem mediu: desenvolvedor, parcela, nota fiscal (sem nome de pessoa)")],
    custo_rs_ha: Annotated[float | None, typer.Option(help="custo real de restauração, R$/ha")] = None,
    captura_tco2_ha_ano: Annotated[float | None, typer.Option(help="captura medida, tCO2/ha/ano")] = None,
    credito_tco2_ha_ano: Annotated[float | None, typer.Option(help="crédito líquido emitido, tCO2/ha/ano")] = None,
    modo: Annotated[str | None, typer.Option(help="regeneracao_assistida, semeadura_direta ou plantio_total")] = None,
    data: Annotated[str | None, typer.Option(help="data da medição (AAAA-MM-DD); padrão hoje")] = None,
    referencia: Annotated[str | None, typer.Option(help="documento ou contrato de onde veio o dado")] = None,
) -> None:
    """Grava o real informado pelo cliente para comparar com o que a Raíz previu."""
    import datetime as dt

    from sqlalchemy import text

    from raiz.banco import engine
    from raiz.busca import normalizar_codigo
    from raiz.restauracao_aprendizado import informar

    eng = engine()
    with eng.begin() as con:
        cod = con.execute(
            text("select cod_imovel from funil.vigente where cod_busca = :b"), {"b": normalizar_codigo(cod_imovel)}
        ).scalar()
        if cod is None:
            typer.echo("imóvel não carregado no banco")
            raise typer.Exit(1)
        quando = dt.date.fromisoformat(data) if data else dt.date.today()
        ids = informar(con, cod, quando, fonte, custo_rs_ha, captura_tco2_ha_ano, credito_tco2_ha_ano, modo, referencia)
    typer.echo(f"{len(ids)} valores reais gravados para {cod} em {quando.isoformat()}")


@restauracao_cli.command("comparar")
def restauracao_comparar() -> None:
    """Real contra previsto por modo: razão mediana, cobertura da faixa P10-P90 e acerto do modo."""
    from raiz.banco import engine
    from raiz.restauracao_aprendizado import comparar

    with engine().connect() as con:
        linhas = comparar(con)
    if not linhas:
        typer.echo("nenhum valor real informado ainda")
    for c in linhas:
        typer.echo(", ".join(f"{k}={v}" for k, v in c.items()))


@restauracao_cli.command("recalibrar")
def restauracao_recalibrar(
    gravar: Annotated[bool, typer.Option(help="gravar restauracao_calibracao.yaml (muda a versão do modelo)")] = False,
) -> None:
    """Propõe (ou grava) os fatores de calibração de custo e captura por modo a partir do real dos clientes."""
    from raiz.banco import engine
    from raiz.restauracao_aprendizado import recalibrar

    with engine().connect() as con:
        r = recalibrar(con, gravar=gravar)
    for grupo, modo, fator in r["mudou"]:
        typer.echo(f"{grupo} {modo}: fator {fator}")
    typer.echo(("gravado em " + r["arquivo"]) if r["gravado"] else "nada gravado (use --gravar)")


executor_cli = typer.Typer(
    help="Agente Dados: o motor rodando dentro do produto, por estado e município, com retomada e armazém S3.",
    no_args_is_help=True,
)
app.add_typer(executor_cli, name="executor")


def _ufs(ufs: str | None) -> list[str]:
    from raiz.executor.tarefas import UFS

    if not ufs or ufs.strip().lower() in ("brasil", "br", "todas"):
        return list(UFS)
    return [u.strip().upper() for u in ufs.split(",") if u.strip()]


@executor_cli.command("rodar")
def executor_rodar(
    ufs: Annotated[str, typer.Option(help="UFs separadas por vírgula, ou brasil")],
    municipios: Annotated[str | None, typer.Option(help="só estes códigos do IBGE, separados por vírgula")] = None,
    lanes: Annotated[int, typer.Option(help="municípios ao mesmo tempo")] = 1,
    refazer: Annotated[bool, typer.Option(help="refazer tudo, mesmo o que está em dia (rodada completa)")] = False,
    ate_minutos: Annotated[
        float | None, typer.Option(help="parar de começar municípios depois disso e publicar (Actions: 330)")
    ] = None,
) -> None:
    """Roda os estados retomando de onde parou: município com a marca em dia é pulado; o resto refaz só o que mudou.
    No GitHub Actions (processar-estados.yml): RAIZ_ARMAZEM_URL=release-github://bernardoemmel/raiz/dados, GH_TOKEN e
    RAIZ_SEM_BANCO=1; lê e grava no Release "dados"."""
    import time

    from raiz.executor import tarefas as T

    ex = T.executor_producao()
    cods = [int(c) for c in municipios.split(",")] if municipios else None
    fim = time.time() + ate_minutos * 60 if ate_minutos else None
    for uf in _ufs(ufs):
        resta = None if fim is None else max(fim - time.time(), 0)
        r = ex.rodar_uf(uf, cods, refazer=refazer, lanes=lanes, preparar=T.preparar, ate_s=resta)
        typer.echo(f"{uf}: {r['situacao']}, {r['feitos']} de {r['total']} municípios, {r['rodados']} rodados, "
                   f"{len(r['erros'])} com erro ({ex.a.descricao})")  # fmt: skip


@executor_cli.command("adotar")
def executor_adotar(
    ufs: Annotated[str, typer.Option(help="UFs separadas por vírgula, ou brasil")],
) -> None:
    """Dá marca de concluído às saídas já publicadas sem marca (ex.: o PA que já está no Release), na versão atual
    de cada tarefa. Depois disso o executor só roda o que faltar (as tarefas do produto) ou o que mudar."""
    from raiz.executor import tarefas as T

    ex = T.executor_producao()
    for uf in _ufs(ufs):
        r = ex.adotar(uf)
        typer.echo(f"{uf}: {r['adotados']} municípios adotados, {r['ja_tinham_marca']} já tinham marca; {r['tarefas']}")


@executor_cli.command("publicar")
def executor_publicar(ufs: Annotated[str, typer.Option(help="UFs separadas por vírgula")]) -> None:
    """Empacota e sobe o estado no Release (precisa de GH_TOKEN ou GITHUB_TOKEN: só de dentro do GitHub Actions)."""
    from raiz.executor.armazem import do_config

    a = do_config()
    if not hasattr(a, "publicar"):
        typer.echo(f"o armazém configurado ({a.descricao}) não publica: grava direto")
        raise typer.Exit(0)
    for uf in _ufs(ufs):
        info = a.publicar(uf).get(uf, {})
        typer.echo(f"{uf}: {info.get('municipios')} municípios, versão {info.get('versao')}")


@executor_cli.command("plano")
def executor_plano(
    uf: Annotated[str, typer.Option(help="UF")],
    municipios: Annotated[str | None, typer.Option(help="só estes códigos do IBGE")] = None,
) -> None:
    """O que rodaria agora em cada município (sem rodar nada)."""
    from collections import Counter

    from raiz.executor import tarefas as T

    ex = T.executor_producao()
    cods = [int(c) for c in municipios.split(",")] if municipios else T.municipios_da_uf(uf)
    cont = Counter()
    for c in cods:
        p = ex.plano(uf.upper(), c)
        cont.update(p)
        if municipios:
            typer.echo(f"{c}: {', '.join(p) or 'em dia'}")
    typer.echo(f"{uf.upper()}: {len(cods)} municípios; tarefas a rodar: {dict(cont) or 'nenhuma'}")


@executor_cli.command("ciclo")
def executor_ciclo(
    ufs: Annotated[str, typer.Option(help="UFs separadas por vírgula, ou brasil")] = "brasil",
    lanes: Annotated[int, typer.Option(help="municípios ao mesmo tempo")] = 1,
    carregar: Annotated[bool, typer.Option(help="espelhar o armazém e carregar no banco depois de cada estado")] = True,
) -> None:
    """Uma volta da agenda: completa se a coleção do MapBiomas mudou, parcial no resto."""
    from raiz.executor import agenda
    from raiz.executor import tarefas as T

    ex = T.executor_producao()
    car = None
    if carregar:
        from raiz.banco import engine
        from raiz.executor.sincronizar import carregar as carregar_armazem

        eng = engine()
        car = lambda u: {k: len(v) if isinstance(v, list) else v for k, v in carregar_armazem(eng, ex.a, u).items()}  # noqa: E731
    r = agenda.ciclo(ex, _ufs(ufs), lanes, car, preparar=T.preparar)
    typer.echo(f"rodada {'completa' if r['completa'] else 'parcial'} (coleção {r['colecao']}):")
    for uf, e in r["estados"].items():
        typer.echo(f"  {uf}: {e}")


@executor_cli.command("vigiar")
def executor_vigiar(
    ufs: Annotated[str, typer.Option(help="UFs separadas por vírgula, ou brasil")] = "brasil",
    intervalo_h: Annotated[float, typer.Option(help="horas entre uma volta e outra")] = 24.0,
    lanes: Annotated[int, typer.Option(help="municípios ao mesmo tempo")] = 1,
) -> None:
    """Repete o ciclo (completa uma vez por ano, parcial no resto) e carrega no banco."""
    from raiz.banco import engine
    from raiz.executor import agenda
    from raiz.executor import tarefas as T
    from raiz.executor.sincronizar import carregar as carregar_armazem

    ex = T.executor_producao()
    eng = engine()
    agenda.vigiar(ex, _ufs(ufs), intervalo_h, lanes, lambda u: carregar_armazem(eng, ex.a, u), preparar=T.preparar)


@executor_cli.command("sincronizar")
def executor_sincronizar(
    ufs: Annotated[str | None, typer.Option(help="UFs separadas por vírgula; padrão: todas")] = None,
    carregar: Annotated[bool, typer.Option(help="carregar no banco o que mudou")] = True,
) -> None:
    """O back-end espelha o armazém numa pasta local e carrega no banco o que mudou."""
    from raiz.executor.armazem import do_config
    from raiz.executor.sincronizar import carregar as carregar_armazem
    from raiz.executor.sincronizar import sincronizar

    a = do_config()
    lista = _ufs(ufs) if ufs else None
    if carregar:
        from raiz.banco import engine

        r = carregar_armazem(engine(), a, lista)
        typer.echo(f"{r['baixados']} arquivos baixados de {a.descricao}; {len(r['carregados'])} municípios carregados")
    else:
        typer.echo(f"{len(sincronizar(a, None, lista))} arquivos baixados de {a.descricao}")


@executor_cli.command("estado")
def executor_estado() -> None:
    """Estados prontos, em andamento e com erro, com a versão do motor de cada um."""
    from raiz.executor.armazem import do_config
    from raiz.executor.painel import processamento

    p = processamento(do_config())
    typer.echo(f"{p['contagem']} (coleção do MapBiomas {p['colecao_mapbiomas']}, feita: {p['colecao_feita']})")
    for e in p["estados"]:
        if e["situacao"] != "nao_iniciado":
            typer.echo(f"  {e['uf']}: {e['situacao']}, {e['feitos']} de {e['total']}, {e['erros']} erros, "
                       f"{e['motor_versao']}")  # fmt: skip


terra_cli = typer.Typer(
    help="Caminho da terra por imóvel e camada de terra pública para restaurar (regra em raiz/regras/padroes/).",
    no_args_is_help=True,
)
app.add_typer(terra_cli, name="terra")


@terra_cli.command("recalcular")
def terra_recalcular(
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    ufs: Annotated[str | None, typer.Option(help="só estas UFs, separadas por vírgula")] = None,
) -> None:
    """Refaz terra_<mun>.csv que falta ou foi calculado com outra versão da regra ou das concessões."""
    from pathlib import Path

    from raiz import terra as T
    from raiz.funil.rodar import dir_trabalho

    pasta = Path(saida) if saida else dir_trabalho() / "saida"
    lista = [u.strip().upper() for u in ufs.split(",")] if ufs else None
    r = T.recalcular(pasta, lista, cache_motor=dir_trabalho() / "cache")
    typer.echo(f"regra {T.versao()}: {len(r['refeitos'])} municípios refeitos, {r['em_dia']} já em dia")
    for e in r["erros"]:
        typer.echo(f"  erro {e}")


@terra_cli.command("preparar-cnfp")
def terra_preparar_cnfp() -> None:
    """Baixa o Cadastro Nacional de Florestas Públicas (SFB) e grava um GeoParquet por estado."""
    from raiz import terra_publica as TP

    z = TP.baixar_cnfp()
    for uf, n in TP.preparar_cnfp(z).items():
        typer.echo(f"{uf}: {n} áreas")


@terra_cli.command("publica")
def terra_publica_gerar(
    ufs: Annotated[str, typer.Option(help="UFs separadas por vírgula")],
    carregar: Annotated[bool, typer.Option(help="carregar no banco (geo.terra_publica)")] = True,
    reducao: Annotated[int, typer.Option(help="grade da distância à mata: 1 = 30 m, 4 = 120 m")] = 4,
) -> None:
    """Gera a camada "Terra pública para restaurar" de cada estado e carrega no banco."""
    from raiz import terra_publica as TP
    from raiz.funil.rodar import dir_trabalho

    for uf in [u.strip().upper() for u in ufs.split(",")]:
        f = TP.gerar_uf(uf, dir_trabalho() / "cache", reducao=reducao)
        if f is None:
            typer.echo(f"{uf}: sem área pública candidata")
            continue
        n = 0
        if carregar:
            from raiz.banco import engine

            n = TP.carregar(engine(), f)
        typer.echo(f"{uf}: {f.name}{f', {n} áreas no banco' if carregar else ''}")


@terra_cli.command("editais")
def terra_editais() -> None:
    """Confere as páginas de editais do SFB e do Ideflor-Bio e lista os links novos (registrar em concessoes.yaml)."""
    from raiz import terra_publica as TP

    r = TP.conferir_editais()
    for n in r["novos"]:
        typer.echo(f"novo ({n['fonte']}, visto em {n['visto_em']}): {n['texto']} {n['link']}")
    for f, e in r["erros"].items():
        typer.echo(f"erro em {f}: {e}")
    typer.echo(f"{len(r['novos'])} novos, {r['total']} links guardados")


ficha_cli = typer.Typer(help="Colunas e camadas dentro do imóvel para o front (design v1).", no_args_is_help=True)
app.add_typer(ficha_cli, name="ficha")


@ficha_cli.command("gerar")
def ficha_gerar(
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    ufs: Annotated[str | None, typer.Option(help="só estas UFs, separadas por vírgula")] = None,
    refazer: Annotated[bool, typer.Option(help="refazer municípios que já têm ficha_<mun>.csv")] = False,
) -> None:
    """Gera ficha_<mun>.csv, camadas_<mun>.parquet e camadas_<mun>.pmtiles para os municípios do motor."""
    from pathlib import Path

    from raiz.carga import municipios_na_pasta
    from raiz.funil.rodar import dir_trabalho
    from raiz.imovel_dados import escrever_municipio
    from raiz.osm import build_recente

    base = Path(saida) if saida else dir_trabalho() / "saida"
    lista = [u.strip().upper() for u in ufs.split(",")] if ufs else sorted(p.name for p in base.iterdir() if p.is_dir())
    dia = build_recente()
    for uf in lista:
        for cod in municipios_na_pasta(base / uf):
            if (base / uf / f"ficha_{cod}.csv").exists() and not refazer:
                continue
            r = escrever_municipio(base / uf, cod, dir_trabalho() / "cache", dia)
            typer.echo(f"{uf} {cod}: {r}")


@ficha_cli.command("lote")
def ficha_lote(
    uf: Annotated[str | None, typer.Option(help="só esta UF")] = None,
    municipios: Annotated[str | None, typer.Option(help="só estes códigos IBGE, separados por vírgula")] = None,
    destino: Annotated[str | None, typer.Option(help="pasta; padrão: RAIZ_FICHAS_DIR ou dados/fichas")] = None,
    refazer: Annotated[bool, typer.Option(help="regravar mesmo o município cuja rodada não mudou")] = False,
) -> None:
    """Grava a ficha JSON de cada fazenda do banco, o rows.json do cartão e do vídeo e o índice (E9, passo 1)."""
    from pathlib import Path

    from raiz import fichas_lote
    from raiz.banco import engine

    cods = [int(x) for x in municipios.split(",")] if municipios else None
    r = fichas_lote.gravar(
        engine(), Path(destino) if destino else None, uf, cods, refazer, aviso=lambda t: typer.echo(f"  {t}")
    )
    typer.echo(
        f"{r['gravados']} município(s) gravado(s), {r['fichas']} fichas; {r['iguais']} sem mudança; em {r['destino']}"
    )


mapa_cli = typer.Typer(help="Mapa base do Brasil (recorte do Protomaps, fontes e sprites).", no_args_is_help=True)
app.add_typer(mapa_cli, name="mapa")


@mapa_cli.command("atualizar")
def mapa_atualizar(
    dia: Annotated[str | None, typer.Option(help="build AAAAMMDD; padrão: o mais recente")] = None,
) -> None:
    """Recorta o Brasil até o zoom 14 do build do Protomaps, baixa fontes e sprites e grava o manifesto."""
    from raiz import mapa_base

    m = mapa_base.atualizar(dia)
    typer.echo(f"mapa base {m['arquivo']}: {m['bytes'] / 1e9:.1f} GB, zoom até {m['zoom_max']}")


satelite_cli = typer.Typer(help="Imagens de satélite por fazenda (Sentinel-2 e Landsat).", no_args_is_help=True)
app.add_typer(satelite_cli, name="satelite")


@satelite_cli.command("gerar")
def satelite_gerar(
    municipio: Annotated[int, typer.Option(help="código IBGE: gera para os imóveis aptos do município")],
    tipos: Annotated[str, typer.Option(help="separados por vírgula")] = "hoje,hoje-produtor,hoje-celular,simulacao",
    limite: Annotated[int, typer.Option(help="no máximo quantos imóveis")] = 50,
) -> None:
    """Gera e guarda as imagens dos imóveis aptos de um município (as maiores áreas de carbono primeiro)."""
    import shapely
    from sqlalchemy import text

    from raiz import satelite
    from raiz.banco import engine

    with engine().connect() as con:
        linhas = con.execute(
            text("""select v.cod_busca, ST_AsBinary(i.geom),
                           (select ST_AsBinary(ST_Union(c.geom)) from geo.camada_imovel c
                            where c.cod_imovel = v.cod_imovel and c.camada = 'pode_voltar')
                    from funil.vigente v join funil.imovel i on i.cod_imovel = v.cod_imovel
                    join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                    where v.cod_municipio_ibge = :m and i.geom is not null
                    order by r.carbono_ha desc nulls last limit :n"""),
            {"m": municipio, "n": limite},
        ).all()
    for b, g, pv in linhas:
        try:
            r = satelite.gerar(b, shapely.from_wkb(bytes(g)), shapely.from_wkb(bytes(pv)) if pv else None,
                               tipos=[t.strip() for t in tipos.split(",")])  # fmt: skip
            typer.echo(f"{b}: " + ", ".join(f"{k} {v['bytes'] // 1024} KB" for k, v in r.items()))
        except LookupError as ex:
            typer.echo(f"{b}: {ex}")


municipio_cli = typer.Typer(help="Dados por município para o front (design v1, item 4).", no_args_is_help=True)
app.add_typer(municipio_cli, name="municipio")


@municipio_cli.command("urbana")
def municipio_urbana(municipios: Annotated[list[int], typer.Argument(help="códigos IBGE")]) -> None:
    """Gera o contorno da área urbanizada da sede (MapBiomas) e grava no PostGIS."""
    from raiz.banco import engine
    from raiz.funil.rodar import dir_trabalho
    from raiz.municipio_dados import urbana

    eng = engine()
    for cod in municipios:
        with eng.connect() as con:
            from sqlalchemy import text

            uf = con.execute(text("select uf from funil.municipio_busca where cod_ibge = :c"), {"c": cod}).scalar()
        tifs = sorted((dir_trabalho() / "cache" / "mapbiomas" / str(uf)).glob(f"{uf}_cobertura_*.tif"))
        if not tifs:
            typer.echo(f"{cod}: sem cobertura do MapBiomas em cache para {uf}")
            continue
        m = urbana(eng, cod, tifs[-1])
        typer.echo(f"{cod}: " + (f"{m.area * 111.32**2 * 100:.0f} ha (aprox.)" if m is not None else "sede não achada"))


pedidos_cli = typer.Typer(
    help="Pedido de lote (docs/cena-alvo.md): oferta por fazenda, clientes, ondas de contato, reservas e vigia.",
    no_args_is_help=True,
)
app.add_typer(pedidos_cli, name="pedidos")


@pedidos_cli.command("oferta")
def pedidos_oferta(
    ufs: Annotated[str | None, typer.Option(help="UFs separadas por vírgula; padrão: todos os municípios")] = None,
) -> None:
    """Refaz a oferta (negocio.oferta) a partir do banco; a carga de cada município já faz isso sozinha."""
    from sqlalchemy import text

    from raiz.banco import engine
    from raiz.pedidos.oferta import atualizar

    eng = engine()
    with eng.connect() as con:
        q = "select distinct cod_municipio_ibge from funil.vigente"
        par = {}
        if ufs:
            q += " v where exists (select 1 from funil.imovel i where i.cod_imovel = v.cod_imovel and i.uf = any(:u))"
            par = {"u": [u.strip().upper() for u in ufs.split(",")]}
        cods = [r[0] for r in con.execute(text(q), par) if r[0] is not None]
    total = sum(atualizar(eng, c) for c in cods)
    typer.echo(f"oferta refeita: {total} fazendas em {len(cods)} municípios")


@pedidos_cli.command("cliente")
def pedidos_cliente(
    rotulo: Annotated[str, typer.Option(help="nome da empresa (nunca CPF)")],
    email: Annotated[str | None, typer.Option(help="e-mail de quem entra (fica cifrado)")] = None,
) -> None:
    """Cria um cliente e mostra o token da primeira sessão (uma vez só). Depois a pessoa entra pelo link do e-mail."""
    from raiz.banco import engine
    from raiz.pedidos import servico as S

    cid, token = S.criar_cliente(engine(), rotulo, email)
    typer.echo(f"cliente {cid} criado. Token da sessão (guarde agora, não aparece de novo): {token}")


@pedidos_cli.command("chave")
def pedidos_chave(
    cliente: Annotated[int, typer.Option(help="id do cliente (empresa)")],
    rotulo: Annotated[str | None, typer.Option(help="qual agente usa a chave")] = None,
    limite_minuto: Annotated[int, typer.Option(help="chamadas por minuto")] = 30,
    limite_dia: Annotated[int, typer.Option(help="chamadas por dia")] = 2000,
) -> None:
    """Cria a chave de API da empresa para o agente de IA dela (a chave aparece uma vez só). A própria empresa também
    cria pela API: POST /v1/chaves, na sessão do login por e-mail."""
    from raiz.banco import engine
    from raiz.publica import chaves as K

    k = K.criar(engine(), cliente, rotulo, limite_minuto, limite_dia)
    typer.echo(f"chave {k['prefixo']}... criada (guarde agora, não aparece de novo): {k['chave']}")


@app.command("mcp")
def mcp_stdio(
    url: Annotated[str | None, typer.Option(help="endereço da API; padrão RAIZ_API_URL")] = None,
) -> None:
    """Servidor MCP da Raíz por stdio, para o Claude Desktop, o Claude Code e outros clientes locais (a chave da
    empresa vem de RAIZ_CHAVE_API). O remoto, por HTTP, fica em /mcp na própria API (docs/agentes-ia.md)."""
    from raiz.publica.servidor_mcp import ApiRaiz, criar_servidor

    criar_servidor(ApiRaiz(url=url)).run("stdio")


@pedidos_cli.command("ciclo")
def pedidos_ciclo() -> None:
    """Um passo de tudo o que anda sozinho: ondas (vence quem não respondeu, chama a próxima onda, fecha o grupo),
    reservas vencidas voltam para a base e o vigia dos pedidos salvos, que antes traz o estado publicado da
    vigilância diária (desmatamento e embargo novos nas fazendas do grupo). Rodar de hora em hora (cron)."""
    from raiz.banco import engine
    from raiz.pedidos import servico as S
    from raiz.vigilancia.pedidos import atualizar_estado

    eng = engine()
    estados = {pid: S.avancar(eng, pid) for pid in S.pedidos_abertos(eng)}
    exp = S.expirar_reservas(eng)
    atualizar_estado()
    vig = S.vigiar(eng)
    typer.echo(f"ondas: {estados or 'nenhum pedido buscando interesse'}; reservas vencidas: {exp}; vigia: {vig}")


@pedidos_cli.command("pagar-teste")
def pedidos_pagar_teste(cobranca: Annotated[str, typer.Argument(help="id da cobrança de teste (teste_...)")]) -> None:
    """Simula o pagamento de uma cobrança Pix de teste (sem chave da AbacatePay)."""
    from raiz.banco import engine
    from raiz.pedidos import servico as S

    if not cobranca.startswith("teste_"):
        raise typer.BadParameter("só cobrança de teste")
    typer.echo(f"reserva: {S.confirmar_pagamento(engine(), cobranca, quem='teste')}")


@pedidos_cli.command("resposta")
def pedidos_resposta(
    cod_imovel: Annotated[str, typer.Argument(help="código do CAR")],
    nivel: Annotated[
        str, typer.Option(help="contatado, interessado, aceite_fase1, contrato_firme, recusou, sem_resposta")
    ],
    canal: Annotated[str | None, typer.Option(help="whatsapp, carta, email, visita")] = None,
    motivo: Annotated[str | None, typer.Option(help="por que recusou ou não respondeu")] = None,
    termo: Annotated[str | None, typer.Option(help="versão do termo LGPD aceito")] = None,
    pedido: Annotated[str | None, typer.Option(help="id do pedido")] = None,
) -> None:
    """Registra a resposta do dono (o nível só sobe com registro; nome e CPF ficam só no esquema pessoal)."""
    from raiz.banco import engine
    from raiz.pedidos import servico as S

    typer.echo(S.registrar_resposta(engine(), cod_imovel, nivel, canal, motivo, termo, pedido))


lote_cli = typer.Typer(
    help="Lote do ProFloresta+ por estado: 1 milhão de créditos com reserva, marcos, preço mínimo, checklist do "
    "edital, relatório para o desenvolvedor e folha de cada dono.",
    no_args_is_help=True,
)
app.add_typer(lote_cli, name="lote")


@lote_cli.command("montar")
def lote_montar(
    uf: Annotated[str, typer.Argument(help="UF (área de elegibilidade da Verra), ex.: PA")],
    saida: Annotated[
        str | None, typer.Option(help="pasta saida/ do motor; padrão: a pasta de trabalho do motor")
    ] = None,
    destino: Annotated[str | None, typer.Option(help="pasta do lote; padrão: <saida>/<UF>/lote")] = None,
    creditos: Annotated[float | None, typer.Option(help="volume do contrato; padrão: 1 milhão")] = None,
    cenario: Annotated[str | None, typer.Option(help="cenário das premissas; padrão: central_r11")] = None,
    municipios: Annotated[str | None, typer.Option(help="só estes códigos IBGE, separados por vírgula")] = None,
    folhas: Annotated[bool, typer.Option(help="gravar a folha de cada dono das titulares e reservas")] = True,
) -> None:
    """Monta o lote do estado com o mesmo cálculo da ficha e do pedido, e grava o csv, o resumo, o relatório e as
    folhas dos donos. Diz quantos municípios entraram e, se não fecha, exatamente o que falta."""
    from pathlib import Path

    from raiz import lote as L
    from raiz import lote_relatorio as LR
    from raiz import restauracao as RS
    from raiz.funil.rodar import dir_trabalho

    base = Path(saida) if saida else dir_trabalho() / "saida"
    mun = [int(x) for x in municipios.split(",")] if municipios else None
    dados = L.ler_uf(base, uf, mun)
    r = RS.regra()
    c = RS.cenario(cenario, r)
    lote = L.montar(dados, creditos, c, r)
    res = lote["resumo"]
    out = LR.gravar_lote(lote, Path(destino) if destino else base / uf.upper() / "lote", c, r, folhas)
    m = res["municipios"]
    typer.echo(
        f"{res['uf']}: {m['lidos']} de {m['no_estado']} municípios no cálculo, {m['no_lote']} com fazenda no lote"
    )
    typer.echo(
        f"  {res['titulares']} titulares e {res['reservas']} de reserva, {res['ha_lote']:,.0f} ha, "
        f"{res['creditos_lote']:,.0f} créditos até o ano 25 (precisa {res['creditos_precisa_com_reserva']:,.0f})"
    )
    eco = res.get("economia") or {}
    pm = eco.get("preco_minimo_usd") or {}
    typer.echo(
        f"  TIR com Fundo Clima {eco.get('tir_alavancada_pct')}% a US$ {res['preco_contrato_usd']:.0f}; "
        f"mínimo para 12%: US$ {(pm.get('12') or {}).get('alavancada')}, para 15%: "
        f"US$ {(pm.get('15') or {}).get('alavancada')}"
    )
    if res["fecha_com_reserva"]:
        typer.echo(f"  fecha {res['volume_creditos']:,.0f} créditos com reserva")
    for x in res["o_que_falta"]:
        typer.echo(f"  falta: {x}")
    if (res.get("abaixo_equilibrio") or {}).get("aviso"):
        typer.echo(f"  aviso: {res['abaixo_equilibrio']['aviso']}")
    for k, v in out.items():
        typer.echo(f"  {k}: {v}")


legibilidade_cli = typer.Typer(help="Medidor de legibilidade dos textos ao dono (ALT, Martins, LanguageTool).")
app.add_typer(legibilidade_cli, name="legibilidade")


@legibilidade_cli.command("medir")
def legibilidade_medir(
    arquivo: Annotated[str | None, typer.Argument(help="arquivo de texto; sem nada, lê da entrada")] = None,
    cru: Annotated[bool, typer.Option(help="conta como o ALT, sem passar números e datas para palavras")] = False,
    como_json: Annotated[bool, typer.Option("--json", help="todas as contagens e notas em JSON")] = False,
) -> None:
    """Mede um texto: as três versões do Flesch, os índices do ALT e as contagens."""
    import json
    from pathlib import Path

    from raiz.legibilidade import medir, resumo
    from raiz.revisor import nota_de_envio

    texto = Path(arquivo).read_text(encoding="utf-8") if arquivo else sys.stdin.read()
    m = medir(texto, preparar_texto=False) if cru else nota_de_envio(texto)
    if como_json:
        typer.echo(json.dumps(m, ensure_ascii=False, indent=2))
        return
    typer.echo(resumo(m))
    if m.get("palavras"):
        typer.echo(
            f"  Flesch: ALT {m['flesch_alt']}, Martins {m['flesch_martins']}, LanguageTool {m['flesch_languagetool']} "
            f"(nível {m['nivel_languagetool']} de 6)"
        )
        typer.echo(
            f"  {m['palavras']} palavras, {m['frases']} frase(s), {m['silabas']} sílabas, {m['complexas']} complexas "
            f"({m['complexas_criterio']}); medidor {m['versao']}"
        )
    lt = m.get("languagetool")
    if lt and lt.get("erro"):
        typer.echo(f"  revisor: {lt['erro']}")
    elif lt:
        typer.echo(f"  revisor (LanguageTool {lt['versao']}): {lt['total']} aviso(s) de estilo")
        for a in lt["avisos"]:
            sug = f" → {', '.join(a['sugestoes'])}" if a["sugestoes"] else ""
            typer.echo(f"    «{a['trecho']}»: {a['mensagem']}{sug}")


@legibilidade_cli.command("modelos")
def legibilidade_modelos() -> None:
    """Mede cada modelo de mensagem ao dono (raiz/agentes/textos.py), preenchido com um exemplo."""
    from raiz.agentes.textos import exemplos
    from raiz.legibilidade import medir

    typer.echo(f"{'modelo':14} {'palavras':>8} {'p/frase':>7} {'ALT':>6} {'Martins':>7} {'LT':>6} {'resultado':>9}")
    for nome, texto in exemplos().items():
        m = medir(texto)
        typer.echo(
            f"{nome:14} {m['palavras']:8} {m['palavras_por_frase']:7.1f} {m['flesch_alt']:6.1f} "
            f"{m['flesch_martins']:7.1f} {m['flesch_languagetool']:6.1f} {m['resultado_alt']:9.1f}"
        )
