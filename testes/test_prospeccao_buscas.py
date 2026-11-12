"""Novas correspondências sem avisar a base antiga, sem duplicatas e por cliente."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from raiz import prospeccao_buscas as buscas
from raiz.busca import normalizar_codigo
from raiz.pedidos.servico import criar_cliente
from raiz.prospeccao_acesso import ErroAcesso


@pytest.fixture
def base(banco_url):
    engine = create_engine(banco_url)
    clientes = [criar_cliente(engine, "Cliente de buscas de teste")[0] for _ in range(2)]
    with engine.begin() as con:
        rodada = con.execute(
            text("""insert into funil.rodada
                (tipo,uf,cod_municipio,origem,arquivos,hash_entradas,motor_versao,regras_versao,data_corte)
                values ('municipio','PA',1504950,'teste','{}',:hash,'teste','teste','2026-11-12') returning id"""),
            {"hash": str(uuid.uuid4())},
        ).scalar_one()
    # Município único por teste mantém filtros alheios fora do snapshot.
    nome = "Seleção " + uuid.uuid4().hex

    def acrescentar(area=1):
        car = "PA-1504950-" + uuid.uuid4().hex.upper()
        with engine.begin() as con:
            con.execute(
                text("""insert into funil.resultado_imovel
                    (rodada_id,cod_imovel,uf,municipio,cod_municipio_ibge,ha,m_fiscal,bioma,atributos)
                    values (:r,:car,'PA',:nome,1504950,:ha,0.1,'Amazônia',cast(:a as jsonb))"""),
                {"r": rodada, "car": car, "nome": nome, "ha": area, "a": json.dumps({"dado_interno": "não publicar"})},
            )
            con.execute(
                text("""insert into funil.vigente(cod_imovel,rodada_id,cod_municipio_ibge,uf,cod_busca)
                    values (:car,:r,1504950,'PA',:b)"""),
                {"car": car, "r": rodada, "b": normalizar_codigo(car)},
            )
        return car

    yield engine, clientes, {"q": nome}, acrescentar
    engine.dispose()


@pytest.mark.banco
def test_snapshot_inicial_silencioso_e_novo_car_mesma_rodada_avisa_uma_vez(base):
    engine, (cliente, outro), filtros, acrescentar = base
    antiga = acrescentar()
    salva = buscas.salvar(engine, cliente, "Pequenas para agrupar", filtros)
    assert buscas.avisos(engine, cliente)["avisos"] == []
    assert buscas.verificar(engine, salva["id"])["novas_fazendas"] == 0
    nova = acrescentar()
    with ThreadPoolExecutor(max_workers=3) as pool:
        respostas = list(pool.map(lambda _: buscas.verificar(engine, salva["id"]), range(3)))
    assert sum(r["novas_fazendas"] for r in respostas) == 1
    avisos = buscas.avisos(engine, cliente)["avisos"]
    assert len(avisos) == 1 and avisos[0]["codigo_car"] == nova
    assert antiga not in str(avisos) and "não publicar" not in str(avisos)
    assert buscas.avisos(engine, outro)["avisos"] == []
    assert buscas.listar(engine, outro) == []
    with pytest.raises(ErroAcesso) as erro:
        buscas.excluir(engine, outro, salva["id"])
    assert erro.value.status == 404
    with pytest.raises(ErroAcesso):
        buscas.ler_aviso(engine, outro, avisos[0]["id"])
    lido = buscas.ler_aviso(engine, cliente, avisos[0]["id"])
    assert buscas.ler_aviso(engine, cliente, avisos[0]["id"]) == lido
    buscas.excluir(engine, cliente, salva["id"])
    assert buscas.avisos(engine, cliente)["avisos"] == []


@pytest.mark.banco
def test_filtros_restritos_e_reserva_ocultam_aviso_existente(base):
    engine, (cliente, outro), filtros, acrescentar = base
    pequena = acrescentar(1)
    salva = buscas.salvar(engine, cliente, "Até cinco hectares", {**filtros, "area_max_ha": 5})
    acrescentar(500)
    nova = acrescentar(2)
    assert buscas.verificar(engine, salva["id"])["novas_fazendas"] == 1
    assert [a["codigo_car"] for a in buscas.avisos(engine, cliente)["avisos"]] == [nova]
    with engine.begin() as con:
        pedido = uuid.uuid4()
        con.execute(
            text("insert into negocio.pedido(id,cliente_id,campos) values (:p,:c,'{}')"), {"p": pedido, "c": outro}
        )
        reserva = con.execute(
            text("""insert into negocio.reserva(pedido_id,cliente_id,estado,ha,valor_rs,dias)
                values (:p,:c,'ativa',1,1,30) returning id"""),
            {"p": pedido, "c": outro},
        ).scalar_one()
        con.execute(
            text("insert into negocio.reserva_fazenda(reserva_id,cod_imovel,ativa) values (:r,:car,true)"),
            {"r": reserva, "car": nova},
        )
    assert buscas.avisos(engine, cliente)["avisos"] == []
    assert buscas.verificar(engine, salva["id"])["novas_fazendas"] == 0
    assert pequena != nova


@pytest.mark.banco
def test_paginacao_e_cursor_nao_perdem_aviso(base):
    engine, (cliente, _), filtros, acrescentar = base
    salva = buscas.salvar(engine, cliente, "Todas", filtros)
    esperadas = {acrescentar() for _ in range(3)}
    assert buscas.verificar(engine, salva["id"])["novas_fazendas"] == 3
    primeira = buscas.avisos(engine, cliente, limite=2)
    segunda = buscas.avisos(engine, cliente, depois=primeira["proximo_cursor"], limite=2)
    assert {a["codigo_car"] for a in primeira["avisos"] + segunda["avisos"]} == esperadas
    assert segunda["proximo_cursor"] is None


@pytest.mark.banco
def test_cli_verifica_buscas_e_repeticao_nao_duplica_aviso(base, monkeypatch):
    from typer.testing import CliRunner

    from raiz import banco
    from raiz.cli import app

    engine, (cliente, _), filtros, acrescentar = base
    salva = buscas.salvar(engine, cliente, "Busca do comando", filtros)
    car = acrescentar()
    monkeypatch.setattr(banco, "engine", lambda: engine)
    runner = CliRunner()
    primeira = runner.invoke(app, ["prospeccao", "verificar-buscas", "--busca", salva["id"]])
    assert primeira.exit_code == 0 and "novas fazendas: 1" in primeira.output
    repeticao = runner.invoke(app, ["prospeccao", "verificar-buscas"])
    assert repeticao.exit_code == 0 and "novas fazendas: 0" in repeticao.output
    assert [a["codigo_car"] for a in buscas.avisos(engine, cliente)["avisos"]] == [car]
    invalida = runner.invoke(app, ["prospeccao", "verificar-buscas", "--busca", "id-invalido"])
    assert invalida.exit_code == 1 and "Busca salva não encontrada" in invalida.output
