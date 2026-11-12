"""Leitor de certidão: regras, conferência com o certidoes_<mun>.csv, leitura simulada de ponta a ponta e saída."""

import datetime as dt
import json
import sqlite3

import pandas as pd
import pytest

from raiz.documentos.armazem import Armazem
from raiz.documentos.certidao import esquema, saida
from raiz.documentos.certidao.conferencia import conferir
from raiz.documentos.certidao.leitor import ler_certidao, reconferir
from raiz.documentos.certidao.regras import area_ha, derivar, normalizar_ato, normalizar_cns, normalizar_matricula
from raiz.documentos.claude import LeitorClaude
from raiz.documentos.config import REPO
from raiz.documentos.simulacao import ClienteSimulado, cpf_ficticio, leitura_exemplo, pdf_exemplo

HOJE = dt.date(2026, 11, 12)
IMOVEL = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"  # na amostra: 06.842-9 / 5178 (268,5 ha) e 5177 (31,9 ha)


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "docs"))
    monkeypatch.setenv("RAIZ_DOCUMENTOS_ENTRADA", str(REPO / "dados" / "amostra"))


def _motor():
    return pd.DataFrame(
        dict(
            cod_imovel=[IMOVEL, IMOVEL],
            registro_cns=["06.842-9", "06.842-9"],
            registro_matricula=["5178", "5177"],
            ha_sobre_car=[268.5, 31.9],
            parcelas=[1, 1],
        )
    )


def _ler(dados, **kw):
    cli = ClienteSimulado([dados], modelo=kw.pop("modelo", "claude-opus-5-5"))
    leitor = LeitorClaude(modelo=cli.modelo, cliente=cli)
    r = ler_certidao(pdf_exemplo(json.dumps(dados)[:40]), leitor=leitor, hoje=HOJE, **kw)
    return r, cli


# --- regras ---------------------------------------------------------------------------------------------------------


def test_normalizacoes():
    assert normalizar_cns("06.842-9") == "068429"
    assert normalizar_cns(68429) == "068429"
    assert normalizar_matricula("Matrícula nº 5.178") == "5178"
    assert normalizar_matricula("005178") == "5178"
    assert normalizar_matricula(5178.0) == "5178"
    assert normalizar_matricula("1234-A") == "1234A"
    assert normalizar_ato("R.3") == "R-3" and normalizar_ato("Av-12/5178") == "AV-12"
    assert normalizar_ato("abertura") == "ABERTURA"


def test_area_em_hectares():
    assert area_ha(10, "alqueire_paulista") == 24.2
    assert area_ha(2, "alqueire_mineiro") == 9.68
    assert area_ha(25000, "m2") == 2.5
    assert area_ha(3, "tarefa") is None  # varia por região: gente confirma


def test_onus_cancelado_e_ativo():
    d = derivar(leitura_exemplo(), HOJE)
    assert d.onus_ativos == [] and d.onus_cancelados == 1
    d = derivar(leitura_exemplo(com_hipoteca_ativa=True), HOJE)
    assert [o["numero"] for o in d.onus_ativos] == ["R-2"]
    assert d.onus_ativos[0]["credor_instituicao"] == "Banco da Amazônia"
    assert not d.onus_graves


def test_cadeia_e_quebra():
    dados = leitura_exemplo()
    d = derivar(dados, HOJE)
    assert d.n_transmissoes == 1 and d.quebras_cadeia == []
    assert {p["rotulo"] for p in d.proprietarios_atuais} == {"P2", "P3"} and d.proprietarios_conferem
    dados["atos"].append(
        dict(
            numero="R-6",
            tipo="registro",
            data="2021-01-01",
            natureza="compra_e_venda",
            afeta="propriedade",
            transmitentes=["P9"],
            adquirentes=["P5"],
            fracao_pct=None,
            cancela=[],
            area_valor=None,
            area_unidade=None,
            matricula_destino=None,
            pagina=3,
            resumo="P9 vende a P5",
        )
    )
    d = derivar(dados, HOJE)
    assert d.quebras_cadeia and d.quebras_cadeia[0]["numero"] == "R-6"


def test_encerrada_vira_cancelada_e_bloqueio_e_grave():
    d = derivar(leitura_exemplo(encerrada=True), HOJE)
    assert d.situacao_documento == "cancelada" and d.matricula_destino == "9.001"
    dados = leitura_exemplo()
    dados["atos"].append(
        dict(
            numero="AV-9",
            tipo="averbacao",
            data="2022-01-01",
            natureza="bloqueio_matricula",
            afeta="encerramento",
            transmitentes=[],
            adquirentes=[],
            fracao_pct=None,
            cancela=[],
            area_valor=None,
            area_unidade=None,
            matricula_destino=None,
            pagina=3,
            resumo="bloqueio por decisão da corregedoria",
        )
    )
    d = derivar(dados, HOJE)
    assert d.situacao_documento == "bloqueada" and d.onus_graves


# --- conferência ----------------------------------------------------------------------------------------------------


def _conf(dados, motor=None, **kw):
    return conferir(dados, derivar(dados, HOJE), _motor() if motor is None else motor, hoje=HOJE, **kw)


def test_conferida():
    [c] = _conf(leitura_exemplo())
    assert c.situacao == "conferida" and c.cod_imovel == IMOVEL and c.motor_ha_sobre_car == 268.5


def test_divergente_por_area_cartorio_numero_e_fora_do_motor():
    [c] = _conf(leitura_exemplo(area_valor=100))
    assert c.situacao == "divergente" and "tem 100,0 ha, menos que os 268,5 ha" in c.resumo()
    [c] = _conf(leitura_exemplo(cns="06.999-1"))
    assert c.situacao == "divergente" and "cartório diferente" in c.resumo()
    [c] = _conf(leitura_exemplo(matricula="777"), cod_imovel=IMOVEL)
    assert c.situacao == "divergente" and "5177, 5178" in c.resumo()
    [c] = _conf(leitura_exemplo(matricula="777"))
    assert c.situacao == "divergente" and c.cod_imovel is None


def test_cancelada_e_revisar():
    [c] = _conf(leitura_exemplo(encerrada=True))
    assert c.situacao == "cancelada" and "9.001" in c.resumo()
    dados = leitura_exemplo()
    dados["documento"]["tipo_documento"] = "nao_e_certidao"
    [c] = _conf(dados)
    assert c.situacao == "revisar"


def test_alqueire_e_pedidos_de_confirmacao():
    # 120 alqueires paulistas = 290,4 ha: bate com a parcela
    [c] = _conf(leitura_exemplo(area_valor=120, area_unidade="alqueire_paulista"))
    assert c.situacao == "conferida" and c.area_matricula_ha == pytest.approx(290.4)
    dados = leitura_exemplo(data_emissao="2026-08-01")
    dados["matricula"]["origem"] = "desconhecida"
    dados["cartorio"]["cns"] = None
    [c] = _conf(dados)
    codigos = {m.codigo for m in c.motivos}
    assert {"origem_para", "sem_cns", "certidao_antiga"} <= codigos and c.situacao == "conferida"
    assert c.precisa_confirmar


# --- esquema ----------------------------------------------------------------------------------------------------


def _objetos(s):
    if isinstance(s, dict):
        if s.get("type") == "object":
            yield s
        for v in s.values():
            yield from _objetos(v)
    elif isinstance(s, list):
        for v in s:
            yield from _objetos(v)


def test_esquema_serve_para_saida_estruturada():
    for o in _objetos(esquema.ESQUEMA):
        assert o["additionalProperties"] is False
        assert set(o["required"]) == set(o["properties"])
    texto = json.dumps(esquema.ESQUEMA)
    assert '"nome"' not in json.dumps(esquema.PARTE)  # parte não tem campo de nome de pessoa
    assert "nome_instituicao" in texto


def test_versao_do_prompt_muda_com_o_texto(monkeypatch):
    v = esquema.versao_prompt()
    monkeypatch.setattr(esquema, "SISTEMA", esquema.SISTEMA + " ")
    assert esquema.versao_prompt() != v


# --- ponta a ponta ----------------------------------------------------------------------------------------------


def test_leitura_simulada_grava_sem_nome_nem_cpf(tmp_path):
    r, cli = _ler(leitura_exemplo(com_nomes=True), cod_imovel=IMOVEL)
    assert r.situacao == "conferida"
    kw = cli.chamadas[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["effort"] == "high"
    assert kw["messages"][0]["content"][0]["type"] == "document"
    # nada de nome nem CPF inteiro em lugar nenhum do armazém
    banco = (tmp_path / "docs" / "documentos.sqlite").read_bytes()
    for proibido in ("Fulano", "Beltrana", cpf_ficticio()):
        assert proibido.encode() not in banco
    partes = r.leitura.dados["partes"]
    assert partes[0]["documento"] == "***.456.789-**" and partes[0]["nome_instituicao"] is None
    assert partes[3]["nome_instituicao"] == "Banco da Amazônia"


def test_modelo_sem_reserva_usa_messages_stream():
    r, cli = _ler(leitura_exemplo(), modelo="claude-haiku-5-5", cod_imovel=IMOVEL)
    assert "fallbacks" not in cli.chamadas[0] and r.leitura.modelo == "claude-haiku-5-5"


def test_recusa_vira_leitura_com_erro():
    r, _ = _ler({"stop_reason": "refusal", "dados": {}}, cod_imovel=IMOVEL)
    assert r.erro.startswith("recusa") and r.conferencias == []
    assert Armazem().leitura(r.leitura.id).erro == r.erro


def test_leitura_e_imutavel_e_prova_o_hash():
    r, _ = _ler(leitura_exemplo(), cod_imovel=IMOVEL)
    arm = Armazem()
    assert arm.conferir_hash(r.leitura.id)
    with arm.con() as c, pytest.raises(sqlite3.IntegrityError, match="imutável"):
        c.execute("update leitura set modelo = 'outro' where id = ?", (r.leitura.id,))


def test_reconferir_sem_nova_leitura():
    r, cli = _ler(leitura_exemplo(), cod_imovel=IMOVEL)
    r2 = reconferir(r.leitura.id, hoje=HOJE)
    assert r2.situacao == "conferida" and len(cli.chamadas) == 1


def test_saida_do_municipio_liga_o_selo_do_front():
    _ler(leitura_exemplo(), cod_imovel=IMOVEL)
    a, b = saida.gravar_municipio(1504950)
    imv = pd.read_csv(b).set_index("cod_imovel").loc[IMOVEL]
    assert imv.matriculas_total == 2 and imv.matriculas_lidas == 1 and imv.matricula_situacao == "a_conferir"
    assert pd.isna(imv.matricula_conferida)  # falta ler a 5177
    _ler(leitura_exemplo(matricula="5177", area_valor=40), cod_imovel=IMOVEL)
    a, b = saida.gravar_municipio(1504950)
    imv = pd.read_csv(b).set_index("cod_imovel").loc[IMOVEL]
    assert bool(imv.matricula_conferida) is True and imv.matricula_situacao == "conferida"
    conf = pd.read_csv(a)
    assert {"situacao", "motivo", "leitura_id", "modelo", "regras_versao"} <= set(conf.columns)
    _ler(leitura_exemplo(encerrada=True), cod_imovel=IMOVEL)
    imv = saida.por_imovel(saida.conferencias_do_municipio(1504950)).set_index("cod_imovel").loc[IMOVEL]
    assert imv.matricula_conferida is False or imv.matricula_conferida == False  # noqa: E712
    assert imv.matricula_situacao == "cancelada"


def test_leitura_manual_vira_modelo_humano():
    r = ler_certidao(pdf_exemplo("manual"), cod_imovel=IMOVEL, json_manual=leitura_exemplo(), hoje=HOJE)
    assert r.leitura.modelo == "humano" and r.situacao == "conferida"
    with pytest.raises(ValueError, match="fora do esquema"):
        ler_certidao(pdf_exemplo("x"), json_manual={"documento": {}}, hoje=HOJE)
