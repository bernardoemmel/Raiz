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
