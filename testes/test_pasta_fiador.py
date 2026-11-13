"""Pasta do lote: falha fechada, fontes, documentos e duas saídas sem dados pessoais."""

import datetime as dt
import io
import json
import zipfile
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from raiz.pasta_fiador.esquema import Documento, FonteCampo, Pasta
from raiz.pasta_fiador.geracao import gerar
from raiz.pasta_fiador.validacao import validar
from raiz.prospeccao_acesso import ErroAcesso
from raiz.prospeccao_protecao import MarcaExportacao

AGORA = dt.datetime(2026, 11, 13, 12, tzinfo=dt.UTC)
CAR = "PA-1504950-" + "A" * 32


def dados_pasta(car=CAR, pedido=None):
    docs = [
        Documento(
            id=uuid4(),
            tipo=t,
            referencia="DOC-" + uuid4().hex.upper(),
            sha256="a" * 64,
            emitido_em=dt.date(2026, 1, 1),
            valido_ate=dt.date(2035, 1, 1),
            conferido_em=dt.datetime(2026, 11, 1, tzinfo=dt.UTC),
            estado="conferido",
        )
        for t in ("area_elegivel", "titularidade", "garantia", "previsao", "preco")
    ]

    def fonte(tipo):
        return [
            FonteCampo(
                documento_id=next(d.id for d in docs if d.tipo == tipo),
                localizador="pagina:1",
                data_referencia=dt.date(2026, 1, 1),
            )
        ]

    def medida(n, unidade="ha", tipo="previsao"):
        return {"valor": str(n), "unidade": unidade, "natureza": "estimado", "fontes": fonte(tipo)}

    periodo = {"inicio": "2027-01-01", "fim": "2052-01-01"}
    return Pasta(
        pedido_id=pedido or uuid4(),
        opcao="segura",
        data_corte=dt.date(2026, 11, 1),
        documentos=docs,
        imoveis=[
            {
                "codigo_car": car,
                "area_elegivel": medida(".25", tipo="area_elegivel"),
                "titulo": {"nivel": "conferencia_concluida", "situacao": "conferida", "fontes": fonte("titularidade")},
                "garantia": {"situacao": "conferida", "fontes": fonte("garantia")},
                "creditos": [
                    {
                        "metodo": "regeneracao_assistida",
                        "previsao_id": uuid4(),
                        "area": medida(".25"),
                        "p10": medida(10, "tCO2e"),
                        "p50": medida(20, "tCO2e"),
                        "p90": medida(30, "tCO2e"),
                        "periodo": periodo,
                        "modelo_versao": "raiz-2026a",
                        "fontes": fonte("previsao"),
                    }
                ],
                "preco": {
                    "valor": "24.90",
                    "moeda": "BRL",
                    "unidade": "tCO2e",
                    "periodo": periodo,
                    "natureza": "estimado",
                    "fontes": fonte("preco"),
                },
            }
        ],
    )


def pacote(pasta):
    return {
        "dados": pasta.model_dump(mode="json"),
        "pasta_id": str(uuid4()),
        "versao_id": str(uuid4()),
        "numero": 1,
        "assinatura": "b" * 64,
        "validacao": validar(pasta, agora=AGORA).model_dump(mode="json"),
        "previsoes": [],
    }


def test_pequena_conferida_tem_fonte_em_cada_valor_e_metadado():
    p = dados_pasta()
    r = validar(p, agora=AGORA)
    assert r.pronto and not r.falhas
    campos = {c.campo: c.fontes for c in r.campos}
    assert campos["imoveis/0/preco/moeda"] and campos["imoveis/0/creditos/0/modelo_versao"]
    assert campos["imoveis/0/area_elegivel/valor"] and campos["imoveis/0/codigo_car"]
    assert p.imoveis[0].area_elegivel.valor == Decimal(".25")


@pytest.mark.parametrize("campo", ["area_elegivel", "titulo", "garantia", "preco", "creditos"])
def test_obrigatorio_falta_impede_pronto_e_geracao(campo):
    p = dados_pasta()
    setattr(p.imoveis[0], campo, [] if campo == "creditos" else None)
    r = validar(p, agora=AGORA)
    assert not r.pronto and any(f.campo.endswith("/" + campo) for f in r.falhas)
    with pytest.raises(ErroAcesso, match="pendentes"):
        gerar(pacote(p), MarcaExportacao("RZP-teste-" + "a" * 32, "teste"))


@pytest.mark.parametrize("campo", ["valor", "moeda", "unidade", "periodo", "natureza"])
def test_preco_nao_inventa_moeda_unidade_periodo_natureza(campo):
    p = dados_pasta()
    setattr(p.imoveis[0].preco, campo, None)
    r = validar(p, agora=AGORA)
    assert not r.pronto and any(f.campo == "imoveis/0/preco/" + campo for f in r.falhas)


@pytest.mark.parametrize("estado", ["apresentado", "revogado", "dispensado"])
def test_garantia_nao_pode_ser_dispensada_ou_nao_conferida(estado):
    p = dados_pasta()
    next(d for d in p.documentos if d.tipo == "garantia").estado = estado
    assert not validar(p, agora=AGORA).pronto


def test_documento_vencido_e_data_futura_sao_pendencias():
    p = dados_pasta()
    p.documentos[0].valido_ate = dt.date(2026, 11, 12)
    assert any(f.codigo == "documento_vencido" for f in validar(p, agora=AGORA).falhas)
    p.documentos[0].valido_ate = dt.date(2035, 1, 1)
    p.documentos[0].conferido_em = AGORA + dt.timedelta(seconds=1)
    assert not validar(p, agora=AGORA).pronto


def test_substituicao_exige_atualizar_fonte_e_preserva_original():
    p = dados_pasta()
    anterior = p.documentos[0]
    novo = anterior.model_copy(deep=True)
    novo.id = uuid4()
    novo.sha256 = "b" * 64
    p.documentos.append(novo)
    anterior.estado = "substituido"
    anterior.substituido_por = novo.id
    anterior.motivo = "nova_via"
    assert not validar(p, agora=AGORA).pronto
    p.imoveis[0].area_elegivel.fontes[0].documento_id = novo.id
    assert validar(p, agora=AGORA).pronto
    novo.estado = "substituido"
    novo.substituido_por = anterior.id
    novo.motivo = "correcao"
    assert any(f.codigo == "substituicao_invalida" for f in validar(p, agora=AGORA).falhas)


def test_dispensa_complementar_exige_documento_de_autorizacao():
    p = dados_pasta()
    autorizacao = p.documentos[0].model_copy(deep=True)
    autorizacao.id = uuid4()
    autorizacao.tipo = "dispensa"
    p.documentos.append(autorizacao)
    dispensado = Documento(
        id=uuid4(),
        tipo="complementar",
        referencia="DOC-" + "C" * 12,
        estado="dispensado",
        motivo="nao_aplicavel",
        dispensa_documento_id=autorizacao.id,
    )
    p.documentos.append(dispensado)
    assert validar(p, agora=AGORA).pronto
    autorizacao.valido_ate = dt.date(2026, 2, 1)
    assert not validar(p, agora=AGORA).pronto


def test_faixa_e_area_metodo_nao_podem_exceder_conferido():
    p = dados_pasta()
    credito = p.imoveis[0].creditos[0]
    credito.p10.valor = Decimal(90)
    credito.area.valor = Decimal(1)
    r = validar(p, agora=AGORA)
    assert {"faixa_invertida", "area_excedida"} <= {f.codigo for f in r.falhas}
    credito.p10.valor = Decimal(10)
    credito.area.valor = Decimal(".25")
    outro = credito.model_copy(deep=True)
    outro.metodo = "plantio_total"
    outro.previsao_id = uuid4()
    p.imoveis[0].creditos.append(outro)
    assert validar(p, agora=AGORA).pronto  # alternativas, sem soma artificial das áreas ou créditos


@pytest.mark.parametrize("campo", ["nome", "cpf", "contato", "modelo_jinja", "template"])
def test_entrada_fechada_recusa_pessoas_e_modelos(campo):
    d = dados_pasta().model_dump(mode="json")
    d[campo] = "nao-aceitar"
    with pytest.raises(ValidationError):
        Pasta.model_validate(d)


def test_duas_saidas_mesmo_retrato_com_marca_fontes_e_escape():
    p = pacote(dados_pasta())
    p["modelo_jinja"] = "{{ 7 * 7 }}"
    p["contato"] = "NAO_EXPORTAR"
    marca = MarcaExportacao("RZP-teste-" + "a" * 32, "teste")
    z = zipfile.ZipFile(io.BytesIO(gerar(p, marca)))
    banco, comprador = [z.read(n).decode() for n in ("banco.html", "comprador.html")]
    assert "Pasta do banco fiador" in banco and "Pasta do comprador" in comprador
    for nome in z.namelist():
        texto = z.read(nome).decode()
        assert marca.codigo in texto and "NAO_EXPORTAR" not in texto and "{{ 7 * 7 }}" not in texto
    for html in (banco, comprador):
        assert p["versao_id"] in html and "24,90 BRL/tCO2e" in html and "2035-01-01" in html
        assert "imoveis/0/preco/moeda" in html and "estimado" in html and "Content-Security-Policy" in html
    assert json.loads(z.read("dados-conferidos.json"))["dados"] == p["dados"]


def test_cli_esquema_invalido_substitui_relatorio_antigo_sem_copiar_valores(tmp_path, capsys):
    from raiz.pasta_fiador.operacao import main

    entrada, relatorio = tmp_path / "entrada.json", tmp_path / "relatorio.json"
    entrada.write_text(
        json.dumps({"tipo": "inclusao", "motivo": "entrada_conferida", "dados": {"DADO_PROTEGIDO": "PRIVADO"}})
    )
    relatorio.write_text('{"pronto": true}')
    assert main([str(entrada), "--relatorio", str(relatorio)]) == 2
    r = json.loads(relatorio.read_text())
    assert not r["pronto"] and any(f["campo"] == "dados/pedido_id" for f in r["falhas"])
    assert "DADO_PROTEGIDO" not in relatorio.read_text() + capsys.readouterr().out
    assert "PRIVADO" not in relatorio.read_text()
    assert relatorio.stat().st_mode & 0o777 == 0o600
    entrada.write_text('{"tipo":"inclusao","tipo":"correcao"}')
    assert main([str(entrada), "--relatorio", str(relatorio)]) == 2
    assert not json.loads(relatorio.read_text())["pronto"]


def test_exportacao_mantem_centavos_alem_da_precisao_do_float():
    p = dados_pasta()
    p.imoveis[0].preco.valor = Decimal("12345678901234567890.12")
    z = zipfile.ZipFile(io.BytesIO(gerar(pacote(p), MarcaExportacao("RZP-teste-" + "a" * 32, "teste"))))
    assert b"12.345.678.901.234.567.890,12 BRL/tCO2e" in z.read("banco.html")
    assert (
        json.loads(z.read("dados-conferidos.json"))["dados"]["imoveis"][0]["preco"]["valor"]
        == "12345678901234567890.12"
    )
