"""Artifacts de dados só saem do Actions após snapshot privado íntegro; evidências CI ficam."""

import copy
import io
import json
import stat
import zipfile

import pytest

from scripts import migrar_artifacts_privados as m
from testes.test_migrar_dados_privados import GitHubFalso, digest


def zip_bytes(nome="artifact.tar", *, symlink=False):
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as pacote:
        info = zipfile.ZipInfo(nome)
        if symlink:
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
        pacote.writestr(info, b"snapshot completo")
    return saida.getvalue()


class ActionsFalso(GitHubFalso):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.artifacts = []
        self.apagados_actions = []
        self.baixados_actions = []
        for n, nome in enumerate(("entradas-congeladas", "github-pages", "teste-pages", "site-agentes"), 1):
            self.artifacts.append(
                {
                    "id": n,
                    "name": nome,
                    "size_in_bytes": 999,
                    "expired": False,
                    "created_at": "2026-11-12T00:00:00Z",
                    "updated_at": "2026-11-12T00:00:00Z",
                    "workflow_run": {"id": 1000},
                }
            )
            self.bytes[n] = zip_bytes()
            self.artifacts[-1]["digest"] = "sha256:" + digest(self.bytes[n])
        self.caches = [
            {"id": 30, "key": "motor-uf-v1-PA", "size_in_bytes": 1000},
            {"id": 31, "key": "node-cache-Linux", "size_in_bytes": 500},
        ]

    def listar(self, repo, recurso, campo):
        return copy.deepcopy(self.artifacts if recurso == "artifacts" else self.caches)

    def baixar_artifact(self, repo, artifact_id, arquivo):
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(self.bytes[artifact_id])
        self.baixados_actions.append(artifact_id)

    def apagar_artifact(self, repo, artifact_id):
        self.apagados_actions.append(artifact_id)
        self.artifacts = [a for a in self.artifacts if a["id"] != artifact_id]

    def json(self, recurso, *, paginar=False):
        if "/actions/artifacts/" in recurso:
            return copy.deepcopy(next(a for a in self.artifacts if a["id"] == int(recurso.rsplit("/", 1)[-1])))
        return super().json(recurso, paginar=paginar)


def preparar(tmp_path):
    gh = ActionsFalso(tmp_path)
    rel = m.inventariar(gh, gh.repo_origem, tmp_path)
    return gh, rel


@pytest.mark.parametrize(
    "nome,esperado",
    [
        ("entradas-congeladas", True),
        ("calculado-PA", True),
        ("calculado-01", True),
        ("github-pages", True),
        ("teste-pages", False),
        ("site-agentes", False),
        ("resultado-pytest", False),
        ("calculado-../x", False),
    ],
)
def test_selecao_estrita_preserva_evidencias(nome, esperado):
    assert m.selecionado(nome) is esperado


def test_inventario_preserva_zip_e_classifica_caches_sem_dados(tmp_path):
    gh, rel = preparar(tmp_path)
    assert sorted(gh.baixados_actions) == [1, 2]
    assert [a["nome_backup"] for a in rel["assets"]] == [
        "actions-1-entradas-congeladas.zip",
        "actions-2-github-pages.zip",
    ]
    assert rel["assets"][0]["sha256"] == digest(zip_bytes())
    assert rel["assets"][0]["origem"]["size"] != gh.artifacts[0]["size_in_bytes"]
    texto = (tmp_path / "inventario-artifacts.json").read_text()
    assert "snapshot completo" not in texto
    assert m.ler_inventario(tmp_path / "inventario-artifacts.json") == rel
    caches = json.loads((tmp_path / "caches-listados.json").read_text())
    assert [c["revisar_dados"] for c in caches] == [True, False]


def test_copia_e_remocao_separadas_idempotentes(tmp_path):
    gh, rel = preparar(tmp_path)
    plano = m.releases.copiar(gh, rel, gh.repo_destino, "backup", tmp_path)
    assert not plano["executado"] and not gh.subidos and not gh.apagados_actions
    m.releases.copiar(gh, rel, gh.repo_destino, "backup", tmp_path, executar=True)
    m.releases.copiar(gh, rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert len(gh.subidos) == 2
    assert not m.remover(gh, rel, gh.repo_destino, "backup", tmp_path)["executado"]
    assert not gh.apagados_actions
    assert m.remover(gh, rel, gh.repo_destino, "backup", tmp_path, executar=True)["executado"]
    assert gh.apagados_actions == [1, 2]
    assert [a["name"] for a in gh.artifacts] == ["teste-pages", "site-agentes"]
    m.remover(gh, rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert gh.apagados_actions == [1, 2] and not gh.apagados


@pytest.mark.parametrize("falha", ["backup_incompleto", "sha", "publico", "anonimo", "origem_mudou", "novo"])
def test_falha_antes_primeiro_delete_nao_remove_nenhum_artifact(tmp_path, falha):
    gh, rel = preparar(tmp_path)
    m.releases.copiar(gh, rel, gh.repo_destino, "backup", tmp_path, executar=True)
    if falha == "backup_incompleto":
        gh.backups.pop()
    elif falha == "sha":
        gh.bytes[gh.backups[-1]["id"]] = b"divergente"
    elif falha == "publico":
        gh.privado = False
    elif falha == "anonimo":
        gh.anonimo = True
    elif falha == "origem_mudou":
        gh.artifacts[-3]["updated_at"] = "2026-11-13T00:00:00Z"
    else:
        gh.artifacts.append({"id": 555, "name": "calculado-99"})
    with pytest.raises(ValueError):
        m.remover(gh, rel, gh.repo_destino, "backup", tmp_path, executar=True)
    assert not gh.apagados_actions


def test_nao_permite_injetar_evidencia_ci_no_inventario(tmp_path):
    _, rel = preparar(tmp_path)
    rel["assets"][0]["artifact"]["name"] = "site-agentes"
    m.releases.gravar_json(tmp_path / "inventario-artifacts.json", rel)
    with pytest.raises(ValueError, match="fora da seleção"):
        m.ler_inventario(tmp_path / "inventario-artifacts.json")


@pytest.mark.parametrize("nome,symlink", [("../segredo", False), ("/absoluto", False), ("arquivo", True)])
def test_zip_nao_extrai_nem_aceita_traversal_ou_link(tmp_path, nome, symlink):
    arquivo = tmp_path / "malicioso.zip"
    arquivo.write_bytes(zip_bytes(nome, symlink=symlink))
    with pytest.raises(ValueError):
        m.conferir_zip(arquivo)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["malicioso.zip"]


def test_artifact_expirado_bloqueia_snapshot_parcial(tmp_path):
    gh = ActionsFalso(tmp_path)
    gh.artifacts[0]["expired"] = True
    with pytest.raises(ValueError, match="expirado"):
        m.inventariar(gh, gh.repo_origem, tmp_path)
    assert not gh.baixados_actions


def test_nao_permite_usar_executar_generico_para_remover(monkeypatch):
    monkeypatch.setattr("sys.argv", ["migrar", "remover", "--executar"])
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code == 2


def test_cache_valido_mas_divergente_e_rebaixado_da_origem(tmp_path):
    gh, rel = preparar(tmp_path)
    arquivo = tmp_path / "artifacts" / rel["assets"][0]["nome_backup"]
    arquivo.write_bytes(zip_bytes("outra-versao.tar"))
    gh.baixados_actions.clear()
    atualizado = m.inventariar(gh, gh.repo_origem, tmp_path)
    assert gh.baixados_actions == [1]
    assert atualizado["assets"][0]["sha256"] == digest(gh.bytes[1])


def test_download_divergente_do_digest_oficial_bloqueia_inventario(tmp_path):
    gh = ActionsFalso(tmp_path)
    gh.bytes[1] = zip_bytes("conteudo-diferente.tar")
    with pytest.raises(ValueError, match="SHA256 oficial"):
        m.inventariar(gh, gh.repo_origem, tmp_path)
    assert not (tmp_path / "inventario-artifacts.json").exists()
    assert not gh.subidos and not gh.apagados_actions


def test_sem_digest_oficial_nunca_reaproveita_zip_local(tmp_path):
    gh = ActionsFalso(tmp_path)
    for a in gh.artifacts:
        a.pop("digest")
    m.inventariar(gh, gh.repo_origem, tmp_path)
    gh.baixados_actions.clear()
    m.inventariar(gh, gh.repo_origem, tmp_path)
    assert sorted(gh.baixados_actions) == [1, 2]


def test_inventario_adulterado_nao_pode_ignorar_digest_oficial(tmp_path):
    _, rel = preparar(tmp_path)
    rel["assets"][0]["sha256"] = "0" * 64
    m.releases.gravar_json(tmp_path / "inventario-artifacts.json", rel)
    with pytest.raises(ValueError, match="SHA256 oficial"):
        m.ler_inventario(tmp_path / "inventario-artifacts.json")
