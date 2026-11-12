"""Pacotes da rodada: dados inválidos e documentos privados nunca chegam ao Release."""

import io
import json
import tarfile

import pandas as pd
import pytest

from raiz.qualidade_dados import OBRIGATORIAS, ErroQualidade
from raiz.qualidade_rodada import JSON_RAIZ, OPCOES, validar_publicacao

CAR = "PA-1504950-0123456789ABCDEF0123456789ABCDEF01"


def montar(tmp_path, extra=None, alteracao=None):
    referencias = tmp_path / "referencias"
    referencias.mkdir()
    imovel = dict.fromkeys(OBRIGATORIAS["imoveis"])
    imovel.update(cod_imovel=CAR, ha=100)
    pd.DataFrame([imovel]).to_csv(referencias / "imoveis_1504950.csv", index=False)
    manifesto = {
        "cenario": "central_r11",
        "uf": "PA",
        "municipios": 1,
        "municipios_calculados": 1,
        "imoveis_calculados": 1,
        "modelo_versao": "restauracao-11",
        "opcoes": sorted(OPCOES),
        "fontes": {},
        "resumos": {},
        "arquivos": {},
    }
    arquivos = {nome: b"{}" for nome in JSON_RAIZ}
    arquivos["decisoes_entrada.jsonl"] = b""
    desenvolvedor = dict.fromkeys(OBRIGATORIAS["desenvolvedor"])
    desenvolvedor.update(cod_imovel=CAR)
    arquivos["previsoes/desenvolvedor_1504950.csv"] = pd.DataFrame([desenvolvedor]).to_csv(index=False).encode()
    for opcao in sorted(OPCOES):
        linha = {
            "cod_imovel": CAR,
            "papel": "titular",
            "area_ha": 80,
            "credito_p10": 10,
            "credito_p50": 20,
            "credito_p90": 30,
        }
        if alteracao:
            linha.update(alteracao)
        arquivos[f"{opcao}/lote_PA.csv"] = pd.DataFrame([linha]).to_csv(index=False).encode()
        arquivos[f"{opcao}/lote_PA.json"] = b"{}"
        arquivos[f"{opcao}/ecologia_PA.json"] = b"[]"
        arquivos[f"{opcao}/decisoes_PA.jsonl"] = b""
    arquivos.update(extra or {})
    pacote = tmp_path / "lote.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        for nome, dado in arquivos.items():
            membro = tarfile.TarInfo(nome)
            membro.size = len(dado)
            tar.addfile(membro, io.BytesIO(dado))
    return [pacote], referencias, manifesto


def test_pacote_publico_tipado_passaria_sem_documentos_individuais(tmp_path):
    # Fixture pequena do portão, não benchmark estadual nem saída do cálculo científico.
    resultado = validar_publicacao(*montar(tmp_path))
    assert resultado["arquivos"] == 21


@pytest.mark.parametrize("nome", ["barata/relatorio_lote_PA.html", f"barata/folhas_dono/folha_dono_{CAR}.html"])
def test_html_e_proposta_individual_exigem_contrato_privado(tmp_path, nome):
    with pytest.raises(ErroQualidade, match="documento individual ou HTML"):
        validar_publicacao(*montar(tmp_path, {nome: b"<html><body>Proposta</body></html>"}))


@pytest.mark.parametrize("alteracao", [{"area_ha": 101}, {"credito_p10": 21}, {"credito_p90": 19}])
def test_pacote_reprova_area_maior_car_e_faixa_invertida(tmp_path, alteracao):
    with pytest.raises(ErroQualidade, match="área fora|P10"):
        validar_publicacao(*montar(tmp_path, alteracao=alteracao))


def test_jsonl_individual_nao_escapa_da_privacidade(tmp_path):
    registro = json.dumps({"cod_imovel": CAR, "contato": "dado que não pode ser publicado"}).encode()
    with pytest.raises(ErroQualidade, match="chave proibida"):
        validar_publicacao(*montar(tmp_path, {"previsoes/validacao_entradas_1504950.jsonl": registro}))


def test_manifesto_ponteiro_tambem_passa_no_portao(tmp_path):
    pacotes, referencias, manifesto = montar(tmp_path)
    manifesto["email"] = "exemplo@dominio.invalid"
    with pytest.raises(ErroQualidade, match="chave proibida"):
        validar_publicacao(pacotes, referencias, manifesto)


def test_geo_sem_contrato_nao_pode_ser_extra_do_pacote(tmp_path):
    with pytest.raises(ErroQualidade, match="sem contrato público"):
        validar_publicacao(*montar(tmp_path, {"poligono.geojson": b"{}"}))


def test_documento_nao_pode_ser_disfarcado_com_extensao_json(tmp_path):
    with pytest.raises(ErroQualidade, match="exportação administrativa"):
        validar_publicacao(*montar(tmp_path, {"fontes.json": b'{"_omaps":"preciso"}'}))


def test_json_sem_p10_nao_pode_esconder_faixa_invertida(tmp_path):
    registro = json.dumps({"cod_imovel": CAR, "credito_p50": 30, "credito_p90": 20}).encode()
    with pytest.raises(ErroQualidade, match="faixa P10/P50/P90 incompleta"):
        validar_publicacao(*montar(tmp_path, {"previsoes/validacao_entradas_1504950.jsonl": registro}))


def test_quantile_isolado_novo_tambem_exige_contrato(tmp_path):
    registro = json.dumps({"cod_imovel": CAR, "metrica_nova_p50": 20}).encode()
    with pytest.raises(ErroQualidade, match="faixa P10/P50/P90 incompleta"):
        validar_publicacao(*montar(tmp_path, {"previsoes/validacao_entradas_1504950.jsonl": registro}))


def test_html_na_publicacao_real_bloqueia_todo_gh(tmp_path, monkeypatch):
    from raiz import restauracao_rodada as RR

    pacotes, referencias, manifesto = montar(tmp_path)
    produto = tmp_path / "produto"
    produto.mkdir()
    with tarfile.open(pacotes[0]) as tar:
        tar.extractall(produto, filter="data")
    (produto / "manifesto.json").write_text(json.dumps(manifesto))
    (produto / "barata" / "relatorio_lote_PA.html").write_text("<html>Privado</html>")
    trabalho = tmp_path / "trabalho" / "PA"
    trabalho.mkdir(parents=True)
    (trabalho / "imoveis_1504950.csv").write_bytes((referencias / "imoveis_1504950.csv").read_bytes())
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    chamadas = []
    monkeypatch.setattr(RR.subprocess, "run", lambda *args, **kwargs: chamadas.append(args))
    with pytest.raises(ErroQualidade, match="documento individual ou HTML"):
        RR.publicar(tmp_path)
    assert chamadas == []
    assert not (tmp_path / "lote_PA_central_r11.json").exists()
