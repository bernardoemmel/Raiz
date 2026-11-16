"""A publicação conserva um conjunto de bytes mesmo com avanço de outra lane."""

import hashlib
import json
from pathlib import Path

import pytest

from raiz.executor.armazem import ArmazemLocal
from raiz.executor.snapshot_publicacao import congelar
from testes.test_armazem_release import GitHubFalso, _armazem


def test_copia_preserva_proveniencia_e_nao_acompanha_escritor(tmp_path):
    local = ArmazemLocal(tmp_path)
    chave = "saida/RN/imoveis_2400604.csv"
    meta = local.por_bytes(chave, b"cod_imovel,ha\nCAR-A,3\n", {"versao": "funil-original", "data": "2026-11-12"})
    with congelar(local, "RN") as copia:
        pasta = copia.raiz
        local.por_bytes(chave, b"cod_imovel,ha\nCAR-A,4\n", {"versao": "funil-novo"})
        local.por_bytes("saida/RN/filtros_2400604.csv", b"cod_imovel,filtro\nCAR-A,ok\n")
        assert copia.ler(chave) == b"cod_imovel,ha\nCAR-A,3\n"
        assert copia.meta(chave) == meta
        assert copia.listar("saida/RN/") == [chave]
        assert pasta.stat().st_mode & 0o777 == 0o700
        assert copia._p(chave).stat().st_mode & 0o777 == 0o600
    assert not pasta.exists()
    assert local.ler(chave) == b"cod_imovel,ha\nCAR-A,4\n"


def test_janela_entre_bytes_e_sidecar_nao_reetiqueta_versao(tmp_path, monkeypatch):
    local = ArmazemLocal(tmp_path)
    chave = "saida/RN/imoveis_2400604.csv"
    local.por_bytes(chave, b"anterior", {"versao": "original"})
    ler = local.ler
    vezes = 0

    def mudar(chave_lida):
        nonlocal vezes
        dados = ler(chave_lida)
        if chave_lida == chave and vezes == 0:
            vezes += 1
            local.por_bytes(chave, b"novo", {"versao": "nova"})
        return dados

    monkeypatch.setattr(local, "ler", mudar)
    with congelar(local, "RN") as copia:
        assert copia.ler(chave) == b"novo"
        assert copia.meta(chave)["versao"] == "nova"
        assert copia.meta(chave)["sha256"] == hashlib.sha256(b"novo").hexdigest()


def test_digest_divergente_impede_copia_sem_expor_conteudo(tmp_path):
    local = ArmazemLocal(tmp_path)
    chave = "saida/RN/imoveis_2400604.csv"
    local.por_bytes(chave, b"original", {"versao": "original"})
    local._p(chave).write_bytes(b"conteudo-privado")
    with pytest.raises(RuntimeError, match="nenhum produto foi enviado") as erro, congelar(local, "RN"):
        pytest.fail("a versão anterior não pode ser atribuída a bytes novos")
    assert "conteudo-privado" not in str(erro.value)


def test_primeiro_arquivo_ainda_sem_sidecar_nao_ganha_proveniencia(tmp_path):
    local = ArmazemLocal(tmp_path)
    destino = local._p("saida/RN/imoveis_2400604.csv")
    destino.parent.mkdir(parents=True)
    destino.write_bytes(b"cod_imovel,ha\nCAR-A,3\n")
    with pytest.raises(RuntimeError, match="nenhum produto foi enviado"), congelar(local, "RN"):
        pytest.fail("arquivo novo ainda sem metadados não está pronto para publicar")


def test_marca_copiada_antes_de_novos_bytes_impede_publicacao(tmp_path, monkeypatch):
    local = ArmazemLocal(tmp_path)
    chave = "saida/RN/imoveis_2400604.csv"
    anterior = local.por_bytes(chave, b"anterior", {"versao": "v1"})
    marca = {"tarefas": {"funil": {"versao": "v1", "saidas": {"imoveis_2400604.csv": anterior["sha256"]}}}}
    local.por_bytes("marcas/RN/2400604.json", json.dumps(marca).encode())
    ler = local.ler

    def avancar(entrada):
        dados = ler(entrada)
        if entrada == chave:
            local.por_bytes(chave, b"novo", {"versao": "v2"})
        return dados

    monkeypatch.setattr(local, "ler", avancar)
    with congelar(local, "RN", tentativas=2) as copia:
        # A marca anterior não conclui bytes da próxima execução; o resto do estado publica.
        assert json.loads(copia.ler("marcas/RN/2400604.json"))["tarefas"] == {}
        assert copia.meta(chave)["versao"] == "v2"
    assert local.meta(chave)["versao"] == "v2"
    assert json.loads(ler("marcas/RN/2400604.json")) == marca


def test_tar_ficha_quantis_cadt_e_projecao_usam_mesmo_conjunto(tmp_path, monkeypatch):
    gh = GitHubFalso()
    a = _armazem(gh, tmp_path / "espelho")
    a.garantir_uf("RN")
    original = a.local
    chave = "saida/RN/imoveis_2400604.csv"
    dados = b"cod_imovel,ha\nCAR-A,3\n"
    a.por_bytes(chave, dados, {"versao": "funil-original", "data": "2026-11-12"})
    tar_original = a._tar
    mudou = False
    copias = []

    def tar_com_avanco(uf, arquivos):
        nonlocal mudou
        pacote = tar_original(uf, arquivos)
        if "_versoes.json" in arquivos and not mudou:
            mudou = True
            original.por_bytes(chave, b"cod_imovel,ha\nCAR-A,4\n", {"versao": "funil-novo"})
            for tipo in ("imoveis", "certidoes", "filtros"):
                original.por_bytes(f"saida/RN/{tipo}_2400703.csv", b"cod_imovel,ha\nCAR-B,2\n")
        return pacote

    from raiz import cadt, quantis

    q_original, c_original = quantis.quantis_uf, cadt.cadt_uf

    def conferir_pasta(pasta):
        pasta = Path(pasta)
        assert sorted(p.name for p in pasta.glob("*.csv")) == ["imoveis_2400604.csv"]
        assert (pasta / "imoveis_2400604.csv").read_bytes() == dados
        copias.append(pasta)

    def q(pasta, *args, **kwargs):
        conferir_pasta(pasta)
        return q_original(pasta, *args, **kwargs)

    def c(pasta, *args, **kwargs):
        conferir_pasta(pasta)
        return c_original(pasta, *args, **kwargs)

    def projecao(uf, entrada):
        conferir_pasta(a.local.raiz / "saida" / uf)

    monkeypatch.setattr(a, "_tar", tar_com_avanco)
    monkeypatch.setattr(quantis, "quantis_uf", q)
    monkeypatch.setattr(cadt, "cadt_uf", c)
    monkeypatch.setattr(a, "_publicar_aberto", projecao)
    a.publico = _armazem(GitHubFalso(), tmp_path / "basico", privado=False)
    a.publicar("RN")
    membros = gh.membros("raiz_RN.tar.gz")
    assert membros["RN/imoveis_2400604.csv"] == dados
    assert sorted(n for n in membros if n.endswith(".csv")) == ["RN/imoveis_2400604.csv"]
    ficha = json.loads(gh.assets["croissant_RN.json"])
    descritos = {
        d["contentUrl"]: d["sha256"] for d in ficha["distribution"] if d.get("contentUrl", "").endswith(".csv")
    }
    assert descritos == {"RN/imoveis_2400604.csv": hashlib.sha256(dados).hexdigest()}
    assert len(copias) == 3 and len(set(copias)) == 1
    assert not copias[0].exists()
    assert a.local is original
    assert original.ler(chave) == b"cod_imovel,ha\nCAR-A,4\n"
    assert len(original.listar("saida/RN/")) == 4


def test_falha_restaura_espelho_e_mantem_saida_nova(tmp_path, monkeypatch):
    gh = GitHubFalso()
    a = _armazem(gh, tmp_path)
    a.garantir_uf("RN")
    original = a.local
    pasta = None

    def falhar(*args):
        nonlocal pasta
        pasta = a.local.raiz
        original.por_bytes("saida/RN/novo.csv", b"preservar")
        raise ValueError("falha controlada")

    monkeypatch.setattr(a, "_publicar_uf", falhar)
    with pytest.raises(ValueError, match="falha controlada"):
        a.publicar("RN")
    assert a.local is original
    assert original.ler("saida/RN/novo.csv") == b"preservar"
    assert not pasta.exists()
    assert not gh.uploads
