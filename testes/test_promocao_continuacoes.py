"""Promoções fechadas com deltas de validação explícitos, sem alterar os jobs vivos."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from testes.test_processar_estados import F, O, _pedido, _run

ORIGEM = "88860b64ee09f811b66e283f5c57997ebcdb3fd5"
BASE = "b624b108b0350135003e1099d9c928fa7cc24151"
DESTINO = "02c3db8de18ef1fb6f5260803e33f4ac3a73c305"
DESTINO_E1 = "be452620f868537251fa832a10cb14bfb5c8efe3"
PROMOCOES = {ORIGEM: DESTINO, BASE: DESTINO,
             "6a53cfbf514f369f694ea0bd3bc594ef8295a3b4": DESTINO_E1,
             "bea53bd06c7178daf2a53c392e5a9d54c55e7bc7": DESTINO_E1,
             "436c7b636f6a8867b47403a1dfad4e4c741dc150": DESTINO_E1}  # fmt: skip
RAIZ = Path(__file__).resolve().parents[1]


def _antigo(**campos):
    return {**_pedido("BA-1", continuacao=2, refazer="direto,ficha"), "ref": ORIGEM, **campos}


def _promovido(pedido):
    destino = PROMOCOES[pedido["ref"]]
    return {**pedido, "ref": destino, "promocao_publicador": {"origem": pedido["ref"], "destino": destino}}


def test_promocao_fechada_declara_guardas_e_versoes_reais_de_cada_origem():
    # Prova de commits imutáveis: o CI raso verifica o artefato sem consultar GitHub.
    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-publicador.json").read_text())
    assert prova["versao_auditoria"] == 2
    assert F.PROMOCOES_CONTINUACAO == PROMOCOES
    assert PROMOCOES == {ref: grupo["destino"] for grupo in prova["grupos"] for ref in grupo["origens"]}
    pares = {(p["origem"], p["destino"]): p for p in prova["comparacoes"]}
    assert set(pares) == set(PROMOCOES.items())
    for ref, destino in PROMOCOES.items():
        antes, depois = prova["commits"][ref], prova["commits"][destino]
        par = pares[(ref, destino)]
        for campo in (
            "arquivos_nativos", "codigo_nativo_sha256", "arquivos", "codigo_preservado_sha256",
            "mapbiomas_formulas_sha256", "mapbiomas_configuracao_sha256", "codigo_tarefas", "depende",
        ):  # fmt: skip
            assert antes[campo] == depois[campo]
        assert antes["mapbiomas_arquivo_sha256"] != depois["mapbiomas_arquivo_sha256"]
        assert antes["versao_motor"] != depois["versao_motor"]
        assert antes["modulo_temporario_conferido"] and depois["modulo_temporario_conferido"]
        mudaram = {t for t, v in antes["versoes_tarefas"].items() if depois["versoes_tarefas"][t] != v}
        esperadas = {"funil", "mapbiomas"}
        if destino == DESTINO_E1 and ref != "436c7b636f6a8867b47403a1dfad4e4c741dc150":
            esperadas.add("filtros")
        assert mudaram == set(par["tarefas_alteradas"]) == esperadas
        assert set(par["tarefas_preservadas"]) == set(antes["versoes_tarefas"]) - mudaram
        dep = par["dependencias"]
        assert dep["pacotes_origem"] > 200 and dep["origem_sha256"] == dep["origem_no_destino_sha256"]
        assert dep["projeto_editavel_fora_da_comparacao"] == ["raiz"]
        legado, adocao, *e1 = par["guardas"]
        assert legado["tipo"] == "embargo_legado" and adocao["tipo"] == "adocao_comprovada"
        assert legado["ocorrencias"] == {"helper_antes": 0, "helper_depois": 1, "bloco_antes": 1, "chamada_depois": 1}
        assert legado["resto_municipio"]["antes_sha256"] == legado["resto_municipio"]["depois_sha256"]
        assert adocao["canonical_conferido"] and adocao["referencia"] == DESTINO_E1
        assert set(adocao["resto_plano_execucao_sha256"]) == {"plano", "processar_municipio"}
        for guarda in par["guardas"]:
            resto = guarda["resto_modulo"]
            assert resto["iguais"] and resto["antes_sha256"] == resto["depois_sha256"]
        assert legado["diff_guardas"] and adocao["diff_guardas"]
        if destino == DESTINO:
            assert not e1 and antes["modulos_e1_presentes"] == depois["modulos_e1_presentes"] == []
            assert depois["codigo_tarefas"]["funil"] == ["motor/raiz_estado.py", "raiz/funil/ponte.py"]
        else:
            assert {g["funcao"] for g in e1} == {"_falha", "embargos_ativos"}
            assert all(g["canonical_conferido"] for g in e1)
            filtro = next(g for g in e1 if g["funcao"] == "embargos_ativos")
            assert (filtro["funcao_antes_ast_sha256"] == filtro["funcao_depois_ast_sha256"]) == (
                ref == "436c7b636f6a8867b47403a1dfad4e4c741dc150"
            )
    assert (
        prova["commits"][DESTINO]["codigo_preservado_sha256"]
        != prova["commits"][DESTINO_E1]["codigo_preservado_sha256"]
    )
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
