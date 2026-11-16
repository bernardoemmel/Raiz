import hashlib
import json

import pytest

from raiz import restauracao as R
from raiz import restauracao_nacional_pa as P


class Arquivo:
    def __init__(self, dado):
        self.bruto = json.dumps(dado).encode()
        self.conferido = False

    def _exigir_privado(self):
        self.conferido = True

    def _baixar_asset(self, nome, fresco):
        assert self.conferido and fresco
        return self.bruto


def manifesto():
    return {
        "modelo_versao": R.versao(),
        "cenario": R.cenario()["cenario"],
        "uf": "PA",
        "municipios": 144,
        "imoveis_calculados": 345870,
        "arquivos": {"lote_PA_central_r12_123_1_previsoes.tar.gz": {}},
    }


def test_ponteiro_privado_congela_manifesto_mesma_versao():
    arm = Arquivo(manifesto())
    r = P.referencia(arm, {"lote_PA_central_r12.json": {}})
    assert r["manifesto_sha256"] == hashlib.sha256(arm.bruto).hexdigest()
    assert r["manifesto"]["modelo_versao"] == R.versao()


def test_rodada_antiga_nao_e_reetiquetada():
    d = manifesto()
    d["modelo_versao"] = "antiga"
    assert P.referencia(Arquivo(d), {"lote_PA_central_r12.json": {}}) is None
    assert P.referencia(Arquivo(d), {}) is None


@pytest.mark.parametrize("campo,valor", [("municipios", 143), ("imoveis_calculados", 1), ("arquivos", {})])
def test_rodada_incompleta_nao_promove(campo, valor):
    d = manifesto()
    d[campo] = valor
    with pytest.raises(ValueError):
        P.referencia(Arquivo(d), {"lote_PA_central_r12.json": {}})
