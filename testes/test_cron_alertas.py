"""Instalação de cron preserva os trabalhos existentes e não duplica alertas."""

import fcntl
import shutil
import subprocess
import sys
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


def test_calendario_diario_preserva_alertas_e_vice_versa():
    alertas = bloco(Path("/srv/raiz"), "/opt/uv", "/usr/bin/flock")
    calendario = bloco(Path("/srv/raiz"), "/opt/uv", "/usr/bin/flock", "calendario")
    original = "0 1 * * * backup\n" + alertas
    completo = atualizar(original, calendario, "calendario")
    assert completo == original + calendario
    assert atualizar(completo, calendario, "calendario") == completo
    assert atualizar(completo, alertas) == completo
    assert "47 6 * * *" in calendario
    assert "dados/operacao/calendario.lock" in calendario
    assert "raiz calendario coletar" in calendario
    assert "--sem-banco" not in calendario
    assert "CRON_TZ" not in calendario  # não muda o fuso dos outros trabalhos


def test_ponte_lotes_renova_catalogo_e_importa_rascunhos_sem_coletor_concorrente():
    ponte = bloco(Path("/srv/raiz"), "/opt/uv", "/usr/bin/flock", "vigilancia_lotes")
    assert "*/15 * * * *" in ponte
    assert "python -m raiz.vigilancia lotes-ciclo --publicar" in ponte
    assert "rodar" not in ponte and "dados/operacao/vigilancia_lotes.lock" in ponte
    assert atualizar(atualizar("", ponte, "vigilancia_lotes"), ponte, "vigilancia_lotes") == ponte


@pytest.mark.parametrize("atual", [INICIO, FIM, FIM + "\n" + INICIO, INICIO + "\n" + INICIO + "\n" + FIM])
def test_recusa_bloco_incompleto_ou_duplicado(atual):
    with pytest.raises(ValueError, match="incompleto ou duplicado"):
        atualizar(atual, "novo")


@pytest.mark.parametrize(
    "tarefa,comando_raiz", [("alertas", ["operacao", "alertas"]), ("calendario", ["calendario", "coletar"])]
)
def test_comando_roda_do_repositorio_com_trava_e_caminho_com_espacos(tmp_path, tarefa, comando_raiz):
    repo = tmp_path / "raiz com espaço"
    repo.mkdir()
    uv = tmp_path / "uv falso"
    uv.write_text("#!/bin/sh\npwd > rodada.txt\nprintf '%s\\n' \"$@\" >> rodada.txt\n")
    uv.chmod(0o700)
    linha = bloco(repo, str(uv), "/usr/bin/flock", tarefa).splitlines()[1]
    comando = linha.split(" ", 5)[5]
    subprocess.run(["/bin/sh", "-c", comando], check=True)
    assert (repo / "rodada.txt").read_text().splitlines() == [
        str(repo),
        "run",
        "--frozen",
        "raiz",
        *comando_raiz,
    ]
    (repo / "rodada.txt").unlink()
    with (repo / f"dados/operacao/{tarefa}.lock").open("w") as trava:
        fcntl.flock(trava, fcntl.LOCK_EX)
        subprocess.run(["/bin/sh", "-c", comando], check=True)
        assert not (repo / "rodada.txt").exists()


@pytest.mark.parametrize("caminho", ["/srv/raiz%nome", "/srv/raiz\ncron", "/srv/raiz\rcron"])
def test_caminho_nao_injeta_linha_ou_entrada_no_cron(caminho):
    with pytest.raises(ValueError):
        bloco(Path(caminho), "/opt/uv", "/usr/bin/flock")


@pytest.mark.parametrize("tarefa", ["alertas", "calendario"])
def test_cron_carrega_dotenv_no_ambiente_sem_executar_shell(tmp_path, monkeypatch, tarefa):
    uv_real = shutil.which("uv")
    if uv_real is None:
        pytest.skip("integração do dotenv exige uv")
    monkeypatch.delenv("RAIZ_VIGILANCIA_DIR", raising=False)
    monkeypatch.setenv("UV_OFFLINE", "1")
    # O valor parece código shell de propósito: uv deve tratá-lo como texto, sem executar nada.
    valor = "$(touch arquivo_que_nao_deve_existir)"
    (tmp_path / ".env").write_text(f"RAIZ_VIGILANCIA_DIR='{valor}'\n")
    prova = (
        "import os; from pathlib import Path; "
        f"Path('ambiente_ok').write_text(str(os.environ.get('RAIZ_VIGILANCIA_DIR') == {valor!r}))"
    )
    uv_teste = tmp_path / "uv_teste"
    # Só troca o comando da aplicação por uma sonda; o dotenv é lido pelo binário uv de verdade.
    uv_teste.write_text(
        f"#!{sys.executable}\nimport os,sys\n"
        f"os.execv({uv_real!r}, [{uv_real!r}, 'run', '--no-project', "
        f"*sys.argv[2:sys.argv.index('raiz')], {sys.executable!r}, '-c', {prova!r}])\n"
    )
    uv_teste.chmod(0o700)
    linha = bloco(tmp_path, str(uv_teste), "/usr/bin/flock", tarefa).splitlines()[1]
    resultado = subprocess.run(["/bin/sh", "-c", linha.split(" ", 5)[5]], capture_output=True, text=True, check=True)
    assert (tmp_path / "ambiente_ok").read_text() == "True"
    assert not (tmp_path / "arquivo_que_nao_deve_existir").exists()
    assert valor not in resultado.stdout + resultado.stderr


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
