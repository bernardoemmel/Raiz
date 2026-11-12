from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text

from raiz.modelos.base import Pedido, Resposta
from raiz.modelos.cascata import Cascata, comparador_por_campos, resolver_revisao

ESQUEMA = {
    "type": "object",
    "properties": {"intencao": {"type": "string"}, "area_ha": {"type": "number"}},
    "required": ["intencao", "area_ha"],
    "additionalProperties": False,
}


class Falso:
    def __init__(self, nome, dados=None, erro=None, custo="0.001", recusou=False):
        self.nome, self.provedor = nome, "teste"
        self.dados, self.erro, self.custo, self.recusou = dados, erro, Decimal(custo), recusou
        self.chamadas = 0

    def responder_json(self, pedido):
        self.chamadas += 1
        return Resposta(self.dados, self.nome, self.provedor, custo_usd=self.custo, custo_fonte="teste",
                        erro=self.erro, recusou=self.recusou)  # fmt: skip


def pedido(pessoal=False):
    return Pedido("teste.cascata", "sistema", "texto do dono", ESQUEMA, cod_imovel="PA-C-1", pessoal=pessoal)


def test_acordo_nao_chama_juiz():
    juiz = Falso("C", {"intencao": "aceita", "area_ha": 10})
    r = Cascata(Falso("A", {"intencao": "Aceita ", "area_ha": 10}), Falso("B", {"intencao": "aceita", "area_ha": 10}),
                juiz).decidir(pedido())  # fmt: skip
    assert r.via == "acordo" and juiz.chamadas == 0 and r.custo_usd == Decimal("0.002")


def test_tolerancia_numerica():
    cmp = comparador_por_campos(["intencao", "area_ha"], tolerancia=0.5)
    assert cmp({"intencao": "a", "area_ha": 10.0}, {"intencao": "a", "area_ha": 10.4})
    assert not cmp({"intencao": "a", "area_ha": 10.0}, {"intencao": "a", "area_ha": 10.6})


def test_juiz_desempata_com_um_dos_votos():
    r = Cascata(Falso("A", {"intencao": "aceita", "area_ha": 10}), Falso("B", {"intencao": "recusa", "area_ha": 10}),
                Falso("C", {"intencao": "recusa", "area_ha": 10})).decidir(pedido())  # fmt: skip
    assert r.via == "juiz" and r.dados["intencao"] == "recusa" and r.custo_usd == Decimal("0.003")


def test_juiz_com_voto_faltando():
    # o modelo local caiu: o B vota, o C confere
    r = Cascata(Falso("A", erro="llama.cpp fora do ar"), Falso("B", {"intencao": "aceita", "area_ha": 3}),
                Falso("C", {"intencao": "aceita", "area_ha": 3})).decidir(pedido())  # fmt: skip
    assert r.via == "juiz"


def test_sem_voto_valido_vai_para_revisao_salvo_se_permitido():
    a, b = Falso("A", erro="x"), Falso("B", recusou=True, erro="recusa")
    c = Falso("C", {"intencao": "aceita", "area_ha": 3})
    assert Cascata(a, b, c).decidir(pedido()).via == "revisao"
    assert Cascata(a, b, c, juiz_decide_sozinho=True).decidir(pedido()).via == "juiz"


def test_juiz_discorda_dos_dois_vai_para_revisao():
    r = Cascata(Falso("A", {"intencao": "aceita", "area_ha": 1}), Falso("B", {"intencao": "recusa", "area_ha": 1}),
                Falso("C", {"intencao": "duvida", "area_ha": 1})).decidir(pedido())  # fmt: skip
    assert r.via == "revisao" and r.dados is None


@pytest.mark.banco
def test_grava_decisao_e_revisao(banco_url):
    eng = create_engine(banco_url)
    with eng.begin() as con:
        con.execute(text("truncate operacao.decisao_cascata, operacao.fila_revisao, operacao.chamada_modelo cascade"))
        cas = Cascata(
            Falso("A", {"intencao": "aceita", "area_ha": 1}), Falso("B", {"intencao": "recusa", "area_ha": 1})
        )
        r = cas.decidir(pedido(), con)
        assert r.via == "revisao" and r.revisao_id and r.decisao_id
        fila = con.execute(text("select * from operacao.fila_revisao where id = :i"), {"i": r.revisao_id}).one()
        assert fila.estado == "aberta" and fila.conteudo["respostas"]["A"]["dados"]["intencao"] == "aceita"
        assert con.execute(text("select count(*) from operacao.chamada_modelo")).scalar() == 2
        resolver_revisao(con, r.revisao_id, {"intencao": "recusa", "area_ha": 1}, "fundador")
        fila = con.execute(text("select * from operacao.fila_revisao where id = :i"), {"i": r.revisao_id}).one()
        assert fila.estado == "resolvida" and fila.resolvida_por == "fundador" and fila.resolvida_em is not None
        with pytest.raises(ValueError):
            resolver_revisao(con, r.revisao_id, {}, "fundador")
        # pedido com dado pessoal: nada da conversa fica na operação
        r2 = cas.decidir(pedido(pessoal=True), con)
        d = con.execute(text("select respostas, decisao from operacao.decisao_cascata where id = :i"),
                        {"i": r2.decisao_id}).one()  # fmt: skip
        assert d.respostas is None and d.decisao is None
        f2 = con.execute(text("select conteudo from operacao.fila_revisao where id = :i"), {"i": r2.revisao_id}).one()
        assert "mensagem" not in f2.conteudo and "aviso" in f2.conteudo
    eng.dispose()
