"""Amostras artificiais verificam o mecanismo; não publicam cortes de produção."""

import datetime as dt
import hashlib
import json
from dataclasses import replace

import pytest

from raiz.documentos import aprendizado
from raiz.documentos.armazem import Armazem
from raiz.documentos.certidao import cache, esquema
from raiz.documentos.certidao.leitor import ler_certidao
from raiz.documentos.claude import LeitorClaude
from raiz.documentos.cli import principal
from raiz.documentos.config import REPO
from raiz.documentos.simulacao import ClienteSimulado, leitura_exemplo, pdf_exemplo

HOJE = dt.date(2026, 11, 12)
IMOVEL = "PA-1504950-0E3B6098A40D44F7B85CFB563EB6A45A"


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    monkeypatch.setenv("RAIZ_DOCUMENTOS_DIR", str(tmp_path / "documentos"))
    monkeypatch.setenv("RAIZ_DOCUMENTOS_ENTRADA", str(REPO / "dados" / "amostra"))


def _leitor(dados=None):
    cliente = ClienteSimulado([dados or leitura_exemplo()])
    return LeitorClaude(cliente=cliente), cliente


@pytest.fixture
def amostra():
    """Imita metadados de API só nesta fixture; nenhuma chamada externa ou corte distribuído."""
    armazem = Armazem()
    leitor, _ = _leitor()
    base = ler_certidao(pdf_exemplo("molde"), leitor=leitor, hoje=HOJE).leitura
    for n in range(140):
        lt = replace(
            base,
            id=None,
            registro_hash=None,
            arquivo_sha256=hashlib.sha256(f"amostra {n}".encode()).hexdigest(),
            chave=f"cns:068429|mat:{n + 100}",
            derivados={
                **base.derivados,
                "origem_leitura": "api",
                "escore_confianca": 0.95 if n < 120 else 0.35,
            },
        )
        armazem.gravar_leitura(lt)
        aprendizado.marcar(
            lt.id,
            fonte="conferencia_humana",
            leitura_integral=n < 120,
            amostra_aleatoria_cache=True,
            armazem=armazem,
        )
    return armazem, base


def _candidata(armazem, base, pdf, **alteracoes):
    lt = replace(
        base,
        id=None,
        registro_hash=None,
        arquivo_sha256=hashlib.sha256(pdf).hexdigest(),
        lido_em=dt.datetime.now(dt.UTC).isoformat(),
        derivados={**base.derivados, "origem_leitura": "api"},
        **alteracoes,
    )
    armazem.gravar_leitura(lt)
    return lt


def test_escore_e_numerico_mas_nao_probabilidade():
    dados = leitura_exemplo()
    assert cache.escore(dados) == 0.95
    dados["confianca"] = "baixa"
    assert cache.escore(dados) == 0.35
    dados["imovel"]["area_valor"] = None
    assert cache.escore(dados) < 0.35
    dados["documento"]["legivel"] = False
    assert cache.escore(dados) == 0
    assert cache.escore({}) == 0


def test_sem_calibracao_rele_e_simulado_nao_calibra():
    leitor, cliente = _leitor()
    pdf = pdf_exemplo("sem corte")
    a = ler_certidao(pdf, leitor=leitor, hoje=HOJE)
    b = ler_certidao(pdf, leitor=leitor, hoje=HOJE)
    assert len(cliente.chamadas) == 2 and not b.cache["reutilizada"]
    assert a.leitura.derivados["escore_confianca"] == 0.95
    aprendizado.marcar(a.leitura.id, fonte="cartorio", leitura_integral=True, amostra_aleatoria_cache=True)
    assert cache.calibrar(hoje=HOJE)["grupos"] == {}


def test_cache_calibrado_e_reconferencia_do_motor(amostra, monkeypatch):
    armazem, base = amostra
    pdf = pdf_exemplo("cache alto")
    lt = _candidata(armazem, base, pdf)
    cal = cache.calibrar(armazem, hoje=HOJE)
    [grupo] = cal["grupos"].values()
    assert grupo["matriculas"] == 140 and grupo["reutilizaveis"] == 120 and grupo["erros"] == 0
    leitor, cliente = _leitor()
    r = ler_certidao(pdf, leitor=leitor, armazem=armazem, cod_imovel=IMOVEL, hoje=HOJE)
    assert r.cache["reutilizada"] and r.leitura.id == lt.id and not cliente.chamadas
    assert r.situacao == "conferida"
    antiga = ler_certidao(pdf, leitor=leitor, armazem=armazem, cod_imovel=IMOVEL, hoje=HOJE + dt.timedelta(days=31))
    assert antiga.cache["reutilizada"]
    assert "certidao_antiga" in {m.codigo for m in antiga.conferencias[0].motivos}
    # Uma mudança do motor é observada mesmo sem nova extração do PDF.
    monkeypatch.setattr("raiz.documentos.certidao.leitor._motor", lambda *a: (None, None, None))
    novo = ler_certidao(pdf, leitor=leitor, armazem=armazem, cod_imovel=IMOVEL, hoje=HOJE)
    assert novo.cache["reutilizada"] and novo.situacao != "conferida" and not cliente.chamadas
    with armazem.con() as c:
        decisoes = c.execute("select decisao_json from cache_decisao where leitura_id = ?", (lt.id,)).fetchall()
    assert all(json.loads(d[0])["calibracao_hash"] for d in decisoes)
    aprendizado.marcar(lt.id, fonte="cartorio", campos={"area_ha": "100"}, armazem=armazem)
    errado = ler_certidao(pdf, leitor=leitor, armazem=armazem, cod_imovel=IMOVEL, hoje=HOJE)
    assert errado.cache["motivo"] == "leitura desmentida por conferência" and len(cliente.chamadas) == 1


def test_baixa_confianca_pdf_modelo_prompt_esforco_e_forcada_releem(amostra, monkeypatch):
    armazem, base = amostra
    pdf = pdf_exemplo("cache baixo")
    baixo = replace(base, derivados={**base.derivados, "escore_confianca": 0.35})
    _candidata(armazem, baixo, pdf)
    cache.calibrar(armazem, hoje=HOJE)
    leitor, cliente = _leitor()
    r = ler_certidao(pdf, leitor=leitor, armazem=armazem, hoje=HOJE)
    assert r.cache["motivo"] == "abaixo do corte: reler" and len(cliente.chamadas) == 1
    outro = pdf_exemplo("outro pdf")
    ler_certidao(outro, leitor=leitor, armazem=armazem, hoje=HOJE)
    assert len(cliente.chamadas) == 2
    _candidata(armazem, base, outro)
    ler_certidao(outro, leitor=leitor, armazem=armazem, hoje=HOJE, forcar_releitura=True)
    assert len(cliente.chamadas) == 3
    for mudar in ("modelo", "esforco"):
        atual, stub = _leitor()
        setattr(atual, mudar, "outro")
        r = ler_certidao(outro, leitor=atual, armazem=armazem, hoje=HOJE)
        assert len(stub.chamadas) == 1 and not r.cache["reutilizada"]
    monkeypatch.setattr(esquema, "SISTEMA", esquema.SISTEMA + " ")
    r = ler_certidao(outro, leitor=leitor, armazem=armazem, hoje=HOJE)
    assert len(cliente.chamadas) == 4 and not r.cache["reutilizada"]


def test_correcao_vencimento_e_arquivo_invalido_fecham_cache(amostra):
    armazem, base = amostra
    pdf = pdf_exemplo("invalidar")
    lt = _candidata(armazem, base, pdf)
    cache.calibrar(armazem, hoje=HOJE)
    leitor, cliente = _leitor()
    r = ler_certidao(pdf, leitor=leitor, armazem=armazem, hoje=HOJE + dt.timedelta(days=91))
    assert r.cache["motivo"] == "calibração vencida ou futura" and len(cliente.chamadas) == 1
    _candidata(armazem, base, pdf)
    cache.caminho_padrao().write_text("quebrado", encoding="utf-8")
    r = ler_certidao(pdf, leitor=leitor, armazem=armazem, hoje=HOJE)
    assert r.cache["motivo"] == "calibração ausente ou inválida"
    _candidata(armazem, base, pdf)
    cache.calibrar(armazem, hoje=HOJE)
    aprendizado.marcar(lt.id, fonte="cartorio", leitura_integral=False, armazem=armazem)
    r = ler_certidao(pdf, leitor=leitor, armazem=armazem, hoje=HOJE)
    assert r.cache["motivo"] == "gabaritos mudaram: recalibrar"


def test_gabarito_parcial_amostra_dirigida_e_duplicatas_nao_inflam_n(amostra):
    armazem, base = amostra
    grupo = next(iter(cache.calibrar(armazem, hoje=HOJE)["grupos"].values()))
    assert grupo["matriculas"] == 140
    lt = _candidata(armazem, base, pdf_exemplo("sem revisão completa"))
    aprendizado.marcar(lt.id, fonte="cartorio", campos={"area_ha": "290"}, armazem=armazem)
    assert next(iter(cache.calibrar(armazem, hoje=HOJE)["grupos"].values()))["matriculas"] == 140
    aprendizado.marcar(lt.id, fonte="cartorio", leitura_integral=True, armazem=armazem)
    assert next(iter(cache.calibrar(armazem, hoje=HOJE)["grupos"].values()))["matriculas"] == 140
    duplicata = _candidata(armazem, base, pdf_exemplo("mesma matrícula"), chave="cns:068429|mat:100")
    aprendizado.marcar(
        duplicata.id,
        fonte="cartorio",
        leitura_integral=True,
        amostra_aleatoria_cache=True,
        armazem=armazem,
    )
    assert next(iter(cache.calibrar(armazem, hoje=HOJE)["grupos"].values()))["matriculas"] == 140


def test_amostra_pequena_nao_libera_e_cli_calibra(amostra, capsys):
    _, base = amostra
    pequeno = Armazem(cache.caminho_padrao().parent / "pequeno.sqlite")
    lt = _candidata(pequeno, base, pdf_exemplo("um só"))
    aprendizado.marcar(lt.id, fonte="onr", leitura_integral=True, amostra_aleatoria_cache=True, armazem=pequeno)
    [g] = cache.calibrar(pequeno, hoje=HOJE)["grupos"].values()
    assert g["corte"] is None and g["reutilizaveis"] == 0
    assert principal(["aprendizado", "calibrar-cache"]) == 0
    assert "MAPIE" in capsys.readouterr().out
