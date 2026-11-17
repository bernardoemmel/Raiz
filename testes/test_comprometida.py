"""Terra já comprometida no processamento: coleta dos limites públicos, status por CAR e a tarefa própria do
executor. Páginas e respostas gravadas: nenhum teste vai à rede."""

import datetime as dt
import io
import json
import shutil
import tarfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box
from sqlalchemy import text

from raiz.comprometida import coleta as CL
from raiz.comprometida import status as ST
from testes.conftest import AMOSTRA

HOJE = "2026-11-16"
COD = 1504950
# projeto oficial: 0,2 x 0,2 grau (~22 km de lado) no sudeste do Pará
PROJETO = box(-50.0, -4.0, -49.8, -3.8)
SECUNDARIO = box(-49.5, -4.0, -49.4, -3.9)


def _reg(fonte="verra", oid="VCS665", geom=PROJETO, certeza="poligono_oficial", situacao="ativo", registro="VCS",
         tipo="projeto_carbono"):  # fmt: skip
    return {"fonte_id": fonte, "objeto_id": oid, "registro": registro, "tipo": tipo, "situacao": situacao,
            "certeza": certeza, "uf": "PA", "fonte_url": "https://verra.org/registry/overview/",
            "data_referencia": None, "observado_em": HOJE, "inicio": None, "fim": None, "geometry": geom}  # fmt: skip


def _cob(fonte, estado="consultado", escopo="projeto", recorte="X"):
    return {"fonte_id": fonte, "estado": estado, "escopo": escopo, "recorte": recorte, "url": "https://verra.org/",
            "data_referencia": None, "consultado_em": HOJE}  # fmt: skip


def _berkeley(n=3):
    regs = [{"fonte_id": "berkeley", "objeto_id": str(i), "registro": "VCS", "tipo": "projeto_carbono",
             "situacao": "ativo", "certeza": "catalogo_sem_geometria", "uf": "PA", "geometry": None}
            for i in range(n)]  # fmt: skip
    return {"registros": regs, "cobertura": _cob("berkeley", "parcial", "brasil", "BR")}


def _iterador(verra_ok=True, sfb_ok=True, zenodo=True):
    def it(**kw):
        yield _berkeley(3)
        if "verra" in kw["fontes"]:
            if verra_ok:
                yield {"registros": [_reg()], "cobertura": _cob("verra", "parcial", recorte="VCS665")}
                yield {"registros": [_reg(oid="VCS70", geom=SECUNDARIO, certeza="poligono_secundario")],
                       "cobertura": _cob("verra", "parcial", recorte="VCS70")}  # fmt: skip
                yield {"registros": [], "cobertura": _cob("verra", "parcial", recorte="VCS99")}  # sem KML
            else:
                yield {"registros": [], "cobertura": _cob("verra", "indisponivel", recorte="VCS665")}
        if "sfb_concessoes" in kw["fontes"]:
            if sfb_ok:
                r = _reg("sfb_concessoes", "SFB-UMF1", box(-52, -5, -51.9, -4.9), registro="SFB",
                         tipo="concessao_florestal")  # fmt: skip
                yield {"registros": [r], "cobertura": _cob("sfb_concessoes", "consultado", "bbox", "BR")}
            else:
                yield {"registros": [], "cobertura": _cob("sfb_concessoes", "indisponivel", "bbox", "BR")}

    return it


# --- coleta --------------------------------------------------------------------------------------------------------


def test_coleta_diz_o_que_cada_fonte_cobriu():
    r = CL.coletar(("verra", "sfb_concessoes"), observado_em=HOJE, iterador=_iterador())
    cob = {c["fonte_id"]: c for c in r["cobertura"]}
    # Verra: 2 de 3 projetos do catálogo trouxeram polígono -> parcial; nunca "consultado" com projeto faltando
    assert cob["verra"]["estado"] == "parcial" and cob["verra"]["projetos_com_poligono"] == 2
    assert cob["verra"]["projetos_esperados"] == 3 and cob["verra"]["escopo"] == "bbox"
    assert cob["sfb_concessoes"]["estado"] == "consultado" and "berkeley" not in cob
    assert len(r["registros"]) == 3
    # fonte que cai vira indisponível, nunca ausência
    r = CL.coletar(("verra", "sfb_concessoes"), observado_em=HOJE, iterador=_iterador(verra_ok=False, sfb_ok=False))
    assert {c["estado"] for c in r["cobertura"]} == {"indisponivel"} and r["erros"]


def test_gravar_limites_manifesto_e_pacote_do_motor(tmp_path):
    r = CL.coletar(("verra", "sfb_concessoes"), observado_em=HOJE, iterador=_iterador())
    m = CL.gravar(r, tmp_path)
    g = gpd.read_parquet(tmp_path / "comprometida_limites.parquet")
    assert len(g) == 3 and set(g.columns) >= {"fonte_id", "objeto_id", "certeza", "geometry"}
    assert not any(c in g.columns for c in ("nome", "proponente", "cpf", "cnpj"))
    assert m["limites"] == 3 and m["projetos_motor"] == 1 and m["projetos_catalogo_verra"] == 3
    assert json.loads((tmp_path / "comprometida_cobertura.json").read_text())["sha256_limites"] == m["sha256_limites"]
    # o motor só recebe limite oficial e ativo da Verra: nem indício, nem concessão
    with tarfile.open(tmp_path / "projetos_carbono.tar.gz") as t:
        assert t.getnames() == ["projetos_carbono/VCS665.geojson"]
        gj = json.load(io.TextIOWrapper(t.extractfile("projetos_carbono/VCS665.geojson")))
    assert (
        gj["features"][0]["properties"] == {"projeto": "VCS665"} and gj["features"][0]["geometry"]["type"] == "Polygon"
    )
    # sem projeto oficial, o pacote some em vez de ficar velho
    r2 = CL.coletar(("sfb_concessoes",), observado_em=HOJE, iterador=_iterador())
    CL.gravar(r2, tmp_path)
    assert not (tmp_path / "projetos_carbono.tar.gz").exists()


# --- status por CAR ------------------------------------------------------------------------------------------------


def _municipio(tmp_path, farms: dict[str, tuple], ha: dict[str, float] | None = None):
    pasta = tmp_path / "PA"
    pasta.mkdir(exist_ok=True)
    cods = {k: f"PA-{COD}-{k * 32}" for k in farms}
    gpd.GeoDataFrame({"cod_imovel": list(cods.values())}, geometry=[farms[k][0] for k in farms], crs=4674).to_parquet(
        pasta / f"geo_{COD}.parquet"
    )
    pd.DataFrame({"cod_imovel": list(cods.values()), "ha": [(ha or {}).get(k, farms[k][1]) for k in farms]}).to_csv(
        pasta / f"imoveis_{COD}.csv", index=False
    )
    return pasta, cods


@pytest.fixture
def limites(tmp_path, monkeypatch):
    pasta = tmp_path / "limites"
    CL.gravar(CL.coletar(("verra", "sfb_concessoes"), observado_em=HOJE, iterador=_iterador()), pasta)
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(pasta))
    return pasta


def test_status_livre_comprometida_risco_e_nao_verificado(tmp_path, limites):
    fazendas = {
        "A": (box(-49.95, -3.95, -49.90, -3.90), 3000.0),  # dentro do projeto oficial
        "C": (box(-49.48, -3.98, -49.42, -3.92), 400.0),  # dentro do polígono secundário (indício)
        "D": (box(-48.0, -2.0, -47.9, -1.9), 500.0),  # longe de tudo
        "E": (box(-49.995, -3.995, -49.99, -3.99), 3.0),  # pequena, inteira dentro do projeto
    }
    pasta, c = _municipio(tmp_path, fazendas)
    df = ST.calcular_municipio(pasta, COD, hoje=HOJE).set_index("cod_imovel")
    a, cc, d, e = (df.loc[c[k]] for k in "ACDE")
    assert a.status_sobreposicao == "ja_comprometida" and a.projeto_id == "VCS665" and a.fonte == "verra"
    assert a.sobreposicao_ha > 100 and a.data_consulta == HOJE and a.comprometida_cobertura == "completa"
    assert cc.status_sobreposicao == "risco_sobreposicao" and cc.projeto_id == "VCS70"  # secundário: indício
    assert cc.sobreposicao_ha == 0 and cc.sobreposicao_indicio_ha > 10
    assert d.status_sobreposicao == "livre" and d.sobreposicao_ha == 0 and pd.isna(d.projeto_id)
    assert e.status_sobreposicao == "ja_comprometida"  # fazenda pequena nunca fica de fora do cruzamento
    assert set(df.status_sobreposicao) <= set(ST.STATUS)
    assert list(df.reset_index().columns) == ST.COLUNAS


def test_pequena_sobreposicao_vira_risco_e_fracao_conta_para_a_pequena(tmp_path, limites):
    # faixa de ~22 m x ~110 m a cavalo na borda leste do projeto: metade dentro (~0,12 ha)
    dentro = box(-49.8001, -3.9, -49.7999, -3.899)
    pasta, c = _municipio(tmp_path, {"A": (dentro, 500.0)})
    df = ST.calcular_municipio(pasta, COD, hoje=HOJE).set_index("cod_imovel")
    assert df.loc[c["A"]].status_sobreposicao == "risco_sobreposicao"  # <1 ha e <5% de 500 ha
    # imóvel de 2 ha com metade dentro conta pela fração (>= 5%)
    dto = {"situacao": "sobreposicao_confirmada", "area_confirmada": {"valor": 0.5}, "area_indicio": {"valor": 0.0}}
    assert ST.classificar(dto, 2.0)[0] == "ja_comprometida" and ST.classificar(dto, 500.0)[0] == "risco_sobreposicao"


def test_sem_fonte_ou_coleta_caida_nunca_vira_livre(tmp_path, monkeypatch):
    pasta, c = _municipio(tmp_path, {"A": (box(-48.0, -2.0, -47.9, -1.9), 500.0)})
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "vazio"))  # coleta ainda não chegou
    df = ST.calcular_municipio(pasta, COD, hoje=HOJE)
    assert set(df.status_sobreposicao) == {"nao_verificado"} and set(df.comprometida_cobertura) == {"nenhuma"}
    assert df.comprometida_versao.iloc[0].endswith("sem_limites")
    # todas as fontes indisponíveis: coletou, mas ninguém cobriu a área
    caida = tmp_path / "caida"
    r = CL.coletar(("verra", "sfb_concessoes"), observado_em=HOJE, iterador=_iterador(False, False))
    CL.gravar(r, caida)
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(caida))
    assert set(ST.calcular_municipio(pasta, COD, hoje=HOJE).status_sobreposicao) == {"nao_verificado"}


def test_retirado_ou_inativo_nao_compromete(tmp_path, monkeypatch):
    pasta_l = tmp_path / "l"
    it = _iterador()

    def retirado(**kw):
        for res in it(**kw):
            for r in res["registros"]:
                if r["objeto_id"] == "VCS665":
                    r["situacao"] = "retirado"
            yield res

    CL.gravar(CL.coletar(("verra",), observado_em=HOJE, iterador=retirado), pasta_l)
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(pasta_l))
    pasta, c = _municipio(tmp_path, {"A": (box(-49.95, -3.95, -49.90, -3.90), 3000.0)})
    assert ST.calcular_municipio(pasta, COD, hoje=HOJE).status_sobreposicao.iloc[0] == "livre"


# --- tarefa do executor ---------------------------------------------------------------------------------------------


def test_tarefa_propria_so_depende_do_funil_e_muda_com_a_coleta(tmp_path, monkeypatch):
    from raiz.executor import tarefas as T

    t = next(x for x in T.tarefas_producao() if x.nome == "comprometida")
    assert t.depende == ("funil",) and t.saidas == ("comprometida_{cod}.csv",)
    assert t.versao().startswith("comprometida-")
    # ninguém depende dela: um cruzamento novo nunca refaz terra, ficha ou desenvolvedor
    assert all("comprometida" not in x.depende for x in T.tarefas_producao())
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "nada"))
    assert t.externas("PA", COD, {}) == {"limites": None}
    CL.gravar(CL.coletar(("verra",), observado_em=HOJE, iterador=_iterador()), tmp_path / "a")
    monkeypatch.setenv("RAIZ_COMPROMETIDA_DIR", str(tmp_path / "a"))
    antes = t.externas("PA", COD, {})["limites"]
    assert antes
    CL.gravar(CL.coletar(("verra", "sfb_concessoes"), observado_em=HOJE, iterador=_iterador()), tmp_path / "a")
    assert t.externas("PA", COD, {})["limites"] != antes  # coleta nova: refaz só esta tarefa


def test_tarefa_roda_pelo_executor_sem_tocar_no_funil(tmp_path, limites):
    from raiz.executor import tarefas as T

    pasta, c = _municipio(tmp_path, {"A": (box(-49.95, -3.95, -49.90, -3.90), 3000.0)})
    T.rodar_comprometida("PA", COD, pasta)
    df = pd.read_csv(pasta / f"comprometida_{COD}.csv")
    assert df.status_sobreposicao.tolist() == ["ja_comprometida"]


# --- carga ---------------------------------------------------------------------------------------------------------


def test_carga_conhece_o_complemento():
    from raiz import carga, contrato

    assert "comprometida" in contrato.COMPLEMENTOS and "comprometida" in carga.TIPOS_MUNICIPIO


@pytest.mark.banco
def test_carga_leva_o_status_como_complemento_do_imovel(con, tmp_path):
    from raiz.carga import carregar_municipio

    pasta = tmp_path / "PA"
    pasta.mkdir()
    for f in (f"imoveis_{COD}.csv", f"filtros_{COD}.csv"):
        shutil.copy(AMOSTRA / f, pasta / f)
    im = pd.read_csv(pasta / f"imoveis_{COD}.csv", low_memory=False)
    im["teste_marca"] = "comprometida"
    im.to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    cods = im.cod_imovel.head(3).tolist()
    pd.DataFrame({"cod_imovel": cods, "status_sobreposicao": ["livre", "ja_comprometida", "nao_verificado"],
                  "sobreposicao_ha": [0.0, 12.5, None], "projeto_id": [None, "VCS665", None],
                  "fonte": [None, "verra", None]}).to_csv(pasta / f"comprometida_{COD}.csv", index=False)  # fmt: skip
    r = carregar_municipio(con, pasta, COD, dt.date(2031, 3, 3))
    rs = con.execute(
        text("""select cod_imovel, atributos->>'status_sobreposicao' s, atributos->>'projeto_id' p
                from funil.complemento_imovel where rodada_id = :r and tipo = 'comprometida' order by cod_imovel"""),
        {"r": r.rodada_id},
    ).all()
    assert {x.cod_imovel: (x.s, x.p) for x in rs} == dict(
        zip(cods, [("livre", None), ("ja_comprometida", "VCS665"), ("nao_verificado", None)], strict=True)
    )


# --- conferência contra a lista CAR x REDD+ do Pará ------------------------------------------------------------------


def test_conferir_lista_car_redd_do_para(tmp_path):
    from typer.testing import CliRunner

    from raiz.cli import app
    from raiz.comprometida import pacote as PK

    uf = tmp_path / "saida" / "PA"
    uf.mkdir(parents=True)
    a, b, c, d = (f"PA-{COD}-{x * 32}" for x in "ABCD")
    pd.DataFrame({"cod_imovel": [a, b, c], "status_sobreposicao": ["ja_comprometida", "livre", "nao_verificado"]}
                 ).to_csv(uf / f"comprometida_{COD}.csv", index=False)  # fmt: skip
    lista = tmp_path / "lista.csv"
    pd.DataFrame({
        "Project_ID": ["1953", "1953", "4681", "4681", "665"],
        "Project_Nm": ["nome que nunca sai"] * 5,
        "Project_ha": [53000.0] * 5,
        "CAR_cod_im": [a, a, b, c, d],  # A repetido (soma), B e C que a camada não marcou, D sem arquivo
        "sobreposicao_ha": [100.0, 20.0, 1458.0, 0.4, 50.0],  # C é lasca (< 5 ha)
    }).to_csv(lista, index=False)  # fmt: skip
    lis = PK.ler_lista(lista)
    assert set(lis.projeto_id) == {"VCS1953", "VCS4681", "VCS665"} and "Project_Nm" not in lis.columns
    assert lis[lis.cod_imovel == a].sobreposicao_ha.iloc[0] == 120.0
    resumo, lac = PK.conferir(lista, tmp_path / "saida")
    assert resumo["car_na_lista"] == 4 and resumo["car_relevantes"] == 3  # C é lasca e fica de fora
    assert resumo["concordam"] == 1 and resumo["lacunas"] == 1 and resumo["sem_arquivo"] == 1
    assert lac.to_dict("records") == [dict(cod_imovel=b, projeto_id="VCS4681", sobreposicao_ha=1458.0,
                                           status_raiz="livre")]  # fmt: skip
    assert resumo["projetos_nas_lacunas"] == ["VCS4681"]
    r = CliRunner().invoke(app, ["comprometida", "conferir-pacote", str(lista), "--saida", str(tmp_path / "saida"),
                                 "--lacunas", str(tmp_path / "lac.csv")])  # fmt: skip
    assert r.exit_code == 0 and "lacunas" in r.output and (tmp_path / "lac.csv").exists()
    assert "nome que nunca sai" not in r.output
