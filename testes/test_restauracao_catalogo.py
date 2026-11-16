"""Proveniência, incremental e preservação das previsões no índice privado."""

import json
from pathlib import Path

import pandas as pd
import pytest

from raiz import restauracao_catalogo as C


def criar_fonte(pasta: Path, uf="PA", cod=1500602, n=3, *, modelo="modelo-teste", bioma="Amazônia"):
    pasta.mkdir(parents=True, exist_ok=True)
    ids = [f"{uf}-{cod}-SINTETICO{i:04d}" for i in range(n)]
    pd.DataFrame(
        {
            "cod_imovel": ids,
            "uf": uf,
            "cod_municipio_ibge": cod,
            "ha": 2.0,
            "m_fiscal": 0.02,
            "bioma": bioma,
            "problema": False,
        }
    ).to_csv(pasta / f"imoveis_{cod}.csv", index=False)
    pd.DataFrame(
        {
            "cod_imovel": ids,
            "modo_restauracao": "regeneracao_assistida",
            "restauracao_area_ha": 0.02,
            "restauracao_regeneracao_assistida_ha": 0.02,
            "restauracao_versao": modelo,
            "restauracao_cenario": "central_r11",
            "credito_liquido_tco2_ha_contrato_p10": 0.0,
            "credito_liquido_tco2_ha_contrato_p50": 1000.0,
            "credito_liquido_tco2_ha_contrato_p90": 1500.0,
            "tir_alavancada_pct_p10": 1.0,
            "tir_alavancada_pct_p50": 40.0,
            "tir_alavancada_pct_p90": 30.0,
            "tir_projeto_pct_p50": -100.0,
            "reserva_risco_pct": 20.0,
            "custo_credito_usd": 10.0,
            "marcos_todos_chance_pct": 0.0,
            "preco_equilibrio_usd_t": 20.0,
            "preco_minimo_tir_12_projeto_usd_t": 50.0,
            "preco_minimo_tir_15_projeto_usd_t": 60.0,
        }
    ).to_csv(pasta / f"desenvolvedor_{cod}.csv", index=False)
    pd.DataFrame(
        {
            "cod_imovel": ids,
            "caminho_terra": "privada_matricula",
            "risco_terra": "baixo",
            "risco_terra_motivo": "Título sintético para teste",
            "terra_regra_versao": "terra-teste",
        }
    ).to_csv(pasta / f"terra_{cod}.csv", index=False)
    return ids


def indexar(pasta, destino, uf="PA", cod=1500602):
    return C.indexar_municipio(pasta, uf, cod, destino, modelo="modelo-teste", cenario="central_r11")


def ler(p, destino):
    return pd.read_parquet(destino / p["arquivos"]["oferta"]["caminho"])


def test_cache_municipal_preserva_pequenas_zero_quantile_tir_central_e_sentinela(tmp_path):
    fonte, destino = tmp_path / "fonte", tmp_path / "privado"
    criar_fonte(fonte)
    p = indexar(fonte, destino)
    t = ler(p, destino)
    assert len(t) == 3 and t.pequena.all() and (t.area_ha == 0.02).all()
    assert (t.credito_p10 == 0).all() and (t.marcos_todos == 0).all()
    assert (t.tir_p50 > t.tir_p90).all() and (t.tir_projeto == -100).all()
    assert t.restauracao_versao.eq("modelo-teste").all()
    arquivo = destino / p["arquivos"]["oferta"]["caminho"]
    antes = arquivo.stat().st_mtime_ns
    assert indexar(fonte, destino)["cache_reutilizado"]
    assert arquivo.stat().st_mtime_ns == antes
    assert arquivo.stat().st_mode & 0o777 == 0o600
    ds = [json.loads(linha) for linha in (destino / p["arquivos"]["decisoes"]["caminho"]).read_text().splitlines()]
    assert ds and all(d["criterio"] and d["revisao_humana_disponivel"] for d in ds)


def test_incompativel_e_ausente_permanecem_sem_reetiquetar(tmp_path):
    fonte, destino = tmp_path / "fonte", tmp_path / "privado"
    criar_fonte(fonte, modelo="historico")
    p = indexar(fonte, destino)
    t = ler(p, destino)
    assert t.restauracao_versao.eq("historico").all()
    assert t.situacao_previsao.eq("modelo_incompativel").all() and not t.elegivel.any()
    (fonte / "desenvolvedor_1500602.csv").unlink()
    novo = indexar(fonte, destino)
    t = ler(novo, destino)
    assert len(t) == 3 and t.situacao_previsao.eq("previsao_ausente").all()
    assert t.credito_p50.isna().all() and t.area_ha.isna().all()
    assert novo["id"] != p["id"]


def test_mudanca_de_um_municipio_nao_invalida_outro(tmp_path):
    destino = tmp_path / "privado"
    criar_fonte(tmp_path / "a")
    criar_fonte(tmp_path / "b", cod=1500107)
    a, b = indexar(tmp_path / "a", destino), indexar(tmp_path / "b", destino, cod=1500107)
    f = tmp_path / "a" / "terra_1500602.csv"
    t = pd.read_csv(f)
    t["risco_terra"] = "alto"
    t.to_csv(f, index=False)
    a2, b2 = indexar(tmp_path / "a", destino), indexar(tmp_path / "b", destino, cod=1500107)
    assert a2["id"] != a["id"] and b2["id"] == b["id"] and b2["cache_reutilizado"]


def test_catalogo_cobertura_parcial_e_hash(tmp_path):
    criar_fonte(tmp_path / "fonte")
    destino = tmp_path / "privado"
    p = indexar(tmp_path / "fonte", destino)
    caminho = C.consolidar_catalogo(
        [p], destino, municipios_esperados={"PA": [1500602, 1500107], "RR": [1400050]}, sem_imoveis={"RR": [1400050]}
    )
    c, arquivos = C.abrir_catalogo(caminho)
    assert len(arquivos) == 1 and c["imoveis"] == 3
    assert c["cobertura"]["PA"]["faltantes"] == [1500107]
    assert c["cobertura"]["RR"]["completo"]
    Path(arquivos[0]).write_bytes(b"alterado")
    with pytest.raises(ValueError, match="SHA-256"):
        C.abrir_catalogo(caminho)


def test_duplicidade_global_nao_soma_creditos(tmp_path):
    destino = tmp_path / "privado"
    criar_fonte(tmp_path / "a")
    criar_fonte(tmp_path / "b", cod=1500107)
    for f in (tmp_path / "b").glob("*.csv"):
        t = pd.read_csv(f)
        t["cod_imovel"] = [f"PA-1500602-SINTETICO{i:04d}" for i in range(3)]
        t.to_csv(f, index=False)
    ps = [indexar(tmp_path / "a", destino), indexar(tmp_path / "b", destino, cod=1500107)]
    with pytest.raises(ValueError, match="CAR repetido"):
        C.consolidar_catalogo(ps, destino, municipios_esperados={"PA": [1500602, 1500107]})


def test_fonte_duplicada_ou_area_impossivel_nao_e_corrigida_no_indice(tmp_path):
    criar_fonte(tmp_path / "fonte")
    f = tmp_path / "fonte" / "desenvolvedor_1500602.csv"
    t = pd.read_csv(f)
    t["restauracao_area_ha"] = 10
    t.to_csv(f, index=False)
    with pytest.raises(ValueError, match="limite físico"):
        indexar(tmp_path / "fonte", tmp_path / "privado")
    t = pd.concat([t, t.iloc[:1]])
    t.to_csv(f, index=False)
    with pytest.raises(ValueError, match="duplicado"):
        indexar(tmp_path / "fonte", tmp_path / "privado")
