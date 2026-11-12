"""Pedido de lote sem banco (docs/cena-alvo.md): a oferta da amostra, quanto existe na base, o que falta e o que
afrouxar, as 3 opções do solver com reserva, a forma do lote, a chance de aceite e o Pix de teste."""

import numpy as np
import pandas as pd
import pytest

from raiz.pedidos import aceite as A
from raiz.pedidos import oferta as O
from raiz.pedidos import otimizador as Z
from raiz.pedidos import pix
from raiz.pedidos.campos import CamposPedido, titulo
from testes.conftest import AMOSTRA

TODA_TERRA = ["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]


@pytest.fixture(scope="module")
def oferta():
    return O.da_pasta([(AMOSTRA, 1504950)])


def _pedido(**kw) -> CamposPedido:
    base = {"meta": {"tipo": "creditos", "valor": 1_000_000}, "onde": {"ufs": ["PA"], "biomas": ["Amazônia"]},
            "terra": TODA_TERRA}  # fmt: skip
    base.update(kw)
    return CamposPedido.model_validate(base)


def test_oferta_le_as_colunas_pelo_nome_e_nao_descarta_por_tamanho(oferta):
    im = pd.read_csv(AMOSTRA / "imoveis_1504950.csv")
    assert len(oferta) == len(im)  # todo imóvel com o cálculo entra na oferta
    assert oferta.pequena.sum() > 0.8 * len(oferta)  # Nova Esperança é quase toda de pequenas
    assert oferta.lon.notna().all() and oferta.local_aproximado.all()  # sem contorno na amostra: sede do município
    assert set(oferta.caminho.dropna()) <= set(TODA_TERRA)
    assert not oferta[oferta.caminho_terra == "publica_sem_destinacao"].elegivel.any()
    # coluna nova não atrapalha; coluna que falta vira o valor neutro
    li = {"cod_imovel": "X", "modo_restauracao": "plantio_total", "restauracao_area_ha": 10,
          "credito_liquido_tco2_ha_contrato_p50": 300, "caminho_terra": "privada_matricula", "coluna_nova": 1,
          "cod_municipio_ibge": 1504950, "uf": "PA"}  # fmt: skip
    o = O.de_linha(li)
    assert o["credito_p50"] == 3000 and o["caminho"] == "matricula_a_conferir" and o["elegivel"]
    assert O.de_linha({**li, "etapa_funil": "titulo_conferido"})["caminho"] == "matricula_conferida"
    assert O.de_linha({"cod_imovel": "Y"}) is None  # sem o valor para quem restaura, fica de fora da oferta


def test_um_milhao_no_para_fecha_com_pequenas_agrupadas(oferta):
    c = _pedido()
    b, ops, f = Z.opcoes(oferta, c)
    assert b["alcanca_meta"] and b["falta"] == 0 and b["creditos"]["p10"] < b["creditos"]["p50"] < b["creditos"]["p90"]
    assert {x["caminho"] for x in b["por_caminho"]} <= set(TODA_TERRA)
    assert [o["id"] for o in ops] == ["barata", "segura", "compacta"]
    for o in ops:
        assert o["alcanca_meta"] and o["creditos"]["p50"] >= 1_000_000, o["id"]
        assert o["creditos"]["p10"] < o["creditos"]["p50"] < o["creditos"]["p90"]
        assert o["pequenas"] >= 0.8 * o["fazendas"]  # pequenas entram, agrupadas
        lote = [i for i in o["itens"] if i["papel"] == "lote"]
        reserva = [i for i in o["itens"] if i["papel"] == "reserva"]
        assert len(lote) == o["fazendas"] and reserva
        r = sum(i["creditos"]["p50"] for i in reserva) / 1_000_000
        assert 0.1 <= r <= 0.35  # reserva de 10 a 20% da meta (a última fazenda passa um pouco)
        assert [m["ano"] for m in o["marcos"]] == [7, 12, 17, 22, 25]
        assert all(0 <= m["chance"] <= 1 for m in o["marcos"])
        assert o["custo_usd_credito"]["p10"] <= o["custo_usd_credito"]["p50"] <= o["custo_usd_credito"]["p90"]
        assert sum(x["fracao"] for x in o["mistura_terra"]) == pytest.approx(1, abs=0.01)
        assert o["pico_caixa_usd"] > 0 and o["multa_esperada_usd"] >= 0
        assert all(set(i) >= {"cod_imovel", "papel", "hectares", "metodo", "caminho", "interesse", "lon", "lat"}
                   for i in o["itens"])  # fmt: skip
        assert not any(k in str(i).lower() for i in o["itens"] for k in ("nome_", "cpf", "cnpj", "telefone"))
    barata, segura, compacta = ops
    assert barata["custo_usd_credito"]["p50"] <= segura["custo_usd_credito"]["p50"]
    # a segura tem menos risco: mais chance de cumprir os marcos e de aceite, ou terra menos arriscada
    risco = {o["id"]: Z._risco_usd(f[f.cod_imovel.isin([i["cod_imovel"] for i in o["itens"] if i["papel"] == "lote"])],
                                     np.full(o["fazendas"], 0.3), Z.premissas()).mean() for o in ops}  # fmt: skip
    assert risco["segura"] <= risco["barata"] + 1e-9
    # a compacta usa menos grupos de vizinhas
    g = Z.grupos(f, None)

    def n_grupos(o):
        lote = [i["cod_imovel"] for i in o["itens"] if i["papel"] == "lote"]
        return len(set(g[f.cod_imovel.isin(lote).to_numpy()]))

    n_grupos = {o["id"]: n_grupos(o) for o in ops}
    assert n_grupos["compacta"] <= n_grupos["barata"]


def test_pedido_impossivel_diz_quanto_falta_e_o_que_afrouxar(oferta):
    c = _pedido(terra=["matricula_conferida", "matricula_a_conferir"], meta={"tipo": "creditos", "valor": 5_000_000})
    b = Z.base(oferta, c)
    assert not b["alcanca_meta"] and b["falta"] > 0
    ganhos = [a["ganho"] for a in b["afrouxar"]]
    assert ganhos == sorted(ganhos, reverse=True) and ganhos[0] > 0
    assert b["afrouxar"][0]["campo"] == "terra" and "posse" in b["afrouxar"][0]["texto"]
    assert not any("embargo" in a["texto"] or "indígena" in a["texto"] for a in b["afrouxar"])  # exclusão não afrouxa
    _, ops, _ = Z.opcoes(oferta, c)
    assert ops and all(not o["alcanca_meta"] and o["falta"] > 0 for o in ops)
    # fora da base inteira: nenhuma opção
    b2, ops2, _ = Z.opcoes(oferta, _pedido(onde={"ufs": ["SP"]}))
    assert b2["fazendas"] == 0 and not ops2 and b2["falta"] == 1_000_000


def test_filtros_do_pedido(oferta):
    c = _pedido()
    todos = Z.filtrar(oferta, c)
    # reservada por outro cliente some de tudo (base, contas, opções)
    fora = set(todos.cod_imovel[:50])
    assert not Z.filtrar(oferta, c, fora=fora).cod_imovel.isin(fora).any()
    assert Z.base(oferta, c, fora=fora)["fazendas"] == len(todos) - 50
    # interesse do dono
    nv = {k: "interessado" for k in todos.cod_imovel[:30]} | {k: "recusou" for k in todos.cod_imovel[30:40]}
    assert len(Z.filtrar(oferta, _pedido(interesse="interessados"), nv)) == 30
    assert len(Z.filtrar(oferta, _pedido(interesse="com_aceite"), nv)) == 0
    assert not Z.filtrar(oferta, c, nv).cod_imovel.isin(list(todos.cod_imovel[30:40])).any()  # quem recusou sai
    # exclusões
    o2 = oferta.copy()
    o2.loc[o2.cod_imovel == todos.cod_imovel.iloc[0], "embargo"] = True
    assert todos.cod_imovel.iloc[0] not in set(Z.filtrar(o2, c).cod_imovel)
    assert todos.cod_imovel.iloc[0] in set(Z.filtrar(o2, _pedido(exclusoes=[])).cod_imovel)
    # raio em volta de uma planta e polígono desenhado no mapa (aqui todas na sede de Nova Esperança)
    perto = _pedido(onde={"ufs": ["PA"], "raio": {"lon": -46.97, "lat": -2.27, "km": 20}})
    longe = _pedido(onde={"ufs": ["PA"], "raio": {"lon": -50.0, "lat": -5.0, "km": 20}})
    assert len(Z.filtrar(oferta, perto)) == len(todos) and len(Z.filtrar(oferta, longe)) == 0
    pol = [(-47.1, -2.4), (-46.8, -2.4), (-46.8, -2.1), (-47.1, -2.1), (-47.1, -2.4)]
    assert len(Z.filtrar(oferta, _pedido(onde={"ufs": ["PA"], "poligono": pol}))) == len(todos)
    # métodos e custo máximo
    so_regen = Z.filtrar(oferta, _pedido(metodos=["regeneracao_assistida"]))
    assert so_regen.metodos.map(lambda m: "regeneracao_assistida" in m).all()
    barato = Z.filtrar(oferta, _pedido(dinheiro={"custo_max_usd_credito": 30}))
    assert (barato.custo_credito_usd <= 30).all() and len(barato) < len(todos)
    # meta em hectares soma a área para restaurar
    assert Z.quantidade(todos, "hectares").sum() == pytest.approx(todos.area_ha.sum())


def test_forma_do_lote_e_mitigacao(oferta):
    c = _pedido(forma={"max_donos": 40})
    f = Z.filtrar(oferta, c).reset_index(drop=True)
    ch = A.chances(f)
    r = Z.resolver(f, c, "barata", ch)
    assert len(r["sel"]) <= 40
    # tudo num círculo do diâmetro pedido: um grupo só (sem contorno, o lote de vizinhas já calculado)
    c2 = _pedido(forma={"distancia_max_km": 15}, meta={"tipo": "creditos", "valor": 300_000})
    f2 = Z.filtrar(oferta, c2).reset_index(drop=True)
    r2 = Z.resolver(f2, c2, "barata", A.chances(f2))
    assert len(set(r2["grupos"][r2["sel"]])) == 1
    # fazenda de mitigação no grupo: vazamento zero, o grupo rende mais (compacta)
    f3 = f.copy()
    g = Z.grupos(f3, None)
    alvo = g[0]
    f3.loc[g == alvo, "mitigacao"] = False
    f3.loc[f3.index[g == alvo][0], "mitigacao"] = True
    r3 = Z.resolver(f3, c, "compacta", A.chances(f3))
    assert r3["mitigacao"][g == alvo].all() and not r3["mitigacao"][g != alvo].any()


def test_chance_de_aceite_aprende_com_os_contatos(oferta):
    f = Z.filtrar(oferta, _pedido()).reset_index(drop=True).head(20)
    base = A.chances(f)
    assert ((0 < base) & (base < 1)).all()
    k = A.perfil(f.iloc[0].to_dict(), "participacao")
    muitos_sim = A.chances(f, historico={k: (40, 5)})
    muitos_nao = A.chances(f, historico={k: (0, 40)})
    assert muitos_sim[0] > base[0] > muitos_nao[0]
    nv = {f.cod_imovel[1]: "aceite_fase1", f.cod_imovel[2]: "recusou", f.cod_imovel[3]: "sem_resposta"}
    ch = A.chances(f, niveis=nv)
    assert ch[1] == 0.9 and ch[2] == 0 and ch[3] < base[3]
    # pequena tem mais chance que grande (premissa), duas fases mais que só parte do crédito
    li = f.iloc[0].to_dict()
    assert A.a_priori({**li, "ha": 20}, "participacao") > A.a_priori({**li, "ha": 5000}, "participacao")
    assert A.a_priori(li, "duas_fases") > A.a_priori(li, "participacao")


def test_campos_do_pedido_e_titulo():
    c = CamposPedido()
    assert c.meta.valor == 1_000_000 and c.cronograma == "profloresta" and c.onde.biomas == ["Amazônia"]
    assert set(c.exclusoes) == {"embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono"}
    assert c.reserva_dias == 60
    assert titulo(_pedido()) == "1 milhão de créditos em PA"
    with pytest.raises(ValueError):
        CamposPedido.model_validate({"meta": {"valor": -1}})
    with pytest.raises(ValueError):
        CamposPedido.model_validate({"terra": []})


def test_marcos_proprios_e_cronograma_livre(oferta):
    c = _pedido(cronograma="proprio", marcos_proprios=[{"ano": 10, "fracao": 0.2}, {"ano": 25, "fracao": 1.0}])
    _, ops, _ = Z.opcoes(oferta, c)
    m = ops[0]["marcos"]
    assert [x["ano"] for x in m] == [10, 25] and all(0 <= x["chance"] <= 1 for x in m)
    _, ops2, _ = Z.opcoes(oferta, _pedido(cronograma="livre"))
    assert ops2[0]["marcos"] == []


def test_pix_de_teste_e_aviso_de_pagamento(monkeypatch):
    monkeypatch.delenv("RAIZ_ABACATEPAY_CHAVE", raising=False)
    c = pix.criar(1234.5, "Reserva Raíz", 3600)
    assert c.modo == "teste" and c.externo_id.startswith("teste_") and "NAO-E-CODIGO-DE-BANCO" in c.copia_e_cola
    assert pix.conferir(c.externo_id) == "pendente"
    assert pix.id_do_webhook({"event": "billing.paid", "data": {"pixQrCode": {"id": "pix_1"}}}) == "pix_1"
    assert pix.id_do_webhook({"event": "billing.paid", "data": {"id": "bill_2"}}) == "bill_2"
    assert pix.id_do_webhook({"event": "outro"}) is None

    class Resp:
        def __init__(self, d):
            self.d = d

        def raise_for_status(self):
            return None

        def json(self):
            return self.d

    class Cli:
        def post(self, url, headers, json):
            assert url.endswith("/pixQrCode/create") and json["amount"] == 123450 and headers["Authorization"]
            return Resp({"data": {"id": "pix_x", "brCode": "000201...", "devMode": True,
                                  "expiresAt": "2026-11-13T12:00:00.000Z"}})  # fmt: skip

        def get(self, url, params, headers):
            return Resp({"data": {"status": "PAID"}})

    monkeypatch.setenv("RAIZ_ABACATEPAY_CHAVE", "chave-de-teste")
    c2 = pix.criar(1234.5, "Reserva Raíz com nome comprido demais para a AbacatePay", 3600, cliente=Cli())
    assert c2.externo_id == "pix_x" and c2.modo == "teste" and c2.copia_e_cola == "000201..."
    assert pix.conferir("pix_x", cliente=Cli()) == "paga"


def test_otimizador_prefere_regeneracao_quando_o_preco_nao_paga_o_plantio():
    """Plantio com custo nivelado menor mas preço de equilíbrio acima do preço do pedido fica para trás da
    regeneração; quando a regeneração não basta, o lote fecha com o plantio e avisa."""
    linhas = []
    for i in range(12):
        regen = i < 6
        linhas.append(O.de_linha({
            "cod_imovel": f"PA-{i}", "uf": "PA", "cod_municipio_ibge": 1504950, "bioma": "Amazônia",
            "modo_restauracao": "regeneracao_assistida" if regen else "plantio_total",
            "restauracao_area_ha": 100, "credito_liquido_tco2_ha_contrato_p50": 200,
            "credito_liquido_tco2_ha_contrato_p10": 150, "credito_liquido_tco2_ha_contrato_p90": 260,
            "custo_credito_usd": 30 if regen else 25, "preco_equilibrio_usd_t": 48 if regen else 92,
            "caminho_terra": "privada_matricula", "risco_terra": "medio",
        }))  # fmt: skip
    oferta = O.tabela(linhas)
    c = _pedido(meta={"tipo": "creditos", "valor": 100_000})
    _, ops, _ = Z.opcoes(oferta, c)
    for o in ops:
        lote = {i["cod_imovel"] for i in o["itens"] if i["papel"] == "lote"}
        assert lote <= {f"PA-{i}" for i in range(6)}, o["id"]  # só regeneração: 5 x 20 mil = 100 mil
        assert o["abaixo_equilibrio"]["fazendas"] == 0 and o["abaixo_equilibrio"]["aviso"] is None
    # meta maior que a regeneração: entra plantio, e o aviso diz que só fecha com ele
    c2 = _pedido(meta={"tipo": "creditos", "valor": 160_000})
    _, ops2, _ = Z.opcoes(oferta, c2)
    ab = ops2[0]["abaixo_equilibrio"]
    assert ops2[0]["alcanca_meta"] and ab["so_fecha_com_elas"] and ab["fazendas"] >= 2
    assert ab["metodos"] == {"plantio_total": ab["fazendas"]} and ab["preco_equilibrio_medio_usd"] == 92
    assert ab["base_que_se_paga"] == 120_000 and "só fecha com plantio abaixo do equilíbrio" in ab["aviso"]
    # preço que paga o plantio: sem aviso, e o custo nivelado volta a mandar
    c3 = _pedido(meta={"tipo": "creditos", "valor": 100_000}, dinheiro={"preco_venda_usd": 100})
    _, ops3, _ = Z.opcoes(oferta, c3)
    assert ops3[0]["abaixo_equilibrio"]["fazendas"] == 0
    assert {i["cod_imovel"] for i in ops3[0]["itens"] if i["papel"] == "lote"} <= {f"PA-{i}" for i in range(6, 12)}
