"""
Raíz: situação de cada estado no motor (o que já foi feito, o que falta e com que versão do código).

Usado por rodar_estado.py (quem roda), publicar_dados.py (quem publica no Release `dados`) e painel.py (README do motor).
Só usa a biblioteca padrão do Python (o planejamento do GitHub Actions roda sem instalar nada).

Versão do motor: cada tabela depende de alguns scripts (ETAPAS). A versão da tabela é um hash do código desses scripts
sem comentários, docstrings e linhas em branco: mudar um texto de ajuda não refaz o Brasil, mudar uma conta refaz. O sha do
commit que rodou fica gravado junto (para o aprendizado saber exatamente qual código gerou cada previsão), mas a decisão
de refazer usa o hash do código, porque o merge com squash troca o sha sem trocar o código.
"""

from __future__ import annotations

import ast
import datetime as dt
import hashlib
import io
import json
import os
import re
import subprocess
import time
import tokenize
import urllib.error
import urllib.request
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REPO = os.environ.get("RAIZ_REPO", "bernardoemmel/raiz")
TAG = os.environ.get("RAIZ_TAG_DADOS", "dados")
BASE = f"https://github.com/{REPO}/releases/download/{TAG}"

# municípios por UF (IBGE 2022; o DF conta como 1)
TOTAL_IBGE = {
    "AC": 22, "AL": 102, "AP": 16, "AM": 62, "BA": 417, "CE": 184, "DF": 1, "ES": 78, "GO": 246,
    "MA": 217, "MT": 142, "MS": 79, "MG": 853, "PA": 144, "PB": 223, "PR": 399, "PE": 185, "PI": 224,
    "RJ": 92, "RN": 167, "RS": 497, "RO": 52, "RR": 15, "SC": 295, "SP": 645, "SE": 75, "TO": 139,
}
NOME_UF = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul", "RO": "Rondônia",
    "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}
# Ordem de trabalho: primeiro completar o que já está publicado, depois a Amazônia Legal, depois o resto do país.
ORDEM = ["PA", "RO", "RR", "AC", "AP",
         "TO", "MA", "AM", "MT",
         "GO", "MS", "MG", "BA", "PI", "CE", "RN", "PB", "PE", "AL", "SE", "ES", "RJ", "SP", "PR", "SC", "RS", "DF"]

# Tabela por município -> scripts de que ela depende. Todas dependem do raiz_estado.py porque ele grava o polígono dos
# imóveis (geo_<mun>.parquet): se o funil muda, o CAR pode mudar, e as outras tabelas precisam ser refeitas junto.
ETAPAS = {
    "imoveis": ("raiz_estado.py",),
    "filtros": ("raiz_filtros.py", "raiz_estado.py", "raiz_extras.py"),
    "mapbiomas": ("raiz_mapbiomas.py", "raiz_extras.py", "raiz_estado.py"),
    "direto": ("raiz_direto.py", "raiz_extras.py", "raiz_estado.py"),
    "extras_direto": ("raiz_extras_direto.py", "raiz_extras.py", "raiz_estado.py"),
    "extras": ("raiz_extras.py", "raiz_estado.py"),
}
CODIGO_MOTOR = ("raiz_estado.py", "raiz_filtros.py", "raiz_mapbiomas.py", "raiz_direto.py", "raiz_extras_direto.py",
                "raiz_extras.py", "raiz_app.py")
# Para o estado estar completo: funil em todos os municípios e estas tabelas em todos os que têm imóvel, mais a APP
# pela escadinha (coluna app_escadinha_ha no imoveis_). Ficam de fora: extras (precisa dos GeoTIFFs exportados uma vez do
# Earth Engine) e certidoes (só existe onde há parcela SIGEF com matrícula).
OBRIGATORIAS = ("filtros", "mapbiomas", "direto", "extras_direto")
TABELAS = ("imoveis", "direto", "filtros", "extras", "extras_direto", "mapbiomas", "certidoes")
# tabelas do produto, feitas pelo executor (raiz/executor/tarefas.py) depois das do motor
PRODUTO = ("flag", "terra", "ficha", "desenvolvedor")
NOME_TABELA = {"imoveis": "funil", "filtros": "filtros", "mapbiomas": "MapBiomas", "direto": "direto",
               "extras_direto": "TMF e causas", "app": "APP escadinha", "extras": "extras (Earth Engine)",
               "flag": "FLAG", "terra": "caminho da terra", "ficha": "ficha", "desenvolvedor": "desenvolvedor"}

_RE_TAB = {t: re.compile(rf"^{t}_(\d{{7}})\.csv$") for t in TABELAS + PRODUTO}
_RE_GEO = re.compile(r"^geo_(\d{7})\.parquet$")


def agora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- versão do código

def _sem_comentarios(fonte: str) -> str:
    """Código sem comentários, docstrings, espaços no fim e linhas em branco. Usa só posições de linha e coluna (iguais em
    todas as versões do Python), para o hash não mudar quando o Python do computador muda."""
    linhas = fonte.replace("\r\n", "\n").split("\n")
    tirar: set[int] = set()
    for no in ast.walk(ast.parse(fonte)):
        corpo = getattr(no, "body", None)
        if isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and corpo:
            p = corpo[0]
            if isinstance(p, ast.Expr) and isinstance(p.value, ast.Constant) and isinstance(p.value.value, str):
                tirar.update(range(p.lineno - 1, p.end_lineno))
    corte: dict[int, int] = {}
    for tok in tokenize.generate_tokens(io.StringIO(fonte).readline):
        if tok.type == tokenize.COMMENT:
            corte[tok.start[0] - 1] = tok.start[1]
    out = []
    for i, linha in enumerate(linhas):
        if i in tirar:
            continue
        if i in corte:
            linha = linha[:corte[i]]
        linha = linha.rstrip()
        if linha:
            out.append(linha)
    return "\n".join(out)


def hash_codigo(arquivos) -> str:
    h = hashlib.sha256()
    for nome in sorted(arquivos):
        h.update(nome.encode())
        h.update(_sem_comentarios((AQUI / nome).read_text(encoding="utf-8")).encode())
    return h.hexdigest()[:12]


def versoes() -> dict[str, str]:
    """Versão atual (hash do código) de cada tabela."""
    return {t: hash_codigo(arqs) for t, arqs in ETAPAS.items()}


def _git(*args) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=AQUI, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def commit_atual() -> str | None:
    return os.environ.get("GITHUB_SHA") or _git("rev-parse", "HEAD")


def codigo_sujo() -> bool:
    """True se o código do motor tem mudança sem commit (só acontece rodando no computador)."""
    if os.environ.get("GITHUB_ACTIONS"):
        return False
    s = _git("status", "--porcelain", "--", *CODIGO_MOTOR)
    return bool(s)


def url_rodada() -> str | None:
    if os.environ.get("GITHUB_RUN_ID"):
        return f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', REPO)}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    return None


# ---------------------------------------------------------------- o que existe na pasta de um estado

def cods(pasta: Path, tabela: str) -> set[str]:
    if not pasta.is_dir():
        return set()
    if tabela == "geo":
        return {m.group(1) for f in pasta.iterdir() if (m := _RE_GEO.match(f.name))}
    rx = _RE_TAB[tabela]
    return {m.group(1) for f in pasta.iterdir() if (m := rx.match(f.name))}


def arquivos_tabela(pasta: Path, tabela: str) -> list[Path]:
    """Arquivos que pertencem a uma tabela (para apagar quando ela precisa ser refeita). O funil leva junto as certidões,
    os polígonos, o resumo e a lista de municípios sem imóvel."""
    if not pasta.is_dir():
        return []
    if tabela == "imoveis":
        rx = re.compile(r"^((imoveis|certidoes)_\d{7}\.csv|geo_\d{7}\.parquet|resumo_[A-Z]{2}\.csv|sem_imoveis_[A-Z]{2}\.csv)$")
    else:
        rx = _RE_TAB[tabela]
    return sorted(f for f in pasta.iterdir() if rx.match(f.name))


def sem_imoveis(pasta: Path, uf: str) -> dict[str, str]:
    """Municípios que o funil consultou e não têm nenhum imóvel IRU no CAR (ex.: Uiramutã, toda dentro de terra indígena).
    Contam como prontos."""
    f = pasta / f"sem_imoveis_{uf}.csv"
    out = {}
    if f.exists():
        for i, linha in enumerate(f.read_text(encoding="utf-8").splitlines()):
            partes = linha.split(",")
            if i == 0 or not partes or not re.fullmatch(r"\d{7}", partes[0]):
                continue
            out[partes[0]] = partes[1] if len(partes) > 1 else ""
    return out


def com_app(pasta: Path, feitos: set[str]) -> set[str]:
    """Municípios cujo imoveis_ já tem a APP pela escadinha (coluna app_escadinha_ha)."""
    ok = set()
    for c in feitos:
        try:
            with open(pasta / f"imoveis_{c}.csv", encoding="utf-8", errors="replace") as fh:
                if "app_escadinha_ha" in fh.readline().split(","):
                    ok.add(c)
        except OSError:
            pass
    return ok


def municipios_ibge(uf: str) -> set[str] | None:
    """Códigos IBGE do estado pela lista local (cache/municipios.csv), se já foi baixada."""
    f = next((x for x in (AQUI / "cache" / "municipios.csv", AQUI.parent / "raiz" / "executor" / "municipios.csv")
              if x.exists()), None)
    if f is None:
        return None
    cod_uf = {"RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17, "MA": 21, "PI": 22, "CE": 23,
              "RN": 24, "PB": 25, "PE": 26, "AL": 27, "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
              "PR": 41, "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53}[uf]
    import csv
    with open(f, encoding="utf-8", newline="") as fh:
        return {r["codigo_ibge"] for r in csv.DictReader(fh) if r.get("codigo_uf") == str(cod_uf)}


def pendentes(pasta: Path, uf: str, vazios: set[str] | None = None, produto: bool = False) -> dict[str, set[str]]:
    """Municípios que faltam em cada etapa. vazios: municípios sem imóvel que o executor anotou na marca (o motor
    sozinho anota em sem_imoveis_<UF>.csv). produto: conta também as tabelas do produto (estado feito pelo executor)."""
    feitos, sem = cods(pasta, "imoveis"), set(sem_imoveis(pasta, uf)) | {str(x) for x in (vazios or ())}
    lista = municipios_ibge(uf)
    out: dict[str, set[str]] = {}
    if lista is not None:
        out["imoveis"] = lista - feitos - sem
    else:  # sem a lista, só dá para saber quantos faltam
        n = TOTAL_IBGE[uf] - len(feitos | sem)
        out["imoveis"] = {f"?{i}" for i in range(max(n, 0))}
    for t in OBRIGATORIAS + ("extras",) + (PRODUTO if produto else ()):
        out[t] = feitos - cods(pasta, t)
    out["app"] = feitos - com_app(pasta, feitos)
    return out


def situacao(pasta: Path, uf: str, vazios: set[str] | None = None, produto: bool = False) -> dict:
    """Resumo do estado para o estados.json: feitos, total, o que falta e se está completo."""
    feitos, sem = cods(pasta, "imoveis"), set(sem_imoveis(pasta, uf)) | {str(x) for x in (vazios or ())}
    p = pendentes(pasta, uf, vazios, produto)
    exigidas = ("imoveis",) + OBRIGATORIAS + ("app",) + (PRODUTO if produto else ())
    faltam = {t: len(p[t]) for t in exigidas if p[t]}
    tabelas = {t: len(cods(pasta, t)) for t in TABELAS + (PRODUTO if produto else ())}
    tabelas["app"] = len(feitos) - len(p["app"])
    return {
        "municipios": len(feitos),
        "sem_imoveis": len(sem - feitos),
        "total_ibge": TOTAL_IBGE.get(uf),
        "funil_completo": "imoveis" not in faltam,
        "completo": not faltam,
        "faltam": faltam,
        "tabelas": tabelas,
    }


def faltam_da_entrada(e: dict) -> dict[str, int] | None:
    """O que falta segundo uma entrada do estados.json. Entrada antiga (sem 'faltam') devolve None: precisa conferir."""
    if "faltam" in e:
        return e["faltam"]
    return None


# ---------------------------------------------------------------- estados.json publicado

def _tem_gh() -> bool:
    return bool(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")) and subprocess.run(
        ["gh", "--version"], capture_output=True).returncode == 0


def ler_manifesto(tentativas: int = 4) -> dict:
    """estados.json publicado no Release. {} se ainda não existe; erro se não conseguir ler (para não tratar o Brasil
    inteiro como vazio por causa de uma falha de rede)."""
    ultimo = None
    for i in range(tentativas):
        if _tem_gh():  # pela API: sempre a versão mais nova, sem cache no caminho
            try:
                r = subprocess.run(["gh", "release", "download", TAG, "-R", REPO, "-p", "estados.json", "-O", "-"],
                                   capture_output=True, text=True, timeout=120)
                if r.returncode == 0:
                    return json.loads(r.stdout) if r.stdout.strip() else {}
                err = r.stderr.lower()
                if "no assets match" in err or "release not found" in err:
                    return {}
                ultimo = r.stderr.strip()[:300]
            except Exception as ex:
                ultimo = ex
        try:  # endereço público do Release (não precisa de token)
            req = urllib.request.Request(f"{BASE}/estados.json", headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as ex:
            if ex.code == 404:
                return {}
            ultimo = ex
        except Exception as ex:
            ultimo = ex
        time.sleep(5 * 2 ** i)
    raise RuntimeError(f"não consegui ler o estados.json publicado: {ultimo}")


# ---------------------------------------------------------------- privacidade

_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CPF = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")


def mascarar(texto: str, limite: int = 240) -> str:
    """Tira qualquer coisa com cara de CPF ou CNPJ de mensagens que vão para log, resumo ou estados.json."""
    t = _CPF.sub("***", _CNPJ.sub("***", str(texto)))
    t = " ".join(t.split())
    return t[:limite] + ("…" if len(t) > limite else "")


def acao_github(tipo: str, titulo: str, mensagem: str) -> None:
    """Anotação no GitHub Actions (aparece no resumo do job). Fora do Actions, só imprime."""
    m = mascarar(mensagem, 400).replace("%", "%25").replace("\n", "%0A")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{tipo} title={titulo}::{m}", flush=True)
    else:
        print(f"[{tipo}] {titulo}: {m}", flush=True)


def resumo_github(texto: str) -> None:
    f = os.environ.get("GITHUB_STEP_SUMMARY")
    if f:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(texto.rstrip() + "\n\n")
