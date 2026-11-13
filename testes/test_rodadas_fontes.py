"""Falhas antes do primeiro município ficam privadas, visíveis e fora do ciclo de redisparo."""

import copy
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from raiz.executor.rodadas import registrar_tentativa
from testes.test_armazem_release import GitHubFalso, _armazem

MOTOR = Path(__file__).resolve().parents[1] / "motor"
sys.path.insert(0, str(MOTOR))

import painel as P  # noqa: E402
import rodar_estado as O  # noqa: E402


def _tentativa(fatia=1, dias=0):
    rodada = {
        "fim": (dt.datetime.now(dt.UTC) - dt.timedelta(days=dias)).isoformat(),
        "parou_por_tempo": False,
        "progresso": 0,
        "falhou_fontes": True,
    }
    motor = {"commit": "a" * 40, "rodada": rodada}
    if fatia:
        motor["fatias"] = {str(fatia): {"rodada": rodada, "completo": False, "erros": 1}}
    return {"motor": motor, "erros": [{"etapa": "fontes", "mensagem": "diagnostico-interno-exemplo"}]}


def test_primeira_tentativa_sem_csv_so_grava_indice_privado(tmp_path):
    gh, gh_publico = GitHubFalso(), GitHubFalso()
    gh_publico.privado = False
    publico = _armazem(gh_publico, tmp_path / "publico", privado=False)
    arm = _armazem(gh, tmp_path / "privado", publico=publico)
    tentativa = _tentativa()

    registrar_tentativa(arm, "rn", tentativa)

    entrada = json.loads(gh.assets["estados.json"])["estados"]["RN"]
    assert entrada["motor"] == tentativa["motor"]
    assert entrada["erros"] == tentativa["erros"]
    assert entrada["atualizado_em"]
    assert gh.uploads[-1] == "estados.json"
    assert not any(n.endswith(".tar.gz") or n.startswith("raiz_controle") for n in gh.uploads)
    assert not gh_publico.uploads
    assert not gh.refs  # ambas as travas são liberadas
    assert O.tentado_ha_pouco(entrada, 1)
    assert not O.tentado_ha_pouco(entrada, 2)  # não bloqueia a fatia nunca tentada


def test_tentativa_preserva_pacote_hashes_e_outras_fatias(tmp_path):
    gh = GitHubFalso()
    pacote = gh.tar("RN", {"imoveis_2400109.csv": b"cod_imovel,ha\nCAR-TESTE,1\n"})
    gh.assets["raiz_RN.tar.gz"] = pacote
    anterior = {
        "municipios": 1,
        "versao": "cientifica-1",
        "sha256": hashlib.sha256(pacote).hexdigest(),
        "versoes": {"funil": "funil-1"},
        "motor": {"fatias": {"2": {"completo": True, "rodada": {"progresso": 1}}}},
    }
    gh.assets["estados.json"] = json.dumps({"estados": {"RN": anterior, "AC": {"municipios": 22}}}).encode()
    arm = _armazem(gh, tmp_path)

    registrar_tentativa(arm, "RN", _tentativa())

    estados = json.loads(gh.assets["estados.json"])["estados"]
    atual = estados["RN"]
    for campo in ("municipios", "versao", "sha256", "versoes"):
        assert atual[campo] == anterior[campo]
    assert atual["motor"]["fatias"]["2"] == anterior["motor"]["fatias"]["2"]
    assert atual["motor"]["fatias"]["1"]["rodada"]["falhou_fontes"] is True
    assert estados["AC"] == {"municipios": 22}
    assert gh.assets["raiz_RN.tar.gz"] == pacote
    assert "raiz_RN.tar.gz" not in gh.uploads


@pytest.mark.parametrize("privado_config,privado_remoto", [(False, True), (True, False)])
def test_tentativa_recusa_destino_publico(tmp_path, privado_config, privado_remoto):
    gh = GitHubFalso()
    gh.privado = privado_remoto
    arm = _armazem(gh, tmp_path, privado=privado_config)

    with pytest.raises(PermissionError, match="(?i)privad"):
        registrar_tentativa(arm, "RN", _tentativa())
    assert not gh.uploads
    assert not gh.refs


@pytest.mark.parametrize("parou_por_tempo", [False, True])
def test_falha_sem_avanco_nao_dispara_continuacao_nem_proximo(tmp_path, monkeypatch, parou_por_tempo):
    pasta = tmp_path / "saida" / "RN"
    pasta.mkdir(parents=True)
    (pasta / "rodada.json").write_text(
        json.dumps(
            {
                "erros": [{"etapa": "fontes"}],
                "progresso": 0,
                "completo": False,
                "parou_por_tempo": parou_por_tempo,
                "continuacao": 1,
            }
        )
    )
    monkeypatch.setattr(O, "AQUI", tmp_path)
    monkeypatch.setattr(O, "disparar", lambda *a, **kw: pytest.fail("falha sem avanço não pode redisparar"))

    O.continuar("RN-1")


def test_tentativa_expirada_volta_a_ser_elegivel():
    assert O.tentado_ha_pouco(_tentativa(dias=1), 1)
    assert not O.tentado_ha_pouco(_tentativa(dias=O.DIAS_TENTADO + 1), 1)


def test_proximo_pula_fatia_com_falha_de_fontes_e_preserva_pedido_explicito(monkeypatch):
    monkeypatch.setattr(O.S, "ORDEM", ["RN"])
    monkeypatch.setattr(O.S, "ler_manifesto", lambda: {"estados": {"RN": _tentativa()}})
    monkeypatch.setattr(O.S, "versoes", lambda: {})
    monkeypatch.setattr(O, "versoes_executor", lambda: {})
    monkeypatch.setattr(O, "ufs_ativas", lambda: (set(), 0))
    for nome in ("GITHUB_ACTIONS", "GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(nome, raising=False)

    assert O.planejar([], set(), "proximo") == ["RN-2"]
    assert O.planejar(["RN-1"], set()) == ["RN-1"]


@pytest.mark.parametrize("fatia", [0, 1])
def test_painel_mostra_falha_fontes_sem_diagnostico_privado(fatia):
    entrada = {**_tentativa(fatia), "faltam": {"imoveis": 167}}
    if fatia:
        # Outra fatia terminou depois: a rodada geral não pode esconder a que falhou.
        entrada["motor"]["rodada"] = {"falhou_fontes": False}
        entrada["motor"]["fatias"]["2"] = {"rodada": {"falhou_fontes": False}}
    texto = P.linha("RN", entrada)

    assert "falha nas fontes obrigatórias" in texto
    assert "não começou" not in texto
    assert "diagnostico-interno-exemplo" not in texto

    recuperada = copy.deepcopy(entrada)
    recuperada["motor"]["rodada"]["falhou_fontes"] = False
    for parte in recuperada["motor"].get("fatias", {}).values():
        parte["rodada"]["falhou_fontes"] = False
    assert "falha nas fontes obrigatórias" not in P.linha("RN", recuperada)


@pytest.mark.parametrize("unidade,uf,fatia", [("AC", "AC", 0), ("RN-1", "RN", 1)])
def test_executor_registra_falha_fontes_antes_do_primeiro_csv_e_falha_job(tmp_path, monkeypatch, unidade, uf, fatia):
    gh = GitHubFalso()
    arm = _armazem(gh, tmp_path / "espelho")
    execucao = SimpleNamespace(a=arm, versoes=lambda: {"funil": "funil-1"})
    monkeypatch.chdir(tmp_path)  # restaura o diretório ao fim, mesmo com o chdir do executor
    monkeypatch.setattr(O, "AQUI", tmp_path)
    tarefas = SimpleNamespace(resumo_uf=lambda *args: None)
    monkeypatch.setattr(O, "_executor", lambda: (tarefas, execucao))
    monkeypatch.setenv("RAIZ_PUBLICAR_MIN", "60")
    monkeypatch.setattr(O, "prazo", lambda: float("inf"))
    monkeypatch.setattr(O.S, "commit_atual", lambda: "a" * 40)
    monkeypatch.setattr(O.S, "acao_github", lambda *a, **kw: None)
    monkeypatch.setattr(O, "resumo_executor", lambda *a, **kw: None)
    monkeypatch.setattr(O, "_rodar_processo", lambda *a, **kw: pytest.fail("não executa sem fontes"))
    paineis = []
    monkeypatch.setattr(P, "atualizar_no_github", lambda manifesto: paineis.append(P.tabela(manifesto)))

    def fonte_indisponivel(*args):
        raise RuntimeError("diagnostico-interno-exemplo")

    monkeypatch.setattr(O, "_fontes_do_estado", fonte_indisponivel)
    with pytest.raises(RuntimeError, match="falha nas fontes obrigatórias"):
        O.rodar_executor(unidade, set(), 0)

    rel = json.loads((tmp_path / "saida" / uf / "rodada.json").read_text())
    assert rel["progresso"] == 0
    assert rel["erros"][0]["etapa"] == "fontes"
    entrada = json.loads(gh.assets["estados.json"])["estados"][uf]
    assert entrada["motor"]["rodada"]["falhou_fontes"] is True
    assert O.tentado_ha_pouco(entrada, fatia)
    assert not any(n.endswith(".tar.gz") for n in gh.uploads)
    assert len(paineis) == 1
    assert "falha nas fontes obrigatórias" in paineis[0]
    assert "diagnostico-interno-exemplo" not in paineis[0]


def test_uf_inteira_com_falha_nao_se_esconde_atras_de_fatias_antigas_boas():
    entrada = {**_tentativa(0), "completo": True, "faltam": {}, "controle": "existente"}
    entrada["motor"]["fatias"] = {"1": {"rodada": {"falhou_fontes": False}}}
    texto = P.linha("RN", entrada)
    assert "falha nas fontes obrigatórias" in texto
    assert "acervo completo; última coleta incompleta" in texto
    assert "fontes obrigatórias indisponíveis" in O.motivo(entrada, {}, {}, "RN")[0]
