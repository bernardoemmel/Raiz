"""HTTP e ferramentas dependem do mesmo acesso; o PDF só contém dados da terra."""

import io
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from raiz import imovel_dados, prospeccao_mcp, prospeccao_pdf
from raiz import prospeccao_servico as servico
from raiz.prospeccao_acesso import ErroAcesso

CAR = "PA-1504950-" + "A" * 32
OUTRO = "PA-1504950-" + "B" * 32


@pytest.fixture
def acesso(monkeypatch):
    eventos = []
    monkeypatch.setattr(servico.acesso, "limitar", lambda *a: eventos.append(("limite", a[1:4])))
    monkeypatch.setattr(servico.pedidos, "cliente_da_sessao", lambda _, token: 7 if token == "sessao-valida" else None)
    monkeypatch.setattr(servico.acesso, "exigir_desbloqueio", lambda _, cid, car: car)
    monkeypatch.setattr(servico, "_montar", lambda _, car: {"codigo_car": car})
    monkeypatch.setattr(servico.prospeccao_versoes, "consultas", lambda _eng, _cid, fichas: nullcontext(fichas))
    monkeypatch.setattr(
        servico.prospeccao_protecao, "operacao_vigiada", lambda *args, **kwargs: nullcontext(lambda *_: None)
    )
    return eventos


def _mcp(argumentos, contexto=None, autorizar=None):
    contexto = contexto or SimpleNamespace(cliente_id=7, via="mcp", escopos=frozenset({"consultar"}))
    return prospeccao_mcp.executar(
        None,
        contexto,
        "consultar_ficha",
        argumentos,
        autorizar_detalhes=autorizar or (lambda *_: nullcontext()),
    )


def test_mcp_usa_contexto_oauth_e_servico_sem_aceitar_identidade_do_argumento(acesso):
    resposta = _mcp({"codigo_car": CAR})
    assert resposta["structuredContent"] == json.loads(resposta["content"][0]["text"]) == {"codigo_car": CAR}
    assert acesso == [("limite", ("cliente:7", "consultas", 60)), ("limite", ("cliente:7", "fichas", 30))]
    with pytest.raises(ErroAcesso) as erro:
        _mcp({"codigo_car": CAR, "cliente_id": 8})
    assert erro.value.status == 422
    with pytest.raises(ErroAcesso) as erro:
        _mcp({"codigo_car": CAR}, contexto="sessao-valida")
    assert erro.value.status == 401
    assert "token" not in json.dumps(prospeccao_mcp.ferramentas())


def test_mcp_nao_contorna_autorizacao_corporativa_do_host(acesso, monkeypatch):
    montadas = []
    monkeypatch.setattr(servico, "_montar", lambda *args: montadas.append(args))

    def negar_conta(*_):
        raise ErroAcesso(403, "A empresa precisa do sinal e do contrato.")

    with pytest.raises(ErroAcesso) as erro:
        _mcp({"codigo_car": CAR}, autorizar=negar_conta)
    assert erro.value.status == 403 and not montadas
    for via, escopos, status in (("sessao", {"consultar"}, 401), ("api", {"consultar"}, 401), ("mcp", {"pedir"}, 403)):
        with pytest.raises(ErroAcesso) as erro:
            _mcp({"codigo_car": CAR}, contexto=SimpleNamespace(cliente_id=7, via=via, escopos=escopos))
        assert erro.value.status == status
    with pytest.raises(TypeError):
        prospeccao_mcp.executar(
            None,
            SimpleNamespace(cliente_id=7, via="mcp", escopos={"consultar"}),
            "consultar_ficha",
            {"codigo_car": CAR},
        )


def test_mcp_nao_contorna_ficha_bloqueada_ou_limite(acesso, monkeypatch):
    def negar(*_):
        raise ErroAcesso(402, "Ficha ainda não liberada.")

    monkeypatch.setattr(servico.acesso, "exigir_desbloqueio", negar)
    with pytest.raises(ErroAcesso) as erro:
        _mcp({"codigo_car": CAR})
    assert erro.value.status == 402

    def limitar(*_):
        raise ErroAcesso(429, "Aguarde.", 60)

    monkeypatch.setattr(servico.acesso, "limitar", limitar)
    with pytest.raises(ErroAcesso) as erro:
        _mcp({"codigo_car": CAR})
    assert erro.value.status == 429


def test_comparacao_nao_compra_acesso_nem_monta_parcial(acesso, monkeypatch):
    montadas, cobradas = [], []

    def autorizar(_, cid, car):
        if car == OUTRO:
            raise ErroAcesso(402, "Libere a ficha.")
        return car

    monkeypatch.setattr(servico.acesso, "exigir_desbloqueio", autorizar)
    monkeypatch.setattr(servico.acesso, "desbloquear", lambda *args: cobradas.append(args))
    monkeypatch.setattr(servico, "_montar", lambda _, car: montadas.append(car))
    with pytest.raises(ErroAcesso):
        servico.comparar_fichas(None, 7, [CAR, OUTRO])
    assert not montadas and not cobradas


@pytest.mark.parametrize("cars", [[], [CAR], [CAR] * 6, [CAR, CAR.lower()], [CAR, 4]])
def test_comparacao_rejeita_quantidade_e_car_repetido(acesso, cars):
    with pytest.raises(ErroAcesso) as erro:
        servico.comparar_fichas(None, 7, cars)
    assert erro.value.status == 422


def test_pdf_preserva_fontes_datas_estimativas_e_ausencia_sem_campos_livres():
    ficha = imovel_dados.ficha_prospeccao(
        {
            "cod_imovel": CAR,
            "ha": 0,
            "carbono_ha": 2.5,
            "municipio": "Município de teste",
            "data_atualizacao": "2026-01-08",
            "ibama_data_referencia": "2025-11-20",
        },
        {"data_corte": "2026-11-12"},
        {"serie_uso": {"anos": [2020], "mata_pct": [42]}},
    )
    ficha["nome_dono"] = "SEGREDO_PROIBIDO"
    ficha["area_total"]["contato"] = "SEGREDO_ANINHADO"
    ficha["sobreposicoes"][0]["cpf"] = "SEGREDO_DOCUMENTO"
    marca = servico.prospeccao_protecao.MarcaExportacao("RZP-teste-" + "a" * 32, "teste")
    pdf = prospeccao_pdf.gerar_pdf(ficha, marca=marca)
    texto = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert pdf.startswith(b"%PDF-")
    for esperado in (
        CAR,
        "SICAR",
        "2026-01-08",
        "2026-11-12",
        "MapBiomas",
        "2020",
        "42.0",
        "0.0",
        "não disponível",
        "P10",
        "P50",
        "P90",
        "Estimado: sim",
        "TIR",
    ):
        assert esperado in texto
    assert "SEGREDO" not in texto


def test_exportacao_passou_pelo_mesmo_desbloqueio(acesso, monkeypatch):
    def negar(*_):
        raise ErroAcesso(404, "Fazenda reservada.")

    monkeypatch.setattr(servico.acesso, "exigir_desbloqueio", negar)
    with pytest.raises(ErroAcesso) as erro:
        servico.exportar_ficha_pdf(None, 7, CAR)
    assert erro.value.status == 404
