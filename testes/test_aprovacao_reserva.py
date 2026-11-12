"""Reserva preparada por agente só vira Pix após pessoa autenticada, evidência vigente e assinatura."""

import base64
import datetime as dt
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz import salvaguardas as SG
from raiz.pedidos import pix
from raiz.pedidos import servico as S
from raiz.pedidos.campos import CamposPedido
from raiz.pessoal import Cofre, gerar_chave
from raiz.publica import aprovacao, recibos


@pytest.fixture(scope="module")
def eng(request):
    url = os.environ.get("RAIZ_RESERVA_URL_TESTE") or request.getfixturevalue("banco_url")
    e = create_engine(url)
    yield e
    e.dispose()


@pytest.fixture
def chaves(monkeypatch):
    k = gerar_chave()
    monkeypatch.setattr("raiz.pessoal.config", lambda: type("C", (), {"chave_pessoal": SecretStr(k)})())
    monkeypatch.setenv("RAIZ_RECIBO_CHAVE", base64.urlsafe_b64encode(os.urandom(32)).decode())
    monkeypatch.delenv("RAIZ_ABACATEPAY_CHAVE", raising=False)
    return Cofre(k)


@pytest.fixture
def grupo(eng, chaves):
    cod = "PA-RESERVA-" + uuid.uuid4().hex
    pid = str(uuid.uuid4())
    hoje = dt.datetime.now(dt.UTC).date()
    with eng.begin() as con:
        cid = con.execute(
            text("insert into negocio.cliente(rotulo,token_hmac) values('teste-reserva',:h) returning id"),
            {"h": uuid.uuid4().hex},
        ).scalar_one()
        con.execute(
            text("""insert into funil.imovel(cod_imovel,uf,geom)
            values(:cod,'PA',ST_Multi(ST_GeomFromText(
            'POLYGON((-52 -5,-51.99 -5,-51.99 -4.99,-52 -4.99,-52 -5))',4674)))"""),
            {"cod": cod},
        )
        con.execute(
            text("""insert into negocio.oferta(cod_imovel,uf,area_restauracao_ha,atributos)
            values(:cod,'PA',2,'{"caminho_terra":"privada_matricula"}')"""),
            {"cod": cod},
        )
        con.execute(
            text("""insert into negocio.pedido(id,cliente_id,estado,campos,premissas_versao)
            values(:p,:c,'grupo_pronto',cast(:b as jsonb),'teste')"""),
            {"p": pid, "c": cid, "b": CamposPedido().model_dump_json()},
        )
        con.execute(
            text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values(:p,:cod,'lote')"),
            {"p": pid, "cod": cod},
        )
    evidencia = SG.Evidencia(sha256="a" * 64, data=hoje)
    SG.registrar_cobertura(eng, SG.Cobertura(uf="PA", evidencia=evidencia, valida_ate=hoje + dt.timedelta(days=30)))
    SG.registrar_verificacao(eng, cod, SG.Verificacao(verificacao=evidencia, territorio_tradicional=False))
    yield cid, pid, cod
    with eng.begin() as con:
        con.execute(text("delete from negocio.reserva where pedido_id=:p"), {"p": pid})
        con.execute(text("delete from negocio.pedido where id=:p"), {"p": pid})
        con.execute(text("delete from negocio.cliente where id=:c"), {"c": cid})
        con.execute(text("delete from negocio.oferta where cod_imovel=:cod"), {"cod": cod})
        con.execute(text("delete from funil.imovel where cod_imovel=:cod"), {"cod": cod})


def _preparar(eng, grupo):
    cid, pid, _ = grupo
    return S.reservar(eng, pid, cid, por_agente="operacao:teste", base_url="https://api.raiz.example/v1")


def _token(res):
    return res["aprovacao_url"].rsplit("/", 1)[1]


@pytest.mark.banco
def test_agente_prepara_sem_pix_sem_envio_e_repete_link_cifrado(eng, grupo, chaves, monkeypatch):
    monkeypatch.setattr(pix, "criar", lambda *a, **kw: pytest.fail("agente não gera Pix"))
    monkeypatch.setattr(S, "ENVIO_CONFIRMACAO", lambda *a: pytest.fail("worker não envia mensagem"))
    monkeypatch.setitem(S.ENVIADORES, "email", lambda *a: pytest.fail("worker não envia email"))
    res = _preparar(eng, grupo)
    assert res["aguardando_confirmacao"] and res["pix"] is None and not res["pago"]
    assert res["recibo_aprovacao"] is None
    assert res["exclusividade"] == {"dias": 60, "inicio": "apos_pagamento_confirmado"}
    assert dt.datetime.fromisoformat(res["preco_valido_ate"]) > dt.datetime.now(dt.UTC) + dt.timedelta(hours=47)
    assert res["aprovacao_url"].startswith("https://api.raiz.example/v1/reservas/confirmar/")
    assert _preparar(eng, grupo)["aprovacao_url"] == res["aprovacao_url"]
    with eng.connect() as con:
        guardado = con.execute(text("select * from negocio.reserva where pedido_id=:p"), {"p": grupo[1]}).one()
        assert chaves.decifrar(guardado.confirmacao_token_cifrado) == _token(res)
        assert _token(res).encode() not in guardado.confirmacao_token_cifrado
        assert (
            con.execute(text("select count(*) from negocio.cobranca where reserva_id=:r"), {"r": guardado.id}).scalar()
            == 0
        )
        notas = (
            con.execute(text("select texto from negocio.notificacao where pedido_id=:p"), {"p": grupo[1]})
            .scalars()
            .all()
        )
        assert all(_token(res) not in t for t in notas)


@pytest.mark.banco
def test_somente_mesma_empresa_aprova_e_recebe_qr_recibo_sem_pagar(eng, grupo):
    res = _preparar(eng, grupo)
    resumo = aprovacao.ver(eng, _token(res), grupo[0])
    assert resumo["valor_brl"] == res["valor_brl"] and resumo["estado"] == "aguardando_confirmacao"
    assert resumo["pagamento_confirmado"] is False and "pix" not in resumo
    with pytest.raises(aprovacao.ErroAprovacao):
        aprovacao.ver(eng, _token(res), grupo[0] + 100000)
    with pytest.raises(aprovacao.ErroAprovacao) as erro:
        aprovacao.aprovar(eng, _token(res), grupo[0] + 100000)
    assert erro.value.status == 410
    aprovada = aprovacao.aprovar(eng, _token(res), grupo[0])
    assert aprovada["estado"] == "aguardando_pagamento" and not aprovada["pago"]
    assert aprovada["pix"]["qr_svg"].lstrip().startswith("<?xml")
    assert "<svg" in aprovada["pix"]["qr_svg"]
    assert dt.datetime.fromisoformat(aprovada["pix"]["expira_em"]) <= dt.datetime.fromisoformat(res["preco_valido_ate"])
    mandato = recibos.verificar(aprovada["recibo_aprovacao"], recibos.jwk())
    assert mandato["empresa"] == grupo[0] and mandato["pedido"] == grupo[1]
    assert mandato["pagamento_confirmado"] is False and mandato["currency"] == "BRL"
    assert mandato["condicoes"]["agente_pode_pagar"] is False
    assert mandato["exclusividade"]["inicio"] == "apos_pagamento_confirmado"
    assert aprovada["aprovacao_url"] is None
    with pytest.raises(aprovacao.ErroAprovacao):
        aprovacao.aprovar(eng, _token(res), grupo[0])
    with eng.connect() as con:
        assert (
            con.execute(
                text("""select count(*) from negocio.cobranca c join negocio.reserva r on r.id=c.reserva_id
            where r.pedido_id=:p"""),
                {"p": grupo[1]},
            ).scalar()
            == 1
        )
        assert not con.execute(
            text("""select bool_or(f.ativa) from negocio.reserva_fazenda f join negocio.reserva r
            on r.id=f.reserva_id where r.pedido_id=:p"""),
            {"p": grupo[1]},
        ).scalar()
        assert (
            con.execute(
                text("select confirmacao_token_cifrado from negocio.reserva where pedido_id=:p"), {"p": grupo[1]}
            ).scalar()
            is None
        )


@pytest.mark.banco
def test_sem_assinante_nao_aprova_nem_chama_provedor(eng, grupo, monkeypatch):
    res = _preparar(eng, grupo)
    monkeypatch.delenv("RAIZ_RECIBO_CHAVE")
    monkeypatch.setattr(pix, "criar", lambda *a, **kw: pytest.fail("sem assinatura não gera Pix"))
    with pytest.raises(aprovacao.ErroAprovacao) as erro:
        aprovacao.aprovar(eng, _token(res), grupo[0])
    assert erro.value.status == 503
    assert S.cobranca_do_pedido(eng, grupo[1], grupo[0])["aguardando_confirmacao"]


@pytest.mark.banco
def test_aprovacoes_concorrentes_geram_uma_cobranca(eng, grupo, monkeypatch):
    res = _preparar(eng, grupo)
    chamadas = []
    original = pix.criar

    def criar(*args, **kwargs):
        chamadas.append(kwargs["chave_idempotencia"])
        return original(*args, **kwargs)

    def executar():
        try:
            aprovacao.aprovar(eng, _token(res), grupo[0])
            return 200
        except aprovacao.ErroAprovacao as ex:
            return ex.status

    monkeypatch.setattr(pix, "criar", criar)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(executar) for _ in range(2)]
        assert sorted(f.result(timeout=5) for f in futuros) == [200, 410]
    assert len(chamadas) == 1


@pytest.mark.banco
def test_evidencia_ausente_bloqueia_preparo_e_evidencia_revogada_bloqueia_aprovacao(eng, grupo, monkeypatch):
    cid, pid, cod = grupo
    res = _preparar(eng, grupo)
    with eng.begin() as con:
        con.execute(text("delete from negocio.salvaguarda where cod_imovel=:c"), {"c": cod})
    monkeypatch.setattr(pix, "criar", lambda *a, **kw: pytest.fail("salvaguarda pendente não gera Pix"))
    with pytest.raises(SG.ErroSalvaguarda):
        S.reservar(eng, pid, cid, por_agente="mcp")
    with pytest.raises(SG.ErroSalvaguarda):
        aprovacao.aprovar(eng, _token(res), cid)


@pytest.mark.banco
def test_token_e_preco_vencidos_nao_aprovam(eng, grupo):
    res = _preparar(eng, grupo)
    with eng.begin() as con:
        con.execute(
            text("update negocio.reserva set preco_valido_ate=now()-interval '1 second' where pedido_id=:p"),
            {"p": grupo[1]},
        )
    with pytest.raises(aprovacao.ErroAprovacao) as erro:
        aprovacao.aprovar(eng, _token(res), grupo[0])
    assert erro.value.status == 410


@pytest.mark.banco
def test_falha_provedor_preserva_aprovacao_pendente(eng, grupo, monkeypatch):
    res = _preparar(eng, grupo)

    def falhar(*a, **kw):
        raise TimeoutError("sem resposta do provedor")

    monkeypatch.setattr(pix, "criar", falhar)
    with pytest.raises(TimeoutError):
        aprovacao.aprovar(eng, _token(res), grupo[0])
    pendente = S.cobranca_do_pedido(eng, grupo[1], grupo[0])
    assert pendente["recibo_aprovacao"] is None and pendente["aguardando_confirmacao"]


def test_qr_local_nao_embute_texto_ou_script():
    svg = pix.qr_svg('<script>alert("x")</script>')
    assert "<svg" in svg and "<script" not in svg and 'alert("x")' not in svg


def test_pix_idempotencia_so_quando_suporte_declarado_e_timeout(monkeypatch):
    chamadas = []

    class Resposta:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"id": "teste-provedor", "brCode": "codigo", "devMode": True}}

    class Cliente:
        def __init__(self, **kw):
            assert kw["timeout"] == 3.0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def post(self, url, **kw):
            chamadas.append(kw)
            return Resposta()

    monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "teste")
    monkeypatch.setenv("RAIZ_PIX_MODO", "producao")
    monkeypatch.delenv("RAIZ_ABACATEPAY_IDEMPOTENCIA_SUPORTADA", raising=False)
    monkeypatch.setattr("httpx.Client", Cliente)
    pix.criar(1, "reserva", 120, chave_idempotencia="reserva:1")
    assert "Idempotency-Key" not in chamadas[-1]["headers"]
    monkeypatch.setenv("RAIZ_ABACATEPAY_IDEMPOTENCIA_SUPORTADA", "1")
    pix.criar(1, "reserva", 120, chave_idempotencia="reserva:1")
    assert chamadas[-1]["headers"]["Idempotency-Key"] == "reserva:1"
