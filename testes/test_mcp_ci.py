"""Aviso restrito à ausência autorizada; falhas nos ensaios continuam obrigatórias."""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import testar_mcp_ci as ci
from testes.mcp import avaliacao, latencia, produto


def test_ausencia_gera_aviso_sem_alegar_ensaio(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ci, "disponivel", lambda: False)
    assert ci.main(["--resultado", str(tmp_path)]) == 0
    assert "::warning" in capsys.readouterr().out
    assert json.loads((tmp_path / "integracao.json").read_text())["ensaios_executados"] is False


def test_implementacao_ou_sdk_nao_podem_ser_tratados_como_ausentes(tmp_path):
    assert ci.disponivel(tmp_path) is False
    p = tmp_path / "raiz/publica/servidor_mcp.py"
    p.parent.mkdir(parents=True)
    p.write_text("raise RuntimeError('servidor quebrado')")
    assert ci.disponivel(tmp_path) is True
    p.unlink()
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["mcp>=2"]')
    assert ci.disponivel(tmp_path) is True


def test_mcp_presente_com_erro_reprova_sem_vazar(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ci, "disponivel", lambda: True)

    def falhar(_):
        raise RuntimeError("contato@exemplo.invalid")

    monkeypatch.setattr(ci, "executar", falhar)
    assert ci.main(["--resultado", str(tmp_path)]) == 1
    saida = capsys.readouterr().out
    assert "::error" in saida and "contato@" not in saida
    assert json.loads((tmp_path / "integracao.json").read_text())["estado"] == "falha"


def test_detecao_presente_nao_executa_nem_aprova(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "disponivel", lambda: True)
    assert ci.main(["--detectar", "--resultado", str(tmp_path)]) == 0
    dado = json.loads((tmp_path / "integracao.json").read_text())
    assert dado["estado"] == "presente" and dado["ensaios_executados"] is False


def test_excecao_de_corpus_antes_dos_ensaios_nao_alega_medicoes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ci, "disponivel", lambda: True)

    def pendente(_):
        raise ci.CorpusPendente

    monkeypatch.setattr(ci, "executar", pendente)
    assert ci.main(["--resultado", str(tmp_path)]) == 1
    assert "::error title=MCP reprovado" in capsys.readouterr().out
    dado = json.loads((tmp_path / "integracao.json").read_text())
    assert dado["estado"] == "falha"
    assert "ensaios_executados" not in dado


@pytest.fixture
def fluxo_controlado(monkeypatch):
    """Dublês só das fronteiras externas; executa o encadeamento real do runner."""
    etapas = []
    estado = SimpleNamespace(defeito=None, leitor=False)

    @contextmanager
    def carga(fase):
        etapas.append(fase)
        yield {}

    @contextmanager
    def integracao():
        etapas.append("oauth")
        if estado.defeito == "oauth":
            raise RuntimeError("diagnostico-privado-sintetico")
        try:
            yield SimpleNamespace(
                cliente=object(),
                casos={"consultar": {"argumentos": {}}},
                inventario=json.loads(produto.REFERENCIA_SEM_LEITOR.read_text())["ferramentas"],
                carga=carga,
                ambiente=object() if estado.leitor else produto.SemAgenteLeitor(),
                # Uma flag antiga esquecida não pode impedir o corpus do leitor.
                injecoes_disponiveis=False,
            )
        finally:
            if estado.defeito == "finalizacao":
                raise RuntimeError("diagnostico-privado-sintetico")

    def medir(*_):
        etapas.append("latencia")
        if estado.defeito == "latencia":
            raise RuntimeError("diagnostico-privado-sintetico")
        return {"medicoes": [{"ferramenta": "consultar", "segundos": 0.1}]}

    def locust(*_, env, **kwargs):
        assert "ANTHROPIC_API_KEY" not in env
        fase = env["RAIZ_CARGA_FASE"]
        dado = {
            "fase": fase,
            "requisicoes": 30,
            "falhas": 0,
            "max_ms": 100,
            "limitadas": 10 if fase == "limite" else 0,
            "retry_after_invalidos": 1 if estado.defeito == "retry_after" and fase == "limite" else 0,
            "sucessos": {"consultar": 20},
        }
        Path(env["RAIZ_CARGA_RELATORIO"]).write_text(json.dumps(dado))
        return SimpleNamespace(returncode=1 if estado.defeito == fase else 0)

    async def corpus(_):
        etapas.append("corpus")
        if estado.defeito == "corpus":
            raise avaliacao.FalhaAvaliacao("diagnostico-privado-sintetico")
        return {"integracao_mcp": True, "resultados": []}

    monkeypatch.setattr(ci, "disponivel", lambda: True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "credencial-sintetica-do-modelo")
    monkeypatch.setattr(produto, "integracao", integracao)
    # Este cenário reproduz a ausência histórica; a main com leitor tem teste próprio.
    referencia = json.loads(produto.REFERENCIA_SEM_LEITOR.read_text())
    monkeypatch.setattr(produto, "_modulos_leitor", lambda: (False, False))
    monkeypatch.setattr(produto, "_codigo_mcp", lambda _: referencia["codigo"])
    monkeypatch.setattr(latencia, "medir_latencia", medir)
    monkeypatch.setattr(ci.subprocess, "run", locust)
    monkeypatch.setattr(avaliacao, "avaliar_injecoes", corpus)
    return estado, etapas


def test_aviso_so_apos_latencia_e_ambas_cargas_aprovadas(tmp_path, monkeypatch, capsys, fluxo_controlado):
    _, etapas = fluxo_controlado
    resumo = tmp_path / "resumo.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(resumo))

    assert ci.main(["--resultado", str(tmp_path)]) == 0

    assert etapas == ["oauth", "latencia", "normal", "limite"]
    assert "::warning title=Corpus MCP pendente" in capsys.readouterr().out
    dado = json.loads((tmp_path / "integracao.json").read_text())
    assert dado["estado"] == "parcial"
    assert dado["ensaios_executados"] == {"latencia": True, "carga": True, "corpus": False}
    assert "corpus não aprovado" in resumo.read_text()
    for nome in ("latencia.json", "carga-normal.json", "carga-limite.json"):
        assert (tmp_path / nome).is_file()


@pytest.mark.parametrize("defeito", ["oauth", "latencia", "normal", "limite", "retry_after", "finalizacao", "corpus"])
def test_aviso_nao_encobre_falha_obrigatoria(tmp_path, capsys, fluxo_controlado, defeito):
    estado, etapas = fluxo_controlado
    estado.defeito = defeito
    estado.leitor = defeito == "corpus"

    assert ci.main(["--resultado", str(tmp_path)]) == 1

    saida = capsys.readouterr().out
    assert "::error title=MCP reprovado" in saida
    assert "::warning" not in saida and "diagnostico-privado-sintetico" not in saida
    dado = json.loads((tmp_path / "integracao.json").read_text())
    assert dado["estado"] == "falha"
    assert "ensaios_executados" not in dado
    assert (
        dado["etapa"]
        == {
            "oauth": "integracao",
            "latencia": "latencia",
            "normal": "carga_normal",
            "limite": "carga_limite",
            "retry_after": "carga_limite",
            "finalizacao": "integracao",
            "corpus": "corpus",
        }[defeito]
    )
    if defeito == "corpus":
        assert etapas == ["oauth", "latencia", "normal", "limite", "corpus"]


def test_leitor_integrado_executa_corpus_sem_aviso(tmp_path, capsys, fluxo_controlado):
    estado, etapas = fluxo_controlado
    estado.leitor = True

    assert ci.main(["--resultado", str(tmp_path)]) == 0

    assert etapas == ["oauth", "latencia", "normal", "limite", "corpus"]
    assert "::warning" not in capsys.readouterr().out
    assert json.loads((tmp_path / "integracao.json").read_text())["estado"] == "aprovado"


def test_diagnostico_corpus_so_publica_codigos_fechados(tmp_path, monkeypatch, capsys):
    from testes.mcp.avaliacao import FalhaAvaliacao

    def falhar(_):
        with ci._etapa("corpus"):
            raise FalhaAvaliacao(
                "conteudo-privado-que-nao-pode-sair",
                caso="certidao-autoridade",
                variante="controle",
                motivo="utilidade",
                criterios=("resposta_fora_do_gabarito", "conteudo-privado"),
                tipo="classe-com-conteudo-privado",
            )

    monkeypatch.setattr(ci, "disponivel", lambda: True)
    monkeypatch.setattr(ci, "executar", falhar)
    assert ci.main(["--resultado", str(tmp_path)]) == 1
    texto = (tmp_path / "integracao.json").read_text() + capsys.readouterr().out
    assert "conteudo-privado" not in texto
    d = json.loads((tmp_path / "integracao.json").read_text())["diagnostico"]
    assert d == {
        "caso": "certidao-autoridade",
        "variante": "controle",
        "motivo": "utilidade",
        "criterios": ["resposta_fora_do_gabarito"],
        "tipo": "desconhecido",
    }


def test_catalogo_do_auditor_cobre_todas_as_ferramentas_registradas():
    from raiz.publica.avaliacao import FERRAMENTAS
    from raiz.publica.servidor_mcp import ESCOPOS_FERRAMENTAS

    assert FERRAMENTAS == set(ESCOPOS_FERRAMENTAS)
