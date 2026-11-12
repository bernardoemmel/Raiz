"""A atestação identifica os bytes enviados, sem incluir upload que falhou."""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from raiz.atestacao import identificador, registrar
from raiz.executor.armazem import ArmazemRelease


def test_conserva_ultimo_digest_por_nome_e_arquivos_distintos(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    registrar("raiz_PA.tar.gz", b"antigo")
    registrar("croissant_PA.json", b"ficha")
    registrar("raiz_PA.tar.gz", b"novo")
    linhas = (tmp_path / "atestar.txt").read_text().splitlines()
    assert len(linhas) == 2
    assert f"{hashlib.sha256(b'novo').hexdigest()}  raiz_PA.tar.gz" in linhas
    assert f"{hashlib.sha256(b'ficha').hexdigest()}  croissant_PA.json" in linhas


def test_mesmo_nome_conserva_digests_publico_e_privado_sem_gravar_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    registrar("raiz_PA.tar.gz", b"completo antigo", privado=True)
    registrar("raiz_PA.tar.gz", b"basico")
    registrar("raiz_PA.tar.gz", b"completo novo", privado=True)

    assert (tmp_path / "atestar.txt").read_text() == (f"{hashlib.sha256(b'basico').hexdigest()}  raiz_PA.tar.gz\n")
    assert set((tmp_path / "atestar-privado.txt").read_text().splitlines()) == {
        f"{digest}  privado-sha256-{digest}"
        for digest in (hashlib.sha256(b"completo antigo").hexdigest(), hashlib.sha256(b"completo novo").hexdigest())
    }
    assert {p.name for p in tmp_path.iterdir()} == {
        "atestar.txt",
        "atestar.lock",
        "atestar-privado.txt",
        "atestar-privado.lock",
    }
    assert (tmp_path / "atestar.lock").stat().st_size == 0
    assert (tmp_path / "atestar-privado.lock").stat().st_size == 0


def test_registros_concorrentes_preservam_todos_os_nomes_por_canal(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    entradas = [(n, privado) for n in range(20) for privado in (False, True)]

    def salvar(entrada):
        n, privado = entrada
        registrar(f"arquivo_{n}.csv", f"{n}-{privado}".encode(), privado=privado)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(salvar, entradas))

    for privado, arquivo in ((False, "atestar.txt"), (True, "atestar-privado.txt")):
        assert set((tmp_path / arquivo).read_text().splitlines()) == {
            f"{digest}  {identificador(f'arquivo_{n}.csv', privado=privado, digest=digest)}"
            for n in range(20)
            for digest in (hashlib.sha256(f"{n}-{privado}".encode()).hexdigest(),)
        }


def test_limite_de_assuntos_independente_por_canal(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    cheio = "".join(f"{'a' * 64}  arquivo_{n}.csv\n" for n in range(1024))
    (tmp_path / "atestar.txt").write_text(cheio)

    registrar("novo.csv", b"completo", privado=True)
    with pytest.raises(ValueError, match="mais de 1024"):
        registrar("novo.csv", b"basico")
    assert (tmp_path / "atestar.txt").read_text() == cheio
    digest = hashlib.sha256(b"completo").hexdigest()
    assert (tmp_path / "atestar-privado.txt").read_text() == f"{digest}  privado-sha256-{digest}\n"


def test_sem_runner_temp_nao_grava_nenhum_canal(tmp_path, monkeypatch):
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.chdir(tmp_path)
    registrar("raiz_PA.tar.gz", b"basico")
    registrar("raiz_PA.tar.gz", b"completo", privado=True)
    assert not list(tmp_path.iterdir())


def _cliente_release(status_upload):
    def responder(requisicao):
        if requisicao.method == "POST":
            return httpx.Response(status_upload)
        if requisicao.url.path.endswith("/assets"):
            return httpx.Response(200, json=[])
        if "/releases/tags/" in requisicao.url.path:
            return httpx.Response(200, json={"id": 1, "draft": True, "assets": []})
        return httpx.Response(200, json={"private": False})

    return httpx.Client(transport=httpx.MockTransport(responder))


@pytest.mark.parametrize("privado", [False, True])
def test_upload_falho_nao_e_atestado(tmp_path, monkeypatch, privado):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    a = ArmazemRelease(espelho=tmp_path / "espelho", token="teste", cliente=_cliente_release(503), privado=privado)
    dados = a._tar("PA", {"resumo_PA.csv": b"cod_ibge,municipio,imoveis\n1500107,Abaetetuba,5\n"})
    with pytest.raises(RuntimeError if privado else httpx.HTTPStatusError):
        a._subir({"id": 1, "assets": []}, "raiz_PA.tar.gz", dados)
    assert not (tmp_path / "atestar.txt").exists()
    assert not (tmp_path / "atestar-privado.txt").exists()


@pytest.mark.parametrize("privado", [False, True])
def test_upload_concluido_registra_checksum(tmp_path, monkeypatch, privado):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    a = ArmazemRelease(espelho=tmp_path / "espelho", token="teste", cliente=_cliente_release(201), privado=privado)
    dados = a._tar("PA", {"resumo_PA.csv": b"cod_ibge,municipio,imoveis\n1500107,Abaetetuba,5\n"})
    a._subir({"id": 1, "assets": []}, "raiz_PA.tar.gz", dados)
    arquivo = "atestar-privado.txt" if privado else "atestar.txt"
    outro = "atestar.txt" if privado else "atestar-privado.txt"
    digest = hashlib.sha256(dados).hexdigest()
    assunto = f"privado-sha256-{digest}" if privado else "raiz_PA.tar.gz"
    assert (tmp_path / arquivo).read_text() == f"{digest}  {assunto}\n"
    assert not (tmp_path / outro).exists()


def test_nomes_privados_legados_sao_opacos_antes_da_atestacao_publica(tmp_path, monkeypatch, capsys):
    from testes.test_privacidade import CPF

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    nome = f"titular-{CPF}-contato@exemplo.invalid.csv"
    caminho = tmp_path / "atestar-privado.txt"
    caminho.write_text(f"{'a' * 64}  {nome}\n")
    registrar("raiz_PA.tar.gz", b"outro", privado=True)
    registrar(nome, b"atualizado", privado=True)
    registrar(nome, b"mais recente", privado=True)

    linhas = caminho.read_text().splitlines()
    digests = {"a" * 64, *(hashlib.sha256(b).hexdigest() for b in (b"outro", b"atualizado", b"mais recente"))}
    assert set(linhas) == {f"{digest}  privado-sha256-{digest}" for digest in digests}
    assert hashlib.sha256(nome.encode()).hexdigest() not in caminho.read_text()
    for arquivo in tmp_path.iterdir():
        assert nome not in arquivo.read_text()
        assert CPF not in arquivo.read_text()
        assert "@exemplo.invalid" not in arquivo.read_text()
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("invalida", [True, False])
def test_falha_ao_converter_lista_privada_nao_deixa_nomes_para_passo_always(tmp_path, monkeypatch, invalida):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    caminho = tmp_path / "atestar-privado.txt"
    if invalida:
        caminho.write_text("inválido  titular-contato@exemplo.invalid.csv\n")
    else:
        caminho.write_text(
            "".join(
                f"{hashlib.sha256(str(n).encode()).hexdigest()}  contato-{n}@exemplo.invalid.csv\n" for n in range(1024)
            )
        )
    with pytest.raises(ValueError, match="lista de atestação inválida"):
        registrar("novo.csv", b"novo", privado=True)
    assert not caminho.exists()


def test_aliases_privados_dos_mesmos_bytes_nao_revelam_nem_hash_do_nome(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    dados = b"conteudo privado de teste"
    digest = hashlib.sha256(dados).hexdigest()
    nomes = ("nome-particular@example.invalid.csv", "outro-nome-privado.csv")
    for nome in nomes:
        registrar(nome, dados, privado=True)
    texto = (tmp_path / "atestar-privado.txt").read_text()
    assert texto == f"{digest}  privado-sha256-{digest}\n"
    assert all(nome not in texto and hashlib.sha256(nome.encode()).hexdigest() not in texto for nome in nomes)


def test_converte_subject_legado_derivado_do_nome_pelo_digest_dos_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    digest = hashlib.sha256(b"bytes antigos").hexdigest()
    hash_nome = hashlib.sha256(b"pessoa@example.invalid.csv").hexdigest()
    destino = tmp_path / "atestar-privado.txt"
    destino.write_text(f"{digest}  privado-sha256-{hash_nome}\n")
    registrar("nome.csv", b"bytes antigos", privado=True)
    assert destino.read_text() == f"{digest}  privado-sha256-{digest}\n"


@pytest.mark.parametrize("digest", [None, "", "x" * 64, "a" * 63, "A" * 64])
def test_identificador_privado_exige_digest_de_conteudo(digest):
    with pytest.raises(ValueError, match="digest de conteúdo inválido"):
        identificador("nome.csv", privado=True, digest=digest)
