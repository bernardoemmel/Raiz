"""Ponta a ponta sem rede: rodada diária com fontes falsas, depois as rotas /vigilancia/imovel e /vigilancia/projeto,
a marcação, os eventos do fundador, o rascunho do relatório, o KML, os avisos, o acerto e a saúde."""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from raiz.vigilancia import api, rodada
from raiz.vigilancia.fontes import Leitura, vazio
from raiz.vigilancia.fontes.mapbiomas_alerta import SemCredencial
from raiz.vigilancia.servico import Vigilancia
from raiz.vigilancia.testes.conftest import COD_A, COD_B, HOJE, ocorrencia, ocorrencias, quadrado_m


def _fontes_falsas(monkeypatch, falhar: str | None = None):
    def ler(nome, ctx, estado, arm, refazer):
        if nome == falhar:
            raise RuntimeError("servidor fora do ar em https://exemplo/x?chave=1")
        if nome == "mapbiomas_alerta":
            raise SemCredencial("defina MAPBIOMAS_ALERTA_EMAIL e MAPBIOMAS_ALERTA_SENHA")
        if nome == "deter":
            oc = ocorrencias(
                ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 150), dt.date(2026, 11, 3), HOJE),
                ocorrencia("deter", "d2", "desmatamento_cr", quadrado_m(1090, -10, 100), dt.date(2026, 11, 3), HOJE),
            )
            return Leitura("deter", oc, cursor={"desde": "2026-08-14"}, nota="falso")
        if nome == "firms":
            oc = ocorrencias(
                ocorrencia(
                    "firms",
                    "N20|2026-11-11|0415|0|0",
                    "foco_alta",
                    quadrado_m(400, 400, 375),
                    dt.date(2026, 11, 11),
                    dt.date(2026, 11, 11),
                )
            )
            return Leitura("firms", oc, nota="falso")
        return Leitura(nome, vazio(), nota="falso")

    monkeypatch.setattr(rodada, "_ler", ler)


@pytest.fixture
def rodado(monkeypatch, cfg, poligonos, lista_projetos):
    _fontes_falsas(monkeypatch)
    res = rodada.rodar(cfg=cfg, hoje=HOJE, poligonos=poligonos, lista_projetos=lista_projetos)
    return res


@pytest.fixture
def cliente(rodado, cfg, poligonos, lista_projetos, regras):
    v = Vigilancia(cfg, None, regras, lista_projetos, poligonos)
    app = FastAPI()
    app.include_router(api.roteador(lambda: v))
    return TestClient(app)


def test_rodada_guarda_alertas_perdas_e_relatorios(rodado, cfg):
    f = rodado["fontes"]
    assert f["deter"]["situacao"] == "ok" and f["deter"]["alertas_novos_imovel"] == 2  # d1 no A; d2 só no B (pequeno)
    assert f["mapbiomas_alerta"]["situacao"] == "sem_credencial"
    assert f["deter"]["alertas_novos_projeto"] == 1 and f["firms"]["alertas_novos_projeto"] == 1
    assert rodado["projetos"]["PTESTE"]["perdas_abertas"] == 1
    rel = cfg.estado / "privado" / "relatorios"
    assert {p.name for p in rel.iterdir()} == {
        "PTESTE_LE1_pt.md",
        "PTESTE_LE1_en.md",
        "PTESTE_LE1.kml",
        "PTESTE_LE1_aviso_verra.eml",
    }
    md = rodada.resumo_markdown(rodado)
    assert "PTESTE" not in md and "deter" in md  # o resumo público não fala de projeto


def test_rodada_com_fonte_fora_do_ar_segue_e_esconde_segredo(monkeypatch, cfg, poligonos, lista_projetos):
    _fontes_falsas(monkeypatch, falhar="firms")
    monkeypatch.setenv("FIRMS_MAP_KEY", "chave123456")
    res = rodada.rodar(cfg=cfg, hoje=HOJE, poligonos=poligonos, lista_projetos=lista_projetos)
    assert res["fontes"]["firms"]["situacao"] == "erro" and "?chave" not in res["fontes"]["firms"]["erro"]
    assert res["fontes"]["deter"]["situacao"] == "ok"


def test_rota_do_imovel(cliente):
    r = cliente.get(f"/vigilancia/imovel/{COD_A}")
    assert r.status_code == 200
    d = r.json()
    assert d["situacao"] == "alerta" and d["municipio"] == "São Félix do Xingu"
    assert d["resumo"]["alertas"] == 2 and d["resumo"]["por_fonte"] == {"deter": 1, "firms": 1}
    assert {a["fonte"] for a in d["alertas"]} == {"deter", "firms"}
    assert all(a["regra_versao"] and a["confianca"] for a in d["alertas"])
    assert "geometria" not in d["alertas"][0]
    # o pequeno (0,5 ha) também é vigiado
    b = cliente.get(f"/vigilancia/imovel/{COD_B}").json()
    assert b["resumo"]["alertas"] == 1 and b["alertas"][0]["fracao_alvo"] > 0
    # com pontos do recibo e em minúsculas
    assert cliente.get("/vigilancia/imovel/" + COD_A.lower()).status_code == 200
    geo = cliente.get(f"/vigilancia/imovel/{COD_A}?geo=true&fonte=deter").json()
    assert len(geo["alertas"]) == 1 and geo["geojson"]["features"][0]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert cliente.get("/vigilancia/imovel/PA-1507300-NAOEXISTE").status_code == 404


def test_rota_do_projeto_relatorio_kml_e_eventos(cliente):
    d = cliente.get("/vigilancia/projeto/PTESTE").json()
    assert d["situacao"] == "perda_suspeita" and d["cliente"] == "C-0001"
    assert d["regra"]["aviso_verra_dias"] == 30 and d["regra"]["relatorio_anos"] == 2
    p = d["perdas"][0]
    # o foco de calor de 11/11 (a 150 m do DETER) entra no mesmo evento: a descoberta é 11/11
    assert p["perda_id"] == "PTESTE_LE1" and p["descoberta_em"] == "2026-11-11"
    assert set(p["fontes"]) == {"deter", "firms"} and p["prazo"]["aviso_verra_ate"] == "2026-12-11"
    assert p["prazo"]["relatorio_ate"] == "2028-11-11" and p["magnitude"]["pct"] is not None
    assert p["avisos"][0]["estado"] == "aguardando_aprovacao"
    assert {a["papel"] for a in d["alertas"]} == {"projeto"} and len(d["alertas"]) == 2
    en = cliente.get("/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1/relatorio?idioma=en")
    assert en.status_code == 200 and "Loss Event Report: 9999, 9999_LE1" in en.text
    assert "text/markdown" in en.headers["content-type"]
    k = cliente.get("/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1/kml")
    assert k.status_code == 200 and "<Placemark>" in k.text
    assert cliente.get("/vigilancia/projeto/PTESTE/perdas/PTESTE_LE9/relatorio").status_code == 404
    assert cliente.get("/vigilancia/projeto/NAO").status_code == 404
    # fundador avisou a Verra
    e = cliente.post(
        "/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1/eventos",
        json={"tipo": "verra_avisada", "quem": "fundador", "data": "2026-11-12"},
    )
    assert e.status_code == 201 and e.json()["publicada"] is False
    p = cliente.get("/vigilancia/projeto/PTESTE").json()["perdas"][0]
    assert p["prazo"]["aviso_verra_situacao"] == "cumprido" and p["prazo"]["aviso_verra_feito_em"] == "2026-11-12"
    ruim = cliente.post("/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1/eventos", json={"tipo": "inventado", "quem": "x"})
    assert ruim.status_code == 422
    sem_nota = cliente.post(
        "/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1/eventos",
        json={"tipo": "descoberta_informada", "quem": "fundador", "data": "2026-11-12"},
    )
    assert sem_nota.status_code == 422
    outro = cliente.post("/vigilancia/projeto/OUTRO/perdas/PTESTE_LE1/eventos", json={"tipo": "nota", "quem": "x"})
    assert outro.status_code == 404


def test_marcacao_confirma_perda_e_aprende(cliente):
    proj = cliente.get("/vigilancia/projeto/PTESTE").json()
    aid = proj["perdas"][0]["alertas"][0]["alerta_id"]
    r = cliente.post(
        f"/vigilancia/alertas/{aid}/marcacao",
        json={"verdadeiro": True, "fonte": "campo", "quem": "Fundador", "evidencia": "visita"},
    )
    assert r.status_code == 201 and r.json()["quem"] == "fundador"
    p = cliente.get("/vigilancia/projeto/PTESTE").json()["perdas"][0]
    assert p["estado"] == "confirmada" and p["confianca"] == 1.0
    assert "perda_confirmada" in [a["marco"] for a in p["avisos"]]
    acerto = cliente.get("/vigilancia/acerto").json()
    assert acerto and acerto[0]["marcados"] == 1 and acerto[0]["por_fonte_marcacao"] == {"campo": 1}
    assert (
        cliente.post(
            f"/vigilancia/alertas/{aid}/marcacao", json={"verdadeiro": True, "fonte": "achismo", "quem": "x"}
        ).status_code
        == 422
    )
    assert (
        cliente.post(
            "/vigilancia/alertas/naoexiste/marcacao", json={"verdadeiro": True, "fonte": "campo", "quem": "x"}
        ).status_code
        == 404
    )


def test_avisos_e_saude(cliente):
    avs = cliente.get("/vigilancia/avisos?estado=aguardando_aprovacao").json()
    assert avs and avs[0]["texto"].startswith("Fonte:")
    aid = avs[0]["aviso_id"]
    assert (
        cliente.post(
            f"/vigilancia/avisos/{aid}/eventos", json={"tipo": "aviso_aprovado", "quem": "fundador"}
        ).status_code
        == 201
    )
    estados = {a["aviso_id"]: a["estado"] for a in cliente.get("/vigilancia/avisos").json()}
    assert estados[aid] == "aprovado"
    s = cliente.get("/vigilancia/saude").json()
    assert s["fontes"]["deter"]["situacao"] == "ok" and s["fontes"]["mapbiomas_alerta"]["situacao"] == "sem_credencial"
    assert s["entradas_pendentes"] >= 1


def test_servidor_avulso_pede_token(rodado, cfg, poligonos, lista_projetos, regras, monkeypatch):
    from raiz.vigilancia.servidor import criar_app

    v = Vigilancia(cfg, None, regras, lista_projetos, poligonos)
    monkeypatch.delenv("RAIZ_API_TOKEN", raising=False)
    with TestClient(criar_app(v, baixar=False)) as c:
        assert c.get("/vigilancia/saude").status_code == 503
    monkeypatch.setenv("RAIZ_API_TOKEN", "segredo")
    with TestClient(criar_app(v, baixar=False)) as c:
        assert c.get("/vigilancia/saude").status_code == 401
        ok = c.get(f"/vigilancia/imovel/{COD_A}", headers={"Authorization": "Bearer segredo"})
        assert ok.status_code == 200 and ok.json()["cod_imovel"] == COD_A


def test_api_prepara_sem_quitar_prazo(cliente):
    base = "/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1"
    antes = cliente.get("/vigilancia/projeto/PTESTE").json()["perdas"][0]
    resposta = cliente.get(base + "/aviso-verra")
    assert resposta.status_code == 200
    d = resposta.json()
    assert d["prazo"] == antes["prazo"]["aviso_verra_ate"]
    assert d["origem_prazo"] == "estado_do_evento" and d["enviado"] is False
    assert "9999" in d["corpo"] and "Preliminary affected area" in d["corpo"]
    eml = cliente.get(base + "/aviso-verra.eml")
    assert eml.status_code == 200 and "message/rfc822" in eml.headers["content-type"]
    depois = cliente.get("/vigilancia/projeto/PTESTE").json()["perdas"][0]
    assert depois["prazo"] == antes["prazo"]
    assert cliente.get("/vigilancia/projeto/OUTRO/perdas/PTESTE_LE1/aviso-verra").status_code == 404
    assert cliente.get("/vigilancia/projeto/PTESTE/perdas/PTESTE_LE99/aviso-verra").status_code == 404


def test_aviso_ja_enviado_exige_conferencia(cliente):
    base = "/vigilancia/projeto/PTESTE/perdas/PTESTE_LE1"
    cliente.post(base + "/eventos", json={"tipo": "verra_avisada", "quem": "fundador", "data": "2026-11-12"})
    d = cliente.get(base + "/aviso-verra").json()
    assert any("aviso já registrado" in p for p in d["pendencias"])
