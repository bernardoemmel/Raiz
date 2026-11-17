"""Fontes complementares na triagem: SICOR, localidades quilombolas (IBGE/Palmares), MPF, Observatório e Restor; e
CNIB/SAEC no fluxo de certidões. Nenhum teste vai à rede.

As linhas do SICOR, do IBGE e da Fundação Palmares copiam o formato real dos arquivos baixados em 17/11/2026 (mesmo
cabeçalho, separador, datas e WKT com coordenada Z). O documento do tomador do SICOR é gerado na hora e o teste
confere que ele não chega à camada.
"""

import datetime as dt
import gzip
import io
import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from raiz.complementares import coleta as CC
from raiz.complementares import status as CS
from raiz.documentos.certidao import onr

COD = 1507300  # São Félix do Xingu (PA)
X0, Y0 = -52.0, -6.6
HOJE = "2026-11-17"
H = "0123456789ABCDEF0123456789ABCDEF"


def _car(i: int) -> str:
    return f"PA-{COD}-{H[:-2]}{i:02d}"


def _dv(nums, pesos):
    r = sum(n * p for n, p in zip(nums, pesos, strict=False)) % 11
    return 0 if r < 2 else 11 - r


def _cpf(base: str) -> str:
    d = [int(c) for c in base]
    d.append(_dv(d, range(10, 1, -1)))
    d.append(_dv(d, range(11, 1, -1)))
    return "".join(map(str, d))


def _gz(texto: str) -> io.BytesIO:
    return io.BytesIO(gzip.compress(texto.encode("latin1")))


# --- SICOR -------------------------------------------------------------------------------------------------------

OPERACOES = (
    "#REF_BACEN;NU_ORDEM;CNPJ_IF;DT_EMISSAO;DT_VENCIMENTO;CD_INST_CREDITO;CD_CATEG_EMITENTE;CD_FONTE_RECURSO;"
    "CNPJ_AGENTE_INVEST;CD_ESTADO;CD_REF_BACEN_INVESTIMENTO;CD_TIPO_SEGURO;CD_EMPREENDIMENTO;CD_PROGRAMA;"
    "CD_TIPO_ENCARG_FINANC;CD_TIPO_IRRIGACAO;CD_TIPO_AGRICULTURA;CD_FASE_CICLO_PRODUCAO;CD_TIPO_CULTIVO;"
    "CD_TIPO_INTGR_CONSOR;CD_TIPO_GRAO_SEMENTE;VL_ALIQ_PROAGRO;VL_JUROS;VL_PRESTACAO_INVESTIMENTO;VL_PREV_PROD;"
    "VL_QUANTIDADE;VL_RECEITA_BRUTA_ESPERADA;VL_PARC_CREDITO;VL_REC_PROPRIO;VL_PERC_RISCO_STN;"
    "VL_PERC_RISCO_FUNDO_CONST;VL_REC_PROPRIO_SRV;VL_AREA_FINANC;CD_SUBPROGRAMA\n"
    # investimento ativo (vence em 2033) ligado ao CAR 1
    "519338131;1;78483310;02/01/2025;17/01/2033;5;2222;0403;;PA;;9;23271300193002;0001;9;00;0;00;00;0;0;;6.00;;;"
    "1.00;;105000.00;0.00;;;;30.00;0002\n"
    # custeio de 2025 já vencido, com gleba, sem CAR (imóvel 2 por sobreposição)
    "519338132;1;78483310;02/01/2025;17/01/2026;5;2222;0403;;PA;;9;12018888000002;0001;9;00;0;00;00;0;0;;6.00;;;"
    "1.00;;25120.00;0.00;;;;80.00;0002\n"
    # florestamento (recuperação ambiental) ligado ao CAR 4
    "519338133;1;78483310;10/03/2024;10/03/2031;5;2222;0403;;PA;;9;99000000000001;0001;9;00;0;00;00;0;0;;6.00;;;"
    "1.00;;5000.00;0.00;;;;12.00;0002\n"
)
EMPREENDIMENTOS = (
    "#CODIGO;DATA_INICIO;DATA_FIM;FINALIDADE;ATIVIDADE;MODALIDADE;PRODUTO;VARIEDADE;CESTA;ZONEAMENTO;"
    "UNIDADE_MEDIDA;UNIDADE_MEDIDA_PREVISAO;CONSORCIO;CEDULA_MAE;CD_TIPO_CULTURA\n"
    '"23271300193002";"01/01/2020";;"Investimento";"Pecuário(a)";"PASTAGEM";"FORMAÇÃO";"";"";"";"Hectare";"";"";0;2\n'
    '"12018888000002";"07/01/2020";;"Custeio";"Agrícola";"LAVOURA";"SOJA";"";"";"";"Hectare";"";"";0;2\n'
    '"99000000000001";"01/01/2020";;"Investimento";"Agrícola";"IMPLANTAÇÃO E MELHORAMENTO";'
    '"RECUPERAÇÃO AMBIENTAL";"";"";"";"Hectare";"";"";0;2\n'
)


def _propriedades(doc: str) -> str:
    sem = lambda c: c.replace("-", "")  # noqa: E731 - o SICOR grava o CAR sem hífens
    return (
        "#REF_BACEN;NU_ORDEM;CD_CNPJ_CPF;CD_SNCR;CD_CIB;CD_CAR\n"
        f"519338131;1;{doc};-1;-1;{sem(_car(1))}\n"
        f"519338132;1;{doc};-1;-1;-1\n"
        f"519338133;1;{doc};-1;-1;{sem(_car(4))}\n"
        f"1102;1;{doc};-1;-1;{sem(_car(9))}\n"  # operação fora dos anos lidos: não entra
    )


def _gleba_wkt(x, y, d=0.01) -> str:
    return f"POLYGON (({x} {y} 0,{x + d} {y} 0,{x + d} {y + d} 0,{x} {y + d} 0,{x} {y} 0))"


def test_normalizar_car_do_sicor():
    assert CC.normalizar_car(_car(1).replace("-", "")) == _car(1)
    assert CC.normalizar_car(_car(1).lower()) == _car(1)
    assert CC.normalizar_car("-1") is None and CC.normalizar_car(None) is None


def test_sicor_le_car_sem_documento_e_agrega_por_imovel():
    doc = _cpf("123456789")
    emp = CC.ler_empreendimentos(io.BytesIO(EMPREENDIMENTOS.encode("latin1")))
    assert emp.set_index("cd_empreendimento").floresta.to_dict() == {
        "23271300193002": False,
        "12018888000002": False,
        "99000000000001": True,
    }
    op = CC.ler_operacoes(_gz(OPERACOES), emp)
    assert len(op) == 3 and set(op.uf) == {"PA"}
    prop = CC.ler_propriedades(_gz(_propriedades(doc)), CC.chave(op.ref, op.ordem))
    assert list(prop.columns) == ["ref", "ordem", "cod_imovel"]
    assert doc not in prop.to_csv()
    t = CC.sicor_por_car(op, prop, HOJE).set_index("cod_imovel")
    assert set(t.index) == {_car(1), _car(4)}
    assert t.loc[_car(1)].vencimento_max == "2033-01-17" and t.loc[_car(1)].area_financiada_ativa_ha == 30.0
    assert bool(t.loc[_car(4)].floresta) and t.loc[_car(4)].floresta_vencimento_max == "2031-03-10"


def test_sicor_glebas_por_uf_sem_chave_da_operacao():
    op = CC.ler_operacoes(_gz(OPERACOES), CC.ler_empreendimentos(io.BytesIO(EMPREENDIMENTOS.encode("latin1"))))
    glebas = (
        "#REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n"
        f"519338132;1;0;{_gleba_wkt(X0 + 0.02, Y0)}\n"
        f"519338132;1;1;{_gleba_wkt(X0 + 0.025, Y0)}\n"  # duas partes da mesma gleba viram uma linha
        f"777;1;0;{_gleba_wkt(X0, Y0)}\n"  # operação que não está nos anos lidos
        "519338131;1;0;POLYGON ((texto quebrado\n"
    )
    g = CC.ler_glebas(_gz(glebas), op, HOJE)
    assert set(g) == {"PA"} and len(g["PA"]) == 1
    assert list(g["PA"].columns) == CC.COLUNAS_GLEBAS
    assert g["PA"].iloc[0].emissao == "2025-01-02" and g["PA"].iloc[0].finalidade == "Custeio"


def test_baixar_recusa_pagina_de_erro_do_bcb(tmp_path):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield b'<?xml version="1.0"?><title>Requisi\xc3\xa7\xc3\xa3o inv\xc3\xa1lida!</title>'

    class S:
        def get(self, *a, **k):
            return R()

    with pytest.raises(OSError):
        CC._baixar(S(), "https://www.bcb.gov.br/x/SICOR_GLEBAS_WKT_2026.gz", tmp_path / "a.gz")


# --- quilombos ---------------------------------------------------------------------------------------------------

IBGE = (
    "﻿CD_UF;NM_UF;SG_UF;CD_MUNIC;NM_MUNIC;IDCQ0001;OCORRENCIA;CD_LQ;PREFIXO;NM_CQ;CD_AGLOM;NM_AGLOM;CD_TQ;NM_TQ;"
    "P_FCP;Lat_d;Long_d\r\n"
    "28;SERGIPE;SE;2803500;Lagarto;00001;1;2803500000011;COMUNIDADE QUILOMBOLA;22 DE NOVEMBRO;;;;;;"
    "-10.9412705554;-37.7860389957\r\n"
    "23;CEARÁ;CE;2304236;Croatá;00002;1;2304236000021;COMUNIDADE QUILOMBOLA;3 IRMÃOS;00007;COMUNIDADE QUILOMBOLA 3 "
    "IRMÃOS;219;TRÊS IRMÃOS;;-4.43469207968259;-41.0817837249122\r\n"
    f"15;PARÁ;PA;{COD};São Félix do Xingu;00003;1;{COD}000011;COMUNIDADE QUILOMBOLA;TESTE;;;;;01420.000001/2020-01;"
    f"{Y0 + 0.005};{X0 + 0.205}\r\n"
)
PALMARES = (
    "REGIÃO, UF,MUNICÍPIO,CÓDIGO DO IBGE,COMUNIDADE,Nº PROCESSO NA FCP,DATA DA ABERTURA,Nº DO LIVRO DE REGISTRO,"
    "Nº DO REGISTRO,Nº DA FOLHA,Nº DA PORTARIA,DATA DA PORTARIA NO DOU,RETIFICAÇÃO NO DOU,Nº PROCESSO INCRA,"
    'ETAPA DO PROCESSO DE TITULAÇÃO,Nº DE CRQ,Nº DE MORADORES,"POPULAÇÃO\nIBGE",ANO CERTIFICAÇÃO,PORTA DE ENTRADA,'
    "CONT\n"
    "SUL,RS,MAQUINÉ | OSÓRIO,4311775 | 4313508,MORRO ALTO,01420.000014/2003-04,09/01/2003,1,1,2,19/2004,04/06/2004, ,"
    "54220.001201/2004-09,RTID,1,456,,2004,,1\n"
    "SUL,RS,RESTINGA SECA,4315503,RINÇÃO DOS MATINIANOS,01420.000036/2003-66,09/01/2003,1,4,5,19/2004,04/06/2004, ,"
    "54220.000258/2005-63,TITULAÇÃO PARCIAL,1,55,,2004,,1\n"
    "NORTE,PA,OEIRAS DO PARÁ,1505106,X,01420.0/2005-01,01/01/2005,1,9,9,1/2006,01/01/2006, ,,Titulada pelo ITERPA,1,"
    ",,2006,,1\n"
)


def test_ibge_quilombolas_sem_nome_da_comunidade():
    g = CC.ler_ibge_quilombolas(io.BytesIO(IBGE.encode("utf-8")))
    assert list(g.columns) == CC.COLUNAS_IBGE and len(g) == 3
    assert "TESTE" not in g.drop(columns="geometry").to_csv() and "IRMÃOS" not in g.to_csv()
    assert g.set_index("cd_lq").territorio_oficial.to_dict()["2304236000021"]
    assert g.set_index("cd_lq").certificada_fcp.to_dict()[f"{COD}000011"]


def test_palmares_conta_por_municipio_sem_nomes_nem_processos():
    p = CC.ler_palmares(io.StringIO(PALMARES)).set_index("cod_ibge")
    assert set(p.index) == {4311775, 4313508, 4315503, 1505106}  # comunidade em dois municípios conta nos dois
    assert p.loc[4315503].certificadas_sem_titulo_n == 1  # titulação parcial ainda não é título
    assert p.loc[1505106].certificadas_sem_titulo_n == 0  # titulada pelo ITERPA
    texto = p.to_csv()
    assert "MORRO ALTO" not in texto and "01420" not in texto


# --- importação com autorização ----------------------------------------------------------------------------------


def _arquivo_importado(tmp_path):
    g = gpd.GeoDataFrame(
        {
            "ID": ["obs-1"],
            "Tipo": ["Regeneração natural"],
            "ano": ["2021"],
            "responsavel": ["Fulano de Tal"],
            "email": ["fulano@exemplo.org"],
        },
        geometry=[box(X0 + 0.04, Y0, X0 + 0.05, Y0 + 0.01)],
        crs=4674,
    )
    f = tmp_path / "recebido.geojson"
    g.to_file(f, driver="GeoJSON")
    return f


def test_importar_exige_autorizacao_e_so_copia_campos_tecnicos(tmp_path):
    f = _arquivo_importado(tmp_path)
    with pytest.raises(ValueError):
        CC.importar(f, "observatorio", tmp_path / "saida", autorizacao="")
    meta = CC.importar(
        f, "observatorio", tmp_path / "saida", "e-mail da Coalizão de 20/11/2026", "uso interno", hoje=HOJE
    )
    assert meta["n"] == 1 and meta["estado"] == "consultado"
    g = gpd.read_parquet(tmp_path / "saida" / CC.NOMES["observatorio"])
    assert list(g.columns) == CC.COLUNAS_IMPORTADAS
    assert g.iloc[0].objeto_id == "obs-1" and g.iloc[0].ano_inicio == 2021
    assert "Fulano" not in g.to_csv() and "@" not in g.to_csv()
    with pytest.raises(ValueError):
        CC.importar(f, "sicor", tmp_path / "saida", "qualquer autorização longa")


def test_guarda_de_privacidade_acha_documento(tmp_path):
    (tmp_path / "complementares_x.csv").write_text(f"a,b\n1,{_cpf('123456789')}\n")
    (tmp_path / "complementares_y.csv").write_text("a,b\n1,2\n")
    achados = CC.conferir_sem_documento(tmp_path)
    assert len(achados) == 1 and achados[0].arquivo == "complementares_x.csv"


# --- status por imóvel -------------------------------------------------------------------------------------------

#  1: crédito ativo pelo CAR                 2: gleba de custeio de 2025 por cima (uso recente)
#  3: nada                                   4: crédito de recuperação ambiental pelo CAR
#  5: projeto do Observatório por cima       6: localidade quilombola dentro
#  7: localidade quilombola a ~1,1 km
IMOVEIS = {i: box(X0 + 0.01 * (i - 1), Y0, X0 + 0.01 * i - 0.0005, Y0 + 0.01) for i in range(1, 8)}
IMOVEIS[6] = box(X0 + 0.2, Y0, X0 + 0.21, Y0 + 0.01)
IMOVEIS[7] = box(X0 + 0.08, Y0, X0 + 0.09, Y0 + 0.01)


def _motor(tmp_path):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    g = gpd.GeoDataFrame({"cod_imovel": [_car(i) for i in IMOVEIS]}, geometry=list(IMOVEIS.values()), crs=4674)
    g.to_parquet(pasta / f"geo_{COD}.parquet")
    pd.DataFrame({"cod_imovel": [_car(i) for i in IMOVEIS], "ha": [110.0] * len(IMOVEIS)}).to_csv(
        pasta / f"imoveis_{COD}.csv", index=False
    )
    return pasta


def _camadas(tmp_path, com_restauracao=True):
    pasta = tmp_path / "complementares"
    pasta.mkdir(exist_ok=True)
    emp = CC.ler_empreendimentos(io.BytesIO(EMPREENDIMENTOS.encode("latin1")))
    op = CC.ler_operacoes(_gz(OPERACOES), emp)
    prop = CC.ler_propriedades(_gz(_propriedades(_cpf("123456789"))))
    CC.sicor_por_car(op, prop, HOJE).to_parquet(pasta / CC.NOMES["sicor_car"], index=False)
    glebas = "#REF_BACEN;NU_ORDEM;NU_INDICE;GT_GEOMETRIA\n" + f"519338132;1;0;{_gleba_wkt(X0 + 0.0105, Y0, 0.009)}\n"
    CC.ler_glebas(_gz(glebas), op, HOJE)["PA"].to_parquet(pasta / CC.GLEBAS.format(uf="PA"))
    q = CC.ler_ibge_quilombolas(io.BytesIO(IBGE.encode("utf-8")))
    q = pd.concat(
        [
            q,
            gpd.GeoDataFrame(
                {
                    "cd_lq": ["x"],
                    "cod_ibge": [COD],
                    "uf": ["PA"],
                    "territorio_oficial": [False],
                    "certificada_fcp": [False],
                },
                geometry=[Point(X0 + 0.0905 + 0.01, Y0 + 0.005)],
                crs=4674,
            ),
        ],
        ignore_index=True,
    )
    gpd.GeoDataFrame(q, crs=4674).to_parquet(pasta / CC.NOMES["ibge_quilombolas"])
    CC.ler_palmares(io.StringIO(PALMARES)).to_csv(pasta / CC.NOMES["palmares"], index=False)
    if com_restauracao:
        CC.importar(_arquivo_importado(tmp_path), "observatorio", pasta, "e-mail da Coalizão de 20/11/2026", hoje=HOJE)
    fontes = {f: {"estado": "consultado"} for f in ("sicor", "ibge_quilombolas", "palmares")}
    (pasta / CC.NOMES["cobertura"]).write_text(json.dumps({"fontes": fontes}))
    return pasta


def test_status_por_imovel_com_casos_de_cada_fonte(tmp_path):
    pasta = _motor(tmp_path)
    df = CS.calcular_municipio(pasta, COD, camadas=CS.Camadas(_camadas(tmp_path)), hoje=HOJE).set_index("cod_imovel")
    assert list(df.reset_index().columns) == CS.COLUNAS
    st = df.complementar_status.to_dict()
    mot = df.complementar_motivos.fillna("").to_dict()
    assert st[_car(1)] == "ressalva" and mot[_car(1)] == "credito_rural_ativo"
    assert st[_car(2)] == "ressalva" and mot[_car(2)] == "uso_agricola_recente"
    assert st[_car(3)] == "livre"
    assert st[_car(4)] == "ressalva" and "credito_rural_floresta" in mot[_car(4)]
    assert st[_car(5)] == "ressalva" and mot[_car(5)] == "restauracao_existente"
    assert df.loc[_car(5)].restauracao_externa_ids == "obs-1"
    assert st[_car(6)] == "exclusao" and mot[_car(6)] == "localidade_quilombola_dentro"
    assert bool(df.loc[_car(6)].quilombola_certificada_fcp)
    assert st[_car(7)] == "ressalva" and mot[_car(7)] == "localidade_quilombola_proxima"
    assert 0.5 < df.loc[_car(7)].quilombola_localidade_km < 2
    # MPF e Restor não chegaram: aparecem como não verificadas, mas não impedem o "livre"
    assert set(df.loc[_car(3)].complementares_nao_verificadas.split("|")) == {"mpf_territorios", "restor"}
    assert df.palmares_certificadas_municipio.eq(0).all()  # SFX não tem comunidade certificada na planilha


def test_sem_coleta_nunca_vira_livre(tmp_path):
    pasta = _motor(tmp_path)
    df = CS.calcular_municipio(pasta, COD, camadas=CS.Camadas(tmp_path / "vazia"), hoje=HOJE)
    assert set(df.complementar_status) == {"nao_verificado"}


def test_importada_depois_da_coleta_entra_pelo_meta(tmp_path):
    camadas = _camadas(tmp_path, com_restauracao=False)
    CC.importar(_arquivo_importado(tmp_path), "restor", camadas, "permissão escrita da Restor de 25/11/2026", hoje=HOJE)
    df = CS.calcular_municipio(_motor(tmp_path), COD, camadas=CS.Camadas(camadas), hoje=HOJE).set_index("cod_imovel")
    assert df.loc[_car(5)].restauracao_externa_fontes == "restor"


def test_classificar_limiar_e_tolerancia():
    r = CS.regra()
    tudo = set(r["fontes_essenciais"])
    base = {"_hoje": HOJE, "sicor_operacoes_n": 0}
    assert CS.classificar({**base, "restauracao_externa_ha": 0.05}, 500, tudo)[0] == "livre"
    assert CS.classificar({**base, "restauracao_externa_ha": 0.5}, 500, tudo)[1] == ["restauracao_existente_borda"]
    assert CS.classificar({**base, "mpf_territorio_ha": 2.0}, 500, tudo)[1] == ["territorio_tradicional_mpf"]
    # crédito vencido ligado ao CAR não marca
    assert CS.classificar({**base, "sicor_operacoes_n": 2, "sicor_vencimento_max": "2025-01-01"}, 50, tudo)[0] == (
        "livre"
    )


# --- executor, oferta e lote -------------------------------------------------------------------------------------


def test_tarefa_propria_folha_que_so_depende_do_funil(tmp_path, monkeypatch):
    from raiz.contrato import COMPLEMENTOS
    from raiz.executor import tarefas as T

    t = next(x for x in T.tarefas_producao() if x.nome == "complementares")
    assert t.depende == ("funil",) and t.saidas == ("complementares_{cod}.csv",)
    assert all("complementares" not in x.depende for x in T.tarefas_producao())
    assert "complementares" in COMPLEMENTOS
    monkeypatch.setenv("RAIZ_COMPLEMENTARES_DIR", str(_camadas(tmp_path)))
    antes = T.externas("complementares")("PA", COD, {})
    (tmp_path / "complementares" / CC.NOMES["cobertura"]).write_text("{}")
    assert T.externas("complementares")("PA", COD, {}) != antes
    pasta = _motor(tmp_path)
    T.rodar_complementares("PA", COD, pasta)
    df = pd.read_csv(pasta / f"complementares_{COD}.csv")
    assert len(df) == len(IMOVEIS) and set(df.complementar_status) <= set(CS.STATUS)


@pytest.mark.parametrize(("status", "bloqueia"), [("exclusao", True), ("ressalva", False), (None, False)])
def test_oferta_exclusao_bloqueia(status, bloqueia, monkeypatch):
    from raiz import salvaguardas
    from raiz.pedidos import oferta as O

    monkeypatch.setattr(salvaguardas, "avaliar", lambda li, v=None: {"pode_originar": True})
    linha = {
        "cod_imovel": _car(1),
        "cod_municipio_ibge": COD,
        "modo_restauracao": "regeneracao_assistida",
        "restauracao_area_ha": 100.0,
        "caminho_terra": "privada_matricula",
        "ha": 500.0,
        "complementar_status": status,
        "complementar_motivos": "credito_rural_ativo" if status else None,
    }
    o = O.de_linha(linha, -52.0, -6.5)
    assert o["bloqueio"] is bloqueia and o["complementar_status"] == status


def test_checagens_do_lote():
    from raiz.lote import cnib_saec_do_lote, complementares_do_lote

    assert complementares_do_lote(pd.DataFrame({"x": [1]}))["situacao"] == "pendente"
    lote = pd.DataFrame(
        {
            "complementar_status": ["livre", "ressalva", None],
            "complementar_motivos": [None, "credito_rural_ativo|uso_agricola_recente", None],
        }
    )
    r = complementares_do_lote(lote)
    assert r["situacao"] == "pendente" and "credito_rural_ativo: 1" in r["detalhe"]
    assert cnib_saec_do_lote(pd.DataFrame({"x": [1]}))["situacao"] == "pendente"
    assert cnib_saec_do_lote(pd.DataFrame({"cnib_situacao": ["sem_ordem", "com_ordem"]}))["situacao"] == "falha"
    assert cnib_saec_do_lote(pd.DataFrame({"cnib_situacao": ["sem_ordem"]}))["situacao"] == "ok"


# --- CNIB e SAEC -------------------------------------------------------------------------------------------------

DIA = dt.date(2026, 11, 17)


def _aut(escopos=("cnib", "saec"), **kw):
    return onr.Autorizacao(_car(1), frozenset(escopos), DIA, "assinatura_eletronica", "a" * 64, **kw)


class _Convenio:
    automatico = True

    def __init__(self):
        self.recebidos = []

    def indisponibilidades(self, documento):
        self.recebidos.append(documento)
        return {"ordens_n": 1, "protocolo": "CNIB-2026-1"}

    def pedir_certidao(self, cns, matricula, tipo):
        return {"protocolo": "SAEC-2026-1"}


def test_cnib_sem_autorizacao_nao_consulta():
    t = _Convenio()
    r = onr.consultar_cnib(_car(1), _cpf("123456789"), None, t, DIA)
    assert r.situacao == "sem_autorizacao" and not t.recebidos
    r = onr.consultar_cnib(_car(1), _cpf("123456789"), _aut(("saec",)), t, DIA)
    assert r.situacao == "sem_autorizacao" and not t.recebidos
    r = onr.consultar_cnib(_car(2), _cpf("123456789"), _aut(), t, DIA)  # autorização é de outro imóvel
    assert r.situacao == "sem_autorizacao"
    vencida = DIA + dt.timedelta(days=onr.VALIDADE_DIAS + 1)
    assert onr.consultar_cnib(_car(1), _cpf("123456789"), _aut(), t, vencida).situacao == "sem_autorizacao"
    revogada = _aut(revogada_em=DIA)
    assert onr.consultar_cnib(_car(1), _cpf("123456789"), revogada, t, DIA).situacao == "sem_autorizacao"


def test_cnib_com_autorizacao_guarda_so_contagem_e_hash():
    t = _Convenio()
    doc = _cpf("123456789")
    r = onr.consultar_cnib(_car(1), doc, _aut(), t, DIA)
    assert r.situacao == "com_ordem" and r.ordens_n == 1 and len(r.protocolo_sha) == 16
    assert doc not in repr(r) and "CNIB-2026-1" not in repr(r)
    with pytest.raises(ValueError):
        onr.consultar_cnib(_car(1), "123", _aut(), t, DIA)
    # sem convênio: pendente, com a instrução do que fazer à mão
    r = onr.consultar_cnib(_car(1), doc, _aut(), None, DIA)
    assert r.situacao == "pendente" and "indisponibilidade.onr.org.br" in r.instrucao


def test_saec_pede_inteiro_teor_so_com_autorizacao_e_matricula():
    assert onr.pedir_inteiro_teor(_car(1), "067314", "1234", None, _Convenio(), DIA).situacao == "sem_autorizacao"
    assert onr.pedir_inteiro_teor(_car(1), None, "1234", _aut(), _Convenio(), DIA).situacao == "pendente"
    p = onr.pedir_inteiro_teor(_car(1), "067314", "1234", _aut(), _Convenio(), DIA)
    assert p.situacao == "pedido" and p.pedido_em == "2026-11-17"
    manual = onr.pedir_inteiro_teor(_car(1), "067314", "1234", _aut(), None, DIA)
    assert manual.situacao == "pendente" and "registradores.onr.org.br" in manual.instrucao
    itens = {
        i["item"]: i["situacao"]
        for i in onr.itens_checklist(onr.consultar_cnib(_car(1), _cpf("123456789"), _aut(), _Convenio(), DIA), p)
    }
    assert itens == {"cnib": "falha", "certidao_inteiro_teor": "pendente"}


def test_autorizacao_valida_campos():
    with pytest.raises(ValueError):
        onr.Autorizacao(_car(1), frozenset({"cpf_livre"}), DIA, "assinatura_eletronica", "a" * 64)
    with pytest.raises(ValueError):
        onr.Autorizacao(_car(1), frozenset({"cnib"}), DIA, "telefonema", "a" * 64)
    with pytest.raises(ValueError):
        onr.Autorizacao(_car(1), frozenset({"cnib"}), DIA, "aceite_whatsapp", "curto")
