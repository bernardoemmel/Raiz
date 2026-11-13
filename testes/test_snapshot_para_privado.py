"""A preparação estadual protege o snapshot e exige uma execução real, sem rede nos testes."""

import ctypes
import hashlib
import importlib
import io
import json
import os
import select
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import testar_para_privado as P

SEGREDO = "segredo-sintetico-que-nao-pode-sair"


@pytest.fixture(autouse=True)
def sem_rede_ou_contexto_do_runner(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

    def proibido(*args, **kwargs):
        pytest.fail("O teste tentou acessar a rede real.")

    monkeypatch.setattr(P.urllib.request.OpenerDirector, "open", proibido)


def _cliente():
    return P.ClientePrivado({"RAIZ_DADOS_PRIVADOS_TOKEN": SEGREDO})


def _release(**muda):
    return {"id": P.RELEASE, "tag_name": "dados-privados", "draft": True, **muda}


def _redirecionar(url):
    return urllib.error.HTTPError("https://api.github.com", 302, SEGREDO, {"Location": url}, io.BytesIO())


@pytest.mark.parametrize("host", ["release-assets.githubusercontent.com", "api.github.com"])
def test_redirect_nunca_recebe_o_token_nem_no_mesmo_host(host):
    cliente, pedidos = _cliente(), []

    def abrir(pedido, **kwargs):
        pedidos.append(pedido)
        if len(pedidos) == 1:
            raise _redirecionar(f"https://{host}/privado?assinatura={SEGREDO}")
        return io.BytesIO(b"ok")

    cliente.opener = SimpleNamespace(open=abrir)
    with cliente._abrir("releases/assets/1", binario=True) as resposta:
        assert resposta.read() == b"ok"
    assert pedidos[0].get_header("Authorization") == f"Bearer {SEGREDO}"
    assert pedidos[1].get_header("Authorization") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://release-assets.githubusercontent.com/arquivo",
        "https://api.github.com.externo.invalid/arquivo",
        "https://externo.invalid/arquivo",
        "https://release-assets.githubusercontent.com:444/arquivo",
        "https://usuario:senha@release-assets.githubusercontent.com/arquivo",
    ],
)
def test_redirect_fora_da_fronteira_e_rejeitado_antes_da_segunda_requisicao(url):
    cliente, pedidos = _cliente(), []

    def abrir(pedido, **kwargs):
        pedidos.append(pedido)
        raise _redirecionar(url)

    cliente.opener = SimpleNamespace(open=abrir)
    with pytest.raises(P.FalhaPrivada) as erro:
        cliente._abrir("releases/assets/1", binario=True)
    assert len(pedidos) == 1
    assert url not in str(erro.value) and SEGREDO not in str(erro.value)


def test_ciclo_de_redirect_tem_limite_e_erro_http_nao_expoe_resposta():
    cliente, pedidos = _cliente(), []

    def abrir(pedido, **kwargs):
        pedidos.append(pedido)
        raise _redirecionar(f"https://release-assets.githubusercontent.com/?assinatura={SEGREDO}")

    cliente.opener = SimpleNamespace(open=abrir)
    with pytest.raises(P.FalhaPrivada, match="redirecionamento"):
        cliente._abrir("releases/assets/1", binario=True)
    assert len(pedidos) == 4

    def recusado(*args, **kwargs):
        raise urllib.error.HTTPError(f"https://api.github.com/?token={SEGREDO}", 403, SEGREDO, {}, io.BytesIO())

    cliente.opener = SimpleNamespace(open=recusado)
    with pytest.raises(P.FalhaPrivada) as erro:
        cliente._api("releases/1")
    assert SEGREDO not in str(erro.value)


@pytest.mark.parametrize("muda", [{"draft": False}, {"id": 1}, {"tag_name": "publico"}])
def test_release_precisa_ser_o_rascunho_exato(monkeypatch, muda):
    cliente = _cliente()
    monkeypatch.setattr(cliente, "_api", lambda endpoint: _release(**muda))
    with pytest.raises(P.FalhaPrivada):
        cliente.verificar()


def test_fork_e_recusado_antes_de_ler_token_ou_criar_cliente(tmp_path, monkeypatch):
    evento = tmp_path / "evento.json"
    evento.write_text(
        json.dumps(
            {"pull_request": {"head": {"repo": {"full_name": "externo/fork"}}, "base": {"repo": {"full_name": P.REPO}}}}
        )
    )

    def proibido(*args, **kwargs):
        pytest.fail("Não deve criar cliente HTTP para um fork.")

    monkeypatch.setattr(P.urllib.request, "build_opener", proibido)
    with pytest.raises(P.FalhaPrivada, match="PR de fork.*não foi executada"):
        P.ClientePrivado(
            {
                "GITHUB_ACTIONS": "true",
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_REPOSITORY": P.REPO,
                "GITHUB_EVENT_PATH": str(evento),
            }
        )


@pytest.mark.parametrize("evento", ["push", "pull_request"])
def test_evento_do_proprio_repositorio_e_aceito(tmp_path, evento):
    arquivo = tmp_path / "evento.json"
    arquivo.write_text(
        json.dumps({"pull_request": {lado: {"repo": {"full_name": P.REPO}} for lado in ("head", "base")}})
    )
    P.conferir_evento(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": evento,
            "GITHUB_REPOSITORY": P.REPO,
            "GITHUB_EVENT_PATH": str(arquivo),
        }
    )


def test_download_reconfere_privacidade_antes_de_ler_os_bytes(tmp_path, monkeypatch):
    cliente, consultas = _cliente(), []
    ref = P.Referencia(1, 3, hashlib.sha256(b"abc").hexdigest())

    def api(endpoint):
        consultas.append(endpoint)
        if endpoint.endswith("assets/1"):
            return {"id": 1, "size": 3, "digest": f"sha256:{ref.sha256}"}
        return _release(draft=len(consultas) == 1)

    monkeypatch.setattr(cliente, "_api", api)
    with pytest.raises(P.FalhaPrivada):
        cliente.baixar(ref, tmp_path / "arquivo")
    assert consultas == [f"releases/{P.RELEASE}", "releases/assets/1", f"releases/{P.RELEASE}"]
    assert not (tmp_path / "arquivo").exists()


@pytest.mark.parametrize("dados", [b"ab", b"abd", b"abcd"])
def test_download_rejeita_truncamento_digest_errado_e_excesso(tmp_path, monkeypatch, dados):
    cliente = _cliente()
    ref = P.Referencia(1, 3, hashlib.sha256(b"abc").hexdigest())
    monkeypatch.setattr(cliente, "verificar", lambda: None)
    monkeypatch.setattr(cliente, "_api", lambda endpoint: {"id": 1, "size": 3, "digest": f"sha256:{ref.sha256}"})
    monkeypatch.setattr(cliente, "_abrir", lambda *args, **kwargs: io.BytesIO(dados))
    with pytest.raises(P.FalhaPrivada):
        cliente.baixar(ref, tmp_path / "arquivo")


def _tar(pasta, membros):
    arquivo = pasta / "pacote.tar.gz"
    with tarfile.open(arquivo, "w:gz") as tar:
        for nome, dados, tipo in membros:
            membro = tarfile.TarInfo(nome)
            membro.type = tipo
            membro.size = len(dados) if tipo == tarfile.REGTYPE else 0
            if tipo in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                membro.linkname = "fora"
            tar.addfile(membro, io.BytesIO(dados))
    return arquivo


@pytest.mark.parametrize("nome", ["/fora", "../fora", "PA/../fora", "PA\\fora"])
def test_tar_rejeita_caminhos_maliciosos_mesmo_nao_selecionados(tmp_path, nome):
    arquivo = _tar(tmp_path, [(nome, b"privado", tarfile.REGTYPE)])
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: None)


@pytest.mark.parametrize("tipo", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE])
def test_tar_rejeita_links_e_arquivos_especiais(tmp_path, tipo):
    arquivo = _tar(tmp_path, [("PA/arquivo", b"", tipo)])
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: None)


@pytest.mark.parametrize("nomes", [("PA/a", "PA/a"), ("PA/a", "PA/./a")])
def test_tar_rejeita_membro_duplicado_ou_alias(tmp_path, nomes):
    arquivo = _tar(tmp_path, [(nome, b"x", tarfile.REGTYPE) for nome in nomes])
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: None)


def test_tar_rejeita_colisao_de_destino(tmp_path):
    arquivo = _tar(tmp_path, [(nome, b"x", tarfile.REGTYPE) for nome in ("a", "b")])
    destino = tmp_path / "saida" / "mesmo"
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: destino)
    assert destino.read_bytes() == b"x"


@pytest.mark.parametrize("tamanhos", [(7,), (4, 4)])
def test_tar_limita_tamanho_individual_e_total_antes_de_extrair(tmp_path, monkeypatch, tamanhos):
    monkeypatch.setattr(P, "LIMITE_TAR", 6)
    arquivo = _tar(tmp_path, [(str(i), b"x" * n, tarfile.REGTYPE) for i, n in enumerate(tamanhos)])
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: None)


def test_tar_limita_quantidade_mesmo_com_membros_vazios(tmp_path):
    arquivo = _tar(tmp_path, [(str(i), b"", tarfile.REGTYPE) for i in range(10001)])
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: None)


def test_tar_comparado_precisa_preservar_os_bytes_originais(tmp_path):
    arquivo = _tar(tmp_path, [("a", b"original", tarfile.REGTYPE)])
    destino = tmp_path / "saida" / "a"
    assert P._percorrer_tar(arquivo, lambda nome: destino) == {destino}
    assert P._percorrer_tar(arquivo, lambda nome: destino, comparar=True) == {destino}
    destino.write_bytes(b"alterado")
    with pytest.raises(P.FalhaPrivada):
        P._percorrer_tar(arquivo, lambda nome: destino, comparar=True)


def test_contrato_exige_os_bytes_ancorados_mesmo_com_json_valido(tmp_path, monkeypatch):
    referencia = {"asset_id": 1, "bytes": 1, "sha256": "a" * 64}
    manifesto = {
        "uf": "PA",
        "municipios": 144,
        "municipios_calculados": 144,
        "imoveis_calculados": 345870,
        "modelo_versao": P.MODELO,
        "cenario": "central_r11",
        "commit": P.ORIGEM,
        "arquivos": {"previsoes": referencia},
    }
    plano = {
        "modelo_versao": P.MODELO,
        "sha_origem": P.ORIGEM,
        "release_id": P.RELEASE,
        "draft": True,
        "execucao_origem": 43285608189,
        "entradas": referencia,
    }
    for nome, valor, constante in (("manifesto", manifesto, "MANIFESTO"), ("plano", plano, "PLANO")):
        dados = json.dumps(valor).encode()
        (tmp_path / f"{nome}.json").write_bytes(dados)
        monkeypatch.setattr(P, constante, P.Referencia(1, len(dados), hashlib.sha256(dados).hexdigest()))
    m, p, refs = P._contrato(tmp_path)
    assert m == manifesto and p == plano and set(refs) == {"entradas.tar.gz", "previsoes.tar.gz"}
    adulterado = (tmp_path / "manifesto.json").read_bytes().replace(b"345870", b"345871")
    (tmp_path / "manifesto.json").write_bytes(adulterado)
    with pytest.raises(P.FalhaPrivada):
        P._contrato(tmp_path)


def _caso(conteudo="", *, nome=None):
    return f'<testcase classname="{P.CASO[0]}" name="{nome or P.CASO[1]}">{conteudo}</testcase>'


@pytest.mark.parametrize(
    ("casos", "codigo"),
    [
        ("", 0),
        (_caso() * 2, 0),
        (_caso(nome="outro_teste"), 0),
        (_caso("<skipped/>"), 0),
        (_caso('<skipped type="pytest.xfail"/>'), 0),
        (_caso("<failure/>"), 0),
        (_caso("<error/>"), 0),
        (_caso(), 1),
    ],
)
def test_resultado_so_aceita_uma_execucao_estadual_aprovada(tmp_path, casos, codigo):
    arquivo = tmp_path / "resultado.xml"
    arquivo.write_text(f"<testsuite>{casos}</testsuite>")
    with pytest.raises(P.FalhaPrivada):
        P.conferir_resultado(arquivo, codigo)


def test_resultado_estadual_aprovado_e_aceito(tmp_path):
    arquivo = tmp_path / "resultado.xml"
    arquivo.write_text(f"<testsuites><testsuite>{_caso()}</testsuite></testsuites>")
    P.conferir_resultado(arquivo, 0)


@pytest.mark.parametrize("falha", [None, "teste", "timeout", "iniciar", "interrupcao"])
def test_execucao_isola_ambiente_saida_diagnosticos_e_limpa_temporarios(tmp_path, monkeypatch, capsys, falha):
    pasta = tmp_path / "privado"
    pasta.mkdir(mode=0o700)
    for nome in ("GH_TOKEN", "RAIZ_DADOS_PRIVADOS_TOKEN", "AWS_SECRET_ACCESS_KEY", "PYTEST_ADDOPTS", "PYTHONPATH"):
        monkeypatch.setenv(nome, SEGREDO)
    monkeypatch.setenv("RUNNER_TRACKING_ID", "runner-de-teste")
    chamadas, grupos = [], []

    def iniciar(comando, **kwargs):
        chamadas.append((comando, kwargs))
        assert kwargs["stderr"] == subprocess.STDOUT and kwargs["start_new_session"] is True
        assert SEGREDO not in repr(kwargs["env"])
        assert kwargs["env"]["RAIZ_TESTE_PA_FILHO"] == "1"
        assert kwargs["env"]["RAIZ_TESTE_PA_PASTA"] == str(pasta)
        assert kwargs["env"]["RUNNER_TRACKING_ID"] == "runner-de-teste"
        assert P.NO_TESTE in comando and "no:cacheprovider" in comando
        kwargs["stdout"].write(f"contato pessoal e {SEGREDO}".encode())
        if falha == "iniciar":
            raise OSError(SEGREDO)
        resultado = Path(next(x.split("=", 1)[1] for x in comando if x.startswith("--junitxml=")))
        resultado.write_text(f"<testsuite>{_caso('<failure/>' if falha == 'teste' else '')}</testsuite>")
        esperas = []
        estado = {"codigo": None}

        def esperar(timeout=None):
            esperas.append(timeout)
            if falha == "timeout" and len(esperas) == 1:
                raise subprocess.TimeoutExpired(SEGREDO, timeout, output=SEGREDO)
            if falha == "interrupcao" and len(esperas) == 1:
                raise KeyboardInterrupt
            estado["codigo"] = 1 if falha == "teste" else 0
            return estado["codigo"]

        return SimpleNamespace(pid=987654, wait=esperar, poll=lambda: estado["codigo"])

    monkeypatch.setattr(P.subprocess, "Popen", iniciar)
    monkeypatch.setattr(P.os, "killpg", lambda pid, sinal: grupos.append((pid, sinal)))
    if falha:
        with pytest.raises(KeyboardInterrupt if falha == "interrupcao" else P.FalhaPrivada) as erro:
            P.executar_preparado(pasta, timeout=1)
        assert SEGREDO not in str(erro.value)
    else:
        resumo = P.executar_preparado(pasta)
        assert set(resumo) == {"municipios", "imoveis", "segundos", "pico_rss_mib"}
        assert resumo["municipios"] == 144 and resumo["imoveis"] == 345870
    assert capsys.readouterr() == ("", "")
    assert len(chamadas) == 1
    assert not Path(chamadas[0][1]["stdout"].name).parent.exists()
    assert grupos == ([(987654, P.signal.SIGKILL)] if falha in {"timeout", "interrupcao"} else [])
    assert pasta.exists()


def test_timeout_real_encerra_filho_e_descendente_sem_deixar_logs(tmp_path, monkeypatch, capsys):
    assert sys.platform == "linux", "O supervisor e esta integração exigem o runner Linux do CI."
    libc = ctypes.CDLL(None, use_errno=True)
    anterior = ctypes.c_int()
    assert libc.prctl(37, ctypes.byref(anterior), 0, 0, 0) == 0, "PR_GET_CHILD_SUBREAPER indisponível."
    # Adota e recolhe o neto depois do killpg; o próprio teste não deixa zumbis no contêiner.
    processos, logs, temporizadores = [], [], []
    resgate = threading.Event()
    iniciar_real = subprocess.Popen
    descendente = tmp_path / "descendente.pid"
    pasta = tmp_path / "privado"
    pasta.mkdir(mode=0o700)
    tratador_anterior = P.signal.getsignal(P.signal.SIGTERM)
    programa = """
import signal
import subprocess
import sys
from pathlib import Path

filho = subprocess.Popen([sys.executable, "-c", "import signal; signal.pause()"])
Path(sys.argv[1]).write_text(str(filho.pid))
print("::error::contato e segredo inteiramente sintéticos", flush=True)
signal.pause()
"""

    def iniciar(comando, **kwargs):
        assert P.NO_TESTE in comando
        logs.append(Path(kwargs["stdout"].name))
        processo = iniciar_real([sys.executable, "-c", programa, str(descendente)], **kwargs)
        processos.append(processo)

        def resgatar():
            # Uma regressão no finally não pode pendurar o próprio teste.
            if processo.poll() is None:
                resgate.set()
                try:
                    os.killpg(processo.pid, P.signal.SIGKILL)
                except ProcessLookupError:
                    pass

        temporizador = threading.Timer(0.75, resgatar)
        temporizador.daemon = True
        temporizadores.append(temporizador)
        temporizador.start()
        limite = time.monotonic() + 0.75
        while not descendente.exists():
            assert processo.poll() is None, "O subprocesso sintético terminou antes da confirmação."
            assert time.monotonic() < limite, "O descendente sintético não iniciou no tempo reservado."
            time.sleep(0.005)
        return processo

    monkeypatch.setattr(P.subprocess, "Popen", iniciar)
    assert libc.prctl(36, 1, 0, 0, 0) == 0, "PR_SET_CHILD_SUBREAPER indisponível."
    try:
        with pytest.raises(P.FalhaPrivada, match="teste estadual privado não aprovado"):
            P.executar_preparado(pasta, timeout=0.1)
        assert not resgate.is_set(), "O encerramento exigiu o resgate do teste, não o supervisor."
        assert len(processos) == 1 and processos[0].returncode == -P.signal.SIGKILL
        pid = int(descendente.read_text())
        pidfd = os.pidfd_open(pid)
        try:
            prontos, _, _ = select.select([pidfd], [], [], 0.25)
            assert prontos, "O killpg do supervisor deixou o descendente vivo."
        finally:
            os.close(pidfd)
        recolhido, estado = os.waitpid(pid, os.WNOHANG)
        assert recolhido == pid and os.waitstatus_to_exitcode(estado) == -P.signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.killpg(processos[0].pid, 0)
        assert logs and all(not arquivo.parent.exists() for arquivo in logs)
        assert capsys.readouterr() == ("", "")
        assert P.signal.getsignal(P.signal.SIGTERM) == tratador_anterior
    finally:
        try:
            for temporizador in temporizadores:
                temporizador.cancel()
                temporizador.join(timeout=0.25)
            for processo in processos:
                try:
                    os.killpg(processo.pid, P.signal.SIGKILL)
                except ProcessLookupError:
                    pass
                processo.wait(timeout=0.5)
                limite = time.monotonic() + 0.5
                while True:
                    try:
                        pid, _ = os.waitpid(-processo.pid, os.WNOHANG)
                    except ChildProcessError:
                        break
                    if not pid:
                        assert time.monotonic() < limite, "Não foi possível recolher o descendente sintético."
                        time.sleep(0.005)
        finally:
            assert libc.prctl(36, anterior.value, 0, 0, 0) == 0, "Falha ao restaurar CHILD_SUBREAPER."


@pytest.mark.parametrize("falha", [P.FalhaPrivada("FALHA: acesso recusado."), OSError(SEGREDO)])
def test_preparacao_remove_download_parcial_e_nao_vaza_erro(tmp_path, falha):
    pasta = tmp_path / "privado"

    def baixar(ref, destino):
        destino.write_bytes(SEGREDO.encode())
        raise falha

    with pytest.raises(P.FalhaPrivada) as erro:
        P.preparar(pasta, SimpleNamespace(baixar=baixar))
    assert SEGREDO not in str(erro.value)
    assert not pasta.exists()


def test_preparacao_nao_apaga_pasta_anterior_na_recusa(tmp_path):
    pasta = tmp_path / "privado"
    pasta.mkdir(mode=0o700)
    anterior = pasta / "anterior"
    anterior.write_bytes(b"preservar")
    with pytest.raises(P.FalhaPrivada):
        P.preparar(pasta, SimpleNamespace())
    assert anterior.read_bytes() == b"preservar"


def test_estadual_sem_preparacao_falha_em_vez_de_pular(monkeypatch):
    estadual = importlib.import_module("testes.test_lote")
    monkeypatch.delenv("RAIZ_TESTE_PA_PASTA", raising=False)
    with pytest.raises(pytest.fail.Exception, match="preparação autenticada.*obrigatória"):
        estadual.test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta(monkeypatch)


@pytest.mark.parametrize("falha", [False, True])
def test_estadual_pai_delega_sem_ler_dados_ou_publicar_erro(tmp_path, monkeypatch, capsys, falha):
    estadual = importlib.import_module("testes.test_lote")
    monkeypatch.setenv("RAIZ_TESTE_PA_PASTA", str(tmp_path))
    monkeypatch.delenv("RAIZ_TESTE_PA_FILHO", raising=False)
    chamadas = []

    def executar(pasta):
        chamadas.append(pasta)
        if falha:
            raise ValueError(SEGREDO)
        return {"municipios": 144}

    def leitura_proibida(*args, **kwargs):
        pytest.fail("O processo pai não pode abrir o conjunto estadual.")

    monkeypatch.setattr(P, "executar_preparado", executar)
    monkeypatch.setattr(P, "conferir_preparado", leitura_proibida)
    monkeypatch.setattr(estadual.L, "ler_uf", leitura_proibida)
    if falha:
        with pytest.raises(pytest.fail.Exception, match="diagnósticos privados não são publicados") as erro:
            estadual.test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta(monkeypatch)
        assert SEGREDO not in str(erro.value)
    else:
        estadual.test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta(monkeypatch)
    assert chamadas == [tmp_path]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("fecha", [False, True])
def test_estadual_filho_confere_antes_de_ler_e_proibe_recalculo(tmp_path, monkeypatch, fecha):
    estadual = importlib.import_module("testes.test_lote")
    monkeypatch.setenv("RAIZ_TESTE_PA_PASTA", str(tmp_path))
    monkeypatch.setenv("RAIZ_TESTE_PA_FILHO", "1")
    chamadas = []
    pasta = tmp_path / "saida" / "PA"
    dados = object()

    def conferir(preparado):
        assert preparado == tmp_path
        chamadas.append("conferir")
        return pasta

    def ler_uf(saida, uf):
        assert chamadas == ["conferir"] and saida == pasta.parent and uf == "PA"
        with pytest.raises(pytest.fail.Exception, match="novo cálculo municipal não é permitido"):
            estadual.R.calcular_municipio(pasta, 1504950)
        chamadas.append("ler")
        return dados

    def montar(recebido):
        assert recebido is dados and chamadas == ["conferir", "ler"]
        chamadas.append("montar")
        return {
            "resumo": {
                "municipios": {"no_estado": 144, "lidos": 144},
                "fecha_com_reserva": fecha,
                "creditos_lote": 120,
                "creditos_precisa_com_reserva": 100,
                "o_que_falta": [] if fecha else ["pendência sintética"],
                "cronograma_lote": {"chance_todos": 0.9},
                "falta_reserva": 1,
            }
        }

    monkeypatch.setattr(P, "conferir_preparado", conferir)
    monkeypatch.setattr(estadual.L, "ler_uf", ler_uf)
    monkeypatch.setattr(estadual.L, "montar", montar)
    estadual.test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta(monkeypatch)
    assert chamadas == ["conferir", "ler", "montar"]
