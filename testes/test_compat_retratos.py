"""Fechamento repetido legado: preserva identidade sem abrir exceção genérica."""

import copy
import gzip
import hashlib
import json
import uuid

import geopandas as gpd
import pandas as pd
import pytest
from shapely import from_wkt
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import text

from raiz.aprendizado import arquivo_historico as A
from raiz.aprendizado import compat_retratos as C
from raiz.aprendizado import retratos as R
from raiz.aprendizado import transporte as T
from raiz.aprendizado.captura import Captura
from raiz.aprendizado.importacao import importar_retrato
from raiz.aprendizado.reexecucao import HistoricoInsuficiente
from raiz.executor.armazem import ArmazemLocal


def _legado(pasta, repeticoes=2, multipoligono=False):
    geom = Polygon([(1, 0), (1, 1), (0, 1), *[(0, 0)] * repeticoes, (1, 0)])
    if multipoligono:
        geom = MultiPolygon([geom])
    cap = Captura("PA", 1504950)
    cap.fonte("acc", gpd.GeoDataFrame(geometry=[geom], crs=4674))
    cap.fonte(
        "car",
        gpd.GeoDataFrame(
            {"cod_imovel": ["PA-1504950-" + "A" * 32], "status_imovel": ["AT"], "tipo_imovel": ["IRU"],
             "municipio": ["Nova Esperança do Piriá"], "m_fiscal": [0.3], "_hash": ["a" * 64]},
            geometry=[geom], crs=4674,
        ),
    )  # fmt: skip
    cap.fonte(
        "regeneracao",
        pd.DataFrame([{"cod_imovel": "PA-1504950-" + "A" * 32, "car_hash": "a" * 64, "pasto_ha": 0.3,
                       "secundaria_ha": 0.0, "pasto_ate1km_ha": 0.1}]),
    )  # fmt: skip
    cap.entrada("flag", {"cod_imovel": "PA-1504950-" + "A" * 32, "ha": 0.3})
    r = R.guardar(cap, "funil", pasta)
    return pasta / "PA" / "1504950" / f"{r['retrato_hash']}.json.gz"


def _gravar(pasta, obj, *, espacos=False):
    bruto = json.dumps(obj).encode() if espacos else R.canonico(obj)
    arquivo = pasta / f"{hashlib.sha256(bruto).hexdigest()}.json.gz"
    arquivo.write_bytes(gzip.compress(bruto, mtime=0))
    return arquivo


def _hash_linha(li, *, chave_derivada=False):
    conteudo = {k: v for k, v in li.items() if k not in ("_chave", "_linha_hash")}
    li["_linha_hash"] = hashlib.sha256(json.dumps(conteudo, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if chave_derivada:
        li["_chave"] = li["_linha_hash"]


@pytest.mark.parametrize("repeticoes", [2, 5, 100])
@pytest.mark.parametrize("multipoligono", [False, True])
def test_guarda_legada_valida_sem_mudar_bytes_hash_data_versoes_ou_car(tmp_path, repeticoes, multipoligono):
    arquivo = _legado(tmp_path, repeticoes, multipoligono)
    antes = arquivo.read_bytes()
    original = json.loads(gzip.decompress(antes))
    with pytest.raises(HistoricoInsuficiente, match="contrato público canônico"):
        R.validar_retrato(arquivo)
    assert C.validar_retrato(arquivo) == original
    assert arquivo.read_bytes() == antes
    assert arquivo.name == f"{hashlib.sha256(R.canonico(original)).hexdigest()}.json.gz"
    assert original["dados"]["car"][0]["_hash"] == original["dados"]["regeneracao"][0]["car_hash"]
    assert set(tmp_path.rglob("*.json.gz")) == {arquivo}


def test_leitor_estrito_normal_continua_sem_excecao(tmp_path):
    arquivo = _legado(tmp_path, repeticoes=1)
    assert C.validar_retrato(arquivo) == R.validar_retrato(arquivo)


@pytest.mark.parametrize("alteracao", ["geometria", "linha_hash", "chave", "atributo", "contexto", "tarefa", "captura"])
def test_mutacao_nao_aproveita_fechamento_para_ignorar_hash_ou_metadados(tmp_path, alteracao):
    arquivo = _legado(tmp_path)
    obj = json.loads(gzip.decompress(arquivo.read_bytes()))
    if alteracao == "geometria":
        obj["dados"]["acc"][0]["geom"] = "POLYGON ((0 0, 0 2, 1 1, 1 0, 0 0, 0 0))"
    elif alteracao == "linha_hash":
        obj["dados"]["acc"][0]["_linha_hash"] = "0" * 64
    elif alteracao == "chave":
        obj["dados"]["acc"][0]["_chave"] = "0" * 64
    elif alteracao == "atributo":
        obj["dados"]["entrada_flag"][0]["atributos"]["ha"] = 1.0
    elif alteracao == "contexto":
        obj["dados"]["entrada_flag"][0]["contexto"]["pasto_baixo_vigor_ha"] = 1.0
    elif alteracao == "tarefa":
        obj["tarefa_versao"] = "sem-versao"
    else:
        obj["captura_versao"] = "sem-versao"
    with pytest.raises(HistoricoInsuficiente):
        C.validar_retrato(_gravar(tmp_path, obj))


@pytest.mark.parametrize("alvo", ["atributos", "contexto", "geometria_rotacionada", "texto_wkt", "ordem", "json"])
def test_novo_hash_nao_aceita_pii_ou_equivalencia_topologica_generica(tmp_path, alvo):
    arquivo = _legado(tmp_path)
    obj = json.loads(gzip.decompress(arquivo.read_bytes()))
    if alvo in ("atributos", "contexto"):
        li = obj["dados"]["entrada_flag"][0]
        li[alvo]["nome"] = "Pessoa que não pode ir"
        _hash_linha(li)
    elif alvo in ("geometria_rotacionada", "texto_wkt"):
        li = obj["dados"]["acc"][0]
        li["geom"] = (
            "POLYGON ((1 0, 0 0, 0 0, 0 1, 1 1, 1 0))"
            if alvo == "geometria_rotacionada"
            else li["geom"].replace("POLYGON", "polygon")
        )
        assert from_wkt(li["geom"]).equals(from_wkt(obj["dados"]["car"][0]["geom"]))
        _hash_linha(li, chave_derivada=True)
    elif alvo == "ordem":
        li = copy.deepcopy(obj["dados"]["entrada_flag"][0])
        li["cod_imovel"] = li["_chave"] = "AA-TESTE-ANTES"
        _hash_linha(li)
        obj["dados"]["entrada_flag"].append(li)
    with pytest.raises(HistoricoInsuficiente, match="contrato"):
        C.validar_retrato(_gravar(tmp_path, obj, espacos=alvo == "json"))


@pytest.mark.parametrize("alteracao", ["nome", "relogio", "membro_extra", "sobras", "corpo"])
def test_gzip_e_identidade_originais_continuam_obrigatorios(tmp_path, alteracao):
    arquivo = _legado(tmp_path)
    dados = arquivo.read_bytes()
    if alteracao == "nome":
        arquivo = arquivo.rename(arquivo.with_name("0" * 64 + ".json.gz"))
    elif alteracao == "relogio":
        arquivo.write_bytes(gzip.compress(gzip.decompress(dados), mtime=1))
    elif alteracao == "membro_extra":
        arquivo.write_bytes(dados + gzip.compress(b"", mtime=0))
    elif alteracao == "sobras":
        arquivo.write_bytes(dados + b"conteudo-extra")
    else:
        arquivo.write_bytes(gzip.compress(b"{}", mtime=0))
    with pytest.raises(HistoricoInsuficiente):
        C.validar_retrato(arquivo)


def test_transporte_legado_copia_bytes_originais_e_deduplica(tmp_path):
    spool = tmp_path / "spool"
    arquivo = _legado(spool, repeticoes=5, multipoligono=True)
    original = arquivo.read_bytes()
    remoto = ArmazemLocal(tmp_path / "remoto")
    assert T.publicar(spool, remoto)["publicados"] == 1
    assert T.publicar(spool, remoto)["existentes"] == 1
    recebidos = T.sincronizar(remoto, tmp_path / "recebido", ["PA"])
    assert len(recebidos) == 1
    assert recebidos[0].name == arquivo.name
    assert recebidos[0].read_bytes() == arquivo.read_bytes() == original


@pytest.mark.banco
def test_importacao_preserva_origem_versoes_observacao_e_deduplica(con, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ESQUEMA", "compat_" + uuid.uuid4().hex[:8])
    arquivo = _legado(tmp_path)
    original = C.validar_retrato(arquivo)
    assert importar_retrato(con, arquivo)["situacao"] == "importado"
    assert importar_retrato(con, arquivo)["situacao"] == "ja_importado"
    linha = con.execute(text(f"select observado_em, retrato_hash, proveniencia from {A.ESQUEMA}.coleta")).one()
    assert linha.retrato_hash == arquivo.name.removesuffix(".json.gz")
    assert linha.observado_em.isoformat() == original["observado_em"]
    for campo in ("tarefa", "tarefa_versao", "captura_versao", "formato"):
        assert linha.proveniencia[campo] == original[campo]
