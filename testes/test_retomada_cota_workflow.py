"""Cota da assinatura, cache e cadência da fila sem chamadas reais ao GitHub."""

import io
import json
from pathlib import Path

import pytest
import yaml

from scripts.esperar_cota_github import aguardar


def test_atestacao_espera_reset_sem_recalcular_nem_expor_token(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "sintetico")
    agora, chamadas = [1000], []

    def abrir(req, timeout):
        chamadas.append(req)
        return io.BytesIO(
            json.dumps(
                {
                    "resources": {
                        "core": {
                            "remaining": 0 if len(chamadas) == 1 else 5000,
                            "reset": 1120,
                        }
                    }
                }
            ).encode()
        )

    aguardar(abrir=abrir, dormir=lambda s: agora.__setitem__(0, agora[0] + s), relogio=lambda: agora[0])
    assert agora[0] == 1121 and len(chamadas) == 2
    assert all(r.headers["Authorization"] == "Bearer sintetico" for r in chamadas)


def test_atestacao_nao_espera_alem_da_margem(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "sintetico")
    resposta = {"resources": {"core": {"remaining": 0, "reset": 5000}}}
    with pytest.raises(RuntimeError, match="resultados preservados"):
        aguardar(abrir=lambda *a, **k: io.BytesIO(json.dumps(resposta).encode()), relogio=lambda: 1000,
                  dormir=lambda _: pytest.fail("não deve ultrapassar o prazo"))  # fmt: skip


def test_cadencia_horaria_uv_fixado_e_cache_checkpoint_com_tempo_para_cota():
    raiz = Path(__file__).resolve().parents[1]
    arquivos = list((raiz / ".github/workflows").glob("*.yml"))
    for arquivo in arquivos:
        w = yaml.safe_load(arquivo.read_text())
        for job in w.get("jobs", {}).values():
            for passo in job.get("steps", []):
                if passo.get("uses", "").startswith("astral-sh/setup-uv@"):
                    assert passo["with"]["version"] == "0.13.6"
    w = yaml.safe_load((raiz / ".github/workflows/processar-estados.yml").read_text())
    assert w[True]["schedule"] == [{"cron": "17 * * * *"}]
    assert w["env"]["RAIZ_PRIORIDADE_FUNIL"] == "1"
    passos = w["jobs"]["processar"]["steps"]
    for passo in passos:
        if passo.get("name", "").startswith("Recuperar") or "checkpoint privado" in passo.get("name", ""):
            assert passo["env"]["RAIZ_GITHUB_ESPERA_MAX_S"] == "3700"
            assert passo["timeout-minutes"] == 75
    restaurar = next(p for p in passos if p.get("id") == "checkpoint_restaurado")
    assert "--herdar-particao" in restaurar["run"]
    action = yaml.safe_load((raiz / ".github/actions/atestar-com-retry/action.yml").read_text())
    tentativas = [p for p in action["runs"]["steps"] if p.get("uses") == "actions/attest-build-provenance@v2"]
    assert len(tentativas) == 3
    assert "continue-on-error" not in tentativas[-1]
    assert all(p["with"]["subject-checksums"] == "${{ inputs.subject-checksums }}" for p in tentativas)
