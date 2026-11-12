"""Chamada às regras em Catala (referência legal) com os dados do motor.

As regras em Catala (raiz/regras/catala/) são compiladas para Python em raiz/regras/gerado/. Este módulo converte uma
linha do motor (colunas de docs/colunas.md) nos tipos do Catala e devolve números comuns. Os números do Catala são
frações exatas; o float só aparece na saída.

É lento (um imóvel por vez) e serve para o laudo, a explicação e a conferência com raiz/regras/federal.py, que é o
caminho vetorizado para o país inteiro.
"""

from __future__ import annotations

from collections.abc import Mapping
from fractions import Fraction

from raiz.regras import Parametros, parametros
from raiz.regras.gerado import Codigo_florestal as C
from raiz.regras.gerado import catala_runtime as rt

_POS = rt.SourcePosition("raiz/regras/referencia.py", 0, 0, 0, 0, [])
SAIDAS_LAUDO = ("pct_RL", "pct_RL_alem", "deficit_RL_ha", "deficit_RL_alem_ha", "alem_RL_ha", "app_recompor_ha")


def _dec(x) -> rt.Decimal:
    """Float do motor para decimal exato do Catala, pela representação curta (35.781504 vira 35781504/10^6)."""
    return rt.Decimal(Fraction(repr(float(x))))


def _f(x) -> float:
    return float(Fraction(x.numerator, x.denominator))


def _opcao(valor) -> rt.Option:
    """Variável de contexto do Catala: None mantém o padrão da lei; um valor substitui."""
    return rt.Option(None) if valor is None else rt.Option(rt.CatalaTuple(valor, _POS))


def vegetacao(bioma: str) -> C.Vegetacao:
    """Mesma leitura do motor e de Parametros.rl_percentual: Amazônia é floresta, Cerrado é cerrado, o resto campos."""
    codigo = {"Amazônia": C.Vegetacao.Code.Floresta, "Cerrado": C.Vegetacao.Code.Cerrado}.get(
        bioma, C.Vegetacao.Code.CamposGerais
    )
    return C.Vegetacao(codigo, rt.Unit())


def imovel(linha: Mapping, p: Parametros | None = None, data=None) -> C.Imovel:
    p = p or parametros()
    amazonia = str(linha["uf"]).upper() in p.valor("amazonia_legal_ufs", data)
    return C.Imovel(
        na_amazonia_legal=rt.Bool(amazonia),
        vegetacao=vegetacao(linha["bioma"]),
        area_ha=_dec(linha["ha"]),
        modulos_fiscais=_dec(linha["m_fiscal"]),
        nao_floresta_ha=_dec(linha.get("nao_floresta_ha", 0.0)),
        floresta_remanescente_ha=_dec(linha["floresta_rem_ha"]),
        area_aberta_ha=_dec(linha["desm_total_ha"]),
    )


def laudo(linha: Mapping, reducao_art12_par4_ou_par5: bool = True, p: Parametros | None = None, data=None) -> dict:
    """Saídas do laudo federal com os nomes do motor. Por padrão usa o cenário do motor (redução a 50% para
    recomposição em floresta da Amazônia Legal, como em pct_RL_alem)."""
    r = C.laudo_federal(
        C.LaudoFederalIn(
            imovel_in=imovel(linha, p, data),
            app_escadinha_ha_in=_dec(linha.get("app_escadinha_ha", 0.0)),
            reducao_art12_par4_ou_par5_in=rt.Bool(reducao_art12_par4_ou_par5),
        )
    )
    return {k: _f(getattr(r, k)) for k in SAIDAS_LAUDO}


def reserva_legal(
    linha: Mapping,
    reducao_art12_par4_ou_par5: bool | None = None,
    app_conservada_fora_da_floresta_ha: float | None = None,
    supressao_respeitou_lei_da_epoca: bool | None = None,
    p: Parametros | None = None,
    data=None,
) -> dict:
    """Reserva legal com todos os fatos opcionais (arts. 12, 15, 67 e 68). Fato não informado: o padrão da lei."""
    art15 = app_conservada_fora_da_floresta_ha is not None
    r = C.reserva_legal(
        C.ReservaLegalIn(
            imovel_in=imovel(linha, p, data),
            reducao_art12_par4_ou_par5_in=_opcao(
                None if reducao_art12_par4_ou_par5 is None else rt.Bool(reducao_art12_par4_ou_par5)
            ),
            computa_app_art15_in=_opcao(rt.Bool(True) if art15 else None),
            app_conservada_fora_da_floresta_ha_in=_opcao(_dec(app_conservada_fora_da_floresta_ha) if art15 else None),
            supressao_respeitou_lei_da_epoca_in=_opcao(
                None if supressao_respeitou_lei_da_epoca is None else rt.Bool(supressao_respeitou_lei_da_epoca)
            ),
        )
    )
    saida = {}
    for k in C.ReservaLegal.fields:
        v = getattr(r, k)
        saida[k] = bool(v) if isinstance(v, rt.Bool) else _f(v)
    return saida


def faixa_app_m(
    corpo: str,
    m_fiscal: float,
    consolidada: bool,
    largura_rio_m: float | None = None,
    superficie_ha: float | None = None,
    urbana: bool = False,
) -> float:
    """Faixa de APP (art. 4º ou escadinha do art. 61-A). corpo: rio, nascente, lago ou vereda."""
    K = C.CorpoDagua.Code
    if corpo == "rio":
        payload = C.Rio(largura_conhecida=rt.Bool(largura_rio_m is not None), largura_m=_dec(largura_rio_m or 0.0))
        c = C.CorpoDagua(K.CursoDagua, payload)
    elif corpo == "lago":
        c = C.CorpoDagua(K.LagoNatural, C.Lago(superficie_ha=_dec(superficie_ha or 0.0)))
    else:
        c = C.CorpoDagua({"nascente": K.Nascente, "vereda": K.Vereda}[corpo], rt.Unit())
    r = C.faixa_app(
        C.FaixaAppIn(
            corpo_in=c,
            modulos_fiscais_in=_dec(m_fiscal),
            area_consolidada_in=rt.Bool(consolidada),
            zona_urbana_in=_opcao(rt.Bool(True) if urbana else None),
        )
    )
    return _f(r.faixa_m)
