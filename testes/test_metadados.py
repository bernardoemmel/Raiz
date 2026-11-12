"""Os metadados devem descrever e permitir ler os mesmos bytes publicados."""

import copy
import hashlib
import json
import tarfile
from fnmatch import fnmatchcase

import pytest

from raiz.metadados import CONFORMIDADE, croissant_release, croissant_uf, ficha_arquivo, validar

mlc = pytest.importorskip("mlcroissant")
pytest.importorskip("croissant_baker")


def _entrada(pacote):
    return {
        "url": f"release-github://exemplo/raiz/dados-privados/{pacote.name}",
        "sha256": hashlib.sha256(pacote.read_bytes()).hexdigest(),
        "tamanho": pacote.stat().st_size,
        "versao": "1.0.0",
        "atualizado_em": "2026-11-12T20:00:00Z",
    }


def test_croissant_le_tar_com_esquemas_diferentes_sem_rede(tmp_path, monkeypatch):
    pasta = tmp_path / "PA"
    pasta.mkdir()
    (pasta / "imoveis_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3\n", encoding="utf-8")
    (pasta / "imoveis_1504951.csv").write_text("cod_imovel,ha,coluna_nova\nCAR-B,2.5,sim\n", encoding="utf-8")
    (pasta / "extras_direto_1504950.csv").write_text("cod_imovel,tmf_classe\nCAR-A,4\n", encoding="utf-8")
    (pasta / "extras_1504950.csv").write_text("cod_imovel,fogo_anos\nCAR-A,2\n", encoding="utf-8")
    (pasta / "flag_1504950.csv").write_text("cod_imovel,flag_tco2_ano\n", encoding="utf-8")
    (pasta / "imoveis_1504950.csv.meta.json").write_text('{"segredo":"NAO_PUBLICAR"}', encoding="utf-8")
    (pasta / "geo_1504950.parquet").write_bytes(b"fora do pacote CSV")
    pacote = tmp_path / "raiz_PA.tar.gz"
    with tarfile.open(pacote, "w:gz") as tar:
        for arquivo in pasta.glob("*.csv"):
            tar.add(arquivo, arcname=f"PA/{arquivo.name}")
    # A validação é estática e a prova de leitura usa somente o tar local.
    import requests

    def sem_rede(*args, **kwargs):
        pytest.fail("a ficha não deve baixar dados para validar")

    monkeypatch.setattr(requests.sessions.Session, "request", sem_rede)
    ficha = croissant_uf(pasta, "pa", _entrada(pacote), escopo="privado")
    assert ficha["@type"] == "sc:Dataset"
    assert ficha["conformsTo"] == CONFORMIDADE
    assert "@base" not in ficha["@context"]  # o validador não modifica a ficha
    assert "license" not in ficha  # o baker presume CC-BY; a Raíz não presume
    assert "ainda não foi definida" in ficha["conditionsOfAccess"]
    assert ficha["distribution"][0]["sha256"] == _entrada(pacote)["sha256"]
    serializada = json.dumps(ficha)
    assert "CAR-A" not in serializada
    assert "NAO_PUBLICAR" not in serializada
    assert "geo_1504950" not in serializada
    assert '"examples"' not in serializada.replace(json.dumps(ficha["@context"]), "")
    conjuntos = {d["name"]: d for d in ficha["distribution"] if d["@type"] == "cr:FileSet"}
    assert conjuntos["imoveis"]["includes"] == ["PA/imoveis_" + "[0-9]" * 7 + ".csv"]
    padrao_extras = conjuntos["extras"]["includes"][0]
    assert fnmatchcase("PA/extras_1504950.csv", padrao_extras)
    assert not fnmatchcase("PA/extras_direto_1504950.csv", padrao_extras)
    assert conjuntos["extras_direto"]["containedIn"] == {"@id": "arquivo"}
    leitor = mlc.Dataset(copy.deepcopy(ficha), mapping={"arquivo": pacote})
    registros = list(leitor.records("imoveis_1504950"))
    assert registros[0]["imoveis_1504950/ha"] == 3
    registros_novos = list(leitor.records("imoveis_1504951"))
    assert registros_novos[0]["imoveis_1504951/ha"] == 2.5
    assert registros_novos[0]["imoveis_1504951/coluna_nova"] == b"sim"
    assert list(leitor.records("flag_1504950")) == []


def test_ficha_recusa_coluna_pessoal_antes_de_chamar_baker(tmp_path, monkeypatch):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,nome_proprietario\nCAR-A,NAO_PUBLICAR\n")
    with pytest.raises(ValueError, match="coluna pessoal proibida"):
        croissant_uf(
            tmp_path,
            "PA",
            {"url": "release-github://exemplo/raiz/dados-privados/a", "sha256": "a" * 64},
            escopo="privado",
        )


def test_ficha_recusa_csv_corrompido_sem_copiar_valores(tmp_path):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3\n")
    (tmp_path / "filtros_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3,NAO_PUBLICAR\n")
    with pytest.raises(ValueError, match="baker não descreveu") as erro:
        croissant_uf(
            tmp_path,
            "PA",
            {"url": "release-github://exemplo/raiz/dados-privados/a", "sha256": "a" * 64},
            escopo="privado",
        )
    assert "NAO_PUBLICAR" not in str(erro.value)


def test_ficha_arquivo_e_catalogo_sem_fingir_hash_ou_licenca():
    with pytest.raises(ValueError, match="SHA-256"):
        ficha_arquivo(
            "raiz_PA.tar.gz", "release-github://exemplo/raiz/dados-privados/a", "versao-curta", escopo="privado"
        )
    arquivo = ficha_arquivo(
        "URTX.kml", "release-github://exemplo/raiz/dados-privados/URTX.kml", "b" * 64, 100, escopo="privado"
    )
    validar(arquivo)
    assert arquivo["recordSet"] == []
    assert "license" not in arquivo
    indice = {
        "gerado_em": "2026-11-12T20:00:00Z",
        "estados": {
            "PA": {
                "croissant": {
                    "url": "release-github://exemplo/raiz/dados-privados/croissant_PA.json",
                    "sha256": "c" * 64,
                },
                "fichas": {"raiz_geo_PA.tar.gz": "release-github://exemplo/raiz/dados-privados/croissant_geo_PA.json"},
            },
            "AM": {"versao": "antigo-sem-ficha"},
        },
        "fichas": {"URTX.kml": "release-github://exemplo/raiz/dados-privados/croissant_URTX.kml.json"},
    }
    catalogo = croissant_release(indice, "exemplo/raiz", "dados-privados", escopo="privado")
    validar(catalogo)
    assert len(catalogo["hasPart"]) == 3
    assert {p["name"] for p in catalogo["hasPart"]} == {"raiz_PA.tar.gz", "raiz_geo_PA.tar.gz", "URTX.kml"}
    assert len(catalogo["distribution"]) == 1  # só há hash confirmado para a ficha de PA
    assert "antigo-sem-ficha" not in json.dumps(catalogo)


def test_ficha_deterministica_sem_horario_da_geracao(tmp_path):
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,ha\nCAR-A,3\n")
    entrada = {
        "url": "release-github://exemplo/raiz/dados-privados/raiz_PA.tar.gz",
        "sha256": "a" * 64,
        "versao": "1.0.0",
    }
    assert croissant_uf(tmp_path, "PA", entrada, escopo="privado") == croissant_uf(
        tmp_path, "PA", entrada, escopo="privado"
    )


def test_inferencia_le_tambem_os_blocos_posteriores(tmp_path):
    # Arrow infere pelo primeiro MiB. Um decimal posterior não pode ficar
    # descrito como inteiro, senão o consumidor trunca a área do imóvel.
    (tmp_path / "imoveis_1504950.csv").write_text("cod_imovel,ha\n" + "CAR-A,3\n" * 160_000 + "CAR-B,2.5\n")
    ficha = croissant_uf(
        tmp_path, "PA", {"url": "release-github://exemplo/raiz/dados-privados/a", "sha256": "a" * 64}, escopo="privado"
    )
    campos = {c["name"]: c for c in ficha["recordSet"][0]["field"]}
    assert campos["ha"]["dataType"] == "cr:Float64"


def _ficha_plana():
    ficha = ficha_arquivo(
        "dados.tar.gz",
        "release-github://exemplo/raiz/dados-privados/dados.tar.gz",
        "a" * 64,
        formato="application/x-tar",
        escopo="privado",
    )
    ficha["distribution"].extend(
        {
            "@id": nome,
            "@type": "cr:FileObject",
            "name": nome,
            "contentUrl": nome + ".csv",
            "sha256": "b" * 64,
            "encodingFormat": "text/csv",
            "containedIn": {"@id": "arquivo"},
        }
        for nome in ("a", "b", "sem_uso")
    )
    for nome in ("a", "b"):
        ficha["recordSet"].append(
            {
                "@id": "registros_" + nome,
                "@type": "cr:RecordSet",
                "name": "registros_" + nome,
                "field": [
                    {
                        "@id": f"registros_{nome}/{coluna}",
                        "@type": "cr:Field",
                        "name": coluna,
                        "dataType": "sc:Text",
                        "source": {"fileObject": {"@id": nome}, "extract": {"column": coluna}},
                    }
                    for coluna in ("cod_imovel", "classe")
                ],
            }
        )
    return ficha


def test_validacao_limitada_cobre_tudo_sem_mutar_entrada(monkeypatch):
    from raiz import metadados

    ficha = _ficha_plana()
    anterior = copy.deepcopy(ficha)
    chamadas = []
    original = mlc.Dataset

    def capturar(parte):
        chamadas.append(copy.deepcopy(parte))
        resultado = original(parte)  # todos os lotes passam pelo validador real
        parte["name"] = "alteração interna do leitor"
        return resultado

    monkeypatch.setattr(metadados, "LIMITE_CAMPOS", 3)
    monkeypatch.setattr(mlc, "Dataset", capturar)
    validar(ficha)
    assert ficha == anterior
    assert len(chamadas) == 3  # dois RecordSets e o arquivo sem uso com seu pai
    assert [r["@id"] for p in chamadas for r in p["recordSet"]] == ["registros_a", "registros_b"]
    assert {d["@id"] for p in chamadas for d in p["distribution"]} == {"arquivo", "a", "b", "sem_uso"}
    for parte in chamadas:
        assert sum(len(r["field"]) for r in parte["recordSet"]) <= 3
        assert {k: v for k, v in parte.items() if k not in {"distribution", "recordSet"}} == {
            k: v for k, v in ficha.items() if k not in {"distribution", "recordSet"}
        }
        assert all(d == next(x for x in ficha["distribution"] if x["@id"] == d["@id"]) for d in parte["distribution"])
        assert "arquivo" in {d["@id"] for d in parte["distribution"]}


@pytest.mark.parametrize(
    "caso", ["id_repetido", "id_campo_arquivo", "origem_orfa", "origem_tipo", "pai_orfao", "ciclo"]
)
def test_invariantes_globais_falham_antes_de_validar_qualquer_lote(monkeypatch, caso):
    from raiz import metadados

    ficha = _ficha_plana()
    a, b = ficha["recordSet"]
    if caso == "id_repetido":
        b["field"][0]["@id"] = a["field"][0]["@id"]
    elif caso == "id_campo_arquivo":
        b["field"][0]["@id"] = "arquivo"
    elif caso == "origem_orfa":
        b["field"][0]["source"]["fileObject"]["@id"] = "ausente"
    elif caso == "origem_tipo":
        b["field"][0]["source"]["fileObject"]["@id"] = a["field"][0]["@id"]
    elif caso == "pai_orfao":
        ficha["distribution"][-1]["containedIn"]["@id"] = "ausente"
    else:
        ficha["distribution"][0]["containedIn"] = {"@id": "a"}
    monkeypatch.setattr(metadados, "LIMITE_CAMPOS", 3)
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("falha global deve preceder todos os lotes"))
    with pytest.raises(ValueError):
        validar(ficha)


@pytest.mark.parametrize("chave", ["references", "parentField", "subField", "annotation", "data"])
def test_ficha_grande_com_relacao_fora_do_perfil_nao_omite_campos(monkeypatch, chave):
    from raiz import metadados

    ficha = _ficha_plana()
    ficha["recordSet"][0]["field"][0][chave] = {"@id": "registros_b/classe"}
    monkeypatch.setattr(metadados, "LIMITE_NOS", 1)
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("não pode validar silenciosamente outro grafo"))
    with pytest.raises(ValueError, match="fora do perfil"):
        validar(ficha)


@pytest.mark.parametrize("chave", ["@graph", "@reverse", "@included", "@nest"])
def test_expansao_jsonld_nao_suportada_em_ficha_grande_e_recusada(monkeypatch, chave):
    from raiz import metadados

    ficha = _ficha_plana()
    ficha[chave] = {"@id": "NAO_PUBLICAR"}
    monkeypatch.setattr(metadados, "LIMITE_NOS", 1)
    with pytest.raises(ValueError, match="fora do perfil") as erro:
        validar(ficha)
    assert "NAO_PUBLICAR" not in str(erro.value)


def test_contexto_remoto_nunca_e_baixado(monkeypatch):
    ficha = _ficha_plana()
    ficha["@context"] = "release-github://exemplo/raiz/dados-privados/NAO_PUBLICAR"
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("contexto remoto não pode acessar rede"))
    with pytest.raises(ValueError, match="contexto remoto") as erro:
        validar(ficha)
    assert "NAO_PUBLICAR" not in str(erro.value)


def test_recordset_maior_que_limite_nao_e_truncado(monkeypatch):
    from raiz import metadados

    monkeypatch.setattr(metadados, "LIMITE_CAMPOS", 1)
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("não deve validar parte do RecordSet"))
    with pytest.raises(ValueError, match="único elemento excede"):
        validar(_ficha_plana())


def test_distribuicao_invalida_sem_recordset_tambem_e_validada():
    ficha = _ficha_plana()
    del ficha["distribution"][-1]["encodingFormat"]
    with pytest.raises(mlc.ValidationError):
        validar(ficha)


def test_ficha_generica_pequena_usa_validador_integral(monkeypatch):
    ficha = _ficha_plana()
    ficha["keywords"] = ["dado público"]
    chamadas = []
    original = mlc.Dataset
    monkeypatch.setattr(mlc, "Dataset", lambda p: chamadas.append(copy.deepcopy(p)) or original(p))
    validar(ficha)
    assert chamadas == [ficha]


def test_baker_em_lotes_preserva_ficha_ids_e_origens(tmp_path, monkeypatch):
    from raiz import metadados

    for i in range(5):
        (tmp_path / f"imoveis_150495{i}.csv").write_text(f"cod_imovel,ha\nCAR-{i},{i + 1}\n")
    entrada = {"url": "release-github://exemplo/raiz/dados-privados/raiz_PA.tar.gz", "sha256": "a" * 64}
    inteira = croissant_uf(tmp_path, "PA", entrada, escopo="privado")
    monkeypatch.setattr(metadados, "LIMITE_CAMPOS", 4)
    em_lotes = croissant_uf(tmp_path, "PA", entrada, escopo="privado")
    assert em_lotes == inteira
    for registro in em_lotes["recordSet"]:
        origem = "arquivos/" + registro["@id"] + ".csv"
        assert {campo["source"]["fileObject"]["@id"] for campo in registro["field"]} == {origem}


def test_grafias_equivalentes_nao_escondem_definicao_duplicada(monkeypatch):
    ficha = _ficha_plana()
    ficha["distribution"][-1]["@id"] = "./a"
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("colisão deve falhar antes do RDF"))
    with pytest.raises(ValueError, match="definido mais de uma vez"):
        validar(ficha)


def test_contexto_remoto_dentro_de_termo_tambem_e_recusado(monkeypatch):
    ficha = _ficha_plana()
    ficha["@context"]["extra"] = {
        "@id": "sc:extra",
        "@context": "release-github://exemplo/raiz/dados-privados/contexto.json",
    }
    ficha["extra"] = {"name": "valor"}
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("o fallback não pode buscar contexto remoto"))
    with pytest.raises(ValueError, match="contexto remoto"):
        validar(ficha)


def test_tipo_em_lista_e_json_literal_usam_fallback_pequeno_sem_falsa_colisao():
    ficha = _ficha_plana()
    ficha["distribution"][0]["@type"] = ["cr:FileObject"]
    ficha["examples"] = [{"@id": "literal", "value": "a"}, {"@id": "literal", "value": "b"}]
    validar(ficha)


def test_lote_inclui_toda_cadeia_de_containers(monkeypatch):
    from raiz import metadados

    ficha = _ficha_plana()
    interno = copy.deepcopy(ficha["distribution"][0])
    interno.update(
        {"@id": "interno", "name": "interno.tar", "contentUrl": "interno.tar", "containedIn": {"@id": "arquivo"}}
    )
    ficha["distribution"].append(interno)
    ficha["distribution"][1]["containedIn"] = {"@id": "interno"}
    chamadas = []
    original = mlc.Dataset
    monkeypatch.setattr(metadados, "LIMITE_CAMPOS", 3)
    monkeypatch.setattr(mlc, "Dataset", lambda p: chamadas.append(copy.deepcopy(p)) or original(p))
    validar(ficha)
    parte_a = next(p for p in chamadas if any(r["@id"] == "registros_a" for r in p["recordSet"]))
    assert {d["@id"] for d in parte_a["distribution"]} == {"arquivo", "interno", "a"}


def test_erro_de_parser_no_filho_nao_expoe_stdout_stderr_ou_valores(tmp_path, capfd):
    from raiz import metadados

    nome = "imoveis_1504950.csv"
    (tmp_path / nome).write_text("cod_imovel,ha\nCAR-A,3,NAO_PUBLICAR_VALOR\n")
    with pytest.raises(ValueError, match="baker não descreveu") as erro:
        metadados._executar_lote(
            "baker", {"pasta": str(tmp_path), "arquivos": [nome], "nome": "teste", "descricao": "teste"}, isolado=True
        )
    saida = capfd.readouterr()
    assert "NAO_PUBLICAR_VALOR" not in str(erro.value) + saida.out + saida.err


def test_contexto_aninhado_nao_pode_mudar_json_literal_para_buscar_rede(monkeypatch):
    ficha = _ficha_plana()
    ficha["extra"] = {
        "@context": {"examples": "https://schema.org/examples"},
        "examples": {"@context": "release-github://exemplo/raiz/dados-privados/contexto.json", "name": "valor"},
    }
    monkeypatch.setattr(mlc, "Dataset", lambda *a, **kw: pytest.fail("contextos dinâmicos não chegam ao leitor"))
    with pytest.raises(ValueError, match="contexto remoto ou aninhado"):
        validar(ficha)


def test_ficha_privada_declara_acesso_e_preserva_repositorio_do_codigo():
    url = "release-github://raiz/arquivo-restrito/dados/raiz_PA.tar.gz"
    ficha = ficha_arquivo("raiz_PA.tar.gz", url, "a" * 64, escopo="privado")
    validar(ficha)
    assert ficha["distribution"][0]["contentUrl"] == url
    assert ficha["isAccessibleForFree"] is False
    assert "servidor resolve o asset pela API autenticada" in ficha["conditionsOfAccess"]
    assert ficha["citation"] == "https://github.com/bernardoemmel/Raiz/blob/main/NOTICE.md"
    assert "arquivo-restrito" not in ficha["creator"]["url"]


@pytest.mark.parametrize(
    ("escopo", "url"),
    [
        ("privado", "https://github.com/bernardoemmel/Raiz/releases/download/dados/raiz_PA.tar.gz"),
        ("publico_basico", "release-github://bernardoemmel/Raiz/dados-privados/raiz_PA.tar.gz"),
        ("privado", "release-github://segredo@bernardoemmel/Raiz/dados-privados/a.csv"),
        ("privado", "release-github://bernardoemmel/Raiz/dados-privados/a.csv?token=NAO_PUBLICAR"),
        ("publico_basico", "https://github.com/bernardoemmel/Raiz/releases/download/dados/a.csv?token=NAO_PUBLICAR"),
        ("desconhecido", "https://example.org/a.csv"),
    ],
)
def test_escopo_e_credenciais_nao_sao_inferidos_de_url(escopo, url):
    with pytest.raises(ValueError) as erro:
        ficha_arquivo("a.csv", url, "a" * 64, escopo=escopo)
    assert "NAO_PUBLICAR" not in str(erro.value)
    assert "segredo@" not in str(erro.value)


@pytest.mark.parametrize(
    "referencia",
    [
        "release-github://bernardoemmel/Raiz/dados-privados/croissant_PA.json",
        "https://github.com/bernardoemmel/Raiz/releases/download/dados-privados/croissant_PA.json",
        "https://github.com/outro/repo/releases/download/dados/croissant_PA.json",
        "https://github.com/bernardoemmel/Raiz/releases/download/dados/croissant_PA.json?token=segredo",
    ],
)
def test_catalogo_recusa_referencia_de_outro_destino_ou_escopo(referencia):
    with pytest.raises(ValueError):
        croissant_release({"estados": {"PA": {"croissant": referencia}}}, escopo="publico_basico")


def test_esquema_financeiro_nao_vira_ficha_publica_por_nao_ter_cpf(tmp_path, monkeypatch):
    from raiz import metadados

    (tmp_path / "desenvolvedor_1504950.csv").write_text("cod_imovel,tir_projeto_pct_p50\nCAR,12\n")
    monkeypatch.setattr(metadados, "_executar_lote", lambda *a, **k: pytest.fail("recusar antes de ler valores"))
    with pytest.raises(ValueError, match="públic"):
        croissant_uf(
            tmp_path,
            "PA",
            {
                "url": "https://github.com/bernardoemmel/Raiz/releases/download/dados/raiz_PA.tar.gz",
                "sha256": "a" * 64,
            },
            escopo="publico_basico",
        )


@pytest.fixture
def ficha_basica(tmp_path):
    (tmp_path / "imoveis_basicos_1504950.csv").write_text(
        "cod_imovel,cod_ibge,municipio,uf,situacao_basica\nPA-1504950-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA,1504950,Teste,PA,apto\n"
    )
    (tmp_path / "resumo_PA.csv").write_text("cod_ibge,municipio,imoveis,ha_carbono\n1504950,Teste,8,12.5\n")
    (tmp_path / "sem_imoveis_PA.csv").write_text("cod_ibge,municipio,verificado_em\n1504951,Vazio,2026-11-12\n")
    return croissant_uf(
        tmp_path,
        "PA",
        {
            "url": "https://github.com/bernardoemmel/Raiz/releases/download/dados/raiz_PA.tar.gz",
            "sha256": "a" * 64,
            "tamanho": 123,
            "versao": "1234567890abcdef",
            "atualizado_em": "2026-11-12T00:00:00+00:00",
        },
        escopo="publico_basico",
    )


def test_guard_publico_aceita_ficha_completa_e_formatos_permitidos(ficha_basica):
    from raiz.metadados import validar_ficha_publica

    def aceitar(nome, ficha):
        validar(ficha)
        validar_ficha_publica(nome, json.dumps(ficha).encode())

    aceitar("croissant_PA.json", ficha_basica)
    assert ficha_basica["isAccessibleForFree"] is True
    assert "AAAA" not in json.dumps(ficha_basica)
    fichas = {
        "raiz_PA.tar.gz": {
            "url": "https://github.com/bernardoemmel/Raiz/releases/download/dados/croissant_PA.json",
            "sha256": "c" * 64,
        }
    }
    for asset, nome, mime in [
        ("raiz_geo_PA.tar.gz", "croissant_raiz_geo_PA.tar.gz.json", ["application/x-tar", "application/gzip"]),
        ("estados.json", "croissant_estados.json", "application/json"),
        ("cartao_modelo.md", "croissant_cartao_modelo.md.json", "text/markdown"),
    ]:
        url = f"https://github.com/bernardoemmel/Raiz/releases/download/dados/{asset}"
        ficha = ficha_arquivo(asset, url, "b" * 64, formato=mime, escopo="publico_basico")
        aceitar(nome, ficha)
        fichas[asset] = {"url": url.rsplit("/", 1)[0] + "/" + nome, "sha256": "d" * 64}
    aceitar("croissant.json", croissant_release({"fichas": fichas}, escopo="publico_basico"))


@pytest.mark.parametrize(
    "ataque", ["texto", "exemplo", "contexto", "draft", "campo_financeiro", "origem", "duplicado", "bool"]
)
def test_guard_publico_recusa_reexposicao_em_metadados(ficha_basica, ataque):
    from raiz.metadados import validar_ficha_publica

    ficha = copy.deepcopy(ficha_basica)
    if ataque == "texto":
        ficha["description"] = "NAO_PUBLICAR_DADOS_PRIVADOS"
    elif ataque == "exemplo":
        ficha["recordSet"][0]["field"][0]["examples"] = ["NAO_PUBLICAR"]
    elif ataque == "contexto":
        ficha["@context"]["campo"] = "https://example.org/privado"
    elif ataque == "draft":
        ficha["distribution"][0]["contentUrl"] = ficha["url"].replace("/dados/", "/dados-privados/")
    elif ataque == "campo_financeiro":
        ficha["recordSet"][0]["field"][0]["name"] = "tir_projeto_pct_p50"
    elif ataque == "origem":
        ficha["recordSet"][0]["field"][0]["source"]["fileObject"]["@id"] = "arquivos/desenvolvedor_1504950.csv"
    elif ataque == "duplicado":
        ficha["recordSet"].append(copy.deepcopy(ficha["recordSet"][0]))
    else:
        ficha["distribution"][0]["contentSize"] = True
    with pytest.raises(ValueError, match="público") as erro:
        validar_ficha_publica("croissant_PA.json", json.dumps(ficha).encode())
    assert "NAO_PUBLICAR" not in str(erro.value)


def test_guard_publico_nao_infere_destino_nem_libera_assets_pagos():
    from raiz.metadados import validar_ficha_publica

    for nome in (
        "quantis_PA.parquet",
        "tasks_PA.json",
        "modelos_PA.json",
        "hub_PA.tar.gz",
        "cadt_lotes.json",
        "URTX.kml",
    ):
        ficha = ficha_arquivo(
            nome,
            f"https://github.com/bernardoemmel/Raiz/releases/download/dados/{nome}",
            "b" * 64,
            escopo="publico_basico",
        )
        with pytest.raises(ValueError, match="público"):
            validar_ficha_publica(f"croissant_{nome}.json", json.dumps(ficha).encode())
    ficha = ficha_arquivo(
        "estados.json",
        "https://github.com/outro/repo/releases/download/dados/estados.json",
        "b" * 64,
        escopo="publico_basico",
        formato="application/json",
    )
    bruto = json.dumps(ficha).encode()
    with pytest.raises(ValueError, match="público"):
        validar_ficha_publica("croissant_estados.json", bruto)
    validar_ficha_publica("croissant_estados.json", bruto, repo="outro/repo")
    with pytest.raises(ValueError, match="público"):
        validar_ficha_publica("croissant_estados.json", bruto[:-1] + b',"recordSet":[]}')


def test_tar_basico_sem_csv_exige_fingerprint_do_pacote_vazio():
    import gzip
    import io

    from raiz.metadados import TAR_VAZIO_SHA256, validar_ficha_publica

    pacote = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=pacote, mode="wb", mtime=0, filename="", compresslevel=6) as gz,
        tarfile.open(fileobj=gz, mode="w"),
    ):
        pass
    assert len(pacote.getvalue()) == 45
    assert hashlib.sha256(pacote.getvalue()).hexdigest() == TAR_VAZIO_SHA256
    ficha = ficha_arquivo(
        "raiz_AM.tar.gz",
        "https://github.com/bernardoemmel/Raiz/releases/download/dados/raiz_AM.tar.gz",
        TAR_VAZIO_SHA256,
        45,
        escopo="publico_basico",
        formato=["application/x-tar", "application/gzip"],
    )
    validar(ficha)
    validar_ficha_publica("croissant_AM.json", json.dumps(ficha).encode())
    for campo, valor in (("sha256", "a" * 64), ("contentSize", "46")):
        invalida = copy.deepcopy(ficha)
        invalida["distribution"][0][campo] = valor
        with pytest.raises(ValueError, match="público"):
            validar_ficha_publica("croissant_AM.json", json.dumps(invalida).encode())
