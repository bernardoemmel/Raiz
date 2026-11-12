"""Exemplos sintéticos; documentos válidos gerados em memória, nunca escritos no git."""

import io
import logging

import httpx

from raiz import logs_seguros as L
from raiz.operacao.healthchecks import Healthchecks
from raiz.privacidade import FormatadorSeguro
from testes.test_privacidade import CNPJ, CPF


def test_presidio_portugues_remove_nomes_contato_e_documentos():
    # Nomes de exemplo, sem correspondência com os donos da base.
    texto = "João da Silva pediu contato; Maria Santos respondeu. "
    texto += f"email=teste@example.invalid, telefone +55 (11) 91234-5678, CPF {CPF}, CNPJ {CNPJ}"
    limpo = L.sanitizar_log(texto)
    assert "indisponível" not in limpo  # exercita o modelo real, não só a falha fechada
    for pessoal in ("João", "Silva", "Maria", "Santos", "teste@example.invalid", "91234-5678", CPF, CNPJ):
        assert pessoal not in limpo
    assert "<PERSON>" in limpo and "<EMAIL_ADDRESS>" in limpo and "<PHONE_NUMBER>" in limpo
    assert "***." in limpo and "/****-**" in limpo


def test_metricas_continuam_legiveis():
    texto = "lote finalizado: 27 fazendas, 4000 ha, tarefa funil"
    assert L.sanitizar_log(texto) == texto


def test_token_em_json_ou_query_nunca_fica_no_log():
    for texto in ('{"token": "credencial-sintetica"}', "?webhookSecret=credencial-sintetica&evento=teste"):
        assert "credencial-sintetica" not in L.sanitizar_log(texto)


def test_falha_no_presidio_nunca_libera_original(monkeypatch):
    def falhar():
        raise RuntimeError("erro que também contém contato@example.org")

    monkeypatch.setattr(L, "_ferramentas", falhar)
    assert L.sanitizar_log("contato@example.org") == "[log suprimido: sanitização indisponível]"


def test_formatador_sanitiza_argumentos_e_traceback_antes_de_escrever():
    arquivo = io.StringIO()
    handler = logging.StreamHandler(arquivo)
    handler.setFormatter(FormatadorSeguro("%(message)s"))
    logger = logging.Logger("teste-seguro")
    logger.addHandler(handler)
    try:
        raise ValueError("nome=Pessoa Sintética, contato@example.org")
    except ValueError:
        logger.exception("falha %s", "https://exemplo.org?webhookSecret=segredo-de-teste")
    salvo = arquivo.getvalue()
    assert "Pessoa Sintética" not in salvo and "contato@example.org" not in salvo
    assert "segredo-de-teste" not in salvo
    assert "ValueError" in salvo


def test_metadados_e_healthchecks_sanitizados():
    detalhe = L.sanitizar_estrutura(
        {"ha": 17.5, "nome_dono": "Pessoa Sintética", "api_token": "segredo", "erro": ["contato@example.org"]}
    )
    assert detalhe == {"ha": 17.5, "erro": ["<EMAIL_ADDRESS>"]}
    enviados = []

    def receber(r):
        enviados.append(r.content.decode())
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(receber)) as cliente:
        hc = Healthchecks(chave_ping="somente-teste", base="https://hc.example.org", cliente=cliente)
        assert hc.falha("lote", "teste", "nome=Pessoa Sintética, contato@example.org")
    assert "Pessoa Sintética" not in enviados[0] and "contato@example.org" not in enviados[0]


def _capturar_json_configurado(monkeypatch):
    from raiz.privacidade import configurar_log

    arquivo = io.StringIO()
    handler = logging.StreamHandler(arquivo)
    raiz = logging.getLogger()
    monkeypatch.setattr(raiz, "handlers", [handler])
    monkeypatch.setattr(raiz, "level", raiz.level)
    configurar_log()
    return arquivo, handler


def test_log_reentrante_do_analisador_e_descartado_sem_ruido_ou_conteudo(monkeypatch):
    import json

    ferramentas = L._ferramentas()
    arquivo, handler = _capturar_json_configurado(monkeypatch)

    def analisar_com_aviso():
        logging.getLogger("analisador-interno-teste").warning("nome=Pessoa Sintética, contato@example.invalid")
        return ferramentas

    monkeypatch.setattr(L, "_ferramentas", analisar_com_aviso)
    logging.getLogger("teste-http").warning(
        "falha: contato@example.invalid", extra={"evento": "http", "status": 500, "rota": "/pedidos/{id}"}
    )
    linhas = arquivo.getvalue().splitlines()
    assert len(linhas) == 1
    dado = json.loads(linhas[0])
    assert dado["nivel"] == "WARNING" and dado["logger"] == "teste-http"
    assert dado["evento"] == "http" and dado["status"] == 500 and dado["rota"] == "/pedidos/{id}"
    assert "<EMAIL_ADDRESS>" in dado["mensagem"]
    assert all(p not in linhas[0] for p in ("Pessoa Sintética", "contato@example.invalid", "indisponível"))
    # Configurar novamente não acumula filtros nem passa a ocultar registros normais.
    from raiz.privacidade import configurar_log

    configurar_log()
    assert len(handler.filters) == 1
    monkeypatch.setattr(L, "_ferramentas", lambda: ferramentas)
    logging.getLogger("analisador-interno-teste").warning("aviso normal fora da sanitização")
    assert len(arquivo.getvalue().splitlines()) == 2


def test_falha_real_da_sanitizacao_permanece_visivel_sem_original(monkeypatch):
    import json

    arquivo, _ = _capturar_json_configurado(monkeypatch)

    def falhar():
        logging.getLogger("analisador-interno-teste").warning("falha interna contato@example.invalid")
        raise RuntimeError("erro com nome=Pessoa Sintética")

    monkeypatch.setattr(L, "_ferramentas", falhar)
    logging.getLogger("teste").warning("não liberar contato@example.invalid")
    linhas = arquivo.getvalue().splitlines()
    assert len(linhas) == 1
    dado = json.loads(linhas[0])
    assert dado["nivel"] == "WARNING"
    assert dado["mensagem"] == "[log suprimido: sanitização indisponível]"
    assert "Pessoa Sintética" not in linhas[0] and "contato@example.invalid" not in linhas[0]


def test_filtro_nao_descarta_registro_de_outra_thread(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from raiz.privacidade import FiltroSanitizacao

    monkeypatch.setattr(L._estado, "ativo", True, raising=False)
    filtro = FiltroSanitizacao()
    registro = logging.LogRecord("teste", logging.WARNING, "", 1, "aviso normal", (), None)
    assert not filtro.filter(registro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(filtro.filter, registro).result()


def test_id_gerado_preserva_correlacao_sem_abrir_campo_a_texto_pessoal(monkeypatch):
    import json

    from raiz.privacidade import FormatadorJSON

    identificador = "abcdef0123456789" * 2
    monkeypatch.setattr(L, "sanitizar_log", lambda texto: "<PERSON>" if texto == identificador else texto)
    registro = logging.LogRecord("teste", logging.INFO, "", 1, "chamada HTTP", (), None)
    registro.requisicao_id = identificador
    assert json.loads(FormatadorJSON().format(registro))["requisicao_id"] == identificador
    registro.requisicao_id = "contato@example.invalid"
    assert "requisicao_id" not in json.loads(FormatadorJSON().format(registro))


def test_http_real_nao_cria_avisos_reentrantes_por_campo_json(monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from testes.test_seguranca_api import app_teste

    arquivo, _ = _capturar_json_configurado(monkeypatch)
    resposta = TestClient(app_teste()).get("/ok")
    linhas = [json.loads(linha) for linha in arquivo.getvalue().splitlines()]
    assert len(linhas) == 1
    assert linhas[0]["evento"] == "http" and linhas[0]["status"] == 200
    assert linhas[0]["requisicao_id"] == resposta.headers["x-request-id"]
    assert "indisponível" not in arquivo.getvalue()


# Credenciais sintéticas opacas não dependem de reconhecimento probabilístico de pessoas.
_CREDENCIAL = "afbecccdddeeaaafffbbbdddccceeaff"


def test_caminhos_de_reserva_cobranca_e_fragmento_de_login_ocultam_credencial():
    casos = (
        (f"GET /v1/reservas/confirmar/{_CREDENCIAL}/resumo HTTP/1.1 200", "/resumo HTTP/1.1 200"),
        (f"POST /v1/reservas/confirmar/{_CREDENCIAL}/entrar HTTP/1.1 200", "/entrar HTTP/1.1 200"),
        (f"GET /v1/cobrancas/{_CREDENCIAL} HTTP/1.1 402", "HTTP/1.1 402"),
        (f"https://api.example/reservas/confirmar/{_CREDENCIAL}", "https://api.example/reservas/confirmar/"),
        (f"https://painel.example/Raiz/#/entrar/{_CREDENCIAL}", "https://painel.example/Raiz/#/entrar/"),
    )
    for entrada, preservado in casos:
        saida = L._sem_credenciais(entrada)
        assert _CREDENCIAL not in saida
        assert "[SEGREDO]" in saida and preservado in saida


def test_query_e_fragmentos_oauth_ocultam_tokens_sem_apagar_parametros_operacionais():
    for chave in ("token", "access_token", "refresh_token", "id_token", "code", "session_state", "t%6Fken"):
        for separador in ("?", "#", "&"):
            entrada = f"https://painel.example/Raiz/{separador}{chave}={_CREDENCIAL}&pagina=2"
            saida = L._sem_credenciais(entrada)
            assert _CREDENCIAL not in saida
            assert f"{separador}{chave}=" in saida and "pagina=2" in saida
    assert L._sem_credenciais("GET /v1/pedidos?pagina=2 HTTP/1.1 200") == "GET /v1/pedidos?pagina=2 HTTP/1.1 200"
    assert L._sem_credenciais("code=200 fazendas=27 creditos=4000") == "code=200 fazendas=27 creditos=4000"


def test_credenciais_em_campos_e_estruturas_sao_removidas():
    for chave in ("X-Chave-API", "api_key", "refresh_token", "id_token", "session", "sessao"):
        assert _CREDENCIAL not in L._sem_credenciais(f"{chave}: {_CREDENCIAL}")
        assert chave not in L.sanitizar_estrutura({chave: _CREDENCIAL, "status": 200})


def test_formatador_de_acesso_com_modelo_real_preserva_rota_e_status_sem_token():
    caminho = f"/v1/reservas/confirmar/{_CREDENCIAL}/resumo"
    registro = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1:1", "GET", caminho, "1.1", 200),
        None,
    )
    texto = FormatadorSeguro("%(message)s").format(registro)
    assert _CREDENCIAL not in texto and "indisponível" not in texto
    assert "/v1/reservas/confirmar/[SEGREDO]/resumo" in texto
    assert "GET" in texto and 'HTTP/1.1" 200' in texto


def test_mascara_de_credenciais_e_estavel_ao_sanitizar_novamente():
    entrada = f"https://painel.example/?token={_CREDENCIAL}&pagina=2#/entrar/{_CREDENCIAL}"
    primeira = L._sem_credenciais(entrada)
    assert L._sem_credenciais(primeira) == primeira
    assert primeira.count("[SEGREDO]") == 2
