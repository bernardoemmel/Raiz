"""Recorte real por CAR, cobertura explícita e rascunho segregado por dono; sem rede nem envio."""

import datetime as dt
import json
from types import SimpleNamespace

import pytest

from raiz.vigilancia import cruzamento, lotes, rodada
from raiz.vigilancia.armazem import Armazem
from raiz.vigilancia.fontes import Contexto, Leitura
from raiz.vigilancia.fontes import firms as firms_mod
from raiz.vigilancia.testes.conftest import COD_A, COD_B, HOJE, ocorrencia, ocorrencias, quadrado_m

PEDIDO = "e1b28c9d-80ac-460b-9ef8-b4264c80e6c1"
OUTRO = "e1b28c9d-80ac-460b-9ef8-b4264c80e6c2"
AGORA = dt.datetime(2026, 11, 12, 12, tzinfo=dt.UTC)


def _catalogo():
    return {
        "versao": 1,
        "gerado_em": AGORA.isoformat(),
        "lotes": [{"pedido_id": PEDIDO, "cliente_id": 1, "desde": "2026-11-01", "imoveis": [COD_B]}],
    }


def test_catalogo_rejeita_vencido_futuro_e_campos_pessoais():
    base = _catalogo()
    assert lotes.validar_catalogo(base, AGORA)[0].imoveis == (COD_B,)
    for instante in (AGORA - dt.timedelta(hours=37), AGORA + dt.timedelta(minutes=6)):
        with pytest.raises(ValueError, match="vencido ou com data"):
            lotes.validar_catalogo({**base, "gerado_em": instante.isoformat()}, AGORA)
    base["lotes"][0]["nome"] = "não pode entrar no catálogo"
    with pytest.raises(ValueError, match="campo não permitido"):
        lotes.validar_catalogo(base, AGORA)


def test_recorte_preserva_pequena_e_nao_acrescenta_car_de_fonte(poligonos):
    lote = lotes.Lote(PEDIDO, 1, HOJE, (COD_B,))
    pol = lotes.PoligonosLotes(poligonos, [lote])
    assert pol.presentes == {COD_B}
    assert len(pol.imoveis("PA", 1507300)) == 1
    assert float(pol.imoveis("PA", 1507300).iloc[0].alvo_ha) < 1
    oc = ocorrencias(ocorrencia("mapbiomas_alerta", "a", "desmatamento", quadrado_m(0, 0, 1500), HOJE, HOJE))
    fora = "TO-1721000-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
    oc["car_fonte"] = [{fora: 1, COD_A: 1, COD_B: 0.5}]
    pares = cruzamento.cruzar_imoveis(oc, pol)
    assert set(pares.alvo_id) == {COD_B}
    assert pol.info_imovel(COD_A) is None


def test_rodada_deduplica_relatorios_por_dono_e_nao_inventa_projeto(monkeypatch, cfg, poligonos):
    l1 = lotes.Lote(PEDIDO, 1, dt.date(2026, 11, 1), (COD_B,))
    l2 = lotes.Lote(OUTRO, 2, dt.date(2026, 11, 1), (COD_B,))
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(1090, -10, 100), HOJE, HOJE))
    monkeypatch.setattr(rodada, "_ler", lambda *args: Leitura("deter", oc))
    primeira = rodada.rodar(cfg, HOJE, ["deter"], poligonos=poligonos, catalogo_lotes=[l1, l2])
    segunda = rodada.rodar(cfg, HOJE, ["deter"], poligonos=poligonos, catalogo_lotes=[l1, l2])
    assert primeira["lotes"]["imoveis_cobertos"] == 1
    assert segunda["lotes"]["rascunhos_disponiveis"] == 2
    arm = Armazem(cfg.estado)
    documentos = arm.ler_privado_json("rascunhos_lotes.json", {})
    assert len(documentos) == 2 and {d["cliente_id"] for d in documentos.values()} == {1, 2}
    assert len(arm.alertas("imovel")) == 1 and not len(arm.alertas("projeto"))
    assert all(
        d["estado"] == "rascunho_nao_enviado"
        and "não confirma perda" in d["relatorio"]
        and "a preencher pelo desenvolvedor" in d["relatorio"]
        for d in documentos.values()
    )
    resumo = rodada.resumo_markdown(segunda)
    assert PEDIDO not in resumo and OUTRO not in resumo and COD_B not in resumo


def test_falso_positivo_descarta_rascunho_ja_preparado(monkeypatch, cfg, poligonos):
    from raiz.vigilancia.aprendizado import marcacao

    lote = lotes.Lote(PEDIDO, 1, dt.date(2026, 11, 1), (COD_B,))
    oc = ocorrencias(ocorrencia("deter", "d1", "desmatamento_cr", quadrado_m(1090, -10, 100), HOJE, HOJE))
    monkeypatch.setattr(rodada, "_ler", lambda *args: Leitura("deter", oc))
    rodada.rodar(cfg, HOJE, ["deter"], poligonos=poligonos, catalogo_lotes=[lote])
    arm = Armazem(cfg.estado)
    documento = next(iter(arm.ler_privado_json("rascunhos_lotes.json", {}).values()))
    arm.gravar_marcacoes([marcacao(documento["alerta_id"], False, "campo", "campo", observado_em=HOJE)])
    atualizados = lotes.preparar_rascunhos(arm, [lote], HOJE, {COD_B})
    assert len(atualizados) == 1 and atualizados[0]["estado"] == "descartado_por_revisao"
    assert "Não usar" in atualizados[0]["relatorio"]
    assert lotes.preparar_rascunhos(arm, [lote], HOJE, {COD_B}) == []


def test_catalogo_indisponivel_preserva_estado_e_nao_expande_universo(monkeypatch, cfg, poligonos):
    arm = Armazem(cfg.estado)
    arm.gravar_privado_json("rascunhos_lotes.json", {"anterior": {"estado": "rascunho_nao_enviado"}})
    monkeypatch.setattr(lotes, "engine_configurado", lambda: None)
    monkeypatch.setattr(lotes, "carregar_catalogo", lambda *args: (_ for _ in ()).throw(ValueError("catálogo vencido")))
    monkeypatch.setattr(rodada, "_ler", lambda *args: pytest.fail("não deve coletar sem catálogo"))
    res = rodada.rodar(cfg, HOJE, ["deter"], poligonos=poligonos, lotes=True)
    assert res["lotes"]["situacao"] == "erro"
    assert "anterior" in arm.ler_privado_json("rascunhos_lotes.json", {})


def test_noaa20_e21_no_mesmo_car_e_dia_tem_um_rascunho_sem_soma_de_area(monkeypatch, cfg, poligonos):
    lote = lotes.Lote(PEDIDO, 1, dt.date(2026, 11, 1), (COD_B,))
    oc = ocorrencias(
        *[
            ocorrencia("firms", f"{sat}|2026-11-12|0415|0|0", "foco_alta", quadrado_m(1090, -10, 100), HOJE, HOJE)
            for sat in ("N20", "N21")
        ]
    )
    monkeypatch.setattr(rodada, "_ler", lambda *args: Leitura("firms", oc))
    resultado = rodada.rodar(cfg, HOJE, ["firms"], poligonos=poligonos, catalogo_lotes=[lote])
    assert resultado["lotes"]["rascunhos_disponiveis"] == 1
    documento = next(iter(Armazem(cfg.estado).ler_privado_json("rascunhos_lotes.json", {}).values()))
    assert len(documento["alerta_ids"]) == 2 and documento["area_sobreposta_ha"] is None
    assert len(documento["evidencias"]) == 2 and "não são somadas" in documento["relatorio"]


def test_lote_novo_rele_fontes_mesmo_quando_publicacao_nao_mudou(monkeypatch, cfg, poligonos):
    from raiz.vigilancia.fontes import vazio

    estados_recebidos = []

    def ler(nome, ctx, estado, arm, refazer):
        estados_recebidos.append(estado)
        return Leitura(nome, vazio(), cursor={"ultima_publicacao": "2026-11-12"})

    monkeypatch.setattr(rodada, "_ler", ler)
    primeiro = lotes.Lote(PEDIDO, 1, HOJE, (COD_A,))
    segundo = lotes.Lote(OUTRO, 2, HOJE, (COD_B,))
    for selecionados in ([primeiro], [primeiro], [primeiro, segundo]):
        rodada.rodar(cfg, HOJE, ["mapbiomas_alerta"], poligonos=poligonos, catalogo_lotes=selecionados)
    assert estados_recebidos[0] == {} and estados_recebidos[1]["cursor"] and estados_recebidos[2] == {}


def test_catalogo_vazio_e_poligono_ausente_nao_significam_brasil_inteiro(monkeypatch, cfg, poligonos):
    monkeypatch.setattr(rodada, "_ler", lambda *args: pytest.fail("sem alvos processados"))
    vazio = rodada.rodar(cfg, HOJE, ["deter"], poligonos=poligonos, catalogo_lotes=[])
    assert vazio["lotes"]["situacao"] == "ok"
    fora = "TO-1721000-CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"
    incompleto = rodada.rodar(
        cfg, HOJE, ["deter"], poligonos=poligonos, catalogo_lotes=[lotes.Lote(PEDIDO, 1, HOJE, (fora,))]
    )
    assert incompleto["lotes"]["situacao"] == "parcial"
    assert incompleto["lotes"]["imoveis_sem_poligono_processado"] == 1


def test_html_firms_nao_vira_zero_focos_e_falha_parcial_preserva_satelite(monkeypatch, cfg, regras):
    ctx = Contexto(regras, cfg, HOJE)
    csv = "latitude,longitude,acq_date,acq_time,confidence\n-6,-53,2026-11-12,415,h\n"
    with pytest.raises(ValueError, match="não retornou CSV"):
        firms_mod._csv("<html>manutenção</html>", "N20")
    with pytest.raises(ValueError, match="colunas obrigatórias"):
        firms_mod._csv("erro\nserviço indisponível\n", "N20")

    def obter(metodo, url, **kw):
        if "noaa-21" in url:
            raise RuntimeError("fonte fora do ar")
        return SimpleNamespace(text=csv)

    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    monkeypatch.setattr(firms_mod.rede, "pedir", obter)
    leitura = firms_mod.ler(ctx, {})
    assert len(leitura.ocorrencias) == 1
    assert leitura.ocorrencias.iloc[0].atributos["satelite"] == "N20"
    assert set(leitura.extras["falhas"]) == {"N21"}


def test_catalogo_privado_rejeita_campos_extras_e_nao_consulta_release_publico(monkeypatch, cfg):
    from raiz.vigilancia import publicacao

    class Release:
        def __init__(self, configuracao):
            assert configuracao is cfg

        def ativos(self):
            return {lotes.ARQUIVO: {"id": 1}}

        def baixar(self, ativo):
            return json.dumps(_catalogo()).encode()

    monkeypatch.setattr(publicacao, "Release", Release)
    carregados, origem = lotes.carregar_catalogo(cfg, agora=AGORA)
    assert carregados[0].cliente_id == 1 and origem["origem"] == "arquivo_privado"


def test_pixel_com_centro_fora_da_caixa_ainda_cobre_fazenda_pequena(cfg, regras):
    caixa = (-53.001, -6.0005, -53.0005, -5.9995)
    ctx = Contexto(regras, cfg, HOJE, caixas=[caixa])
    df = firms_mod._csv(
        "latitude,longitude,acq_date,acq_time,confidence\n-6,-53,2026-11-12,415,h\n-6,-54,2026-11-12,415,h\n",
        "N20",
    )
    linhas = firms_mod.normalizar(df, ctx)
    assert len(linhas) == 1
    assert linhas[0]["atributos"]["lon"] > caixa[2]
    assert linhas[0]["geometry"].bounds[0] < caixa[0]


def test_cli_catalogo_nao_imprime_corpo_de_erro_do_banco(monkeypatch, capsys):
    from raiz.vigilancia import __main__ as cli

    def falhar():
        raise ValueError("configuração inválida com detalhe privado")

    monkeypatch.setattr(lotes, "engine_configurado", falhar)
    for comando in (["exportar-lotes"], ["exportar-lotes", "--publicar"], ["lotes-ciclo", "--publicar"]):
        assert cli.main(comando) == 1
        saida = capsys.readouterr().out
        assert "ValueError" in saida and "detalhe privado" not in saida
