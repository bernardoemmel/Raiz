"""O arquivo privado precede a publicação; o aberto só aceita a projeção conhecida."""

import io
import json

import geopandas as gpd
import httpx
import pytest
from shapely.geometry import box

from raiz.executor.armazem import ArmazemRelease
from raiz.executor.publicacao_aberta import COLUNAS_BASICAS, projetar_csvs, projetar_geo, validar_asset_publico
from testes.test_armazem_release import REPO, TAG, GitHubFalso, _armazem

CAR = "PA-1504950-" + "A" * 32
CSV = (
    "cod_imovel,municipio,ha,carbono_ha,problema,credito_liquido_tco2_contrato\n"
    f"{CAR},Nova Esperança do Piriá,10,2,False,9999\n"
).encode()


def test_projecao_preserva_todos_os_cars_sem_metricas():
    pequena = "PA-1504950-" + "B" * 32
    dados = CSV + f"{pequena},Nova Esperança do Piriá,0.01,0.001,True,8888\n".encode()
    publicos = projetar_csvs("PA", {"imoveis_1504950.csv": dados, "desenvolvedor_1504950.csv": b"privado"})
    assert set(publicos) == {"imoveis_basicos_1504950.csv"}
    basico = publicos["imoveis_basicos_1504950.csv"].decode()
    assert basico.splitlines()[0].split(",") == list(COLUNAS_BASICAS)
    assert CAR in basico and pequena in basico and ",apto" in basico and ",com_pendencia" in basico
    assert "9999" not in basico and "8888" not in basico and "credito" not in basico
    validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", publicos))


@pytest.mark.parametrize("nome", ["imoveis_1504950.csv", "ficha_1504950.csv", "terra_1504950.csv", "_versoes.json"])
def test_upload_aberto_recusa_qualquer_tabela_completa(nome):
    with pytest.raises(ValueError):
        validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", {nome: CSV}))


def test_contorno_recriado_remove_metricas_e_metadados_privados():
    g = gpd.GeoDataFrame({"cod_imovel": [CAR], "credito": [9999]}, geometry=[box(-50, -4, -49, -3)], crs=4674)
    g.attrs["dado_privado"] = "reservado"
    bruto = io.BytesIO()
    g.to_parquet(bruto, index=False)
    with pytest.raises(ValueError, match="atributos privados"):
        validar_asset_publico(
            "raiz_geo_PA.tar.gz", ArmazemRelease._tar("PA", {"geo_1504950.parquet": bruto.getvalue()})
        )
    publico = projetar_geo(bruto.getvalue())
    validar_asset_publico("raiz_geo_PA.tar.gz", ArmazemRelease._tar("PA", {"geo_1504950.parquet": publico}))
    assert "credito" not in gpd.read_parquet(io.BytesIO(publico)).columns


def test_dupla_publicacao_guarda_integra_antes_de_expor_basico(tmp_path, monkeypatch):
    gh_privado, gh_publico = GitHubFalso(), GitHubFalso()
    gh_publico.privado = False
    aberto = _armazem(gh_publico, tmp_path / "aberto", privado=False)
    privado = _armazem(gh_privado, tmp_path / "privado", publico=aberto)
    privado.por_bytes("saida/PA/imoveis_1504950.csv", CSV)
    privado.por_bytes("saida/PA/desenvolvedor_1504950.csv", f"cod_imovel,tir_p50\n{CAR},42\n".encode())
    subir = aberto._subir

    def somente_depois_do_arquivo(*args, **kwargs):
        assert "estados.json" in gh_privado.assets
        assert gh_privado.membros("raiz_PA.tar.gz")["PA/imoveis_1504950.csv"] == CSV
        return subir(*args, **kwargs)

    monkeypatch.setattr(aberto, "_subir", somente_depois_do_arquivo)
    privado.publicar("PA")
    assert "PA/desenvolvedor_1504950.csv" in gh_privado.membros("raiz_PA.tar.gz")
    assert set(gh_publico.membros("raiz_PA.tar.gz")) == {"PA/imoveis_basicos_1504950.csv"}
    assert set(gh_publico.assets) == {
        "raiz_PA.tar.gz",
        "estados.json",
        "croissant_PA.json",
        "croissant_estados.json",
        "croissant_cartao_modelo.md.json",
        "cartao_modelo.md",
        "croissant.json",
    }
    for nome, dados in gh_publico.assets.items():
        validar_asset_publico(nome, dados)
    validar_asset_publico("estados.json", gh_publico.assets["estados.json"])
    assert json.loads(gh_publico.assets["estados.json"])["escopo"] == "publico_basico"


def test_publico_por_engano_nao_recebe_nem_le_snapshot(tmp_path):
    gh = GitHubFalso()
    gh.privado = False
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {"imoveis_1504950.csv": CSV})
    privado = _armazem(gh, tmp_path)
    with pytest.raises(PermissionError, match="rascunho"):
        privado.ler("saida/PA/imoveis_1504950.csv")
    with pytest.raises(PermissionError, match="rascunho"):
        privado.publicar("PA")
    assert not gh.uploads and not gh.downloads


def test_rascunho_autenticado_lookup_por_lista_e_fechado_apos_publicacao(tmp_path):
    gh = GitHubFalso()
    gh.privado, gh.rascunho = False, True
    gh.assets["raiz_PA.tar.gz"] = gh.tar("PA", {"imoveis_1504950.csv": CSV})

    def transporte(req):
        if req.url.path.endswith(f"/releases/tags/{TAG}"):
            return httpx.Response(404)
        if req.url.path.endswith("/releases"):
            assert req.headers["authorization"] == "Bearer segredo"
            return httpx.Response(200, json=[{"id": 7, "tag_name": TAG, "draft": gh.rascunho}])
        return gh(req)

    arm = ArmazemRelease(
        REPO,
        TAG,
        tmp_path,
        token="segredo",
        privado=True,
        cliente=httpx.Client(transport=httpx.MockTransport(transporte)),
    )
    assert arm.ler("saida/PA/imoveis_1504950.csv") == CSV
    assert gh.downloads and not gh.uploads
    gh.rascunho = False
    # Cada nova leitura remota confere de novo; uma mudança de visibilidade fecha o leitor.
    with pytest.raises(PermissionError, match="rascunho"):
        arm._baixar_asset("raiz_PA.tar.gz")


def test_manifesto_nao_aceita_atributo_privado_em_geo():
    info = {
        "escopo": "publico_basico",
        "versao_publicacao": 1,
        "url": f"https://github.com/{REPO}/releases/download/{TAG}/raiz_PA.tar.gz",
        "geo": {"escopo": "publico_basico", "credito": 999},
    }
    manifesto = {"escopo": "publico_basico", "versao_publicacao": 1, "repo": REPO, "tag": TAG, "estados": {"PA": info}}
    with pytest.raises(ValueError, match="privado"):
        validar_asset_publico("estados.json", json.dumps(manifesto).encode())


def test_recorte_municipal_preserva_imovel_limitrofe_sem_reescrever_car():
    dados = projetar_csvs("PA", {"imoveis_1507300.csv": CSV})
    pacote = ArmazemRelease._tar("PA", dados)
    validar_asset_publico("raiz_PA.tar.gz", pacote)
    assert CAR.encode() in dados["imoveis_basicos_1507300.csv"]
    assert b",1507300," in dados["imoveis_basicos_1507300.csv"]


@pytest.mark.parametrize("municipio", ["contato@exemplo.invalid", "nome: Pessoa de Teste", "Parauapebas"])
def test_coluna_permitida_nao_libera_texto_pessoal_ou_municipio_divergente(municipio):
    projetado = projetar_csvs("PA", {"imoveis_1504950.csv": CSV})
    chave = "imoveis_basicos_1504950.csv"
    projetado[chave] = projetado[chave].replace("Nova Esperança do Piriá".encode(), municipio.encode())
    with pytest.raises(ValueError) as erro:
        validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", projetado))
    assert municipio not in str(erro.value)


def test_parquet_publico_inspeciona_metadados_dos_campos():
    import pyarrow as pa
    import pyarrow.parquet as pq

    g = gpd.GeoDataFrame({"cod_imovel": [CAR]}, geometry=[box(-50, -4, -49, -3)], crs=4674)
    bruto = io.BytesIO()
    g.to_parquet(bruto, index=False)
    tabela = pq.read_table(io.BytesIO(bruto.getvalue()))
    campos = [
        f.with_metadata({b"nota": b"contato@exemplo.invalid"}) if f.name == "cod_imovel" else f for f in tabela.schema
    ]
    adulterada = pa.Table.from_arrays(tabela.columns, schema=pa.schema(campos, metadata=tabela.schema.metadata))
    out = io.BytesIO()
    pq.write_table(adulterada, out)
    with pytest.raises(ValueError):
        validar_asset_publico("raiz_geo_PA.tar.gz", ArmazemRelease._tar("PA", {"geo_1504950.parquet": out.getvalue()}))


def test_contorno_reprovado_impede_primeiro_upload_publico(tmp_path):
    gh_privado, gh_publico = GitHubFalso(), GitHubFalso()
    gh_publico.privado = False
    aberto = _armazem(gh_publico, tmp_path / "aberto", privado=False)
    privado = _armazem(gh_privado, tmp_path / "privado", publico=aberto)
    privado.por_bytes("saida/PA/imoveis_1504950.csv", CSV)
    g = gpd.GeoDataFrame({"cod_imovel": ["contato@exemplo.invalid"]}, geometry=[box(-50, -4, -49, -3)], crs=4674)
    bruto = io.BytesIO()
    g.to_parquet(bruto, index=False)
    privado.por_bytes("saida/PA/geo_1504950.parquet", bruto.getvalue())
    with pytest.raises(ValueError):
        privado.publicar("PA")
    assert gh_privado.uploads  # a preservação autenticada não é um selo de publicação
    assert gh_publico.uploads == []


def test_resumo_truncado_nao_passa_por_ser_csv_conhecido():
    with pytest.raises(ValueError):
        validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", {"resumo_PA.csv": b"cod_ibge\n1504950\n"}))


def test_metadado_de_dono_no_tar_nao_e_publicado():
    import tarfile

    basicos = projetar_csvs("PA", {"imoveis_1504950.csv": CSV})
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for nome, dado in basicos.items():
            membro = tarfile.TarInfo("PA/" + nome)
            membro.size = len(dado)
            membro.uname = "contato@exemplo.invalid"
            tar.addfile(membro, io.BytesIO(dado))
    with pytest.raises(ValueError) as erro:
        validar_asset_publico("raiz_PA.tar.gz", out.getvalue())
    assert "contato@" not in str(erro.value)


@pytest.mark.parametrize("ultima", ["1000000", "0.001"])
def test_resumo_publico_bloqueia_salto_de_intensidade_entre_municipios(ultima):
    from raiz.qualidade_dados import _municipios

    linhas = ["cod_ibge,municipio,imoveis,aptas_carbono,ha_carbono,tco2_ano_aptas"]
    municipios = [(c, n) for c, n in _municipios().items() if c.startswith("15")][:5]
    for i, (codigo, nome) in enumerate(municipios):
        carbono = ultima if i == 4 else "100"
        linhas.append(f"{codigo},{nome},10,10,10,{carbono}")
    with pytest.raises(ValueError, match="salto municipal"):
        validar_asset_publico(
            "raiz_PA.tar.gz", ArmazemRelease._tar("PA", {"resumo_PA.csv": "\n".join(linhas).encode()})
        )


def test_resumo_publico_nao_confunde_tamanho_com_intensidade_e_respeita_supressao():
    from raiz.qualidade_dados import _municipios

    linhas = ["cod_ibge,municipio,imoveis,aptas_carbono,ha_carbono,tco2_ano_aptas"]
    municipios = [(c, n) for c, n in _municipios().items() if c.startswith("15")][:7]
    for i, (codigo, nome) in enumerate(municipios):
        area = 10**i
        linhas.append(f"{codigo},{nome},10,10,{area},{area * 10}" if i < 5 else f"{codigo},{nome},10,10,0,")
    validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", {"resumo_PA.csv": "\n".join(linhas).encode()}))
    linhas = [linhas[0], f"{municipios[0][0]},{municipios[0][1]},1,1,10,100"]
    with pytest.raises(ValueError, match="grupo pequeno"):
        validar_asset_publico(
            "raiz_PA.tar.gz", ArmazemRelease._tar("PA", {"resumo_PA.csv": "\n".join(linhas).encode()})
        )


def test_recorte_municipal_admite_nome_atual_sem_reescrever_codigo_car():
    dados = projetar_csvs(
        "PA", {"imoveis_1507300.csv": CSV.replace("Nova Esperança do Piriá".encode(), b"Sao Felix do Xingu")}
    )
    validar_asset_publico("raiz_PA.tar.gz", ArmazemRelease._tar("PA", dados))


@pytest.mark.parametrize(
    "defeito",
    ["cauda_tar", "gzip_extra", "gzip_truncado", "gzip_crc", "padding_membro", "linkname", "nome_apos_nulo"],
)
def test_pacote_publico_confere_todos_os_bytes_sem_expor_conteudo(defeito):
    import gzip
    import tarfile
    import traceback

    marcador = b"contato@exemplo.invalid"
    nome = "sem_imoveis_PA.csv"
    conteudo = b"cod_ibge,municipio,verificado_em\n"
    pacote = ArmazemRelease._tar("PA", {nome: conteudo})
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
    elif defeito == "linkname":
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as tar:
            membro = tarfile.TarInfo("PA/" + nome)
            membro.size = len(conteudo)
            membro.linkname = marcador.decode()
            tar.addfile(membro, io.BytesIO(conteudo))
        pacote = out.getvalue()
    else:
        inicio = len("PA/" + nome) + 1
        bruto[inicio : inicio + len(marcador)] = marcador
        bruto[148:156] = b" " * 8
        bruto[148:156] = f"{sum(bruto[:512]):06o}\0 ".encode()
        pacote = gzip.compress(bruto)

    with pytest.raises(ValueError) as erro:
        validar_asset_publico("raiz_PA.tar.gz", pacote)

    assert marcador.decode() not in "".join(traceback.format_exception(erro.value))


@pytest.mark.parametrize("uf,cod,origem", [("RN", "2400604", "PB-2500106"), ("PI", "2200103", "PE-2600054")])
def test_recorte_estadual_preserva_car_de_outra_uf(uf, cod, origem):
    from raiz.qualidade_dados import _municipios

    car = origem + "-" + "B" * 32
    municipio = _municipios()[cod]
    fonte = ("cod_imovel,municipio,ha,problema\n" + f"{car},{municipio},0.01,False\n").encode()
    projetados = projetar_csvs(uf, {f"imoveis_{cod}.csv": fonte})
    validar_asset_publico(f"raiz_{uf}.tar.gz", ArmazemRelease._tar(uf, projetados))
    linhas = projetados[f"imoveis_basicos_{cod}.csv"].decode().splitlines()
    assert len(linhas) == 2
    assert linhas[1].split(",")[:4] == [car, cod, municipio, uf]
    assert linhas[0].split(",") == list(COLUNAS_BASICAS)


@pytest.mark.parametrize("origem", ["ZZ-2500106", "PB-2400604"])
def test_origem_cadastral_invalida_continua_bloqueada(origem):
    car = origem + "-" + "A" * 32
    fonte = (f"cod_imovel,ha\n{car},1\n").encode()
    projetados = projetar_csvs("RN", {"imoveis_2400604.csv": fonte})
    with pytest.raises(ValueError, match="valores omitidos"):
        validar_asset_publico("raiz_RN.tar.gz", ArmazemRelease._tar("RN", projetados))


def test_arquivo_de_municipio_fora_da_uf_do_recorte_continua_bloqueado():
    projetados = projetar_csvs("RN", {"imoveis_1504950.csv": CSV})
    with pytest.raises(ValueError, match="valores omitidos"):
        validar_asset_publico("raiz_RN.tar.gz", ArmazemRelease._tar("RN", projetados))


def test_processamento_publico_filtra_detalhes_e_recusa_injecao_aninhada():
    from raiz.executor.publicacao_aberta import entrada_publica

    observacao = {
        "versao": 1,
        "escopo": "unidade",
        "unidade": "RN-1",
        "municipios_total": 4,
        "municipios": {"prontos": 1, "em_execucao": 1, "com_erro": 1, "pendentes": 1, "desconhecidos": 0},
        "observado_em": "2026-11-13T00:00:00+00:00",
        "ultima_mudanca_em": "2026-11-12T23:59:30+00:00",
        "valido_ate": "2026-11-13T00:02:00+00:00",
        "erro": "DETALHE_INTERNO",
    }
    entrada = entrada_publica({"processamento": observacao}, uf="RN")
    entrada["url"] = f"https://github.com/{REPO}/releases/download/{TAG}/raiz_RN.tar.gz"
    manifesto = {
        "escopo": "publico_basico",
        "versao_publicacao": 1,
        "repo": REPO,
        "tag": TAG,
        "estados": {"RN": entrada},
    }
    assert "DETALHE_INTERNO" not in json.dumps(manifesto)
    validar_asset_publico("estados.json", json.dumps(manifesto).encode())
    entrada["processamento"]["municipios"]["cod_imovel"] = "DETALHE_INTERNO"
    with pytest.raises(ValueError, match="valores omitidos"):
        validar_asset_publico("estados.json", json.dumps(manifesto).encode())


@pytest.mark.parametrize("origem,aprovado", [("PB-2500106", True), ("PB-2400604", False), ("ZZ-2500106", False)])
def test_geo_do_recorte_preserva_outra_uf_mas_exige_origem_valida(origem, aprovado):
    car = origem + "-" + "B" * 32
    g = gpd.GeoDataFrame({"cod_imovel": [car]}, geometry=[box(-36, -6, -35, -5)], crs=4674)
    bruto = io.BytesIO()
    g.to_parquet(bruto, index=False)
    pacote = ArmazemRelease._tar("RN", {"geo_2400604.parquet": projetar_geo(bruto.getvalue())})
    if aprovado:
        validar_asset_publico("raiz_geo_RN.tar.gz", pacote)
    else:
        with pytest.raises(ValueError):
            validar_asset_publico("raiz_geo_RN.tar.gz", pacote)


def test_manifesto_nao_pode_escolher_outro_destino_para_escapar_do_portao():
    m = {"escopo": "publico_basico", "versao_publicacao": 1, "repo": "outro/projeto", "tag": TAG, "estados": {}}
    with pytest.raises(ValueError):
        validar_asset_publico("estados.json", json.dumps(m).encode(), repo=REPO, tag=TAG)
