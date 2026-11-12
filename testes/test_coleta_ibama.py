import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from raiz.coleta.espelho import Espelho
from raiz.coleta.ibama import coletar
from raiz.coleta.replicacao import sincronizar_fontes
from testes.servidor_falso import sessao_falsa
from testes.test_privacidade import CNPJ, CPF, fmt_cpf

pytestmark = pytest.mark.banco
URL = "https://ibama.exemplo/termo_de_embargo.csv"


def _csv(linhas):
    cab = (
        "SEQ_TAD;NUM_TAD;NOME_PESSOA_EMBARGADA;CPF_CNPJ_EMBARGADO;NOME_IMOVEL;UF;COD_MUNICIPIO;MUNICIPIO;"
        "DES_TAD;DAT_ULT_ALTERACAO;DAT_ULT_ALTER_GEOM;SIT_CANCELADO;SIT_DESEMBARGO;GEOM_AREA_EMBARGADA"
    )
    return "﻿" + cab + "\n" + "\n".join(linhas) + "\n"


def _linha(seq, cod, alt="2026-01-01", desc="Desmatar floresta"):
    return (
        f"{seq};{seq}0;Fulano de Tal;{fmt_cpf(CPF)};Fazenda Boa Vista;PA;{cod};Município;{desc} (ref {CNPJ});"
        f"{alt};{alt};N;N;POLYGON((-47.3 -2.3,-47.29 -2.3,-47.29 -2.29,-47.3 -2.29,-47.3 -2.3))"
    )


def test_ibama_condicional_e_sem_dado_pessoal(banco_url, tmp_path):
    publicado = {"etag": '"v1"', "csv": _csv([_linha(1, 1504950), _linha(2, 1504950), _linha(3, 1500107)])}

    def responder(metodo, base, p, h):
        if h.get("If-None-Match") == publicado["etag"]:
            return 304, {}, ""
        return 200, {"ETag": publicado["etag"]}, publicado["csv"]

    s, srv = sessao_falsa(responder)
    eng = create_engine(banco_url)
    esp = Espelho(tmp_path / "espelho")
    cache = tmp_path / "motor_cache"
    with eng.begin() as c:
        c.execute(text("truncate coleta.replicacao, coleta.evento cascade"))
        sincronizar_fontes(c)
        r = coletar(s, c, esp, cache, URL)
        assert r.acao == "atualizado" and r.linhas == 3
        assert {"NOME_PESSOA_EMBARGADA", "CPF_CNPJ_EMBARGADO", "NOME_IMOVEL"} <= set(r.removidas)
        assert set(r.municipios) == {1504950, 1500107}
        # nada pessoal no espelho nem no cache do motor
        for arq in [*tmp_path.rglob("*.parquet"), cache / "termo_de_embargo.csv"]:
            conteudo = arq.read_bytes()
            assert b"Fulano" not in conteudo and CPF.encode() not in conteudo and CNPJ.encode() not in conteudo
        motor = pd.read_csv(cache / "termo_de_embargo.csv", sep=";", dtype=str, encoding="utf-8-sig")
        assert {"SEQ_TAD", "COD_MUNICIPIO", "SIT_CANCELADO", "GEOM_AREA_EMBARGADA"} <= set(motor.columns)
        assert (cache / "termo_de_embargo.etag").read_text() == '"v1"'

        # mesma versão publicada: 304, nada baixado
        assert coletar(s, c, esp, cache, URL).acao == "sem_mudanca"
        assert srv.pedidos[-1][3]["If-None-Match"] == '"v1"'

        # nova versão: termo 2 alterado e termo 3 retirado; só o que mudou aparece
        publicado.update(etag='"v2"', csv=_csv([_linha(1, 1504950), _linha(2, 1504950, alt="2026-11-01")]))
        r = coletar(s, c, esp, cache, URL)
        assert r.municipios[1504950].mudaram == ["2"] and r.municipios[1500107].sumiram == ["3"]
        assert esp.ler("ibama", "PA", 1504950).crs.to_epsg() == 4674
    eng.dispose()
