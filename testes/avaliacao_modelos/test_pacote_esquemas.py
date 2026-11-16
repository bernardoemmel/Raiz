from zipfile import ZipFile

import pytest

from scripts.conferir_pacote import conferir
from scripts.esquemas_avaliacao import main


def pacote(tmp_path, dependencia="permitida", fonte="", arquivo="raiz/avaliacao/treino.py"):
    p = tmp_path / "raiz.whl"
    with ZipFile(p, "w") as z:
        z.writestr("raiz.dist-info/METADATA", f"Name: raiz\nRequires-Dist: {dependencia}\n")
        z.writestr(arquivo, fonte)
    return p


@pytest.mark.parametrize("nome", ["scpi", "SCPI_pkg", "vegan"])
def test_dependencia_transitiva_gpl_nao_entra_em_distribuicao(tmp_path, nome):
    lock = {"package": [{"name": "permitida", "optional-dependencies": {"extra": [{"name": nome}]}}, {"name": nome}]}
    with pytest.raises(ValueError, match="scpi/vegan"):
        conferir(lock, pacote(tmp_path))


def test_nao_basta_omitir_gpl_dos_metadados(tmp_path):
    lock = {"package": [{"name": "permitida"}]}
    with pytest.raises(ValueError, match="importação GPL"):
        conferir(lock, pacote(tmp_path, fonte="from scpi_pkg import scpi"))
    with pytest.raises(ValueError, match="copiado"):
        conferir(lock, pacote(tmp_path, arquivo="raiz/vendor/vegan/DESCRIPTION"))
    with pytest.raises(ValueError, match="fora do módulo de treino"):
        conferir(lock, pacote(tmp_path, fonte="import imblearn", arquivo="raiz/api.py"))
    conferir(lock, pacote(tmp_path, fonte="from imblearn.pipeline import Pipeline"))


def test_esquemas_publicados_correspondem_ao_validador_fechado():
    assert main(["--conferir"]) == 0
