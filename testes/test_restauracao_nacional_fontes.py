"""O catálogo não aceita pacote trocado, link nem publicação irrecuperável."""

import contextlib
import hashlib
import io
import tarfile

import pytest

from raiz import restauracao_nacional_fontes as F


class Armazem:
    def __init__(self, conteudos, privado=True):
        self.conteudos, self.privado = conteudos, privado
        self.conferencias = 0

    def _exigir_privado(self):
        self.conferencias += 1
        if not self.privado:
            raise PermissionError("Release aberto")

    def _baixar_asset(self, nome, fresco=False):
        assert fresco
        return self.conteudos.get(nome)

    def _trava(self, nome, prazo):
        assert nome == "trava-publicar-PA"
        return contextlib.nullcontext()


def pacote(tmp_path, *, link=False, duplicar=False):
    p = tmp_path / "fonte.tar.gz"
    with tarfile.open(p, "w:gz") as tar:
        m = tarfile.TarInfo("PA/imoveis_1500107.csv")
        b = b"cod_imovel\nSINTETICO\n"
        if link:
            m.type, m.linkname = tarfile.SYMTYPE, "/tmp/externo"
            tar.addfile(m)
        else:
            m.size = len(b)
            tar.addfile(m, io.BytesIO(b))
            if duplicar:
                tar.addfile(m, io.BytesIO(b))
    return p


@pytest.mark.parametrize("link,duplicar", [(True, False), (False, True)])
def test_recusa_link_e_duplicidade_antes_de_extrair(tmp_path, link, duplicar):
    p = pacote(tmp_path, link=link, duplicar=duplicar)
    with pytest.raises(ValueError, match="inválidos"):
        F.extrair_uf(p, "PA", tmp_path / "extraido")
    assert not (tmp_path / "extraido").exists()


def test_download_exige_privacidade_hash_tamanho_e_caminho(tmp_path):
    dados = b"fonte"
    ref = {"nome": "fonte.json", "sha256": hashlib.sha256(dados).hexdigest(), "bytes": len(dados)}
    arm = Armazem({"fonte.json": dados})
    F.baixar(arm, ref, tmp_path / "ok")
    assert (tmp_path / "ok").read_bytes() == dados and arm.conferencias
    with pytest.raises(ValueError, match="divergente"):
        F.baixar(arm, {**ref, "bytes": 1}, tmp_path / "ruim")
    with pytest.raises(ValueError, match="inválida"):
        F.baixar(arm, {**ref, "nome": "../fora"}, tmp_path / "ruim")
    with pytest.raises(PermissionError):
        F.baixar(Armazem({}, privado=False), ref, tmp_path / "aberto")


def test_publicacao_so_devolve_referencia_apos_conferir_leitura(tmp_path, monkeypatch):
    p = tmp_path / "dados.json"
    p.write_bytes(b"{}")
    arm = Armazem({})

    def enviar(nome, arquivo, *, imutavel, arm):
        assert imutavel
        arm.conteudos[nome] = arquivo.read_bytes()

    monkeypatch.setattr(F, "enviar_arquivo", enviar)
    ref = F.publicar(arm, p, "teste", ".json")
    assert ref["acesso"] == "privado" and ref["sha256"] == hashlib.sha256(b"{}").hexdigest()
    monkeypatch.setattr(arm, "_baixar_asset", lambda *a, **kw: b"adulterado")
    with pytest.raises(ValueError, match="não recuperável"):
        F.publicar(arm, p, "teste", ".json")
