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
VAGAS = int(os.environ.get("RAIZ_VAGAS", 4))  # estados rodando ao mesmo tempo, somando todas as rodadas do workflow
DIAS_TENTADO = 6  # o "próximo da fila" não pega de novo estado tentado há menos que isto (a rodada semanal pega)
WORKFLOW = os.environ.get("RAIZ_WORKFLOW", "processar-estados.yml")


def log(msg: str) -> None:
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def prazo() -> float:
    if not (os.environ.get("RAIZ_INICIO") or os.environ.get("RAIZ_LIMITE_MIN")):
        return float("inf")
    ini = float(os.environ.get("RAIZ_INICIO") or time.time())
    return ini + 60 * (float(os.environ.get("RAIZ_LIMITE_MIN", 330)) - float(os.environ.get("RAIZ_MARGEM_MIN", 25)))


def lista_ufs(args: list[str]) -> list[str]:
    ufs = []
    for a in args:
        for x in re.split(r"[\s,;]+", a.upper()):
            if x and x in S.TOTAL_IBGE and x not in ufs:
                ufs.append(x)
            elif x:
                S.acao_github("warning", "UF desconhecida", f"ignorei '{x}'")
    return ufs


def lista_refazer(txt: str) -> set[str]:
    out = set()
    for x in re.split(r"[\s,;]+", (txt or "").lower()):
        if not x:
            continue
        x = APELIDOS.get(x, x)
        if x == "tudo" or x in S.ETAPAS:
            out.add(x)
        else:
            S.acao_github("warning", "refazer", f"tabela desconhecida '{x}' (use: funil, filtros, mapbiomas, direto, "
                                                 "extras_direto, extras ou tudo)")
    if out & {"tudo", "imoveis"}:  # refazer o funil muda os polígonos: refaz tudo que depende dele
        out = set(S.ETAPAS)
    return out


def gh_output(**kv) -> None:
    f = os.environ.get("GITHUB_OUTPUT")
    if f:
        with open(f, "a", encoding="utf-8") as fh:
            for k, v in kv.items():
                fh.write(f"{k}={v}\n")


# ---------------------------------------------------------------- planejar

def ufs_ativas() -> tuple[set[str], int]:
    """Estados com job deste workflow rodando ou na fila em outras rodadas, e quantas rodadas ainda estão planejando
    (cada uma conta como uma vaga ocupada). Sem acesso à API, devolve vazio (e avisa)."""
    eu = os.environ.get("GITHUB_RUN_ID")
    repo = os.environ.get("GITHUB_REPOSITORY", S.REPO)
    try:
        r = subprocess.run(["gh", "run", "list", "-R", repo, "--workflow", WORKFLOW, "--limit", "50",
                            "--json", "databaseId,status"], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise RuntimeError(r.stderr.strip()[:200])
        ativas, planejando = set(), 0
        for run in json.loads(r.stdout):
            if str(run["databaseId"]) == eu or run["status"] == "completed":
                continue
            j = subprocess.run(["gh", "run", "view", str(run["databaseId"]), "-R", repo, "--json", "jobs"],
                               capture_output=True, text=True, timeout=120)
            jobs = json.loads(j.stdout).get("jobs", []) if j.returncode == 0 else []
            ufs = {x["name"] for x in jobs if x.get("name") in S.TOTAL_IBGE and x.get("status") != "completed"}
            feitos = {x["name"] for x in jobs if x.get("name") in S.TOTAL_IBGE}
            ativas |= ufs
            if not feitos:
                planejando += 1
        return ativas, planejando
    except Exception as ex:
        if os.environ.get("GITHUB_ACTIONS"):
            S.acao_github("warning", "planejar", f"não consegui ver as rodadas em andamento ({ex}); conto zero")
        return set(), 0


def tentado_ha_pouco(e: dict) -> bool:
    """Rodou há menos de DIAS_TENTADO dias e terminou dentro do prazo (ou parou sem avançar): o que faltou depende de
    fonte fora do ar ou de erro em município, e fica para a rodada semanal."""
    rod = (e.get("motor") or {}).get("rodada") or {}
    if not rod.get("fim"):
        return False
    try:
        idade = time.time() - dt.datetime.fromisoformat(rod["fim"]).timestamp()
    except ValueError:
        return False
    return idade < DIAS_TENTADO * 86400 and (not rod.get("parou_por_tempo") or (rod.get("progresso") or 0) <= 0)


def planejar(pedidos: list[str], refazer: set[str], modo: str = "automatico", liberou: str | None = None) -> list[str]:
    """Estados que precisam rodar, na ordem de S.ORDEM.
    Pedido explícito (campo ufs, ou continuação de um estado): roda esses. Senão, entram os que não começaram, os
    incompletos, os publicados antes da automação (para conferir e adotar a versão) e os que têm tabela feita com código
    antigo, limitados às vagas livres (VAGAS menos os estados já rodando em outras rodadas). No modo 'proximo' (um job
    terminou e passa a vez), entra no máximo um estado, e ficam de fora os tentados há pouco; `liberou` é o estado do job
    que passou a vez (ainda aparece rodando enquanto este plano é feito, mas a vaga dele já está livre)."""
    pub = S.ler_manifesto().get("estados", {})
    atual = S.versoes()
    if refazer and not pedidos:
        pedidos = [uf for uf in S.ORDEM if uf in pub]
        S.acao_github("notice", "refazer", f"sem lista de estados: refaço {', '.join(sorted(refazer))} em todos os publicados")
    ativas, planejando = (set(), 0) if pedidos else ufs_ativas()
    ativas.discard(liberou)
    vagas = len(S.ORDEM) if pedidos else max(0, VAGAS - len(ativas) - planejando)
    if modo == "proximo":
        vagas = min(vagas, 1)
    matriz, linhas = [], []
    for uf in S.ORDEM:
        e = pub.get(uf)
        motivo, mudou = None, []
        if pedidos:
            if uf not in pedidos:
                continue
            motivo = "pedido" + (f" (refazer {', '.join(sorted(refazer))})" if refazer else "")
        elif not e:
            motivo = "ainda não começou"
        elif not e.get("motor"):
            motivo = "publicado antes da automação: conferir o que falta e adotar a versão"
        else:
            etapas = e["motor"].get("etapas") or {}
            mudou = [t for t, v in atual.items() if t != "extras" and (etapas.get(t) or {}).get("versao") not in (None, v)]
            if mudou:
                motivo = "código mudou: " + ", ".join(S.NOME_TABELA.get(t, t) for t in mudou)
            elif not e.get("completo"):
                falta = e.get("faltam") or {}
                motivo = "falta " + ", ".join(f"{S.NOME_TABELA.get(t, t)} {n}" for t, n in falta.items())
        acao = motivo or "pronto, nada a fazer"
        if motivo and not pedidos:
            if uf in ativas:
                acao, motivo = f"{motivo} (já rodando em outra rodada)", None
            elif modo == "proximo" and not mudou and e and tentado_ha_pouco(e):
                acao, motivo = f"{motivo} (tentado há pouco; fica para a rodada semanal)", None
            elif len(matriz) >= vagas:
                acao, motivo = f"{motivo} (na fila)", None
        feitos = "—" if not e else f"{e.get('municipios', 0) + e.get('sem_imoveis', 0)}/{e.get('total_ibge') or S.TOTAL_IBGE[uf]}"
        linhas.append(f"| {uf} | {feitos} | {acao}{' **agora**' if motivo else ''} |")
        if motivo:
            matriz.append(uf)
    texto = (f"### Plano desta rodada ({'pedido' if pedidos else modo})\n\n"
             f"Rodando em outras rodadas: {', '.join(sorted(ativas)) or 'nenhum'}"
             f"{f' (mais {planejando} planejando)' if planejando else ''}. Vagas: {VAGAS}.\n\n"
             "| Estado | Municípios | O que fazer |\n|---|---|---|\n" + "\n".join(linhas))
    texto += f"\n\nVersão do código por tabela: {', '.join(f'{t} {v}' for t, v in atual.items())}"
    print(texto)
    S.resumo_github(texto)
    gh_output(matriz=json.dumps(matriz), tem="1" if matriz else "0", dia=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d"))
    return matriz


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
    """Depois de publicar: se o job parou pelo prazo e avançou, dispara este workflow de novo só para esta UF
    (continuação). Senão, passa a vez: dispara o 'próximo da fila', que pega o próximo estado na ordem (até VAGAS
    estados ao mesmo tempo, somando todas as rodadas)."""
    arq = AQUI / "saida" / uf / "rodada.json"
    if not arq.exists():
        log(f"{uf}: sem rodada.json (o motor não rodou); não disparo nada, a rodada semanal retoma")
        return
    rel = json.loads(arq.read_text(encoding="utf-8"))
    n = int(rel.get("continuacao") or 0)
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
        if disparar({"ufs": uf, "continuacao": n + 1}, f"a continuação {n + 1} de {uf}"):
            return
    disparar({"continuacao": f"proximo-{uf}"}, "o próximo estado da fila")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ufs", nargs="*")
    p.add_argument("--planejar", action="store_true")
    p.add_argument("--preparar", action="store_true")
    p.add_argument("--continuar", action="store_true")
    p.add_argument("--refazer", default=os.environ.get("RAIZ_REFAZER", ""))
    p.add_argument("--etapas", default=os.environ.get("RAIZ_ETAPAS", ""), help="só estas etapas (vírgula)")
    p.add_argument("--continuacao", default=os.environ.get("RAIZ_CONTINUACAO") or "0",
                   help="número da continuação; 'proximo-<UF>' quando o job de <UF> terminou e passou a vez")
    a = p.parse_args()
    ufs = lista_ufs(a.ufs or [os.environ.get("RAIZ_UFS", "")])
    refazer = lista_refazer(a.refazer)
    cont = str(a.continuacao).strip()
    proximo = cont.lower().startswith("proximo")  # "proximo-PA": o job de PA terminou e passou a vez
    liberou = cont.split("-", 1)[1].upper() if proximo and "-" in cont else None
    continuacao = int(cont) if cont.isdigit() else 0
    if a.planejar:
        planejar(ufs, refazer, "proximo" if proximo else "automatico", liberou)
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
            rodar(uf, refazer if not proximo else set(), continuacao, so)


if __name__ == "__main__":
    main()
