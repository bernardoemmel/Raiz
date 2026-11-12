"""Sobe a pilha API/MCP local ou de produção e mede seus recursos, sem contratar infraestrutura.

Teste: python scripts/pilha_agentes.py teste
Produção: python scripts/pilha_agentes.py subir --env-file producao.env
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
SEGREDOS = (
    "RAIZ_BANCO_SENHA",
    "RAIZ_KEYCLOAK_BANCO_SENHA",
    "RAIZ_KEYCLOAK_ADMIN_SENHA",
    "RAIZ_API_TOKEN",
    "RAIZ_CHAVE_PESSOAL",
    "RAIZ_RECIBO_CHAVE",
)


def ler_env(caminho: Path) -> dict[str, str]:
    """Lê o formato simples gerado aqui; nunca executa comandos contidos no arquivo."""
    resultado = {}
    for linha in caminho.read_text().splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        chave, separador, valor = linha.partition("=")
        if not separador or not re.fullmatch(r"[A-Z][A-Z0-9_]*", chave):
            raise ValueError("arquivo env inválido; use CHAVE=valor, sem export ou comandos")
        resultado[chave] = valor.strip().strip("\"'")
    return resultado


def ambiente_teste(caminho: Path) -> None:
    if caminho.exists():
        return
    senha = secrets.token_hex(24)
    dados = {
        "RAIZ_BANCO_SENHA": senha,
        "RAIZ_BANCO_NOME": "raiz_agentes_teste",
        "RAIZ_BANCO_URL_HOST": f"postgresql+psycopg://raiz:{senha}@localhost:15432/raiz_agentes_teste",
        "RAIZ_KEYCLOAK_BANCO_SENHA": secrets.token_hex(24),
        "RAIZ_KEYCLOAK_ADMIN": "administracao-teste",
        "RAIZ_KEYCLOAK_ADMIN_SENHA": secrets.token_hex(24),
        "RAIZ_API_TOKEN": secrets.token_hex(32),
        "RAIZ_CHAVE_PESSOAL": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "RAIZ_RECIBO_CHAVE": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "RAIZ_KEYCLOAK_URL": "http://localhost:18180",
        "RAIZ_OAUTH_ISSUER": "http://localhost:18180/realms/raiz",
        "RAIZ_MCP_RESOURCE": "http://localhost:18000/mcp",
        "RAIZ_API_PUBLICA_URL": "http://localhost:18000",
        "RAIZ_OAUTH_REDIRECT_URI": "http://localhost:18765/callback",
        "RAIZ_MCP_HOSTS": "localhost:18000,127.0.0.1:18000,localhost:8000,127.0.0.1:8000",
        "RAIZ_API_ORIGENS": "http://localhost:18000",
        "RAIZ_LOGIN_BASE_URL": "http://localhost:18000",
        "RAIZ_FRONT_URL": "http://localhost:18000",
        "RAIZ_PIX_MODO": "teste",
        "RAIZ_AGENDA_MODO": "teste",
        "RAIZ_AGENDA_FUSO": "America/Sao_Paulo",
        "RAIZ_DADOS_PRIVADOS_URL": "/app/dados/armazem",
    }
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(caminho, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as arq:
        arq.write("# Credenciais descartáveis; nunca usar em produção nem versionar.\n")
        arq.write("".join(f"{k}={v}\n" for k, v in dados.items()))


def validar(dados: dict[str, str], teste: bool) -> None:
    if any(not dados.get(k) for k in (*SEGREDOS, "RAIZ_KEYCLOAK_ADMIN")):
        raise ValueError("preencha os segredos exigidos em infra/agentes.env.example")
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", dados["RAIZ_BANCO_SENHA"]):
        raise ValueError("RAIZ_BANCO_SENHA: use ao menos 24 caracteres ASCII, números, hífen ou sublinhado")
    for chave in ("RAIZ_CHAVE_PESSOAL", "RAIZ_RECIBO_CHAVE"):
        try:
            valor = dados[chave].split(",")[0]
            if len(base64.urlsafe_b64decode(valor + "=" * (-len(valor) % 4))) != 32:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError(f"{chave}: configure uma chave de 32 bytes em base64url") from None
    for chave in ("RAIZ_KEYCLOAK_URL", "RAIZ_OAUTH_ISSUER", "RAIZ_MCP_RESOURCE", "RAIZ_API_PUBLICA_URL"):
        url = urlsplit(dados.get(chave, ""))
        if not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError(f"{chave}: URL inválida")
        if not teste and (url.scheme != "https" or url.hostname.endswith(".example")):
            raise ValueError(f"{chave}: configure domínio HTTPS real antes da produção")
    if dados["RAIZ_OAUTH_ISSUER"].rstrip("/") != dados["RAIZ_KEYCLOAK_URL"].rstrip("/") + "/realms/raiz":
        raise ValueError("RAIZ_OAUTH_ISSUER deve corresponder ao realm raiz da URL do Keycloak")
    if not dados["RAIZ_MCP_RESOURCE"].endswith("/mcp"):
        raise ValueError("RAIZ_MCP_RESOURCE deve terminar em /mcp, sem barra final")
    callback = urlsplit(dados.get("RAIZ_OAUTH_REDIRECT_URI", ""))
    if not callback.hostname or "*" in callback.geturl() or callback.fragment or callback.username:
        raise ValueError("configure callback OAuth exato, sem curinga ou fragmento")
    if not teste and callback.scheme != "https":
        raise ValueError("o callback OAuth de produção exige HTTPS")
    if not teste and dados.get("RAIZ_AGENDA_MODO") != "producao":
        raise ValueError("RAIZ_AGENDA_MODO deve ser producao na instalação")
    if not teste and (
        dados.get("RAIZ_PIX_MODO") != "producao"
        or any(
            not dados.get(k)
            for k in (
                "RAIZ_ABACATEPAY_CHAVE",
                "RAIZ_ABACATEPAY_WEBHOOK_SEGREDO",
                "RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA",
            )
        )
    ):
        raise ValueError(
            "produção exige Pix em producao, chave do provedor e configuração dos webhooks; "
            "use a pilha teste enquanto essas credenciais não estiverem disponíveis"
        )
    if teste and dados.get("RAIZ_PIX_MODO") != "teste":
        raise ValueError("a pilha de teste exige RAIZ_PIX_MODO=teste")


def comando_compose(env_file: Path, teste: bool) -> list[str]:
    base = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--project-name",
        "raiz-agentes-teste" if teste else "raiz-agentes",
        "-f",
        str(REPO / "infra/docker-compose.agentes.yml"),
    ]
    if teste:
        base.extend(["-f", str(REPO / "infra/docker-compose.agentes-teste.yml")])
    return base


def executar(cmd: list[str], *, capturar: bool = False) -> str:
    resultado = subprocess.run(cmd, cwd=REPO, check=True, text=True, capture_output=capturar)
    return resultado.stdout if capturar else ""


def memoria_bytes(texto: str) -> int:
    partes = re.fullmatch(r"([0-9.]+)\s*([KMGT]?i?B)", texto.strip())
    if not partes:
        raise ValueError("medida de memória desconhecida")
    numero, unidade = partes.groups()
    ordem = {"B": 0, "KB": 1, "MB": 2, "GB": 3, "TB": 4, "KiB": 1, "MiB": 2, "GiB": 3, "TiB": 4}[unidade]
    return int(float(numero) * (1024 if "i" in unidade else 1000) ** ordem)


def medir(compose: list[str], saida: Path, amostras: int, intervalo: float) -> None:
    ids = executar([*compose, "ps", "-q"], capturar=True).split()
    if not ids:
        raise ValueError("a pilha não tem serviços ativos")
    pico: dict[str, int] = {}
    coleta = []
    for n in range(amostras):
        linhas = executar(["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids], capturar=True)
        pontos = []
        for linha in linhas.splitlines():
            p = json.loads(linha)
            uso = memoria_bytes(p["MemUsage"].split("/")[0])
            pico[p["Name"]] = max(uso, pico.get(p["Name"], 0))
            pontos.append(
                {"servico": p["Name"], "memoria_bytes": uso, "cpu_percentual": float(p["CPUPerc"].rstrip("%"))}
            )
        coleta.append({"em": dt.datetime.now(dt.UTC).isoformat(), "servicos": pontos})
        if n + 1 < amostras:
            time.sleep(intervalo)
    imagens = executar([*compose, "images", "-q"], capturar=True).split()
    tamanhos = json.loads(executar(["docker", "image", "inspect", *sorted(set(imagens))], capturar=True))
    discos = {}
    for servico, caminho in (
        ("banco", "/var/lib/postgresql/data"),
        ("banco-oauth", "/var/lib/postgresql/data"),
        ("valkey", "/data"),
        ("api", "/app/dados"),
    ):
        valor = executar([*compose, "exec", "-T", servico, "du", "-sk", caminho], capturar=True)
        discos[servico] = int(valor.split()[0]) * 1024
    relatorio = {
        "medido_em": dt.datetime.now(dt.UTC).isoformat(),
        "amostras": coleta,
        "pico_memoria_bytes_por_servico": pico,
        "soma_picos_memoria_bytes": sum(pico.values()),
        "volumes_bytes": discos,
        "imagens_bytes_soma_sem_deduplicar_camadas": sum(i["Size"] for i in tamanhos),
        "limites": "Amostras da carga observada; não é pico garantido nem dimensionamento do catálogo nacional. "
        "Imagens compartilham camadas; a soma é limite conservador. WAL, backups e margem de disco são adicionais.",
    }
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n")
    print(f"medição salva em {saida}; soma dos picos amostrados: {sum(pico.values()) / 1024**2:.1f} MiB")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("acao", choices=["teste", "subir", "parar", "medir"])
    p.add_argument("--env-file", type=Path)
    p.add_argument("--teste", action="store_true", help="seleciona pilha descartável para medir/parar")
    p.add_argument("--sem-build", action="store_true")
    p.add_argument("--saida", type=Path, default=REPO / "dados/operacao/recursos-agentes.json")
    p.add_argument("--amostras", type=int, default=5)
    p.add_argument("--intervalo", type=float, default=5)
    a = p.parse_args()
    teste = a.acao == "teste" or a.teste
    env_file = (a.env_file or REPO / (".env.agentes-teste" if teste else "producao.env")).resolve()
    if a.acao == "teste":
        ambiente_teste(env_file)
    if not env_file.is_file():
        p.error("arquivo env ausente; copie infra/agentes.env.example e preencha os segredos")
    dados = ler_env(env_file)
    try:
        validar(dados, teste)
        compose = comando_compose(env_file, teste)
        if a.acao == "parar":
            executar([*compose, "down"])  # preserva dados; nunca apaga volumes implicitamente
        elif a.acao == "medir":
            if not 1 <= a.amostras <= 720 or not 0 <= a.intervalo <= 60:
                p.error("use de 1 a 720 amostras e intervalo de 0 a 60 segundos")
            medir(compose, a.saida, a.amostras, a.intervalo)
        else:
            executar([*compose, "config", "--quiet"])
            if not a.sem_build:
                cmd = [
                    "docker",
                    "build",
                    "-f",
                    "infra/agentes/Dockerfile",
                    "-t",
                    "raiz/agentes:" + dados.get("RAIZ_IMAGEM_TAG", "local"),
                ]
                # Apenas build: CA da plataforma não entra na imagem final.
                if os.environ.get("CODEX_PROXY_CERT"):
                    cmd.extend(["--secret", "id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt"])
                executar([*cmd, "."])
            executar([*compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "300"])
            print("pilha saudável; API/MCP, banco, OAuth, worker e agenda ativos")
    except (ValueError, OSError, subprocess.CalledProcessError) as ex:
        # Não reproduzir arquivo env, URL do banco ou saída de subprocessos com segredos.
        p.exit(1, f"falha na pilha ({type(ex).__name__}); confira a configuração e o estado dos serviços\n")


if __name__ == "__main__":
    main()
