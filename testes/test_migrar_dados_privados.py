"""Migração só remove originais após backup íntegro, protegido e indisponível anonimamente."""

import copy
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from scripts import migrar_dados_privados as m


def digest(dados):
    return hashlib.sha256(dados).hexdigest()


class GitHubFalso:
    def __init__(self, tmp_path):
        self.repo_origem = "empresa/produto"
        self.repo_destino = "empresa/arquivo"
        self.privado = True
        self.draft = False
        self.anonimo = False
        self.subidos = []
        self.apagados = []
        self.originais = []
        self.backups = []
        self.bytes = {}
        self.rel = {"versao": 1, "origem": self.repo_origem, "releases": [{"id": 1, "tag": "dados"}], "assets": []}
        for n in (1, 2):
            dado = f"coluna\nvalor-{n}\n".encode()
            local = tmp_path / f"arquivo{n}.csv"
            local.write_bytes(dado)
            meta = {
                "id": n,
                "name": local.name,
                "size": len(dado),
                "updated_at": "2026-11-12T00:00:00Z",
                "digest": "sha256:" + digest(dado),
            }
            self.originais.append(meta)
            self.bytes[n] = dado
            self.rel["assets"].append(
                {
                    "origem": dict(meta),
                    "arquivo_local": str(local),
                    "sha256": digest(dado),
                    "nome_backup": f"historico-1-{n}-{local.name}",
                }
            )

    def json(self, recurso, *, paginar=False):
        if recurso == f"repos/{self.repo_destino}":
            return {"private": self.privado}
        if recurso == f"repos/{self.repo_destino}/releases":
            lista = [{"id": 2, "tag_name": "backup", "draft": self.draft}]
            if self.repo_destino == self.repo_origem:
                lista.append({"id": 1, "tag_name": "dados", "draft": False})
            return lista
        if recurso == f"repos/{self.repo_origem}/releases":
            return [{"id": 1, "tag_name": "dados", "draft": False}]
        if recurso == f"repos/{self.repo_destino}/releases/2":
            return {"id": 2, "tag_name": "backup", "draft": self.draft}
        if recurso == f"repos/{self.repo_destino}/releases/2/assets":
            return copy.deepcopy(self.backups)
        if recurso == f"repos/{self.repo_origem}/releases/1/assets":
            return copy.deepcopy(self.originais)
        if recurso.startswith(f"repos/{self.repo_origem}/releases/assets/"):
            asset_id = int(recurso.rsplit("/", 1)[-1])
            return dict(next(a for a in self.originais if a["id"] == asset_id))
        raise AssertionError(recurso)

    def baixar(self, repo, asset_id, arquivo):
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(self.bytes[asset_id])

    def subir(self, repo, tag, arquivo, nome):
        dado = arquivo.read_bytes()
        asset_id = 100 + len(self.backups)
        self.bytes[asset_id] = dado
        self.backups.append(
            {
                "id": asset_id,
                "name": nome,
                "size": len(dado),
                "digest": "sha256:" + digest(dado),
                "updated_at": "2026-11-12T01:00:00Z",
            }
        )
        self.subidos.append(nome)

    def conferir_anonimo(self, repo, asset):
        if self.anonimo:
            raise ValueError("O backup respondeu ao acesso sem autenticação")

    def apagar(self, repo, asset_id):
        self.apagados.append(asset_id)
        self.originais = [a for a in self.originais if a["id"] != asset_id]


def test_dry_run_nao_copia_e_copia_idempotente_confere_download(tmp_path):
    gh = GitHubFalso(tmp_path)
    plano = m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path)
    assert not plano["executado"] and not gh.subidos
    feito = m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert feito["executado"] and len(feito["verificacao"]["assets"]) == 2
    assert len(gh.subidos) == 2 and not gh.apagados
    m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert len(gh.subidos) == 2
    assert (tmp_path / "backup-verificado.json").is_file()


def test_remocao_separada_e_idempotente(tmp_path):
    gh = GitHubFalso(tmp_path)
    m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    plano = m.remover(gh, gh.rel, gh.repo_destino, "backup", tmp_path)
    assert not plano["executado"] and not gh.apagados
    assert all(a["acao"] == "remover_original" for a in plano["acoes"])
    resposta = m.remover(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert resposta["executado"] and gh.apagados == [1, 2]
    m.remover(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert gh.apagados == [1, 2]


@pytest.mark.parametrize("falha", ["publico", "anonimo", "bytes", "backup_ausente", "origem_mudou", "asset_novo"])
def test_nenhum_original_e_apagado_se_uma_guarda_falha(tmp_path, falha):
    gh = GitHubFalso(tmp_path)
    m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    if falha == "publico":
        gh.privado = False
    elif falha == "anonimo":
        gh.anonimo = True
    elif falha == "bytes":
        gh.bytes[gh.backups[1]["id"]] = b"alterado"
    elif falha == "backup_ausente":
        gh.backups.pop()
    elif falha == "asset_novo":
        gh.originais.append({**gh.originais[0], "id": 50})
    else:
        gh.originais[-1]["updated_at"] = "2026-11-13T00:00:00Z"
    with pytest.raises(ValueError):
        m.remover(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert not gh.apagados


def test_draft_protegido_no_repo_publico_e_aceito(tmp_path):
    gh = GitHubFalso(tmp_path)
    gh.repo_destino = gh.repo_origem
    gh.privado = False
    gh.draft = True
    m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert len(gh.subidos) == 2
    gh.draft = False
    with pytest.raises(ValueError, match="draft"):
        m.remover(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert not gh.apagados


def test_nao_substitui_backup_existente_diferente(tmp_path):
    gh = GitHubFalso(tmp_path)
    m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    gh.backups[0]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="não sobrescrever"):
        m.copiar(gh, gh.rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert len(gh.subidos) == 2


def tar_de(tmp_path, nome="UF/ficha_1505536.csv", tipo=tarfile.REGTYPE, dados=b"cod_imovel,credito_p50\ncar,20\n"):
    arquivo = tmp_path / "pacote.tar.gz"
    with tarfile.open(arquivo, "w:gz") as tar:
        membro = tarfile.TarInfo(nome)
        membro.type = tipo
        membro.size = len(dados) if tipo == tarfile.REGTYPE else 0
        if tipo in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
            membro.linkname = "/tmp/fora"
        tar.addfile(membro, io.BytesIO(dados) if membro.size else None)
    return arquivo


@pytest.mark.parametrize("nome", ["../fora.csv", "/tmp/fora.csv", "UF/../../fora.csv", "C:/fora.csv", "UF\\fora.csv"])
def test_archive_traversal_recusado_sem_extrair(tmp_path, nome):
    arq = tar_de(tmp_path, nome)
    with pytest.raises(ValueError, match="caminho"):
        m.inspecionar(arq, arq.name)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pacote.tar.gz"]


@pytest.mark.parametrize("tipo", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE])
def test_links_e_dispositivos_no_tar_recusados(tmp_path, tipo):
    arq = tar_de(tmp_path, tipo=tipo)
    with pytest.raises(ValueError, match="link, dispositivo"):
        m.inspecionar(arq, arq.name)


def test_inventario_guarda_schema_e_hash_sem_linhas(tmp_path):
    arq = tar_de(tmp_path, dados=b"cod_imovel,credito_p50\nconteudo-nao-publicar,20\n")
    membros = m.inspecionar(arq, arq.name)
    assert membros[0]["classe"] == "camada_paga" and membros[0]["camadas"] == ["ficha"]
    assert membros[0]["colunas"] == ["cod_imovel", "credito_p50"]
    assert "conteudo-nao-publicar" not in json.dumps(membros)
    assert membros[0]["sha256"] == digest(b"cod_imovel,credito_p50\nconteudo-nao-publicar,20\n")
    assert m.classe_membro("UF/extras_direto_1505536.csv", ["cod_imovel"])[1] == ["extras_direto"]
    assert m.classe_membro("UF/imoveis_1505536.csv", ["cod_imovel", "embargo_ha"])[0].startswith("snapshot_privado")


def test_cabecalho_parquet_e_classe_geo(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    arquivo = tmp_path / "geo_1505536.parquet"
    pq.write_table(pa.table({"cod_imovel": ["exemplo"], "geometry": [b"geometria"]}), arquivo)
    assert m.inspecionar(arquivo, arquivo.name)[0]["classe"] == "mapa_basico"
    pq.write_table(pa.table({"cod_imovel": ["exemplo"], "geometry": [b"geometria"], "risco": ["alto"]}), arquivo)
    assert m.inspecionar(arquivo, arquivo.name)[0]["classe"] == "camada_paga"


def test_paginacao_gh_antigo_sem_slurp(monkeypatch):
    gh = m.GitHub()
    monkeypatch.setattr(gh, "comando", lambda args: b'[ {"id": 1} ]\n[{"id":2}]\n')
    assert gh.json("repos/org/repo/releases", paginar=True) == [{"id": 1}, {"id": 2}]


def test_upload_usa_nome_real_do_backup_sem_rotulo_hash(tmp_path, monkeypatch):
    gh = m.GitHub()
    arq = tmp_path / "local.csv"
    arq.write_bytes(b"snapshot")
    nomes = []

    def comando(args, **kwargs):
        pronto = Path(args[3])
        nomes.append(pronto.name)
        assert pronto.read_bytes() == b"snapshot" and "#" not in str(pronto)
        assert "--clobber" not in args
        return b""

    monkeypatch.setattr(gh, "comando", comando)
    gh.subir("org/repo", "backup", arq, "historico-1-2-publico.csv")
    assert nomes == ["historico-1-2-publico.csv"]


@pytest.mark.parametrize("digest_remoto", [True, False])
def test_inventario_nao_confia_em_cache_corrompido_com_mesmo_tamanho(tmp_path, monkeypatch, digest_remoto):
    gh = GitHubFalso(tmp_path)
    if not digest_remoto:
        gh.originais[0]["digest"] = None
    baixar = gh.baixar
    downloads = []

    def registrar(repo, asset_id, arquivo):
        downloads.append(asset_id)
        baixar(repo, asset_id, arquivo)

    monkeypatch.setattr(gh, "baixar", registrar)
    pasta = tmp_path / "inventario"
    primeira = m.inventariar(gh, gh.repo_origem, pasta, paralelos=1)
    local = Path(primeira["assets"][0]["arquivo_local"])
    local.write_bytes(b"X" * local.stat().st_size)
    segunda = m.inventariar(gh, gh.repo_origem, pasta, paralelos=1)
    assert downloads.count(gh.originais[0]["id"]) == 2
    assert local.read_bytes() == gh.bytes[gh.originais[0]["id"]]
    assert segunda["assets"][0]["sha256"] == digest(gh.bytes[gh.originais[0]["id"]])
    # A prova de backup e a remoção devem cobrir os bytes remotos saudáveis.
    m.copiar(gh, segunda, gh.repo_destino, "backup", pasta, executar=True)
    backup = next(a for a in gh.backups if a["name"] == segunda["assets"][0]["nome_backup"])
    assert gh.bytes[backup["id"]] == gh.bytes[gh.originais[0]["id"]]
    m.remover(gh, segunda, gh.repo_destino, "backup", pasta, executar=True)
    assert gh.apagados == [1, 2]


@pytest.mark.parametrize("digest_remoto,downloads_esperados", [(True, 1), (False, 2)])
def test_cache_so_e_reutilizado_com_sha256_remoto_conferido(tmp_path, monkeypatch, digest_remoto, downloads_esperados):
    gh = GitHubFalso(tmp_path)
    if not digest_remoto:
        gh.originais[0]["digest"] = None
    baixar = gh.baixar
    downloads = []

    def registrar(repo, asset_id, arquivo):
        downloads.append(asset_id)
        baixar(repo, asset_id, arquivo)

    monkeypatch.setattr(gh, "baixar", registrar)
    for _ in range(2):
        m.inventariar(gh, gh.repo_origem, tmp_path / "inventario", paralelos=1)
    assert downloads.count(gh.originais[0]["id"]) == downloads_esperados
