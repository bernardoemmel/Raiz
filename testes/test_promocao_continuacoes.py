"""Promoções fechadas com deltas de validação explícitos, sem alterar os jobs vivos."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from testes.test_processar_estados import F, O, _pedido, _run

ORIGEM = "88860b64ee09f811b66e283f5c57997ebcdb3fd5"
BASE = "b624b108b0350135003e1099d9c928fa7cc24151"
DESTINO = "be452620f868537251fa832a10cb14bfb5c8efe3"
PROMOCOES = {ORIGEM: DESTINO, BASE: DESTINO,
             "6a53cfbf514f369f694ea0bd3bc594ef8295a3b4": DESTINO,
             "bea53bd06c7178daf2a53c392e5a9d54c55e7bc7": DESTINO,
             "436c7b636f6a8867b47403a1dfad4e4c741dc150": DESTINO}  # fmt: skip
RAIZ = Path(__file__).resolve().parents[1]


def _antigo(**campos):
    return {**_pedido("BA-1", continuacao=2, refazer="direto,ficha"), "ref": ORIGEM, **campos}


def _promovido(pedido):
    destino = F.PROMOCOES_CONTINUACAO[pedido["ref"]]
    return {**pedido, "ref": destino, "promocao_publicador": {"origem": pedido["ref"], "destino": destino}}


def test_promocao_fechada_declara_upgrade_e1_e2_guardas_e_versoes_por_origem():
    # O CI raso verifica a prova dos commits imutáveis sem consultar GitHub.
    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-publicador.json").read_text())
    assert prova["versao_auditoria"] == 3
    assert F.PROMOCOES_BASE_PR82 == PROMOCOES
    assert prova["destino"] == DESTINO
    assert set(prova["origens"]) == set(PROMOCOES)
    assert set(PROMOCOES.values()) == {DESTINO}
    pr79 = "6a53cfbf514f369f694ea0bd3bc594ef8295a3b4"
    pr81 = "436c7b636f6a8867b47403a1dfad4e4c741dc150"
    assert prova["referencias"] == {
        "upgrade_e1_e2_pr79": pr79,
        "protecao_pr81": pr81,
        "embargo_legado_e_adocao": DESTINO,
    }
    pares = {(p["origem"], p["destino"]): p for p in prova["comparacoes"]}
    assert set(pares) == set(PROMOCOES.items())
    assert set(prova["commits"]) == {*PROMOCOES, DESTINO}
    for ref in PROMOCOES:
        antes, depois = prova["commits"][ref], prova["commits"][DESTINO]
        par = pares[(ref, DESTINO)]
        # Preserva apenas o que foi comprovado; as origens pré-E1 recebem ciência nova.
        for campo in ("mapbiomas_formulas_sha256", "mapbiomas_configuracao_sha256",
                      "codigo_nativo_sha256", "depende_sha256"):  # fmt: skip
            assert antes[campo] == depois[campo]
        assert antes["versao_motor"] != depois["versao_motor"]
        assert antes["modulo_temporario_conferido"] and depois["modulo_temporario_conferido"]
        mudaram = {t for t, v in antes["versoes_tarefas"].items() if depois["versoes_tarefas"][t] != v}
        anteriores_ao_e1 = ref in {ORIGEM, BASE}
        assert par["upgrade_e1_e2"] == anteriores_ao_e1
        if anteriores_ao_e1:
            assert len(mudaram) == 11 and mudaram == set(antes["versoes_tarefas"])
            assert antes["codigo_tarefas_sha256"] != depois["codigo_tarefas_sha256"]
        else:
            assert mudaram == ({"funil", "mapbiomas"} if ref == pr81 else {"funil", "mapbiomas", "filtros"})
            assert antes["codigo_tarefas_sha256"] == depois["codigo_tarefas_sha256"]
        assert mudaram == set(par["tarefas_alteradas"])
        assert set(par["tarefas_preservadas"]) == set(antes["versoes_tarefas"]) - mudaram
        assert len(par["diff_sha256"]) == 64 and par["arquivos_status"]
        assert par["escopos"] == ["motor/", "raiz/", "nativo/", "uv.lock"]
        dep = par["dependencias"]
        assert dep["pacotes_origem"] > 200 and dep["todos_preservados_integralmente"]
        assert dep["projeto_editavel_excluido"] == ["raiz"]
        assert par["guardas_comuns_comprovadas"] == ["embargo_legado", "adocao_comprovada"]
        assert par["protecao_pr81"] == ("ja_presente" if ref == pr81 else "adicionada")
    legado = prova["guardas_comuns"]["embargo_legado"]
    adocao = prova["guardas_comuns"]["adocao_comprovada"]
    assert legado["ocorrencias"] == {"helper_antes": 0, "helper_depois": 1, "bloco_antes": 1, "chamada_depois": 1}
    assert legado["resto_municipio"]["antes_sha256"] == legado["resto_municipio"]["depois_sha256"]
    assert adocao["canonical_conferido"] and adocao["referencia"] == DESTINO
    assert set(adocao["resto_plano_execucao_sha256"]) == {"plano", "processar_municipio"}
    for guarda in prova["guardas_comuns"].values():
        assert set(guarda["origens"]) == set(PROMOCOES)
        resto = guarda["resto_modulo"]
        assert resto["iguais"] and resto["antes_sha256"] == resto["depois_sha256"]
        assert guarda["arquivo_antes_sha256"] != guarda["arquivo_depois_sha256"]
        assert len(guarda["diff_sha256"]) == 64
    assert set(prova["guardas_pr81"]) == {"_falha", "embargos_ativos"}
    for guarda in prova["guardas_pr81"].values():
        assert guarda["origem"] == pr79 and guarda["destino"] == pr81
        assert guarda["canonical_conferido"] and guarda["resto_modulo"]["iguais"]
    upgrade = prova["upgrade_pr79"]
    assert upgrade["destino"] == pr79 and len(upgrade["diff_sha256"]) == 64
    assert {
        "M\traiz/funil/rodar.py",
        "M\traiz/funil/restricoes.py",
        "M\traiz/funil/duck.py",
        "A\traiz/coleta/prodes.py",
        "M\traiz/executor/tarefas.py",
    } <= set(upgrade["arquivos_status"])
    assert prova["mapbiomas"]["formulas"] == ["ha_pixel", "por_imovel"]
    assert {"ANO", "TEMAS", "FLORESTA", "PASTO", "AGRICULTURA", "SILVICULTURA"} <= set(
        prova["mapbiomas"]["configuracao"]
    )


@pytest.mark.parametrize("origem", F.PROMOCOES_CONTINUACAO)
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


@pytest.mark.parametrize("origem", F.PROMOCOES_CONTINUACAO)
def test_falha_reconciliada_promove_retentativa_sem_continuacao(origem):
    pedido = _antigo(continuacao=0, ref=origem)
    estado = {**F.vazio(), "planejadores": ["1", "2"],
              "reservas": [{"run_id": "1", "unidade": "BA-1", "pedido": pedido}]}  # fmt: skip
    runs = {"1": _run("BA-1", status="completed", conclusion="failure"), "2": _run()}
    assert F.admitir(estado, runs, "2", [], O._e_unidade) == [_promovido({**pedido, "falhas": 1})]


@pytest.mark.parametrize("cancelado", [True, False])
@pytest.mark.parametrize("origem", F.PROMOCOES_CONTINUACAO)
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
        {"ref": F.DESTINO_CONTINUACAO},
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


@pytest.mark.parametrize("origem", F.PROMOCOES_CONTINUACAO)
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


def _conferir_versoes_antes_da_carga_estrita(esperadas, monkeypatch):
    from raiz.executor import tarefas

    # #93 mudou só a chamada da carga em rodar.py, que participa do hash das 11 tarefas.
    # A fila continua no commit fechado anterior; não atribuir a versão da main aos seus resultados.
    rodar = RAIZ / "raiz/funil/rodar.py"
    novo = rodar.read_bytes()
    chamada = b"depois_da_carga(eng, cod, estrito=True)"
    assert novo.count(chamada) == 1
    anterior_rodar = novo.replace(chamada, b"depois_da_carga(eng, cod)")
    ler = Path.read_bytes
    with monkeypatch.context() as m:
        m.setattr(Path, "read_bytes", lambda p: anterior_rodar if p == rodar else ler(p))
        assert esperadas == {n: tarefas.versao(n) for n in tarefas.CODIGO}
    assert all(esperadas[n] != tarefas.versao(n) for n in tarefas.CODIGO)


def test_promocao_urgente_vincula_prova_anterior_e_codigo_corrigido(monkeypatch):
    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-urgente.json").read_text())
    anterior = RAIZ / "docs/passagem/auditoria-promocao-publicador.json"
    assert prova["auditoria_anterior_sha256"] == hashlib.sha256(anterior.read_bytes()).hexdigest()
    assert prova["base_cientifica"] == DESTINO
    assert prova["destino"] == F.DESTINO_URGENTE_PR95
    assert F.PROMOCOES_URGENTE_PR95 == {o: prova["destino"] for o in prova["origens"]}
    assert set(PROMOCOES) < set(prova["origens"])
    atual = prova["commits"][prova["destino"]]
    _conferir_versoes_antes_da_carga_estrita(atual["versoes_tarefas"], monkeypatch)
    assert atual["versoes_tarefas"] == prova["commits"][DESTINO]["versoes_tarefas"]
    assert len(atual["armazem_sha256"]) == 64  # bytes históricos; o leitor mudou na rodada 12
    assert {p["origem"] for p in prova["comparacoes"]} == set(F.PROMOCOES_URGENTE_PR95)
    for par in prova["comparacoes"]:
        origem = prova["commits"][par["origem"]]
        assert origem["modulo_temporario_conferido"]
        assert origem["codigo_nativo_sha256"] == atual["codigo_nativo_sha256"]
        assert par["dependencias_integralmente_preservadas"] and par["pacotes_preservados"] > 200
        assert len(par["diff_sha256"]) == 64
        mudaram = {n for n, v in origem["versoes_tarefas"].items() if v != atual["versoes_tarefas"][n]}
        assert mudaram == set(par["tarefas_alteradas"])
        assert set(par["tarefas_preservadas"]) == set(atual["versoes_tarefas"]) - mudaram


def test_promocao_rodada12_preserva_ciencia_e_vincula_as_duas_provas(monkeypatch):
    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-rodada12.json").read_text())
    for chave, nome in (
        ("auditoria_anterior_sha256", "auditoria-promocao-publicador.json"),
        ("auditoria_urgente_sha256", "auditoria-promocao-urgente.json"),
    ):
        assert prova[chave] == hashlib.sha256((RAIZ / "docs/passagem" / nome).read_bytes()).hexdigest()
    assert prova["destino"] == F.DESTINO_CONTINUACAO
    assert F.PROMOCOES_CONTINUACAO == {o: prova["destino"] for o in prova["origens"]}
    destino = prova["commits"][prova["destino"]]
    _conferir_versoes_antes_da_carga_estrita(destino["versoes_tarefas"], monkeypatch)
    assert destino["armazem_sha256"] == hashlib.sha256((RAIZ / "raiz/executor/armazem.py").read_bytes()).hexdigest()
    assert {p["origem"] for p in prova["comparacoes"]} == set(F.PROMOCOES_CONTINUACAO)
    anterior = json.loads((RAIZ / "docs/passagem/auditoria-promocao-urgente.json").read_text())
    anteriores = {p["origem"]: p for p in anterior["comparacoes"]}
    for par in prova["comparacoes"]:
        origem = prova["commits"][par["origem"]]
        assert origem["modulo_temporario_conferido"]
        for chave in ("codigo_nativo_sha256", "depende", "saidas"):
            assert origem[chave] == destino[chave]
        assert par["dependencias_integralmente_preservadas"] and par["pacotes_preservados"] > 200
        mudaram = sorted(n for n, v in origem["versoes_tarefas"].items() if destino["versoes_tarefas"][n] != v)
        assert par["tarefas_alteradas"] == mudaram
        assert mudaram == (anteriores[par["origem"]]["tarefas_alteradas"] if par["origem"] in anteriores else [])
        assert len(par["diff_sha256"]) == 64


def test_armazem_so_altera_leitura_na_prova_rodada12():
    import ast

    prova = json.loads((RAIZ / "docs/passagem/auditoria-promocao-rodada12.json").read_text())
    arvore = ast.parse((RAIZ / "raiz/executor/armazem.py").read_text())
    classe = next(n for n in arvore.body if isinstance(n, ast.ClassDef) and n.name == "ArmazemRelease")
    alterados = {"_assets", "_baixar_asset", "_erros_privados"}
    classe.body = [n for n in classe.body if not (isinstance(n, ast.FunctionDef) and n.name in alterados)]
    arvore.body = [n for n in arvore.body if not (isinstance(n, ast.ClassDef) and n.name == "FalhaHTTPPrivada")]
    guarda = prova["leitura_assets"]
    assert set(guarda["metodos_alterados"]) == {f"ArmazemRelease.{n}" for n in alterados}
    assert guarda["classe_status"] == "FalhaHTTPPrivada"
    assert guarda["origem"] == F.DESTINO_URGENTE_PR95 and guarda["destino"] == F.DESTINO_CONTINUACAO
    assert guarda["restante_identico"] and guarda["tentativas"] == 4
    assert (
        guarda["restante_ast_sha256"] == hashlib.sha256(ast.dump(arvore, include_attributes=False).encode()).hexdigest()
    )
