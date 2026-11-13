"""A ficha privada exige evidência comum; não deriva elegibilidade dos hectares do resumo."""

import copy
import json
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from raiz.pedidos import ficha_credito as F
from raiz.pedidos import servico
from raiz.publica import apresentacao, privacidade

PID = "aaaaaaaa-bbbb-4ccc-8ddd-aaaaaaaaaaaa"
PEDIDO = {"id": PID, "revisao_lote": "a" * 64, "versao_modelo": "pedidos-2026a", "opcoes": [{"id": "barata"}]}


def documento():
    return {
        "contrato": "ficha_credito",
        "versao": 1,
        "pedido_id": PID,
        "revisao_lote": PEDIDO["revisao_lote"],
        "opcao_id": "barata",
        "publicada_em": "2026-11-12T12:00:00Z",
        "base": {
            "horizonte_anos": 25,
            "unidade": "tCO2e",
            "escopo_carteira": "titulares",
            "inicio": "2026-01-01",
            "fim": "2051-01-01",
            "classe_ativo": "credito_carbono",
            "classe_evidencia": "estimativa_modelo",
            "metodo": "regeneracao_assistida",
            "modelo_versao": PEDIDO["versao_modelo"],
            "fonte": "Raíz, motor de lotes",
            "data_referencia": "2026-11-10",
            "evidencia_id": "ensaio-sintetico-v1",
        },
        "creditos_lote": {"p10": 100, "p50": 200, "p90": 300},
        "area_total_ha": 100,
        "area_elegivel_ha": 50,
        "fonte_area": "Raíz, motor de lotes",
        "data_referencia_area": "2026-11-10",
        "evidencia_area_id": "area-sintetica-v1",
        "exclusoes": None,
        "secoes": {n: {"texto": None, "fonte": None, "data_referencia": None, "revisado_em": None} for n in F.SECOES},
    }


@pytest.fixture
def publicar(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_FICHAS_CREDITO_DIRETORIO", str(tmp_path))

    def gravar(d):
        pasta = tmp_path / PID / PEDIDO["revisao_lote"]
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "barata.json").write_text(json.dumps(d), encoding="utf-8")

    return gravar


def test_mesmos_quantis_e_area_elegivel_nao_area_total(publicar):
    publicar(documento())
    r = F.consultar(PEDIDO, "barata")
    assert r["estado"] == "disponivel"
    assert r["creditos_por_ha"] == {"p10": 2, "p50": 4, "p90": 6}
    assert r["area_total_ha"] == 100
    assert r["exclusoes"] is None
    assert r["secoes"]["garantias"]["revisado_em"] is None
    assert "pedido_id" not in r
    assert "cod_imovel" not in json.dumps(r)


def test_sem_ficha_e_area_desconhecida_nao_viram_zero(publicar):
    assert F.consultar(PEDIDO, "barata")["base"] is None
    d = documento()
    d.update(area_elegivel_ha=None)
    publicar(d)
    r = F.consultar(PEDIDO, "barata")
    assert r["estado"] == "disponivel"
    assert r["creditos_lote"]["p50"] == 200
    assert r["creditos_por_ha"] is None


@pytest.mark.parametrize(
    "mudar",
    [
        lambda d: d["base"].update(fim="2050-01-01"),
        lambda d: d["base"].update(inicio=None),
        lambda d: d["base"].pop("classe_evidencia"),
        lambda d: d["base"].pop("escopo_carteira"),
        lambda d: d["base"].update(classe_ativo="flag", classe_evidencia="emitido"),
        lambda d: d["base"].update(classe_evidencia="verificado"),
        lambda d: d["base"].update(modelo_versao="outro-modelo"),
        lambda d: d["base"].update(fonte="Pessoa Fictícia do Teste"),
        lambda d: d.update(area_elegivel_ha=True),
        lambda d: d.update(area_elegivel_ha=0),
        lambda d: d.update(area_elegivel_ha=1e-320),
        lambda d: d.update(area_elegivel_ha=101),
        lambda d: d.update(area_elegivel_ha=float("inf")),
        lambda d: d.update(evidencia_area_id=None),
        lambda d: d.update(revisao_lote="b" * 64),
        lambda d: d.update(pedido_id="bbbbbbbb-bbbb-4ccc-8ddd-aaaaaaaaaaaa"),
        lambda d: d.update(opcao_id="segura"),
        lambda d: d.update(publicada_em="2026-11-12T12:00:00"),
        lambda d: d.update(proprietario="Pessoa Fictícia do Teste"),
        lambda d: d["creditos_lote"].update(p10=400),
        lambda d: d["secoes"]["titulo"].update(texto="Pessoa Fictícia do Teste", fonte="Raíz, revisão técnica"),
        lambda d: d["secoes"]["titulo"].update(revisado_em="2026-11-13"),
        lambda d: d["secoes"]["titulo"].update(data_referencia="2026-11-10", revisado_em="2026-11-09"),
    ],
)
def test_payload_invalido_falha_fechada(publicar, mudar):
    d = documento()
    mudar(d)
    publicar(d)
    assert F.consultar(PEDIDO, "barata")["estado"] == "indisponivel"


def test_revisao_nova_nao_reusa_ficha_antiga(publicar):
    publicar(documento())
    assert F.consultar({**PEDIDO, "revisao_lote": "b" * 64}, "barata")["estado"] == "indisponivel"
    assert F.consultar({**PEDIDO, "opcoes": []}, "barata")["estado"] == "indisponivel"


def test_documento_muda_com_evidencia_e_revisao_de_secao(publicar):
    d = documento()
    publicar(d)
    antes = F.consultar(PEDIDO, "barata")
    d["secoes"]["titulo"] = {
        "texto": "Há pendências documentais no lote.",
        "fonte": "Raíz, revisão técnica",
        "data_referencia": "2026-11-09",
        "revisado_em": "2026-11-11",
    }
    publicar(d)
    depois = F.consultar(PEDIDO, "barata")
    assert antes["documento_versao"] != depois["documento_versao"]
    assert depois["secoes"]["titulo"]["revisado_em"] == "2026-11-11"
    assert depois["secoes"]["garantias"]["revisado_em"] is None


def test_projecao_revalida_hash_e_nao_aceita_anexo_bruto(publicar):
    publicar(documento())
    r = F.consultar(PEDIDO, "barata")
    assert F.projetar_resposta(r, PEDIDO, "barata") == r
    adulterado = copy.deepcopy(r)
    adulterado["area_elegivel_ha"] = 40
    assert F.projetar_resposta(adulterado, PEDIDO, "barata")["estado"] == "indisponivel"
    adulterado = {**r, "proprietario": "Pessoa Fictícia do Teste"}
    assert F.projetar_resposta(adulterado, PEDIDO, "barata")["estado"] == "indisponivel"
    p = {**PEDIDO, "opcoes": [{"id": "barata", "ficha_credito": r}]}
    assert apresentacao.pedido(p)["opcoes"][0]["ficha_credito"] == r


def test_sugestao_antiga_nao_publica_ficha_anexada():
    o = {"id": "barata", "itens": [], "ficha_credito": {"proprietario": "Pessoa Fictícia do Teste"}}
    assert "ficha_credito" not in servico._limpar_opcoes([o], {}, set())[0]
    assert "Pessoa Fictícia" not in json.dumps(apresentacao.pedido({**PEDIDO, "opcoes": [o]}))


def test_autorizacao_antecede_leitura_do_documento(monkeypatch):
    engine = Mock()
    engine.connect.return_value = nullcontext(Mock())
    monkeypatch.setattr(servico, "_linha_pedido", Mock(side_effect=servico.ErroPedido("pedido não encontrado")))
    ler = Mock()
    monkeypatch.setattr(F, "consultar", ler)
    with pytest.raises(servico.ErroPedido):
        servico.obter_pedido(engine, PID, 999)
    ler.assert_not_called()


def test_hash_numerico_nao_e_confundido_com_telefone():
    digest = "1234567890" * 6 + "1234"
    assert privacidade.para_resposta({"documento_versao": digest, "revisao_lote": digest}) == {
        "documento_versao": digest,
        "revisao_lote": digest,
    }


def test_get_pedido_autenticado_preserva_ficha_e_proibe_cache(publicar, monkeypatch):
    from fastapi.testclient import TestClient

    from raiz.publica import api, chaves, conta, rotas_agentes

    publicar(documento())
    ficha = F.consultar(PEDIDO, "barata")
    p = {**PEDIDO, "opcoes": [{"id": "barata", "itens": [], "ficha_credito": ficha}]}
    monkeypatch.setattr(servico, "cliente_da_sessao", lambda *_: 42)
    monkeypatch.setattr(chaves, "registrar", lambda *a, **k: None)
    monkeypatch.setattr(rotas_agentes, "exigir_escopo", lambda *a: None)
    monkeypatch.setattr(conta, "exigir_liberacao", lambda *a: None)
    monkeypatch.setattr(conta, "cobrar", lambda *a: None)
    monkeypatch.setattr(conta, "valor_cobrado", lambda *a: 0)
    obter = Mock(return_value=p)
    monkeypatch.setattr(servico, "obter_pedido", obter)
    with TestClient(api.criar(lambda _: object())) as cl:
        assert cl.get(f"/pedidos/{PID}").status_code == 401
        obter.assert_not_called()
        resposta = cl.get(f"/pedidos/{PID}", headers={"Authorization": "Bearer sessao-fixture"})
    assert resposta.status_code == 200
    assert obter.call_args.args[1:] == (PID, 42)
    assert resposta.headers["cache-control"] == "private, no-store"
    assert "Authorization" in resposta.headers["vary"]
    assert resposta.json()["opcoes"][0]["ficha_credito"] == ficha
