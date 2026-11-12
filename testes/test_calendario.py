"""Páginas oficiais gravadas, privacidade, retificações e calendário público."""

import datetime as dt
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from raiz.calendario import arquivos, banco, coleta
from raiz.calendario.api import roteador
from raiz.calendario.feed import ics
from raiz.calendario.mcp import proximos_eventos
from raiz.calendario.modelos import Evento, FonteEstado, identificador
from testes.test_privacidade import CNPJ, CPF

AGORA = dt.datetime(2026, 11, 12, 10, tzinfo=dt.UTC)
CAR = "PA-1504950-" + "A" * 32
OUTRO = "PA-1504950-" + "B" * 32
SIGEF = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
FIXTURES = Path(__file__).parent / "fixtures" / "calendario"


def fonte(fid="djen"):
    return next(f for f in coleta.fontes() if f["id"] == fid)


def evento(**kw):
    d = dict(
        id=identificador("djen", "teste", "leilao_imovel", "1"),
        tipo="leilao_imovel",
        data=dt.date(2026, 11, 30),
        fonte_id="djen",
        fonte_nome=fonte()["nome"],
        fonte_url=fonte()["urls"][0] + "/ABCDEFGHIJK/certidao",
        codigos_car=[CAR],
        coletado_em=AGORA,
        atualizado_em=AGORA,
        confianca=0.85,
    )
    return Evento(**(d | kw))


@pytest.mark.parametrize(
    "fid,esperado",
    [
        ("icvcm", ["2026-06-07", "2026-12-04"]),
        ("eudr", ["2026-12-30", "2027-06-30", "2027-12-30"]),
        ("fomento_pr", ["2026-03-30", "2026-03-30"]),
    ],
)
def test_paginas_oficiais_gravadas(fid, esperado):
    f = fonte(fid)
    eventos, _ = coleta.extrair((FIXTURES / f"{fid}.html").read_text(), f, f["urls"][0], AGORA)
    assert sorted(str(e.dia) for e in eventos) == esperado
    assert len({e.id for e in eventos}) == len(eventos)
    assert all(e.fonte_id == fid for e in eventos)


def test_djen_separa_atos_e_descarta_texto_pessoal():
    f = fonte()
    comunicado = f"<p>Edital de leilão rural nº 7/2026. CAR: {CAR}. CNS: 123456. Matrícula 987.</p>"
    comunicado += f"<p>Leilão em 30/11/2026. Titular Pessoa de Teste, CPF {CPF}, CNPJ {CNPJ}.</p>"
    raw = json.dumps(
        {
            "items": [
                {"hash": "ABCDEFGHIJKL", "texto": comunicado, "destinatarios": [{"nome": "Pessoa de Teste"}]},
                {
                    "hash": "MNOPQRSTUVWX",
                    "texto": f"Edital de leilão rural nº 8/2026. CAR {OUTRO}. Leilão em 01/12/2026.",
                },
            ]
        }
    )
    eventos, _ = coleta.extrair(raw, f, f["urls"][0], AGORA)
    assert len(eventos) == 2
    assert eventos[0].codigos_car == [CAR] and eventos[1].codigos_car == [OUTRO]
    assert eventos[0].cns == "123456" and eventos[0].matricula == "987"
    guardado = json.dumps([e.model_dump(mode="json") for e in eventos])
    assert all(s not in guardado for s in [CPF, CNPJ, "Pessoa de Teste", "destinatarios"])
    assert eventos[0].fonte_url.endswith("/ABCDEFGHIJKL/certidao")


def test_html_nao_cruza_artigo_com_varios_editais_e_ignora_publicacao():
    f = fonte("fomento_pr")
    tx = f"""<article><div class="spoiler-content">Edital de leilão rural 1/2026. CAR {CAR}.
      Publicado em 12/11/2026. Leilão em 30/11/2026.</div>
      <div class="spoiler-content">Edital de leilão rural 2/2026. CAR {OUTRO}. Leilão em 01/12/2026.</div>
      <div class="spoiler-content">Credenciamento de leiloeiros: inscrições até 02/12/2026.</div></article>"""
    es, _ = coleta.extrair(tx, f, f["urls"][0], AGORA)
    assert [(e.data, e.codigos_car) for e in es] == [(dt.date(2026, 11, 30), [CAR]), (dt.date(2026, 12, 1), [OUTRO])]


def test_pdf_identificadores_na_mesma_publicacao_e_nao_em_diario_sem_limite():
    f = fonte("fomento_pr")
    tx = f"EDITAL DE LEILÃO rural nº 1/2026\nLeilão em 30/11/2026.\n\nCAR {CAR}. SIGEF: {SIGEF}"
    es, _ = coleta.extrair(tx, f, f["urls"][0], AGORA, "pdf")
    assert es[0].codigos_car == [CAR] and es[0].sigef == [SIGEF]
    es, _ = coleta.extrair(
        tx.replace("EDITAL DE LEILÃO", "Edição oficial"), fonte("doe_pa"), fonte("doe_pa")["urls"][0], AGORA, "pdf"
    )
    assert es == []


def test_coleta_limitada_falha_sem_log_pessoal_e_manifesto_nao_muda(caplog):
    f = {**fonte("icvcm"), "max_paginas": 1, "seguir_links": True}
    urls = list(f["urls"])
    tx = (FIXTURES / "icvcm.html").read_text()
    es, estado = coleta.coletar_fonte(f, AGORA, obter=lambda *_: (tx, "html"))
    assert es and estado.situacao == "parcial" and f["urls"] == urls

    def falhar(*_):
        raise RuntimeError(f"Pessoa de Teste {CPF}")

    es, estado = coleta.coletar_fonte(f, AGORA, obter=falhar)
    assert not es and estado.situacao == "erro"
    assert CPF not in estado.model_dump_json() + caplog.text and "Pessoa de Teste" not in estado.model_dump_json()


def test_nao_acessa_host_externo_ou_parametro_pessoal():
    f = fonte("icvcm")
    tx = f'<a href="https://127.0.0.1/consultation">consultation</a><a href="https://icvcm.org/?cpf={CPF}">consultation</a>'
    assert coleta._links(tx, f["urls"][0], f) == []
    for url in [f"https://icvcm.org/{CPF}", "https://a:b@icvcm.org/", "https://icvcm.org/?token=privado"]:
        with pytest.raises(ValueError):
            evento(fonte_url=url)


def test_uid_retificacao_cancelamento_ausencia_nao_apaga():
    a = evento()
    b = evento(data=dt.date(2026, 12, 4), coletado_em=AGORA + dt.timedelta(days=1))
    c = banco.combinar([a], [b])[0]
    assert c.id == a.id and c.sequencia == 1
    assert banco.combinar([c], [a])[0] == c
    assert banco.combinar([c], [])[0] == c
    igual = banco.combinar([c], [c.model_copy(update={"coletado_em": AGORA + dt.timedelta(days=2)})])[0]
    assert igual.sequencia == 1
    cancelado = banco.combinar([igual], [igual.model_copy(update={"situacao": "cancelado"})])[0]
    assert cancelado.sequencia == 2
    feed = ics([cancelado])
    assert f"UID:{a.id}@calendario.raiz" in feed and "SEQUENCE:2" in feed and "STATUS:CANCELLED" in feed
    assert "DTSTART;VALUE=DATE:20261204" in feed and "DTEND;VALUE=DATE:20261205" in feed
    assert all(len(linha.encode()) <= 75 for linha in feed.split("\r\n"))


def test_snapshot_so_campos_publicos_e_importacao_confiavel(tmp_path):
    e = evento(cns="123456", matricula="987", sigef=[SIGEF])
    estado = FonteEstado(id="djen", nome=fonte()["nome"], coletado_em=AGORA, situacao="ok")
    arquivos.publicar(tmp_path, [e], [estado])
    publico = json.loads((tmp_path / "eventos.json").read_text())
    assert not {"cns", "matricula", "sigef"} & publico["eventos"][0].keys()
    dados = json.loads((tmp_path / "estado.json").read_text())
    dados["eventos"][0]["fonte_nome"] = "Pessoa de Teste"
    dados["fontes"][0]["erro"] = CPF
    arq = tmp_path / "importar.json"
    arq.write_text(json.dumps(dados))
    eventos, estados = arquivos.ler(arq)
    assert eventos[0].fonte_nome == fonte()["nome"] and estados[0].erro is None
    dados["eventos"][0]["fonte_url"] = "https://outro.example/leilao"
    arq.write_text(json.dumps(dados))
    with pytest.raises(ValueError, match="fora do manifesto"):
        arquivos.ler(arq)
    with pytest.raises(ValidationError):
        evento(referencia="Pessoa de Teste")


@pytest.mark.banco
def test_banco_historico_alerta_deduplicado_api_e_mcp(con, banco_url):
    con.execute(text("delete from calendario.evento"))
    e = evento()
    assert banco.gravar(con, [e], []) == 1
    assert banco.gravar(con, [e], []) == 0
    cliente = con.execute(
        text(
            "insert into negocio.cliente(rotulo,token_hmac) values('teste-calendario','calendario-teste') returning id"
        )
    ).scalar_one()
    pedido = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    con.execute(
        text("insert into negocio.pedido(id,cliente_id,estado,campos) values(:id,:c,'grupo_pronto','{}')"),
        {"id": pedido, "c": cliente},
    )
    con.execute(
        text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values(:id,:car,'lote')"),
        {"id": pedido, "car": CAR.lower()},
    )
    assert banco.avisar_pedidos(con, AGORA.date()) == 1
    assert banco.avisar_pedidos(con, AGORA.date()) == 0
    canais = con.execute(text("select canal,estado from negocio.notificacao where pedido_id=:id"), {"id": pedido}).all()
    assert set(canais) == {("painel", "enviada"), ("email", "simulada"), ("whatsapp", "simulada")}
    novo = e.model_copy(update={"data": dt.date(2026, 12, 5), "coletado_em": AGORA + dt.timedelta(days=1)})
    assert banco.gravar(con, [novo], []) == 1
    assert banco.avisar_pedidos(con, AGORA.date()) == 1
    assert con.execute(text("select count(*) from calendario.evento_historico")).scalar() == 2
    resultado = banco.consultar(con, cod_imovel=CAR, inicio=dt.date(2026, 12, 1), estado="PA")
    assert resultado["total"] == 1 and resultado["eventos"][0]["sequencia"] == 1
    con.commit()
    eng = create_engine(banco_url)
    app = FastAPI()
    app.include_router(roteador(lambda _: eng))
    with TestClient(app) as cliente_api:
        assert cliente_api.get("/eventos", params={"cod_imovel": CAR.lower()}).json()["total"] == 1
        assert cliente_api.get("/eventos", params={"tipo": "invalido"}).status_code == 422
        assert cliente_api.get("/eventos", params={"inicio": "2026-12-01", "fim": "2026-11-01"}).status_code == 422
        r = cliente_api.get("/eventos.ics")
        assert r.status_code == 200 and "text/calendar" in r.headers["content-type"]
        assert "SEQUENCE:1" in r.text and "token" not in r.text
    assert proximos_eventos(engine=eng, hoje=AGORA.date(), cod_imovel=CAR)["total"] == 1
    eng.dispose()


def test_cancelamento_sem_repetir_data_retifica_anterior_e_mantem_uid():
    f = fonte("fomento_pr")
    url = f["urls"][0]
    es, _ = coleta.extrair(f"<p>Edital 12/2026. Leilão de imóvel rural em 30/11/2026. CAR {CAR}.</p>", f, url, AGORA)
    novos, _ = coleta.extrair(
        "<p>Edital 12/2026. Leilão de imóvel rural cancelado.</p>", f, url, AGORA + dt.timedelta(days=1), anteriores=es
    )
    final = banco.combinar(es, novos)
    assert len(final) == 1 and final[0].situacao == "cancelado" and final[0].sequencia == 1
    novos, _ = coleta.extrair(
        f"<p>Edital 12/2026. Leilão de imóvel rural cancelado. CAR {CAR}.</p>",
        f,
        url + "/retificacao",
        AGORA + dt.timedelta(days=2),
        anteriores=es,
    )
    assert len(novos) == 1 and novos[0].id == es[0].id and novos[0].situacao == "cancelado"
    with pytest.raises(ValueError):
        evento(fonte_url="https://icvcm.org/?n%6fme=NAO_PUBLICAR")


def test_prazo_nao_extraido_informa_cobertura_parcial():
    f = {**fonte("icvcm"), "urls": ["https://icvcm.org/consulta"], "max_paginas": 2}
    tx = "<p>Consultation closes 30 November 2026.</p><p>Prazo 20/11/2026.</p>"
    es, estado = coleta.coletar_fonte(f, AGORA, obter=lambda *_: (tx, "html"))
    assert len(es) == 1 and estado.sem_data == 1 and estado.situacao == "parcial"


@pytest.mark.banco
def test_cruzamento_cns_matricula_e_sigef_com_imovel_pequeno(con):
    rodada = con.execute(
        text("""insert into funil.rodada
        (tipo,uf,cod_municipio,origem,arquivos,hash_entradas,motor_versao,regras_versao,data_corte)
        values ('municipio','PA',1504950,'teste','{}','calendario-cruzamento','teste','teste','2026-11-12')
        returning id""")
    ).scalar_one()
    con.execute(
        text("""insert into titulo.certidao_alvo
        (rodada_id,cod_imovel,registro_cns,registro_matricula) values (:r,:car,'123456','987')"""),
        {"r": rodada, "car": CAR},
    )
    con.execute(
        text("insert into funil.vigente(cod_imovel,rodada_id,cod_busca) values(:car,:r,:car)"),
        {"car": CAR, "r": rodada},
    )
    e = evento(codigos_car=[], cns="123456", matricula="987")
    assert banco.cruzar(con, e).codigos_car == [CAR]
    assert banco.cruzar(con, e).vinculo == "cns_matricula"
    assert not banco.cruzar(con, e.model_copy(update={"cns": "654321"})).codigos_car
    con.execute(
        text("""insert into funil.imovel(cod_imovel,uf,geom)
        values (:car,'PA', ST_Multi(ST_GeomFromText(
        'POLYGON((-47 -2,-46.9999 -2,-46.9999 -1.9999,-47 -1.9999,-47 -2))',4674)))"""),
        {"car": OUTRO},
    )
    con.execute(
        text("insert into funil.vigente(cod_imovel,rodada_id,cod_busca) values(:car,:r,:car)"),
        {"car": OUTRO, "r": rodada},
    )
    con.execute(text("create schema if not exists bruto"))
    ja_existe = con.execute(text("select to_regclass('bruto.sigef_parcela_vigente')")).scalar()
    if ja_existe:
        con.execute(text("alter view bruto.sigef_parcela_vigente rename to calendario_sigef_anterior"))
    con.execute(
        text("""create view bruto.sigef_parcela_vigente as select
        'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'::text parcela_codigo,
        ST_GeomFromText('POLYGON((-47 -2,-46.9999 -2,-46.9999 -1.9999,-47 -1.9999,-47 -2))',4674) geom""")
    )
    try:
        vinculado = banco.cruzar(con, evento(codigos_car=[], sigef=[SIGEF]))
        assert vinculado.codigos_car == [OUTRO] and vinculado.vinculo == "sigef"
    finally:
        con.execute(text("drop view bruto.sigef_parcela_vigente"))
        if ja_existe:
            con.execute(text("alter view bruto.calendario_sigef_anterior rename to sigef_parcela_vigente"))


def test_indice_de_cards_nao_reabre_detalhes_e_cancelamento_nao_regride():
    f = fonte("icvcm")
    vistas = []

    def obter(url, _):
        vistas.append(url)
        return (FIXTURES / "icvcm.html").read_text(), "html"

    antigos, _ = coleta.extrair((FIXTURES / "icvcm.html").read_text(), f, f["urls"][0], AGORA)
    coleta.coletar_fonte(f, AGORA, obter=obter, anteriores=antigos)
    assert vistas == f["urls"]
    antes = evento(situacao="cancelado", fonte_url=fonte()["urls"][0] + "/RETIFICACAO123/certidao")
    antigo_revisitado = evento(coletado_em=AGORA + dt.timedelta(days=1))
    assert banco.combinar([antes], [antigo_revisitado])[0].situacao == "cancelado"


@pytest.mark.parametrize("inverter", [False, True])
@pytest.mark.parametrize("paginas", [False, True])
def test_cancelamento_na_mesma_coleta_independe_ordem_itens_e_paginas(inverter, paginas):
    f = {**fonte(), "termos": ["leilão rural", "penhora rural"] if paginas else ["leilão rural"], "max_paginas": 2}
    original = {"hash": "ABCDEFGHIJKL", "texto": f"Edital 12/2026. Leilão de imóvel rural em 30/11/2026. CAR {CAR}."}
    cancelamento = {"hash": "MNOPQRSTUVWX", "texto": f"Edital 12/2026. Leilão de imóvel rural cancelado. CAR {CAR}."}
    antigos, _ = coleta.extrair(json.dumps({"items": [original]}), f, f["urls"][0], AGORA)
    itens = [original, cancelamento] if inverter else [cancelamento, original]
    respostas = iter([[item] for item in itens] if paginas else [itens])
    novos, estado = coleta.coletar_fonte(
        f,
        AGORA + dt.timedelta(days=1),
        anteriores=antigos,
        obter=lambda *_: (json.dumps({"items": next(respostas)}), "html"),
    )
    final = banco.combinar(antigos, novos)
    assert estado.eventos == 1 and len(final) == 1
    assert final[0].situacao == "cancelado" and final[0].sequencia == 1


@pytest.mark.banco
@pytest.mark.parametrize("nova_matricula", ["654", None])
def test_cruzamento_matricula_corrigida_ou_removida_nao_usa_rodada_antiga(con, nova_matricula):
    cns = "654321" if nova_matricula else "654322"
    cod = "PA-1504950-" + ("C" if nova_matricula else "D") * 32

    def rodada(sufixo, corte):
        return con.execute(
            text("""insert into funil.rodada
            (tipo,uf,cod_municipio,origem,arquivos,hash_entradas,motor_versao,regras_versao,data_corte)
            values ('municipio','PA',1504950,'teste','{}',:h,'teste','teste',:corte) returning id"""),
            {"h": f"calendario-correcao-{nova_matricula}-{sufixo}", "corte": corte},
        ).scalar_one()

    anterior = rodada("antes", "2026-11-11")
    atual = rodada("atual", "2026-11-12")
    con.execute(
        text("""insert into titulo.certidao_alvo
        (rodada_id,cod_imovel,registro_cns,registro_matricula) values (:r,:car,:cns,'987')"""),
        {"r": anterior, "car": cod, "cns": cns},
    )
    con.execute(
        text("insert into funil.vigente(cod_imovel,rodada_id,cod_busca) values(:car,:r,:car)"),
        {"r": anterior, "car": cod},
    )
    e = evento(codigos_car=[], cns=cns, matricula="987")
    vinculado = banco.cruzar(con, e)
    assert vinculado.codigos_car == [cod]
    con.execute(text("update funil.vigente set rodada_id=:r where cod_imovel=:car"), {"r": atual, "car": cod})
    if nova_matricula:
        con.execute(
            text("""insert into titulo.certidao_alvo
            (rodada_id,cod_imovel,registro_cns,registro_matricula) values (:r,:car,:cns,:m)"""),
            {"r": atual, "car": cod, "m": nova_matricula, "cns": cns},
        )
        assert banco.cruzar(con, e.model_copy(update={"matricula": nova_matricula})).codigos_car == [cod]
    assert banco.cruzar(con, e).codigos_car == []
    revalidado = banco.cruzar(con, vinculado)
    assert revalidado.codigos_car == [] and revalidado.vinculo == "pendente"


@pytest.mark.banco
@pytest.mark.parametrize("vinculo", ["cns_matricula", "sigef"])
def test_enriquecimento_fica_interno_sem_vazar_por_filtro_publico(con, tmp_path, vinculo):
    cod = "PA-1504950-" + ("E" if vinculo == "sigef" else "F") * 32
    e = evento(
        id=identificador("djen", "enriquecido", "leilao_imovel", vinculo),
        codigos_car=[cod],
        cns="654321",
        matricula="765",
        sigef=[SIGEF],
        vinculo=vinculo,
    )
    banco.gravar(con, [e], [], cruzar_imoveis=False)
    assert (
        con.execute(
            text("select cod_imovel from calendario.evento_imovel where evento_id=:id"), {"id": e.id}
        ).scalar_one()
        == cod
    )
    assert e.publico()["codigos_car"] == [] and e.publico()["vinculo"] == "pendente"
    assert banco.consultar(con, cod_imovel=cod)["total"] == 0
    assert arquivos.envelope([e], [], cod_imovel=cod)["total"] == 0
    assert not any(item["codigos_car"] for item in banco.consultar(con)["eventos"] if item["id"] == e.id)
    arquivos.publicar(tmp_path, [e], [])
    publico = (tmp_path / "eventos.json").read_text() + (tmp_path / "eventos.ics").read_text()
    assert cod not in publico and SIGEF not in publico and "654321" not in publico
    # O estado administrativo conserva o vínculo para o servidor e para avisos.
    assert cod in (tmp_path / "estado.json").read_text()
    assert cod not in ics([e])
    explicito = e.model_copy(update={"vinculo": "car"})
    assert explicito.publico()["codigos_car"] == [cod]
    assert arquivos.envelope([explicito], [], cod_imovel=cod)["total"] == 1
    banco.gravar(con, [explicito], [], cruzar_imoveis=False)
    assert banco.consultar(con, cod_imovel=cod)["total"] == 1


def test_pagina_extensa_nao_compara_arvores_inteiras(monkeypatch):
    from bs4.element import Tag

    original = Tag.__eq__
    comparacoes = 0

    def contar(self, outro):
        nonlocal comparacoes
        comparacoes += 1
        return original(self, outro)

    monkeypatch.setattr(Tag, "__eq__", contar)
    f = fonte("icvcm")
    pagina = "<main><article>" + "<p>Consultation closes 30 November 2026.</p>" * 2000 + "</article></main>"
    eventos, _ = coleta.extrair(pagina, f, f["urls"][0], AGORA)
    assert len(eventos) == 1
    assert comparacoes < 10  # regressão: a seleção fazia milhões de comparações profundas


def test_portal_florestal_nao_transforma_pregao_comum_ou_lei_em_concessao():
    f = fonte("ideflor_bio")
    tx = "Pregão eletrônico para serviço de mecanização. Sessão pública em 27/11/2025."
    eventos, _ = coleta.extrair(tx, f, f["urls"][0], AGORA, "pdf")
    assert eventos == []
    tx = (
        "Edital de concessão florestal. Aplicação da Lei Complementar nº 123, de 14 de dezembro de 2006. "
        "Entrega de propostas em 16/04/2025."
    )
    eventos, _ = coleta.extrair(tx, f, f["urls"][0], AGORA, "pdf")
    assert [(e.data, e.marco) for e in eventos] == [(dt.date(2025, 4, 16), "propostas")]


def test_data_repetida_na_mesma_publicacao_nao_duplica_evento():
    f = fonte("verra")
    tx = "<p>Consultation closes 20 March 2026.</p><p>Public comments deadline: 20 March 2026.</p>"
    eventos, _ = coleta.extrair(tx, f, f["urls"][0], AGORA)
    assert len(eventos) == 1 and eventos[0].prazo == dt.date(2026, 3, 20)


def test_numero_do_edital_nao_vem_de_item_do_corpo():
    assert coleta._referencia("edital de concorrencia publica n.º 001/2025 - anexo") == "001/2025"
    assert coleta._referencia("deste edital 2. objeto do leilao") is None
    assert coleta._referencia("edital nº 5") == "5"
    assert coleta._referencia("edital 12/2026") == "12/2026"


def test_sbti_oficial_exclui_contratacao_e_inclui_survey_ate_data():
    f = fonte("sbti")
    eventos, _ = coleta.extrair((FIXTURES / "sbti.html").read_text(), f, f["urls"][0], AGORA)
    assert [(e.data, e.marco) for e in eventos] == [
        (dt.date(2026, 12, 4), "consulta"),
        (dt.date(2026, 12, 6), "consulta"),
    ]
