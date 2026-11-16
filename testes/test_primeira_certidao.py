"""Contrato da primeira certidão com PDFs sintéticos funcionais; não é avaliação real de acerto."""

import datetime as dt
import io
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from raiz.documentos import aprendizado
from raiz.documentos.certidao import entrada as E
from raiz.documentos.claude import LeitorClaude
from raiz.documentos.config import REPO
from raiz.documentos.simulacao import ClienteSimulado, leitura_exemplo, pdf_exemplo
from raiz.pessoal import Cofre, SemChavePessoal, gerar_chave

CAR = "PA-1504950-" + "A" * 32
PEDIDO = str(uuid.UUID(int=41))
PDF = pdf_exemplo("documento sintético para teste funcional")


def chave():
    return str(uuid.uuid4())


def previsao():
    return {
        "capturada_em": dt.datetime.now(dt.UTC).isoformat(),
        "motor": [{"cod_imovel": CAR, "registro_cns": "068429", "registro_matricula": "5178", "ha_sobre_car": 268.5}],
        "imoveis": [{"cod_imovel": CAR}],
        "fontes": {"certidoes": "sha256-do-arquivo-de-teste"},
    }


def modelo():
    dados = leitura_exemplo()
    dados["imovel"]["car"] = CAR
    return LeitorClaude(cliente=ClienteSimulado([dados]))


@pytest.fixture
def servico(tmp_path):
    return E.EntradaCertidao(7, pasta=tmp_path, cofre=Cofre(gerar_chave()))


def receber(servico, **kw):
    return servico.receber(
        PDF,
        pedido_id=PEDIDO,
        cod_imovel=CAR,
        chave=kw.pop("chave", chave()),
        previsao=kw.pop("previsao", previsao()),
        **kw,
    )


def test_pdf_cifrado_isolado_e_upload_idempotente(servico, tmp_path):
    k = chave()
    d = receber(servico, chave=k)
    assert receber(servico, chave=k)["id"] == d["id"]
    k2 = chave()
    assert receber(servico, chave=k2)["id"] == d["id"]
    assert d["estado"] == "recebida" and d["leitura"] is None and d["gabaritos"] == []
    assert b"%PDF" not in servico.armazem.caminho.read_bytes()
    assert servico.original(d["id"]).startswith(b"%PDF-")
    assert servico.pasta.stat().st_mode & 0o777 == 0o700
    assert servico.armazem.caminho.stat().st_mode & 0o777 == 0o600
    with pytest.raises(E.ErroEntrada, match="chave_reutilizada"):
        servico.receber(pdf_exemplo("outro documento"), pedido_id=PEDIDO, cod_imovel=CAR, chave=k2)
    outro = E.EntradaCertidao(8, pasta=tmp_path, cofre=servico.cofre)
    with pytest.raises(E.ErroEntrada, match="nao_encontrada"):
        outro.obter(d["id"])
    assert outro.armazem.leituras() == []


def test_upload_simultaneo_nao_duplica(servico):
    k = chave()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: receber(servico, chave=k)["id"], range(2)))
    assert ids[0] == ids[1]
    with servico.armazem.con() as con:
        assert con.execute("select count(*) from entrada_certidao").fetchone()[0] == 1


def test_pdf_com_senha_ativo_quebrado_ou_grande_e_rejeitado(monkeypatch):
    with pytest.raises(E.ErroEntrada, match="nao_e_pdf"):
        E.validar_pdf(b"<html>nao e pdf</html>")
    with pytest.raises(E.ErroEntrada, match="pdf_invalido"):
        E.validar_pdf(b"%PDF-1.7\nquebrado")
    p = PdfWriter()
    p.add_blank_page(width=100, height=100)
    p.encrypt("senha-de-teste")
    b = io.BytesIO()
    p.write(b)
    with pytest.raises(E.ErroEntrada, match="protegido"):
        E.validar_pdf(b.getvalue())
    p = PdfWriter()
    p.add_blank_page(width=100, height=100)
    p._root_object[NameObject("/OpenAction")] = DictionaryObject(
        {NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("void(0)")}
    )
    b = io.BytesIO()
    p.write(b)
    with pytest.raises(E.ErroEntrada, match="conteudo_ativo"):
        E.validar_pdf(b.getvalue())
    monkeypatch.setattr(E, "MAX_BYTES", 10)
    with pytest.raises(E.ErroEntrada) as erro:
        E.validar_pdf(pdf_exemplo("teste"))
    assert erro.value.status == 413


def test_quota_so_conta_novos_documentos(servico, monkeypatch):
    d = receber(servico)
    monkeypatch.setattr(E, "MAX_ARMAZENAMENTO", d["tamanho"])
    assert receber(servico)["id"] == d["id"]
    with pytest.raises(E.ErroEntrada, match="limite_de_armazenamento"):
        servico.receber(pdf_exemplo("novo"), pedido_id=PEDIDO, cod_imovel=CAR, chave=chave())


def test_sem_chave_nada_e_persistido(tmp_path, monkeypatch):
    monkeypatch.setattr(E, "Cofre", lambda: (_ for _ in ()).throw(SemChavePessoal("sem chave")))
    with pytest.raises(SemChavePessoal):
        E.EntradaCertidao(7, pasta=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_nao_usa_amostra_como_previsao_real(monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_ENTRADA", str(REPO / "dados" / "amostra"))
    p = E.capturar_previsao("PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A")
    assert p["motor"] == [] and p["imoveis"] == []


def test_leitura_congela_previsto_custo_e_gabarito_humano(servico, monkeypatch):
    p = previsao()
    d = receber(servico, previsao=p)
    # Uma alteração posterior no motor não participa desta conferência.
    monkeypatch.setattr(E.leitor, "_motor", lambda *a: pytest.fail("não pode ler previsão de hoje"))
    k = chave()
    feito = servico.processar(d["id"], chave=k, leitor_modelo=modelo())
    assert feito["estado"] == "lida"
    assert feito["comparacao"][0]["situacao"] == "conferida"
    assert feito["leitura"]["campos"]["area_ha"] == 290
    assert feito["leitura"]["custo_usd"] is not None
    assert feito["gabaritos"] == []
    assert servico.processar(d["id"], chave=k)["leitura"] == feito["leitura"]
    assert servico.processar(d["id"], chave=chave())["leitura"] == feito["leitura"]
    assert len(servico.armazem.leituras()) == 1
    antes = servico.armazem.leitura(feito["leitura"]["id"])
    k = chave()
    corpo = dict(
        fonte="conferencia_humana",
        observado_em=dt.date.today().isoformat(),
        situacao_real="divergente",
        campos={"area_ha": "250"},
        leitura_integral=False,
    )
    g = servico.revisar(d["id"], chave=k, **corpo)
    assert g["estado"] == "conferida_por_pessoa"
    assert len(g["gabaritos"]) == 3
    assert servico.revisar(d["id"], chave=k, **corpo) == g
    assert servico.armazem.leitura(antes.id) == antes
    assert servico.armazem.conferir_hash(antes.id)
    prevs, gabs = aprendizado.previsoes_e_gabaritos(servico.armazem)
    assert {pr["data_corte"] for pr in prevs} == {p["capturada_em"][:10]}
    assert {g["valor_texto"] for g in gabs} == {"divergente", "nao"}
    with pytest.raises(E.ErroEntrada, match="revisao_reutilizada"):
        servico.revisar(d["id"], chave=k, **{**corpo, "situacao_real": "conferida"})


def test_sem_previsao_nao_inventa_divergencia_ou_gabarito_do_motor(servico):
    p = {**previsao(), "motor": [], "imoveis": []}
    d = receber(servico, previsao=p)
    r = servico.processar(d["id"], chave=chave(), leitor_modelo=modelo())
    assert r["estado"] == "aguardando_previsao" and r["comparacao"] == []
    g = servico.revisar(
        d["id"],
        chave=chave(),
        fonte="conferencia_humana",
        observado_em=dt.date.today().isoformat(),
        campos={"area_ha": "290"},
        leitura_integral=True,
    )
    assert len(g["gabaritos"]) == 2
    with pytest.raises(E.ErroEntrada, match="sem_previsao"):
        servico.revisar(
            d["id"],
            chave=chave(),
            fonte="cartorio",
            observado_em=dt.date.today().isoformat(),
            situacao_real="conferida",
        )
    assert aprendizado.previsoes_e_gabaritos(servico.armazem) == ([], [])


def test_revisao_invalida_e_atomica(servico):
    d = receber(servico)
    servico.processar(d["id"], chave=chave(), leitor_modelo=modelo())
    with pytest.raises(ValueError):
        servico.revisar(
            d["id"],
            chave=chave(),
            fonte="conferencia_humana",
            observado_em=dt.date.today().isoformat(),
            situacao_real="inventada",
            leitura_integral=True,
        )
    assert servico.armazem.gabaritos() == []
    with pytest.raises(E.ErroEntrada, match="fonte_de_gabarito"):
        servico.revisar(
            d["id"], chave=chave(), fonte="modelo", observado_em=dt.date.today().isoformat(), campos={"area_ha": "1"}
        )
    with pytest.raises(E.ErroEntrada, match="campos_de_gabarito"):
        servico.revisar(
            d["id"], chave=chave(), fonte="cartorio", observado_em=dt.date.today().isoformat(), campos={"nome": "texto"}
        )


def test_falha_pode_repetir_sem_guardar_texto_do_provedor(servico, monkeypatch):
    d = receber(servico)
    k = chave()
    original = E.leitor.ler_certidao

    def falhar(*a, **kw):
        raise RuntimeError("trecho privado do PDF e credencial")

    monkeypatch.setattr(E.leitor, "ler_certidao", falhar)
    r = servico.processar(d["id"], chave=k, leitor_modelo=modelo())
    assert r["estado"] == "falha" and r["erro"] == "leitura_indisponivel"
    monkeypatch.setattr(E.leitor, "ler_certidao", original)
    assert servico.processar(d["id"], chave=k, leitor_modelo=modelo())["estado"] == "falha"
    assert servico.processar(d["id"], chave=chave(), leitor_modelo=modelo())["estado"] == "lida"
    assert b"trecho privado" not in servico.armazem.caminho.read_bytes()


@pytest.mark.parametrize(
    ("campo", "valor"),
    [("area_ha", "--"), ("onus_ativos", "1.5"), ("n_transmissoes", "-1"), ("cns", "123"), ("matricula", "nome")],
)
def test_gabarito_nao_aceita_valor_invalido(servico, campo, valor):
    with pytest.raises(E.ErroEntrada, match="campos_de_gabarito_invalidos"):
        servico.revisar(
            str(uuid.uuid4()),
            chave=chave(),
            fonte="conferencia_humana",
            observado_em=dt.date.today().isoformat(),
            campos={campo: valor},
        )
    assert servico.armazem.gabaritos() == []


def test_texto_pessoal_nao_sai_no_campo_tecnico(servico):
    d = receber(servico)
    dados = leitura_exemplo()
    dados["matricula"]["numero"] = "nome indevido no campo matrícula"
    leitura = LeitorClaude(cliente=ClienteSimulado([dados]))
    r = servico.processar(d["id"], chave=chave(), leitor_modelo=leitura)
    assert r["leitura"]["campos"]["matricula"] is None
    assert "nome indevido" not in str(r)


def test_recupera_leitura_gravada_antes_de_queda_sem_nova_chamada(servico):
    p = previsao()
    d = receber(servico, previsao=p)
    r = servico.processar(d["id"], chave=chave(), leitor_modelo=modelo())
    with servico.armazem.con() as con:
        con.execute(
            "update entrada_certidao set estado='processando', leitura_id=null, tentativa_ate=?",
            ("2000-01-01T00:00:00+00:00",),
        )
    recuperado = servico.processar(d["id"], chave=chave())
    assert recuperado["estado"] == "lida" and recuperado["leitura"] == r["leitura"]
    assert len(servico.armazem.leituras()) == 1
