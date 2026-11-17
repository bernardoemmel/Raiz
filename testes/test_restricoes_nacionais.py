"""Restrições nacionais na triagem: SICAR completo, SIGMINE, autos do Ibama e Lista Suja. Nenhum teste vai à rede.

Os documentos de teste são gerados na hora (dígitos verificadores calculados aqui): nenhum CPF ou CNPJ fica escrito
neste arquivo, e o teste confere que nenhum sai na camada gravada.
"""

import io
import json
import zipfile

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from raiz.restricoes import coleta as RC
from raiz.restricoes import status as RS

COD = 1507300  # São Félix do Xingu (PA)
X0, Y0 = -52.0, -6.6
HOJE = "2026-11-17"


def _dv(nums, pesos):
    r = sum(n * p for n, p in zip(nums, pesos, strict=False)) % 11
    return 0 if r < 2 else 11 - r


def _cpf(base: str) -> str:
    d = [int(c) for c in base]
    d.append(_dv(d, range(10, 1, -1)))
    d.append(_dv(d, range(11, 1, -1)))
    s = "".join(map(str, d))
    return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"


def _cnpj(base: str) -> str:
    d = [int(c) for c in base]
    d.append(_dv(d, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    d.append(_dv(d, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    s = "".join(map(str, d))
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


CPF_LISTADO = _cpf("123456789")
CNPJ_LISTADO = _cnpj("112223330001")
CPF_OUTRO = _cpf("987654321")


def _texto_lista():
    return (
        "Cadastro de Empregadores\nID\nAno da\nação\n"
        f"1 2024 PA FULANO DE TAL {CPF_LISTADO} FAZENDA BOA ESPERANÇA, ZONA RURAL, SÃO FÉLIX DO\n"
        "XINGU/PA 12 0151-2/01 10/03/2025 06/10/2025\n"
        f"2 2023 MT EMPRESA EXEMPLO LTDA {CNPJ_LISTADO} RODOVIA MT 235, KM 10, COMODORO-MT 3 0210-1/08 08/10/2024 "
        "09/04/2025\n"
        f"3 2024 SP BELTRANO {_cpf('111222333')} RESIDÊNCIA DO EMPREGADOR 1 9700-5/00 25/10/2024 09/04/2025\n"
    )


# --- coleta ------------------------------------------------------------------------------------------------------


def test_lista_suja_le_o_pdf_em_texto_e_so_o_agregado_sai():
    linhas = RC.ler_lista_suja_texto(_texto_lista())
    assert len(linhas) == 3
    assert linhas[0]["cod_ibge"] == COD and linhas[0]["rural"] and linhas[0]["trabalhadores"] == 12
    assert linhas[1]["cod_ibge"] == 5103304 and linhas[1]["rural"]  # Comodoro (MT), endereço "CIDADE-UF"
    assert linhas[2]["cod_ibge"] is None and not linhas[2]["rural"]  # residência: sem município, trabalho doméstico
    assert linhas[0]["chave"] == "F" + CPF_LISTADO.replace(".", "").replace("-", "")
    assert linhas[1]["chave"].startswith("J") and len(linhas[1]["chave"]) == 9  # raiz do CNPJ pega as filiais
    m = RC.lista_suja_por_municipio(linhas)
    assert list(m.columns) == ["cod_ibge", "uf", "empregadores", "rurais", "trabalhadores", "inclusao_mais_recente"]
    assert set(m.cod_ibge) == {COD, 5103304}
    assert "FULANO" not in m.to_csv() and CPF_LISTADO not in m.to_csv()


def _csv_autos():
    cab = ("SEQ_AUTO_INFRACAO;DES_STATUS_FORMULARIO;SIT_CANCELADO;DAT_HORA_AUTO_INFRACAO;TIPO_INFRACAO;"
           "GRAVIDADE_INFRACAO;COD_MUNICIPIO;UF;NOME_INFRATOR;CPF_CNPJ_INFRATOR;NUM_LONGITUDE_AUTO;NUM_LATITUDE_AUTO;"
           "WKT_GE_AREA_AUTUADA")  # fmt: skip
    linhas = [
        f"1;Lavrado;N;2024-05-02 10:00:00;Flora;Média;{COD};PA;FULANO;{CPF_LISTADO};-51.95;-6.55;",
        f"2;Lavrado;N;2023-01-02 10:00:00;Flora;Baixa;{COD};PA;CICLANO;{CPF_OUTRO};-51.85;-6.55;",
        f"3;Cancelado;S;2024-01-02 10:00:00;Flora;Baixa;{COD};PA;CICLANO;{CPF_OUTRO};-51.85;-6.55;",
        f"4;Lavrado;N;2005-01-02 10:00:00;Flora;Baixa;{COD};PA;CICLANO;{CPF_OUTRO};-51.85;-6.55;",
        f"5;Lavrado;N;2022-01-02 10:00:00;Fauna;Baixa;{COD};PA;EMPRESA;{CNPJ_LISTADO[:-7]}9999-00;0;0;"
        "POLYGON ((-51.79 -6.59, -51.71 -6.59, -51.71 -6.51, -51.79 -6.51, -51.79 -6.59))",
    ]
    return "\n".join([cab, *linhas]) + "\n"


def test_autos_do_ibama_sem_cancelados_sem_dado_pessoal_e_com_vinculo_da_lista(tmp_path):
    chaves = {x["chave"] for x in RC.ler_lista_suja_texto(_texto_lista())}
    a = RC.ler_autos_csv(io.BytesIO(_csv_autos().encode()), chaves)
    assert list(a.auto_id) == ["1", "2", "5"]  # cancelado e anterior a 2008 saem
    assert list(a.lista_suja) == [True, False, True]  # o 5 é filial do CNPJ listado (mesma raiz)
    assert list(a.geometria_tipo) == ["ponto", "ponto", "area"]
    assert list(a.columns) == RC.COLUNAS_AUTOS
    f = tmp_path / "autos.parquet"
    a.to_parquet(f)
    bruto = f.read_bytes()
    for proibido in (CPF_LISTADO, CPF_OUTRO, "FULANO", "CICLANO", "123456789"):
        assert proibido.encode() not in bruto
    f.rename(tmp_path / "restricoes_ibama_autos.parquet")
    assert RC.conferir_sem_documento(tmp_path) == []
    (tmp_path / "restricoes_vazado.csv").write_text(f"x\n{CPF_OUTRO}\n")
    assert len(RC.conferir_sem_documento(tmp_path)) == 1
    # o zip anual do SIFISC: só os anos desde 2008 são lidos
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("auto_infracao_ano_2024.csv", _csv_autos())
        zf.writestr("auto_infracao_ano_2001.csv", _csv_autos())
    assert len(RC.ler_autos_zip(z.getvalue(), chaves)) == 3


def test_sigmine_sai_sem_o_titular():
    g = gpd.GeoDataFrame(
        {
            "PROCESSO": ["850.001/2010"],
            "NUMERO": [850001],
            "ANO": [2010],
            "AREA_HA": [12.5],
            "ID": ["x"],
            "FASE": ["Concessão de lavra"],
            "ULT_EVENTO": ["evento"],
            "NOME": ["MINERADORA FULANO"],
            "SUBS": ["OURO"],
            "USO": ["Industrial"],
            "UF": ["PA"],
        },  # fmt: skip
        geometry=[box(X0, Y0, X0 + 0.01, Y0 + 0.01)],
        crs=4674,
    )
    s = RC.normalizar_sigmine(g)
    assert list(s.columns) == RC.COLUNAS_SIGMINE
    assert s.fase.iloc[0] == "CONCESSÃO DE LAVRA"
    assert "MINERADORA FULANO" not in s.drop(columns="geometry").to_csv()


# --- status por imóvel -------------------------------------------------------------------------------------------

# imóveis de 0,08 x 0,08 grau (~7.900 ha), lado a lado; P é pequeno (~2 ha)
IMOVEIS = {
    "PA-1507300-A": box(-52.00, -6.60, -51.92, -6.52),  # Lista Suja (auto do infrator listado)
    "PA-1507300-B": box(-51.90, -6.60, -51.82, -6.52),  # auto de Flora recente (não listado)
    "PA-1507300-C": box(-51.80, -6.60, -51.72, -6.52),  # embargo/auto de área do CNPJ listado (polígono)
    "PA-1507300-D": box(-52.00, -6.50, -51.92, -6.42),  # mina em lavra
    "PA-1507300-E": box(-51.90, -6.50, -51.82, -6.42),  # território tradicional (CAR PCT)
    "PA-1507300-F": box(-51.80, -6.50, -51.72, -6.42),  # assentamento + outro CAR + pesquisa mineral
    "PA-1507300-G": box(-52.00, -6.40, -51.92, -6.32),  # limpo
    "PA-1507300-P": box(-51.90, -6.40, -51.8987, -6.3987),  # pequeno: ~2 ha
}


def _motor(tmp_path):
    pasta = tmp_path / "saida" / "PA"
    pasta.mkdir(parents=True)
    g = gpd.GeoDataFrame({"cod_imovel": list(IMOVEIS)}, geometry=list(IMOVEIS.values()), crs=4674)
    g.to_parquet(pasta / f"geo_{COD}.parquet")
    ha = g.to_crs(5880).area / 1e4
    pd.DataFrame({"cod_imovel": g.cod_imovel, "ha": ha}).to_csv(pasta / f"imoveis_{COD}.csv", index=False)
    return pasta


def _car_completo():
    linhas = [(c, "IRU", "SU" if c.endswith("-B") else "AT", geom) for c, geom in IMOVEIS.items()]
    linhas += [
        ("PA-1507300-PCT", "PCT", "AT", box(-51.88, -6.48, -51.84, -6.44)),
        ("PA-1507300-AST", "AST", "AT", box(-51.80, -6.50, -51.76, -6.46)),
        ("PA-1507300-VIZ", "IRU", "AT", box(-51.76, -6.46, -51.70, -6.40)),
        ("PA-1507300-CAN", "PCT", "CA", IMOVEIS["PA-1507300-G"]),  # cancelado não conta
    ]
    return gpd.GeoDataFrame(
        {
            "cod_imovel": [x[0] for x in linhas],
            "tipo_imovel": [x[1] for x in linhas],
            "status_imovel": [x[2] for x in linhas],
        },  # fmt: skip
        geometry=[x[3] for x in linhas],
        crs=4674,
    )


def _camadas(tmp_path, cobertura=True):
    pasta = tmp_path / "restricoes"
    pasta.mkdir()
    chaves = {x["chave"] for x in RC.ler_lista_suja_texto(_texto_lista())}
    autos = RC.ler_autos_csv(io.BytesIO(_csv_autos().encode()), chaves)
    autos.loc[autos.auto_id == "2", "geometry"] = Point(-51.86, -6.56)  # dentro de B
    autos.to_parquet(pasta / RC.NOMES["ibama_autos"])
    RC.vinculos_lista_suja(autos, None).to_parquet(pasta / RC.NOMES["lista_suja_vinculos"])
    RC.lista_suja_por_municipio(RC.ler_lista_suja_texto(_texto_lista())).to_csv(
        pasta / RC.NOMES["lista_suja_municipios"], index=False
    )
    sg = gpd.GeoDataFrame(
        {
            "processo": ["850.001/2010", "850.002/2020", "850.003/2021"],
            "fase": ["CONCESSÃO DE LAVRA", "AUTORIZAÇÃO DE PESQUISA", "CONCESSÃO DE LAVRA"],
            "substancia": ["OURO"] * 3,
            "uso": ["Industrial"] * 3,
            "uf": ["PA"] * 3,
            "area_ha": [1.0] * 3,
            "ultimo_evento": [None] * 3,
        },  # fmt: skip
        geometry=[
            box(-52.0, -6.50, -51.96, -6.46),
            box(-51.75, -6.45, -51.72, -6.42),
            box(-51.8995, -6.3995, -51.8987, -6.3987),
        ],  # fmt: skip
        crs=4674,
    )
    sg.to_parquet(pasta / RC.NOMES["sigmine"])
    fontes = {"sigmine": {"estado": "consultado", "ufs": ["PA"]}, "ibama_autos": {"estado": "consultado"},
              "lista_suja": {"estado": "consultado"}, "car_temas": {"estado": "indisponivel"}}  # fmt: skip
    if cobertura:
        (pasta / RC.NOMES["cobertura"]).write_text(json.dumps({"versao": RC.VERSAO, "fontes": fontes}))
    return pasta


def test_exclusao_ressalva_e_livre_por_imovel(tmp_path):
    pasta = _motor(tmp_path)
    cam = RS.Camadas(_camadas(tmp_path))
    df = RS.calcular_municipio(pasta, COD, camadas=cam, car=_car_completo(), hoje=HOJE).set_index("cod_imovel")
    st, mot = df.restricao_nacional, df.restricao_motivos.fillna("")
    assert st["PA-1507300-A"] == "exclusao" and "lista_suja" in mot["PA-1507300-A"]
    assert st["PA-1507300-C"] == "exclusao" and "lista_suja" in mot["PA-1507300-C"]  # polígono do CNPJ listado
    assert st["PA-1507300-B"] == "ressalva" and mot["PA-1507300-B"] == "car_suspenso|ibama_auto_flora_recente"
    assert df.loc["PA-1507300-B", "car_status"] == "SU"
    assert df.loc["PA-1507300-B", "ibama_autos_ids"] == "2"
    assert st["PA-1507300-D"] == "exclusao" and mot["PA-1507300-D"] == "mineracao_lavra"
    assert df.loc["PA-1507300-D", "mineracao_processos"] == "850.001/2010"
    assert st["PA-1507300-E"] == "exclusao" and mot["PA-1507300-E"] == "territorio_tradicional"
    assert st["PA-1507300-F"] == "ressalva"
    assert set(mot["PA-1507300-F"].split("|")) == {"mineracao_pesquisa", "assentamento_sobreposto", "car_sobreposto"}
    assert df.loc["PA-1507300-F", "car_sobreposto_n"] == 1
    # sem RL/APP da base do SICAR o imóvel limpo ainda é livre (complemento), mas a lacuna fica escrita
    assert st["PA-1507300-G"] == "livre" and df.loc["PA-1507300-G", "restricoes_nao_verificadas"] == "car_temas"
    assert df.loc["PA-1507300-G", "car_pct_ha"] == 0  # o PCT cancelado não conta
    assert df.loc["PA-1507300-A", "lista_suja_municipio_rurais"] == 1
    # imóvel pequeno conta pela fração: 0,6 ha de lavra em ~2 ha passa de 5% e exclui (nunca sai por tamanho)
    assert st["PA-1507300-P"] == "exclusao" and mot["PA-1507300-P"] == "mineracao_lavra"
    assert df.restricoes_versao.str.startswith("restricoes-2026a+").all()
    assert set(df.columns) | {"cod_imovel"} == set(RS.COLUNAS)


def test_sem_coleta_nem_car_completo_nunca_vira_livre(tmp_path, monkeypatch):
    pasta = _motor(tmp_path)
    monkeypatch.setattr(RS, "car_completo", lambda uf, cod: None)
    vazio = tmp_path / "nada"
    vazio.mkdir()
    df = RS.calcular_municipio(pasta, COD, camadas=RS.Camadas(vazio), hoje=HOJE)
    assert set(df.restricao_nacional) == {"nao_verificado"}
    assert set(df.restricoes_nao_verificadas) == {"sicar_car|car_temas|sigmine|ibama_autos|lista_suja"}
    assert df.restricoes_versao.str.endswith("+sem_coleta").all()


def test_fonte_parcial_marca_o_que_cruzou_mas_nao_libera(tmp_path, monkeypatch):
    pasta = _motor(tmp_path)
    cam = RS.Camadas(_camadas(tmp_path))
    cam.cobertura["sigmine"]["ufs"] = ["MT"]  # SIGMINE do Pará não veio
    df = RS.calcular_municipio(pasta, COD, camadas=cam, car=_car_completo(), hoje=HOJE).set_index("cod_imovel")
    assert df.loc["PA-1507300-G", "restricao_nacional"] == "nao_verificado"
    assert "sigmine" in df.loc["PA-1507300-G", "restricoes_nao_verificadas"]
    assert df.loc["PA-1507300-A", "restricao_nacional"] == "exclusao"  # o que cruzou continua valendo
    assert pd.isna(df.loc["PA-1507300-D", "mineracao_lavra_ha"])


def test_rl_app_declarada_por_outro_car_vira_ressalva(tmp_path):
    pasta = _motor(tmp_path)
    cam_pasta = _camadas(tmp_path)
    gpd.GeoDataFrame(
        {"cod_imovel": ["PA-1507300-VIZ", "PA-1507300-G"], "tema": ["reserva_legal", "reserva_legal"]},
        geometry=[box(-52.0, -6.40, -51.96, -6.36), box(-51.96, -6.36, -51.92, -6.32)],
        crs=4674,
    ).to_parquet(cam_pasta / "restricoes_car_temas_PA.parquet")
    df = RS.calcular_municipio(pasta, COD, camadas=RS.Camadas(cam_pasta), car=_car_completo(), hoje=HOJE)
    g = df.set_index("cod_imovel").loc["PA-1507300-G"]
    assert g.restricao_nacional == "ressalva" and g.restricao_motivos == "rl_app_alheia"
    assert g.rl_declarada_ha > 1000 and g.rl_app_alheia_ha > 1000
    assert pd.isna(g.restricoes_nao_verificadas)


def test_classificar_tolerancia_de_contorno_e_limiar():
    r = RS.regra()
    tudo = set(r["fontes_essenciais"])
    assert RS.classificar({"car_pct_ha": 0.05}, 500, tudo)[0] == "livre"  # toque de contorno
    assert RS.classificar({"car_pct_ha": 0.5}, 500, tudo) == ("ressalva", ["territorio_tradicional_borda"])
    assert RS.classificar({"car_pct_ha": 1.5}, 500, tudo) == ("exclusao", ["territorio_tradicional"])
    assert RS.classificar({"car_sobreposto_ha": 0.5}, 5, tudo) == ("ressalva", ["car_sobreposto"])  # 10% de 5 ha


# --- executor, carga e lote --------------------------------------------------------------------------------------


def test_tarefa_propria_folha_que_so_depende_do_funil(tmp_path, monkeypatch):
    from raiz.contrato import COMPLEMENTOS
    from raiz.executor import tarefas as T

    t = next(x for x in T.tarefas_producao() if x.nome == "restricoes")
    assert t.depende == ("funil",) and t.saidas == ("restricoes_{cod}.csv",)
    assert all("restricoes" not in x.depende for x in T.tarefas_producao())
    assert "restricoes" in COMPLEMENTOS
    monkeypatch.setenv("RAIZ_RESTRICOES_DIR", str(_camadas(tmp_path)))
    antes = T.externas("restricoes")("PA", COD, {})
    (tmp_path / "restricoes" / RC.NOMES["cobertura"]).write_text("{}")
    assert T.externas("restricoes")("PA", COD, {}) != antes


def test_tarefa_roda_e_grava_o_csv(tmp_path, monkeypatch):
    from raiz.executor import tarefas as T

    pasta = _motor(tmp_path)
    monkeypatch.setenv("RAIZ_RESTRICOES_DIR", str(_camadas(tmp_path)))
    monkeypatch.setattr(RS, "car_completo", lambda uf, cod: _car_completo())
    T.rodar_restricoes("PA", COD, pasta)
    df = pd.read_csv(pasta / f"restricoes_{COD}.csv")
    assert len(df) == len(IMOVEIS) and set(df.restricao_nacional) <= set(RS.STATUS)
    assert RS.resumo(df)["exclusao"] == 5


@pytest.mark.parametrize(
    ("restricao", "bloqueia"), [("exclusao", True), ("ressalva", False), ("livre", False), (None, False)]
)
def test_oferta_exclusao_bloqueia_e_ressalva_fica_marcada(restricao, bloqueia, monkeypatch):
    from raiz import salvaguardas
    from raiz.pedidos import oferta as O

    monkeypatch.setattr(salvaguardas, "avaliar", lambda li, v=None: {"pode_originar": True})
    linha = {"cod_imovel": "PA-1507300-A", "cod_municipio_ibge": COD, "modo_restauracao": "regeneracao_assistida",
             "restauracao_area_ha": 100.0, "caminho_terra": "privada_matricula", "ha": 500.0,
             "restricao_nacional": restricao, "restricao_motivos": "ibama_auto" if restricao else None}  # fmt: skip
    o = O.de_linha(linha, -52.0, -6.5)
    assert o["bloqueio"] is bloqueia and o["elegivel"] is (not bloqueia)
    assert o["restricao_ressalva"] == ((restricao == "ressalva") if restricao else None)
    assert o["restricao_nacional"] == restricao


def test_checagem_do_lote_lista_ressalvas_e_lacunas():
    from raiz.lote import restricoes_do_lote

    assert restricoes_do_lote(pd.DataFrame({"x": [1]}))["situacao"] == "pendente"
    lote = pd.DataFrame({"restricao_nacional": ["livre", "ressalva", "ressalva", None],
                         "restricao_motivos": [None, "ibama_auto", "ibama_auto|car_sobreposto", None]})  # fmt: skip
    r = restricoes_do_lote(lote)
    assert r["situacao"] == "pendente"
    assert "2 fazendas com ressalva" in r["detalhe"] and "ibama_auto: 2" in r["detalhe"]
    assert "1 sem verificação completa" in r["detalhe"]
    assert (
        restricoes_do_lote(pd.DataFrame({"restricao_nacional": ["livre"], "restricao_motivos": [None]}))["situacao"]
        == "ok"
    )


def test_sigmine_desiste_cedo_do_servidor_fora_e_completa_a_cadeia(monkeypatch, tmp_path):
    import requests

    chamadas = {"portal": 0, "arcgis": 0}

    class Sessao:
        def get(self, url, **kw):
            if "dadosabertos" in url:
                chamadas["portal"] += 1
                raise requests.exceptions.ConnectionError("Connection reset by peer")
            chamadas["arcgis"] += 1
            if not kw.get("verify"):
                raise requests.exceptions.SSLError("CERTIFICATE_VERIFY_FAILED unable to get local issuer certificate")
            raise requests.exceptions.ConnectionError("fora")

    pacotes = []
    monkeypatch.setattr(RC, "cadeia_com_intermediario", lambda url, pasta: pacotes.append(url) or "ca.pem")
    g, cob = RC.baixar_sigmine(Sessao(), ufs=["AC", "PA", "MT", "SP"], pasta_tmp=tmp_path)
    assert cob["estado"] == "indisponivel" and cob["ufs_falharam"] == ["AC", "PA", "MT", "SP"]
    assert chamadas["portal"] == 2  # depois de 2 quedas seguidas, o portal sai das próximas UFs
    assert len(pacotes) == 1  # a cadeia do ArcGIS é completada uma vez, com verificação ligada
    assert chamadas["arcgis"] == 3  # AC sem e com o pacote, PA com o pacote; MT e SP pulam
