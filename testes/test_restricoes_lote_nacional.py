"""Restrições nacionais (SICAR completo, SIGMINE, autos do Ibama, Lista Suja) no lote nacional: índice, filtro,
resumo agregado e rodada que completa restricoes_<mun>.csv. Só dados sintéticos, sem documento."""

import pandas as pd

from raiz import restauracao_catalogo as C
from raiz import restauracao_nacional as N
from raiz import restauracao_selecao as S
from raiz.pedidos.campos import CamposPedido
from testes.test_restauracao_catalogo import criar_fonte, indexar


def _restricoes(pasta, cod, status, motivos):
    ids = [f"PA-{cod}-SINTETICO{i:04d}" for i in range(len(status))]
    pd.DataFrame(
        {
            "cod_imovel": ids,
            "restricao_nacional": status,
            "restricao_motivos": motivos,
            "restricoes_versao": "restricoes-teste",
        }
    ).to_csv(pasta / f"restricoes_{cod}.csv", index=False)
    return ids


def _rodar(cat, tmp_path, uf="PA", saida="saida"):
    return N.montar_tres_opcoes(
        cat,
        CamposPedido(meta={"valor": 20}, cronograma="livre"),
        N.normalizar_recorte(ufs=[uf]),
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / saida,
        limites=S.LimitesSelecao(2, 10, 1),
    )


def test_regra_da_restricao_so_existe_com_a_camada():
    pedido = CamposPedido(meta={"valor": 20})
    sem = [t for t, _ in N._regras_pedido(pedido, "m", "c", False, frozenset())]
    com = [t for t, _ in N._regras_pedido(pedido, "m", "c", False, frozenset({"restricao_exclusao"}))]
    assert not any("Restrição nacional" in t for t in sem)
    assert any("Restrição nacional" in t for t in com)


def test_exclusao_sai_ressalva_fica_marcada_e_resumo_so_agrega(tmp_path):
    criar_fonte(tmp_path / "pa", n=4)
    ids = _restricoes(
        tmp_path / "pa",
        1500602,
        ["exclusao", "ressalva", "livre", "nao_verificado"],
        ["lista_suja", "ibama_auto|car_sobreposto", None, None],
    )
    destino = tmp_path / "indice"
    p = indexar(tmp_path / "pa", destino)
    t = pd.read_parquet(destino / p["arquivos"]["oferta"]["caminho"]).set_index("cod_imovel")
    assert t.loc[ids[0], "restricao_exclusao"] and t.loc[ids[0], "restricao_motivos"] == "lista_suja"
    assert t.loc[ids[1], "restricao_ressalva"] and not t.loc[ids[1], "restricao_exclusao"]
    assert t.loc[ids[2], "restricao_exclusao"] == False  # noqa: E712 (livre verificado é False, não nulo)
    assert pd.isna(t.loc[ids[3], "restricao_exclusao"]) and t.loc[ids[3], "restricao_nacional"] == "nao_verificado"

    cat = C.consolidar_catalogo([p], destino, municipios_esperados={"PA": [1500602]})
    r = _rodar(cat, tmp_path)
    rn = r["restricoes_nacionais"]
    assert rn["situacao"] == "parcial" and rn["nao_verificadas"] == 1
    assert rn["excluidas"] == 1 and rn["ressalvas"] == 1
    assert rn["motivos"] == {"car_sobreposto": 1, "ibama_auto": 1, "lista_suja": 1}
    assert "PA-" not in str(rn)  # agregado: nenhum CAR no resumo
    for op in r["opcoes"].values():
        sel = set(pd.read_parquet(op["tabela"]["caminho"]).cod_imovel)
        assert ids[0] not in sel
        assert op["marcadas_restricao_ressalva"] == int(ids[1] in sel)
        assert op["restricao_nao_verificadas"] == int(ids[3] in sel)
    d = pd.read_parquet(r["auditoria"]["caminho"]).set_index("cod_imovel")
    assert "Restrição nacional" in d.loc[ids[0], "criterio_texto"]

    from raiz.restauracao_nacional_rodada import resumo_consulta

    assert resumo_consulta(r)["restricoes_nacionais"]["excluidas"] == 1


def test_sem_arquivo_fica_nao_verificada_nunca_livre(tmp_path):
    criar_fonte(tmp_path / "to", uf="TO", cod=1721000, n=2)
    destino = tmp_path / "indice"
    p = indexar(tmp_path / "to", destino, uf="TO", cod=1721000)
    t = pd.read_parquet(destino / p["arquivos"]["oferta"]["caminho"])
    assert t.restricao_exclusao.isna().all() and set(t.restricao_nacional) == {"nao_verificado"}
    cat = C.consolidar_catalogo([p], destino, municipios_esperados={"TO": [1721000]})
    assert _rodar(cat, tmp_path, uf="TO")["restricoes_nacionais"]["situacao"] == "nao_verificada"


def test_rodada_completa_restricoes_que_faltam_e_refaz_as_velhas(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    from raiz import restauracao_nacional_rodada as RN
    from raiz.restricoes import status as RS

    fonte = tmp_path / "PA"
    criar_fonte(fonte, n=2)
    criar_fonte(fonte, cod=1500107, n=1)
    ids = [f"PA-1500602-SINTETICO{i:04d}" for i in range(2)]
    gpd.GeoDataFrame(
        {"cod_imovel": ids}, geometry=[box(-47.0, -3.0, -46.99, -2.99), box(-46.0, -3.0, -45.99, -2.99)], crs=4674
    ).to_parquet(fonte / "geo_1500602.parquet")

    class Camadas:
        pasta = tmp_path / "camadas"

    chamadas = []

    def escrever(pasta, cod, camadas=None):
        chamadas.append(cod)
        pd.DataFrame(
            {"cod_imovel": ids, "restricao_nacional": ["ressalva", "livre"], "restricoes_versao": versao}
        ).to_csv(pasta / f"restricoes_{cod}.csv", index=False)

    monkeypatch.setattr(RS, "assinatura", lambda pasta=None: "abc123")
    versao = f"{RS.versao()}+abc123"
    monkeypatch.setattr(RS, "escrever_municipio", escrever)
    r = RN.completar_restricoes(fonte, camadas=Camadas())
    assert r["refeitos"] == 1 and r["sem_geometria"] == 1 and chamadas == [1500602]  # 1500107 sem polígono
    assert RN.completar_restricoes(fonte, camadas=Camadas())["em_dia"] == 1 and chamadas == [1500602]
    monkeypatch.setattr(RS, "assinatura", lambda pasta=None: None)
    assert RN.completar_restricoes(fonte, camadas=Camadas())["situacao"] == "sem_coleta"
