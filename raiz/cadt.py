"""Cronogramas simulados de lotes no vocabulário do CAD Trust.

Não registra projetos nem emite unidades. A data inicial é uma hipótese explícita
de planejamento. Os objetos ``projeto`` seguem os campos do CADT; proveniência e
diagnósticos ficam no envelope Raíz, sem nomes, contatos ou códigos de imóveis.
"""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import hashlib
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from raiz import lote as L
from raiz import restauracao as R

VERSAO = "raiz-cadt-cenarios-1.2.0"
CADT_COMMIT = "58927db8f4b4fe558842a688d33f173c41944279"
REFERENCIA = f"https://github.com/Chia-Network/cadt/tree/{CADT_COMMIT}"
AVISO = (
    "Cenário de planejamento da Raíz, sem registro no CAD Trust ou na Verra e sem emissão de créditos. "
    "Listed identifica somente a listagem neste catálogo de cenários. O início do período é uma hipótese, "
    "não uma data contratada. VM0047 identifica a metodologia de referência, não certificação."
)
REPO = "bernardoemmel/Raiz"


class CronogramaInvalido(ValueError):
    """Dado inconsistente; o publicador registra o código, sem publicar um projeto inventado."""


def _identificar_fontes(pasta: Path) -> tuple[str | None, str | None]:
    """Exige uma única versão e cenário em todas as linhas, inclusive fora da oferta elegível."""
    campos = (("restauracao_versao", "versao"), ("restauracao_cenario", "cenario"))
    encontrados: dict[str, set[str]] = {nome: set() for _, nome in campos}
    for arquivo in sorted(pasta.glob("desenvolvedor_*.csv")):
        with arquivo.open(newline="", encoding="utf-8-sig") as entrada:
            leitor = csv.DictReader(entrada)
            for campo, nome in campos:
                if campo not in (leitor.fieldnames or []):
                    raise CronogramaInvalido(f"{nome}_da_fonte_ausente")
            for linha in leitor:
                for campo, nome in campos:
                    valor = linha.get(campo)
                    if valor is None or not valor.strip():
                        raise CronogramaInvalido(f"{nome}_da_fonte_ausente")
                    encontrados[nome].add(valor)
                    if len(encontrados[nome]) > 1:
                        raise CronogramaInvalido(f"{nome}_da_fonte_incompativel")
    return next(iter(encontrados["versao"]), None), next(iter(encontrados["cenario"]), None)


def _validar_fontes(pasta: Path, versao: str, cenario: str) -> None:
    """Não aplica uma regra a créditos calculados sob outra versão ou cenário."""
    v, c = _identificar_fontes(pasta)
    if v is not None and v != versao:
        raise CronogramaInvalido("versao_da_fonte_incompativel")
    if c is not None and c != cenario:
        raise CronogramaInvalido("cenario_da_fonte_incompativel")


def _resumo_cronograma(dados: dict, r: dict, c: dict, *, edital_versao: str | None = None) -> dict:
    """Seleciona o lote e soma o P50 publicado; não refaz fluxos, custos ou previsões individuais.

    O otimizador usa suas premissas atuais, identificadas separadamente; a curva e o cenário são exatamente os
    da versão das previsões. Evita L.montar, cujo relatório completo recalcula a economia de cada fazenda.
    """
    oferta = dados["oferta"]
    if len(oferta) and not oferta.restauracao_versao.eq(r["versao_completa"]).all():
        raise CronogramaInvalido("versao_da_fonte_incompativel")
    if not {"salvaguardas_planejamento", "salvaguardas_comercializavel"} <= set(oferta.columns):
        raise CronogramaInvalido("salvaguardas_da_oferta_ausentes")
    lt = L.premissas_lote(r)
    volume, chance = float(lt["creditos"]), float(lt["chance_alvo_reserva"])
    precisa50 = R.contrato_para_marcos(volume, c, r)
    precisa_alvo = precisa50 / R.fator_captura_alvo(chance, r)
    sel = L._selecionar(dados["oferta"], dados["uf"], precisa50, precisa_alvo, c)
    tit, res = sel["tit"], sel["res"]
    lote = pd.concat([tit, res], ignore_index=True)
    credito = float(lote.credito_p50.sum())
    if credito <= 0:
        return {"cronograma_lote": None}
    municipios = set(lote.cod_ibge.dropna().astype(int))
    return {
        "uf": dados["uf"],
        "data": dt.date.today().isoformat(),
        "cenario": c["cenario"],
        "versao_premissas": r["versao_completa"],
        "versao_otimizador": L.versao_modelo(),
        "versao_modelo_lote": L.versao_lote(c),
        "versao_salvaguardas": L.S.regra()["versao_completa"],
        "versao_edital": edital_versao or L.edital(r).get("versao"),
        "cronograma_lote": R.cronograma_lote(credito, c, r, volume),
        "titulares": int(len(tit)),
        "reservas": int(len(res)),
        "pequenas": int(lote.pequena.sum()),
        "municipios": {
            "no_estado": len(dados["municipios_estado"]),
            "lidos": len(dados["municipios_lidos"]),
            "com_fazenda_elegivel": int(sel["f"].cod_ibge.nunique()),
            "no_lote": len(municipios),
        },
    }


def _data(valor: dt.date | str, campo: str) -> dt.date:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    try:
        return dt.date.fromisoformat(str(valor))
    except ValueError as ex:
        raise CronogramaInvalido(f"{campo}_invalida") from ex


def _aniversario(inicio: dt.date, anos: int) -> dt.date:
    ano = inicio.year + anos
    dia = min(inicio.day, calendar.monthrange(ano, inicio.month)[1])
    return dt.date(ano, inicio.month, dia)


def estimativas_anuais(
    cronograma: dict, inicio: dt.date | str, prazo_anos: int, forma
) -> tuple[list[dict], list[dict]]:
    """Transforma a curva cumulativa P50 em incrementos anuais inteiros.

    Arredonda os acumulados (meia unidade para cima) e depois diferencia. Assim,
    a soma dos anos é exatamente o total arredondado e os marcos não são somados
    como se fossem emissões anuais. Ano zero deve ter captura nula.
    """
    inicio = _data(inicio, "data_inicio")
    try:
        prazo_inteiro = int(prazo_anos)
    except (TypeError, ValueError, OverflowError) as ex:
        raise CronogramaInvalido("prazo_invalido") from ex
    if isinstance(prazo_anos, bool) or prazo_inteiro != prazo_anos or not 1 <= prazo_anos <= 100:
        raise CronogramaInvalido("prazo_invalido")
    prazo_anos = prazo_inteiro
    if inicio.year + prazo_anos > 9999:
        raise CronogramaInvalido("prazo_fora_do_calendario")
    try:
        total = float(cronograma["credito_contrato_p50"])
        curva = np.asarray(forma, dtype=float)
    except (KeyError, TypeError, ValueError) as ex:
        raise CronogramaInvalido("curva_ou_credito_invalido") from ex
    if not math.isfinite(total) or total <= 0:
        raise CronogramaInvalido("credito_nao_positivo")
    if curva.ndim != 1 or len(curva) <= prazo_anos or not np.isfinite(curva).all() or (curva < 0).any():
        raise CronogramaInvalido("curva_invalida")
    if float(curva[0]) != 0:
        raise CronogramaInvalido("captura_no_ano_zero")
    acumulado = np.cumsum(curva[: prazo_anos + 1])
    if acumulado[-1] <= 0:
        raise CronogramaInvalido("curva_sem_captura_no_prazo")
    acumulado = acumulado / acumulado[-1] * total
    arredondado = [math.floor(float(v) + 0.5) for v in acumulado]
    marcos = cronograma.get("marcos")
    if not isinstance(marcos, list) or not marcos:
        raise CronogramaInvalido("marcos_ausentes")
    verificados, anos_vistos = [], set()
    for marco in marcos:
        try:
            ano = int(marco["ano"])
            valor = float(marco["acumulado_p50"])
        except (KeyError, TypeError, ValueError, OverflowError) as ex:
            raise CronogramaInvalido("marco_invalido") from ex
        if (
            isinstance(marco["ano"], bool)
            or ano != marco["ano"]
            or ano in anos_vistos
            or not 1 <= ano <= prazo_anos
            or not math.isfinite(valor)
        ):
            raise CronogramaInvalido("marco_invalido")
        if not math.isclose(valor, float(acumulado[ano]), rel_tol=1e-9, abs_tol=1e-6):
            raise CronogramaInvalido("marco_diverge_da_curva")
        anos_vistos.add(ano)
        verificados.append({"ano": ano, "acumulado_p50": valor, "acumulado_inteiro": arredondado[ano]})
    estimativas = []
    for ano in range(1, prazo_anos + 1):
        estimativas.append(
            {
                "creditingPeriodStart": _aniversario(inicio, ano - 1).isoformat(),
                "creditingPeriodEnd": (_aniversario(inicio, ano) - dt.timedelta(days=1)).isoformat(),
                "unitCount": arredondado[ano] - arredondado[ano - 1],
            }
        )
    return estimativas, sorted(verificados, key=lambda m: m["ano"])


def projeto_do_resumo(
    resumo: dict,
    uf: str,
    *,
    data_inicio: dt.date | str,
    data_referencia: dt.date | str | None = None,
    r: dict | None = None,
    c: dict | None = None,
    repo: str = REPO,
) -> dict:
    """Converte somente o resumo agregado do lote, com hipótese temporal explícita."""
    uf = uf.upper()
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise CronogramaInvalido("uf_invalida")
    r = r or R.regra()
    c = c or R.cenario("central_r11", r=r)
    if c.get("cenario") != "central_r11":
        raise CronogramaInvalido("cenario_nao_suportado")
    if resumo.get("cenario") != c["cenario"]:
        raise CronogramaInvalido("cenario_diverge_do_resumo")
    inicio = _data(data_inicio, "data_inicio")
    referencia = _data(data_referencia or resumo.get("data"), "data_referencia")
    cronograma = resumo.get("cronograma_lote")
    if not cronograma:
        raise CronogramaInvalido("sem_cronograma")
    versoes = {k: resumo.get(k) for k in ("versao_premissas", "versao_otimizador", "versao_edital")}
    for campo in ("versao_modelo_lote", "versao_salvaguardas"):
        if resumo.get(campo):
            versoes[campo] = resumo[campo]
    if not versoes["versao_premissas"] or not versoes["versao_otimizador"]:
        raise CronogramaInvalido("versao_modelo_ausente")
    estimativas, marcos = estimativas_anuais(cronograma, inicio, c["prazo_anos"], R.forma_curva(r))
    identidade = {
        "uf": uf,
        "cenario": c["cenario"],
        "inicio": inicio.isoformat(),
        "versoes": versoes,
        "exportador": VERSAO,
    }
    h = hashlib.sha256(json.dumps(identidade, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    identificador = f"raiz-cenario-{uf}-{h}"
    projeto = {
        "projectId": identificador,
        "originProjectId": identificador,
        "registryOfOrigin": "Raíz — catálogo de cenários",
        "projectName": f"Cenário ProFloresta+ Raíz — {uf} — início hipotético {inicio.isoformat()}",
        "projectLink": f"https://github.com/{repo}/releases/download/dados/cadt_lotes.json#{quote(identificador)}",
        "projectDeveloper": "Raíz — modelagem de cenário",
        "sector": "Agriculture; forestry and fishing",
        "projectType": "Reforestation and Revegetation",
        "coveredByNDC": "Unknown",
        "projectStatus": "Listed",
        "projectStatusDate": referencia.isoformat(),
        "unitMetric": "tCO2e",
        "methodology": "VCS - VM0047",
        "description": AVISO,
        "estimations": estimativas,
    }
    cobertura = resumo.get("municipios") or {}
    metadados = {
        "versao_exportador": VERSAO,
        "referencia_vocabulario": REFERENCIA,
        "cenario": c["cenario"],
        "versoes": versoes,
        "data_inicio_cenario": inicio.isoformat(),
        "data_inicio_contratada": False,
        "data_simulacao": referencia.isoformat(),
        "data_historica_das_fontes": None,
        "credito_contrato_p50": float(cronograma["credito_contrato_p50"]),
        "total_inteiro_tco2e": sum(e["unitCount"] for e in estimativas),
        "arredondamento": "acumulados P50 à unidade mais próxima (meia para cima), depois diferenças anuais",
        "marcos": marcos,
        "cobertura_municipios": {
            k: cobertura.get(k) for k in ("no_estado", "lidos", "com_fazenda_elegivel", "no_lote")
        },
        "fazendas": {k: resumo.get(k) for k in ("titulares", "reservas", "pequenas")},
        "aviso": AVISO,
    }
    return {"uf": uf, "projeto": projeto, "metadados": metadados, "diagnosticos": []}


def cadt_uf(
    pasta: str | Path,
    uf: str,
    *,
    data_inicio: dt.date | str | None,
    data_referencia: dt.date | str | None = None,
    r: dict | None = None,
    c: dict | None = None,
    repo: str = REPO,
) -> dict:
    """Lê ``saida/UF`` e monta o cenário ProFloresta+, sem copiar linhas de fazendas.

    Data inicial ausente ou dado ainda indisponível produz diagnóstico, não um
    projeto com estimativas fabricadas. Erros inesperados de leitura/cálculo não
    são escondidos pelo exportador.
    """
    pasta, uf = Path(pasta), uf.upper()
    base = {"uf": uf, "projeto": None, "metadados": {"versao_exportador": VERSAO, "aviso": AVISO}, "diagnosticos": []}

    def ausente(codigo: str) -> dict:
        base["diagnosticos"].append({"codigo": codigo})
        return base

    if data_inicio is None:
        return ausente("inicio_de_cenario_nao_informado")
    if pasta.name != uf or not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("pasta deve ser a pasta da UF informada")
    if not any(pasta.glob("desenvolvedor_*.csv")) or not any(pasta.glob("imoveis_*.csv")):
        return ausente("sem_tabelas_do_produto")
    proveniencia = {}
    try:
        versao_fonte, cenario_fonte = _identificar_fontes(pasta)
        if r is None:
            r = R.regra()
            if versao_fonte is not None and versao_fonte != r["versao_completa"]:
                from raiz.regras.historico import carregar

                try:
                    historica = carregar(versao_fonte)
                except ValueError as ex:
                    raise CronogramaInvalido("registro_historico_invalido") from ex
                if historica is None:
                    raise CronogramaInvalido("versao_da_fonte_incompativel")
                r, proveniencia = historica
        if c is None and proveniencia:
            from raiz.regras.historico import cenario

            try:
                c = cenario("central_r11", r)
            except ValueError as ex:
                raise CronogramaInvalido("registro_historico_invalido") from ex
        else:
            c = c or R.cenario("central_r11", r=r)
        if versao_fonte is not None and versao_fonte != r["versao_completa"]:
            raise CronogramaInvalido("versao_da_fonte_incompativel")
        if cenario_fonte is not None and cenario_fonte != c["cenario"]:
            raise CronogramaInvalido("cenario_da_fonte_incompativel")
    except CronogramaInvalido as ex:
        return ausente(str(ex))
    dados = L.ler_uf(pasta.parent, uf)
    if dados["oferta"].empty:
        return ausente("sem_fazendas_com_estimativa")
    try:
        resumo = _resumo_cronograma(dados, r, c, edital_versao=proveniencia.get("regra_source_edital_versao"))
    except CronogramaInvalido as ex:
        return ausente(str(ex))
    if not resumo.get("cronograma_lote"):
        return ausente("sem_lote_elegivel")
    try:
        resultado = projeto_do_resumo(
            resumo, uf, data_inicio=data_inicio, data_referencia=data_referencia, r=r, c=c, repo=repo
        )
        resultado["metadados"].update(proveniencia)
        resultado["metadados"]["origem_creditos"] = "P50 dos arquivos publicados; previsões individuais preservadas"
        resultado["metadados"]["selecao_lote"] = "otimizador atual aplicado aos créditos publicados"
        resultado["metadados"]["previsoes_individuais_recalculadas"] = False
        resultado["metadados"]["comercializacao"] = {
            "situacao": "pendente",
            "aviso": "Lote potencial para diligência, sem liberação de venda. Conferir exclusão jurisdicional, "
            "CLPI, título, aceite e certificação.",
        }
        return resultado
    except CronogramaInvalido as ex:
        return ausente(str(ex))


def combinar_estados(estados: Mapping[str, dict]) -> dict:
    """Reúne resultados estaduais persistidos sob a trava do índice, sem reler os CSV."""
    projetos, resumos = [], {}
    for uf, resultado in sorted(estados.items()):
        if resultado.get("uf") != uf:
            raise ValueError("resultado CADT de UF diferente da chave do índice")
        projeto = resultado.get("projeto")
        if projeto:
            projetos.append(projeto)
        resumos[uf] = {
            "projectId": projeto["projectId"] if projeto else None,
            "metadados": resultado.get("metadados") or {},
            "diagnosticos": resultado.get("diagnosticos") or [],
        }
    return {
        "versao_exportador": VERSAO,
        "referencia_vocabulario": REFERENCIA,
        "aviso": AVISO,
        "projetos": projetos,
        "estados": resumos,
    }
