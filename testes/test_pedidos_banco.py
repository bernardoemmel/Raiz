"""Pedido de lote com o banco (docs/cena-alvo.md): entrar sem senha, pedido salvo com a base e as 3 opções, troca
de fazenda, busca de interesse em ondas (quem recusa é trocado e o grupo fecha a meta de novo), grupo pronto com
aviso, reserva com Pix de teste, exclusividade (a fazenda reservada some para os outros clientes e volta quando a
reserva vence), contrato, vigia e aprendizado da chance de aceite. Nada pessoal do dono sai pela API."""

import base64
import datetime as dt
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz import salvaguardas as SG
from raiz.carga import carregar_pasta
from raiz.pedidos import servico as S
from raiz.pessoal import gerar_chave
from raiz.publica import conta as CT
from raiz.publica import recibos
from testes.conftest import AMOSTRA

pytestmark = pytest.mark.banco
TOKEN = "token-interno-de-teste"
TODA_TERRA = ["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]
CAMPOS = {"meta": {"tipo": "creditos", "valor": 400_000}, "onde": {"ufs": ["PA"], "biomas": ["Amazônia"]},
          "terra": TODA_TERRA}  # fmt: skip
PESSOAL = ("cpf", "cnpj", "telefone", "nome_dono", "email")


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as c:
        c.execute(text("truncate funil.rodada, funil.imovel, negocio.oferta, negocio.cliente cascade"))
        c.execute(text("truncate negocio.interesse_dono, negocio.interesse_evento"))
    carregar_pasta(e, AMOSTRA, dt.date(2026, 11, 12))  # a carga já refaz a oferta do município
    # A amostra CSV não contém geometria nem documentos. Apenas neste cenário feliz,
    # polígonos e evidências sintéticos tornam explícita a revisão prévia à reserva.
    hoje = dt.datetime.now(dt.UTC).date()
    ev = SG.Evidencia(sha256="c" * 64, data=hoje)
    SG.registrar_cobertura(e, SG.Cobertura(uf="PA", evidencia=ev, valida_ate=hoje))
    verificacao = SG.Verificacao(verificacao=ev, territorio_tradicional=False)
    with e.begin() as c:
        c.execute(
            text("""update funil.imovel set geom = ST_Multi(ST_GeomFromText(
            'POLYGON((-47 -1,-46.99 -1,-46.99 -0.99,-47 -0.99,-47 -1))', 4674))
            where geom is null""")
        )
        c.execute(
            text("""insert into negocio.salvaguarda (cod_imovel, evidencia)
            select cod_imovel, cast(:e as jsonb) from funil.imovel"""),
            {"e": verificacao.model_dump_json()},
        )
    yield e
    e.dispose()


@pytest.fixture(scope="module")
def chave():
    import raiz.pessoal as P

    k = gerar_chave()
    mp = pytest.MonkeyPatch()
    mp.setattr(P, "config", lambda: type("C", (), {"chave_pessoal": SecretStr(k)})())
    mp.setenv("RAIZ_RECIBO_CHAVE", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
    mp.delenv("RAIZ_ABACATEPAY_CHAVE", raising=False)
    yield k
    mp.undo()


def _sem_pessoal(obj) -> None:
    txt = str(obj).lower()
    for k in PESSOAL:
        assert f"'{k}'" not in txt, k


def test_carga_monta_a_oferta(eng):
    with eng.connect() as c:
        n, eleg = c.execute(text("""select count(*), count(*) filter (where (atributos->>'elegivel')::boolean)
                                    from negocio.oferta""")).one()  # fmt: skip
    assert n == 880 and eleg > 700


def test_contornos_do_lote_exigem_desbloqueio_atual_sem_nova_cobranca(eng):
    cliente = S.criar_cliente(eng, "Consulta do mapa")[0]
    outro = S.criar_cliente(eng, "Outra consulta do mapa")[0]
    with eng.connect() as con:
        codigos = list(con.execute(text("select cod_imovel from funil.vigente order by cod_imovel limit 3")).scalars())
        con.execute(
            text("""update funil.imovel set geom = ST_Multi(ST_GeomFromText(
                'POLYGON((-50 -6,-49.99 -6,-49.99 -5.99,-50 -5.99,-50 -6))',4674))
                where cod_imovel = any(:codigos)"""),
            {"codigos": codigos},
        )
        assert S._contornos_desbloqueados(con, cliente, codigos) == {}
        con.execute(
            text("insert into negocio.prospeccao_desbloqueio(cliente_id,cod_imovel) values (:cliente,:cod)"),
            [{"cliente": cliente, "cod": cod} for cod in codigos[:2]],
        )
        assert set(S._contornos_desbloqueados(con, cliente, codigos)) == set(codigos[:2])
        assert set(S._contornos_desbloqueados(con, cliente, [codigos[0]])) == {codigos[0]}
        assert S._contornos_desbloqueados(con, outro, codigos) == {}
        pedido = str(uuid.uuid4())
        con.execute(
            text("insert into negocio.pedido(id,cliente_id,campos) values (:id,:cliente,'{}')"),
            {"id": pedido, "cliente": outro},
        )
        reserva = con.execute(
            text("""insert into negocio.reserva(pedido_id,cliente_id,estado,ha,valor_rs,dias)
                values (:pedido,:cliente,'ativa',10,1,30) returning id"""),
            {"pedido": pedido, "cliente": outro},
        ).scalar_one()
        con.execute(
            text("insert into negocio.reserva_fazenda(reserva_id,cod_imovel,ativa) values (:id,:cod,true)"),
            {"id": reserva, "cod": codigos[0]},
        )
        desenhos = S._contornos_desbloqueados(con, cliente, codigos)
        assert set(desenhos) == {codigos[1]}
        assert desenhos[codigos[1]]["type"] == "MultiPolygon"
        assert "properties" not in desenhos[codigos[1]]
        assert (
            con.execute(
                text("select count(*) from negocio.prospeccao_movimento where cliente_id=:id"), {"id": cliente}
            ).scalar_one()
            == 0
        )
        con.execute(text("update negocio.cliente set ativo=false where id=:id"), {"id": cliente})
        assert S._contornos_desbloqueados(con, cliente, codigos) == {}
        # Desfaz dados geográficos/autorização de teste ao fechar a conexão.


def test_sugestao_antiga_nao_carrega_geometria_sem_revalidar_autorizacao():
    opcoes = [{"id": "barata", "itens": [{"cod_imovel": "CAR-teste", "geometria": {"type": "Polygon"}}]}]
    assert "geometria" not in S._limpar_opcoes(opcoes, {}, set())[0]["itens"][0]


def test_itens_do_pedido_so_revelam_detalhes_dos_cars_liberados_pelo_proprio_cliente(eng):
    clientes = [S.criar_cliente(eng, "Consulta paga do lote")[0], S.criar_cliente(eng, "Outro lote")[0]]
    pedidos = [str(uuid.uuid4()), str(uuid.uuid4())]
    with eng.begin() as con:
        codigos = list(con.execute(text("select cod_imovel from funil.vigente order by cod_imovel limit 2")).scalars())
        # A autorização da ficha independe de existir um desenho no banco.
        con.execute(text("update funil.imovel set geom=null where cod_imovel=any(:cods)"), {"cods": codigos})
        itens = [{"cod_imovel": cod, "cod_ibge": "1504950", "municipio": "Pacajá", "uf": "PA", "papel": papel,
                  "hectares": 12, "creditos": {"p10": 100, "p50": 200, "p90": 300, "nome_dono": "não publicar"},
                  "metodo": "regeneracao", "caminho": "matricula_a_conferir", "custo_usd_credito": 5,
                  "risco_terra": "medio", "pequena": True, "interesse": "contatado", "lon": -50, "lat": -6,
                  "nome_dono": "não publicar", "cpf": "não publicar", "telefone": "não publicar",
                  "detalhe_novo": {"email": "não publicar"}, "geometria": {"type": "Polygon"}}
                 for cod, papel in zip(codigos, ("lote", "reserva"), strict=True)]  # fmt: skip
        opcoes = [{"id": opcao, "creditos": {"p10": 100, "p50": 200, "p90": 300}, "hectares": 12,
                   "fazendas": 1, "itens": itens} for opcao in ("barata", "segura", "compacta")]  # fmt: skip
        base = {"fazendas": 2, "hectares": 24, "creditos": {"p10": 200, "p50": 400, "p90": 600}}
        for cliente, pedido in zip(clientes, pedidos, strict=True):
            con.execute(text("insert into negocio.pedido(id,cliente_id,campos) values (:id,:c,'{}')"),
                        {"id": pedido, "c": cliente})  # fmt: skip
            S._salvar_sugestao(con, pedido, "criado", base, opcoes)
    premium = ("creditos", "hectares", "metodo", "caminho", "custo_usd_credito", "risco_terra")
    gratuito = S.obter_pedido(eng, pedidos[0], clientes[0])
    assert gratuito["base"] == base and len(gratuito["opcoes"]) == 3
    for opcao in gratuito["opcoes"]:
        assert {k: v for k, v in opcao.items() if k != "itens"} == {
            k: v for k, v in opcoes[0].items() if k not in ("itens", "id")
        } | {"id": opcao["id"]}
        for item in opcao["itens"]:
            assert not item["ficha_liberada"] and all(item[campo] is None for campo in premium)
            assert item["pequena"] and item["papel"] in ("lote", "reserva")
            assert item["interesse"] == "sem_contato" and "geometria" not in item
    _sem_pessoal(gratuito)
    with eng.begin() as con:
        con.execute(text("insert into negocio.prospeccao_desbloqueio(cliente_id,cod_imovel) values (:c,:cod)"),
                    [{"c": c, "cod": cod} for c, cod in zip(clientes, codigos, strict=True)])  # fmt: skip
    for cliente, pedido, autorizado in zip(clientes, pedidos, codigos, strict=True):
        resposta = S.obter_pedido(eng, pedido, cliente)
        for opcao in resposta["opcoes"]:
            for item in opcao["itens"]:
                assert item["ficha_liberada"] == (item["cod_imovel"] == autorizado)
                if item["ficha_liberada"]:
                    assert item["creditos"] == {"p10": 100, "p50": 200, "p90": 300}
                    assert item["hectares"] == 12 and item["custo_usd_credito"] == 5
                    assert item["caminho"] == "matricula_a_conferir" and item["risco_terra"] == "medio"
                else:
                    assert all(item[campo] is None for campo in premium)
                assert "geometria" not in item and "detalhe_novo" not in item
        _sem_pessoal(resposta)
    with eng.connect() as con:
        assert S._ultima_sugestao(con, pedidos[0])["opcoes"] == opcoes  # cálculo/persistência intactos
        assert con.execute(text("select count(*) from negocio.prospeccao_movimento where cliente_id=any(:cs)"),
                           {"cs": clientes}).scalar_one() == 0  # sem débito implícito  # fmt: skip
    with eng.begin() as con:
        con.execute(text("delete from negocio.prospeccao_desbloqueio where cliente_id=:c"), {"c": clientes[0]})
    assert not any(
        i["ficha_liberada"] for o in S.obter_pedido(eng, pedidos[0], clientes[0])["opcoes"] for i in o["itens"]
    )


def test_andamento_revalida_fichas_por_cliente_sem_alterar_agregados_ou_cobrar(eng):
    clientes = [S.criar_cliente(eng, "Andamento do lote")[0], S.criar_cliente(eng, "Outro andamento")[0]]
    pedidos = [str(uuid.uuid4()), str(uuid.uuid4())]
    with eng.begin() as con:
        codigos = list(con.execute(text("""select cod_imovel from negocio.oferta
            where (atributos->>'elegivel')::boolean and (atributos->>'credito_p50')::float > 0
            order by cod_imovel limit 2""")).scalars())  # fmt: skip
        for cliente, pedido in zip(clientes, pedidos, strict=True):
            con.execute(
                text("insert into negocio.pedido(id,cliente_id,campos) values (:id,:c,cast(:campos as jsonb))"),
                {"id": pedido, "c": cliente, "campos": S.CamposPedido.model_validate(CAMPOS).model_dump_json()},
            )
            con.execute(
                text("""insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel,ordem)
                    values (:p,:cod,:papel,:ordem)"""),
                [
                    {"p": pedido, "cod": cod, "papel": "lote" if k == 0 else "reserva", "ordem": k}
                    for k, cod in enumerate(codigos)
                ],  # fmt: skip
            )

    premium = ("creditos", "hectares", "metodo", "caminho", "custo_usd_credito", "risco_terra")
    inicial = S.andamento(eng, pedidos[0], clientes[0])
    assert {item["cod_imovel"] for item in inicial["fazendas"]} == set(codigos)
    assert all(not item["ficha_liberada"] for item in inicial["fazendas"])
    assert all(item[campo] is None for item in inicial["fazendas"] for campo in premium)

    with eng.begin() as con:
        con.execute(
            text("insert into negocio.prospeccao_desbloqueio(cliente_id,cod_imovel) values (:c,:cod)"),
            [{"c": cliente, "cod": cod} for cliente, cod in zip(clientes, codigos, strict=True)],
        )
    for cliente, pedido, autorizado in zip(clientes, pedidos, codigos, strict=True):
        atual = S.andamento(eng, pedido, cliente)
        assert {k: v for k, v in atual.items() if k not in ("fazendas", "pedido")} == {
            k: v for k, v in inicial.items() if k not in ("fazendas", "pedido")
        }
        for item in atual["fazendas"]:
            assert item["ficha_liberada"] == (item["cod_imovel"] == autorizado)
            if item["ficha_liberada"]:
                assert item["creditos"]["p50"] > 0 and item["hectares"] > 0
            else:
                assert all(item[campo] is None for campo in premium)
            assert "geometria" not in item
        _sem_pessoal(atual)

    with eng.begin() as con:
        con.execute(text("delete from negocio.prospeccao_desbloqueio where cliente_id=:c"), {"c": clientes[0]})
    assert S.andamento(eng, pedidos[0], clientes[0]) == inicial
    with eng.connect() as con:
        for tabela in ("prospeccao_movimento", "lancamento_api"):
            assert con.execute(text(f"select count(*) from negocio.{tabela} where cliente_id=any(:cs)"),
                               {"cs": clientes}).scalar_one() == 0  # fmt: skip


def test_fluxo_completo_com_ondas_reserva_e_exclusividade(eng, chave):
    # cliente A entra sem senha, pelo link do e-mail
    enviados = []
    S.ENVIO_LINK = lambda email, link: enviados.append((email, link))
    try:
        tok = S.pedir_link(eng, "Compras@Frigorifico.example")
    finally:
        S.ENVIO_LINK = None
    assert enviados and enviados[0][0] == "compras@frigorifico.example" and tok in enviados[0][1]
    sess = S.confirmar_link(eng, tok)
    assert sess["email"] == "compras@frigorifico.example"
    with pytest.raises(S.ErroPedido):
        S.confirmar_link(eng, tok)  # link de uso único
    a = S.cliente_da_sessao(eng, sess["token"])
    with eng.connect() as c:  # o e-mail fica só cifrado, no esquema pessoal
        bruto = c.execute(text("select email_cifrado from pessoal.cliente_contato where cliente_id = :c"),
                          {"c": a}).scalar()  # fmt: skip
    assert b"frigorifico" not in bytes(bruto)

    p = S.criar_pedido(eng, a, CAMPOS)
    assert p["status"] == "lote_montado" and p["base"]["alcanca_meta"] and len(p["opcoes"]) == 3
    assert p["versao_modelo"].startswith("pedidos-2026a+")
    _sem_pessoal(p)
    seg = next(o for o in p["opcoes"] if o["id"] == "segura")
    assert seg["alcanca_meta"] and seg["creditos"]["p50"] >= 400_000

    # trocar uma fazenda do lote por uma de reserva (refaz os números)
    sai = next(i for i in seg["itens"] if i["papel"] == "lote")["cod_imovel"]
    p2 = S.mudar_lote(eng, p["id"], a, {"opcao": "segura", "acao": "trocar", "cod_imovel": sai})
    seg2 = next(o for o in p2["opcoes"] if o["id"] == "segura")
    lote2 = [i for i in seg2["itens"] if i["papel"] == "lote"]
    assert sai not in {i["cod_imovel"] for i in lote2} and any(i["trocou"] == sai for i in lote2)
    with pytest.raises(S.ErroPedido):  # outro cliente não vê o pedido
        b0, _ = S.criar_cliente(eng, "Outro"), None
        S.obter_pedido(eng, p["id"], b0[0])

    # busca de interesse em ondas: a 1ª contata bem mais fazendas do que a meta pede
    S.solicitar_interesse(eng, p["id"], a, "segura")
    an = S.andamento(eng, p["id"], a)
    assert an["status"] == "buscando_interesse" and len(an["ondas"]) == 1
    contatados1 = S.contatados_do_pedido(eng, p["id"])
    meta_fazendas = len([i for i in seg2["itens"] if i["papel"] == "lote"])
    assert len(contatados1) > 2 * meta_fazendas
    with eng.connect() as c:  # a chance de aceite de cada contatada ficou congelada, com a versão do modelo
        n_prev = c.execute(text("select count(*) from aprendizado.previsao where alvo = 'aceite_dono'")).scalar()
    assert n_prev == len(contatados1)

    # os 10 primeiros recusam; os demais não respondem no prazo: vem a 2ª onda com fazendas novas
    for cod in contatados1[:10]:
        S.registrar_resposta(eng, cod, "recusou", "whatsapp", "não quer mudar o uso da terra", None, p["id"],
                             avancar_pedidos=False)  # fmt: skip
    depois = dt.datetime.now(dt.UTC) + dt.timedelta(days=16)
    assert S.avancar(eng, p["id"], depois) == "buscando_interesse"
    contatados2 = S.contatados_do_pedido(eng, p["id"])
    novos = [c for c in contatados2 if c not in contatados1]
    assert novos and len(S.andamento(eng, p["id"], a)["ondas"]) == 2
    # os novos se interessam (com a versão do termo) e o grupo fecha a meta sem quem recusou
    for cod in novos:
        S.registrar_resposta(eng, cod, "interessado", "whatsapp", None, "termo-lgpd-2026a", p["id"],
                             avancar_pedidos=False)  # fmt: skip
    estado = S.avancar(eng, p["id"])
    an = S.andamento(eng, p["id"], a)
    if estado != "grupo_pronto":  # se ainda faltar, mais ondas até fechar
        for _ in range(8):
            for cod in [c for c in S.contatados_do_pedido(eng, p["id"]) if c not in contatados2]:
                S.registrar_resposta(eng, cod, "interessado", "carta", None, "termo-lgpd-2026a", p["id"],
                                     avancar_pedidos=False)  # fmt: skip
            contatados2 = S.contatados_do_pedido(eng, p["id"])
            estado = S.avancar(eng, p["id"])
            if estado == "grupo_pronto":
                break
        an = S.andamento(eng, p["id"], a)
    assert estado == "grupo_pronto" and an["status"] == "grupo_pronto" and an["grupo_pronto_em"]
    assert an["com_interessado"] >= 400_000 and an["recusas"] == 10 and an["sem_resposta"] > 0
    assert {"motivo": "não quer mudar o uso da terra", "fazendas": 10} in an["motivos"]
    grupo = [f for f in an["fazendas"] if f["papel"] == "lote"]
    assert grupo and not {f["cod_imovel"] for f in grupo} & set(contatados1[:10])
    assert all(f["interesse"] in ("interessado", "aceite_fase1", "contrato_firme") for f in grupo)
    assert any(f["trocou"] for f in grupo)  # quem entrou no lugar de quem recusou ou não respondeu
    _sem_pessoal(an)
    with eng.connect() as c:  # grupo pronto avisa o cliente no painel, por e-mail e por WhatsApp
        canais = {r[0] for r in c.execute(text("""select canal from negocio.notificacao where pedido_id = :p
                                                 and tipo = 'grupo_pronto'"""), {"p": p["id"]})}  # fmt: skip
    assert canais == {"painel", "email", "whatsapp"}
    # o nível só sobe: quem está interessado não volta para contatado; sem termo não sobe
    with pytest.raises(S.ErroPedido):
        S.registrar_resposta(eng, grupo[0]["cod_imovel"], "contatado", "carta")
    with pytest.raises(S.ErroPedido):
        S.registrar_resposta(eng, grupo[0]["cod_imovel"], "aceite_fase1", "carta")

    # reserva com Pix de teste; paga, as fazendas somem para o cliente B
    cob = S.reservar(eng, p["id"], a)
    assert cob["modo_teste"] and cob["pix"]["copia_e_cola"].startswith("RAIZ-TESTE-PIX") and not cob["pago"]
    assert cob["valor_brl"] >= 500 and cob["prazo_dias"] == 60 and "abatida" in cob["abatimento"]
    assert "<svg" in cob["pix"]["qr_svg"] and cob["pix"]["expira_em"]
    mandato = recibos.verificar(cob["recibo_aprovacao"], recibos.jwk())
    assert mandato["empresa"] == a and mandato["pedido"] == p["id"]
    assert mandato["pagamento_confirmado"] is False and mandato["condicoes"]["agente_pode_pagar"] is False
    b, _ = S.criar_cliente(eng, "Fundo B")
    antes_b = S.criar_pedido(eng, b, CAMPOS)
    with eng.connect() as c:
        ext = c.execute(text("""select c.externo_id from negocio.cobranca c join negocio.reserva r
                                on r.id = c.reserva_id where r.pedido_id = :p"""), {"p": p["id"]}).scalar()  # fmt: skip
    assert S.confirmar_pagamento(eng, ext) == "ativa"
    assert S.confirmar_pagamento(eng, ext) == "ja_paga"
    pa = S.obter_pedido(eng, p["id"], a)
    assert pa["status"] == "reservado" and pa["reservado_ate"]
    reservadas = {f["cod_imovel"] for f in grupo}
    pb = S.criar_pedido(eng, b, CAMPOS)
    itens_b = {i["cod_imovel"] for o in pb["opcoes"] for i in o["itens"]}
    assert not itens_b & reservadas
    assert pb["base"]["fazendas"] == antes_b["base"]["fazendas"] - len(reservadas)
    velho_b = S.obter_pedido(eng, antes_b["id"], b)  # pedido antigo de B também esconde as reservadas
    assert not {i["cod_imovel"] for o in velho_b["opcoes"] for i in o["itens"]} & reservadas
    # nunca em duas reservas ao mesmo tempo
    with eng.begin() as c, pytest.raises(Exception):  # noqa: B017 - índice único parcial do banco
        rid = c.execute(text("""insert into negocio.reserva (pedido_id, cliente_id, estado, ha, valor_rs, dias)
                                values (:p, :c, 'ativa', 1, 1, 60) returning id"""),
                        {"p": antes_b["id"], "c": b}).scalar()  # fmt: skip
        c.execute(text("insert into negocio.reserva_fazenda (reserva_id, cod_imovel, ativa) values (:r, :c, true)"),
                  {"r": rid, "c": next(iter(reservadas))})  # fmt: skip

    # vence o prazo sem contrato: o grupo volta para a base
    assert S.expirar_reservas(eng, dt.datetime.now(dt.UTC) + dt.timedelta(days=61)) == 1
    assert S.obter_pedido(eng, p["id"], a)["status"] == "reserva_vencida"
    pb2 = S.criar_pedido(eng, b, CAMPOS)
    assert pb2["base"]["fazendas"] == antes_b["base"]["fazendas"]
    with eng.connect() as c:
        ev = [r[0] for r in c.execute(text("""select e.evento from negocio.reserva_evento e join negocio.reserva r
                                              on r.id = e.reserva_id where r.pedido_id = :p order by e.id"""),
                                      {"p": p["id"]})]  # fmt: skip
    assert ev == ["criada", "confirmada", "paga", "expirada"]


def test_contrato_abate_a_reserva_e_pedido_impossivel(eng, chave):
    c, _ = S.criar_cliente(eng, "Desenvolvedor C")
    p = S.criar_pedido(eng, c, {**CAMPOS, "meta": {"tipo": "creditos", "valor": 100_000}})
    S.solicitar_interesse(eng, p["id"], c, "barata")
    for cod in S.contatados_do_pedido(eng, p["id"]):
        S.registrar_resposta(eng, cod, "interessado", "visita", None, "termo-lgpd-2026a", p["id"],
                             avancar_pedidos=False)  # fmt: skip
    assert S.avancar(eng, p["id"]) == "grupo_pronto"
    S.reservar(eng, p["id"], c)
    with eng.connect() as con:
        ext, rid = con.execute(
            text("""select co.externo_id, r.id from negocio.cobranca co join negocio.reserva r
                    on r.id = co.reserva_id where r.pedido_id = :p"""),
            {"p": p["id"]},
        ).one()
    S.confirmar_pagamento(eng, ext)
    out = S.converter_reserva(eng, rid, ha_assinados=1000)
    assert out["conexao_rs"] == 30000 and out["abatido_rs"] > 0 and out["a_pagar_rs"] == 30000 - out["abatido_rs"]
    assert S.obter_pedido(eng, p["id"], c)["status"] == "contrato"
    with eng.connect() as con:  # o aceite virou gabarito da chance de aceite congelada
        n = con.execute(text("select count(*) from aprendizado.gabarito where alvo = 'aceite_dono'")).scalar()
    assert n > 0
    # pedido impossível: a busca acaba e diz o que faltou
    d, _ = S.criar_cliente(eng, "Empresa D")
    imp = S.criar_pedido(eng, d, {**CAMPOS, "meta": {"tipo": "creditos", "valor": 50_000_000}})
    assert not imp["base"]["alcanca_meta"] and imp["base"]["falta"] > 0
    assert imp["base"]["afrouxar"][0]["campo"] == "base"  # aceita toda terra e o PA inteiro: falta base, não filtro
    S.solicitar_interesse(eng, imp["id"], d, "barata")
    for _ in range(15):
        for cod in S.contatados_do_pedido(eng, imp["id"]):
            try:
                S.registrar_resposta(eng, cod, "recusou", "carta", "sem interesse", None, imp["id"],
                                     avancar_pedidos=False)  # fmt: skip
            except S.ErroPedido:
                pass
        if S.avancar(eng, imp["id"]) == "faltou":
            break
    an = S.andamento(eng, imp["id"], d)
    assert an["status"] == "faltou" and an["faltou"]["falta"] > 0
    # recusa vale por um ano: depois a fazenda pode ser contatada de novo
    recusou = S.contatados_do_pedido(eng, imp["id"])[0]
    with eng.begin() as con:
        assert S.niveis(con, [recusou]) == {recusou: "recusou"}
        con.execute(text("update negocio.interesse_dono set atualizado_em = now() - interval '400 days' "
                         "where cod_imovel = :c"), {"c": recusou})  # fmt: skip
        assert S.niveis(con, [recusou]) == {recusou: "sem_contato"}


def test_vigia_avisa_lote_melhorou_e_fazenda_com_problema(eng, chave):
    with eng.begin() as con:  # o pedido impossível fez todo mundo recusar: começa limpo
        con.execute(text("truncate negocio.interesse_dono"))
    c, _ = S.criar_cliente(eng, "Cliente E")
    p = S.criar_pedido(eng, c, {**CAMPOS, "meta": {"tipo": "creditos", "valor": 200_000}})
    op = next(o for o in p["opcoes"] if o["id"] == "barata")
    cod = next(i["cod_imovel"] for i in op["itens"] if i["papel"] == "lote")
    with eng.begin() as con:  # embargo novo numa fazenda do lote
        con.execute(text("""update negocio.oferta set atributos = atributos || '{"embargo": true}'::jsonb
                            where cod_imovel = :c"""), {"c": cod})  # fmt: skip
        con.execute(text("""update negocio.oferta set atributos = jsonb_set(atributos, '{custo_credito_usd}',
                            to_jsonb(((atributos->>'custo_credito_usd')::float) * 0.5))
                            where atributos->>'custo_credito_usd' is not null"""))  # fmt: skip
    out = S.vigiar(eng)
    assert out["fazenda_com_problema"] >= 1 and out["lote_melhorou"] >= 1
    tipos = {x["tipo"] for x in S.obter_pedido(eng, p["id"], c)["alertas"]}
    assert tipos >= {"fazenda_com_problema", "lote_melhorou"}
    assert S.vigiar(eng)["fazenda_com_problema"] == 0  # não repete o mesmo alerta
    from raiz.pedidos.oferta import atualizar

    with eng.begin() as con:
        con.execute(text("delete from negocio.oferta"))
    assert atualizar(eng, 1504950) == 880  # a oferta se refaz do banco


def _canais(eng, pedido_id, tipo):
    with eng.connect() as con:
        return sorted(
            (r.canal, r.estado)
            for r in con.execute(
                text("select canal, estado from negocio.notificacao where pedido_id = :p and tipo = :t"),
                {"p": pedido_id, "t": tipo},
            )
        )


def test_vigia_guarda_vigilancia_so_no_painel_sem_repetir(eng, chave):
    from raiz.vigilancia.pedidos import Fato

    c, _ = S.criar_cliente(eng, "Cliente G")
    p = S.criar_pedido(eng, c, {**CAMPOS, "meta": {"tipo": "creditos", "valor": 150_000}})
    lote = [i["cod_imovel"] for i in next(o for o in p["opcoes"] if o["id"] == "barata")["itens"]
            if i["papel"] == "lote"]  # fmt: skip
    hoje = dt.date.today()
    fatos = [
        Fato(lote[0], "desmatamento", "vigilancia:t1", hoje, "Fazenda do grupo com derrubada: 3,0 ha.",
             {"fonte": "deter", "area_ha": 3.0}),
        Fato(lote[1], "embargo", "vigilancia:t2", hoje, "Fazenda do grupo com embargo novo do Ibama.",
             {"fonte": "ibama_embargo"}),
        Fato(lote[0], "matricula_cancelada", f"matricula:{lote[0]}:x", hoje,
             "Fazenda do grupo com matrícula encerrada ou cancelada.", {"fonte": "certidao"}),
    ]  # fmt: skip
    pedidos_e_datas = []

    def fatos_de(cods, desde):
        cods = set(cods)
        if lote[0] in cods:
            pedidos_e_datas.append(desde)
        return [f for f in fatos if f.cod_imovel in cods]

    S.vigiar(eng, fatos_de=fatos_de)
    assert pedidos_e_datas and all(d <= hoje for d in pedidos_e_datas)  # desde quando o pedido foi salvo
    al = [a for a in S.obter_pedido(eng, p["id"], c)["alertas"] if a["tipo"] == "fazenda_com_problema"]
    assert {(a["cod_imovel"], a["motivo"]) for a in al} == {
        (lote[0], "desmatamento"),
        (lote[1], "embargo"),
        (lote[0], "matricula_cancelada"),
    }
    assert next(a for a in al if a["motivo"] == "desmatamento")["detalhe"] == {"fonte": "deter", "area_ha": 3.0}
    _sem_pessoal(al)
    # lote ainda sem grupo: painel e e-mail (simulado)
    assert set(_canais(eng, p["id"], "fazenda_com_problema")) == {("painel", "enviada"), ("email", "simulada")}
    # o mesmo fato nunca volta, mesmo depois de visto
    with eng.begin() as con:
        con.execute(text("update negocio.alerta_pedido set visto_em = now() where pedido_id = :p"), {"p": p["id"]})
    S.vigiar(eng, fatos_de=fatos_de)
    assert len([a for a in S.obter_pedido(eng, p["id"], c)["alertas"] if a["tipo"] == "fazenda_com_problema"]) == 3
    # Mesmo no grupo em formação, vigilância não chama e-mail nem WhatsApp.
    S.solicitar_interesse(eng, p["id"], c, "barata")
    fatos.append(Fato(lote[1], "desmatamento", "vigilancia:t3", hoje, "Fazenda do grupo com derrubada: 1,0 ha.",
                      {"fonte": "mapbiomas_alerta"}))  # fmt: skip
    S.vigiar(eng, fatos_de=fatos_de)
    novos = [x for x in _canais(eng, p["id"], "fazenda_com_problema") if x[0] == "whatsapp"]
    assert novos == []


def test_vigia_le_a_vigilancia_e_as_certidoes(eng, chave, tmp_path, monkeypatch):
    """Sem trocar a fonte: o vigia lê o estado da vigilância (RAIZ_VIGILANCIA_DIR) e as certidões lidas
    (matricula_<mun>.csv em RAIZ_DOCUMENTOS_DIR)."""
    import json

    import pandas as pd

    from raiz.vigilancia.armazem import Armazem
    from raiz.vigilancia.cruzamento import COLUNAS_ALERTA, alerta_id

    c, _ = S.criar_cliente(eng, "Cliente H")
    p = S.criar_pedido(eng, c, {**CAMPOS, "meta": {"tipo": "creditos", "valor": 150_000}})
    lote = [i["cod_imovel"] for i in next(o for o in p["opcoes"] if o["id"] == "barata")["itens"]
            if i["papel"] == "lote"]  # fmt: skip
    hoje = dt.date.today()
    monkeypatch.setenv("RAIZ_VIGILANCIA_DIR", str(tmp_path / "vigilancia"))
    linha = dict.fromkeys(COLUNAS_ALERTA)
    linha.update(alerta_id=alerta_id("deter", "d9", "imovel", lote[0]), fonte="deter", chave="d9",
                 classe="desmatamento_cr", tipo="desmatamento", alvo_tipo="imovel", alvo_id=lote[0], uf="PA",
                 data_evento=hoje, publicado_em=hoje, visto_em=hoje, area_sobreposta_ha=2.5, borda=False,
                 gravidade="alta", estrato="deter_desmatamento", confianca=0.85, regra_versao="teste", novo=True,
                 atributos=json.dumps({}))  # fmt: skip
    Armazem(tmp_path / "vigilancia").gravar_alertas(pd.DataFrame([linha], columns=COLUNAS_ALERTA))
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "documentos"))
    pasta = tmp_path / "documentos" / "saida" / "PA"
    pasta.mkdir(parents=True)
    mun = lote[1].split("-")[1]
    cert = {"cod_imovel": [lote[1]], "matricula_situacao": ["cancelada"], "matricula_lido_em": ["2026-11-12T10:00"]}
    pd.DataFrame(cert).to_csv(pasta / f"matricula_{mun}.csv", index=False)
    S.vigiar(eng)
    al = {(a["cod_imovel"], a["motivo"]) for a in S.obter_pedido(eng, p["id"], c)["alertas"]}
    assert (lote[0], "desmatamento") in al and (lote[1], "matricula_cancelada") in al


def test_vigia_diz_quais_fazendas_novas_melhoram_o_lote(eng, chave):
    c, _ = S.criar_cliente(eng, "Cliente I")
    p = S.criar_pedido(eng, c, {**CAMPOS, "meta": {"tipo": "creditos", "valor": 100_000}})
    barata = next(o for o in p["opcoes"] if o["id"] == "barata")
    no_lote = {i["cod_imovel"] for i in barata["itens"]}
    with eng.begin() as con:  # fazendas de fora do lote ficam muito mais baratas (dado novo na oferta)
        fora = [r[0] for r in con.execute(text("""select cod_imovel from negocio.oferta
                 where (atributos->>'elegivel')::boolean and (atributos->>'credito_p50')::float > 5000
                 order by cod_imovel""")) if r[0] not in no_lote][:15]  # fmt: skip
        barato = """update negocio.oferta set atualizado_em = now(),
                    atributos = atributos || '{"custo_credito_usd": 0.01, "preco_equilibrio_usd": 0.01}'::jsonb
                    where cod_imovel = any(:c)"""
        con.execute(text(barato), {"c": fora})
    S.vigiar(eng)
    al = [a for a in S.obter_pedido(eng, p["id"], c)["alertas"] if a["tipo"] == "lote_melhorou"]
    assert al, "o lote devia melhorar com as fazendas mais baratas"
    novas = al[0]["detalhe"]["fazendas_novas"]
    assert novas and {n["cod_imovel"] for n in novas} <= set(fora)
    assert all(n["nova_na_base"] for n in novas) and "Fazendas novas no lote" in al[0]["texto"]
    from raiz.pedidos.oferta import atualizar

    with eng.begin() as con:
        con.execute(text("delete from negocio.oferta"))
    assert atualizar(eng, 1504950) == 880


def _abrir_conta_de_teste(eng, cliente_id):
    # Documento sintético: construído em teste, não armazenado em texto no repositório.
    cnpj = f"73{cliente_id:010d}"
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(x) * w for x, w in zip(cnpj, pesos, strict=True)) % 11
        cnpj += str(0 if resto < 2 else 11 - resto)
    CT.abrir(eng, cliente_id, cnpj, True)


def test_api_no_contrato_do_front(eng, chave, monkeypatch):
    from raiz.api import criar_app

    cfg = type("C", (), {"api_token": SecretStr(TOKEN), "api_origens": "http://localhost:5173"})()
    import raiz.api as api_mod

    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    monkeypatch.setenv("RAIZ_FRONT_URL", "https://painel.raiz.example")
    monkeypatch.setenv("RAIZ_API_PUBLICA_URL", "https://api.raiz.example")
    links = []
    monkeypatch.setattr(S, "ENVIO_LINK", lambda e, link: links.append(link))
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    with TestClient(app) as cl:
        assert cl.post("/entrar", json={"email": "analista@fundo.example"}).json() == {"enviado": True}
        tok = links[-1].rsplit("/", 1)[1]
        assert cl.post("/entrar/confirmar", json={"token": "errado"}).status_code == 401
        sess = cl.post("/entrar/confirmar", json={"token": tok}).json()
        h = {"Authorization": f"Bearer {sess['token']}"}
        assert cl.get("/pedidos").status_code == 401  # sem sessão
        # O caminho antigo preserva o contrato do front, mas não pode contornar a conta paga.
        recusado = cl.post("/pedidos", json=CAMPOS, headers=h)
        assert recusado.status_code == 403 and recusado.history[0].status_code == 307
        cliente_id = S.cliente_da_sessao(eng, sess["token"])
        _abrir_conta_de_teste(eng, cliente_id)
        CT.aceitar_contrato(eng, cliente_id)
        assert cl.post("/pedidos", json=CAMPOS, headers=h).status_code == 403  # ainda sem sinal
        with eng.begin() as con:
            con.execute(
                text("update negocio.conta_api set sinal_pago_em=now(), saldo_rs=5000 where cliente_id=:c"),
                {"c": cliente_id},
            )
        criado = cl.post("/pedidos", json=CAMPOS, headers=h)
        assert criado.status_code == 200, criado.text
        p = criado.json()
        assert CT.ver(eng, cliente_id)["saldo_rs"] == 4600  # uma cobrança, no destino /v1
        assert set(p) >= {"id", "criado_em", "campos", "status", "base", "opcoes", "opcao_escolhida", "reservado_ate",
                          "alertas", "versao_modelo"}  # fmt: skip
        assert set(p["base"]) >= {"fazendas", "hectares", "creditos", "por_caminho", "por_interesse", "alcanca_meta",
                                  "falta", "afrouxar"}  # fmt: skip
        o = p["opcoes"][0]
        assert set(o) >= {"id", "creditos", "hectares", "fazendas", "pequenas", "tir", "custo_usd_credito",
                          "pico_caixa_usd", "marcos", "multa_esperada_usd", "mistura_terra", "metodos", "itens",
                          "alcanca_meta", "falta"}  # fmt: skip
        campos_item = {"cod_imovel", "cod_ibge", "municipio", "uf", "papel", "hectares", "creditos", "metodo",
                       "caminho", "custo_usd_credito", "pequena", "interesse", "lon", "lat"}  # fmt: skip
        assert set(o["itens"][0]) >= campos_item
        assert not o["itens"][0]["ficha_liberada"]
        assert all(o["itens"][0][k] is None for k in ("creditos", "custo_usd_credito", "caminho", "risco_terra"))
        _sem_pessoal(p)
        lista = cl.get("/pedidos", headers=h).json()
        assert lista[0]["id"] == p["id"] and "créditos em PA" in lista[0]["titulo"]
        sai = next(i for i in o["itens"] if i["papel"] == "lote")["cod_imovel"]
        r = cl.post(f"/pedidos/{p['id']}/lote", json={"opcao": o["id"], "acao": "tirar", "cod_imovel": sai}, headers=h)
        assert r.status_code == 200
        assert sai not in {i["cod_imovel"] for i in r.json()["opcoes"][0]["itens"] if i["papel"] == "lote"}
        assert cl.patch(f"/pedidos/{p['id']}", json={"opcao": "barata", "acao": "tirar", "cod_imovel": "nao-existe"},
                        headers=h).status_code == 422  # fmt: skip
        r = cl.post(f"/pedidos/{p['id']}/solicitar-interesse", json={"opcao": "segura"}, headers=h)
        assert r.json()["status"] == "buscando_interesse" and r.json()["opcao_escolhida"] == "segura"
        an = cl.get(f"/pedidos/{p['id']}/andamento", headers=h).json()
        assert set(an) >= {"pedido", "status", "meta", "com_interessado", "com_aceite", "com_contrato", "ondas",
                           "contatados", "recusas", "sem_resposta", "motivos", "fazendas", "grupo_pronto_em",
                           "proxima_onda_em"}  # fmt: skip
        assert an["proxima_onda_em"] and an["ondas"][0]["canais"]
        cobranca = cl.get(f"/pedidos/{p['id']}/reserva", headers=h).json()
        assert cobranca["pix"] is None and cobranca["prazo_dias"] == 60
        assert cl.post(f"/pedidos/{p['id']}/reservar", headers=h).status_code == 422  # grupo ainda não pronto
        # resposta do dono pela rota interna (token da API)
        cod = an["fazendas"][0]["cod_imovel"]
        assert cl.post(f"/interesse/{cod}", json={"nivel": "interessado"}).status_code == 401
        hi = {"Authorization": f"Bearer {TOKEN}"}
        resp = {"nivel": "interessado", "canal": "whatsapp", "versao_termo": "termo-lgpd-2026a", "pedido_id": p["id"]}
        r = cl.post(f"/interesse/{cod}", json=resp, headers=hi)
        assert r.json() == {"cod_imovel": cod, "nivel": "interessado"}
        assert cl.post("/pedidos-vigiar", headers=hi).status_code == 200
        assert cl.post("/reservas/expirar", headers=hi).json() == {"expiradas": 0}
        # aviso de pagamento: sem o segredo, recusa
        assert cl.post("/pagamentos/abacatepay?webhookSecret=x", json={"event": "billing.paid"}).status_code == 401
        assert cl.get("/notificacoes", headers=h).status_code == 200
        assert cl.get(f"/pedidos/{p['id']}/alertas", headers=h).status_code == 200


def test_grade_sensibilidade_antiga_e_recusada_depois_de_troca_e_remocao(eng, tmp_path, monkeypatch):
    import json

    from raiz.pedidos import sensibilidade

    monkeypatch.setenv("RAIZ_SENSIBILIDADE_DIRETORIO", str(tmp_path))
    cliente = S.criar_cliente(eng, "Revisão de sensibilidade")[0]
    pedido = S.criar_pedido(eng, cliente, CAMPOS)
    parametros = sensibilidade.ParametrosSensibilidade(
        preco_credito_usd=55, reserva_reversao=0.2, taxa_desconto=0.092, pessimista=False
    )
    for acao in ("trocar", "tirar"):
        grade = {
            "pedido_id": pedido["id"],
            "modelo_versao": pedido["versao_modelo"],
            "revisao_lote": pedido["revisao_lote"],
            "atualizado_em": "2026-11-12T12:00:00Z",
            "fonte": "Fixture sintética de teste",
            "aviso": "Não usar em proposta.",
            "cenarios": [
                {
                    "parametros": parametros.model_dump(),
                    "opcoes": [
                        {
                            "id": id_,
                            "creditos": {"p10": 0, "p50": 0, "p90": 0},
                            "hectares": 0,
                            "fazendas": 0,
                            "vpl_usd": None,
                            "tir_projeto": None,
                            "alcanca_meta": False,
                        }
                        for id_ in ("barata", "segura", "compacta")
                    ],
                }
            ],
        }
        (tmp_path / f"{pedido['id']}.json").write_text(json.dumps(grade))
        assert sensibilidade.consultar(pedido, parametros)["estado"] == "disponivel"
        antiga = pedido
        opcao = next(o for o in pedido["opcoes"] if o["id"] == "segura")
        sai = next(i["cod_imovel"] for i in opcao["itens"] if i["papel"] == "lote")
        pedido = S.mudar_lote(eng, pedido["id"], cliente, {"opcao": "segura", "acao": acao, "cod_imovel": sai})
        assert pedido["id"] == antiga["id"] and pedido["versao_modelo"] == antiga["versao_modelo"]
        assert pedido["revisao_lote"] != antiga["revisao_lote"]
        resposta = sensibilidade.consultar(pedido, parametros)
        assert resposta["estado"] == "indisponivel" and resposta["opcoes"] == []
