"""Alertas de operação com escalonamento (E7 passo 9) e backoffice do fundador (E7 passo 6), só leitura."""

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, text

from raiz.operacao import alertas as A
from raiz.operacao import backoffice as B

AGORA = dt.datetime(2026, 11, 12, 15, 0, tzinfo=dt.UTC)
TOKEN = "token-backoffice-teste"


class VigilanciaFalsa:
    """Vigilância atrasada, uma fonte com erro e um evento de perda com o aviso à Verra vencendo."""

    projetos = {"URTX": object()}

    def __init__(self, atrasada=True):
        self.atrasada = atrasada

    def saude(self, hoje):
        return {
            "ultima_rodada": "2026-11-09T09:20:00+00:00" if self.atrasada else hoje.isoformat(),
            "dias_desde_a_ultima": 3 if self.atrasada else 0,
            "fontes": {"deter": {"situacao": "erro", "erro": "500 em https://x"}, "firms": {"situacao": "ok"}},
        }

    def perdas(self, pid, hoje):
        pe = {
            "perda_id": "URTX_LE1",
            "estado": "suspeita",
            "prazo": {
                "aviso_verra_ate": dt.date(2026, 11, 15),
                "aviso_verra_dias_restantes": 3,
                "aviso_verra_situacao": "urgente",
                "relatorio_ate": dt.date(2028, 10, 16),
                "relatorio_situacao": "no_prazo",
            },
        }
        return [pe], None

    def avisos(self, estado, hoje):
        return [{"aviso_id": "a1"}]


class EnviadorFalso(A.Enviador):
    def __init__(self, segunda=False):
        self.enviados = []
        self.segunda = segunda

    def ntfy(self, titulo, texto, prioridade, tags):
        self.enviados.append(("ntfy", prioridade, titulo))
        return "simulado"

    def segunda_pessoa(self, titulo, texto):
        if not self.segunda:
            return None
        self.enviados.append(("goalert", None, titulo))
        return "enviado"


def test_politica_versionada_e_escada():
    p = A.politica()
    assert p["versao"].startswith(p["nome"] + "+")
    t0 = AGORA
    assert A.nivel_devido(t0, "critico", t0, p) == 0
    assert A.nivel_devido(t0, "critico", t0 + dt.timedelta(minutes=31), p) == 1
    assert A.nivel_devido(t0, "critico", t0 + dt.timedelta(hours=3), p) == 2
    assert A.nivel_devido(t0, "urgente", t0 + dt.timedelta(hours=3), p) == 1  # urgente não chama a segunda pessoa
    assert A.nivel_devido(t0, "aviso", t0 + dt.timedelta(days=3), p) == 0  # aviso só sai uma vez


def test_envio_sem_topico_e_simulado(monkeypatch):
    cfg = type("C", (), {"ntfy_topico": None, "ntfy_token": None, "ntfy_url": "https://ntfy.sh", "goalert_url": None})()
    monkeypatch.setattr(A, "config", lambda: cfg)
    e = A.Enviador()
    assert e.ntfy("t", "x", 3, []) == "simulado" and e.segunda_pessoa("t", "x") is None


@pytest.fixture(scope="module")
def eng(banco_url):
    e = create_engine(banco_url)
    with e.begin() as c:
        c.execute(text("truncate operacao.alerta, operacao.lote, operacao.fila_revisao cascade"))
        c.execute(text("truncate operacao.chamada_modelo, operacao.decisao_cascata"))
    yield e
    e.dispose()


@pytest.mark.banco
def test_coleta_registra_escala_e_fecha_sozinho(eng, monkeypatch):
    cfg = type("C", (), {"orcamento_mensal_usd": 10.0})()
    monkeypatch.setattr(A, "config", lambda: cfg)
    with eng.begin() as c:
        c.execute(text("""insert into operacao.lote (tarefa, uf, cod_municipio, rid, estado, iniciado_em, log_final)
                          values ('funil', 'PA', 1504950, gen_random_uuid(), 'falha', :a, 'erro no fim'),
                                 ('carga', 'PA', 1507300, gen_random_uuid(), 'iniciado', :b, null)"""),
                  {"a": AGORA - dt.timedelta(hours=2), "b": AGORA - dt.timedelta(hours=9)})  # fmt: skip
        c.execute(text("""insert into operacao.chamada_modelo (tarefa, cod_imovel, provedor, modelo, ok, custo_usd,
                          criado_em) values ('aceite.intencao', 'PA-1504950-X', 'anthropic', 'claude-haiku-5-5', true,
                          9.0, :a)"""), {"a": AGORA - dt.timedelta(hours=1)})  # fmt: skip
        c.execute(text("""insert into operacao.fila_revisao (tarefa, chave, motivo, conteudo, criado_em)
                          values ('aceite.intencao', 'PA-1504950-X', 'desacordo', '{}', :a)"""),
                  {"a": AGORA - dt.timedelta(hours=30)})  # fmt: skip
    vig = VigilanciaFalsa()
    novos, olhadas = A.coletar(eng, AGORA, vig)
    origens = {n.origem for n in novos}
    assert {"lote_falhou", "lote_travado", "orcamento", "vigilancia_atrasada", "vigilancia_fonte", "verra_prazo",
            "revisao_parada"} <= origens  # fmt: skip
    verra = next(n for n in novos if n.origem == "verra_prazo")
    assert verra.gravidade == "critico" and "15/11/2026" in verra.titulo
    assert next(n for n in novos if n.origem == "orcamento").gravidade == "aviso"  # 90% do orçamento
    env = EnviadorFalso()
    with eng.begin() as c:
        r = A.registrar(c, novos, olhadas)
        assert r["abertos"] == len(novos)
        assert A.registrar(c, novos, olhadas)["abertos"] == 0  # o mesmo problema não abre outro alerta
        primeiro = A.escalar(c, AGORA, env)
    assert len(primeiro) == len(novos) and all(e["nivel"] == 0 for e in primeiro)
    assert {e["estado"] for e in primeiro} == {"simulado"}
    # 40 minutos depois: urgente e crítico sobem para ntfy urgente; aviso fica
    with eng.begin() as c:
        segundo = A.escalar(c, AGORA + dt.timedelta(minutes=40), env)
    graves = {n.chave for n in novos if n.gravidade in ("urgente", "critico")}
    assert len(segundo) == len(graves) and all(e["nivel"] == 1 for e in segundo)
    assert all(p == 5 for canal, p, _ in env.enviados[-len(segundo) :])
    # reconhecido não sobe mais; sem segunda pessoa, o crítico volta urgente para o fundador
    with eng.begin() as c:
        idv = c.execute(text("select id from operacao.alerta where chave = 'verra_aviso:URTX_LE1'")).scalar()
        idf = c.execute(text("select id from operacao.alerta where chave = 'lote_travado:carga'")).scalar()
        assert A.reconhecer(c, idf, "fundador")
        terceiro = A.escalar(c, AGORA + dt.timedelta(hours=3), env)
    assert [e["alerta"] for e in terceiro] == [idv] and terceiro[0]["nivel"] == 2 and terceiro[0]["canal"] == "ntfy"
    # com segunda pessoa (GoAlert), o nível 2 vai para ela
    with eng.begin() as c:
        c.execute(text("update operacao.alerta set nivel = 1 where id = :i"), {"i": idv})
        quarto = A.escalar(c, AGORA + dt.timedelta(hours=3), EnviadorFalso(segunda=True))
    assert quarto[0]["canal"] == "segunda_pessoa" and quarto[0]["estado"] == "enviado"
    # a vigilância voltou: o alerta de atraso fecha sozinho; o lote que falhou (fato) continua aberto
    novos2, olhadas2 = A.coletar(eng, AGORA, VigilanciaFalsa(atrasada=False))
    with eng.begin() as c:
        A.registrar(c, novos2, olhadas2)
        abertos = {r[0] for r in c.execute(text("select chave from operacao.alerta where resolvido_em is null"))}
    assert "vigilancia_atrasada" not in abertos and any(k.startswith("lote_falhou:funil") for k in abertos)


@pytest.mark.banco
def test_backoffice_so_leitura_pela_api(eng, monkeypatch):
    from raiz.api import criar_app

    cfg = type("C", (), {"api_token": SecretStr(TOKEN), "api_origens": "", "orcamento_mensal_usd": 10.0})()
    import raiz.api as api_mod

    monkeypatch.setattr(api_mod, "config", lambda: cfg)
    monkeypatch.setattr(B, "config", lambda: cfg)
    app = criar_app(engine=eng, grafo=object(), deps=object(), whatsapp=False)
    h = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(app) as cl:
        assert cl.get("/backoffice/resumo").status_code == 401
        pagina = cl.get("/painel/backoffice")
        assert pagina.status_code == 200 and "token da API" in pagina.text  # a página não traz dado
        r = cl.get("/backoffice/resumo", headers=h).json()
        assert r["saude"]["banco"] is True and r["custo"]["orcamento_usd"] == 10.0
        assert r["custo"]["gasto_usd"] >= 9.0 and r["filas"]["revisoes_abertas"] >= 1
        assert r["alertas"] and all("texto" in a for a in r["alertas"])
        f = cl.get("/backoffice/fazenda/PA-1504950-X", headers=h).json()
        assert f["custo_modelos_usd"] == 9.0 and f["chamadas_modelo"][0]["modelo"] == "claude-haiku-5-5"
        assert f["revisoes"][0]["motivo"] == "desacordo" and f["lotes_do_municipio"][0]["log_final"] == "erro no fim"
        assert cl.get("/backoffice/custos?por=fazenda", headers=h).json()[0]["chave"] == "PA-1504950-X"
        assert cl.get("/backoffice/custos?por=outra", headers=h).status_code == 422
        assert cl.get("/backoffice/lotes?estado=falha", headers=h).json()[0]["tarefa"] == "funil"
        aberto = cl.get("/backoffice/alertas", headers=h).json()[0]
        assert cl.post(f"/operacao/alertas/{aberto['id']}/resolver", json={"nota": "ok"}, headers=h).status_code == 200
        assert cl.post(f"/operacao/alertas/{aberto['id']}/resolver", json={}, headers=h).status_code == 404
        # nenhuma rota de escrita no backoffice
        assert cl.post("/backoffice/resumo", headers=h).status_code == 405
