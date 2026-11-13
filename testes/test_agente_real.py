"""O replay confere os pedidos completos e nunca se disfarça de medição real."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx2 as httpx
import pytest
from anthropic import APIConnectionError
from mcp.types import ListToolsResult, Tool

from raiz.publica import agente_real as A
from raiz.publica.avaliacao import carregar_gabarito


def _resposta(conteudo, parada="end_turn"):
    return {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": conteudo,
        "stop_reason": parada,
        "stop_sequence": None,
        "usage": {"input_tokens": 20, "output_tokens": 10},
    }


def test_alias_reidrata_id_e_link_sem_guardar_token_na_cassete():
    mapa = A.MapaCassete("sessao")
    pedido = str(uuid4())
    url = "http://localhost:18000/v1/reservas/confirmar/" + "segredo-sintetico-" * 3
    normalizado = mapa.normalizar({"pedido_id": pedido, "link": url})
    assert pedido not in json.dumps(normalizado) and "segredo-sintetico" not in json.dumps(normalizado)
    assert json.loads(mapa.restaurar(json.dumps(normalizado))) == {"pedido_id": pedido, "link": url}
    with pytest.raises(ValueError, match="sem origem"):
        A.MapaCassete("outra").restaurar(normalizado["link"])


def test_alias_de_prazo_preserva_validade_e_duracao_com_resolucao_de_minuto():
    agora = datetime.now(UTC)
    casos = [agora + timedelta(days=2), agora + timedelta(days=1), agora - timedelta(days=2)]
    aliases = [A.MapaCassete("sessao").normalizar({"preco_valido_ate": d.isoformat()}) for d in casos]
    assert len({A.hash_json(a) for a in aliases}) == 3
    assert "FUTURO_2880M" in aliases[0]["preco_valido_ate"]
    assert "VENCIDO" in aliases[2]["preco_valido_ate"]
    # Data do calendário/política não é metadado operacional nem vencimento relativo.
    assert (
        A.MapaCassete("sessao").normalizar({"data_evento": casos[0].isoformat()})["data_evento"] == casos[0].isoformat()
    )


def test_replay_ausente_nao_permite_rede(tmp_path):
    with pytest.raises(ValueError, match="cassete real ausente"):
        with A.gravacao(tmp_path / "ausente.yaml", modo="replay", namespace="tarefa"):
            pytest.fail("não deve iniciar a chamada")


def test_vcr_httpx_grava_claude_e_reidrata_sem_segredo_raciocinio_ou_prompt(tmp_path, monkeypatch):
    # Transporte HTTP falso só neste teste; VCR captura o limite HTTP real do SDK.
    # O runner de campanha não injeta este transporte nem substitui ferramentas.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-sintetica-nao-publicavel")
    antigo, atual = str(uuid4()), str(uuid4())
    token_antigo, token_atual = "token-antigo-" * 3, "token-atual-" * 3
    contador = []

    async def transporte(self, request):
        corpo = json.loads(request.content)
        contador.append(corpo)
        if len(contador) == 1:
            dados = _resposta(
                [
                    {
                        "type": "thinking",
                        "thinking": "raciocinio privado nunca publicado",
                        "signature": "assinatura-privada",
                    },
                    {"type": "text", "text": "Link http://localhost/v1/reservas/confirmar/" + token_antigo},
                    {
                        "type": "tool_use",
                        "id": "toolu_fixture",
                        "name": "acompanhar_contato",
                        "input": {"pedido_id": antigo},
                    },
                ],
                "tool_use",
            )
        else:
            dados = _resposta([{"type": "text", "text": "O pedido aguarda processamento."}])
        return httpx.Response(200, json=dados, request=request)

    import vcr.patch

    monkeypatch.setattr(vcr.patch, "_Httpx2AsyncHttpTransport_handle_async_request", transporte)

    async def duas_chamadas(modo, pedido, token):
        with A.gravacao(tmp_path / "gravacao.yaml", modo=modo, namespace="tarefa-1"):
            async with A.cliente_claude(modo=modo) as cliente:
                mensagens = [
                    {
                        "role": "user",
                        "content": "pedido " + pedido + " link http://localhost/v1/reservas/confirmar/" + token,
                    }
                ]
                r = await cliente.messages.create(model="claude-sonnet-5-5", max_tokens=512, messages=mensagens)
                assert r.content[2].input["pedido_id"] == pedido
                assert token in r.content[1].text
                mensagens.append({"role": "assistant", "content": [c.model_dump(exclude_none=True) for c in r.content]})
                mensagens.append(
                    {
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": "toolu_fixture", "content": "working"}],
                    }
                )
                await cliente.messages.create(model="claude-sonnet-5-5", max_tokens=512, messages=mensagens)

    asyncio.run(duas_chamadas("real", antigo, token_antigo))
    bruto = (tmp_path / "gravacao.yaml").read_text()
    for segredo in ("chave-sintetica-nao-publicavel", antigo, token_antigo, "raciocinio privado", "assinatura-privada"):
        assert segredo not in bruto
    assert "__RAIZ_THINKING_SHA256_" in bruto and "raiz_requisicao_sha256" in bruto
    asyncio.run(duas_chamadas("replay", atual, token_atual))
    assert len(contador) == 2
    assert not (tmp_path / "gravacao.yaml").stat().st_mode & 0o077


def test_replay_rejeita_mudanca_numerica_sem_fazer_chamada_real(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-sintetica")
    chamadas = []

    async def transporte(self, request):
        chamadas.append(request)
        return httpx.Response(200, json=_resposta([{"type": "text", "text": "Estimativa recebida."}]), request=request)

    import vcr.patch

    monkeypatch.setattr(vcr.patch, "_Httpx2AsyncHttpTransport_handle_async_request", transporte)

    async def chamar(modo, total):
        with A.gravacao(tmp_path / "n.yaml", modo=modo, namespace="tarefa-1"):
            async with A.cliente_claude(modo=modo) as c:
                await c.messages.create(
                    model="claude-sonnet-5-5",
                    max_tokens=256,
                    messages=[{"role": "user", "content": f"Oferta: {total}"}],
                )

    asyncio.run(chamar("real", 600000))
    with pytest.raises(APIConnectionError):
        asyncio.run(chamar("replay", 1000000))
    assert len(chamadas) == 1


def test_loop_nao_entrega_gabarito_registra_desconhecida_e_preserva_dialogo_real():
    tarefa = carregar_gabarito()[0].tarefas[0]
    vistos = []

    class Cliente:
        def __init__(self):
            self.messages = self

        async def create(self, **dados):
            vistos.append(json.loads(json.dumps(dados)))
            from anthropic.types import Message

            if len(vistos) == 1:
                return Message.model_validate(
                    _resposta(
                        [
                            {
                                "type": "thinking",
                                "thinking": "cadeia somente em memoria",
                                "signature": "assinatura-memoria",
                            },
                            {"type": "tool_use", "id": "toolu_naoexiste", "name": "pagar", "input": {"valor": 1}},
                        ],
                        "tool_use",
                    )
                )
            return Message.model_validate(_resposta([{"type": "text", "text": "É necessária uma pessoa."}]))

    class Sessao:
        async def call_tool(self, *args, **kwargs):
            pytest.fail("ferramenta desconhecida não deve sair pelo transporte")

    cenario = A.Cenario("Empresa autenticada.", "http://localhost/mcp/", "segredo-nao-passa-ao-agente")
    trace = asyncio.run(
        A.conversar(
            tarefa,
            cenario,
            Sessao(),
            Cliente(),
            modelo="claude-sonnet-5-5",
            max_passos=3,
            max_tokens=512,
            instrucoes="Contrato MCP público.",
            ferramentas=[{"name": "consultar_disponibilidade", "input_schema": {"type": "object"}}],
        )
    )
    assert trace["passos_modelo"] == 2 and trace["chamadas"][0]["ferramenta"] == "pagar"
    assert trace["chamadas"][0]["is_error"]
    primeiro = json.dumps(vistos[0])
    assert "esperado" not in primeiro and "obrigatorias" not in primeiro
    assert "segredo-nao-passa" not in primeiro and "temperature" not in vistos[0]
    assert vistos[0]["output_config"] == {"effort": "medium"}
    assert "cadeia somente em memoria" in json.dumps(vistos[1])
    assert "cadeia somente em memoria" not in json.dumps(trace)


def test_descoberta_com_nomes_reais_do_sdk_e_paginacao():
    class Sessao:
        async def initialize(self):
            return SimpleNamespace(instructions="Contrato")

        async def list_tools(self, params=None):
            if params is None:
                return ListToolsResult(
                    tools=[Tool(name="consultar", input_schema={"type": "object"})], next_cursor="pagina2"
                )
            assert params.cursor == "pagina2"
            return ListToolsResult(tools=[Tool(name="cancelar", input_schema={"type": "object"})])

    instrucoes, ferramentas = asyncio.run(A._descobrir(Sessao()))
    assert instrucoes == "Contrato" and [f["name"] for f in ferramentas] == ["consultar", "cancelar"]


def test_imagens_exigem_stack_real_imutavel_sem_montagem_de_fontes():
    imagens = {k: "sha256:" + "a" * 64 for k in ("api", "worker", "banco", "keycloak")}
    cenario = A.Cenario("Sintético", "http://localhost:18000/mcp/", "token", {"imagens_servico": imagens})
    with pytest.raises(ValueError, match="sem fontes"):
        A._imagens(cenario)
    cenario.dados["fontes_montadas"] = False
    assert A._imagens(cenario) == imagens
    cenario.dados["imagens_servico"] = {"api": imagens["api"]}
    with pytest.raises(ValueError, match="quatro serviços"):
        A._imagens(cenario)


def test_chave_ausente_falha_explicitamente_sem_inventar_resultado(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    codigo = A.main(
        [
            "--provider",
            "modulo_inexistente:provedor",
            "--modelo",
            "claude-sonnet-5-5",
            "--modo",
            "real",
            "--campanha",
            "sem-chave",
            "--cassetes",
            str(tmp_path / "cassetes"),
            "--saida",
            str(tmp_path / "evidencias"),
        ]
    )
    assert codigo == 2 and "ANTHROPIC_API_KEY ausente" in capsys.readouterr().err
    relatorio = json.loads((tmp_path / "evidencias/relatorio.json").read_text())
    assert relatorio["aprovado"] is False and "pass4" not in relatorio
    assert not (tmp_path / "cassetes").exists()


def test_replay_preserva_ritmo_da_inferencia_sem_bloquear_event_loop(monkeypatch):
    esperas = []

    async def esperar(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(A.asyncio, "sleep", esperar)
    resposta = httpx.Response(
        200,
        json={"content": []},
        headers={"x-raiz-inferencia-segundos": "3.25"},
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    token = A._mapa_atual.set(A.MapaCassete("ritmo"))
    try:
        asyncio.run(A._restaurar_resposta(resposta))
    finally:
        A._mapa_atual.reset(token)
    assert esperas == [3.25]


def test_proveniencia_rejeita_imagem_diferente_do_checkout():
    caminhos = [
        "raiz/api.py",
        "raiz/publica/servidor_mcp.py",
        "raiz/publica/trabalhos.py",
        "uv.lock",
        "pyproject.toml",
        "alembic.ini",
    ]
    arquivos = dict.fromkeys(caminhos, "a" * 64)
    manifesto = {"versao": 1, "arquivos": arquivos}
    cenario = A.Cenario(
        "", "http://localhost/mcp/", "token", {"proveniencia_servico": {"api": manifesto, "worker": manifesto}}
    )
    assert A._proveniencia(cenario, {"arquivos": arquivos})
    alterados = {**arquivos, "raiz/api.py": "b" * 64}
    with pytest.raises(ValueError, match="códigos diferentes"):
        A._proveniencia(cenario, {"arquivos": alterados})


def test_upload_recusa_credenciais_raciocinio_e_arquivos_extras(tmp_path):
    from scripts.verificar_evidencias_agentes import verificar

    saida, cassetes = tmp_path / "saida", tmp_path / "cassetes"
    saida.mkdir()
    A._gravar(saida / "relatorio.json", {"aprovado": False})
    assert verificar(saida, cassetes) == 1
    A._gravar(saida / "trace-disponibilidade_pa-1.json", {"resposta": "segredo-conhecido"})
    with pytest.raises(ValueError, match="credencial"):
        verificar(saida, cassetes, chave_api="segredo-conhecido")
    A._gravar(saida / "trace-disponibilidade_pa-1.json", {"type": "thinking", "thinking": "privado"})
    with pytest.raises(ValueError, match="raciocínio"):
        verificar(saida, cassetes)
    (saida / "trace-disponibilidade_pa-1.json").unlink()
    (saida / ".env").write_text("ENV=teste")
    with pytest.raises(ValueError, match="fora da lista"):
        verificar(saida, cassetes)


def test_modelo_divergente_nao_se_torna_medicao_do_modelo_solicitado():
    class Cliente:
        def __init__(self):
            self.messages = self

        async def create(self, **kwargs):
            return SimpleNamespace(model="outro-modelo")

    tarefa = carregar_gabarito()[0].tarefas[0]
    with pytest.raises(ValueError, match="outro modelo"):
        asyncio.run(
            A.conversar(
                tarefa,
                A.Cenario("contexto", "http://localhost/mcp/", "token"),
                object(),
                Cliente(),
                modelo="claude-sonnet-5-5",
                max_passos=2,
                max_tokens=512,
                instrucoes="Contrato",
                ferramentas=[],
            )
        )
