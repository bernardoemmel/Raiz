"""O site recebe apenas resumo; o manifesto e os pacotes completos continuam privados."""

import copy
import hashlib
import json
from unittest.mock import Mock

import pytest

from raiz.lote.publicos import CAMINHOS, OPCOES, baixar_resumo, projetar


def manifesto():
    resumo = {
        "titulares": 6,
        "reservas": 4,
        "ha_lote": 100,
        "volume_creditos": 1000,
        "preco_contrato_usd": 55,
        "custo_credito_usd_medio": 17,
        "faixa": {"carteira": {"p10": 800, "p50": 1200, "p90": 1500}},
        "creditos_lote_faixa": {"p10": 10, "p50": 20, "p90": 30},
        "certidoes": {
            "por_caminho": {c: {"fazendas": 10 if c == "matricula_a_conferir" else 0} for c in CAMINHOS},
            "pedir": ["CAR-PRIVADO"],
        },
        "oferta": {"creditos_terra_pronta": 90000000},
        "o_que_destrava": [{"pendencia": "SEGREDO-PRIVADO"}],
        "itens": [{"cod_imovel": "CAR-PRIVADO", "geometria": {"type": "Polygon"}}],
        "economia": {"tir_alavancada_pct": 25},
    }
    return {
        "uf": "PA",
        "cenario": "central_r11",
        "modelo_versao": "restauracao-2026d+abc123",
        "municipios_calculados": 144,
        "imoveis_calculados": 345870,
        "resumos": {k: copy.deepcopy(resumo) for k in OPCOES},
        "arquivos": {"barata": {"api_url": "https://privado.invalid/pacote.tar.gz"}},
    }


def test_projecao_positiva_nao_confunde_oferta_com_terra_documentada_do_lote():
    p = projetar(manifesto(), "2026-11-12T20:00:00Z")
    for o in p["opcoes"]:
        assert set(o) == {"id", "creditos", "hectares", "fazendas", "custo_usd_credito", "terra_pronta"}
        assert o["fazendas"] == 10
        assert o["creditos"] == {"p10": 800, "p50": 1200, "p90": 1500}
        assert o["terra_pronta"] == {"creditos_p50": 0, "fracao_meta": 0}
    texto = json.dumps(p)
    for proibido in ("PRIVADO", "cod_imovel", "Polygon", "economia", "tir", "destrava", "tar.gz", "api_url"):
        assert proibido not in texto


def test_terra_parcial_nao_rateia_creditos_por_fazendas_e_ausencia_nao_vira_zero():
    m = manifesto()
    por = m["resumos"]["barata"]["certidoes"]["por_caminho"]
    por["matricula_conferida"]["fazendas"] = 3
    por["matricula_a_conferir"]["fazendas"] = 7
    m["resumos"]["segura"]["certidoes"] = {}
    por = m["resumos"]["compacta"]["certidoes"]["por_caminho"]
    por["matricula_conferida"]["fazendas"] = 10
    por["matricula_a_conferir"]["fazendas"] = 0
    p = projetar(m, "2026-11-12T20:00:00Z")
    assert p["opcoes"][0]["terra_pronta"]["creditos_p50"] is None
    assert p["opcoes"][1]["terra_pronta"]["creditos_p50"] is None
    assert p["opcoes"][2]["terra_pronta"] == {"creditos_p50": 1200, "fracao_meta": 1}


def test_grupo_pequeno_conserva_contagem_mas_suprime_medidas_e_rejeita_faixa_invertida():
    m = manifesto()
    m["resumos"]["barata"].update(titulares=2, reservas=2)
    m["resumos"]["segura"]["faixa"]["carteira"]["p10"] = 1600
    p = projetar(m, "2026-11-12T20:00:00Z")
    assert p["opcoes"][0] == {
        "id": "barata",
        "creditos": None,
        "hectares": None,
        "fazendas": 4,
        "custo_usd_credito": None,
        "terra_pronta": {"creditos_p50": None, "fracao_meta": None},
    }
    assert p["opcoes"][1]["creditos"] is None


def test_cenarios_heterogeneos_falham_antes_de_publicar():
    m = manifesto()
    m["resumos"]["compacta"]["volume_creditos"] = 2000
    with pytest.raises(ValueError, match="mesmo pedido"):
        projetar(m, "2026-11-12T20:00:00Z")


def armazem():
    dados = json.dumps(manifesto()).encode()
    digest = hashlib.sha256(dados).hexdigest()
    ativo = {
        "id": 1,
        "name": f"lote_PA_central_r11_retomada_123_1_{digest[:16]}.json",
        "size": len(dados),
        "updated_at": "2026-11-12T20:00:00Z",
        "digest": f"sha256:{digest}",
    }
    arm = Mock()
    arm._exigir_privado.return_value = {"id": 123, "draft": True}
    arm._assets.return_value = [
        ativo,
        {"name": "lote_PA_central_r11_retomada_123_1_barata_abc.tar.gz"},
        {"name": "estados.json"},
    ]
    arm._baixar_ativo.return_value = dados
    return arm, ativo


def test_baixa_apenas_manifesto_e_confere_hash_antes_da_projecao():
    arm, ativo = armazem()
    assert baixar_resumo(arm)["estado"] == "publicado"
    arm._exigir_privado.assert_called_once()
    arm._baixar_ativo.assert_called_once_with(ativo)
    arm._baixar_ativo.return_value += b" "
    with pytest.raises(ValueError, match="Tamanho divergente"):
        baixar_resumo(arm)
    arm, ativo = armazem()
    ativo["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="Digest divergente"):
        baixar_resumo(arm)


def test_release_aberto_e_manifesto_incompleto_nao_produzem_saida_publica():
    arm, _ = armazem()
    arm._exigir_privado.side_effect = PermissionError("Release publicado")
    with pytest.raises(PermissionError):
        baixar_resumo(arm)
    arm._baixar_ativo.assert_not_called()
    arm, ativo = armazem()
    ativo["size"] = 2_000_001
    with pytest.raises(ValueError, match="limite de tamanho"):
        baixar_resumo(arm)
    arm._baixar_ativo.assert_not_called()


@pytest.mark.parametrize("prefixo", ["", "modelo-"])
def test_identificador_de_modelo_nao_publica_documento_civil(prefixo):
    from testes.test_privacidade import CNPJ, CPF

    for documento in (CPF, CNPJ, "".join(c for c in CPF if c.isdigit()), "".join(c for c in CNPJ if c.isalnum())):
        m = manifesto()
        m["modelo_versao"] = prefixo + documento
        with pytest.raises(ValueError, match="Versão de modelo inválida"):
            projetar(m, "2026-11-12T20:00:00Z")


# --- resumo nacional por UF, bioma e Brasil ---------------------------------------------------------------------


def _opcao(fazendas=12, hectares=900.5, sob="nao_verificada"):
    return {
        "fazendas": fazendas,
        "pequenas": 3,
        "hectares": hectares,
        "creditos": {"p10": 800, "p50": 1200, "p90": 1500},
        "fecha_meta": True,
        "sobreposicao": sob,
    }


def _consulta(fazendas=12, espera=40):
    return {
        "pacote": {"nome": "privado.tar.gz", "url": "https://privado.invalid/x"},
        "pedido": {"segredo": "SEGREDO-PRIVADO"},
        "resumo": {
            "opcoes": {o: _opcao(fazendas) for o in OPCOES},
            "terra_em_espera": {
                "incluida_no_pedido": False,
                "fazendas": espera,
                "pequenas": 9,
                "hectares": 5000,
                "soma_creditos_p50": 77000,
            },
            "sobreposicao": "nao_verificada",
        },
    }


def ponteiro():
    return {
        "acesso": "privado",
        "ufs": {"PA": {"fontes": "PRIVADO"}},
        "consultas": {
            "PA": _consulta(),
            "BA": _consulta(fazendas=0, espera=300),
            "Cerrado": _consulta(),
            "Brasil": _consulta(),
            "Recorte Estranho": _consulta(),
        },
    }


def test_nacional_lista_positiva_por_uf_bioma_e_brasil():
    from raiz.lote.publicos import projetar_nacional

    p = projetar_nacional(ponteiro(), "2026-11-16T20:00:00Z")
    assert p["estado"] == "publicado" and p["contrato"] == "publico_lotes_nacional"
    assert [(r["tipo"], r["nome"]) for r in p["recortes"]] == [
        ("brasil", "Brasil"),
        ("bioma", "Cerrado"),
        ("uf", "BA"),
        ("uf", "PA"),
    ]  # o recorte desconhecido fica de fora
    texto = json.dumps(p)
    assert not any(x in texto for x in ("PRIVADO", "privado.invalid", "SEGREDO", "tar.gz", "cod_imovel"))
    pa = next(r for r in p["recortes"] if r["nome"] == "PA")
    assert set(pa) == {"nome", "tipo", "opcoes", "terra_em_espera", "sobreposicao", "vazio"}
    assert pa["opcoes"]["barata"]["creditos"] == {"p10": 800, "p50": 1200, "p90": 1500}
    # terra em espera separada da pronta e nunca habilita venda
    assert pa["terra_em_espera"]["fazendas"] == 40 and pa["terra_em_espera"]["habilita_venda"] is False
    assert pa["terra_em_espera"]["creditos_p50"] == 77000
    # sobreposição: enquanto o catálogo não trouxer a camada, não verificada
    assert pa["sobreposicao"] == "nao_verificada" and pa["opcoes"]["segura"]["sobreposicao"] == "nao_verificada"


def test_nacional_lote_vazio_mostra_a_terra_em_espera_que_o_explica():
    from raiz.lote.publicos import projetar_nacional

    ba = next(r for r in projetar_nacional(ponteiro(), "2026-11-16T20:00:00Z")["recortes"] if r["nome"] == "BA")
    assert ba["vazio"] is True and ba["terra_em_espera"]["fazendas"] == 300


def test_nacional_esconde_medida_de_grupo_pequeno_e_so_aceita_situacao_conhecida():
    from raiz.lote.publicos import projetar_nacional

    pt = ponteiro()
    pt["consultas"]["PA"]["resumo"]["opcoes"]["barata"] = _opcao(fazendas=4, sob="qualquer-coisa")
    p = projetar_nacional(pt, "2026-11-16T20:00:00Z")
    o = next(r for r in p["recortes"] if r["nome"] == "PA")["opcoes"]["barata"]
    assert o["fazendas"] == 4 and o["hectares"] is None and o["creditos"] is None and o["fecha_meta"] is None
    assert o["sobreposicao"] == "nao_verificada"  # texto desconhecido nunca vira "verificada"


def test_nacional_ponteiro_fora_do_contrato_e_ausente():
    from raiz.lote.publicos import baixar_nacional, projetar_nacional

    with pytest.raises(ValueError):
        projetar_nacional({"acesso": "publico", "consultas": {}}, "2026-11-16T20:00:00Z")
    arm = Mock()
    arm._baixar_asset.return_value = b""
    assert baixar_nacional(arm)["estado"] == "ausente"
    arm._baixar_asset.return_value = json.dumps(ponteiro()).encode()
    assert baixar_nacional(arm)["estado"] == "publicado"
    arm._exigir_privado.assert_called()


def test_nacional_acompanha_o_formato_real_do_ponteiro():
    """O resumo que o ponteiro grava (resumo_consulta) é o que a projeção lê."""
    from raiz.lote.publicos import BIOMAS, UFS, projetar_nacional
    from raiz.restauracao.nacional import BIOMAS as B
    from raiz.restauracao.nacional import UFS as U
    from raiz.restauracao.nacional_rodada import resumo_consulta

    assert (UFS, BIOMAS) == (U, B)
    resultado = {
        "opcoes": {o: {"fazendas": 8, "pequenas": 2, "area_ha": 123.4, "creditos": {"p10": 1, "p50": 2, "p90": 3},
                       "fecha_meta": False, "sobreposicao_situacao": "nao_verificada"} for o in OPCOES},
        "terra_em_espera": {"incluida_no_pedido": False, "fazendas": 7, "pequenas": 1, "hectares": 55.0,
                            "soma_creditos_p50": 10.0},
        "sobreposicao": {"situacao": "nao_verificada", "aviso": "x"},
    }  # fmt: skip
    p = projetar_nacional(
        {"acesso": "privado", "consultas": {"PA": {"resumo": resumo_consulta(resultado)}}}, "2026-11-16T20:00:00Z"
    )
    r = p["recortes"][0]
    assert r["opcoes"]["barata"]["hectares"] == 123.4 and r["terra_em_espera"]["fazendas"] == 7
