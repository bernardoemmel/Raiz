"""Inventários mutáveis e vínculos Croissant, somente com respostas e arquivos sintéticos."""

import contextlib
import copy
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest

from raiz.executor.armazem import ArmazemRelease
from scripts import publicar_metadados as P
from scripts import verificar_release_dados as V


def _asset(nome="estados.json", identificador=1, digest="a" * 64):
    return {"name": nome, "id": identificador, "digest": f"sha256:{digest}", "size": 2, "updated_at": "2026-11-12"}


def _publicador():
    # O filtro representa cópias privadas que não precisam de fichas recursivas.
    return SimpleNamespace(
        arquivos_produto=lambda armazem: [a for a in armazem._assets() if not a["name"].startswith("backup-")]
    )


@contextlib.contextmanager
def _armazem(tmp_path, *, privado=False, identidades=None, ativos=None):
    """Cada identidade é (release_id, draft, repositório_privado), lida antes/depois da paginação."""
    identidades = identidades or [(9, privado, False)]
    estado = {"leitura": 0, "ativos": list(ativos if ativos is not None else [_asset()])}

    def responder(req):
        assert req.method == "GET"
        indice = min(estado["leitura"], len(identidades) - 1)
        release_id, draft, repo_privado = identidades[indice]
        if req.url.path == "/repos/exemplo/raiz":
            return httpx.Response(200, json={"private": repo_privado})
        if "/releases/tags/" in req.url.path:
            estado["leitura"] += 1
            return httpx.Response(200, json={"id": release_id, "draft": draft})
        if "/releases/" in req.url.path and req.url.path.endswith("/assets"):
            return httpx.Response(200, json=estado["ativos"])
        pytest.fail("rota fora da API sintética")

    with httpx.Client(transport=httpx.MockTransport(responder)) as cliente:
        armazem = ArmazemRelease(
            "exemplo/raiz",
            "dados-privados" if privado else "dados",
            tmp_path / "espelho",
            token="credencial-ficticia",
            cliente=cliente,
            privado=privado,
        )
        yield armazem, estado


@pytest.mark.parametrize(
    "privado,antes,depois,erro",
    [
        (False, (9, False, False), (10, False, False), "release_alterado_durante_inventario"),
        (False, (9, False, False), (9, True, False), "release_publico_nao_publicado"),
        (False, (9, False, False), (9, False, True), "release_publico_nao_publicado"),
        (True, (9, True, False), (9, False, False), "release_privado_exposto"),
        (True, (9, True, False), (9, True, True), "release_alterado_durante_inventario"),
    ],
    ids=["id", "publico-vira-rascunho", "repositorio-vira-privado", "privado-exposto", "identidade-privada-muda"],
)
def test_snapshot_recusa_identidade_ou_visibilidade_alterada(tmp_path, privado, antes, depois, erro):
    with _armazem(tmp_path, privado=privado, identidades=[antes, depois]) as (armazem, _):
        with pytest.raises(V.FalhaSegura, match=erro):
            V.snapshot(armazem, _publicador())


def test_snapshot_privado_inclui_infraestrutura_apesar_do_filtro_de_produtos(tmp_path):
    ativos = [_asset(), _asset("backup-exemplo.bin", 2, "b" * 64)]
    with _armazem(tmp_path, privado=True, ativos=ativos) as (armazem, estado):
        antes, produtos = V.snapshot(armazem, _publicador())
        assert [a["name"] for a in produtos] == ["estados.json"]
        assert {linha[0] for linha in antes["inventario"]} == {"estados.json", "backup-exemplo.bin"}
        estado["ativos"][1] = _asset("backup-exemplo.bin", 2, "c" * 64)
        depois, mesmos_produtos = V.snapshot(armazem, _publicador())
        assert mesmos_produtos == produtos
        assert depois != antes  # só a cópia privada mudou, mas o Release já não é o mesmo snapshot


def test_snapshot_publico_recusa_infraestrutura_excluida_pelo_publicador(tmp_path):
    ativos = [_asset(), _asset("backup-exemplo.bin", 2)]
    with _armazem(tmp_path, ativos=ativos) as (armazem, _):
        with pytest.raises(V.FalhaSegura, match="infraestrutura_no_release_publico"):
            V.snapshot(armazem, _publicador())


def test_conferencia_final_revisita_publico_depois_de_terminar_privado(tmp_path, monkeypatch, capsys):
    publicador = _publicador()
    with (
        _armazem(tmp_path / "publico") as (publico, estado_publico),
        _armazem(tmp_path / "privado", privado=True) as (privado, _),
    ):
        relatorio = {"escopos": {}}
        for escopo, armazem in (("publico", publico), ("privado", privado)):
            relatorio["escopos"][escopo] = {
                "snapshot": V.snapshot(armazem, publicador)[0],
                "snapshot_estavel": True,
                "integridade_ok": True,
                "erros": [],
            }
        # O público muda só depois de o privado terminar sua conferência inicial.
        estado_publico["ativos"] = [_asset(identificador=3, digest="d" * 64)]
        visitados = []

        @contextlib.contextmanager
        def abrir(args, escopo, cache):
            visitados.append(escopo)
            yield {"publico": publico, "privado": privado}[escopo]

        monkeypatch.setattr(V, "abrir_escopo", abrir)
        V.conferir_snapshots_finais(SimpleNamespace(), None, relatorio, publicador)

    assert visitados == ["publico", "privado"]
    resultado_publico, resultado_privado = (relatorio["escopos"][s] for s in ("publico", "privado"))
    assert not resultado_publico["integridade_ok"]
    assert not resultado_publico["snapshot_estavel"] and not resultado_publico["snapshot_final_estavel"]
    assert resultado_publico["erros"] == [{"etapa": "snapshot_final", "codigo": "release_alterado_antes_do_fim"}]
    assert resultado_privado["integridade_ok"] and resultado_privado["snapshot_final_estavel"]
    assert resultado_privado["erros"] == []
    assert "credencial-ficticia" not in capsys.readouterr().out


def _arquivos_fichados(tmp_path, armazem):
    def url(nome):
        return armazem.url_metadados(nome)

    referencias = {"estados.json": url("croissant_estados.json"), "exemplo.csv": url("croissant_exemplo.csv.json")}
    conteudos = {
        "estados.json": json.dumps({"estados": {}, "fichas": referencias}).encode(),
        "exemplo.csv": b"situacao\nok\n",
    }
    base = {"@type": "sc:Dataset", "conformsTo": "http://mlcommons.org/croissant/1.1", "isAccessibleForFree": False}
    for nome, dados in list(conteudos.items()):
        ficha = {
            **base,
            "distribution": [
                {
                    "@type": "cr:FileObject",
                    "@id": "arquivo",
                    "contentUrl": url(nome),
                    "sha256": hashlib.sha256(dados).hexdigest(),
                    "contentSize": str(len(dados)),
                }
            ],
        }
        conteudos[referencias[nome].rsplit("/", 1)[-1]] = json.dumps(ficha).encode()
    conteudos["croissant.json"] = json.dumps(
        {
            **base,
            "distribution": [],
            "hasPart": [{"name": nome, "url": endereco} for nome, endereco in referencias.items()],
        }
    ).encode()
    arquivos = {}
    for nome, dados in conteudos.items():
        caminho = tmp_path / nome
        caminho.write_bytes(dados)
        arquivos[nome] = (caminho, hashlib.sha256(dados).hexdigest(), len(dados))
    return arquivos


def _validar_fichas(armazem, arquivos):
    resultados, validadas = {}, []
    metadados = SimpleNamespace(CONFORMIDADE="http://mlcommons.org/croissant/1.1", validar=validadas.append)

    def registrar(nome, etapa, fn):
        resultados[(nome, etapa)] = fn()

    indice = V.validar_fichas(armazem, arquivos, registrar, metadados, P.referencias)
    return indice, resultados, validadas


def test_catalogo_com_fichas_presentes_confere_cada_produto(tmp_path):
    with _armazem(tmp_path, privado=True) as (armazem, _):
        arquivos = _arquivos_fichados(tmp_path, armazem)
        indice, resultados, validadas = _validar_fichas(armazem, arquivos)
    assert indice["estados"] == {} and len(indice["fichas"]) == 2
    assert {nome for nome, _ in resultados} == {
        "croissant.json",
        "croissant_estados.json",
        "croissant_exemplo.csv.json",
    }
    assert len(validadas) == 3


def test_catalogo_recusa_haspart_para_ficha_ausente_mesmo_sem_hash_no_indice(tmp_path):
    with _armazem(tmp_path, privado=True) as (armazem, _):
        arquivos = _arquivos_fichados(tmp_path, armazem)
        del arquivos["croissant_exemplo.csv.json"]
        with pytest.raises(V.FalhaSegura, match="ficha_catalogada_ausente_ou_fora_do_release"):
            _validar_fichas(armazem, arquivos)


def test_catalogo_recusa_ficha_que_descreve_outro_produto(tmp_path):
    with _armazem(tmp_path, privado=True) as (armazem, _):
        arquivos = _arquivos_fichados(tmp_path, armazem)
        caminho = arquivos["croissant_exemplo.csv.json"][0]
        outra = copy.deepcopy(V.ler_json(arquivos["croissant_estados.json"][0]))
        caminho.write_text(json.dumps(outra))
        with pytest.raises(V.FalhaSegura, match="ficha_nao_descreve_produto_catalogado"):
            _validar_fichas(armazem, arquivos)
