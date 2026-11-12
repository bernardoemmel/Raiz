"""Contratos estruturais; nenhum exemplo representa certidão/gabarito real."""

import datetime as dt

import pytest

from raiz.calendario import coleta
from raiz.calendario import leiloes_abertos as leiloes

CAR = "PA-1500206-" + "A" * 32
CAR_OUTRO = "PA-1500206-" + "B" * 32
DETALHE = leiloes.CAIXA + "/sistema/detalhe-imovel.asp?hdnimovel=42"
PDF = leiloes.CAIXA + "/editais/matricula/PA/0000042.pdf"
FONTE = {"id": "caixa", "modo": "caixa_csv", "nome": "CAIXA", "urls": [leiloes.CAIXA]}
FONTE_BB = {"id": "bb", "modo": "bb_imoveis", "nome": "Banco do Brasil", "urls": [leiloes.BB]}


def detalhe(*, matricula="5178", tipo="Imóvel rural", car="", pdf=PDF):
    return f"""<html><main>
      <p><span>Tipo de imóvel: <strong>{tipo}</strong></span>
      <span>Matrícula(s): <strong>{matricula}</strong></span><br>Comarca: Município-PA</p>
      <p>Data do 1º Leilão - 12/12/2026 - 10h00<br>Data do 2º Leilão - 19/12/2026 - 10h00</p>
      <p>Descrição: Área de imóvel rural. {car}</p>
      <a href="#" onclick="javascript:ExibeDoc('{pdf}')">Baixar matrícula do imóvel</a>
      <a href="#" onclick="javascript:ExibeDoc('/editais/ELGERAL.PDF')">Edital geral</a>
    </main></html>"""


def csv(*linhas):
    return "Listagem de imóveis\n\n N° do imóvel;UF;Cidade;Descrição;Modalidade de venda;Link de acesso\n" + "\n".join(
        linhas
    )


def test_csv_oficial_filtra_uf_e_tipo_sem_minimo_de_area():
    texto = csv(
        f" 42; PA ;Cidade; Imóvel rural, área de 0,01 ha;Leilão SFI; {DETALHE} ",
        f" 43; SP ;Cidade; Imóvel rural, área de 1000 ha;Leilão SFI;{DETALHE.replace('42', '43')}",
        f" 44; PA ;Cidade;Casa em zona rural;Leilão SFI;{DETALHE.replace('42', '44')}",
    )
    assert leiloes.links(texto, leiloes.sementes(FONTE, dt.date.today())[0], {**FONTE, "_ufs_processadas": ["PA"]}) == [
        DETALHE
    ]


def test_csv_recusa_links_fora_do_portal_ou_com_parametros_pessoais():
    texto = csv(
        "42;PA;Cidade;Imóvel rural;Leilão;https://externo.test/sistema/detalhe-imovel.asp?hdnimovel=42",
        f"42;PA;Cidade;Imóvel rural;Leilão;{DETALHE}&nome=Pessoa",
        f"42;PA;Cidade;Imóvel rural;Leilão;{DETALHE}&hdnimovel=43",
    )
    assert leiloes.links(texto, leiloes.CAIXA + "/listaweb/Lista_imoveis_PA.csv", FONTE) == []


def test_csv_alterado_e_falha_explicita():
    with pytest.raises(ValueError, match="cabeçalho"):
        leiloes.links("erro do servidor", leiloes.CAIXA + "/listaweb/Lista_imoveis_PA.csv", FONTE)


def test_detalhe_caixa_reune_datas_do_proprio_bem_e_descarta_texto_pessoal():
    bruto = detalhe(car=CAR).replace("Área de imóvel rural", "Texto pessoal que deve desaparecer. Área de imóvel rural")
    tx = leiloes.texto_evento(bruto, DETALHE, FONTE)
    assert "Texto pessoal" not in tx
    eventos, _ = coleta.extrair(tx, FONTE, DETALHE, dt.datetime(2026, 11, 12, tzinfo=dt.UTC))
    assert [e.data for e in eventos] == [dt.date(2026, 12, 12), dt.date(2026, 12, 19)]
    assert all(e.codigos_car == [CAR] and e.matricula == "5178" for e in eventos)


def test_detalhe_urbano_nao_herda_car_ou_data_de_outro_cartao():
    assert leiloes.texto_evento(detalhe(tipo="Casa", car=CAR), DETALHE, FONTE) == ""


def test_detalhe_sem_leilao_nao_inventa_prazo():
    tx = detalhe().replace("Data do 1º Leilão", "Publicado em").replace("Data do 2º Leilão", "Atualizado em")
    assert leiloes.texto_evento(tx, DETALHE, FONTE) == ""


def test_descoberta_so_matricula_do_mesmo_item_sem_edital_multibens():
    assert leiloes.documento_matricula(detalhe(), DETALHE, FONTE) == PDF
    assert leiloes.links(detalhe(), DETALHE, FONTE) == [PDF]
    assert leiloes.documento_matricula(detalhe(pdf=PDF.replace("0000042", "0000043")), DETALHE, FONTE) is None


@pytest.mark.parametrize("matricula", ["5178 e 5179", "5178/5179", "", "a conferir"])
def test_multiplas_matriculas_ou_metadado_ausente_nao_comprovam_imovel(matricula):
    assert leiloes.documento_matricula(detalhe(matricula=matricula), DETALHE, FONTE) is None


def test_pdf_unico_com_matricula_primaria_compativel_e_car_tem_prova():
    assert leiloes.complemento_matricula(
        detalhe(), DETALHE, f"MATRÍCULA Nº 5.178\nCadastro Ambiental Rural: {CAR}", PDF, FONTE
    ) == {
        "codigos_car": [CAR],
        "matricula": "5178",
        "car_fonte_url": PDF,
        "vinculo": "car",
    }


@pytest.mark.parametrize(
    "texto_pdf",
    [
        f"MATRÍCULA Nº 999\nMatrícula anterior 5178\nCAR {CAR}",
        f"MATRÍCULA Nº 5178\nCAR {CAR}\nCAR {CAR_OUTRO}",
        "MATRÍCULA Nº 5178\nSem CAR",
        f"MATRÍCULA Nº 5178\nCAR {CAR.replace('PA-', 'GO-')}",
    ],
)
def test_pdf_incompativel_ambiguo_ou_sem_car_continua_pendente(texto_pdf):
    assert leiloes.complemento_matricula(detalhe(), DETALHE, texto_pdf, PDF, FONTE) is None


def test_edital_geral_nao_e_prova_do_car():
    assert (
        leiloes.complemento_matricula(
            detalhe(), DETALHE, f"MATRÍCULA 5178 CAR {CAR}", leiloes.CAIXA + "/editais/geral.pdf", FONTE
        )
        is None
    )


def test_bb_indices_so_destaques_rurais_das_ufs_processadas():
    texto = """<div class="box-rural-highlights">
      <div class="carta">Terreno rural. Município, PA<a href="/imovel/id/42">Ver</a></div>
      <div class="carta">Terreno rural. Município, SP<a href="/imovel/id/43">Ver</a></div>
    </div><a href="/imovel/id/44">Casa urbana</a>"""
    assert leiloes.links(texto, leiloes.BB, {**FONTE_BB, "_ufs_processadas": ["PA"]}) == [leiloes.BB + "/imovel/id/42"]


def test_bb_detalhe_une_so_a_descricao_com_a_data_do_leilao():
    html = f"""<h4>Data do leilão: 12/12/2026 a partir das 14h00</h4>
      <h4>Descrição</h4><div>Imóvel rural. Matrícula 5178. CAR {CAR}.
      Pessoa mencionada e compra antiga em 10/10/2010.</div>
      <h4>Observações</h4><div>Outro imóvel {CAR_OUTRO}</div>"""
    texto = leiloes.texto_evento(html, leiloes.BB + "/imovel/id/42", FONTE_BB)
    assert CAR in texto and CAR_OUTRO not in texto and "Pessoa" not in texto and "2010" not in texto
    ev, _ = coleta.extrair(texto, FONTE_BB, leiloes.BB + "/imovel/id/42", dt.datetime(2026, 11, 12, tzinfo=dt.UTC))
    assert len(ev) == 1 and ev[0].codigos_car == [CAR]


def test_bb_sem_indice_e_falha_explicita():
    with pytest.raises(ValueError, match="índice"):
        leiloes.links("<main>Layout alterado</main>", leiloes.BB, FONTE_BB)


def test_outros_modos_continuam_no_extrator_original():
    assert leiloes.sementes({}, dt.date.today()) is None
    assert leiloes.links("", "https://fonte.test", {}) is None
    assert leiloes.texto_evento("", "https://fonte.test", {}) is None
