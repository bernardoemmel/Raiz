"""Snapshots duráveis, rollback de leitura e avisos privados sob concorrência real."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from raiz import prospeccao_buscas as buscas
from raiz import prospeccao_versoes as versoes
from raiz.prospeccao_acesso import ErroAcesso
from testes.test_prospeccao_buscas import base as base


def liberar(engine, cliente, *cars):
    with engine.begin() as con:
        for car in cars:
            con.execute(
                text(
                    """insert into negocio.prospeccao_desbloqueio(cliente_id,cod_imovel)
                       values (:c,:car) on conflict do nothing"""
                ),
                {"c": cliente, "car": car},
            )


def registrar(engine, *cars):
    with engine.begin() as con:
        return versoes.registrar_versoes(con, list(cars), origem="rodada")


def ficha(engine, car):
    with engine.connect() as con:
        return versoes._montar_lote(con, [car])[0]


def alterar(engine, car, *, area=None, **atributos):
    with engine.begin() as con:
        con.execute(
            text("""update funil.resultado_imovel r set atributos=r.atributos||cast(:a as jsonb),ha=coalesce(:area,r.ha)
            from funil.vigente v where (r.rodada_id,r.cod_imovel)=(v.rodada_id,v.cod_imovel) and v.cod_imovel=:car"""),
            {"a": json.dumps(atributos), "area": area, "car": car},
        )
    return registrar(engine, car)[car]


def consultar(engine, cliente, car):
    with versoes.consultas(engine, cliente, [ficha(engine, car)]) as dados:
        resultado = dados[0]
    return resultado


def escalar(engine, sql, **params):
    with engine.connect() as con:
        return con.execute(text(sql), params).scalar()


def test_hash_ignora_metadados_volateis_e_dados_da_conta():
    a = {
        "codigo_car": "CAR",
        "pendencias": [],
        "o_que_mudou": {"segredo": "cliente"},
        "terra_comprometida": {"cobertura": [{"consultado_em": "2026-01-01", "data_referencia": "2025"}]},
    }
    b = {
        **a,
        "cliente_id": 77,
        "versao_ficha": {"id": 55},
        "terra_comprometida": {"cobertura": [{"consultado_em": "2026-02-02", "data_referencia": "2025"}]},
    }
    assert versoes._hash(a) == versoes._hash(b)
    b["terra_comprometida"]["cobertura"][0]["data_referencia"] = "2026"
    assert versoes._hash(a) != versoes._hash(b)
    assert "cliente" not in str(versoes.documento(a))


@pytest.mark.banco
def test_versoes_antes_da_consulta_dedup_transicao_retorno_e_imutabilidade(base):
    engine, (cliente, _), _, adicionar = base
    car = adicionar()
    primeira = registrar(engine, car)[car]
    assert registrar(engine, car)[car] == primeira
    segunda = alterar(engine, car, embargo_ha=12, ibama_data_referencia="2026-11-11")
    terceira = alterar(engine, car, embargo_ha=0)
    assert segunda != primeira and terceira != segunda
    assert alterar(engine, car, embargo_ha=12) == segunda
    assert (
        escalar(engine, "select count(*) from negocio.prospeccao_ficha_observacao where cod_imovel=:car", car=car) == 4
    )
    with pytest.raises(DBAPIError, match="imutável"), engine.begin() as con:
        con.execute(text("update negocio.prospeccao_ficha_versao set documento='{}' where id=:v"), {"v": primeira})
    liberar(engine, cliente, car)
    assert len(versoes.historico(engine, cliente, car)["historico"]) == 4
    assert escalar(engine, "select count(*) from negocio.prospeccao_ficha_consulta where cod_imovel=:car", car=car) == 0


@pytest.mark.banco
def test_consulta_falha_nao_avanca_baseline_e_contas_sao_independentes(base):
    engine, (cliente, outro), _, adicionar = base
    car = adicionar()
    liberar(engine, cliente, car)
    liberar(engine, outro, car)
    assert consultar(engine, cliente, car)["o_que_mudou"]["primeira_consulta"]
    alterar(engine, car, embargo_ha=12, ibama_data_referencia="2026-11-11", desm_pos2020_ha=2, mb_fogo_2024_ha=3)
    with pytest.raises(RuntimeError), versoes.consultas(engine, cliente, [ficha(engine, car)]) as dados:
        assert {x["tipo"] for x in dados[0]["o_que_mudou"]["mudancas"]} >= {
            "embargos",
            "desmatamento",
            "fogo",
            "pendencias",
        }
        raise RuntimeError("Falha simulada ao renderizar PDF")
    resposta = consultar(engine, cliente, car)
    embargo = next(x for x in resposta["o_que_mudou"]["mudancas"] if x["tipo"] == "embargos")
    assert embargo["depois"]["area"]["valor"] == 12
    assert embargo["fonte"] == "Ibama, embargos ativos" and embargo["data_referencia"] == "2026-11-11"
    assert consultar(engine, cliente, car)["o_que_mudou"]["mudancas"] == []
    assert consultar(engine, outro, car)["o_que_mudou"]["primeira_consulta"]


@pytest.mark.banco
def test_consultas_concorrentes_consumem_baseline_uma_vez(base):
    engine, (cliente, _), _, adicionar = base
    car = adicionar()
    liberar(engine, cliente, car)
    consultar(engine, cliente, car)
    alterar(engine, car, embargo_ha=3)
    with ThreadPoolExecutor(max_workers=3) as pool:
        respostas = list(pool.map(lambda _: consultar(engine, cliente, car), range(3)))
    assert sum(bool(r["o_que_mudou"]["mudancas"]) for r in respostas) == 1
    assert len({r["versao_ficha"]["id"] for r in respostas}) == 1


@pytest.mark.banco
def test_autorizacao_em_todas_e_revogacao_durante_render_rollback(base):
    engine, (cliente, _), _, adicionar = base
    car, fechada = adicionar(), adicionar()
    liberar(engine, cliente, car)
    with pytest.raises(ErroAcesso), versoes.consultas(engine, cliente, [ficha(engine, car), ficha(engine, fechada)]):
        pytest.fail("Não deve abrir comparação parcialmente autorizada")
    assert escalar(engine, "select count(*) from negocio.prospeccao_ficha_consulta where cliente_id=:c", c=cliente) == 0
    with pytest.raises(ErroAcesso), versoes.consultas(engine, cliente, [ficha(engine, car)]):
        with engine.begin() as con:
            con.execute(text("delete from negocio.prospeccao_desbloqueio where cliente_id=:c"), {"c": cliente})
    assert escalar(engine, "select count(*) from negocio.prospeccao_ficha_consulta where cliente_id=:c", c=cliente) == 0


@pytest.mark.banco
def test_monitoramento_avisa_depois_de_sair_do_filtro_sem_avancar_consulta(base):
    engine, (cliente, _), filtros, adicionar = base
    car = adicionar(1)
    liberar(engine, cliente, car)
    consultar(engine, cliente, car)
    salva = buscas.salvar(engine, cliente, "Pequenas", {**filtros, "area_max_ha": 5})
    assert buscas.avisos(engine, cliente)["avisos"] == []
    alterar(engine, car, area=20, embargo_ha=4)
    with ThreadPoolExecutor(max_workers=3) as pool:
        resultados = list(pool.map(lambda _: buscas.verificar(engine, salva["id"]), range(3)))
    assert sum(r["alteracoes_terra"] for r in resultados) == 1
    assert sum(r["alteracoes_filtro"] for r in resultados) == 1
    alterar(engine, car, embargo_ha=8)
    assert buscas.verificar(engine, salva["id"])["alteracoes_terra"] == 1
    avisos = buscas.avisos(engine, cliente)["avisos"]
    assert [a["tipo"] for a in avisos] == ["alteracao_terra", "saiu_filtro", "alteracao_terra"]
    assert any(x["tipo"] == "embargos" for x in consultar(engine, cliente, car)["o_que_mudou"]["mudancas"])
    n = escalar(engine, "select count(*) from negocio.prospeccao_ficha_versao where cod_imovel=:car", car=car)
    buscas.excluir(engine, cliente, salva["id"])
    assert escalar(engine, "select count(*) from negocio.prospeccao_ficha_versao where cod_imovel=:car", car=car) == n


@pytest.mark.banco
def test_avisos_sem_unlock_nao_entregam_tipo_pago_nem_medidas(base):
    engine, (cliente, _), filtros, adicionar = base
    car = adicionar()
    registrar(engine, car)
    salva = buscas.salvar(engine, cliente, "Terras", filtros)
    alterar(engine, car, embargo_ha=789)
    buscas.verificar(engine, salva["id"])
    aviso = buscas.avisos(engine, cliente)["avisos"][0]
    assert aviso["tipo"] == "atualizacao_disponivel" and aviso["mudancas"] == []
    # IDs e frações de segundo podem conter 789 sem revelar uma medida.
    # Confere todo o conteúdo restante, incluindo qualquer campo novo inesperado.
    metadados = {"id", "busca_id", "nome_busca", "codigo_car", "criada_em", "lida_em"}
    assert {k: v for k, v in aviso.items() if k not in metadados} == {
        "tipo": "atualizacao_disponivel",
        "ficha_liberada": False,
        "mudancas": [],
        "mensagem": "Há atualizações da terra ou da seleção. Consulte a ficha liberada.",
    }
    with pytest.raises(ErroAcesso):
        versoes.historico(engine, cliente, car)


@pytest.mark.banco
def test_lote_da_propria_conta_e_reserva_alheia_nao_vazam(base):
    engine, (cliente, outro), filtros, adicionar = base
    car = adicionar()
    liberar(engine, cliente, car)
    consultar(engine, cliente, car)
    salva = buscas.salvar(engine, cliente, "Lotes", filtros)
    pedidos = [uuid.uuid4(), uuid.uuid4()]
    with engine.begin() as con:
        for pedido, dono in zip(pedidos, [cliente, outro], strict=True):
            con.execute(
                text("insert into negocio.pedido(id,cliente_id,campos) values (:p,:c,'{}')"), {"p": pedido, "c": dono}
            )
            con.execute(
                text("insert into negocio.pedido_fazenda(pedido_id,cod_imovel,papel) values (:p,:car,'lote')"),
                {"p": pedido, "car": car},
            )
    assert buscas.verificar(engine, salva["id"])["alteracoes_lote"] == 1
    aviso = buscas.avisos(engine, cliente)["avisos"][0]
    assert aviso["tipo"] == "entrou_lote"
    assert str(pedidos[0]) in str(aviso) and str(pedidos[1]) not in str(aviso)
    assert consultar(engine, cliente, car)["o_que_mudou"]["mudancas"][0]["tipo"] == "entrou_lote"
    with engine.begin() as con:
        reserva = con.execute(
            text("""insert into negocio.reserva(pedido_id,cliente_id,estado,ha,valor_rs,dias)
            values (:p,:c,'ativa',1,1,30) returning id"""),
            {"p": pedidos[1], "c": outro},
        ).scalar_one()
        con.execute(
            text("insert into negocio.reserva_fazenda(reserva_id,cod_imovel,ativa) values (:r,:car,true)"),
            {"r": reserva, "car": car},
        )
    alterar(engine, car, embargo_ha=55)
    resultado = buscas.verificar(engine, salva["id"])
    assert resultado["alteracoes_terra"] == resultado["alteracoes_filtro"] == resultado["alteracoes_lote"] == 0
    assert buscas.avisos(engine, cliente)["avisos"] == []
    with pytest.raises(ErroAcesso):
        versoes.historico(engine, cliente, car)


@pytest.mark.banco
def test_snapshot_em_lote_nao_faz_consultas_por_car_e_registra_removida(base):
    engine, _, _, adicionar = base
    cars = [adicionar() for _ in range(12)]
    comandos = []

    def contar(conn, cursor, stmt, parameters, context, executemany):
        comandos.append(stmt)

    event.listen(engine, "before_cursor_execute", contar)
    try:
        registrar(engine, *cars)
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    assert len(comandos) < 25, "O número de consultas deve ser constante por lote, não por imóvel."
    with engine.begin() as con:
        con.execute(text("delete from funil.vigente where cod_imovel=:car"), {"car": cars[0]})
        versoes.registrar_versoes(con, [cars[0]], origem="carga_depois")
    assert (
        escalar(
            engine,
            """select v.documento->>'disponivel' from negocio.prospeccao_ficha_atual a
        join negocio.prospeccao_ficha_versao v on v.id=a.versao_id where a.cod_imovel=:car""",
            car=cars[0],
        )
        == "false"
    )


def test_documento_fecha_niveis_aninhados_e_preserva_datas_de_fonte():
    dado = {
        "codigo_car": "PA-1504950-" + "A" * 32,
        "credito": {"p50": {"valor": 12, "unidade": "tCO2e/contrato", "nome_dono": "NAO_PERSISTIR"}},
        "terra_comprometida": {
            "evidencias": [
                {
                    "fonte_id": "verra",
                    "observado_em": "2026-11-12",
                    "data_referencia": "2026-01-02",
                    "contato": "NAO_PERSISTIR",
                }
            ],
            "cobertura": [
                {
                    "fonte_id": "verra",
                    "consultado_em": "2026-11-13",
                    "data_referencia": "2026-01-03",
                    "cpf": "NAO_PERSISTIR",
                }
            ],
        },
    }
    fechado = versoes.documento(dado)
    assert "NAO_PERSISTIR" not in json.dumps(fechado)
    assert fechado["terra_comprometida"]["evidencias"][0]["observado_em"] == "2026-11-12"
    assert fechado["terra_comprometida"]["cobertura"][0]["consultado_em"] == "2026-11-13"
    assert fechado["credito"]["p50"]["valor"] == 12
    alterado = json.loads(json.dumps(fechado))
    alterado["terra_comprometida"]["cobertura"][0]["consultado_em"] = "2026-11-15"
    assert versoes._hash(fechado) == versoes._hash(alterado)
    assert versoes.diferencas(fechado, alterado) == []


@pytest.mark.banco
def test_snapshot_preserva_proveniencia_e_rejeita_pii_aninhado_no_banco(base):
    engine, (cliente, _), _, adicionar = base
    car = adicionar()
    liberar(engine, cliente, car)
    dado = ficha(engine, car)
    dado["credito"]["p50"]["nome_dono"] = "NAO_PERSISTIR"
    dado["terra_comprometida"] = {
        "evidencias": [
            {
                "fonte_id": "verra",
                "observado_em": "2026-11-12",
                "data_referencia": "2026-01-02",
                "contato": "NAO_PERSISTIR",
            }
        ],
        "cobertura": [{"fonte_id": "verra", "consultado_em": "2026-11-13"}],
    }
    with versoes.consultas(engine, cliente, [dado]) as resultados:
        ident = resultados[0]["versao_ficha"]["id"]
    salvo = escalar(engine, "select documento from negocio.prospeccao_ficha_versao where id=:id", id=ident)
    assert "NAO_PERSISTIR" not in json.dumps(salvo)
    assert salvo["terra_comprometida"]["evidencias"][0]["observado_em"] == "2026-11-12"
    assert salvo["terra_comprometida"]["cobertura"][0]["consultado_em"] == "2026-11-13"


@pytest.mark.banco
def test_dto_antigo_em_voo_nao_retrocede_observacao_global(base):
    engine, (cliente, _), _, adicionar = base
    car = adicionar()
    liberar(engine, cliente, car)
    antigo = ficha(engine, car)
    primeira = consultar(engine, cliente, car)["versao_ficha"]["id"]
    atual = alterar(engine, car, embargo_ha=8)
    with versoes.consultas(engine, cliente, [antigo]) as entregue:
        assert entregue[0]["versao_ficha"]["id"] == primeira
    assert (
        escalar(engine, "select versao_id from negocio.prospeccao_ficha_atual where cod_imovel=:car", car=car) == atual
    )
    assert (
        escalar(engine, "select count(*) from negocio.prospeccao_ficha_observacao where cod_imovel=:car", car=car) == 2
    )
    seguinte = consultar(engine, cliente, car)
    assert seguinte["versao_ficha"]["id"] == atual
    assert any(x["tipo"] == "embargos" for x in seguinte["o_que_mudou"]["mudancas"])


@pytest.mark.banco
def test_carga_e_consulta_concorrentes_preservam_ordem_e_ponteiro(base):
    engine, (cliente, _), _, adicionar = base
    cars = [adicionar(), adicionar()]
    liberar(engine, cliente, *cars)
    dados = [ficha(engine, c) for c in cars]
    registrar(engine, *cars)

    def carregar():
        with engine.begin() as con:
            versoes.registrar_versoes(con, list(reversed(cars)), origem="carga_antes")
            con.execute(
                text("""update funil.resultado_imovel set atributos=atributos||cast(:atributos as jsonb)
                where cod_imovel=any(:cs)"""),
                {"cs": cars, "atributos": json.dumps({"embargo_ha": 9})},
            )
            return versoes.registrar_versoes(con, list(reversed(cars)), origem="carga_depois")

    def consultar_antiga():
        with versoes.consultas(engine, cliente, dados) as resposta:
            return [r["versao_ficha"]["id"] for r in resposta]

    with ThreadPoolExecutor(max_workers=2) as pool:
        carga, consulta = pool.submit(carregar), pool.submit(consultar_antiga)
        esperadas = carga.result(timeout=15)
        assert len(consulta.result(timeout=15)) == 2
    for car in cars:
        assert (
            escalar(engine, "select versao_id from negocio.prospeccao_ficha_atual where cod_imovel=:car", car=car)
            == esperadas[car]
        )
