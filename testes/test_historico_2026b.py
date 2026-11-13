"""Integridade, semântica e isolamento da reconstrução fechada de 2026b."""

import hashlib
import json
import shutil
from fractions import Fraction

import numpy as np
import pytest

from raiz.regras import historico

VERSAO = "restauracao-2026b+cenarios-2026b+dbc2776a"
VERSAO_2026C = "restauracao-2026c+421970fd"
SHA_COMBINADO = "dbc2776aee416750bf0665599421640101ba3aed46386bb15a703b4ccf787dd4"
SHA_MANIFESTO = "ef4e3d9c2b2c8a1112c5b21b95558db4718c3321e7212e7d51b6ff93cd4a9b52"
SHA_CODIGO = "7620c73e6fbeff00db6545ca010d0893a5ad4cc30831505e63b80d0e712d35b3"
SHA_CURVA = "e71f4b8aeb2cf68782fffffaf20b41d6e3f101b1837054158227815c23ca2c13"
ERRO = "registro histórico de restauração inválido"


def test_registro_2026b_preserva_formato_separado_e_proveniencia():
    r, p = historico.carregar(VERSAO)
    assert r["versao"] == "restauracao-2026b"
    assert r["versao_completa"] == VERSAO
    assert r["cenarios"]["versao"] == "cenarios-2026b"
    assert r["cenarios"]["padrao"] == "central_r11"
    assert r["calibracao"] == {}
    assert not ({"lote", "edital", "padrao", "monte_carlo"} & r.keys())
    assert "incerteza_captura" not in r["captura_curva"]
    assert p == {
        "regra_source_commit": "deec7a776378056509b2cd37e0894f4d00922b84",
        "regra_source_sha256": SHA_COMBINADO,
        "regra_source_versao": VERSAO,
        "regra_source_manifesto_sha256": SHA_MANIFESTO,
        "versao_tarefa_referencia": "desenvolvedor-4e142d4bfca2",
        "regra_source_perfil": "separado_2026b",
        "regra_source_codigo_sha256": SHA_CODIGO,
        "regra_source_codigo_git_blob": "705ffeea80ec63939fcf67aa2a55507d9c7b06a4",
        "regra_source_curva_ast_sha256": SHA_CURVA,
    }


def test_manifesto_2026b_registra_alcance_e_limite_da_prova():
    pasta = historico.PASTA / VERSAO
    bruto = (pasta / "manifesto.json").read_bytes()
    assert hashlib.sha256(bruto).hexdigest() == SHA_MANIFESTO
    m = json.loads(bruto)
    nomes = ["restauracao.yaml", "cenarios_restauracao.yaml", "restauracao_cambio.yaml"]
    assert m["arquivos_combinados"] == nomes
    assert hashlib.sha256(b"\n--\n".join((pasta / n).read_bytes() for n in nomes)).hexdigest() == SHA_COMBINADO
    assert m["codigo"]["raiz/restauracao.py"]["sha256"] == SHA_CODIGO
    assert m["ast"]["funcoes_sha256"]["forma_curva"] == SHA_CURVA
    assert m["sha256_tarefa"] == "4e142d4bfca2df0af9cc24d332c1984e4c4eed7f6be165ac267c60dea3f39750"
    a = m["auditoria_historica"]
    assert a["commits_examinados"] == 525 and a["refs_locais"] == 19
    assert a["total_compativeis"] == len(set(a["commits_compativeis"])) == 23
    assert m["commit"] in a["commits_compativeis"]
    assert a["sha256_combinados_distintos"] == [SHA_COMBINADO]
    assert all(len(blobs) == 1 for blobs in a["blobs_distintos_por_arquivo"].values())
    assert a["versoes_tarefa_distintas"] == [m["versao_tarefa"]]
    assert not a["calibracao_presente_em_compativeis"] and not a["edital_presente_em_compativeis"]
    assert "_versoes.json" in a["limite"]


def test_cenario_2026b_preserva_reserva_descontos_marcos_e_ptax_sem_defaults(monkeypatch):
    from raiz import restauracao as R

    def proibido(*args, **kwargs):
        pytest.fail("O registro fechado não deve consultar regras nem normalizadores atuais")

    for nome in ("regra", "cenario", "_normalizar", "forma_curva"):
        monkeypatch.setattr(R, nome, proibido)
    r, _ = historico.carregar(VERSAO)
    c = historico.cenario("central_r11", r)
    assert c["reserva_risco"] == 0.12
    assert c["linha_base_piso"] == c["vazamento"] == c["incerteza"] == 0.10
    assert c["prazo_anos"] == 25 and c["horizonte_anos"] == 40
    assert c["entregas_anos"] == [7, 12, 17, 22, 25]
    assert c["marcos_pct"] == [12, 30, 50, 70, 100]
    assert c["entregas_pos_contrato_anos"] == [30, 35, 40]
    assert c["cambio_brl_usd"] == 5.5606 and c["cambio_data"] == "2026-11-11"
    assert historico.forma_curva_2026b(r).shape == (41,)


def test_curva_2026b_reproduz_interpolacao_e_declinio_com_oraculo_racional():
    r, _ = historico.carregar(VERSAO)
    forma = historico.forma_curva_2026b(r)
    # Valores derivados com frações dos pontos (2, 0), (7, 13.44), (14, 30.29)
    # e do total 588.8; não são saídas do código histórico nem da função atual.
    esperados = {
        3: Fraction(21, 4600),
        7: Fraction(21, 920),
        8: Fraction(11093, 412160),
        14: Fraction(3029, 58880),
        15: Fraction(204625, 4133376),
        25: Fraction(124517, 4133376),
        40: Fraction(335, 317952),
    }
    assert forma.shape == (41,)
    assert np.array_equal(forma[:3], np.zeros(3))
    assert np.all(forma >= 0) and forma.sum() == pytest.approx(1, abs=1e-14)
    assert forma.argmax() == 14
    for ano, esperado in esperados.items():
        assert forma[ano] == pytest.approx(float(esperado), rel=1e-12, abs=1e-14)
    assert np.all(np.diff(forma[14:]) < 0)
    assert np.diff(forma[14:]) == pytest.approx(-float(Fraction(20027, 10333440)), rel=1e-12)
    assert forma[40] > 0
    acumulado = np.cumsum(forma)
    for ano, esperado in {
        7: Fraction(63, 920),
        12: Fraction(100539, 412160),
        17: Fraction(145397, 299520),
        22: Fraction(392963, 574080),
        25: Fraction(1075639, 1377792),
    }.items():
        assert acumulado[ano] == pytest.approx(float(esperado), rel=1e-12)


@pytest.mark.parametrize("versao", ["restauracao-2026b", VERSAO + "x", "restauracao-2026b+cenarios-2026b+dbc2776b"])
def test_registro_2026b_nao_aceita_prefixo_ou_versao_aproximada(versao):
    assert historico.carregar(versao) is None


@pytest.mark.parametrize(
    "nome",
    [
        "manifesto.json",
        "restauracao.yaml",
        "cenarios_restauracao.yaml",
        "restauracao_cambio.yaml",
        "restauracao_calibracao.yaml",
        "edital_profloresta.yaml",
    ],
)
def test_registro_2026b_adulterado_falha_sem_expor_conteudo(tmp_path, monkeypatch, nome):
    pasta = tmp_path / "registro"
    shutil.copytree(historico.PASTA / VERSAO, pasta / VERSAO)
    arquivo = pasta / VERSAO / nome
    arquivo.write_bytes((arquivo.read_bytes() if arquivo.exists() else b"") + b"\n# NAO_PUBLICAR\n")
    monkeypatch.setattr(historico, "PASTA", pasta)
    with pytest.raises(ValueError) as erro:
        historico.carregar(VERSAO)
    assert str(erro.value) == ERRO
    assert erro.value.__cause__ is None and erro.value.__suppress_context__


@pytest.mark.parametrize("alteracao", ["curva", "cenario", "versao", "campo_ausente"])
def test_regra_2026b_mutada_nao_eh_normalizada_nem_gera_curva(alteracao):
    r, _ = historico.carregar(VERSAO)
    if alteracao == "curva":
        r["captura_curva"]["total_referencia"] += 1
    elif alteracao == "cenario":
        r["cenarios"]["cenarios"]["central_r11"]["reserva_risco"]["valor"] = 0.20
    elif alteracao == "versao":
        r["versao_completa"] = "NAO_PUBLICAR"
    else:
        del r["cenarios"]["cenarios"]["central_r11"]["reserva_risco"]
    for acao in (lambda: historico.cenario("central_r11", r), lambda: historico.forma_curva_2026b(r)):
        with pytest.raises(ValueError, match=f"^{ERRO}$"):
            acao()


def test_curva_2026b_nao_aceita_regra_2026c_nem_cenario_alternativo():
    r, _ = historico.carregar(VERSAO_2026C)
    with pytest.raises(ValueError, match=f"^{ERRO}$"):
        historico.forma_curva_2026b(r)
    r, _ = historico.carregar(VERSAO)
    with pytest.raises(ValueError, match=f"^{ERRO}$"):
        historico.cenario("otimista_fundador", r)


def test_retorno_2026b_eh_independente_entre_chamadas():
    r, _ = historico.carregar(VERSAO)
    c = historico.cenario("central_r11", r)
    c["entregas_anos"][0] = 999
    assert historico.cenario("central_r11", r)["entregas_anos"][0] == 7
    r["captura_curva"]["total_referencia"] = 999
    novo, _ = historico.carregar(VERSAO)
    assert novo["captura_curva"]["total_referencia"] == 588.8
    forma = historico.forma_curva_2026b(novo)
    forma[0] = 999
    assert historico.forma_curva_2026b(novo)[0] == 0


def test_registro_2026c_mantem_bytes_e_resultado_anteriores():
    bruto = (historico.PASTA / VERSAO_2026C / "manifesto.json").read_bytes()
    assert hashlib.sha256(bruto).hexdigest() == "00a4d29577c96fde1a897f52e9e0dab96a300623831bb01b6592d9946be110d5"
    # Baseline capturada antes de incluir o ramo 2026b: regra + proveniência integrais.
    resultado = json.dumps(historico.carregar(VERSAO_2026C), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert (
        hashlib.sha256(resultado.encode()).hexdigest()
        == "16f6d0c46695ed8f4f62cbc43150b351dc8fda5118c3713cceab2e9b08cc120e"
    )
