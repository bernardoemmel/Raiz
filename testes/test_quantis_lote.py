"""Três perfis preservam valores, contexto histórico e isolamento dos produtos do lote."""

import copy
import csv
import datetime as dt
import hashlib
import io
import json
import tarfile

import jsonschema
import pyarrow.parquet as pq
import pytest
import yaml

from raiz import quantis as Q
from raiz import quantis_lote as L

BASE_URL = "release-github://exemplo/raiz/dados-privados/"
CAR_A = "PA-1500107-" + "A" * 32
CAR_B = "PA-1500206-" + "B" * 32
ORIGINAL = "restauracao-original"


def _csv(linhas):
    colunas = list(dict.fromkeys(campo for linha in linhas for campo in linha))
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=colunas)
    escritor.writeheader()
    escritor.writerows(linhas)
    return saida.getvalue().encode()


def _previsao(car):
    linha = {"cod_imovel": car, "restauracao_versao": ORIGINAL}
    for _, _, colunas in L.ALVOS["previsoes"].values():
        linha.update(zip(colunas, (1.125, 2.25, 3.5), strict=True))
    return linha


def _opcao(car, papel="titular", area=0.01):
    return {
        "cod_imovel": car,
        "papel": papel,
        "restauracao_versao": ORIGINAL,
        "area_ha": area,
        "credito_p10": 1.125,
        "credito_p50": 2.25,
        "credito_p90": 3.5,
        "tir_p10": -2.3,
        "tir_p50": 5.4,
        "tir_p90": 12.6,
    }


def _fixture(tmp_path, *, previsoes=None, opcoes=None, resumo_faixa=None, hash_municipal=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    manifesto = {
        "uf": "PA",
        "cenario": "central_r11",
        "municipios_calculados": 2,
        "commit": "commit-consolidacao",
        "execucao": "execucao-consolidacao",
        "retomada": {
            "execucao_origem": "run-origem",
            "sha_origem": "commit-origem",
            "execucao_atual": "run-retomada",
            "sha_orquestrador": "commit-orquestrador",
            "fatias_reusadas": ["01", "02"],
            "fatias_calculadas": ["03"],
            "campo_nao_tecnico": "NAO_COPIAR",
        },
        "resumos": {},
        "arquivos": {},
    }
    membros, pacotes = {}, {}
    for opcao in L.OPCOES:
        resumo = {
            "data": "2026-11-12",
            "opcao": opcao,
            "versao_modelo_lote": "modelo-lote-original",
            "versao_premissas": ORIGINAL,
            "versao_otimizador": "otimizador-original",
            "creditos_lote_faixa": resumo_faixa or {"p10": 10.125, "p50": 20.25, "p90": 30.5},
        }
        manifesto["resumos"][opcao] = resumo
        linhas = (opcoes or {}).get(opcao, [_opcao(CAR_A), _opcao(CAR_B, "reserva", 5000)])
        membros[opcao] = {
            f"{opcao}/lote_PA.csv": _csv(linhas),
            f"{opcao}/lote_PA.json": json.dumps(resumo).encode(),
        }
    municipios = []
    membros["previsoes"] = {}
    for codigo, linhas in (previsoes or {"1500107": [_previsao(CAR_A)], "1500206": [_previsao(CAR_B)]}).items():
        nome = f"desenvolvedor_{codigo}.csv"
        bruto = _csv(linhas)
        membros["previsoes"]["previsoes/" + nome] = bruto
        municipios.append(
            {
                "arquivos": {nome: hash_municipal or hashlib.sha256(bruto).hexdigest()},
                "modelo_versao": ORIGINAL,
            }
        )
    membros["previsoes"]["municipios.json"] = json.dumps(municipios).encode()
    for opcao, arquivos in membros.items():
        nome = f"lote_PA_central_r11_123_1_{opcao}.tar.gz"
        pacote = tmp_path / nome
        with tarfile.open(pacote, "w:gz") as tar:
            diretorio = tarfile.TarInfo(opcao)
            diretorio.type = tarfile.DIRTYPE
            tar.addfile(diretorio)
            for caminho, dados in sorted(arquivos.items()):
                info = tarfile.TarInfo(caminho)
                info.size = len(dados)
                tar.addfile(info, io.BytesIO(dados))
        pacotes[opcao] = pacote
        manifesto["arquivos"][opcao] = {
            "nome": nome,
            "sha256": hashlib.sha256(pacote.read_bytes()).hexdigest(),
            "bytes": pacote.stat().st_size,
        }
    digest = hashlib.sha256(json.dumps(manifesto, sort_keys=True).encode()).hexdigest()
    return manifesto, digest, pacotes, membros


def _exportar(tmp_path, **kwargs):
    manifesto, digest, pacotes, membros = _fixture(tmp_path / "fontes", **kwargs)
    resultado = L.exportar(manifesto, digest, pacotes, tmp_path / "saida", base_url=BASE_URL)
    return resultado, manifesto, digest, membros


def _arquivo(resultado, sufixo):
    return next(arquivo for nome, arquivo in resultado["arquivos"].items() if nome.endswith(sufixo))


def _json(resultado, sufixo):
    return json.loads(_arquivo(resultado, sufixo).read_text())


def test_tres_perfis_preservam_valores_versoes_e_proveniencia(tmp_path):
    resultado, manifesto, digest, membros = _exportar(tmp_path)
    assert len(resultado["arquivos"]) == 16
    assert {p: resultado["contagens"][p]["linhas"] for p in L.PERFIS} == {"resumos": 9, "previsoes": 48, "opcoes": 36}
    assert all(nome.startswith(f"lote_PA_central_r11_{digest[:16]}_") for nome in resultado["arquivos"])
    assert not {"quantis_PA.parquet", "tasks.json", "modelos.json", "hub_PA.tar.gz"} & set(resultado["arquivos"])
    for perfil in L.PERFIS:
        tabela = pq.read_table(_arquivo(resultado, f"_{perfil}_quantis.parquet"))
        assert tabela.schema == L.esquema(perfil)
        assert tabela.schema.field("task_version").nullable == (perfil == "previsoes")
        linhas = tabela.to_pylist()
        assert {linha["reference_date"] for linha in linhas} == {dt.date(2026, 11, 12)}
        assert {linha["reference_date_source"] for linha in linhas} == {L.DATAS[perfil]}
        assert {linha["source_manifest_sha256"] for linha in linhas} == {digest}
        assert {linha["source_model_version"] for linha in linhas} == {ORIGINAL}
        assert {linha["model_version"] for linha in linhas} == (
            {ORIGINAL} if perfil == "previsoes" else {"modelo-lote-original"}
        )
        assert {linha["task_version"] for linha in linhas} == (
            {None} if perfil == "previsoes" else {"otimizador-original"}
        )
        for linha in linhas:
            opcao = "previsoes" if perfil == "previsoes" else linha["opcao"]
            assert linha["source_member_sha256"] == hashlib.sha256(membros[opcao][linha["source_file"]]).hexdigest()
            assert linha["source_archive_sha256"] == manifesto["arquivos"][opcao]["sha256"]
        modelos = _json(resultado, f"_{perfil}_modelos.json")
        assert modelos["proveniencia"]["manifesto"] == {
            "sha256": digest,
            "commit": manifesto["commit"],
            "execucao": manifesto["execucao"],
        }
        assert modelos["proveniencia"]["retomada"] == {
            k: v for k, v in manifesto["retomada"].items() if k != "campo_nao_tecnico"
        }
        assert "NAO_COPIAR" not in json.dumps(modelos)
        schema = _json(resultado, f"_{perfil}_model-metadata-schema.json")
        for modelo in modelos["modelos"].values():
            jsonschema.validate(modelo, schema)
            if perfil != "previsoes":
                with pytest.raises(jsonschema.ValidationError):
                    jsonschema.validate({**modelo, "task_version": None}, schema)
        ids = _json(resultado, f"_{perfil}_tasks.json")["rounds"][0]["model_tasks"][0]["task_ids"]
        assert set(ids["target"]["optional"]) == set(L.ALVOS[perfil])
        assert ids["reference_date"]["optional"] == ["2026-11-12"]
    opcoes = pq.read_table(_arquivo(resultado, "_opcoes_quantis.parquet")).to_pylist()
    assert {linha["papel"] for linha in opcoes} == {"titular", "reserva"}
    assert len({linha["model_id"] for linha in opcoes if linha["location"] == CAR_A}) == 3
    assert {linha["value"] for linha in opcoes if linha["target"] == "tir_pct"} == {-2.3, 5.4, 12.6}
    previsoes = pq.read_table(_arquivo(resultado, "_previsoes_quantis.parquet")).to_pylist()
    assert {linha["value"] for linha in previsoes} == {1.125, 2.25, 3.5}
    assert "flag_tco2_ano" not in {linha["target"] for linha in previsoes}
    diagnosticos = _json(resultado, "_diagnosticos_quantis.json")["diagnosticos"]
    assert len(diagnosticos) == 2
    assert {d["codigo"] for d in diagnosticos} == {"versao_da_tarefa_individual_ausente"}
    assert CAR_A not in json.dumps(diagnosticos)


def test_hub_nativo_tem_seis_colunas_e_modelos_separados(tmp_path):
    resultado, _, _, _ = _exportar(tmp_path)
    for perfil in L.PERFIS:
        quantidade = 0
        with tarfile.open(_arquivo(resultado, f"_{perfil}_hub.tar.gz")) as tar:
            nomes = tar.getnames()
            assert "hub-config/tasks.json" in nomes
            schema = json.load(tar.extractfile("hub-config/model-metadata-schema.json"))
            for membro in tar:
                assert membro.isfile() and membro.mtime == 0
                if membro.name.endswith(".parquet"):
                    tabela = pq.read_table(io.BytesIO(tar.extractfile(membro).read()))
                    assert tabela.schema == Q.ESQUEMA_SAIDA
                    assert tabela.column_names == Q.COLUNAS
                    quantidade += tabela.num_rows
                elif membro.name.endswith(".yml"):
                    jsonschema.validate(yaml.safe_load(tar.extractfile(membro)), schema)
        assert quantidade == resultado["contagens"][perfil]["linhas"]


def test_batches_limitados_hub_por_paths_e_saida_reproduzivel(tmp_path, monkeypatch):
    manifesto, digest, pacotes, _ = _fixture(tmp_path / "fontes")
    escritor = pq.ParquetWriter
    tamanhos = []

    class Espiao:
        def __init__(self, *args, **kwargs):
            self.original = escritor(*args, **kwargs)

        def write_table(self, tabela):
            tamanhos.append(tabela.num_rows)
            self.original.write_table(tabela)

        def close(self):
            self.original.close()

    monkeypatch.setattr(pq, "ParquetWriter", Espiao)
    monkeypatch.setattr(L, "TAMANHO_LOTE", 5)
    monkeypatch.setattr(Q, "_tar", lambda *a: pytest.fail("hub grande deve usar streaming de arquivos"))
    primeiro = L.exportar(manifesto, digest, pacotes, tmp_path / "primeiro", base_url=BASE_URL)
    segundo = L.exportar(manifesto, digest, pacotes, tmp_path / "segundo", base_url=BASE_URL)
    assert tamanhos and max(tamanhos) <= 7
    for nome, arquivo in primeiro["arquivos"].items():
        assert arquivo.read_bytes() == segundo["arquivos"][nome].read_bytes()


def test_diagnostica_faixas_sem_reordenar_duplicatas_e_papel(tmp_path):
    cruzada = {**_previsao(CAR_A), "custo_restauracao_ha_p10": 10}
    invalida = {**_previsao(CAR_B), "vpl_rs_ha_p50": "inf", "tir_projeto_pct_p50": ""}
    opcoes = {
        "barata": [_opcao(CAR_A), _opcao(CAR_A)],
        "segura": [_opcao(CAR_A, "DESCONHECIDO")],
        "compacta": [{**_opcao(CAR_B), "tir_p10": 20}],
    }
    resultado, _, _, _ = _exportar(
        tmp_path,
        previsoes={"1500107": [cruzada, cruzada], "1500206": [invalida]},
        opcoes=opcoes,
        resumo_faixa={"p10": 20, "p50": 10, "p90": 30},
    )
    assert resultado["contagens"]["resumos"]["linhas"] == 0
    assert resultado["contagens"]["previsoes"]["linhas"] == 39
    assert resultado["contagens"]["opcoes"]["linhas"] == 9
    diagnosticos = _json(resultado, "_diagnosticos_quantis.json")["diagnosticos"]
    codigos = {d["codigo"] for d in diagnosticos}
    assert {
        "quantis_cruzados",
        "codigo_car_duplicado",
        "valor_nao_finito",
        "valor_ausente",
        "papel_ausente_ou_desconhecido",
    } <= codigos
    assert CAR_A not in json.dumps(diagnosticos) and CAR_B not in json.dumps(diagnosticos)


def test_coluna_ausente_nao_cria_faixa_e_modelo_ausente_nao_emite(tmp_path):
    parcial = _previsao(CAR_A)
    parcial.pop("vpl_rs_ha_p90")
    sem_versao = {**_previsao(CAR_B), "restauracao_versao": ""}
    resultado, _, _, _ = _exportar(tmp_path, previsoes={"1500107": [parcial], "1500206": [sem_versao]})
    assert resultado["contagens"]["previsoes"]["linhas"] == 21
    codigos = {d["codigo"] for d in _json(resultado, "_diagnosticos_quantis.json")["diagnosticos"]}
    assert {"coluna_de_quantil_ausente", "versao_do_modelo_ausente"} <= codigos


@pytest.mark.parametrize("caso", ["pacote", "municipio", "cobertura", "resumo", "versao"])
def test_proveniencia_divergente_falha_sem_promover_saidas(tmp_path, caso):
    kwargs = {"hash_municipal": "0" * 64} if caso == "municipio" else {}
    manifesto, digest, pacotes, _ = _fixture(tmp_path / "fontes", **kwargs)
    if caso == "pacote":
        manifesto["arquivos"]["previsoes"]["sha256"] = "0" * 64
    elif caso == "cobertura":
        manifesto["municipios_calculados"] = 144
    elif caso == "resumo":
        manifesto["resumos"]["barata"]["creditos_lote_faixa"]["p50"] = 21
    elif caso == "versao":
        manifesto["resumos"]["barata"].pop("versao_otimizador")
    with pytest.raises(ValueError):
        L.exportar(manifesto, digest, pacotes, tmp_path / "saida", base_url=BASE_URL)
    assert not list((tmp_path / "saida").glob("*.parquet"))
    assert not list((tmp_path / "saida").glob("*.tar.gz"))


def test_muda_identidade_quando_muda_manifesto_sem_inventar_versao(tmp_path):
    manifesto, digest, pacotes, _ = _fixture(tmp_path / "fontes")
    primeiro = L.exportar(manifesto, digest, pacotes, tmp_path / "primeiro", base_url=BASE_URL)
    segundo = L.exportar(manifesto, "a" * 64, pacotes, tmp_path / "segundo", base_url=BASE_URL)
    assert set(_json(primeiro, "_opcoes_modelos.json")["modelos"]).isdisjoint(
        _json(segundo, "_opcoes_modelos.json")["modelos"]
    )
    assert {m["model_version"] for m in _json(segundo, "_opcoes_modelos.json")["modelos"].values()} == {
        "modelo-lote-original"
    }


def test_aceita_referencia_publicada_com_nome_como_chave(tmp_path):
    manifesto, digest, pacotes, _ = _fixture(tmp_path / "fontes")
    manifesto["arquivos"] = {info["nome"]: copy.deepcopy(info) for info in manifesto["arquivos"].values()}
    resultado = L.exportar(manifesto, digest, pacotes, tmp_path / "saida", base_url=BASE_URL)
    assert resultado["contagens"]["resumos"]["linhas"] == 9


def test_caminho_malicioso_no_tar_e_recusado_antes_de_exportar(tmp_path):
    manifesto, digest, pacotes, _ = _fixture(tmp_path / "fontes")
    pacote = pacotes["barata"]
    with tarfile.open(pacote, "w:gz") as tar:
        membro = tarfile.TarInfo("../fora.csv")
        membro.size = 4
        tar.addfile(membro, io.BytesIO(b"a\n1\n"))
    manifesto["arquivos"]["barata"].update(
        sha256=hashlib.sha256(pacote.read_bytes()).hexdigest(), bytes=pacote.stat().st_size
    )
    with pytest.raises(ValueError, match="membro inválido"):
        L.exportar(manifesto, digest, pacotes, tmp_path / "saida", base_url=BASE_URL)
    assert not (tmp_path / "fora.csv").exists()
