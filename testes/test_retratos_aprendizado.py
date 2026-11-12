"""Captura sem banco, privacidade em disco e chegada atrasada ao scd2."""

import datetime as dt
import gzip
import hashlib
import io
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from raiz.aprendizado import arquivo_historico as A
from raiz.aprendizado import retratos as R
from raiz.aprendizado.captura import Captura
from raiz.aprendizado.importacao import importar_retrato
from raiz.aprendizado.reexecucao import HistoricoInsuficiente
from raiz.funil import rodar as RD
from raiz.operacao.healthchecks import Healthchecks
from testes.test_privacidade import gerar_cpf

COD = "PA-TESTE-HISTORICO"
MUNICIPIO = 1504950


def _guardar(tmp_path, monkeypatch, dia=1, pasto=0.2, vazia=False):
    class Relogio(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2020, 1, dia, tzinfo=dt.UTC)

    monkeypatch.setattr(R.dt, "datetime", Relogio)
    cap = Captura("PA", MUNICIPIO)
    if vazia:
        cap.fonte("entrada_flag", pd.DataFrame(columns=("cod_imovel", "atributos", "contexto")))
    else:
        cap.entrada("flag", {"cod_imovel": COD, "ha": 0.3, "mb_pasto_2023_ha": pasto, "alem_RL_ha": 0.3})
    resultado = R.guardar(cap, "flag", tmp_path)
    return tmp_path / "PA" / str(MUNICIPIO) / f"{resultado['retrato_hash']}.json.gz"


def test_retrato_somente_dados_publicos_versao_hash_e_gravacao_idempotente(tmp_path, monkeypatch):
    cpf = gerar_cpf("".join(str(i) for i in range(1, 10)))
    cap = Captura("PA", MUNICIPIO)
    cap.entrada("flag", {"cod_imovel": COD, "ha": 0.3, "documento": int(cpf), "nome": "Pessoa que não pode ir"})
    r = R.guardar(cap, "flag", tmp_path)
    arquivo = tmp_path / "PA" / str(MUNICIPIO) / f"{r['retrato_hash']}.json.gz"
    obj = R.validar_retrato(arquivo)
    bruto = gzip.decompress(arquivo.read_bytes())
    assert cpf.encode() not in bruto and b"Pessoa que" not in bruto
    assert obj["dados"]["entrada_flag"][0]["atributos"] == {"ha": 0.3}
    assert obj["tarefa_versao"].startswith("flag-") and len(obj["captura_versao"]) == 64
    assert hashlib.sha256(bruto).hexdigest() == r["retrato_hash"]
    a = _guardar(tmp_path, monkeypatch)
    b = _guardar(tmp_path, monkeypatch)
    assert a == b and R.validar_retrato(a) == R.validar_retrato(b)


def test_alteracao_nome_dados_pessoais_e_versao_desconhecida_sao_recusados(tmp_path, monkeypatch):
    arquivo = _guardar(tmp_path, monkeypatch)
    original = R.validar_retrato(arquivo)
    arquivo.write_bytes(gzip.compress(b"{}", mtime=0))
    with pytest.raises(HistoricoInsuficiente, match="hash"):
        R.validar_retrato(arquivo)
    for novo in ({**original, "formato": 99}, {**original, "segredo": "não pertence ao contrato"}):
        bruto = R.canonico(novo)
        f = tmp_path / f"{hashlib.sha256(bruto).hexdigest()}.json.gz"
        f.write_bytes(gzip.compress(bruto, mtime=0))
        with pytest.raises(HistoricoInsuficiente, match="formato"):
            R.validar_retrato(f)
    original["dados"]["entrada_flag"][0]["atributos"]["nome"] = "não pode ser publicado"
    bruto = R.canonico(original)
    f = tmp_path / f"{hashlib.sha256(bruto).hexdigest()}.json.gz"
    f.write_bytes(gzip.compress(bruto, mtime=0))
    with pytest.raises(HistoricoInsuficiente, match="contrato"):
        R.validar_retrato(f)


def test_executor_sem_banco_captura_chamada_real_e_nao_redata_saida_pronta(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(RD, "_R", SimpleNamespace())
    monkeypatch.setattr(RD, "_engine", lambda *a: pytest.fail("conectou ao banco"))
    spool = tmp_path / "retratos"
    monkeypatch.setenv("RAIZ_HISTORICO_DIR", str(spool))
    pasta = tmp_path / "saida" / "PA"
    pasta.mkdir(parents=True)
    pd.DataFrame([{"cod_imovel": COD, "ha": 0.3, "alem_RL_ha": 0.3, "uf": "PA", "bioma": "Amazônia"}]).to_csv(
        pasta / f"imoveis_{MUNICIPIO}.csv", index=False
    )
    pd.DataFrame([{"cod_imovel": COD, "mb_pasto_2023_ha": 0.2}]).to_csv(
        pasta / f"mapbiomas_{MUNICIPIO}.csv", index=False
    )
    op = RD.Opcoes("PA", tarefas=("flag",), banco=False)
    assert RD.rodar_municipio(MUNICIPIO, op, Healthchecks()) == {"flag": "sucesso"}
    arquivos = list(spool.rglob("*.json.gz"))
    assert len(arquivos) == 1
    obj = R.validar_retrato(arquivos[0])
    assert obj["dados"]["entrada_flag"][0]["atributos"]["mb_pasto_2023_ha"] == 0.2
    assert RD.rodar_municipio(MUNICIPIO, op, Healthchecks()) == {"flag": "pulado"}
    assert list(spool.rglob("*.json.gz")) == arquivos


@pytest.mark.banco
def test_importacao_fora_de_ordem_preserva_futuro_retirada_e_deduplicacao(con, tmp_path, monkeypatch):
    esquema = "retratos_" + uuid.uuid4().hex[:8]
    monkeypatch.setattr(A, "ESQUEMA", esquema)
    arqs = {
        d: _guardar(tmp_path, monkeypatch, d, p, vazio)
        for d, p, vazio in ((1, 0.1, False), (2, 0.2, False), (3, 0.1, False), (4, None, True), (5, 0.5, False))
    }
    for d in (1, 5, 3, 4, 2):
        r = importar_retrato(con, arqs[d])
        assert r["situacao"] == "importado"
        assert dt.datetime.fromisoformat(r["registrado_em"]) > dt.datetime.fromisoformat(r["observado_em"])
    assert importar_retrato(con, arqs[2])["situacao"] == "ja_importado"
    assert con.execute(text(f"select count(*) from {esquema}.coleta")).scalar() == 5
    for dia, esperado in ((1, 0.1), (2, 0.2), (3, 0.1), (4, None), (5, 0.5)):
        valor = con.execute(
            text(
                f"select atributos->>'mb_pasto_2023_ha' from {esquema}.entrada_flag "
                "where _dlt_valid_from<=:c and (_dlt_valid_to is null or _dlt_valid_to>:c)"
            ),
            {"c": dt.datetime(2020, 1, dia, 12, tzinfo=dt.UTC)},
        ).scalar()
        assert (float(valor) if valor else None) == esperado
    cat = A.catalogo(con, MUNICIPIO)
    assert cat["entrada_flag"].desde == dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    assert cat["entrada_flag"].ate == dt.datetime(2020, 1, 5, tzinfo=dt.UTC)
    assert (
        con.execute(text(f"select count(*) from {esquema}.entrada_flag where _dlt_valid_from<'2020-01-01'")).scalar()
        == 0
    )
    # A retirada atrasada não apaga o estado já confirmado no dia seguinte.
    atual = con.execute(
        text(f"select atributos->>'mb_pasto_2023_ha' from {esquema}.entrada_flag where _dlt_valid_to is null")
    ).scalar_one()
    assert float(atual) == 0.5


@pytest.mark.banco
def test_fonte_ausente_nao_fecha_e_retrato_futuro_nao_entra(con, tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ESQUEMA", "ausente_" + uuid.uuid4().hex[:8])
    arq = _guardar(tmp_path, monkeypatch)
    importar_retrato(con, arq)
    A.arquivar(
        con,
        {
            "ibama": pd.DataFrame(
                columns=("seq_tad", "cod_municipio", "sit_cancelado", "sit_desembargo", "geom_area_embargada")
            )
        },
        "PA",
        MUNICIPIO,
        exigir_completo=False,
    )
    assert con.execute(text(f"select count(*) from {A.ESQUEMA}.entrada_flag where _dlt_valid_to is null")).scalar() == 1
    obj = R.validar_retrato(arq)
    obj["observado_em"] = "2999-01-01T00:00:00+00:00"
    bruto = R.canonico(obj)
    futuro = tmp_path / f"{hashlib.sha256(bruto).hexdigest()}.json.gz"
    futuro.write_bytes(gzip.compress(bruto, mtime=0))
    with pytest.raises(HistoricoInsuficiente, match="futuro"):
        importar_retrato(con, futuro)


@pytest.mark.banco
def test_carregar_recebe_historico_publicado_e_fold_funciona_sem_fontes_atuais(banco_url, tmp_path, monkeypatch):
    from raiz import carga_continua
    from raiz.aprendizado import reexecucao
    from raiz.aprendizado.transporte import publicar
    from raiz.executor.armazem import ArmazemLocal
    from raiz.executor.sincronizar import carregar

    monkeypatch.setattr(A, "ESQUEMA", "recebido_" + uuid.uuid4().hex[:8])
    monkeypatch.setattr(carga_continua, "varrer", lambda *a, **kw: {"carregados": []})
    spool, espelho = tmp_path / "spool", tmp_path / "espelho"
    arquivo = _guardar(spool, monkeypatch)
    armazem = ArmazemLocal(tmp_path / "armazem")
    assert publicar(spool, armazem)["publicados"] == 1
    with create_engine(banco_url).connect() as con:
        engine = con.engine
        primeiro = carregar(engine, armazem, ["PA"], espelho)
        segundo = carregar(engine, armazem, ["PA"], espelho)
        assert primeiro["historico_aprendizado"]["importados"] == 1
        assert segundo["historico_aprendizado"]["ja_importados"] == 1
        cat = A.catalogo(con, MUNICIPIO)
        resultado = reexecucao.reexecutar(
            con, [cat["entrada_flag"].desde], "PA", MUNICIPIO, cat, ("flag",), congelar=False
        )
        assert resultado[0]["situacao"] == "ok" and resultado[0]["previsoes"] == 1
        hash_db = con.execute(text(f"select retrato_hash from {A.ESQUEMA}.coleta")).scalar_one()
        assert hash_db == arquivo.name.removesuffix(".json.gz")


@pytest.mark.parametrize("alteracao", ["nome", "comentario", "relogio", "membro_extra", "sobras"])
def test_gzip_nao_transporta_metadados_ou_membros_ocultos(tmp_path, monkeypatch, alteracao):
    arquivo = _guardar(tmp_path, monkeypatch)
    normal = arquivo.read_bytes()
    bruto = gzip.decompress(normal)
    pessoa = "PessoaTeste-" + gerar_cpf("".join(str(i) for i in range(1, 10)))
    if alteracao == "nome":
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, filename=pessoa, mode="wb", mtime=0) as f:
            f.write(bruto)
        adulterado = buf.getvalue()
    elif alteracao == "comentario":
        adulterado = normal[:3] + bytes([16]) + normal[4:10] + pessoa.encode() + b"\x00" + normal[10:]
    elif alteracao == "relogio":
        adulterado = gzip.compress(bruto, mtime=1)
    elif alteracao == "membro_extra":
        adulterado = normal + gzip.compress(b"", mtime=0)
    else:
        adulterado = normal + pessoa.encode()
    arquivo.write_bytes(adulterado)
    with pytest.raises(HistoricoInsuficiente, match="gzip"):
        R.validar_retrato(arquivo)
