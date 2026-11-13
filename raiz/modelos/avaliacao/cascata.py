"""Avaliação da cascata por entrada, sem copiar documentos ou gabaritos para o relatório.

O banco de aceite continua sendo um teste de tarefas. Documentos reais entram por manifesto
privado, e só têm medida de acerto quando existe um gabarito humano completo.
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import io
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

from genai_prices import Usage as UsoPreco
from genai_prices import calc_price
from genai_prices.types import calc_unit_price
from pypdf import PdfReader

from raiz.documentos.claude import LeitorClaude, falta_campo
from raiz.modelos import rota
from raiz.modelos.avaliacao import carregar, pedido
from raiz.modelos.base import Modelo, Pedido, Resposta, Uso
from raiz.modelos.cascata import Cascata, ResultadoCascata
from raiz.modelos.custo import custo

LIMITE_BYTES = 32 * 1024 * 1024
FONTE_PRECOS_ANTHROPIC = "https://platform.claude.com/docs/en/about-claude/pricing"
PRECOS_CONFERIDOS_EM = "2026-11-12"


@dataclass(frozen=True)
class Caso:
    sha256: str
    pedido: Pedido
    esperado: dict | None
    unidade: str = "documento"
    pdf: bytes | None = None
    pdf_visual: bool = False
    instrucao_pdf: str | None = None
    gabarito_confirmado_em: str | None = None


def banco_aceite() -> tuple[dict, list[Caso]]:
    meta, tarefas = carregar()
    casos = []
    for t in tarefas:
        p = pedido(t)
        bruto = json.dumps([p.sistema, p.mensagem, p.esquema], ensure_ascii=False, sort_keys=True).encode()
        casos.append(Caso(hashlib.sha256(bruto).hexdigest(), p, t.esperado, unidade="tarefa"))
    return {**meta, "tipo": "benchmark_aceite", "origem": "banco de tarefas; não são certidões"}, casos


def documentos(caminho: Path) -> tuple[dict, list[Caso]]:
    """Lê PDF/TXT e gabarito local. Nunca imprime nome de arquivo, conteúdo ou valor do gabarito."""
    bruto = caminho.read_bytes()
    manifesto = json.loads(bruto)
    if not isinstance(manifesto, dict) or manifesto.get("origem") != "documentos_reais":
        raise ValueError("o manifesto deve declarar origem=documentos_reais; testes sintéticos não são avaliação real")
    entradas = manifesto.get("documentos")
    if not isinstance(entradas, list) or not entradas:
        raise ValueError("manifesto sem documentos; não foi criado conjunto sintético")
    casos, vistos = [], set()
    for i, entrada in enumerate(entradas, 1):
        if not isinstance(entrada, dict):
            raise ValueError(f"documento {i}: entrada inválida")
        arquivo = caminho.parent / str(entrada.get("arquivo") or "")
        if not arquivo.is_file() or arquivo.suffix.lower() not in {".pdf", ".txt"}:
            raise ValueError(f"documento {i}: informe arquivo PDF ou TXT existente")
        if arquivo.stat().st_size > LIMITE_BYTES:
            raise ValueError(f"documento {i}: excede 32 MiB")
        conteudo = arquivo.read_bytes()
        sha = hashlib.sha256(conteudo).hexdigest()
        if sha in vistos:
            raise ValueError(f"documento {i}: conteúdo repetido; não contar o mesmo documento duas vezes")
        vistos.add(sha)
        pdf = conteudo if arquivo.suffix.lower() == ".pdf" else None
        pdf_visual = False
        try:
            if pdf is not None:
                paginas = list(PdfReader(io.BytesIO(conteudo)).pages)
                if not paginas:
                    raise ValueError("PDF sem páginas")
                textos = [p.extract_text() or "" for p in paginas]
                pdf_visual = any(not texto.strip() or len(p.images) for p, texto in zip(paginas, textos, strict=True))
                texto = "\n".join(textos)
            else:
                texto = conteudo.decode("utf-8")
        except Exception:  # noqa: BLE001 - não expor texto/nome do documento na falha do parser
            raise ValueError(f"documento {i}: arquivo ilegível") from None
        tarefa = entrada.get("tarefa", "")
        if not isinstance(tarefa, str) or not re.fullmatch(r"[a-z][a-z0-9_.]{0,79}", tarefa):
            raise ValueError(f"documento {i}: tarefa deve ser um identificador estável")
        esquema = entrada.get("esquema")
        if not isinstance(esquema, dict) or esquema.get("type") != "object":
            raise ValueError(f"documento {i}: esquema deve descrever um objeto")
        esperado = entrada.get("gabarito")
        if esperado is not None and (not isinstance(esperado, dict) or not esperado or falta_campo(esperado, esquema)):
            raise ValueError(f"documento {i}: gabarito incompleto ou fora do esquema")
        confirmado_em = None
        if esperado is not None:
            if entrada.get("gabarito_origem") != "revisao_humana_integral":
                raise ValueError(f"documento {i}: gabarito exige revisão humana integral, não previsão do motor")
            try:
                confirmado = dt.datetime.fromisoformat(entrada.get("gabarito_confirmado_em") or "")
                if confirmado.tzinfo is None or confirmado > dt.datetime.now(dt.UTC):
                    raise ValueError("data inválida")
                confirmado_em = confirmado.isoformat()
            except (ValueError, TypeError):
                raise ValueError(f"documento {i}: data da revisão humana deve ter fuso e não pode ser futura") from None
        sistema, instrucao = entrada.get("sistema"), entrada.get("pedido")
        if not isinstance(sistema, str) or not sistema or not isinstance(instrucao, str) or not instrucao:
            raise ValueError(f"documento {i}: sistema e pedido são obrigatórios")
        max_tokens = entrada.get("max_tokens", 400)
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or not 1 <= max_tokens <= 64000:
            raise ValueError(f"documento {i}: max_tokens inválido")
        p = Pedido(
            tarefa,
            sistema,
            f"<documento>\n{texto}\n</documento>\n{instrucao}",
            esquema,
            max_tokens=max_tokens,
            pessoal=True,
        )
        # Não tratar a camada parcial de texto como leitura integral de PDF com imagem/página escaneada.
        if pdf_visual:
            p = Pedido(tarefa, sistema, instrucao, esquema, max_tokens=max_tokens, pessoal=True, ferramentas=1)
        casos.append(
            Caso(
                sha,
                p,
                esperado,
                pdf=pdf,
                pdf_visual=pdf_visual,
                instrucao_pdf=instrucao,
                gabarito_confirmado_em=confirmado_em,
            )
        )
    return {
        "tipo": "documentos",
        "origem": "documentos reais declarados no manifesto privado",
        "versao": hashlib.sha256(bruto).hexdigest(),
    }, casos


class _ModeloPDF:
    """Mantém o PDF inteiro disponível ao Haiku/juiz, inclusive se o local só leu a camada de texto."""

    def __init__(self, modelo: Modelo, pdf: bytes, instrucao: str):
        self.modelo, self.pdf, self.instrucao = modelo, pdf, instrucao
        self.nome, self.provedor = modelo.nome, modelo.provedor

    def responder_json(self, p: Pedido) -> Resposta:
        leitor = LeitorClaude(
            modelo=self.nome,
            esforco=getattr(self.modelo, "esforco", "low"),
            cliente=getattr(self.modelo, "cliente", None),
            reserva=getattr(self.modelo, "reserva", False),
            max_tokens=p.max_tokens,
        )
        r = leitor.ler_pdf(self.pdf, p.sistema, self.instrucao, p.esquema)
        uso = Uso(**asdict(r.uso))
        informado = getattr(r, "uso_informado", True)
        valor, fonte = (
            (None, "sem_uso")
            if not informado or (r.erro and r.custo_usd is None)
            else custo(uso, r.modelo, self.provedor)
        )
        return Resposta(
            r.dados,
            r.modelo,
            self.provedor,
            uso=uso,
            custo_usd=valor,
            custo_fonte=fonte,
            duracao_ms=r.duracao_ms,
            recusou=r.recusou,
            erro=r.erro or ("fora do esquema" if r.dados and falta_campo(r.dados, p.esquema) else None),
            uso_informado=informado,
        )


def _preco_aplicado(r: Resposta) -> dict | None:
    if not r.uso_informado or r.custo_usd is None:
        return None
    if r.provedor == "local":
        return {"tarifa_api_usd": 0, "custo_execucao_usd": None}
    if r.custo_fonte != "genai-prices":
        return None
    total = r.uso.entrada + r.uso.cache_leitura + r.uso.cache_escrita
    try:
        preco = calc_price(
            UsoPreco(
                input_tokens=total,
                output_tokens=r.uso.saida,
                cache_read_tokens=r.uso.cache_leitura,
                cache_write_tokens=r.uso.cache_escrita,
            ),
            model_ref=r.modelo,
            provider_id=r.provedor,
        )
    except (LookupError, ValueError):
        return None
    campos = {
        "entrada": "input_mtok",
        "saida": "output_mtok",
        "cache_leitura": "cache_read_mtok",
        "cache_escrita_5min": "cache_write_mtok",
    }
    tarifas = {
        nome: float(calc_unit_price(getattr(preco.model_price, chave), 1_000_000, total, 1_000_000))
        if getattr(preco.model_price, chave) is not None
        else None
        for nome, chave in campos.items()
    }
    return {
        "modelo_tabela": preco.model.id,
        "usd_por_milhao_tokens": tarifas,
        "tokens_prompt_para_faixa": total,
        "fontes": [FONTE_PRECOS_ANTHROPIC] if r.provedor == "anthropic" else preco.provider.pricing_urls,
        "fonte_oficial_conferida_em": PRECOS_CONFERIDOS_EM
        if r.modelo in {"claude-haiku-5-5", "claude-sonnet-5-5"}
        else None,
        "calculado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }


def _chamada(papel: str, r: Resposta) -> dict:
    return {
        "papel": papel,
        "modelo": r.modelo,
        "provedor": r.provedor,
        "tokens": asdict(r.uso) if r.uso_informado else None,
        "uso_informado": r.uso_informado,
        "custo_usd": float(r.custo_usd) if r.custo_usd is not None and r.uso_informado else None,
        "custo_fonte": r.custo_fonte if r.uso_informado else "sem_uso",
        "preco_aplicado": _preco_aplicado(r),
        "duracao_ms": r.duracao_ms,
        "ok": r.ok,
        # A mensagem da API pode conter texto do documento; o relatório só guarda a categoria.
        "falha": "recusa" if r.recusou else "falha" if not r.ok else None,
    }


def _custos(chamadas: list[dict]) -> dict:
    conhecidos = sum((Decimal(str(c["custo_usd"])) for c in chamadas if c["custo_usd"] is not None), Decimal(0))
    faltantes = sum(c["custo_usd"] is None for c in chamadas)
    return {
        "custo_usd": None if faltantes else float(conhecidos),
        "custo_conhecido_usd": float(conhecidos),
        "chamadas_sem_custo": faltantes,
    }


def _igual(a, b) -> bool:
    # A comparação não confunde true com 1, nem grava os valores que vieram do documento.
    return json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False)


def _linha(caso: Caso, out: ResultadoCascata, tentativa: int, duracao_ms: int, motivo: str) -> dict:
    chamadas = [_chamada(papel, r) for papel, r in out.respostas.items()]
    esperado, dados = caso.esperado, out.dados
    return {
        "unidade": caso.unidade,
        "sha256": caso.sha256,
        "tarefa": caso.pedido.tarefa,
        "tentativa": tentativa,
        "com_gabarito": esperado is not None,
        "gabarito_confirmado_em": caso.gabarito_confirmado_em,
        "acerto": _igual(dados, esperado) if esperado is not None else None,
        "campos_conferidos": len(esperado) if esperado else 0,
        "campos_corretos": sum(k in (dados or {}) and _igual(dados[k], v) for k, v in esperado.items())
        if esperado
        else None,
        "via": out.via,
        "rota": out.rota,
        "motivo_rota": motivo,
        "confianca_local": out.confianca,
        "corte": out.corte,
        "regra_versao": out.versao,
        "decisao_automatica": dados is not None and out.via != "revisao",
        "duracao_ms": duracao_ms,
        "chamadas": chamadas,
        **_custos(chamadas),
    }


def avaliar(cascata: Cascata, casos: list[Caso], tentativas: int = 1, progresso=None) -> list[dict]:
    if not casos or not 1 <= tentativas <= 10:
        raise ValueError("informe entradas e de 1 a 10 tentativas")
    linhas = []
    for i, caso in enumerate(casos, 1):
        corrente = copy.copy(cascata)
        if caso.pdf is not None:
            corrente.b = _ModeloPDF(cascata.b, caso.pdf, caso.instrucao_pdf or caso.pedido.mensagem)
            if cascata.juiz is not None:
                corrente.juiz = _ModeloPDF(cascata.juiz, caso.pdf, caso.instrucao_pdf or caso.pedido.mensagem)
        no_local, motivo = rota.cabe_no_local(caso.pedido, corrente.politica())
        if caso.pdf_visual:
            motivo = "PDF com imagem ou página sem texto; leitura visual no Haiku"
        elif no_local:
            motivo = "local primeiro; sem corte aprovado ou abaixo dele, chama Haiku"
        for tentativa in range(1, tentativas + 1):
            t0 = time.perf_counter()
            out = corrente.decidir(caso.pedido)
            linhas.append(_linha(caso, out, tentativa, int((time.perf_counter() - t0) * 1000), motivo))
        if progresso:
            progresso(i, len(casos))
    return linhas


def _resumir(linhas: list[dict]) -> dict:
    rotulados = [r for r in linhas if r["com_gabarito"]]
    automaticos = [r for r in rotulados if r["decisao_automatica"]]
    chamadas = [c for r in linhas for c in r["chamadas"]]
    custos = _custos(chamadas)
    com_uso = [c for c in chamadas if c["uso_informado"]]
    tokens = {k: sum(c["tokens"][k] for c in com_uso) for k in asdict(Uso())}
    return {
        "entradas": len({(r["unidade"], r["sha256"]) for r in linhas}),
        "tentativas": len(linhas),
        "tentativas_com_gabarito": len(rotulados),
        "acerto": sum(r["acerto"] for r in rotulados) / len(rotulados) if rotulados else None,
        "acerto_automatico": sum(r["acerto"] for r in automaticos) / len(automaticos) if automaticos else None,
        "decisoes_automaticas": sum(r["decisao_automatica"] for r in linhas),
        "revisoes": sum(r["via"] == "revisao" for r in linhas),
        "chamadas_por_modelo": dict(Counter(c["modelo"] for c in chamadas)),
        "tokens": tokens if len(com_uso) == len(chamadas) else None,
        "tokens_conhecidos": tokens,
        "chamadas_sem_uso": len(chamadas) - len(com_uso),
        "execucao_local": {
            "duracao_ms": sum(c["duracao_ms"] for c in chamadas if c["provedor"] == "local"),
            "custo_usd": None,
            "situacao_custo": "indisponível: tarifa da máquina não informada",
        },
        **custos,
        "custo_medio_por_tentativa_usd": (
            custos["custo_usd"] / len(linhas) if linhas and custos["custo_usd"] is not None else None
        ),
    }


def relatorio(meta: dict, linhas: list[dict]) -> dict:
    por: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in linhas:
        por[r["unidade"], r["sha256"]].append(r)
    return {
        "tipo": meta["tipo"],
        "origem": meta["origem"],
        "versao_conjunto": meta["versao"],
        "rodado_em": dt.datetime.now(dt.UTC).isoformat(timespec="microseconds"),
        "escopo_custo": "API em USD; custo da máquina local não incluído",
        "precos": {"fonte": "genai-prices", "versao": version("genai-prices")},
        "resumo": _resumir(linhas),
        "por_entrada": [{"unidade": k[0], "sha256": k[1], **_resumir(v)} for k, v in por.items()],
        "linhas": linhas,
    }


def gravar(rel: dict, pasta: Path) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    arq = pasta / f"{rel['rodado_em'][:26].replace(':', '')}_cascata_{rel['tipo']}.json"
    # Mesmo sem texto ou gabarito, o relatório operacional não é artefato público.
    with arq.open("x", encoding="utf-8") as f:
        arq.chmod(0o600)
        json.dump(rel, f, ensure_ascii=False, indent=2)
    return arq
