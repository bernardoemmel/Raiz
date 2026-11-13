"""Referências artificiais só para testar integridade; não são evidência de Claude."""

import asyncio
import copy
import hashlib
import json

import pytest
import yaml

from raiz.publica.agente_real import Cenario, hash_json
from raiz.publica.avaliacao import Execucao, avaliar, carregar_gabarito
from scripts.reproduzir_agentes import ProvedorReplay, Referencia, _chamadas_http
from testes.test_avaliacao_agentes import _registros


@pytest.fixture
def referencia(tmp_path):
    pasta = tmp_path / "referencia"
    (pasta / "cassetes").mkdir(parents=True)
    gabarito = carregar_gabarito()
    config = {"modelo": "fixture-sem-llm", "modelo_juiz": "fixture-sem-llm", "max_passos": 12, "max_tokens": 2048}
    registros = [
        Execucao.model_validate({**r, "configuracao_sha256": hash_json(config)})
        for r in _registros(gabarito, origem="agente_real")
    ]
    relatorio = avaliar(registros, *gabarito)
    relatorio["metricas"] = []
    (pasta / "configuracao.json").write_text(json.dumps(config))
    (pasta / "execucoes.jsonl").write_text("\n".join(r.model_dump_json() for r in registros))
    for r in registros:
        nome = f"{r.tarefa_id}-{r.tentativa}"
        arquivo = pasta / "cassetes" / f"{nome}.yaml"
        interacao = {
            "request": {"headers": {}, "body": json.dumps({"raiz_requisicao_sha256": "a" * 64})},
            "response": {"status": {"code": 200}, "headers": {}, "body": {"string": json.dumps({"content": []})}},
        }
        arquivo.write_text(yaml.safe_dump({"version": 1, "interactions": [interacao, interacao]}))
        trace = pasta / f"trace-{nome}.json"
        trace.write_text(json.dumps({"resposta": "Resposta artificial."}))
        relatorio["metricas"].append(
            {
                "tarefa_id": r.tarefa_id,
                "tentativa": r.tentativa,
                "passos_modelo": 1,
                "cassete_sha256": hashlib.sha256(arquivo.read_bytes()).hexdigest(),
                "trace_sha256": hashlib.sha256(trace.read_bytes()).hexdigest(),
            }
        )
    (pasta / "relatorio.json").write_text(json.dumps(relatorio))
    return pasta


def test_referencia_exige_96_sessoes_reais_aprovadas_e_hashes(referencia):
    assert len(Referencia(referencia).registros) == 96
    arquivo = referencia / "execucoes.jsonl"
    linhas = arquivo.read_text().splitlines()
    arquivo.write_text("\n".join(linhas[:-1]))
    with pytest.raises(ValueError, match="quatro execuções"):
        Referencia(referencia)
    arquivo.write_text("\n".join(linhas).replace('"origem":"agente_real"', '"origem":"contrato"'))
    with pytest.raises(ValueError, match="real completa"):
        Referencia(referencia)


def test_cassete_modificada_reprovada_antes_de_conectar_mcp(referencia):
    cassete = next((referencia / "cassetes").glob("*.yaml"))
    cassete.write_text(cassete.read_text() + "\n# alteração\n")
    with pytest.raises(ValueError, match="alterado"):
        Referencia(referencia)


def test_replay_separa_agente_do_juiz_preservando_original(referencia, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ref = Referencia(referencia)
    destino = tmp_path / "replay"
    ref.cassetes_do_agente(destino)
    assert len(list(destino.glob("*.yaml"))) == 96
    nome = next(destino.glob("*.yaml")).name
    assert len(yaml.safe_load((destino / nome).read_text())["interactions"]) == 1
    assert len(yaml.safe_load((referencia / "cassetes" / nome).read_text())["interactions"]) == 2
    with pytest.raises(ValueError, match="pasta nova"):
        ref.cassetes_do_agente(destino)


def test_nota_congelada_nao_supera_barreira_atual(referencia):
    ref = Referencia(referencia)
    tarefa = next(t for t in carregar_gabarito()[0].tarefas if t.id == "outra_empresa")
    p = ProvedorReplay()
    p.referencia = ref

    async def snapshot(_):
        return {}

    p.snapshot = snapshot
    cenario = Cenario("", "http://localhost/mcp/", "", {"referencia_tentativa": 1})
    trace = {"chamadas": [], "resposta": "", "erro": "limite_de_passos"}
    nota = asyncio.run(p.julgar(tarefa, cenario, trace))
    assert trace["julgamento"]["chamadas_modelo"] == 0
    assert trace["julgamento"]["uso"] == {"input_tokens": 0, "output_tokens": 0}
    assert not any(nota.criterios.values())
    assert ref.registros[tarefa.id, 1].criterios == dict.fromkeys(tarefa.esperado, True)


@pytest.mark.parametrize("chamadas_juiz", [0, 3])
def test_correcoes_do_juiz_nao_entram_no_replay_do_agente(referencia, tmp_path, chamadas_juiz):
    relatorio = json.loads((referencia / "relatorio.json").read_text())
    metrica = relatorio["metricas"][0]
    if chamadas_juiz == 0:
        arquivo_registros = referencia / "execucoes.jsonl"
        registros = [Execucao.model_validate_json(linha) for linha in arquivo_registros.read_text().splitlines()]
        registros[0].criterios = dict.fromkeys(registros[0].criterios, False)
        arquivo_registros.write_text("\n".join(r.model_dump_json() for r in registros))
        relatorio.update(avaliar(registros, *carregar_gabarito()))
    nome = f"{metrica['tarefa_id']}-{metrica['tentativa']}.yaml"
    arquivo = referencia / "cassetes" / nome
    dados = yaml.safe_load(arquivo.read_text())
    dados["interactions"] = dados["interactions"][:1] + dados["interactions"][-1:] * chamadas_juiz
    arquivo.write_text(yaml.safe_dump(dados))
    metrica.update(chamadas_juiz=chamadas_juiz, cassete_sha256=hashlib.sha256(arquivo.read_bytes()).hexdigest())
    (referencia / "relatorio.json").write_text(json.dumps(relatorio))
    destino = tmp_path / "replay-com-correcao"
    Referencia(referencia).cassetes_do_agente(destino)
    assert len(yaml.safe_load((destino / nome).read_text())["interactions"]) == 1
    assert len(yaml.safe_load(arquivo.read_text())["interactions"]) == 1 + chamadas_juiz


def test_replay_preserva_erros_http_do_agente_sem_incluir_juiz(referencia, tmp_path):
    relatorio = json.loads((referencia / "relatorio.json").read_text())
    metrica = relatorio["metricas"][0]
    nome = f"{metrica['tarefa_id']}-{metrica['tentativa']}.yaml"
    arquivo = referencia / "cassetes" / nome
    dados = yaml.safe_load(arquivo.read_text())
    agente, juiz = dados["interactions"]
    erro = copy.deepcopy(agente)
    erro["response"]["status"]["code"] = 503
    dados["interactions"] = [erro, agente, erro, erro, juiz]
    arquivo.write_text(yaml.safe_dump(dados))
    metrica.update(
        retentativas_http_agente=1,
        retentativas_http_juiz=2,
        cassete_sha256=hashlib.sha256(arquivo.read_bytes()).hexdigest(),
    )
    (referencia / "relatorio.json").write_text(json.dumps(relatorio))
    destino = tmp_path / "com-falhas-http"
    Referencia(referencia).cassetes_do_agente(destino)
    assert [i["response"]["status"]["code"] for i in yaml.safe_load((destino / nome).read_text())["interactions"]] == [
        503,
        200,
    ]
    assert len(yaml.safe_load(arquivo.read_text())["interactions"]) == 5
    for invalidas in ([erro], [erro] * 3 + [agente], [erro, {**agente, "request": {"body": "outro"}}]):
        with pytest.raises(ValueError):
            _chamadas_http(invalidas)
