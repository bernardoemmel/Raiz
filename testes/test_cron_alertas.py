"""Instalação de cron preserva os trabalhos existentes e não duplica alertas."""

import fcntl
import subprocess
from pathlib import Path

import pytest

from scripts.instalar_cron_alertas import FIM, INICIO, atualizar, bloco, instalar


def test_instalacao_preserva_outros_trabalhos_e_e_idempotente():
    novo = bloco(Path("/srv/raiz"), "/opt/uv", "/usr/bin/flock")
    antes = "MAILTO=operacao\n0 1 * * * backup\n"
    depois = "0 2 * * * outro_trabalho\n"
    atual = antes + INICIO + "\ncron antigo\n" + FIM + "\n" + depois
    esperado = antes + novo + depois
    assert atualizar(atual, novo) == esperado
    assert atualizar(esperado, novo) == esperado
    assert atualizar("0 1 * * * backup", novo) == "0 1 * * * backup\n" + novo


@pytest.mark.parametrize("atual", [INICIO, FIM, FIM + "\n" + INICIO, INICIO + "\n" + INICIO + "\n" + FIM])
def test_recusa_bloco_incompleto_ou_duplicado(atual):
    with pytest.raises(ValueError, match="incompleto ou duplicado"):
        atualizar(atual, "novo")


def test_comando_roda_do_repositorio_com_trava_e_caminho_com_espacos(tmp_path):
    repo = tmp_path / "raiz com espaço"
    repo.mkdir()
    uv = tmp_path / "uv falso"
    uv.write_text("#!/bin/sh\npwd > rodada.txt\nprintf '%s\\n' \"$@\" >> rodada.txt\n")
    uv.chmod(0o700)
    linha = bloco(repo, str(uv), "/usr/bin/flock").splitlines()[1]
    comando = linha.removeprefix("*/15 * * * * ")
    subprocess.run(["/bin/sh", "-c", comando], check=True)
    assert (repo / "rodada.txt").read_text().splitlines() == [
        str(repo),
        "run",
        "--frozen",
        "raiz",
        "operacao",
        "alertas",
    ]
    (repo / "rodada.txt").unlink()
    with (repo / "dados/operacao/alertas.lock").open("w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        subprocess.run(["/bin/sh", "-c", comando], check=True)
        assert not (repo / "rodada.txt").exists()


@pytest.mark.parametrize("caminho", ["/srv/raiz%nome", "/srv/raiz\ncron", "/srv/raiz\rcron"])
def test_caminho_nao_injeta_linha_ou_entrada_no_cron(caminho):
    with pytest.raises(ValueError):
        bloco(Path(caminho), "/opt/uv", "/usr/bin/flock")


def test_falha_ao_ler_cron_nao_apaga_agendamentos(monkeypatch):
    chamadas = []
    monkeypatch.setattr("scripts.instalar_cron_alertas.shutil.which", lambda _: "/usr/bin/crontab")

    def executar(args, **kwargs):
        chamadas.append(args)
        return subprocess.CompletedProcess(args, 1, "", "permission denied")

    monkeypatch.setattr("scripts.instalar_cron_alertas.subprocess.run", executar)
    with pytest.raises(ValueError, match="nenhum agendamento foi alterado"):
        instalar("novo")
    assert chamadas == [["/usr/bin/crontab", "-l"]]
