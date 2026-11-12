"""Troca operacional fechada do publicador, preservando a ciência e os jobs vivos."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from testes.test_processar_estados import F, O, _pedido, _run

ORIGEM = "88860b64ee09f811b66e283f5c57997ebcdb3fd5"
DESTINO = "b624b108b0350135003e1099d9c928fa7cc24151"
RAIZ = Path(__file__).resolve().parents[1]


def _antigo(**campos):
    return {**_pedido("BA-1", continuacao=2, refazer="direto,ficha"), "ref": ORIGEM, **campos}


def _promovido(pedido):
    return {**pedido, "ref": DESTINO, "promocao_publicador": {"origem": ORIGEM, "destino": DESTINO}}


def test_par_fechado_tem_auditoria_de_codigo_dependencias_e_versoes_iguais():
    # Evidência arquivada dos dois commits: o checkout do CI é raso e a main
    # posterior (#79) muda ciência legitimamente; não deve substituir o destino.
    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-publicador.json").read_text())
    assert F.PROMOCOES_CONTINUACAO == {ORIGEM: DESTINO} == {prova["origem"]: prova["destino"]}
    antes, depois = (prova["commits"][ref] for ref in (ORIGEM, DESTINO))
    assert antes == depois
    assert antes["arquivos"] > 300 and antes["pacotes_origem"] == 213
    assert set(antes["versoes_tarefas"]) == {
        "funil",
        "filtros",
        "direto",
        "mapbiomas",
        "extras_direto",
        "flag",
        "terra",
        "titulo",
        "ficha",
        "rebanho",
        "desenvolvedor",
    }
    assert prova["escopos"] == ["motor/", "raiz/"]
    assert "raiz/regras/padroes/" not in prova["excluidos_operacionais"]


def test_continuacao_promovida_preserva_pedido_e_reserva_viva():
    vivo = _antigo(continuacao=1, id="anterior/BA-1/1")
    pendente = _antigo(falhas=1)
    estado = {**F.vazio(), "planejadores": ["1", "2"], "fila": [copy.deepcopy(pendente)],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": vivo}]}  # fmt: skip
    runs = {"1": _run("BA-1"), "2": _run()}
    original = copy.deepcopy(estado["reservas"])
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == []
    assert estado["reservas"] == original
    assert estado["fila"] == [_promovido(pendente)]
    runs["1"] = _run("BA-1", status="completed", conclusion="success")
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [_promovido(pendente)]


def test_falha_reconciliada_promove_retentativa_sem_continuacao():
    pedido = _antigo(continuacao=0)
    estado = {**F.vazio(), "planejadores": ["1", "2"],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": pedido}]}  # fmt: skip
    runs = {"1": _run("BA-1", status="completed", conclusion="failure"), "2": _run()}
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [_promovido({**pedido, "falhas": 1})]


@pytest.mark.parametrize("cancelado", [True, False])
def test_reconciliacao_nao_promove_cancelados_nem_erros_bloqueados(cancelado):
    pedido = _antigo(falhas=0 if cancelado else 2)
    estado = {**F.vazio(), "planejadores": ["1", "2"],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": pedido}]}  # fmt: skip
    runs = {"1": _run("BA-1", status="completed", conclusion="cancelled" if cancelado else "failure"),
            "2": _run()}  # fmt: skip
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == []
    assert estado["fila"][0]["ref"] == ORIGEM
    assert estado["fila"][0]["bloqueado"]
    assert "promocao_publicador" not in estado["fila"][0]


@pytest.mark.parametrize(
    "campos",
    [
        {"continuacao": 0},
        {"ref": "a" * 40},
        {"ref": DESTINO},
        {"bloqueado": "cancelado"},
        {"continuacao": True},
        {"continuacao": "2"},
        {"continuacao": -1},
        {"falhas": True},
        {"falhas": "1"},
        {"falhas": -1},
    ],
)
def test_pedidos_fora_do_contrato_nao_mudam(campos):
    estado = {**F.vazio(), "fila": [_antigo(**campos)]}
    antes = copy.deepcopy(estado)
    assert F.promover_continuacoes(estado) == 0
    assert estado == antes


def test_continuacao_tardia_sera_promovida_sem_reordenar_fila():
    primeiro = _antigo()
    estado = {**F.vazio(), "planejadores": ["2"], "fila": [copy.deepcopy(primeiro)]}
    runs = {"2": _run()}
    assert F.admitir(estado, runs, "2", [], O._e_unidade, limite=0) == []
    tardio = _antigo(id="anterior/CE-1/3", unidade="CE-1", continuacao=3)
    F.enfileirar(estado, [tardio])
    assert F.admitir(estado, runs, "2", [], O._e_unidade, limite=0) == []
    assert estado["fila"] == [_promovido(primeiro), _promovido(tardio)]
    assert F.promover_continuacoes(estado) == 0


def test_conflito_cas_rele_reserva_antiga_sem_reescrever_job_ja_admitido(monkeypatch):
    pedido = _antigo()
    estado = {**F.vazio(), "planejadores": ["1", "2"], "fila": [copy.deepcopy(pedido)]}
    runs = {"1": _run(), "2": _run()}

    class Repo:
        revisao = 0

        def ler(self):
            return str(self.revisao), copy.deepcopy(estado)

        def trocar(self, antes, novo):
            if self.revisao == 0:
                # Planejador antigo ganhou o lease antes de publicar este patch.
                estado["reservas"] = [{"run_id": "1", "unidade": "BA-1", "pedido": estado["fila"].pop()}]
                self.revisao = 1
                return False
            assert antes == "1"
            estado.update(novo)
            return True

    monkeypatch.setattr(F.time, "sleep", lambda _: None)
    assert F.transacao(Repo(), lambda e: F.admitir(e, runs, "2", [], O._e_unidade)) == []
    assert estado["reservas"][0]["pedido"] == pedido


@pytest.mark.parametrize(
    "mudanca,autorizado",
    [
        ({}, True),
        ({"event_name": "workflow_dispatch", "id": 1}, True),
        ({"event_name": "push"}, False),
        ({"id": 1}, False),
        ({"head_sha": DESTINO}, False),
        ({"head_branch": "outra"}, False),
        ({"head_repository.full_name": "outro/raiz"}, False),
    ],
)
def test_gatilho_unico_nao_confia_em_codigo_de_outro_run(mudanca, autorizado):
    workflow = yaml.safe_load((RAIZ / ".github/workflows/publicar-metadados.yml").read_text())
    evento = workflow.get("on", workflow.get(True))
    assert evento["workflow_run"] == {"workflows": ["Processar estados (motor)"], "types": ["completed"]}
    contexto = {"event_name": "workflow_run", "id": 43305564503, "head_sha": ORIGEM,
                "head_branch": "main", "head_repository.full_name": "exemplo/raiz", **mudanca}  # fmt: skip
    expressao = workflow["jobs"]["catalogo"]["if"]
    for chave, valor in contexto.items():
        caminho = "github.event_name" if chave == "event_name" else f"github.event.workflow_run.{chave}"
        expressao = expressao.replace(caminho, repr(valor))
    expressao = expressao.replace("github.repository", repr("exemplo/raiz")).replace("&&", "and").replace("||", "or")
    funcoes = {"format": lambda modelo, valor: modelo.format(valor)}
    assert eval(" ".join(expressao.split()), {"__builtins__": {}}, funcoes) is autorizado
    checkout = workflow["jobs"]["catalogo"]["steps"][0]
    assert checkout["uses"] == "actions/checkout@v4" and "with" not in checkout
