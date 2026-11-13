"""Fixtures sintéticas em memória: verificam o avaliador, nunca constituem avaliação real de certidões."""

import hashlib
import io
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from pypdf import PdfWriter
from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from raiz.modelos.avaliacao import cascata as AC
from raiz.modelos.base import Pedido, Resposta, Uso
from raiz.modelos.cascata import Cascata
from raiz.modelos.claude import Claude
from raiz.modelos.custo import custo
from raiz.modelos.local import LlamaCpp

ESQUEMA = {
    "type": "object",
    "properties": {"classe": {"type": "string", "enum": ["edital", "outro"]}},
    "required": ["classe"],
    "additionalProperties": False,
}


class ModeloTeste:
    def __init__(self, nome, dados, *, conf=None, valor=Decimal(0), erro=None, chamadas=None):
        self.nome, self.dados, self.conf, self.valor, self.erro = nome, dados, conf, valor, erro
        self.provedor = "local" if nome == "local-teste" else "anthropic"
        self.chamadas = chamadas if chamadas is not None else []

    def responder_json(self, pedido):
        self.chamadas.append(self.nome)
        return Resposta(
            self.dados,
            self.nome,
            self.provedor,
            uso=Uso(entrada=20, saida=4, cache_leitura=3, cache_escrita=2),
            custo_usd=self.valor,
            custo_fonte="teste" if self.valor is not None else "sem_preco",
            confianca=self.conf,
            erro=self.erro,
        )


def caso(esperado=None):
    p = Pedido(
        "documento.classe", "Classifique o documento.", "CONTEÚDO SINTÉTICO", ESQUEMA, max_tokens=50, pessoal=True
    )
    return AC.Caso(hashlib.sha256(p.mensagem.encode()).hexdigest(), p, esperado)


def cortes():
    return {
        "versao": "teste",
        "modelo_local": "local-teste",
        "cortes": {"documento.classe": {"corte": 0.9}},
    }


def test_local_primeiro_confiante_e_baixa_confianca_sobe_com_custo_por_entrada():
    ordem = []
    a = ModeloTeste("local-teste", {"classe": "edital"}, conf=0.95, chamadas=ordem)
    b = ModeloTeste("haiku-teste", {"classe": "edital"}, valor=Decimal("0.002"), chamadas=ordem)
    c = Cascata(a, b, cortes=cortes())
    linhas = AC.avaliar(c, [caso({"classe": "edital"})])
    assert ordem == ["local-teste"]
    assert linhas[0]["via"] == "confianca" and linhas[0]["custo_usd"] == 0
    a.conf = 0.4
    linhas = AC.avaliar(c, [caso({"classe": "edital"})], tentativas=2)
    assert ordem == ["local-teste", "local-teste", "haiku-teste", "local-teste", "haiku-teste"]
    rel = AC.relatorio({"tipo": "documentos", "origem": "teste", "versao": "teste"}, linhas)
    r = rel["por_entrada"][0]
    assert r["entradas"] == 1 and r["tentativas"] == 2 and r["acerto"] == 1
    assert r["custo_usd"] == 0.004 and r["custo_medio_por_tentativa_usd"] == 0.002
    assert r["tokens"] == {"entrada": 80, "saida": 16, "cache_leitura": 12, "cache_escrita": 8}
    assert r["chamadas_por_modelo"] == {"local-teste": 2, "haiku-teste": 2}
    assert "CONTEÚDO SINTÉTICO" not in json.dumps(rel)
    assert "esperado" not in json.dumps(rel) and '"gabarito":' not in json.dumps(rel)


def test_sem_corte_nao_aprova_local_mesmo_com_confianca_alta_e_preserva_revisao():
    a = ModeloTeste("local-teste", {"classe": "edital"}, conf=1.0)
    b = ModeloTeste("haiku-teste", {"classe": "outro"}, valor=Decimal("0.002"))
    linhas = AC.avaliar(Cascata(a, b, cortes={"cortes": {}}), [caso({"classe": "edital"})])
    assert len(linhas[0]["chamadas"]) == 2
    assert linhas[0]["via"] == "revisao" and not linhas[0]["acerto"]
    r = AC.relatorio({"tipo": "documentos", "origem": "teste", "versao": "teste"}, linhas)["resumo"]
    assert r["acerto"] == 0 and r["acerto_automatico"] is None and r["revisoes"] == 1


def test_sem_gabarito_ou_preco_nao_inventa_acerto_nem_custo_zero():
    a = ModeloTeste("local-teste", {"classe": "edital"}, conf=0.2)
    b = ModeloTeste("haiku-teste", {"classe": "edital"}, valor=None)
    linhas = AC.avaliar(Cascata(a, b, cortes={"cortes": {}}), [caso()])
    r = AC.relatorio({"tipo": "documentos", "origem": "teste", "versao": "teste"}, linhas)["resumo"]
    assert r["acerto"] is None and r["tentativas_com_gabarito"] == 0
    assert r["custo_usd"] is None and r["custo_medio_por_tentativa_usd"] is None
    assert r["chamadas_sem_custo"] == 1 and r["custo_conhecido_usd"] == 0


def test_ausencia_de_uso_nao_vira_zero_no_relatorio_nem_no_provedor():
    cliente = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                model="claude-haiku-5-5",
                usage=None,
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text='{"classe":"edital"}')],
            )
        )
    )
    resp = Claude("claude-haiku-5-5", cliente=cliente).responder_json(caso().pedido)
    assert resp.ok and resp.custo_usd is None and not resp.uso_informado
    c = AC._chamada("B", resp)
    assert c["tokens"] is None and c["preco_aplicado"] is None and c["custo_fonte"] == "sem_uso"
    cliente_local = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "choices": [{"finish_reason": "stop", "message": {"content": '{"classe":"edital"}'}}],
                },
            )
        )
    )
    r = LlamaCpp(url="http://llama", cliente=cliente_local).responder_json(caso().pedido)
    assert r.ok and r.custo_usd is None and not r.uso_informado


def test_preco_haiku_inclui_cache_no_limiar_e_registra_fonte():
    uso = Uso(entrada=99999, saida=1000, cache_leitura=1, cache_escrita=1)
    valor, fonte = custo(uso, "claude-haiku-5-5", "anthropic")
    resp = Resposta({"classe": "edital"}, "claude-haiku-5-5", "anthropic", uso=uso, custo_usd=valor, custo_fonte=fonte)
    preco = AC._chamada("B", resp)["preco_aplicado"]
    assert preco["tokens_prompt_para_faixa"] == 100001
    assert preco["usd_por_milhao_tokens"] == {
        "entrada": 0.5,
        "saida": 2.5,
        "cache_leitura": 0.05,
        "cache_escrita_5min": 0.625,
    }
    assert preco["fontes"] == [AC.FONTE_PRECOS_ANTHROPIC]
    assert preco["fonte_oficial_conferida_em"] == "2026-11-12"
    uso.cache_escrita = 0
    preco = AC._chamada("B", resp)["preco_aplicado"]
    assert preco["tokens_prompt_para_faixa"] == 100000
    assert preco["usd_por_milhao_tokens"]["entrada"] == 0.1


def test_erro_bruto_e_valores_pessoais_nao_entram_no_relatorio():
    segredo = "NOME PESSOAL QUE VEIO DO DOCUMENTO"
    a = ModeloTeste("local-teste", None, erro=segredo)
    b = ModeloTeste("haiku-teste", None, valor=None, erro=segredo)
    linhas = AC.avaliar(Cascata(a, b, cortes={"cortes": {}}), [caso({"classe": segredo})])
    rel = AC.relatorio({"tipo": "documentos", "origem": "teste", "versao": "teste"}, linhas)
    assert segredo not in json.dumps(rel) and linhas[0]["chamadas"][0]["falha"] == "falha"
    assert not AC._igual(True, 1)


def manifesto(tmp_path, nome="teste.txt", **trocas):
    entrada = {
        "arquivo": nome,
        "tarefa": "documento.classe",
        "sistema": "Classifique o documento sintético de teste.",
        "pedido": "Informe a classe.",
        "esquema": ESQUEMA,
        "gabarito": {"classe": "edital"},
        "gabarito_origem": "revisao_humana_integral",
        "gabarito_confirmado_em": "2026-01-01T12:00:00-03:00",
        **trocas,
    }
    arq = tmp_path / "manifesto.json"
    arq.write_text(json.dumps({"origem": "documentos_reais", "documentos": [entrada]}))
    return arq


def test_manifesto_real_e_obrigatorio_sem_inventar_conjunto(tmp_path):
    arq = tmp_path / "manifesto.json"
    arq.write_text(json.dumps({"origem": "documentos_reais", "documentos": []}))
    with pytest.raises(ValueError, match="não foi criado conjunto sintético"):
        AC.documentos(arq)
    arq.write_text(json.dumps({"origem": "sintetico", "documentos": []}))
    with pytest.raises(ValueError, match="não são avaliação real"):
        AC.documentos(arq)
    (tmp_path / "teste.txt").write_text("DOCUMENTO SINTÉTICO DE TESTE")
    meta, casos = AC.documentos(manifesto(tmp_path))
    assert meta["tipo"] == "documentos" and casos[0].pedido.pessoal
    assert casos[0].sha256 == hashlib.sha256((tmp_path / "teste.txt").read_bytes()).hexdigest()
    assert casos[0].esperado == {"classe": "edital"}
    with pytest.raises(ValueError, match="gabarito incompleto"):
        AC.documentos(manifesto(tmp_path, gabarito={}))
    with pytest.raises(ValueError, match="não previsão do motor"):
        AC.documentos(manifesto(tmp_path, gabarito_origem="previsto_pelo_motor"))


def test_documento_repetido_nao_infla_numero_de_amostras(tmp_path):
    (tmp_path / "teste.txt").write_text("DOCUMENTO SINTÉTICO")
    arq = manifesto(tmp_path)
    d = json.loads(arq.read_text())
    d["documentos"] *= 2
    arq.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="conteúdo repetido"):
        AC.documentos(arq)


def test_pdf_curto_local_primeiro_e_haiku_recebe_pdf_completo_sem_duplicar_texto(tmp_path, monkeypatch):
    pdf = io.BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(20, 700, "DOCUMENTO SINTETICO PARA TESTE")
    canvas.save()
    (tmp_path / "teste.pdf").write_bytes(pdf.getvalue())
    _, casos = AC.documentos(manifesto(tmp_path, nome="teste.pdf"))
    assert not casos[0].pdf_visual
    vistos = []

    class Leitor:
        def __init__(self, **kw):
            assert kw["modelo"] == "claude-haiku-5-5"

        def ler_pdf(self, conteudo, sistema, instrucao, esquema):
            vistos.append("haiku-pdf")
            assert conteudo == pdf.getvalue() and instrucao == "Informe a classe."
            assert "DOCUMENTO SINTETICO" not in instrucao
            return SimpleNamespace(dados={"classe": "edital"}, modelo="claude-haiku-5-5", uso=Uso(10, 2),
                                   duracao_ms=1, recusou=False, erro=None, custo_usd=0.001)  # fmt: skip

    monkeypatch.setattr(AC, "LeitorClaude", Leitor)
    a = ModeloTeste("local-teste", {"classe": "edital"}, conf=0.2, chamadas=vistos)
    b = ModeloTeste("claude-haiku-5-5", {"classe": "edital"})
    linhas = AC.avaliar(Cascata(a, b, cortes={"cortes": {}}), casos)
    assert vistos == ["local-teste", "haiku-pdf"] and linhas[0]["acerto"]
    assert linhas[0]["chamadas"][1]["custo_fonte"] == "genai-prices"


def test_pdf_sem_texto_nao_finge_ter_sido_lido_pelo_qwen(tmp_path, monkeypatch):
    pdf = PdfWriter()
    pdf.add_blank_page(width=300, height=400)
    with (tmp_path / "teste.pdf").open("wb") as f:
        pdf.write(f)
    _, casos = AC.documentos(manifesto(tmp_path, nome="teste.pdf"))
    assert casos[0].pdf_visual

    class Leitor:
        def __init__(self, **kw):
            pass

        def ler_pdf(self, *args):
            return SimpleNamespace(dados={"classe": "edital"}, modelo="claude-haiku-5-5", uso=Uso(10, 2),
                                   duracao_ms=1, recusou=False, erro=None, custo_usd=0.001)  # fmt: skip

    monkeypatch.setattr(AC, "LeitorClaude", Leitor)
    a = ModeloTeste("local-teste", {"classe": "edital"}, conf=1.0)
    b = ModeloTeste("claude-haiku-5-5", {"classe": "edital"})
    linhas = AC.avaliar(Cascata(a, b, cortes=cortes()), casos)
    assert a.chamadas == [] and linhas[0]["rota"] == "nuvem"
    assert [c["papel"] for c in linhas[0]["chamadas"]] == ["B"]
    assert "página sem texto" in linhas[0]["motivo_rota"]


def test_benchmark_nao_e_rotulado_como_documento_e_relatorio_e_privado(tmp_path):
    meta, casos = AC.banco_aceite()
    assert len(casos) == 120 and meta["tipo"] == "benchmark_aceite"
    assert all(c.unidade == "tarefa" for c in casos)
    rel = AC.relatorio(meta, [])
    assert rel["resumo"]["acerto"] is None
    arq = AC.gravar(rel, tmp_path)
    assert arq.stat().st_mode & 0o777 == 0o600


def test_cli_sem_chave_bloqueia_antes_de_chamar_local_ou_publicar_metricas(tmp_path, monkeypatch):
    from raiz.cli import app
    from raiz.config import config

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RAIZ_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("raiz.config.config", lambda: SimpleNamespace(anthropic_api_key=None))
    monkeypatch.setattr(AC, "avaliar", lambda *a, **k: pytest.fail("não deveria chamar modelo sem credencial"))
    run = CliRunner().invoke(app, ["modelos", "avaliar-cascata", "--benchmark-aceite", "--saida", str(tmp_path)])
    assert run.exit_code == 1 and "ANTHROPIC_API_KEY ausente ou vazia" in run.output
    assert "Nenhum acerto ou custo Haiku foi medido" in run.output and not list(tmp_path.iterdir())
    config.cache_clear()
