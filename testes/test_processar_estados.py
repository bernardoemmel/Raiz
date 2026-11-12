"""Fila do processamento do Brasil (motor/rodar_estado.py --planejar): estados grandes em fatias por longitude que
somam o estado; estados novos entram antes da manutenção (tarefa nova em estado já feito), que não passa do teto; job
antigo do estado inteiro segura as fatias dele; o próximo da fila pega uma unidade só; continuação por fatia."""

import datetime as dt
import sys
from pathlib import Path

import pytest

MOTOR = Path(__file__).resolve().parents[1] / "motor"
sys.path.insert(0, str(MOTOR))

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


def test_proximo_da_fila_pega_uma_unidade_e_pula_a_tentada_ha_pouco(plano, monkeypatch):
    monkeypatch.setattr(O, "ufs_ativas", lambda: ({"MG-1"}, 0))
    assert O.planejar([], set(), "proximo", liberou="MG-1") == ["MG-1"]  # a vaga do MG-1 acabou de ficar livre
    # fatia que terminou dentro do prazo há pouco, mas com erro: fica para a rodada semanal
    plano["MG"] = {"municipios": 100, "total_ibge": 853, "completo": False, "faltam": {"imoveis": 753}, "controle": "x",
                   "motor": {"fatias": {"1": {"completo": False, "faltam": {"imoveis": 7},
                                              "rodada": {"fim": _agora(0.1), "parou_por_tempo": False}}}}}  # fmt: skip
    assert O.planejar([], set(), "proximo", liberou="MG-1") == ["MG-2"]


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
