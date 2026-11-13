"""Retomada das cinco fatias com destino privado conferido a cada operação."""

import hashlib
import json
import shutil
import stat
import subprocess
import tarfile
import zipfile
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from raiz import restauracao_retomada as RT
from raiz import restauracao_rodada as RR


@pytest.fixture(autouse=True)
def ambiente_privado(monkeypatch):
    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_URL", f"release-github://{RT.REPO_ORIGEM}/{RT.TAG}")
    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_TOKEN", "token-privado-de-teste")


def _release(**muda):
    return {"id": RT.RELEASE_ID, "tag_name": "dados-privados", "draft": True, "assets": [], **muda}


def _origem(**muda):
    return {
        "id": RT.EXECUCAO_ORIGEM,
        "head_sha": RT.SHA_ORIGEM,
        "path": ".github/workflows/lote-para.yml",
        "status": "completed",
        "conclusion": "cancelled",
        **muda,
    }


def _snapshot():
    cods = sorted(RR.municipios_pa())
    return {
        "cenario": "central_r11",
        "cobertura": {"total": 144, "com_imoveis": cods, "vazios": []},
        "plano": [{"fatia": f"{i:02d}", "municipios": cods[i::15], "imoveis": 23058} for i in range(15)],
    }


PRONTAS = {"03", "04", "06", "07", "08", "09", "10", "11", "13", "14"}


def _comprovantes():
    inventario = {"versao": 1, "tipo": "actions_artifacts", "origem": RT.REPO_ORIGEM, "assets": []}
    backup = {
        "versao": 1,
        "origem": RT.REPO_ORIGEM,
        "destino": RT.REPO_ORIGEM,
        "release_id": RT.RELEASE_ID,
        "tag": "dados-privados",
        "assets": [],
    }
    assets = {}
    nomes = ["entradas-congeladas", *(f"calculado-{f}" for f in sorted(PRONTAS)), "github-pages"]
    for i, nome in enumerate(nomes, start=1):
        conteudo = f"arquivo-{nome}".encode()
        sha = hashlib.sha256(conteudo).hexdigest()
        digest = "sha256:" + sha
        origem = {"id": i, "name": nome, "size": len(conteudo), "digest": digest}
        nome_backup = f"actions-{i}-{nome}.zip"
        a = {
            "id": i,
            "name": nome,
            "size_in_bytes": len(conteudo),
            "digest": digest,
            "expired": False,
            "workflow_run": {
                "id": RT.EXECUCAO_ORIGEM if nome != "github-pages" else RT.EXECUCAO_ORIGEM + 1,
                "head_sha": RT.SHA_ORIGEM,
                "repository_id": RT.REPOSITORIO_ID,
                "head_repository_id": RT.REPOSITORIO_ID,
            },
        }
        ref = {"id": 100 + i, "name": nome_backup, "size": len(conteudo), "digest": digest}
        inventario["assets"].append({"artifact": a, "origem": origem, "nome_backup": nome_backup, "sha256": sha})
        backup["assets"].append({"origem_id": i, "backup": ref, "sha256": sha})
        assets[nome_backup] = deepcopy(ref)
    return inventario, backup, assets


def test_comprovantes_ligam_dez_fatias_e_entradas_aos_zips_privados():
    inventario, backup, assets = _comprovantes()
    encontrados = RT._validar_comprovantes(inventario, backup, assets)
    assert set(encontrados) == {"entradas-congeladas", *(f"calculado-{f}" for f in PRONTAS)}
    for a in encontrados.values():
        ref = assets[a["nome_backup"]]
        assert a["backup_asset_id"] == ref["id"]
        assert "sha256:" + a["sha256"] == ref["digest"]
        assert a["size_in_bytes"] == ref["size"]


@pytest.mark.parametrize(
    "documento,caminho,valor",
    [
        ("inventario", ("origem",), "outro/repositorio"),
        ("inventario", ("tipo",), "release_assets"),
        ("backup", ("origem",), "outro/repositorio"),
        ("backup", ("destino",), "outro/repositorio"),
        ("backup", ("release_id",), 123),
        ("backup", ("tag",), "dados"),
        ("inventario", ("assets", 0, "artifact", "workflow_run", "id"), RT.EXECUCAO_ORIGEM + 1),
        ("inventario", ("assets", 0, "artifact", "workflow_run", "head_sha"), "0" * 40),
        ("inventario", ("assets", 0, "artifact", "workflow_run", "repository_id"), 123),
        ("inventario", ("assets", 0, "artifact", "workflow_run", "head_repository_id"), 123),
        ("inventario", ("assets", 0, "artifact", "expired"), True),
        ("inventario", ("assets", 0, "artifact", "size_in_bytes"), 1),
        ("inventario", ("assets", 0, "artifact", "digest"), "sha256:" + "0" * 64),
        ("inventario", ("assets", 0, "nome_backup"), "actions-1-substituido.zip"),
        ("inventario", ("assets", 0, "origem", "id"), 123),
        ("inventario", ("assets", 0, "origem", "name"), "substituido"),
        ("inventario", ("assets", 0, "origem", "size"), 1),
        ("inventario", ("assets", 0, "origem", "digest"), "sha256:" + "0" * 64),
        ("inventario", ("assets", 0, "sha256"), "0" * 64),
        ("backup", ("assets", 0, "origem_id"), 123),
        ("backup", ("assets", 0, "sha256"), "0" * 64),
        ("backup", ("assets", 0, "backup", "id"), 123),
        ("backup", ("assets", 0, "backup", "name"), "actions-1-substituido.zip"),
        ("backup", ("assets", 0, "backup", "size"), 1),
        ("backup", ("assets", 0, "backup", "digest"), "sha256:" + "0" * 64),
    ],
)
def test_comprovante_adulterado_nao_autoriza_retomada(documento, caminho, valor):
    inventario, backup, assets = _comprovantes()
    alvo = {"inventario": inventario, "backup": backup}[documento]
    for chave in caminho[:-1]:
        alvo = alvo[chave]
    alvo[caminho[-1]] = valor
    with pytest.raises(ValueError):
        RT._validar_comprovantes(inventario, backup, assets)


@pytest.mark.parametrize("documento", ["inventario", "backup", "assets"])
def test_falta_de_comprovante_ou_zip_privado_bloqueia_retomada(documento):
    inventario, backup, assets = _comprovantes()
    if documento == "assets":
        del assets[next(iter(assets))]
    else:
        {"inventario": inventario, "backup": backup}[documento]["assets"].pop(0)
    with pytest.raises(ValueError):
        RT._validar_comprovantes(inventario, backup, assets)


@pytest.mark.parametrize("documento", ["inventario", "backup"])
def test_artifact_duplicado_nos_comprovantes_bloqueia_retomada(documento):
    inventario, backup, assets = _comprovantes()
    itens = {"inventario": inventario, "backup": backup}[documento]["assets"]
    itens.append(deepcopy(itens[0]))
    with pytest.raises(ValueError):
        RT._validar_comprovantes(inventario, backup, assets)


@pytest.mark.parametrize(
    "campo,valor", [("id", 123), ("name", "substituido.zip"), ("size", 1), ("digest", "sha256:" + "0" * 64)]
)
def test_zip_atual_divergente_do_backup_bloqueia_retomada(campo, valor):
    inventario, backup, assets = _comprovantes()
    assets[next(iter(assets))][campo] = valor
    with pytest.raises(ValueError):
        RT._validar_comprovantes(inventario, backup, assets)


def _privado_com_provas(monkeypatch):
    inventario, backup, assets = _comprovantes()
    provas = {"inventario": inventario, "backup": backup}
    corpos, referencias = {}, {}
    for i, (tipo, prova) in enumerate(provas.items(), start=1000):
        corpo = json.dumps(prova).encode()
        sha = hashlib.sha256(corpo).hexdigest()
        nome = f"{tipo}.json"
        referencias[tipo] = {"nome": nome, "asset_id": i, "sha256": sha}
        corpos[nome] = corpo
        assets[nome] = {"id": i, "name": nome, "size": len(corpo), "digest": "sha256:" + sha}
    monkeypatch.setattr(RT, "COMPROVANTES_MIGRACAO", referencias)
    monkeypatch.setattr(RT, "_api_json", lambda *args: pytest.fail("Não consultar artifacts públicos"))
    monkeypatch.setattr(RT, "_api_baixar", lambda *args: pytest.fail("Não baixar artifacts públicos"))

    class PrivadoComProvas:
        def __init__(self):
            self.downloads = []

        def listar(self):
            return assets

        def baixar(self, nome, destino, sha):
            assert hashlib.sha256(corpos[nome]).hexdigest() == sha
            self.downloads.append((nome, sha))
            destino.write_bytes(corpos[nome])

    return PrivadoComProvas(), referencias, assets


def test_recuperacao_baixa_as_duas_provas_por_sha_fixo_sem_actions(monkeypatch):
    privado, refs, _ = _privado_com_provas(monkeypatch)
    encontrados = RT._artefatos_origem(privado)
    assert len(encontrados) == 11
    assert privado.downloads == [(r["nome"], r["sha256"]) for r in refs.values()]


@pytest.mark.parametrize("campo,valor", [("ausente", None), ("id", 123), ("digest", "sha256:" + "0" * 64)])
def test_prova_privada_ausente_ou_divergente_nao_e_baixada(monkeypatch, campo, valor):
    privado, refs, assets = _privado_com_provas(monkeypatch)
    nome = refs["inventario"]["nome"]
    if campo == "ausente":
        del assets[nome]
    else:
        assets[nome][campo] = valor
    with pytest.raises(ValueError):
        RT._artefatos_origem(privado)
    assert privado.downloads == []


@pytest.mark.parametrize("adulteracao", [None, "id", "tamanho", "hash"])
def test_zip_migrado_so_e_baixado_do_privado_e_conferido(tmp_path, monkeypatch, adulteracao):
    inventario, backup, assets = _comprovantes()
    a = RT._validar_comprovantes(inventario, backup, assets)["entradas-congeladas"]
    corpo = b"arquivo-entradas-congeladas"
    eventos = []
    monkeypatch.setattr(RT, "_api_baixar", lambda *args: pytest.fail("Não baixar de Actions"))
    if adulteracao == "id":
        assets[a["nome_backup"]]["id"] += 1

    class PrivadoComZip:
        def listar(self):
            eventos.append("listar")
            return assets

        def baixar(self, nome, destino, sha):
            assert eventos[-1] == "listar"
            eventos.append("baixar")
            assert nome == a["nome_backup"] and sha == a["sha256"]
            dados = corpo + b"extra" if adulteracao == "tamanho" else corpo
            destino.write_bytes(b"X" * len(corpo) if adulteracao == "hash" else dados)

    destino = tmp_path / "migrado.zip"
    if adulteracao:
        with pytest.raises(ValueError):
            RT._baixar_artifact(PrivadoComZip(), a, destino)
        if adulteracao == "id":
            assert eventos == ["listar"]
    else:
        RT._baixar_artifact(PrivadoComZip(), a, destino)
        assert destino.read_bytes() == corpo
        assert eventos == ["listar", "baixar"]


@pytest.mark.parametrize("adulteracao", [None, "ausente", "sha256", "asset_id"])
def test_plano_hash_integro_ainda_exige_comprovantes_autorizados(tmp_path, monkeypatch, adulteracao):
    plano = {
        "execucao_origem": RT.EXECUCAO_ORIGEM,
        "sha_origem": RT.SHA_ORIGEM,
        "modelo_versao": RT.MODELO,
        "release_id": RT.RELEASE_ID,
        "comprovantes_migracao": deepcopy(RT.COMPROVANTES_MIGRACAO),
        "reusadas": sorted(PRONTAS),
        "calcular": sorted(RT.FALTANTES),
        "fatias": _snapshot()["plano"],
        "concluidas": {f: {"nome": f"pacote-{f}", "sha256": "a" * 64} for f in PRONTAS},
    }
    if adulteracao == "ausente":
        del plano["comprovantes_migracao"]
    elif adulteracao:
        plano["comprovantes_migracao"]["inventario"][adulteracao] = "0" * 64 if adulteracao == "sha256" else 123
    corpo = json.dumps(plano).encode()
    digest = hashlib.sha256(corpo).hexdigest()
    monkeypatch.setattr(RT, "conferir_modelo", lambda: None)

    class PrivadoComPlano:
        def baixar(self, nome, destino, sha):
            assert nome == "plano-privado.json" and sha == digest
            destino.write_bytes(corpo)

    if adulteracao:
        with pytest.raises(ValueError, match="retomada autorizada"):
            RT.carregar_plano(PrivadoComPlano(), "plano-privado.json", digest, tmp_path)
    else:
        assert RT.carregar_plano(PrivadoComPlano(), "plano-privado.json", digest, tmp_path) == plano


@pytest.mark.parametrize(
    "endpoint,accept",
    [
        ("repos/bernardoemmel/Raiz/actions/artifacts/123/zip", "application/vnd.github+json"),
        ("repos/bernardoemmel/Raiz/releases/assets/456", "application/octet-stream"),
    ],
)
def test_download_usa_accept_proprio_de_artifact_ou_asset(tmp_path, monkeypatch, endpoint, accept):
    chamadas = []
    corpo = b"\x1f\x8b\x00\xffconteudo-binario"

    def executar(cmd, *, stdout, stderr, check, env):
        chamadas.append(cmd)
        assert check is True
        assert stderr is subprocess.PIPE
        assert env["GH_TOKEN"] == "token-privado-de-teste"
        stdout.write(corpo)

    monkeypatch.setattr(RT.subprocess, "run", executar)
    destino = tmp_path / "entrada" / "pacote.bin"
    RT._api_baixar(endpoint, destino)
    assert len(chamadas) == 1
    assert chamadas[0][:3] == ["gh", "api", endpoint]
    assert chamadas[0][chamadas[0].index("-H") + 1] == f"Accept: {accept}"
    assert destino.read_bytes() == corpo
    assert not destino.with_suffix(".bin.download").exists()


def test_falha_de_download_nao_expoe_url_assinada_no_erro(tmp_path, monkeypatch):
    endpoint = "repos/bernardoemmel/Raiz/actions/artifacts/123/zip"

    def executar(cmd, *, stdout, stderr, check, env):
        assert stderr is subprocess.PIPE and check is True
        stdout.write(b"download parcial")
        raise subprocess.CalledProcessError(22, cmd, stderr=b"https://blob.example/arquivo?sig=segredo")

    monkeypatch.setattr(RT.subprocess, "run", executar)
    destino = tmp_path / "pacote.bin"
    destino.write_bytes(b"arquivo anterior")
    with pytest.raises(RuntimeError) as erro:
        RT._api_baixar(endpoint, destino)
    texto = str(erro.value)
    assert endpoint in texto and "22" in texto
    assert "sig=" not in texto and "segredo" not in texto and "blob.example" not in texto
    assert erro.value.__cause__ is None
    assert erro.value.__suppress_context__ is True
    assert destino.read_bytes() == b"arquivo anterior"


@pytest.mark.parametrize(
    "variavel,valor",
    [
        ("RAIZ_DADOS_PRIVADOS_URL", ""),
        ("RAIZ_DADOS_PRIVADOS_URL", f"release-github://{RT.REPO_ORIGEM}/dados"),
        ("RAIZ_DADOS_PRIVADOS_URL", "release-github://outra/conta/dados-privados"),
        ("RAIZ_DADOS_PRIVADOS_TOKEN", ""),
    ],
)
def test_configuracao_sem_destino_historico_ou_token_falha_antes_da_rede(monkeypatch, variavel, valor):
    monkeypatch.setenv(variavel, valor)
    monkeypatch.setattr(RT, "_api_json", lambda *args: pytest.fail("Configuração inválida não acessa a rede"))
    with pytest.raises(PermissionError):
        RT.Privado()


@pytest.mark.parametrize("falha", [False, True])
def test_api_usa_token_do_arquivo_privado_e_suprime_erros_com_url_assinada(monkeypatch, falha):
    monkeypatch.setenv("GH_TOKEN", "token-de-outro-destino")

    def executar(cmd, *, text, stderr, env):
        assert text is True and stderr is subprocess.PIPE
        assert env["GH_TOKEN"] == "token-privado-de-teste" and "token-privado-de-teste" not in cmd
        if falha:
            raise subprocess.CalledProcessError(22, cmd, stderr=b"https://blob.example/arquivo?sig=segredo")
        return json.dumps(_release())

    monkeypatch.setattr(RT.subprocess, "check_output", executar)
    if falha:
        with pytest.raises(RuntimeError) as erro:
            RT.Privado().verificar()
        assert "sig=" not in str(erro.value) and "segredo" not in str(erro.value)
        assert erro.value.__suppress_context__ is True
    else:
        assert RT.Privado().verificar() == _release()


@pytest.mark.parametrize("muda", [{"draft": False}, {"id": 1}, {"tag_name": "dados"}])
def test_destino_publico_ou_release_errado_bloqueia_operacao(monkeypatch, muda):
    monkeypatch.setattr(RT, "_api_json", lambda argumentos: _release(**muda))
    with pytest.raises(PermissionError):
        RT.Privado().verificar()


def test_mudanca_para_publico_depois_da_primeira_checagem_bloqueia_leitura_e_escrita(tmp_path, monkeypatch):
    atual = _release()
    chamadas = []

    def api(argumentos):
        chamadas.append("verificar")
        return deepcopy(atual)

    monkeypatch.setattr(RT, "_api_json", api)
    monkeypatch.setattr(RT, "_api_baixar", lambda *args: pytest.fail("Não pode ler asset de release publicado"))
    monkeypatch.setattr(RT, "_api_subir", lambda *args: pytest.fail("Não pode escrever em release publicado"))
    privado = RT.Privado()
    assert privado.verificar()["draft"] is True
    atual["draft"] = False
    arquivo = tmp_path / "previsoes.json"
    arquivo.write_text("{}")
    with pytest.raises(PermissionError):
        privado.baixar("previsoes.json", tmp_path / "baixado.json")
    with pytest.raises(PermissionError):
        privado.subir(arquivo, RT.PREFIXO + "_previsoes.json")
    assert len(chamadas) >= 3


def test_download_confere_hash_e_destino_antes_de_ler_asset(tmp_path, monkeypatch):
    corpo = b"previsao privada\n"
    digest = hashlib.sha256(corpo).hexdigest()
    eventos = []
    asset = {"id": 55, "name": "previsoes.jsonl", "size": len(corpo), "digest": "sha256:" + digest}

    def api(argumentos):
        if "/assets?" in argumentos[0]:
            eventos.append("listar")
            return [asset]
        eventos.append("verificar")
        return _release(assets=[asset])

    def baixar(endpoint, destino):
        assert eventos[-1] == "verificar"
        eventos.append("baixar")
        assert "55" in endpoint
        Path(destino).write_bytes(corpo)

    monkeypatch.setattr(RT, "_api_json", api)
    monkeypatch.setattr(RT, "_api_baixar", baixar)
    privado = RT.Privado()
    destino = tmp_path / "local.jsonl"
    privado.baixar("previsoes.jsonl", destino, sha_esperado=digest)
    assert destino.read_bytes() == corpo
    with pytest.raises(ValueError):
        privado.baixar("previsoes.jsonl", destino, sha_esperado="0" * 64)


def test_upload_tem_destino_privado_e_nao_publica_release(tmp_path, monkeypatch):
    eventos, assets = [], []
    nome = RT.PREFIXO + "_resumo.json"

    def api(argumentos):
        if "/assets?" in argumentos[0]:
            eventos.append("listar")
            return list(assets)
        eventos.append("verificar")
        return _release()

    def subir(endpoint, arquivo):
        assert eventos[-1] == "verificar"
        assert str(RT.RELEASE_ID) in endpoint
        eventos.append("subir")
        asset = {"id": 66, "name": nome, "size": Path(arquivo).stat().st_size}
        assets.append(asset)
        return asset

    def baixar(endpoint, destino):
        assert eventos[-1] == "verificar"
        eventos.append("baixar")
        Path(destino).write_text("{}")

    monkeypatch.setattr(RT, "_api_json", api)
    monkeypatch.setattr(RT, "_api_subir", subir)
    monkeypatch.setattr(RT, "_api_baixar", baixar)
    arquivo = tmp_path / "resumo.json"
    arquivo.write_text("{}")
    RT.Privado().subir(arquivo, nome)
    assert eventos.count("subir") == 1
    assert eventos.count("baixar") == 1
    assert eventos[-1] == "baixar"


def test_nome_existente_com_conteudo_diferente_nunca_e_sobrescrito(tmp_path, monkeypatch):
    nome = RT.PREFIXO + "_resumo.json"
    corpo = b"resultado anterior"
    asset = {"id": 66, "name": nome, "size": len(corpo)}

    def api(argumentos):
        return [asset] if "/assets?" in argumentos[0] else _release()

    monkeypatch.setattr(RT, "_api_json", api)
    monkeypatch.setattr(RT, "_api_baixar", lambda endpoint, destino: Path(destino).write_bytes(corpo))
    monkeypatch.setattr(RT, "_api_subir", lambda *args: pytest.fail("Não sobrescrever resultado imutável"))
    arquivo = tmp_path / "resumo.json"
    arquivo.write_text("resultado diferente")
    with pytest.raises(ValueError):
        RT.Privado().subir(arquivo, nome)


@pytest.mark.parametrize(
    "muda",
    [
        {"id": RT.EXECUCAO_ORIGEM + 1},
        {"head_sha": "0" * 40},
        {"path": ".github/workflows/outro.yml"},
        {"conclusion": "success"},
    ],
)
def test_retomada_rejeita_execucao_de_outra_origem(muda):
    RT.validar_origem(_origem())
    with pytest.raises(ValueError):
        RT.validar_origem(_origem(**muda))


def test_planejamento_exige_as_dez_fatias_concluidas_e_cobertura_completa():
    snapshot = _snapshot()
    plano = RT.planejar_retomada(snapshot, PRONTAS)
    assert plano["reusadas"] == sorted(PRONTAS)
    assert plano["calcular"] == ["00", "01", "02", "05", "12"]
    assert {x["fatia"] for x in plano["matriz"]["include"]} == {"00", "01", "02", "05", "12"}
    for prontas in (PRONTAS - {"03"}, PRONTAS | {"00"}, (PRONTAS - {"03"}) | {"00"}):
        with pytest.raises(ValueError):
            RT.planejar_retomada(snapshot, prontas)
    snapshot["plano"][0]["municipios"].pop()
    with pytest.raises(ValueError):
        RT.planejar_retomada(snapshot, PRONTAS)


def test_planejamento_rejeita_municipio_duplicado_em_duas_fatias():
    snapshot = _snapshot()
    snapshot["plano"][1]["municipios"].append(snapshot["plano"][0]["municipios"][0])
    with pytest.raises(ValueError):
        RT.planejar_retomada(snapshot, PRONTAS)


def test_calcular_fatia_pronta_e_rejeitado_antes_de_qualquer_calculo(tmp_path, monkeypatch):
    monkeypatch.setattr(RR, "calcular", lambda *args, **kwargs: pytest.fail("A fatia pronta não deve ser recalculada"))
    with pytest.raises(ValueError):
        RT.calcular(object(), {}, tmp_path, "03")


@pytest.mark.parametrize("nome", ["../vazamento.json", "/tmp/vazamento.json", "subpasta/previsoes.json"])
def test_zip_nao_pode_gravar_fora_da_pasta_ou_aninhar_arquivos(tmp_path, nome):
    arquivo = tmp_path / "artifact.zip"
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr(nome, "privado")
    with pytest.raises(ValueError):
        RT.extrair_zip(arquivo, tmp_path / "destino")


def test_zip_rejeita_link_simbolico(tmp_path):
    arquivo = tmp_path / "artifact.zip"
    with zipfile.ZipFile(arquivo, "w") as z:
        link = zipfile.ZipInfo("previsoes.json")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, "/tmp/fora")
    with pytest.raises(ValueError):
        RT.extrair_zip(arquivo, tmp_path / "destino")


def test_zip_legitimo_preserva_arquivos(tmp_path):
    arquivo = tmp_path / "artifact.zip"
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr("calculado_03.tar.gz", b"pacote")
    RT.extrair_zip(arquivo, tmp_path / "destino")
    assert (tmp_path / "destino/calculado_03.tar.gz").read_bytes() == b"pacote"


def test_zip_rejeita_nome_duplicado_que_sobrescreveria_resultado(tmp_path):
    arquivo = tmp_path / "artifact.zip"
    with zipfile.ZipFile(arquivo, "w") as z:
        z.writestr("calculado_03.tar.gz", b"original")
        with pytest.warns(UserWarning, match="Duplicate name"):
            z.writestr("calculado_03.tar.gz", b"sobrescrito")
    with pytest.raises(ValueError):
        RT.extrair_zip(arquivo, tmp_path / "destino")


def _fatia(tmp_path, modelo=None, com_previsao=True, entradas="entrada-1", quantidade_registros=1):
    pasta = tmp_path / "PA"
    pasta.mkdir(exist_ok=True)
    tabela = pasta / "desenvolvedor_1504950.csv"
    pd.DataFrame(
        [{"cod_imovel": "CAR-A", "restauracao_versao": modelo or RT.MODELO, "entradas_versao": entradas}]
    ).to_csv(tabela, index=False)
    registro = pasta / "previsoes.jsonl"
    conteudo = json.dumps({"cod_imovel": "CAR-A", "modelo_versao": modelo or RT.MODELO, "entradas_versao": entradas})
    registro.write_text((conteudo + "\n") * quantidade_registros)
    sha = RR.sha256(registro)
    marca = {
        "modelo_versao": modelo or RT.MODELO,
        "entradas_versao": entradas,
        "cenario": "central_r11",
        "imoveis": 1,
        "arquivos": {tabela.name: RR.sha256(tabela), registro.name: sha},
        "previsoes": {"arquivo": registro.name, "sha256": sha, "quantidade": 1},
    }
    (pasta / "rodada_1504950.json").write_text(json.dumps(marca))
    if not com_previsao:
        registro.unlink()
    pacote = tmp_path / "calculado_03.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        tar.add(pasta, arcname="PA")
    return pacote


def test_fatia_completa_exige_modelo_e_previsoes_imutaveis(tmp_path):
    RT.validar_fatia(_fatia(tmp_path), [1504950])
    with pytest.raises(ValueError):
        RT.validar_fatia(_fatia(tmp_path, com_previsao=False), [1504950])
    with pytest.raises(ValueError):
        RT.validar_fatia(_fatia(tmp_path, modelo="modelo-obsoleto"), [1504950])


def _snapshot_fatia():
    return {
        "fontes": {p: {"sha256": "a" * 64} for p in RR.PACOTES},
        "plano": [{"fatia": "03", "municipios": [1504950], "imoveis": 1}],
    }


def test_fatia_rejeita_mesmo_modelo_com_outras_entradas_apesar_de_hashes_integros(tmp_path):
    snapshot = _snapshot_fatia()
    with pytest.raises(ValueError, match="entradas congeladas"):
        RT.validar_fatia(_fatia(tmp_path, entradas="outra-coleta"), [1504950], snapshot, "03")
    entradas = RR._hash_entradas(snapshot, 1504950)
    pacote = _fatia(tmp_path, entradas=entradas)
    RT.validar_fatia(pacote, [1504950], snapshot, "03")
    snapshot["plano"][0]["imoveis"] = 2
    with pytest.raises(ValueError, match="contagem"):
        RT.validar_fatia(pacote, [1504950], snapshot, "03")


@pytest.mark.parametrize("quantidade", [0, 2])
def test_fatia_rejeita_registros_ausentes_ou_duplicados_mesmo_com_metadata_valida(tmp_path, quantidade):
    snapshot = _snapshot_fatia()
    pacote = _fatia(tmp_path, entradas=RR._hash_entradas(snapshot, 1504950), quantidade_registros=quantidade)
    with pytest.raises(ValueError):
        RT.validar_fatia(pacote, [1504950], snapshot, "03")


def test_fatia_preserva_os_cars_da_origem_e_nao_apenas_a_contagem(tmp_path):
    snapshot = _snapshot_fatia()
    pacote = _fatia(tmp_path, entradas=RR._hash_entradas(snapshot, 1504950))
    origem = tmp_path / "origem"
    origem.mkdir()
    arquivo = origem / "imoveis_1504950.csv"
    arquivo.write_text("cod_imovel\nCAR-B\n")
    with pytest.raises(ValueError, match="conjunto de fazendas"):
        RT.validar_fatia(pacote, [1504950], snapshot, "03", origem)
    arquivo.write_text("cod_imovel\nCAR-A\n")
    RT.validar_fatia(pacote, [1504950], snapshot, "03", origem)


def test_calcular_reaproveita_conclusao_privada_sem_recalcular_ou_sobrescrever(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    monkeypatch.setattr(RT, "conferir_modelo", lambda: None)
    monkeypatch.setattr(RR, "calcular", lambda *args: pytest.fail("Fatia já concluída não pode ser recalculada"))
    snapshot = _snapshot_fatia()
    snapshot["plano"][0]["fatia"] = "00"
    entradas = tmp_path / "entradas"
    entradas.mkdir()
    (entradas / "snapshot.json").write_text(json.dumps(snapshot))
    origem = tmp_path / "fonte/PA"
    origem.mkdir(parents=True)
    (origem / "imoveis_1504950.csv").write_text("cod_imovel\nCAR-A\n")
    with tarfile.open(entradas / RR.PACOTES[0], "w:gz") as tar:
        tar.add(origem, arcname="PA")
    pronto = tmp_path / "pronto"
    pronto.mkdir()
    pacote = _fatia(pronto, entradas=RR._hash_entradas(snapshot, 1504950))
    nome_conclusao = RT._nome_conclusao("00")
    conclusao = {
        "fatia": "00",
        "modelo_versao": RT.MODELO,
        "execucao_origem": RT.EXECUCAO_ORIGEM,
        "execucao_retomada": "99",
        "resumo": {"municipios": 1, "imoveis": 1},
        "pacote": {"nome": "pacote-00", "sha256": RR.sha256(pacote)},
    }

    class DestinoPrivado:
        def verificar(self):
            return _release()

        def listar(self):
            return {nome_conclusao: {"name": nome_conclusao}}

        def baixar(self, nome, destino, sha=None):
            destino.parent.mkdir(parents=True, exist_ok=True)
            if nome == nome_conclusao:
                destino.write_text(json.dumps(conclusao))
            else:
                assert nome == "pacote-00" and sha == RR.sha256(pacote)
                shutil.copyfile(pacote, destino)

        def subir(self, *args):
            pytest.fail("Conclusão imutável não pode ser sobrescrita")

    resultado = RT.calcular(DestinoPrivado(), {"fatias": snapshot["plano"]}, tmp_path, "00")
    assert resultado == {"municipios": 1, "imoveis": 1, "conclusao_reaproveitada": True}


def test_reuniao_publica_somente_no_destino_privado_e_guarda_proveniencia(tmp_path, monkeypatch):
    snapshot = _snapshot()
    entradas = tmp_path / "entradas"
    entradas.mkdir()
    (entradas / "snapshot.json").write_text(json.dumps(snapshot))
    plano = {
        "concluidas": {f: {"nome": f"pacote-{f}", "sha256": "a" * 64} for f in PRONTAS},
        "fatias": snapshot["plano"],
        "comprovantes_migracao": RT.COMPROVANTES_MIGRACAO,
    }
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    monkeypatch.setenv("GITHUB_SHA", "orquestrador-novo")
    monkeypatch.setattr(RT, "conferir_modelo", lambda: None)
    monkeypatch.setattr(RT, "validar_fatia", lambda *args, **kwargs: None)
    monkeypatch.setattr(RR, "extrair", lambda *args, **kwargs: None)
    monkeypatch.setattr(RR, "publicar", lambda *args, **kwargs: pytest.fail("Publicador aberto não pode ser usado"))

    def reunir(entradas, calculados, entrega):
        produto = entrega / "produto"
        for nome in RR.OPCOES:
            (produto / nome).mkdir(parents=True)
            (produto / nome / "lote.json").write_text("{}")
        return {"municipios": 144, "imoveis_calculados": 345870, "modelo_versao": RT.MODELO}

    monkeypatch.setattr(RR, "reunir", reunir)

    class DestinoPrivado:
        def __init__(self):
            self.publicados = []

        def baixar(self, nome, destino, sha=None):
            destino.parent.mkdir(parents=True, exist_ok=True)
            if nome.endswith(".json"):
                fatia = nome.rsplit("_", 1)[1].split(".")[0]
                destino.write_text(
                    json.dumps(
                        {
                            "fatia": fatia,
                            "modelo_versao": RT.MODELO,
                            "execucao_origem": RT.EXECUCAO_ORIGEM,
                            "execucao_retomada": "99",
                            "pacote": {"nome": f"pacote-{fatia}", "sha256": "a" * 64},
                        }
                    )
                )
            else:
                destino.write_bytes(b"pacote validado em teste separado")

        def subir(self, arquivo, nome):
            self.publicados.append(nome)
            return {"nome": nome, "sha256": RR.sha256(arquivo), "asset_id": len(self.publicados)}

    destino = DestinoPrivado()
    resultado = RT.reunir_publicar(destino, plano, tmp_path)
    assert resultado["fatias_reusadas"] == 10 and resultado["fatias_calculadas"] == 5
    assert len(destino.publicados) == 5
    manifesto = json.loads((tmp_path / "entrega/manifesto_privado.json").read_text())
    assert manifesto["retomada"]["execucao_origem"] == RT.EXECUCAO_ORIGEM
    assert manifesto["retomada"]["sha_origem"] == RT.SHA_ORIGEM
    assert manifesto["retomada"]["comprovantes_migracao"] == RT.COMPROVANTES_MIGRACAO
    assert manifesto["destino"] == {
        "tipo": "release_rascunho",
        "id": RT.RELEASE_ID,
        "tag": "dados-privados",
        "publico": False,
    }


def test_workflow_nao_grava_dados_em_artifact_ou_cache_publico():
    texto = (Path(__file__).resolve().parents[1] / ".github/workflows/retomar-lote-para.yml").read_text()
    workflow = yaml.safe_load(texto)
    actions = [s.get("uses", "") for job in workflow["jobs"].values() for s in job["steps"]]
    for prefixo in ("actions/upload-artifact", "actions/cache/save", "actions/cache/restore", "actions/cache@"):
        assert not any(a.startswith(prefixo) for a in actions)
    assert workflow["jobs"]["calcular"]["strategy"]["max-parallel"] == "${{ fromJSON(needs.preparar.outputs.vagas) }}"
    assert any(
        passo.get("run") == "python scripts/reservar_lote.py --reservar 5"
        for passo in workflow["jobs"]["preparar"]["steps"]
    )
    assert "RAIZ_DADOS_PRIVADOS_URL" in workflow["env"] and "RAIZ_DADOS_PRIVADOS_TOKEN" in workflow["env"]
    assert workflow["env"]["SHA_ORIGEM"] == RT.SHA_ORIGEM
    for job in workflow["jobs"].values():
        assert any(s.get("with", {}).get("ref") == "${{ env.SHA_ORIGEM }}" for s in job["steps"])
