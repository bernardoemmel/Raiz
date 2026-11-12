"""Assinatura SIGEF por bbox e aceitação do espelho, sem rede ou banco externo."""

import json
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import box, mapping

from raiz.coleta import car, rodada, sigef, wfs
from raiz.coleta.espelho import Espelho
from raiz.coleta.fila import Plano
from testes.servidor_falso import sessao_falsa

COD = 1504950
RECORTE = f"PA/{COD}"


class MundoSIGEF:
    def __init__(self, n=2):
        self.n = n
        self.data = "2026-11-01"
        self.baixados = 0
        self.falhar = False
        self.faltando = 0
        self.area = 10.0
        self.repetir_chave = False

    def responder(self, metodo, base, p, h):
        if self.falhar:
            return 503, {}, "fora do ar"
        if p.get("resultType") == "hits":
            assert p["bbox"].endswith("urn:ogc:def:crs:EPSG::4674")
            return 200, {}, f'<wfs:FeatureCollection numberMatched="{self.n}"/>'
        if p.get("count") == "1":
            assert p["sortBy"] == "data_aprovacao DESC"
            assert p["propertyName"] == "data_aprovacao"
            assert "bbox" not in p and "CQL_FILTER" not in p
            filtro = ET.fromstring(p["filter"])
            assert filtro.find(".//{http://www.opengis.net/fes/2.0}BBOX") is not None
            assert (
                filtro.find(".//{http://www.opengis.net/fes/2.0}PropertyIsNull/{*}ValueReference").text
                == "data_aprovacao"
            )
            return 200, {}, json.dumps({"features": [{"properties": {"data_aprovacao": self.data}}]})
        assert p["bbox"].endswith("urn:ogc:def:crs:EPSG::4674")
        self.baixados += 1
        n = self.n - self.faltando
        feats = [
            {
                "type": "Feature",
                "geometry": mapping(box(-47 + i / 100, -2, -46.99 + i / 100, -1.99)),
                "properties": {"parcela_codigo": f"P{i}", "data_aprovacao": self.data, "area_ha": self.area},
            }
            for i in range(n)
        ]
        if self.repetir_chave and len(feats) > 1:
            feats[-1]["properties"]["parcela_codigo"] = feats[0]["properties"]["parcela_codigo"]
        return 200, {}, json.dumps({"type": "FeatureCollection", "features": feats, "numberMatched": n})


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    esp = Espelho(tmp_path)
    g = gpd.GeoDataFrame({"cod_imovel": ["A"]}, geometry=[box(-48, -3, -46, -1)], crs=4674)
    esp.gravar("car", "PA", COD, g, "cod_imovel")
    estados, escritos, eventos, alertas = {}, [], [], []

    def estado(con, fonte, recorte):
        return estados.get((fonte, recorte))

    def atualizar(con, fonte, recorte, **campos):
        chave = fonte, recorte
        e = estados.setdefault(
            chave, SimpleNamespace(assinatura=None, tentativas=0, sujo=True, liberado=False, cursor=None)
        )
        e.__dict__.update(campos)
        escritos.append(campos)

    monkeypatch.setattr(sigef, "estado", estado)
    monkeypatch.setattr(sigef, "atualizar", atualizar)
    monkeypatch.setattr(sigef, "evento", lambda *a, **kw: eventos.append((a, kw)))
    monkeypatch.setattr(sigef, "registrar_alertas", lambda con, fonte, recorte, dif: alertas.extend(dif.alertas))
    mundo = MundoSIGEF()
    s, servidor = sessao_falsa(mundo.responder)
    return SimpleNamespace(
        esp=esp, estados=estados, escritos=escritos, eventos=eventos, alertas=alertas, mundo=mundo, s=s, srv=servidor
    )


def test_assinatura_e_download_usam_mesmo_bbox_e_poucos_campos(ambiente):
    a = ambiente
    assert sigef.verificar_municipio(a.s, None, a.esp, "PA", COD)
    assert all("assinatura" not in e for e in a.escritos)  # verificar não aceita dados ainda não baixados
    r = sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    assert r.acao == "completo" and r.contagem == 2
    e = a.estados[(sigef.FONTE, RECORTE)]
    assert json.loads(e.assinatura) == {
        "bbox": "-3.0,-48.0,-1.0,-46.0,urn:ogc:def:crs:EPSG::4674",
        "contagem": 2,
        "mais_novo": "2026-11-01",
    }
    bboxs = set()
    for _, _, p, _ in a.srv.pedidos:
        if "bbox" in p:
            bboxs.add(p["bbox"])
        else:
            filtro = ET.fromstring(p["filter"])
            env = filtro.find(".//{http://www.opengis.net/gml/3.2}Envelope")
            limites = env.find("{*}lowerCorner").text.split() + env.find("{*}upperCorner").text.split()
            bboxs.add(",".join(limites + [env.attrib["srsName"]]))
    assert bboxs == {"-3.0,-48.0,-1.0,-46.0,urn:ogc:def:crs:EPSG::4674"}
    assert e.cursor == "2026-11-01" and not e.sujo
    assert not sigef.verificar_municipio(a.s, None, a.esp, "PA", COD)
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD).acao == "sem_mudanca"
    assert a.mundo.baixados == 1


def test_bbox_novo_invalida_assinatura_mesmo_com_mesma_contagem_e_data(ambiente):
    a = ambiente
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    antiga = a.estados[(sigef.FONTE, RECORTE)].assinatura
    g = a.esp.ler("car", "PA", COD)
    g.geometry = [box(-49, -4, -46, -1)]
    a.esp.gravar("car", "PA", COD, g, "cod_imovel")
    assert sigef.verificar_municipio(a.s, None, a.esp, "PA", COD)
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD).acao == "completo"
    assert a.estados[(sigef.FONTE, RECORTE)].assinatura != antiga
    assert a.mundo.baixados == 2


def test_falha_ou_leitura_incompleta_preserva_ultima_assinatura_aceita(ambiente):
    a = ambiente
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    e = a.estados[(sigef.FONTE, RECORTE)]
    antiga = e.assinatura
    a.mundo.falhar = True
    assert sigef.verificar_municipio(a.s, None, a.esp, "PA", COD)
    assert e.sujo and e.assinatura == antiga
    a.mundo.falhar = False
    a.mundo.n, a.mundo.faltando = 3, 1
    r = sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    assert r.acao == "falha" and "2 de 3" in r.erro
    assert e.sujo and e.assinatura == antiga and e.tentativas == 2
    assert len(a.esp.ler("sigef", "PA", COD)) == 2
    a.mundo.faltando = 0
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD).acao == "completo"
    assert e.assinatura != antiga and not e.sujo and e.tentativas == 0


@pytest.mark.parametrize("metodo", [sigef.verificar_municipio, sigef.atualizar_municipio])
def test_diagnostico_nao_persiste_nome_contato_ou_segredo(ambiente, monkeypatch, metodo):
    a = ambiente
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    e = a.estados[(sigef.FONTE, RECORTE)]
    antiga = e.assinatura

    def falhar(*args):
        raise ValueError("nome=Pessoa Sintetica Teste; contato=canario@example.invalid; token=segredo-sintetico")

    monkeypatch.setattr(sigef, "assinatura", falhar)
    resultado = metodo(a.s, None, a.esp, "PA", COD)
    diagnosticos = json.dumps([a.escritos, a.eventos, getattr(resultado, "erro", None)], default=str)
    for sensivel in ("Pessoa Sintetica Teste", "canario@example.invalid", "segredo-sintetico"):
        assert sensivel not in diagnosticos
    assert e.sujo and e.assinatura == antiga and e.tentativas == 1
    assert e.ultimo_erro and "ValueError" in e.ultimo_erro


def test_trava_nao_confirma_assinatura_e_liberacao_aceita_snapshot_vazio(ambiente):
    a = ambiente
    a.mundo.n = 40
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    e = a.estados[(sigef.FONTE, RECORTE)]
    antiga = e.assinatura
    a.mundo.n = 0
    r = sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    assert r.acao == "travado" and e.sujo and e.assinatura == antiga
    assert len(a.esp.ler("sigef", "PA", COD)) == 40
    assert a.alertas[0]["tipo"] == "queda_contagem"
    e.liberado = True
    r = sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    assert r.acao == "completo" and r.contagem == 0
    assert e.assinatura != antiga and not e.liberado and not e.sujo
    vazio = a.esp.ler("sigef", "PA", COD)
    assert vazio.empty and "parcela_codigo" in vazio


def test_mesma_contagem_com_parcela_repetida_nao_aceita_snapshot(ambiente):
    a = ambiente
    a.mundo.repetir_chave = True
    r = sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    assert r.acao == "falha" and "repetida" in r.erro
    assert a.estados[(sigef.FONTE, RECORTE)].assinatura is None
    assert not a.esp.caminho("sigef", "PA", COD).exists()


def test_reconciliacao_ignora_assinatura_e_sem_car_nao_consulta_nacao(ambiente):
    a = ambiente
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD, forcar=True).acao == "completo"
    assert a.mundo.baixados == 2
    antes = len(a.srv.pedidos)
    assert not sigef.verificar_municipio(a.s, None, a.esp, "PA", 999)
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", 999).acao == "sem_recorte"
    assert len(a.srv.pedidos) == antes


def test_mudanca_silenciosa_travada_nao_e_esquecida_quando_assinatura_igual(ambiente):
    a = ambiente
    a.mundo.n = 40
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    e = a.estados[(sigef.FONTE, RECORTE)]
    antiga = e.assinatura
    a.mundo.area = 20.0  # mesma contagem e data; só a reconciliação detecta
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD, forcar=True).acao == "travado"
    assert e.assinatura == antiga and e.sujo
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD).acao == "travado"
    assert e.sujo
    e.liberado = True
    assert sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD).acao == "completo"
    assert not e.sujo and not e.liberado
    assert a.esp.ler("sigef", "PA", COD).area_ha.eq(20.0).all()


def test_sigef_mudou_sozinho_entra_na_fila_e_no_recalculo(ambiente, monkeypatch):
    a = ambiente
    sigef.atualizar_municipio(a.s, None, a.esp, "PA", COD)
    a.mundo.n = 3
    monkeypatch.setattr(car, "verificar_municipio", lambda *a: False)

    def planejar(con, fonte, recortes, **kwargs):
        sujos = [] if fonte == car.FONTE else [r for r in recortes if a.estados[(fonte, r)].sujo]
        return Plano("incremental", sujos, len(sujos), len(recortes), [])

    @contextmanager
    def begin():
        yield None

    @contextmanager
    def lote(*args, **kwargs):
        yield SimpleNamespace(detalhe={})

    monkeypatch.setattr(rodada, "planejar", planejar)
    monkeypatch.setattr(rodada, "lote", lote)
    eng = SimpleNamespace(begin=begin)
    r = rodada.rodada_car(eng, a.s, a.esp, {"PA": [COD]}, historico=False)
    assert r["baixados"] == 0 and r["sigef_baixados"] == 1 and r["mudaram"] == [COD]
    assert r["sigef_verificados"] == 1 and r["falhas"] == 0
    assert len(a.esp.ler("sigef", "PA", COD)) == 3


def test_bbox_em_tupla_tambem_tem_representacao_igual_na_assinatura_e_paginas():
    pedidos = []

    def responder(metodo, base, p, h):
        pedidos.append(p)
        if p.get("resultType") == "hits":
            return 200, {}, '<wfs:FeatureCollection numberMatched="0"/>'
        return 200, {}, '{"type":"FeatureCollection","features":[],"numberMatched":0}'

    s, _ = sessao_falsa(responder)
    camada = wfs.Camada("https://geo.exemplo/wfs", "exemplo")
    bbox = (-48, -3, -46, -1)
    assert wfs.assinatura(s, camada, "data_aprovacao", bbox=bbox) == "0|"
    assert wfs.ler(s, camada, "id", bbox=bbox).empty
    assert [p["bbox"] for p in pedidos] == ["-48,-3,-46,-1,EPSG:4674"] * 2
