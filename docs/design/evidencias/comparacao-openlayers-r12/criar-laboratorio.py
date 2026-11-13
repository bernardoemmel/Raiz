"""Materializa o laboratório registrado sem alterar o checkout nem o snapshot."""

import argparse
import hashlib
import json
import pathlib
import re
import shlex
import subprocess

COMMIT = "7fe3539f63416258f0d91e1c4371fc4d52899aa6"
FONTE_SHA256 = "bf9e2634c586275a54bd2f1ad75c244806f677cae5a29c82b52bf592a2b06c6b"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serie", choices=("corrigida", "exploratoria"), default="corrigida")
for nome in ("repo", "snapshot", "chrome", "destino"):
    parser.add_argument(f"--{nome}", required=True, type=pathlib.Path)
args = parser.parse_args()
repo, snapshot, chrome, destino = (
    getattr(args, nome).resolve() for nome in ("repo", "snapshot", "chrome", "destino")
)
for caminho in (repo, snapshot, chrome, destino):
    if any(c in str(caminho) for c in "'\"\\\n\r"):
        parser.error("Use caminhos sem aspas, barras invertidas ou quebras de linha.")
if destino.exists():
    parser.error("O destino deve ser novo; relatórios anteriores não serão sobrescritos.")
head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip():
    parser.error("O checkout precisa estar limpo para reproduzir o baseline registrado.")
if head != COMMIT:
    parser.error(f"O checkout precisa estar no commit {COMMIT}; encontrado {head}.")
fonte = snapshot / "geo/imoveis_1505536.geojson.gz"
if not fonte.is_file() or hashlib.sha256(fonte.read_bytes()).hexdigest() != FONTE_SHA256:
    parser.error("A geometria não corresponde ao snapshot congelado. Não use o dado atual silenciosamente.")
if not chrome.is_file():
    parser.error("Executável do Chrome não encontrado.")
version = subprocess.check_output([str(chrome), "--version"], text=True).strip()
if "157.0.8103.78" not in version:
    parser.error(f"Versão do navegador divergente: {version}.")
origem = pathlib.Path(__file__).resolve().parent / (
    "laboratorio" if args.serie == "corrigida" else "laboratorio-exploratorio"
)
destino.mkdir(parents=True)
substituicoes = {
    # O prefixo mais longo precisa vir primeiro, para não gerar destino-corrigida.
    "/tmp/raiz-comparacao-openlayers-corrigida": str(destino),
    "/workspace/Raiz-mapa-integrado": str(repo),
    "/tmp/raiz-fontes-final-real-site": str(snapshot),
    "/tmp/raiz-chrome157/chrome-linux64/chrome": str(chrome),
    "/tmp/raiz-comparacao-openlayers": str(destino),
}
for arquivo in origem.iterdir():
    if not arquivo.is_file():
        continue
    texto = arquivo.read_text()
    # Uma passagem evita substituir novamente um prefixo presente no destino escolhido.
    padrao = "|".join(re.escape(s) for s in sorted(substituicoes, key=len, reverse=True))
    texto = re.sub(padrao, lambda m: substituicoes[m.group(0)], texto)
    (destino / arquivo.name).write_text(texto)
(destino / "proveniencia-dados.json").write_text((origem.parent / "proveniencia-dados.json").read_text())
(destino / "reproducao.json").write_text(
    json.dumps({"commit": head, "chrome": version, "snapshot_sha256": FONTE_SHA256,
                "serie": args.serie}, indent=2) + "\n"
)
node_modules = repo / "front/globo/node_modules"
q = lambda p: shlex.quote(str(p))
baseline = "node verificar-baseline.mjs" if args.serie == "corrigida" else "# Série exploratória: sem plugin; não equivale ao produto."
comandos = f"""# Preparar dentro do diretório novo, com as dependências do checkout já instaladas.
cd {q(destino)}
npm ci --ignore-scripts --no-audit --no-fund
{q(repo / '.venv/bin/python')} preparar.py
python validar-entradas.py
node validar-estilo.mjs
{q(node_modules / '.bin/vite')} build
{baseline}

# Terminal 1: servidor exclusivo do laboratório na porta 8765.
python serve.py

# Terminal 2, no mesmo diretório: nenhum navegador ou build concorrente.
# Inspecionar os resultados e capturas do ensaio antes da série.
node rodar.mjs functional-repro
# Só depois da paridade funcional: uma série fixa, sem descarte.
node rodar.mjs serie
node analisar.mjs serie
node validar-serie.mjs serie resultado.json
"""
(destino / "REPRODUZIR.txt").write_text(comandos)
print(f"Laboratório criado em {destino}. Leia REPRODUZIR.txt; nada foi instalado ou medido.")
