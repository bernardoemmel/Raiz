"""Polígonos, isolamento por empresa e revisão sem contornar salvaguardas."""

import base64
import datetime as dt
import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz import salvaguardas as SG
from raiz.pedidos import oferta
from raiz.pedidos import servico as S
from raiz.pessoal import gerar_chave
from raiz.publica import aprovacao, recibos
from raiz.publica import chaves as K

pytestmark = pytest.mark.banco
EV = {"sha256": "b" * 64, "data": "2026-01-01"}
COD = "PA-SALVAGUARDA-TESTE"
TOKEN = "token-interno-salvaguardas-teste"


@pytest.fixture(autouse=True)
def configuracao(monkeypatch):
    import raiz.api as principal

    monkeypatch.setattr(principal, "config", lambda: type("C", (), {"api_token": SecretStr(TOKEN)})())
    monkeypatch.delenv("RAIZ_ABACATEPAY_CHAVE", raising=False)


def _app(eng):
    from raiz.api import criar_app

    return criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as con:
        con.execute(text("truncate geo.redd_programa, geo.redd_cobertura"))
        con.execute(
            text("""insert into funil.imovel (cod_imovel, uf, geom) values (:c, 'PA',
            ST_Multi(ST_GeomFromText('POLYGON((-50 -3,-49 -3,-49 -2,-50 -2,-50 -3))', 4674)))"""),
            {"c": COD},
        )
        linha = oferta.de_linha(
            {
                "cod_imovel": COD,
                "caminho_terra": "privada_matricula",
                "uf": "PA",
                "restauracao_area_ha": 2,
                "modo_restauracao": "plantio_total",
            }
        )
        con.execute(
            text("""insert into negocio.oferta (cod_imovel, atributos) values (:c, cast(:a as jsonb))"""),
            {"c": COD, "a": json.dumps(linha)},
        )
    yield e
    e.dispose()


def test_sobreposicao_real_e_reverificacao_da_oferta(eng):
    SG.registrar_programa(
        eng,
        SG.Programa(
            id="pa-contabil-2020",
            uf="PA",
            inicio="2020-01-01",
            fim="2025-12-31",
            fonte="https://exemplo.gov.br/redd",
            evidencia=EV,
            geometria={"type": "Polygon", "coordinates": [[[-50, -3], [-49.5, -3], [-49.5, -2], [-50, -2], [-50, -3]]]},
        ),
    )
    dados = SG.do_banco(eng, [COD])[COD]
    assert dados["redd_programas"][0]["area_ha"] > 0
    assert not dados["redd_cobertura_verificada"]
    assert not oferta.do_banco(eng).set_index("cod_imovel").loc[COD, "elegivel"]
    with pytest.raises(S.ErroPedido, match="salvaguardas"):
        SG.exigir_para_reserva(eng, [COD])
    ev = {**EV, "data": dt.date.today().isoformat()}
    SG.registrar_cobertura(eng, SG.Cobertura(uf="PA", evidencia=ev, valida_ate=dt.date.today()))
    SG.registrar_verificacao(
        eng,
        COD,
        SG.Verificacao(
            verificacao=ev,
            territorio_tradicional=False,
            exclusoes_conaredd={"pa-contabil-2020": ev},
        ),
    )
    assert oferta.do_banco(eng).set_index("cod_imovel").loc[COD, "elegivel"]
    SG.exigir_para_reserva(eng, [COD])
    geo = SG.camada(eng)
    assert geo["features"][0]["properties"]["inicio"] == "2020-01-01"


def test_revisao_tem_protocolo_criterios_e_credencial_humana(eng, monkeypatch):
    cid, sessao = S.criar_cliente(eng, "empresa de teste")
    outro, sessao_outro = S.criar_cliente(eng, "outra empresa")
    pid = str(uuid.uuid4())
    with eng.begin() as con:
        con.execute(
            text("""insert into negocio.pedido (id, cliente_id, estado, campos, premissas_versao)
            values (:p, :c, 'lote_montado', '{}', 'teste')"""),
            {"p": pid, "c": cid},
        )
        S._salvar_sugestao(con, pid, "teste", {}, [{"id": "segura", "itens": [{"cod_imovel": COD}]}])
        for c in (cid, outro):
            con.execute(
                text("""insert into negocio.conta_api (cliente_id, cnpj_hmac, cnpj_mascarado, termos_versao,
                contrato_aceito_em, sinal_pago_em) values (:c, :h, '**', 'teste', now(), now())"""),
                {"c": c, "h": uuid.uuid4().hex},
            )
    chave_agente = K.criar(eng, cid)["chave"]
    with TestClient(_app(eng)) as cl:
        h = {"Authorization": f"Bearer {sessao}"}
        corpo = {"cod_imovel": COD, "motivo": "nota_de_risco"}
        r = cl.post(f"/pedidos/{pid}/revisoes", headers=h, json=corpo)
        assert r.status_code == 200, r.text
        assert r.history[0].status_code == 307 and r.url.path == f"/v1/pedidos/{pid}/revisoes"
        rid = r.json()["revisao_id"]
        assert r.json()["criterios"]["regra"] == SG.VERSAO
        assert cl.post(f"/pedidos/{pid}/revisoes", headers=h, json=corpo).json()["revisao_id"] == rid
        assert (
            cl.get(f"/pedidos/{pid}/revisoes", headers={"Authorization": f"Bearer {sessao_outro}"}).status_code == 404
        )
        assert (
            cl.post(f"/pedidos/{pid}/revisoes", headers={"X-Chave-API": chave_agente}, json=corpo).status_code == 403
        )  # contestação exige a sessão da pessoa, não a chave do agente
        resolucao = {"revisor_id": str(uuid.uuid4()), "decisao": "corrigir_dados", "evidencia": EV}
        rota = f"/salvaguardas/revisoes/{rid}/resolver"
        interno = {"Authorization": f"Bearer {TOKEN}"}
        assert cl.post(rota, json=resolucao).status_code == 401
        assert cl.post(rota, json=resolucao, headers=interno).status_code == 403
        monkeypatch.setenv("RAIZ_REVISAO_HUMANA_TOKEN", "credencial-humana-teste")
        assert cl.post(rota, json=resolucao, headers=interno).status_code == 403
        assert cl.post(rota, json=resolucao, headers={"X-Revisao-Humana": "credencial-humana-teste"}).status_code == 401
        assert (
            cl.post(
                rota, json=resolucao, headers={**interno, "X-Revisao-Humana": "credencial-humana-teste"}
            ).status_code
            == 200
        )
        lista = cl.get(f"/pedidos/{pid}/revisoes", headers=h).json()
        assert lista[0]["estado"] == "resolvida" and lista[0]["decisao"] == "corrigir_dados"
        assert "revisor_id" not in lista[0]  # cliente não recebe identidade do revisor


def test_revisao_nao_abre_detalhe_sem_liberacao_ou_vinculo_e_respeita_exclusividade(eng):
    cid, sessao = S.criar_cliente(eng, "revisora de teste")
    outro, _ = S.criar_cliente(eng, "titular da reserva de teste")
    pid, pid_outro = str(uuid.uuid4()), str(uuid.uuid4())
    with eng.begin() as con:
        for p, c in ((pid, cid), (pid_outro, outro)):
            con.execute(
                text("""insert into negocio.pedido (id, cliente_id, estado, campos, premissas_versao)
                values (:p, :c, 'lote_montado', '{}', 'teste')"""),
                {"p": p, "c": c},
            )
        con.execute(
            text("""insert into negocio.conta_api (cliente_id, cnpj_hmac, cnpj_mascarado, termos_versao)
            values (:c, :h, '**', 'teste')"""),
            {"c": cid, "h": uuid.uuid4().hex},
        )
    rota = f"/pedidos/{pid}/revisoes"
    corpo = {"cod_imovel": COD, "motivo": "exclusao_automatica"}
    with TestClient(_app(eng)) as cl:
        h = {"Authorization": f"Bearer {sessao}"}
        assert cl.post(rota, headers=h, json=corpo).status_code == 403
        assert cl.get(rota, headers=h).status_code == 403
        with eng.begin() as con:
            con.execute(
                text("update negocio.conta_api set contrato_aceito_em = now() where cliente_id = :c"), {"c": cid}
            )
        assert cl.post(rota, headers=h, json=corpo).status_code == 403  # só contrato não basta
        with eng.begin() as con:
            con.execute(text("update negocio.conta_api set sinal_pago_em = now() where cliente_id = :c"), {"c": cid})
        r = cl.post(rota, headers=h, json=corpo)
        assert r.status_code == 404 and "criterios" not in r.json()
        with eng.begin() as con:
            assert (
                con.execute(
                    text("select count(*) from negocio.revisao_humana where pedido_id = :p"), {"p": pid}
                ).scalar()
                == 0
            )
            # Mesmo uma fazenda que saiu do grupo pode contestar uma decisão já vinculada ao pedido.
            con.execute(
                text("insert into negocio.pedido_fazenda (pedido_id, cod_imovel, papel) values (:p, :cod, 'fora')"),
                {"p": pid, "cod": COD},
            )
        assert cl.post(rota, headers=h, json=corpo).status_code == 200
        assert len(cl.get(rota, headers=h).json()) == 1
        with eng.begin() as con:
            rid = con.execute(
                text("""insert into negocio.reserva (pedido_id, cliente_id, estado, ha, valor_rs, dias, inicio, fim)
                values (:p, :c, 'ativa', 2, 100, 1, now(), now() + interval '1 day') returning id"""),
                {"p": pid_outro, "c": outro},
            ).scalar_one()
            con.execute(
                text("insert into negocio.reserva_fazenda (reserva_id, cod_imovel, ativa) values (:r, :cod, true)"),
                {"r": rid, "cod": COD},
            )
        assert cl.post(rota, headers=h, json=corpo).status_code == 404
        assert cl.get(rota, headers=h).json() == []  # o histórico também não contorna exclusividade
        with eng.begin() as con:
            con.execute(text("delete from negocio.reserva_fazenda where reserva_id = :r"), {"r": rid})
            con.execute(text("delete from negocio.reserva where id = :r"), {"r": rid})


@pytest.fixture
def chaves_reserva(monkeypatch):
    chave = gerar_chave()
    monkeypatch.setattr("raiz.pessoal.config", lambda: type("C", (), {"chave_pessoal": SecretStr(chave)})())
    monkeypatch.setenv("RAIZ_RECIBO_CHAVE", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())


@pytest.fixture
def grupo_reserva(eng, chaves_reserva):
    """Grupo mínimo sintético: geometria e documentos são necessários, não pressupostos."""
    cid, _ = S.criar_cliente(eng, "compradora da reserva de teste")
    pid = str(uuid.uuid4())
    cod = f"TO-RESERVA-TESTE-{uuid.uuid4().hex}"
    with eng.begin() as con:
        con.execute(text("delete from geo.redd_cobertura where uf = 'TO'"))
        con.execute(text("insert into funil.imovel (cod_imovel, uf) values (:c, 'TO')"), {"c": cod})
        con.execute(
            text("""insert into negocio.oferta (cod_imovel, area_restauracao_ha, atributos)
            values (:c, 2, '{"caminho_terra": "privada_matricula", "uf": "TO"}')"""),
            {"c": cod},
        )
        con.execute(
            text("""insert into negocio.pedido (id, cliente_id, estado, campos, premissas_versao)
            values (:p, :c, 'grupo_pronto', '{}', 'teste')"""),
            {"p": pid, "c": cid},
        )
        con.execute(
            text("insert into negocio.pedido_fazenda (pedido_id, cod_imovel, papel) values (:p, :c, 'lote')"),
            {"p": pid, "c": cod},
        )
    _verificar_grupo(eng, cod)
    try:
        yield cid, pid, cod
    finally:
        # O catálogo diário consulta todas as contas ativas. O grupo sintético
        # desta fixture não pode vazar para outros testes como um lote real.
        with eng.begin() as con:
            con.execute(text("update negocio.cliente set ativo=false where id=:c"), {"c": cid})


def _verificar_grupo(eng, cod):
    hoje = dt.datetime.now(dt.UTC).date()
    ev = SG.Evidencia(sha256="d" * 64, data=hoje)
    with eng.begin() as con:
        con.execute(
            text("""update funil.imovel set geom = ST_Multi(ST_GeomFromText(
            'POLYGON((-48 -10,-47.99 -10,-47.99 -9.99,-48 -9.99,-48 -10))', 4674))
            where cod_imovel = :c"""),
            {"c": cod},
        )
    SG.registrar_cobertura(eng, SG.Cobertura(uf="TO", evidencia=ev, valida_ate=hoje))
    SG.registrar_verificacao(eng, cod, SG.Verificacao(verificacao=ev, territorio_tradicional=False))


def _invalidar_grupo(eng, cod, falta):
    with eng.begin() as con:
        if falta == "verificacao":
            con.execute(text("delete from negocio.salvaguarda where cod_imovel = :c"), {"c": cod})
        elif falta == "cobertura":
            con.execute(
                text("""update geo.redd_cobertura set verificada_em = current_date - 2,
            valida_ate = current_date - 1,
            evidencia = jsonb_set(evidencia, '{data}', to_jsonb((current_date - 2)::text)) where uf = 'TO'""")
            )
        elif falta == "geometria":
            con.execute(text("update funil.imovel set geom = null where cod_imovel = :c"), {"c": cod})
        elif falta == "clpi":
            con.execute(
                text("""update negocio.salvaguarda set evidencia =
                jsonb_set(evidencia, '{territorio_tradicional}', 'true') where cod_imovel = :c"""),
                {"c": cod},
            )
        else:
            raise AssertionError(f"cenário desconhecido: {falta}")


@pytest.mark.parametrize("falta", ["verificacao", "cobertura", "geometria", "clpi"])
def test_preparar_reserva_exige_evidencias_antes_de_qualquer_pix(eng, grupo_reserva, falta):
    cid, pid, cod = grupo_reserva
    _invalidar_grupo(eng, cod, falta)
    for por_agente in (None, "agente-de-teste"):
        with pytest.raises(SG.ErroSalvaguarda, match="salvaguardas"):
            S.reservar(eng, pid, cid, por_agente=por_agente)
    with eng.connect() as con:
        assert con.execute(text("select count(*) from negocio.reserva where pedido_id = :p"), {"p": pid}).scalar() == 0


@pytest.mark.parametrize("falta", ["verificacao", "cobertura", "geometria", "clpi"])
def test_confirmacao_revalida_grupo_congelado_e_preserva_link_apos_recusa(eng, grupo_reserva, falta, monkeypatch):
    cid, pid, cod = grupo_reserva
    monkeypatch.setattr(S, "ENVIO_CONFIRMACAO", lambda *a: pytest.fail("a preparação não envia token externamente"))
    preparada = S.reservar(eng, pid, cid, por_agente="agente-de-teste", base_url="https://api.raiz.example/v1")
    assert preparada["aguardando_confirmacao"] and preparada["pix"] is None
    assert preparada["recibo_aprovacao"] is None and not preparada["pago"]
    token = preparada["aprovacao_url"].rsplit("/", 1)[1]
    _invalidar_grupo(eng, cod, falta)
    with pytest.raises(SG.ErroSalvaguarda, match="salvaguardas"):
        S.reservar(eng, pid, cid, por_agente="agente-de-teste")
    # O serviço recebe a empresa autenticada pela rota humana, nunca infere o titular pelo token.
    with pytest.raises(SG.ErroSalvaguarda, match="salvaguardas"):
        aprovacao.aprovar(eng, token, cid)
    # Retirar a fazenda do pedido não contorna o grupo congelado nem consome o link de aprovação.
    with eng.begin() as con:
        con.execute(text("delete from negocio.pedido_fazenda where pedido_id = :p"), {"p": pid})
    with pytest.raises(S.ErroPedido, match="grupo não tem fazendas"):
        S.reservar(eng, pid, cid, por_agente="agente-de-teste")
    with pytest.raises(aprovacao.ErroAprovacao, match="fazendas do grupo mudaram"):
        aprovacao.aprovar(eng, token, cid)
    with eng.connect() as con:
        estado, tem_link, n_pix = con.execute(
            text("""select r.estado, r.confirmacao_hash is not null,
            (select count(*) from negocio.cobranca c where c.reserva_id = r.id)
            from negocio.reserva r where r.pedido_id = :p"""),
            {"p": pid},
        ).one()
        congelados = (
            con.execute(
                text("""select f.cod_imovel from negocio.reserva_fazenda f
        join negocio.reserva r on r.id=f.reserva_id where r.pedido_id=:p"""),
                {"p": pid},
            )
            .scalars()
            .all()
        )
    assert (estado, tem_link, n_pix) == ("aguardando_confirmacao", True, 0)
    assert congelados == [cod]
    _verificar_grupo(eng, cod)
    with eng.begin() as con:
        con.execute(
            text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values(:p,:c,'lote')"),
            {"p": pid, "c": cod},
        )
    confirmada = aprovacao.aprovar(eng, token, cid)
    assert confirmada["estado"] == "aguardando_pagamento" and confirmada["pix"]
    assert not confirmada["pago"] and confirmada["aprovacao_url"] is None
    mandato = recibos.verificar(confirmada["recibo_aprovacao"], recibos.jwk())
    assert mandato["empresa"] == cid and mandato["pedido"] == pid
    assert mandato["pagamento_confirmado"] is False and mandato["condicoes"]["agente_pode_pagar"] is False
    with pytest.raises(aprovacao.ErroAprovacao, match="link de confirmação inválido"):
        aprovacao.aprovar(eng, token, cid)

    with eng.connect() as con:
        assert (
            con.execute(
                text("""select count(*) from negocio.cobranca c join negocio.reserva r on c.reserva_id = r.id
            where r.pedido_id = :p"""),
                {"p": pid},
            ).scalar()
            == 1
        )


def test_programa_novo_exige_recertificar_cobertura_sem_apagar_certificado(eng, grupo_reserva):
    _, _, cod = grupo_reserva
    SG.exigir_para_reserva(eng, [cod])
    SG.registrar_programa(
        eng,
        SG.Programa(
            id="to-programa-novo-2026",
            uf="TO",
            inicio="2026-01-01",
            fim="2026-12-31",
            fonte="https://exemplo.gov.br/redd-to",
            evidencia=EV,
            geometria={
                "type": "Polygon",
                "coordinates": [[[-47, -12], [-46, -12], [-46, -11], [-47, -11], [-47, -12]]],
            },
        ),
    )
    dados = SG.do_banco(eng, [cod])[cod]
    assert dados["redd_programas"] == []  # a revisão do catálogo não é somente teste de interseção
    assert not dados["redd_cobertura_verificada"]
    with eng.connect() as con:
        ev, pendente = con.execute(
            text("select evidencia, revalidacao_pendente from geo.redd_cobertura where uf = 'TO'")
        ).one()
    assert ev["sha256"] == "d" * 64 and pendente
    with pytest.raises(SG.ErroSalvaguarda, match="salvaguardas"):
        SG.exigir_para_reserva(eng, [cod])
    hoje = dt.datetime.now(dt.UTC).date()
    SG.registrar_cobertura(
        eng, SG.Cobertura(uf="TO", evidencia=SG.Evidencia(sha256="e" * 64, data=hoje), valida_ate=hoje)
    )
    SG.exigir_para_reserva(eng, [cod])
