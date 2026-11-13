"""O CI divide a suíte sem omitir casos nem publicar a referência estadual privada."""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
import yaml

RAIZ = Path(__file__).parents[1]
ARQUIVO_ESTADUAL = "testes/test_lote.py"
NO_ESTADUAL = f"{ARQUIVO_ESTADUAL}::test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta"
INTERNO = "github.event_name!='pull_request'||github.event.pull_request.head.repo.full_name==github.repository"


@pytest.fixture
def fluxo():
    workflow = yaml.safe_load((RAIZ / ".github/workflows/ci.yml").read_text())
    jobs = workflow["jobs"]
    privado = jobs["referencia_para"]
    preparadores = [p for p in privado["steps"] if "--preparar" in shlex.split(p.get("run", ""))]
    assert len(preparadores) == 1
    return workflow, jobs["testes_python"], privado, jobs["checagens"], preparadores[0]


def _condicao(passo):
    return re.sub(r"\s+", "", passo.get("if", "")).removeprefix("${{").removesuffix("}}")


def _caminho(valor):
    valor = re.sub(r"\$\{\{\s*runner\.temp\s*\}\}|\$\{?RUNNER_TEMP\}?", "/__temporario__", valor)
    valor = re.sub(r"\$\{\{\s*github\.workspace\s*\}\}|\$\{?GITHUB_WORKSPACE\}?", "/__checkout__", valor)
    return PurePosixPath(valor.replace("~/", "/__usuario__/", 1))


def _destino(preparador):
    argumentos = shlex.split(preparador["run"])
    return _caminho(argumentos[argumentos.index("--preparar") + 1])


def _ambiente(workflow, job, passo):
    return {**workflow.get("env", {}), **job.get("env", {}), **passo.get("env", {})}


def _pytest(job):
    passos = [p for p in job["steps"] if shlex.split(p.get("run", ""))[:3] == ["uv", "run", "pytest"]]
    assert len(passos) == 1
    return passos[0]


def test_escrita_fica_apenas_no_job_privado_e_checkout_nao_persiste_credencial(fluxo):
    workflow, gerais, privado, portao, _ = fluxo
    assert workflow["permissions"] == {"contents": "read"}
    for nome, job in workflow["jobs"].items():
        permissoes = job.get("permissions", workflow["permissions"])
        assert permissoes == {"contents": "write" if nome == "referencia_para" else "read"}
    for job in (gerais, privado, portao):
        checkouts = [p for p in job["steps"] if p.get("uses", "").startswith("actions/checkout@")]
        assert checkouts
        assert all(p.get("with", {}).get("persist-credentials") is False for p in checkouts)


def test_job_privado_requer_origem_interna_sem_pull_request_target(fluxo):
    workflow, _, privado, _, preparador = fluxo
    # PyYAML também aceita a chave `on` como booleano, conforme YAML 1.1.
    eventos = workflow.get("on", workflow.get(True))
    assert "pull_request" in eventos and "pull_request_target" not in eventos
    assert _condicao(privado) == INTERNO
    token = _ambiente(workflow, privado, preparador)["RAIZ_DADOS_PRIVADOS_TOKEN"]
    assert _condicao({"if": token}) == f"({INTERNO})&&github.token||''"


def test_credencial_explicita_fica_somente_no_passo_de_preparacao(fluxo):
    workflow, gerais, privado, portao, preparador = fluxo
    assert preparador.get("continue-on-error", False) is False
    for job in (gerais, privado, portao):
        for passo in job["steps"]:
            if passo is preparador:
                continue
            ambiente = _ambiente(workflow, job, passo)
            assert not any(re.search(r"TOKEN|SECRET|CREDENTIAL", nome, re.I) for nome in ambiente)
            # Isso confere a injeção explícita; a permissão continua valendo para as actions do job.
            assert not re.search(r"github\.token|secrets\.", json.dumps({**passo, "env": ambiente}))


def test_particao_executa_apenas_o_caso_estadual_no_job_privado(fluxo):
    workflow, gerais, privado, _, preparador = fluxo
    teste_geral, teste_privado = _pytest(gerais), _pytest(privado)
    assert shlex.split(teste_geral["run"]) == [
        "uv",
        "run",
        "pytest",
        "-q",
        f"--deselect={NO_ESTADUAL}",
        "--junitxml=resultado-pytest.xml",
    ]
    assert shlex.split(teste_privado["run"]) == [
        "uv",
        "run",
        "pytest",
        "-q",
        NO_ESTADUAL,
        "--junitxml=resultado-para.xml",
    ]
    assert "RAIZ_TESTE_PA_PASTA" not in _ambiente(workflow, gerais, teste_geral)
    assert privado["steps"].index(preparador) < privado["steps"].index(teste_privado)
    assert _condicao(teste_privado) == "!cancelled()"
    ambiente = _ambiente(workflow, privado, teste_privado)
    assert str(ambiente.get("RAIZ_TESTE_PA_OBRIGATORIO")) == "1"
    assert _caminho(ambiente["RAIZ_TESTE_PA_PASTA"]) == _destino(preparador)
    assert not gerais.get("needs") and not privado.get("needs")
    for job, passo in ((gerais, teste_geral), (privado, teste_privado)):
        assert "PYTEST_ADDOPTS" not in _ambiente(workflow, job, passo)
        assert job.get("continue-on-error", False) is False
        assert passo.get("continue-on-error", False) is False
        assert "|| true" not in passo["run"]


def _coletar(tmp_path, *selecao):
    ambiente = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    resultado = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", ARQUIVO_ESTADUAL, *selecao],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if resultado.returncode:
        pytest.fail("A coleta do módulo estadual deve terminar sem executar os testes.", pytrace=False)
    return {linha.strip() for linha in resultado.stdout.splitlines() if linha.startswith(f"{ARQUIVO_ESTADUAL}::")}


def test_deselecao_real_nao_omite_outro_caso_com_prefixo_semelhante(fluxo, tmp_path):
    _, gerais, _, _, _ = fluxo
    seletores = [a for a in shlex.split(_pytest(gerais)["run"]) if a.startswith("--deselect=")]
    todos = _coletar(tmp_path)
    restantes = _coletar(tmp_path, *seletores)
    # O pytest interpreta --deselect como prefixo; a comparação da coleta detecta um vizinho futuro.
    assert todos and restantes
    assert todos - restantes == {NO_ESTADUAL}
    assert restantes - todos == set()


def test_check_obrigatorio_checagens_continua_portao_das_duas_partes(fluxo):
    workflow, _, _, portao, _ = fluxo
    assert workflow["jobs"]["checagens"] is portao
    assert set(portao["needs"]) == {"testes_python", "referencia_para"}
    assert _condicao(portao) == "always()&&!cancelled()"
    passos = portao["steps"]
    conferir_status = [p for p in passos if "GERAIS" in p.get("env", {}) and "ESTADUAL" in p.get("env", {})]
    assert len(conferir_status) == 1
    status = conferir_status[0]
    assert status["env"] == {
        "GERAIS": "${{ needs.testes_python.result }}",
        "ESTADUAL": "${{ needs.referencia_para.result }}",
    }
    assert '"$GERAIS" != success' in status["run"] and '"$ESTADUAL" != success' in status["run"]
    assert "exit 1" in status["run"] and not status.get("continue-on-error", False)
    downloads = [p for p in passos if p.get("uses", "").startswith("actions/download-artifact@")]
    assert {p["with"]["name"]: p["with"]["path"] for p in downloads} == {
        "resultado-pytest": "resultados/gerais",
        "resultado-para": "resultados/para",
    }
    gates = [p for p in passos if "scripts/conferir_testes_ci.py" in shlex.split(p.get("run", ""))]
    assert len(gates) == 1
    gate = gates[0]
    assert shlex.split(gate["run"]) == [
        "python3",
        "scripts/conferir_testes_ci.py",
        "resultados/gerais/resultado-pytest.xml",
        "resultados/para/resultado-para.xml",
    ]
    assert str(_ambiente(workflow, portao, gate)["RAIZ_TESTE_PA_OBRIGATORIO"]) == "1"
    assert all(passos.index(status) < passos.index(p) < passos.index(gate) for p in downloads)
    for passo in [*downloads, gate]:
        assert _condicao(passo) == "!cancelled()" and not passo.get("continue-on-error", False)
    assert not portao.get("continue-on-error", False)


def test_limpeza_privada_roda_sempre_depois_dos_testes(fluxo):
    _, _, privado, _, preparador = fluxo
    destino, teste = _destino(preparador), _pytest(privado)
    limpezas = []
    for passo in privado["steps"]:
        argumentos = shlex.split(passo.get("run", ""))
        if argumentos[:1] == ["rm"] and any(_caminho(a) == destino for a in argumentos[1:]):
            limpezas.append(passo)
    assert len(limpezas) == 1
    assert _condicao(limpezas[0]) == "always()"
    assert privado["steps"].index(limpezas[0]) > privado["steps"].index(teste)


def test_referencia_privada_fica_fora_de_artifacts_e_caches(fluxo):
    workflow, gerais, privado, _, preparador = fluxo
    destino = _destino(preparador)
    assert destino.is_relative_to("/__temporario__") and destino != PurePosixPath("/__temporario__")
    for job, resultado in ((gerais, "resultado-pytest"), (privado, "resultado-para")):
        uploads = [p for p in job["steps"] if "upload-artifact@" in p.get("uses", "")]
        assert len(uploads) == 1
        assert uploads[0]["with"]["name"] == resultado
        assert uploads[0]["with"]["path"] == f"{resultado}.xml"
        assert _condicao(uploads[0]) == "always()"
        for passo in job["steps"]:
            uso = passo.get("uses", "")
            # setup-uv também tem cache automático, sem usar uma action cujo nome contenha "cache".
            if uso.startswith("astral-sh/setup-uv@"):
                assert "UV_CACHE_DIR" not in _ambiente(workflow, job, passo)
                assert "XDG_CACHE_HOME" not in _ambiente(workflow, job, passo)
                assert "cache-local-path" not in passo.get("with", {})
            if "upload-artifact@" not in uso and "cache" not in uso:
                continue
            for linha in str(passo.get("with", {}).get("path", "")).splitlines():
                if not linha or linha.startswith("!"):
                    continue
                assert "RAIZ_TESTE_PA_PASTA" not in linha and "${{" not in str(_caminho(linha))
                prefixo = re.split(r"[*?\[]", str(_caminho(linha)), maxsplit=1)[0]
                base = PurePosixPath(prefixo)
                if not base.is_absolute():
                    base = PurePosixPath("/__checkout__") / base
                assert not destino.is_relative_to(base), "artifact/cache abrange o diretório privado"
