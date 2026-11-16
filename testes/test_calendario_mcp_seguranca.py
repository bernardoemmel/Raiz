"""Função real de calendário: leitura adversarial e tempo, ainda sem transporte MCP.

Não há agente LLM neste caminho. A prova é da fronteira determinística:
coleta/importação → Postgres → proximos_eventos, sem transformar texto em ação.
"""

import datetime as dt
import json
import time
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, event, text

from raiz.calendario import arquivos, banco, coleta
from raiz.calendario.mcp import proximos_eventos
from testes.mcp.avaliacao import carregar_casos
from testes.mcp.latencia import prazo_real

AGORA = dt.datetime(2026, 11, 12, 10, tzinfo=dt.UTC)
CAR = "PA-1504950-" + "D" * 32


def _estado_negocio(engine):
    with engine.connect() as con:
        tabelas = con.execute(
            text("select tablename from pg_tables where schemaname='negocio' order by tablename")
        ).scalars()
        return {
            tabela: sorted(
                json.dumps(linha, sort_keys=True, default=str)
                for linha in con.execute(text(f'SELECT to_jsonb(t) FROM negocio."{tabela}" t')).scalars()
            )
            for tabela in tabelas
        }


@contextmanager
def _somente_leitura(engine):
    comandos = []

    def verificar(_con, _cursor, comando, _parametros, _contexto, _muitos):
        comandos.append(comando)
        assert comando.lstrip().lower().startswith("select "), "função de leitura tentou escrever no banco"

    event.listen(engine, "before_cursor_execute", verificar)
    try:
        yield comandos
    finally:
        event.remove(engine, "before_cursor_execute", verificar)


@pytest.mark.banco
@pytest.mark.parametrize("caso", carregar_casos(), ids=lambda c: c.id)
def test_proximos_eventos_real_nao_transforma_entrada_em_acao(caso, banco_url, tmp_path, monkeypatch):
    engine = create_engine(banco_url)
    f = next(f for f in coleta.fontes() if f["id"] == "djen")

    def proibido(*args, **kwargs):
        raise AssertionError("entrada não confiável tentou executar ação externa")

    # As entradas não precisam de rede nem shell. Os bloqueios observam tentativas,
    # sem disponibilizar credenciais de envio/pagamento nem executar ação real.
    monkeypatch.setattr("subprocess.Popen", proibido)
    monkeypatch.setattr("os.system", proibido)
    monkeypatch.setattr("requests.Session.request", proibido)
    monkeypatch.setattr("httpx.Client.request", proibido)
    monkeypatch.setattr("httpx.AsyncClient.request", proibido)
    monkeypatch.setattr("raiz.calendario.banco.avisar_pedidos", proibido)
    try:
        for variante in ("controle", "ataque"):
            entrada = getattr(caso, variante)
            texto_base = f"Edital de leilão rural nº 981/2026. CAR {CAR}. Leilão em 30/11/2026."
            corpo = texto_base if caso.fonte == "nome_arquivo" else texto_base + " " + entrada
            recebido = json.dumps({"items": [{"hash": "ADVERSARIALMCP001", "texto": corpo}]})
            eventos, _ = coleta.extrair(recebido, f, f["urls"][0], AGORA)
            assert len(eventos) == 1 and eventos[0].dia == dt.date(2026, 11, 30)
            # Usa o importador real. Nome com sintaxe de comando continua sendo
            # apenas nome de arquivo; barras de URL viram texto de metadado no JSON.
            nome = "edital_$(touch ACAO_INDEVIDA).json" if variante == "ataque" else "edital.json"
            arquivo = tmp_path / nome
            arquivo.write_text(
                json.dumps(
                    {
                        "eventos": [{**e.model_dump(mode="json"), "nome_arquivo": entrada} for e in eventos],
                        "fontes": [],
                    }
                ),
                encoding="utf-8",
            )
            importados, fontes = arquivos.ler(arquivo)
            assert all("nome_arquivo" not in e.model_dump() for e in importados)
            with engine.begin() as con:
                banco.gravar(con, importados, fontes, cruzar_imoveis=False)
            antes = _estado_negocio(engine)
            arquivos_antes = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
            with _somente_leitura(engine) as sql, prazo_real():
                inicio = time.monotonic()
                resultado = proximos_eventos(engine=engine, hoje=AGORA.date(), cod_imovel=CAR)
                duracao = time.monotonic() - inicio
            assert duracao < 5
            assert sql and resultado["total"] == 1
            assert resultado["eventos"][0]["data"] == "2026-11-30"
            assert resultado["eventos"][0]["situacao"] == "previsto"
            resposta = json.dumps(resultado)
            assert entrada not in resposta
            assert "preparar_reserva" not in resposta and "coletor.example.invalid" not in resposta
            assert _estado_negocio(engine) == antes
            assert {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()} == arquivos_antes
    finally:
        with engine.begin() as con:
            con.execute(text("delete from calendario.evento where fonte_url like '%ADVERSARIALMCP001%'"))
        engine.dispose()
