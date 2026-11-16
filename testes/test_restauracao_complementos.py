"""Complementos privados preservam os lotes e recusam origem ou pacote adulterado."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml

from raiz import restauracao_complementos as C


class Privado:
    def __init__(self, assets=None, privado=True):
        self.assets = assets or {}
        self.privado = privado
        self.leituras = []

    def _exigir_privado(self):
        if not self.privado:
            raise PermissionError("público")

    def _baixar_asset(self, nome, fresco=False):
        assert fresco
        self.leituras.append(nome)
        return self.assets.get(nome)


def pacote(resumo=None, duplicado=False, link=False, opcao="barata"):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:gz") as t:
        for nome, dados in (
            (f"{opcao}/lote_PA.csv", b"cod_imovel,papel\nA,titular\n"),
            (f"{opcao}/lote_PA.json", json.dumps(resumo or {"opcao": opcao}).encode()),
        ):
            m = tarfile.TarInfo(nome)
            m.size = len(dados)
            if link:
                m.type, m.linkname = tarfile.SYMTYPE, "/etc/passwd"
            t.addfile(m, io.BytesIO(dados))
            if duplicado:
                t.addfile(m, io.BytesIO(dados))
    return b.getvalue()


def test_baixar_confere_hash_tamanho_e_privacidade_antes_dos_dados():
    a = Privado({"x.json": b"{}"})
    sha = hashlib.sha256(b"{}").hexdigest()
    assert C._baixar(a, "x.json", sha, 2) == b"{}"
    for nome, digest, tamanho in [("../x", sha, 2), ("x.json", "0" * 64, 2), ("x.json", sha, 3)]:
        with pytest.raises(ValueError):
            C._baixar(a, nome, digest, tamanho)
    a.privado = False
    n = len(a.leituras)
    with pytest.raises(PermissionError):
        C._baixar(a, "x.json", sha)
    assert len(a.leituras) == n


def test_ler_pacote_nao_extrai_e_rejeita_duplicatas_links():
    tabela, resumo = C.ler_lote(pacote(), "barata", "PA")
    assert list(tabela.cod_imovel) == ["A"] and resumo["opcao"] == "barata"
    for b in (pacote(duplicado=True), pacote(link=True)):
        with pytest.raises(ValueError, match="único e regular"):
            C.ler_lote(b, "barata", "PA")
    with pytest.raises(ValueError, match="inválida"):
        C.ler_lote(pacote(), "../barata", "PA")


@pytest.mark.parametrize("historico", [True, False])
def test_referencias_preservam_os_dois_formatos_privados(historico):
    arquivos = {}
    for opcao in C.OPCOES:
        nome = f"lote_PA_123_1_{opcao}.tar.gz"
        arquivos[opcao if historico else nome] = {"nome": nome, "sha256": "a" * 64, "bytes": 10}
    assert set(C.referencias({"arquivos": arquivos})) == set(C.OPCOES)
    arquivos["lote_PA_456_1_barata.tar.gz"] = {"sha256": "b" * 64, "bytes": 20}
    with pytest.raises(ValueError, match="exatamente um"):
        C.referencias({"arquivos": arquivos})


def test_publicar_so_referencia_pacote_depois_de_confirmar_bytes(tmp_path, monkeypatch):
    produto = tmp_path / "produto"
    produto.mkdir()
    (produto / "relatorio.json").write_text("{}")
    a, enviados = Privado(), []

    def enviar(nome, caminho, **kwargs):
        assert kwargs == {"imutavel": True, "arm": a}
        enviados.append(nome)
        a.assets[nome] = caminho.read_bytes()

    monkeypatch.setattr(C, "enviar_arquivo", enviar)
    m = {"uf": "PA", "origem": {"sha256": "a" * 64}}
    resultado = C.publicar(a, tmp_path, m)
    assert enviados == [resultado["arquivo"]["nome"], resultado["manifesto"]]
    assert a.leituras == enviados
    assert json.loads(a.assets[resultado["manifesto"]])["origem"] == m["origem"]

    enviados.clear()

    def corromper(nome, caminho, **kwargs):
        enviados.append(nome)
        a.assets[nome] = b"corrompido"

    monkeypatch.setattr(C, "enviar_arquivo", corromper)
    with pytest.raises(ValueError, match="divergente"):
        C.publicar(a, tmp_path, m)
    assert len(enviados) == 1 and enviados[0].endswith(".tar.gz")


def test_workflow_reserva_uma_cota_e_nao_publica_artifacts_ou_cache():
    p = Path(__file__).parents[1] / ".github/workflows/desbloqueio-lote.yml"
    texto, workflow = p.read_text(), yaml.safe_load(p.read_text())
    assert workflow["concurrency"]["cancel-in-progress"] is False
    passos = workflow["jobs"]["preparar"]["steps"]
    reserva = next(i for i, s in enumerate(passos) if "--reservar 1" in s.get("run", ""))
    dados = next(i for i, s in enumerate(passos) if "restauracao_complementos" in s.get("run", ""))
    assert reserva < dados
    assert "upload-artifact" not in texto and "actions/cache" not in texto
    assert "RAIZ_DADOS_PRIVADOS_TOKEN" in texto and "--sha256" in texto


def test_gerar_recusa_resumo_trocado_sem_recalcular(tmp_path, monkeypatch):
    from raiz import restauracao_desbloqueio as D

    resumo = {"opcao": "barata", "uf": "PA", "cenario": "central_r11", "versao_premissas": "historico"}
    tar = pacote(resumo)
    referencias = {
        opcao: {"nome": f"lote_PA_{opcao}.tar.gz", "sha256": C._sha(tar), "bytes": len(tar)} for opcao in C.OPCOES
    }
    m = {
        "uf": "PA",
        "cenario": "central_r11",
        "modelo_versao": "historico",
        "arquivos": referencias,
        "resumos": {"barata": {**resumo, "titulares": 99}},
    }
    original = json.dumps(m).encode()
    a = Privado({"manifesto.json": original, referencias["barata"]["nome"]: tar})

    def nao_chamar(*args, **kwargs):
        pytest.fail("Não pode gerar relatório de pacote divergente")

    monkeypatch.setattr(D, "relatorio", nao_chamar)
    with pytest.raises(ValueError, match="diverge"):
        C.gerar(a, "manifesto.json", C._sha(original), tmp_path)


def test_gerar_recusa_pasta_com_saida_anterior(tmp_path):
    m = {"arquivos": {opcao: {"nome": f"lote_PA_{opcao}.tar.gz"} for opcao in C.OPCOES}}
    original = json.dumps(m).encode()
    a = Privado({"manifesto.json": original})
    (tmp_path / "produto").mkdir()
    (tmp_path / "produto/antigo.json").write_text("{}")
    with pytest.raises(ValueError, match="vazia"):
        C.gerar(a, "manifesto.json", C._sha(original), tmp_path)


def test_gerar_preserva_as_tres_opcoes_e_origem_sem_modelo_atual(tmp_path, monkeypatch):
    from raiz import restauracao_desbloqueio as D

    m = {
        "uf": "PA",
        "cenario": "central_r11",
        "modelo_versao": "historico",
        "execucao": "origem-123",
        "commit": "origem-sha",
        "arquivos": {},
        "resumos": {},
    }
    a = Privado()
    for opcao in C.OPCOES:
        resumo = {"opcao": opcao, "uf": "PA", "cenario": "central_r11", "versao_premissas": "historico"}
        b = pacote(resumo, opcao=opcao)
        nome = f"lote_PA_{opcao}.tar.gz"
        m["arquivos"][opcao] = {"nome": nome, "sha256": C._sha(b), "bytes": len(b)}
        m["resumos"][opcao] = resumo
        a.assets[nome] = b
    original = json.dumps(m).encode()
    a.assets["manifesto.json"] = original
    chamadas = []

    def relatorio(tabela, resumo):
        assert list(tabela.cod_imovel) == ["A"]
        assert resumo["versao_premissas"] == "historico"
        chamadas.append(resumo["opcao"])
        return {"opcao": resumo["opcao"], "modelo_versao": "historico"}

    def gravar(resultado, pasta):
        pasta.mkdir(parents=True)
        (pasta / "teste.json").write_text(json.dumps(resultado))

    monkeypatch.setattr(D, "relatorio", relatorio)
    monkeypatch.setattr(D, "gravar", gravar)
    monkeypatch.setenv("GITHUB_RUN_ID", "complemento-456")
    monkeypatch.setenv("GITHUB_SHA", "complemento-sha")
    saida = C.gerar(a, "manifesto.json", C._sha(original), tmp_path)
    assert chamadas == list(C.OPCOES)
    assert saida["origem"]["execucao"] == "origem-123"
    assert saida["origem"]["commit"] == "origem-sha"
    assert saida["execucao"] == "complemento-456"
    assert saida["commit"] == "complemento-sha"
    assert saida["modelo_versao"] == "historico"
    assert saida["calculo_original_preservado"] is True
    assert saida["origem"]["sha256"] == C._sha(original)
    assert len(list((tmp_path / "produto").glob("*/teste.json"))) == 3
