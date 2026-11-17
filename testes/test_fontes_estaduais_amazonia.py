"""Fontes estaduais da Amazônia Legal (PA, RO, MT, MA, AM, AC, AP, RR, TO): catálogo, LDI do Pará, junção pelo
número do CAR, CNFP estadual e regra de matrícula do TJPA. Sem rede: tudo com dado sintético."""

import json

import geopandas as gpd
import pandas as pd
import pytest
import shapely

from raiz.estaduais import coleta, cruzamento, matricula

AMAZONIA = ("PA", "RO", "MT", "MA", "AM", "AC", "AP", "RR", "TO")
X, Y = 5_400_000, 9_300_000  # coerente em EPSG:5880 (só a UF vem do código do município)


def test_catalogo_amazonia_valido():
    fontes = coleta.catalogo(AMAZONIA)
    assert coleta.validar(fontes) == []
    assert {f["uf"] for f in fontes} == set(AMAZONIA)
    for f in fontes:
        if f["acesso"] in ("bloqueado_fora_brasil", "sem_download"):
            assert f.get("alternativa"), f["id"]
    # toda UF da Amazônia tem pelo menos a camada automática de glebas estaduais do CNFP
    assert {f["uf"] for f in fontes if f["tipo"] == "cnfp"} == set(AMAZONIA)


def test_motivos_da_amazonia_tem_texto():
    textos = cruzamento.regra()["motivos"]
    for f in coleta.catalogo(AMAZONIA):
        assert f["motivo"] in textos, f["id"]
        for r in f.get("regra_efeito") or []:
            assert r["motivo"] in textos, f["id"]
        if f["efeito"] == "exclusao":
            assert f"{f['motivo']}_borda" in textos or f["motivo"] in ("territorio_quilombola_estadual",), f["id"]
    assert "matricula_acima_limite_tjpa" in textos


# --- LDI do Pará ---------------------------------------------------------------------------------------------------

COM_CAR = (
    "Consulta de Áreas com desmatamento ilegal Com CAR;\nData de emissão:16/11/2026;\n\n"
    "CodLDI;CodList;Nº do recibo;Situação do CAR;Ano Desmatamento;Área Desmatamento (ha);"
    "Desmate em CAR - APRT(ha);Município(s);Sobreposição CAR-CodList;Latitude;Longitude;Fonte;"
    "Proc. Punitivo com CAR;Área Car (ha);Razão Social;Proprietário - CPF/CNPJ;Município CAR;\n"
    'C-18-03-00141;935;PA-1507805-AAAA;Pendente;2015;26,09;26,09000;Senador José Porfírio;"935";'
    '03º43\'39,07" S;51º47\'00,53" S;RVD/SAD;1781;120,5;FAZENDA "EXEMPLO; LTDA;***.123.456-**;Altamira;\n'
    ';;;-;2018;14,11;-;Altamira;"-";06º05\'44,32" S;53º41\'59,16" S;CIMAM;2020/00000330;-;-;-;-;\n'
)
SEM_CAR = (
    "Consulta de Áreas com desmatamento ilegal;\nData de emissão:16/11/2026;\n\n"
    "Nº do processo;Área Desmatada;Fonte;Ano;Município(s);Latitude;Longitude;\n"
    "2020/0000021947;19,45;CIMAM;2018;São Félix do Xingu;06º13'33,69\" S;53º16'03,43\" O;\n"
)


def test_ldi_sem_dado_pessoal_e_com_recibo():
    g = coleta.ldi_pa(COM_CAR.encode("latin-1"), SEM_CAR.encode("utf-8"))
    assert len(g) == 3
    assert not [c for c in g.columns if "raz" in c.lower() or "cpf" in c.lower() or "propriet" in c.lower()]
    assert g.cod_imovel.iloc[0] == "PA-1507805-AAAA"
    assert g.cod_imovel.iloc[1:].isna().all()
    assert g.desmate_car_ha.iloc[0] == pytest.approx(26.09)
    p = g.geometry.iloc[2]
    assert p.y == pytest.approx(-6.2260, abs=1e-3) and p.x == pytest.approx(-53.2676, abs=1e-3)
    assert "EXEMPLO" not in g.drop(columns="geometry").to_csv()


def test_dms_hemisferio():
    assert coleta.dms("06º13'33,69\" S") == pytest.approx(-6.22603, abs=1e-4)
    assert coleta.dms("53º16'03,43\" S") < 0  # a LDI erra o hemisfério da longitude: fica oeste
    assert coleta.dms("02º00'00\" N") == pytest.approx(2.0)
    assert coleta.dms("-") is None


def test_cnfp_so_estadual_nao_destinada():
    g = gpd.GeoDataFrame(
        {"governo": ["ESTADUAL", "FEDERAL", "Estadual", "ESTADUAL"], "tipo": ["B", "B", "TIPO B", "A"]},
        geometry=[shapely.box(0, 0, 1, 1)] * 4,
        crs=4674,
    )
    assert list(coleta.filtrar_cnfp_estadual(g).index) == [0, 2]


def test_arquivo_geojson_por_url():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"pct": "Q1"}, "geometry": shapely.geometry.mapping(shapely.box(0, 0, 1, 1))},
    ]}  # fmt: skip

    class Resp:
        content = json.dumps(fc).encode()

        def raise_for_status(self):
            pass

    class Sessao:
        def get(self, *a, **k):
            return Resp()

    g = coleta._arquivo(Sessao(), {"url": "https://x/y.geojson"})
    assert len(g) == 1 and g.crs.to_epsg() == 4674


# --- cruzamento ----------------------------------------------------------------------------------------------------


def _q(x0, y0, lado):
    return gpd.GeoSeries([shapely.box(x0, y0, x0 + lado, y0 + lado)], crs=5880).to_crs(4674).iloc[0]


def _pt(x, y):
    return gpd.GeoSeries([shapely.Point(x, y)], crs=5880).to_crs(4674).iloc[0]


def _montar(tmp_path, cod, uf, feicoes):
    pasta, col = tmp_path / "saida", tmp_path / "coleta"
    pasta.mkdir()
    col.mkdir()
    gpd.GeoDataFrame(
        {"cod_imovel": [f"{uf}-{cod}-A", f"{uf}-{cod}-B", f"{uf}-{cod}-C", f"{uf}-{cod}-D", f"{uf}-{cod}-E"]},
        geometry=[
            _q(X, Y, 1000),
            _q(X + 2000, Y, 1000),
            _q(X + 4000, Y, 1000),
            _q(X + 6000, Y, 1000),
            _q(X + 10000, Y, 6000),
        ],  # E: 3.600 ha  # fmt: skip
        crs=4674,
    ).to_parquet(pasta / f"geo_{cod}.parquet")
    cob = {"fontes": {}}
    for f in coleta.catalogo([uf]):
        if f["acesso"] != "aberto" or f["tipo"] not in coleta.TIPOS_AUTOMATICOS:
            continue
        linhas = [{"efeito": f["efeito"], "motivo": f["motivo"], **x} for x in feicoes.get(f["id"], [])]
        if linhas:
            g = gpd.GeoDataFrame(pd.DataFrame(linhas), geometry="geometry", crs=4674)
        else:
            g = gpd.GeoDataFrame({"efeito": [], "motivo": []}, geometry=[], crs=4674)
        g.insert(0, "fonte_id", f["id"])
        g.to_parquet(col / f"estaduais_{f['id']}.parquet")
        cob["fontes"][f["id"]] = {"estado": "consultado", "uf": uf}
    (col / coleta.COBERTURA).write_text(json.dumps(cob))
    return pasta, cruzamento.Camadas(col)


def test_cruzamento_para(tmp_path):
    cod = 1507300  # São Félix do Xingu
    pasta, camadas = _montar(tmp_path, cod, "PA", {
        "pa_ldi": [
            {"cod_imovel": f"PA-{cod}-A", "desmate_car_ha": 30.0, "geometry": _pt(X + 9000, Y + 9000)},  # ligado
            {"cod_imovel": f"PA-{cod}-B", "desmate_car_ha": 0.5, "geometry": _pt(X + 2500, Y + 500)},
            {"cod_imovel": None, "desmate_car_ha": None, "geometry": _pt(X + 4500, Y + 500)},  # sem CAR, dentro de C
        ],
        "pa_quilombolas_car": [{"geometry": _q(X + 6000, Y, 500)}],  # 25 ha de D
    })  # fmt: skip
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas).set_index("cod_imovel")
    a, b, c, d, e = (df.loc[f"PA-{cod}-{k}"] for k in "ABCDE")
    assert a.estadual_status == "exclusao" and a.estadual_motivos == "desmatamento_ilegal_estadual"
    assert b.estadual_status == "ressalva" and b.estadual_motivos == "desmatamento_ilegal_estadual_borda"
    assert c.estadual_status == "ressalva" and c.estadual_motivos == "desmatamento_ilegal_estadual_ponto"
    assert d.estadual_status == "exclusao" and "territorio_quilombola_estadual" in d.estadual_motivos
    # imóvel grande: ressalva da matrícula do TJPA (não sai por tamanho)
    assert e.estadual_status == "ressalva" and e.estadual_motivos == "matricula_acima_limite_tjpa"
    for x in (a, b, c, d, e):
        assert "matricula_acima_limite_tjpa" in x.estadual_conferir
        assert "terra_devoluta_a_conferir" in x.estadual_conferir  # ITERPA sem camada: checklist
    assert "pa_ldi" in a.estadual_fontes


def test_cruzamento_rondonia_pra_e_zsee(tmp_path):
    cod = 1100205  # Porto Velho
    pasta, camadas = _montar(tmp_path, cod, "RO", {
        "ro_pra": [{"cod_imovel": f"RO-{cod}-A", "geometry": _q(X + 50000, Y, 100)}],  # vale o CAR, não o desenho
        "ro_zsee": [{"SPRNOME_1": "ZONA1", "geometry": _q(X - 1000, Y - 1000, 30000)}],
        "ro_uc_estaduais": [
            {"grupo": "Uso Sustentável", "efeito": "ressalva", "motivo": "uc_estadual_uso_sustentavel",
             "geometry": _q(X + 2000, Y, 1000)},
            {"grupo": "Proteção Integral", "geometry": _q(X + 4000, Y, 1000)},
        ],
    })  # fmt: skip
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas).set_index("cod_imovel")
    assert df.loc[f"RO-{cod}-A", "estadual_motivos"] == "pra_assinado"
    assert df.loc[f"RO-{cod}-B", "estadual_motivos"] == "uc_estadual_uso_sustentavel"
    assert df.loc[f"RO-{cod}-C", "estadual_status"] == "exclusao"
    assert df.loc[f"RO-{cod}-D", "estadual_status"] == "livre"  # tudo coberto e nada restritivo cruzou
    assert all("zsee_ro_zona_1" in (x or "") for x in df.estadual_informacoes)
    assert df.estaduais_nao_verificadas.isna().all()


def test_mato_grosso_sem_acesso_nunca_vira_livre(tmp_path):
    cod = 5103254  # Colniza
    pasta, camadas = _montar(tmp_path, cod, "MT", {})
    df = cruzamento.calcular_municipio(pasta, cod, camadas=camadas)
    assert set(df.estadual_status) == {"nao_verificado"}
    assert "mt_sema_embargos" in df.estaduais_nao_verificadas.iloc[0]
    assert "car_estadual_a_conferir" in df.estadual_conferir.iloc[0]


# --- matrícula do TJPA ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("aberta", "ha", "situacao", "limite"),
    [
        ("1950-05-01", 12000, "suspeita", 10000),
        ("1950-05-01", 9000, "dentro_do_limite", 10000),
        ("1975-03-01", 4200, "suspeita", 3000),
        ("1999-01-01", 2600, "suspeita", 2500),
        ("1999-01-01", 2400, "dentro_do_limite", 2500),
        (None, 5000, "sem_dados", None),
    ],
)
def test_matricula_tjpa_por_epoca(aberta, ha, situacao, limite):
    a = matricula.avaliar("PA", aberta, ha)
    assert a.situacao == situacao
    assert a.limite_ha == limite


def test_matricula_uf_sem_regra():
    assert matricula.avaliar("MT", "1999-01-01", 50_000).situacao == "sem_regra"
