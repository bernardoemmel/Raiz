"""Cadeia dominial (E5 passo 6): ato por ato da certidão lida até o Postgres, origem da cadeia, bandeiras de contexto e
auditoria, e a localização da sede mandada pelo dono. Os testes marcados com banco rodam no PostgreSQL do CI."""

import datetime as dt
import json
import shutil

import pandas as pd
import pytest
from shapely.geometry import Polygon
from sqlalchemy import text

from raiz.documentos.certidao.cadeia import COLUNAS, cadeia_das_conferencias, linhas_da_leitura
from raiz.documentos.certidao.leitor import sanear
from raiz.documentos.certidao.regras import derivar, normalizar_cns, normalizar_matricula
from raiz.documentos.simulacao import leitura_exemplo
from raiz.titulo import cadeia as CA
from raiz.titulo import contexto as CX
from raiz.titulo import sede as SD
from testes.conftest import AMOSTRA

COD = 1504950
IMOVEL = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"
HOJE = dt.date(2026, 11, 12)


@pytest.fixture(autouse=True)
def _documentos_isolados(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))


def _linhas(**kw):
    dados = sanear(leitura_exemplo(**kw))
    der = derivar(dados, HOJE).para_dict()
    meta = dict(leitura_hash="h" + kw.get("matricula", "5178"), leitura_id=1, lido_em="2026-11-12T10:00:00",
                modelo="claude-opus-5-5", leitor_versao="v", regras_versao="r", conferencia="conferida")  # fmt: skip
    return linhas_da_leitura(dados, der, meta)


# --- do documento ao arquivo ---------------------------------------------------------------------------------------


def test_um_ato_por_linha_com_o_anterior_e_quem_cancela():
    ls = _linhas()
    assert [x["ato_numero"] for x in ls] == ["ABERTURA", "R-1", "R-2", "AV-3", "AV-4"]
    r1 = ls[1]
    assert r1["transmissao"] and r1["anterior_numero"] == "ABERTURA"
    assert ls[2]["cancelado_por"] == "AV-4" and not ls[2]["transmissao"]
    assert {x["registro_cns"] for x in ls} == {"068429"} and {x["registro_matricula"] for x in ls} == {"5178"}
    assert ls[0]["origem"] == "titulo_publico" and ls[0]["origem_matricula"] is None
    de = json.loads(r1["transmitentes_json"])
    assert de == [{"rotulo": "P1", "tipo": "pessoa_fisica", "documento": "***.456.789-**", "instituicao": None}]
    credor = json.loads(ls[2]["adquirentes_json"])[0]
    assert credor["instituicao"] == "Banco da Amazônia"
    donos = json.loads(ls[0]["proprietarios_json"])
    assert {d["rotulo"] for d in donos} == {"P2", "P3"}


def test_modelo_que_desobedece_nao_vaza_nome_nem_cpf():
    ls = _linhas(com_nomes=True)
    tudo = json.dumps(ls, ensure_ascii=False, default=str)
    assert "Fulano" not in tudo and "Beltrana" not in tudo
    from raiz.privacidade import mascarar

    assert mascarar(tudo) == tudo  # nada para mascarar: nenhum CPF ou CNPJ inteiro


def test_conferencias_viram_cadeia_sem_repetir_leitura():
    dados = sanear(leitura_exemplo())
    der = derivar(dados, HOJE).para_dict()
    c = dict(registro_hash="abc", leitura_id=7, lido_em="2026-11-12", modelo="m", leitor_versao="v",
             prompt_versao="p", regras_versao="r", situacao="conferida", dados_json=json.dumps(dados),
             derivados_json=json.dumps(der))  # fmt: skip
    df = cadeia_das_conferencias([c, {**c, "cod_imovel": "outro"}])  # a mesma matrícula em dois imóveis
    assert list(df.columns) == COLUNAS and len(df) == 5 and set(df.leitura_hash) == {"abc"}
    assert df.leitor_versao.iloc[0] == "v+p"


# --- origem da cadeia ------------------------------------------------------------------------------------------------


def _mat(mat, origem, origem_mat=None, natureza="abertura", cns="068429", ref=None):
    return dict(registro_cns=cns, registro_matricula=mat, origem=origem, origem_matricula=origem_mat,
                origem_referencia=ref or origem_mat, natureza=natureza)  # fmt: skip


def test_cadeia_segue_a_origem_ate_o_titulo_publico():
    df = pd.DataFrame(
        [
            _mat("100", "matricula_anterior", "50"),
            _mat("50", "matricula_anterior", "10"),
            _mat("10", "titulo_publico"),
            _mat("200", "transcricao_anterior", ref="T-3.456"),
            _mat("300", "desconhecida"),
            _mat("400", "desconhecida", natureza="titulacao_publica"),  # ato originário na cadeia
            _mat("7", "matricula_anterior", "8"),  # ciclo: não trava
            _mat("8", "matricula_anterior", "7"),
        ]
    )
    r = CA.resolver(CA.matriculas(df))
    k = lambda m: ("068429", m)  # noqa: E731
    assert r[k("100")]["situacao"] == "chega_a_origem" and r[k("100")]["saltos"] == 2
    assert r[k("200")]["situacao"] == "falta_ler_origem"
    assert r[k("300")]["situacao"] == "origem_desconhecida"
    assert r[k("400")]["situacao"] == "chega_a_origem"
    assert r[k("7")]["situacao"] == "falta_ler_origem"


def _docs(tmp_path, conf: pd.DataFrame, cadeia: pd.DataFrame | None = None):
    doc = tmp_path / "docs" / "saida" / "PA"
    doc.mkdir(parents=True, exist_ok=True)
    conf.to_csv(doc / f"matricula_conferencia_{COD}.csv", index=False)
    if cadeia is not None:
        cadeia.to_csv(doc / f"cadeia_{COD}.csv", index=False)


def test_achado_da_origem_por_imovel(tmp_path):
    ls = pd.DataFrame(_linhas() + _linhas(matricula="5177"))
    ls.loc[ls.registro_matricula == "5177", "origem"] = "transcricao_anterior"
    ls.loc[ls.registro_matricula == "5177", "origem_referencia"] = "T-1.234"
    conf = pd.DataFrame(
        [
            dict(cod_imovel=IMOVEL, registro_cns="06.842-9", registro_matricula="5178", situacao="conferida"),
            dict(cod_imovel=IMOVEL, registro_cns="06.842-9", registro_matricula="5177", situacao="conferida"),
        ]
    )
    _docs(tmp_path, conf, ls)
    a = CA.achados_da_cadeia(tmp_path / "PA", COD)
    assert dict(zip(a.valor, a.situacao, strict=True)) == {"chega_a_origem": "ok", "falta_ler_origem": "conferir"}
    falta = a[a.valor == "falta_ler_origem"].iloc[0]
    assert "transcrição T-1.234" in falta.mensagem and falta.fase == "cadeia" and "6.015" in falta.base


# --- contexto e auditoria ------------------------------------------------------------------------------------------


def test_cercas_e_areas_redondas():
    c = CX.cercas([1.0, 1.0, 1.02, 0.98, 1.01, 0.99, 1.0, 1.03], piso=0.05)
    assert CX.posicao(1.0, c) is None
    assert CX.posicao(1.12, c) == "interna_alta" and CX.posicao(2.0, c) == "externa_alta"
    assert CX.posicao(0.5, c) == "externa_baixa"
    assert CX.cercas([1, 2, 3]) is None  # grupo pequeno: sem cerca
    assert CX.area_redonda(100.0) == "100 ha" and CX.area_redonda(1_500.0) == "1.500 ha"
    assert CX.area_redonda(48.4) == "20 alqueires (paulista)"
    assert CX.area_redonda(123.4567) is None and CX.area_redonda(7.0) is None and CX.area_redonda(None) is None


def test_bandeiras_de_contexto_do_municipio(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    im = pd.read_csv(AMOSTRA / f"imoveis_{COD}.csv", dtype={"cod_imovel": str}, low_memory=False).head(12)
    im.to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    linhas = []
    for i, r in enumerate(im.itertuples(index=False)):
        fator = 2.5 if i == 0 else (0.5 if i == 1 else 1.0 + 0.01 * (i % 3))
        cart = "000001" if i < 3 else f"00010{i % 9}"
        linhas.append(dict(cod_imovel=r.cod_imovel, registro_cns=cart, registro_matricula=str(1000 + i),
                           situacao="divergente" if i < 3 else "conferida",
                           area_matricula_ha=r.ha * fator))  # fmt: skip
    linhas.append(
        dict(
            cod_imovel=im.cod_imovel.iloc[5],
            registro_cns="000002",
            registro_matricula="9999",
            situacao="conferida",
            area_matricula_ha=300.0,
        )
    )  # redonda; e o imóvel 5 passa a ter 2 glebas
    _docs(tmp_path, pd.DataFrame(linhas))
    a = CX.achados_de_contexto(pasta, COD)
    soma = a[a.regra == "auditoria.soma_glebas"].set_index("cod_imovel")
    assert soma.loc[im.cod_imovel.iloc[0]].gravidade == "confirmar"  # título 2,5 vezes o CAR
    assert "sem matrícula" in soma.loc[im.cod_imovel.iloc[1]].mensagem
    assert soma.loc[im.cod_imovel.iloc[4]].situacao == "ok"
    mun = a[a.regra == "contexto.municipio"]
    assert set(mun.cod_imovel) >= {im.cod_imovel.iloc[0]}
    assert "cerca externa" in mun.set_index("cod_imovel").loc[im.cod_imovel.iloc[0]].mensagem
    red = a[a.regra == "auditoria.area_redonda"]
    assert list(red.valor) == ["300.0000"] and set(red.gravidade) == {"info"}
    assert set(a.fase) <= {"coerencia", "referencia", "cadeia"}
    # sem certidão lida, nenhuma bandeira
    _docs(tmp_path, pd.DataFrame([dict(cod_imovel=IMOVEL, registro_cns="1", registro_matricula="1",
                                       situacao="a_conferir", area_matricula_ha=None)]))  # fmt: skip
    assert CX.achados_de_contexto(pasta, COD).empty


def test_cartorio_e_dono_fora_da_cerca(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    im = pd.read_csv(AMOSTRA / f"imoveis_{COD}.csv", dtype={"cod_imovel": str}, low_memory=False).head(30)
    im.to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    conf, cad = [], []
    for i, r in enumerate(im.itertuples(index=False)):
        cart = f"{i % 10:06d}"  # 10 cartórios com 3 matrículas cada; o 000000 com tudo divergente
        mat = str(2000 + i)
        sit = "divergente" if cart == "000000" else "conferida"
        conf.append(dict(cod_imovel=r.cod_imovel, registro_cns=cart, registro_matricula=mat, situacao=sit,
                         area_matricula_ha=10.0 + i))  # fmt: skip
        doc = "**.902.995/****-**" if i < 3 else f"***.{i:03d}.111-**"  # um dono com 3 matrículas grandes
        cad.append(dict(registro_cns=cart, registro_matricula=mat, area_matricula_ha=900.0 if i < 3 else 10.0 + i,
                        georreferenciado=False, proprietarios_json=json.dumps([{"rotulo": "P1", "documento": doc}]),
                        origem="titulo_publico", natureza="abertura", ordem=0))  # fmt: skip
    _docs(tmp_path, pd.DataFrame(conf), pd.DataFrame(cad))
    a = CX.achados_de_contexto(pasta, COD)
    cart = a[a.regra == "contexto.cartorio"]
    assert len(cart) == 3 and set(cart.fase) == {"referencia"} and "100%" in cart.mensagem.iloc[0]
    dono = a[a.regra == "contexto.dono"]
    assert len(dono) == 3 and set(dono.gravidade) == {"confirmar"} and "**.902.995/****-**" in dono.mensagem.iloc[0]


def test_tarefa_leva_cadeia_e_contexto_aos_achados(tmp_path):
    from raiz.titulo import tarefa

    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"terra_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    conf = pd.DataFrame([dict(cod_imovel=IMOVEL, registro_cns="06.842-9", registro_matricula="5178",
                              situacao="conferida", area_matricula_ha=290.0, motivos_json="[]")])  # fmt: skip
    _docs(tmp_path, conf, pd.DataFrame(_linhas()))
    tarefa.escrever_municipio(pasta, COD)
    a = pd.read_csv(pasta / f"achados_{COD}.csv")
    assert {"cadeia.origem", "auditoria.area_redonda"} <= set(a.regra)
    assert "cadeia-origem-2026a" in tarefa.versao() and "contexto-2026a" in tarefa.versao()


# --- sede ----------------------------------------------------------------------------------------------------------

QUADRADO = Polygon([(-47.0, -2.0), (-46.99, -2.0), (-46.99, -1.99), (-47.0, -1.99)])  # ~1,1 km de lado


def test_sede_dentro_na_divisa_e_fora():
    assert SD.conferir_ponto("X", QUADRADO, -46.995, -1.995).situacao == "dentro"
    d = SD.conferir_ponto("X", QUADRADO, -46.98973, -1.995)  # ~30 m a leste da borda
    assert d.situacao == "divisa" and 20 <= d.distancia_borda_m <= 40
    f = SD.conferir_ponto("X", QUADRADO, -46.98, -1.995)
    assert f.situacao == "fora" and 1000 <= f.distancia_borda_m <= 1200
    assert SD.conferir_ponto("X", None, -46.98, -1.995).situacao == "sem_poligono"
    a = f.achado()
    assert a.fase == "geometria" and a.gravidade == "confirmar" and "-46" not in a.mensagem  # o ponto não vai


def test_pedido_da_sede_e_facil_de_ler():
    from raiz import legibilidade as L
    from raiz.agentes import textos

    m = L.medir(textos.pedido_sede())
    assert m["flesch_martins"] >= 50 and m["palavras_por_frase"] <= 15
    assert "pedido_sede" in textos.exemplos()


# --- banco --------------------------------------------------------------------------------------------------------


@pytest.mark.banco
def test_normalizacao_no_banco_igual_a_do_python(con):
    exemplos = ["06.842-9", "6842-9", "068429", "1234567", None, "", "abc"]
    for x in exemplos:
        assert con.execute(text("select titulo.norm_cns(:x)"), {"x": x}).scalar() == normalizar_cns(x), x
    mats = ["5.178", "Matrícula nº 5.178", "005178", "1234-A", "5178.0", "5.000", "MATRICULA N. 12", "AB-12", None, ""]
    for x in mats:
        assert con.execute(text("select titulo.norm_matricula(:x)"), {"x": x}).scalar() == normalizar_matricula(x), x


@pytest.mark.banco
def test_cadeia_no_banco(con, tmp_path):
    from raiz.carga import carregar_municipio
    from raiz.titulo import banco as TB

    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"certidoes_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    im = pd.read_csv(pasta / f"imoveis_{COD}.csv", low_memory=False)
    im["teste_marca"] = "cadeia"  # muda o hash: a carga não devolve a rodada de outro teste
    im.to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    a = pd.DataFrame(_linhas())
    b = pd.DataFrame(_linhas(matricula="5177"))
    b["origem"], b["origem_matricula"], b["origem_referencia"] = "matricula_anterior", "5178", "5.178"
    pd.concat([a, b]).to_csv(pasta / f"cadeia_{COD}.csv", index=False)
    r = carregar_municipio(con, pasta, COD, dt.date(2026, 11, 2))
    assert r.nova
    n = con.execute(text("select count(*) from titulo.ato where leitura_hash in ('h5178', 'h5177')")).scalar()
    assert n == 10
    # a mesma leitura de novo não duplica
    assert TB.carregar_cadeia(con, pasta / f"cadeia_{COD}.csv") == {"matriculas": 0, "atos": 0}
    # partes só com documento mascarado: o banco recusa documento inteiro
    ato = con.execute(text("select id from titulo.ato where leitura_hash = 'h5178' and numero = 'R-1'")).scalar()
    with pytest.raises(Exception, match="check"):
        with con.begin_nested():
            con.execute(text("insert into titulo.ato_parte (ato_id, papel, documento) values (:a, 'adquirente', "
                             "'52998224725')"), {"a": ato})  # fmt: skip
    cad = TB.cadeia_do_imovel(con, IMOVEL)
    por = {m["matricula"]: m for m in cad}
    assert set(por) == {"5178", "5177"}
    assert por["5177"]["origem_situacao"] == "chega_a_origem" and por["5177"]["origem_saltos"] == 1
    r1 = next(x for x in por["5178"]["atos"] if x["numero"] == "R-1")
    assert r1["anterior_numero"] == "ABERTURA" and {p["papel"] for p in r1["partes"]} == {"transmitente", "adquirente"}
    assert all(p["documento"] is None or "*" in p["documento"] for p in r1["partes"])


@pytest.mark.banco
def test_sede_pelo_whatsapp_guarda_so_o_resultado(con, banco_url):
    from sqlalchemy import create_engine

    from raiz.pessoal import Cofre, gerar_chave, registrar_contato_whatsapp
    from raiz.whatsapp import enviar_aprovadas, receber_localizacao

    cofre = Cofre(gerar_chave())
    cod = "PA-1504950-SEDETESTE"
    eng = create_engine(banco_url)
    with eng.begin() as c:
        c.execute(text("delete from titulo.achado where cod_imovel = :c"), {"c": cod})
        c.execute(text("delete from negocio.aceite where cod_imovel = :c"), {"c": cod})
        c.execute(text("delete from pessoal.mensagem_saida where cod_imovel = :c"), {"c": cod})
        c.execute(
            text("""insert into funil.imovel (cod_imovel, uf, geom)
                    values (:c, 'PA', ST_Multi(ST_GeomFromText(:w, 4674)))
                    on conflict (cod_imovel) do update set geom = excluded.geom"""),
            {"c": cod, "w": QUADRADO.wkt},
        )
        ct = registrar_contato_whatsapp(c, "BR.sede1", None, cofre=cofre)
        c.execute(text("insert into pessoal.contato_imovel (contato_id, cod_imovel) values (:t, :c) "
                       "on conflict do nothing"), {"t": ct, "c": cod})  # fmt: skip
        c.execute(text("insert into negocio.aceite (cod_imovel, contato_id, estado, etapa) "
                       "values (:c, :t, 'aceito', 'aceito')"), {"t": ct, "c": cod})  # fmt: skip
        mid = SD.pedir(c, cod)
        c.execute(text("update pessoal.mensagem_saida set estado = 'aprovada' where id = :i"), {"i": mid})
    # o pedido sai pelo botão de localização, as outras mensagens pelo texto
    pedidos, textos_ = [], []
    n = enviar_aprovadas(eng, lambda d, t: textos_.append(t) or "w1", cofre,
                         pedir_localizacao=lambda d, t: pedidos.append(t) or "w2")  # fmt: skip
    assert n == 1 and len(pedidos) == 1 and not textos_
    r = receber_localizacao(eng, "BR.sede1", None, -46.995, -1.995, cofre=cofre)
    assert r["acao"] == "sede" and r["sede"] == "dentro" and r["cod_imovel"] == cod
    with eng.connect() as c:
        ult = SD.ultima(c, cod)
        assert ult["valor"] == "dentro"
        # o ponto não fica em lugar nenhum do achado
        linha = c.execute(text("select row_to_json(a)::text from titulo.achado a where cod_imovel = :c"),
                          {"c": cod}).scalar()  # fmt: skip
        assert "46.995" not in linha and "1.995" not in linha
    # contato sem imóvel com aceite: revisão
    assert receber_localizacao(eng, "BR.sede-sem", None, -46.0, -1.0, cofre=cofre)["acao"] == "revisao"
    eng.dispose()
