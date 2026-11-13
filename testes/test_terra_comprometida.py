import json

import pytest
from shapely.geometry import box
from sqlalchemy import text

from raiz import terra_comprometida as tc
from raiz.ficha_prospeccao_dados import ficha


def reg(**kw):
    return {
        "fonte_id": "verra",
        "objeto_id": "VCS665",
        "registro": "VCS",
        "tipo": "projeto_carbono",
        "situacao": "ativo",
        "certeza": "poligono_oficial",
        "geometry": box(-60, -10, -59.99, -9.99),
        "uf": "MT",
        "fonte_url": "https://registry.verra.org/verra/public/program/VCS/projects/665",
        "data_referencia": None,
        "observado_em": "2026-11-01",
        **kw,
    }


def cov(**kw):
    return {
        "fonte_id": "verra",
        "estado": "parcial",
        "escopo": "projeto",
        "recorte": "VCS665",
        "url": "https://verra.org/registry/overview/",
        "consultado_em": "2026-11-01",
        **kw,
    }


def test_uniao_nao_soma_registros_iguais():
    car = box(-60.01, -10.01, -59.98, -9.98)
    simples = tc.cruzar(car, "MT", [reg()], [cov()], em="2026-11-12")
    duplo = tc.cruzar(car, "MT", [reg(), reg(objeto_id="VCS666")], [cov()], em="2026-11-12")
    assert duplo["situacao"] == "sobreposicao_confirmada"
    assert duplo["area_confirmada"]["valor"] == pytest.approx(simples["area_confirmada"]["valor"])
    assert len(duplo["evidencias"]) == 2
    assert duplo["area_confirmada"]["data_referencia"] is None


def test_ausencia_catalogo_e_programa_nao_provam_car_livre_ou_comprometido():
    car = box(-60, -10, -59.99, -9.99)
    catalogo = reg(geometry=None, certeza="catalogo_sem_geometria")
    art = reg(fonte_id="art_jurisdicional", registro="ART", tipo="programa_jurisdicional", geometry=car)
    r = tc.cruzar(car, "MT", [catalogo, art], [cov()], em="2026-11-12")
    assert r["situacao"] == "nao_verificado"
    assert r["area_confirmada"]["valor"] is None
    assert r["evidencias"] == []
    assert len(r["contexto_jurisdicional"]) == 1
    assert r["contexto_jurisdicional"][0]["area"]["valor"] is None


def test_retirada_temporal_prevalece_sem_apagar_historia():
    car = box(-60, -10, -59.99, -9.99)
    regs = [reg(), reg(situacao="retirado", observado_em="2026-11-10")]
    antes = tc.cruzar(car, "MT", regs, [cov()], em="2026-11-05")
    depois = tc.cruzar(car, "MT", regs, [cov()], em="2026-11-12")
    assert antes["area_confirmada"]["valor"] > 0
    assert depois["area_confirmada"]["valor"] == 0
    assert depois["evidencias"][0]["situacao"] == "retirado"


def test_prazo_encerrado_e_poligono_secundario_nao_confirmam():
    car = box(-60, -10, -59.99, -9.99)
    r = tc.cruzar(car, "MT", [reg(fim="2026-01-01")], [cov()], em="2026-11-12")
    assert r["area_confirmada"]["valor"] == 0
    r = tc.cruzar(car, "MT", [reg(certeza="poligono_secundario")], [cov()], em="2026-11-12")
    assert r["situacao"] == "indicio"
    assert r["area_indicio"]["valor"] > 0


def test_bbox_fora_recorte_e_falha_nao_criam_ausencia():
    car = box(-60, -10, -59.99, -9.99)
    for c in [cov(escopo="bbox", bbox=[-40, -4, -39, -3]), cov(estado="indisponivel")]:
        assert tc.cruzar(car, "MT", [], [c])["situacao"] == "nao_verificado"


def test_dto_elimina_pessoas_e_extras_aninhados():
    raw = tc.cruzar(box(-60, -10, -59.99, -9.99), "MT", [reg(nome="Pessoa", cpf="123", contato="email")], [cov()])
    raw["dono"] = {"nome": "Segredo"}
    raw["evidencias"][0]["dono"] = "Segredo"
    raw["evidencias"][0]["area"]["nome"] = "Segredo"
    raw["cobertura"][0]["licenca"] = "Segredo"
    final = ficha({"cod_imovel": "MT-5100000-ABC"}, banco={"terra_comprometida": raw})
    assert "Segredo" not in json.dumps(final)
    assert "dono" not in json.dumps(final)
    assert final["terra_comprometida"]["evidencias"][0]["data_referencia"] is None


@pytest.mark.banco
def test_ingestao_idempotente_privada_e_snapshot_parcial_nao_apaga(con):
    con.execute(
        text("""INSERT INTO funil.imovel(cod_imovel,uf,geom) VALUES('MT-TESTE','MT',
        ST_Multi(ST_GeomFromText('POLYGON((-60 -10,-59.99 -10,-59.99 -9.99,-60 -9.99,-60 -10))',4674)))""")
    )
    coleta = {"registros": [reg()], "cobertura": cov()}
    a = tc.ingerir(con, coleta)
    assert tc.ingerir(con, coleta) == a
    assert tc.atualizar(con, ["MT-TESTE"]) == 1
    assert tc.por_codigos(con, ["MT-TESTE"])["MT-TESTE"]["area_confirmada"]["valor"] > 0
    tc.ingerir(con, {"registros": [], "cobertura": cov(consultado_em="2026-11-12", estado="indisponivel")})
    tc.atualizar(con, ["MT-TESTE"])
    assert tc.por_codigos(con, ["MT-TESTE"])["MT-TESTE"]["area_confirmada"]["valor"] > 0
    tc.ingerir(
        con,
        {
            "registros": [reg(situacao="retirado", observado_em="2026-11-12")],
            "cobertura": cov(consultado_em="2026-11-12"),
        },
    )
    tc.atualizar(con, ["MT-TESTE"])
    assert tc.por_codigos(con, ["MT-TESTE"])["MT-TESTE"]["area_confirmada"]["valor"] == 0


def test_cobertura_invalida_e_fonte_sem_proveniencia_nao_confirmam():
    car = box(-60, -10, -59.99, -9.99)
    for bbox in (None, [-60, -10, -61, -11], [float("nan"), -10, -59, -9]):
        assert tc.cruzar(car, "MT", [], [cov(escopo="bbox", bbox=bbox)])["situacao"] == "nao_verificado"
    r = tc.cruzar(car, "MT", [reg(fonte_url=None, observado_em=None)], [cov()])
    assert r["area_confirmada"]["valor"] == 0
    assert r["area_indicio"]["valor"] > 0


def test_indicios_descontam_poligonos_confirmados_e_resultado_estavel_sem_nova_fonte():
    car = box(-60, -10, -59.99, -9.99)
    regs = [reg(), reg(objeto_id="VCS2", certeza="poligono_secundario")]
    r = tc.cruzar(car, "MT", regs, [cov()], em="2026-11-12")
    assert r["area_indicio"]["valor"] == 0
    assert r == tc.cruzar(car, "MT", regs, [cov()], em="2026-11-13")


@pytest.mark.banco
def test_redd_estadual_apenas_car_intersectado_sem_dado_pessoal(con):
    con.execute(
        text("""INSERT INTO funil.imovel(cod_imovel,uf,geom) VALUES
      ('PA-CONTEXTO','PA',
      ST_Multi(ST_GeomFromText('POLYGON((-50 -10,-49.99 -10,-49.99 -9.99,-50 -9.99,-50 -10))',4674))),
      ('PA-FORA','PA',
      ST_Multi(ST_GeomFromText('POLYGON((-55 -10,-54.99 -10,-54.99 -9.99,-55 -9.99,-55 -10))',4674)))""")
    )
    con.execute(
        text("""INSERT INTO geo.redd_programa(id,uf,inicio,fim,fonte,evidencia,geom)
      SELECT 'pa-periodo','PA','2023-01-01','2027-12-31','https://www.semas.pa.gov.br/redd/',
      '{"data":"2026-11-01","nome":"NAO_PUBLICAR"}'::jsonb,geom FROM funil.imovel WHERE cod_imovel='PA-CONTEXTO'""")
    )
    tc.atualizar(con, ["PA-CONTEXTO", "PA-FORA"])
    r = tc.por_codigos(con, ["PA-CONTEXTO", "PA-FORA"])
    assert r["PA-CONTEXTO"]["contexto_jurisdicional"][0]["fonte_id"] == "redd_estadual"
    assert r["PA-CONTEXTO"]["contexto_jurisdicional"][0]["data_referencia"] == "2026-11-01"
    assert r["PA-CONTEXTO"]["contexto_jurisdicional"][0]["observado_em"] is None
    assert r["PA-CONTEXTO"]["area_confirmada"]["valor"] is None
    assert r["PA-FORA"]["contexto_jurisdicional"] == []
    assert "NAO_PUBLICAR" not in json.dumps(r)


def test_identificador_e_caminho_oficial_nao_sao_excecao_para_dados_pessoais():
    from urllib.parse import quote

    from testes.test_privacidade import CNPJ, CPF

    for documento in (CPF, CNPJ, "".join(c for c in CPF if c.isdigit()), "".join(c for c in CNPJ if c.isalnum())):
        with pytest.raises(ValueError, match="identificadores reconhecidos"):
            tc.normalizar(reg(objeto_id="projeto-" + documento))
        r = tc.normalizar(reg(fonte_url="https://registry.verra.org/" + quote(documento, safe="")))
        assert r["fonte_url"] is None
    for sufixo in ("/contato%40example.invalid", "/nome-Pessoa-Sintetica", "/%0Aconteudo"):
        assert tc.normalizar(reg(fonte_url="https://www.gov.br" + sufixo))["fonte_url"] is None
    assert tc.normalizar(reg(fonte_url="https://:segredo-sintetico@www.gov.br/anexo"))["fonte_url"] is None
    assert tc.normalizar(reg())["fonte_url"].endswith("/projects/665")
