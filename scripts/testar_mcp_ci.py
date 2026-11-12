"""Ativa automaticamente os ensaios quando o servidor MCP entrar no checkout.

A ausência (ou o stub exato da migração) gera aviso explícito autorizado pelo
fundador. Qualquer implementação presente exige integração real: erro nunca vira skip.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
STUB_MIGRACAO = "86561f0d67031f4944f5a4295282d37bfd42a2e95117ae48446cb2a835d28e5f"
ENTRADAS = ("raiz/publica/servidor_mcp.py", "raiz/mcp.py", "raiz/mcp/__init__.py")


def disponivel(raiz: Path = RAIZ) -> bool:
    for relativo in ENTRADAS:
        arquivo = raiz / relativo
        if arquivo.exists() and hashlib.sha256(arquivo.read_bytes()).hexdigest() != STUB_MIGRACAO:
            return True
    projeto = raiz / "pyproject.toml"
    if projeto.exists():
        dependencias = tomllib.loads(projeto.read_text()).get("project", {}).get("dependencies", [])
        if any(re.match(r"(?i)^mcp(?:\[|[<>=!~ ;]|$)", d) for d in dependencias):
            return True
    return False


class CorpusPendente(RuntimeError):
    """Transporte verificado, mas o produto ainda não oferece o agente leitor do corpus."""


def executar(resultado: Path) -> dict:
    from testes.carga.contrato import conferir_relatorio
    from testes.mcp.avaliacao import avaliar_injecoes
    from testes.mcp.latencia import medir_latencia

    # A integração pertence ao produto: precisa iniciar OAuth/MCP/banco reais e
    # fornecer observadores independentes. Ausência desse módulo REPROVA se há MCP.
    fabrica = importlib.import_module("testes.mcp.produto").integracao
    with fabrica() as produto:
        latencia = medir_latencia(produto.cliente, produto.casos)
        (resultado / "latencia.json").write_text(json.dumps(latencia, ensure_ascii=False, indent=2))
        cargas = []
        for fase in ("normal", "limite"):
            arquivo = (resultado / f"carga-{fase}.json").resolve()
            # Cada contexto prepara dados descartáveis e o orçamento da fase.
            with produto.carga(fase) as variaveis:
                env = {**os.environ, **variaveis, "RAIZ_CARGA_FASE": fase, "RAIZ_CARGA_RELATORIO": str(arquivo)}
                r = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "locust",
                        "-f",
                        "testes/carga/locust_mcp.py",
                        "--headless",
                        "--users",
                        "6",
                        "--spawn-rate",
                        "6",
                        "--run-time",
                        "10s",
                        "--only-summary",
                    ],
                    cwd=RAIZ,
                    env=env,
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
                if r.returncode:
                    raise RuntimeError("Locust MCP reprovou")
                dado = json.loads(arquivo.read_text())
                if conferir_relatorio(dado, set(produto.casos)):
                    raise RuntimeError("Contrato da carga MCP reprovou")
                cargas.append(dado)
        if getattr(produto, "injecoes_disponiveis", True) is False:
            raise CorpusPendente
        injecoes = asyncio.run(avaliar_injecoes(produto.ambiente))
        return {"estado": "aprovado", "injecoes": injecoes, "latencia": latencia, "carga": cargas}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detectar", action="store_true")
    parser.add_argument("--resultado", type=Path, default=Path("resultado-mcp"))
    args = parser.parse_args(argv)
    args.resultado.mkdir(parents=True, exist_ok=True)
    codigo = 0
    try:
        tem = disponivel()
        if args.detectar and os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as f:
                f.write(f"disponivel={'true' if tem else 'false'}\n")
        if not tem:
            aviso = "MCP ausente: ensaios de integração não executados; responsável Produto e regras."
            print("::warning title=MCP pendente::" + aviso)
            dado = {"estado": "ausente", "aviso": aviso, "ensaios_executados": False}
        elif args.detectar:
            dado = {"estado": "presente", "ensaios_executados": False}
        else:
            dado = executar(args.resultado)
    except CorpusPendente:
        codigo = 1
        dado = {
            "estado": "falha",
            "aviso": "Latência e carga MCP passaram; corpus não executado: agente leitor de documentos pendente de Produto e regras.",
            "ensaios_executados": {"latencia": True, "carga": True, "corpus": False},
        }
        print("::error title=Corpus MCP pendente::" + dado["aviso"])
    except Exception:
        # Não ecoar exceções do adaptador, servidor, OAuth ou Locust.
        codigo = 1
        dado = {
            "estado": "falha",
            "aviso": "MCP presente exige adaptador, OAuth, corpus, todas as ferramentas e carga aprovados.",
        }
        print("::error title=MCP reprovado::" + dado["aviso"])
    (args.resultado / "integracao.json").write_text(json.dumps(dado, ensure_ascii=False, indent=2))
    if resumo := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(resumo).open("a") as f:
            f.write("\n### MCP — " + dado["estado"] + "\n\n" + dado.get("aviso", "Ver relatório de integração.") + "\n")
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
