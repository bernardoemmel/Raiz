"""Guarda de privacidade. Os documentos de teste são gerados por cálculo: nenhum CPF ou CNPJ válido fica escrito
no repositório (a varredura do CI acusaria)."""

import logging
import subprocess

import pandas as pd

from raiz import RAIZ_REPO
from raiz import privacidade as P


def gerar_cpf(base9: str) -> str:
    d = [int(x) for x in base9]
    for n in (9, 10):
        soma = sum(d[i] * (n + 1 - i) for i in range(n))
        d.append(soma * 10 % 11 % 10)
    return "".join(map(str, d))


def gerar_cnpj(base12: str) -> str:
    s = base12
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        r = sum((ord(c) - 48) * p for c, p in zip(s, pesos, strict=True)) % 11
        s += str(0 if r < 2 else 11 - r)
    return s


def fmt_cpf(d: str) -> str:
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def fmt_cnpj(s: str) -> str:
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


CPF = gerar_cpf("529982247")
CNPJ = gerar_cnpj("112223330001")
CNPJ_ALFA = gerar_cnpj("12ABC34501DE")


def test_validacao():
    assert P.cpf_valido(CPF) and P.cpf_valido(fmt_cpf(CPF))
    assert not P.cpf_valido(CPF[:-1] + str((int(CPF[-1]) + 1) % 10))
    assert not P.cpf_valido("11111111111")
    assert P.cnpj_valido(CNPJ) and P.cnpj_valido(fmt_cnpj(CNPJ))
    assert P.cnpj_valido(CNPJ_ALFA) and P.cnpj_valido(fmt_cnpj(CNPJ_ALFA))
    assert not P.cnpj_valido(CNPJ_ALFA[:-1] + str((int(CNPJ_ALFA[-1]) + 1) % 10))


def test_mascara_formatado_e_cru():
    for doc in (fmt_cpf(CPF), CPF):
        out = P.mascarar(f"dono {doc} no CAR")
        assert CPF not in out.replace(".", "").replace("-", "")
        assert "***." in out
    for doc in (fmt_cnpj(CNPJ), CNPJ, fmt_cnpj(CNPJ_ALFA), CNPJ_ALFA):
        out = P.mascarar(f"empresa {doc};")
        assert "/****-**" in out, out


def test_mascara_nao_estraga_numeros_comuns():
    textos = [
        "189.99087022873272",  # área com muitas casas decimais (está na amostra)
        "PA-1504950-00162AB1E0B34E339E65946061393F10",  # código do CAR
        "sicar_imoveis_pa.15965100",
        "12345678901",  # 11 dígitos sem dígito verificador válido
    ]
    for t in textos:
        assert P.mascarar(t) == t


def test_log_mascarado(caplog):
    fmt = P.FormatadorSeguro("%(message)s")
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "contato %s", (fmt_cpf(CPF),), None)
    assert CPF[3:6] in fmt.format(rec) and fmt_cpf(CPF) not in fmt.format(rec)


def test_log_mascara_traceback():
    fmt = P.FormatadorSeguro("%(message)s")
    try:
        raise ValueError(f"CPF {CPF} inválido")
    except ValueError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "falhou", None, sys.exc_info())
    assert CPF not in fmt.format(rec)


def test_remove_colunas_pessoais():
    df = pd.DataFrame(
        columns=[
            "SEQ_TAD",
            "NOME_PESSOA_EMBARGADA",
            "CPF_CNPJ_EMBARGADO",
            "NOME_IMOVEL",
            "MUNICIPIO",
            "COD_MUNICIPIO",
            "UF",
            "GEOM_AREA_EMBARGADA",
            "nome_uc",
            "telefone",
            "email_contato",
        ]
    )
    limpo, fora = P.remover_colunas_pessoais(df)
    assert set(fora) == {"NOME_PESSOA_EMBARGADA", "CPF_CNPJ_EMBARGADO", "NOME_IMOVEL", "telefone", "email_contato"}
    assert {"SEQ_TAD", "MUNICIPIO", "COD_MUNICIPIO", "UF", "GEOM_AREA_EMBARGADA", "nome_uc"} <= set(limpo.columns)


def test_varredura_acha_e_mascara(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text(f"cod,doc\n1,{fmt_cpf(CPF)}\n2,{CNPJ}\n3,189.99087022873272\n")
    achados = P.varrer([f])
    assert [(a.linha, a.tipo) for a in achados] == [(2, "CPF"), (3, "CNPJ")]
    assert all(CPF not in a.trecho and CNPJ not in a.trecho for a in achados)


def test_repositorio_sem_cpf_cnpj():
    arquivos = subprocess.run(["git", "ls-files"], cwd=RAIZ_REPO, capture_output=True, text=True).stdout.split()
    achados = P.varrer([RAIZ_REPO / a for a in arquivos])
    assert achados == [], achados


def test_documento_no_identificador_com_prefixo_e_formatacao():
    from raiz.privacidade import documento_em_identificador

    cpf_fmt = f"{CPF[:3]}.{CPF[3:6]}.{CPF[6:9]}-{CPF[9:]}"
    for v in (CPF, CNPJ, cpf_fmt):
        assert documento_em_identificador("modelo-" + v)
    assert not documento_em_identificador("restauracao-2026d+a84f9789")
