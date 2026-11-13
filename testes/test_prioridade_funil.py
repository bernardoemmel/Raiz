"""Conclusão dos 27 funis: três UFs, quinze unidades e nenhuma manutenção."""

import copy

import pytest

from testes.test_processar_estados import F, O, S, _completo, _pedido, _run


def test_subdivisoes_preservam_fatias_antigas_e_cobrem_uf_sem_sobreposicao(monkeypatch):
    antigos = {uf: {i: S.municipios_da_fatia(uf, i) for i in range(1, S.n_fatias(uf) + 1)} for uf in S.TOTAL_IBGE}
    monkeypatch.setenv("RAIZ_PRIORIDADE_FUNIL", "1")
    for uf in S.TOTAL_IBGE:
        unidades = S.unidades(uf)
        partes = [set(S.municipios_da_fatia(uf, S.ler_unidade(u)[1])) for u in unidades]
        assert sum(map(len, partes)) == len(set().union(*partes)) == S.TOTAL_IBGE[uf]
        assert all(partes)
        for i, municipios in antigos[uf].items():
            assert S.municipios_da_fatia(uf, i) == municipios
        if S.n_fatias(uf) < 5 and S.TOTAL_IBGE[uf] >= 5:
            assert len(unidades) == 5
    assert S.unidade_ancestral("TO-1001") == "TO-1"
    assert S.unidade_ancestral("AM-1001") == "AM"
    assert S.unidade_ancestral("MG-3") is None


def test_primeiras_tres_ufs_enchem_quinze_e_nao_trocam_quando_uma_fatia_termina(monkeypatch):
    monkeypatch.setenv("RAIZ_PRIORIDADE_FUNIL", "1")
    estado = {**F.vazio(), "planejadores": ["1", "2", "3"]}
    candidatos = [_pedido(u) for uf in F.ORDEM_FUNIL for u in S.unidades(uf)]
    runs = {str(i): _run() for i in (1, 2, 3)}
    escolhidos = F.admitir(estado, runs, "1", candidatos, O._e_unidade, funis_prontos=set())
    assert len(escolhidos) == 15
    assert {p["unidade"].split("-")[0] for p in escolhidos} == {"TO", "MA", "MT"}
    frente = copy.deepcopy(estado["prioridade_funil"])
    runs["1"] = _run(*(p["unidade"] for p in escolhidos), status="completed", conclusion="success")
    assert not F.admitir(estado, runs, "2", [_pedido("AM-1001", "2")], O._e_unidade, funis_prontos=set())
    assert estado["prioridade_funil"] == frente
    assert F.admitir(estado, {**runs, "3": _run()}, "3", [_pedido("AM-1001", "3")], O._e_unidade,
                     funis_prontos={"TO"})  # fmt: skip
    assert estado["prioridade_funil"]["frente"] == ["MA", "MT", "AM"]


def test_reservas_legadas_de_quatro_ufs_terminam_sem_admitir_quinta():
    estado = {**F.vazio(), "planejadores": ["novo"]}
    runs = {"legado": _run("SP-1", "PR-1", "SC-1", "RS-1"), "novo": _run()}
    assert not F.admitir(estado, runs, "novo", [_pedido("TO-1001")], O._e_unidade, funis_prontos=set())
    assert runs["legado"]["status"] == "in_progress"


def test_manutencao_so_volta_depois_dos_27_funis():
    estado = {**F.vazio(), "planejadores": ["1"],
              "prioridade_funil": {"frente": ["DF"], "prontos": [], "ref": "b" * 40}}  # fmt: skip
    pedido = _pedido("AC")
    assert F.admitir(estado, {"1": _run()}, "1", [pedido], O._e_unidade,
                     funis_prontos=set(F.ORDEM_FUNIL), ref_funil="c" * 40) == [pedido]  # fmt: skip
    assert estado["prioridade_funil"]["frente"] == []
    assert estado["prioridade_funil"]["ref"] is None


def test_pedido_antigo_manutencao_e_nova_versao_ficam_guardados():
    velho, pronto, refazer = _pedido("TO-1"), _pedido("AC"), _pedido("TO-1001", refazer="funil")
    novo = {**_pedido("TO-1001", "2"), "ref": "b" * 40}
    estado = {**F.vazio(), "planejadores": ["2"], "fila": [velho, pronto, refazer, novo]}
    assert F.admitir(estado, {"2": _run()}, "2", [], O._e_unidade, funis_prontos={"AC"}, ref_funil="b" * 40) == [novo]
    assert estado["fila"] == [velho, pronto, refazer]
    # A próxima mudança da main não troca a versão fixada para esta conclusão.
    F.admitir(estado, {"2": _run("TO-1001"), "3": _run()}, "3", [], O._e_unidade,
              funis_prontos={"AC"}, ref_funil="c" * 40)  # fmt: skip
    assert estado["prioridade_funil"]["ref"] == "b" * 40


@pytest.mark.parametrize("ativa,proxima", [("TO-1", "TO-1001"), ("TO-1002", "TO-1"), ("AM", "AM-1001")])
def test_fatia_antiga_e_subdivisao_nao_rodam_juntas(ativa, proxima):
    assert F.ocupada(proxima, {ativa})
    assert not F.ocupada("TO-1003", {"TO-1001"})
    assert not F.ocupada("TO-2001", {"TO-1"})


def test_plano_ignora_manutencao_mesmo_pedida_ou_com_codigo_novo(monkeypatch):
    estados = {uf: _completo(uf) for uf in S.TOTAL_IBGE if uf not in {"TO", "MA", "MT", "AM"}}
    estados["AC"].update(completo=False, versoes={"funil": "antiga"}, faltam={"ficha": 22})
    monkeypatch.setenv("RAIZ_PRIORIDADE_FUNIL", "1")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(S, "ler_manifesto", lambda: {"estados": estados})
    monkeypatch.setattr(O, "versoes_executor", lambda: {"funil": "nova"})
    monkeypatch.setattr(O, "ufs_ativas", lambda: (set(), 0))
    assert {u.split("-")[0] for u in O.planejar([], set())} == {"TO", "MA", "MT"}
    assert len(O.planejar([], set())) == 15
    assert all(not u.startswith("AC") for u in O.planejar(["AC", "TO-1001"], set()))
    with pytest.raises(ValueError, match="manutenção suspensa"):
        O.planejar(["TO-1001"], {"funil"})
