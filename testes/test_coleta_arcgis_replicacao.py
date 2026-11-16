"""ArcGIS público: recorte, privacidade, snapshot atômico e cursor só depois da leitura aceita."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely.geometry import Point
from typer.testing import CliRunner

from raiz.coleta import arcgis
from raiz.coleta.espelho import Espelho
from raiz.coleta.manifesto import Fonte, carregar
from raiz.coleta.wfs import LeituraIncompleta
from testes.servidor_falso import sessao_falsa
from testes.test_privacidade import CPF, fmt_cpf

URL = "https://servicos.exemplo/arcgis/FeatureServer/0"
CAIXA = (-48, -3, -47, -2)
COD = 1504950


def fonte():
    return Fonte(id="arcgis_teste", nome="Teste", orgao="SFB", tipo="arcgis", url=URL, recorte="municipio",
                 densidade="esparsa", sinal={"tipo": "last_edit"}, calendario="diario", licenca="a conferir",
                 pode_treinar=False, campos_publicos=["fid", "codigo", "uf"], chave="fid")  # fmt: skip


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    import raiz.coleta.espelho as modulo_espelho

    registros, eventos = {}, []
    defaults = dict(cursor=None, assinatura=None, hash_conteudo=None, contagem=0, tentativas=0, liberado=False)

    def estado(con, f, recorte):
        r = registros.get((f, recorte))
        return SimpleNamespace(**{**defaults, **r}) if r is not None else None

    def atualizar(con, f, recorte, **kw):
        registros.setdefault((f, recorte), {}).update(kw)

    monkeypatch.setattr(arcgis, "estado", estado)
    monkeypatch.setattr(arcgis, "atualizar", atualizar)
    monkeypatch.setattr(arcgis, "evento", lambda *args, **kwargs: eventos.append((args, kwargs)))
    monkeypatch.setattr(modulo_espelho, "registrar_alertas", lambda *args, **kwargs: None)
    mundo = {"edicao": 10, "n": 3, "metadados": 0, "mudar_durante": False, "repetir": False}

    def responder(metodo, url, p, cab):
        if url == URL:
            mundo["metadados"] += 1
            ed = mundo["edicao"]
            if mundo["mudar_durante"] and mundo["metadados"] % 2 == 0:
                ed += 1
            mudou_schema = mundo.get("mudar_schema") and mundo["metadados"] % 2 == 0
            campos = ("fid", "codigo") if mudou_schema else ("fid", "codigo", "uf")
            return (
                200,
                {},
                json.dumps(
                    {
                        "objectIdField": "fid",
                        "maxRecordCount": 2,
                        "editingInfo": {"lastEditDate": ed},
                        "fields": [{"name": c} for c in campos],
                    }
                ),
            )
        assert p["geometry"] == "-48.0,-3.0,-47.0,-2.0" or p["geometry"] == "-49.0,-3.0,-47.0,-2.0"
        assert p["geometryType"] == "esriGeometryEnvelope" and p["inSR"] == "4674"
        if p.get("returnCountOnly") == "true":
            return 200, {}, json.dumps({"count": mundo["n"]})
        assert p["outFields"] == "fid,codigo,uf"
        ultimo = int(p["where"].split(">")[-1])
        if mundo["repetir"]:
            ultimo = -1
        ids = [i for i in range(1, mundo["n"] + 1) if i > ultimo][:2]
        # O servidor ignora parcialmente outFields: o cliente ainda precisa remover os campos extras.
        feats = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-47.5, -2.5]},
                "properties": {
                    "fid": i,
                    "codigo": f"G{i}",
                    "uf": "PA",
                    "nome_embargado": "Pessoa",
                    "cpf_cnpj_embargado": fmt_cpf(CPF),
                    "des_infracao": "texto pessoal",
                },
            }
            for i in ids
        ]
        return 200, {}, json.dumps({"type": "FeatureCollection", "features": feats})

    s, srv = sessao_falsa(responder)
    return Espelho(tmp_path), s, srv, mundo, registros, eventos


def coletar(ambiente, caixa=CAIXA, forcar=False):
    esp, s, *_ = ambiente
    return arcgis.coletar_municipio(s, None, esp, fonte(), "PA", COD, caixa, forcar=forcar)


def test_snapshot_sem_pessoais_e_edicao_estavel_pula_so_com_mesmo_recorte(ambiente):
    esp, _, srv, mundo, registros, _ = ambiente
    r = coletar(ambiente)
    assert r.acao == "atualizado" and r.linhas == 3
    p = esp.caminho("arcgis_teste", "PA", COD)
    g = gpd.read_parquet(p)
    assert set(g.columns) == {"fid", "codigo", "uf", "geometry"}
    assert CPF.encode() not in p.read_bytes() and b"Pessoa" not in p.read_bytes()
    e = registros[("arcgis_teste", f"PA/{COD}")]
    assert e["cursor"] == "10" and e["hash_conteudo"]
    n = len(srv.pedidos)
    assert coletar(ambiente).acao == "sem_mudanca" and len(srv.pedidos) == n + 1
    assert coletar(ambiente, (-49, -3, -47, -2)).acao == "atualizado"
    mundo["edicao"] = None
    n = len(srv.pedidos)
    assert coletar(ambiente).acao == "atualizado"
    assert coletar(ambiente).acao == "atualizado" and len(srv.pedidos) > n + 2


def test_edicao_muda_durante_leitura_nao_troca_snapshot_nem_cursor(ambiente):
    esp, _, _, mundo, registros, _ = ambiente
    coletar(ambiente)
    p = esp.caminho("arcgis_teste", "PA", COD)
    antes = p.read_bytes()
    mundo.update(edicao=20, mudar_durante=True, metadados=0)
    r = coletar(ambiente)
    assert r.acao == "falha" and "mudou durante" in r.erro
    e = registros[("arcgis_teste", f"PA/{COD}")]
    assert e["cursor"] == "10" and e["sujo"] and p.read_bytes() == antes


def test_esquema_muda_sem_last_edit_nao_aceita_snapshot(ambiente):
    esp, _, _, mundo, registros, _ = ambiente
    mundo.update(edicao=None, mudar_schema=True)
    r = coletar(ambiente)
    assert r.acao == "falha" and "metadados" in r.erro
    assert not list(esp.raiz.rglob("*.parquet"))
    assert "cursor" not in registros[("arcgis_teste", f"PA/{COD}")]


def test_pagina_sem_progresso_para_e_nao_persiste(ambiente):
    esp, s, srv, mundo, *_ = ambiente
    mundo["repetir"] = True
    with pytest.raises(LeituraIncompleta, match="OBJECTID"):
        arcgis.ler(s, URL, bbox=CAIXA, campos=fonte().campos_publicos)
    assert len(srv.pedidos) == 4
    assert not list(esp.raiz.rglob("*.parquet"))


def test_falha_ao_gravar_e_trava_preservam_versao_aceita(ambiente, monkeypatch):
    esp, _, _, mundo, registros, _ = ambiente
    coletar(ambiente)
    p = esp.caminho("arcgis_teste", "PA", COD)
    antes = p.read_bytes()
    original = esp._escrever

    def falhar(*args):
        raise OSError("disco indisponível")

    monkeypatch.setattr(esp, "_escrever", falhar)
    mundo.update(edicao=20, n=4)
    assert coletar(ambiente).acao == "falha"
    assert registros[("arcgis_teste", f"PA/{COD}")]["cursor"] == "10" and p.read_bytes() == antes
    monkeypatch.setattr(esp, "_escrever", original)
    assert coletar(ambiente).acao == "atualizado"
    # A queda grande mantém o retrato aceito até liberação explícita.
    muitos = gpd.GeoDataFrame(
        {"fid": range(1, 41), "codigo": [f"G{i}" for i in range(1, 41)], "uf": "PA"},
        geometry=[Point(-47.5, -2.5)] * 40,
        crs=4674,
    )
    esp.gravar("arcgis_teste", "PA", COD, muitos, "fid", liberar=True)
    mundo.update(edicao=30, n=2)
    assert coletar(ambiente).acao == "travado"
    assert registros[("arcgis_teste", f"PA/{COD}")]["cursor"] == "20"
    assert len(gpd.read_parquet(p)) == 40


def test_camada_vazia_tem_chave_e_eh_snapshot_valido(ambiente):
    esp, _, _, mundo, registros, _ = ambiente
    mundo["n"] = 0
    r = coletar(ambiente)
    assert r.acao == "atualizado" and r.linhas == 0
    assert "fid" in gpd.read_parquet(esp.caminho("arcgis_teste", "PA", COD))
    assert registros[("arcgis_teste", f"PA/{COD}")]["cursor"] == "10"


def test_erro_externo_nao_registra_valores_pessoais(ambiente, monkeypatch):
    def falhar(*args, **kwargs):
        raise ValueError(f"Pessoa Identificável {fmt_cpf(CPF)}")

    monkeypatch.setattr(arcgis, "ler", falhar)
    r = coletar(ambiente)
    assert r.acao == "falha" and r.erro.startswith("ValueError:")
    assert "Pessoa" not in r.erro and CPF not in r.erro
    assert "Pessoa" not in str(ambiente[-2:]) and CPF not in str(ambiente[-2:])


@pytest.mark.parametrize("edicao", [True, -1, "2026-11-12", {"nome": "Pessoa"}])
def test_last_edit_invalido_falha_sem_gravar(ambiente, edicao):
    esp, _, _, mundo, registros, _ = ambiente
    mundo["edicao"] = edicao
    r = coletar(ambiente)
    assert r.acao == "falha" and "lastEditDate inválido" in r.erro
    assert not list(esp.raiz.rglob("*.parquet"))
    assert "cursor" not in registros[("arcgis_teste", f"PA/{COD}")]


def test_manifesto_separa_snapshot_ibama_e_falta_de_edicao():
    m = carregar()
    cnfp = m.fonte("sfb_cnfp_arcgis")
    direto = m.fonte("ibama_embargos_arcgis")
    snapshot = m.fonte("ibama_embargos_sfb_arcgis")
    assert cnfp.sinal["campo"] == "editingInfo.lastEditDate" and not cnfp.pode_treinar
    assert direto.sinal["disponivel"] is False and direto.sinal["sem_campo"] == "releitura_completa"
    assert snapshot.snapshot and snapshot.nao_substitui == "ibama_embargos"
    assert not any(arcgis.colunas_pessoais(f.campos_publicos) for f in (cnfp, direto, snapshot))
    prodes = m.fonte("prodes")
    assert prodes.sinal["tipo"] == "catalogo_downloads" and prodes.sinal["campos"] == ["link", "created", "enabled"]
    assert not prodes.pode_treinar


def test_cli_arcgis_exige_bbox_valida_antes_de_conectar_banco():
    from raiz.cli import app

    r = CliRunner().invoke(app, ["coleta", "arcgis", "sfb_cnfp_arcgis", "PA", str(COD), "--bbox=1,2,0,3"])
    assert r.exit_code == 2 and "bbox inválida" in r.output


@pytest.mark.banco
def test_cursor_e_hash_arcgis_no_banco_so_avancam_apos_snapshot(con, tmp_path, monkeypatch):
    from raiz.coleta.manifesto import Manifesto
    from raiz.coleta.replicacao import estado, sincronizar_fontes

    f = fonte()
    sincronizar_fontes(con, Manifesto(versao="teste-arcgis", fontes=[f]))
    esp = Espelho(tmp_path)
    g = gpd.GeoDataFrame({"fid": [1], "codigo": ["G1"], "uf": ["PA"]}, geometry=[Point(-47.5, -2.5)], crs=4674)
    monkeypatch.setattr(arcgis, "ler", lambda *args, **kwargs: (g, 10))
    r = arcgis.coletar_municipio(None, con, esp, f, "PA", COD, CAIXA)
    e = estado(con, f.id, f"PA/{COD}")
    assert r.acao == "atualizado" and e.cursor == "10" and e.contagem == 1 and e.hash_conteudo
    aceito = e.hash_conteudo, e.assinatura

    def incompleta(*args, **kwargs):
        raise LeituraIncompleta("a edição ArcGIS mudou durante a leitura")

    monkeypatch.setattr(arcgis, "ler", incompleta)
    r = arcgis.coletar_municipio(None, con, esp, f, "PA", COD, CAIXA)
    e = estado(con, f.id, f"PA/{COD}")
    assert r.acao == "falha" and e.sujo and e.cursor == "10"
    assert (e.hash_conteudo, e.assinatura) == aceito


@pytest.mark.parametrize("acao", ["sem_mudanca", "travado"])
def test_cli_ibama_retoma_historico_apos_transacao_inclusive_304(tmp_path, monkeypatch, acao):
    import raiz.banco
    import raiz.coleta.http
    import raiz.coleta.ibama
    import raiz.coleta.replicacao
    import raiz.coleta.rodada
    import raiz.funil.ponte
    from raiz.cli import app

    chamadas = []

    @contextmanager
    def begin():
        chamadas.append("inicio")
        yield None
        chamadas.append("commit")

    eng = SimpleNamespace(begin=begin)
    monkeypatch.setattr(raiz.banco, "engine", lambda: eng)
    monkeypatch.setattr(raiz.funil.ponte, "espelho_padrao", lambda: tmp_path)
    monkeypatch.setattr(raiz.coleta.http, "sessao", lambda: None)
    monkeypatch.setattr(raiz.coleta.replicacao, "sincronizar_fontes", lambda con: None)
    monkeypatch.setattr(raiz.coleta.ibama, "coletar", lambda *args, **kwargs: raiz.coleta.ibama.ResultadoIbama(acao))
    for uf, cod in [("PA", COD), ("MT", 5105150)]:
        p = tmp_path / "ibama" / uf / f"{cod}.parquet"
        p.parent.mkdir(parents=True)
        p.touch()

    def historico(engine, esp, uf, cods, hc, agora):
        assert "commit" in chamadas and engine is eng
        chamadas.append((uf, cods))
        return 1

    monkeypatch.setattr(raiz.coleta.rodada, "sincronizar_historico", historico)
    r = CliRunner().invoke(app, ["coleta", "ibama"])
    assert r.exit_code == (1 if acao == "travado" else 0), r.output
    assert chamadas == ["inicio", "commit", ("MT", [5105150]), ("PA", [COD])]
    assert "cargas no histórico: 2" in r.output
