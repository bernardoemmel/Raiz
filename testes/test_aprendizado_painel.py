"""O site só recebe notas de grupos observados; nenhum identificador de imóvel."""

import datetime as dt
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.aprendizado import painel as P

AGORA = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)


def linhas(n=5, **alteracoes):
    registros = [
        {
            "modelo": "motor",
            "tipo": "ao_vivo",
            "modelo_versao": "v1",
            "alvo": "area_ha",
            "horizonte_dias": 365,
            "cod_imovel": f"IMOVEL-INTERNO-{i}",
            "data_corte": "2025-01-01",
            "horizonte_em": "2026-01-01",
            "observado_em": "2026-01-01",
            "previsao_criada_em": "2025-01-01T12:00:00Z",
            "gabarito_registrado_em": "2026-01-02T12:00:00Z",
            "gabarito_id": i + 1,
            "gabarito_fonte": "Fonte interna",
            "valor_num": 10,
            "real_num": 10 + i,
            "nome": "NAO PUBLICAR",
            **alteracoes,
        }
        for i in range(n)
    ]
    for r in registros:
        if "horizonte_em" not in alteracoes:
            r["horizonte_em"] = str(dt.date.fromisoformat(r["data_corte"]) + dt.timedelta(days=r["horizonte_dias"]))
        if "observado_em" not in alteracoes:
            r["observado_em"] = r["horizonte_em"]
    return registros


def test_notas_reais_fonte_data_e_allowlist():
    r = P.resumir(linhas(), AGORA)
    v = r["versoes"][0]
    assert v["metricas"] == {"ae": 2.0, "eq": 6.0}
    assert v["comparacoes"] == v["imoveis_observados"] == 5
    assert v["ultima_observacao"] == "2026-01-01"
    assert v["cronologia"] == "congelada_antes_da_observacao"
    assert r["gerado_em"] == AGORA.isoformat()
    publicado = json.dumps(r)
    for privado in ["cod_imovel", "IMOVEL-INTERNO", "NAO PUBLICAR", "Fonte interna", "real_num", "gabarito_id"]:
        assert privado not in publicado


def test_zero_medido_permanece_zero_e_ausencia_nao_gera_nota():
    assert P.resumir(linhas(real_num=10), AGORA)["versoes"][0]["metricas"]["ae"] == 0
    assert P.resumir(linhas(real_num=None), AGORA)["versoes"] == []
    assert P.resumir([], AGORA)["versoes"] == []


def test_minimo_exige_imoveis_distintos_nao_previsoes_repetidas():
    assert P.resumir(linhas(4), AGORA)["versoes"] == []
    assert P.resumir(linhas(8, cod_imovel="MESMO-IMOVEL"), AGORA)["versoes"] == []
    assert P.resumir(linhas() * 2, AGORA)["versoes"][0]["comparacoes"] == 10


@pytest.mark.parametrize(
    "mudanca",
    [
        {"horizonte_em": "2027-01-01"},
        {"observado_em": "2027-01-01"},
        {"observado_em": "2025-01-01"},
        {"gabarito_fonte": None},
        {"gabarito_id": None},
        {"modelo": "texto livre"},
        {"real_num": float("nan")},
        {"p10": 20, "p50": 10, "p90": 30},
    ],
)
def test_nao_divulga_resultado_prematuro_ou_sem_proveniencia(mudanca):
    assert P.resumir(linhas(**mudanca), AGORA)["versoes"] == []


def test_separa_versoes_horizontes_e_tipos():
    pares = linhas() + linhas(modelo_versao="v2") + linhas(horizonte_dias=30)
    assert len(P.resumir(pares, AGORA)["versoes"]) == 3
    # Cinco casos somados entre horizontes distintos não liberam um grupo pequeno.
    assert P.resumir(linhas(3) + linhas(2, horizonte_dias=30), AGORA)["versoes"] == []


def test_rota_publica_recebe_somente_projecao(monkeypatch):
    monkeypatch.setattr(P, "ler", lambda _: P.resumir(linhas(), AGORA))
    app = FastAPI()
    app.include_router(P.roteador(lambda _: None))
    resposta = TestClient(app).get("/acerto/resumo")
    assert resposta.status_code == 200
    assert resposta.json()["versoes"][0]["comparacoes"] == 5
    assert "IMOVEL-INTERNO" not in resposta.text


def test_reexecucao_retrospectiva_nunca_mistura_com_previsao_ao_vivo():
    r = P.resumir(linhas() + linhas(tipo="backtest"), AGORA)
    assert {v["avaliacao"] for v in r["versoes"]} == {"ao_vivo", "backtest"}
    assert all(v["comparacoes"] == 5 for v in r["versoes"])
    assert P.resumir(linhas(tipo=None), AGORA)["versoes"] == []


@pytest.mark.banco
def test_consulta_real_separa_backtest_e_preserva_minimo(banco_url):
    from sqlalchemy import create_engine

    from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote

    engine = create_engine(banco_url)
    try:
        with engine.begin() as con:
            for tipo in ("ao_vivo", "backtest"):
                registrar_lote(
                    con,
                    [Previsao(f"PA-1504950-PAINEL{i}", "area_ha", 365, valor_num=10) for i in range(5)],
                    Versoes("painel_acerto_teste", "v1", "fixture", dt.date(2025, 1, 1), tipo=tipo),
                )
            for i in range(5):
                registrar_gabarito(con, f"PA-1504950-PAINEL{i}", "area_ha", dt.date(2026, 1, 1), "campo", 10 + i)
        r = P.ler(engine)
        grupos = [v for v in r["versoes"] if v["modelo"] == "painel_acerto_teste"]
        # Inseridos hoje com corte antigo: não provam previsão ao vivo anterior ao resultado.
        assert len(grupos) == 1
        assert grupos[0]["avaliacao"] == "backtest"
        assert grupos[0]["cronologia"] == "backtest_declarado"
        assert all(v["metricas"] == {"ae": 2, "eq": 6} for v in grupos)
        assert all(v["comparacoes"] == v["imoveis_observados"] == 5 for v in grupos)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "mudanca",
    [
        {"valor_num": -0.1},
        {"valor_num": 1.1},
        {"real_num": 0.2},
        {"real_num": 2},
        {"real_num": None, "real_texto": "desconhecido"},
        {"real_num": None, "real_texto": "pendente"},
        {"real_num": None, "real_texto": ""},
        {"real_num": None, "real_texto": "sem_resposta"},
        {"real_num": 0, "real_texto": "desconhecido"},
        {"real_num": 1, "real_texto": "não"},
    ],
)
def test_chance_invalida_ou_resultado_desconhecido_nao_vira_acerto(mudanca):
    entradas = linhas(**{"alvo": "aceite_dono", "valor_num": 0, "real_num": 0, **mudanca})
    assert P.resumir(entradas, AGORA)["versoes"] == []
    # A validação da projeção não altera a previsão nem o gabarito congelados.
    assert all(all(r[k] == v for k, v in mudanca.items()) for r in entradas)


@pytest.mark.parametrize("real_texto,valor", [("aceitou", 1), ("recusou", 0), ("sim", 1), ("não", 0)])
def test_booleanos_explicitos_continuam_aceitos_sem_coercao_de_desconhecimento(real_texto, valor):
    entradas = linhas(alvo="aceite_dono", valor_num=valor, real_num=None, real_texto=real_texto)
    v = P.resumir(entradas, AGORA)["versoes"][0]
    assert v["metricas"] == {"brier": 0, "log_score": 0, "acerto": 1}
    assert all(r["real_num"] is None for r in entradas)


@pytest.mark.parametrize(
    "alvo,valor,real", [("area_ha", 10, 10), ("aceite_dono", 1, 1), ("restauracao_captura_tco2_ha_ano", 10, 10)]
)
@pytest.mark.parametrize("dia", ["2025-01-02", "2025-12-31", "2026-01-02"])
def test_medicao_de_outro_periodo_nao_comprova_horizonte_encerrado(alvo, valor, real, dia):
    assert P.resumir(linhas(alvo=alvo, valor_num=valor, real_num=real, observado_em=dia), AGORA)["versoes"] == []


@pytest.mark.parametrize(
    "mudanca",
    [
        {"previsao_criada_em": None},
        {"gabarito_registrado_em": None},
        {"previsao_criada_em": "2025-01-01T12:00:00"},
        {"previsao_criada_em": "2026-01-01T00:00:00Z"},
        {"previsao_criada_em": "2026-11-01T12:00:00Z"},
        {"previsao_criada_em": "2024-12-31T12:00:00Z"},
        {"gabarito_registrado_em": "2025-12-31T12:00:00Z"},
        {"gabarito_registrado_em": "2027-01-01T12:00:00Z"},
    ],
)
def test_ao_vivo_exige_cronologia_imutavel_e_nao_reclassifica_sem_prova(mudanca):
    assert P.resumir(linhas(**mudanca), AGORA)["versoes"] == []


def test_backtest_explicitamente_declarado_nao_e_confundido_com_ao_vivo():
    entradas = linhas(previsao_criada_em="2026-02-01T12:00:00Z")
    assert P.resumir(entradas, AGORA)["versoes"] == []
    resultado = P.resumir([{**r, "tipo": "backtest"} for r in entradas], AGORA)
    assert resultado["versoes"][0]["cronologia"] == "backtest_declarado"
    assert resultado["versoes"][0]["avaliacao"] == "backtest"


def test_excluir_invalidos_nao_libera_grupo_com_menos_de_cinco_imoveis():
    entradas = linhas()
    entradas[-1]["observado_em"] = "2025-01-02"
    assert P.resumir(entradas, AGORA)["versoes"] == []
    assert P.resumir(linhas(horizonte_em="2026-01-02", observado_em="2026-01-02"), AGORA)["versoes"] == []


@pytest.mark.parametrize("campo", ["modelo", "modelo_versao", "alvo"])
def test_rotulos_tecnicos_nao_publicam_documentos_civis(campo):
    from testes.test_privacidade import CNPJ, CPF

    for documento in (CPF, CNPJ, "".join(c for c in CPF if c.isdigit()), "".join(c for c in CNPJ if c.isalnum())):
        assert P.resumir(linhas(**{campo: "modelo-" + documento}), AGORA)["versoes"] == []


def test_versao_oficial_do_leitor_preserva_prompt_sem_afrouxar_evidencia():
    from raiz.documentos.certidao.esquema import versao_prompt

    versao = f"claude-haiku-4-5-20251001|{versao_prompt()}"
    entradas = linhas(
        modelo="leitor_certidao",
        modelo_versao=versao,
        alvo="titulo_matricula_situacao",
        horizonte_dias=30,
        valor_num=None,
        real_num=None,
        valor_texto="conferida",
        real_texto="conferida",
    )
    grupo = P.resumir(entradas, AGORA)["versoes"][0]
    assert grupo["versao"] == versao
    assert grupo["metricas"] == {"acerto": 1, "brier": 0}
    assert grupo["imoveis_observados"] == 5
    assert "IMOVEL-INTERNO" not in json.dumps(grupo)
    assert P.resumir(entradas[:4], AGORA)["versoes"] == []
    assert P.resumir([{**r, "observado_em": "2025-01-02"} for r in entradas], AGORA)["versoes"] == []
    assert P.resumir([{**r, "previsao_criada_em": "2025-01-31T12:00:00Z"} for r in entradas], AGORA)["versoes"] == []
    assert P.resumir([{**r, "modelo": "motor"} for r in entradas], AGORA)["versoes"] == []


@pytest.mark.parametrize(
    "versao",
    [
        "modelo|",
        "|prompt",
        "modelo||prompt",
        "modelo|prompt|outro",
        "modelo|texto livre",
        "modelo|prompt\n",
        "modelo|<script>",
        "modelo|" + "p" * 114,
    ],
)
def test_versao_composta_recusa_texto_livre_partes_vazias_e_excesso_de_tamanho(versao):
    assert P.resumir(linhas(modelo="leitor_certidao", modelo_versao=versao), AGORA)["versoes"] == []
