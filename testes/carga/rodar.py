"""Executa a carga local da API e exige sucesso, saturação e recuperação da janela.

uv run python -m testes.carga.rodar --resultado resultado-carga
RAIZ_BANCO_URL_CARGA precisa apontar para PostGIS local descartável terminado em _carga.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from testes.carga.contrato import ROTAS_API, conferir_relatorio, retry_after_valido
from testes.carga.servidor import banco_local


def porta_livre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def aguardar(processo: subprocess.Popen, porta: int, pronto: Path) -> None:
    prazo = time.monotonic() + 120
    while time.monotonic() < prazo and processo.poll() is None:
        if pronto.exists():
            try:
                with socket.create_connection(("127.0.0.1", porta), timeout=0.2):
                    return
            except OSError:
                pass
        time.sleep(0.1)
    raise RuntimeError("API de carga não iniciou; consulte o log estruturado do servidor")


def recuperar(url: str, token: str) -> dict:
    cab = {"Authorization": "Bearer " + token}
    # Espera apenas o intervalo informado pelo servidor, depois verifica a recuperação real.
    resposta = requests.get(url + "/saude", headers=cab, timeout=4.9)
    if resposta.status_code != 429:
        # Garante nova saturação, mesmo se o Locust acabou exatamente na virada da janela.
        for _ in range(40):
            resposta = requests.get(url + "/saude", headers=cab, timeout=4.9)
            if resposta.status_code == 429:
                break
    if resposta.status_code != 429 or not retry_after_valido(resposta.headers.get("Retry-After")):
        raise RuntimeError("Não foi possível comprovar 429 com Retry-After na recuperação")
    espera = int(resposta.headers["Retry-After"])
    time.sleep(espera + 0.1)
    resposta = requests.get(url + "/saude", headers=cab, timeout=4.9)
    if resposta.status_code != 200 or resposta.json() != {"ok": True}:
        raise RuntimeError("API não voltou a atender depois de Retry-After")
    return {"status_saturado": 429, "retry_after_segundos": espera, "status_recuperado": 200}


def rodar(resultado: Path, usuarios: int = 6, segundos: int = 10) -> None:
    url_banco = banco_local(os.environ["RAIZ_BANCO_URL_CARGA"])
    if usuarios < 2 or segundos < 5:
        raise ValueError("Carga precisa de pelo menos 2 usuários e 5 segundos por fase")
    resultado.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "RAIZ_CARGA_TOKEN": token, "RAIZ_BANCO_URL_CARGA": url_banco}
    with tempfile.TemporaryDirectory(prefix="raiz-carga-") as temporario:
        for fase in ("normal", "limite"):
            porta = porta_livre()
            url = f"http://127.0.0.1:{porta}"
            pronto = Path(temporario) / fase
            cmd = [
                sys.executable,
                "-m",
                "testes.carga.servidor",
                "--fase",
                fase,
                "--porta",
                str(porta),
                "--pronto",
                str(pronto),
            ]
            if fase == "limite":
                cmd.append("--reutilizar")
            with (resultado / f"servidor-{fase}.jsonl").open("w", encoding="utf-8") as log:
                processo = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    aguardar(processo, porta, pronto)
                    arquivo = resultado / f"api-{fase}.json"
                    carga = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "locust",
                            "-f",
                            "testes/carga/locustfile.py",
                            "--headless",
                            "--host",
                            url,
                            "--users",
                            str(usuarios),
                            "--spawn-rate",
                            str(usuarios),
                            "--run-time",
                            f"{segundos}s",
                            "--stop-timeout",
                            "5",
                            "--only-summary",
                            "--exit-code-on-error",
                            "1",
                        ],
                        env={**env, "RAIZ_CARGA_FASE": fase, "RAIZ_CARGA_RELATORIO": str(arquivo.resolve())},
                        timeout=segundos + 30,
                        check=False,
                    )
                    if carga.returncode:
                        raise RuntimeError(f"Locust reprovou fase {fase}")
                    problemas = conferir_relatorio(json.loads(arquivo.read_text()), set(ROTAS_API))
                    if problemas:
                        raise RuntimeError("Portão de carga reprovou: " + "; ".join(problemas))
                    if fase == "limite":
                        (resultado / "recuperacao.json").write_text(
                            json.dumps(recuperar(url, token), indent=2), encoding="utf-8"
                        )
                finally:
                    processo.terminate()
                    try:
                        processo.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        processo.kill()
                        processo.wait(timeout=5)
    print("Carga aprovada: rotas reais, respostas <5 s, 429 com Retry-After e recuperação.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resultado", type=Path, default=Path("resultado-carga"))
    parser.add_argument("--usuarios", type=int, default=6)
    parser.add_argument("--segundos", type=int, default=10)
    args = parser.parse_args()
    rodar(args.resultado, args.usuarios, args.segundos)
