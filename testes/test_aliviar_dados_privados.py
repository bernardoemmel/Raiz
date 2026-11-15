"""O alívio do arquivo privado só leva o que o processamento não lê mais."""

import datetime as dt
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "aliviar", Path(__file__).parents[1] / "scripts/aliviar_dados_privados.py"
)
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)

AGORA = dt.datetime(2026, 11, 14, 23, tzinfo=dt.UTC)
VELHO, NOVO = "2026-11-14T10:00:00Z", "2026-11-14T22:30:00Z"


class Falso:
    def __init__(self, conteudos):
        self.conteudos = conteudos

    def ler(self, asset_id):
        return json.dumps(self.conteudos[asset_id]).encode()


def test_mantem_checkpoint_apontado_e_leva_soltos_e_relatorios():
    usado, solto = "checkpoint-objeto-" + "a" * 64 + ".tar.gz", "checkpoint-objeto-" + "b" * 64 + ".tar.gz"
    atual, antigo = "checkpoint-TO-1001-9-1-" + "c" * 64 + ".json", "checkpoint-TO-1001-8-1-" + "d" * 64 + ".json"
    assets = [
        {"id": 1, "name": "checkpoint-TO-1001-latest.json", "updated_at": VELHO},
        {"id": 2, "name": atual, "updated_at": VELHO},
        {"id": 3, "name": antigo, "updated_at": VELHO},
        {"id": 4, "name": usado, "updated_at": VELHO},
        {"id": 5, "name": solto, "updated_at": VELHO},
        {"id": 6, "name": "checkpoint-objeto-" + "e" * 64 + ".tar.gz", "updated_at": NOVO},  # job em curso
        {"id": 7, "name": "catalogo-relatorio-1-1-TO-1001.json", "updated_at": VELHO},
        {"id": 8, "name": "raiz_TO.tar.gz", "updated_at": VELHO},
    ]
    gh = Falso({1: {"manifesto": atual}, 2: {"pacotes": [{"nome": usado}]}})
    nomes = {a["name"] for a in A.escolher(gh, assets, 6, AGORA)}
    assert nomes == {antigo, solto, "catalogo-relatorio-1-1-TO-1001.json"}


def test_estado_pronto_libera_checkpoint_e_cache():
    assets = [
        {"id": 1, "name": "checkpoint-PI-1-latest.json", "updated_at": VELHO},
        {"id": 2, "name": "cache_motor_unidade_PI-1.tar.gz", "updated_at": VELHO},
        {"id": 3, "name": "cache_motor_unidade_TO-1001.tar.gz", "updated_at": VELHO},
        {"id": 4, "name": "checkpoint-TO-1001-latest.json", "updated_at": VELHO},
    ]
    gh = Falso({1: {"manifesto": None}, 4: {"manifesto": None}})
    escolhidos = A.escolher(gh, assets, 6, AGORA, frozenset({"PI"}))
    assert {a["name"] for a in escolhidos} == {"checkpoint-PI-1-latest.json", "cache_motor_unidade_PI-1.tar.gz"}
    assert all(a["_livre"] for a in escolhidos)
