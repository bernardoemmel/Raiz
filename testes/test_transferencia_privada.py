"""Jobs transportam dados completos só pela API privada, com retomada íntegra."""

import io
import logging
import tarfile
import traceback
from pathlib import Path

import httpx
import pytest

from raiz.executor.transferencia_privada import arquivo_privado, baixar_arquivo, empacotar, enviar_arquivo, extrair
from testes.test_armazem_release import GitHubFalso, _armazem


def test_checkpoint_privado_retomado_em_outra_maquina_e_imutavel(tmp_path):
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "cache")
    fonte = tmp_path / "fonte" / "PA"
    fonte.mkdir(parents=True)
    (fonte / "previsoes.jsonl").write_text('{"credito":999}')
    pacote = tmp_path / "checkpoint.tar.gz"
    empacotar(fonte.parent, pacote)
    enviar_arquivo(pacote.name, pacote, imutavel=True, arm=arm)
    enviar_arquivo(pacote.name, pacote, imutavel=True, arm=arm)
    assert gh.uploads == [pacote.name]
    destino = tmp_path / "outra" / pacote.name
    assert baixar_arquivo(pacote.name, destino, arm=arm)
    extrair(destino, tmp_path / "retomado")
    assert (tmp_path / "retomado" / "PA" / "previsoes.jsonl").read_text() == '{"credito":999}'
    pacote.write_bytes(b"alterado")
    with pytest.raises(ValueError, match="imutável"):
        enviar_arquivo(pacote.name, pacote, imutavel=True, arm=arm)


def test_transferencia_e_upload_nao_aceitam_release_publicado(tmp_path):
    gh = GitHubFalso()
    gh.privado = False
    arm = _armazem(gh, tmp_path / "cache")
    caminho = tmp_path / "completo.csv"
    caminho.write_text("credito\n999")
    with pytest.raises(PermissionError, match="rascunho"):
        enviar_arquivo(caminho.name, caminho, arm=arm)
    with pytest.raises(PermissionError, match="rascunho"):
        baixar_arquivo(caminho.name, caminho, opcional=True, arm=arm)
    assert not gh.downloads and not gh.uploads
    gh.privado = True
    with pytest.raises(PermissionError, match="configurado"):
        arm._subir({"id": 999}, caminho.name, caminho.read_bytes())
    assert not gh.uploads


def test_ausencia_opcional_nao_esconde_falta_de_configuracao(tmp_path, monkeypatch):
    monkeypatch.delenv("RAIZ_DADOS_PRIVADOS_URL", raising=False)
    monkeypatch.delenv("RAIZ_DADOS_PRIVADOS_REPO", raising=False)
    with pytest.raises(PermissionError):
        arquivo_privado()
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path)
    assert not baixar_arquivo("ausente.tar.gz", tmp_path / "nada", opcional=True, arm=arm)
    with pytest.raises(FileNotFoundError):
        baixar_arquivo("ausente.tar.gz", tmp_path / "nada", arm=arm)


def test_asset_apos_primeira_pagina_pode_ser_lido_e_atualizado(tmp_path):
    gh = GitHubFalso()
    for i in range(110):
        gh.assets[f"snapshot_{i}.json"] = str(i).encode()
    arm = _armazem(gh, tmp_path)
    assert arm._baixar_asset("snapshot_109.json") == b"109"
    arm._subir(arm._release(), "snapshot_109.json", b"atualizado")
    assert arm._baixar_asset("snapshot_109.json") == b"atualizado"


@pytest.mark.parametrize("nome,tipo", [("../fora", tarfile.REGTYPE), ("PA/link", tarfile.SYMTYPE)])
def test_checkpoint_rejeita_travessia_e_links_antes_de_escrever(tmp_path, nome, tipo):
    pacote = tmp_path / "checkpoint.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        bom = tarfile.TarInfo("PA/valido")
        bom.size = 2
        tar.addfile(bom, io.BytesIO(b"ok"))
        ruim = tarfile.TarInfo(nome)
        ruim.type = tipo
        ruim.linkname = "../fora"
        tar.addfile(ruim)
    with pytest.raises(ValueError, match="inválido"):
        extrair(pacote, tmp_path / "destino")
    assert not (tmp_path / "destino").exists()


def test_workflows_nao_transportam_resultados_completos_em_artifacts_ou_cache():
    raiz = Path(__file__).resolve().parents[1]
    lote = (raiz / ".github/workflows/lote-para.yml").read_text()
    vigilancia = (raiz / ".github/workflows/vigilancia.yml").read_text()
    assert "actions/upload-artifact" not in lote and "actions/download-artifact" not in lote
    assert "actions/cache" not in lote and "actions/cache" not in vigilancia
    assert "transferencia_privada" in lote and "--repo" not in lote


def test_cache_seleciona_somente_fontes_e_recusa_pacote_acima_do_limite(tmp_path, monkeypatch):
    from raiz.executor import transferencia_privada as T

    pasta = tmp_path / "trabalho"
    (pasta / "motor/cache/PA").mkdir(parents=True)
    (pasta / "motor/cache/PA/fonte.tif").write_bytes(b"fonte")
    (pasta / "motor/cache/bruta.parquet").write_bytes(b"camada")
    (pasta / ".env").write_text("SEGREDO=nao_empacotar")
    pacote = tmp_path / "cache.tar.gz"
    empacotar(pasta, pacote, incluir=("motor/cache/PA", "motor/cache/*.parquet", "motor/cache/ausente"))
    with tarfile.open(pacote, "r:gz") as tar:
        assert set(tar.getnames()) == {"motor/cache/PA/fonte.tif", "motor/cache/bruta.parquet"}
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "espelho")
    monkeypatch.setattr(T, "MAX_ASSET_BYTES", 1)
    with pytest.raises(ValueError, match="2 GB"):
        enviar_arquivo("cache.tar.gz", pacote, arm=arm)
    assert not gh.uploads
    with pytest.raises(ValueError, match="dentro"):
        empacotar(pasta, pacote, incluir=("../fora",))


def test_motor_cache_privado_e_guard_impedem_ref_legada_de_rodar():
    raiz = Path(__file__).resolve().parents[1]
    workflow = (raiz / ".github/workflows/processar-estados.yml").read_text()
    assert "actions/cache" not in workflow and "transferencia_privada" in workflow
    assert "id: privacidade" in workflow
    assert workflow.count("if: always() && steps.privacidade.outcome == 'success'") == 2
    assert "--selecao-env CACHE_COMUM" in workflow and "--selecao-env CACHE_UF" in workflow


@pytest.mark.parametrize("operacao", ["baixar", "preparar", "enviar", "timeout"])
def test_erro_remoto_privado_nao_revela_url_assinada_em_traceback_ou_log(tmp_path, monkeypatch, caplog, operacao):
    from raiz import restauracao_rodada as RR

    gh = GitHubFalso()
    gh.assets["raiz_PA.tar.gz"] = b"dados completos"
    arm = _armazem(gh, tmp_path / "cache")
    assinado = "https://arquivo-assinado.invalid/privado?token=SEGREDO-NA-URL"

    def remoto(req):
        if req.url.host == "arquivo-assinado.invalid":
            if operacao == "timeout":
                raise httpx.ReadTimeout(f"falhou em {assinado}", request=req)
            return httpx.Response(403, text="CORPO-PRIVADO", headers={"X-Privado": "HEADER-PRIVADO"})
        if "/releases/assets/" in req.url.path or req.url.host == "uploads.github.com":
            return httpx.Response(307, headers={"Location": assinado})
        return gh(req)

    arm.cli = httpx.Client(transport=httpx.MockTransport(remoto), follow_redirects=True)
    monkeypatch.setattr(RR, "arquivo_privado", lambda: arm)
    caplog.set_level(logging.INFO, logger="httpx")
    with pytest.raises(RuntimeError) as falha:
        if operacao == "preparar":
            RR.preparar(tmp_path / "entradas")
        elif operacao == "enviar":
            arquivo = tmp_path / "novo.csv"
            arquivo.write_text("conteudo privado")
            enviar_arquivo("novo.csv", arquivo, arm=arm)
        else:
            baixar_arquivo("raiz_PA.tar.gz", tmp_path / "pacote", arm=arm)
    texto = "".join(traceback.format_exception(falha.value)) + caplog.text
    assert "falha de comunicação" in texto if operacao == "timeout" else "HTTP 403" in texto
    for segredo in ("SEGREDO-NA-URL", "CORPO-PRIVADO", "HEADER-PRIVADO", "arquivo-assinado.invalid"):
        assert segredo not in texto
    assert falha.value.__suppress_context__
