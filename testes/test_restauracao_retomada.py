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

    def executar(cmd, *, stdout, stderr, check):
        chamadas.append(cmd)
        assert check is True
        assert stderr is subprocess.PIPE
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

    def executar(cmd, *, stdout, stderr, check):
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
    for prefixo in ("actions/upload-artifact", "actions/cache/save", "actions/cache@"):
        assert not any(a.startswith(prefixo) for a in actions)
    assert any(job.get("strategy", {}).get("max-parallel") == 5 for job in workflow["jobs"].values())
    assert any(a.startswith("actions/cache/restore") for a in actions)
    restores = [
        s
        for job in workflow["jobs"].values()
        for s in job["steps"]
        if s.get("uses", "").startswith("actions/cache/restore")
    ]
    assert restores[0]["with"]["path"] == "rodada/fatia/resultado"
    assert restores[0]["with"]["key"].startswith(f"lote-pa-{RT.SHA_ORIGEM}-{RT.EXECUCAO_ORIGEM}-")
