"""A mesma cota CAS cobre motor, catálogo e todas as fases do Lote."""

import copy
from pathlib import Path

import pytest
import yaml

from scripts import reservar_lote as L

F = L.F
RODAR = L.O
LEGADO = "3546687c66ec07ef9bd875d181efcff57ff1d312"


def _pedido(nome, origem="lote", tentativa=1):
    return {
        "id": f"{origem}/{nome}",
        "unidade": nome,
        "refazer": "",
        "continuacao": 0,
        "ref": "a" * 40,
        "repetir": False,
        "escopo": "rodada",
        "tentativa": tentativa,
    }


def _run(workflow="processar-estados.yml", status="in_progress", tentativa=1, jobs=()):
    return {
        "_workflow": workflow,
        "status": status,
        "run_attempt": tentativa,
        "jobs": [{"name": j, "status": "in_progress"} for j in jobs],
    }


def _motor(n):
    unidades = [f"SP-{i}" for i in range(1, 7)] + [f"RS-{i}" for i in range(1, 6)] + [f"PR-{i}" for i in range(1, 5)]
    return _run(jobs=unidades[:n])


def test_reserva_lote_usa_somente_vagas_livres_e_nao_consume_fila():
    estado = F.vazio()
    estado["planejadores"] = ["lote", "catalogo"]
    pendente = {"id": "motor/MG-1", "unidade": "MG-1"}
    estado["fila"] = [pendente]
    runs = {"motor": _motor(13), "lote": _run("retomar-lote-para.yml"), "catalogo": _run()}
    candidatos = [_pedido(f"lote-pa-vaga-{i}") for i in range(5)]
    assert len(F.admitir(estado, runs, "lote", candidatos, RODAR._e_unidade, consumir_fila=False)) == 2
    assert estado["fila"] == [pendente]
    assert F.admitir(estado, runs, "catalogo", [{"id": "catalogo", "unidade": "catalogo"}], RODAR._e_unidade) == []


@pytest.mark.parametrize("vencedor", ["lote", "motor"])
def test_cas_reconsulta_apos_disputa_entre_lote_e_motor(monkeypatch, vencedor):
    estado = {**F.vazio(), "planejadores": ["lote", "novo"]}
    runs = {"antigo": _motor(14), "lote": _run("retomar-lote-para.yml"), "novo": _run()}
    lote = [_pedido("lote-pa-vaga-0")]
    motor = [{"id": "novo/MG-1", "unidade": "MG-1"}]

    class Repositorio:
        versao = 0
        primeiro = True

        def ler(self):
            return str(self.versao), copy.deepcopy(estado)

        def trocar(self, anterior, proposta):
            if self.primeiro:
                self.primeiro = False
                F.admitir(
                    estado,
                    runs,
                    "lote" if vencedor == "lote" else "novo",
                    lote if vencedor == "lote" else motor,
                    RODAR._e_unidade,
                )
                self.versao += 1
                return False
            assert anterior == str(self.versao)
            estado.clear()
            estado.update(proposta)
            return True

    monkeypatch.setattr(F.time, "sleep", lambda _: None)
    perdedor = "novo" if vencedor == "lote" else "lote"
    escolhido = F.transacao(
        Repositorio(), lambda e: F.admitir(e, runs, perdedor, motor if vencedor == "lote" else lote, RODAR._e_unidade)
    )
    assert escolhido == [] and len(estado["reservas"]) == 1


@pytest.mark.parametrize("fase", ["preparar", "calcular (00)", "publicar"])
def test_legado_auditado_ocupa_cinco_durante_toda_rodada(fase):
    estado = {**F.vazio(), "planejadores": ["novo"]}
    runs = {"legado": {**_run("retomar-lote-para.yml", jobs=[fase]), "head_sha": LEGADO}, "novo": _run()}
    candidatos = [{"id": u, "unidade": u} for u in _motor(15)["jobs"] for u in [u["name"]]]
    assert len(F.admitir(estado, runs, "novo", candidatos, RODAR._e_unidade)) == 10


@pytest.mark.parametrize("workflow,sha", [("retomar-lote-para.yml", "b" * 40), ("lote-para.yml", LEGADO)])
def test_lote_legado_desconhecido_bloqueia_novas_admissoes(workflow, sha):
    estado = {**F.vazio(), "planejadores": ["novo"]}
    runs = {"legado": {**_run(workflow), "head_sha": sha}, "novo": _run()}
    assert F.admitir(estado, runs, "novo", [{"id": "MG", "unidade": "MG-1"}], RODAR._e_unidade) == []


@pytest.mark.parametrize("conclusao", ["success", "failure", "cancelled"])
def test_cota_so_sai_ao_fim_da_rodada_sem_reenfileirar_lote(conclusao):
    p = _pedido("lote-pa-vaga-0")
    estado = {
        **F.vazio(),
        "planejadores": ["lote"],
        "reservas": [{"run_id": "lote", "unidade": p["unidade"], "pedido": p}],
    }
    run = _run("retomar-lote-para.yml")
    run["jobs"] = [{"name": "calcular (00)", "status": "completed", "conclusion": "success"}]
    F.reconciliar(estado, {"lote": run}, RODAR._e_unidade)
    assert len(estado["reservas"]) == 1
    run.update(status="completed", conclusion=conclusao)
    F.reconciliar(estado, {"lote": run}, RODAR._e_unidade)
    assert estado["reservas"] == estado["fila"] == []


def _ambiente(monkeypatch):
    for nome, valor in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_JOB": "calcular",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_WORKFLOW_REF": "exemplo/raiz/.github/workflows/retomar-lote-para.yml@refs/heads/main",
    }.items():
        monkeypatch.setenv(nome, valor)


@pytest.mark.parametrize("ocupadas,esperadas", [(13, 2), (15, 0)])
def test_script_reserva_real_compartilha_cas_sem_consumir_pedido_motor(monkeypatch, ocupadas, esperadas):
    _ambiente(monkeypatch)
    monkeypatch.setenv("GITHUB_JOB", "preparar")
    monkeypatch.setenv("GITHUB_REPOSITORY", "exemplo/raiz")
    estado = F.vazio()
    pendente = {"id": "motor/MG-1", "unidade": "MG-1"}
    estado["fila"] = [pendente]

    class Repositorio:
        versao = 0

        def ler(self):
            return str(self.versao), copy.deepcopy(estado)

        def trocar(self, anterior, proposta):
            assert anterior == str(self.versao)
            self.versao += 1
            estado.clear()
            estado.update(proposta)
            return True

    repo = Repositorio()
    monkeypatch.setattr(F, "Repositorio", lambda: repo)
    monkeypatch.setattr(F, "comando", lambda args: "a" * 40)
    consultas = []

    def rodadas(*args, **kw):
        consultas.append(kw)
        return {"motor": _motor(ocupadas), "123": _run("retomar-lote-para.yml", tentativa=2)}

    monkeypatch.setattr(F, "rodadas", rodadas)
    if esperadas:
        assert L.reservar(5) == esperadas
        assert all(r["pedido"]["tentativa"] == 2 for r in estado["reservas"])
        assert all(r["pedido"]["repetir"] is False for r in estado["reservas"])
    else:
        with pytest.raises(RuntimeError, match="sem vaga global"):
            L.reservar(5)
    assert len(estado["reservas"]) == esperadas
    assert estado["fila"] == [pendente]
    assert consultas == [{"incluir_lotes": True}]


def test_rerun_sem_preparar_nao_pode_calcular_sem_cota(monkeypatch):
    _ambiente(monkeypatch)
    monkeypatch.setattr(F, "transacao", lambda repo, mudar: mudar(F.vazio()))
    with pytest.raises(RuntimeError, match="reexecute o workflow completo"):
        L.confirmar(5)


def test_rerun_confirma_por_cas_e_snapshot_antigo_nao_libera_cota(monkeypatch):
    _ambiente(monkeypatch)
    p = _pedido("lote-pa-vaga-0")
    estado = {
        **F.vazio(),
        "planejadores": ["123"],
        "reservas": [{"run_id": "123", "unidade": p["unidade"], "pedido": p}],
    }
    monkeypatch.setattr(F, "transacao", lambda repo, mudar: mudar(estado))
    L.confirmar(1)
    assert p["tentativa"] == 2
    runs = {"123": _run("retomar-lote-para.yml", "completed", tentativa=1)}
    F.reconciliar(estado, runs, RODAR._e_unidade)
    assert len(estado["reservas"]) == 1
    runs["123"]["run_attempt"] = 2
    F.reconciliar(estado, runs, RODAR._e_unidade)
    assert estado["reservas"] == []


def test_api_inclui_ambos_lotes_so_quando_solicitado(monkeypatch):
    consultados = []

    def paginas(url, campo):
        consultados.append(url)
        return []

    monkeypatch.setattr(F, "paginas", paginas)
    assert F.rodadas("exemplo/raiz", "processar-estados.yml") == {}
    assert len(consultados) == 5
    consultados.clear()
    assert F.rodadas("exemplo/raiz", "processar-estados.yml", incluir_lotes=True) == {}
    assert len(consultados) == 5 * (1 + len(F.WORKFLOWS_LOTE))
    assert any("/retomar-lote-para.yml/" in u for u in consultados)
    assert any("/lote-para.yml/" in u for u in consultados)


def test_falha_consulta_lote_nao_vira_zero(monkeypatch):
    def paginas(url, campo):
        if "/retomar-lote-para.yml/" in url:
            raise RuntimeError("indisponível")
        return []

    monkeypatch.setattr(F, "paginas", paginas)
    with pytest.raises(RuntimeError):
        F.rodadas("exemplo/raiz", "processar-estados.yml", incluir_lotes=True)


@pytest.mark.parametrize("nome,maximo", [("lote-para.yml", 15), ("retomar-lote-para.yml", 5)])
def test_workflows_reservam_antes_de_dados_e_guardam_reruns(nome, maximo):
    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows" / nome).read_text())
    assert workflow["concurrency"]["cancel-in-progress"] is False
    jobs = workflow["jobs"]
    reserva = jobs["preparar"]["steps"][1]
    assert reserva["id"] == "reserva" and reserva["run"].endswith(f"--reservar {maximo}")
    assert jobs["calcular"]["strategy"]["max-parallel"] == "${{ fromJSON(needs.preparar.outputs.vagas) }}"
    assert jobs["calcular"]["strategy"]["fail-fast"] is False
    for nome_job in ("calcular", "publicar"):
        passos = jobs[nome_job]["steps"]
        assert passos[1]["id"] == "reserva" and "--confirmar" in passos[1]["run"]
        for passo in passos:
            if "always()" in passo.get("if", ""):
                assert "steps.reserva.outcome == 'success'" in passo["if"]
    assert workflow["permissions"]["contents"] == "write"
    assert workflow["permissions"]["actions"] == "read"
