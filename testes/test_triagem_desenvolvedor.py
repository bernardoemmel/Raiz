"""Triagem em lote para o desenvolvedor: lista de CAR -> ranking com nota e motivo, CSV e PDF, API e MCP.
Dados sintéticos por coluna (nunca nome, CPF ou contato)."""

import io
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import SecretStr

from raiz.documentos.simulacao import cpf_ficticio
from raiz.triagem_desenvolvedor import dados as D
from raiz.triagem_desenvolvedor import entrada as E
from raiz.triagem_desenvolvedor import mcp as M
from raiz.triagem_desenvolvedor import nota as N
from raiz.triagem_desenvolvedor import relatorio as RL
from raiz.triagem_desenvolvedor import resumo, triar

COD = 1504950
CPF = cpf_ficticio()  # montado na hora: nunca escrito no arquivo


def car(letra: str) -> str:
    return f"PA-{COD}-{letra * 32}"


# A recomendada, B pequena e boa, C embargo, D já comprometida, E indício, F sem valor calculado, G risco alto
FAZENDAS = {
    "A": dict(ha=300, m_fiscal=2.0, custo=9.0, tir=14.0, credito=140, risco="baixo", caminho="privada_matricula"),
    "B": dict(ha=3.0, m_fiscal=0.1, custo=10.0, tir=13.0, credito=130, risco="baixo", caminho="privada_matricula"),
    "C": dict(
        ha=300,
        m_fiscal=3.0,
        custo=8.0,
        tir=15.0,
        credito=150,
        risco="baixo",
        caminho="privada_matricula",
        embargo_ha=12.5,
    ),  # fmt: skip
    "D": dict(
        ha=500,
        m_fiscal=5.0,
        custo=8.0,
        tir=15.0,
        credito=150,
        risco="baixo",
        caminho="privada_matricula",
        status="ja_comprometida",
        projeto="VCS665",
    ),  # fmt: skip
    "E": dict(
        ha=400,
        m_fiscal=4.0,
        custo=9.0,
        tir=14.0,
        credito=140,
        risco="baixo",
        caminho="privada_matricula",
        status="risco_sobreposicao",
    ),  # fmt: skip
    "F": dict(ha=200, m_fiscal=2.0, custo=None, tir=None, credito=None, risco="medio", caminho="posse_em_titulacao"),
    "G": dict(ha=250, m_fiscal=2.5, custo=20.0, tir=4.0, credito=40, risco="alto", caminho="posse_em_titulacao"),
}


@pytest.fixture
def pasta(tmp_path):
    uf = tmp_path / "saida" / "PA"
    uf.mkdir(parents=True)
    im, ds, tr, fl, cp = [], [], [], [], []
    for k, f in FAZENDAS.items():
        c = car(k)
        im.append(dict(cod_imovel=c, municipio="Nova Esperança do Piriá", uf="PA", cod_municipio_ibge=COD, ha=f["ha"],
                       m_fiscal=f["m_fiscal"], embargo_ha=f.get("embargo_ha", 0.0), ti_ha=0.0, desm_pos2020_ha=0.0,
                       alerta_ultimo_ano=0.0, proprietario="NOME QUE NUNCA SAI", cpf=CPF))  # fmt: skip
        if f["custo"] is not None:
            ds.append(dict(cod_imovel=c, modo_restauracao="regeneracao_assistida", restauracao_area_ha=f["ha"] * 0.5,
                           credito_liquido_tco2_ha_contrato_p50=f["credito"], custo_credito_usd=f["custo"],
                           tir_alavancada_pct_p50=f["tir"]))  # fmt: skip
        tr.append(dict(cod_imovel=c, caminho_terra=f["caminho"], risco_terra=f["risco"]))
        fl.append(dict(cod_imovel=c, uc_protecao_integral_ha=0.0, filtro_territorial="ok"))
        if "status" in f:
            cp.append(dict(cod_imovel=c, status_sobreposicao=f["status"], projeto_id=f.get("projeto")))
    for nome, linhas in (("imoveis", im), ("desenvolvedor", ds), ("terra", tr), ("filtros", fl), ("comprometida", cp)):
        pd.DataFrame(linhas).to_csv(uf / f"{nome}_{COD}.csv", index=False)
    return tmp_path / "saida"


# --- entrada -------------------------------------------------------------------------------------------------------


def test_entrada_le_so_o_codigo_e_nao_repete_o_que_nao_e_codigo():
    csv_ = (
        "nome,cod_imovel,cpf\n"
        f"Fulano de Tal,{car('A').lower()},{CPF}\n"
        f"Beltrana,{CPF},111\n"  # CPF na coluna do código: inválido, nunca repetido
        f"x,{car('A')},y\n"  # repetido
        f"x,pa{COD}{'b' * 32},y\n"  # sem traços
    )
    codigos, invalidas = E.ler(csv_)
    assert codigos == [car("A"), car("B")] and invalidas == [3]
    # texto solto: vários por linha e uma coluna sem cabeçalho
    assert E.ler(f"{car('A')} {car('B')}\n{car('C')}")[0] == [car("A"), car("B"), car("C")]
    assert E.ler(f"{car('A')}\n{car('B')}\n")[0] == [car("A"), car("B")]
    with pytest.raises(ValueError, match="mais de"):
        E.ler("\n".join(f"PA-{COD}-{i:032X}" for i in range(E.LIMITE + 1)))


# --- nota ----------------------------------------------------------------------------------------------------------


def _linha(**kw):
    base = dict(cod_imovel=car("A"), ha=300, m_fiscal=2.0, custo_credito_usd=9.0, tir_alavancada_pct_p50=14.0,
                credito_liquido_tco2_ha_contrato_p50=140.0, caminho_terra="privada_matricula",
                risco_terra="baixo")  # fmt: skip
    return {**base, **kw}


def test_nota_pela_regra_e_motivo_mostra_a_conta():
    x = N.avaliar(_linha())
    assert x["faixa"] == "recomendada" and 85 <= x["nota"] <= 100
    assert (
        "custo US$ 9,00 por crédito" in x["motivo"]
        and "TIR 14,0%" in x["motivo"]
        and "privada com matrícula" in x["motivo"]
    )
    pior = N.avaliar(_linha(custo_credito_usd=25.0, tir_alavancada_pct_p50=0.0,
                            credito_liquido_tco2_ha_contrato_p50=20.0, risco_terra="alto"))  # fmt: skip
    assert pior["nota"] == pytest.approx(5.0) and pior["faixa"] == "com_ressalvas"  # 0,25 de terra x 20%
    # ordem certa: mais barato, nota maior
    assert N.avaliar(_linha(custo_credito_usd=8.0))["nota"] > N.avaliar(_linha(custo_credito_usd=15.0))["nota"]


def test_travas_limitam_a_nota_e_nao_tiram_a_fazenda():
    for col, texto in (("embargo_ha", "embargo ativo"), ("ti_ha", "terra indígena"),
                       ("uc_protecao_integral_ha", "proteção integral"),
                       ("desm_pos2020_ha", "depois de 2020"), ("alerta_ultimo_ano", "alerta")):  # fmt: skip
        x = N.avaliar(_linha(**{col: 4.2}))
        assert x["faixa"] == "nao_segue" and x["nota"] <= 30 and texto in x["motivo"] and "4,2 ha" in x["motivo"]
    x = N.avaliar(_linha(status_sobreposicao="ja_comprometida", projeto_id="VCS665"))
    assert x["faixa"] == "nao_segue" and "VCS665" in x["motivo"]
    x = N.avaliar(_linha(caminho_terra="terra_indigena_ou_tradicional"))
    assert x["faixa"] == "nao_segue" and "não origina" in x["motivo"]
    assert N.avaliar(_linha(status_sobreposicao="risco_sobreposicao"))["faixa"] == "com_ressalvas"
    assert "não verificada" in N.avaliar(_linha())["motivo"]  # sem a camada, diz que não verificou


def test_sem_dado_nao_vira_zero_e_o_peso_se_reparte():
    sem_tir = N.avaliar(_linha(tir_alavancada_pct_p50=None, tir_projeto_pct_p50=None))
    assert sem_tir["faixa"] == "recomendada" and "sem TIR" in sem_tir["motivo"]
    vazio = N.avaliar({"cod_imovel": car("A"), "ha": 10})
    assert vazio["faixa"] == "sem_dados" and vazio["nota"] is None
    assert (
        N.avaliar(_linha(tir_alavancada_pct_p50=None, tir_projeto_pct_p50=11.0))["tir_pct"] == 11.0
    )  # cai para a do projeto


# --- ranking, CSV e PDF -------------------------------------------------------------------------------------------


def test_ranking_nunca_descarta_pequena_nem_perde_codigo(pasta):
    lista = [car(k) for k in "ABCDEFG"] + [car("0")]  # o último não está nos dados
    dados = D.das_pastas(lista, pasta)
    assert set(dados) == {car(k) for k in "ABCDEFG"}
    linhas = triar(lista, dados)
    assert len(linhas) == 8 and [x["posicao"] for x in linhas] == list(range(1, 9))
    por = {x["cod_imovel"]: x for x in linhas}
    assert por[car("B")]["pequena"] is True and por[car("B")]["faixa"] == "recomendada"  # pequena entra e fica no topo
    assert {por[car(k)]["faixa"] for k in "CD"} == {"nao_segue"} and por[car("E")]["faixa"] == "com_ressalvas"
    assert por[car("F")]["faixa"] == "sem_dados" and por[car("0")]["faixa"] == "nao_encontrada"
    ordem = [x["faixa"] for x in linhas]
    assert ordem == sorted(ordem, key=N.FAIXAS.index)  # recomendadas, ressalvas, travadas, sem dados, não encontradas
    assert resumo(linhas) == {"recomendada": 2, "com_ressalvas": 2, "nao_segue": 2, "sem_dados": 1, "nao_encontrada": 1,
                              "total": 8}  # fmt: skip
    assert por[car("C")]["embargo_ha"] == 12.5 and por[car("D")]["projeto_id"] == "VCS665"
    assert linhas[0]["regra_versao"].startswith("triagem-desenvolvedor-2026a+")


def test_csv_e_pdf_sem_nome_nem_cpf(pasta):
    linhas = triar([car(k) for k in "ABCDEFG"], D.das_pastas([car(k) for k in "ABCDEFG"], pasta))
    bruto = RL.csv_bytes(linhas).decode()
    df = pd.read_csv(io.StringIO(bruto))
    assert list(df.columns)[:3] == ["posicao", "cod_imovel", "municipio"] and len(df) == 7
    assert {
        "nota",
        "credito_p50_tco2_ha",
        "custo_credito_usd",
        "tir_pct",
        "caminho_terra",
        "risco_terra",
        "embargo_ha",
        "ti_uc",
        "desmatamento_recente_ha",
        "alerta_recente_ha",
        "status_sobreposicao",
        "motivo",
    } <= set(df.columns)
    pdf = RL.pdf_bytes(linhas)
    assert pdf[:4] == b"%PDF"
    from pypdf import PdfReader

    texto = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Triagem de fazendas" in texto and "premissas provisórias" in texto
    for proibido in ("NOME QUE NUNCA SAI", CPF):  # as colunas pessoais do arquivo de entrada nunca saem
        assert proibido not in bruto and proibido not in texto


def test_cli_lote_so_imprime_contagens(pasta, tmp_path):
    from typer.testing import CliRunner

    from raiz.cli import app

    lista = tmp_path / "lista.csv"
    lista.write_text("cod_imovel,nome\n" + "".join(f"{car(k)},Fulano\n" for k in "ABC") + "lixo,Beltrana\n")
    r = CliRunner().invoke(app, ["triagem", "lote", "--entrada", str(lista), "--pasta", str(pasta), "--saida",
                                 str(tmp_path / "out"), "--nome", "teste-1"])  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "3 fazendas (1 linhas inválidas)" in r.output and car("A") not in r.output and "lixo" not in r.output
    assert (tmp_path / "out" / "teste-1.csv").exists() and (tmp_path / "out" / "teste-1.pdf").exists()
    ruim = CliRunner().invoke(
        app, ["triagem", "lote", "--entrada", str(lista), "--pasta", str(pasta), "--nome", "Teste Ruim"]
    )
    assert ruim.exit_code != 0


# --- API e MCP -----------------------------------------------------------------------------------------------------


def test_funcao_unica_para_api_e_mcp(pasta):
    r = M.triar_codigos([car("A"), car("a"), "lixo", car("C")], pasta=pasta)
    assert r["codigos_invalidos"] == 1 and [x["cod_imovel"] for x in r["linhas"]] == [car("A"), car("C")]
    assert r["resumo"]["recomendada"] == 1 and r["resumo"]["nao_segue"] == 1
    with pytest.raises(ValueError):
        M.triar_codigos([f"PA-{COD}-{i:032X}" for i in range(E.LIMITE + 1)], pasta=pasta)


def test_ferramenta_mcp_exige_contexto_e_barreira_do_host(pasta, monkeypatch):
    monkeypatch.setattr(D, "do_banco", lambda codigos, engine: D.das_pastas(codigos, pasta))
    assert M.ferramentas()[0]["name"] == "triar_fazendas"
    assert M.ferramentas()[0]["inputSchema"]["properties"]["codigos_car"]["maxItems"] == M.MAXIMO_MCP
    chamadas = []

    @contextmanager
    def autorizar(engine, ctx, nome, codigos):
        chamadas.append((nome, codigos))
        yield

    ctx = SimpleNamespace(cliente_id=7, via="mcp", escopos=frozenset({"consultar"}))
    out = M.executar(object(), ctx, "triar_fazendas", {"codigos_car": [car("A"), car("C")]}, autorizar=autorizar)
    assert chamadas == [("triar_fazendas", (car("A"), car("C")))] and out["isError"] is False
    assert json.loads(out["content"][0]["text"])["resumo"]["total"] == 2
    with pytest.raises(PermissionError):
        M.executar(object(), SimpleNamespace(cliente_id=7, via="rest"), "triar_fazendas", {"codigos_car": [car("A")]},
                   autorizar=autorizar)  # fmt: skip
    with pytest.raises(ValueError):
        M.executar(object(), ctx, "triar_fazendas", {"codigos_car": [car("A")], "extra": 1}, autorizar=autorizar)


@pytest.mark.banco
def test_endpoint_da_api_pede_token(banco_url, pasta, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine

    from raiz import api

    monkeypatch.setattr(api, "config", lambda: SimpleNamespace(api_token=SecretStr("segredo")))
    monkeypatch.setattr(D, "do_banco", lambda codigos, engine: D.das_pastas(codigos, pasta))
    eng = create_engine(banco_url)
    cli = TestClient(api.criar_app(eng, SimpleNamespace(), SimpleNamespace(), whatsapp=False))
    corpo = {"codigos_car": [car("A"), car("B"), car("C")]}
    assert cli.post("/triagem/desenvolvedor", json=corpo).status_code == 401
    r = cli.post("/triagem/desenvolvedor", json=corpo, headers={"Authorization": "Bearer segredo"})
    assert r.status_code == 200 and r.json()["resumo"]["total"] == 3 and r.json()["linhas"][0]["posicao"] == 1
    r = cli.post("/triagem/desenvolvedor", json={"codigos_car": []}, headers={"Authorization": "Bearer segredo"})
    assert r.status_code == 422
    eng.dispose()
