"""Instrumentação sem credenciais: doubles validam contagem, nunca desempenho de agente."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from mcp_types import CallToolResult, TextContent, Tool

from raiz.publica.avaliacao import FERRAMENTAS, Execucao, carregar_gabarito
from scripts import medir_agentes as m


def resposta(*blocos):
    def bloco(d):
        return SimpleNamespace(**d, model_dump=lambda **_: d)

    return SimpleNamespace(
        content=[bloco(b) for b in blocos],
        usage=SimpleNamespace(input_tokens=30, output_tokens=5),
        id="fixture-resposta",
        _request_id="fixture-requisicao",
    )


class Modelo:
    def __init__(self, *respostas):
        self.respostas = iter(respostas)
        self.messages = self
        self.pedidos = []

    async def create(self, **kwargs):
        self.pedidos.append(kwargs)
        return next(self.respostas)


class MCP:
    def __init__(self):
        self.chamadas = []

    async def list_tools(self):
        return SimpleNamespace(tools=[Tool(name=n, input_schema={"type": "object"}) for n in FERRAMENTAS])

    async def call_tool(self, nome, args, **kwargs):
        self.chamadas.append(nome)
        return CallToolResult(content=[TextContent(type="text", text="recusado")], is_error=True)


def test_registra_tentativa_proibida_mesmo_quando_servidor_recusa():
    tarefa = carregar_gabarito()[0].tarefas[0]
    modelo = Modelo(
        resposta({"type": "tool_use", "id": "uso", "name": "preparar_reserva", "input": {}}),
        resposta({"type": "text", "text": "Não autorizado"}),
    )
    medidas = m.Medidas(tarefa.id, 1)
    transporte = MCP()
    retorno = asyncio.run(
        m.conversar(
            modelo,
            "modelo-exato",
            transporte,
            SimpleNamespace(contexto={}),
            tarefa,
            m.Limites(),
            medidas,
            m.Consumo(),
            (),
        )
    )
    assert transporte.chamadas == ["preparar_reserva"]
    assert medidas.chamadas_proibidas == 1 and medidas.passos == 2
    assert retorno[1][0]["autorizada"] is False
    assert medidas.tentadas == retorno[1]


def test_ferramenta_inventada_nao_executa_codigo_ou_navega():
    tarefa = carregar_gabarito()[0].tarefas[0]
    modelo = Modelo(
        resposta({"type": "tool_use", "id": "uso", "name": "executar_codigo", "input": {"texto": "privado"}}),
        resposta({"type": "text", "text": "Recuso"}),
    )
    medidas, transporte = m.Medidas(tarefa.id, 1), MCP()
    asyncio.run(
        m.conversar(
            modelo, "exato", transporte, SimpleNamespace(contexto={}), tarefa, m.Limites(), medidas, m.Consumo(), ()
        )
    )
    assert transporte.chamadas == [] and medidas.chamadas_proibidas == 1
    assert "privado" not in json.dumps(medidas.fatos)


def test_limite_de_tokens_impede_chamada_extra_ao_provedor():
    modelo, medida, consumo = Modelo(), m.Medidas("t", 1), m.Consumo(4000000)
    with pytest.raises(m.Interrupcao) as exc:
        asyncio.run(m.gerar(modelo, "exato", [], "", [], m.Limites(), medida, consumo))
    assert exc.value.codigo == "limite_tokens_campanha" and not modelo.pedidos


def test_juiz_nao_aceita_veredito_parcial_ou_texto_livre():
    tarefa = carregar_gabarito()[0].tarefas[0]
    modelo = Modelo(
        resposta(
            {
                "type": "tool_use",
                "id": "uso",
                "name": "registrar_julgamento",
                "input": {"criterios": {}, "violacoes": []},
            }
        )
    )
    with pytest.raises(m.Interrupcao, match="julgamento_invalido"):
        asyncio.run(
            m.julgar(modelo, "exato", tarefa, "resposta", [], {}, m.Limites(), m.Medidas(tarefa.id, 1), m.Consumo())
        )
    assert modelo.pedidos[0]["system"] == m.JUIZ


def test_campanha_sem_chave_publica_96_nao_executadas_sem_chamar_pilha(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    args = SimpleNamespace(modelo="exato", juiz="exato", saida=tmp_path, **m.asdict(m.Limites()))
    assert asyncio.run(m.campanha(args)) == 2
    r = json.loads((tmp_path / "relatorio.json").read_text())
    assert r["estado"] == "incompleta" and r["pass4"] is None and not r["aprovado"]
    assert r["tentativas_nao_executadas"] == 96 and r["motivo"] == "segredo_ausente"


def test_relatorio_completo_conta_uma_falha_por_limite_sem_inflar_pass4(tmp_path):
    g, assinatura = carregar_gabarito()
    medidas, execucoes = [], []
    for i, t in enumerate(g.tarefas):
        for n in range(1, 5):
            falhou = i == 0 and n == 1
            medidas.append(m.Medidas(t.id, n, estado="reprovada_por_limite" if falhou else "concluida"))
            execucoes.append(
                Execucao.model_validate(
                    {
                        "campanha_id": "teste",
                        "tarefa_id": t.id,
                        "tentativa": n,
                        "origem": "contrato",
                        "agente": "double",
                        "modelo": "double",
                        "configuracao_sha256": "a" * 64,
                        "gabarito_sha256": assinatura,
                        "avaliador": "contrato",
                        "trace_id": f"{i}-{n}",
                        "sessao_id": f"s-{i}-{n}",
                        "inicio_em": "2026-11-12T12:00:00+00:00",
                        "resposta_sha256": "b" * 64,
                        "criterios": {k: not falhou for k in t.esperado},
                        "chamadas": [
                            {"ferramenta": f, "autorizada": True, "argumentos_sha256": "c" * 64} for f in t.obrigatorias
                        ],
                        "violacoes": [],
                    }
                )
            )
    r = m.publicar(tmp_path, g, assinatura, execucoes, medidas, "a" * 64)
    assert r["estado"] == "concluida" and r["pass4"] == 23 / 24 and not r["aprovado"]
    assert r["origem_declarada"] == "contrato" and r["tentativas_concluidas"] == 96


def test_hash_congela_codigo_infra_e_configuracao():
    assert m.configuracao_hash("modelo-a", "juiz", m.Limites()) != m.configuracao_hash("modelo-b", "juiz", m.Limites())


def test_fixture_recusa_banco_que_nao_e_descartavel():
    from scripts.avaliacao_fixture import FixtureConfig

    with pytest.raises(ValueError):
        with FixtureConfig("postgresql+psycopg://raiz@127.0.0.1:5432/raiz"):
            pytest.fail("Não deve abrir banco")


def test_realm_exige_sub_pkce_e_nao_habilita_password_grant():
    realm = json.loads((m.RAIZ / "infra/keycloak/raiz-realm.json").read_text())
    cliente = next(c for c in realm["clients"] if c["clientId"] == "raiz-agentes")
    assert cliente["attributes"]["pkce.code.challenge.method"] == "S256"
    assert not cliente["directAccessGrantsEnabled"] and not cliente["implicitFlowEnabled"]
    identidade = next(s for s in realm["clientScopes"] if s["name"] == "raiz-identidade")
    assert any(x["protocolMapper"] == "oidc-sub-mapper" for x in identidade["protocolMappers"])


def test_erro_de_provedor_dentro_do_mcp_interrompe_a_campanha():
    causa = m.Interrupcao("provedor_http_401", global_=True)
    grupo = ExceptionGroup("transporte", [ExceptionGroup("cliente", [causa])])
    assert m.interrupcao_conhecida(grupo) is causa
    assert m.interrupcao_conhecida(RuntimeError("não publicar")) is None
