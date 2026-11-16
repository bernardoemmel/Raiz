"""Fatos novos para o vigia do pedido salvo: desmatamento e embargo da vigilância, matrícula cancelada das certidões.
Fica de fora o que é falso, borda, linha de base, antigo, fogo e embargo já retirado."""

from __future__ import annotations

import datetime as dt

import pandas as pd

from raiz.vigilancia import aprendizado, cruzamento
from raiz.vigilancia.armazem import Armazem
from raiz.vigilancia.pedidos import fatos, fatos_matricula, fatos_vigilancia
from raiz.vigilancia.testes.conftest import COD_A, COD_B, HOJE, ocorrencia, ocorrencias, quadrado_m

DESDE = dt.date(2026, 11, 1)


def _armazem(tmp_path, poligonos, regras) -> Armazem:
    oc = ocorrencias(
        ocorrencia("deter", "novo", "desmatamento_cr", quadrado_m(100, 100, 200), dt.date(2026, 11, 3), HOJE),
        ocorrencia("deter", "degr", "cs_desordenado", quadrado_m(400, 100, 200), dt.date(2026, 11, 4), HOJE),
        ocorrencia("deter", "falso", "desmatamento_cr", quadrado_m(100, 600, 200), dt.date(2026, 11, 5), HOJE),
        ocorrencia("firms", "N20|2026-11-11|0400", "foco_alta", quadrado_m(700, 700, 300), HOJE, HOJE),
        ocorrencia("ibama_embargo", "777", "embargo", quadrado_m(1100, 0, 50), dt.date(2026, 11, 10), HOJE),
        ocorrencia("ibama_embargo", "888", "embargo", quadrado_m(600, 600, 50), dt.date(2026, 11, 10), HOJE),
        # linha de base: publicado há anos, achado agora na primeira leitura
        ocorrencia(
            "prodes", "velho", "desmatamento", quadrado_m(800, 100, 150), dt.date(2019, 7, 1), dt.date(2019, 10, 1)
        ),  # fmt: skip
    )
    al = cruzamento.montar_alertas(oc, cruzamento.cruzar_imoveis(oc, poligonos), regras, HOJE)
    # um alerta visto antes do pedido não é fato novo
    antigo = cruzamento.montar_alertas(
        ocorrencias(
            ocorrencia(
                "deter",
                "antes",
                "desmatamento_cr",
                quadrado_m(300, 300, 100),
                dt.date(2026, 10, 1),
                dt.date(2026, 10, 2),
            )
        ),  # fmt: skip
        cruzamento.cruzar_imoveis(
            ocorrencias(
                ocorrencia(
                    "deter",
                    "antes",
                    "desmatamento_cr",
                    quadrado_m(300, 300, 100),
                    dt.date(2026, 10, 1),
                    dt.date(2026, 10, 2),
                )
            ),  # fmt: skip
            poligonos,
        ),
        regras,
        dt.date(2026, 10, 5),
    )
    arm = Armazem(tmp_path / "estado")
    arm.gravar_alertas(pd.concat([al, antigo], ignore_index=True))
    falso = al[al.chave == "falso"].iloc[0]["alerta_id"]
    arm.gravar_marcacoes([aprendizado.marcacao(falso, False, "campo", "fundador")])
    arm.gravar_espelho_ibama(
        pd.DataFrame(
            {
                "seq_tad": ["777", "888"],
                "ativo": [True, False],
                "hash": ["a", "b"],
                "cancelado": [False, False],
                "desembargado": [False, True],
            }
        )  # fmt: skip
    )
    return arm


def test_fatos_da_vigilancia(tmp_path, poligonos, regras):
    arm = _armazem(tmp_path, poligonos, regras)
    f = fatos_vigilancia([COD_A, COD_B], DESDE, arm)
    por = {(x.cod_imovel, x.motivo, x.detalhe.get("tipo")) for x in f}
    assert por == {
        (COD_A, "desmatamento", "desmatamento"),
        (COD_A, "desmatamento", "degradacao"),
        (COD_A, "fogo", "fogo"),
        (COD_B, "embargo", "embargo"),  # o 777 está ativo; o 888 foi desembargado
    }
    d = next(x for x in f if x.detalhe.get("tipo") == "desmatamento")
    assert d.chave.startswith("vigilancia:") and d.data == dt.date(2026, 11, 3)
    assert "derrubada" in d.texto and "03/11/2026" in d.texto and "DETER" in d.texto
    assert d.detalhe["fonte"] == "deter" and d.detalhe["area_ha"] > 0
    assert "não confirma área queimada" in next(x.texto for x in f if x.motivo == "fogo")
    # mesma leitura de novo: mesmas chaves (o vigia não repete)
    assert [x.chave for x in fatos_vigilancia([COD_A, COD_B], DESDE, arm)] == [x.chave for x in f]
    # a fazenda fora do pedido não entra; pedido salvo depois de tudo não vê nada
    assert fatos_vigilancia([COD_B], DESDE, arm)[0].cod_imovel == COD_B
    assert fatos_vigilancia([COD_A], dt.date(2026, 11, 13), arm) == []


def test_matricula_cancelada_das_certidoes(tmp_path):
    arq = tmp_path / "matricula_1507300.csv"
    pd.DataFrame(
        {
            "cod_imovel": [COD_A, COD_B],
            "matricula_situacao": ["cancelada", "conferida"],
            "matricula_lido_em": ["2026-11-10T14:00:00", "2026-11-10T14:00:00"],
            "coluna_nova": [1, 2],
        }
    ).to_csv(arq, index=False)
    f = fatos_matricula(
        [COD_A, COD_B], achar=lambda tabela, mun: arq if (tabela, mun) == ("matricula", "1507300") else None
    )
    assert [(x.cod_imovel, x.motivo) for x in f] == [(COD_A, "matricula_cancelada")]
    assert f[0].chave == f"matricula:{COD_A}:2026-11-10T14:00:00" and "10/11/2026" in f[0].texto
    assert fatos_matricula([COD_A], achar=lambda t, m: None) == []


def test_fatos_juntos_e_fonte_fora_do_ar(tmp_path, poligonos, regras):
    arm = _armazem(tmp_path, poligonos, regras)

    def quebrado(tabela, mun):
        raise OSError("disco fora")

    f = fatos([COD_A, COD_B], DESDE, armazem=arm, achar=quebrado)  # certidões fora: a vigilância continua
    assert {x.motivo for x in f} == {"desmatamento", "embargo", "fogo"}
