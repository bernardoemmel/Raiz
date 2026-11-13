"""
Raíz: roda um estado inteiro, etapa por etapa, dentro do prazo do job, e deixa o relatório para a publicação.
É o que o GitHub Actions chama (.github/workflows/processar-estados.yml); também roda no computador.

Uso (da pasta motor/):
  python rodar_estado.py TO                     roda o que falta em Tocantins (saida/TO/), na ordem das etapas
  python rodar_estado.py TO --refazer direto    apaga e refaz tabelas (várias com vírgula; "funil" ou "tudo" refaz tudo)
  python rodar_estado.py TO --etapas direto     só estas etapas (várias com vírgula; também RAIZ_ETAPAS)
  python rodar_estado.py --planejar [UF ...]    diz quais estados precisam rodar, na ordem (lê o estados.json publicado)
  python rodar_estado.py --preparar             baixa uma vez os arquivos nacionais (lista de municípios, embargos,
                                                biomas, geobr, TMF, causas da perda) para o cache comum
  python rodar_estado.py --continuar TO         depois de publicar: se parou pelo prazo, dispara o workflow só para TO

Etapas, nesta ordem (cada script pula o município que já está pronto):
  funil (raiz_estado.py), filtros (raiz_filtros.py), MapBiomas (raiz_mapbiomas.py), direto (raiz_direto.py),
  TMF e causas da perda (raiz_extras_direto.py), APP pela escadinha (raiz_app.py) e, só se houver GeoTIFF em extras/,
  o histórico do Earth Engine (raiz_extras.py).
Prazo: RAIZ_INICIO (início do job, em segundos desde 1970) + RAIZ_LIMITE_MIN (330 = 5h30) - RAIZ_MARGEM_MIN (25, tempo
  guardado para publicar). Perto do prazo a etapa em curso é interrompida; os scripts gravam cada arquivo de uma vez
  (arquivo .tmp e troca), então nada fica pela metade. Sem RAIZ_INICIO nem RAIZ_LIMITE_MIN, roda sem prazo.
Fonte recusando: os scripts esperam e tentam de novo com espera crescente e seguem para o próximo município. Se uma etapa
  acumula RAIZ_ERROS_SEGUIDOS (8) erros seguidos, a fonte está fora do ar para o GitHub: a etapa para, as outras seguem e
  ela tenta de novo no fim (depois de 10 e de 30 min, se der tempo).
Versões: cada tabela guarda o hash do código que a gerou (raiz_situacao.ETAPAS) e o commit. Se o código mudou desde a
  última publicação, a tabela é apagada e refeita. Tabelas publicadas antes da automação (sem versão) são adotadas como
  estão e marcadas como legado.
Relatório: saida/<UF>/rodada.json (o publicar_dados.py lê) e resumo no GitHub Actions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import raiz_situacao as S  # noqa: E402  (só biblioteca padrão: o planejamento roda sem instalar nada)

PLANO = [
    ("imoveis", "raiz_estado.py"),
    ("filtros", "raiz_filtros.py"),
    ("mapbiomas", "raiz_mapbiomas.py"),
    ("direto", "raiz_direto.py"),
    ("extras_direto", "raiz_extras_direto.py"),
    ("app", "raiz_app.py"),
    ("extras", "raiz_extras.py"),
]
APELIDOS = {"funil": "imoveis", "tmf": "extras_direto", "causas": "extras_direto"}
RE_ERRO = re.compile(r"(\d{7})\D{0,3}ERRO[,:]?\s*(?:pulando:\s*)?(.*)")
RE_OK = re.compile(r"(\d{7})\b.*(imóveis|APP 30 m|nenhum imóvel)")
ERROS_SEGUIDOS = int(os.environ.get("RAIZ_ERROS_SEGUIDOS", 8))
MAX_CONTINUACOES = int(os.environ.get("RAIZ_MAX_CONTINUACOES", 40))
ESPERAS_FONTE_MIN = (10, 30)
# jobs de estado ao mesmo tempo, somando todas as rodadas do workflow. O GitHub dá no máximo 20 máquinas ao mesmo
# tempo para o repositório inteiro: 15 para o processamento deixa 5 livres para o CI dos PRs, o site e o planejamento
# das rodadas. Vale para o próximo planejamento; os jobs que já rodam não são interrompidos.
VAGAS = max(0, min(15, int(os.environ.get("RAIZ_VAGAS", 15))))
# fila de manutenção (tarefa nova, código mudado ou reconferência em estado com o funil pronto): no máximo isto, e só
# com as vagas que sobram dos estados novos
VAGAS_MANUTENCAO = int(os.environ.get("RAIZ_VAGAS_MANUTENCAO", 4))
DIAS_TENTADO = 6  # o "próximo da fila" não pega de novo estado tentado há menos que isto (a rodada semanal pega)
WORKFLOW = os.environ.get("RAIZ_WORKFLOW", "processar-estados.yml")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def prazo() -> float:
    if not (os.environ.get("RAIZ_INICIO") or os.environ.get("RAIZ_LIMITE_MIN")):
        return float("inf")
    ini = float(os.environ.get("RAIZ_INICIO") or time.time())
    return ini + 60 * (float(os.environ.get("RAIZ_LIMITE_MIN", 330)) - float(os.environ.get("RAIZ_MARGEM_MIN", 25)))


def lista_unidades(args: list[str], expandir: bool = True) -> list[str]:
    """'MG' vira as fatias MG-1..MG-8 (expandir); 'MG-3' é uma fatia; 'AC' é o estado inteiro."""
    out = []
    for a in args:
        for x in re.split(r"[\s,;]+", a.upper()):
            if not x:
                continue
            try:
                uf, i, _ = S.ler_unidade(x)
            except ValueError:
                S.acao_github("warning", "unidade desconhecida", f"ignorei '{x}'")
                continue
            for u in (S.unidades(uf) if (expandir and i == 0) else [x]):
                if u not in out:
                    out.append(u)
    return out


def lista_refazer(txt: str) -> set[str]:
    out = set()
    for x in re.split(r"[\s,;]+", (txt or "").lower()):
        if not x:
            continue
        x = APELIDOS.get(x, x)
        if x == "tudo" or x in S.ETAPAS or x in S.PRODUTO:
            out.add(x)
        else:
            S.acao_github("warning", "refazer", f"tabela desconhecida '{x}' (use: funil, filtros, mapbiomas, direto, "
                                                 "extras_direto, extras, flag, terra, ficha, desenvolvedor ou tudo)")
    if out & {"tudo", "imoveis"}:  # refazer o funil muda os polígonos: refaz tudo que depende dele
        out = set(S.ETAPAS) | set(S.PRODUTO)
    return out


def gh_output(**kv) -> None:
    f = os.environ.get("GITHUB_OUTPUT")
    if f:
        with open(f, "a", encoding="utf-8") as fh:
            for k, v in kv.items():
                fh.write(f"{k}={v}\n")


# ---------------------------------------------------------------- planejar

def _e_unidade(nome: str) -> bool:
    try:
        S.ler_unidade(nome)
        return True
    except ValueError:
        return False


def ufs_ativas() -> tuple[set[str], int]:
    """Unidades (estado inteiro ou fatia) com job deste workflow rodando ou na fila em outras rodadas, e quantas rodadas
    ainda estão planejando. Plano legado sem matriz reserva conservadoramente 15 vagas.
    Falha de consulta interrompe o planejamento em vez de presumir que as máquinas estão livres."""
    from fila_processamento import TETO, rodadas

    eu = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY", S.REPO)
    ativas, planejando = set(), 0
    for identificador, run in rodadas(repo, WORKFLOW).items():
        if identificador == eu or run["status"] == "completed":
            continue
        jobs = [x for x in run["jobs"] if _e_unidade(x.get("name", ""))]
        ufs = [x["name"] for x in jobs if x["status"] != "completed"]
        planejando += len(ufs) - len(set(ufs) - ativas)  # jobs duplicados também ocupam vagas
        ativas.update(ufs)
        if not jobs:
            planejando += TETO
    return ativas, planejando


def dias_desde_a_rodada(e: dict) -> float | None:
    rod = (e.get("motor") or {}).get("rodada") or {}
    try:
        return (time.time() - dt.datetime.fromisoformat(rod["fim"]).timestamp()) / 86400 if rod.get("fim") else None
    except ValueError:
        return None


def _rodada_da_unidade(e: dict, i: int) -> dict:
    m = e.get("motor") or {}
    if i:
        return ((m.get("fatias") or {}).get(str(i)) or {}).get("rodada") or {}
    return m.get("rodada") or {}


def _dias(rod: dict) -> float | None:
    try:
        return (time.time() - dt.datetime.fromisoformat(rod["fim"]).timestamp()) / 86400 if rod.get("fim") else None
    except ValueError:
        return None


def tentado_ha_pouco(e: dict, i: int = 0) -> bool:
    """Rodou há menos de DIAS_TENTADO dias e terminou dentro do prazo (ou parou sem avançar): o que faltou depende de
    fonte fora do ar ou de erro em município, e fica para a rodada semanal."""
    rod = _rodada_da_unidade(e, i)
    dias = _dias(rod)
    return dias is not None and dias < DIAS_TENTADO and (not rod.get("parou_por_tempo") or (rod.get("progresso") or 0) <= 0)


def versoes_executor() -> dict[str, str] | None:
    """Versão atual de cada tarefa do executor do produto (raiz/executor/tarefas.py), ou None sem o pacote raiz."""
    try:
        if str(AQUI.parent) not in sys.path:
            sys.path.insert(0, str(AQUI.parent))
        from raiz.executor import tarefas as T
        return {n: T.versao(n) for n in T.DEPENDE}
    except Exception as ex:  # planejamento sem as dependências do produto: decide sem esta conferência
        log(f"sem as versões do executor ({type(ex).__name__}: {ex})")
        return None


def motivo(e: dict | None, atual: dict, atual_exec: dict | None, unidade: str | None = None) -> tuple[str | None, bool, str]:
    """Por que a unidade (estado inteiro ou fatia) precisa rodar (None: não precisa), se é porque o código mudou e em
    que fila entra: 'novo' (funil ainda incompleto) ou 'manutencao' (funil pronto: tarefa nova, código mudado,
    adoção ou reconferência das fontes)."""
    uf, i, _ = S.ler_unidade(unidade) if unidade else (None, 0, 1)
    if not e:
        return "ainda não começou", False, "novo"
    total = e.get("total_ibge") or (S.TOTAL_IBGE.get(uf) if uf else 0)
    funil_ok = (e.get("municipios", 0) + (e.get("sem_imoveis") or 0)) >= (total or 0)
    if not e.get("controle") and _rodada_da_unidade(e, i).get("falhou_fontes"):
        return "fontes obrigatórias indisponíveis na última tentativa", False, "novo"
    if not e.get("controle"):
        return ("publicado antes do executor: adotar (com a APP pela escadinha onde faltar) e rodar o que falta", False,
                "manutencao" if funil_ok else "novo")
    mudou = []
    if atual_exec and e.get("versoes"):
        mudou = [t for t, v in atual_exec.items() if (e["versoes"] or {}).get(t) not in (None, v)]
    elif not e.get("versoes"):
        etapas = (e.get("motor") or {}).get("etapas") or {}
        mudou = [t for t, v in atual.items() if t != "extras" and (etapas.get(t) or {}).get("versao") not in (None, v)]
    if mudou:
        return "código mudou: " + ", ".join(S.NOME_TABELA.get(t, t) for t in mudou), True, "manutencao"
    if _rodada_da_unidade(e, i).get("falhou_fontes"):
        return "fontes obrigatórias indisponíveis na última tentativa", False, "manutencao" if funil_ok else "novo"
    fat = ((e.get("motor") or {}).get("fatias") or {}).get(str(i)) if i else None
    if i and fat is None and not e.get("completo"):  # fatia que nunca rodou sozinha
        return "fatia ainda não rodou", False, "manutencao" if funil_ok else "novo"
    completo, falta = (fat.get("completo"), fat.get("faltam") or {}) if fat else (e.get("completo"), e.get("faltam") or {})
    if not completo:
        texto = "falta " + (", ".join(f"{S.NOME_TABELA.get(t, t)} {n}" for t, n in falta.items()) or "conferir")
        return texto, False, "novo" if falta.get("imoveis") else "manutencao"
    dias = _dias(_rodada_da_unidade(e, i)) if fat else dias_desde_a_rodada(e)
    if dias is None or dias >= DIAS_TENTADO:
        texto = f"reconferir o que mudou nas fontes (última rodada há {dias:.0f} dias)" if dias else "reconferir"
        return texto, False, "manutencao"
    return None, False, "manutencao"


def planejar(pedidos: list[str], refazer: set[str], modo: str = "automatico", liberou: str | None = None,
             continuacao: int = 0) -> list[str]:
    """Unidades que precisam rodar (estado inteiro, ou fatia de estado grande), na ordem de S.ORDEM, em duas filas.
    Pedido explícito (campo ufs, ou continuação): roda essas. Senão, a fila 'novo' (estado que não começou ou com funil
    incompleto) pega primeiro as vagas livres (VAGAS menos as unidades já rodando em outras rodadas); a fila
    'manutencao' (funil pronto: tarefa nova, código mudado, adoção, reconferência) pega só o que sobra, até
    VAGAS_MANUTENCAO ao mesmo tempo, e nunca segura vaga de estado novo. No modo 'proximo' (um job terminou e passa a
    vez), repõe todas as vagas livres e ficam de fora as tentadas há pouco. O cron repõe só a fila nova.
    `liberou` é apenas informativo:
    a vaga só fica livre quando a API confirma o job concluído, inclusive seus passos finais.
    No Actions a fila/reserva persistente serializa a admissão entre rodadas, sem cancelar jobs."""
    pub = S.ler_manifesto().get("estados", {})
    prioridade_solicitada = os.environ.get("RAIZ_PRIORIDADE_FUNIL") == "1"
    funis_prontos = {uf for uf, total in S.TOTAL_IBGE.items()
                    if (pub.get(uf, {}).get("municipios", 0) + (pub.get(uf, {}).get("sem_imoveis") or 0)) >= total}
    prioridade = prioridade_solicitada and len(funis_prontos) < len(S.TOTAL_IBGE)
    falhas_funil = {uf: (e.get("motor") or {}).get("commit") for uf, e in pub.items()
                   if e.get("erros") or any(f.get("erros") for f in ((e.get("motor") or {}).get("fatias") or {}).values())}
    if prioridade:
        from fila_processamento import ORDEM_FUNIL
        ordem = [uf for uf in ORDEM_FUNIL if uf in S.ORDEM]
        pedidos = [u for u in pedidos if S.ler_unidade(u)[0] not in funis_prontos]
        if refazer:
            raise ValueError("manutenção suspensa até concluir os 27 funis; pedido de refazer preservado sem execução")
    else:
        ordem = S.ORDEM
    atual = S.versoes()
    atual_exec = versoes_executor()
    if refazer and not pedidos:
        pedidos = [u for uf in S.ORDEM if uf in pub for u in S.unidades(uf)]
        S.acao_github("notice", "refazer", f"sem lista de estados: refaço {', '.join(sorted(refazer))} em todos os publicados")
    no_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    ativas, planejando = (set(), 0) if no_actions else ufs_ativas()
    def ocupada(u: str) -> bool:
        from fila_processamento import ocupada as unidade_ocupada
        return unidade_ocupada(u, ativas)

    manut_ativas = sum(1 for u in ativas if motivo(pub.get(S.ler_unidade(u)[0]), atual, atual_exec, u)[2] != "novo")
    vagas = max(0, min(VAGAS, 15) - len(ativas) - planejando)
    vagas_manut = vagas if pedidos else max(0, VAGAS_MANUTENCAO - manut_ativas)
    filas = {"novo": [], "manutencao": []}
    linhas, prontas = [], 0
    for uf in ordem:
        e = pub.get(uf)
        for u in S.unidades(uf):
            if prioridade and uf in funis_prontos:
                prontas += 1
                continue
            if pedidos:
                if u not in pedidos:
                    continue
                razao, mudou, classe = "pedido" + (f" (refazer {', '.join(sorted(refazer))})" if refazer else ""), False, "novo"
            else:
                razao, mudou, classe = motivo(e, atual, atual_exec, u)
                if prioridade:
                    razao, mudou, classe = "completar o funil; manutenção suspensa", False, "novo"
                if not prioridade and razao and modo == "proximo" and not mudou and e and tentado_ha_pouco(e, S.ler_unidade(u)[1]):
                    linhas.append((u, e, f"{razao} (tentada há pouco; fica para a rodada semanal)", None))
                    continue
            if razao and ocupada(u):
                linhas.append((u, e, f"{razao} (já rodando)", None))
                continue
            if not razao:
                prontas += 1
                continue
            filas[classe].append(u)
            linhas.append((u, e, razao, classe))
    escolhidas = filas["novo"][:vagas]
    if modo != "fila" and not prioridade:
        escolhidas += filas["manutencao"][:max(0, min(vagas - len(escolhidas), vagas_manut))]
    matriz = escolhidas
    if no_actions:
        from fila_processamento import reservar

        manutencao = {u for uf in S.ORDEM for u in S.unidades(uf)
                     if motivo(pub.get(uf), atual, atual_exec, u)[2] == "manutencao"}
        if prioridade:
            manutencao = set()
        candidatos = filas["novo"] if modo == "fila" else filas["novo"] + filas["manutencao"]
        opcoes = {"funis_prontos": funis_prontos, "falhas_funil": falhas_funil} if prioridade_solicitada else {}
        matriz = reservar(candidatos, pedidos, refazer, _e_unidade, VAGAS, continuacao,
                          None, manutencao, 0 if prioridade else VAGAS_MANUTENCAO, **opcoes)
        escolhidas = [p["unidade"] for p in matriz]
    tabela = []
    for u, e, razao, classe in linhas:
        feitos = "—" if not e else f"{e.get('municipios', 0) + (e.get('sem_imoveis') or 0)}/{e.get('total_ibge') or S.TOTAL_IBGE[S.ler_unidade(u)[0]]}"
        acao = "**agora**" if u in escolhidas else ("na fila" if classe else "")
        tabela.append(f"| {u} | {feitos} | {classe or ''} | {razao} | {acao} |")
    ocupacao = ("Admissão conferida na fila persistente, incluindo reservas e jobs legados" if no_actions else
                f"Rodando em outras rodadas: {', '.join(sorted(ativas)) or 'nenhuma'}"
                f"{f' (mais {planejando} vagas reservadas por planejamentos)' if planejando else ''}")
    texto = (f"### Plano desta rodada ({'pedido' if pedidos else modo})\n\n"
             f"{ocupacao}. Vagas: {VAGAS} "
             f"(manutenção até {VAGAS_MANUTENCAO}). Começam agora: {len(escolhidas)}. Prontas: {prontas}.\n\n"
             "| Unidade | Municípios do estado | Fila | O que fazer | |\n|---|---|---|---|---|\n" + "\n".join(tabela))
    texto += f"\n\nVersão das tarefas: {', '.join(f'{v}' for v in (atual_exec or atual).values())}"
    print(texto)
    S.resumo_github(texto)
    gh_output(matriz=json.dumps(matriz), tem="1" if escolhidas else "0",
              dia=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d"))
    return escolhidas


# ---------------------------------------------------------------- preparar (cache comum)

def preparar() -> None:
    """Arquivos nacionais, baixados uma vez por dia no job 'preparar' e guardados no cache comum."""
    os.chdir(AQUI)
    import raiz_estado as R
    import raiz_filtros as F
    import raiz_extras_direto as X
    passos = [("lista de municípios", R.garantir_municipios), ("embargos do Ibama", R.embargos),
              ("biomas", R.biomas), ("causas da perda (Zenodo)", X.drivers), ("TMF (blocos)", X.tmf_tiles)]
    passos += [(f"geobr {k}", (lambda k=k: F.baixar(k))) for k in F.ARQ]
    for nome, f in passos:
        t0 = time.time()
        try:
            f()
            log(f"{nome}: ok ({time.time() - t0:.0f} s)")
        except Exception as ex:  # o job do estado tenta de novo sozinho
            S.acao_github("warning", f"preparar: {nome}", str(ex))


# ---------------------------------------------------------------- rodar um estado

def publicada(uf: str) -> dict:
    f = os.environ.get("RAIZ_ESTADOS_JSON")
    if f and Path(f).exists():
        return json.loads(Path(f).read_text(encoding="utf-8")).get("estados", {}).get(uf, {})
    return S.ler_manifesto().get("estados", {}).get(uf, {})


def tem_geotiff_extras(uf: str) -> bool:
    return any((AQUI / "extras").glob(f"raiz_extras*_{uf}*.tif"))


def conciliar_versoes(pasta: Path, uf: str, motor_ant: dict, refazer: set[str]) -> tuple[dict, list[str]]:
    """Compara a versão de cada tabela publicada com o código de agora; apaga o que precisa ser refeito."""
    atual = S.versoes()
    ant = motor_ant.get("etapas") or {}
    legado = set(motor_ant.get("legado") or [])
    primeira = not motor_ant
    commit, agora = S.commit_atual(), S.agora()
    tif = tem_geotiff_extras(uf)
    out = {}
    for t, v in atual.items():
        a = ant.get(t)
        nova = {"versao": v, "commit": commit, "desde": agora}
        mudou = a is not None and a.get("versao") != v
        if (t in refazer or mudou) and t == "extras" and not tif:
            if mudou:
                log(f"extras: código mudou, mas não apago (sem GeoTIFF do Earth Engine em extras/ para refazer)")
            out[t] = a or nova
            continue
        if t in refazer or mudou:
            arqs = S.arquivos_tabela(pasta, t)
            for f in arqs:
                f.unlink()
            porque = f"código mudou ({a.get('versao')} -> {v})" if mudou else "pedido para refazer"
            log(f"{S.NOME_TABELA.get(t, t)}: {porque}; apaguei {len(arqs)} arquivo(s) e refaço")
            out[t] = nova
            legado.discard(t)
        elif a is None:
            out[t] = nova
            if primeira and S.arquivos_tabela(pasta, t):
                legado.add(t)  # veio da rodada manual, antes da automação: adotado como está
        else:
            out[t] = a
    return out, sorted(legado)


def contagem(pasta: Path, uf: str) -> int:
    s = S.situacao(pasta, uf)
    return sum(s["tabelas"].values()) + s["sem_imoveis"]


def rodar_etapa(nome: str, script: str, uf: str, pasta: Path, fim: float) -> dict:
    falta = len(S.pendentes(pasta, uf)[nome])
    res = {"faltavam": falta, "faltam": falta, "segundos": 0, "codigo": None, "parada": None, "erros": []}
    if nome == "extras" and not tem_geotiff_extras(uf):
        res["parada"] = "sem GeoTIFF do Earth Engine em extras/"
        return res
    if falta == 0:
        res["parada"] = "nada a fazer"
        return res
    restante = fim - time.time()
    if restante < 120:
        res["parada"] = "prazo"
        return res
    log(f"{uf} {S.NOME_TABELA.get(nome, nome)}: {falta} município(s) para fazer ({script})")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    env.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")
    if fim != float("inf"):
        env["RAIZ_PRAZO"] = str(int(fim))
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, script, uf], cwd=AQUI, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1, errors="replace", start_new_session=True)
    trava = threading.Lock()

    def matar(motivo: str) -> None:
        with trava:
            if res["parada"] is None:
                res["parada"] = motivo
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return

        def forca():
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        t = threading.Timer(30, forca)
        t.daemon = True
        t.start()

    relogio = None
    if restante != float("inf"):
        relogio = threading.Timer(restante, matar, args=("prazo",))
        relogio.daemon = True
        relogio.start()
    seguidos, ultimas = 0, deque(maxlen=15)
    for linha in proc.stdout:
        print(linha, end="", flush=True)
        if linha.strip():
            ultimas.append(linha.strip())
        m = RE_ERRO.search(linha)
        if m:
            res["erros"].append({"etapa": nome, "municipio": m.group(1), "mensagem": S.mascarar(m.group(2))})
            seguidos += 1
            if seguidos >= ERROS_SEGUIDOS and res["parada"] is None:
                S.acao_github("warning", f"{uf} {S.NOME_TABELA.get(nome, nome)}",
                              f"{seguidos} erros seguidos: a fonte parece recusar o GitHub. Paro esta etapa, sigo com as "
                              f"outras e tento de novo no fim.")
                matar("fonte")
        elif RE_OK.search(linha):
            seguidos = 0
    proc.wait()
    if relogio:
        relogio.cancel()
    res["codigo"] = proc.returncode
    res["segundos"] = round(time.time() - t0)
    res["faltam"] = len(S.pendentes(pasta, uf)[nome])
    if proc.returncode not in (0, None) and res["parada"] is None and time.time() > fim - 300:
        res["parada"] = "prazo"  # o script desistiu sozinho perto do prazo (ex.: exportação ainda na fila do MapBiomas)
    elif proc.returncode not in (0, None) and res["parada"] is None:
        res["parada"] = "falhou"
        msg = next((x for x in reversed(ultimas) if not x.startswith("[")), ultimas[-1] if ultimas else "")
        res["erros"].append({"etapa": nome, "municipio": None, "mensagem": S.mascarar(msg)})
    log(f"{uf} {S.NOME_TABELA.get(nome, nome)}: faltavam {falta}, faltam {res['faltam']} "
        f"({res['segundos']} s{', parou: ' + res['parada'] if res['parada'] else ''})")
    return res


def resumo_rodada(uf: str, rel: dict) -> None:
    linhas = [f"### {uf} {S.NOME_UF[uf]}" + (f" (continuação {rel['continuacao']})" if rel.get("continuacao") else ""),
              "", "| Etapa | Faltavam | Faltam | Tempo | Erros | Observação |", "|---|---|---|---|---|---|"]
    for nome, _ in PLANO:
        r = rel["etapas_rodadas"].get(nome)
        if not r:
            continue
        linhas.append(f"| {S.NOME_TABELA.get(nome, nome)} | {r['faltavam']} | {r['faltam']} | {r['segundos'] // 60} min "
                      f"| {len(r['erros'])} | {r['parada'] or ''} |")
    linhas.append("")
    linhas.append(f"Parou pelo prazo: {'sim' if rel['parou_por_tempo'] else 'não'}. Arquivos novos: {rel['progresso']}. "
                  f"Completo: {'sim' if rel['completo'] else 'não'}.")
    if rel["erros"]:
        linhas += ["", f"<details><summary>Erros ({len(rel['erros'])})</summary>", ""]
        linhas += [f"- {e['etapa']} {e['municipio'] or ''}: {e['mensagem']}" for e in rel["erros"][:200]]
        linhas += ["", "</details>"]
    S.resumo_github("\n".join(linhas))


def rodar(uf: str, refazer: set[str], continuacao: int, so: set[str] | None = None) -> dict:
    os.chdir(AQUI)
    pasta = AQUI / "saida" / uf
    pasta.mkdir(parents=True, exist_ok=True)
    for f in pasta.glob("*.tmp"):  # sobra de rodada interrompida
        f.unlink()
    fim = prazo()
    if continuacao and refazer:
        log("continuação: ignoro o pedido de refazer (já foi feito na primeira rodada)")
        refazer = set()
    entrada = publicada(uf)
    motor_ant = entrada.get("motor") or {}
    etapas, legado = conciliar_versoes(pasta, uf, motor_ant, refazer)
    rel = {"uf": uf, "inicio": S.agora(), "fim": None, "continuacao": continuacao, "url": S.url_rodada(),
           "commit": S.commit_atual(), "versao_motor": S.hash_codigo(S.CODIGO_MOTOR), "etapas": etapas,
           "legado": legado, "parou_por_tempo": False, "progresso": 0, "completo": False,
           "etapas_rodadas": {}, "erros": []}
    arq = pasta / "rodada.json"

    def grava():
        arq.with_suffix(".json.tmp").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(arq.with_suffix(".json.tmp"), arq)

    grava()
    antes = contagem(pasta, uf)
    if fim != float("inf"):
        log(f"{uf}: prazo das etapas às {dt.datetime.fromtimestamp(fim, dt.timezone.utc):%H:%M} UTC")
    de_novo = []
    for nome, script in PLANO:
        if so and nome not in so:
            continue
        r = rodar_etapa(nome, script, uf, pasta, fim)
        rel["etapas_rodadas"][nome] = r
        if r["parada"] == "prazo":
            rel["parou_por_tempo"] = True
        if r["parada"] == "fonte" or (r["parada"] == "falhou" and r["faltam"] == r["faltavam"]):
            de_novo.append((nome, script))
        grava()
        if rel["parou_por_tempo"]:
            break
    for espera in ESPERAS_FONTE_MIN:  # fonte recusando: espera e tenta de novo no fim, se der tempo
        if not de_novo or rel["parou_por_tempo"] or time.time() + (espera + 15) * 60 > fim:
            break
        log(f"{uf}: {', '.join(n for n, _ in de_novo)} com a fonte fora do ar; espero {espera} min e tento de novo")
        time.sleep(espera * 60)
        pendentes, de_novo = de_novo, []
        for nome, script in pendentes:
            r = rodar_etapa(nome, script, uf, pasta, fim)
            ant = rel["etapas_rodadas"][nome]
            r["faltavam"], r["segundos"], r["erros"] = ant["faltavam"], ant["segundos"] + r["segundos"], ant["erros"] + r["erros"]
            rel["etapas_rodadas"][nome] = r
            if r["parada"] == "prazo":
                rel["parou_por_tempo"] = True
            elif r["parada"] in ("fonte", "falhou"):
                de_novo.append((nome, script))
            grava()
    rel["erros"] = [e for r in rel["etapas_rodadas"].values() for e in r["erros"]]
    for nome, r in rel["etapas_rodadas"].items():
        if r["erros"]:
            e = r["erros"][0]
            S.acao_github("warning", f"{uf} {S.NOME_TABELA.get(nome, nome)}",
                          f"{len(r['erros'])} erro(s); primeiro: {e['municipio'] or ''} {e['mensagem']}")
    rel["progresso"] = contagem(pasta, uf) - antes
    rel["completo"] = S.situacao(pasta, uf)["completo"]
    rel["fim"] = S.agora()
    grava()
    resumo_rodada(uf, rel)
    log(f"{uf}: fim. Arquivos novos: {rel['progresso']}; completo: {rel['completo']}; parou pelo prazo: {rel['parou_por_tempo']}")
    return rel


# ---------------------------------------------------------------- rodar pelo executor do produto (raiz/executor)

def _executor():
    """O executor do produto (raiz/executor/tarefas.py), lendo e gravando no armazém configurado (o Release `dados`)."""
    if str(AQUI.parent) not in sys.path:
        sys.path.insert(0, str(AQUI.parent))
    from raiz.executor import tarefas as T
    return T, T.executor_producao()


def _pasta_espelho(a, uf: str) -> Path | None:
    """Pasta local onde o armazém guarda os arquivos do estado (Release: o espelho; pasta local: ela mesma)."""
    local = getattr(a, "local", a)
    return Path(local.raiz) / "saida" / uf if hasattr(local, "raiz") else None


def _vazios(a, uf: str) -> set[str]:
    from raiz.executor.armazem import ler_json
    out = set()
    for k in a.listar(f"marcas/{uf}/"):
        m = ler_json(a, k) or {}
        if ((m.get("tarefas") or {}).get("funil") or {}).get("vazio"):
            out.add(k.rsplit("/", 1)[1][:-5])
    return out


def _fontes_do_estado(uf: str, fim: float) -> None:
    """Alertas, MapBiomas (os 5 temas), geobr, TMF e causas da perda antes de adotar e de rodar: a assinatura de cada
    município no executor já nasce com eles (se viessem depois, o executor refaria tudo achando que a fonte mudou)."""
    from raiz.funil.rodar import preparar_motor
    if fim != float("inf"):
        os.environ["RAIZ_PRAZO"] = str(int(fim))
    R = preparar_motor(carregar_embargos=False)
    R.garantir_alertas(uf)
    import raiz_extras_direto as X
    import raiz_filtros as F
    import raiz_mapbiomas
    raiz_mapbiomas.exporta_uf(uf)
    for k in F.ARQ:
        F.baixar(k)
    X.tmf_tiles()
    X.drivers()
    os.chdir(AQUI)


def _copiar_do_armazem(a, uf: str, cods, padroes, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for c in cods:
        for p in padroes:
            arq = p.format(cod=c)
            if not (destino / arq).exists():
                a.baixar(f"saida/{uf}/{arq}", destino / arq)


def _app_legado(a, uf: str, cods: list[str], fim: float) -> dict:
    """APP pela escadinha (raiz_app.py) nos municípios publicados antes dela, ANTES de adotar: o imoveis_ com a APP vai
    para o armazém e a marca adotada já nasce com ele (adotar antes e mexer depois faria o executor refazer tudo)."""
    trab = AQUI / "saida" / uf
    _copiar_do_armazem(a, uf, cods, ("imoveis_{cod}.csv", "geo_{cod}.parquet"), trab)
    r = rodar_etapa("app", "raiz_app.py", uf, trab, fim)
    feitos = S.com_app(trab, set(cods))
    for c in sorted(feitos):
        a.por(f"saida/{uf}/imoveis_{c}.csv", trab / f"imoveis_{c}.csv",
              {"tarefa": "funil", "versao": "publicado", "app": "escadinha", "data": S.agora(), "uf": uf,
               "cod_municipio": c})
    r["faltam"] = len(set(cods) - feitos)
    return r


def _refazer_no_executor(a, uf: str, refazer: set[str], tarefas: tuple[str, ...], so: set[str] | None = None) -> int:
    """Apaga das marcas as tarefas pedidas (só da fatia, com so): o executor as refaz (e o que depende delas, se a
    saída mudar)."""
    from raiz.executor.armazem import ler_json, por_json
    alvo = {("funil" if t == "imoveis" else t) for t in refazer} & set(tarefas)
    if "funil" in alvo:
        alvo = set(tarefas)
    n = 0
    for k in a.listar(f"marcas/{uf}/") if alvo else []:
        if so is not None and k.rsplit("/", 1)[1][:-5] not in so:
            continue
        m = ler_json(a, k) or {}
        if any(m.get("tarefas", {}).pop(t, None) is not None for t in list(alvo)):
            por_json(a, k, m)
            n += 1
    if "extras" in refazer and tem_geotiff_extras(uf):
        for k in a.listar(f"saida/{uf}/"):
            m = re.search(r"/extras_(\d{7})\.csv$", k)
            if m and (so is None or m.group(1) in so):
                a.apagar(k)
    return n


def _extras_no_armazem(a, uf: str, esp: Path, fim: float, so: set[str] | None = None) -> dict | None:
    """Histórico do Earth Engine (raiz_extras.py), só com os GeoTIFFs em extras/; o resultado vai para o armazém."""
    if not tem_geotiff_extras(uf) or esp is None:
        return None
    feitos = S.cods(esp, "imoveis") & (so if so is not None else S.cods(esp, "imoveis"))
    falta = sorted(feitos - S.cods(esp, "extras"))
    if not falta:
        return {"faltavam": 0, "faltam": 0, "segundos": 0, "parada": "nada a fazer", "erros": []}
    trab = AQUI / "saida" / uf
    _copiar_do_armazem(a, uf, falta, ("imoveis_{cod}.csv", "geo_{cod}.parquet"), trab)
    _copiar_do_armazem(a, uf, sorted(feitos - set(falta)), ("extras_{cod}.csv",), trab)  # já feitos: o script pula
    r = rodar_etapa("extras", "raiz_extras.py", uf, trab, fim)
    versao = S.hash_codigo(S.ETAPAS["extras"])
    for c in falta:
        f = trab / f"extras_{c}.csv"
        if f.exists():
            a.por(f"saida/{uf}/extras_{c}.csv", f,
                  {"tarefa": "extras", "versao": versao, "data": S.agora(), "uf": uf, "cod_municipio": c})
    return r


def _rodar_processo(cmd: list[str], limite: float, env: dict) -> tuple[int | None, bool, list[str]]:
    """Roda um comando mostrando a saída; mata o grupo de processos no limite. Devolve (código, morto, últimas linhas)."""
    proc = subprocess.Popen(cmd, cwd=AQUI, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1, errors="replace", start_new_session=True)
    morto = {"v": False}

    def matar():
        morto["v"] = True
        for sinal, espera in ((signal.SIGTERM, 30), (signal.SIGKILL, 0)):
            try:
                os.killpg(proc.pid, sinal)
            except ProcessLookupError:
                return
            t0 = time.time()
            while proc.poll() is None and time.time() - t0 < espera:
                time.sleep(1)

    relogio = None
    if limite != float("inf"):
        relogio = threading.Timer(max(limite - time.time(), 1), matar)
        relogio.daemon = True
        relogio.start()
    ultimas = deque(maxlen=20)
    for linha in proc.stdout:
        print(linha, end="", flush=True)
        if linha.strip():
            ultimas.append(linha.strip())
    proc.wait()
    if relogio:
        relogio.cancel()
    return proc.returncode, morto["v"], list(ultimas)


def rodar_executor(unidade: str, refazer: set[str], continuacao: int) -> dict:
    """Uma unidade (estado inteiro ou fatia de estado grande) pelo executor do produto: fontes do estado, APP e adoção
    do que foi publicado antes do executor, `raiz executor rodar` dentro do prazo, extras do Earth Engine (se houver
    GeoTIFF) e publicação com a rodada. Fatia: só os municípios dela; publica relendo o que as outras fatias do mesmo
    estado já publicaram (trava do estado no armazém) e refaz o resumo do estado inteiro."""
    from raiz.executor.armazem import ler_json
    from raiz.versoes import motor_versao
    uf, i_fatia, k_fatias = S.ler_unidade(unidade)
    fatia = set(S.municipios_da_fatia(uf, i_fatia)) if i_fatia else None
    if fatia is not None:
        os.environ.setdefault("RAIZ_PUBLICAR_MIN", "60")  # cada publicação de fatia sobe o estado inteiro
    os.chdir(AQUI)
    fim = prazo()
    pasta = AQUI / "saida" / uf
    pasta.mkdir(parents=True, exist_ok=True)
    T, ex = _executor()
    a = ex.a
    if continuacao and refazer:
        log("continuação: ignoro o pedido de refazer (já foi feito na primeira rodada)")
        refazer = set()
    rel = {"uf": uf, "unidade": unidade, "fatia": i_fatia, "fatias": k_fatias, "modo": "executor",
           "inicio": S.agora(), "fim": None, "continuacao": continuacao,
           "url": S.url_rodada(), "commit": S.commit_atual(), "versao_motor": motor_versao(), "etapas": {},
           "legado": [], "parou_por_tempo": False, "progresso": 0, "completo": False, "etapas_rodadas": {},
           "erros": []}
    arq = pasta / "rodada.json"

    def grava():
        arq.with_suffix(".json.tmp").write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(arq.with_suffix(".json.tmp"), arq)

    def erro(etapa: str, ex_: Exception) -> None:
        rel["erros"].append({"etapa": etapa, "municipio": None, "mensagem": S.mascarar(f"{type(ex_).__name__}: {ex_}")})
        S.acao_github("warning", f"{unidade} {etapa}", f"{type(ex_).__name__}: {ex_}")

    grava()
    if fim != float("inf"):
        log(f"{unidade}: prazo das etapas às {dt.datetime.fromtimestamp(fim, dt.timezone.utc):%H:%M} UTC ({a.descricao})"
            + (f"; fatia {i_fatia} de {k_fatias}, {len(fatia)} municípios" if fatia else ""))
    if hasattr(a, "garantir_uf"):
        a.garantir_uf(uf)  # baixa do Release o que já está publicado (saídas, marcas e andamento)
    esp = _pasta_espelho(a, uf)
    seguir = True
    # 1. fontes do estado
    t0 = time.time()
    try:
        _fontes_do_estado(uf, fim)
        rel["etapas_rodadas"]["fontes"] = {"segundos": round(time.time() - t0), "parada": None}
    except Exception as ex_:
        erro("fontes", ex_)
        rel["parou_por_tempo"] = time.time() > fim - 300
        seguir = False
    finally:
        os.chdir(AQUI)
    # 2. publicado antes do executor (sem marca): APP onde falta e adoção
    if seguir and esp is not None:
        marcados = {k.rsplit("/", 1)[1][:-5] for k in a.listar(f"marcas/{uf}/")}
        sem_marca = S.cods(esp, "imoveis") - marcados
        if fatia is not None:
            sem_marca &= fatia
        if sem_marca:
            falta_app = sorted(sem_marca - S.com_app(esp, sem_marca))
            if falta_app:
                r = _app_legado(a, uf, falta_app, fim)
                rel["etapas_rodadas"]["app"] = r
                rel["progresso"] += r["faltavam"] - r["faltam"]
                if r["faltam"]:
                    rel["parou_por_tempo"] = r["parada"] == "prazo"
                    seguir = False  # adota quando a APP estiver em todos (próxima rodada)
            if seguir:
                r = ex.adotar(uf, sorted(int(c) for c in sem_marca))
                rel["legado"] = sorted(r["tarefas"])
                rel["etapas_rodadas"]["adotar"] = {"municipios": r["adotados"], "tarefas": r["tarefas"]}
                log(f"{uf}: adotei {r['adotados']} municípios publicados antes do executor ({r['tarefas']})")
    if seguir and refazer:
        n = _refazer_no_executor(a, uf, refazer, tuple(T.DEPENDE), fatia)
        log(f"{uf}: refazer {', '.join(sorted(refazer))}: marca apagada em {n} municípios")
    # 3. o executor
    if seguir:
        graca = float(os.environ.get("RAIZ_GRACA_MIN", 10))
        ate = (fim - time.time()) / 60 - graca - 8  # 8 min para o executor publicar no fim
        if ate < 5:
            rel["parou_por_tempo"] = True
        else:
            raiz_bin = shutil.which("raiz")
            cmd = ([raiz_bin] if raiz_bin else [sys.executable, "-c", "from raiz.cli import app; app()"]) + [
                "executor", "rodar", "--ufs", uf, "--lanes", os.environ.get("LANES", "3")]
            if ate != float("inf"):
                cmd += ["--ate-minutos", f"{ate:.0f}"]
            env = dict(os.environ, PYTHONUNBUFFERED="1", RAIZ_SEM_BANCO="1")
            if fatia is not None:
                cmd += ["--municipios", ",".join(sorted(fatia))]
                env["RAIZ_SEM_RESUMO"] = "1"  # o resumo do estado inteiro é feito no fim, com todas as fatias
            if fim != float("inf"):
                env["RAIZ_PRAZO"] = str(int(fim))
            log(f"{unidade}: {' '.join(x if len(x) < 80 else x[:60] + '…' for x in cmd[-10:])}")
            t0 = time.time()
            codigo, morto, ultimas = _rodar_processo(cmd, fim + 600, env)
            est = ler_json(a, f"estado/{uf}.json") or {}
            rodou_agora = (est.get("inicio") or "") >= rel["inicio"]
            rel["etapas_rodadas"]["executor"] = {"segundos": round(time.time() - t0), "codigo": codigo,
                                                 "situacao": est.get("situacao") if rodou_agora else None,
                                                 "feitos": est.get("feitos"), "total": est.get("total"),
                                                 "rodados": est.get("rodados") if rodou_agora else 0, "morto": morto}
            if rodou_agora:
                rel["progresso"] += int(est.get("rodados") or 0)
                rel["parou_por_tempo"] = est.get("situacao") in ("parado_no_prazo", "em_andamento") or morto
                rel["erros"] += [{"etapa": e.get("tarefa"), "municipio": str(e.get("cod")) if e.get("cod") else None,
                                  "mensagem": S.mascarar(e.get("erro", ""))} for e in est.get("erros", [])]
            else:
                rel["parou_por_tempo"] = morto
            if codigo not in (0, None) and not morto:
                msg = next((x for x in reversed(ultimas) if "Error" in x or "erro" in x.lower()), ultimas[-1] if ultimas else "")
                rel["erros"].append({"etapa": "executor", "municipio": None, "mensagem": S.mascarar(msg)})
                S.acao_github("warning", f"{uf} executor", f"saiu com código {codigo}: {msg}")
    # 4. extras do Earth Engine
    if seguir and not rel["parou_por_tempo"]:
        r = _extras_no_armazem(a, uf, esp, fim, fatia)
        if r:
            rel["etapas_rodadas"]["extras"] = r
            rel["parou_por_tempo"] = r.get("parada") == "prazo"
    # 5. situação, resumo do estado (fatia), publicação (com a rodada) e painel
    if fatia is not None and esp is not None and getattr(a, "token", None):
        try:
            a.garantir_uf(uf, forcar=True)  # o que as outras fatias já publicaram
            cods_uf = sorted(int(c) for c in S.cods(esp, "imoveis"))
            f = T.resumo_uf(uf, esp, cods_uf)
            os.chdir(AQUI)
            if f is not None:
                a.por(f"saida/{uf}/resumo_{uf}.csv", Path(f),
                      {"tarefa": "resumo", "data": S.agora(), "uf": uf, "motor_versao": rel["versao_motor"]})
        except Exception as ex_:
            erro("resumo", ex_)
    vazios = _vazios(a, uf)
    if esp is not None:
        sit = S.situacao(esp, uf, vazios=vazios, produto=True, so=fatia)
        rel["completo"] = sit["completo"]
        rel["faltam"] = sit["faltam"]
    est = ler_json(a, f"estado/{uf}.json") or {}
    rel["etapas"] = {t: {"versao": v} for t, v in (est.get("versoes") or ex.versoes()).items()}
    falhou_fontes = any(e.get("etapa") == "fontes" for e in rel["erros"])
    if falhou_fontes:
        rel["completo"] = False  # arquivos antigos não provam que as fontes obrigatórias desta rodada foram lidas
    rel["fim"] = S.agora()
    grava()
    rodada = {k: rel[k] for k in ("url", "inicio", "fim", "continuacao", "parou_por_tempo", "progresso")}
    rodada["falhou_fontes"] = falhou_fontes
    motor = {"commit": rel["commit"], "versao": rel["versao_motor"], "etapas": rel["etapas"], "rodada": rodada}
    if fatia is not None:  # cada fatia anota a sua; o armazém junta as fatias no estados.json
        motor["fatias"] = {str(i_fatia): {"rodada": rodada, "completo": rel["completo"], "faltam": rel.get("faltam"),
                                          "erros": len(rel["erros"]), "municipios": len(fatia)}}
    else:
        motor["legado"] = rel["legado"]
    extra = {uf: {"motor": motor, "erros": rel["erros"][:50]}}
    if getattr(a, "token", None) and hasattr(a, "publicar") and esp is not None and S.cods(esp, "imoveis"):
        try:
            a.publicar(uf, extra=extra)
            log(f"{unidade}: publicado no {a.descricao}")
            import painel
            painel.atualizar_no_github(a.manifesto(fresco=True))
        except Exception as ex_:
            erro("publicar", ex_)
            rel["publicado"] = False
            grava()
            raise
    else:
        if getattr(a, "token", None) and hasattr(a, "_gravar_indice"):
            # Falha antes do primeiro CSV também é uma tentativa: persiste o diagnóstico no índice PRIVADO,
            # sem produzir pacotes vazios nem divulgar detalhes de execução no manifesto aberto.
            from raiz.executor.rodadas import registrar_tentativa
            registrar_tentativa(a, uf, extra[uf])
            import painel
            painel.atualizar_no_github(a.manifesto(fresco=True))
            log(f"{unidade}: tentativa registrada sem pacote de dados")
        else:
            log(f"{unidade}: sem dados para publicar; a tentativa permanece no relatório local")
    resumo_executor(unidade, rel)
    log(f"{unidade}: fim. Avanço: {rel['progresso']}; completo: {rel['completo']}; parou pelo prazo: {rel['parou_por_tempo']}")
    if rodada["falhou_fontes"]:
        raise RuntimeError(f"{unidade}: falha nas fontes obrigatórias; execução incompleta, sem avanço científico")
    return rel


def resumo_executor(unidade: str, rel: dict) -> None:
    uf = S.ler_unidade(unidade)[0]
    linhas = [f"### {unidade} {S.NOME_UF[uf]} (executor)"
              + (f", fatia {rel['fatia']} de {rel['fatias']}" if rel.get("fatia") else "")
              + (f", continuação {rel['continuacao']}" if rel.get("continuacao") else ""), ""]
    for nome, r in rel["etapas_rodadas"].items():
        detalhe = ", ".join(f"{k} {v}" for k, v in r.items() if k not in ("erros",) and v not in (None, [], {}))
        linhas.append(f"- {nome}: {detalhe}")
    linhas.append("")
    faltam = ", ".join(f"{S.NOME_TABELA.get(t, t)} {n}" for t, n in (rel.get("faltam") or {}).items()) or "nada"
    linhas.append(f"Parou pelo prazo: {'sim' if rel['parou_por_tempo'] else 'não'}. Avanço: {rel['progresso']} "
                  f"município(s). Completo: {'sim' if rel['completo'] else 'não'} (falta: {faltam}).")
    if rel["erros"]:
        linhas += ["", f"<details><summary>Erros ({len(rel['erros'])})</summary>", ""]
        linhas += [f"- {e['etapa']} {e['municipio'] or ''}: {e['mensagem']}" for e in rel["erros"][:200]]
        linhas += ["", "</details>"]
    S.resumo_github("\n".join(linhas))


# ---------------------------------------------------------------- continuar

def disparar(campos: dict, rotulo: str) -> bool:
    cmd = ["gh", "workflow", "run", WORKFLOW, "--ref", os.environ.get("GITHUB_REF_NAME", "main"),
           "-R", os.environ.get("GITHUB_REPOSITORY", S.REPO)]
    for k, v in campos.items():
        cmd += ["-f", f"{k}={v}"]
    for i in range(4):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            log(f"disparei {rotulo}")
            S.resumo_github(f"Disparado: {rotulo}.")
            return True
        log(f"disparar {rotulo} falhou ({r.stderr.strip()[:200]}); tento de novo")
        time.sleep(15 * 2 ** i)
    S.acao_github("error", "disparar", f"não consegui disparar {rotulo}; a rodada semanal retoma")
    return False


def continuar(uf: str) -> None:
    """Depois de publicar: se o job parou pelo prazo e avançou, dispara este workflow de novo só para esta unidade
    (estado inteiro ou fatia: continuação). Senão, passa a vez: dispara o 'próximo da fila', que pega a próxima
    unidade (até VAGAS ao mesmo tempo, somando todas as rodadas)."""
    arq = AQUI / "saida" / S.ler_unidade(uf)[0] / "rodada.json"
    if not arq.exists():
        log(f"{uf}: sem rodada.json (o motor não rodou); não disparo nada, a rodada semanal retoma")
        return
    rel = json.loads(arq.read_text(encoding="utf-8"))
    n = int(rel.get("continuacao") or 0)
    if rel.get("erros") and (rel.get("progresso") or 0) <= 0:
        log(f"{uf}: falhou sem avançar; não disparo outro job. A fila limita as novas tentativas e conserva o diagnóstico")
        return
    if rel.get("completo"):
        log(f"{uf}: completo")
    elif not rel.get("parou_por_tempo"):
        log(f"{uf}: terminou dentro do prazo; o que faltou ({', '.join(sorted({e['etapa'] for e in rel.get('erros', [])})) or 'nada'}) "
            "fica para a rodada semanal")
    elif rel.get("progresso", 0) <= 0:
        S.acao_github("warning", f"{uf} sem avanço", "parou pelo prazo sem terminar nenhum município novo; não continuo "
                      "este estado para não girar em falso (a rodada semanal tenta outra vez)")
    elif n + 1 > MAX_CONTINUACOES:
        S.acao_github("warning", f"{uf} continuações", f"chegou a {n} continuações seguidas; paro aqui")
    else:
        campos = {"ufs": uf, "continuacao": n + 1}
        if os.environ.get("GITHUB_ACTIONS") == "true":
            from fila_processamento import guardar_continuacao

            guardar_continuacao(uf, n + 1)
            campos = {"continuacao": "fila"}  # só acorda a fila; não duplica o pedido sob outro run_id
        if disparar(campos, f"a continuação {n + 1} de {uf}"):
            return
    disparar({"continuacao": f"proximo-{uf}"}, "o próximo estado da fila")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ufs", nargs="*")
    p.add_argument("--planejar", action="store_true")
    p.add_argument("--fila", action="store_true", help="planejar somente pedidos já persistidos, sem rodada nova")
    p.add_argument("--preparar", action="store_true")
    p.add_argument("--continuar", action="store_true")
    p.add_argument("--refazer", default=os.environ.get("RAIZ_REFAZER", ""))
    p.add_argument("--etapas", default=os.environ.get("RAIZ_ETAPAS", ""), help="só estas etapas (vírgula)")
    p.add_argument("--executor", action="store_true", default=os.environ.get("RAIZ_EXECUTOR") == "1",
                   help="roda pelo executor do produto (raiz executor), como o GitHub Actions")
    p.add_argument("--continuacao", default=os.environ.get("RAIZ_CONTINUACAO") or "0",
                   help="número da continuação; 'proximo-<UF>' quando o job de <UF> terminou e passou a vez")
    a = p.parse_args()
    ufs = lista_unidades(a.ufs or [os.environ.get("RAIZ_UFS", "")], expandir=a.planejar)
    refazer = lista_refazer(a.refazer)
    cont = str(a.continuacao).strip()
    proximo = cont.lower().startswith("proximo")  # "proximo-PA": o job de PA terminou e passou a vez
    liberou = cont.split("-", 1)[1].upper() if proximo and "-" in cont else None  # unidade: "PA" ou "MG-3"
    continuacao = int(cont) if cont.isdigit() else 0
    if a.planejar:
        modo = "fila" if a.fila or cont == "fila" or os.environ.get("RAIZ_SO_FILA") == "1" else ("proximo" if proximo else "automatico")
        planejar(ufs, refazer, modo, liberou, continuacao)
    elif a.preparar:
        preparar()
    elif a.continuar:
        for uf in ufs:
            continuar(uf)
    else:
        if not ufs:
            p.error("diga o estado, ex.: python rodar_estado.py TO")
        so = {APELIDOS.get(x, x) for x in re.split(r"[\s,;]+", a.etapas.lower()) if x} or None
        if so and so - {n for n, _ in PLANO}:
            p.error(f"etapa desconhecida: {', '.join(so - {n for n, _ in PLANO})}")
        for uf in ufs:
            if a.executor:
                rodar_executor(uf, refazer if not proximo else set(), continuacao)
            else:  # só o motor: a fatia vira o estado inteiro (os scripts do motor rodam por estado)
                rodar(S.ler_unidade(uf)[0], refazer if not proximo else set(), continuacao, so)


if __name__ == "__main__":
    main()
