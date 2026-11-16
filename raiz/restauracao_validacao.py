"""Confronto com a coleta real e registro imutável das previsões da restauração.

O teste de 12/11/2026 é uma comparação entre fontes de entrada, não um inventário
de captura realizada. Sua diferença de carbono não calibra a produtividade da
floresta. Nenhuma guarda exclui um imóvel por tamanho.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from raiz.privacidade import mascarar

DOCUMENTO = "docs/teste-real-2026-11-12.md"
REFERENCIA = {
    "cod_municipio": 1504950,
    "imoveis": 880,
    "carbono_tco2_ano": {"amostra_antiga": 222694.0, "real_corrigido": 209708.0, "fallback_inflado": 443546.0},
    "pasto_ha": {"amostra_antiga": 40325.0, "real_corrigido": 37736.0},
}
COLUNAS_COMPARAR = (
    "ha", "m_fiscal", "desm_total_ha", "desm_pos2008_ha", "desm_pos2020_ha", "floresta_rem_ha",
    "deficit_RL_ha", "alem_RL_ha", "embargo_ha", "sigef_ha", "matricula_ha", "f_matricula",
    "app_desmatada_ha", "app_escadinha_ha", "app_recompor_ha", "frente", "filtro_territorial",
    "problema", "compra_arrendamento", "carbono_tco2_ano", "carbono_ha", "pasto_ha", "secundaria_ha",
    "pasto_ate1km_ha", "tmf_classe", "tmf_floresta_pct", "tmf_regeneracao_pct", "causa_perda",
)  # fmt: skip
TEXTOS_PREVISAO = {"modo_restauracao", "metodo_escolhido", "restauracao_cenario", "restauracao_versao"}
NUMEROS_PREVISAO = re.compile(
    r"(?:restauracao_(?:area|regeneracao_assistida|semeadura_direta|plantio_total)_ha|"
    r"(?:custo|captura|credito|tir|vpl|pico_capital|preco|minimo_preco|reserva_risco|arvores|especies|densidade)_\w+)"
)
CAMPOS_PESSOAIS = re.compile(r"(?:cpf|cnpj|nome|telefone|email|contato|endereco)", re.IGNORECASE)


def _numero(valor) -> float | None:
    if isinstance(valor, bool):
        return None
    try:
        n = float(valor)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def _valor(valor):
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, str):
        return mascarar(valor)
    if isinstance(valor, (str, bool, int, float)):
        return valor
    return valor.item() if hasattr(valor, "item") else str(valor)


def _pasto(linha: dict) -> tuple[float | None, str | None]:
    n = _numero(linha.get("pasto_ha"))
    if n is not None:
        return n, "pasto_ha"
    campos = sorted(c for c in linha if re.fullmatch(r"mb_pasto_(?:19|20)\d{2}_ha", c))
    for campo in reversed(campos):
        n = _numero(linha[campo])
        if n is not None:
            return n, campo
    return None, None


def validar_area(linha: dict) -> dict:
    """Expõe entrada ausente e área inflada; ``None`` não vira área livre restaurável.

    ``area_segura_ha`` é um limite de triagem, não certificação espacial. A guarda
    preserva áreas pequenas e permite agrupá-las assim que a entrada for conhecida.
    """
    pasto, fonte = _pasto(linha)
    alem = _numero(linha.get("alem_RL_ha"))
    app = _numero(linha.get("app_recompor_ha"))
    if app is None:
        app = _numero(linha.get("app_desmatada_ha"))
    ha = _numero(linha.get("ha"))
    pendencias = []
    for nome, valor in (("pasto", pasto), ("área além da reserva legal", alem), ("APP a recompor", app)):
        if valor is None:
            pendencias.append(f"Falta {nome}; não inferir área restaurável a partir de área livre.")
        elif valor < 0:
            pendencias.append(f"{nome.capitalize()} negativa: conferir a entrada.")
    valido = all(x is not None and x >= 0 for x in (pasto, alem, app))
    limite = max(min(pasto, max(alem - app, 0)), 0) if valido else None
    if ha is not None and ha >= 0 and limite is not None:
        limite = min(limite, ha)
    area = _numero(linha.get("restauracao_area_ha"))
    if area is not None and area < 0:
        pendencias.append("Área restaurável negativa: refazer o cálculo.")
    if area is not None and limite is not None and area > limite + 1e-6:
        pendencias.append("Área restaurável excede pasto, área livre de RL/APP ou área do imóvel: refazer o cálculo.")
    return {
        "tem_dados": valido,
        "area_segura_ha": limite,
        "pasto_fonte": fonte,
        "pendencias": pendencias,
        "apto_para_previsao": valido and not pendencias,
        "criterio": (
            "Área positiva é mantida, sem tamanho mínimo; limite = mínimo(pasto, além RL − APP, área do imóvel)."
        ),
    }


def confrontar_referencia(df: pd.DataFrame, cod: int = 1504950) -> dict:
    """Compara totais lidos agora com valores arredondados do documento histórico."""
    if int(cod) != REFERENCIA["cod_municipio"]:
        return {"situacao": "sem_referencia", "cod_municipio": int(cod), "fonte": DOCUMENTO}
    totais, classificados, faltantes = {}, {}, []
    for campo in ("carbono_tco2_ano", "pasto_ha"):
        valores = pd.to_numeric(df[campo], errors="coerce") if campo in df else pd.Series(dtype=float)
        valores = valores.replace([float("inf"), -float("inf")], float("nan"))
        total = float(valores.sum()) if len(valores) and valores.notna().any() else None
        totais[campo] = total
        if campo not in df or len(valores) != len(df) or valores.isna().any():
            faltantes.append(campo)
        classificados[campo] = next(
            (k for k, v in REFERENCIA[campo].items() if total is not None and abs(total - v) <= 1), "outro"
        )
    return {
        "situacao": "comparado_com_documento",
        "cod_municipio": int(cod),
        "fonte": DOCUMENTO,
        "imoveis": len(df),
        "imoveis_referencia": REFERENCIA["imoveis"],
        "contagem_confere": len(df) == REFERENCIA["imoveis"],
        "totais_lidos": totais,
        "compatibilidade": classificados,
        "colunas_incompletas": faltantes,
        "referencia": REFERENCIA,
        "calibracao_captura_autorizada": False,
        "interpretacao": (
            "O documento compara exportação antiga com cobertura MapBiomas atualizada. A diferença de 5,8% "
            "do carbono não mede erro de crescimento nem captura realizada; não aplicar fator de calibração. "
            "Totais novos diferentes exigem conferir data, coleção e universo de imóveis."
        ),
    }


def _ler(pasta: Path, cod: int) -> tuple[pd.DataFrame, dict[str, str]]:
    dados, hashes = None, {}
    for tipo in ("imoveis", "filtros", "mapbiomas", "extras_direto"):
        arquivo = pasta / f"{tipo}_{cod}.csv"
        if not arquivo.exists():
            if tipo == "imoveis":
                raise FileNotFoundError(arquivo)
            continue
        hashes[arquivo.name] = hashlib.sha256(arquivo.read_bytes()).hexdigest()
        quadro = pd.read_csv(arquivo, dtype={"cod_imovel": str}, low_memory=False)
        if "cod_imovel" not in quadro or quadro.cod_imovel.isna().any() or quadro.cod_imovel.duplicated().any():
            raise ValueError(f"Chave CAR ausente ou duplicada em {arquivo.name}")
        campos = [c for c in quadro if c in {"cod_imovel", *COLUNAS_COMPARAR}]
        quadro = quadro[campos]
        if dados is None:
            dados = quadro
        else:
            novas = [c for c in quadro if c == "cod_imovel" or c not in dados]
            dados = dados.merge(quadro[novas], on="cod_imovel", how="left", validate="one_to_one")
    return dados, hashes


def comparar_pastas(amostra: str | Path, real: str | Path, cod: int = 1504950) -> dict:
    """Alinha pelo CAR; publica só atributos técnicos explicitamente permitidos."""
    a, ha = _ler(Path(amostra), cod)
    b, hb = _ler(Path(real), cod)
    ia, ib = a.set_index("cod_imovel"), b.set_index("cod_imovel")
    comuns = sorted(set(ia.index) & set(ib.index))
    diferencas, colunas = [], {}
    for campo in COLUNAS_COMPARAR:
        if campo not in ia or campo not in ib:
            if campo in ia or campo in ib:
                colunas[campo] = {"situacao": "ausente_amostra" if campo not in ia else "ausente_real"}
            continue
        n = 0
        for car in comuns:
            va, vb = _valor(ia.at[car, campo]), _valor(ib.at[car, campo])
            na, nb = _numero(va), _numero(vb)
            igual = math.isclose(na, nb, rel_tol=1e-9, abs_tol=1e-6) if na is not None and nb is not None else va == vb
            if not igual:
                diferencas.append({"cod_imovel": car, "coluna": campo, "amostra": va, "real": vb})
                n += 1
        colunas[campo] = {"situacao": "comparada", "diferentes": n, "comparados": len(comuns)}
    return {
        "cod_municipio": int(cod),
        "imoveis_amostra": len(a),
        "imoveis_real": len(b),
        "imoveis_comuns": len(comuns),
        "apenas_amostra": sorted(set(ia.index) - set(ib.index)),
        "apenas_real": sorted(set(ib.index) - set(ia.index)),
        "arquivos_sha256": {"amostra": ha, "real": hb},
        "colunas": colunas,
        "diferencas": diferencas,
        "referencia_amostra": confrontar_referencia(a, cod),
        "referencia_real": confrontar_referencia(b, cod),
    }


def registrar_previsoes(
    pasta: str | Path,
    linhas: Iterable[dict] | pd.DataFrame,
    modelo_versao: str,
    entradas_versao: str,
) -> dict:
    """Congela saídas por CAR; mesma identidade com resultado diferente é erro.

    A identidade é (modelo, entradas, cenário). Arquivos novos usam criação
    exclusiva e nunca sobrescrevem um registro. Nome, contato e campos desconhecidos
    são descartados por uma lista positiva de atributos.
    """
    if not all(isinstance(v, str) and v.strip() for v in (modelo_versao, entradas_versao)):
        raise ValueError("Versões do modelo e das entradas são obrigatórias.")
    registros = linhas.to_dict("records") if isinstance(linhas, pd.DataFrame) else list(linhas)
    saidas, cods = [], set()
    for linha in registros:
        car_bruto = linha.get("cod_imovel")
        car = "" if car_bruto is None or pd.isna(car_bruto) else str(car_bruto).strip()
        if not car or car in cods:
            raise ValueError("Cada previsão exige um CAR único e não vazio.")
        versao_linha = linha.get("restauracao_versao")
        if versao_linha is not None and not pd.isna(versao_linha) and str(versao_linha) != modelo_versao:
            raise ValueError("Versão da previsão diverge da versão do modelo informada.")
        cods.add(car)
        saida = {"cod_imovel": mascarar(car), "modelo_versao": modelo_versao, "entradas_versao": entradas_versao}
        for campo, valor in linha.items():
            if CAMPOS_PESSOAIS.search(campo):
                continue
            if campo in TEXTOS_PREVISAO:
                if valor is not None and not pd.isna(valor):
                    saida[campo] = mascarar(str(valor))
            elif NUMEROS_PREVISAO.fullmatch(campo):
                saida[campo] = _numero(valor)
        saidas.append(saida)
    saidas.sort(key=lambda x: x["cod_imovel"])
    cenarios = sorted({x.get("restauracao_cenario", "") for x in saidas})
    identidade = json.dumps([modelo_versao, entradas_versao, cenarios], ensure_ascii=False).encode()
    chave = hashlib.sha256(identidade).hexdigest()
    conteudo = "".join(json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for x in saidas)
    digest = hashlib.sha256(conteudo.encode()).hexdigest()
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / f"previsoes_{chave}.jsonl"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=pasta, delete=False) as temporario:
        temporario.write(conteudo)
        temporario.flush()
        os.fsync(temporario.fileno())
        temporario_nome = Path(temporario.name)
    try:
        try:
            os.link(temporario_nome, arquivo)  # criação exclusiva e conteúdo completo visível de uma vez
            novo = True
        except FileExistsError:
            if arquivo.read_text(encoding="utf-8") != conteudo:
                raise ValueError(
                    "Previsões diferentes para a mesma versão de modelo e entradas; registro preservado."
                ) from None
            novo = False
    finally:
        temporario_nome.unlink(missing_ok=True)
    return {"arquivo": str(arquivo), "sha256": digest, "identidade": chave, "novo": novo, "quantidade": len(saidas)}
