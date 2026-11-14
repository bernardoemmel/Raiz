"""Testa todas as ferramentas do MCP OAuth local; serviço ausente não é aprovação."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from testes.mcp.cliente import ClienteMCP, ErroMCP  # noqa: E402
from testes.mcp.latencia import carregar_manifesto, medir_latencia  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifesto", default=os.environ.get("RAIZ_MCP_TESTE_CASOS"))
    args = parser.parse_args(argv)
    cliente = None
    try:
        if not args.manifesto:
            raise ErroMCP("Falta o manifesto de argumentos válidos das ferramentas")
        casos = carregar_manifesto(Path(args.manifesto))
        cliente = ClienteMCP(os.environ["RAIZ_MCP_TESTE_URL"], os.environ["RAIZ_MCP_TESTE_TOKEN"])
        print(json.dumps(medir_latencia(cliente, casos), ensure_ascii=False))
        return 0
    except ErroMCP as erro:
        print(f"FALHA: {erro}")
        return 1
    except (KeyError, ValueError):
        print("BLOQUEADO: configure MCP OAuth local, token descartável e manifesto; Produto e regras entrega o MCP.")
        return 2
    except Exception:
        print("FALHA: o transporte MCP não concluiu; consulte diagnóstico sanitizado.")
        return 1
    finally:
        if cliente:
            cliente.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
