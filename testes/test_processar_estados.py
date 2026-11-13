"""Fila do processamento do Brasil (motor/rodar_estado.py --planejar): estados grandes em fatias por longitude que
somam o estado; estados novos entram antes da manutenção (tarefa nova em estado já feito), que não passa do teto; job
antigo do estado inteiro segura as fatias dele; o próximo da fila repõe as vagas livres; continuação por fatia."""

import copy
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

MOTOR = Path(__file__).resolve().parents[1] / "motor"
sys.path.insert(0, str(MOTOR))

import fila_processamento as F  # noqa: E402
import raiz_situacao as S  # noqa: E402
import rodar_estado as O  # noqa: E402


def test_fatias_somam_o_estado_e_seguem_a_longitude():
    for uf in S.TOTAL_IBGE:
        k = S.n_fatias(uf)
        fatias = [S.municipios_da_fatia(uf, i) for i in range(1, k + 1)] if k > 1 else [S.municipios_da_fatia(uf, 0)]
        assert sum(map(len, fatias)) == S.TOTAL_IBGE[uf] == len(set().union(*map(set, fatias))), uf
        assert all(len(f) <= S.LIMITE_FATIA for f in fatias), uf
    assert S.unidades("MG") == [f"MG-{i}" for i in range(1, 9)] and S.unidades("AC") == ["AC"]
    assert S.ler_unidade("mg-3") == ("MG", 3, 8) and S.ler_unidade("AC") == ("AC", 0, 1)
    with pytest.raises(ValueError):
        S.ler_unidade("XX-1")
    # faixas de longitude: a fatia 1 do MG fica toda a oeste da fatia 8
    lon = {r["codigo_ibge"]: float(r["longitude"]) for r in S._lista_municipios()}
    assert max(lon[c] for c in S.municipios_da_fatia("MG", 1)) <= min(lon[c] for c in S.municipios_da_fatia("MG", 8))


def test_lista_de_unidades():
    assert O.lista_unidades(["MG"])[:2] == ["MG-1", "MG-2"] and len(O.lista_unidades(["MG"])) == 8
    assert O.lista_unidades(["MG-3, AC"]) == ["MG-3", "AC"]
    assert O.lista_unidades(["MG"], expandir=False) == ["MG"]


def _agora(dias: float = 0) -> str:
    return (dt.datetime.now(dt.UTC) - dt.timedelta(days=dias)).isoformat(timespec="seconds")


def _completo(uf: str, dias: float = 1) -> dict:
    return {"municipios": S.TOTAL_IBGE[uf], "total_ibge": S.TOTAL_IBGE[uf], "completo": True, "faltam": {},
            "controle": "x", "motor": {"rodada": {"fim": _agora(dias)}}}  # fmt: skip


@pytest.fixture
def plano(monkeypatch):
    """Brasil com tudo pronto, menos: MG não começou (novo) e RO com tarefa nova do produto (manutenção)."""
    estados = {uf: _completo(uf) for uf in S.TOTAL_IBGE if uf != "MG"}
    estados["RO"] = {**_completo("RO"), "completo": False, "faltam": {"ficha": 3}}
    monkeypatch.setattr(S, "ler_manifesto", lambda: {"estados": estados})
    monkeypatch.setattr(O, "versoes_executor", lambda: None)
    monkeypatch.setattr(O, "ufs_ativas", lambda: (set(), 0))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return estados


def test_estados_novos_antes_da_manutencao(plano, monkeypatch):
    monkeypatch.setattr(O, "VAGAS", 5)
    assert O.planejar([], set()) == ["MG-1", "MG-2", "MG-3", "MG-4", "MG-5"]  # RO espera: não segura vaga de MG
    monkeypatch.setattr(O, "VAGAS", 18)
    assert O.planejar([], set()) == [f"MG-{i}" for i in range(1, 9)] + ["RO"]


def test_manutencao_tem_teto(plano, monkeypatch):
    plano["AC"] = {**_completo("AC"), "completo": False, "faltam": {"flag": 1}}
    plano["AP"] = {**_completo("AP"), "completo": False, "faltam": {"flag": 1}}
    monkeypatch.setattr(O, "VAGAS_MANUTENCAO", 2)
    assert O.planejar([], set())[8:] == ["RO", "AC"]  # o AP fica na fila
    monkeypatch.setattr(O, "ufs_ativas", lambda: ({"PA-1"}, 0))  # já há uma de manutenção rodando
    assert O.planejar([], set())[8:] == ["RO"]


def test_job_antigo_do_estado_inteiro_segura_as_fatias(plano, monkeypatch):
    plano["TO"] = {**_completo("TO"), "completo": False, "municipios": 11, "faltam": {"imoveis": 128}}
    monkeypatch.setattr(O, "ufs_ativas", lambda: ({"TO"}, 0))
    assert not {"TO-1", "TO-2"} & set(O.planejar([], set()))
    monkeypatch.setattr(O, "ufs_ativas", lambda: ({"MG-1"}, 0))  # fatia de outro estado não segura nada
    assert {"TO-1", "TO-2", "MG-2"} <= set(O.planejar([], set())) and "MG-1" not in O.planejar([], set())


def test_proximo_da_fila_repoe_vagas_e_pula_a_tentada_ha_pouco(plano, monkeypatch):
    monkeypatch.setattr(O, "ufs_ativas", lambda: ({"MG-1"}, 0))
    assert O.planejar([], set(), "proximo", liberou="MG-1") == [f"MG-{i}" for i in range(2, 9)]  # MG-1 segue ocupando
    # fatia que terminou dentro do prazo há pouco, mas com erro: fica para a rodada semanal
    plano["MG"] = {"municipios": 100, "total_ibge": 853, "completo": False, "faltam": {"imoveis": 753}, "controle": "x",
                   "motor": {"fatias": {"1": {"completo": False, "faltam": {"imoveis": 7},
                                              "rodada": {"fim": _agora(0.1), "parou_por_tempo": False}}}}}  # fmt: skip
    assert O.planejar([], set(), "proximo", liberou="MG-1") == [f"MG-{i}" for i in range(2, 9)]


def test_pedido_explicito_expande_o_estado_em_fatias(plano):
    assert O.planejar(O.lista_unidades(["PA"]), set()) == ["PA-1", "PA-2"]


def test_situacao_de_uma_fatia(tmp_path):
    cods = S.municipios_da_fatia("TO", 1)
    for c in cods[:3]:
        (tmp_path / f"imoveis_{c}.csv").write_text("cod_imovel,app_escadinha_ha\nx,0\n")
    sit = S.situacao(tmp_path, "TO", produto=True, so=set(cods))
    assert sit["total_ibge"] == len(cods) and sit["municipios"] == 3 and sit["faltam"]["imoveis"] == len(cods) - 3


def test_quinze_jobs_no_maximo_deixando_cinco_maquinas_para_ci_e_site(plano, monkeypatch):
    """O GitHub dá 20 máquinas ao repositório; o processamento usa até 15. Quem já roda não é interrompido: com 17
    rodando (de antes do limite), nada novo começa até sobrar vaga."""
    assert O.VAGAS == 15
    rodando = {f"BA-{i}" for i in range(1, 5)} | {f"SP-{i}" for i in range(1, 7)} | {f"RS-{i}" for i in range(1, 6)}
    monkeypatch.setattr(O, "ufs_ativas", lambda: (rodando | {"PR-1", "PR-2"}, 0))  # 17
    assert O.planejar([], set()) == []
    monkeypatch.setattr(O, "ufs_ativas", lambda: (set(sorted(rodando)[:14]), 0))
    assert O.planejar([], set()) == ["MG-1"]


def test_pedido_refazer_e_continuacao_respeitam_vagas_e_estado_inteiro(plano, monkeypatch):
    ativos = {f"SP-{i}" for i in range(1, 7)} | {f"RS-{i}" for i in range(1, 6)} | {"PA", "PR-1", "PR-2"}
    monkeypatch.setattr(O, "ufs_ativas", lambda: (ativos, 0))
    assert O.planejar(["PA-1", "PA-2", "MG-1", "MG-2"], set(), continuacao=2) == ["MG-1"]
    monkeypatch.setattr(O, "ufs_ativas", lambda: (ativos | {"PR-3"}, 0))
    assert O.planejar(["MG-1"], {"funil"}) == []
    assert O.planejar([], {"funil"}) == []


@pytest.mark.parametrize(("valor", "esperado"), [("100", 15), ("8", 8), ("-1", 0)])
def test_variavel_de_ambiente_so_reduz_teto(valor, esperado):
    env = {**os.environ, "RAIZ_VAGAS": valor, "PYTHONPATH": str(MOTOR)}
    r = subprocess.run(
        [sys.executable, "-c", "import rodar_estado; print(rodar_estado.VAGAS)"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    assert int(r.stdout.strip()) == esperado


def _pedido(unidade, origem="1", continuacao=0, refazer=""):
    return {
        "id": f"{origem}/{unidade}/{continuacao}",
        "unidade": unidade,
        "refazer": refazer,
        "continuacao": continuacao,
        "ref": "a" * 40,
    }


def _run(*unidades, status="in_progress", conclusion=None):
    return {"status": status, "jobs": [{"name": u, "status": status, "conclusion": conclusion} for u in unidades]}


def _legados(n=14):
    unidades = [f"SP-{i}" for i in range(1, 7)] + [f"RS-{i}" for i in range(1, 6)] + [f"PR-{i}" for i in range(1, 5)]
    return {"antiga": _run(*unidades[:n])}


def test_dois_planejadores_disputam_ultima_vaga_sem_estourar_quinze():
    estado = {**F.vazio(), "planejadores": ["1", "2"]}
    runs = {**_legados(), "1": _run(), "2": _run()}
    assert F.admitir(estado, runs, "1", [_pedido("MG-1")], O._e_unidade) == [_pedido("MG-1")]
    assert F.admitir(estado, runs, "2", [_pedido("MG-2", "2")], O._e_unidade) == []
    assert len(estado["reservas"]) == 1
    # A matriz do primeiro apareceu: não contar seu job duas vezes (API + reserva).
    runs["1"] = _run("MG-1")
    assert F.admitir(estado, runs, "2", [_pedido("MG-2", "2")], O._e_unidade) == []


def test_plano_legado_sem_matriz_impede_admissao_e_erro_de_api_nao_vira_zero(monkeypatch):
    estado = {**F.vazio(), "planejadores": ["1"]}
    assert F.admitir(estado, {"antigo": _run(), "1": _run()}, "1", [_pedido("MG-1")], O._e_unidade) == []
    monkeypatch.setattr(F, "rodadas", lambda *a: (_ for _ in ()).throw(RuntimeError("rede indisponível")))
    with pytest.raises(RuntimeError, match="rede indisponível"):
        O.ufs_ativas()


def test_api_le_todas_as_paginas_e_confere_resposta(monkeypatch):
    chamadas = []

    def executar(args, entrada=None):
        chamadas.append(args)
        return json.dumps({"jobs": [{"id": i} for i in range(100)]}) + "\n" + json.dumps({"jobs": [{"id": 100}]})

    monkeypatch.setattr(F, "comando", executar)
    assert len(F.paginas("repos/raiz/teste/actions/runs/1/jobs?per_page=100", "jobs")) == 101
    assert "--paginate" in chamadas[0] and "--slurp" not in chamadas[0]
    monkeypatch.setattr(F, "comando", lambda *a: '{"message":"erro"}')
    with pytest.raises(RuntimeError, match="resposta incompleta"):
        F.paginas("jobs", "jobs")


def test_reserva_so_libera_depois_do_job_inteiro_e_recupera_falha_de_preparo():
    p = _pedido("MG-1", continuacao=2, refazer="direto")
    estado = {**F.vazio(), "planejadores": ["1", "2"], "reservas": [{"run_id": "1", "unidade": "MG-1", "pedido": p}]}
    runs = {"1": _run("MG-1"), "2": _run()}
    assert F.admitir(estado, runs, "2", [_pedido("MG-1", "2")], O._e_unidade) == []
    # O cache ainda está rodando: nem o tempo transcorrido nem uma continuação liberam.
    assert len(estado["reservas"]) == 1
    runs["1"] = _run(status="completed")  # sem job da unidade: preparar não chegou a criar a matriz
    escolhidos = F.admitir(estado, runs, "2", [], O._e_unidade)
    assert escolhidos == [{**p, "falhas": 1}]
    assert escolhidos[0]["refazer"] == "direto" and escolhidos[0]["continuacao"] == 2


@pytest.mark.parametrize("conclusao", ["failure", "timed_out", "skipped"])
def test_job_sem_sucesso_devolve_pedido_a_fila(conclusao):
    p = _pedido("MG-1", refazer="ficha")
    estado = {**F.vazio(), "planejadores": ["1", "2"], "reservas": [{"run_id": "1", "unidade": "MG-1", "pedido": p}]}
    runs = {"1": _run("MG-1", status="completed", conclusion=conclusao), "2": _run()}
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [{**p, "falhas": 1}]


def test_conclusao_de_job_libera_reserva_mesmo_com_outras_unidades_no_run():
    p = _pedido("MG-1")
    estado = {**F.vazio(), "planejadores": ["1", "2"], "reservas": [{"run_id": "1", "unidade": "MG-1", "pedido": p}]}
    runs = {"1": _run("MG-1", "MG-2"), "2": _run()}
    runs["1"]["jobs"][0].update(status="completed", conclusion="success")
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == []
    assert estado["reservas"] == [] and estado["fila"] == []


def test_falha_depois_do_executor_retoma_sem_refazer_resultados_prontos():
    p = _pedido("MG-1", refazer="funil")
    estado = {
        **F.vazio(),
        "planejadores": ["1", "2"],
        "reservas": [{"run_id": "1", "unidade": "MG-1", "pedido": p}],
    }
    runs = {"1": _run("MG-1", status="completed", conclusion="failure"), "2": _run()}
    runs["1"]["jobs"][0]["steps"] = [{"name": F.PASSO_EXECUTOR, "conclusion": "success"}]
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [{**p, "refazer": "", "falhas": 1}]


@pytest.mark.parametrize("cancelado", [True, False])
def test_cancelamento_e_tres_falhas_ficam_visiveis_sem_reabrir_automaticamente(cancelado):
    p = {**_pedido("MG-1"), "falhas": 0 if cancelado else 2}
    estado = {
        **F.vazio(),
        "planejadores": ["1", "2"],
        "reservas": [{"run_id": "1", "unidade": "MG-1", "pedido": p}],
    }
    runs = {
        "1": _run("MG-1", status="completed", conclusion="cancelled" if cancelado else "failure"),
        "2": _run(),
    }
    novo = _pedido("MG-1", "2")
    assert F.admitir(estado, runs, "2", [novo], O._e_unidade) == []
    assert len(estado["fila"]) == 1 and estado["fila"][0]["bloqueado"]
    assert estado["fila"][0]["falhas"] == (1 if cancelado else 3)
    F.enfileirar(estado, [novo])  # novo pedido explícito autorizado, depois da correção
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [novo]


def test_continuacao_sem_vaga_permanece_ate_o_proximo_planejamento():
    p = _pedido("MG-1", continuacao=2)
    estado = {**F.vazio(), "planejadores": ["1"]}
    F.enfileirar(estado, [p])
    F.enfileirar(estado, [p])
    assert F.admitir(estado, {**_legados(15), "1": _run()}, "1", [], O._e_unidade) == []
    assert estado["fila"] == [p]
    estado["planejadores"].append("2")
    assert F.admitir(estado, {"1": _run(status="completed"), "2": _run()}, "2", [], O._e_unidade) == [p]
    assert estado["fila"] == []


def test_transacao_refaz_plano_apos_conflito_sem_perder_reserva(monkeypatch):
    estado = {**F.vazio(), "planejadores": ["1", "2"]}
    runs = {**_legados(), "1": _run(), "2": _run()}

    class Repo:
        revisao = 0
        conflito = True

        def ler(self):
            return str(self.revisao), copy.deepcopy(estado)

        def trocar(self, antes, novo):
            if self.conflito:
                self.conflito = False
                F.admitir(estado, runs, "2", [_pedido("MG-2", "2")], O._e_unidade)
                self.revisao += 1
            if antes != str(self.revisao):
                return False
            estado.update(novo)
            self.revisao += 1
            return True

    monkeypatch.setattr(F.time, "sleep", lambda _: None)
    resultado = F.transacao(Repo(), lambda e: F.admitir(e, runs, "1", [_pedido("MG-1")], O._e_unidade))
    assert resultado == []
    assert [r["unidade"] for r in estado["reservas"]] == ["MG-2"]


def test_git_lease_rejeita_escritor_atrasado_e_preserva_main(tmp_path, monkeypatch):
    remoto = tmp_path / "remoto.git"
    local = tmp_path / "local"
    subprocess.run(["git", "init", "--bare", str(remoto)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remoto), str(local)], check=True, capture_output=True)
    monkeypatch.chdir(local)
    F.comando(["git", "config", "user.name", "Teste"])
    F.comando(["git", "config", "user.email", "teste@raiz.invalid"])
    F.comando(["git", "checkout", "-b", "main"])
    F.comando(["git", "commit", "--allow-empty", "-m", "Início do teste"])
    F.comando(["git", "push", "origin", "main"])
    antes_main = F.comando(["git", "ls-remote", "origin", "refs/heads/main"])
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)  # SHA do workflow não existe neste checkout histórico
    repo = F.Repositorio()
    anterior, inicial = repo.ler()
    primeiro = {**inicial, "fila": [_pedido("MG-1")]}
    assert repo.trocar(anterior, primeiro)
    assert not repo.trocar(anterior, {**inicial, "fila": [_pedido("MG-2")]})
    assert repo.ler()[1] == primeiro
    assert F.comando(["git", "ls-remote", "origin", "refs/heads/main"]) == antes_main


def test_continuacao_persistida_dispara_so_dreno_sem_duplicar(tmp_path, monkeypatch):
    pasta = tmp_path / "saida" / "MG"
    pasta.mkdir(parents=True)
    (pasta / "rodada.json").write_text(json.dumps({"continuacao": 1, "parou_por_tempo": True, "progresso": 3}))
    monkeypatch.setattr(O, "AQUI", tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    fila, disparos = [], []
    monkeypatch.setattr(F, "guardar_continuacao", lambda u, n: fila.append((u, n)))
    monkeypatch.setattr(O, "disparar", lambda campos, rotulo: disparos.append(campos) or True)
    O.continuar("MG-1")
    assert fila == [("MG-1", 2)]
    assert disparos == [{"continuacao": "fila"}]


def test_workflow_drena_fila_e_preserva_parametros_da_matriz():
    import yaml

    w = yaml.safe_load((MOTOR.parent / ".github/workflows/processar-estados.yml").read_text())
    evento = w.get("on", w.get(True))
    assert {c["cron"] for c in evento["schedule"]} == {"17 * * * *"}
    job = w["jobs"]["processar"]
    assert job["strategy"]["max-parallel"] == 15 and job["strategy"]["fail-fast"] is False
    assert job["concurrency"]["cancel-in-progress"] is False
    assert "include" in job["strategy"]["matrix"]
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "${{ matrix.ref }}"
    assert job["env"]["RAIZ_REFAZER"] == "${{ matrix.refazer }}"
    assert any(s.get("name") == F.PASSO_EXECUTOR for s in job["steps"])


@pytest.mark.parametrize("modo", ["proximo", "fila"])
@pytest.mark.parametrize("ocupadas", [0, 7, 14, 15])
def test_reposicao_automatica_enche_vagas_globais_em_varias_ufs(plano, monkeypatch, modo, ocupadas):
    # Todas as UFs novas, RO apenas em manutenção. A contagem efetiva é da fila CAS.
    plano.clear()
    plano["RO"] = {**_completo("RO"), "completo": False, "faltam": {"ficha": 3}}
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    estado = {**F.vazio(), "planejadores": ["novo"]}
    runs = {**(_legados(ocupadas) if ocupadas else {}), "novo": _run()}

    def reservar(
        candidatos, pedidos, refazer, e_unidade, limite, continuacao, max_novos, manutencao, limite_manutencao
    ):
        assert max_novos is None and not pedidos and not refazer
        if modo == "fila":
            assert "RO" not in candidatos
        return F.admitir(
            estado,
            runs,
            "novo",
            [_pedido(u, "novo") for u in candidatos],
            e_unidade,
            limite,
            max_novos,
            manutencao,
            limite_manutencao,
        )

    monkeypatch.setattr(F, "reservar", reservar)
    escolhidas = O.planejar([], set(), modo)
    assert len(escolhidas) == 15 - ocupadas
    assert ocupadas + len(estado["reservas"]) == 15
    if ocupadas < 14:
        assert len({u.split("-")[0] for u in escolhidas}) > 1
