"""Recortes explícitos e consulta privada sem cálculo municipal."""

import json

import pandas as pd
import pytest

from raiz import restauracao as R
from raiz import restauracao_catalogo as C
from raiz import restauracao_nacional as N
from raiz import restauracao_selecao as S
from raiz.pedidos.campos import CamposPedido
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
