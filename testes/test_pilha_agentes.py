"""O bootstrap não aceita configurações perigosas nem transforma medidas em estimativas inventadas."""

import datetime as dt
import importlib.util
import stat
from pathlib import Path

import pytest


def _modulo(nome):
    spec = importlib.util.spec_from_file_location(nome, Path(__file__).parents[1] / "scripts" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


pilha = _modulo("pilha_agentes")
agenda = _modulo("agendar_servicos")


def test_bootstrap_gera_segredos_privados_distintos_e_preserva_reinicio(tmp_path):
    a, b = tmp_path / "a.env", tmp_path / "b.env"
    pilha.ambiente_teste(a)
    pilha.ambiente_teste(b)
    original = a.read_bytes()
    pilha.ambiente_teste(a)
    assert a.read_bytes() == original
    assert stat.S_IMODE(a.stat().st_mode) == 0o600
    va, vb = pilha.ler_env(a), pilha.ler_env(b)
    assert all(va[chave] != vb[chave] for chave in pilha.SEGREDOS)
    assert va["RAIZ_BANCO_NOME"] == "raiz_agentes_teste"
    assert va["RAIZ_BANCO_URL_HOST"].endswith("/raiz_agentes_teste")
    pilha.validar(va, teste=True)
    with pytest.raises(ValueError, match="HTTPS"):
        pilha.validar(va, teste=False)


def test_env_nao_executa_shell_e_nao_reproduz_valor_na_falha(tmp_path):
    env = tmp_path / "a.env"
    env.write_text("export CHAVE=privado\n")
    with pytest.raises(ValueError) as erro:
        pilha.ler_env(env)
    assert "privado" not in str(erro.value)
    env.write_text("CHAVE=$(comando)\n")
    assert pilha.ler_env(env)["CHAVE"] == "$(comando)"


@pytest.mark.parametrize(("texto", "esperado"), [("1.5GiB", 1610612736), ("128MiB", 134217728), ("2MB", 2000000)])
def test_unidades_docker_memoria(texto, esperado):
    assert pilha.memoria_bytes(texto) == esperado


def test_configuracao_pix_real_e_rejeitada_em_teste(tmp_path):
    env = tmp_path / "a.env"
    pilha.ambiente_teste(env)
    dados = pilha.ler_env(env)
    dados["RAIZ_PIX_MODO"] = "producao"
    with pytest.raises(ValueError, match="PIX_MODO=teste"):
        pilha.validar(dados, teste=True)


def test_calendario_recupera_horario_apos_reinicio_e_periodicas_nao_duplicam():
    antes = dt.datetime(2026, 11, 12, 6, 46, tzinfo=dt.UTC)
    depois = antes + dt.timedelta(minutes=1)
    assert agenda.faixa("calendario", antes) is None
    assert agenda.faixa("calendario", depois) == "2026-11-12"
    assert agenda.faixa("calendario", depois + dt.timedelta(hours=10)) == "2026-11-12"
    assert agenda.faixa("alertas", antes) == agenda.faixa("alertas", depois)
    assert agenda.faixa("alertas", depois + dt.timedelta(minutes=15)) != agenda.faixa("alertas", depois)


def test_agenda_teste_nao_inicia_coleta_ou_envio(monkeypatch):
    def externo(*args, **kwargs):
        raise AssertionError("não pode iniciar processo externo")

    monkeypatch.setattr(agenda.subprocess, "run", externo)
    assert all(agenda.executar(nome, teste=True) for nome in agenda.TAREFAS)
