"""Agente Claude sem ferramentas locais: toda ação do produto passa pelo MCP HTTP.

O provedor prepara cenários sintéticos e julga em uma sessão independente. O agente
não recebe o gabarito, os critérios nem a lista de ações autorizadas de cada tarefa.
VCR grava somente o fornecedor do modelo; OAuth, MCP e banco continuam reais no replay.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import copy
import hashlib
import importlib
import inspect
import json
import logging
import math
import os
import re
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx2 as httpx
from anthropic import AsyncAnthropic
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from raiz.publica.avaliacao import FERRAMENTAS, GABARITO, Chamada, Execucao, Tarefa, avaliar, carregar_gabarito

VERSAO = "claude-mcp-v1"
_UUID = re.compile(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b")
_DATA = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b")
_ALIAS = re.compile(r"__RAIZ_(?:UUID|DATA|TOKEN|PRAZO_(?:FUTURO|VENCIDO)_\d+M)_\d{4}__")
_mapa_atual = contextvars.ContextVar("mapa_cassete", default=None)
_TOKEN_URL = re.compile(r"(/(?:v1/)?(?:reservas/confirmar|cobrancas)/)[A-Za-z0-9_-]{24,128}")
_MODELO = re.compile(r"^[a-z][a-z0-9.-]{2,100}$")
_DATAS_TECNICAS = {"criado_em", "criada_em", "atualizado_em", "registrado_em", "inicio_em", "resolvida_em"}
_PRAZOS = {"expira_em", "confirmacao_expira", "preco_valido_ate"}


def _opaco(tipo: str, valor: str) -> str:
    prefixo = f"__RAIZ_{tipo}_SHA256_"
    return valor if valor.startswith(prefixo) else prefixo + hashlib.sha256(valor.encode()).hexdigest() + "__"


def _ocultar_raciocinio(dado: Any) -> Any:
    """O diálogo real preserva thinking/signature; gravações guardam somente seus hashes.

    No replay o bloco opaco nunca é enviado ao fornecedor: o modo none do VCR
    exige uma resposta gravada para cada pedido. A mesma transformação no pedido
    canônico confere a cadeia sem publicar conteúdo de raciocínio ou assinatura.
    """
    if isinstance(dado, list):
        return [_ocultar_raciocinio(v) for v in dado]
    if isinstance(dado, dict):
        if dado.get("type") in {"thinking", "redacted_thinking"}:
            return {k: _opaco(k.upper(), v) if k != "type" and isinstance(v, str) else v for k, v in dado.items()}
        return {k: _ocultar_raciocinio(v) for k, v in dado.items()}
    return dado


def _json(dado: Any) -> str:
    return json.dumps(dado, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hash_json(dado: Any) -> str:
    return hashlib.sha256(_json(dado).encode()).hexdigest()


def _sem_segredos(dado: Any, segredos: list[str]) -> Any:
    if isinstance(dado, str):
        for segredo in segredos:
            if segredo:
                dado = dado.replace(segredo, "[CREDENCIAL_REMOVIDA]")
        return dado
    if isinstance(dado, dict):
        return {k: _sem_segredos(v, segredos) for k, v in dado.items()}
    if isinstance(dado, list):
        return [_sem_segredos(v, segredos) for v in dado]
    return dado


@dataclass
class Cenario:
    contexto: str
    mcp_url: str
    access_token: str = field(repr=False)
    dados: dict = field(default_factory=dict, repr=False)


@dataclass
class Julgamento:
    criterios: dict[str, bool]
    violacoes: list[str] = field(default_factory=list)
    chamadas_nao_autorizadas: list[int] = field(default_factory=list)


class Provedor(Protocol):
    versao: str

    async def preparar(self, tarefa: Tarefa, tentativa: int, campanha_id: str) -> Cenario: ...

    async def julgar(self, tarefa: Tarefa, cenario: Cenario, trace: dict) -> Julgamento: ...

    async def finalizar(self, cenario: Cenario) -> None: ...


class MapaCassete:
    """Remove IDs dinâmicos da gravação, reidratando-os com os IDs da sessão atual.

    Números de negócio, argumentos, ordem de mensagens e esquema continuam no hash
    do pedido. Não há matcher permissivo que esconda regressão de conteúdo.
    """

    def __init__(self, namespace: str):
        self.namespace = namespace
        self.valores: dict[str, str] = {}
        self.originais: dict[str, str] = {}
        self.contadores: dict[str, int] = {}
        self.inicio_requisicao: float | None = None

    def _alias(self, valor: str, tipo: str) -> str:
        if valor not in self.valores:
            numero = self.contadores.get(tipo, 0) + 1
            self.contadores[tipo] = numero
            alias = f"__RAIZ_{tipo}_{numero:04d}__"
            self.valores[valor] = alias
            self.originais[alias] = valor
        return self.valores[valor]

    def normalizar(self, dado: Any, chave: str = "") -> Any:
        if isinstance(dado, str):
            # MCP e o juiz carregam objetos também dentro de content[].text.
            if dado.startswith(("{", "[")):
                try:
                    interno = json.loads(dado)
                except ValueError:
                    pass
                else:
                    if isinstance(interno, dict | list):
                        return _json(self.normalizar(interno))
            dado = _TOKEN_URL.sub(lambda m: m[1] + self._alias(m[0][len(m[1]) :], "TOKEN"), dado)
            dado = _UUID.sub(lambda m: self._alias(m[0], "UUID"), dado)
            if chave in _DATAS_TECNICAS and _DATA.fullmatch(dado):
                return self._alias(dado, "DATA")
            if chave in _PRAZOS and _DATA.fullmatch(dado):
                if dado not in self.valores:
                    restante = (datetime.fromisoformat(dado.replace("Z", "+00:00")) - datetime.now(UTC)).total_seconds()
                    estado = "FUTURO" if restante > 0 else "VENCIDO"
                    return self._alias(dado, f"PRAZO_{estado}_{round(abs(restante) / 60)}M")
                return self.valores[dado]
            # Texto que cita um prazo já visto recebe o MESMO alias sem perder
            # a relação. Outras datas de negócio ficam integrais.
            return _DATA.sub(lambda m: self.valores.get(m[0], m[0]), dado)
        if isinstance(dado, dict):
            return {k: self.normalizar(v, k) for k, v in dado.items()}
        if isinstance(dado, list):
            return [self.normalizar(v) for v in dado]
        return dado

    def restaurar(self, texto: str) -> str:
        def original(m):
            alias = m[0]
            if alias not in self.originais:
                # UUID novo sugerido pelo modelo, por exemplo Idempotency-Key.
                if "_UUID_" not in alias:
                    raise ValueError("cassete contém data ou token sem origem na sessão atual")
                valor = str(uuid5(NAMESPACE_URL, self.namespace + alias))
                self.originais[alias] = valor
                self.valores[valor] = alias
                self.contadores["UUID"] = max(self.contadores.get("UUID", 0), int(alias[-6:-2]))
            return self.originais[alias]

        return _ALIAS.sub(original, texto)


async def _restaurar_resposta(response: httpx.Response) -> None:
    mapa = _mapa_atual.get()
    if mapa is not None and response.request.url.host == "api.anthropic.com":
        duracao = float(response.headers.get("x-raiz-inferencia-segundos", "0"))
        if not math.isfinite(duracao) or not 0 <= duracao <= 180:
            raise ValueError("duração inválida na cassette")
        # O worker continua real. Reproduzir o tempo da inferência evita adiantar
        # artificialmente o próximo polling quando o Claude é reproduzido localmente.
        await asyncio.sleep(duracao)
        corpo = await response.aread()
        response._content = mapa.restaurar(corpo.decode()).encode()


async def _marcar_inicio(request: httpx.Request) -> None:
    mapa = _mapa_atual.get()
    if mapa is not None and request.url.host == "api.anthropic.com":
        mapa.inicio_requisicao = time.monotonic()


def cliente_claude(*, modo: str = "real") -> AsyncAnthropic:
    """Cliente comum ao agente e ao juiz; replay não usa nem transmite credencial real."""
    chave = os.environ.get("ANTHROPIC_API_KEY") if modo == "real" else "replay-sem-credencial"
    if not chave:
        raise ValueError("ANTHROPIC_API_KEY ausente")
    return AsyncAnthropic(
        api_key=chave,
        base_url="https://api.anthropic.com",
        max_retries=0,
        http_client=httpx.AsyncClient(
            timeout=90,
            event_hooks={
                "request": [_marcar_inicio],
                "response": [_restaurar_resposta] if modo == "replay" else [],
            },
        ),
    )


def _sanitizar_texto(texto: str) -> str:
    from raiz.logs_seguros import sanitizar_log

    # Presidio não deve destruir o alias opaco de um link que será reidratado.
    partes, posicao = [], 0
    for m in _ALIAS.finditer(texto):
        partes.extend((sanitizar_log(texto[posicao : m.start()]), m[0]))
        posicao = m.end()
    partes.append(sanitizar_log(texto[posicao:]))
    return "".join(partes)


def _sanitizar_input(dado: Any) -> Any:
    from raiz.publica.privacidade import chave_pessoal

    if isinstance(dado, str):
        return _sanitizar_texto(dado)
    if isinstance(dado, list):
        return [_sanitizar_input(v) for v in dado]
    if isinstance(dado, dict):
        return {
            k: _sanitizar_input(v)
            for k, v in dado.items()
            if not chave_pessoal(k) and not re.search(r"(?i)token|secret|senha|password|authorization", k)
        }
    return dado


def _sanitizar_resposta_modelo(dado: dict) -> dict:

    for bloco in dado.get("content", []):
        if bloco.get("type") == "text":
            bloco["text"] = _sanitizar_texto(bloco.get("text", ""))
        elif bloco.get("type") == "tool_use":
            bloco["name"] = _nome_chamada(bloco.get("name", ""))
            bloco["input"] = _sanitizar_input(bloco.get("input", {}))
        elif bloco.get("type") not in {"thinking", "redacted_thinking"}:
            raise ValueError("tipo de conteúdo do modelo não configurado para a avaliação")
    return dado


@contextmanager
def gravacao(caminho: Path, *, modo: str, namespace: str, segredos: list[str] | None = None):
    import vcr

    if modo == "real" and caminho.exists():
        raise ValueError("cassete existente: use uma pasta nova para uma campanha nova")
    if modo == "replay" and not caminho.is_file():
        raise ValueError("cassete real ausente; replay não pode chamar o fornecedor")
    mapa = MapaCassete(namespace)
    segredos = [*(segredos or []), os.environ.get("ANTHROPIC_API_KEY", "")]
    token = _mapa_atual.set(mapa)

    def pedido(request):
        if urlsplit(request.uri).hostname != "api.anthropic.com":
            return None
        bruto = json.loads(request.body)
        # O prompt não é gravado: apenas seu hash canônico permite casar o replay.
        if set(bruto) != {"raiz_requisicao_sha256"}:
            bruto = mapa.normalizar(_ocultar_raciocinio(_sem_segredos(bruto, segredos)))
            # A cassette sanitiza respostas antes de persistir. A mesma projeção
            # nos blocos já presentes na conversa mantém o casamento estrito.
            for mensagem in bruto.get("messages", []):
                if mensagem.get("role") == "assistant" and isinstance(mensagem.get("content"), list):
                    mensagem = _sanitizar_resposta_modelo(mensagem)
            bruto = {"raiz_requisicao_sha256": hash_json(bruto)}
        request.body = _json(bruto).encode()
        request.headers = {"content-type": "application/json"}
        return request

    def resposta(response):
        # VCR também aplica este filtro ao carregar a cassette. A gravação já está
        # sanitizada: reprocessá-la apagaria a latência e alteraria seus aliases.
        if modo == "replay":
            return response
        if response["status"]["code"] != 200:
            response["body"]["string"] = b'{"type":"error","error":{"type":"api_error","message":"falha"}}'
        else:
            bruto = json.loads(response["body"]["string"])
            bruto = _sanitizar_resposta_modelo(mapa.normalizar(_ocultar_raciocinio(_sem_segredos(bruto, segredos))))
            response["body"]["string"] = _json(bruto).encode()
        duracao = time.monotonic() - mapa.inicio_requisicao if mapa.inicio_requisicao is not None else 0
        response["headers"] = {"content-type": ["application/json"], "x-raiz-inferencia-segundos": [str(duracao)]}
        return response

    recorder = vcr.VCR(
        record_mode="all" if modo == "real" else "none",
        match_on=["method", "scheme", "host", "port", "path", "query", "body"],
        before_record_request=pedido,
        before_record_response=resposta,
        decode_compressed_response=True,
    )
    try:
        with recorder.use_cassette(str(caminho)) as cassette:
            yield cassette
            if modo == "replay" and not cassette.all_played:
                raise ValueError("replay não consumiu todas as respostas gravadas")
    finally:
        _mapa_atual.reset(token)
        if caminho.exists():
            caminho.chmod(0o600)


async def conversar(
    tarefa: Tarefa,
    cenario: Cenario,
    session,
    cliente,
    *,
    modelo: str,
    max_passos: int,
    max_tokens: int,
    instrucoes: str,
    ferramentas: list[dict],
) -> dict:
    """Loop sem shell, navegador, SDK de pagamentos ou ferramenta fora do MCP."""
    inicio = time.monotonic()
    mensagens = [{"role": "user", "content": tarefa.solicitacao + "\n\nContexto disponível:\n" + cenario.contexto}]
    trace = {
        "tarefa_id": tarefa.id,
        "inicio_em": datetime.now(UTC).isoformat(),
        "modelo": modelo,
        "resposta": "",
        "mensagens": mensagens,
        "chamadas": [],
        "passos_modelo": 0,
        "duracao_segundos": 0.0,
        "erro": None,
        "uso": {"input_tokens": 0, "output_tokens": 0},
    }
    catalogo = {f["name"] for f in ferramentas}
    for _ in range(max_passos):
        trace["passos_modelo"] += 1
        resposta = await cliente.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            output_config={"effort": "medium"},
            system=instrucoes,
            tools=ferramentas,
            messages=mensagens,
        )
        if resposta.model != modelo:
            raise ValueError("o fornecedor respondeu com outro modelo")
        for k in trace["uso"]:
            trace["uso"][k] += getattr(resposta.usage, k, 0)
        blocos = [b.model_dump(mode="json", exclude_none=True) for b in resposta.content]
        mensagens.append({"role": "assistant", "content": blocos})
        chamadas = [b for b in blocos if b["type"] == "tool_use"]
        if not chamadas:
            trace["resposta"] = "\n".join(b["text"] for b in blocos if b["type"] == "text")
            if resposta.stop_reason != "end_turn":
                trace["erro"] = "resposta_interrompida"
            break
        resultados = []
        for chamada in chamadas:
            agora = time.monotonic()
            registro = {
                "ferramenta": chamada["name"],
                "argumentos": chamada["input"],
                "inicio_segundos": agora - inicio,
                "duracao_segundos": 0.0,
                "resultado": {},
                "is_error": False,
            }
            # Tentativas proibidas e desconhecidas entram no trace ANTES da execução.
            trace["chamadas"].append(registro)
            if chamada["name"] not in catalogo:
                resultado = {"isError": True, "content": [{"type": "text", "text": "Ferramenta inexistente no MCP."}]}
            else:
                try:
                    bruto = await session.call_tool(chamada["name"], chamada["input"], read_timeout_seconds=5)
                    resultado = bruto.model_dump(mode="json", by_alias=True, exclude_none=True)
                except Exception:
                    # A nota continua reprovável, sem copiar tokens/argumentos da exceção.
                    resultado = {"isError": True, "content": [{"type": "text", "text": "Falha no transporte MCP."}]}
            registro.update(
                resultado=resultado,
                is_error=bool(resultado.get("isError")),
                duracao_segundos=time.monotonic() - agora,
            )
            resultados.append(
                {
                    "type": "tool_result",
                    "tool_use_id": chamada["id"],
                    "content": _json(resultado),
                    "is_error": registro["is_error"],
                }
            )
        mensagens.append({"role": "user", "content": resultados})
    else:
        trace["erro"] = "limite_de_passos"
    trace["duracao_segundos"] = time.monotonic() - inicio
    trace["mensagens"] = _ocultar_raciocinio(copy.deepcopy(mensagens))
    return trace


async def _descobrir(session) -> tuple[str, list[dict]]:
    inicial = await session.initialize()
    ferramentas, cursores = [], set()
    resultado = await session.list_tools()
    while True:
        ferramentas.extend(
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in resultado.tools
        )
        if not resultado.next_cursor:
            break
        if resultado.next_cursor in cursores:
            raise ValueError("paginação MCP repetiu cursor")
        cursores.add(resultado.next_cursor)
        from mcp.types import PaginatedRequestParams

        resultado = await session.list_tools(params=PaginatedRequestParams(cursor=resultado.next_cursor))
    if len({f["name"] for f in ferramentas}) != len(ferramentas):
        raise ValueError("catálogo MCP duplicado")
    return inicial.instructions or "", ferramentas


def _hash_codigo(provedor) -> dict:
    raiz = Path(__file__).resolve().parents[2]
    rastreados = (
        subprocess.run(
            [
                "git",
                "ls-files",
                "-co",
                "--exclude-standard",
                "-z",
                "--",
                "raiz",
                "migracoes",
                "infra",
                "motor",
                "scripts",
                "nativo",
                "uv.lock",
                "pyproject.toml",
                "alembic.ini",
            ],
            cwd=raiz,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .split("\0")
    )
    caminhos = [raiz / p for p in sorted(set(rastreados)) if p]
    origem = inspect.getsourcefile(type(provedor))
    if origem:
        caminhos.append(Path(origem))
    extras = getattr(provedor, "arquivos_configuracao", [])
    caminhos.extend(Path(p) for p in extras)
    head = (
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=raiz, check=True, capture_output=True).stdout.decode().strip()
    )
    arquivos = {
        str(p.relative_to(raiz)) if p.is_relative_to(raiz) else p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in caminhos
        if p.is_file()
    }
    return {"git_head": head, "arquivos": arquivos}


def _imagens(cenario: Cenario) -> dict:
    if cenario.dados.get("fontes_montadas") is not False:
        raise ValueError("medição exige imagens imutáveis, sem fontes montadas do host")
    imagens = cenario.dados.get("imagens_servico")
    if not isinstance(imagens, dict) or not {"api", "worker", "banco", "keycloak"} <= imagens.keys():
        raise ValueError("provider não comprovou as imagens dos quatro serviços")
    if any(not isinstance(v, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", v) for v in imagens.values()):
        raise ValueError("identidade de imagem inválida")
    return imagens


def _proveniencia(cenario: Cenario, codigo: dict) -> dict:
    manifestos = cenario.dados.get("proveniencia_servico", {})
    if not isinstance(manifestos, dict) or not {"api", "worker"} <= manifestos.keys():
        raise ValueError("API e worker precisam do manifesto de código embutido na imagem")
    obrigatorios = {
        "raiz/api.py",
        "raiz/publica/servidor_mcp.py",
        "raiz/publica/trabalhos.py",
        "uv.lock",
        "pyproject.toml",
        "alembic.ini",
    }
    for manifesto in manifestos.values():
        if not isinstance(manifesto, dict) or manifesto.get("versao") != 1:
            raise ValueError("manifesto de código da imagem inválido")
        arquivos = manifesto.get("arquivos", {})
        if not isinstance(arquivos, dict) or not obrigatorios <= arquivos.keys():
            raise ValueError("manifesto de código da imagem incompleto")
        if any(codigo["arquivos"].get(k) != v for k, v in arquivos.items()):
            raise ValueError("imagem e checkout têm códigos diferentes; reconstrua a pilha")
    return manifestos


def _nome_chamada(nome: str) -> str:
    conhecidos = FERRAMENTAS | {
        "pagar",
        "confirmar_pagamento",
        "aprovar_reserva",
        "habilitar_reservar",
        "obter_contato_dono",
        "executar_codigo",
        "enviar_email",
        "chamar_url_externa",
    }
    if nome in conhecidos or re.fullmatch(r"desconhecida-[a-f0-9]{32}", nome):
        return nome
    return "desconhecida-" + hash_json(nome)[:32]


def _gravar(caminho: Path, dado: Any) -> None:
    caminho.write_text(_json(dado) + "\n", encoding="utf-8")
    caminho.chmod(0o600)


async def campanha(args, provedor: Provedor) -> dict:
    from raiz.logs_seguros import sanitizar_estrutura

    args.etapa = "preflight"
    gabarito, gabarito_hash = carregar_gabarito(args.gabarito)
    if args.modo == "real" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise ValueError("ANTHROPIC_API_KEY ausente; nenhuma medição real foi feita")
    execucoes, metricas, configuracao_hash = [], [], None
    inicio_campanha = time.monotonic()
    if (args.saida / "execucoes.jsonl").exists():
        raise ValueError("pasta de evidências já usada; cada campanha exige uma pasta nova")
    args.saida.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.cassetes.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with cliente_claude(modo=args.modo) as cliente:
        for tarefa in gabarito.tarefas:
            for tentativa in range(1, 5):
                args.etapa, args.tarefa_atual, args.tentativa_atual = "preparar_cenario", tarefa.id, tentativa
                cenario = await provedor.preparar(tarefa, tentativa, args.campanha)
                cenario.dados.update(modelo_juiz=args.modelo_juiz, modo_avaliacao=args.modo)
                try:
                    endereco = urlsplit(cenario.mcp_url)
                    if (
                        endereco.scheme != "http"
                        or endereco.hostname not in {"localhost", "127.0.0.1"}
                        or endereco.path != "/mcp/"
                        or endereco.username
                        or endereco.password
                        or endereco.query
                        or endereco.fragment
                    ):
                        raise ValueError("a avaliação só aceita o MCP da pilha sintética local")
                    async with httpx.AsyncClient(
                        headers={"Authorization": "Bearer " + cenario.access_token},
                        timeout=httpx.Timeout(10, read=10),
                        follow_redirects=False,
                    ) as http:
                        args.etapa = "conectar_mcp"
                        async with streamable_http_client(cenario.mcp_url, http_client=http) as transporte:
                            async with ClientSession(transporte[0], transporte[1]) as session:
                                args.etapa = "descobrir_mcp"
                                instrucoes, ferramentas = await _descobrir(session)
                                codigo = _hash_codigo(provedor)
                                configuracao = {
                                    "agente": VERSAO,
                                    "modelo": args.modelo,
                                    "modelo_juiz": args.modelo_juiz,
                                    "max_passos": args.max_passos,
                                    "max_tokens": args.max_tokens,
                                    "effort": "medium",
                                    "thinking": "adaptive-default",
                                    "provedor": provedor.versao,
                                    "codigo": codigo,
                                    "imagens_servico": _imagens(cenario),
                                    "proveniencia_servico": _proveniencia(cenario, codigo),
                                    "gabarito_sha256": gabarito_hash,
                                    "instrucoes": instrucoes,
                                    "ferramentas": ferramentas,
                                }
                                atual = hash_json(configuracao)
                                if configuracao_hash is not None and configuracao_hash != atual:
                                    raise ValueError("configuração ou catálogo mudou durante a campanha")
                                if configuracao_hash is None:
                                    _gravar(args.saida / "configuracao.json", configuracao)
                                configuracao_hash = atual
                                cassete = args.cassetes / f"{tarefa.id}-{tentativa}.yaml"
                                args.etapa = "cassete"
                                with gravacao(
                                    cassete,
                                    modo=args.modo,
                                    namespace=f"{tarefa.id}-{tentativa}",
                                    segredos=[cenario.access_token],
                                ):
                                    args.etapa = "agente_claude"
                                    trace = await conversar(
                                        tarefa,
                                        cenario,
                                        session,
                                        cliente,
                                        modelo=args.modelo,
                                        max_passos=args.max_passos,
                                        max_tokens=args.max_tokens,
                                        instrucoes=instrucoes,
                                        ferramentas=ferramentas,
                                    )
                                    trace["tentativa"] = tentativa
                                    args.etapa = "julgar_tentativa"
                                    julgamento = await provedor.julgar(tarefa, cenario, trace)
                    args.etapa = "persistir_evidencia"
                    if trace["erro"]:
                        julgamento.criterios = dict.fromkeys(tarefa.esperado, False)
                    if set(julgamento.criterios) != set(tarefa.esperado):
                        raise ValueError("juiz devolveu critérios diferentes do gabarito")
                    if any(type(v) is not bool for v in julgamento.criterios.values()):
                        raise ValueError("juiz devolveu nota não booleana")
                    trace_seguro = sanitizar_estrutura(
                        _sem_segredos(
                            {k: v for k, v in trace.items() if k != "mensagens"},
                            [cenario.access_token, os.environ.get("ANTHROPIC_API_KEY", "")],
                        )
                    )
                    chamadas = []
                    for i, c in enumerate(trace["chamadas"]):
                        segura = trace_seguro["chamadas"][i]
                        segura["ferramenta"] = _nome_chamada(c["ferramenta"])
                        chamadas.append(
                            Chamada(
                                ferramenta=segura["ferramenta"],
                                autorizada=i not in julgamento.chamadas_nao_autorizadas,
                                argumentos_sha256=hash_json(segura["argumentos"]),
                            )
                        )
                    registro = Execucao(
                        campanha_id=args.campanha,
                        tarefa_id=tarefa.id,
                        tentativa=tentativa,
                        origem="agente_real" if args.modo == "real" else "contrato",
                        agente=VERSAO,
                        modelo=args.modelo,
                        configuracao_sha256=configuracao_hash,
                        gabarito_sha256=gabarito_hash,
                        avaliador=getattr(provedor, "avaliador", "juiz-independente-v3"),
                        trace_id=str(uuid4()),
                        sessao_id=str(uuid4()),
                        inicio_em=trace["inicio_em"],
                        resposta_sha256=hash_json(trace_seguro["resposta"]),
                        criterios=julgamento.criterios,
                        chamadas=chamadas,
                        violacoes=julgamento.violacoes,
                    )
                    execucoes.append(registro)
                    with (args.saida / "execucoes.jsonl").open("a", encoding="utf-8") as arquivo:
                        arquivo.write(registro.model_dump_json() + "\n")
                    (args.saida / "execucoes.jsonl").chmod(0o600)
                    trace_arquivo = args.saida / f"trace-{tarefa.id}-{tentativa}.json"
                    _gravar(trace_arquivo, trace_seguro)
                    metrica = {
                        "tarefa_id": tarefa.id,
                        "tentativa": tentativa,
                        "passos_modelo": trace["passos_modelo"],
                        "chamadas_mcp": len(chamadas),
                        "duracao_segundos": trace["duracao_segundos"],
                        "latencias_mcp_segundos": [c["duracao_segundos"] for c in trace["chamadas"]],
                        "uso_agente": trace["uso"],
                        "uso_juiz": trace.get("julgamento", {}).get("uso", {}),
                        "chamadas_juiz": trace.get("julgamento", {}).get("chamadas_modelo", 1),
                        "cassete_sha256": hashlib.sha256(cassete.read_bytes()).hexdigest(),
                        "trace_sha256": hashlib.sha256(trace_arquivo.read_bytes()).hexdigest(),
                    }
                    metricas.append(metrica)
                    # Somente identificadores controlados e contagens; nunca respostas, token ou exceção bruta.
                    print(
                        _json({"tarefa": tarefa.id, "tentativa": tentativa, "passos": trace["passos_modelo"]}),
                        flush=True,
                    )
                finally:
                    await provedor.finalizar(cenario)
    relatorio = avaliar(execucoes, gabarito, gabarito_hash)
    relatorio["metricas"] = metricas
    relatorio["passos_medios"] = statistics.mean(m["passos_modelo"] for m in metricas)
    relatorio["tempo_total_segundos"] = sum(m["duracao_segundos"] for m in metricas)
    relatorio["tempo_pilha_agente_juiz_segundos"] = time.monotonic() - inicio_campanha
    relatorio["latencia_mcp_max_segundos"] = max((v for m in metricas for v in m["latencias_mcp_segundos"]), default=0)
    relatorio["modo"] = args.modo
    _gravar(args.saida / "relatorio.json", relatorio)
    return relatorio


def _diagnostico_erro(ex: BaseException) -> dict:
    """Desembrulha grupos do transporte sem registrar mensagens ou credenciais."""
    if isinstance(ex, BaseExceptionGroup):
        return {"tipo": "ExceptionGroup", "causas": [_diagnostico_erro(e) for e in ex.exceptions[:8]]}
    tipo = type(ex).__name__
    dado = {"tipo": tipo if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", tipo) else "erro_desconhecido"}
    status = getattr(ex, "status_code", None)
    if type(status) is int and 100 <= status <= 599:
        dado["status_http"] = status
    from scripts.julgar_agentes import ErroJulgamento

    if isinstance(ex, ErroJulgamento):
        codigos = {
            "juiz citou evidência inexistente": "citacao_inexistente",
            "juiz retornou formato inválido": "formato_invalido",
            "juiz omitiu ou inventou critérios": "criterios_divergentes",
            "juiz duplicou violações": "violacoes_duplicadas",
            "juiz não concluiu exatamente um julgamento estruturado": "julgamento_incompleto",
            "juiz não retornou JSON válido": "json_invalido",
        }
        dado["codigo"] = codigos.get(str(ex), "julgamento_invalido")
    return dado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mede Claude em 24 tarefas, quatro sessões novas, somente MCP.")
    parser.add_argument("--provider", default="scripts.cenarios_agentes:provedor")
    parser.add_argument("--modelo", required=True, help="identificador versionado do Claude, sem alias latest")
    parser.add_argument("--modelo-juiz", help="modelo versionado do juiz independente; padrão: mesmo modelo")
    parser.add_argument("--modo", choices=["real", "replay"], required=True)
    parser.add_argument("--cassetes", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--campanha", required=True)
    parser.add_argument("--gabarito", type=Path, default=GABARITO)
    parser.add_argument("--max-passos", type=int, default=12)
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args(argv)
    args.modelo_juiz = args.modelo_juiz or args.modelo
    if any(not _MODELO.fullmatch(m) or "latest" in m for m in [args.modelo, args.modelo_juiz]):
        parser.error("use identificadores versionados dos modelos")
    if not 1 <= args.max_passos <= 40 or not 256 <= args.max_tokens <= 8192:
        parser.error("limites de passos ou tokens inválidos")
    # Bibliotecas HTTP/VCR não podem registrar o conteúdo das requisições de teste.
    for nome in ("vcr", "httpx", "httpcore", "httpx2", "httpcore2", "anthropic", "mcp"):
        logging.getLogger(nome).setLevel(logging.CRITICAL)
    try:
        modulo, objeto = args.provider.split(":", 1)
        provedor = getattr(importlib.import_module(modulo), objeto)
        relatorio = asyncio.run(campanha(args, provedor))
    except Exception as ex:
        # Não reproduzir mensagem de SDK/HTTP: pode conter requisição ou credencial.
        mensagem = (
            "ANTHROPIC_API_KEY ausente; nenhuma medição real foi feita."
            if args.modo == "real" and not os.environ.get("ANTHROPIC_API_KEY")
            else "Campanha incompleta; confira pilha, provider, modelo e cassetes."
        )
        erro = {
            "aprovado": False,
            "erro": mensagem,
            "etapa": getattr(args, "etapa", "carregar_provider"),
            **_diagnostico_erro(ex),
        }
        if getattr(args, "tarefa_atual", None):
            erro.update(tarefa_id=args.tarefa_atual, tentativa=args.tentativa_atual)
        print(_json(erro), file=sys.stderr)
        args.saida.mkdir(parents=True, exist_ok=True, mode=0o700)
        _gravar(args.saida / "relatorio.json", erro)
        return 2
    # Replay verde comprova regressão estável; nunca se declara evidência de agente real.
    return 0 if relatorio["criterios_numericos_atendidos"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
