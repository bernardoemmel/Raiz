"""Filtros nacionais, soma anterior à paginação, dados ausentes e reserva privada."""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from raiz.busca import FiltrosProspeccao, buscar_prospeccao


@pytest.mark.parametrize(
    "filtro",
    [
        {"uf": "ZZ"},
        {"bioma": "desconhecido"},
        {"q": "a"},
        {"area_min_ha": -1},
        {"area_max_ha": float("nan")},
        {"credito_min": float("inf")},
        {"area_min_ha": 20, "area_max_ha": 10},
        {"credito_min": 10, "credito_max": 1},
        {"risco": "livre"},
        {"situacao_terra": "regular"},
        {"cod_ibge": 123},
        {"campo_inventado": 5},
    ],
)
def test_filtros_invalidos_nao_chegam_ao_banco(filtro):
    with pytest.raises(ValidationError):
        FiltrosProspeccao.model_validate(filtro)


def test_filtros_normalizados_e_sem_corte_implicito():
    f = FiltrosProspeccao(uf=" pa ", bioma="amazonia", q="  São Félix  ")
    assert f.uf == "PA" and f.bioma == "Amazônia" and f.q == "São Félix"
    assert f.area_min_ha is None and f.credito_min is None and f.risco is None


@pytest.fixture
def base(banco_url):
    engine = create_engine(banco_url)
    with engine.begin() as con:
        con.execute(text("truncate funil.rodada, funil.vigente, negocio.cliente cascade"))
        clientes = [
            con.execute(
                text("""insert into negocio.cliente (rotulo, token_hmac)
                values ('Cliente de teste', :token) returning id"""),
                {"token": f"busca-{n}"},
            ).scalar_one()
            for n in range(2)
        ]
        rodadas = {}
        for uf, mun in (("PA", 1507300), ("RS", 4314902)):
            rodadas[uf] = con.execute(
                text("""insert into funil.rodada
                (tipo,uf,cod_municipio,origem,arquivos,hash_entradas,motor_versao,regras_versao,data_corte)
                values ('municipio', :uf, :mun, 'teste', '{}', :hash, 'teste', 'teste', '2026-11-12') returning id
                """),
                {"uf": uf, "mun": mun, "hash": f"busca-{uf}"},
            ).scalar_one()
        codigos = []
        for n, (uf, ha, mf, bioma, caminho, risco, area, credito) in enumerate(
            (
                ("PA", 1, 0.01, "Amazônia", "posse_em_titulacao", "alto", 0.5, 100),
                ("PA", 10, 0.1, "Amazônia", "privada_matricula", "baixo", 5, 200),
                ("PA", 5000, 50, "Amazônia", "privada_matricula", "medio", 1000, 300),
                ("RS", 1, 0.1, "Pampa", None, None, None, None),
                ("RS", 2, 0.2, "Pampa", "assentamento", "alto", 1, "NaN"),
            ),
            1,
        ):
            mun = 1507300 if uf == "PA" else 4314902
            codigo = f"{uf}-{mun}-{n:032X}"
            codigos.append(codigo)
            con.execute(
                text("""insert into funil.resultado_imovel
                (rodada_id,cod_imovel,uf,municipio,cod_municipio_ibge,ha,m_fiscal,bioma,carbono_ha,atributos)
                values (:rid,:car,:uf,:nome,:mun,:ha,:mf,:bioma, :area, cast(:atributos as jsonb))"""),
                {
                    "rid": rodadas[uf],
                    "car": codigo,
                    "uf": uf,
                    "nome": "São Félix do Xingu" if uf == "PA" else "Porto Alegre",
                    "mun": mun,
                    "ha": ha,
                    "mf": mf,
                    "bioma": bioma,
                    "area": area,
                    "atributos": json.dumps({"dado_interno": {"nao_publicar": "teste"}}),
                },
            )
            con.execute(
                text("""insert into funil.vigente (cod_imovel,rodada_id,cod_municipio_ibge,uf,cod_busca)
                values (:car,:rid,:mun,:uf,:busca)"""),
                {"car": codigo, "rid": rodadas[uf], "mun": mun, "uf": uf, "busca": codigo.replace("-", "")},
            )
            if caminho:
                con.execute(
                    text("""insert into funil.complemento_imovel (rodada_id,cod_imovel,tipo,atributos)
                    values (:rid,:car,'terra',cast(:dado as jsonb))"""),
                    {
                        "rid": rodadas[uf],
                        "car": codigo,
                        "dado": json.dumps({"caminho_terra": caminho, "risco_terra": risco}),
                    },
                )
            if area is not None:
                con.execute(
                    text("""insert into funil.complemento_imovel (rodada_id,cod_imovel,tipo,atributos)
                    values (:rid,:car,'desenvolvedor',cast(:dado as jsonb))"""),
                    {
                        "rid": rodadas[uf],
                        "car": codigo,
                        "dado": json.dumps(
                            {
                                "restauracao_area_ha": area,
                                **{f"credito_liquido_tco2_ha_contrato_{q}": credito for q in ("p10", "p50", "p90")},
                            }
                        ),
                    },
                )
    yield engine, codigos, clientes
    engine.dispose()


@pytest.mark.banco
def test_busca_nacional_preserva_pequenas_e_agrega_antes_pagina(base):
    engine, codigos, clientes = base
    r = buscar_prospeccao(engine, cliente_id=clientes[0], limite=1, incluir_imoveis=True)
    assert r["total"] == 5 and len(r["imoveis"]) == 1 and r["tem_mais"]
    assert r["totais"]["area_ha"] == 5014 and r["totais"]["pequenas"] == 4
    assert r["totais"]["credito_p50"] == 301050 and r["totais"]["com_credito"] == 3
    assert r["totais"]["data_corte_min"] == "2026-11-12" and "contrato" in r["credito_unidade"]
    assert r["total_agrupamentos"] == 2
    assert all(g["fazendas"] == 2 and "vizinhança a conferir" in g["criterio"] for g in r["agrupamentos"])
    segunda = buscar_prospeccao(engine, cliente_id=clientes[0], pagina=2, limite=1, incluir_imoveis=True)
    assert segunda["imoveis"][0]["codigo_car"] != r["imoveis"][0]["codigo_car"]
    assert segunda["totais"] == r["totais"]
    aberto = buscar_prospeccao(engine)
    serializado = json.dumps(aberto)
    assert "imoveis" not in aberto and all(c not in serializado for c in codigos)
    assert "dado_interno" not in serializado and "nao_publicar" not in serializado
    assert aberto["total"] == 5 and aberto["totais"]["credito_p50"] is None
    assert aberto["totais"]["area_ha"] == 5014 and aberto["agrupamentos"] == []
    assert aberto["totais"]["pequenas"] is None and aberto["totais"]["com_credito"] is None
    suprimido = buscar_prospeccao(engine, {"uf": "PA"})
    assert suprimido["total"] is None and suprimido["totais"]["area_ha"] is None
    assert suprimido["contagem"] == "menos de 5"


@pytest.mark.banco
def test_filtros_combinados_e_ausencias(base):
    engine, codigos, clientes = base
    filtros = {
        "uf": "pa",
        "cod_ibge": 1507300,
        "q": "sao felix",
        "bioma": "amazonia",
        "area_min_ha": 0,
        "area_max_ha": 10,
        "credito_min": 0,
        "credito_max": 2000,
        "risco": "baixo",
        "caminho_terra": "privada_matricula",
        "situacao_terra": "pronta_agora",
    }
    r = buscar_prospeccao(engine, filtros, clientes[0], incluir_imoveis=True)
    assert r["total"] == 1 and r["imoveis"][0]["codigo_car"] == codigos[1]
    assert r["imoveis"][0]["pequena"] and r["imoveis"][0]["agrupar"]
    desconhecida = buscar_prospeccao(engine, {"risco": "sem_dados"}, clientes[0], incluir_imoveis=True)
    assert desconhecida["total"] == 1 and desconhecida["imoveis"][0]["credito_p50"] is None
    assert desconhecida["imoveis"][0]["area_restauravel_ha"] is None
    assert buscar_prospeccao(engine, {"uf": "RS", "credito_min": 0}, clientes[0], incluir_imoveis=True)["total"] == 0
    assert buscar_prospeccao(engine, {"uf": "MT"})["total"] == 0
    assert buscar_prospeccao(engine, {"q": "Porto%"})["total"] == 0
    assert buscar_prospeccao(engine, {"q": "' OR 1=1 --"}, clientes[0], incluir_imoveis=True)["total"] == 0
    assert buscar_prospeccao(engine, {"q": "1507300"}, clientes[0], incluir_imoveis=True)["total"] == 3
    assert (
        buscar_prospeccao(engine, {"q": codigos[0].lower().replace("-", "")}, clientes[0], incluir_imoveis=True)[
            "imoveis"
        ][0]["codigo_car"]
        == codigos[0]
    )


@pytest.mark.banco
@pytest.mark.parametrize("total", [0, 875.5])
def test_total_contratual_prevalece_sobre_anual_sem_area_nem_faixas(base, total):
    engine, codigos, clientes = base
    # O total P50 da carga continua válido mesmo sem a área usada na simulação.
    with engine.begin() as con:
        con.execute(
            text("""update funil.resultado_imovel set atributos = atributos || cast(:dados as jsonb)
                    where cod_imovel = :car"""),
            {
                "car": codigos[3],
                "dados": json.dumps({"credito_liquido_tco2_contrato": total, "credito_liquido_tco2_ano": 55}),
            },
        )
    r = buscar_prospeccao(
        engine, {"uf": "RS", "credito_min": total, "credito_max": total}, clientes[0], incluir_imoveis=True
    )
    assert r["total"] == 1 and r["imoveis"][0]["codigo_car"] == codigos[3]
    assert r["imoveis"][0]["credito_p50"] == total
    assert r["imoveis"][0]["credito_p10"] is None and r["imoveis"][0]["credito_p90"] is None
    assert r["totais"]["credito_p50"] == total and r["totais"]["com_credito"] == 1


@pytest.mark.banco
def test_total_contratual_e_fallback_sem_sobrescrever_calculo_por_area(base):
    engine, codigos, clientes = base
    with engine.begin() as con:
        con.execute(
            text("""update funil.resultado_imovel
                    set atributos = atributos || cast(:dados as jsonb)
                    where cod_imovel = :car"""),
            {"car": codigos[0], "dados": json.dumps({"credito_liquido_tco2_contrato": 999})},
        )
    r = buscar_prospeccao(engine, {"q": codigos[0]}, clientes[0], incluir_imoveis=True)
    assert r["imoveis"][0]["credito_p50"] == 50


@pytest.mark.banco
@pytest.mark.parametrize("total", ["NaN", "Infinity", True, {"valor": 20}])
def test_total_contratual_malformado_nao_vira_credito(base, total):
    engine, codigos, clientes = base
    with engine.begin() as con:
        con.execute(
            text("""update funil.resultado_imovel set atributos = atributos || cast(:dados as jsonb)
                    where cod_imovel = :car"""),
            {"car": codigos[3], "dados": json.dumps({"credito_liquido_tco2_contrato": total})},
        )
    r = buscar_prospeccao(engine, {"q": codigos[3]}, clientes[0], incluir_imoveis=True)
    assert r["imoveis"][0]["credito_p50"] is None


@pytest.mark.banco
def test_reserva_de_outro_cliente_some_de_lista_e_agregados(base):
    engine, codigos, clientes = base
    with engine.begin() as con:
        pedido = con.execute(
            text("""insert into negocio.pedido (id,cliente_id,campos)
            values ('00000000-0000-4000-a000-000000000001',:cid,'{}') returning id"""),
            {"cid": clientes[0]},
        ).scalar_one()
        reserva = con.execute(
            text("""insert into negocio.reserva (pedido_id,cliente_id,estado,ha,valor_rs,dias)
            values (:pid,:cid,'ativa',1,1,30) returning id"""),
            {"pid": pedido, "cid": clientes[0]},
        ).scalar_one()
        con.execute(
            text("""insert into negocio.reserva_fazenda (reserva_id,cod_imovel,ativa)
            values (:rid,:car,true)"""),
            {"rid": reserva, "car": codigos[0]},
        )
    assert buscar_prospeccao(engine)["total"] is None
    assert buscar_prospeccao(engine)["contagem"] == "menos de 5"
    assert buscar_prospeccao(engine, cliente_id=clientes[0])["total"] == 5
    outro = buscar_prospeccao(engine, cliente_id=clientes[1], incluir_imoveis=True)
    assert outro["total"] == 4 and all(i["codigo_car"] != codigos[0] for i in outro["imoveis"])
    assert outro["totais"]["credito_p50"] == 301000
    assert not any(g["uf"] == "PA" for g in outro["agrupamentos"])


def test_paginacao_e_lista_sem_cliente_fecham_antes_do_banco():
    for pagina, limite in ((0, 10), (201, 10), (1, 51), (True, 10), (1, 1.5)):
        with pytest.raises(ValueError):
            buscar_prospeccao(None, pagina=pagina, limite=limite)
    with pytest.raises(ValueError, match="autenticado"):
        buscar_prospeccao(None, incluir_imoveis=True)


@pytest.mark.parametrize(
    "filtro",
    [
        {"q": "PA-1507300-ABC"},
        {"q": "1507300"},
        {"area_min_ha": 0},
        {"area_max_ha": 5},
        {"credito_min": 0},
        {"credito_max": 100},
    ],
)
def test_agregado_nao_permita_isolar_car_por_codigo_ou_intervalo(filtro):
    with pytest.raises(ValueError, match="exige"):
        buscar_prospeccao(None, filtro)
