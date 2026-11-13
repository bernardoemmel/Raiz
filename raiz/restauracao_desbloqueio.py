"""Diligência dos lotes publicados, sem refazer previsões nem liberar créditos.

O quadro cobre somente titulares e reservas. Terra documentada significa a
classificação existente no snapshot: este relatório não autentica o título.
Uma referência documental isolada permanece pendente de conferência.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path

import pandas as pd
import yaml

ARQUIVO = Path(__file__).parent / "regras/padroes/desbloqueio_lote.yaml"
PAPEIS = ("titular", "reserva")
TERRA_DOCUMENTADA = frozenset({"matricula_conferida", "concessao"})
QUANTIS = ("p10", "p50", "p90")
REQUERIDAS = frozenset(
    {
        "papel",
        "cod_imovel",
        "area_ha",
        "credito_p10",
        "credito_p50",
        "credito_p90",
        "caminho",
        "restauracao_versao",
        "salvaguardas_pendencias",
    }
)
GATES_PROJETO = (
    "aceite_direito_carbono",
    "linha_base_controles",
    "permanencia_buffer",
    "certificacao_emissao",
)


def regra() -> dict:
    texto = ARQUIVO.read_bytes()
    r = yaml.safe_load(texto)
    h = hashlib.sha256(texto + Path(__file__).read_bytes()).hexdigest()[:12]
    r["versao_completa"] = f"{r['versao']}+{h}"
    return r


def _texto(x) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    texto = str(x).strip()
    return "" if texto.lower() in {"nan", "none", "null", "<na>"} else texto


def _numero(x) -> float | None:
    if isinstance(x, bool):
        return None
    try:
        n = float(x)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) else None


def _serie(t: pd.DataFrame, coluna: str) -> pd.Series:
    if coluna not in t:
        return pd.Series(float("nan"), index=t.index, dtype=float)
    return t[coluna].map(_numero).astype(float)


def _quantidade(t: pd.DataFrame) -> dict:
    return {
        "fazendas": len(t),
        "ha_restauracao": round(float(t.area_ha.sum()), 6),
        "creditos": {q: round(float(t[f"credito_{q}"].sum()), 6) for q in QUANTIS},
    }


def _preparar(tabela: pd.DataFrame, resumo: Mapping) -> tuple[pd.DataFrame, str, float]:
    ausentes = REQUERIDAS - set(tabela.columns)
    if ausentes:
        raise ValueError("O lote não possui as colunas necessárias: " + ", ".join(sorted(ausentes)))
    t = tabela.loc[tabela.papel.isin(PAPEIS)].copy().reset_index(drop=True)
    ids = t.cod_imovel.map(_texto)
    if ids.eq("").any() or ids.duplicated().any():
        raise ValueError("As selecionadas precisam ter identificadores únicos e preenchidos.")
    t["cod_imovel"] = ids
    modelo_resumo = _texto(resumo.get("versao_premissas") or resumo.get("modelo_versao"))
    modelos = set(t.restauracao_versao.map(_texto))
    if "" in modelos or len(modelos) > 1 or (modelos and modelo_resumo not in modelos):
        raise ValueError("O relatório não aceita modelo ausente, misturado ou diferente do resumo.")
    if not modelo_resumo:
        raise ValueError("O resumo precisa informar a versão do modelo de restauração.")
    for c in ("area_ha", *(f"credito_{q}" for q in QUANTIS)):
        t[c] = t[c].map(_numero).astype(float)
        if not t[c].map(lambda n: math.isfinite(n) and n >= 0).all():
            raise ValueError(f"As selecionadas possuem {c} ausente, negativo ou não finito.")
    if ((t.credito_p10 > t.credito_p50) | (t.credito_p50 > t.credito_p90)).any():
        raise ValueError("A faixa de créditos das selecionadas está fora de ordem.")
    meta = _numero(resumo.get("volume_creditos"))
    if meta is None or meta <= 0:
        raise ValueError("A meta de créditos precisa ser positiva e finita.")
    # Não substituir valores do CSV por totais arredondados do resumo.
    for papel, chave in (("titular", "titulares"), ("reserva", "reservas")):
        if chave in resumo and _numero(resumo[chave]) != int(t.papel.eq(papel).sum()):
            raise ValueError("O número de selecionadas não confere com o resumo.")
    t["caminho"] = t.caminho.map(_texto)
    return t, modelo_resumo, meta


def _ponderada(t: pd.DataFrame, coluna: str) -> dict:
    valores = _serie(t, coluna)
    peso = t.credito_p50
    validos = valores.map(math.isfinite)
    faltam = (~validos) & peso.gt(0)
    total = float(peso.sum())
    valor = None
    if total > 0 and not faltam.any():
        valor = round(float((valores[validos] * peso[validos]).sum()) / total, 4)
    return {
        "valor": valor,
        "unidade": "USD por credito",
        "coluna_origem": coluna,
        "metodo": "média entre fazendas ponderada pelos créditos P50 publicados",
        "fazendas_validas": int(validos.sum()),
        "fazendas_sem_valor": int((~validos).sum()),
        "credito_p50_sem_valor": round(float(peso[faltam].sum()), 6),
        "situacao": "calculada" if valor is not None else "indisponivel",
        "motivo_indisponibilidade": None
        if valor is not None
        else "Créditos totais nulos ou métrica ausente em fazenda com peso positivo; não preencher com zero.",
    }


def _mediana_tir(t: pd.DataFrame, coluna: str) -> dict:
    valores = _serie(t, coluna)
    finitos = valores.map(math.isfinite)
    sentinelas = finitos & valores.le(-100)
    validos = finitos & ~sentinelas
    # Não anunciar mediana do conjunto inteiro quando somente parte dele tem TIR.
    valor = round(float(valores.median()), 4) if len(t) and validos.all() else None
    return {
        "valor": valor,
        "unidade": "percentual ao ano",
        "coluna_origem": coluna,
        "metodo": "mediana entre fazendas, sem ponderação; cada valor é a TIR do caminho central",
        "interpretacao": "Não é a mediana dos sorteios Monte Carlo nem a TIR do fluxo agregado do lote.",
        "fazendas_validas": int(validos.sum()),
        "fazendas_sem_tir": int((~validos).sum()),
        "sentinelas_menos100": int(sentinelas.sum()),
        "situacao": "calculada" if valor is not None else "indisponivel",
        "motivo_indisponibilidade": None
        if valor is not None
        else "Há TIR não disponível ou o lote está vazio; -100 legado significa TIR não encontrada, não taxa medida.",
    }


def _terra(t: pd.DataFrame, meta: float) -> dict:
    documentada = t.caminho.isin(TERRA_DOCUMENTADA)
    pronta, pendente = _quantidade(t[documentada]), _quantidade(t[~documentada])
    pronta_meta = min(meta, pronta["creditos"]["p50"])
    pendente_meta = min(meta - pronta_meta, pendente["creditos"]["p50"])
    falta = max(0.0, meta - pronta_meta - pendente_meta)
    for parte, na_meta in ((pronta, pronta_meta), (pendente, pendente_meta)):
        parte["credito_p50_alocado_meta"] = round(na_meta, 6)
        parte["fracao_meta_pct"] = round(100 * na_meta / meta, 6)
        parte["credito_p50_excedente"] = round(max(0.0, parte["creditos"]["p50"] - na_meta), 6)
    return {
        "criterio": "Documentada na classificação publicada: matricula_conferida ou concessao. "
        "matricula_a_conferir e CAR não são prova conferida de direito. Não revalida o título fora do snapshot.",
        "documentada": pronta,
        "pendente": pendente,
        "meta_creditos": meta,
        "credito_p50_faltante_meta": round(falta, 6),
        "fracao_meta_faltante_pct": round(100 * falta / meta, 6),
        "alocacao": "Alocar à meta primeiro os créditos com terra documentada e depois os pendentes. "
        "As categorias são exclusivas; percentuais ficam limitados a 100% e o excedente é separado. "
        "Esta conta estática não comprova cumprimento dos marcos de entrega nem liberação comercial.",
    }


def _pendencias(valor) -> set[str]:
    if isinstance(valor, list):
        return {_texto(x.get("codigo")) for x in valor if isinstance(x, Mapping) and _texto(x.get("codigo"))}
    return {x.strip() for x in _texto(valor).split(";") if x.strip()}


def _trava_desconhecida(codigo: str) -> dict:
    return {
        "nome": "Pendência publicada sem roteiro específico",
        "natureza": "revisao_de_decisao",
        "documento": "Registro de origem da pendência e evidência pertinente ao critério.",
        "conferencia": f"Revisar o critério {codigo}; código novo não é ignorado nem convertido em autorização.",
        "responsavel": "Equipe responsável pela regra e revisor humano.",
        "marco": "Antes de tratar a pendência como resolvida.",
        "fundamento": "Conservação de pendência publicada e revisão do critério; confirmar a base específica.",
        "fontes": ["lgpd"],
    }


def _roteiro(codigo: str, r: dict) -> dict:
    item = copy.deepcopy(r["travas"].get(codigo) or _trava_desconhecida(codigo))
    item["fontes"] = [r["fontes"][x] for x in item["fontes"]]
    item["prazo_dias"] = None
    item["tipo_prazo"] = "marco_operacional_sem_SLA_em_dias"
    return item


def _exigencias_projeto(resumo: Mapping, t: pd.DataFrame) -> list[dict]:
    """Conserva os bloqueios do edital sem atribuir uma interseção a cada fazenda."""
    out = []
    for item in resumo.get("checklist") or []:
        if item.get("gravidade") != "bloqueia" or item.get("situacao") == "ok":
            continue
        out.append(
            {
                "codigo": _texto(item.get("id")),
                "nome": _texto(item.get("item")),
                "bloco": _texto(item.get("bloco")),
                "situacao_origem": _texto(item.get("situacao")) or "a_conferir",
                "fundamento": _texto(item.get("exigido_por")),
                "fontes": [x.strip() for x in _texto(item.get("fonte")).split("|") if x.strip()],
                "documento_ou_condicao": _texto(item.get("item")),
                "conferencia": _texto(item.get("detalhe")),
                "responsavel": "Responsável pelo projeto e equipe competente para a exigência citada.",
                "marco": "Conferir o marco da exigência e da versão do edital citados; "
                "o snapshot não informa prazo de atendimento em dias.",
                "prazo_dias": None,
                "abrangencia": "Exigência do projeto inteiro no checklist publicado. "
                "A cobertura do lote não é uma medição de sobreposição ou de infração física por imóvel.",
                **_quantidade(t),
                "somavel": False,
                "liberacao_automatica": False,
            }
        )
    return out


def relatorio(
    tabela: pd.DataFrame,
    resumo: Mapping,
    *,
    evidencias: Mapping[str, Mapping[str, str]] | None = None,
) -> dict:
    """Resume o lote, sem alterar seleção, dados históricos ou situação comercial.

    ``evidencias`` contém somente referências por imóvel/código de trava. Elas
    são contadas, não publicadas nem aceitas como prova conferida. Este relatório
    não é o fluxo autenticado de aprovação de documentos.
    """
    t, modelo, meta = _preparar(tabela, resumo)
    r = regra()
    referencias = evidencias or {}
    if not isinstance(referencias, Mapping) or any(not isinstance(v, Mapping) for v in referencias.values()):
        raise ValueError("As referências devem ser organizadas por imóvel e código de trava.")
    codigos = t.salvaguardas_pendencias.map(_pendencias)
    todos = set().union(*codigos) if len(t) else set()
    mascaras = {
        codigo: codigos.map(lambda cs, c=codigo: c in cs).astype(bool)
        for codigo in (*r["travas"], *sorted(todos - set(r["travas"])))
    }
    mascaras["titulo_terra"] = ~t.caminho.isin(TERRA_DOCUMENTADA)
    for codigo in GATES_PROJETO:
        mascaras[codigo] = pd.Series(True, index=t.index, dtype=bool)
    vz = t.get("vazamento_motivo", pd.Series("", index=t.index)).map(_texto)
    vizinha = t.get("vazamento_mitigacao_imovel", pd.Series("", index=t.index)).map(_texto)
    mascaras["vazamento_mitigacao"] = vz.eq("mitigacao_vizinha") | vizinha.ne("")
    travas = []
    uniao = pd.Series(False, index=t.index, dtype=bool)
    for codigo, mascara in mascaras.items():
        uniao |= mascara
        linhas = t[mascara]
        refs = sum(bool(_texto(referencias.get(cod, {}).get(codigo))) for cod in linhas.cod_imovel)
        projeto = codigo in GATES_PROJETO or codigo == "vazamento_mitigacao"
        travas.append(
            {
                "codigo": codigo,
                **_roteiro(codigo, r),
                **_quantidade(linhas),
                "situacao": "nao_comprovada_no_pacote"
                if len(linhas) and projeto
                else "pendente_no_snapshot"
                if len(linhas)
                else "nao_sinalizada_no_snapshot",
                "incidencia": "Exigência documental do projeto, sem documento conferido neste pacote; "
                "não afirma que a documentação inexiste fora dele."
                if projeto
                else "Classificação ou pendência publicada; área afetada é a área de restauração da fazenda, "
                "não a medida geográfica da interseção.",
                "referencias_recebidas_sem_conferencia": refs,
                "somavel": False,
                "liberacao_automatica": False,
            }
        )
    economia = resumo.get("economia") or {}
    referencia_resumo = {
        k: resumo.get(k)
        for k in (
            "uf",
            "opcao",
            "data",
            "versao_premissas",
            "versao_modelo_lote",
            "volume_creditos",
            "preco_contrato_usd",
        )
    }
    selecionadas = t.sort_values("cod_imovel").reset_index(drop=True).to_json(orient="split", date_format="iso")
    pequena = t.get("pequena", pd.Series(False, index=t.index)).map(
        lambda x: _texto(x).lower() in {"true", "1", "1.0", "sim"}
    )
    return {
        "versao_relatorio": r["versao_completa"],
        "modelo_versao": modelo,
        "modelo_lote_versao": _texto(resumo.get("versao_modelo_lote")) or None,
        "uf": _texto(resumo.get("uf")) or "UF",
        "opcao": _texto(resumo.get("opcao")) or "lote",
        "data_snapshot": _texto(resumo.get("data")) or None,
        "escopo": "Somente titulares e reservas do snapshot; exclui linhas de espera e áreas de mitigação. "
        "Hectares são de restauração, não a área total dos imóveis. Pequenas não são descartadas.",
        "selecionadas": {**_quantidade(t), "pequenas": int(pequena.sum())},
        "financeiro": {
            "preco_contrato_cenario_usd_t": _numero(resumo.get("preco_contrato_usd")),
            "aviso_preco": "Preço do cenário, sem inferir transação ou oferta firme. "
            "Custo e equilíbrio são métricas distintas.",
            "custo_medio_ponderado_usd_t": _ponderada(t, "custo_credito_usd"),
            "equilibrio_individual_medio_ponderado_usd_t": _ponderada(t, "preco_equilibrio_usd"),
            "equilibrio_fluxo_lote_usd_t": _numero(economia.get("preco_equilibrio_usd")),
            "tir_mediana_central_projeto_pct": _mediana_tir(t, "tir_projeto"),
            "tir_mediana_central_alavancada_pct": _mediana_tir(t, "tir_p50"),
            "tir_fluxo_lote_projeto_pct": _numero(economia.get("tir_projeto_pct")),
            "tir_fluxo_lote_alavancada_pct": _numero(economia.get("tir_alavancada_pct")),
        },
        "terra_meta": _terra(t, meta),
        "travas": travas,
        "uniao_fazendas_com_pendencia": _quantidade(t[uniao]),
        "interpretacao_travas": "Uma fazenda pode ter várias travas. Não somar linhas, hectares nem créditos. "
        "Resolver uma trava não remove as outras nem representa crédito emitido. Referências recebidas não são "
        "provas conferidas. Incidência zero indica somente ausência de sinalização no snapshot.",
        "comercializacao": {
            "situacao": "nao_liberada_por_este_relatorio",
            "aviso": "A análise explica pendências; não autentica títulos, aceita contratos, "
            "certifica ou libera venda.",
        },
        "exigencias_projeto_pendentes": _exigencias_projeto(resumo, t),
        "checklist_origem": copy.deepcopy(resumo.get("checklist") or []),
        "homologacao_inicial_edital": copy.deepcopy(resumo.get("certidoes") or {}),
        "fontes": copy.deepcopy(r["fontes"]),
        "proveniencia": {
            "selecionadas_sha256": hashlib.sha256(selecionadas.encode()).hexdigest(),
            "resumo_parametros_sha256": hashlib.sha256(
                json.dumps(referencia_resumo, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
            "recalculo_realizado": False,
        },
    }


def _formatar(valor, casas: int = 2) -> str:
    if valor is None:
        return "indisponível"
    texto = f"{float(valor):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _md(valor) -> str:
    return html.escape(str(valor)).replace("|", "\\|").replace("\n", " ")


def markdown(rel: Mapping) -> str:
    f, terra = rel["financeiro"], rel["terra_meta"]
    s = rel["selecionadas"]
    linhas = [
        f"# Diligência do lote {_md(rel['uf'])}: {_md(rel['opcao'])}",
        "",
        f"Modelo de origem: `{_md(rel['modelo_versao'])}`. "
        f"Relatório: `{_md(rel['versao_relatorio'])}`. Nenhuma previsão foi recalculada.",
        "",
        f"{s['fazendas']} fazendas selecionadas, {_formatar(s['ha_restauracao'])} ha de restauração, "
        f"{s['pequenas']} pequenas. {_md(rel['comercializacao']['aviso'])}",
        "",
        "| Métrica | Valor |",
        "|---|---:|",
        f"| Preço do cenário (US$/crédito) | {_formatar(f['preco_contrato_cenario_usd_t'])} |",
        "| Custo médio, ponderado por créditos P50 (US$/crédito) | "
        f"{_formatar(f['custo_medio_ponderado_usd_t']['valor'])} |",
        "| Equilíbrio individual médio, ponderado por créditos P50 (US$/crédito) | "
        f"{_formatar(f['equilibrio_individual_medio_ponderado_usd_t']['valor'])} |",
        f"| Equilíbrio do fluxo agregado (US$/crédito) | {_formatar(f['equilibrio_fluxo_lote_usd_t'])} |",
        "| Mediana das TIRs centrais por fazenda, projeto (% a.a.) | "
        f"{_formatar(f['tir_mediana_central_projeto_pct']['valor'])} |",
        "| Mediana das TIRs centrais por fazenda, alavancada (% a.a.) | "
        f"{_formatar(f['tir_mediana_central_alavancada_pct']['valor'])} |",
        f"| TIR do fluxo agregado, projeto (% a.a.) | {_formatar(f['tir_fluxo_lote_projeto_pct'])} |",
        f"| TIR do fluxo agregado, alavancada (% a.a.) | {_formatar(f['tir_fluxo_lote_alavancada_pct'])} |",
        "",
        "A mediana acima é entre fazendas, sem ponderação. O P50 legado de TIR é caminho central, "
        "não mediana de Monte Carlo; -100 é sentinela de TIR não encontrada. "
        "Uma métrica com fazenda sem valor fica indisponível; não se completa com zero.",
        "",
        f"Meta: {_formatar(terra['meta_creditos'], 0)} créditos. "
        f"Terra documentada na classificação: {_formatar(terra['documentada']['fracao_meta_pct'])}% da meta; "
        f"terra pendente: {_formatar(terra['pendente']['fracao_meta_pct'])}%; "
        f"oferta faltante: {_formatar(terra['fracao_meta_faltante_pct'])}%.",
        "",
        _md(terra["criterio"]),
        "",
        "| Trava sinalizada ou prova não comprovada | Fazendas | ha de restauração | Créditos P50 |",
        "|---|---:|---:|---:|",
    ]
    for item in rel["travas"]:
        if item["fazendas"]:
            linhas.append(
                f"| {_md(item['nome'])} | {item['fazendas']} | {_formatar(item['ha_restauracao'])} | "
                f"{_formatar(item['creditos']['p50'], 0)} |"
            )
    linhas.extend(["", _md(rel["interpretacao_travas"]), ""])
    for item in rel["travas"]:
        if item["fazendas"]:
            linhas.extend(
                [
                    f"## {_md(item['nome'])}",
                    "",
                    f"Documento: {_md(item['documento'])}",
                    "",
                    f"Conferência: {_md(item['conferencia'])}",
                    "",
                    f"Responsável: {_md(item['responsavel'])}",
                    "",
                    f"Prazo: {_md(item['marco'])} Sem SLA confirmado em dias.",
                    "",
                    "Fontes: " + "; ".join(item["fontes"]),
                    "",
                ]
            )
    linhas.extend(
        [
            "O JSON mantém também as salvaguardas sem sinalização, os valores P10/P90, o checklist e "
            "a homologação inicial do edital. Requisitos de projeto não significam sobreposição física confirmada.",
            "",
        ]
    )
    cert = rel["homologacao_inicial_edital"]
    if cert:
        linhas.extend(
            [
                "## Marco de homologação inicial do edital",
                "",
                f"Área exigida na assinatura: {_formatar(_numero(cert.get('ha_exigidos')))} ha; "
                f"homologada na classificação publicada: {_formatar(_numero(cert.get('ha_homologados')))} ha; "
                f"falta: {_formatar(_numero(cert.get('falta_ha')))} ha.",
                "",
                "Esse requisito parcial de assinatura não corresponde à área inteira do lote e não dispensa "
                "a conferência dos direitos de todas as fazendas nem as demais salvaguardas. A sugestão de pedir "
                "certidão não é certidão recebida, autenticada ou aceita.",
                "",
            ]
        )
    if rel["exigencias_projeto_pendentes"]:
        linhas.extend(
            [
                "## Exigências do projeto ainda pendentes no checklist publicado",
                "",
                "Afetam a homologação ou a contratação do projeto inteiro. Não representam nova interseção "
                "territorial por fazenda nem nova soma de hectares ou créditos.",
                "",
                "| Exigência | Situação no snapshot | Conferência e fonte |",
                "|---|---|---|",
            ]
        )
        for item in rel["exigencias_projeto_pendentes"]:
            linhas.append(
                f"| {_md(item['nome'])} | {_md(item['situacao_origem'])} | "
                f"{_md(item['conferencia'])} {'; '.join(item['fontes'])} |"
            )
        linhas.append("")
    return "\n".join(linhas)


def gravar(rel: Mapping, pasta: str | Path) -> dict[str, str]:
    """Grava somente indicadores agregados; mantém os detalhes das referências fora da exportação."""
    pasta = Path(pasta)
    uf, opcao = str(rel["uf"]), str(rel["opcao"])
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", uf) or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", opcao):
        raise ValueError("Identificador de região ou opção inválido para o nome do relatório.")
    pasta.mkdir(parents=True, exist_ok=True)
    base = pasta / f"desbloqueio_{uf}_{opcao}"
    out = {tipo: str(base.with_suffix(sufixo)) for tipo, sufixo in
           (("json", ".json"), ("csv", ".csv"), ("markdown", ".md"), ("html", ".html"))}  # fmt: skip
    Path(out["json"]).write_text(
        json.dumps(rel, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    linhas = []
    for item in rel["travas"]:
        linhas.append(
            {
                **{
                    k: item[k]
                    for k in (
                        "codigo",
                        "nome",
                        "natureza",
                        "situacao",
                        "fazendas",
                        "ha_restauracao",
                        "documento",
                        "conferencia",
                        "responsavel",
                        "marco",
                        "prazo_dias",
                        "tipo_prazo",
                        "fundamento",
                        "somavel",
                    )
                },
                **{f"credito_{q}": item["creditos"][q] for q in QUANTIS},
                "fontes": "; ".join(item["fontes"]),
                "modelo_versao": rel["modelo_versao"],
                "versao_relatorio": rel["versao_relatorio"],
            }
        )
    pd.DataFrame(linhas).to_csv(out["csv"], index=False)
    texto = markdown(rel)
    Path(out["markdown"]).write_text(texto, encoding="utf-8")
    # O HTML usa texto escapado; referências recebidas nunca viram HTML ativo.
    pagina = '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Diligência do lote</title>'
    pagina += '<meta name="viewport" content="width=device-width,initial-scale=1">'
    pagina += "<style>body{max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17362b;background:#fafbf8}"
    pagina += "pre{white-space:pre-wrap;font:15px/1.55 ui-monospace,monospace}a{color:#175f45}</style>"
    pagina += "<body><pre>" + html.escape(texto) + "</pre></body></html>"
    Path(out["html"]).write_text(pagina, encoding="utf-8")
    return out
