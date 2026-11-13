"""Corridas reais de substituição do asset: leitura por nome e leitura de ID congelado."""

import httpx
import pytest

from raiz.executor.armazem import ArmazemRelease, FalhaHTTPPrivada


@pytest.mark.parametrize("modo", ["substituido", "intervalo", "sumiu", "persistente", "proibido", "ausente"])
def test_leitura_por_nome_revalida_apenas_404_sem_confundir_com_estado_vazio(tmp_path, monkeypatch, modo):
    chamadas, esperas = [], []
    paginas = 0

    def servidor(req):
        nonlocal paginas
        assert req.method == "GET"
        chamadas.append(req.url.path)
        if req.url.path.endswith("/assets"):
            paginas += 1
            if modo == "ausente" or (paginas > 1 and modo == "sumiu") or (paginas == 2 and modo == "intervalo"):
                return httpx.Response(200, json=[])
            ident = 1 if paginas == 1 or modo in {"persistente", "proibido"} else 2
            return httpx.Response(200, json=[{"id": ident, "name": "estados.json", "size": 2}])
        if req.url.path.endswith("/1"):
            return httpx.Response(403 if modo == "proibido" else 404, text="corpo privado")
        assert req.url.path.endswith("/2")
        return httpx.Response(200, content=b"{}")

    monkeypatch.setattr("raiz.executor.armazem.time.sleep", esperas.append)
    with httpx.Client(transport=httpx.MockTransport(servidor)) as cli:
        arm = ArmazemRelease("teste/repo", "privado", tmp_path, token="segredo", cliente=cli, privado=True)
        monkeypatch.setattr(arm, "_exigir_privado", lambda: {"id": 7})
        if modo in {"persistente", "sumiu"}:
            with pytest.raises(RuntimeError, match="substituído durante a leitura"):
                arm.manifesto(fresco=True)
            assert paginas == 4 and esperas == [0.25, 0.5, 1]
        elif modo == "proibido":
            with pytest.raises(FalhaHTTPPrivada, match="HTTP 403") as erro:
                arm._baixar_asset("estados.json")
            assert "corpo privado" not in str(erro.value)
            assert paginas == 1 and esperas == []
        elif modo == "ausente":
            assert arm._baixar_asset("estados.json") is None
            assert paginas == 1 and esperas == []
        else:
            assert arm._baixar_asset("estados.json") == b"{}"
            assert paginas == (3 if modo == "intervalo" else 2)


def test_download_de_id_congelado_nao_troca_por_outro_asset(tmp_path, monkeypatch):
    chamadas = []

    def servidor(req):
        chamadas.append(req.url.path)
        return httpx.Response(404, text="corpo privado")

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cli:
        arm = ArmazemRelease("teste/repo", "privado", tmp_path, token="segredo", cliente=cli, privado=True)
        monkeypatch.setattr(arm, "_exigir_privado", lambda: {"id": 7})
        with pytest.raises(FalhaHTTPPrivada, match="HTTP 404"):
            arm._baixar_ativo({"id": 1, "name": "produto.tar.gz"})
    assert chamadas == ["/repos/teste/repo/releases/assets/1"]
