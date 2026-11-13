"""A ficha privada exige evidência comum; não deriva elegibilidade dos hectares do resumo."""

import copy
import datetime as dt
import json
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

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
            "metrica": "credito_liquido",
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
        "secoes": {
            **{n: {"texto": None, "fonte": None, "data_referencia": None, "revisado_em": None} for n in F.SECOES},
            "metodo": {
                "texto": F.ORIGEM_EVIDENCIA["estimativa_modelo"][1],
                "fonte": "Raíz, motor de lotes",
                "data_referencia": "2026-11-10",
                "revisado_em": None,
            },
        },
    }


def com_resultados():
    """Contratos e backtest sintéticos sobre a mesma carteira e o mesmo período da ficha."""
    d = documento()
    d["base"].update(inicio="2000-01-01", fim="2025-01-01")
    ref = {
        "classe": "credito_carbono",
        "metrica": "credito_liquido",
        "unidade": "tCO2e",
        "escala": "lote",
        "escopo_carteira": "titulares",
        "area_base_ha": 50,
        "area_elegivel_carteira_ha": 50,
        "inicio": "2000-01-01",
        "fim": "2025-01-01",
        "horizonte_dias": (dt.date(2025, 1, 1) - dt.date(2000, 1, 1)).days,
    }
    fonte = {"nome": "Banco de aprendizado da Raíz", "registro_id": "evidencia-sintetica", "data": "2026-11-10"}
    d["resultados"] = {
        "schema": "raiz.resultados.graficos.v1",
        "origem": "real",  # exercita o contrato operacional somente com valores sintéticos do teste
        "gerado_em": "2026-11-11T00:00:00Z",
        "contratos": [
            {
                "id": "contrato-sintetico",
                "metodo": "regeneracao_assistida",
                "referencia": copy.deepcopy(ref),
                "regime": "acumulado",
                "marcos": [{"data": "2025-01-01", "contratado": None, "emitido": None, "entregue": None}],
            }
        ],
        "comparacoes": [
            {
                "id": "backtest-sintetico",
                "metodo": "regeneracao_assistida",
                "modelo": "ensaio",
                "versao": "v1",
                "avaliacao": "backtest",
                "previsao": {
                    "referencia": copy.deepcopy(ref),
                    "corte": "2000-01-01",
                    "congelada_em": "2026-11-10T00:00:00Z",
                    "p10": 100,
                    "p50": 200,
                    "p90": 300,
                    "fonte": copy.deepcopy(fonte),
                },
                "observado": {
                    "referencia": copy.deepcopy(ref),
                    "data": "2025-01-01",
                    "registrado_em": "2025-01-02T00:00:00Z",
                    "valor": 150,
                    "fonte": {**fonte, "data": "2025-01-01"},
                },
            }
        ],
    }
    return d


def referencias(d):
    return [
        d["resultados"]["contratos"][0]["referencia"],
        d["resultados"]["comparacoes"][0]["previsao"]["referencia"],
        d["resultados"]["comparacoes"][0]["observado"]["referencia"],
    ]


def test_acompanhamento_mesma_carteira_aceita_total_e_por_hectare(publicar):
    d = com_resultados()
    publicar(d)
    assert F.consultar(PEDIDO, "barata")["resultados"]["comparacoes"][0]["avaliacao"] == "backtest"
    for ref in referencias(d):
        ref.update(escala="por_hectare", unidade="tCO2e/ha", area_base_ha=1)
    publicar(d)
    assert F.consultar(PEDIDO, "barata")["estado"] == "disponivel"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("classe", "flag"),
        ("metrica", "captura_bruta"),
        ("escopo_carteira", "titulares_e_reservas"),
        ("unidade", "tCO2e/ano"),
        ("area_elegivel_carteira_ha", 999),
    ],
)
def test_grafico_coerente_sozinho_mas_de_outra_carteira_e_recusado(publicar, campo, valor):
    d = com_resultados()
    for ref in referencias(d):
        ref[campo] = valor
        if campo == "area_elegivel_carteira_ha":
            ref["area_base_ha"] = valor
    # As duas evidências do gráfico concordam entre si; quem precisa barrar é a ficha externa.
    F.ResultadosGraficos.model_validate(d["resultados"])
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)
    publicar(d)
    assert F.consultar(PEDIDO, "barata")["estado"] == "indisponivel"


def test_por_hectare_guarda_denominador_original_da_carteira():
    d = com_resultados()
    for ref in referencias(d):
        ref.update(escala="por_hectare", unidade="tCO2e/ha", area_base_ha=1, area_elegivel_carteira_ha=999)
    F.ResultadosGraficos.model_validate(d["resultados"])
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)


@pytest.mark.parametrize(
    "alvo",
    ["publicacao", "registro_observado", "congelamento", "sem_calendario", "outro_periodo", "sem_area", "marco_fora"],
)
def test_cronologia_e_base_do_acompanhamento_na_ficha(alvo):
    d = com_resultados()
    r = d["resultados"]
    if alvo == "publicacao":
        r["gerado_em"] = "2026-11-12T13:00:00Z"
    elif alvo in {"registro_observado", "congelamento"}:
        chave, campo = ("observado", "registrado_em") if alvo == "registro_observado" else ("previsao", "congelada_em")
        r["comparacoes"][0][chave][campo] = "2026-11-12T13:00:00Z"
        r["gerado_em"] = "2026-11-12T14:00:00Z"
    elif alvo == "sem_calendario":
        d["base"].update(inicio=None, fim=None)
    elif alvo == "outro_periodo":
        d["base"].update(inicio="2001-01-01", fim="2026-01-01")
    elif alvo == "sem_area":
        d["area_elegivel_ha"] = None
    else:
        r["contratos"][0]["marcos"][0]["data"] = "1999-12-31"
    F.ResultadosGraficos.model_validate(r)
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)


def test_regressao_exata_anexo_futuro_flag_999ha_em_ficha_carbono_50ha(publicar):
    d = com_resultados()
    d["base"].update(inicio="2026-01-01", fim="2051-01-01")
    r = d["resultados"]
    r["gerado_em"] = "2027-01-03T00:00:00Z"
    for ref in referencias(d):
        ref.update(
            classe="flag",
            area_base_ha=999,
            area_elegivel_carteira_ha=999,
            inicio="2026-01-01",
            fim="2027-01-01",
            horizonte_dias=365,
        )
    c = r["comparacoes"][0]
    c["previsao"].update(corte="2026-01-01", congelada_em="2026-01-01T00:00:00Z")
    c["observado"].update(data="2027-01-01", registrado_em="2027-01-02T00:00:00Z")
    r["contratos"][0]["marcos"][0]["data"] = "2027-01-01"
    F.ResultadosGraficos.model_validate(r)  # contrato interno válido; anexo incompatível com esta ficha
    publicar(d)
    assert F.consultar(PEDIDO, "barata")["estado"] == "indisponivel"


@pytest.mark.parametrize("publicada", ["2026-11-12T12:00:00Z", "2026-11-13T02:00:00+14:00"])
@pytest.mark.parametrize("instante", ["2026-11-12T10:00:00Z", "2026-11-13T00:00:00+14:00"])
@pytest.mark.parametrize("dia_observado", [12, 13])
def test_fuso_nao_antecipa_dia_observado_na_ficha(publicar, publicada, instante, dia_observado):
    d = com_resultados()
    inicio, fim = f"2001-11-{dia_observado}", f"2026-11-{dia_observado}"
    d["publicada_em"] = publicada
    d["base"].update(inicio=inicio, fim=fim)
    for ref in referencias(d):
        ref.update(
            inicio=inicio, fim=fim, horizonte_dias=(dt.date.fromisoformat(fim) - dt.date.fromisoformat(inicio)).days
        )
    r = d["resultados"]
    r["gerado_em"] = instante
    r["contratos"][0]["marcos"][0]["data"] = fim
    c = r["comparacoes"][0]
    c["previsao"]["corte"] = inicio
    c["observado"].update(data=fim, registrado_em=instante)
    c["observado"]["fonte"]["data"] = fim
    publicar(d)
    resposta = F.consultar(PEDIDO, "barata")
    estado = "disponivel" if dia_observado == 12 else "indisponivel"
    assert resposta["estado"] == estado
    assert F.projetar_resposta(resposta, PEDIDO, "barata")["estado"] == estado


@pytest.mark.parametrize("publicada", ["2026-11-12T12:00:00Z", "2026-11-13T02:00:00+14:00"])
@pytest.mark.parametrize("alvo", ["base", "area", "revisao"])
def test_referencias_da_ficha_limitadas_ao_dia_utc_da_publicacao(publicada, alvo):
    d = documento()
    d["publicada_em"] = publicada
    if alvo == "base":
        d["base"]["data_referencia"] = "2026-11-13"
        d["secoes"]["metodo"]["data_referencia"] = "2026-11-13"
    elif alvo == "area":
        d["data_referencia_area"] = "2026-11-13"
    else:
        d["secoes"]["titulo"]["revisado_em"] = "2026-11-13"
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)


@pytest.mark.parametrize("classe", ["verificado", "emitido", "entregue", "validado", "conservador"])
def test_estimativa_do_motor_nao_pode_ser_promovida_a_fato(classe):
    d = documento()
    d["base"].update(inicio="2000-01-01", fim="2025-01-01", classe_evidencia=classe)
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)


@pytest.mark.parametrize("classe", ["verificado", "emitido", "entregue"])
def test_classe_exige_origem_conclusao_e_data_compativeis(classe):
    d = documento()
    fonte, texto = F.ORIGEM_EVIDENCIA[classe]
    d["base"].update(inicio="2000-01-01", fim="2025-01-01", classe_evidencia=classe, fonte=fonte)
    d["creditos_lote"] = {"p10": 200, "p50": 200, "p90": 200}
    with pytest.raises(ValidationError):  # o Método continua dizendo estimativa do motor
        F.DocumentoFichaCredito.model_validate(d)
    d["secoes"]["metodo"].update(texto=texto, fonte=fonte)
    assert F.DocumentoFichaCredito.model_validate(d).base.classe_evidencia == classe
    d["secoes"]["metodo"]["data_referencia"] = "2026-11-09"
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)


@pytest.mark.parametrize("classe", ["emitido", "entregue"])
def test_quantidade_emitida_entregue_nao_reutiliza_faixa_estimada(classe):
    d = documento()
    fonte, texto = F.ORIGEM_EVIDENCIA[classe]
    d["base"].update(inicio="2000-01-01", fim="2025-01-01", classe_evidencia=classe, fonte=fonte)
    d["secoes"]["metodo"].update(texto=texto, fonte=fonte)
    with pytest.raises(ValidationError):
        F.DocumentoFichaCredito.model_validate(d)


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
        lambda d: d.update(publicada_em="0001-01-01T00:00:00+14:00"),
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
