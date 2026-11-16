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


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://localhost/raiz",
        "postgresql://externo/raiz_agentes_teste",
        "postgresql://banco/producao",
    ],
)
def test_car_sintetico_recusa_banco_fora_da_pilha_descartavel(url):
    from scripts.agentes_car_teste import validar_url

    with pytest.raises(ValueError, match="base descartável"):
        validar_url(url)


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


def test_medicao_encerra_no_sentinela_sem_perder_a_amostra(tmp_path, monkeypatch):
    import json

    fim = tmp_path / "terminou"
    fim.touch()
    chamadas = []

    def docker(cmd, *, capturar=False):
        chamadas.append(cmd)
        if "stats" in cmd:
            return json.dumps({"Name": "api-sintetica", "MemUsage": "128MiB / 2GiB", "CPUPerc": "2.0%"})
        if "inspect" in cmd:
            return json.dumps([{"Id": "sha256:imagem", "Size": 500, "Config": {}}])
        if "du" in cmd:
            return "1024 /volume\n"
        return "imagem\n"

    monkeypatch.setattr(pilha, "executar", docker)
    monkeypatch.setattr(pilha.time, "sleep", lambda _: pytest.fail("não deve esperar após o sentinela"))
    saida = tmp_path / "recursos.json"
    pilha.medir(["docker", "compose"], saida, 720, 10, fim)
    relatorio = json.loads(saida.read_text())
    assert len(relatorio["amostras"]) == 1
    assert relatorio["soma_picos_memoria_bytes"] == 134217728
    assert relatorio["imagens"][0]["id"] == "sha256:imagem"
    assert sum("stats" in c for c in chamadas) == 1


def test_producao_nao_aceita_pix_simulado_ou_sem_chave(tmp_path):
    env = tmp_path / "a.env"
    pilha.ambiente_teste(env)
    dados = pilha.ler_env(env)
    dados.update(
        {
            "RAIZ_KEYCLOAK_URL": "https://oauth.exemplo.org",
            "RAIZ_OAUTH_ISSUER": "https://oauth.exemplo.org/realms/raiz",
            "RAIZ_MCP_RESOURCE": "https://api.exemplo.org/mcp",
            "RAIZ_API_PUBLICA_URL": "https://api.exemplo.org",
            "RAIZ_OAUTH_REDIRECT_URI": "https://cliente.exemplo.org/callback",
            "RAIZ_AGENDA_MODO": "producao",
        }
    )
    with pytest.raises(ValueError, match="produção exige Pix"):
        pilha.validar(dados, teste=False)
    dados["RAIZ_PIX_MODO"] = "producao"
    with pytest.raises(ValueError, match="produção exige Pix"):
        pilha.validar(dados, teste=False)


def test_manifesto_imagem_hash_fontes_modelos_e_ignora_segredos_e_cache(tmp_path):
    import hashlib

    codigo = _modulo("proveniencia_imagem")
    (tmp_path / "raiz/modelos").mkdir(parents=True)
    (tmp_path / "raiz/modelos/rota.py").write_text("codigo = 1\n")
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra/.env").write_text("SEGREDO=privado\n")
    (tmp_path / "infra/agentes.env").write_text("SEGREDO=privado\n")
    (tmp_path / "scripts/__pycache__").mkdir(parents=True)
    (tmp_path / "scripts/__pycache__/gerado.pyc").write_bytes(b"cache")
    resultado = codigo.manifesto(tmp_path)
    assert resultado["arquivos"] == {"raiz/modelos/rota.py": hashlib.sha256(b"codigo = 1\n").hexdigest()}
