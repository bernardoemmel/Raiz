"""Prova local do rollup municipal e do CAS, sem acesso ao GitHub."""

import copy
import datetime as dt
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from raiz.executor import status_publico as S

AGORA = dt.datetime(2026, 11, 13, 0, tzinfo=dt.UTC)


def evento(cod=None, *, situacao="em_execucao", unidade="PA-1", run="100", attempt=1, observado=AGORA):
    return {
        "cod_ibge": cod or sorted(S.municipios_ibge()["PA"])[0],
        "situacao": situacao,
        "unidade": unidade,
        "run_id": run,
        "run_attempt": attempt,
        "observado_em": observado.isoformat(timespec="seconds"),
        "ultima_mudanca_em": observado.isoformat(timespec="seconds"),
        "valido_ate": (observado + dt.timedelta(seconds=120)).isoformat(timespec="seconds"),
    }


def estado(dado, uf="PA"):
    return next(e for e in dado["estados"] if e["uf"] == uf)


def test_regua_oficial_completa_sem_ler_linhas_de_imoveis():
    regua = S.municipios_ibge()
    assert len(regua) == 27 and sum(map(len, regua.values())) == 5571
    assert len(regua["PA"]) == 144


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("cod_imovel", "PRIVADO"),
        ("erro", "SEGREDO"),
        ("cod_ibge", "1599999"),
        ("unidade", "RN-1"),
        ("run_id", "100/segredo"),
        ("run_attempt", True),
        ("situacao", "em andamento: SEGREDO"),
        ("observado_em", "2026-11-13T00:00:00"),
        ("ultima_mudanca_em", "2026-11-13T00:00:01Z"),
        ("valido_ate", "2026-11-13T01:00:01Z"),
    ],
)
def test_evento_fora_do_contrato_nao_chega_ao_git(campo, valor, monkeypatch, tmp_path):
    def nunca(*args):
        pytest.fail("nenhuma leitura/escrita Git antes de recusar dados privados")

    monkeypatch.setattr(S, "RepositorioStatus", nunca)
    dado = evento()
    dado[campo] = valor
    with pytest.raises(ValueError) as erro:
        S.publicar_eventos([dado], repositorio=tmp_path)
    assert not any(v in str(erro.value) for v in ("PRIVADO", "SEGREDO", "1599999"))


def test_recusa_duplicacao_no_mesmo_lote_e_futuro():
    with pytest.raises(ValueError, match="duplicada"):
        S.validar_eventos([evento(), evento()], agora=AGORA)
    with pytest.raises(ValueError, match="futuro"):
        S.validar_eventos([evento(observado=AGORA + dt.timedelta(minutes=1))], agora=AGORA)


def test_tentativa_nova_prevalece_sobre_worker_antigo_ainda_vivo():
    primeira = evento(run="100", attempt=1, observado=AGORA + dt.timedelta(seconds=30))
    nova = evento(run="100", attempt=2, situacao="pronto")
    assert S.juntar_eventos([primeira], [nova]) == [nova]
    assert S.juntar_eventos([nova], [primeira]) == [nova]
    rodada = evento(run="101", situacao="pendente")
    assert S.juntar_eventos([nova], [rodada]) == [rodada]


def test_recusa_empate_contraditorio_sem_escolher_conclusao_favoravel():
    with pytest.raises(ValueError, match="conflitantes"):
        S.juntar_eventos([evento()], [evento(situacao="pronto")])


def test_preserva_microsegundos_no_inicio_e_fim_do_mesmo_segundo():
    inicio, fim = evento(), evento(situacao="pronto")
    fim["observado_em"] = fim["ultima_mudanca_em"] = (AGORA + dt.timedelta(microseconds=1)).isoformat()
    a = S.validar_eventos([inicio], agora=AGORA)[0]
    b = S.validar_eventos([fim], agora=AGORA)[0]
    assert S.juntar_eventos([a], [b]) == [b]
    assert ".000001" in b["observado_em"]


def test_duas_fatias_e_retencao_duplicada_contam_municipio_uma_vez():
    a, b = sorted(S.municipios_ibge()["PA"])[:2]
    antigos = [evento(a), evento(b, unidade="PA-2", situacao="com_erro")]
    novos = [evento(a, situacao="pronto", attempt=2)]
    d = S.documento(S.juntar_eventos(antigos, novos), agora=AGORA)
    pa = estado(d)
    assert pa["escopo"] == "uf" and pa["municipios_total"] == 144
    assert pa["municipios"] == {
        "prontos": 1,
        "em_execucao": 0,
        "com_erro": 1,
        "pendentes": 0,
        "desconhecidos": 142,
    }
    assert estado(d, "RN")["situacao"] == "sem_telemetria"
    assert len(d["eventos"]) == 2


def test_lease_expirado_vira_desconhecido_sem_apagar_erro_observado():
    a, b = sorted(S.municipios_ibge()["PA"])[:2]
    dados = [
        evento(a, observado=AGORA - dt.timedelta(minutes=3)),
        evento(b, situacao="com_erro"),
    ]
    pa = estado(S.documento(dados, agora=AGORA))
    assert pa["municipios"]["em_execucao"] == 0
    assert pa["municipios"]["desconhecidos"] == 143
    assert pa["municipios"]["com_erro"] == 1
    assert sum(pa["municipios"].values()) == 144


def test_menor_lease_prevalece_sobre_heartbeat_de_outro_worker():
    a, b = sorted(S.municipios_ibge()["PA"])[:2]
    pa = estado(S.documento([evento(a, observado=AGORA - dt.timedelta(seconds=90)), evento(b)], agora=AGORA))
    assert pa["valido_ate"] == (AGORA + dt.timedelta(seconds=30)).isoformat()


def test_snapshot_anterior_tem_rollup_recalculado_e_chaves_estritas():
    dado = S.documento([evento()], agora=AGORA)
    assert len(S._ler_documento(json.dumps(dado), agora=AGORA)) == 1
    alterado = copy.deepcopy(dado)
    estado(alterado)["municipios"]["prontos"] = 3
    with pytest.raises(ValueError, match="diverge"):
        S._ler_documento(json.dumps(alterado), agora=AGORA)
    dado["privado"] = "SEGREDO"
    with pytest.raises(ValueError, match="campos desconhecidos"):
        S._ler_documento(json.dumps(dado), agora=AGORA)


def test_snapshot_entre_micros_de_expiracao_rele_sem_alterar_status():
    fonte = evento(observado=AGORA - dt.timedelta(seconds=119))
    fonte["observado_em"] = fonte["ultima_mudanca_em"] = (AGORA - dt.timedelta(seconds=119.5)).isoformat()
    fonte["valido_ate"] = (AGORA + dt.timedelta(seconds=0.5)).isoformat()
    agora = AGORA + dt.timedelta(seconds=0.8)
    dado = S.documento([fonte], agora=agora)
    assert dado["gerado_em"] == agora.isoformat()
    assert len(S._ler_documento(json.dumps(dado), agora=agora)) == 1
    assert estado(dado)["municipios"]["desconhecidos"] == 144


def git(pasta: Path, *args):
    return subprocess.run(["git", "-C", str(pasta), *args], capture_output=True, text=True, check=True).stdout


class Local(S.RepositorioStatus):
    """Somente fixture: o remoto é um bare no tmp_path, nunca o GitHub."""

    def __init__(self, pasta):
        self.pasta = pasta


@pytest.fixture
def clones(tmp_path):
    remoto = tmp_path / "remoto.git"
    remoto.mkdir()
    git(remoto, "init", "--bare", "-q")
    saida = []
    for nome in ("a", "b"):
        pasta = tmp_path / nome
        pasta.mkdir()
        git(pasta, "init", "-q")
        git(pasta, "remote", "add", "origin", str(remoto))
        saida.append(Local(pasta))
    return *saida, remoto


def test_cas_concorrente_real_preserva_dois_estados_sem_historico(clones):
    a, b, remoto = clones
    sha_a, _ = a.ler(agora=AGORA)
    sha_b, _ = b.ler(agora=AGORA)
    d1 = S.documento([evento()], agora=AGORA)
    rn = evento(sorted(S.municipios_ibge()["RN"])[0], unidade="RN-1")
    d2 = S.documento([rn], agora=AGORA)
    assert sha_a == sha_b == ""
    assert a.trocar(sha_a, d1)
    assert not b.trocar(sha_b, d2)  # CAS recusou sobrescrever o primeiro escritor
    sha, anteriores = b.ler(agora=AGORA)
    unido = S.documento(S.juntar_eventos(anteriores, [rn]), agora=AGORA)
    assert b.trocar(sha, unido)
    _, eventos = a.ler(agora=AGORA)
    assert len(eventos) == 2
    assert git(remoto, "rev-list", "--count", S.REF).strip() == "1"
    assert git(remoto, "ls-tree", "--name-only", S.REF).strip() == "processamento.json"
    assert git(remoto, "for-each-ref", "--format=%(refname)").strip() == S.REF
    assert not (a.pasta / "processamento.json").exists()  # sem checkout/índice de trabalho


def test_pushes_simultaneos_releem_cas_servidor_e_preservam_ambas_ufs(clones, monkeypatch):
    a, b, remoto = clones
    # Ambos anunciam a ref vazia antes do primeiro recebimento terminar. Assim a
    # rejeição vem do CAS do servidor, não do aviso antecipado "stale info".
    hook = remoto / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\nsleep 0.3\ncat >/dev/null\n")
    hook.chmod(0o700)
    monkeypatch.setattr(S, "RepositorioStatus", Local)
    rn = evento(sorted(S.municipios_ibge()["RN"])[0], unidade="RN-1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(S.publicar_eventos, [e], repositorio=r.pasta) for r, e in ((a, evento()), (b, rn))]
        resultados = [f.result() for f in futuros]
    assert sorted(r["municipios"] for r in resultados) == [1, 2]
    _, eventos = a.ler(agora=dt.datetime.now(dt.UTC))
    assert len(eventos) == 2
    assert git(remoto, "rev-list", "--count", S.REF).strip() == "1"


def test_transporte_recusa_origem_alheia_antes_de_consultar_ref(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "remote", "add", "origin", "https://example.test/fora.git")
    with pytest.raises(ValueError, match="repositório autorizado"):
        S.RepositorioStatus(tmp_path)


def test_publicador_rele_cas_antes_de_tentar_novamente(monkeypatch, tmp_path):
    rn = evento(sorted(S.municipios_ibge()["RN"])[0], unidade="RN-1")
    tentados = []

    class Concorrente:
        def __init__(self, pasta):
            self.n = 0

        def ler(self, *, agora):
            self.n += 1
            return ("a", []) if self.n == 1 else ("b", [rn])

        def trocar(self, sha, dado):
            tentados.append((sha, len(dado["eventos"])))
            return self.n == 2

    monkeypatch.setattr(S, "RepositorioStatus", Concorrente)
    resultado = S.publicar_eventos([evento()], repositorio=tmp_path)
    assert tentados == [("a", 1), ("b", 2)]
    assert resultado == {"municipios": 2, "estados": 2}
