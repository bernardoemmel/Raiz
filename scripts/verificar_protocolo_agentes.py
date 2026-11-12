"""Conferência reproduzível: OpenAPI real, Inspector oficial e manifesto do registro, sem publicar.

Sem --mcp-url, confere o OpenAPI gerado pelo app e o manifesto de teste. Com a pilha local em execução,
confere também descoberta, esquemas e uma consulta via MCP autenticado. Nunca imprime o token nem o corpo de erros.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft7Validator, FormatChecker

REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "infra/mcp/server.schema.2025-12-11.json"
SCHEMA_SHA256 = "3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0"
BIN = REPO / "servicos/conferencia-agentes/node_modules/.bin"
PROTOCOLO = "2026-07-28"
BASE_TESTE = "https://raiz.invalid"


def manifesto(base: str | None = None) -> dict:
    """Renderiza server.json; .invalid é apenas a fixture de CI, nunca um domínio anunciado."""
    base = base or BASE_TESTE
    u = urlsplit(base)
    if (
        u.scheme != "https"
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.path not in {"", "/"}
        or u.port not in {None, 443}
        or "." not in u.hostname
    ):
        raise ValueError("o manifesto exige a origem HTTPS, sem caminho, credenciais ou parâmetros")
    modelo = (REPO / "infra/mcp/server.json.template").read_text()
    dados = json.loads(modelo.replace("${RAIZ_API_URL}", base.rstrip("/")))
    bruto = SCHEMA.read_bytes()
    if hashlib.sha256(bruto).hexdigest() != SCHEMA_SHA256:
        raise ValueError("o esquema oficial do registro mudou sem atualização do hash conferido")
    esquema = json.loads(bruto)
    Draft7Validator.check_schema(esquema)
    Draft7Validator(esquema, format_checker=FormatChecker()).validate(dados)
    return dados


def executar(comando: list[str], *, ambiente: dict | None = None) -> subprocess.CompletedProcess:
    """Saída capturada: uma ferramenta externa não pode imprimir credenciais através de um erro."""
    resultado = subprocess.run(comando, env=ambiente, text=True, capture_output=True, timeout=90, check=False)
    if resultado.returncode:
        raise RuntimeError(f"{Path(comando[0]).name} falhou (código {resultado.returncode}); confira a configuração")
    return resultado


def conferir_openapi(saida: Path, url: str | None = None) -> dict:
    from raiz.publica.contrato import RESUMO

    if url:
        resposta = httpx.get(url, timeout=10, follow_redirects=False)
        resposta.raise_for_status()
        documento = resposta.json()
    else:
        from raiz.api import criar_app

        app = criar_app(grafo=object(), deps=object(), whatsapp=False)
        publica = next(r.app for r in app.routes if getattr(r, "path", None) == "/v1")
        documento = publica.openapi()
    if not documento.get("info", {}).get("description", "").startswith(RESUMO) or len(RESUMO.encode()) > 8192:
        raise ValueError("o OpenAPI não contém o resumo único de até 8 KiB")
    arquivo = saida / "openapi.json"
    arquivo.write_text(json.dumps(documento, ensure_ascii=False, indent=2) + "\n")
    relatorio = saida / "vacuum.json"
    executar(
        [
            str(BIN / "vacuum"),
            "lint",
            "--no-update-check",
            "--remote=false",
            "--no-banner",
            "--fail-severity",
            "error",
            "--format",
            "json",
            "--output",
            str(relatorio),
            str(arquivo),
        ]
    )
    return {"caminhos": len(documento["paths"]), "resumo_bytes": len(RESUMO.encode()), "vacuum": "aprovado"}


def conferir_mcp(url: str, token: str) -> dict:
    from raiz.publica.contrato import RESUMO
    from raiz.publica.servidor_mcp import ESCOPOS_FERRAMENTAS

    if not token or any(c.isspace() for c in token):
        raise ValueError("token OAuth de teste ausente ou inválido")
    with tempfile.TemporaryDirectory(prefix="raiz-inspector-") as pasta:
        config = Path(pasta) / "config.json"
        config.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "raiz": {
                            "type": "http",
                            "url": url,
                            "protocolEra": "modern",
                            "headers": {"Authorization": "Bearer " + token},
                        }
                    }
                }
            )
        )
        config.chmod(0o600)
        ambiente = {
            **os.environ,
            "MCP_INSPECTOR_SECRET_STORE": "memory",
            "MCP_STORAGE_DIR": pasta,
            "MCP_INSPECTOR_OAUTH_STATE_PATH": str(Path(pasta) / "oauth.json"),
        }
        comando = [
            str(BIN / "mcp-inspector"),
            "--cli",
            "--config",
            str(config),
            "--server",
            "raiz",
            "--connect-timeout",
            "10000",
            "--stored-auth-only",
            "--format",
            "json",
        ]

        def pedir(*args: str) -> dict:
            resultado = executar([*comando, *args], ambiente=ambiente)
            return json.loads(resultado.stdout)["result"]

        inicio = pedir("--method", "initialize")
        if inicio.get("protocolVersion") != PROTOCOLO or inicio.get("instructions") != RESUMO:
            raise ValueError("descoberta MCP divergiu do protocolo ou do resumo contratado")
        catalogo = pedir("--method", "tools/list", "--strict")
        nomes = {f["name"] for f in catalogo["tools"]}
        if nomes != set(ESCOPOS_FERRAMENTAS):
            raise ValueError("catálogo MCP divergiu das ferramentas autorizadas")
        resposta = pedir(
            "--method",
            "tools/call",
            "--tool-name",
            "consultar_disponibilidade",
            "--tool-args-json",
            '{"campos":{"onde":{"ufs":["PA"]}}}',
        )
        if resposta.get("isError") or not resposta.get("structuredContent", {}).get("pedido_id"):
            raise ValueError("a consulta MCP não devolveu um pedido rastreável")
        # Somente metadados seguros vão ao relatório; resultado, token e configuração temporária não são copiados.
        return {"protocolo": PROTOCOLO, "ferramentas": sorted(nomes), "consulta": "aprovada"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida", type=Path, default=Path(".cache/protocolo-agentes"))
    parser.add_argument("--openapi-url")
    parser.add_argument("--mcp-url")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--token-env", default="RAIZ_MCP_TOKEN")
    parser.add_argument("--dominio", help="origem HTTPS futura; gera server.json, nunca publica")
    args = parser.parse_args()
    args.saida.mkdir(parents=True, exist_ok=True)
    relatorio: dict = {"aprovado": False, "publicado": False}
    try:
        registro = manifesto(args.dominio)
        (args.saida / "server.json").write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n")
        relatorio["registro"] = "validado; domínio de teste" if not args.dominio else "validado; aguarda implantação"
        relatorio["openapi"] = conferir_openapi(args.saida, args.openapi_url)
        if args.mcp_url:
            token = args.token_file.read_text().strip() if args.token_file else os.environ.get(args.token_env, "")
            relatorio["mcp"] = conferir_mcp(args.mcp_url, token)
        else:
            relatorio["mcp"] = "não executado; informe --mcp-url e token de uma empresa sintética"
        relatorio["aprovado"] = True
    except (ValueError, RuntimeError, OSError, httpx.HTTPError, subprocess.SubprocessError) as exc:
        # Não reproduzir mensagem externa: ela pode conter token, URL ou dados de resposta.
        relatorio["erro"] = type(exc).__name__
    (args.saida / "resultado.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(relatorio, ensure_ascii=False))
    return 0 if relatorio["aprovado"] else 1


if __name__ == "__main__":
    sys.exit(main())
