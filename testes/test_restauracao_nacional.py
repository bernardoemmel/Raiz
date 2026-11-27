"""Recortes explícitos e consulta privada sem cálculo municipal."""

import json

import pandas as pd
import pytest

from raiz import restauracao as R
from raiz.pedidos.campos import CamposPedido
from raiz.restauracao import catalogo as C
from raiz.restauracao import nacional as N
from raiz.restauracao import selecao as S
from testes.test_restauracao_catalogo import criar_fonte, indexar


@pytest.fixture
def catalogo(tmp_path):
    destino = tmp_path / "indice"
    criar_fonte(tmp_path / "pa", n=4)
    criar_fonte(tmp_path / "to", uf="TO", cod=1721000, n=2, bioma="Cerrado")
    ps = [indexar(tmp_path / "pa", destino), indexar(tmp_path / "to", destino, uf="TO", cod=1721000)]
    return C.consolidar_catalogo(ps, destino, municipios_esperados={"PA": [1500602, 1500107], "TO": [1721000]})


def rodar(catalogo, tmp_path, recorte, **kwargs):
    return N.montar_tres_opcoes(
        catalogo,
        CamposPedido(meta={"valor": 20}, cronograma="livre"),
        recorte,
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / "saida",
        limites=S.LimitesSelecao(2, 10, 1),
        **kwargs,
    )


def test_brasil_nao_herda_amazonia_e_preserva_pequenas(catalogo, tmp_path, monkeypatch):
    def proibido(*a, **kw):
        raise AssertionError("Pedido não pode recalcular municípios")

    monkeypatch.setattr(R, "calcular_municipio", proibido)
    r = rodar(catalogo, tmp_path, N.normalizar_recorte(brasil=True))
    assert r["cobertura"]["imoveis"] == 6 and r["cobertura"]["pequenas"] == 6
    assert not r["cobertura"]["cobertura_completa"]
    assert "AC" in r["cobertura"]["ufs_sem_catalogo"]
    assert r["cobertura"]["municipios_faltantes_identificados"] == [1500107]
    assert r["pedido"]["onde"]["biomas"] == []
    assert set(r["opcoes"]) == {"barata", "segura", "compacta"}
    for op in r["opcoes"].values():
        t = pd.read_parquet(op["tabela"]["caminho"])
        assert op["fecha_meta"] and t.cod_imovel.is_unique and t.pequena.all()
        assert (t.tir_p50 > t.tir_p90).all()
        assert "preco_minimo_tir_15_projeto_usd_t" in t
    d = pd.read_parquet(r["auditoria"]["caminho"])
    assert len(d) == 6 and d.revisao_humana_disponivel.all() and d.criterio_texto.str.len().min() > 30
    assert r["acesso"] == "privado"
    assert not r["cronograma_contratual_validado"]


def test_uf_inteira_e_bioma_sem_filtro_oculto(catalogo, tmp_path):
    r = rodar(catalogo, tmp_path, N.normalizar_recorte(ufs=["TO"]))
    assert r["cobertura"]["imoveis"] == 2 and r["pedido"]["onde"]["biomas"] == []
    assert r["cobertura"]["cobertura_completa"]
    r = rodar(catalogo, tmp_path, N.normalizar_recorte(biomas=["Cerrado"]))
    assert r["cobertura"]["imoveis"] == 2
    r = rodar(catalogo, tmp_path, N.normalizar_recorte(ufs=["PA"], biomas=["Cerrado"]))
    assert r["cobertura"]["imoveis"] == 0
    assert all(o["fazendas"] == 0 for o in r["opcoes"].values())


def test_recorte_precisa_ser_explicito():
    with pytest.raises(ValueError, match="explicitamente"):
        N.normalizar_recorte()
    with pytest.raises(ValueError, match="esconder filtros"):
        N.normalizar_recorte(brasil=True, ufs=["PA"])
    with pytest.raises(ValueError, match="inválido"):
        N.normalizar_recorte(ufs=["XX"])


def test_cache_do_pedido_e_catalogo_imutavel(catalogo, tmp_path):
    r = rodar(catalogo, tmp_path, N.normalizar_recorte(ufs=["PA"]))
    assert rodar(catalogo, tmp_path, N.normalizar_recorte(ufs=["PA"])) == json.loads(json.dumps(r))


def test_terra_pendente_permanece_mesmo_sem_lote_e_sem_previsao(tmp_path):
    fonte, indice = tmp_path / "fonte", tmp_path / "indice"
    criar_fonte(fonte, uf="BA", cod=2927408, n=2, modelo="historico")
    terra = pd.read_csv(fonte / "terra_2927408.csv")
    terra["caminho_terra"] = "posse_em_titulacao"
    terra.to_csv(fonte / "terra_2927408.csv", index=False)
    dev = pd.read_csv(fonte / "desenvolvedor_2927408.csv")
    dev.iloc[:1].to_csv(fonte / "desenvolvedor_2927408.csv", index=False)
    particao = C.indexar_municipio(fonte, "BA", 2927408, indice, modelo="modelo-teste", cenario="central_r11")
    cat = C.consolidar_catalogo([particao], indice, municipios_esperados={"BA": [2927408]})
    r = rodar(cat, tmp_path, N.normalizar_recorte(ufs=["BA"]))
    assert all(o["fazendas"] == 0 for o in r["opcoes"].values())
    quadro = r["quadro_terra"]
    assert all(i["caminho_terra"] == "posse_em_titulacao" for i in quadro)
    assert sum(i["fazendas"] for i in quadro) == 2
    assert sum(i["pequenas"] for i in quadro) == 2
    antigo = next(i for i in quadro if i["modelo_origem"] == "historico")
    assert antigo["soma_creditos_p50"] == 20
    assert antigo["situacao_previsao"] == "modelo_incompativel"
    ausente = next(i for i in quadro if i["situacao_previsao"] == "previsao_ausente")
    assert ausente["soma_creditos_p50"] is None
    assert ausente["fazendas_sem_creditos_estimados"] == 1
    assert all(i["revisao_humana_disponivel"] and not i["habilita_venda"] for i in quadro)


def test_exclusao_guarda_criterio_financeiro_que_falhou(catalogo, tmp_path):
    pedido = CamposPedido(meta={"valor": 20}, cronograma="livre", dinheiro={"custo_max_usd_credito": 1})
    r = N.montar_tres_opcoes(
        catalogo,
        pedido,
        N.normalizar_recorte(brasil=True),
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / "consulta",
    )
    t = pd.read_parquet(r["auditoria"]["caminho"])
    assert t.criterio_texto.str.contains("Custo acima do limite ou ausente").all()
    assert not t.criterio_texto.str.contains("Versão financeira diferente").any()
    assert t.revisao_humana_disponivel.all()


def test_marcos_e_reserva_nao_se_reduzem_ao_volume_contratado():
    pedido = CamposPedido(meta={"valor": 1000000})
    efetivo, contrato, r, c = N.preparar_contrato(pedido, R.versao(), "central_r11")
    assert efetivo.meta.valor == R.contrato_para_marcos(1000000, c, r)
    assert contrato["necessario_com_reserva"] > contrato["necessario_p50"] >= 1000000
    assert pedido.meta.valor == 1000000
    with pytest.raises(ValueError, match="mesma versão"):
        N.preparar_contrato(pedido, "historica", "central_r11")


def test_pedido_parcial_herda_cenario_sem_trocar_preco_explicito():
    pedido = CamposPedido.model_validate({"meta": {"valor": 1000000}, "dinheiro": {"tir_min": 12}})
    antes = pedido.model_dump()
    efetivo, _, _, c = N.preparar_contrato(pedido, R.versao(), "central_r12")
    assert efetivo.dinheiro.preco_venda_usd == c["preco_usd_t"] == 59.2
    assert efetivo.dinheiro.tir_min == 12
    assert pedido.model_dump() == antes
    explicito = CamposPedido(dinheiro={"preco_venda_usd": 55})
    with pytest.raises(ValueError, match="reavaliar a oferta"):
        N.preparar_contrato(explicito, R.versao(), "central_r12")


def _catalogo_posse(tmp_path):
    fonte, indice = tmp_path / "fonte_ba", tmp_path / "indice_ba"
    criar_fonte(fonte, uf="BA", cod=2927408, n=3, bioma="Caatinga")
    terra = pd.read_csv(fonte / "terra_2927408.csv")
    terra["caminho_terra"] = "posse_em_titulacao"
    terra.to_csv(fonte / "terra_2927408.csv", index=False)
    particao = C.indexar_municipio(fonte, "BA", 2927408, indice, modelo="modelo-teste", cenario="central_r11")
    return C.consolidar_catalogo([particao], indice, municipios_esperados={"BA": [2927408]})


def test_posse_em_titulacao_aparece_como_terra_em_espera_sem_mudar_o_pedido(tmp_path):
    cat = _catalogo_posse(tmp_path)
    r = rodar(cat, tmp_path, N.normalizar_recorte(ufs=["BA"]))
    assert all(o["fazendas"] == 0 for o in r["opcoes"].values())  # o pedido padrão exclui a terra em espera
    espera = r["terra_em_espera"]
    assert not espera["incluida_no_pedido"]
    assert espera["fazendas"] == 3 and espera["pequenas"] == 3 and espera["soma_creditos_p50"] > 0
    assert espera["grupos"][0]["caminho"] == "posse_em_titulacao" and not espera["grupos"][0]["habilita_venda"]
    assert "posse_em_titulacao" in espera["como_incluir"]
    assert r["pedido"]["terra"] == CamposPedido(meta={"valor": 20}).terra  # pedido do cliente intacto
    assert r["sobreposicao"]["situacao"] == "nao_verificada"
    assert all(o["sobreposicao_situacao"] == "nao_verificada" for o in r["opcoes"].values())


def test_cliente_que_pede_posse_recebe_o_lote_e_a_espera_some(tmp_path):
    cat = _catalogo_posse(tmp_path)
    pedido = CamposPedido(meta={"valor": 20}, cronograma="livre", terra=["posse_em_titulacao"])
    r = N.montar_tres_opcoes(
        cat,
        pedido,
        N.normalizar_recorte(ufs=["BA"]),
        modelo="modelo-teste",
        cenario="central_r11",
        destino=tmp_path / "saida2",
        limites=S.LimitesSelecao(2, 10, 1),
    )
    assert r["terra_em_espera"]["incluida_no_pedido"] is False or r["terra_em_espera"]["grupos"] == []
    assert any(o["fazendas"] > 0 for o in r["opcoes"].values())


def test_camada_ja_comprometida_vira_regra_so_quando_existe():
    pedido = CamposPedido(meta={"valor": 20})
    sem = [t for t, _ in N._regras_pedido(pedido, "m", "c", False)]
    com = [t for t, _ in N._regras_pedido(pedido, "m", "c", False, True)]
    assert "Terra já comprometida com outro projeto ou contrato" in com and set(sem) < set(com)


def test_amazonia_primeiro_e_brasil_por_ultimo():
    ordem = N.ordem_recortes(["Brasil", "SP", "Cerrado", "PA", "BA", "Amazônia", "AC", "Pampa", "MA"])
    assert ordem[0] == "Amazônia" and ordem[-1] == "Brasil"
    assert ordem.index("AC") < ordem.index("MA") < ordem.index("PA") < ordem.index("BA") < ordem.index("Cerrado")


def _comprometida(pasta, cod, status):
    ids = [f"PA-{cod}-SINTETICO{i:04d}" for i in range(len(status))]
    pd.DataFrame(
        {
            "cod_imovel": ids,
            "status_sobreposicao": status,
            "sobreposicao_ha": [
                1.5 if s == "ja_comprometida" else (0.0 if s != "nao_verificado" else None) for s in status
            ],  # fmt: skip
            "projeto_id": ["VCS4681" if s == "ja_comprometida" else None for s in status],
            "comprometida_versao": "comprometida-teste",
        }
    ).to_csv(pasta / f"comprometida_{cod}.csv", index=False)
    return ids


def test_lote_tira_ja_comprometida_e_marca_risco_sem_apagar_pequenas(tmp_path):
    criar_fonte(tmp_path / "pa", n=4)
    ids = _comprometida(tmp_path / "pa", 1500602, ["ja_comprometida", "risco_sobreposicao", "livre", "livre"])
    destino = tmp_path / "indice"
    p = indexar(tmp_path / "pa", destino)
    t = pd.read_parquet(destino / p["arquivos"]["oferta"]["caminho"]).set_index("cod_imovel")
    assert t.loc[ids[0], "ja_comprometida"] and t.loc[ids[0], "sobreposicao_projetos"] == "VCS4681"
    assert t.loc[ids[1], "risco_sobreposicao"] and not t.loc[ids[1], "ja_comprometida"]
    cat = C.consolidar_catalogo([p], destino, municipios_esperados={"PA": [1500602]})
    r = rodar(cat, tmp_path, N.normalizar_recorte(ufs=["PA"]))
    assert r["sobreposicao"]["situacao"] == "verificada"
    assert r["sobreposicao"]["excluidas_ja_comprometidas"] == 1
    for op in r["opcoes"].values():
        sel = pd.read_parquet(op["tabela"]["caminho"])
        assert ids[0] not in set(sel.cod_imovel)
        assert op["sobreposicao_situacao"] == "verificada" and op["sobreposicao_nao_verificadas"] == 0
        assert op["marcadas_risco_sobreposicao"] == int(ids[1] in set(sel.cod_imovel))
    d = pd.read_parquet(r["auditoria"]["caminho"]).set_index("cod_imovel")
    assert "já comprometida" in d.loc[ids[0], "criterio_texto"]


def test_sem_arquivo_ou_nao_verificado_fica_nulo_e_consulta_diz_parcial(tmp_path):
    criar_fonte(tmp_path / "pa", n=3)
    ids = _comprometida(tmp_path / "pa", 1500602, ["livre", "nao_verificado", "livre"])
    destino = tmp_path / "indice"
    p = indexar(tmp_path / "pa", destino)
    t = pd.read_parquet(destino / p["arquivos"]["oferta"]["caminho"]).set_index("cod_imovel")
    assert pd.isna(t.loc[ids[1], "ja_comprometida"]) and t.loc[ids[1], "status_sobreposicao"] == "nao_verificado"
    assert t.loc[ids[0], "ja_comprometida"] == False  # noqa: E712 (livre verificado é False, não nulo)
    cat = C.consolidar_catalogo([p], destino, municipios_esperados={"PA": [1500602]})
    r = rodar(cat, tmp_path, N.normalizar_recorte(ufs=["PA"]))
    assert r["sobreposicao"]["situacao"] == "parcial" and r["sobreposicao"]["nao_verificadas"] == 1
    # Sem nenhum comprometida_<mun>.csv: coluna existe, mas tudo nulo = não verificada (nunca terra livre).
    criar_fonte(tmp_path / "to", uf="TO", cod=1721000, n=2)
    destino2 = tmp_path / "indice2"
    p2 = indexar(tmp_path / "to", destino2, uf="TO", cod=1721000)
    cat2 = C.consolidar_catalogo([p2], destino2, municipios_esperados={"TO": [1721000]})
    r2 = N.montar_tres_opcoes(
        cat2, CamposPedido(meta={"valor": 20}, cronograma="livre"), N.normalizar_recorte(ufs=["TO"]),
        modelo="modelo-teste", cenario="central_r11", destino=tmp_path / "saida2", limites=S.LimitesSelecao(2, 10, 1),
    )  # fmt: skip
    assert r2["sobreposicao"]["situacao"] == "nao_verificada"


def test_rodada_completa_comprometida_que_falta_e_refaz_a_velha(tmp_path, monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    from raiz.comprometida import status as ST
    from raiz.restauracao import nacional_rodada as RN

    fonte = tmp_path / "PA"
    criar_fonte(fonte, n=2)
    criar_fonte(fonte, cod=1500107, n=1)
    ids = [f"PA-1500602-SINTETICO{i:04d}" for i in range(2)]
    gpd.GeoDataFrame(
        {"cod_imovel": ids}, geometry=[box(-47.0, -3.0, -46.99, -2.99), box(-46.0, -3.0, -45.99, -2.99)], crs=4674
    ).to_parquet(fonte / "geo_1500602.parquet")
    limites = gpd.GeoDataFrame(
        {"fonte_id": ["verra"], "objeto_id": ["VCS4681"], "registro": ["verra"], "tipo": ["projeto_carbono"],
         "situacao": ["ativo"], "certeza": ["limite_oficial"], "uf": ["PA"], "fonte_url": [None],
         "data_referencia": [None], "observado_em": ["2026-11-17"], "inicio": [None], "fim": [None]},
        geometry=[box(-47.1, -3.1, -46.9, -2.9)], crs=4326,
    )  # fmt: skip
    cobertura = [{"fonte_id": "verra", "estado": "consultado", "uf": None, "consultado_em": "2026-11-17",
                  "bbox": None}]  # fmt: skip
    monkeypatch.setattr(ST, "assinatura", lambda pasta=None: "abc123")
    monkeypatch.setattr(ST, "avaliar_imovel", lambda g, c, ha, cands, cob, hoje: {
        "cod_imovel": c, "status_sobreposicao": "ja_comprometida" if cands else "livre",
        "projeto_id": "VCS4681" if cands else None})  # fmt: skip
    r = RN.completar_comprometida(fonte, limites=limites, cobertura=cobertura)
    assert r["refeitos"] == 1 and r["sem_geometria"] == 1  # 1500107 sem polígono fica não verificado
    t = pd.read_csv(fonte / "comprometida_1500602.csv").set_index("cod_imovel")
    assert t.loc[ids[0], "status_sobreposicao"] == "ja_comprometida" and t.loc[ids[1], "status_sobreposicao"] == "livre"
    assert RN.completar_comprometida(fonte, limites=limites, cobertura=cobertura)["em_dia"] == 1
    assert RN.completar_comprometida(fonte, limites=None, cobertura=[])["situacao"] == "sem_limites"
