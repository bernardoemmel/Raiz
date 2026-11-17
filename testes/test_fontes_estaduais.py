"""Fontes estaduais na triagem: catálogo, coleta sem dado pessoal e cruzamento por imóvel."""

from __future__ import annotations

import datetime as dt
import json

import geopandas as gpd
import pandas as pd
import pytest
import shapely
import yaml

from raiz.estaduais import coleta, cruzamento

UFS_FORA_AMAZONIA = ("BA", "ES", "GO", "MG", "MS", "PI", "PR", "SP")


def test_catalogo_valido_e_completo():
    fontes = coleta.catalogo(UFS_FORA_AMAZONIA)
    assert coleta.validar(fontes) == []
    assert {f["uf"] for f in fontes} == set(UFS_FORA_AMAZONIA)
    # toda fonte bloqueada fora do Brasil fica documentada com alternativa
    for f in fontes:
        if f["acesso"] == "bloqueado_fora_brasil":
            assert f.get("alternativa"), f["id"]


def test_todo_motivo_tem_texto():
    textos = cruzamento.regra()["motivos"]
    motivos = set()
    for f in coleta.catalogo():
        motivos.add(f["motivo"])
        motivos |= {r["motivo"] for r in f.get("regra_efeito") or [] if r.get("motivo")}
        if f["efeito"] == "exclusao":
            motivos.add(f"{f['motivo']}_borda")
    motivos |= {m["motivo"] for m in cruzamento.matriculas()}
    faltam = sorted(m for m in motivos if m not in textos and not m.endswith("_borda"))
    assert faltam == []


def test_matriculas_com_municipios_ibge():
    for m in cruzamento.matriculas():
        assert m["uf"] in UFS_FORA_AMAZONIA or len(m["uf"]) == 2
        assert all(
            str(k).startswith(next(c for c, u in cruzamento.UF_IBGE.items() if u == m["uf"])) for k in m["municipios"]
        )
        assert m["efeito"] in ("ressalva", "conferir")
        assert m["fonte"].startswith("https://")


def _gdf(linhas, crs=4674):
    return gpd.GeoDataFrame(pd.DataFrame(linhas), geometry="geometry", crs=crs)


def test_limpar_apaga_nome_e_documento():
    f = {"descartar": ["fiscalizad", "doc_fiscal"], "manter": ["num_ai", "atividade_", "descricao"]}
    cpf = "".join(("529", ".982", ".247", "-25"))  # CPF sintético de exemplo, montado para não ficar no repositório
    g = _gdf([{
        "num_ai": "1/2026", "fiscalizad": "FULANO DE TAL", "doc_fiscal": cpf.replace(".", "").replace("-", ""),
        "nome_razao_social": "OUTRO", "cpf_cnpj": "123", "atividade_": "FL-02",
        "descricao": f"autuado CPF {cpf} em APP", "geometry": shapely.Point(-45, -18),
    }])  # fmt: skip
    out = coleta.limpar(g, f)
    assert list(out.columns) == ["num_ai", "atividade_", "descricao", "geometry"]
    assert cpf not in out.descricao.iloc[0]
    # código que coincide com um CPF válido some
    out = coleta.limpar(_gdf([{"num_ai": cpf.replace(".", "").replace("-", ""), "geometry": shapely.Point(0, 0)}]), f)
    assert out.num_ai.iloc[0] is None or "529" not in out.num_ai.iloc[0]


def test_classificar_por_campo_e_recencia():
    f = {
        "efeito": "ressalva", "motivo": "auto_estadual", "campo_data": "ano",
        "regra_efeito": [
            {"campo": "grupo", "padrao": "(?i)flora", "recente_anos": 5, "motivo": "auto_estadual_flora_recente"}
        ],
    }  # fmt: skip
    g = _gdf([
        {"grupo": "FLORA", "ano": "2025", "geometry": shapely.Point(0, 0)},
        {"grupo": "Flora", "ano": "2010", "geometry": shapely.Point(0, 0)},
        {"grupo": "PESCA", "ano": "2025", "geometry": shapely.Point(0, 0)},
    ])  # fmt: skip
    out = coleta.classificar(g, f, hoje=dt.date(2026, 11, 17))
    assert list(out.motivo) == ["auto_estadual_flora_recente", "auto_estadual", "auto_estadual"]

    uc = {"efeito": "ressalva", "motivo": "uc_estadual_uso_sustentavel",
          "regra_efeito": [{"campo": "grupo", "padrao": "(?i)prote..o integral|- PI", "efeito": "exclusao",
                            "motivo": "uc_estadual_protecao_integral"}]}  # fmt: skip
    g = _gdf(
        [
            {"grupo": g, "geometry": shapely.Point(0, 0)}
            for g in ("Protecao Integral", "Proteção Integral - PI", "Uso Sutententável - US")
        ]
    )
    assert list(coleta.classificar(g, uc).efeito) == ["exclusao", "exclusao", "ressalva"]


def test_desembargo_tira_embargo():
    fontes = [{"id": "go_embargos", "excluir_se_em": {"fonte": "go_desembargos", "campo": "codigo_processo"}}]
    saidas = {
        "go_embargos": _gdf([{"codigo_processo": p, "geometry": shapely.Point(0, 0)} for p in ("1", "2")]),
        "go_desembargos": _gdf([{"codigo_processo": "2", "geometry": shapely.Point(0, 0)}]),
    }
    coleta.aplicar_desembargos(saidas, fontes)
    assert list(saidas["go_embargos"].codigo_processo) == ["1"]


# --- cruzamento ---------------------------------------------------------------------------------------------------


def _quadrado(x0, y0, lado_m):
    """Quadrado em metros (EPSG:5880) devolvido em 4674."""
    g = gpd.GeoSeries([shapely.box(x0, y0, x0 + lado_m, y0 + lado_m)], crs=5880).to_crs(4674)
    return g.iloc[0]


X, Y = 5_000_000, 7_800_000  # Minas Gerais em EPSG:5880 (só precisa ser coerente)


def _montar(tmp_path, uf_cod, feicoes: dict[str, list[dict]], cobertas: set[str] | None = None):
    pasta, col = tmp_path / "saida", tmp_path / "coleta"
    pasta.mkdir()
    col.mkdir()
    imoveis = _gdf([
        {"cod_imovel": "A", "geometry": _quadrado(X, Y, 1000)},          # 100 ha
        {"cod_imovel": "B", "geometry": _quadrado(X + 2000, Y, 1000)},   # 100 ha
        {"cod_imovel": "C", "geometry": _quadrado(X + 4000, Y, 1000)},   # 100 ha
        {"cod_imovel": "D", "geometry": _quadrado(X + 6000, Y, 70)},     # 0,49 ha (pequeno)
    ])  # fmt: skip
    imoveis.to_parquet(pasta / f"geo_{uf_cod}.parquet")
    uf = cruzamento.UF_IBGE[str(uf_cod)[:2]]
    fontes = {f["id"]: f for f in coleta.catalogo([uf])}
    cob = {"fontes": {}}
    for fid, f in fontes.items():
        if f["acesso"] != "aberto" or f["tipo"] not in ("wfs", "arcgis"):
            continue
        if cobertas is not None and fid not in cobertas:
            continue
        linhas = [{"efeito": f["efeito"], "motivo": f["motivo"], **x} for x in feicoes.get(fid, [])]
        g = _gdf(linhas) if linhas else _gdf({"efeito": [], "motivo": [], "geometry": []})
        g.insert(0, "fonte_id", fid)
        g.to_parquet(col / f"estaduais_{fid}.parquet")
        cob["fontes"][fid] = {"estado": "consultado", "uf": uf}
    (col / coleta.COBERTURA).write_text(json.dumps(cob))
    return pasta, cruzamento.Camadas(col)


def test_cruzamento_minas(tmp_path):
    cod = 3106200  # Belo Horizonte (só para a UF)
    pasta, camadas = _montar(tmp_path, cod, {
        "mg_embargos_sisema": [
            {"geometry": _quadrado(X + 100, Y + 100, 300)},       # 9 ha dentro de A: exclusão
            {"geometry": _quadrado(X + 2950, Y + 100, 100)},      # 0,5 ha na borda de B: ressalva _borda
            {"geometry": _quadrado(X + 6000, Y, 50)},             # 0,25 ha de D (51%): exclusão pela fração
        ],
        "mg_uc_estaduais": [
            {"geometry": _quadrado(X + 4000, Y, 1000), "efeito": "ressalva", "motivo": "uc_estadual_uso_sustentavel"},
        ],
        "mg_prioridade_restauracao": [{"geometry": _quadrado(X, Y, 7000)}],
    })  # fmt: skip
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas).set_index("cod_imovel")
    assert df.loc["A", "estadual_status"] == "exclusao"
    assert df.loc["A", "estadual_motivos"].startswith("embargo_estadual")
    assert 8.9 < df.loc["A", "estadual_exclusao_ha"] < 9.1
    assert df.loc["B", "estadual_status"] == "ressalva"
    assert "embargo_estadual_borda" in df.loc["B", "estadual_motivos"]
    assert df.loc["C", "estadual_status"] == "ressalva"
    assert df.loc["C", "estadual_motivos"] == "uc_estadual_uso_sustentavel"
    assert df.loc["D", "estadual_status"] == "exclusao"  # imóvel pequeno conta pela fração, nunca sai por tamanho
    assert all("prioridade_restauracao_mg" in (x or "") for x in df.estadual_informacoes)
    assert df.estaduais_nao_verificadas.isna().all()


def test_sem_coleta_nunca_vira_livre(tmp_path):
    cod = 3106200
    pasta, camadas = _montar(tmp_path, cod, {}, cobertas={"mg_embargos_sisema"})
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas)
    assert set(df.estadual_status) == {"nao_verificado"}
    assert "mg_uc_estaduais" in df.estaduais_nao_verificadas.iloc[0]


def test_livre_quando_tudo_coberto_e_nada_cruza(tmp_path):
    cod = 3106200
    pasta, camadas = _montar(tmp_path, cod, {})
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas)
    assert set(df.estadual_status) == {"livre"}


def test_ponto_de_embargo_vira_ressalva(tmp_path):
    cod = 5208707  # Goiânia (só para a UF)
    centro = gpd.GeoSeries([shapely.Point(X + 500, Y + 500)], crs=5880).to_crs(4674).iloc[0]
    pasta, camadas = _montar(tmp_path, cod, {"go_embargos": [{"geometry": centro}]})
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas).set_index("cod_imovel")
    assert df.loc["A", "estadual_status"] == "ressalva"
    assert df.loc["A", "estadual_motivos"] == "embargo_estadual_ponto"


def test_bahia_bloqueada_e_matricula_tjba(tmp_path):
    cod = 2911105  # Formosa do Rio Preto
    pasta, camadas = _montar(tmp_path, cod, {})
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas)
    assert set(df.estadual_status) == {"ressalva"}
    assert all("matricula_bloqueio_tjba" in m for m in df.estadual_motivos)
    assert "ba_fundo_fecho_pasto" in df.estaduais_nao_verificadas.iloc[0]
    assert "terra_devoluta_a_conferir" in df.estadual_conferir.iloc[0]


def test_piaui_fora_dos_municipios_bloqueados(tmp_path):
    cod = 2211001  # Teresina: sem regra de matrícula, fontes do PI bloqueadas daqui
    pasta, camadas = _montar(tmp_path, cod, {})
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas)
    assert set(df.estadual_status) == {"nao_verificado"}


@pytest.mark.parametrize("uf", UFS_FORA_AMAZONIA)
def test_resumo_publico_sem_imovel(tmp_path, uf):
    cod = int(next(c for c, u in cruzamento.UF_IBGE.items() if u == uf) + "00000")
    pasta, camadas = _montar(tmp_path, cod, {})
    r = cruzamento.resumo(cruzamento.calcular_municipio(pasta, cod, camadas=camadas))
    assert r["imoveis"] == 4 and sum(r[s] for s in cruzamento.STATUS) == 4


def test_yaml_regra_carrega():
    assert yaml.safe_load(cruzamento.REGRA.read_text(encoding="utf-8"))["limiar_ha"] == 1.0
