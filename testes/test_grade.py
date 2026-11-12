"""Chave de bloco: mesma grade do motor (cache/tb) e mesmo resultado no Python e no banco."""

import shapely
from shapely.geometry import box

from raiz.funil import grade


def test_formato_igual_ao_cache_do_motor():
    # nomes reais de cache/tb do motor: ..._-46.5_-2.5.parquet, ..._-47.0_-3.0.parquet
    assert grade.chave(-46.3, -2.1) == "-46.5_-2.5"
    assert grade.chave(-46.7, -2.6) == "-47.0_-3.0"
    assert grade.chave(-0.2, 0.2) == "-0.5_0.0" and grade.chave(0.0, -0.0) == "0.0_0.0"
    assert grade.caixa("-47.0_-3.0") == (-47.0, -3.0, -46.5, -2.5)


def test_bloco_do_imovel_e_blocos_tocados():
    anel = box(-47.2, -3.2, -46.3, -2.9).difference(box(-46.9, -3.1, -46.6, -2.95))  # com buraco no meio
    tocados = grade.blocos_tocados(anel)
    assert sorted(tocados) == ["-46.5_-3.0", "-46.5_-3.5", "-47.0_-3.0", "-47.0_-3.5", "-47.5_-3.0", "-47.5_-3.5"]
    (ch,) = grade.chaves([anel])
    assert ch in tocados  # o bloco do imóvel é um dos que ele toca
    assert list(grade.chaves([None, shapely.Polygon()])) == [None, None]
