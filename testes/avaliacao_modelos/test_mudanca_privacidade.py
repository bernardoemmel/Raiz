import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from raiz.avaliacao.contratos import FunilFixo, Inclusao, MembroFunil, PlanoMudanca
from raiz.avaliacao.integridade import conferir_plano_fixado, congelar, fixar_plano, resumo_hash
from raiz.avaliacao.mudanca import avaliar
from scripts.avaliar_modelos import main
from testes.avaliacao_modelos.fixtures import DIA, ensaio, id_, inclusoes


def test_candidato_melhor_com_controle_estavel_e_subgrupos_aprova():
    e = ensaio()
    r = avaliar(e)
    assert r["aprovado"] and r["acao"] == "elegivel_para_revisao"
    assert len(r["subgrupos"]) == 3
    assert all(x["crps_candidata"] < x["crps_anterior"] for x in r["subgrupos"])


@pytest.mark.parametrize("campo", ["anteriores", "gabaritos", "inclusoes"])
def test_nao_pode_trocar_gabarito_previsao_antiga_ou_denominador(campo):
    e = ensaio()
    itens = list(getattr(e, campo))
    chave, valor = {
        "anteriores": ("sorteios", (1.0, 2.0, 3.0)),
        "gabaritos": ("valor", 99.0),
        "inclusoes": ("aptidao", "baixa"),
    }[campo]
    itens[0] = itens[0].model_copy(update={chave: valor})
    with pytest.raises(ValueError, match="diverge|divergem"):
        avaliar(e.model_copy(update={campo: tuple(itens)}))


def test_nao_pode_retocar_limite_depois_do_treino():
    d = ensaio().plano.model_dump()
    d["fixado_em"] = d["inicio_treino_em"] + timedelta(seconds=1)
    with pytest.raises(ValidationError):
        PlanoMudanca.model_validate(d)


def test_versao_candidata_nao_pode_usar_gabarito_revelado():
    e = ensaio()
    cs = tuple(c.model_copy(update={"emitida_em": e.gabaritos[0].revelado_em}) for c in e.candidatas)
    with pytest.raises(ValueError, match="revelado"):
        avaliar(e.model_copy(update={"candidatas": cs}))


@pytest.mark.parametrize("problema", ["subgrupo", "controle", "equidade"])
def test_regressao_exige_manter_ou_retornar_a_versao_anterior(problema):
    e = ensaio()
    if problema == "subgrupo":
        cs = tuple(c.model_copy(update={"sorteios": (50.0, 51.0)}) if i < 30 else c for i, c in enumerate(e.candidatas))
        e = e.model_copy(update={"candidatas": cs})
    elif problema == "controle":
        e = e.model_copy(update={"medicoes_controle": (e.medicoes_controle[0].model_copy(update={"valor": 14.0}),)})
    else:
        e = e.model_copy(
            update={"inclusoes": tuple(x.model_copy(update={"entrou": x.porte != "pequena"}) for x in e.inclusoes)}
        )
    r = avaliar(e)
    assert not r["aprovado"] and r["acao"] == "manter_ou_retornar_anterior"


def test_sem_controle_no_dia_da_medicao_reprova():
    e = ensaio()
    m = e.medicoes_controle[0].model_copy(update={"medido_em": DIA + timedelta(days=370)})
    with pytest.raises(ValueError, match="sem controle"):
        avaliar(e.model_copy(update={"medicoes_controle": (m,)}))


def test_arquivo_nao_sobrescreve_previsoes_antigas_e_detecta_adulteracao(tmp_path):
    e = ensaio()
    h = congelar(tmp_path, list(e.anteriores))
    original = (tmp_path / f"{h}.json").read_bytes()
    assert congelar(tmp_path, list(e.anteriores)) == h
    assert congelar(tmp_path, list(e.candidatas)) != h
    assert (tmp_path / f"{h}.json").read_bytes() == original
    (tmp_path / f"{h}.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="adulterado"):
        congelar(tmp_path, list(e.anteriores))


def test_funil_preserva_inelegiveis_e_desconhecidos_no_denominador():
    estrato = ensaio().gabaritos[0].estrato
    ms = (
        MembroFunil(
            caso_id=id_(1), estrato=estrato, elegibilidade="elegivel", disposicao="nao_abordado", motivo="nenhum"
        ),
        MembroFunil(
            caso_id=id_(2),
            estrato=estrato,
            elegibilidade="desconhecida",
            disposicao="sem_resposta",
            motivo="desconhecido",
        ),
    )
    f = FunilFixo(
        coorte_id=id_(3),
        fixado_em=DIA,
        corte_em=DIA,
        denominador=2,
        membros=ms,
        manifesto_ids_sha256=resumo_hash(sorted(str(x.caso_id) for x in ms)),
    )
    d = f.model_dump()
    d["membros"] = d["membros"][:1]
    d["denominador"] = 1
    with pytest.raises(ValidationError, match="coorte mudou"):
        FunilFixo.model_validate(d)


@pytest.mark.parametrize("campo", ["nome", "cpf", "cnpj", "telefone", "email", "contato", "cod_imovel"])
def test_esquema_rejeita_identificacao_civil_e_contato(campo):
    d = inclusoes()[0].model_dump()
    d[campo] = "conteudo-pessoal-nao-deve-aparecer"
    with pytest.raises(ValidationError) as erro:
        Inclusao.model_validate(d)
    assert "conteudo-pessoal" not in str(erro.value)


def test_cli_e_arquivo_privado_falham_sem_vazar_entrada(tmp_path, capsys):
    entrada = tmp_path / "entrada.json"
    entrada.write_text('{"nome":"conteudo-pessoal-nao-deve-aparecer"}')
    assert main([str(entrada), "--arquivo-privado", str(tmp_path / "arquivo")]) == 1
    assert "conteudo-pessoal" not in capsys.readouterr().out
    e = ensaio()
    entrada.write_text(e.model_dump_json())
    assert main([str(entrada), "--arquivo-privado", str(tmp_path / "arquivo")]) == 1
    capsys.readouterr()
    fixar_plano(tmp_path / "arquivo", e.plano, agora=e.plano.fixado_em)
    assert main([str(entrada), "--arquivo-privado", str(tmp_path / "arquivo")]) == 0
    assert json.loads(capsys.readouterr().out)["aprovado"]
    assert len(list((tmp_path / "arquivo").glob("*.json"))) == 6


def test_plano_precisa_ser_recebido_antes_do_treino_e_nao_admite_troca(tmp_path):
    p = ensaio().plano
    with pytest.raises(ValueError, match="retroativamente"):
        fixar_plano(tmp_path, p, agora=p.inicio_treino_em)
    fixar_plano(tmp_path, p, agora=p.fixado_em)
    conferir_plano_fixado(tmp_path, p)
    with pytest.raises(ValueError, match="já fixado"):
        fixar_plano(tmp_path, p, agora=p.fixado_em)
    alterado = p.model_copy(update={"mudancas": ("pesos",)})
    with pytest.raises(ValueError, match="não coincide"):
        conferir_plano_fixado(tmp_path, alterado)
