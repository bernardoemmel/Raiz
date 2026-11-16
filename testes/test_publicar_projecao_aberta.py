"""Corte público simulado: integralidade do backup precede qualquer remoção."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from raiz.executor.armazem import ArmazemRelease
from raiz.executor.publicacao_aberta import validar_asset_publico
from scripts import migrar_dados_privados as m
from scripts import publicar_projecao_aberta as corte

CAR = "PA-1505536-" + "A" * 32


class GitHubFalso:
    """Mesmo repo público com destino draft; API não permite substituir sem DELETE."""

    repo = "empresa/produto"
    tag = "dados-privados"

    def __init__(self):
        self.releases = {
            1: {"id": 1, "tag_name": "dados", "draft": False},
            2: {"id": 2, "tag_name": "dados-privados", "draft": True},
            3: {"id": 3, "tag_name": "historico", "draft": False},
        }
        self.assets = {1: [], 2: [], 3: []}
        self.bytes = {}
        self.eventos = []
        self.contador = 0
        self.anonimo = False
        self.antes_apagar = None
        self.antes_subir = None
        self.criar(
            1,
            "raiz_PA.tar.gz",
            ArmazemRelease._tar(
                "PA",
                {
                    "imoveis_1505536.csv": f"cod_imovel,municipio,credito_p50\n{CAR},Parauapebas,999\n".encode(),
                    "ficha_1505536.csv": f"cod_imovel,credito_p50\n{CAR},999\n".encode(),
                    "desconhecido.csv": b"campo\nnao-publicar\n",
                },
            ),
        )
        self.criar(
            1, "raiz_camadas_PA.tar.gz", ArmazemRelease._tar("PA", {"terra_1505536.csv": b"codigo,risco\n1,alto\n"})
        )
        self.criar(1, "raiz_controle_PA.json", b'{"estado":{"segredo":"nao-publicar"}}')
        self.criar(1, "URTX.kml", b"arquivo-desconhecido-mantido-so-no-backup")
        self.criar(
            1,
            "estados.json",
            json.dumps(
                {
                    "estados": {
                        "PA": {"municipios": 1, "erro": "nao-publicar"},
                        "AM": {"municipios": 0, "situacao": "com_erro"},
                    }
                }
            ).encode(),
        )
        self.criar(3, "raiz_PA.tar.gz", ArmazemRelease._tar("PA", {"antigo.csv": b"campo\nnao-publicar\n"}))
        self.ids_originais = {a["id"] for rid, lista in self.assets.items() if rid != 2 for a in lista}

    def criar(self, release_id, nome, dados):
        self.contador += 1
        asset = {
            "id": self.contador,
            "name": nome,
            "size": len(dados),
            "digest": "sha256:" + hashlib.sha256(dados).hexdigest(),
            "updated_at": "2026-11-12T00:00:00Z",
        }
        self.assets[release_id].append(asset)
        self.bytes[asset["id"]] = dados
        return asset

    def json(self, recurso, *, paginar=False):
        if recurso == f"repos/{self.repo}":
            return {"private": False}
        if recurso == f"repos/{self.repo}/releases":
            return copy.deepcopy(list(self.releases.values()))
        if recurso.startswith(f"repos/{self.repo}/releases/assets/"):
            asset_id = int(recurso.rsplit("/", 1)[-1])
            return copy.deepcopy(next(a for lista in self.assets.values() for a in lista if a["id"] == asset_id))
        partes = recurso.split("/")
        release_id = int(partes[4])
        return copy.deepcopy(self.assets[release_id] if partes[-1] == "assets" else self.releases[release_id])

    def baixar(self, repo, asset_id, arquivo):
        self.eventos.append(("baixar", asset_id))
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(self.bytes[asset_id])

    def subir(self, repo, tag, arquivo, nome):
        release_id = next(r["id"] for r in self.releases.values() if r["tag_name"] == tag)
        if self.antes_subir:
            self.antes_subir(release_id, nome)
        assert all(a["name"] != nome for a in self.assets[release_id]), "upload nunca usa clobber"
        self.eventos.append(("subir", release_id, nome))
        self.criar(release_id, nome, arquivo.read_bytes())

    def conferir_anonimo(self, repo, asset):
        self.eventos.append(("404", asset["id"]))
        if self.anonimo or not self.releases[2]["draft"]:
            raise ValueError("Backup acessível anonimamente")

    def apagar(self, repo, asset_id):
        if self.antes_apagar:
            self.antes_apagar(asset_id)
        assert asset_id in self.ids_originais, "jamais apaga asset criado depois do inventário"
        self.eventos.append(("apagar", asset_id))
        for release_id in self.assets:
            self.assets[release_id] = [a for a in self.assets[release_id] if a["id"] != asset_id]


def inventario(gh, tmp_path):
    return m.inventariar(gh, gh.repo, tmp_path / "snapshot", paralelos=1)


def executar(gh, rel, tmp_path, *, tag_publica="dados", **kwargs):
    return corte.cortar(gh, rel, gh.repo, gh.tag, tag_publica, tmp_path / "corte", **kwargs)


@pytest.mark.parametrize("tag_publica", ["dados", "publico-teste"])
def test_prepara_sem_rede_allowlist_estados_parciais_e_sem_historico(tmp_path, tag_publica):
    gh = GitHubFalso()
    gh.releases[1]["tag_name"] = tag_publica
    rel = inventario(gh, tmp_path)
    plano = executar(gh, rel, tmp_path, tag_publica=tag_publica)
    assert not plano["executado"]
    assert not any(e[0] in {"apagar", "subir"} for e in gh.eventos)
    for arquivo in (tmp_path / "corte" / "publico").iterdir():
        validar_asset_publico(arquivo.name, arquivo.read_bytes(), repo=gh.repo, tag=tag_publica)
    indice = json.loads((tmp_path / "corte" / "publico" / "estados.json").read_bytes())
    assert set(indice["estados"]) == {"PA", "AM"}
    assert indice["estados"]["AM"]["municipios"] == 0
    assert "nao-publicar" not in json.dumps(indice)
    assert {a["nome"] for a in plano["projecoes"]} == {"raiz_PA.tar.gz", "raiz_AM.tar.gz", "estados.json"}


def test_backup_inteiro_verificado_antes_primeiro_delete_e_indice_por_ultimo(tmp_path):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)
    plano = executar(gh, rel, tmp_path, executar=True)
    assert plano["executado"]
    primeiro_delete = next(i for i, e in enumerate(gh.eventos) if e[0] == "apagar")
    eventos_antes = gh.eventos[:primeiro_delete]
    backups = {a["name"]: a for a in gh.assets[2]}
    for item in rel["assets"]:
        backup = backups[item["nome_backup"]]
        assert ("baixar", backup["id"]) in eventos_antes
        assert ("404", backup["id"]) in eventos_antes
        assert gh.bytes[backup["id"]] == Path(item["arquivo_local"]).read_bytes()
    assert "URTX.kml" not in backups
    assert "raiz_camadas_PA.tar.gz" in backups and "raiz_controle_PA.json" in backups
    assert [e[2] for e in gh.eventos if e[0:2] == ("subir", 1)][-1] == "estados.json"
    assert not gh.assets[3]
    assert {a["id"] for a in gh.assets[1]}.isdisjoint(gh.ids_originais)
    for a in gh.assets[1]:
        validar_asset_publico(a["name"], gh.bytes[a["id"]], repo=gh.repo, tag="dados")
    prova = json.loads(gh.bytes[backups[plano["inventario_privado"]]["id"]])
    assert all("arquivo_local" not in item for item in prova["assets"])
    assert any(a["name"].startswith("corte-") and "concluido" in a["name"] for a in gh.assets[2])
    assert len(plano["originais_com_404_anonimo"]) == 4  # camadas, controle, desconhecido e histórico


@pytest.mark.parametrize(
    "falha", ["anonimo", "backup_corrompido", "canonico_conflitante", "novo", "mutado", "release", "tag_mudou"]
)
def test_nenhuma_remocao_se_backup_ou_inventario_divergir(tmp_path, falha):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)
    if falha == "anonimo":
        gh.anonimo = True
    elif falha == "backup_corrompido":
        item = rel["assets"][-1]
        gh.criar(2, item["nome_backup"], b"alterado")
    elif falha == "canonico_conflitante":
        gh.criar(2, "estados.json", b'{"origem":"diferente"}')
    elif falha == "novo":
        gh.criar(1, "novo.csv", b"nunca-apagar-sem-backup")
    elif falha == "mutado":
        gh.assets[1][-1]["updated_at"] = "2026-11-13T00:00:00Z"
    elif falha == "tag_mudou":
        gh.releases[1]["tag_name"] = "dados-renomeados"
    else:
        gh.releases[4] = {"id": 4, "tag_name": "novo-release", "draft": False}
        gh.assets[4] = []
    with pytest.raises(ValueError):
        executar(gh, rel, tmp_path, executar=True)
    assert not any(e[0] == "apagar" for e in gh.eventos)


def test_projecao_invalida_nao_faz_nenhuma_mutacao(tmp_path):
    gh = GitHubFalso()
    gh.assets[1] = [a for a in gh.assets[1] if a["name"] != "raiz_PA.tar.gz"]
    gh.criar(1, "raiz_PA.tar.gz", ArmazemRelease._tar("PA", {"imoveis_1505536.csv": b"cod_imovel\nINVALIDO\n"}))
    rel = inventario(gh, tmp_path)
    with pytest.raises(ValueError, match="CAR inválido"):
        executar(gh, rel, tmp_path, executar=True)
    assert not any(e[0] in {"subir", "apagar"} for e in gh.eventos)


def test_retomada_em_outro_diretorio_apos_delete_sem_upload(tmp_path):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)

    def interromper(release_id, nome):
        if release_id == 1 and nome == "raiz_PA.tar.gz":
            raise RuntimeError("rede interrompida depois do delete")

    gh.antes_subir = interromper
    with pytest.raises(RuntimeError, match="rede interrompida"):
        executar(gh, rel, tmp_path, executar=True)
    nome = next(a["name"] for a in gh.assets[2] if a["name"].endswith("-inventario.json"))
    assert any(e[0] == "apagar" for e in gh.eventos)
    outro = tmp_path / "outra-maquina"
    outro.mkdir()
    rel_novo = corte.retomar(gh, gh.repo, gh.tag, gh.repo, nome, outro)
    gh.antes_subir = None
    feito = executar(gh, rel_novo, outro, executar=True, retomada=True)
    assert feito["executado"] and feito["inventario_privado"] == nome
    numero_uploads = sum(e[0] == "subir" and e[1] == 1 for e in gh.eventos)
    executar(gh, rel_novo, outro, executar=True, retomada=True)
    assert sum(e[0] == "subir" and e[1] == 1 for e in gh.eventos) == numero_uploads
    assert not gh.assets[3]


def test_novo_asset_durante_publicacao_interrompe_sem_remover_camadas(tmp_path):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)

    def concorrencia(release_id, nome):
        if release_id == 1 and nome == "raiz_AM.tar.gz":
            gh.criar(1, "dados-novos.csv", b"nao-apagar")

    gh.antes_subir = concorrencia
    with pytest.raises(ValueError, match="Asset novo"):
        executar(gh, rel, tmp_path, executar=True)
    assert not any(e[0] == "apagar" for e in gh.eventos)
    assert any(a["name"] == "raiz_camadas_PA.tar.gz" for a in gh.assets[1])


def test_backup_desaparecido_durante_corte_bloqueia_proximo_delete(tmp_path):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)

    def perder_backup(release_id, nome):
        if release_id == 1:
            gh.assets[2] = [a for a in gh.assets[2] if not a["name"].startswith("historico-3-")]

    gh.antes_subir = perder_backup
    with pytest.raises(ValueError, match="Backup verificado"):
        executar(gh, rel, tmp_path, executar=True)
    assert not any(e[0] == "apagar" for e in gh.eventos)


def test_mesmo_destino_e_recusado(tmp_path):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)
    with pytest.raises(ValueError, match="separado"):
        corte.cortar(gh, rel, gh.repo, "dados", "dados", tmp_path, executar=True)
    assert not any(e[0] in {"apagar", "subir"} for e in gh.eventos)


def test_retomada_confere_conteudo_contra_identificador_do_inventario(tmp_path):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)
    feito = executar(gh, rel, tmp_path, executar=True)
    registro = next(a for a in gh.assets[2] if a["name"] == feito["inventario_privado"])
    alterado = json.loads(gh.bytes[registro["id"]])
    alterado["gerado_em"] = "2026-11-13T00:00:00Z"
    novo = json.dumps(alterado).encode()
    gh.bytes[registro["id"]] = novo
    registro.update(size=len(novo), digest="sha256:" + hashlib.sha256(novo).hexdigest())
    with pytest.raises(ValueError, match="identificador de retomada"):
        corte.retomar(gh, gh.repo, gh.tag, gh.repo, feito["inventario_privado"], tmp_path)


def test_nao_declara_conclusao_se_url_original_ainda_responde_anonimamente(tmp_path, monkeypatch):
    gh = GitHubFalso()
    rel = inventario(gh, tmp_path)
    original = gh.conferir_anonimo

    def conferir(repo, asset):
        if asset.get("browser_download_url") and asset["id"] in gh.ids_originais:
            raise ValueError("URL original ainda responde anonimamente")
        original(repo, asset)

    monkeypatch.setattr(gh, "conferir_anonimo", conferir)
    with pytest.raises(ValueError, match="URL original"):
        executar(gh, rel, tmp_path, executar=True)
    assert not any("-concluido-" in a["name"] for a in gh.assets[2])
    assert len([a for a in gh.assets[2] if a["name"].startswith("historico-")]) == len(rel["assets"])
