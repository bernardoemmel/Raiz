"""O CAR extraído de um anexo conserva uma prova pública, sem abrir vínculos internos."""

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from raiz.calendario import arquivos, coleta
from raiz.calendario.feed import ics
from raiz.calendario.modelos import Evento, identificador
from testes.test_privacidade import CPF

CAR = "PA-1504950-" + "A" * 32


def evento(**campos):
    fonte = next(f for f in coleta.fontes() if f["id"] == "djen")
    url = fonte["urls"][0] + "/ABCDEFGHIJK/certidao"
    return Evento(
        **(
            {
                "id": identificador("djen", url, "leilao_imovel", "1"),
                "tipo": "leilao_imovel",
                "data": dt.date(2026, 11, 30),
                "fonte_id": "djen",
                "fonte_nome": fonte["nome"],
                "fonte_url": url,
                "codigos_car": [CAR],
                "vinculo": "car",
                "car_fonte_url": fonte["urls"][0] + "/anexo-matricula.pdf",
                "coletado_em": dt.datetime(2026, 11, 12, tzinfo=dt.UTC),
                "confianca": 0.85,
            }
            | campos
        )
    )


def test_prova_do_car_sobrevive_ao_snapshot_e_feed(tmp_path):
    e = evento()
    arquivos.publicar(tmp_path, [e], [])
    lidos, _ = arquivos.ler(tmp_path / "estado.json")
    publico = json.loads((tmp_path / "eventos.json").read_text())["eventos"][0]
    assert lidos[0].car_fonte_url == publico["car_fonte_url"] == e.car_fonte_url
    feed = ics(lidos).replace("\r\n ", "")
    assert "Documento que informa o CAR: " + e.car_fonte_url in feed
    assert "URL:" + e.fonte_url in feed


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "https://usuario:senha@exemplo.test/matricula.pdf", f"https://exemplo.test/{CPF}.pdf"],
)
def test_prova_recusa_documento_pessoal_credencial_e_codigo(url):
    with pytest.raises(ValidationError):
        evento(car_fonte_url=url)


@pytest.mark.parametrize("campos", [{"codigos_car": []}, {"vinculo": "cns_matricula"}, {"vinculo": "sigef"}])
def test_so_car_explicito_pode_ter_prova_publica(campos):
    with pytest.raises(ValidationError, match="código explícito"):
        evento(**campos)


def test_importacao_rejeita_anexo_de_host_fora_do_manifesto(tmp_path):
    arquivos.publicar(tmp_path, [evento(car_fonte_url="https://outro.example/matricula.pdf")], [])
    with pytest.raises(ValueError, match="documento do CAR fora"):
        arquivos.ler(tmp_path / "estado.json")


def test_revalidacao_interna_nao_expoe_prova_antiga():
    e = evento().model_copy(update={"vinculo": "cns_matricula"})
    assert e.publico()["car_fonte_url"] is None
    assert e.publico()["codigos_car"] == []
    assert e.car_fonte_url not in ics([e]).replace("\r\n ", "")


def test_snapshot_antigo_sem_anexo_continua_valido(tmp_path):
    e = evento().model_dump(mode="json", exclude={"car_fonte_url"})
    arq = tmp_path / "estado.json"
    arq.write_text(json.dumps({"eventos": [e], "fontes": []}))
    lidos, _ = arquivos.ler(arq)
    assert lidos[0].car_fonte_url is None
