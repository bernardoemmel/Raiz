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


@pytest.mark.parametrize("embutido", ["presente", "parcial", "antigo"])
def test_leitura_usa_presenca_no_release_mas_nunca_infere_ausencia(tmp_path, monkeypatch, embutido):
    chamadas = []

    def servidor(req):
        chamadas.append(req.url.path)
        if req.url.path.endswith("/assets"):
            assert embutido != "presente", "a paginação concorrente não é necessária para este arquivo"
            return httpx.Response(200, json=[{"id": 2, "name": "estados.json", "size": 2}])
        if req.url.path.endswith("/1"):
            return httpx.Response(404)
        assert req.url.path.endswith("/2")
        return httpx.Response(200, content=b"{}")

    ativo = {"id": 1 if embutido == "antigo" else 2, "name": "estados.json", "size": 2}
    with httpx.Client(transport=httpx.MockTransport(servidor)) as cli:
        arm = ArmazemRelease("teste/repo", "privado", tmp_path, token="segredo", cliente=cli, privado=True)
        monkeypatch.setattr(
            arm, "_exigir_privado", lambda: {"id": 7, "assets": [] if embutido == "parcial" else [ativo]}
        )
        monkeypatch.setattr("raiz.executor.armazem.time.sleep", lambda _: None)
        assert arm._baixar_asset("estados.json") == b"{}"
    assert sum(p.endswith("/assets") for p in chamadas) == (0 if embutido == "presente" else 1)


def test_verificar_acesso_nao_depende_da_paginacao_dos_assets(tmp_path, monkeypatch):
    from testes.test_armazem_release import GitHubFalso, _armazem

    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path)
    monkeypatch.setattr(arm, "_assets", lambda *args: pytest.fail("paginação concorrente desnecessária"))
    arm.verificar_publicacao()
    gh.privado = False
    with pytest.raises(PermissionError):
        arm.verificar_publicacao()


@pytest.mark.parametrize("alteracao", ["nenhuma", "publicado", "apagado", "acesso_recusado"])
def test_rascunho_reutiliza_id_mas_revalida_privacidade_e_existencia(tmp_path, alteracao):
    chamadas = []
    repeticao = False

    def servidor(req):
        chamadas.append(req.url.path)
        if req.url.path.endswith("/teste/repo"):
            return httpx.Response(200, json={"private": False})
        if req.url.path.endswith("/tags/privado"):
            return httpx.Response(404)
        if req.url.path.endswith("/releases/7"):
            if alteracao == "acesso_recusado":
                return httpx.Response(403)
            if alteracao == "apagado":
                return httpx.Response(404)
            return httpx.Response(200, json={"id": 7, "tag_name": "privado", "draft": alteracao != "publicado"})
        assert req.url.path.endswith("/releases")
        ident = 8 if repeticao and alteracao == "apagado" else 7
        return httpx.Response(200, json=[{"id": ident, "tag_name": "privado", "draft": True, "assets": []}])

    with httpx.Client(transport=httpx.MockTransport(servidor)) as cli:
        arm = ArmazemRelease("teste/repo", "privado", tmp_path, token="segredo", cliente=cli, privado=True)
        arm.verificar_publicacao()
        repeticao = True
        if alteracao == "publicado":
            with pytest.raises(PermissionError):
                arm.verificar_publicacao()
        elif alteracao == "acesso_recusado":
            with pytest.raises(FalhaHTTPPrivada, match="403"):
                arm.verificar_publicacao()
        else:
            arm.verificar_publicacao()
        assert arm._release_id == (8 if alteracao == "apagado" else 7)
    assert chamadas.count("/repos/teste/repo/releases/tags/privado") == (2 if alteracao == "apagado" else 1)
    assert chamadas.count("/repos/teste/repo") == 2
