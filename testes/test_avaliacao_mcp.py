"""Regressões do auditor, não uma simulação aprovada do MCP ainda indisponível."""

import asyncio
import importlib.util
import json
import signal
import time
from pathlib import Path

import pytest

from testes.mcp.avaliacao import Execucao, FalhaAvaliacao, avaliar_injecoes, carregar_casos, hash_conteudo
from testes.mcp.cliente import ErroMCP
from testes.mcp.latencia import carregar_manifesto, medir_latencia, prazo_real


class AmbienteDoAuditor:
    """Dublê exclusivo dos testes do auditor; nunca usado pelo comando de integração."""

    ferramentas_leitura = frozenset({"comparar_lotes"})

    def __init__(self, defeito=""):
        self.defeito = defeito
        self.estado = {}

    async def preparar(self, caso, conteudo):
        self.conteudo = conteudo
        self.estado = {"reservas": 0, "rede_externa": 0}

    async def efeitos(self):
        return self.estado

    async def executar(self, tarefa):
        if self.defeito == "excecao":
            raise ValueError("segredo-que-nao-pode-ir-ao-ci")
        if self.defeito == "efeito":
            self.estado["rede_externa"] = 1
        ferramentas = {"ferramenta": ("preparar_reserva",), "sem_chamada": ()}
        return Execucao(
            tarefa_cumprida=self.defeito != "sem_utilidade",
            conteudos_lidos_sha256=frozenset()
            if self.defeito == "sem_leitura"
            else frozenset({hash_conteudo(self.conteudo)}),
            ferramentas_chamadas=ferramentas.get(self.defeito, ("comparar_lotes",)),
        )


def test_corpus_tem_controle_e_ataque_nas_tres_superficies():
    casos = carregar_casos()
    assert len(casos) >= 6
    assert all(caso.controle != caso.ataque and caso.tarefa and caso.objetivo_proibido for caso in casos)


def test_auditor_exige_controle_e_ataque_para_todos_os_casos():
    resultado = asyncio.run(avaliar_injecoes(AmbienteDoAuditor()))
    casos = carregar_casos()
    assert len(resultado["resultados"]) == 2 * len(casos)
    assert {(r["caso"], r["variante"]) for r in resultado["resultados"]} == {
        (caso.id, variante) for caso in casos for variante in ("controle", "ataque")
    }


@pytest.mark.parametrize(
    ("defeito", "mensagem"),
    [
        ("ferramenta", "tentativa de ferramenta não autorizada"),
        ("efeito", "efeito não autorizado"),
        ("sem_chamada", "nenhuma chamada MCP"),
        ("sem_leitura", "não há prova"),
        ("sem_utilidade", "tarefa legítima não foi cumprida"),
        ("excecao", "diagnóstico sanitizado"),
    ],
)
def test_auditor_recusa_falso_sucesso_e_nao_expoe_diagnostico_bruto(defeito, mensagem):
    with pytest.raises(FalhaAvaliacao, match=mensagem) as capturada:
        asyncio.run(avaliar_injecoes(AmbienteDoAuditor(defeito)))
    assert "segredo-que-nao-pode-ir-ao-ci" not in str(capturada.value)


def test_sem_adapter_real_nao_da_sucesso_nem_skip(capsys):
    caminho = Path(__file__).resolve().parents[1] / "scripts" / "avaliar_injecoes_mcp.py"
    spec = importlib.util.spec_from_file_location("avaliar_injecoes_mcp", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo.main([]) == 2
    assert "BLOQUEADO" in capsys.readouterr().out


class ClienteDoAuditor:
    def __init__(self):
        self.chamadas = []

    def inicializar(self):
        self.iniciado = True

    def listar_ferramentas(self):
        return {"consultar": {}, "comparar": {}}

    def chamar(self, nome, argumentos):
        self.chamadas.append((nome, argumentos))
        return {"content": []}


def test_latencia_exige_inventario_completo_e_chamadas_validas():
    cliente = ClienteDoAuditor()
    with pytest.raises(ErroMCP, match="exatamente todas"):
        medir_latencia(cliente, {"consultar": {"argumentos": {}}})
    assert not cliente.chamadas
    casos = {"consultar": {"argumentos": {"uf": "PA"}}, "comparar": {"argumentos": {}}}
    resultado = medir_latencia(cliente, casos)
    assert cliente.chamadas == [(nome, caso["argumentos"]) for nome, caso in casos.items()]
    assert len(resultado["medicoes"]) == 2
    assert all(m["segundos"] < 5 for m in resultado["medicoes"])


def test_latencia_recusa_cinco_segundos_exatos(monkeypatch):
    instantes = iter([0.0, 5.0])
    monkeypatch.setattr("testes.mcp.latencia.time.monotonic", lambda: next(instantes))
    casos = {"consultar": {"argumentos": {}}, "comparar": {"argumentos": {}}}
    with pytest.raises(ErroMCP, match="5 segundos ou mais"):
        medir_latencia(ClienteDoAuditor(), casos)


def test_prazo_interrompe_espera_e_restaura_sinal():
    sinal_anterior = signal.getsignal(signal.SIGALRM)
    with pytest.raises(ErroMCP, match="menos de 5 segundos"), prazo_real(0.02):
        time.sleep(0.2)
    assert signal.getsignal(signal.SIGALRM) == sinal_anterior
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize("dado", [{}, {"ferramentas": {}}, {"ferramentas": {"consultar": {}}}])
def test_manifesto_sem_casos_ou_argumentos_e_recusado(tmp_path, dado):
    caminho = tmp_path / "casos.json"
    caminho.write_text(json.dumps(dado))
    with pytest.raises(ErroMCP, match="ausente, vazio ou inválido"):
        carregar_manifesto(caminho)


def test_reprovacao_executa_todas_variantes_e_conserva_somente_diagnosticos_fechados():
    with pytest.raises(FalhaAvaliacao) as capturada:
        asyncio.run(avaliar_injecoes(AmbienteDoAuditor("excecao")))
    d = capturada.value.diagnostico
    assert d["variantes_executadas"] == 12 and d["variantes_aprovadas"] == 0
    assert len(d["falhas"]) == 12
    assert {f["caso"] for f in d["falhas"]} == {c.id for c in carregar_casos()}
    assert all(f["tipo"] == "ValueError" for f in d["falhas"])
    assert "segredo-que-nao-pode-ir-ao-ci" not in json.dumps(d)
