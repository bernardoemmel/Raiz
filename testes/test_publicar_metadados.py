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
    monkeypatch.setenv("RAIZ_CADT_INICIO_CENARIO", "2027-01-01")
    monkeypatch.setattr(P, "confirmar_reserva", lambda: None)

    def seguro(relatorio):
        relatorio["seguranca_processamento"] = {"seguro": True}
        return relatorio["seguranca_processamento"]

    monkeypatch.setattr(P, "conferir_processamento_seguro", seguro)


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
    monkeypatch.setattr(fila, "rodadas", lambda *args: runs)
    chamadas = []

    def comparar(caminho):
        chamadas.append(caminho)
        return {"status": comparacao}

    monkeypatch.setattr(fila, "api", comparar)
    return fila, chamadas


def _run(sha="a" * 40, status="in_progress", job_status="in_progress"):
    return {"head_sha": sha, "status": status, "jobs": [{"name": "MA", "status": job_status}]}


@pytest.mark.parametrize("status", ["ahead", "identical"])
def test_preflight_permite_codigo_com_travas_e_cacheia_apenas_commit(tmp_path, monkeypatch, status):
    runs = {"11": _run(), "12": _run()}
    _, consultas = _preflight(tmp_path, monkeypatch, runs, comparacao=status)
    assert P.conferir_processamento_seguro()["seguro"]
    assert consultas == [f"repos/exemplo/raiz/compare/{P.COMMIT_TRAVAS_UF}...{'a' * 40}"]
    # O cache da ancestralidade não transforma um snapshot dos runs em cache.
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
    monkeypatch.setattr(fila, "api", lambda caminho: {"status": "behind" if caminho.endswith("b" * 40) else "ahead"})
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
        if "/contents/" in caminho:
            return {"encoding": "base64", "content": base64.b64encode(workflow.encode()).decode()}
        return {"status": "ahead"}

    monkeypatch.setattr(fila, "api", api)
    if permitido:
        resultado = P.conferir_processamento_seguro()
        assert resultado["seguro"] and resultado["checkouts_head_confirmados"] == ["123"]
        assert P.conferir_processamento_seguro()["seguro"]
        assert len([c for c in chamadas if "/contents/" in c]) == 1
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
    monkeypatch.setattr(fila, "rodadas", lambda *args: next(snapshots))
    resultado = P.publicar(fabrica=lambda repo, tag, espelho: _armazem(github, espelho))
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
    monkeypatch.setattr(fila, "rodadas", lambda *args: next(snapshots))
    resultado = P.publicar(fabrica=lambda repo, tag, espelho: _armazem(github, espelho))
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
    github.assets["estados.json"] = json.dumps({"estados": {"AM": {"situacao": "em_curso"}}}).encode()
    classe = P.classe_armazem()

    def fabrica(repo, tag, espelho):
        return classe(repo, tag, espelho, token="segredo", cliente=httpx.Client(transport=httpx.MockTransport(github)))

    relatorio = P.publicar(fabrica=fabrica)
    assert relatorio["falhas"] == []
    assert relatorio["pendentes"] == []
    assert relatorio["concluidas"] == ["AM", "PA"]
    assert relatorio["sem_pacote_tabular"] == ["AM"]
    assert relatorio["global_concluido"] is True
    assert github.membros("raiz_PA.tar.gz")["PA/imoveis_1504950.csv"] == csv_original
    assert github.assets["raiz_controle_AM.json"] == controle_am
    assert json.loads(github.assets["estados.json"])["estados"]["AM"]["situacao"] == "em_curso"
    for nome in ("URTX.kml", "raiz_controle_AM.json"):
        ficha = json.loads(github.assets[f"croissant_{nome}.json"])
        assert ficha["distribution"][0]["sha256"] == hashlib.sha256(github.assets[nome]).hexdigest()
    assinados = P.checksums()
    assert set(github.assets) <= set(assinados)
    assert all(assinados[n] == hashlib.sha256(d).hexdigest() for n, d in github.assets.items())
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

    def fabrica(repo, tag, espelho):
        return ComFalha(
            repo, tag, espelho, token="segredo", cliente=httpx.Client(transport=httpx.MockTransport(github))
        )

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
