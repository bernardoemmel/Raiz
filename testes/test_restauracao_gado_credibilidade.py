import pytest

from raiz import restauracao_credibilidade as C
from raiz import restauracao_evidencias as E
from raiz import restauracao_gado as G


def test_embrapa_periodo_seco_nao_confunde_ingestao_ou_cabecas_com_ua():
    assert G.capacidade_seca(6250, 155)["ua_ha"] == pytest.approx(0.8146, abs=0.0001)
    assert G.capacidade_seca(1200, 30)["ua_ha"] == pytest.approx(1200 / (450 * 0.11 * 30))
    assert G.converter_cabecas(100, 225) == 50
    with pytest.raises(ValueError, match="oferta"):
        G.capacidade_seca(1200, 30, oferta_peso_vivo_dia=0.025)


def test_vcs3743_reproduz_2500_ua_tres_destinos_e_lotacoes():
    destinos = E.fontes()["gado_vcs3743"]["destinos"]
    assert len(destinos) == 3 and sum(d["ua_recebidas"] for d in destinos) == 2500
    for d, depois in zip(destinos, [1.23, 530 / 260, 2.25], strict=True):
        assert (d["ua_antes"] + d["ua_recebidas"]) / d["pasto_ha"] == pytest.approx(depois)
        assert depois < d["capacidade_regional_ua_ha"]


def test_menor_conjunto_e_fluxo_nao_contam_capacidade_duas_vezes():
    origens = [{"id": "O1", "ua": 60}, {"id": "O2", "ua": 60}]
    receptores = [{"id": i, "pasto_ha": 50, "ua_antes": 40, "capacidade_seca_ua_ha": 2} for i in ["R1", "R2", "R3"]]
    rotas = [
        {"origem": o["id"], "receptor": r["id"], "distancia_km": 20, "custo_por_ua": custo}
        for o in origens
        for r, custo in zip(receptores, [1, 2, 10], strict=True)
    ]
    p = G.planejar(origens, receptores, rotas)
    assert p["ua_atendidas"] == 120
    assert len(p["receptores"]) == 2
    assert {r["id"] for r in p["receptores"]} == {"R1", "R2"}
    assert all(r["lotacao_depois_ua_ha"] <= 2 for r in p["receptores"])
    assert not p["vazamento_pode_zerar"]  # plano não substitui comprovação.
    assert p["custo_total"] == 180


def test_insuficiencia_preserva_ua_sem_destino_e_area_regional_nao_e_credito():
    p = G.planejar(
        [{"id": "pequena", "ua": 0.5}],
        [{"id": "R", "pasto_ha": 1, "ua_antes": 0.8, "capacidade_seca_ua_ha": 1}],
        [{"origem": "pequena", "receptor": "R", "distancia_km": 1, "custo_por_ua": 1}],
    )
    assert p["ua_atendidas"] == 0.2
    assert p["ua_sem_destino"] == pytest.approx(0.3)
    assert not p["vazamento_pode_zerar"]
    s = G.sensibilidade_regional(100)
    assert s["area_deslocamento_ha"] == 12 and s["raio_km"] == 150
    assert s["desconto_creditos"] is None


PERFIL = {"bioma": "Amazônia", "metodo": "regeneracao_assistida", "unidade": "Mg/ha", "protocolo": "DAP>=5"}


def registros():
    return [
        {**PERFIL, "parcela_id": f"{i}-{j}", "bloco_id": str(i), "idade_anos": 5, "valor": i * 10 + j * 10}
        for i in (1, 2, 3, 4)
        for j in (0, 1)
    ]


def local(n=1):
    return [
        {**PERFIL, "parcela_id": f"local-{j}", "bloco_id": "fazenda", "idade_anos": 5, "valor": 80} for j in range(n)
    ]


def test_amostra_pequena_combina_com_coorte_e_divulga_peso_sem_replica_falsa():
    a = C.combinar(local(), registros(), perfil=PERFIL, idade_anos=5)
    b = C.combinar(local(100), registros(), perfil=PERFIL, idade_anos=5)
    assert 0 < a["peso_local"] < 1
    assert a["peso_local"] == b["peso_local"]  # 100 parcelas correlacionadas no mesmo bloco não são 100 sítios.
    assert a["media_coorte"] < a["media_combinada"] < a["media_local"]
    assert a["p10"] <= a["p50"] <= a["p90"]
    assert a["modelo_versao"] == C.versao()


def test_sem_inventario_peso_local_zero_e_protocolo_distinto_nao_entra():
    coorte = registros() + [{**registros()[0], "parcela_id": "incompativel", "protocolo": "DAP>=10", "valor": 1e6}]
    a = C.combinar([], coorte, perfil=PERFIL, idade_anos=5)
    assert a["peso_local"] == 0 and a["n_coorte"] == 8
    assert a["rotulo"] == "estimativa regional, não medida na fazenda"
    assert C.combinar([], coorte, perfil=PERFIL, idade_anos=15)["status"] == "pendente_coorte_comparavel"


def test_local_nao_e_contado_de_novo_na_coorte():
    r = C.combinar(local(), registros() + local(), perfil=PERFIL, idade_anos=5)
    assert r["n_coorte"] == 8


def test_destino_exige_documentos_revisados_e_plano_da_propria_origem():
    import json

    r = dict(id="R", pasto_ha=10, ua_antes=0, capacidade_seca_ua_ha=1)
    for chave in G.PROVAS:
        r[chave + "_confirmado"] = True
    args = ([dict(id="O", ua=1)], [r], [dict(origem="O", receptor="R", distancia_km=1, custo_por_ua=1)])
    assert not G.planejar(*args)["vazamento_pode_zerar"]
    r["evidencias"] = {k: dict(sha256="a" * 64, revisao_id="revisao-sintetica") for k in G.PROVAS}
    p = G.planejar(*args)
    assert p["vazamento_pode_zerar"]
    assert G.mitigacao_comprovada(dict(cod_imovel="O", vazamento_plano_json=json.dumps(p)))
    from raiz import restauracao as R
    from testes.test_restauracao import _linha

    li = _linha(cod_imovel="O", vazamento_plano_json=json.dumps(p))
    previsao, _ = R.calcular(li, R.cenario("central_r12"), financeiro_p50=True)
    assert previsao["vazamento_comprovado"]
    assert previsao["vazamento_plano_json"] == li["vazamento_plano_json"]
    assert G.mitigacao_comprovada({**li, **previsao})
    assert not G.mitigacao_comprovada(dict(cod_imovel="outra", vazamento_plano_json=json.dumps(p)))
    p["ua_atendidas"] = 100
    assert not G.mitigacao_comprovada(dict(cod_imovel="O", vazamento_plano_json=json.dumps(p)))
