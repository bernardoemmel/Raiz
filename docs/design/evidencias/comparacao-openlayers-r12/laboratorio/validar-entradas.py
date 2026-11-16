"""Impede substituir a entrada congelada por tiles ou geometria atualizados."""
import hashlib
import json
import pathlib

root = pathlib.Path(__file__).resolve().parent
expected = json.loads((root / "proveniencia-dados.json").read_text())
actual = json.loads((root / "dados-manifesto.json").read_text())
if actual["source_sha256"] != expected["snapshot_source_sha256"]:
    raise SystemExit("Geometria de origem divergente do snapshot.")
if actual["prepared_sha256"] != expected["prepared_sha256"]:
    raise SystemExit("Geometria preparada divergente do snapshot.")
for tile in expected["tiles"]:
    path = root / "public" / tile["file"]
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != tile["sha256"]:
        raise SystemExit(f"Tile divergente: {tile['file']}. Nenhuma série deve iniciar.")
print("Geometria e todos os tiles correspondem ao snapshot registrado.")
