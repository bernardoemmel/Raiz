"""Troca operacional fechada do publicador, preservando a ciência e os jobs vivos."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from testes.test_processar_estados import F, O, _pedido, _run

ORIGEM = "88860b64ee09f811b66e283f5c57997ebcdb3fd5"
BASE = "b624b108b0350135003e1099d9c928fa7cc24151"
DESTINO = "ec2ebd2c5772c6307aa1c3a41e1f97aac54e1b51"
DESTINO_E1 = "dac754f9d27a61481fdb0db24c496cdea0dd4f35"
PROMOCOES = {ORIGEM: DESTINO, BASE: DESTINO,
             "6a53cfbf514f369f694ea0bd3bc594ef8295a3b4": DESTINO_E1,
             "bea53bd06c7178daf2a53c392e5a9d54c55e7bc7": DESTINO_E1}  # fmt: skip
RAIZ = Path(__file__).resolve().parents[1]


def _antigo(**campos):
    return {**_pedido("BA-1", continuacao=2, refazer="direto,ficha"), "ref": ORIGEM, **campos}


def _promovido(pedido):
    destino = PROMOCOES[pedido["ref"]]
    return {**pedido, "ref": destino, "promocao_publicador": {"origem": pedido["ref"], "destino": destino}}


def test_promocao_fechada_versiona_aquisicao_preservando_ciencia_de_cada_grupo():
    # Evidência arquivada de commits imutáveis: CI tem checkout raso. Cada grupo
    # preserva sua ciência, sem substituir o destino pela main que incorpora E1.
    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-publicador.json").read_text())
    assert F.PROMOCOES_CONTINUACAO == PROMOCOES
    assert PROMOCOES == {ref: grupo["destino"] for grupo in prova["grupos"] for ref in grupo["origens"]}
    for ref, destino in PROMOCOES.items():
        depois = prova["commits"][destino]
        antes = prova["commits"][ref]
        for campo in ("arquivos", "codigo_preservado_sha256", "pacotes_origem", "dependencias_sha256",
                      "mapbiomas_formulas_sha256", "mapbiomas_configuracao_sha256"):  # fmt: skip
            assert antes[campo] == depois[campo]
        assert antes["mapbiomas_arquivo_sha256"] != depois["mapbiomas_arquivo_sha256"]
        assert antes["versao_motor"] != depois["versao_motor"]
        mudaram = {t for t, v in antes["versoes_tarefas"].items() if depois["versoes_tarefas"][t] != v}
        assert mudaram == {"mapbiomas"}
    assert prova["commits"][BASE]["versoes_tarefas"]["mapbiomas"] == "mapbiomas-732fe6f08784"
    assert prova["commits"][DESTINO]["versoes_tarefas"]["mapbiomas"] == "mapbiomas-3ffd6cd150c6"
    assert (
        prova["commits"][DESTINO]["codigo_preservado_sha256"]
        != prova["commits"][DESTINO_E1]["codigo_preservado_sha256"]
    )
    assert depois["arquivos"] > 300 and depois["pacotes_origem"] == 213
    assert set(depois["versoes_tarefas"]) == {
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
    assert "raiz/regras/padroes/" not in prova["excluidos_operacionais_ou_aquisicao"]
    assert "raiz/funil/restricoes.py" not in prova["excluidos_operacionais_ou_aquisicao"]
    assert "raiz/funil/duck.py" not in prova["excluidos_operacionais_ou_aquisicao"]
    assert prova["mapbiomas_formulas"] == ["ha_pixel", "por_imovel"]
    assert {"ANO", "TEMAS", "FLORESTA", "PASTO", "AGRICULTURA", "SILVICULTURA"} <= set(prova["mapbiomas_configuracao"])


@pytest.mark.parametrize("origem", PROMOCOES)
def test_continuacao_promovida_preserva_pedido_e_reserva_viva(origem):
    vivo = _antigo(continuacao=1, id="anterior/BA-1/1", ref=origem)
    pendente = _antigo(falhas=1, ref=origem)
    estado = {**F.vazio(), "planejadores": ["1", "2"], "fila": [copy.deepcopy(pendente)],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": vivo}]}  # fmt: skip
    runs = {"1": _run("BA-1"), "2": _run()}
    original = copy.deepcopy(estado["reservas"])
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == []
    assert estado["reservas"] == original
    assert estado["fila"] == [_promovido(pendente)]
    runs["1"] = _run("BA-1", status="completed", conclusion="success")
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [_promovido(pendente)]


@pytest.mark.parametrize("origem", PROMOCOES)
def test_falha_reconciliada_promove_retentativa_sem_continuacao(origem):
    pedido = _antigo(continuacao=0, ref=origem)
    estado = {**F.vazio(), "planejadores": ["1", "2"],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": pedido}]}  # fmt: skip
    runs = {"1": _run("BA-1", status="completed", conclusion="failure"), "2": _run()}
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [_promovido({**pedido, "falhas": 1})]


@pytest.mark.parametrize("cancelado", [True, False])
@pytest.mark.parametrize("origem", PROMOCOES)
def test_reconciliacao_nao_promove_cancelados_nem_erros_bloqueados(cancelado, origem):
    pedido = _antigo(falhas=0 if cancelado else 2, ref=origem)
    estado = {**F.vazio(), "planejadores": ["1", "2"],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": pedido}]}  # fmt: skip
    runs = {"1": _run("BA-1", status="completed", conclusion="cancelled" if cancelado else "failure"),
            "2": _run()}  # fmt: skip
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == []
    assert estado["fila"][0]["ref"] == origem
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
    F.enfileirar(estado, [copy.deepcopy(tardio)])
    assert F.admitir(estado, runs, "2", [], O._e_unidade, limite=0) == []
    assert estado["fila"] == [_promovido(primeiro), _promovido(tardio)]
    assert F.promover_continuacoes(estado) == 0


@pytest.mark.parametrize("origem", PROMOCOES)
def test_conflito_cas_rele_reserva_antiga_sem_reescrever_job_ja_admitido(monkeypatch, origem):
    pedido = _antigo(ref=origem)
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
