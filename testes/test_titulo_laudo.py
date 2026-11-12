"""Laudo de título (E5 passo 7), consultas públicas em WARC cifrado (passo 2) e triagem rápida ou completa com o
registro da previsão (passo 8). Os testes marcados com banco rodam no PostgreSQL do CI."""

import datetime as dt
import http.server
import random
import shutil
import threading
import uuid

import pandas as pd
import pytest
from sqlalchemy import text

from raiz.documentos.simulacao import cpf_ficticio
from raiz.pessoal import Cofre, gerar_chave
from raiz.titulo import laudo as L
from raiz.titulo import tarefa
from raiz.titulo import triagem as T
from raiz.titulo import warc as W
from testes.conftest import AMOSTRA
from testes.test_titulo_cadeia import COD, IMOVEL, _docs, _linhas


@pytest.fixture(autouse=True)
def _documentos_isolados(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))


# --- triagem -------------------------------------------------------------------------------------------------------

LIMPO = dict(cod_imovel=IMOVEL, caminho_terra="privada_matricula", matricula_conferida=True, titulo_nota=1,
             titulo_reprova=0, matricula_onus_graves=False)  # fmt: skip
ORIGEM_OK = dict(regra="cadeia.origem", valor="chega_a_origem")


def test_triagem_rapida_so_com_tudo_limpo():
    t = T.triar(LIMPO, [ORIGEM_OK, dict(regra="geometria.car_sigef", valor="D2")])
    assert t["titulo_triagem"] == "rapida" and t["titulo_triagem_chance_problema"] == 0.05
    assert t["titulo_triagem_motivos"] is None and t["titulo_triagem_versao"].startswith("triagem-titulo-2026a+")


def test_triagem_completa_diz_o_porque_e_o_que_pedir():
    falta = dict(regra="cadeia.origem", valor="falta_ler_origem",
                 mensagem="a matrícula 5177 vem da transcrição T-1.234, que ainda não foi lida: pedir")  # fmt: skip
    t = T.triar({**LIMPO, "matricula_onus_graves": True}, [falta, dict(regra="geometria.car_sigef", valor="D6")])
    assert t["titulo_triagem"] == "completa" and t["titulo_triagem_chance_problema"] == 0.35
    m = t["titulo_triagem_motivos"]
    assert "cadeia" in m and "ônus grave" in m and "D6" in m
    assert "vintenária" in t["titulo_triagem_pedir"] and "transcrição T-1.234" in t["titulo_triagem_pedir"]
    # matrícula não lida e sem cadeia: busca completa
    t = T.triar({**LIMPO, "matricula_conferida": None}, [])
    assert t["titulo_triagem"] == "completa" and "não lida" in t["titulo_triagem_motivos"]


def test_posse_segue_a_regularizacao():
    t = T.triar(
        dict(caminho_terra="posse_em_titulacao", regularizacao_proximo_passo="contratar o georreferenciamento."), []
    )
    assert t["titulo_triagem"] == "regularizacao" and t["titulo_triagem_chance_problema"] is None
    assert "georreferenciamento" in t["titulo_triagem_pedir"]


# --- WARC ----------------------------------------------------------------------------------------------------------

PAGINA = b"<html><body>Parcela de teste - detentor: Fulano de Tal</body></html>"


class _Pagina(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGINA)))
        self.end_headers()
        self.wfile.write(PAGINA)

    def log_message(self, *a):
        pass


@pytest.fixture
def servidor(monkeypatch):
    for v in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(v, "127.0.0.1,localhost")
    s = http.server.HTTPServer(("127.0.0.1", 0), _Pagina)
    th = threading.Thread(target=s.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{s.server_port}"
    s.shutdown()


def test_consulta_vira_warc_cifrado(servidor, tmp_path):
    cofre = Cofre(gerar_chave())
    reg, corpo = W.consultar(f"{servidor}/parcela/abc", IMOVEL, "parcela do SIGEF", cofre=cofre, base=tmp_path)
    assert reg.status == 200 and corpo == PAGINA and reg.arquivo.endswith(".warc.gz.cifrado")
    bruto = (tmp_path / IMOVEL / reg.arquivo).read_bytes()
    assert b"Fulano" not in bruto  # a página tem nome: no disco só cifrada
    recs = W.abrir(IMOVEL, reg.arquivo, cofre=cofre, base=tmp_path)
    assert [r["tipo"] for r in recs] == ["request", "response"]
    assert recs[1]["status"] == "200" and recs[1]["bytes"] == len(PAGINA)
    idx = W.consultas(IMOVEL, tmp_path)
    assert len(idx) == 1 and idx[0]["sha256_warc"] == reg.sha256_warc and "Fulano" not in str(idx)
    with pytest.raises(ValueError, match="CPF"):
        W.consultar(f"{servidor}/?cpf={cpf_ficticio()}", IMOVEL, "x", cofre=cofre, base=tmp_path)


def test_sem_chave_fica_so_o_hash(servidor, tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_cofre", lambda c: None)
    reg, _ = W.consultar(f"{servidor}/p", IMOVEL, "parcela", base=tmp_path)
    assert reg.arquivo is None and reg.sha256_resposta and not list((tmp_path / IMOVEL).glob("*.cifrado"))
    reg, _ = W.consultar("http://127.0.0.1:9/fora", IMOVEL, "fora do ar", base=tmp_path, timeout=2)
    assert reg.status is None and reg.erro


# --- laudo ---------------------------------------------------------------------------------------------------------


def _pasta(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir(exist_ok=True)
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"terra_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    conf = pd.DataFrame([dict(cod_imovel=IMOVEL, registro_cns="06.842-9", registro_matricula="5178",
                              situacao="conferida", area_matricula_ha=290.0, motivos_json="[]")])  # fmt: skip
    _docs(tmp_path, conf, pd.DataFrame(_linhas()))
    tarefa.escrever_municipio(pasta, COD)
    return pasta


def test_tarefa_grava_a_triagem(tmp_path):
    pasta = _pasta(tmp_path)
    t = pd.read_csv(pasta / f"titulo_{COD}.csv")
    assert set(t.titulo_triagem) <= set(T.SAIDAS) and "titulo_triagem_pedir" in t.columns
    assert (t.titulo_triagem == "regularizacao").sum() > 0


def test_laudo_html_sem_nome_nem_cpf(tmp_path, servidor):
    pasta = _pasta(tmp_path)
    W.consultar(f"{servidor}/sigef", IMOVEL, "parcela do SIGEF", cofre=Cofre(gerar_chave()))
    d = L.dados(pasta, COD, IMOVEL)
    assert [f for f, _ in d["fases"]][0] in L.ORDEM_FASES and d["cadeia"][0]["matricula"] == "5178"
    assert d["cadeia"][0]["origem_situacao"] == "chega_a_origem" and len(d["consultas"]) == 1
    out = L.gravar(pasta, COD, IMOVEL, tmp_path / "laudos")
    h = out["html"].read_text(encoding="utf-8")
    assert "Laudo de título" in h and "Matrícula 5178" in h and "***.456.789-**" in h and "Banco da Amazônia" in h
    assert "Cadeia dominial" in h and "parcela do SIGEF" in h and "Fulano" not in h
    with pytest.raises(KeyError):
        L.dados(pasta, COD, "PA-1504950-NAOEXISTE")


@pytest.mark.skipif(shutil.which("soffice") is None and shutil.which("libreoffice") is None, reason="sem LibreOffice")
def test_laudo_em_pdf(tmp_path):
    pasta = _pasta(tmp_path)
    out = L.gravar(pasta, COD, IMOVEL, tmp_path / "laudos", pdf=True)
    assert out["pdf"].exists() and out["pdf"].read_bytes()[:4] == b"%PDF"


# --- banco: previsão e gabarito da triagem -------------------------------------------------------------------------


@pytest.mark.banco
def test_triagem_congelada_e_gabaritada_pela_certidao(con, tmp_path):
    from raiz.aprendizado.congelar import congelar_rodada
    from raiz.carga import carregar_municipio

    pasta = _pasta(tmp_path)
    t = pd.read_csv(pasta / f"titulo_{COD}.csv")
    t.loc[t.cod_imovel == IMOVEL, ["titulo_triagem", "titulo_triagem_chance_problema"]] = ["completa", 0.35]
    t.to_csv(pasta / f"titulo_{COD}.csv", index=False)
    im = pd.read_csv(pasta / f"imoveis_{COD}.csv", low_memory=False)
    im["teste_marca"] = f"triagem-{uuid.uuid4().hex}"  # banco reaproveitado: rodada e datas novas a cada vez
    im.to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    d1 = dt.date(2030, 1, 1) + dt.timedelta(days=random.randint(0, 20000))
    r1 = carregar_municipio(con, pasta, COD, d1)
    congelar_rodada(con, r1.rodada_id)
    p = con.execute(
        text("""select valor_num, valor_texto from aprendizado.previsao
                where modelo = 'triagem_titulo' and cod_imovel = :c and rodada_id = :r"""),
        {"c": IMOVEL, "r": r1.rodada_id},
    ).first()
    assert p is not None and p.valor_num == 0.35 and p.valor_texto == "completa"
    # rodada seguinte: todas as matrículas do imóvel lidas, uma divergente
    pd.DataFrame([dict(cod_imovel=IMOVEL, matricula_conferida=False, matricula_situacao="divergente",
                       matriculas_total=2, matriculas_lidas=2, matricula_onus_graves=False,
                       matricula_quebra_cadeia=False)]).to_csv(pasta / f"matricula_{COD}.csv", index=False)  # fmt: skip
    r2 = carregar_municipio(con, pasta, COD, d1 + dt.timedelta(days=17))
    assert r2.nova
    res = T.gabaritar(con, d1 + dt.timedelta(days=18))
    assert res["com_problema"] >= 1
    g = con.execute(
        text("""select valor_num, valor_texto from aprendizado.gabarito where cod_imovel = :c and alvo = :a
                order by observado_em desc, id desc limit 1"""),
        {"c": IMOVEL, "a": T.ALVO},
    ).first()
    assert g.valor_num == 1.0 and g.valor_texto == "divergente"
