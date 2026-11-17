"""Arquivo da Raíz num balde S3 (docs/armazenamento.md): mesmo contrato do Release, outro transporte.

Fase 1: completo no balde privado e projeção básica ainda no Release público. Fase 2: projeção num balde aberto.
O S3 é simulado pelo moto e o GitHub (só as travas e o Release aberto) pelo GitHubFalso; sem rede."""

import hashlib
import io
import json
import tarfile

import boto3
import httpx
import pytest
from moto import mock_aws

from raiz.executor.armazem_balde import ArmazemBalde, partes_s3
from raiz.executor.publicacao_aberta import validar_asset_publico
from testes.test_armazem_release import GitHubFalso, _armazem

CAR = "PA-1504950-" + "A" * 32
CSV = (
    "cod_imovel,municipio,ha,carbono_ha,problema,credito_liquido_tco2_contrato\n"
    f"{CAR},Mojuí dos Campos,10,2,False,9999\n"
).encode()
PRIVADO = "s3://raiz-privado/dados"
PUBLICA = "https://dados.raiz.exemplo/dados"


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_URL", PRIVADO)
    monkeypatch.delenv("RAIZ_PUBLICO_URL_BASE", raising=False)
    with mock_aws():
        cli = boto3.client("s3", region_name="us-east-1")
        cli.create_bucket(Bucket="raiz-privado")
        cli.create_bucket(Bucket="raiz-publico")
        yield cli


def _gh_cli(gh):
    return httpx.Client(transport=httpx.MockTransport(gh))


def _balde(s3, gh, pasta, url=PRIVADO, privado=True, **kw):
    return ArmazemBalde(url, privado=privado, espelho=pasta, cliente_s3=s3, token="segredo", cliente=_gh_cli(gh), **kw)


def _objetos(s3, balde):
    return {o["Key"] for o in s3.list_objects_v2(Bucket=balde).get("Contents", [])}


def _membros(dados: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as t:
        return {m.name: t.extractfile(m).read() for m in t.getmembers() if m.isfile()}


def test_endereco_do_balde_e_validado():
    assert partes_s3("s3://raiz-privado/dados/") == ("raiz-privado", "dados")
    for ruim in ("https://x/y", "s3://UPPER/x", "s3://raiz/../x", "s3://raiz/a?b"):
        with pytest.raises(ValueError):
            partes_s3(ruim)


def test_fase1_completo_no_balde_e_basico_no_release_publico(s3, tmp_path):
    gh_publico, gh_travas = GitHubFalso(), GitHubFalso()
    gh_publico.privado = False
    aberto = _armazem(gh_publico, tmp_path / "aberto", privado=False)
    arm = _balde(s3, gh_travas, tmp_path / "privado", publico=aberto)
    arm.por_bytes("saida/PA/imoveis_1504950.csv", CSV)
    arm.por_bytes("saida/PA/desenvolvedor_1504950.csv", f"cod_imovel,tir_p50\n{CAR},42\n".encode())
    arm.publicar("PA")

    chaves = _objetos(s3, "raiz-privado")
    assert {"dados/raiz_PA.tar.gz", "dados/estados.json", "dados/croissant.json"} <= chaves
    completo = s3.get_object(Bucket="raiz-privado", Key="dados/raiz_PA.tar.gz")["Body"].read()
    assert "PA/desenvolvedor_1504950.csv" in _membros(completo)  # o completo fica só no privado
    meta = s3.head_object(Bucket="raiz-privado", Key="dados/raiz_PA.tar.gz")["Metadata"]
    assert meta["sha256"] == hashlib.sha256(completo).hexdigest()
    indice = json.loads(s3.get_object(Bucket="raiz-privado", Key="dados/estados.json")["Body"].read())
    assert indice["estados"]["PA"]["sha256"] == meta["sha256"]
    assert indice["estados"]["PA"]["url"] == "s3://raiz-privado/dados/raiz_PA.tar.gz"
    # a projeção aberta continua indo para o Release público, igual a hoje
    assert set(gh_publico.membros("raiz_PA.tar.gz")) == {"PA/imoveis_basicos_1504950.csv"}
    for nome, dados in gh_publico.assets.items():
        validar_asset_publico(nome, dados)
    # travas: refs git próprias do balde, liberadas no fim
    assert not gh_travas.refs


def test_maquina_nova_retoma_do_balde(s3, tmp_path):
    gh = GitHubFalso()
    a = _balde(s3, gh, tmp_path / "m1")
    a.por_bytes("saida/PA/imoveis_1504950.csv", CSV, {"versao": "funil-1"})
    a.publicar("PA")
    b = _balde(s3, gh, tmp_path / "m2")
    assert b.ler("saida/PA/imoveis_1504950.csv") == CSV
    assert b.manifesto()["estados"]["PA"]["municipios"] == 1
    assert {x["name"] for x in b._assets()} >= {"raiz_PA.tar.gz", "estados.json"}
    assert all(x.get("digest", "").startswith("sha256:") for x in b._assets())


def test_historico_por_car_vira_objeto_por_chave(s3, tmp_path):
    from raiz.aprendizado.transporte import _sem_balde

    a = _balde(s3, GitHubFalso(), tmp_path / "m")
    cru = _sem_balde(a)
    assert cru is a.cru and cru.prefixo == "dados/"
    # retratos ficam em subpasta e não poluem a lista de arquivos do estado
    caminho = "dados/historico/PA/1504950/" + "a" * 64 + ".json.gz"
    s3.put_object(Bucket="raiz-privado", Key=caminho, Body=b"x")
    assert "historico" not in {x["name"] for x in a._assets()}


def test_privado_recusa_balde_igual_ao_aberto(s3, tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_PUBLICO_URL_BASE", "https://raiz-privado.r2.dev/dados")
    a = _balde(s3, GitHubFalso(), tmp_path / "m")
    with pytest.raises(PermissionError):
        a.ler("saida/PA/imoveis_1504950.csv")


def test_sondagem_anonima_bloqueia_balde_aberto(s3, tmp_path, monkeypatch):
    a = _balde(s3, GitHubFalso(), tmp_path / "m")
    a._endpoint = "https://conta.r2.cloudflarestorage.com"

    class Resp:
        status_code = 200

    monkeypatch.setattr(httpx, "get", lambda *a, **k: Resp())
    with pytest.raises(PermissionError, match="sem credencial"):
        a._exigir_privado()
    a._privacidade_conferida = False
    Resp.status_code = 400  # resposta normal do R2 a pedido sem assinatura
    a._exigir_privado()


def test_fase2_projecao_aberta_em_balde_publico(s3, tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_PUBLICO_URL_BASE", PUBLICA)
    gh = GitHubFalso()
    aberto = _balde(s3, gh, tmp_path / "aberto", url="s3://raiz-publico/dados", privado=False)
    arm = _balde(s3, gh, tmp_path / "privado", publico=aberto)
    arm.por_bytes("saida/PA/imoveis_1504950.csv", CSV)
    arm.publicar("PA")
    publicos = _objetos(s3, "raiz-publico")
    assert "dados/raiz_PA.tar.gz" in publicos and "dados/estados.json" in publicos
    basico = s3.get_object(Bucket="raiz-publico", Key="dados/raiz_PA.tar.gz")["Body"].read()
    assert set(_membros(basico)) == {"PA/imoveis_basicos_1504950.csv"}
    manifesto = s3.get_object(Bucket="raiz-publico", Key="dados/estados.json")["Body"].read()
    validar_asset_publico("estados.json", manifesto, repo=aberto.repo, tag=aberto.tag)
    assert json.loads(manifesto)["estados"]["PA"]["url"] == f"{PUBLICA}/raiz_PA.tar.gz"
    for chave in publicos:
        corpo = s3.get_object(Bucket="raiz-publico", Key=chave)["Body"].read()
        validar_asset_publico(chave.removeprefix("dados/"), corpo, repo=aberto.repo, tag=aberto.tag)
    # o aberto nunca recebe tabela completa
    with pytest.raises(ValueError):
        aberto._subir(aberto._release(), "raiz_PA.tar.gz", ArmazemBalde._tar("PA", {"imoveis_1504950.csv": CSV}))


def test_do_config_escolhe_o_balde_quando_configurado(monkeypatch, tmp_path):
    from raiz.executor import armazem

    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_URL", PRIVADO)
    monkeypatch.setenv("RAIZ_S3_ENDPOINT", "https://conta.r2.cloudflarestorage.com")
    monkeypatch.setenv("RAIZ_S3_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("RAIZ_S3_SECRET_ACCESS_KEY", "s")
    from raiz.config import config

    config.cache_clear() if hasattr(config, "cache_clear") else None
    a = armazem.do_config("release-github://bernardoemmel/Raiz/dados")
    assert isinstance(a, ArmazemBalde) and a.privado
    assert a.publico.repo == "bernardoemmel/Raiz" and a.publico.tag == "dados"  # aberto segue no Release
    assert armazem.destino_privado() is None  # quem só fala com Release falha fechado
    ck = armazem.arquivo_privado_configurado("-checkpoints")
    assert ck.base_s3 == "s3://raiz-privado/dados-checkpoints/"
    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_URL", "release-github://bernardoemmel/Raiz/dados-privados")
    assert not isinstance(armazem.do_config("release-github://bernardoemmel/Raiz/dados"), ArmazemBalde)


def test_migracao_mapeia_cada_release(tmp_path):
    import importlib.util

    from raiz import RAIZ_REPO

    spec = importlib.util.spec_from_file_location("migrar", RAIZ_REPO / "scripts" / "migrar_releases_para_balde.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.destino("dados-privados", "raiz_PA.tar.gz", "dados")["chave"] == "dados/raiz_PA.tar.gz"
    assert m.destino("dados-privados-checkpoints", "c.tar.gz", "dados")["chave"] == "dados-checkpoints/c.tar.gz"
    h = m.destino("historico-2026-11-17", "historico_PA_" + "b" * 64 + ".tar.gz", "dados")
    assert h == {"tipo": "historico", "chave": "dados/historico/"}
    assert m.destino("dados", "estados.json", "dados")["chave"] == "releases-publicos/dados/estados.json"
    with pytest.raises(ValueError):
        m.destino("dados", "../x", "dados")
