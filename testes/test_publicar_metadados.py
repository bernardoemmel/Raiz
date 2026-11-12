"""Retropreenchimento usa uma vaga global, preserva fontes e retoma por UF."""

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
import yaml

from scripts import publicar_metadados as P
from testes.test_armazem_release import GitHubFalso, _armazem


def test_catalogo_nao_consume_fila_nem_ultrapassa_teto():
    fila, rodar = P.modulos_fila()
    pedido_uf = {"id": "anterior/PA", "unidade": "PA", "refazer": "", "continuacao": 0, "ref": "a" * 40}
    pedido_catalogo = {**pedido_uf, "id": "novo/catalogo", "unidade": "catalogo", "repetir": False}
    estado = {**fila.vazio(), "planejadores": ["novo"], "fila": [pedido_uf]}
    runs = {
        "legado": {
            "status": "in_progress",
            "jobs": [{"name": f"MG-{i}", "status": "in_progress"} for i in range(1, 15)],
        },
        "novo": {"status": "in_progress", "jobs": [{"name": "catalogo", "status": "in_progress"}]},
    }
    # Use unidades válidas, inclusive fatias dos outros estados, para os 14 jobs.
    unidades = [f"SP-{i}" for i in range(1, 7)] + [f"RS-{i}" for i in range(1, 6)] + ["PR-1", "PR-2", "PR-3"]
    runs["legado"]["jobs"] = [{"name": unidade, "status": "in_progress"} for unidade in unidades]
    assert fila.admitir(estado, runs, "novo", [pedido_catalogo], rodar._e_unidade, consumir_fila=False) == [
        pedido_catalogo
    ]
    assert estado["fila"] == [pedido_uf]
    assert len(estado["reservas"]) == 1
    # Mesmo a matriz principal vê a reserva auxiliar enquanto o job estiver vivo.
    assert fila.admitir(estado, runs, "outro", [], rodar._e_unidade) == []
    runs["novo"] = {
        "status": "completed",
        "jobs": [{"name": "catalogo", "status": "completed", "conclusion": "failure"}],
    }
    escolhidos = fila.admitir(estado, runs, "outro", [], rodar._e_unidade)
    assert escolhidos == [pedido_uf]
    assert all(r["unidade"] != "catalogo" for r in estado["reservas"])
    assert not any(p["unidade"] == "catalogo" for p in estado["fila"])


def test_sem_reserva_nao_cria_armazem_nem_baixa_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_JOB", "catalogo")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "exemplo/raiz")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    fila, _ = P.modulos_fila()
    monkeypatch.setattr(fila.Repositorio, "ler", lambda self: ("", fila.vazio()))

    def proibido(*args):
        pytest.fail("nenhuma operação pesada antes da reserva")

    with pytest.raises(RuntimeError, match="sem reserva global"):
        P.publicar(fabrica=proibido)


def test_reserva_auxiliar_recusa_sem_vaga_e_nao_enfileira(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_JOB", "catalogo")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "exemplo/raiz")
    monkeypatch.setattr(P, "conferir_processamento_seguro", lambda: {})
    fila, _ = P.modulos_fila()
    monkeypatch.setattr(fila.Repositorio, "ler", lambda self: ("", fila.vazio()))
    chamadas = []
    monkeypatch.setattr(fila, "reservar", lambda **kw: chamadas.append(kw) or [])
    with pytest.raises(RuntimeError, match="sem vaga entre os 15"):
        P.reservar_vaga()
    assert chamadas[0]["pedidos"] == []
    assert chamadas[0]["candidatos"] == ["catalogo"]
    assert chamadas[0]["consumir_fila"] is False and chamadas[0]["repetir"] is False


def test_release_com_mais_de_cem_assets_e_paginado(tmp_path):
    github = GitHubFalso()
    github.assets = {f"arquivo_{i}.json": b"{}" for i in range(205)}
    armazem = _armazem(github, tmp_path)
    assert len(armazem._release()["assets"]) == 205


def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "bernardoemmel/raiz")
    monkeypatch.setenv("RAIZ_SEM_BANCO", "1")
    monkeypatch.setenv("GH_TOKEN", "segredo")
    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_URL", "release-github://exemplo/privado/dados-privados")
    monkeypatch.setenv("RAIZ_DADOS_PRIVADOS_TOKEN", "segredo")
    monkeypatch.setenv("RAIZ_CADT_INICIO_CENARIO", "2027-01-01")
    monkeypatch.setattr(P, "confirmar_reserva", lambda: None)
    monkeypatch.setattr(P, "conferir_orcamento", lambda relatorio: True)

    def seguro(relatorio):
        relatorio["seguranca_processamento"] = {"seguro": True}
        return relatorio["seguranca_processamento"]

    monkeypatch.setattr(P, "conferir_processamento_seguro", seguro)


def _fabrica(github, classe=None):
    from raiz.executor.armazem import ArmazemRelease

    classe = classe or ArmazemRelease
    if not hasattr(github, "publico"):
        github.publico = GitHubFalso()
        github.publico.privado = False
        github.publico.assets["estados.json"] = json.dumps(
            {
                "escopo": "publico_basico",
                "versao_publicacao": 1,
                "repo": "bernardoemmel/raiz",
                "tag": "dados",
                "gerado_em": "2026-11-12T00:00:00Z",
                "estados": {},
            }
        ).encode()

    def responder(req):
        privado = "/repos/exemplo/privado/" in req.url.path or req.url.path == "/repos/exemplo/privado"
        return (github if privado else github.publico)(req)

    def fabricar(repo, tag, espelho, **kw):
        kw.setdefault("token", "segredo")
        return classe(repo, tag, espelho, cliente=httpx.Client(transport=httpx.MockTransport(responder)), **kw)

    return fabricar


def _preflight(tmp_path, monkeypatch, runs, estado=None, comparacao="ahead"):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "exemplo/raiz")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "resumo.md"))
    fila, _ = P.modulos_fila()
    P._COMPATIBILIDADE.clear()
    P._CHECKOUT_HEAD.clear()
    if estado is None:
        estado = fila.vazio()
        estado["reservas"] = [
            {"run_id": run_id, "unidade": job["name"], "pedido": {"ref": run["head_sha"]}}
            for run_id, run in runs.items()
            for job in run["jobs"]
        ]
    monkeypatch.setattr(fila.Repositorio, "ler", lambda self: ("", estado))
    monkeypatch.setattr(fila, "rodadas", lambda *args, **kwargs: runs)
    chamadas = []

    def comparar(caminho):
        chamadas.append(caminho)
        if "contents/raiz/executor/armazem.py" in caminho:
            if comparacao not in {"ahead", "identical", "behind", "diverged"}:
                return {"encoding": "desconhecida"}
            codigo = (
                (P.RAIZ / "raiz/executor/armazem.py").read_bytes()
                if comparacao in {"ahead", "identical"}
                else b"legado"
            )
            return {"encoding": "base64", "content": base64.b64encode(codigo).decode()}
        if "/contents/" in caminho:
            return {"encoding": "base64", "content": base64.b64encode(b"workflow com matrix.ref").decode()}
        pytest.fail("endpoint inesperado")

    monkeypatch.setattr(fila, "api", comparar)
    return fila, chamadas


def _run(sha="a" * 40, status="in_progress", job_status="in_progress"):
    return {"head_sha": sha, "status": status, "jobs": [{"name": "MA", "status": job_status}]}


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_preflight_permite_codigo_com_travas_e_cacheia_apenas_commit(tmp_path, monkeypatch, status):
    runs = {"11": _run(), "12": _run()}
    _, consultas = _preflight(tmp_path, monkeypatch, runs, comparacao=status)
    assert P.conferir_processamento_seguro()["seguro"]
    assert consultas == [
        f"repos/exemplo/raiz/contents/raiz/executor/armazem.py?ref={'a' * 40}",
        f"repos/exemplo/raiz/contents/.github/workflows/processar-estados.yml?ref={'a' * 40}",
    ]
    # O cache dos bytes auditados não transforma um snapshot dos runs em cache.
    runs["13"] = _run(sha=None)
    with pytest.raises(P.ProcessamentoInseguro):
        P.conferir_processamento_seguro()


@pytest.mark.parametrize("status", ["behind", "diverged"])
def test_legado_bloqueia_antes_de_reservar_sem_cancelar(tmp_path, monkeypatch, status):
    fila, _ = _preflight(tmp_path, monkeypatch, {"123": _run()}, comparacao=status)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_JOB", "catalogo")
    monkeypatch.setenv("GITHUB_RUN_ID", "456")
    monkeypatch.setattr(fila, "reservar", lambda **kw: pytest.fail("não deve reservar enquanto há legado"))
    with pytest.raises(P.ProcessamentoInseguro, match=r"MA \(rodada 123\).*não cancele"):
        P.reservar_vaga()
    resultado = json.loads((tmp_path / "catalogo-metadados.json").read_text())["seguranca_processamento"]
    assert resultado["codigo"] == "aguardando_processamento_legado"
    assert resultado["rodadas_legadas"][0]["url"] == "https://github.com/exemplo/raiz/actions/runs/123"
    assert "MA" in (tmp_path / "resumo.md").read_text()


@pytest.mark.parametrize("falha", ["runs", "comparacao", "resposta"])
def test_preflight_falha_fechada_sem_expor_resposta_autenticada(tmp_path, monkeypatch, falha, capsys):
    fila, _ = _preflight(tmp_path, monkeypatch, {"123": _run()}, comparacao="desconhecido")

    def indisponivel(*args):
        raise RuntimeError("SEGREDO_RESPOSTA_PRIVADA")

    if falha == "runs":
        monkeypatch.setattr(fila, "rodadas", indisponivel)
    elif falha == "comparacao":
        monkeypatch.setattr(fila, "api", indisponivel)
    with pytest.raises(P.ProcessamentoInseguro) as erro:
        P.conferir_processamento_seguro()
    texto = (tmp_path / "catalogo-metadados.json").read_text() + (tmp_path / "resumo.md").read_text()
    assert "consulta_de_processamento_nao_confirmada" in texto
    assert "SEGREDO_RESPOSTA_PRIVADA" not in texto + str(erro.value) + capsys.readouterr().out


@pytest.mark.parametrize("terminal", [False, True])
def test_ref_antiga_da_matriz_bloqueia_somente_reserva_ainda_viva(tmp_path, monkeypatch, terminal):
    fila, _ = P.modulos_fila()
    estado = fila.vazio()
    estado["reservas"] = [{"run_id": "123", "unidade": "MA", "pedido": {"ref": "b" * 40}}]
    runs = {"123": _run(job_status="completed" if terminal else "in_progress")}
    fila, _ = _preflight(tmp_path, monkeypatch, runs, estado)
    original = fila.api
    monkeypatch.setattr(
        fila, "api", lambda caminho: {"status": "behind"} if caminho.endswith("b" * 40) else original(caminho)
    )
    if terminal:
        assert P.conferir_processamento_seguro()["seguro"]
    else:
        with pytest.raises(P.ProcessamentoInseguro):
            P.conferir_processamento_seguro()


def test_rerun_sem_reserva_nao_presume_checkout_pelo_head_do_workflow(tmp_path, monkeypatch):
    fila, _ = P.modulos_fila()
    _preflight(tmp_path, monkeypatch, {"123": _run()}, fila.vazio())
    with pytest.raises(P.ProcessamentoInseguro):
        P.conferir_processamento_seguro()
    resultado = json.loads((tmp_path / "catalogo-metadados.json").read_text())["seguranca_processamento"]
    assert resultado["codigo"] == "consulta_de_processamento_nao_confirmada"


@pytest.mark.parametrize(
    "checkout,permitido",
    [
        ("      - uses: actions/checkout@v4\n", True),
        ("      - uses: actions/checkout@v4\n        with:\n          ref: ${{ matrix.ref }}\n", False),
        ("      - uses: actions/checkout@v4\n        <<: *checkout\n", False),
        ("      - uses: actions/checkout@v4\n      - uses: actions/checkout@v4\n", False),
        ("      - uses: actions/checkout@v5\n", False),
        ("      - uses: actions/checkout@v4\n      - run: git checkout commit_antigo\n", False),
    ],
)
def test_pre_cap_sem_reserva_so_passa_com_checkout_default_comprovado(tmp_path, monkeypatch, checkout, permitido):
    fila, _ = P.modulos_fila()
    _preflight(tmp_path, monkeypatch, {"123": _run()}, fila.vazio())
    workflow = (
        "jobs:\n  planejar:\n    steps:\n      - uses: actions/checkout@v4\n"
        "  processar:\n    steps:\n" + checkout + "      - run: python motor/rodar_estado.py\n"
    )
    confiavel = (
        "jobs:\n  planejar:\n    steps:\n      - uses: actions/checkout@v4\n"
        "  processar:\n    steps:\n      - uses: actions/checkout@v4\n"
        "      - run: python motor/rodar_estado.py\n"
    )
    monkeypatch.setattr(P, "WORKFLOWS_CHECKOUT_HEAD", {hashlib.sha256(confiavel.encode()).hexdigest()})
    chamadas = []

    def api(caminho):
        chamadas.append(caminho)
        if "contents/raiz/executor/armazem.py" in caminho:
            return {
                "encoding": "base64",
                "content": base64.b64encode((P.RAIZ / "raiz/executor/armazem.py").read_bytes()).decode(),
            }
        if "/contents/" in caminho:
            return {"encoding": "base64", "content": base64.b64encode(workflow.encode()).decode()}
        return {"status": "ahead"}

    monkeypatch.setattr(fila, "api", api)
    if permitido:
        resultado = P.conferir_processamento_seguro()
        assert resultado["seguro"] and resultado["checkouts_head_confirmados"] == ["123"]
        assert P.conferir_processamento_seguro()["seguro"]
        assert len([c for c in chamadas if "/contents/" in c]) == 2
    else:
        with pytest.raises(P.ProcessamentoInseguro):
            P.conferir_processamento_seguro()


@pytest.mark.parametrize("bloqueado", [False, True])
def test_fila_legada_que_pode_iniciar_durante_catalogacao_bloqueia(tmp_path, monkeypatch, bloqueado):
    fila, _ = P.modulos_fila()
    estado = fila.vazio()
    estado["fila"] = [{"unidade": "MA", "ref": "b" * 40, "bloqueado": bloqueado}]
    _preflight(tmp_path, monkeypatch, {"123": _run(status="completed")}, estado, "behind")
    if bloqueado:
        assert P.conferir_processamento_seguro()["seguro"]
    else:
        with pytest.raises(P.ProcessamentoInseguro):
            P.conferir_processamento_seguro()
        resultado = json.loads((tmp_path / "catalogo-metadados.json").read_text())["seguranca_processamento"]
        assert resultado["pedidos_legados"] == [{"unidade": "MA", "ref": "b" * 40}]


def test_reconfere_dentro_da_trava_antes_de_publicar_uf(tmp_path, monkeypatch):
    real = P.conferir_processamento_seguro
    _ambiente(tmp_path, monkeypatch)
    fila, _ = _preflight(tmp_path, monkeypatch, {}, comparacao="behind")
    monkeypatch.setattr(P, "conferir_processamento_seguro", real)
    github = GitHubFalso()
    github.assets["raiz_PA.tar.gz"] = github.tar("PA", {"imoveis_1504950.csv": b"cod_imovel,ha\nCAR-A,3\n"})
    snapshots = iter([{}, {"123": _run()}])
    monkeypatch.setattr(fila, "rodadas", lambda *args, **kwargs: next(snapshots))
    resultado = P.publicar(fabrica=_fabrica(github))
    assert not github.uploads
    assert resultado["pendentes"] == ["PA"] and not resultado["global_concluido"]
    assert resultado["falhas"][0]["etapa"] == "seguranca_processamento"


def test_reconfere_dentro_da_trava_antes_de_publicar_globais(tmp_path, monkeypatch):
    real = P.conferir_processamento_seguro
    _ambiente(tmp_path, monkeypatch)
    fila, _ = _preflight(tmp_path, monkeypatch, {}, comparacao="behind")
    monkeypatch.setattr(P, "conferir_processamento_seguro", real)
    github = GitHubFalso()
    snapshots = iter([{}, {"123": _run()}])
    monkeypatch.setattr(fila, "rodadas", lambda *args, **kwargs: next(snapshots))
    resultado = P.publicar(fabrica=_fabrica(github))
    assert not github.uploads
    assert not resultado["global_concluido"]
    assert resultado["falhas"][0]["etapa"] == "seguranca_processamento"


def test_retropreenche_csv_controle_orfao_e_kml_sem_refazer_motor(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    github = GitHubFalso()
    csv_original = b"cod_imovel,ha\nCAR-A,3\n"
    github.assets["raiz_PA.tar.gz"] = github.tar("PA", {"imoveis_1504950.csv": csv_original})
    controle_am = b'{"marcas":{},"estado":{"situacao":"em_curso"}}'
    github.assets["raiz_controle_AM.json"] = controle_am
    github.assets["URTX.kml"] = b"<kml><Document/></kml>"
    infraestrutura = {
        "retomada_PA_43285608189_entradas_abc.tar.gz": b"entrada privada congelada",
        "retomada_PA_43285608189_exec_123_fatia_01_checkpoint_abc.tar.gz": b"checkpoint privado",
        "lote_PA_calculado_123_01.tar.gz": b"fatia intermediaria",
    }
    github.assets.update(infraestrutura)
    produto_lote = "lote_PA_central_r11_retomada_123_1.json"
    github.assets[produto_lote] = b'{"municipios":1}'
    github.assets["estados.json"] = json.dumps({"estados": {"AM": {"situacao": "em_curso"}}}).encode()
    classe = P.classe_armazem()

    fabrica = _fabrica(github, classe)

    relatorio = P.publicar(fabrica=fabrica)
    assert relatorio["falhas"] == []
    assert relatorio["pendentes"] == []
    assert relatorio["concluidas"] == ["AM", "PA"]
    assert relatorio["sem_pacote_tabular"] == ["AM"]
    assert relatorio["global_concluido"] is True
    assert github.membros("raiz_PA.tar.gz")["PA/imoveis_1504950.csv"] == csv_original
    assert github.assets["raiz_controle_AM.json"] == controle_am
    assert json.loads(github.assets["estados.json"])["estados"]["AM"]["situacao"] == "em_curso"
    for nome in ("URTX.kml", "raiz_controle_AM.json", produto_lote):
        ficha = json.loads(github.assets[f"croissant_{nome}.json"])
        assert ficha["distribution"][0]["sha256"] == hashlib.sha256(github.assets[nome]).hexdigest()
    assinados = P.checksums(privado=True)
    assert set(github.assets) - infraestrutura.keys() <= set(assinados)
    assert all(
        assinados[n] == hashlib.sha256(d).hexdigest() for n, d in github.assets.items() if n not in infraestrutura
    )
    assert not infraestrutura.keys() & set(github.downloads)
    assert all(github.assets[n] == d and f"croissant_{n}.json" not in github.assets for n, d in infraestrutura.items())
    assert not any(n.startswith("croissant_croissant") for n in github.assets)
    assert not list(tmp_path.glob("raiz-catalogo-*"))
    assert (tmp_path / "catalogo-metadados.json").exists()


def test_falha_de_uma_uf_preserva_anterior_e_continua(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    github = GitHubFalso()
    github.assets["raiz_AC.tar.gz"] = github.tar("AC", {"imoveis_1200001.csv": b"cod_imovel,ha\nCAR-A,3\n"})
    github.assets["raiz_PA.tar.gz"] = github.tar("PA", {"imoveis_1504950.csv": b"cod_imovel,ha\nCAR-B,4\n"})
    classe = P.classe_armazem()

    class ComFalha(classe):
        def publicar(self, uf=None, extra=None):
            if uf == "AC":
                raise RuntimeError("falha simulada")
            return super().publicar(uf, extra)

    fabrica = _fabrica(github, ComFalha)

    relatorio = P.publicar(fabrica=fabrica)
    assert relatorio["concluidas"] == ["PA"] and relatorio["pendentes"] == ["AC"]
    falha = relatorio["falhas"][0]
    assert falha["unidade"] == "AC" and falha["tipo"] == "RuntimeError"
    assert falha["etapa"] == "publicar_uf" and falha["arquivo"] == "raiz_AC.tar.gz"
    assert falha["rastro"][-1]["funcao"] == "publicar" and falha["rastro"][-1]["linha"] > 0
    assert "croissant_PA.json" in github.assets
    assert not list(tmp_path.glob("raiz-catalogo-*"))


def test_diagnostico_nao_registra_mensagem_fonte_nem_variaveis_da_excecao(capsys):
    relatorio = {"falhas": []}
    try:
        raise ValueError("VALOR_PRIVADO_NAO_PUBLICAR")
    except ValueError as erro:
        P.registrar_falha(relatorio, "PA", "conferir_arquivo", "raiz_PA.tar.gz", erro)
    texto = json.dumps(relatorio) + capsys.readouterr().out
    assert "VALOR_PRIVADO_NAO_PUBLICAR" not in texto
    ponto = relatorio["falhas"][0]["rastro"][-1]
    assert set(ponto) == {"arquivo", "linha", "funcao"}
    assert ponto["arquivo"] == "test_publicar_metadados.py" and ponto["linha"] > 0


def test_workflow_reserva_antes_de_dependencias_e_atesta_mesmo_com_falha():
    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows/publicar-metadados.yml").read_text())
    job = workflow["jobs"]["catalogo"]
    assert job["name"] == "catalogo"
    passos = job["steps"]
    assert "--reservar" in passos[1]["run"]
    assert passos[2]["uses"].startswith("astral-sh/setup-uv")
    atestar = next(p for p in passos if p.get("uses", "").startswith("actions/attest-build-provenance"))
    assert atestar["if"].startswith("always()")
    assert atestar["with"]["subject-checksums"] == "${{ runner.temp }}/atestar.txt"
    assert workflow["permissions"]["attestations"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
    assert all(not p.get("uses", "").startswith("actions/upload-artifact") for p in passos)
    privado = next(p for p in passos if p.get("with", {}).get("subject-checksums", "").endswith("atestar-privado.txt"))
    assert privado["with"]["show-summary"] is False
    relatorio = next(p for p in passos if "enviar-arquivo --imutavel" in p.get("run", ""))
    assert relatorio["if"] == "always()"
    assert "transferencia_privada" in relatorio["run"]


def test_rodadas_preserva_jobs_por_padrao_e_permite_consulta_leve(monkeypatch):
    fila, _ = P.modulos_fila()
    chamadas = []

    def paginas(caminho, campo):
        chamadas.append(caminho)
        if campo == "jobs":
            return [{"name": "MA", "status": "in_progress"}]
        return [{"id": 123, "status": "in_progress"}] if "status=in_progress" in caminho else []

    monkeypatch.setattr(fila, "paginas", paginas)
    assert fila.rodadas("exemplo/raiz", "processar-estados.yml")["123"]["jobs"]
    chamadas.clear()
    assert "jobs" not in fila.rodadas("exemplo/raiz", "processar-estados.yml", incluir_jobs=False)["123"]
    assert len(chamadas) == 5 and not any("/jobs?" in c for c in chamadas)


def test_guard_pre_cap_auditado_nao_consulta_jobs_mas_reconfere_runs(tmp_path, monkeypatch):
    runs = {str(i): {"head_sha": "a" * 40, "status": "in_progress"} for i in range(10)}
    fila, _ = P.modulos_fila()
    _preflight(tmp_path, monkeypatch, runs, fila.vazio())
    monkeypatch.setattr(P, "checkout_do_head", lambda *args: True)
    monkeypatch.setattr(fila, "paginas", lambda *args: pytest.fail("checkout auditado não precisa dos jobs"))
    chamadas = []
    monkeypatch.setattr(fila, "rodadas", lambda *args, **kw: chamadas.append(kw) or runs)
    assert P.conferir_processamento_seguro()["seguro"]
    assert P.conferir_processamento_seguro()["seguro"]
    assert chamadas == [{"incluir_jobs": False}, {"incluir_jobs": False}]


@pytest.mark.parametrize("restantes,permitido", [(249, False), (250, True)])
def test_cota_insuficiente_vira_checkpoint_sem_esperar_reset(tmp_path, monkeypatch, restantes, permitido):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    fila, _ = P.modulos_fila()
    monkeypatch.setattr(
        fila, "api", lambda caminho: {"resources": {"core": {"remaining": restantes, "reset": 9999999999}}}
    )
    monkeypatch.setattr(P.time, "sleep", lambda _: pytest.fail("cota curta deve terminar, não ocupar vaga esperando"))
    relatorio = {}
    assert P.conferir_orcamento(relatorio) is permitido
    assert bool(relatorio.get("adiado_por_cota")) is not permitido


def test_queda_de_cota_preserva_uf_concluida_e_pendentes(tmp_path, monkeypatch):
    real = P.conferir_orcamento
    _ambiente(tmp_path, monkeypatch)
    monkeypatch.setattr(P, "conferir_orcamento", real)
    fila, _ = P.modulos_fila()
    cotas = iter([250, 249])
    monkeypatch.setattr(
        fila, "api", lambda caminho: {"resources": {"core": {"remaining": next(cotas), "reset": 9999999999}}}
    )
    github = GitHubFalso()
    for uf in ("AC", "PA"):
        github.assets[f"raiz_{uf}.tar.gz"] = github.tar(uf, {"imoveis_1504950.csv": b"cod_imovel,ha\nCAR-A,3\n"})
    resultado = P.publicar(fabrica=_fabrica(github))
    assert resultado["concluidas"] == ["AC"] and resultado["pendentes"] == ["PA"]
    assert resultado["adiado_por_cota"] and not resultado["global_concluido"]
    assert not any("PA" in nome for nome in github.uploads)
    assert not github.refs


def test_erro_ao_consultar_cota_bloqueia_sem_expor_resposta(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    fila, _ = P.modulos_fila()

    def falhar(*args):
        raise RuntimeError("RESPOSTA_PRIVADA")

    monkeypatch.setattr(fila, "api", falhar)
    relatorio = {}
    with pytest.raises(P.ProcessamentoInseguro) as erro:
        P.conferir_orcamento(relatorio)
    assert relatorio["adiado_por_cota"]
    assert "RESPOSTA_PRIVADA" not in json.dumps(relatorio) + str(erro.value)


@pytest.mark.parametrize(
    "status,headers,esperado",
    [
        (429, {"Retry-After": "2"}, 2),
        (429, {"Retry-After": "Thu, 01 Jan 1970 00:16:43 GMT"}, 3),
        (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1004"}, 4),
    ],
)
def test_retry_repete_apenas_request_recusada_com_mesmos_bytes(monkeypatch, status, headers, esperado):
    chamadas, esperas = [], []
    monkeypatch.setattr(P.time, "time", lambda: 1000)
    monkeypatch.setattr(P.time, "monotonic", lambda: 100)
    monkeypatch.setattr(P.time, "sleep", esperas.append)

    def responder(req):
        chamadas.append((req.method, req.url, req.content, dict(req.headers)))
        return httpx.Response(status, headers=headers) if len(chamadas) == 1 else httpx.Response(201)

    with httpx.Client(transport=P.transporte_com_retry(200, httpx.MockTransport(responder))) as cliente:
        assert cliente.post("https://uploads.github.com/arquivo", content=b"arquivo inteiro").status_code == 201
    assert chamadas[0] == chamadas[1]
    assert esperas == [esperado]


@pytest.mark.parametrize(
    "status,headers,prazo",
    [
        (403, {}, 200),
        (429, {"Retry-After": "3600"}, 5000),
        (429, {"Retry-After": "2"}, 101),
        (429, {"Retry-After": "invalido"}, 200),
        (429, {"Retry-After": "nan"}, 200),
        (401, {}, 200),
    ],
)
def test_retry_nao_monopoliza_trava_nem_repete_permissao_negada(monkeypatch, status, headers, prazo):
    chamadas = []
    monkeypatch.setattr(P.time, "monotonic", lambda: 100)
    monkeypatch.setattr(P.time, "sleep", lambda _: pytest.fail("não deve aguardar esta resposta"))

    def responder(req):
        chamadas.append(req.method)
        return httpx.Response(status, headers=headers)

    with httpx.Client(transport=P.transporte_com_retry(prazo, httpx.MockTransport(responder))) as cliente:
        assert cliente.delete("https://api.github.com/repos/exemplo/raiz/git/refs/tags/trava").status_code == status
    assert chamadas == ["DELETE"]


def _armazem_backup(github, tmp_path, responder, prazo=None):
    classe = P.classe_armazem(prazo)
    return classe(
        "exemplo/privado",
        "dados-privados",
        tmp_path / "espelho",
        token="segredo",
        privado=True,
        cliente=httpx.Client(transport=httpx.MockTransport(responder)),
    )


def test_backup_sobrevive_post_falho_e_original_ausente_no_retry(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    github = GitHubFalso()
    nome, original = "raiz_PA.tar.gz", b"original irrecuperavel"
    github.assets[nome] = original
    chamadas = []

    def responder(req):
        chamadas.append((req.method, req.url.host, req.url.path))
        if req.method == "POST" and req.url.host == "uploads.github.com" and req.url.params["name"] == nome:
            return httpx.Response(429)
        return github(req)

    a = _armazem_backup(github, tmp_path, responder)
    with pytest.raises(P.ProcessamentoInseguro):
        a._subir(a._release(), nome, b"novo")
    assert nome not in github.assets
    marcadores = list((tmp_path / "recuperacao-release").glob("*.json"))
    assert len(marcadores) == 1
    meta = json.loads(marcadores[0].read_bytes())
    assert meta["origem"] == "exemplo/privado/dados-privados/" + nome
    assert meta["sha256"] == hashlib.sha256(original).hexdigest()
    assert github.assets[meta["arquivo"]] == original
    assert not any(host == "github.com" for _, host, _ in chamadas)
    assert not (tmp_path / "atestar.txt").exists()
    assert nome not in P.checksums(privado=True)
    # A retomada não perde o backup remoto nem precisa baixar o original ausente.
    a.cli = httpx.Client(transport=httpx.MockTransport(github))
    a._subir(a._release(), nome, b"novo")
    assert github.assets[nome] == b"novo" and github.assets[meta["arquivo"]] == original
    assert not list((tmp_path / "recuperacao-release").glob("*.json"))
    assert P.checksums(privado=True)[nome] == hashlib.sha256(b"novo").hexdigest()


def test_backup_divergente_impede_delete_do_original(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    github = GitHubFalso()
    github.assets["estados.json"] = b'{"estados":{}}'
    a = _armazem_backup(github, tmp_path, github)
    rel = a._release()
    rel["assets"][0]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(P.ProcessamentoInseguro):
        a._subir(rel, "estados.json", b"novo")
    assert github.assets["estados.json"] == b'{"estados":{}}' and not github.uploads


def test_backup_preserva_versao_intermediaria_publicada_por_outro_job(tmp_path, monkeypatch):
    _ambiente(tmp_path, monkeypatch)
    github = GitHubFalso()
    nome = "estados.json"

    def responder(req):
        if req.method == "POST" and req.url.host == "uploads.github.com" and req.url.params["name"] == nome:
            return httpx.Response(429)
        return github(req)

    a = _armazem_backup(github, tmp_path, responder)
    for original in (b"original1", b"original2"):
        github.assets[nome] = original
        with pytest.raises(P.ProcessamentoInseguro):
            a._subir(a._release(), nome, b"novo")
    preservados = {b for n, b in github.assets.items() if n.startswith("recuperacao-") and n.endswith(".bin")}
    assert preservados == {b"original1", b"original2"}
    assert nome not in github.assets


def test_403_permissao_nao_e_classificado_como_cota():
    assert not P.resposta_de_cota(httpx.Response(403))
    assert P.resposta_de_cota(httpx.Response(403, headers={"x-ratelimit-remaining": "0"}))


def test_checkpoint_global_retoma_sem_reprocessar_ufs(tmp_path, monkeypatch):
    real = P.conferir_orcamento
    _ambiente(tmp_path, monkeypatch)
    monkeypatch.setattr(P, "conferir_orcamento", real)
    fila, _ = P.modulos_fila()
    cotas = iter([250, 249, 250])
    monkeypatch.setattr(
        fila, "api", lambda caminho: {"resources": {"core": {"remaining": next(cotas), "reset": 9999999999}}}
    )
    github = GitHubFalso()
    original = b"cod_imovel,ha\nCAR-A,3\n"
    github.assets["raiz_PA.tar.gz"] = github.tar("PA", {"imoveis_1504950.csv": original})
    github.assets["URTX.kml"] = b"<kml/>"
    publicadas = []
    classe = P.classe_armazem()

    class Contar(classe):
        def publicar(self, uf=None, extra=None):
            publicadas.append(uf)
            return super().publicar(uf, extra)

    fabrica = _fabrica(github, Contar)

    primeiro = P.publicar(fabrica=fabrica)
    assert primeiro["concluidas"] == ["PA"] and primeiro["pendentes"] == []
    assert not primeiro["global_concluido"]
    segundo = P.publicar(ufs=[], fabrica=fabrica)
    assert segundo["global_concluido"] and not segundo["falhas"]
    assert publicadas == ["PA"]
    assert github.membros("raiz_PA.tar.gz")["PA/imoveis_1504950.csv"] == original
    assert "croissant_URTX.kml.json" in github.assets


def test_cli_globais_rejeita_ufs_antes_de_reservar(monkeypatch):
    monkeypatch.setenv("RAIZ_CATALOGO_UFS", "PA")
    monkeypatch.setattr(P.sys, "argv", ["publicar_metadados.py", "--reservar", "--somente-globais"])
    monkeypatch.setattr(P, "reservar_vaga", lambda: pytest.fail("combinação inválida não deve reservar vaga"))
    with pytest.raises(ValueError, match="não pode ser combinado"):
        P.main()


def _ambiente_finalizador(tmp_path, monkeypatch):
    confirmar = P.confirmar_reserva
    _ambiente(tmp_path, monkeypatch)
    monkeypatch.setattr(P, "confirmar_reserva", confirmar)
    for nome, valor in {
        "GITHUB_ACTIONS": "true",
        "GITHUB_JOB": "processar",
        "GITHUB_RUN_ID": "123",
        "UNIDADE": "MG-3",
        "RAIZ_EXECUTOR_REF": "b" * 40,
        "RAIZ_PUBLICADOR_REF": "a" * 40,
        "RAIZ_INICIO": str(P.time.time() - 300 * 60),
    }.items():
        monkeypatch.setenv(nome, valor)
    monkeypatch.delenv("RAIZ_CATALOGO_UFS", raising=False)
    monkeypatch.delenv("RAIZ_CATALOGO_SOMENTE_GLOBAIS", raising=False)
    fila, _ = P.modulos_fila()
    estado = fila.vazio()
    estado["reservas"] = [{"run_id": "123", "unidade": "MG-3", "pedido": {"ref": "b" * 40}}]
    monkeypatch.setattr(fila.Repositorio, "ler", lambda self: ("", estado))
    monkeypatch.setattr(fila, "comando", lambda args: "a" * 40)
    monkeypatch.setattr(fila, "reservar", lambda **kw: pytest.fail("finalizador não pode reservar outra vaga"))
    return fila, estado


@pytest.mark.parametrize("invalido", ["reserva", "job", "executor", "publicador", "uf", "globais"])
def test_finalizador_rejeita_escopo_ou_referencia_incompativel_antes_de_dados(tmp_path, monkeypatch, invalido):
    fila, estado = _ambiente_finalizador(tmp_path, monkeypatch)
    ufs, globais = ["MG"], False
    if invalido == "reserva":
        estado["reservas"][0]["unidade"] = "MG-2"
    elif invalido == "job":
        monkeypatch.setenv("GITHUB_JOB", "catalogo")
    elif invalido == "executor":
        monkeypatch.setenv("RAIZ_EXECUTOR_REF", "c" * 40)
    elif invalido == "publicador":
        monkeypatch.setattr(fila, "comando", lambda args: "c" * 40)
    elif invalido == "uf":
        ufs = ["PA"]
    else:
        globais = True
    with pytest.raises((RuntimeError, ValueError)):
        P.publicar(
            ufs=ufs,
            incluir_globais=globais,
            unidade_reservada="MG-3",
            fabrica=lambda *a: pytest.fail("não deve criar armazém antes da autorização exata"),
        )


def test_finalizador_atual_completa_executor_antigo_na_mesma_reserva(tmp_path, monkeypatch):
    _, estado = _ambiente_finalizador(tmp_path, monkeypatch)
    antes = json.dumps(estado, sort_keys=True)
    github = GitHubFalso()
    fonte = (
        b"cod_imovel,flag_regra_versao,flag_tco2_ano_min,flag_tco2_ano,flag_tco2_ano_max\n"
        b"MG-3100001-AAAA,ghg-lsr-1.1+antiga,0,2,10\n"
    )
    versoes = {"flag_3100001.csv": {"tarefa": "flag", "versao": "tarefa-antiga", "data": "2026-11-12T10:00:00Z"}}
    github.assets["raiz_MG.tar.gz"] = github.tar(
        "MG",
        {
            "flag_3100001.csv": fonte,
            "_versoes.json": json.dumps(versoes).encode(),
        },
    )
    github.assets["URTX.kml"] = b"<kml/>"
    github.assets["raiz_controle_PA.json"] = b'{"estado":{"situacao":"preservar"}}'
    (tmp_path / "atestar-privado.txt").write_text("d" * 64 + "  legado.json\n")
    classe = P.classe_armazem()
    resultados = []
    publicar = P.publicar

    def executar(*args, **kwargs):
        resultado = publicar(
            *args,
            **kwargs,
            fabrica=_fabrica(github, classe),
        )
        resultados.append(resultado)
        return resultado

    monkeypatch.setattr(P, "publicar", executar)
    monkeypatch.setattr(P.sys, "argv", ["publicar_metadados.py", "--finalizar-unidade"])
    assert P.main() == 0
    assert resultados[0]["escopo"] == "uf_reservada" and resultados[0]["concluidas"] == ["MG"]
    assert not resultados[0]["global_concluido"]
    assert json.dumps(estado, sort_keys=True) == antes
    assert github.membros("raiz_MG.tar.gz")["MG/flag_3100001.csv"] == fonte
    ficha = json.loads(github.assets["croissant_MG.json"])
    digest = hashlib.sha256(github.assets["raiz_MG.tar.gz"]).hexdigest()
    assert ficha["distribution"][0]["sha256"] == digest == P.checksums(privado=True)["raiz_MG.tar.gz"]
    assert json.loads(github.assets["estados.json"])["estados"]["MG"]["quantis"]["linhas"] == 3
    assert P.checksums(privado=True)["legado.json"] == "d" * 64
    assert "croissant_URTX.kml.json" not in github.assets
    assert github.assets["raiz_controle_PA.json"] == b'{"estado":{"situacao":"preservar"}}'


def test_prazo_finalizador_reserva_dez_minutos_para_cache_e_assinatura(monkeypatch):
    monkeypatch.setenv("RAIZ_INICIO", "1000")
    monkeypatch.setattr(P.time, "time", lambda: 1000 + 315 * 60)
    assert P.minutos_para_finalizar() == 20
    monkeypatch.setattr(P.time, "time", lambda: 1000 + 334 * 60)
    with pytest.raises(RuntimeError, match="sem prazo seguro"):
        P.minutos_para_finalizar()


@pytest.mark.parametrize("expira_no_backup", [False, True])
def test_prazo_nao_autoriza_delete_apos_calculo_ou_backup_demorar(tmp_path, monkeypatch, expira_no_backup):
    _ambiente(tmp_path, monkeypatch)
    relogio = [99 if expira_no_backup else 100]
    monkeypatch.setattr(P.time, "monotonic", lambda: relogio[0])
    github = GitHubFalso()
    github.assets["estados.json"] = b"original"

    def responder(req):
        if req.method == "GET" and "/releases/assets/" in req.url.path:
            relogio[0] = 101
        return github(req)

    a = _armazem_backup(github, tmp_path, responder, prazo=100)
    with pytest.raises(P.ProcessamentoInseguro):
        a._subir(a._release(), "estados.json", b"novo")
    assert github.assets["estados.json"] == b"original"
    assert "estados.json" not in github.uploads
    assert bool(list((tmp_path / "recuperacao-release").glob("*.json"))) is expira_no_backup


def test_workflow_finalizador_separa_checkout_e_preserva_executor_e_continuacao():
    caminho = Path(__file__).parents[1] / ".github/workflows/processar-estados.yml"
    job = yaml.safe_load(caminho.read_text())["jobs"]["processar"]
    passos = job["steps"]
    checkout = next(p for p in passos if p.get("id") == "publicador_checkout")
    assert checkout["with"] == {"ref": "${{ github.workflow_sha }}", "path": "publicador-atual"}
    assert "matrix.ref != github.workflow_sha" in checkout["if"] and "!cancelled()" in checkout["if"]
    final = next(p for p in passos if "--finalizar-unidade" in p.get("run", ""))
    assert final["working-directory"] == "publicador-atual"
    assert final["env"] == {
        "RAIZ_EXECUTOR_REF": "${{ matrix.ref }}",
        "RAIZ_PUBLICADOR_REF": "${{ github.workflow_sha }}",
    }
    atestar = next(p for p in passos if p.get("uses", "").startswith("actions/attest-build-provenance"))
    continuar = next(p for p in passos if '--continuar "$UNIDADE"' in p.get("run", ""))
    assert passos.index(final) < passos.index(atestar) < passos.index(continuar)
    assert "working-directory" not in continuar
    fila, _ = P.modulos_fila()
    executor = next(p for p in passos if p.get("name") == fila.PASSO_EXECUTOR)
    assert "working-directory" not in executor and "--executor" in executor["run"]
    for passo in passos:
        if passo.get("uses", "").startswith("actions/upload-artifact"):
            assert passo["if"] == "always()"
            assert "matrix.unidade" in passo["with"]["name"] and "github.run_attempt" in passo["with"]["name"]
