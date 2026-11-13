"""Falha de transporte não encerra cálculo nem transforma erro em município pronto."""

import datetime as dt
import json
import sys
import time
import types
from pathlib import Path

import pytest
import yaml

from raiz.executor import processamento as P
from raiz.executor.armazem import ArmazemLocal, ler_json
from raiz.executor.executor import Executor, Tarefa


class PublicacaoFalha(ArmazemLocal):
    token = "token-sintetico"

    def __init__(self, pasta, *, final_falha=False):
        super().__init__(pasta)
        self.periodicas = self.finais = 0
        self.final_falha = final_falha

    def talvez_publicar(self, uf):
        self.periodicas += 1
        raise ValueError("segredo-sintetico que não pode aparecer no log")

    def publicar(self, uf):
        self.finais += 1
        if self.final_falha:
            raise OSError("segredo-sintetico que não pode aparecer no log")


def tarefa(*, falhar=None, versao="t1"):
    def rodar(uf, cod, pasta):
        if cod == falhar:
            raise ValueError("erro sintético de cálculo")
        # Tarefas ainda em curso quando o primeiro resultado dispara publicação.
        time.sleep(0.02)
        (pasta / f"imoveis_{cod}.csv").write_text("coluna\n1\n")

    return Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: versao, rodar)


@pytest.mark.parametrize("lanes", [1, 3])
@pytest.mark.parametrize("final_falha", [False, True])
def test_publicacao_falha_nao_aborta_municipios_e_retomada_nao_refaz(tmp_path, caplog, lanes, final_falha):
    arm = PublicacaoFalha(tmp_path / "arm", final_falha=final_falha)
    ex = Executor(arm, tmp_path / "motor", [tarefa()])
    cods = list(range(1500001, 1500008))
    if final_falha:
        with pytest.raises(RuntimeError, match="publicação pendente"):
            ex.rodar_uf("PA", cods, lanes=lanes)
    else:
        ex.rodar_uf("PA", cods, lanes=lanes)
    estado = ler_json(arm, "estado/PA.json")
    assert estado["feitos"] == estado["rodados"] == len(cods)
    assert estado["processamento"]["municipios"] == {
        "prontos": 7,
        "em_execucao": 0,
        "com_erro": 0,
        "pendentes": 0,
        "desconhecidos": 0,
    }
    assert estado["publicacao"]["pendente"] is final_falha
    assert estado["publicacao"]["falhas"] == (2 if final_falha else 1)
    assert (arm.periodicas, arm.finais) == (1, 1)
    assert all(ex.plano("PA", cod) == [] for cod in cods)
    assert "segredo-sintetico" not in caplog.text
    assert "segredo-sintetico" not in json.dumps(estado)
    arm.final_falha = False
    retomada = Executor(arm, tmp_path / "motor_novo", [tarefa()]).rodar_uf("PA", cods, lanes=lanes)
    assert retomada["rodados"] == 0
    assert retomada["processamento"]["municipios"]["prontos"] == len(cods)


def test_municipio_com_erro_nao_conta_como_pronto(tmp_path):
    arm = ArmazemLocal(tmp_path / "arm")
    ex = Executor(arm, tmp_path / "motor", [tarefa(falhar=1500002)])
    estado = ex.rodar_uf("PA", [1500001, 1500002], lanes=2)
    assert estado["feitos"] == 2  # contador legado, não usado pelo painel novo
    assert estado["processamento"]["municipios"] == {
        "prontos": 1,
        "em_execucao": 0,
        "com_erro": 1,
        "pendentes": 0,
        "desconhecidos": 0,
    }


@pytest.mark.parametrize("dano", ["bytes", "ausente", "versao"])
def test_marca_sem_bytes_integros_recalcula_antes_de_declarar_pronto(tmp_path, dano):
    arm = ArmazemLocal(tmp_path / "arm")
    ex = Executor(arm, tmp_path / "motor", [tarefa()])
    ex.rodar_uf("PA", [1500001])
    chave = "saida/PA/imoveis_1500001.csv"
    if dano == "bytes":
        arm._p(chave).write_text("alterado\n")
    elif dano == "ausente":
        arm._p(chave).unlink()
    else:
        arm.por_bytes(chave, arm.ler(chave), {"versao": "outra"})
    novo = Executor(arm, tmp_path / "motor", [tarefa()])
    assert novo.plano("PA", 1500001) == ["funil"]
    assert not novo._conclusao_comprovada("PA", 1500001)
    estado = novo.rodar_uf("PA", [1500001])
    assert estado["rodados"] == 1
    assert estado["processamento"]["municipios"]["prontos"] == 1
    assert arm.ler(chave) == b"coluna\n1\n"
    assert arm.meta(chave)["versao"] == "t1"
    assert novo.plano("PA", 1500001) == []


def test_falha_do_painel_nao_interrompe_publicacao(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_JOB", "processar")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("UNIDADE", "PA-1")
    chamadas = []

    def publicar(eventos, **kw):
        chamadas.append(eventos)
        raise RuntimeError("segredo-sintetico")

    monkeypatch.setitem(sys.modules, "raiz.executor.status_publico", types.SimpleNamespace(publicar_eventos=publicar))
    ex = Executor(ArmazemLocal(tmp_path / "arm"), tmp_path / "motor", [tarefa()])
    estado = ex.rodar_uf("PA", [1500001])
    assert estado["processamento"]["municipios"]["prontos"] == 1
    assert [x[0]["situacao"] for x in chamadas] == ["pendente", "pronto"]
    assert "segredo-sintetico" not in caplog.text


def test_ultimo_municipio_tem_andamento_enquanto_calcula(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "INTERVALO_S", 0.01)
    arm = ArmazemLocal(tmp_path / "arm")

    def calcular(uf, cod, pasta):
        prazo = time.monotonic() + 3
        while time.monotonic() < prazo:
            estado = ler_json(arm, "estado/PA.json")
            if estado["processamento"]["municipios"]["em_execucao"] == 1:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("andamento não foi observado enquanto o município calculava")
        (pasta / f"imoveis_{cod}.csv").write_text("coluna\n1\n")

    ex = Executor(arm, tmp_path / "motor", [Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: "v1", calcular)])
    # Mesmo com lanes=3, o último município usa o caminho serial.
    estado = ex.rodar_uf("PA", [1500001], lanes=3)
    assert estado["situacao"] == "pronto"
    assert estado["processamento"]["municipios"]["prontos"] == 1


def test_eventos_reais_inicio_fim_lease_e_whitelist(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("UNIDADE", "PA-1")
    ctx = P.contexto(tmp_path, "PA")
    cods = [1500001, 1500002, 1500003]
    antes = P.eventos_publicos(ctx, cods, {1500003})
    assert [x["situacao"] for x in antes] == ["pendente", "pendente", "pronto"]
    with P.acompanhar(ctx, 1500001) as resultado:
        evento = P.eventos_publicos(ctx, cods, {1500003})[0]
        assert evento["situacao"] == "em_execucao"
        validade = evento["valido_ate"]
        assert P.eventos_publicos(ctx, cods, {1500003})[0]["valido_ate"] == validade
        resumo = P.resumir(ctx, cods, {1500003})
        assert resumo["municipios"]["em_execucao"] == 1
        resultado["erro"] = False
    fim = P.eventos_publicos(ctx, cods, {1500003})[0]
    assert fim["situacao"] == "pronto"
    assert fim["observado_em"] > evento["observado_em"]
    assert set(fim) == {
        "cod_ibge",
        "situacao",
        "unidade",
        "run_id",
        "run_attempt",
        "observado_em",
        "ultima_mudanca_em",
        "valido_ate",
    }
    assert dt.datetime.fromisoformat(fim["observado_em"]).microsecond
    # O evento vencido em execução fica desconhecido; um pronto não é apagado pelo lease.
    arquivo = ctx["pasta"] / "1500001.json"
    salvo = json.loads(arquivo.read_text())
    salvo["situacao"] = "em_execucao"
    arquivo.write_text(json.dumps(salvo))
    perto_de_vencer = dt.datetime.fromisoformat(salvo["valido_ate"]) - dt.timedelta(seconds=2)
    monkeypatch.setattr(P, "agora", lambda: perto_de_vencer)
    resumo = P.resumir(ctx, cods, {1500003})
    assert resumo["municipios"]["em_execucao"] == 1
    assert resumo["valido_ate"] == salvo["valido_ate"]  # pai não renova heartbeat antigo
    futuro = dt.datetime.fromisoformat(salvo["valido_ate"]) + dt.timedelta(seconds=1)
    monkeypatch.setattr(P, "agora", lambda: futuro)
    assert P.resumir(ctx, cods, {1500003})["municipios"]["desconhecidos"] == 1
    assert P.eventos_publicos(ctx, cods, {1500003})[0]["situacao"] == "desconhecido"
    salvo["situacao"] = "pronto"
    arquivo.write_text(json.dumps(salvo))
    assert P.eventos_publicos(ctx, cods, {1500003})[0]["situacao"] == "pronto"


def test_encerrar_pool_nao_deixa_running_fantasma(tmp_path):
    ctx = P.contexto(tmp_path, "PA")
    with P.acompanhar(ctx, 1500001):
        P.encerrar(ctx)
        assert P.resumir(ctx, [1500001], set())["municipios"]["desconhecidos"] == 1


def test_workflow_checkpoint_antes_calculo_e_preservacao_incondicional():
    repo = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((repo / ".github/workflows/processar-estados.yml").read_text())
    passos = workflow["jobs"]["processar"]["steps"]
    restaurar = next(i for i, x in enumerate(passos) if x.get("id") == "checkpoint_restaurado")
    calcular = next(i for i, x in enumerate(passos) if x.get("id") == "executor")
    salvar = next(i for i, x in enumerate(passos) if "checkpoint salvar" in x.get("run", ""))
    retratos = next(i for i, x in enumerate(passos) if "Preservar retratos imutáveis" in x.get("name", ""))
    assert restaurar < calcular < salvar < retratos
    assert "always()" in passos[salvar]["if"]
    assert "steps.executor.outcome != 'skipped'" in passos[salvar]["if"]
    assert '--repositorio "$GITHUB_WORKSPACE"' in passos[salvar]["run"]
    assert "upload-artifact" not in passos[salvar].get("uses", "")
