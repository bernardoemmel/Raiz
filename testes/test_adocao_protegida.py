"""CSV legado não recebe versão atual nem validação científica por adoção."""

import hashlib

import pytest

from raiz.executor.armazem import ArmazemLocal, ler_json, por_json
from raiz.executor.executor import Executor, Tarefa


@pytest.fixture
def executor(tmp_path):
    chamadas = []

    def rodar(nome):
        def executar(uf, cod, pasta):
            chamadas.append(nome)
            arquivo = "imoveis" if nome == "funil" else nome
            (pasta / f"{arquivo}_{cod}.csv").write_text(f"resultado novo de {nome}\n")

        return executar

    tarefas = [
        Tarefa("funil", (), ("imoveis_{cod}.csv", "auxiliar_{cod}.json"), lambda: "funil-v2", rodar("funil")),
        Tarefa("filtros", ("funil",), ("filtros_{cod}.csv",), lambda: "filtros-v2", rodar("filtros")),
    ]
    return Executor(ArmazemLocal(tmp_path / "armazem"), tmp_path / "trabalho", tarefas), chamadas


def guardar(ex, nome, versao=None, dados=b"resultado legado\n"):
    meta = {"data": "2025-01-02T03:04:05+00:00"}
    if versao is not None:
        meta["versao"] = versao
    chave = ex.chave_saida("PA", nome)
    ex.a.por_bytes(chave, dados, meta)
    return chave


@pytest.mark.parametrize("versao", [None, "", "publicado", "funil-v1"])
def test_recusa_versao_nao_comprovada_sem_reescrever_dados_ou_origem(executor, versao):
    ex, chamadas = executor
    chave = guardar(ex, "imoveis_1.csv", versao)
    guardar(ex, "filtros_1.csv", "filtros-v2")
    antes = {k: (ex.a.ler(k), ex.a.meta(k)) for k in ex.a.listar("saida/PA/")}

    assert ex.adotar("PA", [1]) == {"adotados": 0, "ja_tinham_marca": 0, "tarefas": {}}
    assert ler_json(ex.a, "marcas/PA/1.json") is None
    assert {k: (ex.a.ler(k), ex.a.meta(k)) for k in antes} == antes
    assert ex.plano("PA", 1) == ["funil", "filtros"]
    assert chamadas == []

    resultado = ex.processar_municipio("PA", 1)
    assert resultado["rodadas"] == chamadas == ["funil", "filtros"]
    assert resultado["erro"] is None
    assert ex.a.meta(chave)["versao"] == "funil-v2"
    assert ex.plano("PA", 1) == []


def test_adota_mesma_versao_e_preserva_data_e_metadados_de_origem(executor):
    ex, chamadas = executor
    principal = guardar(ex, "imoveis_1.csv", "funil-v2")
    guardar(ex, "auxiliar_1.json", "funil-v2")
    guardar(ex, "filtros_1.csv", "filtros-v2")
    antes = {k: (ex.a.ler(k), ex.a.meta(k)) for k in ex.a.listar("saida/PA/")}

    assert ex.adotar("PA", [1])["tarefas"] == {"funil": 1, "filtros": 1}
    marca = ler_json(ex.a, "marcas/PA/1.json")
    assert marca["tarefas"]["funil"]["data"] == antes[principal][1]["data"]
    assert marca["adotado_em"] != marca["tarefas"]["funil"]["data"]
    assert ex.plano("PA", 1) == []
    assert ex.processar_municipio("PA", 1)["puladas"] == ["funil", "filtros"]
    assert chamadas == []
    assert {k: (ex.a.ler(k), ex.a.meta(k)) for k in antes} == antes


@pytest.mark.parametrize("versao_auxiliar", [None, "publicado", "funil-v1"])
def test_nao_adota_tarefa_com_saida_secundaria_de_versao_mista(executor, versao_auxiliar):
    ex, _ = executor
    guardar(ex, "imoveis_1.csv", "funil-v2")
    guardar(ex, "auxiliar_1.json", versao_auxiliar)
    guardar(ex, "filtros_1.csv", "filtros-v2")
    assert ex.adotar("PA", [1])["tarefas"] == {}
    assert ex.plano("PA", 1) == ["funil", "filtros"]


def test_adota_so_dependencias_comprovadas_e_recalcula_tarefa_divergente(executor):
    ex, chamadas = executor
    guardar(ex, "imoveis_1.csv", "funil-v2")
    guardar(ex, "filtros_1.csv", "filtros-v1")
    assert ex.adotar("PA", [1])["tarefas"] == {"funil": 1}
    assert ex.plano("PA", 1) == ["filtros"]
    assert ex.processar_municipio("PA", 1)["rodadas"] == ["filtros"]
    assert chamadas == ["filtros"]


@pytest.mark.parametrize("versao", [None, "publicado", "funil-v1"])
def test_marca_adotada_com_assinatura_atual_nao_legitima_csv_velho(executor, versao):
    ex, chamadas = executor
    chave = guardar(ex, "imoveis_1.csv", versao)
    origem = ex.a.meta(chave)
    marca = {"uf": "PA", "cod": 1, "tarefas": {}}
    marca["tarefas"]["funil"] = {
        "versao": "funil-v2",
        "assinatura": ex.assinatura(ex.tarefas[0], "PA", 1, marca),
        "saidas": {"imoveis_1.csv": origem["sha256"]},
        "adotado": True,
    }
    por_json(ex.a, "marcas/PA/1.json", marca)

    assert ex.adotar("PA", [1])["ja_tinham_marca"] == 1
    assert ex.a.meta(chave) == origem
    assert ex.plano("PA", 1) == ["funil", "filtros"]
    assert ex.processar_municipio("PA", 1)["rodadas"] == ["funil", "filtros"]
    assert chamadas == ["funil", "filtros"]
    assert "adotado" not in ex.marca("PA", 1)["tarefas"]["funil"]


def test_marca_adotada_nao_encobre_substituicao_dos_bytes(executor):
    ex, chamadas = executor
    chave = guardar(ex, "imoveis_1.csv", "funil-v2")
    ex.adotar("PA", [1])
    antigo = ex.marca("PA", 1)["tarefas"]["funil"]["saidas"]["imoveis_1.csv"]
    guardar(ex, "imoveis_1.csv", "funil-v2", dados=b"outra execucao\n")
    assert ex.a.meta(chave)["sha256"] != antigo
    assert ex.a.meta(chave)["sha256"] == hashlib.sha256(b"outra execucao\n").hexdigest()
    assert ex.plano("PA", 1)[0] == "funil"
    assert ex.processar_municipio("PA", 1)["rodadas"] == chamadas == ["funil", "filtros"]


def test_adocao_nao_inventa_data_de_execucao_ausente(executor):
    ex, _ = executor
    ex.a.por_bytes("saida/PA/imoveis_1.csv", b"historico", {"versao": "funil-v2"})
    ex.adotar("PA", [1])
    assert ex.marca("PA", 1)["tarefas"]["funil"]["data"] is None
