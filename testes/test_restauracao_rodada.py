"""A publicação estadual só avança com a cobertura, a versão e a integridade conferidas."""

import io
import json
import subprocess
import tarfile

import pandas as pd
import pytest

from raiz import restauracao_rodada as RR


def test_cobertura_exige_municipio_vazio_documentado(tmp_path):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel\nCAR-A\n")
    with pytest.raises(ValueError, match="faltam.*1507300"):
        RR.conferir_cobertura(tmp_path, {1504950, 1507300})

    (tmp_path / "sem_imoveis_PA.csv").write_text("cod_municipio_ibge\n1507300\n")
    c = RR.conferir_cobertura(tmp_path, {1504950, 1507300})
    assert c == {"total": 2, "com_imoveis": [1504950], "vazios": [1507300]}
    (tmp_path / "imoveis_1507300.csv").write_text("cod_imovel\n")
    with pytest.raises(ValueError, match="como vazio"):
        RR.conferir_cobertura(tmp_path, {1504950, 1507300})


def test_cobertura_aceita_cod_ibge_do_contrato(tmp_path):
    (tmp_path / "sem_imoveis_PA.csv").write_text("cod_ibge\n1504950\n")
    assert RR.conferir_cobertura(tmp_path, {1504950})["vazios"] == [1504950]


def test_preserva_terra_publica_tradicional_e_risco_publicados(tmp_path):
    original = pd.DataFrame(
        [
            {
                "cod_imovel": "A",
                "caminho_terra": "publica_sem_destinacao",
                "risco_terra": "alto",
                "terra_publica_ha": 100.0,
                "caminho_terra_situacao": "so_mostrar",
                "risco_terra_motivo": "Gleba pública",
            },
            {
                "cod_imovel": "B",
                "caminho_terra": "terra_indigena_ou_tradicional",
                "risco_terra": "alto",
                "terra_tradicional_ha": 70.0,
                "caminho_terra_situacao": "so_mostrar",
                "risco_terra_motivo": "Quilombo",
            },
        ]
    )
    original.to_csv(tmp_path / "terra_1504950.csv", index=False)
    bruto = pd.DataFrame(
        [
            {"cod_imovel": cod, "ha": 100.0, "matricula_ha": 100.0, "f_matricula": 1.0, "ti_ha": 0.0}
            for cod in ("A", "B", "C")
        ]
    )
    resultado, n = RR.terra_dos_dados_publicados(tmp_path, 1504950, bruto)
    assert n == 2 and len(resultado) == 3
    for _, linha in original.iterrows():
        atual = resultado.set_index("cod_imovel").loc[linha.cod_imovel]
        for chave in ("caminho_terra", "risco_terra", "caminho_terra_situacao", "risco_terra_motivo"):
            assert atual[chave] == linha[chave]
    assert resultado.set_index("cod_imovel").loc["A", "terra_publica_ha"] == 100
    assert resultado.set_index("cod_imovel").loc["B", "terra_tradicional_ha"] == 70


@pytest.mark.parametrize("nome,tipo", [("../fora", tarfile.REGTYPE), ("PA/link", tarfile.SYMTYPE)])
def test_extracao_rejeita_travessia_e_link(tmp_path, nome, tipo):
    pacote = tmp_path / "teste.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        m = tarfile.TarInfo(nome)
        m.type = tipo
        m.linkname = "/etc/passwd" if tipo == tarfile.SYMTYPE else ""
        tar.addfile(m)
    with pytest.raises(ValueError, match="Caminho inválido"):
        RR.extrair(pacote, tmp_path / "saida")


def test_extracao_so_da_fatia(tmp_path):
    pacote = tmp_path / "teste.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        for cod in (1504950, 1507300):
            b = b"cod_imovel\nCAR\n"
            m = tarfile.TarInfo(f"PA/imoveis_{cod}.csv")
            m.size = len(b)
            tar.addfile(m, io.BytesIO(b))
    RR.extrair(pacote, tmp_path / "saida", {1504950})
    assert [f.name for f in (tmp_path / "saida/PA").iterdir()] == ["imoveis_1504950.csv"]


def test_planejamento_inclui_todas_as_fazendas_e_balanceia(tmp_path):
    for cod, n in ((1504950, 9), (1507300, 5), (1500010, 4), (1500101, 1)):
        (tmp_path / f"imoveis_{cod}.csv").write_text("cod_imovel\n" + "CAR\n" * n)
    plano = RR.planejar(tmp_path, 2)
    assert sum(p["imoveis"] for p in plano) == 19
    assert sorted(c for p in plano for c in p["municipios"]) == [1500010, 1500101, 1504950, 1507300]
    assert sorted(p["imoveis"] for p in plano) == [9, 10]


def test_conferencia_rejeita_calculo_obsoleto_ou_modificado(tmp_path):
    arq = tmp_path / "desenvolvedor_1504950.csv"
    pd.DataFrame(
        [{"cod_imovel": "CAR", "restauracao_versao": "modelo-1", "restauracao_area_ha": 1, "reserva_risco_pct": 20}]
    ).to_csv(arq, index=False)
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel\nCAR\n")
    registro = tmp_path / "previsoes.jsonl"
    registro.write_text('{"cod_imovel": "CAR"}\n')
    marca = {
        "modelo_versao": "modelo-1",
        "cenario": RR.CENARIO,
        "imoveis": 1,
        "arquivos": {arq.name: RR.sha256(arq), registro.name: RR.sha256(registro)},
        "previsoes": {"arquivo": registro.name, "sha256": RR.sha256(registro), "quantidade": 1},
    }
    (tmp_path / "rodada_1504950.json").write_text(json.dumps(marca))
    cobertura = {"com_imoveis": [1504950]}
    assert len(RR.conferir_calculos(tmp_path, cobertura, "modelo-1")) == 1
    with pytest.raises(ValueError, match="Versão ou cenário"):
        RR.conferir_calculos(tmp_path, cobertura, "modelo-2")
    registro.unlink()
    with pytest.raises(ValueError, match="alterado depois"):
        RR.conferir_calculos(tmp_path, cobertura, "modelo-1")
    registro.write_text('{"cod_imovel": "CAR"}\n')
    arq.write_text(arq.read_text() + "CAR2,modelo-1\n")
    with pytest.raises(ValueError, match="alterado depois"):
        RR.conferir_calculos(tmp_path, cobertura, "modelo-1")


def test_catalogo_pa_tem144_municipios():
    assert len(RR.municipios_pa()) == 144


def test_rodada_recusa_execucao_local_e_modelo_alterado(monkeypatch):
    from raiz import restauracao as R

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(SystemExit, match="GitHub Actions"):
        RR.exigir_actions()
    monkeypatch.setenv("GITHUB_SHA", "commit-de-teste")
    snapshot = {"commit": "commit-de-teste", "modelo_versao": R.versao()}
    RR.conferir_modelo(snapshot)
    with pytest.raises(ValueError, match="premissas divergentes"):
        RR.conferir_modelo({**snapshot, "modelo_versao": "versao-obsoleta"})


@pytest.mark.parametrize("falha", ["car", "piso", "pessoal"])
def test_publicacao_rejeita_troca_de_imovel_piso_e_coluna_pessoal(tmp_path, falha):
    arq = tmp_path / "desenvolvedor_1504950.csv"
    linha = {"cod_imovel": "CAR", "restauracao_versao": "modelo-1", "restauracao_area_ha": 1, "reserva_risco_pct": 20}
    if falha == "car":
        linha["cod_imovel"] = "OUTRO-CAR"
    elif falha == "piso":
        linha["reserva_risco_pct"] = 19
    else:
        linha["telefone_dono"] = "dado-privado"
    pd.DataFrame([linha]).to_csv(arq, index=False)
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel\nCAR\n")
    previsao = tmp_path / "previsoes.jsonl"
    previsao.write_text("{}\n")
    marca = {
        "modelo_versao": "modelo-1",
        "cenario": RR.CENARIO,
        "imoveis": 1,
        "arquivos": {arq.name: RR.sha256(arq), previsao.name: RR.sha256(previsao)},
        "previsoes": {"arquivo": previsao.name, "sha256": RR.sha256(previsao), "quantidade": 1},
    }
    (tmp_path / "rodada_1504950.json").write_text(json.dumps(marca))
    with pytest.raises(
        ValueError, match={"car": "divergem da fonte", "piso": "piso de 20%", "pessoal": "Coluna pessoal"}[falha]
    ):
        RR.conferir_calculos(tmp_path, {"com_imoveis": [1504950]}, "modelo-1")


def test_publicacao_so_atualiza_ponteiro_apos_todos_os_assets(tmp_path, monkeypatch):
    produto = tmp_path / "produto"
    produto.mkdir()
    (produto / "manifesto.json").write_text(json.dumps({"municipios": 144}))
    for nome in RR.OPCOES:
        (produto / nome).mkdir()
        (produto / nome / "lote.json").write_text("{}")
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    chamadas = []

    def upload(cmd, **kwargs):
        chamadas.append(cmd)
        if len(chamadas) == 2:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(RR.subprocess, "run", upload)
    with pytest.raises(subprocess.CalledProcessError):
        RR.publicar(tmp_path)
    assert not any("--clobber" in c for c in chamadas)
    assert not (tmp_path / "lote_PA_central_r11.json").exists()
    chamadas.clear()
    monkeypatch.setattr(RR.subprocess, "run", lambda cmd, **kwargs: chamadas.append(cmd))
    manifesto = RR.publicar(tmp_path)
    assert len(manifesto["arquivos"]) == 4
    assert len(chamadas) == 6
    assert "--clobber" not in [x for cmd in chamadas[:-1] for x in cmd]
    assert chamadas[-1][-1] == "--clobber"
