"""Retificações e autorização em PostGIS real, incluindo duas operações concorrentes."""

import datetime as dt
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from raiz.pasta_fiador import servico as s
from raiz.pasta_fiador.esquema import Retificacao
from raiz.prospeccao_acesso import ErroAcesso
from testes.test_pasta_fiador import dados_pasta
from testes.test_prospeccao_buscas import base as base

pytestmark = pytest.mark.banco


@pytest.fixture
def pasta(base, monkeypatch):
    engine, (cliente, outro), _, adicionar = base
    car = adicionar(0.25)
    pedido = uuid4()
    with engine.begin() as con:
        con.execute(
            text("insert into negocio.pedido(id,cliente_id,campos) values(:p,:c,'{}')"), {"p": pedido, "c": cliente}
        )
        con.execute(
            text("""insert into negocio.pedido_sugestao(pedido_id,motivo,base,opcoes,premissas_versao,otimizador_versao)
            values(:p,'criado','{}',cast(:o as jsonb),'teste','teste')"""),
            {"p": pedido, "o": json.dumps([{"id": "segura", "itens": [{"cod_imovel": car, "papel": "lote"}]}])},
        )
        con.execute(
            text("insert into negocio.prospeccao_desbloqueio(cliente_id,cod_imovel) values(:c,:car)"),
            {"c": cliente, "car": car},
        )
    monkeypatch.setenv("RAIZ_PROTECAO_VERSAO", "teste")
    monkeypatch.setenv("RAIZ_PROTECAO_CHAVES", json.dumps({"teste": "chave-sintetica-exclusiva-dos-testes-pasta"}))
    p = dados_pasta(car, pedido)
    return engine, cliente, outro, p


def incluir(engine, dados):
    return s.registrar(engine, Retificacao(tipo="inclusao", motivo="entrada_conferida", dados=dados))


def retificar(engine, dados, anterior, tipo="correcao"):
    return s.registrar(engine, Retificacao(tipo=tipo, motivo="erro_material", dados=dados, versao_anterior_id=anterior))


def consultar(pasta):
    e, c, _, p = pasta
    return s.consultar(e, c, p.pedido_id, p.opcao)


def test_duas_saidas_privadas_marca_e_previsao_com_id_estavel(pasta):
    e, c, outro, p = pasta
    inicial = incluir(e, p)
    a = consultar(pasta)
    assert a["validacao"]["pronto"] and a["versao_id"] == inicial["versao_id"]
    referencia = a["previsoes"][0]
    assert referencia["relacoes"][0]["tipo"] == "IsVersionOf"
    z = zipfile.ZipFile(io.BytesIO(s.exportar(e, c, p.pedido_id, p.opcao)))
    for n in z.namelist():
        assert b"RZP-teste-" in z.read(n)
    with pytest.raises(ErroAcesso) as erro:
        s.exportar(e, outro, p.pedido_id, p.opcao)
    assert erro.value.status == 404
    assert s.historico(e, c, p.pedido_id, p.opcao)["versoes"][0]["numero"] == 1


def test_retificacao_append_only_muda_previsao_referencia_e_preserva_versao(pasta):
    e, c, _, p = pasta
    inicial = incluir(e, p)
    a = consultar(pasta)
    p.imoveis[0].creditos[0].p50.valor = Decimal(22)
    nova = retificar(e, p, inicial["versao_id"], "nova_previsao")
    b = consultar(pasta)
    assert b["pasta_id"] == a["pasta_id"] and nova["numero"] == 2
    assert b["previsoes"][0]["referencia"] != a["previsoes"][0]["referencia"]
    assert b["previsoes"][0]["relacoes"][1] == {"tipo": "IsNewVersionOf", "referencia": a["previsoes"][0]["referencia"]}
    antiga = s.consultar(e, c, p.pedido_id, p.opcao, versao_id=UUID(inicial["versao_id"]))
    assert antiga["dados"]["imoveis"][0]["creditos"][0]["p50"]["valor"] == "20"
    assert antiga["previsoes"] == a["previsoes"]
    for tabela in ("pasta_fiador_versao", "pasta_previsao_referencia", "pasta_previsao_serie"):
        with pytest.raises(DBAPIError), e.begin() as con:
            con.execute(text(f"delete from negocio.{tabela} where pasta_id=:p"), {"p": a["pasta_id"]})
    # Correção de preço não muda previsão; histórico do documento permanece referenciado.
    p.imoveis[0].preco.valor = Decimal(25)
    retificar(e, p, nova["versao_id"])
    assert consultar(pasta)["previsoes"] == b["previsoes"]


def test_concorrencia_so_anexa_uma_versao_e_rejeita_base_antiga(pasta):
    e, _, _, p = pasta
    a = incluir(e, p)

    def rodar(_):
        try:
            return retificar(e, p, a["versao_id"])["numero"]
        except ErroAcesso as ex:
            return ex.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(rodar, range(2))) == [2, 409]


def test_lote_incompleto_ou_alterado_nao_e_exportado(pasta):
    e, c, _, p = pasta
    incluir(e, p)
    with e.begin() as con:
        con.execute(text("update negocio.pedido_sugestao set opcoes='[]' where pedido_id=:p"), {"p": p.pedido_id})
    assert not consultar(pasta)["validacao"]["pronto"]
    with pytest.raises(ErroAcesso, match="pendências"):
        s.exportar(e, c, p.pedido_id, p.opcao)
    with pytest.raises(ErroAcesso, match="exatamente"):
        incluir(e, p)


def test_perdeu_acesso_pago_nega_historico_e_exportacao(pasta):
    e, c, _, p = pasta
    incluir(e, p)
    with e.begin() as con:
        con.execute(text("delete from negocio.prospeccao_desbloqueio where cliente_id=:c"), {"c": c})
    for funcao in (s.consultar, s.historico, s.exportar):
        with pytest.raises(ErroAcesso) as erro:
            funcao(e, c, p.pedido_id, p.opcao)
        assert erro.value.status == 403


def test_id_documento_nao_pode_trocar_conteudo_e_serie_nao_muda(pasta):
    e, _, _, p = pasta
    a = incluir(e, p)
    p.documentos[0].sha256 = "b" * 64
    with pytest.raises(ErroAcesso, match="novo ID"):
        retificar(e, p, a["versao_id"])
    p.documentos[0].sha256 = "a" * 64
    p.imoveis[0].creditos[0].previsao_id = uuid4()
    with pytest.raises(ErroAcesso, match="ID estável"):
        retificar(e, p, a["versao_id"])
    assert consultar(pasta)["numero"] == 1  # Transação também desfez a nova versão.


def test_documento_vence_entre_consulta_e_exportacao(pasta, monkeypatch):
    e, c, _, p = pasta
    incluir(e, p)
    assert consultar(pasta)["validacao"]["pronto"]
    original = s.validar
    monkeypatch.setattr(s, "validar", lambda dados: original(dados, agora=dt.datetime(2036, 1, 1, tzinfo=dt.UTC)))
    assert not consultar(pasta)["validacao"]["pronto"]
    with pytest.raises(ErroAcesso, match="pendências"):
        s.exportar(e, c, p.pedido_id, p.opcao)


def test_retirada_preserva_historico_mas_bloqueia_entrega(pasta):
    e, c, _, p = pasta
    a = incluir(e, p)
    retificar(e, p, a["versao_id"], "retirada")
    atual = consultar(pasta)
    assert not atual["validacao"]["pronto"]
    assert atual["tipo_alteracao"] == "retirada"
    assert len(s.historico(e, c, p.pedido_id, p.opcao)["versoes"]) == 2
    with pytest.raises(ErroAcesso):
        s.exportar(e, c, p.pedido_id, p.opcao)


def test_exclusividade_de_outro_cliente_tambem_bloqueia_pasta(pasta):
    e, c, outro, p = pasta
    incluir(e, p)
    with e.begin() as con:
        pid = uuid4()
        con.execute(text("insert into negocio.pedido(id,cliente_id,campos) values(:p,:c,'{}')"), {"p": pid, "c": outro})
        reserva = con.execute(
            text("""insert into negocio.reserva(pedido_id,cliente_id,estado,ha,valor_rs,dias)
            values(:p,:c,'ativa',1,1,30) returning id"""),
            {"p": pid, "c": outro},
        ).scalar_one()
        con.execute(
            text("insert into negocio.reserva_fazenda(reserva_id,cod_imovel,ativa) values(:r,:car,true)"),
            {"r": reserva, "car": p.imoveis[0].codigo_car},
        )
    for funcao in (s.consultar, s.historico, s.exportar):
        with pytest.raises(ErroAcesso) as erro:
            funcao(e, c, p.pedido_id, p.opcao)
        assert erro.value.status == 403


def test_ficha_separa_conferencia_do_lote_por_cliente_sem_contaminar_snapshot(pasta):
    e, c, outro, p = pasta
    incluir(e, p)
    car = p.imoveis[0].codigo_car
    with e.begin() as con:
        con.execute(
            text("insert into negocio.prospeccao_desbloqueio(cliente_id,cod_imovel) values(:c,:car)"),
            {"c": outro, "car": car},
        )
    propria = s.da_ficha(e, c, car)
    assert len(propria["pastas"]) == 1
    assert propria["pastas"][0]["imovel"]["creditos"][0]["metodo"] == "regeneracao_assistida"
    assert propria["pastas"][0]["imovel"]["titulo"]["nivel"] == "conferencia_concluida"
    assert s.da_ficha(e, outro, car)["pastas"] == []
    with e.connect() as con:
        assert (
            con.execute(
                text("select count(*) from negocio.prospeccao_ficha_versao where cod_imovel=:car"), {"car": car}
            ).scalar()
            == 0
        )


def test_identidade_da_previsao_nao_pode_mudar_de_metodo(pasta):
    e, _, _, p = pasta
    a = incluir(e, p)
    p.imoveis[0].creditos[0].metodo = "plantio_total"
    with pytest.raises(ErroAcesso, match="já utilizada"):
        retificar(e, p, a["versao_id"])
    assert consultar(pasta)["numero"] == 1
