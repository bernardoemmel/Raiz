"""O arquivo privado precede a publicação; o aberto só aceita a projeção conhecida."""

import io
import json

import geopandas as gpd
import httpx
import pytest
from shapely.geometry import box

from raiz.executor.armazem import ArmazemRelease
from raiz.executor.publicacao_aberta import COLUNAS_BASICAS, projetar_csvs, projetar_geo, validar_asset_publico
from testes.test_armazem_release import REPO, TAG, GitHubFalso, _armazem

CAR = "PA-1504950-" + "A" * 32
CSV = (
    "cod_imovel,municipio,ha,carbono_ha,problema,credito_liquido_tco2_contrato\n"
    f"{CAR},Mojuí dos Campos,10,2,False,9999\n"
).encode()


def test_projecao_preserva_todos_os_cars_sem_metricas():
    pequena = "PA-1504950-" + "B" * 32
    dados = CSV + f"{pequena},Mojuí dos Campos,0.01,0.001,True,8888\n".encode()
    publicos = projetar_csvs("PA", {"imoveis_1504950.csv": dados, "desenvolvedor_1504950.csv": b"privado"})
    assert set(publicos) == {"imoveis_basicos_1504950.csv"}
    basico = publicos["imoveis_basicos_1504950.csv"].decode()
    assert basico.splitlines()[0].split(",") == list(COLUNAS_BASICAS)
    assert CAR in basico and pequena in basico and ",apto" in basico and ",com_pendencia" in basico
    assert "9999" not in basico and "8888" not in basico and "credito" not in basico
    validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", publicos))


@pytest.mark.parametrize("nome", ["imoveis_1504950.csv", "ficha_1504950.csv", "terra_1504950.csv", "_versoes.json"])
def test_upload_aberto_recusa_qualquer_tabela_completa(nome):
    with pytest.raises(ValueError):
        validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", {nome: CSV}))


def test_contorno_recriado_remove_metricas_e_metadados_privados():
    g = gpd.GeoDataFrame({"cod_imovel": [CAR], "credito": [9999]}, geometry=[box(-50, -4, -49, -3)], crs=4674)
    g.attrs["dado_privado"] = "reservado"
    bruto = io.BytesIO()
    g.to_parquet(bruto, index=False)
    with pytest.raises(ValueError, match="atributos privados"):
        validar_asset_publico(
            "raiz_geo_PA.tar.gz", ArmazemRelease._tar("PA", {"geo_1504950.parquet": bruto.getvalue()})
        )
    publico = projetar_geo(bruto.getvalue())
    validar_asset_publico("raiz_geo_PA.tar.gz", ArmazemRelease._tar("PA", {"geo_1504950.parquet": publico}))
    assert "credito" not in gpd.read_parquet(io.BytesIO(publico)).columns


def test_dupla_publicacao_guarda_integra_antes_de_expor_basico(tmp_path, monkeypatch):
    gh_privado, gh_publico = GitHubFalso(), GitHubFalso()
    gh_publico.privado = False
    aberto = _armazem(gh_publico, tmp_path / "aberto", privado=False)
    privado = _armazem(gh_privado, tmp_path / "privado", publico=aberto)
    privado.por_bytes("saida/PA/imoveis_1504950.csv", CSV)
    privado.por_bytes("saida/PA/desenvolvedor_1504950.csv", f"cod_imovel,tir_p50\n{CAR},42\n".encode())
    subir = aberto._subir

    def somente_depois_do_arquivo(*args, **kwargs):
        assert "estados.json" in gh_privado.assets
        assert gh_privado.membros("raiz_PA.tar.gz")["PA/imoveis_1504950.csv"] == CSV
        return subir(*args, **kwargs)

    monkeypatch.setattr(aberto, "_subir", somente_depois_do_arquivo)
    privado.publicar("PA")
    assert "PA/desenvolvedor_1504950.csv" in gh_privado.membros("raiz_PA.tar.gz")
    assert set(gh_publico.membros("raiz_PA.tar.gz")) == {"PA/imoveis_basicos_1504950.csv"}
    assert set(gh_publico.assets) == {"raiz_PA.tar.gz", "estados.json"}
    validar_asset_publico("estados.json", gh_publico.assets["estados.json"])
    assert json.loads(gh_publico.assets["estados.json"])["escopo"] == "publico_basico"


def test_publico_por_engano_nao_recebe_nem_le_snapshot(tmp_path):
    gh = GitHubFalso()
    gh.privado = False
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {"imoveis_1504950.csv": CSV})
    privado = _armazem(gh, tmp_path)
    with pytest.raises(PermissionError, match="rascunho"):
        privado.ler("saida/PA/imoveis_1504950.csv")
    with pytest.raises(PermissionError, match="rascunho"):
        privado.publicar("PA")
    assert not gh.uploads and not gh.downloads


def test_rascunho_autenticado_lookup_por_lista_e_fechado_apos_publicacao(tmp_path):
    gh = GitHubFalso()
    gh.privado, gh.rascunho = False, True
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {"imoveis_1504950.csv": CSV})

    def transporte(req):
        if req.url.path.endswith(f"/releases/tags/{TAG}"):
            return httpx.Response(404)
        if req.url.path.endswith("/releases"):
            assert req.headers["authorization"] == "Bearer segredo"
            return httpx.Response(200, json=[{"id": 7, "tag_name": TAG, "draft": gh.rascunho}])
        return gh(req)

    arm = ArmazemRelease(
        REPO,
        TAG,
        tmp_path,
        token="segredo",
        privado=True,
        cliente=httpx.Client(transport=httpx.MockTransport(transporte)),
    )
    assert arm.ler("saida/PA/imoveis_1504950.csv") == CSV
    assert gh.downloads and not gh.uploads
    gh.rascunho = False
    # Cada nova leitura remota confere de novo; uma mudança de visibilidade fecha o leitor.
    with pytest.raises(PermissionError, match="rascunho"):
        arm._baixar_asset("raiz_PA.tar.gz")


def test_manifesto_nao_aceita_atributo_privado_em_geo():
    info = {
        "escopo": "publico_basico",
        "versao_publicacao": 1,
        "url": f"https://github.com/{REPO}/releases/download/{TAG}/raiz_PA.tar.gz",
        "geo": {"escopo": "publico_basico", "credito": 999},
    }
    manifesto = {"escopo": "publico_basico", "versao_publicacao": 1, "repo": REPO, "tag": TAG, "estados": {"PA": info}}
    with pytest.raises(ValueError, match="privado"):
        validar_asset_publico("estados.json", json.dumps(manifesto).encode())


def test_recorte_municipal_preserva_imovel_limitrofe_sem_reescrever_car():
    dados = projetar_csvs("PA", {"imoveis_1507300.csv": CSV})
    pacote = ArmazemRelease._tar("PA", dados)
    validar_asset_publico("raiz_PA.tar.gz", pacote)
    assert CAR.encode() in dados["imoveis_basicos_1507300.csv"]
    assert b",1507300," in dados["imoveis_basicos_1507300.csv"]
