"""Publicação nacional do mapa sem depender de CAR/WFS no teste."""

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from pmtiles.reader import Reader
from pmtiles.tile import Compression
from shapely.geometry import box, mapping, shape


@pytest.fixture
def geo(tmp_path, monkeypatch):
    caminho = Path(__file__).resolve().parents[1] / "front/scripts/geo.py"
    spec = importlib.util.spec_from_file_location("geo_site", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    saida = tmp_path / "geo"
    saida.mkdir()
    monkeypatch.setattr(modulo, "SAIDA", saida)
    return modulo


def escrever_municipio(pasta, uf, cod, com_geo=True):
    destino = pasta / uf
    destino.mkdir(parents=True, exist_ok=True)
    csv = destino / f"imoveis_basicos_{cod}.csv"
    csv.write_text(
        f"cod_imovel,cod_ibge,municipio,uf,situacao_basica\nCAR-A,{cod},Cidade,{uf},apto\nCAR-B,{cod},Cidade,{uf},com_pendencia\n"
    )
    if com_geo:
        # O pacote mínimo pode repetir CAR; um CAR ausente do CSV não é publicado.
        gpd.GeoDataFrame(
            {"cod_imovel": ["CAR-A", "CAR-B", "CAR-A", "ANTIGO"]},
            geometry=[box(-50, -6, -49.9, -5.9), box(-50, -6, -49.99999999, -5.99999999)] * 2,
            crs=4326,
        ).to_parquet(destino / f"geo_{cod}.parquet")
    return csv


def manifesto_publico(*ufs, gerado_em=None):
    return {
        "versao_publicacao": 1,
        "escopo": "publico_basico",
        "gerado_em": gerado_em,
        "estados": {uf: {"versao_publicacao": 1, "escopo": "publico_basico"} for uf in ufs},
    }


def test_exporta_parquet_sem_dados_pessoais_e_sem_perder_fazenda_pequena(geo, tmp_path):
    csv = escrever_municipio(tmp_path / "dados", "PA", "1505536")
    antigo = geo.SAIDA / "imoveis_1505536.geojson"
    antigo.write_text("cache antigo")
    cache = {}
    quantidade, tamanho = geo.exportar_geometria(csv, cache)
    resultado = geo.SAIDA / "imoveis_1505536.geojson.gz"
    fs = json.loads(gzip.decompress(resultado.read_bytes()))["features"]
    assert quantidade == 2
    assert tamanho == resultado.stat().st_size
    assert [f["properties"] for f in fs] == [{"cod_imovel": "CAR-A"}, {"cod_imovel": "CAR-B"}]
    assert all(f["geometry"]["coordinates"] for f in fs)
    assert not antigo.exists()
    # Mesmo com o cache preenchido, uma tabela nova invalida a geometria antiga.
    csv.write_text("cod_imovel,cod_ibge,municipio,uf,situacao_basica\nCAR-B,1505536,Cidade,PA,com_pendencia\n")
    assert geo.exportar_geometria(csv, cache)[0] == 1


def test_geometria_publica_recusa_pacote_legado_e_campos_privados(geo, tmp_path):
    pasta = tmp_path / "dados"
    csv = escrever_municipio(pasta, "PA", "1505536")
    (pasta / "estados.json").write_text(json.dumps({"estados": {"PA": {}}}))
    with pytest.raises(ValueError, match="publico_basico"):
        geo.municipios_publicados(pasta)
    parcial = manifesto_publico("PA")
    parcial["estados"]["PA"] = {}
    (pasta / "estados.json").write_text(json.dumps(parcial))
    with pytest.raises(ValueError, match="publico_basico"):
        geo.municipios_publicados(pasta)
    origem = csv.with_name("geo_1505536.parquet")
    dados = gpd.read_parquet(origem)
    dados["credito_p50"] = 999999
    dados.to_parquet(origem)
    with pytest.raises(ValueError, match="fora do contrato"):
        geo.exportar_geometria(csv, {})
    assert not (geo.SAIDA / "imoveis_1505536.geojson.gz").exists()


@pytest.mark.parametrize(
    "cabecalho",
    ["cod_imovel,cod_ibge,situacao_basica", "cod_imovel,cod_ibge,municipio,uf,situacao_basica,municipio"],
)
def test_geometria_publica_exige_exatamente_cinco_colunas_basicas(geo, tmp_path, cabecalho):
    csv = escrever_municipio(tmp_path / "dados", "PA", "1505536")
    csv.write_text(cabecalho + "\n")
    with pytest.raises(ValueError, match="CSV público contém campos fora do contrato"):
        geo.exportar_geometria(csv, {})


def test_release_descobre_todos_os_municipios_e_indica_desenho_ausente(geo, tmp_path):
    pasta = tmp_path / "dados"
    escrever_municipio(pasta, "PA", "1505536")
    escrever_municipio(pasta, "GO", "5200050", com_geo=False)
    escrever_municipio(pasta, "MG", "3100104")
    (pasta / "estados.json").write_text(json.dumps(manifesto_publico("PA", "GO")))
    fronteiras = [
        {"type": "Feature", "properties": {"cod_ibge": cod, "nome": cod}, "geometry": mapping(box(-50, -6, -49, -5))}
        for cod in ("1505536", "5200050")
    ]
    geo.salvar("brasil_municipios.geojson", fronteiras)
    geo.salvar("brasil_estados.geojson", [])
    (geo.SAIDA / "base_PA.pmtiles").write_bytes(b"base compartilhada")
    (geo.SAIDA / "imoveis_5200050.geojson").write_text("cache velho")
    geo.do_release(pasta, sem_base=True)
    indice = json.loads((geo.SAIDA / "indice.json").read_text())
    assert set(indice["municipios"]) == {"1505536", "5200050"}
    assert indice["municipios"]["1505536"]["imoveis"]["arquivo"] == "imoveis_1505536.geojson.gz"
    assert indice["municipios"]["1505536"]["base"]["arquivo"] == "base_PA.pmtiles"
    assert "imoveis" not in indice["municipios"]["5200050"]
    assert "5200050" in indice["sem_contorno"]
    assert not (geo.SAIDA / "imoveis_5200050.geojson").exists()


def test_rodada_seguinte_inclui_municipio_e_estado_novos_sem_lista_fixa(geo, tmp_path):
    pasta = tmp_path / "dados"
    escrever_municipio(pasta, "PA", "1505536")
    manifesto = pasta / "estados.json"
    manifesto.write_text(json.dumps(manifesto_publico("PA", gerado_em="2026-11-11T10:00:00Z")))
    fronteiras = [
        {"type": "Feature", "properties": {"cod_ibge": cod}, "geometry": mapping(box(-50, -6, -49, -5))}
        for cod in ("1505536", "1502772", "5200050")
    ]
    geo.salvar("brasil_municipios.geojson", fronteiras)
    geo.salvar("brasil_estados.geojson", [])
    geo.do_release(pasta, sem_base=True)
    primeiro = json.loads((geo.SAIDA / "indice.json").read_text())
    assert set(primeiro["municipios"]) == {"1505536"}
    assert primeiro["dados_publicados_em"] == "2026-11-11T10:00:00Z"

    # Simula a próxima publicação do processamento, conservando o cache do site anterior.
    escrever_municipio(pasta, "PA", "1502772")
    escrever_municipio(pasta, "GO", "5200050", com_geo=False)
    manifesto.write_text(json.dumps(manifesto_publico("PA", "GO", gerado_em="2026-11-12T10:00:00Z")))
    geo.do_release(pasta, sem_base=True)
    segundo = json.loads((geo.SAIDA / "indice.json").read_text())
    assert set(segundo["municipios"]) == {"1505536", "1502772", "5200050"}
    assert segundo["dados_publicados_em"] == "2026-11-12T10:00:00Z"
    assert set(segundo["sem_contorno"]) == {"5200050"}
    assert "imoveis" in segundo["municipios"]["1502772"]

    # Quando o desenho chega depois, a mesma descoberta retira o aviso na rodada seguinte.
    escrever_municipio(pasta, "GO", "5200050")
    geo.do_release(pasta, sem_base=True)
    terceiro = json.loads((geo.SAIDA / "indice.json").read_text())
    assert not terceiro["sem_contorno"]
    assert "imoveis" in terceiro["municipios"]["5200050"]


def test_release_basico_prevalece_e_nao_reutiliza_csv_tecnico_antigo(geo, tmp_path):
    pasta = tmp_path / "dados"
    basico = escrever_municipio(pasta, "PA", "1505536")
    basico.write_text("cod_imovel,cod_ibge,municipio,uf,situacao_basica\nCAR-B,1505536,Cidade,PA,apto\n")
    basico.with_name("imoveis_1505536.csv").write_text("cod_imovel,credito_p50\nCAR-A,999999\n")
    basico.with_name("imoveis_1502772.csv").write_text("cache técnico de município retirado")
    (pasta / "estados.json").write_text(json.dumps(manifesto_publico("PA")))
    assert geo.municipios_publicados(pasta) == {"1505536": basico}
    assert geo.exportar_geometria(basico, {})[0] == 1
    fs = json.loads(gzip.decompress((geo.SAIDA / "imoveis_1505536.geojson.gz").read_bytes()))["features"]
    assert fs[0]["properties"] == {"cod_imovel": "CAR-B"}


@pytest.mark.parametrize(
    "vazio,municipios,saida,sem_url",
    [(False, 1, 0, False), (True, 0, 0, False), (True, 1, 1, False), (True, 0, 0, True)],
)
def test_atualizacao_do_pacote_remove_csv_antigo_e_conserva_geo(tmp_path, vazio, municipios, saida, sem_url):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    (pasta / "imoveis_1502772.csv").write_text("cache técnico antigo")
    car = "PA-1505536-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    origem_geo = pasta / "geo_1505536.parquet"
    gpd.GeoDataFrame({"cod_imovel": [car]}, geometry=[box(-50, -6, -49.9, -5.9)], crs=4326).to_parquet(origem_geo)
    geometria = origem_geo.read_bytes()
    pacote = io.BytesIO()
    with tarfile.open(fileobj=pacote, mode="w:gz") as tar:
        texto = f"cod_imovel,cod_ibge,municipio,uf,situacao_basica\n{car},1505536,Cidade,PA,apto\n".encode()
        membro = tarfile.TarInfo("PA/imoveis_basicos_1505536.csv")
        membro.size = len(texto)
        if not vazio:
            tar.addfile(membro, io.BytesIO(texto))
    pacote_geo = io.BytesIO()
    with tarfile.open(fileobj=pacote_geo, mode="w:gz") as tar:
        membro = tarfile.TarInfo("PA/geo_1505536.parquet")
        membro.size = len(geometria)
        tar.addfile(membro, io.BytesIO(geometria))

    def manifesto(versao):
        dado = manifesto_publico("PA")
        dado["estados"]["PA"].update(
            {
                "municipios": municipios,
                "tamanho": len(pacote.getvalue()),
                "versao": versao,
                "url": url + "/raiz_PA.tar.gz",
                "geo": {"escopo": "publico_basico", "versao": "g1", "url": url + "/raiz_geo_PA.tar.gz"},
            }
        )
        if sem_url and versao == "nova":
            dado["estados"]["PA"].pop("url")
            dado["estados"]["PA"].pop("geo")
            dado["estados"]["PA"]["tamanho"] = 0
        return dado

    class Servidor(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            if self.path == "/estados.json":
                self.wfile.write(json.dumps(manifesto("nova")).encode())
            elif self.path == "/raiz_geo_PA.tar.gz":
                self.wfile.write(pacote_geo.getvalue())
            else:
                self.wfile.write(pacote.getvalue())

        def log_message(self, *_args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Servidor)
    url = f"http://127.0.0.1:{servidor.server_port}"
    (tmp_path / "estados.json").write_text(json.dumps(manifesto("antiga")))
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        script = Path(__file__).resolve().parents[1] / "front/scripts/baixar-dados.mjs"
        resultado = subprocess.run(
            ["node", str(script), "--geo", "--exigir"],
            env={**os.environ, "RAIZ_DADOS_URL": url, "RAIZ_DADOS": str(tmp_path), "RAIZ_SEM_DOWNLOAD": "0"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert resultado.returncode == saida, resultado.stderr
        if sem_url:
            assert not pasta.exists(), "Município retirado do manifesto não pode voltar por cache antigo."
        elif saida == 0:
            assert sorted(p.name for p in pasta.iterdir()) == ["geo_1505536.parquet"] + (
                [] if vazio else ["imoveis_basicos_1505536.csv"]
            )
        else:
            # Falha fechada: arquivo vazio para município anunciado não substitui o snapshot anterior.
            assert "fora do contrato público" in resultado.stderr
            assert (pasta / "imoveis_1502772.csv").read_text() == "cache técnico antigo"
        if not sem_url:
            assert origem_geo.read_bytes() == geometria
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=2)


def test_base_nacional_uniforme_tem_tile_ao_aproximar_fora_do_para(geo, monkeypatch):
    class Remoto:
        def __init__(self, _url):
            self.header = {"tile_compression": Compression.NONE}

        def ladrilho(self, tid):
            return str(tid).encode()

        def metadados(self):
            return {"vector_layers": []}

    monkeypatch.setattr(geo, "Remoto", Remoto)
    geo.base_brasil("20260101")
    dados = (geo.SAIDA / "base_brasil.pmtiles").read_bytes()
    leitor = Reader(lambda inicio, tamanho: dados[inicio : inicio + tamanho])
    assert leitor.header()["max_zoom"] == 6
    for lon, lat in [(-49.9, -6.1), (-46.6, -23.5), (-67.8, -9.9), (-51.2, -30.0)]:
        z, x, y = geo.ladrilhos_na_caixa(6, (lon, lat, lon, lat))[0]
        assert leitor.get(z, x, y) is not None


def test_cache_nacional_parcial_nao_publica_uf_sem_fundo_e_pode_ser_refeito(geo):
    geo.salvar("brasil_municipios.geojson", [])
    geo.salvar("brasil_estados.geojson", [])
    pasta = geo.SAIDA / "cache"
    pasta.mkdir()
    bruto = pasta / "municipalities_cerrado_biome.geojson"
    bruto.write_text('{"features":[]}')
    with pytest.raises(RuntimeError, match="UFs.*GO"):
        geo.conferir_limites({"5200050": Path("imoveis_5200050.csv")}, {"5200050": {}}, [])
    assert not bruto.exists()
    assert not (geo.SAIDA / "brasil_municipios.geojson").exists()
    assert not (geo.SAIDA / "brasil_estados.geojson").exists()


@pytest.fixture
def malha_desmembrada(geo, monkeypatch):
    """Novo município ocupa partes dos dois anteriores; acrescentá-lo sozinho sobreporia os três."""
    codigos = ["5107925", "5106240", "5101837"]
    antigos = [
        geo.feicao(box(0, 0, 2, 1), {"cod_ibge": codigos[0], "nome": "Origem A", "uf": "MT"}),
        geo.feicao(box(2, 0, 4, 1), {"cod_ibge": codigos[1], "nome": "Origem B", "uf": "MT"}),
        geo.feicao(box(10, 0, 11, 1), {"cod_ibge": "1505536", "nome": "Outra UF", "uf": "PA"}),
    ]
    geo.salvar("brasil_municipios.geojson", antigos)
    geo.salvar("brasil_estados.geojson", [geo.feicao(box(0, 0, 4, 1), {"uf": "MT", "cod": "51"})])
    for f in antigos[:2]:
        geo.salvar(f"municipio_{f['properties']['cod_ibge']}.geojson", [f])
        geo.salvar(f"municipio_{f['properties']['cod_ibge']}.geojson.gz", [f])
    (geo.SAIDA / "imoveis_5107925.geojson.gz").write_bytes(b"CAR preservado")
    (geo.SAIDA / "base_MT.pmtiles").write_bytes(b"base preservada")
    pedidos = []
    dados = gpd.GeoDataFrame(
        {"CD_MUN": codigos, "NM_MUN": ["Origem A", "Origem B", "Novo"]},
        geometry=[box(0, 0, 1, 1), box(3, 0, 4, 1), box(1, 0, 3, 1)],
        crs=4674,
    )

    def baixar(url, **_kwargs):
        pedidos.append(url)
        if url == geo.MALHAS_IBGE:
            return SimpleNamespace(text='<a href="municipio_2024/">2024</a><a href="municipio_2025/">2025</a>')
        assert url.endswith("municipio_2025/UFs/MT/MT_Municipios_2025.zip")
        return SimpleNamespace(content=b"ZIP oficial simulado")

    monkeypatch.setattr(geo, "baixar", baixar)
    monkeypatch.setattr(gpd, "read_file", lambda *_a, **_kw: dados.copy())
    return codigos, antigos, dados, pedidos


def test_municipio_novo_atualiza_uf_pais_recortes_e_proveniencia_sem_sobrepor(geo, malha_desmembrada, monkeypatch):
    codigos, antigos, _, pedidos = malha_desmembrada
    publicados = {cod: Path(f"imoveis_{cod}.csv") for cod in codigos}
    geo.atualizar_malha_ibge(publicados)
    fs = json.loads((geo.SAIDA / "brasil_municipios.geojson").read_text())["features"]
    por_cod = {f["properties"]["cod_ibge"]: shape(f["geometry"]) for f in fs}
    assert set(por_cod) == {*codigos, "1505536"}
    assert next(f for f in fs if f["properties"]["uf"] == "PA") == json.loads(json.dumps(antigos[2]))
    assert por_cod[codigos[2]].area == pytest.approx(2)
    for pai in codigos[:2]:
        assert por_cod[pai].intersection(por_cod[codigos[2]]).area == 0
        recorte = json.loads((geo.SAIDA / f"municipio_{pai}.geojson").read_text())["features"][0]
        assert shape(recorte["geometry"]).equals(por_cod[pai])
        comprimido = json.loads(gzip.decompress((geo.SAIDA / f"municipio_{pai}.geojson.gz").read_bytes()))["features"][
            0
        ]
        assert comprimido == recorte, "A variante gzip não pode sobrescrever o recorte novo no índice."
    assert (geo.SAIDA / "imoveis_5107925.geojson.gz").read_bytes() == b"CAR preservado"
    assert (geo.SAIDA / "base_MT.pmtiles").read_bytes() == b"base preservada"
    geo.indice(codigos)
    assert json.loads((geo.SAIDA / "indice.json").read_text())["malhas"] == {
        "MT": {"fonte": "IBGE", "ano": 2025, "sha256": hashlib.sha256(b"ZIP oficial simulado").hexdigest()}
    }
    # Recriação da malha antiga/interrupção entre saídas: reaplica o ZIP conferido, sem rede e sem perder a UF nova.
    geo.salvar("brasil_municipios.geojson", antigos)
    geo.salvar("brasil_estados.geojson", [])
    monkeypatch.setattr(geo, "baixar", lambda *_a, **_kw: pytest.fail("Retomada não deve consultar a rede"))
    geo.atualizar_malha_ibge(publicados)
    assert len(pedidos) == 2, "A retomada reaplica a edição conferida mesmo se o índice remoto estiver indisponível."
    assert len(json.loads((geo.SAIDA / "brasil_municipios.geojson").read_text())["features"]) == 4
    assert json.loads((geo.SAIDA / "brasil_estados.geojson").read_text())["features"][0]["properties"]["uf"] == "MT"
    geo.atualizar_malha_ibge(publicados)
    assert len(pedidos) == 2, "Rodada normal reutiliza fonte/ano/hash sem nova consulta."


def test_municipio_novo_em_uf_ja_promovida_busca_edicao_mais_recente(geo, malha_desmembrada, monkeypatch):
    codigos, _, dados, pedidos = malha_desmembrada
    cache = geo.SAIDA / "cache"
    cache.mkdir()
    anterior = b"ZIP anterior confirmado"
    (cache / "MT_Municipios_2024.zip").write_bytes(anterior)
    (cache / "malhas-ibge-v1.json").write_text(
        json.dumps({"MT": {"fonte": "IBGE", "ano": 2024, "sha256": hashlib.sha256(anterior).hexdigest()}})
    )
    monkeypatch.setattr(gpd, "read_file", lambda nome, **_kw: (dados.iloc[:2] if "2024" in nome else dados).copy())
    geo.atualizar_malha_ibge({cod: Path("publicado.csv") for cod in codigos})
    assert len(pedidos) == 2
    assert (cache / "MT_Municipios_2024.zip").read_bytes() == anterior
    assert json.loads((cache / "malhas-ibge-v1.json").read_text())["MT"]["ano"] == 2025
    assert len(json.loads((geo.SAIDA / "brasil_municipios.geojson").read_text())["features"]) == 4


@pytest.mark.parametrize("problema", ["parcial", "duplicado", "outra_uf", "sem_crs"])
def test_malha_ibge_invalida_nao_substitui_saidas_nem_registra_edicao(geo, malha_desmembrada, monkeypatch, problema):
    codigos, _, dados, _ = malha_desmembrada
    if problema == "parcial":
        dados = dados.iloc[2:]
    elif problema == "duplicado":
        dados.loc[1, "CD_MUN"] = codigos[0]
    elif problema == "outra_uf":
        dados.loc[1, "CD_MUN"] = "1505536"
    else:
        dados = dados.set_crs(None, allow_override=True)
    monkeypatch.setattr(gpd, "read_file", lambda *_a, **_kw: dados.copy())
    anteriores = {p: p.read_bytes() for p in geo.SAIDA.iterdir() if p.is_file()}
    with pytest.raises((ValueError, RuntimeError), match="IBGE"):
        geo.atualizar_malha_ibge({cod: Path("publicado.csv") for cod in codigos})
    assert all(p.read_bytes() == conteudo for p, conteudo in anteriores.items())
    assert not (geo.SAIDA / "cache" / "malhas-ibge-v1.json").exists()


def test_malha_ibge_cache_com_hash_alterado_falha_sem_apagar_dados(geo, malha_desmembrada):
    codigos, _, _, _ = malha_desmembrada
    publicados = {cod: Path("publicado.csv") for cod in codigos}
    geo.atualizar_malha_ibge(publicados)
    zipado = geo.SAIDA / "cache" / "MT_Municipios_2025.zip"
    zipado.write_bytes(b"bytes alterados")
    anterior = (geo.SAIDA / "brasil_municipios.geojson").read_bytes()
    with pytest.raises(ValueError, match="hash"):
        geo.atualizar_malha_ibge(publicados)
    assert zipado.read_bytes() == b"bytes alterados"
    assert (geo.SAIDA / "brasil_municipios.geojson").read_bytes() == anterior


def test_malha_ibge_retomada_sem_zip_exige_o_mesmo_hash(geo, malha_desmembrada, monkeypatch):
    codigos, _, _, _ = malha_desmembrada
    publicados = {cod: Path("publicado.csv") for cod in codigos}
    geo.atualizar_malha_ibge(publicados)
    (geo.SAIDA / "cache" / "MT_Municipios_2025.zip").unlink()
    registro = geo.SAIDA / "cache" / "malhas-ibge-v1.json"
    anterior = registro.read_bytes()
    monkeypatch.setattr(geo, "baixar", lambda *_a, **_kw: SimpleNamespace(content=b"edicao modificada"))
    with pytest.raises(ValueError, match="hash"):
        geo.atualizar_malha_ibge(publicados)
    assert registro.read_bytes() == anterior


def test_servidor_sem_range_nao_e_aceito_como_pmtiles(geo, monkeypatch):
    class Resposta:
        status_code = 200
        content = b"arquivo inteiro"

    monkeypatch.setattr(geo, "baixar", lambda *_a, **_k: Resposta())
    with pytest.raises(RuntimeError, match="HTTP Range"):
        geo.Remoto("https://exemplo.test/base.pmtiles")


def test_tiles_concorrentes_compartilham_download_e_leitura_do_diretorio(geo, monkeypatch):
    leituras = []
    interpretacoes = []
    remoto = geo.Remoto.__new__(geo.Remoto)
    remoto.cache = {}
    remoto.trava = threading.Lock()
    remoto.ler = lambda inicio, tamanho: leituras.append((inicio, tamanho)) or b"diretorio"
    monkeypatch.setattr(geo, "deserialize_directory", lambda dado: interpretacoes.append(dado) or ["tile"])
    with ThreadPoolExecutor(16) as executor:
        resultados = list(executor.map(lambda _: remoto.diretorio(127, 50), range(64)))
    assert leituras == [(127, 50)]
    assert interpretacoes == [b"diretorio"]
    assert all(resultado == ["tile"] for resultado in resultados)


@pytest.mark.parametrize("municipios,saida", [(0, 0), (1, 1)])
def test_download_estrito_distingue_estado_sem_pacote_de_download_quebrado(tmp_path, municipios, saida):
    pedidos = []

    class Servidor(BaseHTTPRequestHandler):
        def do_GET(self):
            pedidos.append(self.path)
            if self.path == "/estados.json":
                self.send_response(200)
                self.end_headers()
                corpo = {
                    "versao_publicacao": 1,
                    "escopo": "publico_basico",
                    "estados": {
                        "AM": {
                            "municipios": municipios,
                            "versao": "v1",
                            "versao_publicacao": 1,
                            "escopo": "publico_basico",
                            **({"url": url + "/raiz_AM.tar.gz"} if municipios else {}),
                        }
                    },
                }
                self.wfile.write(json.dumps(corpo).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_args):
            pass

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Servidor)
    url = f"http://127.0.0.1:{servidor.server_port}"
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        script = Path(__file__).resolve().parents[1] / "front/scripts/baixar-dados.mjs"
        resultado = subprocess.run(
            ["node", str(script), "--geo", "--exigir"],
            env={**os.environ, "RAIZ_DADOS_URL": url, "RAIZ_DADOS": str(tmp_path), "RAIZ_SEM_DOWNLOAD": "0"},
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert resultado.returncode == saida, resultado.stderr
        assert pedidos == (["/estados.json"] if municipios == 0 else ["/estados.json", "/raiz_AM.tar.gz"])
    finally:
        servidor.shutdown()
        servidor.server_close()
        thread.join(timeout=2)
