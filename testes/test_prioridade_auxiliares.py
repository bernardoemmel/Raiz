"""A prioridade dos funis não bloqueia lotes ou catálogo nem altera suas referências."""

import copy

import pytest

from testes.test_processar_estados import F, O, _pedido, _run

REF_ATUAL = "a" * 40
REF_FUNIL = "b" * 40


def _estado():
    return {
        **F.vazio(),
        "prioridade_funil": {"frente": ["TO", "MA", "MT"], "prontos": [], "ref": REF_FUNIL},
    }


def _auxiliar(unidade, origem="novo", ref=REF_ATUAL):
    return {
        **_pedido(unidade, origem),
        "ref": ref,
        "repetir": False,
        "escopo": "rodada",
        "tentativa": 1,
    }


@pytest.mark.parametrize("unidade", ["catalogo", "lote-pa-vaga-0"])
def test_prioridade_admite_auxiliar_sem_consumir_fila_ou_interromper_reserva(unidade):
    estado = _estado()
    pendente = {**_pedido("AM-1001", "anterior"), "ref": REF_FUNIL}
    ativo = {**_pedido("TO-1001", "motor"), "ref": REF_FUNIL}
    reserva = {"run_id": "motor", "unidade": ativo["unidade"], "pedido": ativo}
    estado.update(planejadores=["motor", "novo"], fila=[pendente], reservas=[reserva])
    runs = {"motor": _run("TO-1001"), "novo": {**_run(), "run_attempt": 1}}
    anterior = copy.deepcopy((reserva, runs, estado["prioridade_funil"]))
    auxiliar = _auxiliar(unidade)

    assert F.admitir(estado, runs, "novo", [auxiliar], O._e_unidade, consumir_fila=False) == [auxiliar]
    assert estado["fila"] == [pendente]
    assert estado["reservas"][0] == anterior[0]
    assert runs == anterior[1]
    assert estado["prioridade_funil"] == anterior[2]
    assert len(estado["reservas"]) == 2


def test_auxiliares_ativos_nao_ocupam_a_terceira_uf_do_motor():
    estado = _estado()
    unidades = ["TO-1001", "MA-1001", "catalogo", "lote-pa-vaga-0"]
    runs = {"novo": _run()}
    estado["planejadores"] = ["novo"]
    for numero, unidade in enumerate(unidades):
        run_id = f"ativo-{numero}"
        pedido = {**_pedido(unidade, run_id), "ref": REF_FUNIL} if O._e_unidade(unidade) else _auxiliar(unidade, run_id)
        estado["planejadores"].append(run_id)
        estado["reservas"].append({"run_id": run_id, "unidade": unidade, "pedido": pedido})
        runs[run_id] = {**_run(unidade), "run_attempt": 1}
    anteriores = copy.deepcopy(estado["reservas"])
    terceiro = {**_pedido("MT-1001", "novo"), "ref": REF_FUNIL}
    fora_da_frente = {**_pedido("AM-1001", "novo"), "ref": REF_FUNIL}

    assert F.admitir(estado, runs, "novo", [terceiro, fora_da_frente], O._e_unidade) == [terceiro]
    assert estado["reservas"][:4] == anteriores
    assert len(estado["reservas"]) == 5


def test_auxiliares_contam_no_teto_global_mesmo_com_prioridade_funil():
    estado = _estado()
    estado["planejadores"] = ["novo"]
    unidades_motor = [f"SP-{i}" for i in range(1, 7)] + [f"RS-{i}" for i in range(1, 6)] + ["PR-1", "PR-2"]
    runs = {"motor": _run(*unidades_motor), "novo": {**_run(), "run_attempt": 1}}
    anteriores = copy.deepcopy(runs)
    candidatos = [_auxiliar(u) for u in ("catalogo", "lote-pa-vaga-0", "lote-pa-vaga-1")]

    assert F.admitir(estado, runs, "novo", candidatos, O._e_unidade, consumir_fila=False) == candidatos[:2]
    assert len(unidades_motor) + len(estado["reservas"]) == F.TETO == 15
    assert F.admitir(estado, runs, "novo", candidatos[2:], O._e_unidade, consumir_fila=False) == []
    assert runs == anteriores


@pytest.mark.parametrize("unidade", ["catalogo", "lote-pa-vaga-0"])
def test_bloqueio_auxiliar_de_outra_versao_impede_nova_admissao_automatica(unidade):
    estado = _estado()
    bloqueado = {**_auxiliar(unidade, "anterior", "c" * 40), "bloqueado": "Aguardando correção explícita."}
    estado.update(planejadores=["novo"], fila=[bloqueado])
    anterior = copy.deepcopy(bloqueado)
    runs = {"novo": {**_run(), "run_attempt": 1}}

    assert F.admitir(estado, runs, "novo", [_auxiliar(unidade)], O._e_unidade, consumir_fila=False) == []
    assert estado["fila"] == [anterior]
    assert estado["reservas"] == []
    # Uma ordem explícita nova mantém a possibilidade de retomar após a correção.
    explicito = _auxiliar(unidade, "pedido-explicito")
    F.enfileirar(estado, [explicito])
    assert F.admitir(estado, runs, "novo", [], O._e_unidade) == [explicito]
    assert estado["fila"] == [anterior]


@pytest.mark.parametrize("explicito", [False, True], ids=["automatico", "explicito"])
@pytest.mark.parametrize("unidade", ["catalogo", "lote-pa-vaga-0"])
def test_reservar_preserva_ref_auxiliar_e_fixa_somente_ref_da_uf(monkeypatch, explicito, unidade):
    estado = _estado()
    propostas = []

    class Repositorio:
        versao = 0

        def ler(self):
            return str(self.versao), copy.deepcopy(estado)

        def trocar(self, anterior, proposta):
            assert anterior == str(self.versao)
            self.versao += 1
            propostas.append(copy.deepcopy(proposta))
            estado.clear()
            estado.update(proposta)
            return True

    repo = Repositorio()
    monkeypatch.setenv("GITHUB_RUN_ID", "novo")
    monkeypatch.setenv("GITHUB_REPOSITORY", "exemplo/raiz")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(F, "Repositorio", lambda: repo)
    monkeypatch.setattr(F, "comando", lambda args: REF_ATUAL)
    monkeypatch.setattr(F, "rodadas", lambda *args, **kwargs: {"novo": _run()})
    unidades = [unidade, "TO-1001"]

    escolhidos = F.reservar(
        candidatos=[] if explicito else unidades,
        pedidos=unidades if explicito else [],
        refazer=(),
        e_unidade=O._e_unidade,
        limite=15,
    )

    esperado = {unidade: REF_ATUAL, "TO-1001": REF_FUNIL}
    assert {p["unidade"]: p["ref"] for p in escolhidos} == esperado
    assert {r["unidade"]: r["pedido"]["ref"] for r in estado["reservas"]} == esperado
    assert estado["fila"] == []
    if explicito:
        assert {p["unidade"]: p["ref"] for p in propostas[0]["fila"]} == esperado
    assert estado["prioridade_funil"]["ref"] == REF_FUNIL
