"""O build usa a projeção validada, inclusive no cache, e não copia o ICS remoto."""

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PESSOAL = "Pessoa Particular; pessoa@example.invalid"


@pytest.fixture
def site(tmp_path):
    for relativo in (
        "front/scripts/baixar-calendario.mjs",
        "front/compartilhado/calendario-fontes.json",
        "raiz/__init__.py",
        "raiz/privacidade.py",
        "raiz/calendario/__init__.py",
        "raiz/calendario/feed.py",
        "raiz/qualidade_calendario.py",
    ):
        destino = tmp_path / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / relativo, destino)
    return tmp_path


def _coleta():
    return {
        "eventos": [
            {
                "id": "a" * 24,
                "tipo": "leilao_imovel",
                "marco": "evento",
                "titulo": PESSOAL,
                "data": "2099-11-15",
                "fonte_id": "dou",
                "fonte_nome": PESSOAL,
                "fonte_url": "https://www.in.gov.br/web/dou/-/edital-ficticio",
                "coletado_em": "2026-11-12T12:00:00Z",
                "confianca": 0.9,
                "situacao": "previsto",
                "titular": PESSOAL,
            }
        ],
        "total": 1,
        "fontes": [],
    }


def _rodar(site, **variaveis):
    ambiente = {k: v for k, v in os.environ.items() if not k.startswith("RAIZ_CALENDARIO")}
    ambiente.update(variaveis)
    return subprocess.run(
        ["node", "front/scripts/baixar-calendario.mjs"],
        cwd=site,
        env=ambiente,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_build_reconstroi_json_e_ics_sem_copiar_texto_livre(site):
    entrada = site / "entrada"
    entrada.mkdir()
    (entrada / "eventos.json").write_text(json.dumps(_coleta()))
    (entrada / "eventos.ics").write_text(f"BEGIN:VCALENDAR\nDESCRIPTION:{PESSOAL}\nEND:VCALENDAR\n")
    r = _rodar(site, RAIZ_CALENDARIO_DADOS=str(entrada))
    assert r.returncode == 0, r.stderr
    publico = site / "front/globo/public/calendario"
    texto = (publico / "eventos.json").read_text() + (publico / "eventos.ics").read_text()
    assert "Particular" not in texto and "pessoa@" not in texto
    assert "DESCRIPTION:" in texto and "Leilão de imóvel rural" in texto
    assert "titular" not in texto


def test_cache_offline_tambem_e_revalidado(site):
    publico = site / "front/globo/public/calendario"
    publico.mkdir(parents=True)
    (publico / "eventos.json").write_text(json.dumps(_coleta()))
    (publico / "eventos.ics").write_text(PESSOAL)
    r = _rodar(site, RAIZ_SEM_DOWNLOAD="1")
    assert r.returncode == 0, r.stderr
    assert "Particular" not in (publico / "eventos.json").read_text() + (publico / "eventos.ics").read_text()


def test_download_invalido_interrompe_build_em_vez_de_usar_copia_antiga(site):
    publico = site / "front/globo/public/calendario"
    publico.mkdir(parents=True)
    anterior = json.dumps(_coleta())
    (publico / "eventos.json").write_text(anterior)

    class Resposta(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"eventos": [{"titular": PESSOAL}], "fontes": []}).encode())

        def log_message(self, *args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Resposta)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        r = _rodar(site, RAIZ_CALENDARIO_URL=f"http://127.0.0.1:{servidor.server_port}")
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=5)
    assert r.returncode != 0
    assert "não passou na validação" in r.stderr
    assert "Particular" not in r.stderr and "pessoa@" not in r.stderr
    assert (publico / "eventos.json").read_text() == anterior
