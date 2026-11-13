"""Preservação privada opaca e retomada do executor; GitHub inteiramente simulado."""

import gzip
import hashlib
import json

import pytest

from raiz.executor import checkpoint as C
from raiz.executor.armazem import ArmazemLocal
from raiz.executor.executor import Executor, Tarefa
from testes.test_armazem_release import GitHubFalso, _armazem


def raizes(tmp_path):
    return {n: tmp_path / n for n in ("espelho", "motor", "retratos")}


def gravar(raiz, nome, dados):
    p = raiz / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(dados)
    return p


def fontes(roots):
    a = ArmazemLocal(roots["espelho"])
    a.por_bytes(
        "saida/PA/imoveis_1504950.csv",
        b"coluna\nvalor\n",
        {
            "tarefa": "funil",
            "versao": "funil-antiga",
            "data": "2026-11-12T10:00:00+00:00",
            "gravado_aqui": "sim",
        },
    )
    a.por_bytes("marcas/PA/1504950.json", b'{"tarefas":{"funil":{"versao":"funil-antiga"}}}')
    a.por_bytes("estado/PA.json", b'{"situacao":"processando"}')
    gravar(roots["motor"], "saida/PA/imoveis_1504950.csv", b"coluna\nvalor\n")
    gravar(roots["motor"], "saida/PA/rodada.json", b'{"situacao":"com_erro"}')
    gravar(roots["motor"], ".executor/processamento/PA/PA-1/execucao-1/1504950.json", b'{"etapa":"iniciada"}')
    # Não é gzip nem retrato canônico; deve permanecer recuperável e opaco.
    gravar(roots["retratos"], "PA/1504950/" + "a" * 64 + ".json.gz", b"retrato incompleto deliberado")


def bytes_arquivos(roots):
    return {
        (nome, p.relative_to(raiz).as_posix()): p.read_bytes()
        for nome, raiz in roots.items()
        for p in raiz.rglob("*")
        if p.is_file()
    }


def manifesto(gh, unidade="PA-1"):
    ponteiro = json.loads(gh.assets[f"checkpoint-{unidade}-latest.json"])
    return ponteiro, json.loads(gh.assets[ponteiro["manifesto"]])


def test_checkpoint_restaura_bytes_sidecars_marcas_e_retratos_opacos(tmp_path, monkeypatch):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    esperado = bytes_arquivos(roots)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    monkeypatch.setenv("GITHUB_RUN_ID", "1234")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    salvo = C.salvar("PA-1", arm=arm, raizes=roots)
    assert salvo["situacao"] == "preservado"
    ptr, m = manifesto(gh)
    assert m["run"] == "1234" and m["attempt"] == "2" and m["uf"] == "PA"
    assert m["retratos"] == "opacos_sem_validacao"
    assert gh.uploads[-1] == "checkpoint-PA-1-latest.json"
    assert all(p["nome"] in gh.downloads for p in m["pacotes"])
    assert ptr["manifesto"] in gh.downloads
    destino = raizes(tmp_path / "novo")
    out = C.restaurar("PA-1", arm=arm, raizes=destino)
    assert out["arquivos"] == len(esperado)
    assert bytes_arquivos(destino) == esperado
    meta = json.loads((destino["espelho"] / "saida/PA/imoveis_1504950.csv.meta.json").read_bytes())
    assert meta["gravado_aqui"] == "sim" and meta["versao"] == "funil-antiga"
    assert C.restaurar("PA-1", arm=arm, raizes=destino)["gravados"] == 0


def test_checkpoint_primeira_rodada_ausente_e_sem_arquivos_nao_muda_latest(tmp_path):
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    roots = raizes(tmp_path / "vazio")
    assert C.restaurar("PA", arm=arm, raizes=roots)["situacao"] == "ausente"
    assert C.salvar("PA", arm=arm, raizes=roots)["situacao"] == "sem_arquivos"
    assert not gh.uploads


def test_allowlist_ignora_segredos_tmp_outra_uf_e_arquivos_arbitrarios(tmp_path):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    for raiz, nome in (
        ("motor", ".env"),
        ("motor", "saida/PA/credenciais.json"),
        ("motor", "saida/PA/imoveis_1504950.csv.tmp"),
        ("espelho", "saida/RO/imoveis_1100015.csv"),
        ("retratos", "PA/1504950/segredo.txt"),
    ):
        gravar(roots[raiz], nome, b"SEGREDO_FORA_DA_SELECAO")
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    C.salvar("PA-1", arm=arm, raizes=roots)
    _, m = manifesto(gh)
    assert len(m["arquivos"]) == 10
    destino = raizes(tmp_path / "novo")
    C.restaurar("PA-1", arm=arm, raizes=destino)
    assert not any(b"SEGREDO_FORA_DA_SELECAO" in b for b in bytes_arquivos(destino).values())


def test_arquivo_maior_que_lote_e_dividido_e_recomposto_sem_truncar(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "LOTE_BYTES", 32768)
    roots = raizes(tmp_path / "origem")
    dados = bytes(range(256)) * 600
    gravar(roots["motor"], "saida/PA/camadas_1504950.parquet", dados)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    C.salvar("PA", arm=arm, raizes=roots)
    _, m = manifesto(gh, "PA")
    assert len(m["pacotes"]) > 1 and len(m["arquivos"][0]["partes"]) > 1
    for p in m["pacotes"]:
        assert len(gzip.decompress(gh.assets[p["nome"]])) <= C.LOTE_BYTES
    destino = raizes(tmp_path / "novo")
    C.restaurar("PA", arm=arm, raizes=destino)
    assert (destino["motor"] / "saida/PA/camadas_1504950.parquet").read_bytes() == dados


@pytest.mark.parametrize("defeito", ["meta", "link_fonte", "remoto", "publico"])
def test_preservacao_falha_sem_mudar_latest(tmp_path, monkeypatch, defeito):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    C.salvar("PA-1", arm=arm, raizes=roots)
    anterior = gh.assets["checkpoint-PA-1-latest.json"]
    if defeito == "meta":
        (roots["espelho"] / "saida/PA/imoveis_1504950.csv").write_bytes(b"bytes mudaram sem meta")
    elif defeito == "link_fonte":
        alvo = roots["motor"] / "saida/PA/imoveis_1504950.csv"
        alvo.unlink()
        alvo.symlink_to(tmp_path / "fora")
    elif defeito == "publico":
        gh.privado = False
    else:
        original = C.T.baixar_arquivo

        def corromper(nome, destino, **kw):
            ok = original(nome, destino, **kw)
            if nome.startswith("checkpoint-objeto-"):
                destino.write_bytes(b"remoto errado")
            return ok

        monkeypatch.setattr(C.T, "baixar_arquivo", corromper)
    with pytest.raises(C.CheckpointInvalido):
        C.salvar("PA-1", arm=arm, raizes=roots)
    assert gh.assets["checkpoint-PA-1-latest.json"] == anterior


@pytest.mark.parametrize("defeito", ["pacote", "manifesto", "conflito", "link_destino"])
def test_restauracao_confere_tudo_antes_de_escrever(tmp_path, defeito):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    C.salvar("PA-1", arm=arm, raizes=roots)
    ptr, m = manifesto(gh)
    destino = raizes(tmp_path / "novo")
    if defeito == "pacote":
        gh.assets[m["pacotes"][0]["nome"]] = b"corrompido"
    elif defeito == "manifesto":
        gh.assets[ptr["manifesto"]] += b"alterado"
    elif defeito == "conflito":
        gravar(destino["motor"], "saida/PA/imoveis_1504950.csv", b"trabalho local mais novo")
    else:
        destino["motor"].mkdir(parents=True)
        (destino["motor"] / "saida").symlink_to(tmp_path / "fora")
    antes = bytes_arquivos(destino)
    with pytest.raises(C.CheckpointInvalido):
        C.restaurar("PA-1", arm=arm, raizes=destino)
    assert bytes_arquivos(destino) == antes
    assert not destino["espelho"].exists()


def test_checkpoint_nao_chama_publicador_croissant_cadt_ou_validador_retrato(tmp_path, monkeypatch):
    import builtins

    original = builtins.__import__

    def sem_produto(nome, *args, **kwargs):
        if nome in {"raiz.metadados", "raiz.cadt", "raiz.aprendizado.retratos"}:
            pytest.fail("checkpoint não pode depender de validação do produto")
        return original(nome, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sem_produto)
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    C.salvar("PA-1", arm=arm, raizes=roots)
    assert C.restaurar("PA-1", arm=arm, raizes=raizes(tmp_path / "novo"))["situacao"] == "restaurado"


def test_checkpoint_erros_nao_expoem_conteudo_ou_urls(tmp_path, monkeypatch):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    arm = _armazem(GitHubFalso(), tmp_path / "api")

    def falhar(*args, **kwargs):
        raise RuntimeError("https://privado.invalid/?token=SEGREDO")

    monkeypatch.setattr(C.T, "enviar_arquivo", falhar)
    with pytest.raises(C.CheckpointInvalido) as erro:
        C.salvar("PA-1", arm=arm, raizes=roots)
    assert str(erro.value) == "checkpoint_preservacao_falhou"
    assert erro.value.__suppress_context__ and erro.value.__cause__ is None


def test_retomada_preserva_gravado_aqui_e_executor_pula_tarefa_concluida(tmp_path):
    gh = GitHubFalso()
    roots = raizes(tmp_path / "origem")
    arm = _armazem(gh, roots["espelho"])
    rodadas = []

    def rodar(uf, cod, pasta):
        rodadas.append(cod)
        (pasta / f"imoveis_{cod}.csv").write_bytes(b"coluna\nconcluido\n")

    tarefa = Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: "funil-original", rodar)
    executor = Executor(arm, roots["motor"], [tarefa])
    assert executor.processar_municipio("PA", 1504950)["rodadas"] == ["funil"]
    C.salvar("PA-1", arm=arm, raizes=roots)
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {"imoveis_1504950.csv": b"resultado antigo"})
    gh.assets["raiz_controle_PA.json"] = json.dumps({"marcas": {"1504950": {"tarefas": {}}}}).encode()
    destino = raizes(tmp_path / "novo")
    C.restaurar("PA-1", arm=arm, raizes=destino)
    novo = _armazem(gh, destino["espelho"])
    retomado = Executor(novo, destino["motor"], [tarefa]).processar_municipio("PA", 1504950)
    assert retomado["puladas"] == ["funil"] and retomado["rodadas"] == []
    assert rodadas == [1504950]
    assert novo.local.meta("marcas/PA/1504950.json")["gravado_aqui"] == "sim"
    assert novo.local.meta("saida/PA/imoveis_1504950.csv")["versao"] == "funil-original"

    # Mudança real de versão deve executar novamente; restaurar nunca adota a
    # ciência atual apenas para fazer a marca parecer concluída.
    def rodar_nova(uf, cod, pasta):
        assert novo.local.meta("saida/PA/imoveis_1504950.csv")["versao"] == "funil-original"
        rodadas.append(cod)
        (pasta / f"imoveis_{cod}.csv").write_bytes(b"coluna\nrecalculado na nova versao\n")

    atualizada = Tarefa("funil", (), ("imoveis_{cod}.csv",), lambda: "funil-nova", rodar_nova)
    recalculo = Executor(novo, destino["motor"], [atualizada])
    assert recalculo.plano("PA", 1504950) == ["funil"]
    assert novo.local.meta("saida/PA/imoveis_1504950.csv")["versao"] == "funil-original"
    resultado = recalculo.processar_municipio("PA", 1504950)
    assert resultado["rodadas"] == ["funil"] and resultado["puladas"] == []
    assert rodadas == [1504950, 1504950]
    assert novo.local.meta("saida/PA/imoveis_1504950.csv")["versao"] == "funil-nova"
    assert novo.local.ler("saida/PA/imoveis_1504950.csv") == b"coluna\nrecalculado na nova versao\n"


def test_allowlist_cobre_todas_as_saidas_atuais_e_sidecars_de_controle():
    from raiz.executor.tarefas import SAIDAS

    for padroes in SAIDAS.values():
        for padrao in padroes:
            caminho = "saida/PA/" + padrao.format(cod=1504950)
            for raiz in ("motor", "espelho"):
                assert C._permitido(raiz, caminho, "PA", "PA-1")
                assert C._permitido(raiz, caminho + ".meta.json", "PA", "PA-1")
    for caminho in ("marcas/PA/1504950.json", "estado/PA.json"):
        assert C._permitido("espelho", caminho, "PA", "PA-1")
        assert C._permitido("espelho", caminho + ".meta.json", "PA", "PA-1")


@pytest.mark.parametrize(
    "caminho", ["../fora", "saida/PA/.env", "saida/PA//imoveis_1504950.csv", "saida/RO/imoveis_1504950.csv"]
)
def test_manifesto_com_path_reassinado_ainda_e_recusado_antes_de_escrever(tmp_path, caminho):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    C.salvar("PA-1", arm=arm, raizes=roots)
    ptr, m = manifesto(gh)
    m["arquivos"][0]["caminho"] = caminho
    bruto = C._json(m)
    sha = hashlib.sha256(bruto).hexdigest()
    ptr["manifesto"] = f"checkpoint-PA-1-{ptr['run']}-{ptr['attempt']}-{sha}.json"
    ptr["sha256"] = sha
    gh.assets[ptr["manifesto"]] = bruto
    gh.assets["checkpoint-PA-1-latest.json"] = C._json(ptr)
    destino = raizes(tmp_path / "novo")
    with pytest.raises(C.CheckpointInvalido, match="caminho_recusado"):
        C.restaurar("PA-1", arm=arm, raizes=destino)
    assert not (tmp_path / "novo").exists()


def test_run_antigo_preserva_objetos_sem_substituir_latest_novo(tmp_path, monkeypatch):
    roots = raizes(tmp_path / "origem")
    fontes(roots)
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "api")
    monkeypatch.setenv("GITHUB_RUN_ID", "200")
    C.salvar("PA-1", arm=arm, raizes=roots)
    anterior = gh.assets["checkpoint-PA-1-latest.json"]
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    assert C.salvar("PA-1", arm=arm, raizes=roots)["situacao"] == "preservado_sem_mudar_latest"
    assert gh.assets["checkpoint-PA-1-latest.json"] == anterior


def test_cli_repositorio_original_independe_do_checkout_do_publicador(tmp_path, monkeypatch, capsys):
    import sys
    from types import SimpleNamespace

    import raiz.config

    visto = []
    monkeypatch.setattr(
        raiz.config, "config", lambda: SimpleNamespace(armazem_espelho_dir=None, motor_dir_trabalho=None)
    )
    monkeypatch.delenv("RAIZ_HISTORICO_DIR", raising=False)
    monkeypatch.setattr(C, "restaurar", lambda unidade, **kw: visto.append((unidade, kw)) or {"situacao": "ausente"})
    monkeypatch.setattr(sys, "argv", ["checkpoint", "restaurar", "--unidade", "PA-1", "--repositorio", str(tmp_path)])
    C.main()
    assert visto == [
        (
            "PA-1",
            {
                "raizes": {
                    "espelho": tmp_path / "dados/armazem_local_privado",
                    "motor": tmp_path / "motor",
                    "retratos": tmp_path / "dados/historico_aprendizado",
                }
            },
        )
    ]
    assert json.loads(capsys.readouterr().out)["situacao"] == "ausente"
