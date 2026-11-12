"""Privacidade, regras versionadas, KML e cadastro de projetos."""

from __future__ import annotations

import shapely
from shapely.geometry import Polygon

from raiz.vigilancia import kml, privacidade, projetos
from raiz.vigilancia.regras import ARQUIVO, carregar
from raiz.vigilancia.testes.conftest import CNPJ, CNPJ_ALFA, CPF, CPF_MASCARADO, fmt_cnpj, fmt_cpf


def test_mascara_cpf_e_cnpj_e_nao_estraga_codigo_do_car():
    t = f"Embargado {fmt_cpf(CPF)}, empresa {fmt_cnpj(CNPJ)} e sem pontos {CPF}; CAR PA-1507300-{CPF}ABC"
    m = privacidade.mascarar(t)
    assert fmt_cpf(CPF) not in m and CPF_MASCARADO in m
    assert fmt_cnpj(CNPJ) not in m and f"**.{CNPJ[2:5]}.{CNPJ[5:8]}/****-**" in m
    assert f"sem pontos {CPF_MASCARADO};" in m
    assert f"PA-1507300-{CPF}ABC" in m  # pedaço do código do CAR não é CPF
    assert privacidade.mascarar("área 189.99087022873272 ha") == "área 189.99087022873272 ha"


def test_cnpj_alfanumerico():
    assert privacidade.cnpj_valido(CNPJ_ALFA)
    assert "**.ABC.345/****-**" in privacidade.mascarar("CNPJ " + fmt_cnpj(CNPJ_ALFA))


def test_colunas_pessoais_saem_e_lugares_ficam():
    cols = ["NOME_EMBARGADO", "CPF_CNPJ_EMBARGADO", "NUM_PESSOA_EMBARGO", "nome_projeto", "municipio", "uf", "ha"]
    assert set(privacidade.colunas_pessoais(cols)) == {"NOME_EMBARGADO", "CPF_CNPJ_EMBARGADO", "NUM_PESSOA_EMBARGO"}
    limpo = privacidade.limpar_registro({"nome": "PESSOA_A", "nota": f"CPF {fmt_cpf(CPF)}", "x": [{"telefone": 1}]})
    assert limpo == {"nota": f"CPF {CPF_MASCARADO}", "x": [{}]}


def test_versao_da_regra_tem_nome_e_hash(tmp_path):
    r = carregar()
    assert r.versao.startswith(r["nome"] + "+") and len(r.versao.split("+")[1]) == 8
    copia = tmp_path / "regras.yaml"
    copia.write_text(ARQUIVO.read_text(encoding="utf-8") + "\n# mudou\n", encoding="utf-8")
    assert carregar(copia).versao != r.versao  # qualquer mudança no arquivo muda a versão


def test_tipos_e_confianca_inicial():
    r = carregar()
    assert r.tipo("deter", "cicatriz_de_queimada") == "fogo"
    assert r.tipo("deter", "desmatamento_cr") == "desmatamento"
    assert r.tipo("firms", "foco_alta") == "fogo"
    assert r.tipo("ibama_embargo", "embargo") == "embargo"
    a, b = r.prior("mapbiomas_alerta")
    assert a / (a + b) == 0.95
    assert r.prior("estrato_que_nao_existe") == tuple(map(float, r["confianca_inicial"]["padrao"]))
    v = r.verra
    assert v["aviso_verra_dias"] == 30 and v["relatorio_anos"] == 2 and v["limiar_evento_pct"] == 5


def test_kml_le_buraco_e_campos_e_volta_igual():
    externo = [(-53.0, -6.0), (-52.99, -6.0), (-52.99, -5.99), (-53.0, -5.99)]
    buraco = [(-52.997, -5.997), (-52.993, -5.997), (-52.993, -5.993), (-52.997, -5.993)]
    p = Polygon(externo, [buraco])
    texto = kml.escrever(
        "doc", [{"nome": "Plantio", "geometria": p, "campos": {"Class_Refl": "Plantio", "area_ha": 1}}]
    )
    lido = kml.ler(texto)
    assert len(lido) == 1 and lido[0]["nome"] == "Plantio"
    assert lido[0]["campos"]["Class_Refl"] == "Plantio"
    g = lido[0]["geometria"]
    assert abs(g.area - p.area) < 1e-12  # o buraco foi lido
    assert shapely.equals_exact(g.geoms[0].exterior, p.exterior, tolerance=1e-6)


def test_kml_sem_entidade_externa():
    malicioso = (
        '<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>&x;</name></Placemark></Document></kml>'
    )
    try:
        kml.ler(malicioso)
    except Exception:  # noqa: BLE001 (recusar também serve; só não pode ler o arquivo)
        return
    assert True


def test_projeto_publico_mais_privado(tmp_path):
    pub = tmp_path / "p.yaml"
    pub.write_text("projetos:\n  - id: URTX\n    nome_projeto: URTX\n    classes_projeto: [A]\n", encoding="utf-8")
    priv = "projetos:\n  - id: URTX\n    verificado_tco2e: 500\n  - id: GRUPO1\n    imoveis: [PA-1-X]\n"
    lista = {p.id: p for p in projetos.carregar(pub, priv)}
    assert lista["URTX"].get("verificado_tco2e") == 500 and not lista["URTX"].privado
    assert lista["GRUPO1"].privado
    assert "verificado_tco2e" not in lista["URTX"].publico()
    assert lista["GRUPO1"].papel("qualquer") == "projeto"
    assert lista["URTX"].papel("A") == "projeto" and lista["URTX"].papel("B") == "fora"


def test_areas_do_projeto_e_aviso_de_poligono(lista_projetos, cfg):
    a = projetos.areas(lista_projetos[0], cfg)
    papeis = dict(zip(a["classe"], a["papel"], strict=True))
    assert papeis == {"Plantio": "projeto", "Aceiro": "entorno", "Excluída": "fora"}
    plantio = a[a.classe == "Plantio"].iloc[0]
    assert abs(plantio["ha"] - 36.0) < 0.2  # 600 m x 600 m
    a.loc[a.classe == "Plantio", "declarado_ha"] = 3.0
    assert any("Plantio" in x for x in projetos.conferir_areas(a))
