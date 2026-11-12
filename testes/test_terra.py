"""Caminho da terra: a situação da terra deixa de ser corte e vira caminho com risco. Ninguém sai do mapa por falta
de matrícula; cada caminho com a regra escrita, o risco com o motivo, o aviso do que falta (caminhos 2, 3 e 5), o
selo prata só para matrícula conferida ou concessão, as sobreposições com SIGEF, florestas públicas, UC, terras
indígenas e quilombos, e a camada de terra pública para restaurar."""

import shutil

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from raiz import imovel_dados as I
from raiz import terra as T
from testes.conftest import AMOSTRA


def _linha(**kw):
    base = {"cod_imovel": "PA-1-A", "uf": "PA", "ha": 100.0, "carbono_ha": 40.0, "carbono_tco2_ano": 100.0,
            "matricula_ha": 0.0, "f_matricula": 0.0, "sigef_ha": 0.0, "assentamento_ha": 0.0, "ti_ha": 0.0}  # fmt: skip
    return {**base, **kw}


def test_seis_caminhos_pela_regra():
    c = T.caminho
    assert c(_linha(matricula_ha=80, f_matricula=0.8, sigef_ha=80))["caminho_terra"] == "privada_matricula"
    assert c(_linha())["caminho_terra"] == "posse_em_titulacao"
    assert c(_linha(tipo_imovel="AST"))["caminho_terra"] == "assentamento"
    assert c(_linha(assentamento_ha=70))["caminho_terra"] == "assentamento"
    assert c(_linha(terra_publica_ha=60))["caminho_terra"] == "publica_sem_destinacao"
    assert c(_linha(ti_ha=10))["caminho_terra"] == "terra_indigena_ou_tradicional"
    assert (
        c(_linha(terra_concessao="flona_bom_futuro_um2", terra_concessao_ha=90))["caminho_terra"] == "publica_concessao"
    )
    # terra indígena vem antes de tudo; terra pública grande nunca passa por particular
    assert c(_linha(matricula_ha=90, ti_ha=10))["caminho_terra"] == "terra_indigena_ou_tradicional"
    assert c(_linha(matricula_ha=55, terra_publica_ha=60))["caminho_terra"] == "publica_sem_destinacao"
    # sobreposição pequena com TI (abaixo de 1 ha ou de 5%) não muda o caminho
    assert c(_linha(matricula_ha=90, ti_ha=0.5))["caminho_terra"] == "privada_matricula"


def test_risco_com_motivo():
    c = T.caminho
    r = c(_linha(matricula_ha=80, sigef_ha=80))
    assert r["risco_terra"] == "medio" and "conferir cancelamentos" in r["risco_terra_motivo"]
    assert r["risco_terra_motivo"][0].isupper() and "Pará" in r["risco_terra_motivo"]
    assert c(_linha(uf="MT", matricula_ha=95, sigef_ha=95, matricula_conferida=True))["risco_terra"] == "baixo"
    assert c(_linha(matricula_ha=90, sigef_ha=90, terra_publica_ha=10))["risco_terra"] == "alto"
    assert c(_linha())["risco_terra"] == "alto"  # posse só declarada no CAR
    assert c(_linha(terra_sigef_registrada_ha=0, terra_sigef_titulacao_ha=60))["risco_terra"] == "medio"
    assert c(_linha(tipo_imovel="AST"))["risco_terra"] == "alto"
    assert (
        c(_linha(tipo_imovel="AST", terra_sigef_registrada_ha=0, terra_sigef_assentamento_titulado_ha=80))[
            "risco_terra"
        ]
        == "medio"
    )
    assert c(_linha(terra_concessao="flona_bom_futuro_um2", terra_concessao_ha=90))["risco_terra"] == "baixo"
    assert c(_linha(terra_concessao="flona_bom_futuro_lote2", terra_concessao_ha=90))["risco_terra"] == "medio"
    for k in ("publica_sem_destinacao", "terra_indigena_ou_tradicional"):
        assert c(_linha(terra_publica_ha=100) if k.startswith("publica") else _linha(ti_ha=50))["risco_terra"] == "alto"


def test_aviso_so_nos_caminhos_em_espera_ou_so_para_mostrar_e_sem_chamar_posse_de_propriedade():
    r = T.regra()
    for cam, c in r["caminhos"].items():
        tem = bool(" ".join(str(c.get("aviso") or "").split()))
        assert tem == (cam in ("posse_em_titulacao", "assentamento", "publica_sem_destinacao",
                               "terra_indigena_ou_tradicional")), cam  # fmt: skip
    posse = T.caminho(_linha())
    textos = " ".join(str(v) for v in posse.values()) + " " + str(r["caminhos"]["posse_em_titulacao"])
    assert "propriedade" not in textos.lower() and "proprietário" not in textos.lower()
    b = T.bloco_ficha(_linha())
    assert b["situacao"] == "em_espera" and "título" in b["aviso"] and b["base_legal"]
    assert any("3.6.2" in x["texto"] for x in b["base_legal"])  # Verra não exige matrícula
    assert T.bloco_ficha(_linha(assentamento_ha=80))["profloresta_fase1"] is False
    assert T.bloco_ficha(_linha(matricula_ha=80))["profloresta_fase1"] is True


def test_selo_prata_so_para_matricula_conferida_ou_concessao():
    assert not T.selo_prata(_linha(matricula_ha=95))
    assert T.selo_prata(_linha(matricula_ha=95, matricula_conferida=True))
    assert T.selo_prata(_linha(terra_concessao="flona_bom_futuro_um2", terra_concessao_ha=100))
    assert not T.selo_prata(_linha(matricula_conferida=True))  # conferida, mas é posse (sem matrícula no SIGEF)


def test_sem_matricula_nao_sai_do_funil():
    """A apta sem matrícula fica no caminho da terra (em espera), nunca para em 'apta' por falta de matrícula."""
    etapa, motivo = I.etapa_e_motivo(_linha())
    assert etapa == "caminho_terra" and motivo["id"] == "terra_posse"
    assert I.etapa_e_motivo(_linha(tipo_imovel="AST"))[0] == "caminho_terra"
    assert I.etapa_e_motivo(_linha(matricula_ha=95, matricula_conferida=True))[0] == "titulo_conferido"


def test_ninguem_some_do_total_por_causa_da_terra():
    im = pd.read_csv(AMOSTRA / "imoveis_1504950.csv", low_memory=False)
    linhas = im.to_dict("records")
    por = T.por_caminho(linhas, "ha")
    assert sum(x["imoveis"] for x in por["caminhos"].values()) == len(linhas)
    assert sum(x["imoveis"] for x in por["situacoes"].values()) == len(linhas)
    assert por["caminhos"]["posse_em_titulacao"]["imoveis"] > 0  # sem matrícula, continuam contados
    assert sum(x["ha"] for x in por["caminhos"].values()) == pytest.approx(im.ha.sum(), rel=1e-3)
    # e a etapa do funil: toda apta chega ao caminho da terra
    etapas = [I.etapa_e_motivo(x)[0] for x in linhas]
    ordem = {e: i for i, e in enumerate(I.ETAPAS)}
    aptas = sum(ordem[e] >= ordem["apta"] for e in etapas)
    assert aptas == sum(ordem[e] >= ordem["caminho_terra"] for e in etapas)


def test_municipio_da_amostra_sem_geo(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in ("imoveis", "filtros"):
        shutil.copy(AMOSTRA / f"{f}_1504950.csv", pasta / f"{f}_1504950.csv")
    t = T.calcular_municipio(pasta, 1504950)
    im = pd.read_csv(pasta / "imoveis_1504950.csv")
    assert len(t) == len(im) and set(t.cod_imovel) == set(im.cod_imovel.astype(str))
    assert t.caminho_terra.notna().all() and t.risco_terra.isin(T.RISCOS).all()
    assert (t.terra_fonte == "motor").all() and (t.terra_regra_versao == T.versao()).all()
    doc = (AMOSTRA.parents[1] / "docs" / "colunas.md").read_text(encoding="utf-8")
    real = pd.read_csv(AMOSTRA / "terra_1504950.csv", nrows=1)  # com as sobreposições medidas
    faltam = [c for c in {*t.columns, *real.columns} if c not in doc]
    assert not faltam, faltam


# --- sobreposições em dados sintéticos --------------------------------------------------------------------------


def _quadrado(x, y, lado=0.01):
    return shapely.box(x, y, x + lado, y + lado)


def test_sobreposicoes_sigef_e_camadas():
    imoveis = gpd.GeoDataFrame({"cod_imovel": ["A", "B", "C"]},
                               geometry=[_quadrado(-47.0, -2.0), _quadrado(-46.9, -2.0), _quadrado(-46.8, -2.0)],
                               crs=4674)  # fmt: skip
    sigef = gpd.GeoDataFrame(
        {"natureza": ["Particular", "Particular", "Assentamento Parcela", "Gleba Pública"],
         "situacao_informada": ["REGISTRADA", "NAO_TITULADA", "NAO_TITULADA", "NAO_TITULADA"],
         "status": ["REGISTRADA", "TITULACAO", "CERTIFICADA", "CERTIFICADA"],
         "tipo_envio": ["certificacao", "envio_part_titulacao", "contrato", "certificacao"],
         "registro_matricula": ["123", None, None, None], "parcela_codigo": list("abcd")},
        geometry=[_quadrado(-47.0, -2.0), _quadrado(-46.9, -2.0, 0.005), _quadrado(-46.8, -2.0),
                  _quadrado(-46.8, -2.0, 0.004)], crs=4674)  # fmt: skip
    cls = T.classes_sigef(sigef)
    assert len(cls["registrada"]) == 1 and len(cls["titulacao"]) == 1 and len(cls["assentamento"]) == 1
    assert len(cls["gleba_publica"]) == 1 and len(cls["posse"]) == 0
    ti = gpd.GeoDataFrame(geometry=[_quadrado(-46.9, -2.0, 0.004)], crs=4674)  # 16% do imóvel B
    por = T.sobreposicoes(imoveis, sigef, {"tradicional": ti})
    ha_a = imoveis.to_crs(5880).area.iloc[0] / 1e4
    assert por["A"]["terra_sigef_registrada_ha"] == pytest.approx(ha_a, rel=1e-3)
    assert por["B"]["terra_sigef_titulacao_ha"] == pytest.approx(ha_a / 4, rel=2e-2)
    assert por["C"]["terra_sigef_assentamento_ha"] == pytest.approx(ha_a, rel=1e-3)
    assert por["C"]["terra_publica_ha"] == pytest.approx(ha_a * 0.16, rel=2e-2)
    assert por["B"]["terra_tradicional_ha"] > 0
    caminhos = {c: T.caminho({"cod_imovel": c, "uf": "PA", "ha": ha_a, **v})["caminho_terra"] for c, v in por.items()}
    assert caminhos == {"A": "privada_matricula", "B": "terra_indigena_ou_tradicional", "C": "assentamento"}


def test_camadas_de_terra_e_concessao_na_flona(tmp_path):
    ucs = gpd.GeoDataFrame(
        {"nome_uc": ["FLORESTA NACIONAL DO BOM FUTURO", "ÁREA DE PROTEÇÃO AMBIENTAL TRIUNFO DO XINGU",
                     "RESERVA EXTRATIVISTA X"],
         "categoria": ["Floresta", "Área de Proteção Ambiental", "Reserva Extrativista"],
         "uf": ["RONDÔNIA", "PARÁ", "PARÁ"], "esfera": ["Federal", "Estadual", "Federal"], "cd_cnuc": ["1", "2", "3"],
         "org_gestor": ["ICMBio", "Ideflor-Bio", "ICMBio"]},
        geometry=[_quadrado(-64.0, -9.5, 0.2), _quadrado(-52.0, -6.5, 0.2), _quadrado(-50.0, -5.0, 0.2)],
        crs=4674)  # fmt: skip
    ucs.to_parquet(tmp_path / "conservationunits_202503.parquet")
    c = T.camadas_de_terra((-64.1, -9.6, -49.0, -4.0), tmp_path, None)
    assert list(c["uc_publica"].categoria) == ["Floresta"]  # APA admite terra privada: fora
    assert set(c["concessoes"].concessao) == {"flona_bom_futuro_um2", "flona_bom_futuro_lote2"}
    assert len(c["tradicional"]) == 1  # a reserva extrativista
    im = gpd.GeoDataFrame({"cod_imovel": ["F", "APA"]}, geometry=[_quadrado(-63.95, -9.45), _quadrado(-51.95, -6.45)],
                          crs=4674)  # fmt: skip
    por = T.sobreposicoes(im, None, c)
    assert por["F"]["terra_concessao"] in ("flona_bom_futuro_um2", "flona_bom_futuro_lote2")
    assert "terra_concessao" not in por["APA"]  # dentro da APA não vira concessão: a APA tem terra privada
    ha = im.to_crs(5880).area.iloc[0] / 1e4
    assert T.caminho({"cod_imovel": "F", "uf": "RO", "ha": ha, **por["F"]})["caminho_terra"] == "publica_concessao"


# --- camada de terra pública para restaurar ---------------------------------------------------------------------


def test_terra_publica_da_uf(tmp_path, monkeypatch):
    import rasterio
    from rasterio.transform import from_origin

    from raiz import terra_publica as TP

    res = 0.00026949458523585647
    n = 300
    cob = np.full((n, n), 3, dtype="uint8")
    cob[:, 150:] = 15  # metade de pasto
    (tmp_path / "mapbiomas" / "PA").mkdir(parents=True)
    with rasterio.open(tmp_path / "mapbiomas" / "PA" / "PA_cobertura_2025.tif", "w", driver="GTiff", width=n,
                       height=n, count=1, dtype="uint8", crs="EPSG:4326", transform=from_origin(-47.0, -2.0, res, res),
                       nodata=0) as f:  # fmt: skip
        f.write(cob, 1)
    x0, y0 = -47.0 + 100 * res, -2.0 - 200 * res
    gleba = shapely.box(x0, y0, x0 + 100 * res, y0 + 100 * res)  # metade mata, metade pasto
    cnfp = gpd.GeoDataFrame({"nome": ["GLEBA TESTE"], "categoria": ["GLEBA ARRECADADA"], "tipo": ["B"],
                             "governo": ["ESTADUAL"], "orgao": ["ITERPA"], "uf": ["PA"], "bioma": ["AMAZÔNIA"],
                             "geocodigo": ["1"]}, geometry=[gleba], crs=4674)  # fmt: skip
    cnfp.to_parquet(tmp_path / "cnfp_PA.parquet")
    monkeypatch.setattr(TP, "pasta", lambda: tmp_path)
    a = TP.areas_da_uf("PA", tmp_path, espelho=tmp_path / "espelho", cnfp=tmp_path / "cnfp_PA.parquet")
    assert len(a) == 1 and a.fonte.iloc[0] == "cnfp" and a.destinacao.iloc[0] == "sem_destinacao"
    t = TP.cruzar(
        a, tmp_path / "mapbiomas" / "PA" / "PA_cobertura_2025.tif", tmp_path, reducao=1, fontes_geo=("faixas",)
    )
    x = t.iloc[0]
    assert x.desmatado_ha == pytest.approx(x.ha / 2, rel=0.05) and x.pasto_ha == pytest.approx(x.desmatado_ha)
    assert x.modo_restauracao in ("regeneracao_assistida", "semeadura_direta", "plantio_total")
    assert x.custo_restauracao_ha_p10 <= x.custo_restauracao_ha_p50 <= x.custo_restauracao_ha_p90
    assert x.credito_liquido_tco2_ano > 0
    assert TP.concessao_da_area({"nome": "FLORESTA NACIONAL DO BOM FUTURO", "fonte": "cnuc"})["link"].startswith(
        "https"
    )


def test_conferir_editais_guarda_data_e_link(tmp_path):
    import httpx

    from raiz import terra_publica as TP

    paginas = {
        "www.gov.br": '<a href="/florestal/edital-flona-x.pdf">Edital de concessão da Flona X</a>'
        '<a href="/florestal/compra.pdf">Pregão de compra de papel</a>',
        "ideflorbio.pa.gov.br": '<a href="https://ideflorbio.pa.gov.br/ur/">Unidade de Recuperação Y</a>',
    }
    cli = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, text=paginas[req.url.host])))
    r = TP.conferir_editais(tmp_path / "vistos.json", cliente=cli)
    links = {n["link"] for n in r["novos"]}
    assert links == {"https://www.gov.br/florestal/edital-flona-x.pdf", "https://ideflorbio.pa.gov.br/ur/"}
    assert all(n["visto_em"] for n in r["novos"])
    assert TP.conferir_editais(tmp_path / "vistos.json", cliente=cli)["novos"] == []  # já vistos
