"""Portão de Release sem rede: artefatos produzidos pelo gerador real e ataques sintéticos."""

import datetime as dt
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from raiz.documentos.busca import fontes as F
from raiz.documentos.busca import semanal
from raiz.qualidade_busca import ErroQualidadeBusca, preparar, validar
from testes.test_privacidade import CNPJ, CPF


@pytest.fixture
def pacote(tmp_path):
    estado = semanal.EstadoBusca(tmp_path / "busca.sqlite")

    def item(chave, titulo):
        url = "https://www.gov.br/florestal/" + chave
        return F.Item(
            "sfb", url, titulo, url, "2026-11-12", "Serviço Florestal Brasileiro", detalhe={"lista": "editais"}
        )

    base = item("base", "Concessão para restauração")
    semanal.rodar(estado, [F.ResultadoFonte("sfb", [base], via="direto")], hoje=dt.date(2026, 11, 9))
    novo = item("novo", "Edital de restauração florestal")
    rel = semanal.rodar(estado, [F.ResultadoFonte("sfb", [base, novo], via="direto")], hoje=dt.date(2026, 11, 12))
    return estado.caminho, rel.arquivo_md, rel.arquivo_csv


def test_aceita_gerador_real_e_preserva_dados_institucionais(pacote):
    assert preparar(*pacote) == {"arquivos": 3, "itens": 2, "rodadas": 2, "novidades": 1}
    assert "Edital de restauração florestal" in pacote[1].read_text()
    assert "Edital de restauração florestal" in pacote[2].read_text()
    with sqlite3.connect(pacote[0]) as con:
        assert con.execute("select count(*) from item").fetchone()[0] == 2


@pytest.mark.parametrize("valor", [CPF, CNPJ, "contato@example.invalid", "(11) 91234-5678", "token=segredo-sintetico"])
def test_bloqueia_dados_pessoais_e_segredos_em_todos_artefatos(pacote, valor):
    with sqlite3.connect(pacote[0]) as con:
        con.execute("update item set detalhe_json=? where chave like '%base'", (json.dumps({"lista": valor}),))
    antes = [p.read_bytes() for p in pacote]
    with pytest.raises(ErroQualidadeBusca, match="valores omitidos") as ex:
        preparar(*pacote)
    assert valor not in str(ex.value)
    assert [p.read_bytes() for p in pacote] == antes


def test_nao_aceita_tabela_privada_no_sqlite(pacote):
    with sqlite3.connect(pacote[0]) as con:
        con.execute("create table contato (nome text)")
    with pytest.raises(ErroQualidadeBusca, match="SQLite fora do contrato"):
        validar(*pacote)


def test_nao_aceita_json_com_nome_do_dono_ou_erro_com_segredo(pacote):
    with sqlite3.connect(pacote[0]) as con:
        con.execute("update item set detalhe_json=?", (json.dumps({"nome_dono": "Pessoa Sintética"}),))
    with pytest.raises(ErroQualidadeBusca, match="JSON fora do contrato"):
        validar(*pacote)
    with sqlite3.connect(pacote[0]) as con:
        con.execute("update item set detalhe_json='{}'")
        resumo = {"sfb": {"itens": 2, "via": "direto", "erro": "password=segredo-sintetico"}}
        con.execute("update rodada set resumo_json=?", (json.dumps(resumo),))
    with pytest.raises(ErroQualidadeBusca, match="documento, contato ou segredo"):
        validar(*pacote)


def test_nao_aceita_nome_de_dono_em_markdown_editorial(pacote):
    with pacote[1].open("a") as arquivo:
        arquivo.write("\nProprietário: João da Silva\n")
    with pytest.raises(ErroQualidadeBusca, match="dono"):
        validar(*pacote)


def test_nao_aceita_pii_codificada_em_link_do_csv(pacote):
    conteudo = pacote[2].read_text().replace("/novo,", "/novo?token%3Dsegredo-sintetico,")
    pacote[2].write_text(conteudo)
    with pytest.raises(ErroQualidadeBusca):
        validar(*pacote)


def test_nao_aceita_relatorio_com_contato_mesmo_com_estado_limpo(pacote):
    with pacote[1].open("a") as arquivo:
        arquivo.write("\ncontato@example.invalid\n")
    with pytest.raises(ErroQualidadeBusca, match="documento, contato ou segredo"):
        validar(*pacote)


def test_compactacao_retira_conteudo_apagado_sem_perder_estado(pacote):
    marcador = "segredo-antigo-" * 1000
    with sqlite3.connect(pacote[0]) as con:
        con.execute("pragma secure_delete=off")
        con.execute("update item set detalhe_json=? where chave like '%base'", (json.dumps({"lista": marcador}),))
        con.commit()
        con.execute("update item set detalhe_json=? where chave like '%base'", (json.dumps({"lista": "editais"}),))
    assert marcador.encode()[:100] in pacote[0].read_bytes()
    preparar(*pacote)
    assert marcador.encode()[:100] not in pacote[0].read_bytes()
    assert validar(*pacote)["itens"] == 2


def test_cli_falha_sem_expor_conteudo_e_sem_alterar_arquivos(pacote):
    pacote[1].write_text("contato@example.invalid")
    antes = pacote[0].read_bytes()
    resultado = subprocess.run(
        [sys.executable, "-m", "raiz.qualidade_busca", *map(str, pacote)], capture_output=True, text=True, check=False
    )
    assert resultado.returncode == 1
    assert "bloqueada" in resultado.stderr
    assert "contato@example.invalid" not in resultado.stderr + resultado.stdout
    assert pacote[0].read_bytes() == antes


def test_recusa_arquivo_faltando_e_nunca_cria_sqlite(tmp_path):
    with pytest.raises(ErroQualidadeBusca, match="arquivo ausente"):
        preparar(tmp_path / "busca.sqlite", tmp_path / "novidades_2026-11-12.md", tmp_path / "novidades_2026-11-12.csv")
    assert not Path(tmp_path / "busca.sqlite").exists()


def test_rotulo_de_autoria_nao_libera_nome_pessoal(pacote):
    with pacote[1].open("a") as arquivo:
        arquivo.write("\nAutor: João da Silva\n")
    with pytest.raises(ErroQualidadeBusca, match="texto pessoal"):
        validar(*pacote)


@pytest.mark.parametrize("campo", ["chave", "via", "url", "id"])
def test_campos_estruturais_nao_transportam_dados_pessoais(pacote, campo):
    with sqlite3.connect(pacote[0]) as con:
        if campo == "chave":
            con.execute("update item set chave='Proprietário: João da Silva' where chave like '%base'")
        elif campo == "via":
            resumo = {"sfb": {"itens": 2, "via": "Proprietário: João da Silva", "erro": None}}
            con.execute("update rodada set resumo_json=?", (json.dumps(resumo),))
        elif campo == "url":
            con.execute("update item set url='https://www.gov.br/Proprietario-Joao-da-Silva' where chave like '%base'")
        else:
            numero = int("".join(c for c in CPF if c.isdigit()))
            con.execute("update rodada set id=? where id=1", (numero,))
    with pytest.raises(ErroQualidadeBusca):
        validar(*pacote)


@pytest.mark.parametrize("documento", [CPF, CNPJ, "".join(c for c in CPF if c.isdigit())])
def test_documentos_no_caminho_da_url_sao_bloqueados(pacote, documento):
    from urllib.parse import quote

    with sqlite3.connect(pacote[0]) as con:
        con.execute(
            "update item set url=? where chave like '%base'", ("https://www.gov.br/" + quote(documento, safe=""),)
        )
    with pytest.raises(ErroQualidadeBusca, match="documento"):
        validar(*pacote)
