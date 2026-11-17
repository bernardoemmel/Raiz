"""Terra já comprometida: robustez da coleta Verra (falha de 16/11/2026), fontes secundárias (InfoAmazonia e REDD+ do
Pará) e limites amplos de projetos agrupados. Nenhum teste vai à rede."""

import geopandas as gpd
import httpx
import pandas as pd
import pytest
from shapely.geometry import box

from raiz.coleta import compromissos_registros as CR
from raiz.coleta import compromissos_secundarios as SEC
from raiz.comprometida import coleta as CL
from raiz.comprometida import status as ST

HOJE = "2026-11-17"
COD = 1505502
# "YBYRÁ" de mentira no nordeste do Pará e um imóvel com ~45% dentro dele
PROJETO = box(-47.6, -3.4, -47.4, -3.2)
IMOVEL = box(-47.45, -3.3, -47.39, -3.25)


def _reg(fonte, oid="VCS4681", geom=PROJETO, certeza="poligono_secundario", situacao="desconhecido"):
    return {"fonte_id": fonte, "objeto_id": oid, "registro": "VCS", "tipo": "projeto_carbono", "situacao": situacao,
            "certeza": certeza, "uf": "PA", "fonte_url": "https://zenodo.org/records/23929936",
            "data_referencia": None, "observado_em": HOJE, "inicio": None, "fim": None, "geometry": geom}  # fmt: skip


def _cob(fonte, estado="parcial", escopo="brasil", recorte="BR"):
    return {"fonte_id": fonte, "estado": estado, "escopo": escopo, "recorte": recorte, "url": "https://verra.org/",
            "data_referencia": None, "consultado_em": HOJE}  # fmt: skip


# --- KML e fila Verra ----------------------------------------------------------------------------------------------

KML_PREFIXO_SOLTO = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<gx:Tour/><Document>'
    b"<Placemark><kml:name>x</kml:name><Polygon><outerBoundaryIs><LinearRing><coordinates>"
    b"-50,-4 -49.9,-4 -49.9,-3.9 -50,-4</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
    b"</Document></kml>"
)


def test_kml_com_prefixo_sem_declaracao_e_lido():
    # o erro "unbound prefix: line 3" derrubou a coleta inteira em 16/11
    assert CR.ler_kml(KML_PREFIXO_SOLTO).area == pytest.approx(0.005)
    with pytest.raises(ValueError):
        CR.ler_kml(b"<kml><Polygon><outerBoundaryIs>")  # ilegível vira ValueError, nunca ParseError solto


def test_projeto_com_problema_nao_para_a_fila_verra(monkeypatch):
    monkeypatch.setattr(CR, "PAUSA_S", 0)
    feitos = []

    def verra(oid, **kw):
        feitos.append(oid)
        if oid == "1":
            raise ValueError("Documento sem polígono de projeto")
        if oid == "2":
            raise RuntimeError("erro inesperado de geometria")
        return {"registros": [], "cobertura": _cob("verra", "parcial", "projeto", f"VCS{oid}")}

    monkeypatch.setattr(CR, "coletar_verra", verra)
    res = list(CR.iterar_compromissos(fontes=["verra"], projetos_verra=["1", "2", "4681"]))
    assert feitos == ["1", "2", "4681"]  # antes, o primeiro erro encerrava toda a Verra
    assert [r["cobertura"]["estado"] for r in res] == ["indisponivel", "indisponivel", "parcial"]


def test_registro_fora_do_ar_para_depois_de_falhas_seguidas(monkeypatch):
    monkeypatch.setattr(CR, "PAUSA_S", 0)
    feitos = []

    def verra(oid, **kw):
        feitos.append(oid)
        raise CR.FonteIndisponivel("429")

    monkeypatch.setattr(CR, "coletar_verra", verra)
    list(CR.iterar_compromissos(fontes=["verra"], projetos_verra=[str(i) for i in range(1, 20)]))
    assert len(feitos) == CR.VERRA_FALHAS_SEGUIDAS


def test_json_publico_tenta_de_novo_no_429(monkeypatch):
    monkeypatch.setattr(CR, "PAUSA_S", 0)
    respostas = iter([429, 503, 200])

    def h(req):
        s = next(respostas)
        return httpx.Response(s, json={"id": 1} if s == 200 else None)

    with httpx.Client(transport=httpx.MockTransport(h)) as c:
        assert CR._json_publico(c, "https://x.test/a") == {"id": 1}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(429))) as c:
        with pytest.raises(CR.FonteIndisponivel):
            CR._json_publico(c, "https://x.test/a")


# --- fontes secundárias --------------------------------------------------------------------------------------------


def test_infoamazonia_le_so_identificador_status_e_uf(tmp_path):
    g = gpd.GeoDataFrame(
        {
            "id_crbn": ["BR4681VER", "BR4681VER", "BR125CER", "XYZ"],
            "status": ["Registration requested", "Registered", "Certified", "Registered"],
            "uf": ["PA", "PA", "AC, MT", "PA"],
            "id_mpr*": ["doc-da-empresa"] * 4,  # CNPJ da empresa: nunca lido
            "emprs__": ["Empresa X"] * 4,
        },
        geometry=[PROJETO, box(-47.4, -3.4, -47.3, -3.3), box(-70, -10, -69.9, -9.9), box(0, 0, 1, 1)],
        crs=4674,
    )
    g.to_file(tmp_path / "shp_projetos.shp")
    r = SEC.ler_infoamazonia(tmp_path / "shp_projetos.shp", observado_em=HOJE)
    regs = {x["objeto_id"]: x for x in r["registros"]}
    assert set(regs) == {"VCS4681", "CER125"}  # identificador fora do padrão fica de fora
    y = regs["VCS4681"]
    assert y["certeza"] == "poligono_secundario" and y["situacao"] == "ativo" and y["uf"] == "PA"
    assert y["geometry"].area == pytest.approx(0.05, rel=1e-3)  # as feições do mesmo projeto viram uma
    assert regs["CER125"]["registro"] == "CERCARBONO" and regs["CER125"]["uf"] is None
    assert not any("doc-da-empresa" in str(v) or "Empresa" in str(v) for x in r["registros"] for v in x.values())
    assert r["cobertura"]["estado"] == "parcial"


def test_para_redd_le_so_os_limites_dos_projetos(tmp_path):
    g = gpd.GeoDataFrame(
        {
            "Project_ID": [4681, 4681, 4681],
            "CAR_cod_im": [None, None, "PA-1505502-A5BAFA27DA9649528BAD616CBA637576"],
            "Source": ["Verra", "Verra", "Verra"],
            "Type": ["KML Projeto", "KML Projeto", "CAR"],
        },
        geometry=[PROJETO, PROJETO, IMOVEL],
        crs=4674,
    )
    g.to_file(tmp_path / "db.gpkg", driver="GPKG")
    r = SEC.ler_para_redd(tmp_path / "db.gpkg", observado_em=HOJE, data_referencia="2026-11-03")
    assert len(r["registros"]) == 1  # recorte de CAR não é limite de projeto
    x = r["registros"][0]
    assert x["objeto_id"] == "VCS4681" and x["fonte_id"] == "para_redd_zenodo" and x["certeza"] == "poligono_secundario"
    assert "CAR_cod_im" not in x and x["data_referencia"] == "2026-11-03"


def test_checksum_errado_nao_vira_limite(monkeypatch):
    def h(req):
        return httpx.Response(200, content=b"outro arquivo")

    with httpx.Client(transport=httpx.MockTransport(h)) as c:
        with pytest.raises(ValueError, match="Checksum"):
            SEC.coletar_infoamazonia(cliente=c, observado_em=HOJE)


# --- o imóvel de Paragominas e os limites amplos -------------------------------------------------------------------


def _municipio(tmp_path, geoms: dict, ha: dict):
    pasta = tmp_path / "PA"
    pasta.mkdir(exist_ok=True)
    cods = {k: f"PA-{COD}-{k * 32}" for k in geoms}
    gpd.GeoDataFrame({"cod_imovel": list(cods.values())}, geometry=list(geoms.values()), crs=4674).to_parquet(
        pasta / f"geo_{COD}.parquet"
    )
    pd.DataFrame({"cod_imovel": list(cods.values()), "ha": [ha[k] for k in geoms]}).to_csv(
        pasta / f"imoveis_{COD}.csv", index=False
    )
    return pasta, cods


def _coleta(*resultados):
    def it(**kw):
        yield {"registros": [], "cobertura": {**_cob("berkeley"), "fonte_id": "berkeley"}}
        yield from resultados

    return it


def test_imovel_dentro_do_ybyra_so_por_indicio_vira_risco(tmp_path, monkeypatch):
    # Verra caída (como em 16/11): InfoAmazonia e REDD+ do Pará ainda mostram o imóvel dentro do projeto
    it = _coleta(
        {"registros": [], "cobertura": _cob("verra", "indisponivel", "projeto", "VCS4681")},
        {
            "registros": [_reg("infoamazonia_carbono", situacao="em_validacao")],
            "cobertura": _cob("infoamazonia_carbono"),
        },
        {"registros": [_reg("para_redd_zenodo")], "cobertura": _cob("para_redd_zenodo")},
    )
    CL.gravar(CL.coletar(CL.FONTES_PADRAO, observado_em=HOJE, iterador=it), tmp_path / "l")
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "l"))
    pasta, c = _municipio(tmp_path, {"A": IMOVEL}, {"A": 3263.0})
    a = ST.calcular_municipio(pasta, COD, hoje=HOJE).iloc[0]
    assert a.status_sobreposicao == "risco_sobreposicao" and a.projeto_id == "VCS4681"
    assert a.sobreposicao_indicio_ha > 1000 and set(a.fonte.split("|")) == {"infoamazonia_carbono", "para_redd_zenodo"}


def test_imovel_dentro_do_ybyra_com_kml_oficial_vira_ja_comprometida(tmp_path, monkeypatch):
    oficial = {**_reg("verra", certeza="poligono_oficial", situacao="ativo"),
               "fonte_url": "https://registry.verra.org/verra/public/program/VCS/projects/4681"}  # fmt: skip
    it = _coleta(
        {"registros": [oficial], "cobertura": _cob("verra", "parcial", "projeto", "VCS4681")},
        {"registros": [_reg("para_redd_zenodo")], "cobertura": _cob("para_redd_zenodo")},
    )
    m = CL.gravar(CL.coletar(CL.FONTES_PADRAO, observado_em=HOJE, iterador=it), tmp_path / "l")
    assert m["projetos_motor"] == 1
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "l"))
    pasta, c = _municipio(tmp_path, {"A": IMOVEL}, {"A": 3263.0})
    a = ST.calcular_municipio(pasta, COD, hoje=HOJE).iloc[0]
    assert a.status_sobreposicao == "ja_comprometida" and a.projeto_id.startswith("VCS4681")
    assert a.sobreposicao_ha > 1000 and a.sobreposicao_indicio_ha == 0  # indício não conta a mesma terra de novo


def test_area_geografica_de_projeto_agrupado_nao_compromete(tmp_path, monkeypatch):
    # "área geográfica" de agrupado (ex. VCS3380): dezenas de milhões de ha cobrindo o estado inteiro
    amplo = {**_reg("verra", "VCS3380", box(-56, -9, -46, 0), "poligono_oficial", "ativo"),
             "fonte_url": "https://registry.verra.org/verra/public/program/VCS/projects/3380"}  # fmt: skip
    it = _coleta({"registros": [amplo], "cobertura": _cob("verra", "parcial", "projeto", "VCS3380")})
    m = CL.gravar(CL.coletar(("verra",), observado_em=HOJE, iterador=it), tmp_path / "l")
    assert m["limites_amplos"] == ["VCS3380"] and m["projetos_motor"] == 0
    assert not (tmp_path / "l" / "projetos_carbono.tar.gz").exists()
    g = gpd.read_parquet(tmp_path / "l" / "comprometida_limites.parquet")
    assert bool(g.limite_amplo.iloc[0]) and g.area_ha.iloc[0] > CL.LIMITE_AMPLO_HA
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "l"))
    pasta, c = _municipio(tmp_path, {"A": IMOVEL}, {"A": 3263.0})
    assert ST.calcular_municipio(pasta, COD, hoje=HOJE).status_sobreposicao.iloc[0] == "livre"


def test_kml_com_anel_que_se_cruza_fica_so_com_a_area():
    # make_valid de anel com laço pode devolver coleção com linha (VCS1382): só a área entra
    kml = (
        b'<kml xmlns="http://www.opengis.net/kml/2.2"><Polygon><outerBoundaryIs><LinearRing><coordinates>'
        b"0,0 1,1 1,0 0,1 0,0 0,0</coordinates></LinearRing></outerBoundaryIs></Polygon>"
        b"<Polygon><outerBoundaryIs><LinearRing><coordinates>2,2 3,2 3,2 2,2</coordinates></LinearRing>"
        b"</outerBoundaryIs></Polygon></kml>"
    )
    g = CR.ler_kml(kml)
    assert g.geom_type in ("Polygon", "MultiPolygon") and g.area == pytest.approx(0.5)


def test_limite_suspeito_so_vale_como_indicio(tmp_path, monkeypatch):
    # REDD grande de verdade (VCS1811 tem ~909 mil ha): acima de 500 mil ha só alerta, nunca ja_comprometida
    grande = {**_reg("verra", "VCS1811", box(-48.5, -3.32, -45.5, -3.0), "poligono_oficial", "ativo"),
              "fonte_url": "https://registry.verra.org/verra/public/program/VCS/projects/1811"}  # fmt: skip
    it = _coleta({"registros": [grande], "cobertura": _cob("verra", "parcial", "projeto", "VCS1811")})
    m = CL.gravar(CL.coletar(("verra",), observado_em=HOJE, iterador=it), tmp_path / "l")
    assert m["limites_suspeitos"] == ["VCS1811"] and m["limites_amplos"] == [] and m["projetos_motor"] == 0
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "l"))
    pasta, c = _municipio(tmp_path, {"A": IMOVEL}, {"A": 3263.0})
    a = ST.calcular_municipio(pasta, COD, hoje=HOJE).iloc[0]
    assert a.status_sobreposicao == "risco_sobreposicao" and a.projeto_id == "VCS1811"
