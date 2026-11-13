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

VERSAO = "raiz-cadt-cenarios-1.3.0"
CADT_COMMIT = "58927db8f4b4fe558842a688d33f173c41944279"
REFERENCIA = f"https://github.com/Chia-Network/cadt/tree/{CADT_COMMIT}"
AVISO = (
    "Cenário de planejamento da Raíz, sem registro no CAD Trust ou na Verra e sem emissão de créditos. "
    "Listed identifica somente a listagem neste catálogo de cenários. O início do período é uma hipótese, "
    "não uma data contratada. VM0047 identifica a metodologia de referência, não certificação."
)
REPO = "bernardoemmel/Raiz"
HISTORICA_2026B = "restauracao-2026b+cenarios-2026b+dbc2776a"
METODO_2026B = "cronograma-deterministico-2026b-1"


class CronogramaInvalido(ValueError):
    """Dado inconsistente; o publicador registra o código, sem publicar um projeto inventado."""


def _catalogo_privado(url: str) -> None:
    from raiz.metadados import _url_acesso

    try:
        _url_acesso(url, escopo="privado")
        if not url.endswith("/cadt_lotes.json"):
            raise ValueError("arquivo de catálogo diferente")
    except ValueError as ex:
        raise CronogramaInvalido("catalogo_privado_invalido") from ex


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


def _conferir_tarefa_historica(pasta: Path, versao: str) -> dict:
    """O hash YAML antigo não identifica o código: exige a tarefa original e os bytes do CSV."""
    try:
        arquivo = pasta / "_versoes.json"
        manifesto = json.loads(arquivo.read_text()) if arquivo.exists() else {}
        if not isinstance(manifesto, dict):
            raise ValueError
        quantidade = 0
        for csv_ in sorted(pasta.glob("desenvolvedor_*.csv")):
            meta = manifesto.get(csv_.name) or {}
            lateral = csv_.with_name(csv_.name + ".meta.json")
            if lateral.exists():
                outra = json.loads(lateral.read_text())
                if not isinstance(meta, dict) or not isinstance(outra, dict):
                    raise ValueError
                if any(k in meta and k in outra and meta[k] != outra[k] for k in ("tarefa", "versao", "sha256")):
                    raise ValueError
                meta = {**meta, **outra}
            if not isinstance(meta, dict) or meta.get("tarefa") != "desenvolvedor" or meta.get("versao") != versao:
                raise ValueError
            digest = hashlib.sha256()
            with csv_.open("rb") as entrada:
                for bloco in iter(lambda: entrada.read(1 << 20), b""):
                    digest.update(bloco)
            if meta.get("sha256") != digest.hexdigest():
                raise ValueError
            quantidade += 1
        if not quantidade:
            raise ValueError
    except (OSError, ValueError, TypeError):
        raise CronogramaInvalido("codigo_historico_da_fonte_nao_comprovado") from None
    return {
        "versao_tarefa_fonte_verificada": versao,
        "arquivos_fonte_verificados": quantidade,
        "evidencia_tarefa": "metadados_do_arquivo_e_sha256_dos_bytes",
    }


def _cronograma_2026b(credito: float, c: dict, r: dict) -> dict:
    """Distribui apenas o total publicado; não reconstrói chances, multas ou fluxos por imóvel."""
    from raiz.regras.historico import forma_curva_2026b

    acumulado = np.cumsum(forma_curva_2026b(r))
    acumulado = acumulado / acumulado[int(c["prazo_anos"])] * credito
    return {
        "credito_contrato_p50": credito,
        "marcos": [{"ano": int(a), "acumulado_p50": float(acumulado[int(a)])} for a in c["entregas_anos"]],
    }


def _oferta_p50_publicado(pasta: Path, oferta: pd.DataFrame, *, versao: str | None = None) -> pd.DataFrame:
    """Preserva o total publicado: o P50 por hectare foi arredondado separadamente."""
    totais = {}
    areas = (
        ["restauracao_area_ha", *(f"restauracao_{modo}_ha" for modo in L.METODOS)] if versao == HISTORICA_2026B else []
    )
    curva = ["credito_liquido_tco2_ha_contrato_p50", "credito_liquido_tco2_ha_horizonte"] if areas else []
    try:
        for arquivo in sorted(pasta.glob("desenvolvedor_*.csv")):
            for bloco in pd.read_csv(
                arquivo,
                usecols=["cod_imovel", "credito_liquido_tco2_contrato", *areas, *curva],
                dtype={"cod_imovel": str},
                chunksize=100_000,
            ):
                valores = pd.to_numeric(bloco.credito_liquido_tco2_contrato, errors="coerce")
                if not (np.isfinite(valores) & valores.ge(0) & valores.eq(np.floor(valores))).all():
                    raise ValueError
                if areas:
                    fisicas = bloco[areas].apply(pd.to_numeric, errors="coerce")
                    # Cada uma das quatro áreas foi publicada com quatro casas.
                    # A tolerância é somente a soma desses arredondamentos.
                    if (
                        not np.isfinite(fisicas).all().all()
                        or (fisicas < 0).any().any()
                        or ((fisicas[areas[0]] - fisicas[areas[1:]].sum(axis=1)).abs() > 0.000200001).any()
                        or (valores.gt(0) & fisicas[areas[0]].eq(0)).any()
                    ):
                        raise CronogramaInvalido("areas_historicas_incompativeis")
                    publicados = bloco.loc[valores.gt(0), curva].apply(pd.to_numeric, errors="coerce")
                    # Se o teto fosse atingido até 25, N40 seria igual a N25.
                    # Cada P50/ha tem erro de arredondamento de até 0,05.
                    if (
                        not np.isfinite(publicados).all().all()
                        or (publicados < 0).any().any()
                        or ((publicados[curva[1]] - publicados[curva[0]]) <= 0.100000001).any()
                    ):
                        raise CronogramaInvalido("curva_historica_nao_comprovada")
                for codigo, valor in zip(bloco.cod_imovel, valores, strict=True):
                    if not isinstance(codigo, str) or not codigo or codigo in totais:
                        raise ValueError
                    totais[codigo] = float(valor)
        credito = oferta.cod_imovel.map(totais)
        if credito.isna().any():
            raise ValueError
    except CronogramaInvalido:
        raise
    except (OSError, ValueError, TypeError):
        raise CronogramaInvalido("total_p50_publicado_nao_comprovado") from None
    return oferta.assign(credito_p50=credito)


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
    legado = r.get("versao_completa") == HISTORICA_2026B
    # A versão 2026b antecede o otimizador de lotes. Sua curva e seus créditos
    # não recebem regras novas; a política atual apenas escolhe a carteira.
    r_selecao = R.regra() if legado else r
    c_selecao = R.cenario("central_r11", r=r_selecao) if legado else c
    lt = L.premissas_lote(r_selecao)
    volume, chance = float(lt["creditos"]), float(lt["chance_alvo_reserva"])
    precisa50 = R.contrato_para_marcos(volume, c_selecao, r_selecao)
    precisa_alvo = precisa50 / R.fator_captura_alvo(chance, r_selecao)
    sel = L._selecionar(dados["oferta"], dados["uf"], precisa50, precisa_alvo, c_selecao)
    tit, res = sel["tit"], sel["res"]
    lote = pd.concat([tit, res], ignore_index=True)
    credito = float(lote.credito_p50.sum())
    municipios = set(lote.cod_ibge.dropna().astype(int))
    resumo = {
        "uf": dados["uf"],
        "data": dt.date.today().isoformat(),
        "cenario": c["cenario"],
        "versao_premissas": r["versao_completa"],
        "versao_otimizador": L.versao_modelo(),
        "versao_modelo_lote": L.versao_lote(c_selecao),
        "versao_salvaguardas": L.S.regra()["versao_completa"],
        "versao_edital": edital_versao or L.edital(r_selecao).get("versao"),
        "cronograma_lote": (_cronograma_2026b(credito, c, r) if legado else R.cronograma_lote(credito, c, r, volume))
        if credito > 0
        else None,
        "diagnostico_selecao": {
            "oferta_com_estimativa": int(len(oferta)),
            "caminho_pronto": int(oferta.caminho.isin(L.PRONTA).sum()),
            "elegiveis_pedido": int(len(sel["f"])),
        },
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
    if legado:
        resumo.update(versao_metodo_cronograma=METODO_2026B, versao_premissas_selecao=r_selecao["versao_completa"])
    return resumo


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
    url_catalogo: str,
    data_referencia: dt.date | str | None = None,
    r: dict | None = None,
    c: dict | None = None,
    repo: str = REPO,
) -> dict:
    """Converte somente o resumo agregado do lote, com hipótese temporal explícita."""
    _catalogo_privado(url_catalogo)
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
    for campo in ("versao_modelo_lote", "versao_salvaguardas", "versao_metodo_cronograma", "versao_premissas_selecao"):
        if resumo.get(campo):
            versoes[campo] = resumo[campo]
    if not versoes["versao_premissas"] or not versoes["versao_otimizador"]:
        raise CronogramaInvalido("versao_modelo_ausente")
    if r.get("versao_completa") == HISTORICA_2026B:
        from raiz.regras.historico import cenario as cenario_historico
        from raiz.regras.historico import forma_curva_2026b

        if versoes.get("versao_metodo_cronograma") != METODO_2026B or not versoes.get("versao_premissas_selecao"):
            raise CronogramaInvalido("metodo_historico_nao_identificado")
        if c != cenario_historico("central_r11", r):
            raise CronogramaInvalido("cenario_historico_nao_comprovado")
        forma = forma_curva_2026b(r)
    else:
        forma = R.forma_curva(r)
    estimativas, marcos = estimativas_anuais(cronograma, inicio, c["prazo_anos"], forma)
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
        "projectLink": f"{url_catalogo}#{quote(identificador)}",
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
        "escopo": "privado",
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
    if r.get("versao_completa") == HISTORICA_2026B:
        metadados.update(
            metodo_cronograma=METODO_2026B,
            probabilidade_historica_lote="nao_disponivel",
            politica_selecao="politica_atual_seleciona_carteira_sem_recalcular_creditos",
            descontos_reaplicados_ao_p50=False,
        )
    return {"uf": uf, "projeto": projeto, "metadados": metadados, "diagnosticos": []}


def cadt_uf(
    pasta: str | Path,
    uf: str,
    *,
    data_inicio: dt.date | str | None,
    url_catalogo: str,
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
    _catalogo_privado(url_catalogo)
    pasta, uf = Path(pasta), uf.upper()
    base = {
        "uf": uf,
        "projeto": None,
        "metadados": {"escopo": "privado", "versao_exportador": VERSAO, "aviso": AVISO},
        "diagnosticos": [],
    }

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
        if versao_fonte is not None and versao_fonte != r["versao_completa"]:
            raise CronogramaInvalido("versao_da_fonte_incompativel")
        if versao_fonte == HISTORICA_2026B:
            from raiz.regras.historico import carregar

            try:
                registro = carregar(versao_fonte)
            except ValueError as ex:
                raise CronogramaInvalido("registro_historico_invalido") from ex
            if registro is None or r != registro[0]:
                raise CronogramaInvalido("registro_historico_invalido")
            proveniencia.update(registro[1])
            proveniencia.update(_conferir_tarefa_historica(pasta, proveniencia["versao_tarefa_referencia"]))
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
        if versao_fonte == HISTORICA_2026B:
            from raiz.regras.historico import cenario as cenario_historico

            if c != cenario_historico("central_r11", r):
                raise CronogramaInvalido("cenario_historico_nao_comprovado")
    except CronogramaInvalido as ex:
        return ausente(str(ex))
    dados = L.ler_uf(pasta.parent, uf)
    if dados["oferta"].empty:
        return ausente("sem_fazendas_com_estimativa")
    try:
        dados["oferta"] = _oferta_p50_publicado(pasta, dados["oferta"], versao=versao_fonte)
        resumo = _resumo_cronograma(dados, r, c, edital_versao=proveniencia.get("regra_source_edital_versao"))
    except CronogramaInvalido as ex:
        return ausente(str(ex))
    if not resumo.get("cronograma_lote"):
        base["metadados"].update(proveniencia)
        base["metadados"].update(
            cenario=c["cenario"],
            versoes={k: v for k, v in resumo.items() if k.startswith("versao_")},
            coluna_total_p50="credito_liquido_tco2_contrato",
            diagnostico_selecao=resumo.get("diagnostico_selecao", {}),
            previsoes_individuais_recalculadas=False,
        )
        if versao_fonte == HISTORICA_2026B:
            base["metadados"].update(
                metodo_cronograma=METODO_2026B,
                probabilidade_historica_lote="nao_disponivel",
                politica_selecao="politica_atual_seleciona_carteira_sem_recalcular_creditos",
                descontos_reaplicados_ao_p50=False,
            )
        return ausente("sem_lote_elegivel")
    try:
        resultado = projeto_do_resumo(
            resumo,
            uf,
            data_inicio=data_inicio,
            url_catalogo=url_catalogo,
            data_referencia=data_referencia,
            r=r,
            c=c,
            repo=repo,
        )
        resultado["metadados"].update(proveniencia)
        resultado["metadados"]["origem_creditos"] = "P50 dos arquivos publicados; previsões individuais preservadas"
        resultado["metadados"]["coluna_total_p50"] = "credito_liquido_tco2_contrato"
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
        "escopo": "privado",
        "versao_exportador": VERSAO,
        "referencia_vocabulario": REFERENCIA,
        "aviso": AVISO,
        "projetos": projetos,
        "estados": resumos,
    }
