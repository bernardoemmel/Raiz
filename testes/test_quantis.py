"""Exportação pública: proveniência, representação hubverse e prior FLAG explícito."""

import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import tarfile

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

from raiz import quantis as Q

CAR = "PA-1504950-" + "A" * 32


def _desenvolvedor(car=CAR, versao="restauracao-v1+abc"):
    linha = {"cod_imovel": car, "restauracao_versao": versao, "restauracao_cenario": "profloresta"}
    for alvo in Q.ALVOS:
        if alvo != "flag_tco2_ano":
            linha.update(dict(zip(Q._colunas("desenvolvedor", alvo), (1.125, 2.25, 3.5), strict=True)))
    return linha


def _flag(car=CAR):
    return {
        "cod_imovel": car,
        "flag_regra_versao": "ghg-lsr-1.1+abc",
        "flag_tco2_ano_min": 0,
        "flag_tco2_ano": 2,
        "flag_tco2_ano_max": 10,
    }


def _escrever(pasta, tarefa, linhas, meta=None):
    arquivo = pasta / f"{tarefa}_1504950.csv"
    with arquivo.open("w", newline="") as saida:
        escritor = csv.DictWriter(saida, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)
    dados = (
        meta
        if meta is not None
        else {"tarefa": tarefa, "versao": f"{tarefa}-hash123", "data": "2026-11-12T23:30:00-03:00"}
    )
    arquivo.with_name(arquivo.name + ".meta.json").write_text(json.dumps(dados))
    return arquivo


def _tabela(resultado):
    return pq.read_table(io.BytesIO(resultado["arquivos"]["quantis_PA.parquet"]))


def _hub(resultado):
    with tarfile.open(fileobj=io.BytesIO(resultado["arquivos"]["hub_PA.tar.gz"]), mode="r:gz") as tar:
        return {p.name: tar.extractfile(p).read() for p in tar.getmembers() if p.isfile()}


def test_preserva_quantis_versoes_e_data_da_execucao_sem_inventar_corte(tmp_path):
    arquivo = _escrever(tmp_path, "desenvolvedor", [_desenvolvedor()])
    antes = arquivo.read_bytes()
    r = Q.quantis_uf(tmp_path, "PA")
    tabela = _tabela(r)
    assert r["linhas"] == 24 and not r["diagnosticos"]
    assert tabela.schema == Q.ESQUEMA_PUBLICO
    linhas = tabela.to_pylist()
    assert {x["reference_date"] for x in linhas} == {dt.date(2026, 11, 13)}  # converte fuso da execução para UTC
    assert {x["output_type_id"] for x in linhas} == {0.1, 0.5, 0.9}
    assert {x["source_model_version"] for x in linhas} == {"restauracao-v1+abc"}
    assert {x["task_version"] for x in linhas} == {"desenvolvedor-hash123"}
    for alvo in set(x["target"] for x in linhas):
        assert [x["value"] for x in linhas if x["target"] == alvo] == [1.125, 2.25, 3.5]
    assert arquivo.read_bytes() == antes
    meta = json.loads(r["arquivos"]["modelos_PA.json"])
    assert meta["reference_date_basis"] == Q.BASE_DATA
    assert meta["fontes"][0]["sha256"] == hashlib.sha256(antes).hexdigest()
    assert "horizon" not in tabela.column_names and "target_end_date" not in tabela.column_names


def test_hub_nativo_separa_modelos_e_omite_colunas_extras(tmp_path):
    _escrever(tmp_path, "desenvolvedor", [_desenvolvedor(), _desenvolvedor(CAR[:-1] + "B", "restauracao-v2")])
    r = Q.quantis_uf(tmp_path, "PA")
    hub = _hub(r)
    assert len(r["modelos"]) == 2
    arquivos = {p: b for p, b in hub.items() if p.startswith("model-output/")}
    assert len(arquivos) == 2
    for nome, dados in arquivos.items():
        tabela = pq.read_table(io.BytesIO(dados))
        assert tabela.schema == Q.ESQUEMA_SAIDA
        assert tabela.num_rows == 24
        mid = nome.split("/")[1]
        assert re.fullmatch(r"raiz-desenvolvedor_[a-f0-9]{16}", mid)
        metadata = yaml.safe_load(hub[f"model-metadata/{mid}.yml"])
        assert Q.model_id("desenvolvedor", metadata["model_version"]) == mid
        assert metadata["source_model_version"] in {"restauracao-v1+abc", "restauracao-v2"}
        assert metadata["license_status"] == "licenca_dos_dados_derivados_nao_definida"
        assert "license" not in metadata
    assert json.loads(hub["hub-config/admin.json"])["file_format"] == ["parquet"]
    assert json.loads(hub["hub-config/tasks.json"]) == r["tasks"]


def test_flag_deriva_prior_triangular_sem_chamar_moda_de_mediana(tmp_path):
    arquivo = _escrever(tmp_path, "flag", [_flag()])
    antes = arquivo.read_bytes()
    r = Q.quantis_uf(tmp_path, "PA")
    valores = _tabela(r).column("value").to_pylist()
    assert valores == pytest.approx([math.sqrt(2), 10 - math.sqrt(40), 10 - math.sqrt(8)])
    assert valores[1] != 2 and valores[0] != 0 and valores[2] != 10
    modelo = next(iter(r["modelos"].values()))
    assert modelo["quantile_method"] == "prior_triangular_nao_calibrado"
    assert Q.TRIANGULAR_VERSAO in modelo["model_version"]
    assert modelo["source_model_version"] == "ghg-lsr-1.1+abc"
    assert "sem calibração" in modelo["model_details"]["methods"]
    assert arquivo.read_bytes() == antes


@pytest.mark.parametrize("moda", [0, 2, 10])
def test_inversa_triangular_corresponde_a_cdf_nos_tres_quantis(moda):
    for q in Q.QUANTIS:
        x = Q.triangular(0, moda, 10, q)
        prob = x**2 / (10 * moda) if x < moda else 1 - (10 - x) ** 2 / (10 * (10 - moda))
        assert prob == pytest.approx(q)
    assert Q.triangular(0, 0, 0, 0.5) == 0
    assert math.isfinite(Q.triangular(0, 5e307, 1e308, 0.9))


def test_zero_explicito_flag_e_fazenda_pequena_nao_sao_descartados(tmp_path):
    linha = {**_flag(), "flag_tco2_ano": 0, "flag_tco2_ano_max": 0, "ha": 0.01}
    _escrever(tmp_path, "flag", [linha])
    r = Q.quantis_uf(tmp_path, "PA")
    assert _tabela(r).column("value").to_pylist() == [0, 0, 0] and not r["diagnosticos"]


def test_codigo_car_de_outro_municipio_e_preservado(tmp_path):
    # O espelho real de 1504950 inclui CAR com código municipal 1503077.
    car = CAR.replace("1504950", "1503077")
    _escrever(tmp_path, "flag", [_flag(car)])
    r = Q.quantis_uf(tmp_path, "PA")
    assert _tabela(r).column("location").to_pylist() == [car] * 3
    assert not r["diagnosticos"]


def test_car_repetido_em_dois_municipios_nao_duplica_chave_hubverse(tmp_path):
    primeiro = _escrever(tmp_path, "flag", [_flag()])
    segundo = tmp_path / "flag_1503077.csv"
    segundo.write_bytes(primeiro.read_bytes())
    segundo.with_name(segundo.name + ".meta.json").write_bytes(
        primeiro.with_name(primeiro.name + ".meta.json").read_bytes()
    )
    r = Q.quantis_uf(tmp_path, "PA")
    assert r["linhas"] == 3
    assert r["diagnosticos"] == [
        {
            "arquivo": "flag_1504950.csv",
            "linha": 2,
            "target": None,
            "codigo": "codigo_car_duplicado_na_rodada_do_modelo",
        }
    ]


@pytest.mark.parametrize(
    ("valor", "codigo"),
    [("", "valor_ausente"), ("NaN", "valor_nao_finito"), ("inf", "valor_nao_finito"), ("inválido", "valor_invalido")],
)
def test_valores_invalidos_nao_viram_zero_nem_vazam_no_diagnostico(tmp_path, valor, codigo):
    linha = _desenvolvedor()
    linha["vpl_rs_ha_p10"] = valor
    _escrever(tmp_path, "desenvolvedor", [linha])
    r = Q.quantis_uf(tmp_path, "PA")
    assert r["linhas"] == 21
    assert "vpl_rs_ha" not in _tabela(r).column("target").to_pylist()
    assert r["diagnosticos"] == [
        {"arquivo": "desenvolvedor_1504950.csv", "linha": 2, "target": "vpl_rs_ha", "codigo": codigo}
    ]


def test_quantis_cruzados_nao_sao_reordenados(tmp_path):
    linha = _desenvolvedor()
    linha.update(vpl_rs_ha_p10=9, vpl_rs_ha_p50=1, vpl_rs_ha_p90=5)
    _escrever(tmp_path, "desenvolvedor", [linha])
    r = Q.quantis_uf(tmp_path, "PA")
    assert r["linhas"] == 21 and r["diagnosticos"][0]["codigo"] == "quantis_cruzados"


@pytest.mark.parametrize("versao", ["", "NaN", "null", "publicado"])
def test_versao_vazia_ou_marcador_legado_nao_viram_modelo(tmp_path, versao):
    linha = {**_flag(), "flag_regra_versao": versao}
    _escrever(tmp_path, "flag", [linha])
    r = Q.quantis_uf(tmp_path, "PA")
    assert r["linhas"] == 0
    assert r["diagnosticos"][0]["codigo"] == "versao_do_modelo_ausente"


@pytest.mark.parametrize(
    "meta",
    [
        {},
        {"versao": "tarefa-v1"},
        {"versao": "publicado", "data": "2026-01-01"},
        {"versao": "tarefa-v1", "data": "2026-11-12T12:00:00"},
    ],
)
def test_sem_proveniencia_nao_adota_versao_atual_ou_data_de_publicacao(tmp_path, meta):
    _escrever(tmp_path, "flag", [_flag()], meta)
    r = Q.quantis_uf(tmp_path, "PA")
    assert r["linhas"] == 0 and r["diagnosticos"] and not r["modelos"]
    assert _tabela(r).schema == Q.ESQUEMA_PUBLICO and _tabela(r).num_rows == 0


def test_metadados_explicitos_prevalecem_e_sha_divergente_impede_rotular_dados(tmp_path):
    arquivo = _escrever(tmp_path, "flag", [_flag()])
    dados = {arquivo.name: {"data": "2025-01-02", "versao": "flag-antiga"}}
    r = Q.quantis_uf(tmp_path, "PA", dados)
    assert _tabela(r).column("reference_date").to_pylist() == [dt.date(2025, 1, 2)] * 3
    assert next(iter(r["modelos"].values()))["task_version"] == "flag-antiga"
    dados[arquivo.name]["sha256"] = "0" * 64
    r = Q.quantis_uf(tmp_path, "PA", dados)
    assert r["linhas"] == 0 and r["diagnosticos"][0]["codigo"] == "sha256_da_fonte_divergente"


def test_versoes_do_pacote_sao_usadas_sem_sidecar(tmp_path):
    arquivo = _escrever(tmp_path, "flag", [_flag()])
    lateral = arquivo.with_name(arquivo.name + ".meta.json")
    (tmp_path / "_versoes.json").write_text(json.dumps({arquivo.name: json.loads(lateral.read_text())}))
    lateral.unlink()
    assert Q.quantis_uf(tmp_path, "PA")["linhas"] == 3


def test_allowlist_nao_exporta_aceite_contato_ou_colunas_novas(tmp_path):
    linha = {**_flag(), "nome": "PESSOA_NAO_EXPORTAR", "email": "NAO_EXPORTAR", "aceite_p10": 0.8}
    _escrever(tmp_path, "flag", [linha])
    (tmp_path / "aceite_1504950.csv").write_text("cod_imovel,nome,aceite_p10\nCPF_NAO_EXPORTAR,SEGREDO,0.9\n")
    r = Q.quantis_uf(tmp_path, "PA")
    assert r["linhas"] == 3 and not r["diagnosticos"]
    assert set(_tabela(r).column("target").to_pylist()) == {"flag_tco2_ano"}
    assert "PESSOA_NAO_EXPORTAR" not in str(_tabela(r).to_pylist())
    assert "PESSOA_NAO_EXPORTAR" not in str(r["modelos"])


def test_coluna_ausente_e_codigo_car_invalido_sao_diagnosticados(tmp_path):
    linha = _desenvolvedor("CODIGO_PRIVADO_NAO_EXPORTAR")
    del linha["vpl_rs_ha_p50"]
    _escrever(tmp_path, "desenvolvedor", [linha])
    r = Q.quantis_uf(tmp_path, "PA")
    assert {x["codigo"] for x in r["diagnosticos"]} == {
        "coluna_de_quantil_ausente",
        "codigo_car_ausente_ou_incompativel",
    }
    assert "CODIGO_PRIVADO_NAO_EXPORTAR" not in str(r)


def test_tasks_agregado_enumera_so_datas_locais_e_alvos_publicos(tmp_path):
    _escrever(tmp_path, "flag", [_flag()])
    r = Q.quantis_uf(tmp_path, "PA")
    outro = Q.tasks(["2025-01-02"], ["TO-1700251-" + "B" * 32])
    combinado = Q.combinar_tasks([r["tasks"], outro, outro])
    ids = combinado["rounds"][0]["model_tasks"][0]["task_ids"]
    assert ids["reference_date"]["optional"] == ["2025-01-02", "2026-11-13"]
    assert len(ids["location"]["optional"]) == 2
    assert set(ids["target"]["optional"]) == set(Q.ALVOS)
    for linha in _tabela(r).to_pylist():
        assert str(linha["reference_date"]) in ids["reference_date"]["optional"]
        assert linha["location"] in ids["location"]["optional"]
        assert linha["target"] in ids["target"]["optional"]
    for alvo in combinado["rounds"][0]["model_tasks"][0]["target_metadata"]:
        assert len(alvo["target_id"]) <= 30 and len(alvo["target_name"]) <= 100
        assert alvo["is_step_ahead"] is False
    assert combinado["output_type_id_datatype"] == "double"


def test_saida_reprodutivel_sem_relogio_e_versao_muda_modelo(tmp_path):
    arquivo = _escrever(tmp_path, "flag", [_flag()])
    primeiro = Q.quantis_uf(tmp_path, "PA")
    assert primeiro["arquivos"] == Q.quantis_uf(tmp_path, "PA")["arquivos"]
    segundo = Q.quantis_uf(tmp_path, "PA", {arquivo.name: {"versao": "flag-novo"}})
    assert set(primeiro["modelos"]) != set(segundo["modelos"])


def test_parquet_vazio_e_model_output_tem_tipos_estaveis(tmp_path):
    r = Q.quantis_uf(tmp_path, "PA")
    assert _tabela(r).schema.field("reference_date").type == pa.date32()
    assert _tabela(r).schema.field("output_type_id").type == pa.float64()
    assert _tabela(r).num_rows == 0
    assert not any(n.startswith("model-output/") for n in _hub(r))
