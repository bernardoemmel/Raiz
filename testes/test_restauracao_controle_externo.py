import hashlib

import geopandas as gpd
import pandas as pd
import requests

from raiz import restauracao_controle_externo as C
from raiz import restauracao_validacao_regeneracao as V


def test_falha_http_registra_pendencia_sem_numeros(tmp_path, monkeypatch):
    def falhar(_):
        resposta = requests.Response()
        resposta.status_code = 403
        raise requests.HTTPError(response=resposta)

    monkeypatch.setattr(C, "_baixar", falhar)
    r = C.avaliar(tmp_path)
    assert r["status"] == "pendente_fonte_conferida"
    assert r["erro_mg_ha_por_idade"] is None
    assert "403" in r["motivo"]
    assert not list(tmp_path.iterdir())


def test_publica_controle_conferido_sem_nome_pessoal(tmp_path, monkeypatch):
    t = pd.DataFrame(
        [
            {
                "plot_id": str(i),
                "cod_ibge": str(i % 16),
                "forest_age_years": i % 40 + 1,
                "biomass_total_Mg_ha": 200 * (i % 40 + 1) / (20 + i % 40 + 1),
                "responsible": "NAO_PUBLICAR",
            }
            for i in range(126)
        ]
    )
    monkeypatch.setattr(C, "_baixar", lambda f: t.to_csv(index=False).encode() if f is C.CAMPO else b"malha")
    monkeypatch.setattr(gpd, "read_file", lambda _: None)

    def vincular(p, _):
        assert "responsible" not in p
        return p

    monkeypatch.setattr(V, "vincular_municipios", vincular)
    r = C.avaliar(tmp_path)
    assert r["status"] == "validado_fora_do_municipio"
    bruto = (tmp_path / r["arquivo"]).read_bytes()
    assert hashlib.sha256(bruto).hexdigest() == r["sha256"]
    assert b"NAO_PUBLICAR" not in bruto
    assert sum(m["n"] for m in r["erro_mg_ha_por_idade"]) == 126


def test_download_recusa_conteudo_divergente(monkeypatch):
    class Resposta:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            yield b"trocado"

    import pytest

    monkeypatch.setattr(requests, "get", lambda *a, **kw: Resposta())
    with pytest.raises(ValueError, match="SHA256"):
        C._baixar({"url": "https://example.org", "bytes": 7, "sha256": "0" * 64})
