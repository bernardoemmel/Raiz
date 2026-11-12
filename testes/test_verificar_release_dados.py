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
        "ficha_pacote": {"distribution": [{"contentUrl": "PA/flag_1504950.csv", "sha256": "f" * 64}]},
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


def test_cadt_real_curva_25_anos_e_sem_identificacao():
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
    pacote = url.rsplit("/", 1)[0] + "/raiz_PA.tar.gz"
    dado = cadt.projeto_do_resumo(resumo, "PA", data_inicio="2028-02-29", url_catalogo=url, r=r, c=c)
    dado["metadados"].update(
        entradas={"pacote_sha256": "a" * 64, "proveniencia_sha256": "b" * 64, "url": pacote},
        previsoes_individuais_recalculadas=False,
        comercializacao={"situacao": "pendente"},
    )
    entrada = {"proveniencia_sha256": "b" * 64, "cadt": dado}
    assert V.validar_cadt(dado, "PA", entrada, "a" * 64, pacote, url)["anos"] == 25
    with pytest.raises(V.FalhaSegura, match="diverge_indice"):
        V.validar_cadt(dado, "PA", {**entrada, "cadt": {}}, "a" * 64, pacote, url)
    dado["extra"] = {"location": "PA-1504950-ABC"}
    with pytest.raises(V.FalhaSegura, match="identificacao"):
        V.validar_cadt(dado, "PA", entrada, "a" * 64, pacote, url)


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
