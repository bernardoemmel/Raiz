"""Camada estadual (E2 passo 5): regra estadual em vigor vem antes da federal, só na sua UF, zona e vigência."""

import shutil

import pytest
import yaml

from raiz.regras import PASTA, ParametroAusente, Parametros, parametros


def _tabela(tmp_path, regras_pi):
    shutil.copy(PASTA / "federal.yaml", tmp_path / "federal.yaml")
    (tmp_path / "estadual").mkdir(exist_ok=True)
    doc = {
        "versao": "regras-2026b",
        "nivel": "estadual",
        "uf": "PI",
        "parametros": {"rl_percentual": {"valores": regras_pi}},
    }
    (tmp_path / "estadual" / "PI.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True))
    return parametros.__wrapped__(tmp_path)


def _regra(**extra):
    return {
        "rotulos": {"bioma": "Cerrado"},
        "valor": 30,
        "artigo": "lei estadual (teste)",
        "urn_frag": None,
        "vigencia_inicio": "2020-01-01",
        "adotado_em": "2026-11-12",
        **extra,
    }


def test_estadual_vem_antes_da_federal(tmp_path):
    P = _tabela(tmp_path, [_regra()])
    assert P.rl_percentual("PI", "Cerrado") == 30
    assert P.rl_percentual("PI", "Caatinga") == 20  # outro bioma: federal
    assert P.rl_percentual("MA", "Cerrado") == 35  # outra UF: federal (MA é Amazônia Legal)
    assert P.rl_percentual("PI", "Cerrado", "2019-12-31") == 20  # antes da vigência estadual
    assert [v.area for v in P.estaduais_ativas()] == [{"uf": "PI"}]


def test_pendente_e_duplicada(tmp_path):
    P = _tabela(tmp_path, [_regra(pendente="conferir a norma")])
    assert P.rl_percentual("PI", "Cerrado") == 20 and P.estaduais_ativas() == []
    P2 = _tabela(tmp_path, [_regra(), _regra(valor=25)])
    with pytest.raises(ParametroAusente, match="regras estaduais"):
        P2.rl_percentual("PI", "Cerrado")


def test_zona_de_validade():
    P = parametros()
    # a redução do ZEE do Pará só vale na zona de consolidação, e está pendente: nunca devolvida
    assert (
        P.estadual("rl_percentual_reduzido", "PA", zona="zee_consolidacao", amazonia_legal=True, vegetacao="floresta")
        is None
    )


def test_tabela_real_sem_regra_estadual_ativa():
    """Hoje toda regra estadual está pendente. Quando uma entrar em vigor, ela precisa ir também para as regras em
    Catala (raiz/regras/catala/) e para os testes de conformidade; este teste lembra disso."""
    P = parametros()
    assert P.estaduais_ativas() == []
    ufs = {v.area["uf"] for v in P.valores if v.nivel == "estadual"}
    assert ufs == {"PA", "MT", "SP", "PI"}
    assert isinstance(P, Parametros)
