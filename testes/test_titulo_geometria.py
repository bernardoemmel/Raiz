"""Título, geometria (E5 passos 1 a 5): ângulos, fechamento, comparação D1 a D7, memorial, planilha ODS, nota de
risco e a tarefa do município."""

import io
import json
import shutil
import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon
from typer.testing import CliRunner

from raiz.titulo import conferir as C
from raiz.titulo import geometria as G
from raiz.titulo import memorial as M
from raiz.titulo import nota as N
from raiz.titulo import planilha as P
from raiz.titulo import tarefa as T
from testes.conftest import AMOSTRA

COD = 1504950


@pytest.fixture(autouse=True)
def _documentos_isolados(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs_isolados"))


def _quadra(lon0=-47.0, lat0=-2.0, lados=((80, 500), (10, 400), (260, 520), (175, 30))):
    pts = [(lon0, lat0)]
    for az, d in lados:
        pts.append(G.avancar(*pts[-1], az, d))
    return pts


# --- ângulos e fechamento -----------------------------------------------------------------------------------------


def test_angulos_e_coordenadas():
    assert G.dms_para_graus("48°12'34,567\" W") == pytest.approx(-48.2096019, abs=1e-6)
    assert G.dms_para_graus("2°34'56,789\" S") == pytest.approx(-2.5824414, abs=1e-6)
    assert G.dms_para_graus("-2°34'56,789\"") == pytest.approx(-2.5824414, abs=1e-6)
    assert G.graus_para_dms(-48.2096019) == "-48°12'34,57\""
    assert [G.rumo_para_azimute(30, *q) for q in (("N", "E"), ("S", "E"), ("S", "O"), ("N", "W"))] == [
        30,
        150,
        210,
        330,
    ]
    assert G.fuso_do_meridiano(-51) == 22 and G.fuso_do_meridiano(-45) == 23
    lon, lat = G.utm_para_geo(500000, 9778000, 22, True)
    assert lon == pytest.approx(-51.0, abs=1e-6) and lat == pytest.approx(-2.0, abs=0.01)


def test_fechamento_e_regra_da_bussola():
    pts = _quadra()
    lados = [G.azimute_distancia(*pts[i], *pts[(i + 1) % len(pts)]) for i in range(len(pts))]
    f = G.fechar(*pts[0], lados)
    assert f.erro_m < 0.01 and (f.precisao is None or f.precisao > 100_000)
    errado = [(az, d + (1.5 if i == 0 else 0)) for i, (az, d) in enumerate(lados)]
    f = G.fechar(*pts[0], errado)
    assert f.erro_m == pytest.approx(1.5, abs=0.05) and f.precisao == pytest.approx(f.perimetro_m / f.erro_m)
    assert f.texto_precisao.startswith("1:")
    # depois do ajuste, o último vértice volta para perto do inicial (a correção cresce com a distância percorrida)
    assert G.azimute_distancia(*f.ajustados[0], *pts[0])[1] < 1e-6


def test_comparacao_d1_a_d7():
    p = Polygon(_quadra())
    assert G.comparar(p, Polygon([G.avancar(x, y, 45, 0.3) for x, y in _quadra()]))["classe"] == "D1"
    assert G.comparar(p, Polygon([G.avancar(x, y, 45, 0.8) for x, y in _quadra()]))["classe"] == "D2"
    assert G.comparar(p, Polygon([G.avancar(x, y, 45, 5) for x, y in _quadra()]))["classe"] == "D3"
    c = G.comparar(p, Polygon([G.avancar(x, y, 45, 120) for x, y in _quadra()]))
    assert c["classe"] in ("D5", "D6") and c["dif_area_pct"] < 0.1
    longe = Polygon([G.avancar(x, y, 0, 5000) for x, y in _quadra()])
    assert G.comparar(p, longe)["classe"] == "D7"
    a, per = G.area_perimetro(p)
    assert a > 0 and per > 1400


# --- memorial ------------------------------------------------------------------------------------------------------


def _vertices():
    return [(f"ABC1-M-{i + 1:04d}", x, y) for i, (x, y) in enumerate(_quadra())]


def test_memorial_gerado_volta_igual_nos_dois_estilos():
    p = Polygon(_quadra())
    for estilo in ("sigef", "rumo"):
        lt = M.ler(M.gerar(_vertices(), "Exemplo", "PA", estilo))
        assert len(lt.vertices) == 5 and not lt.revisar and lt.confianca == 1.0, estilo
        assert G.comparar(p, lt.poligono, 0.5)["classe"] == "D1", estilo
        assert lt.area_declarada_ha == pytest.approx(lt.area_ha, rel=1e-3)
    ach = M.ler(M.gerar(_vertices())).achados("PA-1504950-X")
    assert {a.regra: a.situacao for a in ach} == {
        "memorial.leitura": "ok",
        "memorial.fechamento": "ok",
        "memorial.area_declarada": "ok",
    }


def test_memorial_em_utm_e_sem_nome_de_confrontante():
    texto = (
        "Inicia-se no vértice M-01, de coordenadas N 9.778.000,00 m e E 500.000,00 m; deste, segue confrontando com "
        "Fulano de Tal, com azimute de 90°00'00\" e distância de 100,00 m até o vértice M-02, de coordenadas "
        "N 9.778.000,00 m e E 500.100,00 m; deste, segue com azimute de 0°00'00\" e distância de 100,00 m até o "
        "vértice M-03, de coordenadas N 9.778.100,00 m e E 500.100,00 m; deste, segue com azimute de 270°00'00\" e "
        "100,00 m até o vértice M-04, de coordenadas N 9.778.100,00 m e E 500.000,00 m; deste, segue com azimute de "
        "180°00'00\" e distância de 100,00 m até o vértice M-01, ponto inicial. Fuso 22 Sul. Área de 1,0000 ha."
    )
    lt = M.ler(texto)
    assert lt.sistema == "utm" and len(lt.vertices) == 4
    assert lt.area_ha == pytest.approx(1.0, rel=0.01) and not lt.revisar
    assert "Fulano" not in json.dumps([a.linha() for a in lt.achados("PA-1")], ensure_ascii=False)


def test_memorial_ruim_pede_revisao_e_o_modelo_so_entra_com_nota_baixa():
    from raiz.documentos.claude import LeitorClaude
    from raiz.documentos.simulacao import ClienteSimulado

    bom = M.gerar(_vertices())
    ruim = bom.replace("500,00 m", "").replace("400,00 m", "")  # dois lados sem distância
    lt = M.ler(ruim)
    assert lt.revisar and any("sem azimute ou distância" in p for p in lt.problemas)
    assert next(a for a in lt.achados("PA-1") if a.regra == "memorial.leitura").gravidade == "confirmar"
    pts = _quadra()
    resposta = dict(
        vertices=[dict(codigo=c, longitude=x, latitude=y, e=None, n=None) for c, x, y in _vertices()],
        lados=[dict(de=_vertices()[i][0], para=_vertices()[(i + 1) % 5][0],
                    azimute_graus=G.azimute_distancia(*pts[i], *pts[(i + 1) % 5])[0],
                    distancia_m=G.azimute_distancia(*pts[i], *pts[(i + 1) % 5])[1]) for i in range(5)],
        fuso=None, hemisferio_sul=True, area_ha=None, perimetro_m=None,
    )  # fmt: skip
    cli = ClienteSimulado([resposta])
    lm = M.ler(ruim, LeitorClaude(cliente=cli))
    assert lm.fonte == "modelo" and not lm.revisar and len(cli.chamadas) == 1
    cli2 = ClienteSimulado([resposta])
    assert M.ler(bom, LeitorClaude(cliente=cli2)).fonte == "regras" and cli2.chamadas == []


# --- planilha ODS -------------------------------------------------------------------------------------------------


def _ods(linhas: list[list[str]], aba: str = "Perimetro_1") -> bytes:
    def cel(v):
        return f'<table:table-cell office:value-type="string"><text:p>{v}</text:p></table:table-cell>'

    corpo = "".join(f"<table:table-row>{''.join(cel(v) for v in r)}</table:table-row>" for r in linhas)
    content = (
        '<?xml version="1.0" encoding="UTF-8"?><office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet>'
        f'<table:table table:name="{aba}"><table:table-row><table:table-cell table:number-columns-repeated="3"/>'
        f"</table:table-row>{corpo}</table:table></office:spreadsheet></office:body></office:document-content>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("content.xml", content)
    return buf.getvalue()


def test_planilha_ods_le_e_valida():
    cab = ["Código do vértice", "Longitude", "Sigma Long (m)", "Latitude", "Sigma Lat (m)", "Tipo de limite", "CNS",
           "Matrícula"]  # fmt: skip
    linhas = [cab]
    for i, (c, x, y) in enumerate(_vertices()):
        sig = "0,80" if i == 1 else "0,10"  # o segundo vértice passa da tolerância do limite artificial
        lim = "LN1" if i == 2 else "LA1"
        linhas.append([c, G.graus_para_dms(x, 3), sig, G.graus_para_dms(y, 3), sig, lim, "06.842-9", "5178"])
    linhas.append(["xx-1", "abc", "", "-2,0", "", "LA1", "", ""])  # código fora do padrão e coordenada que não lê
    [per] = P.perimetros(_ods(linhas))
    assert len(per.vertices) == 6 and per.cns == "06.842-9" and per.matricula == "5178"
    assert per.faltam_colunas == ["altitude", "metodo"]
    ach = {a.regra: a for a in P.validar(per, "PA-1504950-X")}
    assert ach["planilha.precisao"].gravidade == "reprova" and "ABC1-M-0002" in ach["planilha.precisao"].mensagem
    assert ach["planilha.codigo_vertice"].situacao == "conferir" and ach["planilha.coordenada"].situacao == "falta"
    assert ach["planilha.colunas"].gravidade == "confirmar"
    assert ach["planilha.precisao"].registro == "car:PA-1504950-X|mat:68429/5178"


# --- nota de risco e decisão ----------------------------------------------------------------------------------------


def _ach(fase, gravidade, regra="x", valor=None, conf=None):
    return dict(fase=fase, gravidade=gravidade, regra=regra, mensagem=f"{regra} {gravidade}", valor=valor,
                confirmacao_decisao=conf)  # fmt: skip


def test_nota_e_decisao():
    priv = dict(cod_imovel="A", caminho_terra="privada_matricula", risco_terra="baixo")
    assert N.nota_do_imovel(priv, [])["titulo_decisao"] == "aceitar"
    n = N.nota_do_imovel({**priv, "risco_terra": "medio", "risco_terra_motivo": "Matrícula ainda não conferida."}, [])
    assert (n["titulo_nota"], n["titulo_decisao"]) == (2, "aceitar_com_condicoes")
    assert "não conferida" in n["titulo_condicoes"]
    n = N.nota_do_imovel({**priv, "matricula_situacao": "cancelada"}, [])
    assert (n["titulo_nota"], n["titulo_decisao"]) == (5, "recusar") and "cancelada" in n["titulo_decisao_texto"]
    # achado que reprova sobe a nota; confirmado por gente, deixa de contar
    n = N.nota_do_imovel(priv, [_ach("coerencia", "reprova", "certidao.area_menor")])
    assert n["titulo_nota"] == 2 and n["titulo_decisao"] == "analise_humana"
    n = N.nota_do_imovel(priv, [_ach("coerencia", "reprova", "certidao.area_menor", conf="descartado")])
    assert n["titulo_decisao"] == "aceitar"
    # geometria muito divergente
    n = N.nota_do_imovel(priv, [_ach("geometria", "confirmar", "geometria.car_sigef", "D6")])
    assert n["titulo_nota"] == 3 and "divergem" in n["titulo_bandeiras"]
    # posse: a classe da regularização é a base; os requisitos dela viram bandeira, não somam de novo
    posse = dict(cod_imovel="B", caminho_terra="posse_em_titulacao", risco_terra="alto",
                 regularizacao_classe="falta_georreferenciamento")  # fmt: skip
    n = N.nota_do_imovel(posse, [_ach("regularizacao", "reprova", "regularizacao.georreferenciamento")])
    assert (n["titulo_nota"], n["titulo_decisao"]) == (3, "aceitar_com_condicoes")
    assert N.nota_do_imovel({**posse, "regularizacao_classe": "impedida"}, [])["titulo_decisao"] == "recusar"
    assert N.nota_do_imovel({**posse, "regularizacao_classe": "pendente"}, [])["titulo_decisao"] == "analise_humana"


# --- tarefa do município ---------------------------------------------------------------------------------------------


def test_geometria_car_contra_sigef():
    car = gpd.GeoDataFrame({"cod_imovel": ["A", "B"]}, geometry=[Polygon(_quadra()),
                           Polygon(_quadra(lon0=-46.9))], crs=4674)  # fmt: skip
    sig = gpd.GeoDataFrame(
        {"parcela_codigo": ["p1", "p2"]},
        geometry=[Polygon([G.avancar(x, y, 45, 2) for x, y in _quadra()]),
                  Polygon([G.avancar(x, y, 45, 150) for x, y in _quadra(lon0=-46.9)])],
        crs=4674,
    )  # fmt: skip
    ach = {a.cod_imovel: a for a in T.geometria_car_sigef(car, sig)}
    assert ach["A"].valor == "D1" and ach["A"].situacao == "ok" and ach["A"].registro == "car:A|sigef:p1"
    assert ach["B"].valor in ("D5", "D6") and ach["B"].gravidade == "confirmar"
    assert T.geometria_car_sigef(car, sig.iloc[0:0]) == []


def test_tarefa_do_municipio(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv", f"terra_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    r = T.escrever_municipio(pasta, COD)
    nt = pd.read_csv(pasta / f"titulo_{COD}.csv")
    assert len(nt) == r["imoveis"] and set(nt.titulo_decisao) <= set(N.DECISOES)
    assert nt.titulo_nota.between(1, 5).all() and (nt.titulo_versao == T.versao()).all()
    t = pd.read_csv(pasta / f"terra_{COD}.csv").merge(nt, on="cod_imovel")
    assert (t[t.caminho_terra == "publica_sem_destinacao"].titulo_decisao == "recusar").all()
    assert (t[t.caminho_terra == "privada_matricula"].titulo_decisao == "aceitar_com_condicoes").all()
    assert T.recalcular(tmp_path) == {"refeitos": [], "em_dia": 1, "erros": []}


# --- documento avulso e conjunto de teste ----------------------------------------------------------------------------


def test_conferir_documento_e_conjunto_de_teste(tmp_path):
    p = Polygon(_quadra())
    res, ach = C.conferir_poligono(p, "PA-1504950-X", "memorial", 0.5,
                                   car=Polygon([G.avancar(x, y, 0, 3) for x, y in _quadra()]), sigef=p)  # fmt: skip
    assert res["sigef"]["classe"] == "D1" and res["car"]["classe"] == "D1"
    assert {a.regra for a in ach} == {"memorial.contra_sigef", "memorial.contra_car"}
    parcelas = gpd.GeoDataFrame(
        {"parcela_codigo": [f"p{i}" for i in range(6)]},
        geometry=[Polygon(_quadra(lon0=-47 + 0.05 * i)) for i in range(6)],
        crs=4674,
    )
    pares = C.conjunto_teste(parcelas, n=4, pasta=tmp_path / "teste")
    assert len(pares) == 8 and (tmp_path / "teste" / "pares.jsonl").exists()
    placar = C.avaliar_conjunto(pares)
    assert placar["sigef"]["acerto"] == 1.0 and placar["rumo"]["acerto"] == 1.0


def test_cli_memorial_e_planilha(tmp_path, monkeypatch):
    from raiz.cli import app

    monkeypatch.setattr("raiz.funil.rodar.dir_trabalho", lambda: tmp_path)
    arq = tmp_path / "memorial.txt"
    arq.write_text(M.gerar(_vertices()), encoding="utf-8")
    r = CliRunner().invoke(app, ["titulo", "memorial", str(arq), "--cod-imovel", "PA-1504950-X"])
    assert r.exit_code == 0, r.output
    assert "5 vértices (geo, regras), confiança 100%" in r.output and "sem polígono do CAR" in r.output
    ods = tmp_path / "p.ods"
    cab = ["Código do vértice", "Longitude", "Latitude"]
    ods.write_bytes(_ods([cab] + [[c, str(x), str(y)] for c, x, y in _vertices()]))
    r = CliRunner().invoke(app, ["titulo", "planilha", str(ods), "--cod-imovel", "PA-1504950-X"])
    assert r.exit_code == 0, r.output
    assert "aba Perimetro_1: 5 vértices" in r.output and "planilha.poligono" in r.output
