"""Espera limitada antes da atestação; não imprime respostas nem credenciais."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def aguardar(*, limite=1200, minimo=30, abrir=urllib.request.urlopen, dormir=time.sleep, relogio=time.time):
    fim = relogio() + limite
    while True:
        pedido = urllib.request.Request(
            "https://api.github.com/rate_limit",
            headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"},
        )
        try:
            with abrir(pedido, timeout=30) as resposta:
                cota = json.load(resposta)["resources"]["core"]
            if cota["remaining"] >= minimo:
                return
            espera = max(1, cota["reset"] - relogio() + 1)
        except urllib.error.HTTPError as erro:
            if erro.code not in (403, 429):
                raise RuntimeError("não foi possível conferir a cota para atestação") from None
            espera = max(60, float(erro.headers.get("Retry-After", "60")))
        if relogio() + espera > fim:
            raise RuntimeError("cota insuficiente para atestar no prazo; resultados preservados no checkpoint")
        while espera > 0:
            passo = min(60, espera)
            dormir(passo)
            espera -= passo


if __name__ == "__main__":
    aguardar()
