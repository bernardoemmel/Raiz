"""Trancas de privacidade dos documentos: CPF/CNPJ mascarados e nomes fora dos textos livres."""

from raiz.documentos.privacidade import limpar, mascarar, mascarar_documento, tirar_nomes
from raiz.documentos.simulacao import cpf_ficticio


def test_mascara_cpf_e_cnpj_em_texto():
    cpf = cpf_ficticio("529982247")
    t = mascarar(f"Transmitente com CPF {cpf} e CPF sem ponto {cpf.replace('.', '').replace('-', '')}")
    assert cpf not in t and "***.982.247-**" in t
    assert cpf.replace(".", "").replace("-", "") not in t
    # número qualquer com 11 dígitos que não é CPF fica como está
    assert mascarar("processo 12345678901") == "processo 12345678901"


def test_documento_da_parte_nunca_volta_inteiro():
    cpf = cpf_ficticio()
    assert mascarar_documento(cpf) == "***.456.789-**"
    # montados na hora: nenhum arquivo do repositório tem CPF ou CNPJ por extenso
    assert mascarar_documento("123.456.789-" + "00") == "***.456.789-**"  # dígito errado também mascara
    assert mascarar_documento("12.345.678/" + "0001-95") == "**.345.678/****-**"
    assert mascarar_documento("***.456.789-**") == "***.456.789-**"
    assert mascarar_documento(None) is None
    assert mascarar_documento("RG 1234") == "[documento]"


def test_tira_nomes_mas_deixa_instituicao_lugar_e_rotulo():
    assert tirar_nomes("Compra e venda de FULANO DE TAL para Beltrana Souza Lima.") == (
        "Compra e venda de [nome] para [nome]."
    )
    assert tirar_nomes("Hipoteca cedular em favor do Banco da Amazônia, devedor P2") == (
        "Hipoteca cedular em favor do Banco da Amazônia, devedor P2"
    )
    assert tirar_nomes("P1 vende a P2 a fração de 50%") == "P1 vende a P2 a fração de 50%"
    assert tirar_nomes("Cartório do Registro de Imóveis da Comarca de Tucumã") == (
        "Cartório do Registro de Imóveis da Comarca de Tucumã"
    )
    assert tirar_nomes("EDITAL Nº 3, DE 11 DE NOVEMBRO DE 2026") == "EDITAL Nº 3, DE 11 DE NOVEMBRO DE 2026"
    assert tirar_nomes("Ana Sá assina") == "[nome] assina"
    assert tirar_nomes("imóvel em Nova Esperança do Piriá", permitir=["Nova Esperança do Piriá"]) == (
        "imóvel em Nova Esperança do Piriá"
    )


def test_limpar_respeita_chaves_seguras():
    d = limpar(
        {"municipio": "São Félix do Xingu", "resumo": "Fulano Beltrano vende", "lista": ["Ciclano Souza"]},
        chaves_seguras={"municipio"},
    )
    assert d == {"municipio": "São Félix do Xingu", "resumo": "[nome] vende", "lista": ["[nome]"]}
