"""Prepara ou instala o cron dos alertas sem apagar os outros trabalhos do usuário.

Execute no servidor da Raíz, com o usuário que lê o .env e acessa o banco:
    uv run python scripts/instalar_cron_alertas.py
    uv run python scripts/instalar_cron_alertas.py --instalar
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
from pathlib import Path

INICIO = "# INICIO RAIZ ALERTAS (gerenciado por instalar_cron_alertas.py)"
FIM = "# FIM RAIZ ALERTAS"


def bloco(repositorio: Path, uv: str, flock: str) -> str:
    """Caminhos absolutos, diretório do .env e trava contra rodadas simultâneas."""
    caminhos = [str(repositorio.resolve()), str(Path(uv).resolve()), str(Path(flock).resolve())]
    if any(any(c in caminho for c in "\n\r%") for caminho in caminhos):
        # O cron interpreta % mesmo dentro de aspas; não aceitar caminhos ambíguos.
        raise ValueError("Os caminhos não podem conter quebra de linha nem %.")
    repo, uv, flock = map(shlex.quote, caminhos)
    comando = (
        f"cd {repo} && /bin/mkdir -p dados/operacao && "
        "if [ -f .env ]; then set -- --env-file .env; else set --; fi && "
        f'{flock} -n -E 0 dados/operacao/alertas.lock {uv} run "$@" --frozen raiz operacao alertas'
    )
    return f"{INICIO}\n*/15 * * * * {comando}\n{FIM}\n"


def atualizar(atual: str, novo_bloco: str) -> str:
    """Substitui só o bloco da Raíz; repetir a instalação não duplica o cron."""
    linhas = atual.splitlines(keepends=True)
    inicios = [i for i, linha in enumerate(linhas) if linha.rstrip("\r\n") == INICIO]
    fins = [i for i, linha in enumerate(linhas) if linha.rstrip("\r\n") == FIM]
    if not inicios and not fins:
        separador = "\n" if atual and not atual.endswith("\n") else ""
        return atual + separador + novo_bloco
    if len(inicios) != 1 or len(fins) != 1 or inicios[0] >= fins[0]:
        raise ValueError("Bloco da Raíz incompleto ou duplicado no crontab; corrija antes de instalar.")
    return "".join(linhas[: inicios[0]]) + novo_bloco + "".join(linhas[fins[0] + 1 :])


def instalar(novo_bloco: str) -> None:
    cron = shutil.which("crontab")
    if cron is None:
        raise ValueError("crontab não está instalado neste servidor.")
    ambiente = {**os.environ, "LC_ALL": "C"}
    anterior = subprocess.run([cron, "-l"], capture_output=True, text=True, env=ambiente, check=False)
    if anterior.returncode:
        # Não interpretar falta de permissão ou falha do serviço como crontab vazio.
        if anterior.returncode != 1 or "no crontab for" not in anterior.stderr.lower():
            raise ValueError("Não foi possível ler o crontab; nenhum agendamento foi alterado.")
        atual = ""
    else:
        atual = anterior.stdout
    novo = atualizar(atual, novo_bloco)
    if novo != atual:
        subprocess.run([cron, "-"], input=novo, text=True, check=True, env=ambiente)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instalar", action="store_true", help="instala no crontab do usuário atual")
    parser.add_argument("--repositorio", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        if not (args.repositorio / "pyproject.toml").is_file():
            raise ValueError("O diretório precisa ser a raiz do repositório da Raíz.")
        uv, flock = shutil.which("uv"), shutil.which("flock")
        if not uv or not flock:
            raise ValueError("Instale uv e flock (util-linux) antes de preparar o cron.")
        agendamento = bloco(args.repositorio, uv, flock)
        if args.instalar:
            instalar(agendamento)
            print("Alertas agendados a cada 15 minutos no crontab deste usuário.")
        else:
            print(agendamento, end="")
            print("# Prévia: use --instalar no servidor para ativar.")
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Não foi possível preparar os alertas: {exc}\n")


if __name__ == "__main__":
    main()
