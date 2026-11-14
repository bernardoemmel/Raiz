"""A lista pública do navegador usa somente os nomes e hosts do manifesto revisado."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO = Path(__file__).resolve().parents[1]


def test_manifesto_publico_conserva_somente_rotulos_e_hosts_oficiais():
    fontes = yaml.safe_load((REPO / "raiz/calendario/fontes.yaml").read_text())["fontes"]
    esperado = [
        {
            "id": f["id"],
            "nome": f["nome"],
            "hosts": sorted({urlsplit(u).hostname for u in f["urls"]} | set(f.get("hosts", []))),
        }
        for f in fontes
    ]
    publicado = json.loads((REPO / "front/compartilhado/calendario-fontes.json").read_text())
    assert publicado == esperado
