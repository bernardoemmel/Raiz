"""Reprocessamento progressivo (docs/reprocessamento-progressivo.md): o site só troca um estado quando ele inteiro foi
refeito com as regras novas; até lá, os dados que estão no ar ficam intactos. A fila abre poucas vagas para refazer
estados prontos durante a conclusão dos funis. O GitHub é simulado (sem rede)."""

import json

import pytest

from raiz.executor import reprocessamento as R
from raiz.executor.publicacao_aberta import validar_asset_publico
from testes.test_armazem_release import _armazem, gh  # noqa: F401 - fixture
from testes.test_processar_estados import F, O, S, _pedido, _run

V = {"funil": "funil-novo", "terra": "terra-novo", "comprometida": "comprometida-novo"}


def _marca(versoes=V, erro=None, vazio=False):
    tarefas = {n: {"versao": v, "saidas": {"x": "y"}} for n, v in versoes.items()}
    if vazio:
        tarefas = {"funil": {"versao": versoes["funil"], "saidas": {}, "vazio": True}}
    if erro:
        tarefas[erro]["erro"] = "RuntimeError: falhou"
    return {"tarefas": tarefas}


# ---------------------------------------------------------------- avaliar


def test_estado_so_fica_atualizado_com_todos_os_municipios_em_dia():
    marcas = {1: _marca(), 2: _marca(vazio=True), 3: _marca()}
    r = R.avaliar(marcas.get, [1, 2, 3], V, completo=True)
    assert (r["situacao"], r["prontos"], r["total"], r["motivo"]) == ("atualizado", 3, 3, None)
    assert r["geracao"] == R.regras_vigentes()["geracao"]
    # O índice ainda diz incompleto (falta uma tabela): não troca.
    assert R.avaliar(marcas.get, [1, 2, 3], V, completo=False)["situacao"] == "reprocessando"


@pytest.mark.parametrize(
    "marca,motivo",
    [
        (None, "falta_municipio"),
        (_marca(erro="terra"), "tarefa_com_erro"),
        (_marca({**V, "terra": "terra-antigo"}), "tarefa_desatualizada"),
    ],
)
def test_municipio_atrasado_segura_o_estado(marca, motivo):
    marcas = {1: _marca(), 2: marca}
    r = R.avaliar(marcas.get, [1, 2], V, completo=True)
    assert (r["situacao"], r["prontos"], r["motivo"]) == ("reprocessando", 1, motivo)


# ---------------------------------------------------------------- decidir


def _privado(situacao="reprocessando", municipios=144, versoes=V, prontos=10):
    return {"municipios": municipios, "sem_imoveis": 0, "versoes": versoes,
            "reprocessamento": {"geracao": "2026-11-17", "situacao": situacao, "prontos": prontos, "total": 144,
                                "motivo": None if situacao == "atualizado" else "tarefa_desatualizada"}}  # fmt: skip


ANTIGA = {"municipios": 144, "sem_imoveis": 0, "versoes": {"funil": "funil-velho"}}


def test_estado_sendo_refeito_nao_mexe_no_que_esta_no_ar():
    d = R.decidir(_privado(), ANTIGA, None)
    assert d["publicar"] is False
    assert d["status"]["situacao"] == "reprocessando" and d["status"]["prontos"] == 10
    assert "geracao" not in d["status"]  # o que está no ar é das regras antigas


def test_estado_fechado_troca_de_uma_vez():
    d = R.decidir(_privado("atualizado", prontos=144), ANTIGA, {"situacao": "reprocessando"})
    assert d["publicar"] is True
    assert d["status"]["situacao"] == "atualizado" and d["status"]["geracao"] == "2026-11-17"


def test_troca_recusada_se_o_novo_tem_menos_municipios_que_o_publicado():
    d = R.decidir(_privado("atualizado", municipios=100, prontos=144), ANTIGA, None)
    assert d["publicar"] is False and d["status"]["motivo"] == "validacao_menos_municipios"


def test_estado_sem_nada_no_ar_publica_aos_poucos():
    assert R.decidir(_privado(), None, None)["publicar"] is True


def test_mesmas_regras_que_estao_no_ar_continuam_crescendo():
    """Funil de estado novo avançando com a mesma versão: não há mistura de regras."""
    no_ar = {"municipios": 50, "versoes": V}
    d = R.decidir({**_privado(), "municipios": 60}, no_ar, {"situacao": "atualizado", "geracao": "2026-11-17"})
    assert d["publicar"] is True and d["status"]["situacao"] == "atualizado"
    legado = R.decidir({"municipios": 60}, {"municipios": 50}, None)  # índices sem versões: comportamento antigo
    assert legado["publicar"] is True and legado["status"]["situacao"] == "antigo"


def test_sem_avaliacao_e_versoes_diferentes_segura():
    d = R.decidir({"municipios": 144, "versoes": V}, ANTIGA, None)
    assert d["publicar"] is False and d["status"]["motivo"] == "sem_avaliacao"


# ---------------------------------------------------------------- arquivo público


def test_reprocessamento_json_e_um_contrato_fechado():
    dados = R.montar_status_publico({}, "PA", {"situacao": "reprocessando", "prontos": 3, "total": 144})
    validar_asset_publico("reprocessamento.json", dados)
    doc = json.loads(dados)
    doc["estados"]["PA"]["cod_imovel"] = "PA-1504950-" + "A" * 32
    with pytest.raises(ValueError):
        validar_asset_publico("reprocessamento.json", json.dumps(doc).encode())
    doc["estados"]["PA"] = {"situacao": "qualquer"}
    with pytest.raises(ValueError):
        R.validar_status_publico(json.dumps(doc).encode())


def test_montar_preserva_os_outros_estados():
    um = json.loads(R.montar_status_publico({}, "PA", {"situacao": "reprocessando"}))
    dois = json.loads(R.montar_status_publico(um, "AC", {"situacao": "atualizado", "geracao": "2026-11-17"}))
    assert set(dois["estados"]) == {"AC", "PA"}
    assert not R.mudou(dois["estados"]["AC"], {"situacao": "atualizado", "geracao": "2026-11-17",
                                               "atualizado_em": "2026-11-18T00:00:00+00:00"})  # fmt: skip


# ---------------------------------------------------------------- armazém


def test_publicar_aberto_segura_o_estado_e_so_grava_o_andamento(gh, tmp_path, monkeypatch):  # noqa: F811
    a = _armazem(gh, tmp_path / "espelho")
    a.publico = _armazem(gh, tmp_path / "aberto", privado=False)
    monkeypatch.setattr(a.publico, "manifesto", lambda fresco=False: {"estados": {"PA": ANTIGA}})
    monkeypatch.setattr(a.publico, "status_reprocessamento", lambda: {})
    gravados = []
    monkeypatch.setattr(a.publico, "gravar_status_reprocessamento", lambda uf, s: gravados.append((uf, s)))
    monkeypatch.setattr(a.publico, "_subir", lambda *x, **k: pytest.fail("não pode trocar o pacote no ar"))
    a._publicar_aberto("PA", _privado())
    assert gravados and gravados[0][0] == "PA" and gravados[0][1]["situacao"] == "reprocessando"
    assert not gh.uploads


def test_andamento_gravado_no_release_aberto(gh, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    aberto = _armazem(gh, tmp_path / "aberto", privado=False)
    aberto.gravar_status_reprocessamento("PA", {"situacao": "reprocessando", "prontos": 1, "total": 144})
    assert gh.uploads == ["reprocessamento.json"]
    assert aberto.status_reprocessamento()["estados"]["PA"]["prontos"] == 1
    aberto.gravar_status_reprocessamento("PA", {"situacao": "reprocessando", "prontos": 1, "total": 144})
    assert gh.uploads == ["reprocessamento.json"]  # nada mudou: não regrava


def test_estado_segurado_nao_conta_como_aberto_atrasado(gh, tmp_path, monkeypatch):  # noqa: F811
    a = _armazem(gh, tmp_path / "espelho")
    a.publico = _armazem(gh, tmp_path / "aberto", privado=False)
    monkeypatch.setattr(a, "_exigir_privado", lambda: {"id": 7})
    privado = {
        "PA": {**_privado(), "atualizado_em": "2026-11-17T08:00:00+00:00"},
        "AC": {**_privado("atualizado", municipios=22, prontos=22), "atualizado_em": "2026-11-17T08:00:00+00:00"},
    }
    aberto = {
        "PA": {**ANTIGA, "atualizado_em": "2026-11-15T00:00:00+00:00"},
        "AC": {"municipios": 22, "versoes": {"funil": "funil-velho"}, "atualizado_em": "2026-11-15T00:00:00+00:00"},
    }
    monkeypatch.setattr(a, "manifesto", lambda fresco=False: {"estados": privado})
    monkeypatch.setattr(a.publico, "manifesto", lambda fresco=False: {"estados": aberto})
    monkeypatch.setattr(a.publico, "status_reprocessamento", lambda: {})
    assert a.defasados_no_aberto() == ["AC"]  # PA ainda refazendo; AC fechou e vai para o site


# ---------------------------------------------------------------- fila


def test_fila_abre_vagas_limitadas_para_refazer_estados_prontos(monkeypatch):
    monkeypatch.setenv("RAIZ_PRIORIDADE_FUNIL", "1")
    estado = {**F.vazio(), "planejadores": ["1"]}
    reproc = [{**_pedido(uf), "reprocessar": True} for uf in ("AC", "AP", "RO")]
    comum = _pedido("RR")  # sem a marca: continua guardado como antes
    escolhidos = F.admitir(estado, {"1": _run()}, "1", [*reproc, comum, _pedido("TO-1001")], O._e_unidade,
                           funis_prontos={"AC", "AP", "RO", "RR"}, limite_reprocessamento=2)  # fmt: skip
    refeitos = [p["unidade"] for p in escolhidos if p.get("reprocessar")]
    assert len(refeitos) == 2 and set(refeitos) <= {"AC", "AP", "RO"}  # na ordem da Amazônia Legal
    assert "RR" not in {p["unidade"] for p in escolhidos}
    assert "TO-1001" in {p["unidade"] for p in escolhidos}
    # Com as duas vagas ocupadas, o terceiro espera.
    resto = next(p for p in reproc if p["unidade"] not in refeitos)
    outro = F.admitir(estado, {"1": _run(*refeitos, "TO-1001"), "2": _run()}, "2", [resto], O._e_unidade,
                      funis_prontos={"AC", "AP", "RO", "RR"}, limite_reprocessamento=2)  # fmt: skip
    assert outro == []


def test_sem_limite_nada_de_reprocessamento_durante_a_prioridade(monkeypatch):
    monkeypatch.setenv("RAIZ_PRIORIDADE_FUNIL", "1")
    estado = {**F.vazio(), "planejadores": ["1"]}
    pedido = {**_pedido("AC"), "reprocessar": True}
    assert F.admitir(estado, {"1": _run()}, "1", [pedido], O._e_unidade, funis_prontos={"AC"}) == []


def test_precisa_reprocessar_le_a_avaliacao_do_indice_privado():
    atual = {"funil": "f2", "terra": "t2"}
    assert O.precisa_reprocessar({"municipios": 22}, atual) == "reprocessar com as regras novas"
    em_dia = {"reprocessamento": {"situacao": "atualizado", "versoes": dict(sorted(atual.items()))}}
    assert O.precisa_reprocessar(em_dia, atual) is None
    meio = {"reprocessamento": {"situacao": "reprocessando", "prontos": 5, "total": 22, "versoes": atual}}
    assert "5 de 22" in O.precisa_reprocessar(meio, atual)


def test_plano_adiciona_reprocessamento_sem_tirar_vaga_dos_funis(monkeypatch):
    from testes.test_processar_estados import _completo

    estados = {uf: _completo(uf) for uf in S.TOTAL_IBGE if uf not in {"TO", "MA", "MT", "AM"}}
    monkeypatch.setenv("RAIZ_PRIORIDADE_FUNIL", "1")
    monkeypatch.setenv("RAIZ_VAGAS", "6")
    monkeypatch.setattr(O, "VAGAS", 6)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(S, "ler_manifesto", lambda: {"estados": estados})
    monkeypatch.setattr(O, "versoes_executor", lambda: {"funil": "nova"})
    monkeypatch.setattr(O, "ufs_ativas", lambda: (set(), 0))
    escolhidas = O.planejar([], set())
    funis = [u for u in escolhidas if u.split("-")[0] in {"AM", "MT", "TO", "MA"}]
    assert len(funis) == len(escolhidas)  # as 6 vagas ficam com os funis
    monkeypatch.setattr(O, "VAGAS", 15)
    # Pedido explícito de estado pronto vira reprocessamento, até o limite de vagas, sem puxar os funis junto.
    assert O.planejar(S.unidades("AC"), set()) == S.unidades("AC")[: O.VAGAS_REPROCESSAMENTO]


# ---------------------------------------------------------------- sobreposição com projetos de carbono


def test_assinatura_do_funil_muda_so_com_projeto_que_toca_o_municipio(tmp_path, monkeypatch):
    from raiz.executor import tarefas as T

    pasta = tmp_path / "projetos_carbono"
    pasta.mkdir()
    monkeypatch.setattr("raiz.funil.rodar.dir_trabalho", lambda: tmp_path)

    def projeto(nome, x0, y0):
        caixa = [[x0, y0], [x0 + 1, y0], [x0 + 1, y0 + 1], [x0, y0 + 1], [x0, y0]]
        (pasta / nome).write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [caixa]}}
                    ],
                }
            )
        )

    caixa_mun = [-52.0, -7.0, -51.5, -6.5]
    sem = T._projetos_na_caixa(caixa_mun)
    projeto("longe.geojson", -40.0, -20.0)
    assert T._projetos_na_caixa(caixa_mun) == sem  # projeto em outro canto não refaz este município
    projeto("perto.geojson", -52.2, -7.2)
    assert T._projetos_na_caixa(caixa_mun) != sem
