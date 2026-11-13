"""Comparações ARR por projeto, período e base contábil, sem calibração automática.

Emissões não são medições de crescimento. A normalização segue o documento
Design & Calculations do Berkeley VROD v2026-08 (CC BY 4.0): totais históricos
de vintage são deduplicados; Units só substitui um total ausente. Comparações
incompletas também ficam registradas, com motivo e versão, sem inventar zeros.

Uso: python -m raiz.restauracao_validacao_arr --help
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

ESQUEMA = "validacao-arr-v1"
FONTES_DESENVOLVIMENTO = frozenset({"VCS665", "VCS5709"})
ALVOS = {"remocao_adicional_pre_buffer", "credito_emitivel_pos_buffer"}
REFERENCIAS = Path(__file__).parent / "regras" / "padroes" / "arr_referencias_2026.json"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def versao_comparador() -> str:
    return f"{ESQUEMA}+{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]}"


def _json(valor: object) -> str:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(valor: object) -> str:
    """Identidade de entradas estruturadas, independente da ordem das chaves."""
    return hashlib.sha256(_json(valor).encode()).hexdigest()


def _numero(valor: object, campo: str, *, negativo: bool = False) -> float:
    if isinstance(valor, bool):
        raise ValueError(f"{campo}: booleano não é quantidade")
    try:
        n = float(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{campo}: quantidade ausente ou inválida") from erro
    if not math.isfinite(n) or (n < 0 and not negativo):
        raise ValueError(f"{campo}: quantidade fora do domínio")
    return n


def _data(valor: object, campo: str) -> str:
    if isinstance(valor, dt.datetime):
        return valor.date().isoformat()
    if isinstance(valor, dt.date):
        return valor.isoformat()
    try:
        return dt.datetime.fromisoformat(str(valor)).date().isoformat()
    except ValueError as erro:
        raise ValueError(f"{campo}: data ISO inválida") from erro


def _projeto(valor: object) -> str:
    texto = str(valor)
    if texto.startswith("VCS"):
        texto = texto[3:]
    if not texto.isdigit() or int(texto) <= 0:
        raise ValueError("Project ID: esperado identificador VCS numérico")
    return f"VCS{int(texto)}"


def normalizar_emissoes(linhas: list[dict]) -> list[dict]:
    """Normaliza a aba Verra VCS Issuances; nunca mistura Units com totais.

    Colunas novas são aceitas. Para vintages novos, o serial identifica uma
    fração emitida: reimportar a mesma fração não aumenta o total. Totais e
    Units simultâneos sem total no mesmo período exigem reconciliação humana.
    """
    grupos: dict[tuple, list] = defaultdict(list)
    seriais: dict[str, tuple] = {}
    for linha in linhas:
        projeto = _projeto(linha.get("Project ID"))
        inicio = _data(linha.get("Vintage Start +"), "Vintage Start +")
        fim = _data(linha.get("Vintage End +"), "Vintage End +")
        if inicio > fim:
            raise ValueError("vintage termina antes de começar")
        emissao = _data(linha.get("Issuance Date"), "Issuance Date")
        total_bruto = linha.get("Total Vintage Quantity +")
        total = None if total_bruto is None else _numero(total_bruto, "Total Vintage Quantity +")
        unidades = _numero(linha.get("Units"), "Units")
        serial = linha.get("Serial Number")
        if not serial and total is None:
            raise ValueError("vintage sem total requer serial para deduplicar Units")
        identidade = (projeto, inicio, fim, emissao, total, unidades)
        if serial:
            if serial in seriais:
                if seriais[serial] != identidade:
                    raise ValueError(f"serial com valores conflitantes: {serial}")
                continue
            seriais[serial] = identidade
        grupos[(projeto, inicio, fim)].append((total, unidades, emissao))
    resultado = []
    for (projeto, inicio, fim), eventos in sorted(grupos.items()):
        totais = sorted({x[0] for x in eventos if x[0] is not None})
        if totais and any(x[0] is None for x in eventos):
            raise ValueError(f"{projeto}/{inicio}: totais e Units sem total misturados; reconciliar")
        soma_units = sum(x[1] for x in eventos)
        resultado.append(
            {
                "projeto_id": projeto,
                "periodo_inicio": inicio,
                "periodo_fim": fim,
                "emitido_tco2e": sum(totais) if totais else soma_units,
                "regra_agregacao": "totais_vintage_distintos" if totais else "units_por_serial",
                "totais_vintage_distintos": totais,
                "soma_units": soma_units,
                "primeira_emissao": min(x[2] for x in eventos),
                "ultima_emissao": max(x[2] for x in eventos),
                "eventos_distintos": len(eventos),
            }
        )
    return resultado


def reconciliar_creditos(
    bruto: float,
    linha_base: float,
    vazamento: float,
    emissoes_projeto: float,
    buffer: float,
    emitido: float | None,
) -> dict:
    """Mantém remoção bruta, adicional, emitível e emissão efetiva separados.

    Buffer deve pertencer à mesma janela, não ser o acumulado do cadastro.
    A reserva histórica não é substituída pela política atual do motor.
    Diferença entre emitível e emitido pode ser emissão parcial: não é erro
    de crescimento. Remoção adicional negativa permanece negativa.
    """
    valores = [
        _numero(v, n)
        for v, n in zip(
            (bruto, linha_base, vazamento, emissoes_projeto, buffer),
            ("bruto", "linha_base", "vazamento", "emissoes_projeto", "buffer"),
            strict=True,
        )
    ]
    bruto, linha_base, vazamento, emissoes_projeto, buffer = valores
    adicional = bruto - linha_base - vazamento - emissoes_projeto
    if buffer > max(adicional, 0):
        raise ValueError("buffer excede remoção adicional do período; conferir a base contábil")
    emitivel = adicional - buffer
    emitido = None if emitido is None else _numero(emitido, "emitido")
    return {
        "bruto_tco2e": bruto,
        "linha_base_tco2e": linha_base,
        "vazamento_tco2e": vazamento,
        "emissoes_projeto_tco2e": emissoes_projeto,
        "adicional_pre_buffer_tco2e": adicional,
        "buffer_periodo_tco2e": buffer,
        "emitivel_pos_buffer_tco2e": emitivel,
        "emitido_tco2e": emitido,
        "diferenca_emitivel_emitido_tco2e": None if emitido is None else emitivel - emitido,
        "diferenca_nao_mede_erro_crescimento": True,
    }


def comparar(previsao: dict, observado: dict) -> dict:
    """Compara apenas mesma área/coortes, janela, método, pools e deduções.

    Previsão obrigatoriamente tem versão e hash de entradas. Ausências nos
    metadados físicos geram incomparabilidade auditável, não descarte. Mesmo
    comparações compatíveis não autorizam calibração sem validação independente.
    """
    if not previsao.get("modelo_versao") or not _SHA.fullmatch(str(previsao.get("entradas_sha256", ""))):
        raise ValueError("previsão requer modelo_versao e entradas_sha256 válido")
    if not observado.get("fonte_versao") or not _SHA.fullmatch(str(observado.get("fonte_sha256", ""))):
        raise ValueError("observação requer fonte_versao e fonte_sha256 válido")
    previsao, observado = dict(previsao), dict(observado)
    for registro in (previsao, observado):
        if registro.get("projeto_id") is not None:
            registro["projeto_id"] = _projeto(registro["projeto_id"])
    motivos = []
    campos = (
        "projeto_id",
        "instancia_id",
        "periodo_inicio",
        "periodo_fim",
        "bioma",
        "metodo",
        "coortes_sha256",
        "alvo",
        "pools",
        "base_contabil",
    )
    for campo in campos:
        p, o = previsao.get(campo), observado.get(campo)
        if p in (None, "", []) or o in (None, "", []):
            motivos.append(f"{campo}_ausente")
            continue
        if campo == "pools":
            if any(not isinstance(v, list) or not all(isinstance(x, str) and x for x in v) for v in (p, o)):
                raise ValueError("pools deve ser uma lista de identificadores textuais")
            p, o = sorted(p), sorted(o)
        if campo == "coortes_sha256" and not all(_SHA.fullmatch(str(v)) for v in (p, o)):
            raise ValueError("coortes_sha256 inválido")
        if p != o:
            motivos.append(f"{campo}_divergente")
    for campo in ("periodo_inicio", "periodo_fim"):
        for registro in (previsao, observado):
            if registro.get(campo):
                _data(registro[campo], campo)
    for registro in (previsao, observado):
        if registro.get("periodo_inicio") and registro.get("periodo_fim"):
            if _data(registro["periodo_inicio"], "inicio") > _data(registro["periodo_fim"], "fim"):
                motivos.append("periodo_invertido")
    areas = [r.get("area_ha") for r in (previsao, observado)]
    if None in areas:
        motivos.append("area_ha_ausente")
    else:
        p, o = (_numero(a, "area_ha") for a in areas)
        if p <= 0 or o <= 0 or not math.isclose(p, o, rel_tol=0, abs_tol=1e-6):
            motivos.append("area_ha_divergente_ou_invalida")
    alvo = previsao.get("alvo")
    if alvo not in ALVOS:
        motivos.append("alvo_nao_suportado")
    if observado.get("natureza") != "monitorado":
        motivos.append("observacao_nao_e_monitoramento_harmonizado")
    if alvo == "credito_emitivel_pos_buffer":
        reservas = [r.get("reserva_fracao") for r in (previsao, observado)]
        if None in reservas or reservas[0] != reservas[1]:
            motivos.append("reserva_historica_divergente_ou_ausente")
        elif not 0 <= _numero(reservas[0], "reserva_fracao") <= 1:
            raise ValueError("reserva_fracao fora de 0..1")
    if observado.get("valor_tco2e") is None:
        motivos.append("observado_ausente_nao_e_zero")
        real = None
    else:
        real = _numero(observado["valor_tco2e"], "valor_tco2e", negativo=True)
    quantis = [previsao.get(q) for q in ("p10", "p50", "p90")]
    if None in quantis:
        motivos.append("previsao_incompleta")
    else:
        quantis = [_numero(q, "quantil", negativo=True) for q in quantis]
        if quantis != sorted(quantis):
            raise ValueError("esperado p10 <= p50 <= p90")
    desenvolvimento = FONTES_DESENVOLVIMENTO | {_projeto(v) for v in previsao.get("fontes_desenvolvimento") or []}
    independente = observado.get("projeto_id") not in desenvolvimento
    independente = independente and observado.get("conjunto") == "validacao_independente"
    metricas = None
    if not motivos:
        p10, p50, p90 = quantis
        metricas = {
            "erro_tco2e": p50 - real,
            "erro_absoluto_tco2e": abs(p50 - real),
            "razao_observado_previsto": None if p50 == 0 else real / p50,
            "cobertura_p10_p90": p10 <= real <= p90,
        }
    registro = {
        "esquema": ESQUEMA,
        "comparador_versao": versao_comparador(),
        "modelo_versao": previsao["modelo_versao"],
        "entradas_sha256": previsao["entradas_sha256"],
        "status": "incomparavel" if motivos else "comparavel",
        "motivos": sorted(set(motivos)),
        "validacao_independente": independente,
        "calibracao_autorizada": False,
        "motivo_calibracao": "exige avaliação separada de múltiplos projetos e ganho fora da amostra",
        "previsao": previsao,
        "observado": observado,
        "metricas": metricas,
    }
    # Congela cópia: mutar o dicionário de entrada não altera o registro retornado.
    registro = json.loads(_json(registro))
    return {"comparacao_id": sha256(registro), **registro}


def diagnosticar_janela_inicial(observado: dict) -> dict:
    """Testa o arranque da curva atual sem chamar isso de calibração.

    Usa o período completo monitorado, nunca vintages obtidos por rateio. O
    início deve ser o início da intervenção e não o ano da emissão. Este teste
    detecta uma limitação de escopo: curva que parte do zero não representa
    necessariamente uma área com regenerantes/estoque inicial ou outros pools.
    """
    from raiz import restauracao as rs

    if not _SHA.fullmatch(str(observado.get("fonte_sha256", ""))):
        raise ValueError("diagnóstico requer fonte_sha256 válido")
    inicio = dt.date.fromisoformat(_data(observado.get("intervencao_inicio"), "intervencao_inicio"))
    fim = dt.date.fromisoformat(_data(observado.get("periodo_fim"), "periodo_fim"))
    idade = (fim - inicio).days / 365.2425
    forma = rs.forma_curva()
    if idade <= 0 or idade > len(forma) - 1:
        raise ValueError("janela fora do horizonte da curva")
    # Cada índice anual é o fluxo daquele ano. Interpolar o acumulado é
    # equivalente a ratear somente a fração do último ano da curva do motor.
    inteiro = int(idade)
    fracao = float(sum(forma[: inteiro + 1]))
    if idade > inteiro:
        fracao += (idade - inteiro) * float(forma[inteiro + 1])
    real = _numero(observado.get("valor_tco2e"), "valor_tco2e", negativo=True)
    registro = {
        "esquema": ESQUEMA,
        "tipo": "diagnostico_temporal_sem_pareamento_de_coortes_e_pools",
        "modelo_versao": rs.versao(),
        "entradas_sha256": sha256(observado),
        "observado": observado,
        "idade_intervencao_anos": idade,
        "fracao_total_curva_na_janela": fracao,
        "curva_zero_na_janela": fracao == 0,
        "observado_positivo": real > 0,
        "incompatibilidade_temporal_de_escopo": fracao == 0 and real > 0,
        "previsao_pareada": None,
        "calibracao_autorizada": False,
        "motivos": [
            "coortes_estoque_inicial_e_pools_nao_harmonizados",
            "diagnostico_nao_estima_fator_de_produtividade",
            "vintages_rateados_nao_sao_medicoes_anuais_independentes",
        ],
    }
    registro = json.loads(_json(registro))
    return {"comparacao_id": sha256(registro), **registro}


def gravar_comparacao(registro: dict, pasta: Path | str) -> tuple[Path, bool]:
    """Um JSON por conteúdo, criação exclusiva; nunca sobrescreve histórico."""
    conteudo = {k: v for k, v in registro.items() if k != "comparacao_id"}
    identidade = sha256(conteudo)
    if registro.get("comparacao_id") != identidade:
        raise ValueError("identidade da comparação inválida; conteúdo foi alterado")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{identidade}.json"
    texto = _json(registro) + "\n"
    try:
        with caminho.open("x", encoding="utf-8") as arquivo:
            arquivo.write(texto)
    except FileExistsError:
        if caminho.read_text(encoding="utf-8") != texto:
            raise ValueError("registro existente diverge do hash; histórico não será sobrescrito") from None
        return caminho, False
    return caminho, True


def avaliar_referencias(referencias: dict, pasta: Path | str) -> list[dict]:
    """Persiste a confrontação com os MR públicos sem fabricar uma previsão.

    Enquanto faltarem coortes/pools, registra previsão pareada pendente com a
    versão atual. A remoção monitorada é líquida de baseline, antes do buffer;
    não são usadas as médias anuais do cadastro ou os percentuais do PDF.
    """
    from raiz import restauracao as rs

    resultados = []
    for caso in referencias["monitoramentos"]:
        observado = {
            k: caso.get(k)
            for k in (
                "projeto_id",
                "instancia_id",
                "periodo_inicio",
                "periodo_fim",
                "bioma",
                "metodo",
                "area_ha",
                "pools",
                "fonte_versao",
                "fonte_sha256",
                "conjunto",
            )
        }
        observado.update(
            natureza="monitorado",
            alvo="remocao_adicional_pre_buffer",
            base_contabil="delta_estoque_menos_baseline_vazamento_emissoes",
            valor_tco2e=caso["adicional_pre_buffer_tco2e"],
            pendencias=caso["pendencias"],
        )
        previsao = {
            "tipo": "previsao_pareada_pendente",
            "modelo_versao": rs.versao(),
            "entradas_sha256": sha256(caso),
            "projeto_id": caso["projeto_id"],
            "instancia_id": caso["instancia_id"],
            "alvo": "remocao_adicional_pre_buffer",
            "fontes_desenvolvimento": referencias["fontes_desenvolvimento"],
        }
        registro = comparar(previsao, observado)
        caminho, novo = gravar_comparacao(registro, pasta)
        resultados.append({"arquivo": str(caminho), "novo": novo, "registro": registro})
        if caso.get("implantacao_mais_antiga_mes"):
            # Dia 1 é um limite conservador, não uma data de plantio medida.
            diagnostico = diagnosticar_janela_inicial(
                {
                    **observado,
                    "intervencao_inicio": caso["implantacao_mais_antiga_mes"] + "-01",
                    "inicio_tipo": "limite_inferior_do_mes_documentado; dia_nao_informado",
                }
            )
            caminho, novo = gravar_comparacao(diagnostico, pasta)
            resultados.append({"arquivo": str(caminho), "novo": novo, "registro": diagnostico})
    anteriores = {r["id"]: r for r in referencias["emissoes_berkeley"]}
    for atual in referencias["verra_atual"]:
        anterior = anteriores[atual["projeto_id"]]
        registro = {
            "esquema": ESQUEMA,
            "tipo": "reconciliacao_de_cortes_do_registro_nao_erro_de_previsao",
            "modelo_versao": rs.versao(),
            "entradas_sha256": sha256([referencias["berkeley"], anterior, atual]),
            "projeto_id": atual["projeto_id"],
            "corte_anterior": {
                "fonte": referencias["berkeley"],
                "emitido_tco2e": anterior["creditos_emitidos"],
                "buffer_tco2e": anterior["buffer_depositado"],
            },
            "corte_atual": atual,
            "diferenca_emitido_entre_cortes": atual["emitido_tco2e"] - anterior["creditos_emitidos"],
            "previsao_pareada": None,
            "calibracao_autorizada": False,
            "motivos": [
                "diferenca_entre_snapshots_nao_e_erro_de_crescimento",
                "aposentadoria_nao_e_emissao_nem_remocao_nova",
                "data_e_causa_da_mudanca_nao_inferidas",
            ],
        }
        registro = json.loads(_json(registro))
        registro = {"comparacao_id": sha256(registro), **registro}
        caminho, novo = gravar_comparacao(registro, pasta)
        resultados.append({"arquivo": str(caminho), "novo": novo, "registro": registro})
    return resultados


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    comandos = p.add_subparsers(dest="comando", required=True)
    n = comandos.add_parser("normalizar-verra", help="normalizar linhas JSON da aba Verra VCS Issuances")
    n.add_argument("entrada", type=Path)
    n.add_argument("saida", type=Path)
    c = comandos.add_parser("comparar", help="guardar comparação ou motivos de incomparabilidade")
    c.add_argument("previsao", type=Path)
    c.add_argument("observacao", type=Path)
    c.add_argument("registro", type=Path)
    r = comandos.add_parser("referencias", help="confrontar os MR públicos curados e registrar pendências")
    r.add_argument("registro", type=Path)
    r.add_argument("--arquivo", type=Path, default=REFERENCIAS)
    a = p.parse_args()
    if a.comando == "normalizar-verra":
        resultado = normalizar_emissoes(json.loads(a.entrada.read_text(encoding="utf-8")))
        with a.saida.open("x", encoding="utf-8") as arquivo:
            arquivo.write(_json(resultado) + "\n")
        print(f"{len(resultado)} períodos gravados em {a.saida}")
    elif a.comando == "comparar":
        resultado = comparar(
            json.loads(a.previsao.read_text(encoding="utf-8")),
            json.loads(a.observacao.read_text(encoding="utf-8")),
        )
        caminho, novo = gravar_comparacao(resultado, a.registro)
        print(_json({"arquivo": str(caminho), "novo": novo, "status": resultado["status"]}))
    else:
        resultados = avaliar_referencias(json.loads(a.arquivo.read_text(encoding="utf-8")), a.registro)
        print(_json([{k: v for k, v in r.items() if k != "registro"} for r in resultados]))


if __name__ == "__main__":
    main()
