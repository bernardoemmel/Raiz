"""Executa o contrato adversarial somente com um adaptador real explicitamente configurado."""

import argparse
import asyncio
import importlib
import json
import sys
from pathlib import Path

# Também funciona como `uv run python scripts/avaliar_injecoes_mcp.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from testes.mcp.avaliacao import FalhaAvaliacao, avaliar_injecoes  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adaptador", help="modulo:fabrica do ambiente de teste MCP/OAuth real")
    args = parser.parse_args(argv)
    if not args.adaptador:
        print("BLOQUEADO: o MCP/OAuth e seu adaptador de teste ainda precisam ser entregues por Produto e regras.")
        return 2
    try:
        modulo, fabrica = args.adaptador.split(":", 1)
        ambiente = getattr(importlib.import_module(modulo), fabrica)()
        resultado = asyncio.run(avaliar_injecoes(ambiente))
    except FalhaAvaliacao as erro:
        print(f"FALHA: {erro}")
        return 1
    except Exception:
        print("BLOQUEADO: não foi possível carregar ou executar o adaptador MCP; nenhum cenário foi aprovado.")
        return 2
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
