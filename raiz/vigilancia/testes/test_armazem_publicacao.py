"""Armazém (alertas imutáveis, só acréscimo, público e privado separados) e publicação no Release (parte privada
cifrada, manifesto por último, entradas da API juntadas e apagadas)."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from raiz.vigilancia import aprendizado, cruzamento, projetos, publicacao
from raiz.vigilancia.armazem import Armazem
from raiz.vigilancia.testes.conftest import COD_A, HOJE, ReleaseFalso, ocorrencia, ocorrencias, quadrado_m


@pytest.fixture
def alertas(poligonos, regras, lista_projetos, cfg):
    areas = projetos.areas(lista_projetos[0], cfg)
    oc = ocorrencias(
        ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(100, 100, 100), HOJE, HOJE),
        ocorrencia("firms", "N20|2026-11-11|0400|0|0", "foco_alta", quadrado_m(500, 500, 375), HOJE),
    )
    pares = pd.concat(
        [cruzamento.cruzar_imoveis(oc, poligonos), cruzamento.cruzar_projetos(oc, areas)], ignore_index=True
    )
    return cruzamento.montar_alertas(oc, pares, regras, HOJE)


def test_alertas_sem_duplicar_e_separados(tmp_path, alertas):
    arm = Armazem(tmp_path)
    novos = arm.gravar_alertas(alertas)
    assert len(novos) == len(alertas)
    assert len(arm.gravar_alertas(alertas)) == 0  # mesma leitura de novo: nada entra
    pub = pd.read_parquet(tmp_path / "publico/alertas/alertas_2026-11.parquet")
    priv = pd.read_parquet(tmp_path / "privado/alertas/alertas_2026-11.parquet")
    assert set(pub.alvo_tipo) == {"imovel"} and set(priv.alvo_tipo) == {"projeto"}
    lidos = arm.alertas("imovel", COD_A)
    assert len(lidos) == 2 and isinstance(lidos.iloc[0]["data_evento"], dt.date)


def test_marcacoes_so_acrescimo_e_entradas(tmp_path, alertas):
    arm = Armazem(tmp_path)
    arm.gravar_alertas(alertas)
    aid = alertas.iloc[0]["alerta_id"]
    m = aprendizado.marcacao(aid, True, "campo", "fundador")
    assert arm.gravar_marcacoes([m]) == 1 and arm.gravar_marcacoes([m]) == 0
    arm.nova_entrada("marcacao", aprendizado.marcacao(aid, False, "cliente", "cliente"))
    arm.nova_entrada(
        "evento",
        {
            "evento_id": "e1",
            "alvo": "perda",
            "alvo_id": "X_LE1",
            "tipo": "nota",
            "data": "2026-11-12",
            "quem": "fundador",
            "nota": "",
            "registrado_em": "x",
        },
    )
    assert len(arm.pendentes("marcacao")) == 1
    assert arm.incorporar_entradas() == {"marcacoes": 1, "eventos": 1}
    assert arm.entradas() == [] and len(arm.marcacoes()) == 2
    with pytest.raises(ValueError):
        arm.nova_entrada("outra_coisa", {})


def test_cifra_e_pacote_deterministico(tmp_path):
    chave = publicacao.gerar_chave()
    assert publicacao.decifrar(publicacao.cifrar(b"segredo", chave), chave) == b"segredo"
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("1")
    assert publicacao.empacotar(tmp_path / "a") == publicacao.empacotar(tmp_path / "a")
    publicacao.desempacotar(publicacao.empacotar(tmp_path / "a"), tmp_path / "b")
    assert (tmp_path / "b" / "x.txt").read_text() == "1"


def test_publicar_e_baixar_com_parte_privada_cifrada(tmp_path, alertas, cfg):
    chave = publicacao.gerar_chave()
    arm = Armazem(tmp_path / "origem")
    arm.gravar_alertas(alertas)
    arm.gravar_fontes({"deter": {"ok": True}})
    arm.gravar_marcacoes([aprendizado.marcacao(alertas.iloc[0]["alerta_id"], True, "campo", "fundador")])
    rel = ReleaseFalso(cfg)
    rel.subir("entrada_1.cifrado", publicacao.cifrar(b'{"tipo":"evento","registro":{}}', chave))
    r = publicacao.publicar(arm, rel, chave, resumo={"n": 1}, entradas_lidas=["entrada_1.cifrado"])
    assert rel.ordem[-1] == publicacao.MANIFESTO  # manifesto por último
    assert "alertas_2026-11.parquet" in rel.arquivos and publicacao.PRIVADO in rel.arquivos
    assert "entrada_1.cifrado" not in rel.arquivos and r["entradas_apagadas"] == 1
    # o que é de projeto não aparece aberto em lugar nenhum do Release
    aberto = b"".join(v for k, v in rel.arquivos.items() if k != publicacao.PRIVADO)
    assert b"PTESTE" not in aberto and b"fundador" not in aberto
    assert b"PTESTE" not in rel.arquivos[publicacao.PRIVADO]
    # publicar de novo sem mudança: só o manifesto sobe
    antes = len(rel.ordem)
    publicacao.publicar(arm, rel, chave)
    assert rel.ordem[antes:] == [publicacao.MANIFESTO]
    # outra máquina baixa tudo; sem a chave, só a parte pública
    destino = Armazem(tmp_path / "destino")
    info = publicacao.baixar_estado(destino, rel, chave)
    assert info["privado"] == "baixado" and len(destino.alertas()) == len(alertas)
    assert len(destino.marcacoes()) == 1
    sem = Armazem(tmp_path / "sem_chave")
    assert publicacao.baixar_estado(sem, rel, None)["privado"] == "sem chave"
    assert set(sem.alertas()["alvo_tipo"]) == {"imovel"}


def test_entrada_da_api_vai_cifrada_e_volta(tmp_path, cfg):
    chave = publicacao.gerar_chave()
    cfg.token_github = "x"
    rel = ReleaseFalso(cfg)
    arm = Armazem(tmp_path / "servidor")
    caminho = arm.nova_entrada("marcacao", aprendizado.marcacao("a1", True, "campo", "fundador"))
    assert publicacao.enviar_entrada(rel, chave, caminho)
    nome = caminho.name.replace(".json", ".cifrado")
    assert b"fundador" not in rel.arquivos[nome]
    rodada = Armazem(tmp_path / "rodada")
    rel.subir(publicacao.MANIFESTO, b'{"arquivos": {}}')
    info = publicacao.baixar_estado(rodada, rel, chave)
    assert info["entradas"] == [nome] and rodada.incorporar_entradas()["marcacoes"] == 1
    assert not publicacao.enviar_entrada(rel, None, caminho)  # sem chave fica só local
