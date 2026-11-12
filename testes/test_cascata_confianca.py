"""Cascata por confiança, rota do modelo local e teste próprio em português (E7 passo 10), com modelos simulados."""

import json
import math
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from raiz.agentes import aceite
from raiz.modelos import avaliacao as AV
from raiz.modelos import rota
from raiz.modelos.base import Pedido, Resposta
from raiz.modelos.cascata import Cascata
from raiz.modelos.confianca import confianca
from raiz.modelos.local import LlamaCpp
from raiz.modelos.simulado import Simulado

LIVRE = {
    "type": "object",
    "properties": {"resumo": {"type": "string"}},
    "required": ["resumo"],
    "additionalProperties": False,
}


class Falso:
    def __init__(self, nome, dados=None, conf=None, erro=None, provedor="teste"):
        self.nome, self.provedor = nome, provedor
        self.dados, self.conf, self.erro = dados, conf, erro
        self.chamadas = 0

    def responder_json(self, pedido):
        self.chamadas += 1
        return Resposta(self.dados, self.nome, self.provedor, custo_usd=Decimal("0.001"), custo_fonte="teste",
                        erro=self.erro, confianca=self.conf)  # fmt: skip


def cortes(corte=0.8, modelo="qwen-teste"):
    return {"versao": "cortes+teste", "modelo_local": modelo, "cortes": {"aceite.intencao": {"corte": corte}}}


def test_rota_so_classificacao_curta_vai_ao_local():
    pol = rota.politica()
    assert pol["versao"].startswith("cascata-")
    assert rota.cabe_no_local(aceite.pedido_intencao("sim"), pol) == (True, "classificação curta")
    prop = {"area_ha": 12, "prazo_anos": 30, "pagamento": "anual"}
    assert rota.cabe_no_local(aceite.pedido_explicacao(prop, "entendi"), pol)[0]
    ok, motivo = rota.cabe_no_local(Pedido("t", "s", "m", LIVRE, max_tokens=200), pol)
    assert not ok and "resumo" in motivo
    p = aceite.pedido_intencao("sim")
    assert rota.cabe_no_local(Pedido(p.tarefa, p.sistema, p.mensagem, p.esquema, max_tokens=2048), pol)[0] is False
    ok, motivo = rota.cabe_no_local(Pedido(p.tarefa, p.sistema, p.mensagem, p.esquema, ferramentas=3), pol)
    assert not ok and "ferramenta" in motivo
    so_nuvem = {**pol, "local": {**pol["local"], "so_nuvem": ["aceite.intencao"]}}
    assert rota.cabe_no_local(p, so_nuvem)[0] is False
    # cortes de outro modelo local não valem
    assert rota.corte_da_tarefa("aceite.intencao", cortes(0.7)) == 0.7
    assert rota.corte_da_tarefa("aceite.intencao", cortes(0.7), "qwen-teste") == 0.7
    assert rota.corte_da_tarefa("aceite.intencao", cortes(0.7), "outro-gguf") is None
    assert rota.corte_da_tarefa("aceite.explicacao", cortes(0.7)) is None


def _tok(t, p):
    return {"token": t, "logprob": math.log(p), "bytes": list(t.encode())}


def test_confianca_vem_dos_tokens_dos_valores():
    toks = [_tok('{"', 0.5), _tok("intenc", 0.99), _tok("ao", 0.99), _tok('":', 0.9), _tok(' "', 0.95),
            _tok("ace", 0.72), _tok("ita", 0.98), _tok('"}', 0.999)]  # fmt: skip
    # a moldura do JSON ({", nomes, aspas) fica de fora: vale o menor token do valor
    assert confianca(toks, {"intencao": "aceita"}) == pytest.approx(0.72)
    toks = [_tok('{"a":', 0.4), _tok("true", 0.61), _tok(',"b":', 0.99), _tok(" false", 0.93), _tok("}", 1.0)]
    assert confianca(toks, {"a": True, "b": False}) == pytest.approx(0.61)
    assert confianca(None, {"a": True}) is None and confianca(toks, {"zz": 1}) is None
    # acento: o token pode cortar um caractere ao meio (bytes)
    txt = '{"intencao": "dúvida"}'.encode()
    k = txt.index("ú".encode()) + 1
    partes = [txt[:k], txt[k:]]
    toks = [{"token": "", "logprob": math.log(0.66), "bytes": list(partes[0])},
            {"token": "", "logprob": math.log(0.9), "bytes": list(partes[1])}]  # fmt: skip
    assert confianca(toks, {"intencao": "dúvida"}) == pytest.approx(0.66)


def test_llama_pede_logprobs_e_devolve_a_confianca():
    corpo = {}
    conteudo = '{"intencao": "recusa"}'

    def responder(req):
        corpo.update(json.loads(req.content))
        toks = [_tok('{"intencao": "', 0.97), _tok("rec", 0.81), _tok("usa", 0.99), _tok('"}', 1.0)]
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": conteudo},
                                                       "logprobs": {"content": toks}}],
                                         "usage": {"prompt_tokens": 50, "completion_tokens": 8}})  # fmt: skip

    cliente = httpx.Client(transport=httpx.MockTransport(responder))
    m = LlamaCpp(url="http://llama", modelo="qwen-teste", cliente=cliente)
    r = m.responder_json(aceite.pedido_intencao("não quero"))
    assert corpo["logprobs"] is True and corpo["temperature"] == 0
    assert corpo["response_format"]["json_schema"]["schema"] == aceite.ESQ_INTENCAO
    assert r.ok and r.dados == {"intencao": "recusa"} and r.confianca == pytest.approx(0.81)


def test_cascata_por_confianca_so_sobe_quem_tem_duvida():
    p = aceite.pedido_intencao("pode mandar")
    a = Falso("qwen-teste", {"intencao": "aceita"}, conf=0.93, provedor="local")
    b, c = Falso("B", {"intencao": "aceita"}), Falso("C", {"intencao": "aceita"})
    r = Cascata(a, b, c, cortes=cortes(0.8)).decidir(p)
    assert r.via == "confianca" and b.chamadas == 0 and r.confianca == 0.93 and r.corte == 0.8
    assert r.rota == "local" and r.custo_usd == Decimal("0.001") and "cortes+teste" in r.versao
    # abaixo do corte: sobe para a votação com o Haiku
    a.conf = 0.55
    r = Cascata(a, b, c, cortes=cortes(0.8)).decidir(p)
    assert r.via == "acordo" and b.chamadas == 1 and r.confianca == 0.55
    # sem corte da tarefa, ou corte de outro modelo: votação, como antes
    a.conf = 0.99
    assert Cascata(a, b, c, cortes={"versao": "x", "cortes": {}}).decidir(p).via == "acordo"
    assert Cascata(a, b, c, cortes=cortes(0.5, modelo="outro")).decidir(p).via == "acordo"
    # A sem confiança (sem logprobs) também vota
    assert (
        Cascata(Falso("qwen-teste", {"intencao": "aceita"}, provedor="local"), b, c, cortes=cortes()).decidir(p).via
        == "acordo"
    )


def test_tarefa_longa_ou_com_ferramenta_vai_para_a_nuvem():
    p = Pedido("relatorio.resumo", "sistema", "texto longo", LIVRE, max_tokens=1500)
    a = Falso("qwen-teste", {"resumo": "x"}, conf=0.99, provedor="local")
    b, c = Falso("B", {"resumo": "do haiku"}), Falso("C", {"resumo": "do sonnet"})
    r = Cascata(a, b, c, cortes=cortes()).decidir(p)
    assert r.via == "direto" and r.dados == {"resumo": "do haiku"} and a.chamadas == 0 and c.chamadas == 0
    assert r.rota == "nuvem" and r.confianca is None
    r = Cascata(a, Falso("B", erro="fora do ar"), c, cortes=cortes()).decidir(p)
    assert r.via == "direto" and r.dados == {"resumo": "do sonnet"} and set(r.respostas) == {"B", "C"}
    r = Cascata(a, Falso("B", erro="x"), Falso("C", erro="y"), cortes=cortes()).decidir(p)
    assert r.via == "revisao" and r.dados is None
    # o Falso de outro provedor não é o modelo local: a rota não se aplica
    r = Cascata(Falso("A", {"resumo": "x"}), Falso("B", {"resumo": "x"}), c, cortes=cortes()).decidir(p)
    assert r.via == "acordo"


def test_banco_proprio_em_portugues():
    meta, ts = AV.carregar()
    assert 30 <= len(ts) <= 200 and meta["versao"].startswith("banco-pt-")
    assert len({t.id for t in ts}) == len(ts)
    sem = [t for t in ts if t.sem_resposta]
    assert round(len(sem) / len(ts), 2) == 0.15
    assert {t.esperado["intencao"] for t in sem if t.tarefa == "aceite.intencao"} == {"outro"}
    assert all(not any(t.esperado.values()) for t in sem if t.tarefa == "aceite.explicacao")
    # o teste usa o prompt de produção
    t = next(t for t in ts if t.tarefa == "aceite.intencao")
    assert AV.pedido(t).sistema == aceite.SISTEMA_INTENCAO and AV.pedido(t).esquema == aceite.ESQ_INTENCAO
    t = next(t for t in ts if t.tarefa == "aceite.explicacao")
    assert AV.pedido(t).sistema == aceite.sistema_explicacao(t.proposta)
    assert {x.tarefa for x in ts} == {"aceite.intencao", "aceite.explicacao"}
    from raiz.privacidade import mascarar

    assert all(mascarar(x.mensagem) == x.mensagem for x in ts)  # nenhum CPF ou CNPJ


class Alternado:
    """Acerta a intenção nas tentativas ímpares e erra nas pares: pega a consistência das 3 tentativas."""

    nome, provedor = "alternado", "teste"

    def __init__(self):
        self.n = 0

    def responder_json(self, pedido):
        self.n += 1
        rot = "aceita" if self.n % 2 else "recusa"
        return Resposta({"intencao": rot}, self.nome, self.provedor, confianca=0.5)


def test_tres_tentativas_seguidas_e_resumo():
    _, ts = AV.carregar()
    aceitas = [t for t in ts if t.esperado.get("intencao") == "aceita"][:4]
    linhas = AV.avaliar(Alternado(), aceitas, 3, chamar=lambda m, p: m.responder_json(p))
    assert len(linhas) == 12 and [x["tentativa"] for x in linhas[:3]] == [1, 2, 3]
    res = AV.resumo(linhas)["aceite.intencao"]
    assert res["tarefas"] == 4 and res["consistencia"] == 0.0 and res["acerto_nas_tentativas"] == 0.0
    assert 0 < res["acerto"] < 1 and res["abstencao_correta"] is None


def _linhas(pares):
    return [{"tarefa": "t", "confianca": c, "acerto": ok, "erro": None} for c, ok in pares]


def test_calibra_o_corte_na_faixa_de_subida():
    # 100 respostas: entre as 25 menos confiantes, as 5 do topo erram; acima delas, 1 erro em 75
    pares = [(0.30 + i * 0.01, i < 20) for i in range(25)] + [(0.60 + i * 0.004, i != 40) for i in range(75)]
    cal = AV.calibrar(_linhas(pares))["t"]
    assert cal["corte"] is not None and 0.20 <= cal["subida"] <= 0.30 and cal["acerto_que_fica"] >= 0.95
    # dentro da faixa, fica o corte com mais acerto no que não sobe
    assert cal["corte"] == pytest.approx(0.60) and cal["subida"] == 0.25
    # acerto baixo demais: sem corte, a tarefa fica na votação
    ruim = AV.calibrar(_linhas([(i / 100, i % 3 != 0) for i in range(100)]))["t"]
    assert ruim["corte"] is None and "abaixo" in ruim["motivo"]
    assert AV.calibrar(_linhas(pares[:10]))["t"]["corte"] is None  # poucas respostas
    sem = [{"tarefa": "t", "confianca": None, "acerto": True, "erro": None}] * 40
    assert "logprobs" in AV.calibrar(sem)["t"]["motivo"]
    # respostas com erro contam como subida
    com_falha = _linhas(pares[25:]) + [{"tarefa": "t", "confianca": None, "acerto": False, "erro": "x"}] * 25
    assert AV.calibrar(com_falha)["t"]["subida"] >= 0.25


def test_simulado_de_ponta_a_ponta_e_calibrar_so_grava_o_local(tmp_path):
    from raiz.cli import app

    meta, ts = AV.carregar()
    m = Simulado()
    linhas = AV.avaliar(m, ts, 3, chamar=lambda mo, p: mo.responder_json(p))
    rel = AV.relatorio(meta, m, linhas, 3)
    assert rel["resumo"]["aceite.intencao"]["respostas"] == 240
    arq = AV.gravar_relatorio(rel, tmp_path)
    run = CliRunner().invoke(app, ["modelos", "calibrar", "--relatorio", str(arq)])
    assert run.exit_code == 1 and "não gravei" in run.output
    destino = tmp_path / "cortes.yaml"
    run = CliRunner().invoke(app, ["modelos", "calibrar", "--relatorio", str(arq), "--cortes", str(destino)])
    assert run.exit_code == 0, run.output
    cs = rota.cortes(destino)
    assert cs["modelo_local"] == "simulado-regras-1" and cs["banco"] == meta["versao"]
    for t, c in cs["cortes"].items():
        assert 0.20 <= c["subida"] <= 0.30 and c["acerto_que_fica"] >= 0.95, t
    # o arquivo de produção continua sem corte até a rodada no Qwen de verdade
    assert rota.cortes()["cortes"] == {}


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    yield e
    e.dispose()


@pytest.mark.banco
def test_decisao_guarda_rota_confianca_e_versao(eng):
    p = Pedido("teste.confianca", aceite.SISTEMA_INTENCAO, "pode mandar", aceite.ESQ_INTENCAO, cod_imovel="PA-CF-1",
               max_tokens=200)  # fmt: skip
    a = Falso("qwen-teste", {"intencao": "aceita"}, conf=0.91, provedor="local")
    cs = {"versao": "cortes+teste", "modelo_local": "qwen-teste", "cortes": {"teste.confianca": {"corte": 0.8}}}
    with eng.begin() as con:
        r = Cascata(a, Falso("B", {"intencao": "aceita"}), None, cortes=cs).decidir(p, con)
        r2 = Cascata(a, Falso("B", {"resumo": "ok"}), None, cortes=cs).decidir(
            Pedido("teste.nuvem", "s", "m", LIVRE, cod_imovel="PA-CF-1", ferramentas=2), con
        )
        linhas = con.execute(
            text("""select via, rota, confianca, corte, regra_versao from operacao.decisao_cascata
                    where id in (:a, :b) order by id"""),
            {"a": r.decisao_id, "b": r2.decisao_id},
        ).all()
    assert linhas[0][:4] == ("confianca", "local", 0.91, 0.8) and linhas[0][4].endswith("|cortes+teste")
    assert linhas[1][:3] == ("direto", "nuvem", None)


@pytest.mark.banco
def test_alerta_quando_a_subida_sai_da_faixa(eng):
    import datetime as dt

    from raiz.operacao import alertas as AL

    agora = dt.datetime(2026, 11, 12, 15, 0, tzinfo=dt.UTC)
    with eng.begin() as con:
        con.execute(text("delete from operacao.decisao_cascata where tarefa like 'teste.deriva%'"))
        for k in range(60):  # 45 de 60 subiram (75%): bem acima de 30% + 15 pontos
            con.execute(
                text("""insert into operacao.decisao_cascata (tarefa, entrada_hash, via, rota, confianca, corte,
                        criado_em) values ('teste.deriva', 'h', :v, 'local', 0.5, 0.8, :t)"""),
                {"v": "confianca" if k < 15 else "acordo", "t": agora - dt.timedelta(days=1)},
            )
        for k in range(60):  # 15 de 60 (25%): dentro da faixa, sem alerta
            con.execute(
                text("""insert into operacao.decisao_cascata (tarefa, entrada_hash, via, rota, confianca, corte,
                        criado_em) values ('teste.deriva_ok', 'h', :v, 'local', 0.5, 0.8, :t)"""),
                {"v": "acordo" if k < 15 else "confianca", "t": agora - dt.timedelta(days=1)},
            )
        novos = AL._cascata(con, AL.politica()["regras"], agora)
    chaves = {n.chave for n in novos}
    assert "cascata_faixa:teste.deriva" in chaves and "cascata_faixa:teste.deriva_ok" not in chaves
    n = next(n for n in novos if n.chave == "cascata_faixa:teste.deriva")
    assert n.gravidade == "aviso" and "75%" in n.titulo and "raiz modelos calibrar" in n.texto
