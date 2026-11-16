"""Retomar o catálogo mantém a cota, mesmo com snapshots antigos do Actions."""

import copy

import pytest

from scripts import publicar_metadados as P

F, RODAR = P.modulos_fila()


class RepositorioMemoria:
    def __init__(self, estado):
        self.estado = estado
        self.versao = 0

    def ler(self):
        return str(self.versao), copy.deepcopy(self.estado)

    def trocar(self, anterior, proposta):
        if anterior != str(self.versao):
            return False
        self.estado.clear()
        self.estado.update(proposta)
        self.versao += 1
        return True


@pytest.fixture
def ambiente(monkeypatch):
    for nome, valor in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_JOB": "catalogo",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_REPOSITORY": "exemplo/raiz",
    }.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.setattr(P, "conferir_processamento_seguro", lambda: {})
    monkeypatch.setattr(F, "comando", lambda args: "a" * 40)
    monkeypatch.setattr(F.time, "sleep", lambda _: None)


def _estado(*, legado=False):
    pedido = {"id": "123/catalogo/0", "unidade": "catalogo", "repetir": False, "ref": "a" * 40}
    if not legado:
        pedido.update(escopo="rodada", tentativa=1)
    return {
        **F.vazio(),
        "planejadores": ["123", "novo"],
        "reservas": [{"run_id": "123", "unidade": "catalogo", "pedido": pedido}],
    }


def _runs(*, tentativa=1, status="completed"):
    unidades = [f"SP-{i}" for i in range(1, 7)] + [f"RS-{i}" for i in range(1, 6)] + [f"PR-{i}" for i in range(1, 4)]
    return {
        "123": {
            "status": status,
            "run_attempt": tentativa,
            "jobs": [{"name": "catalogo", "status": status, "conclusion": "failure"}],
        },
        "novo": {"status": "in_progress", "jobs": []},
        "motor": {"status": "in_progress", "jobs": [{"name": u, "status": "in_progress"} for u in unidades]},
    }


@pytest.mark.parametrize("legado", [False, True])
def test_rerun_confirma_cas_e_snapshot_antigo_nao_admite_decimo_sexto_job(ambiente, monkeypatch, legado):
    estado = _estado(legado=legado)
    repo = RepositorioMemoria(estado)
    monkeypatch.setattr(F, "Repositorio", lambda: repo)

    P.reservar_vaga()
    P.confirmar_reserva()
    assert repo.versao == 2
    assert estado["reservas"][0]["pedido"]["tentativa"] == 2
    candidato = {"id": "novo/MG-1", "unidade": "MG-1"}
    assert F.admitir(estado, _runs(), "novo", [candidato], RODAR._e_unidade) == []
    assert len(estado["reservas"]) == 1

    assert F.admitir(estado, _runs(tentativa=2), "novo", [candidato], RODAR._e_unidade) == [candidato]
    assert all(r["unidade"] != "catalogo" for r in estado["reservas"])
    assert estado["fila"] == []  # catálogo auxiliar não é reenfileirado como estado


def test_primeira_reserva_guarda_tentativa_e_dura_ate_fim_da_rodada(ambiente, monkeypatch):
    estado = F.vazio()
    estado["planejadores"] = ["novo"]
    repo = RepositorioMemoria(estado)
    monkeypatch.setattr(F, "Repositorio", lambda: repo)
    monkeypatch.setattr(F, "rodadas", lambda *a, **kw: _runs(tentativa=2, status="in_progress"))

    P.reservar_vaga()
    (reserva,) = estado["reservas"]
    assert reserva["unidade"] == "catalogo"
    assert reserva["pedido"]["escopo"] == "rodada"
    assert reserva["pedido"]["tentativa"] == 2
    runs = _runs(tentativa=2, status="in_progress")
    runs["123"]["jobs"][0]["status"] = "completed"
    F.reconciliar(estado, runs, RODAR._e_unidade)
    assert len(estado["reservas"]) == 1


def test_perder_cota_entre_leitura_e_cas_recusa_retomada(ambiente, monkeypatch):
    estado = _estado(legado=True)

    class RepositorioConcorrido(RepositorioMemoria):
        def trocar(self, anterior, proposta):
            if self.versao == 0:
                self.estado["reservas"] = []
                self.versao += 1
                return False
            return super().trocar(anterior, proposta)

    monkeypatch.setattr(F, "Repositorio", lambda: repo)
    repo = RepositorioConcorrido(estado)
    with pytest.raises(RuntimeError, match="sem reserva global"):
        P.reservar_vaga()
    assert estado["reservas"] == []


@pytest.mark.parametrize("tentativa", ["", "0", "-1", "inválida"])
def test_tentativa_invalida_nao_altera_reserva(ambiente, monkeypatch, tentativa):
    repo = RepositorioMemoria(_estado())
    monkeypatch.setattr(F, "Repositorio", lambda: repo)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", tentativa)
    with pytest.raises(RuntimeError, match="tentativa do catálogo não confirmada"):
        P.confirmar_reserva()
    assert repo.versao == 0


def test_tentativa_antiga_nao_reduz_reserva_ja_confirmada(ambiente, monkeypatch):
    estado = _estado()
    estado["reservas"][0]["pedido"]["tentativa"] = 3
    repo = RepositorioMemoria(estado)
    monkeypatch.setattr(F, "Repositorio", lambda: repo)
    with pytest.raises(RuntimeError, match="incompatível com a tentativa"):
        P.confirmar_reserva()
    assert repo.versao == 0
