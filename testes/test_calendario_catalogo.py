import datetime as dt
import json

import pytest
from typer.testing import CliRunner

from raiz.calendario import catalogo, coleta, diarios
from raiz.calendario.cli import app

HOJE = dt.date(2026, 11, 12)


def cobertura(**contagens):
    return {"escopo": "publico_basico", "estados": {uf: {"municipios": n} for uf, n in contagens.items()}}


def fonte(fid):
    return next(f for f in coleta.fontes() if f["id"] == fid)


def test_cobertura_parcial_e_estado_pequeno_entram_zero_nao():
    todas = coleta.fontes()
    selecionadas = catalogo.selecionar(todas, cobertura(PA=144, AC=1, MT=0, AM=0))
    ids = {f["id"] for f in selecionadas}
    assert {"doe_pa", "doe_ac", "djen", "sbti"} <= ids
    assert "doe_mt" not in ids
    assert "doe_go" not in ids
    assert all(f["_ufs_processadas"] == ["AC", "PA"] for f in selecionadas)
    assert all("_ufs_processadas" not in f for f in todas)


def test_todas_as_ufs_processadas_observadas_tem_diario():
    observadas = "AC AP BA CE GO MA MG PA PI RN RO RR TO".split()
    selecionadas = catalogo.selecionar(coleta.fontes(), cobertura(**dict.fromkeys(observadas, 1)))
    assert {f["uf"] for f in selecionadas if f.get("grupo") == "diario_estadual"} == set(observadas)


@pytest.mark.parametrize(
    "d", [{}, {"escopo": "completo", "estados": {}}, cobertura(ZZ=1), cobertura(AC=-1), cobertura(AC=True)]
)
def test_cobertura_invalida_nao_vira_todas_ufs(d):
    with pytest.raises(ValueError):
        catalogo.estados_processados(d)


def test_estado_novo_sem_fonte_e_erro_visivel():
    with pytest.raises(ValueError, match="sem diário no catálogo: SC"):
        catalogo.selecionar(coleta.fontes(), cobertura(SC=1))


def test_manifesto_local_recusa_snapshot_completo_e_grande(tmp_path):
    p = tmp_path / "estados.json"
    p.write_text(json.dumps(cobertura(PA=1)))
    assert catalogo.estados_processados(catalogo.carregar_manifesto(p)) == {"PA"}
    p.write_text(json.dumps({"estados": {"PA": {"municipios": 1}}}))
    with pytest.raises(ValueError, match="manifesto público"):
        catalogo.carregar_manifesto(p)
    p.write_bytes(b" " * (catalogo.MAX_MANIFESTO + 1))
    with pytest.raises(ValueError, match="manifesto público"):
        catalogo.carregar_manifesto(p)


def test_cli_diaria_usa_cobertura_e_override_manual_preserva_mt(tmp_path, monkeypatch):
    p = tmp_path / "estados.json"
    p.write_text(json.dumps(cobertura(PA=1, MT=0)))
    vistas = []
    monkeypatch.setattr(coleta, "coletar", lambda lista, **_: (vistas.extend(lista) or [], []))
    resultado = CliRunner().invoke(
        app, ["coletar", "--sem-banco", "--saida", str(tmp_path / "agenda"), "--manifesto-estados", str(p)]
    )
    assert resultado.exit_code == 0, resultado.output
    assert "Diários dos estados processados: PA" in resultado.output
    assert "doe_pa" in {f["id"] for f in vistas} and "doe_mt" not in {f["id"] for f in vistas}
    vistas.clear()
    resultado = CliRunner().invoke(
        app, ["coletar", "--sem-banco", "--saida", str(tmp_path / "manual"), "--fontes", "doe_mt"]
    )
    assert resultado.exit_code == 0, resultado.output
    assert [f["id"] for f in vistas] == ["doe_mt"]


def test_portal_dias_e_suplementos_na_virada_do_ano():
    f = fonte("doe_go")
    sementes = diarios.sementes(f, dt.date(2027, 1, 2))
    assert len(sementes) == 7
    assert sementes[-1].endswith("2026-12-27.json")
    texto = json.dumps(
        {
            "erro": False,
            "itens": [
                {"id": 7441, "data": "12/11/2026", "suplemento": 0},
                {"id": 7440, "data": "12/11/2026", "suplemento": 1},
                {"id": 7200, "data": "01/11/2026"},
            ],
        }
    )
    assert diarios.descobrir(f, sementes[0], texto, HOJE) == [
        "https://diariooficial.abc.go.gov.br/portal/edicoes/download/7441",
        "https://diariooficial.abc.go.gov.br/portal/edicoes/download/7440",
    ]
    with pytest.raises(ValueError):
        diarios.descobrir(f, sementes[0], '{"erro":true,"msg":"resposta externa"}', HOJE)


def test_piaui_post_publico_pdf_paginacao_e_host():
    f = fonte("doe_pi")
    u = f["urls"][0]
    assert diarios.pedido(f, u)["metodo"] == "POST"
    assert diarios.pedido(f, u + "?pagina=2")["json_corpo"]["start"] == 200
    texto = json.dumps(
        {
            "recordsFiltered": 101,
            "data": [
                ['<a href="../doe/files/diarios/anexo/abc/DOEPI_216_2026.pdf">baixar</a>', "216/2026", "12/11/2026"],
                ['<a href="https://nao-permitido.example/edicao.pdf">baixar</a>', "215/2026", "11/11/2026"],
            ],
        }
    )
    assert diarios.descobrir(f, u, texto, HOJE) == [
        "https://www.diario.pi.gov.br/doe/files/diarios/anexo/abc/DOEPI_216_2026.pdf",
        u + "?pagina=1",
    ]


def test_maranhao_index_javascript_nao_e_executado():
    f = fonte("doe_ma")
    tx = """<button onclick="setModal('EX20261111','texto descartado','EX20261111','','1')">Diário</button>
    <button onclick="setModal('TE20261111','','TE20261111','','1')">Terceiros</button>
    <button onclick="setModal('ET20260629','','ET20260629','','1')">Antigo</button>
    <button onclick="fetch('https://nao-permitido.example')">outro</button>"""
    assert diarios.descobrir(f, f["urls"][0], tx, HOJE) == [
        "https://diariooficial.ma.gov.br/download.php?arq=EX20261111",
        "https://diariooficial.ma.gov.br/download.php?arq=TE20261111",
    ]


def test_links_pdfs_da_janela_sem_arquivo_antigo_ou_terceiro():
    f = fonte("doe_ro")
    texto = """<a href="/data/uploads/2026/11/DOE-12-11-2026.pdf">edição</a>
    <a href="/data/uploads/2026/11/DOE-SUPLEMENTAR-11-11-2026.pdf">extra</a>
    <a href="/data/uploads/2026/11/DOE-01-11-2026.pdf">antigo</a>
    <a href="https://outro.example/DOE-12-11-2026.pdf">externo</a>"""
    links = diarios.descobrir(f, f["urls"][0], texto, HOJE)
    assert len(links) == 2
    assert all("diof.ro.gov.br" in u for u in links)
    with pytest.raises(ValueError, match="documentos de edição"):
        diarios.descobrir(f, f["urls"][0], "<html>Página vazia</html>", HOJE)


def test_rn_corrente_e_ac_download_opaco_publico():
    rn, ac = fonte("doe_rn"), fonte("doe_ac")
    assert diarios.descobrir(
        rn, rn["urls"][0], '<a href="https://webdisk.diariooficial.rn.gov.br/Jornal/sdoe.pdf">Diário</a>', HOJE
    ) == ["https://webdisk.diariooficial.rn.gov.br/Jornal/sdoe.pdf"]
    assert diarios.descobrir(
        ac, ac["urls"][0], '<a href="https://diario.ac.gov.br/download.php?arquivo=YWJjLnBkZg==">PDF</a>', HOJE
    ) == ["https://diario.ac.gov.br/download.php?arquivo=YWJjLnBkZg=="]
    assert diarios.sementes({"modo": "djen"}, HOJE) is None
    assert diarios.descobrir({"modo": "djen"}, "", "", HOJE) is None
    assert diarios.pedido({"modo": "djen"}, "") is None


def test_roraima_formulario_publico_mesma_edicao_sem_gravar_dados_da_sessao():
    f = fonte("doe_rr")
    texto = """<form method="post" action="../_visualizar-doe/">
    <input name="doe" value="2026/11/doe-20261111.pdf">
    <input name="ipconexao" value="10.0.0.1">
    <input name="dia" value="11"><input name="mes" value="11"><input name="ano" value="2026">
    <input name="hora" value="17:00:00"><input name="extra" value="não enviar">
    </form>"""
    links = diarios.descobrir(f, f["urls"][0], texto, HOJE)
    assert links == ["https://imprensaoficial.rr.gov.br/_visualizar-doe/?doe=2026%2F11%2Fdoe-20261111.pdf"]
    assert "10.0.0.1" not in links[0] and "17:00" not in links[0]
    assert diarios.preparacao(f, links[0]) == f["urls"][0]
    pedido = diarios.pedido(f, links[0], texto)
    assert pedido["metodo"] == "POST"
    assert set(pedido["dados_form"]) == {"doe", "ipconexao", "dia", "mes", "ano", "hora"}
    assert pedido["dados_form"]["ipconexao"] == "10.0.0.1"
    with pytest.raises(ValueError, match="índice público"):
        diarios.pedido(f, links[0].replace("20261111", "20261110"), texto)
    with pytest.raises(ValueError, match="documento público"):
        diarios.pedido(f, links[0].replace("2026%2F11%2Fdoe-20261111.pdf", "..%2F..%2Fsegredo"), texto)
    assert diarios.preparacao(f, f["urls"][0]) is None
