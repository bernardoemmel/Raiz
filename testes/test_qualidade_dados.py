"""Portão exercitado com bytes que seriam publicados, sem rede nem descarte de linhas."""

import io
import json
import subprocess
import sys
import tarfile

import geopandas as gpd
import pytest
from shapely.geometry import box

from raiz.qualidade_dados import ErroQualidade, validar_arquivos, validar_json, validar_pacotes
from testes.dados_publicacao import csv_contrato

MUN = "1504950"
COD = "PA-1504950-" + "A" * 32
BASE = {"cod_imovel": COD, "ha": 100.0}


def csv(tipo="imoveis", mun=MUN, **valores):
    return {f"{tipo}_{mun}.csv": csv_contrato(tipo, {**BASE, **valores})}


@pytest.mark.parametrize(
    "campo,valor",
    [("ha", -1), ("pasto_ha", 101), ("novo_ha_p10", 101), ("pct_RL", 101), ("novo_pct", -1), ("ha", float("inf"))],
)
def test_bloqueia_faixas(campo, valor):
    with pytest.raises(ErroQualidade):
        validar_arquivos(csv(**{campo: valor}))


def test_preserva_metrica_do_dono_e_taxas_que_nao_sao_proporcoes():
    validar_arquivos(
        csv(
            pagamento_dono="participacao",
            dono_rs_ha_ano=200,
            tir_projeto_pct_p10=-100,
            tir_projeto_pct_p50=8,
            tir_projeto_pct_p90=120,
            declividade_media_pct=140,
            custo_restauracao_ha_p10=1000,
            custo_restauracao_ha_p50=2000,
            custo_restauracao_ha_p90=3000,
        )
    )


@pytest.mark.parametrize("faixa", [(3, 2, 4), (1, 4, 3), (1, None, 3)])
def test_quantilo_desordenado_ou_parcial_falha(faixa):
    with pytest.raises(ErroQualidade, match="P10"):
        validar_arquivos(csv(**dict(zip(["x_p10", "x_p50", "x_p90"], faixa, strict=True))))


def test_coluna_obrigatoria_e_duplicada_falham():
    for dados in [b"cod_imovel\nx\n", b"cod_imovel,ha,ha\nx,1,1\n"]:
        with pytest.raises(ErroQualidade):
            validar_arquivos({f"imoveis_{MUN}.csv": dados})


def test_area_de_complemento_compara_car_da_mesma_linha():
    complemento = csv_contrato("filtros", {"cod_imovel": COD, "filtro_territorial": "ok", "quilombo_ha": 101})
    with pytest.raises(ErroQualidade, match="maior"):
        validar_arquivos({**csv(), f"filtros_{MUN}.csv": complemento})


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("contato", "não publicar"),
        ("observacao", "nome: Pessoa de Teste"),
        ("uf", "Pessoa de Teste"),
        ("status_imovel", "Pessoa de Teste"),
        ("dat_criacao", "Pessoa de Teste"),
        ("modelo", "nome: Pessoa de Teste"),
        ("municipio", "dono: Pessoa de Teste"),
        ("mensagem", "teste@exemplo.invalid"),
    ],
)
def test_celula_pessoal_nunca_aparece_no_erro(campo, valor):
    with pytest.raises(ErroQualidade) as erro:
        validar_arquivos(csv(**{campo: valor}))
    assert valor not in str(erro.value)


def test_json_aninhado_e_extra_bloqueiam():
    for valor in [
        {"resultado": {"contato": "privado"}},
        {"observacao": '{"email":"teste@exemplo.invalid"}'},
        {"erro": "nome: Pessoa de Teste"},
        {"extra": {"valor": "Bearer " + "x" * 30}},
    ]:
        with pytest.raises(ErroQualidade):
            validar_json(valor)


def test_salto_entre_municipios_sem_usar_totais_de_area():
    arquivos = {}
    for i, taxa in enumerate([10, 10, 11, 9, 500]):
        arquivos.update(csv(mun=str(1504950 + i), taxa_tco2_ha_ano=taxa, ha=10 ** (i + 1)))
    with pytest.raises(ErroQualidade, match="salto municipal"):
        validar_arquivos(arquivos)
    arquivos.update(csv(mun="1504954", taxa_tco2_ha_ano=12, ha=100000))
    assert validar_arquivos(arquivos)["linhas"] == 5


def test_parquet_e_geojson_nao_podem_esconder_coluna_pessoal():
    geo = gpd.GeoDataFrame({"cod_imovel": [COD], "contato": ["privado"]}, geometry=[box(-50, -5, -49, -4)], crs=4326)
    buf = io.BytesIO()
    geo.to_parquet(buf)
    with pytest.raises(ErroQualidade, match="proibida"):
        validar_arquivos({**csv(), f"geo_{MUN}.parquet": buf.getvalue()})
    with pytest.raises(ErroQualidade, match="propriedade GeoJSON"):
        validar_arquivos({f"geo_{MUN}.geojson": geo.to_json(drop_id=True).encode()})


def test_pmtiles_inspeciona_todos_os_atributos(tmp_path):
    from raiz.tiles import gerar

    p = tmp_path / f"camadas_{MUN}.pmtiles"
    geo = gpd.GeoDataFrame({"cod_imovel": [COD], "contato": ["privado"]}, geometry=[box(-50, -5, -49, -4)], crs=4326)
    gerar(p, {"imoveis": geo}, zmin=1, zmax=1)
    with pytest.raises(ErroQualidade, match="atributo vetorial"):
        validar_arquivos({**csv(), p.name: p.read_bytes()})


def test_kml_rejeita_entidade_externa():
    with pytest.raises(ErroQualidade):
        validar_arquivos({"URTX.kml": b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><kml>&e;</kml>'})


def test_pacote_nao_extrai_caminhos_ou_links(tmp_path):
    p = tmp_path / "raiz_PA.tar.gz"
    with tarfile.open(p, "w:gz") as tar:
        info = tarfile.TarInfo("PA/../../fora")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ErroQualidade, match="TAR"):
        validar_pacotes([p])
    assert not (tmp_path / "fora").exists()


@pytest.mark.parametrize(
    "defeito",
    [
        "cauda_tar",
        "gzip_extra",
        "gzip_truncado",
        "gzip_crc",
        "padding_membro",
        "nome_apos_nulo",
        "uname",
        "gname",
        "pax",
        "linkname",
        "diretorio_com_nome",
    ],
)
def test_cli_confere_container_inteiro_sem_aprovar_metadados_privados(tmp_path, defeito):
    import gzip
    import traceback

    marcador = b"contato@exemplo.invalid"
    conteudo = b"{}"
    nome = "PA/fontes.json"
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        if defeito == "diretorio_com_nome":
            diretorio = tarfile.TarInfo("PA/")
            diretorio.type = tarfile.DIRTYPE
            diretorio.uname = marcador.decode()
            tar.addfile(diretorio)
        membro = tarfile.TarInfo(nome)
        membro.size = len(conteudo)
        if defeito in {"uname", "gname", "linkname"}:
            setattr(membro, defeito, marcador.decode())
        elif defeito == "pax":
            membro.pax_headers = {"comentario": marcador.decode()}
        tar.addfile(membro, io.BytesIO(conteudo))
    pacote = out.getvalue()
    bruto = bytearray(gzip.decompress(pacote))
    if defeito == "cauda_tar":
        pacote = gzip.compress(bruto + marcador)
    elif defeito == "gzip_extra":
        pacote += gzip.compress(marcador)
    elif defeito == "gzip_truncado":
        pacote = pacote[:-4]
    elif defeito == "gzip_crc":
        adulterado = bytearray(pacote)
        adulterado[-8] ^= 1
        pacote = bytes(adulterado)
    elif defeito == "padding_membro":
        inicio = 512 + len(conteudo)
        bruto[inicio : inicio + len(marcador)] = marcador
        pacote = gzip.compress(bruto)
    elif defeito == "nome_apos_nulo":
        inicio = len(nome) + 1
        bruto[inicio : inicio + len(marcador)] = marcador
        bruto[148:156] = b" " * 8
        bruto[148:156] = f"{sum(bruto[:512]):06o}\0 ".encode()
        pacote = gzip.compress(bruto)
    caminho = tmp_path / "raiz_PA.tar.gz"
    caminho.write_bytes(pacote)

    with pytest.raises(ErroQualidade) as erro:
        validar_pacotes([caminho])

    assert marcador.decode() not in "".join(traceback.format_exception(erro.value))


def test_cli_preserva_pacote_integro_com_diretorio_e_indice(tmp_path):
    caminho = tmp_path / "raiz_PA.tar.gz"
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        diretorio = tarfile.TarInfo("PA/")
        diretorio.type = tarfile.DIRTYPE
        tar.addfile(diretorio)
        for nome in ("fontes.json", "_versoes.json"):
            membro = tarfile.TarInfo("PA/" + nome)
            membro.size = 2
            tar.addfile(membro, io.BytesIO(b"{}"))
    caminho.write_bytes(out.getvalue())
    assert validar_pacotes([caminho]) == {"arquivos": 1, "tabelas": 0, "linhas": 0}


@pytest.mark.parametrize("nome", ["PA/contato@exemplo.invalid/", "ZZ/", "../PA/", "./PA/"])
def test_cli_diretorio_so_admite_nome_de_uf_real(tmp_path, nome):
    import traceback

    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        membro = tarfile.TarInfo(nome)
        membro.type = tarfile.DIRTYPE
        tar.addfile(membro)
    caminho = tmp_path / "raiz_PA.tar.gz"
    caminho.write_bytes(out.getvalue())

    with pytest.raises(ErroQualidade) as erro:
        validar_pacotes([caminho])

    assert nome not in "".join(traceback.format_exception(erro.value))


def test_cli_recusa_subdiretorio_extra(tmp_path):
    (tmp_path / "privado").mkdir()
    resultado = subprocess.run([sys.executable, "-m", "raiz.qualidade_dados", str(tmp_path)], capture_output=True)
    assert resultado.returncode == 1 and b"diret" in resultado.stderr


def test_executor_preserva_extra_privado_sem_levar_para_publicacao(tmp_path):
    from testes.test_armazem_release import GitHubFalso, _armazem

    gh, publico = GitHubFalso(), GitHubFalso()
    publico.privado = False
    aberto = _armazem(publico, tmp_path / "aberto", privado=False)
    a = _armazem(gh, tmp_path / "espelho", publico=aberto)
    a.local.por_bytes(f"saida/PA/imoveis_{MUN}.csv", next(iter(csv(municipio="Nova Esperança do Piriá").values())))
    a.publicar("PA", extra={"PA": {"erro": "nome: Pessoa de Teste"}})
    assert gh.uploads and publico.uploads
    assert all(b"Pessoa de Teste" not in dados for dados in publico.assets.values())


def test_vigilancia_valida_todo_lote_antes_do_primeiro_upload(tmp_path):
    from raiz.vigilancia.armazem import Armazem
    from raiz.vigilancia.publicacao import publicar

    arm = Armazem(tmp_path)
    arm.gravar_fontes({"origem": {"ok": True}})
    arm.registrar_rodada({"erro": "teste@exemplo.invalid"})

    class NaoPodeTocarRelease:
        def id(self):
            pytest.fail("tocou Release antes de validar todo o lote")

    with pytest.raises(ErroQualidade):
        publicar(arm, NaoPodeTocarRelease(), None)


def test_documento_numerico_nao_escapa_do_scanner():
    documento = int("529" + "982" + "247" + "25")
    with pytest.raises(ErroQualidade, match="pessoal"):
        validar_arquivos(csv(documento=documento))
    with pytest.raises(ErroQualidade, match="pessoal"):
        validar_json({"valor": documento})


def test_p50_p90_sem_p10_nao_e_faixa_completa():
    with pytest.raises(ErroQualidade, match="incompleta"):
        validar_arquivos(csv(outra_p50=9, outra_p90=2))


def test_binario_textual_e_metadados_de_campo_nao_escapam():
    import pyarrow as arrow
    import pyarrow.parquet as parquet

    for coluna, valor, meta in [
        ("texto", b"teste@exemplo.invalid", None),
        ("ha", 1.0, {b"contato": b"teste@exemplo.invalid"}),
    ]:
        tabela = arrow.table({"cod_imovel": [COD], coluna: [valor]})
        if meta:
            esquema = arrow.schema([tabela.schema.field(0), tabela.schema.field(1).with_metadata(meta)])
            tabela = tabela.cast(esquema)
        buf = io.BytesIO()
        parquet.write_table(tabela, buf)
        with pytest.raises(ErroQualidade):
            validar_arquivos({f"imoveis_{MUN}.parquet": buf.getvalue()})


def test_cabecalho_com_contato_nao_escapa():
    with pytest.raises(ErroQualidade, match="pessoal"):
        validar_arquivos(csv(**{"teste@exemplo.invalid": 1}))


@pytest.mark.parametrize(
    "xml",
    [
        "<kml><Document />teste@exemplo.invalid</kml>",
        "<kml><!--teste@exemplo.invalid--><Document /></kml>",
    ],
)
def test_texto_kml_em_cauda_ou_comentario_nao_escapa(xml):
    with pytest.raises(ErroQualidade, match="pessoal"):
        validar_arquivos({"URTX.kml": xml.encode()})


def test_geojson_membro_extra_da_geometria_nao_escapa():
    from shapely.geometry import mapping

    objeto = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"cod_imovel": COD},
                "geometry": {**mapping(box(-50, -5, -49, -4)), "contato": "teste@exemplo.invalid"},
            }
        ],
    }
    with pytest.raises(ErroQualidade, match="geometria GeoJSON"):
        validar_arquivos({f"geo_{MUN}.geojson": json.dumps(objeto).encode()})


def test_csv_truncado_mesmo_com_chave_e_area_nao_passa():
    with pytest.raises(ErroQualidade, match="obrigatórias"):
        validar_arquivos({f"imoveis_{MUN}.csv": f"cod_imovel,ha\n{COD},100\n".encode()})


def test_kml_aceita_classe_cartografica_aceiro_sem_bypass_para_nome_livre():
    for texto in (
        "<kml><Document><name>Aceiro 10 m</name></Document></kml>",
        '<kml><SimpleData name="Class_Refl">Aceiro 10m</SimpleData></kml>',
    ):
        validar_arquivos({"URTX.kml": texto.encode()})
    with pytest.raises(ErroQualidade):
        validar_arquivos({"URTX.kml": b"<kml><name>Aceiro 10 m; nome: Pessoa de Teste</name></kml>"})


def test_json_chave_repetida_nao_pode_ocultar_valor():
    with pytest.raises(ErroQualidade, match="duplicada"):
        validar_arquivos({"estados.json": b'{"erro":"teste@exemplo.invalid","erro":""}'})
