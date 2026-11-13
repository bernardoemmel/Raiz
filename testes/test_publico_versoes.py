"""EPREL público: versão básica imutável, origem histórica e consentimento consultado ao vivo."""

import datetime as dt
import hashlib
import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from raiz import publico
from raiz import publico_versoes as v

CODIGO = "AB23CD"
CAR = "PA-1505536-00000000000000000000000000000001"


def test_lista_positiva_nunca_envia_coluna_nova_ao_cartao(tmp_path, monkeypatch):
    d = {
        "codigo": CODIGO,
        "municipio": "Parauapebas",
        "uf": "PA",
        "hectares": "120",
        "frase": "no CAR",
        "selo": "bronze",
        "aceito": False,
        "carbono_ha": 99,
        "tir": 18,
        "nome_dono": "SEGREDO",
        "cpf": "000.000.000-00",
        "_cod_imovel": CAR,
    }
    monkeypatch.setattr(publico, "pasta", lambda: tmp_path)
    assert set(publico._publico(d)) == {"codigo", "municipio", "uf", "hectares", "frase", "selo", "aceito"}
    assert "SEGREDO" not in publico._assinatura(d) and "carbono" not in publico._assinatura(d)
    for codigo, nome in (("../AB23CD", "previa.jpg"), (CODIGO, "../previa.jpg"), (CODIGO, "..\\previa.jpg")):
        with pytest.raises(ValueError, match="caminho"):
            publico._cache({**d, "codigo": codigo}, nome)
    assert list(tmp_path.iterdir()) == []
    assert not v.codigo_valido("AB23CK")  # alfabeto ASCII do código curto, sem homóglifos Unicode


@pytest.mark.parametrize(
    "problema,carbono,esperado",
    [
        (False, 20, "apto"),
        (True, 20, "com_pendencia"),
        (False, 0, "nao_apto"),
        (False, None, None),
        (False, float("nan"), None),
        (None, 20, None),
    ],
)
def test_situacao_basica_sem_detalhar_motivo_ou_confundir_ausencia(problema, carbono, esperado):
    r = dict.fromkeys(("embargo_ha", "ti_ha", "desm_pos2020_ha", "alerta_pos2020_ha"))
    r.update(problema=problema, carbono_ha=carbono, desm_pos2016_ha=0)
    assert v._situacao(r) == esperado


@pytest.fixture
def banco(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as con:
        con.execute(text("truncate negocio.codigo_curto, negocio.aceite, funil.rodada cascade"))
        con.execute(
            text("insert into negocio.codigo_curto(cod_imovel,codigo) values(:car,:codigo)"),
            {"car": CAR, "codigo": CODIGO},
        )
        con.execute(text("insert into negocio.aceite(cod_imovel,estado) values(:car,'aceito')"), {"car": CAR})
    yield eng
    eng.dispose()


def rodada(eng, corte="2026-01-10", municipio="Parauapebas", ha=123.5, problema=False, carbono=19.87):
    with eng.begin() as con:
        numero = con.execute(
            text("""insert into funil.rodada(tipo,uf,cod_municipio,origem,arquivos,
                hash_entradas,motor_versao,regras_versao,data_corte)
                values('municipio','PA',1505536,'teste','{}',gen_random_uuid()::text,'1','1',:data) returning id"""),
            {"data": corte},
        ).scalar_one()
        con.execute(
            text("""insert into funil.resultado_imovel(rodada_id,cod_imovel,cod_municipio_ibge,municipio,uf,ha,
                           problema,carbono_ha,desm_pos2016_ha,atributos)
                   values(:r,:car,1505536,:mun,'PA',:ha,:problema,:carbono,0,
                          cast(:atributos as jsonb))"""),
            {
                "r": numero,
                "car": CAR,
                "mun": municipio,
                "ha": ha,
                "problema": problema,
                "carbono": carbono,
                "atributos": json.dumps({"nome_dono": "SEGREDO", "tir": 99, "cpf": "000.000.000-00"}),
            },
        )
        con.execute(
            text("""insert into funil.vigente(cod_imovel,rodada_id,uf,cod_busca)
                           values(:car,:r,'PA','BUSCAINTERNA') on conflict(cod_imovel)
                           do update set rodada_id=excluded.rodada_id"""),
            {"car": CAR, "r": numero},
        )
    return numero


def cliente(eng):
    app = FastAPI()
    app.include_router(publico.roteador(lambda _: eng))
    return TestClient(app)


@pytest.mark.banco
def test_snapshot_basico_historico_nao_preenche_com_cadastro_atual(banco):
    antigo = rodada(banco, municipio=None, ha=None, carbono=None)
    novo = rodada(banco, "2026-02-10", "Parauapebas", 999)
    a = v.registrar(banco, CODIGO, antigo)
    n = v.registrar(banco, CODIGO)
    assert a.rodada_id == antigo and a.data_corte == dt.date(2026, 1, 10)
    assert a.municipio is None and a.area_car_ha is None and a.situacao_basica is None
    assert n.rodada_id == novo and n.municipio == "Parauapebas" and n.area_car_ha == 999
    assert a.registrada_em.date() >= a.data_corte  # registro de hoje não finge ter sido criado no passado
    with banco.connect() as con:
        registro = dict(
            con.execute(text("select * from negocio.ficha_publica_versao where rodada_id=:r"), {"r": antigo})
            .mappings()
            .one()
        )
    assert set(registro) == {
        "codigo",
        "rodada_id",
        "data_corte",
        "municipio",
        "uf",
        "area_car_ha",
        "situacao_basica",
        "fonte",
        "sha256",
        "registrada_em",
    }
    serializado = json.dumps(registro, default=str)
    assert all(secreto not in serializado for secreto in (CAR, "SEGREDO", "carbono", "cpf", "tir"))
    payload = {
        k: str(x) if isinstance(x, dt.date) else x for k, x in registro.items() if k not in {"sha256", "registrada_em"}
    }
    assert (
        a.sha256
        == hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    )


@pytest.mark.banco
def test_imutabilidade_conteudo_e_banco_e_sobrevivencia_da_origem(banco):
    rid = rodada(banco)
    antes = v.registrar(banco, CODIGO)
    with banco.begin() as con:
        con.execute(text("update funil.resultado_imovel set ha=999, municipio='Outra' where rodada_id=:r"), {"r": rid})
    assert v.registrar(banco, CODIGO) == antes
    for sql in ("update negocio.ficha_publica_versao set area_car_ha=999", "delete from negocio.ficha_publica_versao"):
        with pytest.raises(DBAPIError, match="imutável"), banco.begin() as con:
            con.execute(text(sql))
    with banco.begin() as con:
        con.execute(text("delete from funil.rodada where id=:r"), {"r": rid})
    assert v.obter(banco, CODIGO, antes.identificador) == (antes, None)


@pytest.mark.banco
def test_nova_versao_usa_data_e_desempata_por_rodada_nunca_por_carga(banco):
    rodada(banco, "2026-03-10")
    marco = v.registrar(banco, CODIGO)
    atrasado = rodada(banco, "2026-01-10", "Histórico carregado depois")
    assert atrasado > marco.rodada_id
    assert v.obter(banco, CODIGO, marco.identificador) == (marco, None)
    mesmo_dia = rodada(banco, "2026-03-10", "Correção na mesma data")
    a, nova = v.obter(banco, CODIGO, marco.identificador)
    assert a == marco and nova.rodada_id == mesmo_dia and nova.identificador != marco.identificador
    proxima = rodada(banco, "2026-04-10")
    assert v.obter(banco, CODIGO, marco.identificador)[1].rodada_id == proxima
    with banco.begin() as con:
        con.execute(text("delete from funil.rodada where id=:r"), {"r": proxima})
    assert v.obter(banco, CODIGO, marco.identificador)[1].rodada_id == proxima


@pytest.mark.banco
def test_rotulos_livres_e_numero_invalido_nao_passam_na_projecao(banco):
    rid = rodada(banco, municipio="Pessoa Fictícia do Teste", ha=float("nan"))
    with banco.begin() as con:
        con.execute(text("update funil.resultado_imovel set uf='ZZ' where rodada_id=:r"), {"r": rid})
    versao = v.registrar(banco, CODIGO)
    assert versao.municipio is None and versao.uf is None and versao.area_car_ha is None
    with cliente(banco) as cl:
        for caminho in (versao.caminho, versao.caminho + ".md", f"/p/{CODIGO}", f"/p/{CODIGO}.md"):
            resposta = cl.get(caminho)
            assert resposta.status_code == 200
            assert "Pessoa Fictícia" not in resposta.text and "ZZ" not in resposta.text
            assert "SEGREDO" not in resposta.text and "000.000.000-00" not in resposta.text
        assert "Não informada" in cl.get(versao.caminho).text


@pytest.mark.banco
@pytest.mark.parametrize("estado", ["cancelado", "recusado", "revisao", "em_andamento", None])
def test_revogacao_bloqueia_tambem_html_markdown_e_versoes_antigas(banco, estado):
    rodada(banco)
    versao = v.registrar(banco, CODIGO)
    with banco.begin() as con:
        if estado is None:
            con.execute(text("delete from negocio.aceite where cod_imovel=:car"), {"car": CAR})
        else:
            con.execute(text("update negocio.aceite set estado=:e where cod_imovel=:car"), {"car": CAR, "e": estado})
    assert v.registrar(banco, CODIGO) is None
    with cliente(banco) as cl:
        for suffix in ("", ".md"):
            resp = cl.get(versao.caminho + suffix)
            assert resp.status_code == 404 and resp.headers["cache-control"] == "private, no-store"
        atual = cl.get(f"/p/{CODIGO}")
        assert atual.status_code == 200 and CAR not in atual.text and "/v/" not in atual.text
        assert cl.get(f"/p/{CODIGO}/satelite.webp").status_code == 404


@pytest.mark.banco
def test_revogacao_entre_leitura_e_revalidacao_nao_renderiza_autorizacao_antiga(banco, monkeypatch):
    rodada(banco)
    registrar = v.registrar

    def revogar_antes_de_registrar(engine, codigo, rodada_id):
        with engine.begin() as con:
            con.execute(text("update negocio.aceite set estado='cancelado' where cod_imovel=:car"), {"car": CAR})
        return registrar(engine, codigo, rodada_id)

    def imagem_nao_pode_ser_consultada(_):
        pytest.fail("A renderização não pode consultar a imagem após a revalidação recusada")

    monkeypatch.setattr(v, "registrar", revogar_antes_de_registrar)
    monkeypatch.setattr(publico, "_imagens_do_aceite", imagem_nao_pode_ser_consultada)
    with cliente(banco) as cl:
        for caminho, headers in (
            (f"/p/{CODIGO}", {}),
            (f"/p/{CODIGO}.md", {}),
            (f"/p/{CODIGO}", {"Accept": "text/markdown"}),
        ):
            with banco.begin() as con:
                con.execute(text("update negocio.aceite set estado='aceito' where cod_imovel=:car"), {"car": CAR})
            resposta = cl.get(caminho, headers=headers)
            assert resposta.status_code == 404
            assert resposta.headers["cache-control"] == "private, no-store"
            assert CAR not in resposta.text and "satelite.webp" not in resposta.text


@pytest.mark.banco
def test_html_markdown_datados_com_aviso_e_fronteira_paga(banco):
    rodada(banco)
    with cliente(banco) as cl:
        atual = cl.get(f"/p/{CODIGO}")
        assert "19,87" not in atual.text and "podem voltar a ser mata" not in atual.text
        assert "124 ha" in atual.text  # área CAR, nunca os 19,87 ha pagos
        link = re.search(r'href="http://testserver(/p/AB23CD/v/[^" ]+)"', atual.text)[1]
        pagina = cl.get(link)
        assert pagina.status_code == 200 and 'rel="canonical"' in pagina.text
        assert "123,50 ha" in pagina.text and "10/01/2026" in pagina.text and "SICAR/SFB" in pagina.text
        assert "og:image" not in pagina.text  # a imagem atual mutável não representa a rodada congelada
        assert all(x not in pagina.text for x in (CAR, "SEGREDO", "19,87", "cpf", "BUSCAINTERNA", "satélite"))
        rodada(banco, "2026-02-10", ha=300)
        html = cl.get(link)
        md = cl.get(link + ".md")
        negociado = cl.get(link, headers={"Accept": "text/markdown"})
        assert md.text == negociado.text and md.headers["content-type"].startswith("text/markdown")
        assert "Há uma versão mais recente" in html.text and "Há uma versão mais recente" in md.text
        assert "123,50 ha" in md.text and "300,00" not in md.text
        assert "Versão registrada em" in html.text and "Dados até" in md.text
        for resposta in (atual, pagina, html, md, negociado):
            assert resposta.headers["cache-control"] == "private, no-store"
        assert cl.get(link.replace(CODIGO, CODIGO.lower())).status_code == 200


@pytest.mark.banco
def test_identificador_estrito_sem_traversal_e_sem_fabricar_passado(banco):
    rodada(banco)
    a = v.registrar(banco, CODIGO)
    with cliente(banco) as cl:
        for token in (
            "../segredo",
            a.identificador + "x",
            a.identificador.replace("2026-01-10", "2026-02-30"),
            a.identificador.replace(a.sha256, "0" * 64),
            "2026-01-10-r" + "9" * 30 + "-" + "a" * 64,
        ):
            assert v.obter(banco, CODIGO, token) is None
            assert cl.get(f"/p/{CODIGO}/v/{token}").status_code == 404
        assert v.obter(banco, "../AB23CD", a.identificador) is None
        assert v.registrar(banco, CODIGO, 999999999) is None
        assert cl.get(f"/p/ZZZZZZ/v/{a.identificador}").status_code == 404
    with banco.connect() as con:
        assert con.execute(text("select count(*) from negocio.ficha_publica_versao")).scalar_one() == 1
