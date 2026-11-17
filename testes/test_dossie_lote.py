"""Dossiê executivo do lote: os filtros que o Bot Agro aplicava na mão em Paragominas, agora em código.

Casos reais de Paragominas (17/11/2026): A5BAFA27 cruza o VCS4681 (YBYRÁ) em ~45% do CAR; CE800C8A e A79C0259 têm
divisa a menos de 100 m (VCS4681 e VCS1953); os quatro estão dentro do KML regional do VCS4137, que nunca exclui;
D4386947 e CE800C8A não têm gleba federal não destinada no CNFP 2025. Os dados reais vêm recortados em
testes/fixtures/paragominas_*.geojson."""

from pathlib import Path

import geopandas as gpd
import shapely

from raiz import dossie_lote as D

# um grau ~ 111 km; caixas pequenas perto de Paragominas
X0, Y0 = -47.5, -3.0


def _caixa(dx, dy, lado=0.02):
    return shapely.box(X0 + dx, Y0 + dy, X0 + dx + lado, Y0 + dy + lado)


def _linha(cod, **kw):
    base = {
        "cod_imovel": cod,
        "ha": 400.0,
        "restauracao_area_ha": 100.0,
        "desm_pos2016_ha": 0,
        "alerta_ha": 0,
        "embargo_ha": 0,
        "ti_ha": 0,
        "uc_protecao_integral_ha": 0,
        "uc_uso_sustentavel_ha": 0,
        "quilombo_ha": 0,
        "assentamento_ha": 0,
        "caminho_terra": "privada_matricula",
        "terra_gleba_federal_ha": 0.0,
    }
    base.update(kw)
    return base


def _limites(itens):
    return gpd.GeoDataFrame(
        {
            "objeto_id": [i[0] for i in itens],
            "certeza": [i[1] for i in itens],
            "situacao": [i[2] for i in itens],
            "area_ha": [i[3] for i in itens],
            "limite_suspeito": [False] * len(itens),
            "limite_amplo": [False] * len(itens),
        },
        geometry=[i[4] for i in itens],
        crs=4674,
    )


def test_exclusoes_valem_em_qualquer_modo_e_tamanho_nao_corta():
    for modo in D.MODOS:
        a = D.avaliar(_linha("PA-1-X", desm_pos2016_ha=3.0), None, modo)
        assert not a["no_lote"] and any("PRODES" in t for t in a["fora"])
        b = D.avaliar(_linha("PA-1-Y", alerta_ha=0.5), None, modo)
        assert not b["no_lote"]
        c = D.avaliar(_linha("PA-1-Z", ha=0.8, restauracao_area_ha=0.3), None, modo)  # pequena entra
        assert c["no_lote"]
    assert D.avaliar(_linha("PA-1-B", alerta_ha=0.005), None)["no_lote"]  # ruído de borda (< 100 m²)


def test_gleba_federal_estrito_sai_normal_ressalva():
    li = _linha("PA-1-G", ha=1000, terra_gleba_federal_ha=500)  # 50% do CAR
    assert not D.avaliar(li, None, "estrito")["no_lote"]
    n = D.avaliar(li, None, "normal")
    assert n["no_lote"] and n["prontidao"] == "baixa"
    assert any("gleba federal" in t for t in n["ressalvas_fortes"])
    assert D.avaliar(_linha("PA-1-H", ha=1000, terra_gleba_federal_ha=100), None, "estrito")["no_lote"]  # 10%
    sem = D.avaliar(_linha("PA-1-S", terra_gleba_federal_ha=None), None, "estrito")
    assert sem["no_lote"] and "gleba federal não medida" in sem["ressalvas_medias"]


def test_matricula_sem_sigef_vale_e_so_certificado_pede_inteiro_teor():
    a = D.avaliar(_linha("PA-1-M", caminho_terra="privada_matricula", matricula_ha=400), None)
    assert a["matricula"].startswith("matrícula") and a["no_lote"]
    b = D.avaliar(_linha("PA-1-C", caminho_terra="posse_em_titulacao", terra_sigef_posse_ha=300), None, "estrito")
    assert b["no_lote"] and "só certificado no SIGEF: pedir inteiro teor" in b["ressalvas_medias"]
    c = D.avaliar(_linha("PA-1-P", caminho_terra="posse_em_titulacao"), None, "estrito")
    assert not c["no_lote"]
    assert D.avaliar(_linha("PA-1-P", caminho_terra="posse_em_titulacao"), None, "normal")["no_lote"]
    assert not D.avaliar(_linha("PA-1-T", caminho_terra="publica_sem_destinacao"), None, "normal")["no_lote"]


def test_carbono_real_regional_e_divisa():
    geo = gpd.GeoDataFrame(
        {"cod_imovel": ["PA-1-CRUZA", "PA-1-DIVISA", "PA-1-LONGE"]},
        geometry=[_caixa(0, 0), _caixa(0.0405, 0), _caixa(0.5, 0.5)],
        crs=4674,
    )
    lim = _limites([
        ("VCS9001", "poligono_oficial", "registrado", 300.0, _caixa(0.01, 0, 0.0300)),  # cruza o 1º, encosta no 2º
        ("VCS4137", "poligono_oficial", "registrado", 2_000_000.0, shapely.box(-48, -4, -46, -2)),  # regional
        ("VCS4137", "poligono_secundario", "registrado", 900.0, _caixa(0.6, 0.6)),  # instância pública
        ("VCS7777", "poligono_oficial", "retirado", 500.0, _caixa(0.5, 0.5)),  # inativo não conta
    ])  # fmt: skip
    carb = D.carbono(geo, lim)
    c1, c2, c3 = carb["PA-1-CRUZA"], carb["PA-1-DIVISA"], carb["PA-1-LONGE"]
    assert c1["projetos"] == ["VCS9001"] and c1["oficial_ha"] > 100
    assert c2["projetos"] == [] and c2["divisas"][0]["projeto"] == "VCS9001" and c2["divisas"][0]["distancia_m"] < 100
    assert c3["projetos"] == [] and not c3["divisas"]  # retirado não conta
    for c in (c1, c2, c3):
        assert [x["projeto"] for x in c["regionais"]] == ["VCS4137"]  # regional nunca exclui
    assert 5_000 < c3["regionais"][0]["distancia_instancia_m"] < 20_000

    li = [_linha(c) for c in geo.cod_imovel]
    estrito = {a["cod_imovel"]: a for a in (D.avaliar(x, carb[x["cod_imovel"]], "estrito") for x in li)}
    assert not estrito["PA-1-CRUZA"]["no_lote"]
    assert estrito["PA-1-CRUZA"]["projeto_carbono_ha"] > 100  # não sai mais zero
    assert estrito["PA-1-DIVISA"]["no_lote"] and estrito["PA-1-DIVISA"]["ressalvas_leves"]
    assert estrito["PA-1-LONGE"]["no_lote"] and "a conferir" in estrito["PA-1-LONGE"]["ressalvas_medias"][0]
    normal = D.avaliar(li[0], carb["PA-1-CRUZA"], "normal")
    assert normal["no_lote"] and normal["prontidao"] == "baixa"


def test_lotes_por_vizinhanca_e_dossie_nos_tres_formatos(tmp_path):
    # 3 perto (até ~10 km), 1 a ~60 km, sem corte por tamanho
    geo = gpd.GeoDataFrame(
        {"cod_imovel": ["PA-1-A", "PA-1-B", "PA-1-C", "PA-1-D", "PA-1-E"]},
        geometry=[_caixa(0, 0), _caixa(0.05, 0), _caixa(0, 0.08), _caixa(0.55, 0), _caixa(0.02, 0.02, 0.001)],
        crs=4674,
    )
    linhas = [_linha("PA-1-A", restauracao_area_ha=300), _linha("PA-1-B"), _linha("PA-1-C"),
              _linha("PA-1-D", restauracao_area_ha=50), _linha("PA-1-E", ha=1.0, restauracao_area_ha=0.5),
              _linha("PA-1-F", desm_pos2016_ha=10)]  # fmt: skip
    d = D.montar(tmp_path, 1505502, linhas=linhas, geo=geo, limites=False, hoje="2026-11-17")
    assert d["municipio"] == "Paragominas" and d["uf"] == "PA"
    assert [x["n"] for x in d["lotes"]] == [4, 1]
    assert {m["cod_imovel"] for m in d["lotes"][0]["imoveis"]} == {"PA-1-A", "PA-1-B", "PA-1-C", "PA-1-E"}
    assert d["imoveis_aptos"] == 5 and d["fora_por_motivo"][0][0] == "desmatamento PRODES desde 2016"
    assert "embargo ICMBio" in d["filtros_sem_dado"]
    md = D.markdown(d)
    assert md.startswith("# Paragominas: 2 lotes de restauração para avaliação")
    tabela = "| Lote | Imóveis | ha restauráveis | Raio / centro | Principais ressalvas | Prontidão |"
    for parte in ("## Oferta", tabela, "## O que já foi checado", "## O que falta (validação humana)", "Carbonext",
                  "## Potencial adicional no município", "## Anexo: imóveis por lote", "PA-1-E"):  # fmt: skip
        assert parte in md
    arq = D.gravar(d, tmp_path / "saida", "dossie-teste")
    assert arq["pdf"].read_bytes()[:4] == b"%PDF"
    assert arq["docx"].read_bytes()[:2] == b"PK"
    assert "CPF" not in md and "CNPJ" not in md


def test_estrito_tira_e_normal_mantem_no_montar(tmp_path):
    geo = gpd.GeoDataFrame({"cod_imovel": ["PA-1-A", "PA-1-B"]}, geometry=[_caixa(0, 0), _caixa(0.05, 0)], crs=4674)
    lim = _limites([("VCS9001", "poligono_oficial", "registrado", 300.0, _caixa(0, 0, 0.01))])
    linhas = [_linha("PA-1-A"), _linha("PA-1-B")]
    e = D.montar(tmp_path, 1505502, modo="estrito", linhas=linhas, geo=geo, limites=lim)
    n = D.montar(tmp_path, 1505502, modo="normal", linhas=linhas, geo=geo, limites=lim)
    assert e["imoveis_aptos"] == 1 and n["imoveis_aptos"] == 2
    # o de ressalva forte forma lote à parte, depois do pronto
    assert [(x["n"], x["prontidao"]) for x in n["lotes"]] == [(1, "alta"), (1, "baixa")]


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_paragominas_quatro_cars_reais():
    """Polígonos reais (Release dados) e limites reais (Release insumos), recortados em volta dos CARs."""
    geo = gpd.read_file(FIXTURES / "paragominas_cars.geojson")
    alvo = {"D4386947", "CE800C8A", "A5BAFA27", "A79C0259"}
    chave = {c: next(a for a in alvo if a in c.replace(".", "").replace("-", "")) for c in geo.cod_imovel.astype(str)
             if any(a in c.replace(".", "").replace("-", "") for a in alvo)}  # fmt: skip
    assert set(chave.values()) == alvo
    carb = D.carbono(
        geo[geo.cod_imovel.astype(str).isin(chave)], gpd.read_file(FIXTURES / "paragominas_limites_carbono.geojson")
    )
    por = {chave[c]: v for c, v in carb.items()}
    assert "VCS4681" in por["A5BAFA27"]["projetos"] and 1300 < por["A5BAFA27"]["oficial_ha"] < 1600
    assert {x["projeto"]: x["distancia_m"] for x in por["CE800C8A"]["divisas"]}.get("VCS4681", 999) < 100
    assert {x["projeto"]: x["distancia_m"] for x in por["A79C0259"]["divisas"]}.get("VCS1953", 999) < 100
    for a in alvo:
        assert "VCS4137" in [x["projeto"] for x in por[a]["regionais"]]  # regional: a conferir, nunca exclusão
    assert not por["D4386947"]["projetos"] and not por["CE800C8A"]["projetos"]
    ha = dict(zip(geo.cod_imovel.astype(str), geo.to_crs(5880).area / 1e4, strict=True))
    for c, a in chave.items():
        gleba = 0.0 if a in ("D4386947", "CE800C8A") else None  # CNFP 2025: 0 ha (Croatá a ~11 km)
        li = _linha(c, ha=ha[c], matricula_ha=ha[c], terra_gleba_federal_ha=gleba)
        e, n = D.avaliar(li, carb[c], "estrito"), D.avaliar(li, carb[c], "normal")
        assert n["no_lote"]
        assert e["no_lote"] is (a != "A5BAFA27")
