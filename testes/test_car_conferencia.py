"""Conferência na entrada do lote: desenho atual, exclusões e retomada do recálculo."""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from raiz.coleta import car_conferencia as C

COD = 2100154
QUANDO = "2026-11-13T22:00:00+00:00"


@pytest.fixture
def base():
    return gpd.GeoDataFrame(
        {
            "cod_imovel": [f"MA-{COD}-A", f"MA-{COD}-B"],
            "uf": "MA",
            "cod_municipio_ibge": COD,
            "status_imovel": "AT",
            "tipo_imovel": "IRU",
            "m_fiscal": 1.0,
            "municipio": "Município",
            "area": 10.0,
        },
        geometry=[box(-44, -4, -43.99, -3.99), box(-44, -3.9, -43.99, -3.89)],
        crs=4674,
    )


def test_so_selecionadas_recebem_data_e_desenho_atual(base):
    atual = base.copy()
    atual.loc[0, "geometry"] = box(-44, -4, -43.98, -3.98)
    nova, marcas, mudou = C.comparar(base, atual, {base.cod_imovel[0]}, QUANDO)
    assert mudou and nova.geometry[0].equals(atual.geometry[0])
    assert nova.geometry[1].equals(base.geometry[1])
    assert set(marcas) == {base.cod_imovel[0]}
    assert marcas[base.cod_imovel[0]] == {
        "car_conferido_em": QUANDO,
        "car_conferencia": "CAR conferido em 2026-11-13",
        "car_situacao": "conferido",
        "car_geometria_alterada": True,
    }
    _, _, mudou = C.comparar(base, base, set(base.cod_imovel), QUANDO)
    assert not mudou


@pytest.mark.parametrize("problema", ["ausente", "cancelado", "sem_geometria", "duplicado", "ponto"])
def test_cadastro_inconfirmavel_nao_entra_no_lote(base, problema):
    from raiz.pedidos import oferta as O
    from testes.conftest import AMOSTRA

    atual = base.copy()
    cod = base.cod_imovel[0]
    if problema == "ausente":
        atual = atual.iloc[1:]
    elif problema == "cancelado":
        atual.loc[0, "status_imovel"] = "CA"
    elif problema == "sem_geometria":
        atual.loc[0, "geometry"] = None
    elif problema == "ponto":
        atual.loc[0, "geometry"] = atual.geometry[0].centroid
    else:
        atual = pd.concat([atual, atual.iloc[:1]], ignore_index=True)
    _, marcas, mudou = C.comparar(base, atual, {cod}, QUANDO)
    assert not mudou
    assert marcas[cod]["car_situacao"] != "conferido"
    linha = next(li for li in O.linhas_da_pasta(AMOSTRA, 1504950) if li.get("modo_restauracao"))
    oferta = O.de_linha({**linha, **marcas[cod]})
    assert not oferta["elegivel"] and oferta["bloqueio"]


def test_falha_preserva_desenho_e_recalcula_antes_de_marcar(base, tmp_path, monkeypatch):
    base.drop(columns="geometry").to_csv(tmp_path / f"imoveis_{COD}.csv", index=False)
    base[["cod_imovel", "geometry"]].to_parquet(tmp_path / f"geo_{COD}.parquet")
    atual = base.copy()
    atual.loc[0, "geometry"] = box(-44, -4, -43.98, -3.98)
    cod = base.cod_imovel[0]
    monkeypatch.setattr(C, "consultar", lambda uf, codigos: atual)

    def cair(*args):
        raise C.ConferenciaPendente("interrompido")

    monkeypatch.setattr(C, "recalcular", cair)
    with pytest.raises(C.ConferenciaPendente):
        C.conferir_pasta(tmp_path, "MA", COD, {cod}, quando=QUANDO)
    checkpoint = tmp_path / ".car_atual" / str(COD)
    assert (checkpoint / "pendente.json").exists()
    salvo = gpd.read_parquet(checkpoint / "car.parquet")
    assert salvo.geometry[0].equals(atual.geometry[0])
    assert "car_conferido_em" not in pd.read_csv(tmp_path / f"imoveis_{COD}.csv")
    retomadas = []

    def retomar(pasta, uf, codigo, entrada, trabalho):
        g = gpd.read_parquet(entrada)
        retomadas.append(g.geometry[0])
        # Representa o resultado completo do motor, com área calculada no desenho novo.
        t = g.drop(columns="geometry")
        t["ha"] = g.to_crs(5880).area / 1e4
        t.to_csv(pasta / f"imoveis_{codigo}.csv", index=False)
        g[["cod_imovel", "geometry"]].to_parquet(pasta / f"geo_{codigo}.parquet")

    monkeypatch.setattr(C, "recalcular", retomar)
    C.conferir_pasta(tmp_path, "MA", COD, {cod}, quando=QUANDO)
    assert len(retomadas) == 1 and not (checkpoint / "pendente.json").exists()
    t = pd.read_csv(tmp_path / f"imoveis_{COD}.csv")
    assert t.car_situacao.iloc[0] == "conferido" and pd.isna(t.car_situacao.iloc[1])
    assert t.ha.iloc[0] == pytest.approx(atual.to_crs(5880).area.iloc[0] / 1e4)


def test_selecao_de_pedido_confere_tambem_as_substitutas(monkeypatch):
    from raiz.pedidos import servico as S
    from raiz.pedidos.campos import CamposPedido

    oferta = pd.DataFrame({"cod_imovel": ["a", "b"], "uf": "MA", "cod_ibge": COD})
    monkeypatch.setattr(S, "_oferta", lambda *a: oferta)
    consultas = []

    def conferir(engine, of, ids):
        consultas.append(ids)

    monkeypatch.setattr(S, "_conferir_car", conferir)

    def opcoes(*args):
        # A primeira conferência alterou a seleção, que agora escolhe outra fazenda.
        cod = "a" if not consultas else "b"
        return {}, [{"itens": [{"cod_imovel": cod}]}], oferta

    monkeypatch.setattr(S.Z, "opcoes", opcoes)
    S._opcoes_conferidas(None, CamposPedido(), {}, set(), None)
    assert consultas == [{"a"}, {"b"}]


def test_lote_de_producao_rele_dados_depois_da_conferencia(monkeypatch, tmp_path):
    from raiz import lote as L

    dados = {"pasta": tmp_path, "uf": "MA", "municipios_lidos": [COD]}
    conferidas = []

    def montar(dados, **kwargs):
        return {
            "tabela": pd.DataFrame({"cod_imovel": ["A"], "cod_ibge": [COD], "papel": "titular"}),
            "resumo": {"atual": dados.get("atual", False)},
        }

    monkeypatch.setattr(L, "montar", montar)
    monkeypatch.setattr(C, "conferir_pasta", lambda *a: conferidas.append(a))
    monkeypatch.setattr(L, "ler_pasta", lambda *a: {**dados, "atual": True})
    resultado = L.montar_atual(dados)
    assert resultado["resumo"]["atual"] and len(conferidas) == 1
    assert conferidas[0] == (tmp_path, "MA", COD, {"A"})


def test_api_publica_marca_data_sem_repassar_texto_da_fonte():
    from raiz.publica.apresentacao import fazenda

    atual = fazenda(
        {"car_conferido_em": QUANDO, "car_situacao": "conferido", "car_conferencia": "texto da fonte que não pode sair"}
    )
    assert atual["car_conferencia"] == "CAR conferido em 2026-11-13"
    assert atual["car_conferido_em"] == QUANDO and atual["car_situacao"] == "conferido"
    sem_data = fazenda({"car_conferido_em": "não é data", "car_conferencia": "texto não conferido"})
    assert sem_data["car_conferencia"] == "CAR a conferir" and sem_data["car_conferido_em"] is None


def test_lote_nao_admite_fazenda_sem_municipio_para_conferir(monkeypatch):
    from raiz import lote as L

    monkeypatch.setattr(
        L,
        "montar",
        lambda *a, **kw: {"tabela": pd.DataFrame({"cod_imovel": ["A"], "cod_ibge": [None], "papel": "titular"})},
    )
    with pytest.raises(C.ConferenciaPendente, match="sem município"):
        L.montar_atual({})


@pytest.mark.banco
def test_conferencia_chega_a_oferta_e_a_resposta_do_pedido(banco_url, tmp_path, monkeypatch):
    import shutil

    from sqlalchemy import create_engine

    from raiz.carga import carregar_municipio, depois_da_carga
    from raiz.executor import sincronizar
    from raiz.pedidos import oferta as O
    from raiz.pedidos import otimizador as Z
    from testes.conftest import AMOSTRA

    cod = 1504950
    pasta = tmp_path / "saida" / "PA"
    pasta.mkdir(parents=True)
    for arquivo in AMOSTRA.glob(f"*_{cod}.csv"):
        shutil.copyfile(arquivo, pasta / arquivo.name)
    t = pd.read_csv(pasta / f"imoveis_{cod}.csv", low_memory=False)
    geo = gpd.GeoDataFrame(t, geometry=[box(-47, -2, -46.99, -1.99)] * len(t), crs=4674)
    geo[["cod_imovel", "geometry"]].to_parquet(pasta / f"geo_{cod}.parquet")
    monkeypatch.setattr(sincronizar, "espelho_local", lambda: tmp_path)
    consultas = []

    def consultar(uf, codigos):
        consultas.append((uf, codigos))
        return geo[geo.cod_imovel.isin(codigos)].copy()

    monkeypatch.setattr(C, "consultar", consultar)
    monkeypatch.setattr(C, "recalcular", lambda *a: pytest.fail("desenho igual não refaz o município"))
    engine = create_engine(banco_url)
    try:
        with engine.begin() as con:
            carregar_municipio(con, pasta, cod)
        depois_da_carga(engine, cod, estrito=True)
        oferta = O.do_banco(engine, municipios=[cod])
        alvo = oferta.iloc[:1]
        C.conferir_banco(engine, alvo)
        atual = O.do_banco(engine, municipios=[cod]).set_index("cod_imovel").loc[alvo.cod_imovel.iloc[0]].to_dict()
        atual["cod_imovel"] = alvo.cod_imovel.iloc[0]
        resposta = Z.fazenda_do_lote(atual, "lote", "sem_contato")
        assert resposta["car_situacao"] == "conferido"
        assert resposta["car_conferencia"].startswith("CAR conferido em ")
        assert resposta["car_conferido_em"]
        assert consultas == [("PA", set(alvo.cod_imovel))]
    finally:
        engine.dispose()
