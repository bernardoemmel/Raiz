"""TARs privados mantêm seus bytes, caminhos e esquemas reais, sem valores nas fichas."""

import copy
import hashlib
import io
import json
import tarfile

import pytest

from raiz import metadados as M
from raiz import metadados_lote as ML

mlc = pytest.importorskip("mlcroissant")
pytest.importorskip("croissant_baker")


def _pacote(tmp_path, membros):
    pacote = tmp_path / "lote_PA_central_r11_123_1_previsoes.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        for nome, dados in membros:
            info = tarfile.TarInfo(nome) if isinstance(nome, str) else nome
            info.size = len(dados)
            tar.addfile(info, io.BytesIO(dados))
    return pacote


def _entrada(pacote):
    return {
        "url": f"release-github://exemplo/raiz/dados-privados/{pacote.name}",
        "sha256": hashlib.sha256(pacote.read_bytes()).hexdigest(),
        "tamanho": pacote.stat().st_size,
    }


def _gerar(pacote):
    return ML.croissant_tar_csv(pacote, pacote.name, _entrada(pacote))


def test_esquemas_reais_tipos_hashes_e_leitura_local_sem_valores_na_ficha(tmp_path, monkeypatch):
    import requests

    membros = {
        "previsoes/desenvolvedor_1504950.csv": b"cod_imovel,ha\nCAR-SINTETICO-A,3\n",
        "outra_pasta/desenvolvedor_1504950.csv": b"cod_imovel,ha,coluna_nova\nCAR-SINTETICO-B,2.5,texto-unico\n",
        "previsoes/vazio.csv": b"cod_imovel,ha\n",
        "barata/lote_PA.csv": b"cod_ibge,p50\n0012345,7.25\n",
        "manifesto.json": b'{"dado":"SEGREDO_JSON_SINTETICO"}',
        "previsoes/registros/congeladas.jsonl": b'{"valor":"SEGREDO_JSONL_SINTETICO"}\n',
        "folhas_dono/relatorio.pdf": b"%PDF-1.7 SEGREDO_PDF_SINTETICO",
        "sem_extensao": b"SEGREDO_BINARIO_SINTETICO",
    }
    pacote = _pacote(tmp_path, membros.items())
    antes = pacote.read_bytes()

    def sem_rede(*args, **kwargs):
        pytest.fail("metadados e prova de leitura devem usar somente arquivos locais")

    monkeypatch.setattr(requests.sessions.Session, "request", sem_rede)
    ficha = _gerar(pacote)
    assert pacote.read_bytes() == antes
    assert ficha["name"] == pacote.name
    assert ficha["distribution"][0]["sha256"] == hashlib.sha256(antes).hexdigest()
    assert ficha["distribution"][0]["contentSize"] == str(len(antes))
    assert ficha["isAccessibleForFree"] is False
    arquivos = {d["name"]: d for d in ficha["distribution"][1:]}
    assert set(arquivos) == set(membros)
    for nome, dados in membros.items():
        assert arquivos[nome]["contentUrl"] == nome
        assert arquivos[nome]["sha256"] == hashlib.sha256(dados).hexdigest()
        assert arquivos[nome]["contentSize"] == str(len(dados))
        assert arquivos[nome]["containedIn"] == {"@id": "arquivo"}
    assert arquivos["folhas_dono/relatorio.pdf"]["encodingFormat"] == "application/pdf"
    assert arquivos["previsoes/registros/congeladas.jsonl"]["encodingFormat"] == "application/x-ndjson"
    assert arquivos["sem_extensao"]["encodingFormat"] == "application/octet-stream"
    registros = {r["name"]: r for r in ficha["recordSet"]}
    assert set(registros) == {nome for nome in membros if nome.endswith(".csv")}
    serializada = json.dumps(ficha, ensure_ascii=False)
    assert "CAR-SINTETICO" not in serializada
    assert "texto-unico" not in serializada
    assert "SEGREDO_" not in serializada
    assert "tabela_000" not in serializada
    assert "examples" not in {k for objeto in M._objetos(ficha) for k in objeto}
    assert "data" not in {k for objeto in M._objetos(ficha) for k in objeto}
    assert "license" not in ficha
    for nome, registro in registros.items():
        for campo in registro["field"]:
            assert campo["source"]["fileObject"] == {"@id": arquivos[nome]["@id"]}
            if campo["name"].startswith("cod_"):
                assert campo["dataType"] == "sc:Text"
    leitor = mlc.Dataset(copy.deepcopy(ficha), mapping={"arquivo": pacote})
    for nome, valor in (
        ("previsoes/desenvolvedor_1504950.csv", 3),
        ("outra_pasta/desenvolvedor_1504950.csv", 2.5),
    ):
        registro = registros[nome]
        campo = next(c for c in registro["field"] if c["name"] == "ha")
        linhas = list(leitor.records(registro["@id"]))
        assert linhas[0][campo["@id"]] == valor
    assert list(leitor.records(registros["previsoes/vazio.csv"]["@id"])) == []


@pytest.mark.parametrize(
    "nome",
    [
        "../fora.csv",
        "/absoluto.csv",
        "PA/../fora.csv",
        "PA/./a.csv",
        "PA//a.csv",
        "./a.csv",
        "PA\\a.csv",
        "C:/a.csv",
        "https:outro.csv",
    ],
)
def test_recusa_traversal_e_alias_antes_de_abrir_membros(tmp_path, monkeypatch, nome):
    pacote = _pacote(tmp_path, [("valido.csv", b"a\n1\n"), (nome, b"a\n1\n")])
    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *a, **k: pytest.fail("validação deve preceder cópia"))
    with pytest.raises(ValueError, match="membro inválido"):
        _gerar(pacote)
    assert not (tmp_path / "fora.csv").exists()


@pytest.mark.parametrize("tipo", [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE])
def test_recusa_links_e_especiais(tmp_path, monkeypatch, tipo):
    info = tarfile.TarInfo("objeto")
    info.type = tipo
    info.linkname = "valido.csv"
    pacote = _pacote(tmp_path, [("valido.csv", b"a\n1\n"), (info, b"")])
    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *a, **k: pytest.fail("objeto inválido não pode abrir"))
    with pytest.raises(ValueError, match="membro inválido"):
        _gerar(pacote)


def test_diretorios_canonicos_nao_viram_arquivos_na_ficha(tmp_path):
    diretorio = tarfile.TarInfo("previsoes")
    diretorio.type = tarfile.DIRTYPE
    vazio = tarfile.TarInfo("pasta_vazia")
    vazio.type = tarfile.DIRTYPE
    pacote = _pacote(tmp_path, [(diretorio, b""), (vazio, b""), ("previsoes/tabela.csv", b"a\n1\n")])
    ficha = _gerar(pacote)
    assert [m["name"] for m in ficha["distribution"][1:]] == ["previsoes/tabela.csv"]
    assert len(ficha["recordSet"]) == 1


@pytest.mark.parametrize("conteudo", [b"", b"conteudo"])
def test_recusa_conflito_arquivo_diretorio_e_diretorio_com_bytes(tmp_path, conteudo):
    diretorio = tarfile.TarInfo("conflito")
    diretorio.type = tarfile.DIRTYPE
    membros = [(diretorio, conteudo)]
    if not conteudo:
        membros.append(("conflito", b"arquivo"))
    pacote = _pacote(tmp_path, membros)
    with pytest.raises(ValueError, match="membro inválido"):
        _gerar(pacote)


@pytest.mark.parametrize("nomes", [("a.csv", "a.csv"), ("a.csv", "a.csv/b.csv")])
def test_recusa_duplicatas_e_ancestral_regular(tmp_path, nomes):
    pacote = _pacote(tmp_path, [(nome, b"a\n1\n") for nome in nomes])
    with pytest.raises(ValueError, match="membro|caminhos conflitantes"):
        _gerar(pacote)


@pytest.mark.parametrize(
    ("limite", "valor"),
    [("LIMITE_MEMBROS", 1), ("LIMITE_BYTES_PACOTE", 1), ("LIMITE_BYTES_MEMBRO", 3), ("LIMITE_BYTES_CONTEUDO", 7)],
)
def test_limites_explicitos_antes_de_copiar(tmp_path, monkeypatch, limite, valor):
    pacote = _pacote(tmp_path, [("a.csv", b"a\n1\n"), ("b.csv", b"b\n2\n")])
    monkeypatch.setattr(ML, limite, valor)
    monkeypatch.setattr(tarfile.TarFile, "extractfile", lambda *a, **k: pytest.fail("limite deve preceder cópia"))
    with pytest.raises(ValueError, match="limite"):
        _gerar(pacote)


@pytest.mark.parametrize("alteracao", [{"sha256": "a" * 64}, {"tamanho": 1}, {"bytes": 1}])
def test_confere_referencia_dos_bytes_originais(tmp_path, alteracao):
    pacote = _pacote(tmp_path, [("a.csv", b"a\n1\n")])
    with pytest.raises(ValueError, match="diverge"):
        ML.croissant_tar_csv(pacote, pacote.name, {**_entrada(pacote), **alteracao})


@pytest.mark.parametrize("cabecalho", [b"", b"a,a\n", b"cod_imovel,nome_proprietario\n", b"a,\n"])
def test_recusa_cabecalho_inseguro_antes_da_inferencia(tmp_path, monkeypatch, cabecalho):
    pacote = _pacote(tmp_path, [("a.csv", cabecalho)])
    monkeypatch.setattr(M, "_executar_lote", lambda *a, **k: pytest.fail("cabeçalho deve preceder inferência"))
    with pytest.raises(ValueError, match="cabeçalho"):
        _gerar(pacote)


def test_particiona_inferencia_e_validacao_com_ids_preservados(tmp_path, monkeypatch):
    pacote = _pacote(tmp_path, [(f"pasta_{i}/igual.csv", b"coluna,outra\n1,2\n") for i in range(5)])
    executar = M._executar_lote
    chamadas = []

    def registrar(tarefa, dados, *, isolado):
        chamadas.append((tarefa, len(dados.get("arquivos", [])), isolado))
        return executar(tarefa, dados, isolado=False)

    monkeypatch.setattr(M, "LIMITE_CAMPOS", 5)
    monkeypatch.setattr(M, "_executar_lote", registrar)
    ficha = _gerar(pacote)
    assert len(ficha["recordSet"]) == 5
    assert [(tamanho, isolado) for tarefa, tamanho, isolado in chamadas if tarefa == "baker"] == [
        (2, True),
        (2, True),
        (1, True),
    ]
    assert len({c["@id"] for r in ficha["recordSet"] for c in r["field"]}) == 10


def test_tar_sem_csv_descreve_arquivos_sem_fingir_tabela(tmp_path):
    pacote = _pacote(tmp_path, [("manifesto.json", b"{}"), ("relatorio.pdf", b"%PDF-1.7")])
    ficha = _gerar(pacote)
    assert len(ficha["distribution"]) == 3
    assert ficha["recordSet"] == []


def test_muitos_arquivos_nao_tabulares_reservam_espaco_para_tar_ancestral(tmp_path, monkeypatch):
    pacote = _pacote(tmp_path, [(f"pasta/relatorio_{i}.pdf", b"%PDF-1.7") for i in range(7)])
    validar, tamanhos = M.validar, []

    def conferir(parte):
        tamanhos.append(len(parte["distribution"]))
        validar(parte)

    monkeypatch.setattr(M, "LIMITE_CAMPOS", 3)
    monkeypatch.setattr(M, "validar", conferir)
    ficha = _gerar(pacote)
    assert len(ficha["distribution"]) == 8
    assert tamanhos == [3, 3, 3, 2]


def test_coluna_texto_apos_primeiro_bloco_permanece_no_tipo(tmp_path):
    csv = b"cod_imovel,medida\n" + b"CAR-SINTETICO,1\n" * 1002 + b"CAR-SINTETICO,pendente\n"
    pacote = _pacote(tmp_path, [("previsoes/resultado.csv", csv)])
    ficha = _gerar(pacote)
    tipos = {campo["name"]: campo["dataType"] for campo in ficha["recordSet"][0]["field"]}
    assert tipos["medida"] == "sc:Text" or "sc:Text" in tipos["medida"]
