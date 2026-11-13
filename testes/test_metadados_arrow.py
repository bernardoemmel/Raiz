"""Conflitos tardios do Arrow mantêm a área numérica com uma ou várias CPUs."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from raiz import metadados as M

pytest.importorskip("croissant_baker")


@pytest.fixture
def handler_csv(tmp_path, monkeypatch):
    from croissant_baker import metadata_generator

    handlers = []

    def baker(*args, **kwargs):
        handlers.extend(kwargs["handlers"])
        return SimpleNamespace(generate_metadata=lambda: {}, scan_report=SimpleNamespace(to_dict=lambda: {"files": []}))

    monkeypatch.setattr(metadata_generator, "MetadataGenerator", baker)
    M._executar_lote(
        "baker", {"pasta": str(tmp_path), "arquivos": [], "nome": "sintético", "descricao": "teste"}, isolado=False
    )
    return handlers[0]


@pytest.mark.parametrize(
    "mensagem,esperado",
    [
        ("In CSV column #1: CSV conversion error to int64: invalid value '2.5'", (1, "int64")),
        ("In CSV column #1: Row #160002: CSV conversion error to int64: invalid value '2.5'", (1, "int64")),
        ("In CSV column #1: Row #160002: CSV conversion error to double: invalid value 'texto'", (1, "double")),
        ("In CSV column #1: Row #160002: erro desconhecido", (None, None)),
        ("In CSV column #1: Row #incerta: CSV conversion error to int64", (None, None)),
        ("Row #160002: CSV conversion error to int64", (None, None)),
    ],
)
def test_parser_preserva_conflitos_conhecidos_e_fallback(handler_csv, mensagem, esperado):
    assert handler_csv._parse_conflict(mensagem) == esperado


@pytest.mark.parametrize("uma_cpu", [False, True], ids=["padrao", "uma_cpu"])
@pytest.mark.parametrize("isolado", [False, True], ids=["direto", "worker"])
def test_decimal_depois_do_primeiro_bloco_preserva_float(tmp_path, uma_cpu, isolado):
    nome = "imoveis_1504950.csv"
    (tmp_path / nome).write_text("cod_imovel,ha\n" + "CAR-A,3\n" * 160_000 + "CAR-B,2.5\n", encoding="utf-8")
    ambiente = os.environ.copy()
    raiz = Path(M.__file__).resolve().parents[1]
    ambiente["PYTHONPATH"] = str(raiz) + os.pathsep + ambiente.get("PYTHONPATH", "")
    if uma_cpu:
        ambiente["OMP_NUM_THREADS"] = "1"
    else:
        ambiente.pop("OMP_NUM_THREADS", None)
    codigo = """
import json
import sys
import pyarrow as pa
from raiz import metadados as M
ficha = M._executar_lote(
    "baker",
    {"pasta": sys.argv[1], "arquivos": [sys.argv[2]], "nome": "sintético", "descricao": "teste"},
    isolado=sys.argv[3] == "True",
)
campos = {campo["name"]: str(campo["dataType"]) for campo in ficha["recordSet"][0]["field"]}
print(json.dumps({"cpus": pa.cpu_count(), "campos": campos}))
"""
    processo = subprocess.run(
        [sys.executable, "-c", codigo, str(tmp_path), nome, str(isolado)],
        cwd=raiz,
        env=ambiente,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    resultado = json.loads(processo.stdout)
    if uma_cpu:
        assert resultado["cpus"] == 1
    assert resultado["campos"] == {"cod_imovel": "sc:Text", "ha": "cr:Float64"}
