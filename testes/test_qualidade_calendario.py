"""Contrato público e execução do gate sem dependências do produto instaladas."""

import copy
import datetime as dt
import json
import subprocess
import sys

import pytest

from raiz import qualidade_calendario as Q
from raiz.calendario.feed import ics
from raiz.calendario.modelos import MARCOS, TITULOS, Evento
from testes.test_privacidade import CPF


@pytest.fixture
def snapshot():
    return {
        "eventos": [
            {
                "id": "a" * 24,
                "tipo": "concessao",
                "marco": "propostas",
                "referencia": "12/2026",
                "data": "2026-11-12",
                "prazo": "2026-12-01",
                "uf": "PA",
                "municipio": "1500800",
                "fonte_id": "sfb",
                "fonte_nome": "Serviço Florestal Brasileiro",
                "fonte_url": "https://www.gov.br/florestal/edital-12-2026",
                "coletado_em": "2026-11-12T10:00:00-03:00",
                "confianca": 0.9,
            }
        ],
        "fontes": [
            {
                "id": "sfb",
                "nome": "Serviço Florestal Brasileiro",
                "situacao": "ok",
                "coletado_em": "2026-11-12T13:00:00Z",
                "paginas": 1,
                "eventos": 1,
                "sem_data": 0,
            }
        ],
    }


def test_projecao_preserva_contrato_e_ics_do_produto(snapshot):
    publicado = Q.projetar_snapshot(snapshot)
    evento = Evento.model_validate(snapshot["eventos"][0])
    assert publicado["ics"] == ics([evento])
    assert publicado["agenda"]["total"] == 1
    assert publicado["agenda"]["eventos"][0]["titulo"] == evento.titulo
    assert publicado["agenda"]["eventos"][0]["prazo"] == "2026-12-01"
    assert "DTSTART;VALUE=DATE:20261201" in publicado["ics"]
    assert Q.TITULOS == TITULOS and Q.MARCOS == MARCOS


def test_textos_pessoais_e_enriquecimento_sao_descartados(snapshot):
    e = snapshot["eventos"][0]
    e.update(
        {
            "titulo": "nome=Pessoa Sintética",
            "fonte_nome": "contato@example.invalid",
            "titular": "Pessoa Sintética",
            "cns": "123456",
            "matricula": "1234",
            "sigef": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
            "codigos_car": ["PA-1500800-" + "A" * 32],
            "vinculo": "cns_matricula",
        }
    )
    snapshot["fontes"][0].update({"nome": "Pessoa Sintética", "erro": "token=segredo-sintetico", "situacao": "erro"})
    snapshot["titular"] = "Pessoa Sintética"
    publicado = Q.projetar_snapshot(snapshot)
    texto = json.dumps(publicado, ensure_ascii=False)
    for proibido in (
        "Pessoa Sintética",
        "contato@example.invalid",
        "segredo-sintetico",
        '"matricula"',
        '"cns"',
        '"sigef"',
    ):
        assert proibido not in texto
    assert publicado["agenda"]["eventos"][0]["codigos_car"] == []
    assert publicado["agenda"]["fontes"][0]["erro"].startswith("Fonte com leitura incompleta")


@pytest.mark.parametrize(
    "sufixo",
    [
        "?telefone=11912345678",
        "?api_key=segredo-sintetico",
        "?owner=Pessoa",
        "/contato%40example.invalid",
        "/Proprietario-Joao-da-Silva",
        "/+5511912345678",
        "/%0Asegredo",
        "/nome%253DJoao",
    ],
)
def test_links_pessoais_ou_injecao_nao_passam(snapshot, sufixo):
    snapshot["eventos"][0]["fonte_url"] = "https://www.gov.br/florestal" + sufixo
    with pytest.raises(ValueError):
        Q.projetar_snapshot(snapshot)


def test_documento_na_url_e_referencia_bloqueiam(snapshot):
    snapshot["eventos"][0]["fonte_url"] += "/" + CPF
    with pytest.raises(ValueError):
        Q.projetar_snapshot(snapshot)
    snapshot["eventos"][0]["fonte_url"] = "https://www.gov.br/florestal/edital"
    snapshot["eventos"][0]["referencia"] = CPF
    with pytest.raises(ValueError):
        Q.projetar_snapshot(snapshot)


def test_fonte_id_host_e_tipos_invalidos_bloqueiam(snapshot):
    for campo, valor in (
        ("fonte_id", "desconhecida"),
        ("fonte_url", "https://www.gov.br.atacante.invalid/"),
        ("tipo", "nome_pessoal"),
        ("data", "2026-02-30"),
        ("confianca", float("nan")),
    ):
        alterado = copy.deepcopy(snapshot)
        alterado["eventos"][0][campo] = valor
        with pytest.raises(ValueError):
            Q.projetar_snapshot(alterado)


def test_fragmentos_nao_sao_publicados(snapshot):
    snapshot["eventos"][0]["fonte_url"] += "#:~:text=Pessoa"
    resultado = Q.projetar_snapshot(snapshot)
    assert "Pessoa" not in json.dumps(resultado)


def test_cli_funciona_sem_site_packages_e_nao_emite_erro_bruto(snapshot):
    resultado = subprocess.run(
        [sys.executable, "-S", "-m", "raiz.qualidade_calendario"],
        input=json.dumps(snapshot),
        text=True,
        capture_output=True,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert json.loads(resultado.stdout)["agenda"]["total"] == 1
    snapshot["eventos"][0]["fonte_url"] = "https://contato@example.invalid/"
    resultado = subprocess.run(
        [sys.executable, "-S", "-m", "raiz.qualidade_calendario"],
        input=json.dumps(snapshot),
        text=True,
        capture_output=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert not resultado.stdout and "example.invalid" not in resultado.stderr


def test_cancelamento_uid_e_sequencia_preservados(snapshot):
    e = snapshot["eventos"][0]
    e.update({"situacao": "cancelado", "sequencia": 3, "atualizado_em": "2026-11-13T01:00:00Z"})
    resultado = Q.projetar_snapshot(snapshot)
    assert "STATUS:CANCELLED" in resultado["ics"] and "SEQUENCE:3" in resultado["ics"]
    assert f"UID:{e['id']}@calendario.raiz" in resultado["ics"]
    assert dt.datetime.fromisoformat(resultado["agenda"]["coletado_em"]).tzinfo is not None


@pytest.mark.parametrize("formatado", [True, False])
def test_documento_codificado_em_caminho_de_url_bloqueia(snapshot, formatado):
    from urllib.parse import quote

    from testes.test_privacidade import CNPJ

    for documento in (CPF, CNPJ):
        if not formatado:
            documento = "".join(c for c in documento if c.isdigit())
        snapshot["eventos"][0]["fonte_url"] = "https://www.gov.br/" + quote(documento, safe="")
        with pytest.raises(ValueError):
            Q.projetar_snapshot(snapshot)


def _publicar(tmp_path, snapshot):
    from raiz.calendario.arquivos import publicar
    from raiz.calendario.modelos import FonteEstado

    eventos = [Evento.model_validate(e) for e in snapshot["eventos"]]
    estados = [FonteEstado.model_validate(e) for e in snapshot["fontes"]]
    publicar(tmp_path, eventos, estados)


def test_pasta_valida_trio_real_sem_alterar(tmp_path, snapshot):
    _publicar(tmp_path, snapshot)
    antes = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert Q.validar_pasta(tmp_path) == {"arquivos": 3, "eventos": 1, "fontes": 1}
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == antes


@pytest.mark.parametrize("nome", ["estado.json", "eventos.json", "eventos.ics"])
def test_pasta_recusa_original_contaminado_mesmo_que_projecao_seria_limpa(tmp_path, snapshot, nome):
    _publicar(tmp_path, snapshot)
    arquivo = tmp_path / nome
    if nome.endswith("json"):
        dados = json.loads(arquivo.read_text())
        dados["titular"] = "Pessoa Sintética"
        arquivo.write_text(json.dumps(dados))
    else:
        arquivo.write_text(arquivo.read_text().replace("SUMMARY:", "SUMMARY:Pessoa Sintética "))
    resultado = subprocess.run(
        [sys.executable, "-S", "-m", "raiz.qualidade_calendario", "--pasta", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert not resultado.stdout and "Pessoa Sintética" not in resultado.stderr


def test_estado_e_publico_precisam_ser_da_mesma_coleta(tmp_path, snapshot):
    _publicar(tmp_path, snapshot)
    p = tmp_path / "eventos.json"
    dados = json.loads(p.read_text())
    dados["eventos"][0]["sequencia"] = 8
    p.write_text(json.dumps(dados))
    with pytest.raises(ValueError):
        Q.validar_pasta(tmp_path)


def test_estado_privado_mantem_so_identificadores_tipados(tmp_path, snapshot):
    snapshot["eventos"][0].update(
        {"cns": "123456", "matricula": "1234A", "sigef": ["a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12]}
    )
    _publicar(tmp_path, snapshot)
    assert Q.validar_pasta(tmp_path)["eventos"] == 1
    p = tmp_path / "estado.json"
    dados = json.loads(p.read_text())
    dados["eventos"][0]["matricula"] = "PESSOASINTETICA"
    p.write_text(json.dumps(dados))
    with pytest.raises(ValueError):
        Q.validar_pasta(tmp_path)


def test_erros_padronizados_da_coleta_sao_legitimos(tmp_path, snapshot):
    snapshot["fontes"][0].update(
        {
            "situacao": "parcial",
            "erro": (
                "1 página(s) não puderam ser lidas; consulte a fonte oficial. "
                "Limite de páginas da rodada atingido; cobertura parcial."
            ),
        }
    )
    _publicar(tmp_path, snapshot)
    assert Q.validar_pasta(tmp_path)["eventos"] == 1
    p = tmp_path / "estado.json"
    dados = json.loads(p.read_text())
    dados["fontes"][0]["erro"] = "token=segredo-sintetico"
    p.write_text(json.dumps(dados))
    with pytest.raises(ValueError):
        Q.validar_pasta(tmp_path)
