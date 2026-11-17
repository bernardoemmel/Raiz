"""Trava de merge em áreas críticas (raiz/operacao/aprovacao_merge.py, docs/politica-de-merge.md)."""

from pathlib import Path

import yaml

from raiz.operacao import aprovacao_merge as am

APROVADORES = {"bernardoemmel"}


def _rotulado(quem: str, app: str | None = None, nome: str = am.ROTULO_APROVADO) -> dict:
    evento = {"event": "labeled", "label": {"name": nome}, "actor": {"login": quem}}
    evento["performed_via_github_app"] = {"slug": app} if app else None
    return evento


def test_baixo_risco_passa_sem_aprovacao():
    d = am.decidir(["docs/lote.md", "testes/test_x.py", "front/globo/src/App.tsx"], [], [], APROVADORES, "opened")
    assert d.passa and not d.criticos


def test_areas_criticas_reconhecidas():
    for caminho in [
        "motor/raiz_estado.py",
        "motor/gee/x.js",
        ".github/workflows/publicar-site.yml",
        ".github/workflows/ci.yml",
        "raiz/funil/regras.py",
        "scripts/publicar_metadados.py",
        "front/scripts/construir-site.sh",
        "front/scripts/baixar-dados.mjs",
        "raiz/operacao/aprovacao_merge.py",
        "CLAUDE.md",
        "docs/colunas.md",
    ]:
        assert am.motivo_critico(caminho), caminho
    for caminho in ["front/scripts/testar-pedido.mjs", "docs/motor.md", "testes/test_motor.py", "raiz/api.py"]:
        assert am.motivo_critico(caminho) is None, caminho


def test_critico_sem_rotulo_bloqueia():
    d = am.decidir(["motor/fila.sh"], [], [], APROVADORES, "opened")
    assert not d.passa and "motor/fila.sh" in d.criticos


def test_rotulo_do_fundador_pela_pagina_libera():
    d = am.decidir(["motor/fila.sh"], [_rotulado("bernardoemmel")], [am.ROTULO_APROVADO], APROVADORES, "labeled")
    assert d.passa


def test_rotulo_posto_por_app_de_agente_nao_vale():
    eventos = [_rotulado("bernardoemmel", app="claude")]
    d = am.decidir(["motor/fila.sh"], eventos, [am.ROTULO_APROVADO], APROVADORES, "labeled")
    assert not d.passa and "claude" in d.motivo


def test_vale_o_ultimo_que_pos_o_rotulo():
    eventos = [_rotulado("bernardoemmel"), _rotulado("bernardoemmel", app="chatgpt-codex-connector")]
    assert not am.decidir([".github/x.yml"], eventos, [am.ROTULO_APROVADO], APROVADORES, "labeled").passa


def test_rotulo_de_quem_nao_e_aprovador_nao_vale():
    eventos = [_rotulado("github-actions[bot]")]
    assert not am.decidir(["motor/x.py"], eventos, [am.ROTULO_APROVADO], APROVADORES, "labeled").passa


def test_rotulo_tirado_depois_bloqueia():
    assert not am.decidir(["motor/x.py"], [_rotulado("bernardoemmel")], [], APROVADORES, "unlabeled").passa


def test_push_novo_derruba_aprovacao():
    d = am.decidir(["motor/x.py"], [_rotulado("bernardoemmel")], [am.ROTULO_APROVADO], APROVADORES, "synchronize")
    assert not d.passa


def test_resumo_explica_como_liberar():
    d = am.decidir(["motor/x.py"], [], [], APROVADORES, "opened")
    texto = am.resumo(d, "bernardoemmel/Raiz", 7)
    assert am.ROTULO_APROVADO in texto and "motor/x.py" in texto and "/pull/7" in texto


def test_simulacao_local_sem_rede(capsys):
    assert am.main(["--arquivos", "motor/a.py", "docs/b.md"]) == 0
    saida = capsys.readouterr().out
    assert "CRÍTICO  motor/a.py" in saida and "livre    docs/b.md" in saida


def test_workflow_roda_codigo_da_main_e_nunca_o_do_pr():
    fluxo = yaml.safe_load(Path(".github/workflows/aprovacao.yml").read_text(encoding="utf-8"))
    eventos = fluxo[True] if True in fluxo else fluxo["on"]
    assert list(eventos) == ["pull_request_target"]
    job = fluxo["jobs"]["aprovacao"]
    checkout = job["steps"][0]
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert "contents" in fluxo["permissions"] and fluxo["permissions"]["contents"] == "read"


def _arquivo(nome: str, sha: str | None, status: str = "modified", antes: str | None = None) -> dict:
    f = {"filename": nome, "sha": sha, "status": status}
    if antes:
        f["previous_filename"] = antes
    return f


def _base(mapa: dict[str, str]):
    return lambda caminho: {mapa.get(caminho)}


def test_push_que_so_junta_a_main_mantem_aprovacao():
    arquivos = [
        _arquivo("motor/a.py", "s1"),
        _arquivo("docs/x.md", "qualquer"),
        _arquivo("raiz/novo.py", "s9", "added"),
    ]
    so_base = am.push_so_juntou_a_base("ahead", arquivos, _base({"motor/a.py": "s1"}))
    assert so_base[0]
    d = am.decidir(
        ["motor/fila.sh"], [_rotulado("bernardoemmel")], [am.ROTULO_APROVADO], APROVADORES, "synchronize", so_base
    )
    assert d.passa and "juntou a main" in d.motivo


def test_push_que_muda_arquivo_critico_derruba_aprovacao():
    arquivos = [_arquivo("motor/a.py", "do-agente")]
    so_base = am.push_so_juntou_a_base("ahead", arquivos, _base({"motor/a.py": "da-main"}))
    assert not so_base[0] and "motor/a.py" in so_base[1]
    d = am.decidir(
        ["motor/a.py"], [_rotulado("bernardoemmel")], [am.ROTULO_APROVADO], APROVADORES, "synchronize", so_base
    )
    assert not d.passa


def test_push_que_cria_ou_apaga_critico_fora_da_main_derruba():
    assert not am.push_so_juntou_a_base("ahead", [_arquivo("motor/novo.py", "x", "added")], _base({}))[0]
    assert not am.push_so_juntou_a_base("ahead", [_arquivo("motor/a.py", None, "removed")], _base({"motor/a.py": "s"}))[
        0
    ]
    # a main apagou o arquivo: o push só trouxe a remoção
    assert am.push_so_juntou_a_base("ahead", [_arquivo("motor/a.py", None, "removed")], _base({}))[0]


def test_renomear_critico_conta_o_caminho_antigo():
    arquivos = [_arquivo("docs/a.py", "s1", "renamed", antes="motor/a.py")]
    assert not am.push_so_juntou_a_base("ahead", arquivos, _base({"motor/a.py": "s0"}))[0]


def test_push_que_reescreve_historico_derruba():
    assert not am.push_so_juntou_a_base("diverged", [], _base({}))[0]


def test_comparacao_cortada_nao_vale():
    arquivos = [_arquivo(f"docs/{i}.md", "s") for i in range(am.LIMITE_ARQUIVOS_COMPARACAO)]
    assert not am.push_so_juntou_a_base("ahead", arquivos, _base({}))[0]


def test_push_so_base_sem_rotulo_continua_bloqueado():
    d = am.decidir(["motor/a.py"], [], [], APROVADORES, "synchronize", (True, "o push só juntou a main"))
    assert not d.passa


def test_conferir_push_usa_ponta_da_main_e_base_do_evento():
    class Falso:
        def comparar(self, antes, depois):
            assert (antes, depois) == ("A", "B")
            return "ahead", [_arquivo("motor/a.py", "novo")]

        def ponta(self, ramo):
            assert ramo == "main"
            return "PONTA"

        def blob(self, caminho, ref):
            return {"PONTA": "novo", "BASE": "velho"}[ref]

    evento = {"before": "A", "after": "B", "pull_request": {"base": {"ref": "main", "sha": "BASE"}}}
    assert am.conferir_push(Falso(), evento)[0]
    assert not am.conferir_push(Falso(), {"before": None, "after": "B", "pull_request": {}})[0]
