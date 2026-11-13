"""Fluxos de municípios distintos, sem excluir microárea nem aceitar origem parcial."""

from pathlib import Path

import pandas as pd
import pytest

from raiz import restauracao as R
from raiz import restauracao_nacional_financeiro as F


def preparar(tmp_path, cenario="central_r11"):
    r, c = R.regra(), R.cenario(cenario)
    linhas = {
        "PEQUENA": {"cod_imovel": "PEQUENA", "ha": 0.01, "pasto_ha": 0.01, "alem_RL_ha": 0.01, "bioma": "Amazônia"},
        "MAIOR": {"cod_imovel": "MAIOR", "ha": 100.0, "pasto_ha": 100.0, "alem_RL_ha": 100.0, "bioma": "Cerrado"},
    }
    tabela = pd.DataFrame(
        [
            {
                "cod_imovel": car,
                "cod_ibge": cod,
                "papel": papel,
                "restauracao_versao": r["versao_completa"],
                "restauracao_cenario": c["cenario"],
                "credito_p50": R.fluxo_p50(li, c, r)["creditos_contrato_ha"] * li["ha"],
            }
            for (car, li), cod, papel in zip(linhas.items(), (1500107, 1721000), ("titular", "reserva"), strict=True)
        ]
    )
    arquivo = tmp_path / "selecionadas.parquet"
    tabela.to_parquet(arquivo, index=False)
    return arquivo, linhas, tabela, r, c


def test_fluxo_multiuf_inclui_pequena_reserva_multas_e_limite_contrato(tmp_path, monkeypatch):
    arquivo, linhas, tabela, r, c = preparar(tmp_path)
    consultados = []

    def ler(pasta, cod, so):
        consultados.append((pasta, cod, so))
        return {car: linhas[car] for car in so}

    monkeypatch.setattr(R, "linhas_para_refazer", ler)
    volume = 100.0
    out = F.economia_selecionadas(arquivo, {1500107: Path("PA"), 1721000: Path("TO")}, c=c, r=r, volume=volume)
    assert len(consultados) == 2 and {next(iter(x[2])) for x in consultados} == set(linhas)
    assert out["fazendas_com_fluxo"] == 2 and out["excesso_creditos"] > 0
    cron = R.cronograma_lote(float(tabela.credito_p50.sum()), c, r, volume)
    fl = R.fluxo_lote(
        [R.fluxo_p50(li, c, r) for li in linhas.values()],
        c,
        {int(m["ano"]) + 1: m["multa_esperada_rs"] for m in cron["marcos"]},
        volume=volume,
    )
    assert out["vpl_rs"] == round(R.tir_lote(fl, c)["vpl_rs"], 0)
    assert set(out["preco_minimo_usd"]) == {"12", "15"}
    for alvo in (12, 15):
        assert out["preco_minimo_usd"][str(alvo)]["projeto"] == R.preco_para_tir(fl, c, alvo / 100, alavancada=False)


def test_entrada_parcial_e_versao_divergente_nao_geram_tir(tmp_path, monkeypatch):
    arquivo, _, tabela, r, c = preparar(tmp_path)
    monkeypatch.setattr(R, "linhas_para_refazer", lambda *a, **kw: {})
    with pytest.raises(ValueError, match="fluxo parcial"):
        F.economia_selecionadas(arquivo, {1500107: tmp_path}, c=c, r=r, volume=100)
    tabela.loc[0, "restauracao_versao"] = "antiga"
    tabela.to_parquet(arquivo)
    with pytest.raises(ValueError, match="Versão/cenário"):
        F.economia_selecionadas(arquivo, {}, c=c, r=r, volume=100)


def test_r12_preserva_curva_real_mista_no_cronograma(tmp_path, monkeypatch):
    arquivo, linhas, tabela, r, c = preparar(tmp_path, "central_r12")
    monkeypatch.setattr(R, "linhas_para_refazer", lambda pasta, cod, so: {car: linhas[car] for car in so})
    out = F.economia_selecionadas(arquivo, {1500107: tmp_path, 1721000: tmp_path}, c=c, r=r, volume=100)
    partes = [R.fluxo_p50(li, c, r) for li in linhas.values()]
    acumulado = sum(p["area_ha"] * p["credito_acumulado_ha"] for p in partes)
    esperado = R.cronograma_lote(float(tabela.credito_p50.sum()), c, r, 100, acumulado_ano=acumulado)
    assert out["cronograma_lote"] == esperado
    assert out["fazendas_com_fluxo"] == 2
