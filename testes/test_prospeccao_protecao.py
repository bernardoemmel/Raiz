"""Marcas não pessoais, exportação fechada e varredura persistente entre processos."""

import copy
import csv
import io
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml
from pypdf import PdfReader
from sqlalchemy import create_engine, text

from raiz import prospeccao_protecao as p
from raiz.pedidos.servico import criar_cliente
from raiz.prospeccao_acesso import ErroAcesso
from raiz.prospeccao_contrato import projetar_ficha
from raiz.prospeccao_pdf import gerar_pdf
from raiz.publica import conta as CT


def car(n):
    return f"PA-1505536-{n:032X}"


@pytest.fixture
def chaves(monkeypatch):
    monkeypatch.setenv("RAIZ_PROTECAO_CHAVES", json.dumps({"v1": "a" * 32, "v2": "b" * 32}))
    monkeypatch.setenv("RAIZ_PROTECAO_VERSAO", "v1")


@pytest.fixture
def ficha():
    medida = {
        "valor": 12.5,
        "unidade": "ha",
        "fonte": "SICAR",
        "data_referencia": "2026-01-01",
        "data_corte": "2026-11-12",
        "estimado": True,
        "nome_dono": "PROIBIDO_MEDIDA",
    }
    return {
        "codigo_car": car(1),
        "municipio": "Município de teste",
        "uf": "PA",
        "area_total": medida,
        "nome_dono": "PROIBIDO_TOPO",
        "tir": {"p50": {**medida, "valor": -0.12, "unidade": "%"}},
        "terra_comprometida": {
            "situacao": "indicio",
            "area_indicio": medida,
            "evidencias": [
                {
                    "fonte_id": "verra",
                    "objeto_id": "registro-1",
                    "area": medida,
                    "data_referencia": "2025-12-30",
                    "observado_em": "2026-11-12T10:00:00Z",
                    "contato": "PROIBIDO_EVIDENCIA",
                }
            ],
        },
        "versao_ficha": {"id": 1, "hash": "f" * 64, "registrada_em": "2026-11-12T10:00:00Z"},
        "o_que_mudou": {
            "primeira_consulta": False,
            "mudancas": [
                {
                    "tipo": "area_total",
                    "campo": "area_total",
                    "antes": medida,
                    "depois": {**medida, "valor": 13.5},
                    "fonte": "SICAR",
                    "data_referencia": "2026-01-01",
                },
                {"tipo": "nome_dono", "campo": "nome_dono", "antes": "PROIBIDO_DIFF"},
            ],
        },
    }


def test_marca_estavel_por_cliente_e_versao_sem_identificador(chaves, monkeypatch):
    primeira = p.marca_cliente(123456789)
    assert primeira == p.marca_cliente(123456789)
    assert primeira != p.marca_cliente(123456790)
    assert "123456789" not in primeira.codigo and "a" * 32 not in primeira.codigo
    monkeypatch.setenv("RAIZ_PROTECAO_VERSAO", "v2")
    assert primeira != p.marca_cliente(123456789)
    assert primeira == p.marca_cliente(123456789, versao="v1")


def test_sem_chave_nao_exporta_e_marca_nao_aceita_texto_livre(monkeypatch, ficha):
    monkeypatch.delenv("RAIZ_PROTECAO_CHAVES", raising=False)
    monkeypatch.delenv("RAIZ_PROTECAO_VERSAO", raising=False)
    with pytest.raises(ErroAcesso) as erro:
        p.marca_cliente(1)
    assert erro.value.status == 503
    for marca in (None, "nome livre", p.MarcaExportacao("<script>segredo</script>", "v1")):
        for gerar in (p.gerar_json, p.gerar_csv):
            with pytest.raises(ErroAcesso):
                gerar(ficha, marca)
        with pytest.raises(ErroAcesso):
            gerar_pdf(ficha, marca=marca)


def test_json_pdf_csv_preservam_proveniencia_e_sentinela_separada(chaves, ficha):
    marca = p.marca_cliente(123)
    antes = copy.deepcopy(ficha)
    doc = json.loads(p.gerar_json(ficha, marca))
    assert doc["protecao"] == marca.metadados()
    assert doc["ficha"]["area_total"]["valor"] == 12.5
    assert doc["ficha"]["terra_comprometida"]["evidencias"][0]["observado_em"] == "2026-11-12T10:00:00Z"
    assert len(doc["ficha"]["o_que_mudou"]["mudancas"]) == 1
    assert "PROIBIDO" not in json.dumps(doc)
    csv_bytes = p.gerar_csv(ficha, marca)
    linhas = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    assert linhas[0]["tipo_registro"] == "sentinela_rastreio"
    assert linhas[0]["valor"] == p.SENTINELA
    assert all(r["marca_rastreio"] == marca.codigo for r in linhas)
    assert next(r["valor"] for r in linhas if r["campo"] == "tir.p50.valor") == "-0.12"
    pdf = PdfReader(io.BytesIO(gerar_pdf(ficha, marca=marca)))
    textos = [pagina.extract_text() for pagina in pdf.pages]
    assert all(marca.codigo in pagina for pagina in textos)
    todo = "\n".join(textos)
    for esperado in ("Sentinela de rastreio", "SICAR", "2026-01-01", "2026-11-12", "12.5", "13.5"):
        assert esperado in todo
    assert "PROIBIDO" not in todo and "PROIBIDO" not in csv_bytes.decode("utf-8-sig")
    assert ficha == antes


@pytest.mark.parametrize("valor", ["=1+1", "+SUM(A1)", "-cmd", "@cmd", " \t=cmd", "\tcmd", "\rcmd", "\ncmd"])
def test_csv_neutraliza_formula_em_campo_textual(chaves, valor):
    linhas = list(
        csv.DictReader(io.StringIO(p.gerar_csv({"municipio": valor}, p.marca_cliente(1)).decode("utf-8-sig")))
    )
    assert linhas[1]["valor"] == "'" + valor


def test_diff_fechado_por_campo_e_lotes_somente_uuid(ficha):
    pedido = str(uuid.uuid4())
    ficha["o_que_mudou"]["mudancas"].append(
        {
            "campo": "lotes_da_conta",
            "tipo": "entrou_lote",
            "antes": [],
            "depois": [pedido, "CONTATO_PROIBIDO"],
        }
    )
    dado = projetar_ficha(ficha)
    assert dado["o_que_mudou"]["mudancas"][-1]["depois"] == [pedido]
    assert "PROIBIDO" not in json.dumps(dado)


def test_contexto_vigia_falhas_e_nao_duplica_operacoes_aninhadas(monkeypatch):
    eventos = []
    monkeypatch.setattr(p, "registrar_tentativa", lambda engine, cliente_id, **kw: eventos.append(kw))
    with p.operacao_vigiada(None, 1, acao="comparacao") as concluir:
        p.executar_vigiado(None, 1, lambda: {"codigo_car": car(1)}, acao="ficha")
        concluir({"fichas": [{"codigo_car": car(1)}, {"codigo_car": car(2)}]})
        assert len(eventos) == 1  # já gravou antes do commit do contexto externo
    assert eventos[0]["status"] == 200 and len(eventos[0]["codigos_car"]) == 2
    with pytest.raises(ErroAcesso):
        with p.operacao_vigiada(None, 1, acao="ficha", codigos_car=[car(3)]):
            raise ErroAcesso(404, "Não disponível")
    assert eventos[-1]["status"] == 404


def test_auditoria_falha_preserva_erro_original_e_nao_vaza_detalhes(monkeypatch, caplog):
    def falhar(*args, **kwargs):
        raise RuntimeError("SEGREDO_NAO_LOGAR")

    monkeypatch.setattr(p, "registrar_tentativa", falhar)
    with pytest.raises(ErroAcesso) as original:
        with p.operacao_vigiada(None, 1, acao="ficha"):
            raise ErroAcesso(403, "Não permitido")
    assert original.value.status == 403
    with pytest.raises(ErroAcesso) as sucesso:
        p.executar_vigiado(None, 1, lambda: {}, acao="ficha")
    assert sucesso.value.status == 503
    assert "SEGREDO_NAO_LOGAR" not in caplog.text


@pytest.fixture
def engine(banco_url):
    eng = create_engine(banco_url)
    yield eng
    eng.dispose()


@pytest.fixture
def cliente(engine):
    return criar_cliente(engine, "Conta de teste de proteção")[0]


@pytest.fixture
def limiares(tmp_path, monkeypatch):
    doc = yaml.safe_load(p._REGRAS.read_text())
    for perfil in ("padrao", "licenciada"):
        doc[perfil].update(
            volume_min=4,
            diversidade_car_min=3,
            sequencia_car_min=3,
            paginas_consecutivas_min=3,
            falhas_min=3,
            taxa_falhas_min=0.8,
        )
    caminho = tmp_path / "protecao.yaml"
    caminho.write_text(yaml.safe_dump(doc))
    monkeypatch.setenv("RAIZ_PROTECAO_REGRAS", str(caminho))


def totais(engine, cliente):
    with engine.connect() as con:
        return {
            tabela: con.execute(
                text(f"select count(*) from negocio.{tabela} where cliente_id=:c"), {"c": cliente}
            ).scalar()
            for tabela in ("prospeccao_evento_protecao", "prospeccao_alerta_protecao", "alerta_api")
        }


@pytest.mark.banco
def test_marca_persistida_rastreavel_e_rotacao_exige_nova_versao(engine, cliente, chaves, monkeypatch):
    marca = p.registrar_marca(engine, cliente)
    assert p.registrar_marca(engine, cliente) == marca
    assert p.rastrear_marca(engine, marca.codigo)["cliente_id"] == cliente
    monkeypatch.setenv("RAIZ_PROTECAO_CHAVES", json.dumps({"v1": "c" * 32, "v2": "b" * 32}))
    with pytest.raises(ErroAcesso, match="sem nova versão"):
        p.registrar_marca(engine, cliente)
    monkeypatch.setenv("RAIZ_PROTECAO_VERSAO", "v2")
    nova = p.registrar_marca(engine, cliente)
    assert nova != marca and p.rastrear_marca(engine, marca.codigo)["cliente_id"] == cliente


@pytest.mark.banco
def test_sequencia_volume_diversidade_persistem_e_alerta_operador_deduplicado(engine, cliente, limiares):
    ids = []
    for i in range(1, 6):
        # Outro engine simula outro worker, sem estado do detector em memória.
        outro = create_engine(engine.url)
        ids.append(p.registrar_tentativa(outro, cliente, acao="ficha", status=200, codigos_car=[car(i)])["evento_id"])
        outro.dispose()
    contagem = totais(engine, cliente)
    assert contagem == {"prospeccao_evento_protecao": 5, "prospeccao_alerta_protecao": 2, "alerta_api": 2}
    duplicado = p.registrar_tentativa(
        engine, cliente, acao="ficha", status=200, codigos_car=[car(5)], evento_id=ids[-1]
    )
    assert duplicado["duplicado"] and totais(engine, cliente) == contagem
    with engine.connect() as con:
        registros = (
            con.execute(
                text("select metricas from negocio.prospeccao_alerta_protecao where cliente_id=:c"), {"c": cliente}
            )
            .scalars()
            .all()
        )
    assert all(r["diversidade_car"] == 5 for r in registros)
    assert all(car(1) not in json.dumps(r) for r in registros)


@pytest.mark.banco
def test_volume_repetido_sem_diversidade_nao_basta_para_alertar(engine, cliente, limiares):
    for _ in range(8):
        p.registrar_tentativa(engine, cliente, acao="ficha", status=200, codigos_car=[car(1)])
    assert totais(engine, cliente)["prospeccao_alerta_protecao"] == 0


@pytest.mark.banco
def test_paginacao_e_erros_403_404_sao_auditados(engine, cliente, limiares):
    for pagina in range(1, 5):
        p.registrar_tentativa(
            engine,
            cliente,
            acao="busca",
            canal="mcp",
            status=403 if pagina % 2 else 404,
            codigos_car=[car(pagina)],
            pagina=pagina,
            consulta_hash="f" * 64,
        )
    with engine.connect() as con:
        regras = (
            con.execute(
                text("select regra from negocio.prospeccao_alerta_protecao where cliente_id=:c"), {"c": cliente}
            )
            .scalars()
            .all()
        )
    assert "paginacao_sequencial" in regras and "varredura_recusada" in regras


@pytest.mark.banco
def test_licenca_autoriza_volume_e_paginacao_mas_nao_varredura_negada(engine, cliente, limiares):
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.conta_api
            (cliente_id,cnpj_hmac,cnpj_mascarado,termos_versao,licenca_dados_aprovada_em)
            values (:c,:h,'mascarado','teste',now())"""),
            {"c": cliente, "h": uuid.uuid4().hex},
        )
    for i in range(1, 6):
        p.registrar_tentativa(
            engine, cliente, acao="busca", status=200, codigos_car=[car(i)], pagina=i, consulta_hash="f" * 64
        )
    assert totais(engine, cliente)["prospeccao_alerta_protecao"] == 0
    # Nova janela só de recusas, sem reclassificar consultas autorizadas anteriores.
    with engine.begin() as con:
        con.execute(
            text(
                "update negocio.prospeccao_evento_protecao set criado_em=now()-interval '2 hours' where cliente_id=:c"
            ),
            {"c": cliente},
        )
    for i in range(6, 10):
        p.registrar_tentativa(engine, cliente, acao="ficha", status=404, codigos_car=[car(i)])
    with engine.connect() as con:
        regras = (
            con.execute(
                text("select regra from negocio.prospeccao_alerta_protecao where cliente_id=:c"), {"c": cliente}
            )
            .scalars()
            .all()
        )
    assert regras == ["varredura_recusada"]


@pytest.mark.banco
def test_mesmo_evento_concorrente_so_e_contado_uma_vez(engine, cliente, limiares):
    evento = uuid.uuid4()
    with ThreadPoolExecutor(max_workers=6) as pool:
        respostas = list(
            pool.map(
                lambda _: p.registrar_tentativa(
                    engine, cliente, acao="ficha", status=404, codigos_car=[car(1)], evento_id=evento
                ),
                range(12),
            )
        )
    assert sum(not r["duplicado"] for r in respostas) == 1
    assert totais(engine, cliente)["prospeccao_evento_protecao"] == 1


@pytest.mark.banco
def test_eventos_expiram_sem_apagar_marcas_e_alertas(engine, cliente, chaves, limiares):
    marca = p.registrar_marca(engine, cliente)
    for i in range(1, 5):
        p.registrar_tentativa(engine, cliente, acao="ficha", status=404, codigos_car=[car(i)])
    alertas = totais(engine, cliente)["alerta_api"]
    with engine.begin() as con:
        con.execute(
            text(
                "update negocio.prospeccao_evento_protecao set criado_em=now()-interval '100 days' where cliente_id=:c"
            ),
            {"c": cliente},
        )
    assert p.limpar_eventos(engine) == 4
    assert totais(engine, cliente)["alerta_api"] == alertas
    assert p.rastrear_marca(engine, marca.codigo)["cliente_id"] == cliente


@pytest.mark.banco
def test_falha_depois_de_concluir_corrige_status_sem_duplicar_evento(engine, cliente, limiares):
    evento = uuid.uuid4()
    with pytest.raises(ErroAcesso) as erro:
        with p.operacao_vigiada(engine, cliente, acao="busca", evento_id=evento) as concluir:
            concluir({"imoveis": [{"cod_imovel": car(1)}]})
            raise ErroAcesso(402, "A autorização mudou antes de confirmar a consulta.")
    assert erro.value.status == 402
    with engine.connect() as con:
        row = con.execute(
            text("select status,codigos_car from negocio.prospeccao_evento_protecao where id=:id"), {"id": evento}
        ).one()
    assert row.status == 402 and row.codigos_car == [car(1)]
    assert totais(engine, cliente)["prospeccao_evento_protecao"] == 1
    p.registrar_tentativa(engine, cliente, acao="busca", status=200, codigos_car=[car(1)], evento_id=evento)
    with engine.connect() as con:
        assert (
            con.execute(
                text("select status from negocio.prospeccao_evento_protecao where id=:id"), {"id": evento}
            ).scalar()
            == 402
        )


@pytest.mark.banco
def test_correcao_recusa_outra_conta_e_metadados_diferentes(engine, cliente, limiares):
    evento = uuid.uuid4()
    p.registrar_tentativa(engine, cliente, acao="ficha", status=200, codigos_car=[car(1)], evento_id=evento)
    outra = criar_cliente(engine, "Outra conta de teste")[0]
    for cid, cars, acao in ((outra, [car(1)], "ficha"), (cliente, [car(2)], "ficha"), (cliente, [car(1)], "busca")):
        with pytest.raises(ValueError, match="outros metadados"):
            p.registrar_tentativa(engine, cid, acao=acao, status=404, codigos_car=cars, evento_id=evento)
    with engine.connect() as con:
        assert (
            con.execute(
                text("select status from negocio.prospeccao_evento_protecao where id=:id"), {"id": evento}
            ).scalar()
            == 200
        )


@pytest.mark.banco
def test_correcao_reavalia_alerta_sem_duplicar_ocorrencia(engine, cliente, limiares):
    ids = [uuid.uuid4() for _ in range(3)]
    for indice, evento in enumerate(ids, 1):
        p.registrar_tentativa(engine, cliente, acao="ficha", status=200, codigos_car=[car(indice)], evento_id=evento)
    resposta = p.registrar_tentativa(engine, cliente, acao="ficha", status=500, codigos_car=[car(3)], evento_id=ids[-1])
    assert resposta["corrigido"]
    with engine.connect() as con:
        alerta = con.execute(
            text("select ocorrencias,metricas from negocio.prospeccao_alerta_protecao where cliente_id=:c"),
            {"c": cliente},
        ).one()
    assert alerta.ocorrencias == 1
    assert alerta.metricas["reavaliado_apos_falha"] and not alerta.metricas["criterio_atingido"]
    assert totais(engine, cliente)["alerta_api"] == 1
    historico = p.alertas(engine, cliente_id=cliente)
    assert len(historico) == 1 and not historico[0]["criterio_atingido"]
    assert historico[0]["reavaliado_apos_falha"]
    assert p.alertas(engine, cliente_id=cliente, apenas_ativos=True) == []
    lista_conta = CT.alertas(engine, cliente)
    assert lista_conta[0]["tipo"] == "raspagem_alerta"
    assert lista_conta[0]["protecao"] == historico[0]


@pytest.mark.banco
def test_lista_operador_preserva_alerta_legado_e_fecha_metricas(engine, cliente, limiares):
    with engine.begin() as con:
        antigo = (
            con.execute(
                text("""insert into negocio.alerta_api(cliente_id,tipo,regra,valor,limite)
            values (:c,'licenca','aprovada pelo fundador',null,null) returning *"""),
                {"c": cliente},
            )
            .mappings()
            .one()
        )
    for i in range(1, 4):
        p.registrar_tentativa(engine, cliente, acao="ficha", status=200, codigos_car=[car(i)])
    with engine.begin() as con:
        con.execute(
            text("""update negocio.prospeccao_alerta_protecao
            set metricas=metricas || '{"nome_dono":"PROIBIDO","tentativas":"TEXTO_PROIBIDO"}'::jsonb
            where cliente_id=:c"""),
            {"c": cliente},
        )
    lista = CT.alertas(engine, cliente)
    assert lista[0] == dict(antigo) and "protecao" not in lista[0]
    assert lista[1]["protecao"]["criterio_atingido"]
    assert lista[1]["protecao"]["regras_versao"].startswith("protecao-2026a+")
    assert "PROIBIDO" not in json.dumps(lista[1]["protecao"])
    assert p.alertas(engine, cliente_id=cliente, apenas_ativos=True, limite=1) == [lista[1]["protecao"]]
