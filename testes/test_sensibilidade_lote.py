"""A tela só recebe cenários completos, do pedido e modelo autorizados; ausência não vira extrapolação."""

import copy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from raiz.pedidos import sensibilidade as S
from raiz.publica import api, chaves, conta, rotas_agentes

PID = "aaaaaaaa-bbbb-4ccc-8ddd-aaaaaaaaaaaa"
PEDIDO = {"id": PID, "versao_modelo": "modelo-fixture-v1"}
PARAMETROS = {"preco_credito_usd": 55, "reserva_reversao": 0.2, "taxa_desconto": 0.092, "pessimista": False}


def grade():
    return {
        "pedido_id": PID,
        "modelo_versao": PEDIDO["versao_modelo"],
        "atualizado_em": "2026-11-12T15:00:00Z",
        "fonte": "Grade sintética de teste",
        "aviso": "Não é resultado real.",
        "cenarios": [
            {
                "parametros": PARAMETROS,
                "opcoes": [
                    {
                        "id": i,
                        "creditos": {"p10": 700_000, "p50": 1_000_000, "p90": 1_200_000},
                        "hectares": 4_000,
                        "fazendas": 40,
                        "vpl_usd": 100,
                        "tir_projeto": None,
                        "alcanca_meta": True,
                    }
                    for i in ("barata", "segura", "compacta")
                ],
            }
        ],
    }


@pytest.fixture
def publicar(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_SENSIBILIDADE_DIRETORIO", str(tmp_path))

    def salvar(dados):
        (tmp_path / f"{PID}.json").write_text(json.dumps(dados), encoding="utf-8")

    return salvar


def test_grade_exata_preserva_nulo_e_zero_sem_detalhes_por_fazenda(publicar):
    dados = grade()
    dados["cenarios"][0]["opcoes"][1]["vpl_usd"] = 0
    publicar(dados)
    resposta = S.consultar(PEDIDO, S.ParametrosSensibilidade(**PARAMETROS))
    assert resposta["estado"] == "disponivel"
    assert resposta["exemplo"] is False
    assert resposta["opcoes"][0]["tir_projeto"] is None
    assert resposta["opcoes"][1]["vpl_usd"] == 0
    assert "pedido_id" not in resposta
    assert "cenarios" not in resposta


def test_falta_grade_ou_combinacao_nao_inventa_resultado(publicar):
    p = S.ParametrosSensibilidade(**PARAMETROS)
    assert S.consultar(PEDIDO, p)["opcoes"] == []
    publicar(grade())
    r = S.consultar(PEDIDO, p.model_copy(update={"preco_credito_usd": 56}))
    assert r["estado"] == "indisponivel"
    assert r["opcoes"] == []
    assert "não interpola" in r["aviso"]


@pytest.mark.parametrize(
    "mudar",
    [
        lambda d: d.update(pedido_id="bbbbbbbb-bbbb-4ccc-8ddd-aaaaaaaaaaaa"),
        lambda d: d.update(modelo_versao="outro-modelo"),
        lambda d: d.update(atualizado_em="2026-11-12T15:00:00"),
        lambda d: d["cenarios"][0]["opcoes"].pop(),
        lambda d: d["cenarios"][0]["opcoes"][0].update(cod_imovel="DEMONSTRACAO-1"),
        lambda d: d["cenarios"][0]["opcoes"][0]["creditos"].update(p10=2_000_000),
        lambda d: d["cenarios"].append(copy.deepcopy(d["cenarios"][0])),
    ],
)
def test_recusa_modelo_pedido_campos_ou_grade_ambiguos(publicar, mudar):
    dados = grade()
    mudar(dados)
    publicar(dados)
    assert S.consultar(PEDIDO, S.ParametrosSensibilidade(**PARAMETROS))["estado"] == "indisponivel"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("reserva_reversao", 0.199),
        ("reserva_reversao", 1),
        ("preco_credito_usd", 0),
        ("preco_credito_usd", float("inf")),
        ("taxa_desconto", -0.1),
        ("taxa_desconto", float("nan")),
        ("pessimista", "false"),
    ],
)
def test_limites_das_premissas(campo, valor):
    with pytest.raises(ValidationError):
        S.ParametrosSensibilidade(**{**PARAMETROS, campo: valor})


def test_api_autoriza_conta_e_pedido_antes_de_ler_arquivo(monkeypatch):
    from raiz.pedidos import servico

    eventos = []
    monkeypatch.setattr(servico, "cliente_da_sessao", lambda *_: 42)
    monkeypatch.setattr(chaves, "registrar", lambda *a, **k: None)
    monkeypatch.setattr(rotas_agentes, "exigir_escopo", lambda *a: eventos.append("escopo"))
    monkeypatch.setattr(conta, "exigir_liberacao", lambda *a: eventos.append("liberacao"))

    def obter(_, pid, cliente):
        eventos.append("propriedade")
        assert pid == PID and cliente == 42
        raise servico.ErroPedido("pedido não encontrado")

    monkeypatch.setattr(servico, "obter_pedido", obter)
    monkeypatch.setattr(S, "consultar", lambda *a: pytest.fail("não ler grade antes de verificar a propriedade"))
    with TestClient(api.criar(lambda _: object())) as cl:
        assert cl.post(f"/pedidos/{PID}/sensibilidade", json=PARAMETROS).status_code == 401
        assert eventos == []
        assert (
            cl.post(
                f"/pedidos/{PID}/sensibilidade", json=PARAMETROS, headers={"Authorization": "Bearer sessao-fixture"}
            ).status_code
            == 404
        )
    assert eventos == ["escopo", "liberacao", "propriedade"]


def test_api_responde_ausencia_sem_404_e_sem_cache(monkeypatch):
    from raiz.pedidos import servico

    monkeypatch.delenv("RAIZ_SENSIBILIDADE_DIRETORIO", raising=False)
    monkeypatch.setattr(servico, "cliente_da_sessao", lambda *_: 42)
    monkeypatch.setattr(chaves, "registrar", lambda *a, **k: None)
    monkeypatch.setattr(rotas_agentes, "exigir_escopo", lambda *a: None)
    monkeypatch.setattr(conta, "exigir_liberacao", lambda *a: None)
    monkeypatch.setattr(servico, "obter_pedido", lambda *a: PEDIDO)
    with TestClient(api.criar(lambda _: object())) as cl:
        r = cl.post(
            f"/pedidos/{PID}/sensibilidade", json=PARAMETROS, headers={"Authorization": "Bearer sessao-fixture"}
        )
    assert r.status_code == 200
    assert r.json()["estado"] == "indisponivel"
    assert r.headers["cache-control"] == "private, no-store"
