import argparse
import datetime as dt
import hashlib
import importlib.util
import io
import json
import tarfile
from types import SimpleNamespace

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from raiz import RAIZ_REPO, cadt
from raiz import metadados as M
from raiz import quantis as Q
from raiz import restauracao as R
from raiz.executor.armazem import ArmazemRelease
from scripts import verificar_release_dados as V

CODIGO = RAIZ_REPO


def _pacote_cadt(tmp_path, versao, tarefa="desenvolvedor-teste", *, arquivos=None, alterar_manifesto=None):
    if arquivos is None:
        arquivos = {
            "desenvolvedor_1504950.csv": (
                "restauracao_versao,restauracao_cenario,credito_liquido_tco2_contrato,"
                "credito_liquido_tco2_ha_contrato_p50,credito_liquido_tco2_ha_horizonte\n"
                f"{versao},central_r11,2000000.0,100.0,200.0\n"
            ).encode()
        }
    manifesto = {
        nome: {"tarefa": "desenvolvedor", "versao": tarefa, "sha256": hashlib.sha256(bruto).hexdigest()}
        for nome, bruto in arquivos.items()
    }
    if alterar_manifesto:
        alterar_manifesto(manifesto)
    bruto_manifesto = json.dumps(manifesto).encode()
    caminho = tmp_path / "raiz_PA.tar.gz"
    with tarfile.open(caminho, "w:gz") as tar:
        for nome, bruto in [*arquivos.items(), ("_versoes.json", bruto_manifesto)]:
            membro = tarfile.TarInfo("PA/" + nome)
            membro.size = len(bruto)
            tar.addfile(membro, io.BytesIO(bruto))
    return caminho, V.sha_arquivo(caminho), hashlib.sha256(bruto_manifesto).hexdigest()


def _argumentos_cadt(dado, pacote):
    caminho, digest, prov = pacote
    url = "release-github://bernardoemmel/Raiz/dados-privados/cadt_lotes.json"
    url_pacote = url.rsplit("/", 1)[0] + "/raiz_PA.tar.gz"
    dado["metadados"]["entradas"] = {"pacote_sha256": digest, "proveniencia_sha256": prov, "url": url_pacote}
    entrada = {"proveniencia_sha256": prov, "cadt": dado}
    return (dado, "PA", entrada, digest, url_pacote, url), {"pacote": caminho}


def _caso_cadt_historico(tmp_path, versao=cadt.HISTORICA_2026B, *, credito=1234567.0):
    from raiz.regras import historico

    r, prova = historico.carregar(versao)
    c = historico.cenario("central_r11", r)
    legado = versao == cadt.HISTORICA_2026B
    resumo = {
        "data": "2026-11-12",
        "cenario": "central_r11",
        "versao_premissas": versao,
        "versao_otimizador": "lote-teste",
        "cronograma_lote": cadt._cronograma_2026b(credito, c, r) if legado else R.cronograma_lote(credito, c, r),
    }
    if legado:
        resumo.update(versao_premissas_selecao="premissas-teste", versao_metodo_cronograma=cadt.METODO_2026B)
    url = "release-github://bernardoemmel/Raiz/dados-privados/cadt_lotes.json"
    dado = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2027-01-01", url_catalogo=url, r=r, c=c)
    dado["metadados"].update(prova)
    dado["metadados"].update(previsoes_individuais_recalculadas=False, comercializacao={"situacao": "pendente"})
    if legado:
        dado["metadados"].update(
            versao_tarefa_fonte_verificada=prova["versao_tarefa_referencia"],
            arquivos_fonte_verificados=1,
            evidencia_tarefa="metadados_do_arquivo_e_sha256_dos_bytes",
        )
    return _argumentos_cadt(dado, _pacote_cadt(tmp_path, versao, prova["versao_tarefa_referencia"]))


def test_cache_por_hash_sem_novo_download(tmp_path):
    dados, chamadas = b"conteudo de teste", []
    digest = hashlib.sha256(dados).hexdigest()

    def resposta(req):
        assert req.method == "GET"
        chamadas.append(req.url.path)
        return httpx.Response(200, content=dados)

    a = ArmazemRelease(token="credencial-teste", cliente=httpx.Client(transport=httpx.MockTransport(resposta)))
    cache = V.Cache(tmp_path)
    asset = {"name": "arquivo.csv", "id": 7, "size": len(dados), "digest": "sha256:" + digest}
    caminho, _, reutilizado = cache.obter(a, asset)
    assert not reutilizado
    assert cache.obter(a, asset)[2] and len(chamadas) == 1
    caminho.write_bytes(b"X" * len(dados))
    assert not cache.obter(a, asset)[2] and len(chamadas) == 2


def test_download_privado_por_id_e_visibilidade_obrigatoria(tmp_path):
    dados = b"arquivo privado de teste"
    digest = hashlib.sha256(dados).hexdigest()
    paths = []
    draft = {"valor": True}

    def resposta(req):
        assert req.method == "GET"
        assert req.headers["Authorization"] == "Bearer credencial-falsa"
        paths.append(req.url.path)
        if req.url.path.endswith("/releases/tags/dados-privados"):
            return httpx.Response(200, json={"id": 9, "draft": draft["valor"]})
        if req.url.path.endswith("/releases/assets/42"):
            return httpx.Response(200, content=dados)
        if req.url.path == "/repos/bernardoemmel/Raiz":
            return httpx.Response(200, json={"private": False})
        raise AssertionError("rota inesperada")

    a = ArmazemRelease(
        "bernardoemmel/Raiz",
        "dados-privados",
        tmp_path / "espelho",
        token="credencial-falsa",
        privado=True,
        cliente=httpx.Client(transport=httpx.MockTransport(resposta)),
    )
    asset = {
        "name": "arquivo.json",
        "id": 42,
        "size": len(dados),
        "digest": "sha256:" + digest,
        "browser_download_url": "https://nao-deve-ser-usado.invalid/arquivo.json",
    }
    assert V.Cache(tmp_path / "cache").obter(a, asset)[1] == digest
    assert paths[-1].endswith("/releases/assets/42")
    draft["valor"] = False
    with pytest.raises(PermissionError):
        a._exigir_privado()


def test_contidos_privados_aceitam_manifesto_e_recusam_hash_errado(tmp_path):
    arquivo = b"a,b\n1,2\n"
    versoes = b"{}"
    caminho = tmp_path / "a.tar.gz"
    with tarfile.open(caminho, "w:gz") as tar:
        for nome, dados in [("PA/tabela.csv", arquivo), ("PA/_versoes.json", versoes)]:
            info = tarfile.TarInfo(nome)
            info.size = len(dados)
            tar.addfile(info, io.BytesIO(dados))
    ficha = {
        "isAccessibleForFree": False,
        "distribution": [
            {
                "@type": "cr:FileObject",
                "contentUrl": "PA/tabela.csv",
                "containedIn": {"@id": "arquivo"},
                "sha256": hashlib.sha256(arquivo).hexdigest(),
                "contentSize": str(len(arquivo)),
            }
        ],
    }
    assert V.validar_contidos(ficha, caminho, hashlib.sha256(versoes).hexdigest()) == 1
    with pytest.raises(V.FalhaSegura, match="proveniencia"):
        V.validar_contidos(ficha, caminho, "0" * 64)
    with pytest.raises(V.FalhaSegura, match="membro_tar_sem_ficha"):
        V.validar_contidos({"isAccessibleForFree": False, "distribution": []}, caminho, uf="PA")
    ficha["distribution"] *= 2
    with pytest.raises(V.FalhaSegura, match="descrito_mais_de_uma_vez"):
        V.validar_contidos(ficha, caminho, hashlib.sha256(versoes).hexdigest())


@pytest.fixture
def quantis_validos(tmp_path):
    mid, modelo = Q._modelo("flag", "regra-1", "flag-tarefa-1", "")
    data = dt.date(2026, 11, 12)
    linhas = [
        {
            "reference_date": data,
            "location": "PA-1504950-ABC",
            "target": "flag_tco2_ano",
            "output_type": "quantile",
            "output_type_id": q,
            "value": v,
            "model_id": mid,
            "source_file": "flag_1504950.csv",
            **{k: modelo[k] for k in ("model_version", "source_model_version", "task_version", "quantile_method")},
        }
        for q, v in ((0.1, 1.0), (0.5, 2.0), (0.9, 3.0))
    ]
    meta = {
        "modelos": {mid: modelo},
        "exporter_version": Q.EXPORTADOR_VERSAO,
        "reference_date_basis": Q.BASE_DATA,
        "fontes": [
            {
                "arquivo": "flag_1504950.csv",
                "task_version": "flag-tarefa-1",
                "reference_date": data.isoformat(),
                "source_execution_time": data.isoformat(),
                "sha256": "f" * 64,
            }
        ],
    }
    caminho = tmp_path / "q.parquet"
    pq.write_table(pa.Table.from_pylist(linhas, schema=Q.ESQUEMA_PUBLICO), caminho)
    entrada = {"quantis": {"linhas": 3, "modelos": [mid], "diagnosticos": 0}}
    auxiliares = {
        "schema": Q.esquema_modelos(),
        "diagnosticos": [],
        "tasks": Q.tasks([data.isoformat()], [linhas[0]["location"]]),
        "tasks_globais": Q.tasks([data.isoformat()], [linhas[0]["location"]]),
        "ficha_pacote": {
            "distribution": [
                {
                    "@type": "cr:FileObject",
                    "@id": "arquivo",
                    "contentUrl": "release-github://exemplo/raiz/dados-privados/a",
                },
                {"@type": "cr:FileSet", "@id": "flag", "containedIn": {"@id": "arquivo"}, "includes": "PA/flag_*.csv"},
                {
                    "@type": "cr:FileObject",
                    "containedIn": {"@id": "arquivo"},
                    "contentUrl": "PA/flag_1504950.csv",
                    "sha256": "f" * 64,
                },
            ]
        },
    }
    return caminho, meta, entrada, auxiliares


def test_quantis_agregados_versoes_e_ordem(quantis_validos):
    caminho, meta, entrada, auxiliares = quantis_validos
    assert V.validar_quantis(caminho, "PA", meta, meta, entrada, auxiliares=auxiliares)["grupos"] == 1
    linhas = pq.read_table(caminho).to_pylist()
    linhas[1]["value"] = 9.0
    pq.write_table(pa.Table.from_pylist(linhas, schema=Q.ESQUEMA_PUBLICO), caminho)
    with pytest.raises(V.FalhaSegura, match="desordenados"):
        V.validar_quantis(caminho, "PA", meta, meta, entrada, auxiliares=auxiliares)


@pytest.mark.parametrize("defeito", ["so_fileset", "sem_pacote", "hash", "url", "duplicada"])
def test_quantis_exigem_fileobject_fonte_unico_e_valido(quantis_validos, defeito):
    caminho, meta, entrada, auxiliares = quantis_validos
    distribuicoes = auxiliares["ficha_pacote"]["distribution"]
    fonte = distribuicoes[-1]
    if defeito == "so_fileset":
        fonte["@type"] = "cr:FileSet"
    elif defeito == "sem_pacote":
        del fonte["containedIn"]
    elif defeito == "hash":
        fonte["sha256"] = "nao_e_hash"
    elif defeito == "url":
        fonte["contentUrl"] = "../PA/flag_1504950.csv"
    else:
        distribuicoes.append(dict(fonte))
    with pytest.raises(V.FalhaSegura):
        V.validar_quantis(caminho, "PA", meta, meta, entrada, auxiliares=auxiliares)


@pytest.mark.parametrize("defeito", ["schema", "diagnosticos", "fonte", "tasks", "tasks_globais", "modelos"])
def test_quantis_recusam_auxiliares_incoerentes(quantis_validos, defeito):
    caminho, meta, entrada, auxiliares = quantis_validos
    if defeito == "schema":
        auxiliares["schema"] = {}
    elif defeito == "diagnosticos":
        auxiliares["diagnosticos"] = [{"codigo": "exemplo_sintetico"}]
    elif defeito == "fonte":
        meta["fontes"][0]["sha256"] = "b" * 64
    elif defeito == "modelos":
        entrada["quantis"]["modelos"] = []
    else:
        auxiliares[defeito] = Q.tasks()
    with pytest.raises(V.FalhaSegura):
        V.validar_quantis(caminho, "PA", meta, meta, entrada, auxiliares=auxiliares)


def test_tasks_globais_podem_preservar_datas_e_locais_historicos(quantis_validos):
    caminho, meta, entrada, auxiliares = quantis_validos
    auxiliares["tasks_globais"] = Q.combinar_tasks(
        [auxiliares["tasks"], Q.tasks(["2025-01-01"], ["SP-3550308-EXEMPLO"])]
    )
    assert V.validar_quantis(caminho, "PA", meta, meta, entrada, auxiliares=auxiliares)["linhas"] == 3


def test_quantis_vazios_exigem_modelos_tasks_e_contagens_vazios(tmp_path):
    caminho = tmp_path / "vazio.parquet"
    pq.write_table(pa.Table.from_pylist([], schema=Q.ESQUEMA_PUBLICO), caminho)
    meta = {
        "exporter_version": Q.EXPORTADOR_VERSAO,
        "reference_date_basis": Q.BASE_DATA,
        "modelos": {},
        "fontes": [],
    }
    entrada = {"quantis": {"linhas": 0, "modelos": [], "diagnosticos": 0}}
    auxiliares = {
        "schema": Q.esquema_modelos(),
        "diagnosticos": [],
        "tasks": Q.tasks(),
        "tasks_globais": Q.tasks(),
        "ficha_pacote": {"distribution": []},
    }
    assert V.validar_quantis(caminho, "PA", meta, meta, entrada, auxiliares=auxiliares)["grupos"] == 0


def test_cadt_real_curva_25_anos_e_sem_identificacao(tmp_path):
    r = R.regra()
    c = R.cenario("central_r11", r=r)
    resumo = {
        "data": "2026-11-12",
        "cenario": "central_r11",
        "versao_premissas": r["versao_completa"],
        "versao_otimizador": "lote-teste",
        "cronograma_lote": R.cronograma_lote(1000.0, c, r),
    }
    url = "release-github://bernardoemmel/Raiz/dados-privados/cadt_lotes.json"
    dado = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2028-02-29", url_catalogo=url, r=r, c=c)
    dado["metadados"].update(
        previsoes_individuais_recalculadas=False,
        comercializacao={"situacao": "pendente"},
    )
    args, kwargs = _argumentos_cadt(dado, _pacote_cadt(tmp_path, r["versao_completa"]))
    assert V.validar_cadt(*args, **kwargs)["anos"] == 25
    with pytest.raises(V.FalhaSegura, match="diverge_indice"):
        V.validar_cadt(*args[:2], {**args[2], "cadt": {}}, *args[3:], **kwargs)
    dado["extra"] = {"location": "PA-1504950-ABC"}
    with pytest.raises(V.FalhaSegura, match="identificacao"):
        V.validar_cadt(*args, **kwargs)


def test_atestacao_exige_nome_hash_workflow_e_runner_hospedado(tmp_path, monkeypatch):
    argumentos = []

    def rodar(cmd, **kw):
        argumentos.extend(cmd)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "verificationResult": {
                            "statement": {
                                "predicateType": "https://slsa.dev/provenance/v1",
                                "subject": [{"name": "a.json", "digest": {"sha256": "a" * 64}}],
                            }
                        }
                    }
                ]
            ).encode(),
        )

    monkeypatch.setattr(V.subprocess, "run", rodar)
    assert V.atestacao(tmp_path / "a", "a.json", "a" * 64, "gh")["verificadas"] == 1
    assert "--deny-self-hosted-runners" in argumentos and V.WORKFLOW in argumentos
    with pytest.raises(V.FalhaSegura, match="subject"):
        V.atestacao(tmp_path / "a", "outro.json", "a" * 64, "gh")


def test_escopo_publico_inteiro_com_api_falsa_so_get(tmp_path, monkeypatch):
    repo, tag = "bernardoemmel/Raiz", "dados"
    base = f"https://github.com/{repo}/releases/download/{tag}/"
    indice = {"repo": repo, "tag": tag, "escopo": "publico_basico", "versao_publicacao": 1, "estados": {}}
    dados = {
        "estados.json": json.dumps(indice).encode(),
        "cartao_modelo.md": (CODIGO / "docs/modelo/cartao.md").read_bytes(),
    }
    refs = {}
    for nome, conteudo in list(dados.items()):
        nome_ficha = "croissant_estados.json" if nome == "estados.json" else "croissant_cartao_modelo.md.json"
        ficha = M.ficha_arquivo(
            nome,
            base + nome,
            hashlib.sha256(conteudo).hexdigest(),
            len(conteudo),
            escopo="publico_basico",
            formato="application/json" if nome.endswith(".json") else "text/markdown",
        )
        dados[nome_ficha] = json.dumps(ficha, ensure_ascii=False, indent=2).encode()
        refs[nome] = {
            "url": base + nome_ficha,
            "sha256": hashlib.sha256(dados[nome_ficha]).hexdigest(),
            "tamanho": len(dados[nome_ficha]),
        }
    dados["croissant.json"] = json.dumps(
        M.croissant_release({"fichas": refs}, repo, tag, escopo="publico_basico"), ensure_ascii=False, indent=2
    ).encode()
    ativos = [
        {
            "id": i,
            "name": n,
            "size": len(b),
            "digest": "sha256:" + hashlib.sha256(b).hexdigest(),
            "updated_at": "2026-11-12T00:00:00Z",
        }
        for i, (n, b) in enumerate(dados.items(), 1)
    ]
    por_id = {str(a["id"]): dados[a["name"]] for a in ativos}

    def responder(req):
        assert req.method == "GET"
        path = req.url.path
        if path.endswith("/releases/tags/dados"):
            return httpx.Response(200, json={"id": 1, "draft": False})
        if path.endswith("/releases/1/assets"):
            return httpx.Response(200, json=ativos)
        if "/releases/assets/" in path:
            return httpx.Response(200, content=por_id[path.rsplit("/", 1)[-1]])
        if path == f"/repos/{repo}":
            return httpx.Response(200, json={"private": False})
        raise AssertionError("rota inesperada")

    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: client(transport=httpx.MockTransport(responder), **kw))
    monkeypatch.setenv("GH_TOKEN", "teste")
    spec = importlib.util.spec_from_file_location("publicador_teste", CODIGO / "scripts/publicar_metadados.py")
    publicador = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publicador)
    args = argparse.Namespace(
        repo_publico=repo, tag_publica=tag, sem_atestacao=True, gh="gh", relatorio=tmp_path / "relatorio.json"
    )
    relatorio = {"escopos": {}}
    V.executar_escopo(args, "publico", V.Cache(tmp_path / "cache"), relatorio, publicador, M)
    assert relatorio["escopos"]["publico"]["erros"] == []
    assert relatorio["escopos"]["publico"]["integridade_ok"]


def test_verificador_confere_metodo2026b_e_curva_sem_depender_do_adaptador(tmp_path):
    args, kwargs = _caso_cadt_historico(tmp_path)
    dado = args[0]
    assert V.validar_cadt(*args, **kwargs)["anos"] == 25
    dado["metadados"]["metodo_cronograma"] = "inventado"
    with pytest.raises(V.FalhaSegura, match="metodo_historico"):
        V.validar_cadt(*args, **kwargs)
    dado["metadados"]["metodo_cronograma"] = cadt.METODO_2026B
    # Conserva total, marcos e identidade: ainda assim a distribuição anual
    # adulterada deve falhar pela curva racional independente do gerador.
    es = dado["projeto"]["estimations"]
    es[2]["unitCount"] += 10
    es[3]["unitCount"] -= 10
    with pytest.raises(V.FalhaSegura, match="curva_historica"):
        V.validar_cadt(*args, **kwargs)


def test_cadt_recusa_curva_adulterada_com_versao_falsa_e_identidade_recalculada(tmp_path):
    args, kwargs = _caso_cadt_historico(tmp_path)
    dado, _, _, _, _, url = args
    m, p = dado["metadados"], dado["projeto"]
    p["estimations"][2]["unitCount"] += 10
    p["estimations"][3]["unitCount"] -= 10
    m["versoes"]["versao_premissas"] = "restauracao-inventada"
    del m["metodo_cronograma"], m["versoes"]["versao_metodo_cronograma"]
    identidade = {
        "uf": "PA",
        "cenario": m["cenario"],
        "inicio": m["data_inicio_cenario"],
        "versoes": m["versoes"],
        "exportador": m["versao_exportador"],
    }
    h = hashlib.sha256(json.dumps(identidade, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    p["projectId"] = p["originProjectId"] = f"raiz-cenario-PA-{h}"
    p["projectLink"] = url + "#" + p["projectId"]
    with pytest.raises(V.FalhaSegura, match="versao_diverge_fonte"):
        V.validar_cadt(*args, **kwargs)


@pytest.mark.parametrize("credito", [100.25, True, float("nan"), float("inf"), 0, -1])
def test_cadt_total_agregado_de_fontes_inteiras_exige_inteiro_finito_positivo(tmp_path, credito):
    # O caso fracionário tem curva, marcos e arredondamentos coerentes; ainda
    # assim não pode ser soma de um subconjunto dos totais inteiros da fonte.
    args, kwargs = _caso_cadt_historico(tmp_path, credito=100.25 if credito == 100.25 else 1.0)
    args[0]["metadados"]["credito_contrato_p50"] = credito
    with pytest.raises(V.FalhaSegura, match="cadt_credito_invalido"):
        V.validar_cadt(*args, **kwargs)


@pytest.mark.parametrize("defeito", ["contagem", "prova", "tarefa", "sem_pacote", "pacote_hash", "proveniencia_hash"])
def test_cadt_confere_prova_contra_pacote_real(tmp_path, defeito):
    args, kwargs = _caso_cadt_historico(tmp_path)
    m = args[0]["metadados"]
    if defeito == "contagem":
        m["arquivos_fonte_verificados"] = 999999
    elif defeito == "prova":
        m["regra_source_codigo_sha256"] = "0" * 64
    elif defeito == "tarefa":
        pacote = _pacote_cadt(tmp_path, cadt.HISTORICA_2026B, "adotado-atual")
        args, kwargs = _argumentos_cadt(args[0], pacote)
    elif defeito == "sem_pacote":
        kwargs = {}
    elif defeito == "pacote_hash":
        kwargs["pacote"].write_bytes(kwargs["pacote"].read_bytes() + b"adulterado")
    else:
        m["entradas"]["proveniencia_sha256"] = args[2]["proveniencia_sha256"] = "0" * 64
    with pytest.raises(V.FalhaSegura):
        V.validar_cadt(*args, **kwargs)


def test_cadt_2026c_original_continua_suportado(tmp_path):
    args, kwargs = _caso_cadt_historico(tmp_path, "restauracao-2026c+421970fd")
    assert V.validar_cadt(*args, **kwargs)["anos"] == 25
    args[0]["metadados"]["regra_source_perfil"] = "separado_2026b"
    with pytest.raises(V.FalhaSegura, match="prova_historica"):
        V.validar_cadt(*args, **kwargs)


def test_cadt_regra_atual_nao_pode_alegar_prova_historica(tmp_path):
    args, _ = _caso_cadt_historico(tmp_path)
    dado = args[0]
    dado["metadados"]["versoes"]["versao_premissas"] = R.versao()
    args, kwargs = _argumentos_cadt(dado, _pacote_cadt(tmp_path, R.versao()))
    with pytest.raises(V.FalhaSegura, match="prova_historica_contraditoria"):
        V.validar_cadt(*args, **kwargs)


def test_cadt_diagnostico_com_prova_tambem_confere_a_fonte(tmp_path):
    args, kwargs = _caso_cadt_historico(tmp_path)
    dado = args[0]
    dado["projeto"] = None
    dado["diagnosticos"] = [{"codigo": "sem_lote_elegivel"}]
    assert V.validar_cadt(*args, **kwargs)["projeto"] is False
    dado["metadados"]["versoes"] = {}
    with pytest.raises(V.FalhaSegura, match="versao_diverge_fonte"):
        V.validar_cadt(*args, **kwargs)


@pytest.mark.parametrize("valor", ["", "NaN", "Infinity", "-1", "123.00000000000001", "1e9999"])
def test_origem_cadt_recusa_total_invalido_sem_expor_linha(tmp_path, valor):
    arquivo = (
        "restauracao_versao,restauracao_cenario,credito_liquido_tco2_contrato,ignorado\n"
        f"{cadt.HISTORICA_2026B},central_r11,{valor},NAO_PUBLICAR\n"
    ).encode()
    p, digest, prov = _pacote_cadt(tmp_path, cadt.HISTORICA_2026B, arquivos={"desenvolvedor_1504950.csv": arquivo})
    with pytest.raises(V.FalhaSegura) as erro:
        V._origem_cadt(p, "PA", digest, prov)
    assert "NAO_PUBLICAR" not in str(erro.value) and "NAO_PUBLICAR" not in repr(erro.value)


@pytest.mark.parametrize("defeito", ["hash_csv", "coluna_ausente", "coluna_duplicada", "linha_curta", "cenario_misto"])
def test_origem_cadt_recusa_csv_e_manifesto_incoerentes(tmp_path, defeito):
    cabecalho = "restauracao_versao,restauracao_cenario,credito_liquido_tco2_contrato"
    linha = f"{cadt.HISTORICA_2026B},central_r11,123.0"
    cabecalho += ",credito_liquido_tco2_ha_contrato_p50,credito_liquido_tco2_ha_horizonte"
    linha += ",100.0,200.0"
    extra = ""
    if defeito == "coluna_ausente":
        cabecalho = cabecalho.replace("credito_liquido_tco2_contrato", "outro")
    elif defeito == "coluna_duplicada":
        cabecalho += ",restauracao_versao"
        linha += "," + cadt.HISTORICA_2026B
    elif defeito == "linha_curta":
        linha = linha.rsplit(",", 1)[0]
    elif defeito == "cenario_misto":
        extra = linha.replace("central_r11", "alternativo") + "\n"
    arquivo = (cabecalho + "\n" + linha + "\n" + extra).encode()

    def alterar(m):
        if defeito == "hash_csv":
            m["desenvolvedor_1504950.csv"]["sha256"] = "0" * 64

    p, digest, prov = _pacote_cadt(
        tmp_path, cadt.HISTORICA_2026B, arquivos={"desenvolvedor_1504950.csv": arquivo}, alterar_manifesto=alterar
    )
    with pytest.raises(V.FalhaSegura):
        V._origem_cadt(p, "PA", digest, prov)


def test_origem_cadt_aceita_zero_decimal_e_manifesto_com_geo_fora_do_tar(tmp_path):
    bruto = (
        "restauracao_versao,restauracao_cenario,credito_liquido_tco2_contrato\n"
        f"{cadt.HISTORICA_2026B},central_r11,0.0\n"
    ).encode()
    p, digest, prov = _pacote_cadt(
        tmp_path,
        cadt.HISTORICA_2026B,
        arquivos={"desenvolvedor_1504950.csv": bruto},
        alterar_manifesto=lambda m: m.update({"geo_1504950.parquet": {"sha256": "f" * 64}}),
    )
    assert V._origem_cadt(p, "PA", digest, prov)["credito_total"] == 0


@pytest.mark.parametrize("horizonte", ["100.0", "100.1", "NaN", "Infinity", "-1"])
def test_origem_cadt_exige_evidencia_de_teto_nao_atingido_ate25(tmp_path, horizonte):
    bruto = (
        "restauracao_versao,restauracao_cenario,credito_liquido_tco2_contrato,"
        "credito_liquido_tco2_ha_contrato_p50,credito_liquido_tco2_ha_horizonte\n"
        f"{cadt.HISTORICA_2026B},central_r11,123.0,100.0,{horizonte}\n"
    ).encode()
    p, digest, prov = _pacote_cadt(tmp_path, cadt.HISTORICA_2026B, arquivos={"desenvolvedor_1504950.csv": bruto})
    with pytest.raises(V.FalhaSegura, match="curva_fonte_nao_comprovada"):
        V._origem_cadt(p, "PA", digest, prov)


@pytest.mark.parametrize(
    "alias", ["PA/desenvolvedor_1504950.csv", "PA//desenvolvedor_1504950.csv", "PA/./desenvolvedor_1504950.csv"]
)
def test_origem_cadt_nao_soma_membro_duplicado_nem_alias_do_mesmo_nome(tmp_path, alias):
    p, _, prov = _pacote_cadt(tmp_path, cadt.HISTORICA_2026B)
    with tarfile.open(p) as tar:
        membros = [(m.name, tar.extractfile(m).read()) for m in tar]
    membros.insert(1, (alias, membros[0][1]))
    with tarfile.open(p, "w:gz") as tar:
        for nome, bruto in membros:
            m = tarfile.TarInfo(nome)
            m.size = len(bruto)
            tar.addfile(m, io.BytesIO(bruto))
    with pytest.raises(V.FalhaSegura, match="membro_tar"):
        V._origem_cadt(p, "PA", V.sha_arquivo(p), prov)


def test_origem_cadt_recusa_chave_json_repetida_mesmo_com_hash_do_manifesto(tmp_path):
    p, _, _ = _pacote_cadt(tmp_path, cadt.HISTORICA_2026B)
    with tarfile.open(p) as tar:
        membros = [(m.name, tar.extractfile(m).read()) for m in tar]
    manifesto = membros[-1][1].replace(b'"tarefa":', b'"tarefa": "falsa", "tarefa":', 1)
    membros[-1] = (membros[-1][0], manifesto)
    with tarfile.open(p, "w:gz") as tar:
        for nome, bruto in membros:
            m = tarfile.TarInfo(nome)
            m.size = len(bruto)
            tar.addfile(m, io.BytesIO(bruto))
    with pytest.raises(V.FalhaSegura, match="manifesto_fonte_duplicado"):
        V._origem_cadt(p, "PA", V.sha_arquivo(p), hashlib.sha256(manifesto).hexdigest())
