"""Contabilidade e curvas da rodada 12, com observação histórica separada de previsão.

Um desconto sempre identifica seu denominador. O buffer de uma emissão antiga
não reduz o piso prospectivo da Raíz. Duas observações usadas para ajustar uma
curva regional não constituem uma validação independente dessa mesma curva.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np

REFERENCIAS = Path(__file__).parent / "regras/padroes/rodada12_referencias.json"
PISO_RESERVA = 0.20


def fontes() -> dict:
    return json.loads(REFERENCIAS.read_text())


def versao() -> str:
    h = hashlib.sha256(Path(__file__).read_bytes() + REFERENCIAS.read_bytes()).hexdigest()[:12]
    return f"evidencias-r12-2026a+{h}"


def _quantidade(v: float, nome: str, *, fracao: bool = False) -> float:
    if isinstance(v, bool) or not math.isfinite(float(v)) or v < 0 or (fracao and v > 1):
        raise ValueError(f"{nome}: quantidade fora do domínio")
    return float(v)


def descontos(
    bruto: float,
    linha_base: float,
    incerteza: float,
    vazamento_tco2e: float,
    reserva: float,
    *,
    historico: bool = False,
    fonte_historica: str | None = None,
) -> dict:
    """Ordem VM0047 do 5511: baseline, incerteza, vazamento absoluto e buffer.

    A entrada de vazamento é toneladas, não percentual. O relatório deixa isso
    explícito para impedir que um percentual regional de área vire crédito.
    """
    bruto = _quantidade(bruto, "bruto")
    linha_base = _quantidade(linha_base, "linha_base", fracao=True)
    incerteza = _quantidade(incerteza, "incerteza", fracao=True)
    reserva = _quantidade(reserva, "reserva", fracao=True)
    vazamento_tco2e = _quantidade(vazamento_tco2e, "vazamento_tco2e")
    if historico and not fonte_historica:
        raise ValueError("reprodução histórica requer fonte_historica")
    aplicada = reserva if historico else max(PISO_RESERVA, reserva)
    saldo, etapas = bruto, []
    for nome, fracao, base in (
        ("linha_base", linha_base, "ganho_bruto"),
        ("incerteza", incerteza, "adicional_apos_linha_base"),
        ("vazamento", None, "quantidade_absoluta_tco2e"),
        ("reserva", aplicada, "adicional_apos_incerteza_e_vazamento"),
    ):
        valor = vazamento_tco2e if fracao is None else saldo * fracao
        if valor > saldo:
            raise ValueError(f"{nome} excede o saldo adicional")
        etapas.append(
            {
                "desconto": nome,
                "base": base,
                "denominador_tco2e": saldo,
                "fracao": fracao,
                "desconto_tco2e": valor,
                "saldo_tco2e": saldo - valor,
            }
        )
        saldo -= valor
    return {
        "modelo_versao": versao(),
        "historico": historico,
        "fonte_historica": fonte_historica,
        "bruto_tco2e": bruto,
        "liquido_tco2e": saldo,
        "fracao_liquida": saldo / bruto if bruto else None,
        "etapas": etapas,
        "reserva_solicitada": reserva,
        "reserva_aplicada": aplicada,
    }


def cenario_contabil(nome: str, bruto: float, *, planejamento: bool = True) -> dict:
    """57% é premissa; 69,88% é referência histórica com denominadores conhecidos."""
    bruto = _quantidade(bruto, "bruto")
    if nome == "conservador_plantio_pasto":
        return {
            "cenario": nome,
            "modelo_versao": versao(),
            "bruto_tco2e": bruto,
            "liquido_tco2e": bruto * 0.57,
            "fracao_liquida": 0.57,
            "natureza": "premissa conservadora agregada; não somar novamente os descontos",
            "habilita_comercializacao": False,
        }
    if nome != "verificado_5511":
        raise ValueError(f"cenário contábil desconhecido: {nome}")
    f = fontes()["vcs5511"]
    return {
        "cenario": nome,
        "fracao_historica_referencia": f["fracao_liquida_arredondada"],
        "habilita_comercializacao": False,
        **descontos(
            bruto,
            f["linha_base_fracao"],
            f["incerteza_fracao"],
            f["vazamento_tco2e"],
            f["reserva_historica_fracao"],
            historico=not planejamento,
            fonte_historica=f["url"],
        ),
    }


def observacoes_mombak() -> list[dict]:
    f = fontes()["mombak"]
    out = []
    for sitio in f["sitios"]:
        inicio, fim = (dt.date.fromisoformat(sitio[k]) for k in ("periodo_inicio", "periodo_fim"))
        out.append(
            {
                **sitio,
                "idade_projeto_anos": (fim - inicio).days / 365.2425,
                "remocao_tco2e_ha": sitio["remocao_tco2e"] / sitio["area_ha"],
                "mitigacao_calculada_tco2e": sitio["gado_cabecas"] * f["mitigacao_tco2e_cabeca"],
                "fonte_sha256": f["sha256"],
                "modelo_versao": versao(),
            }
        )
    return out


def calibrar_inicio_plantio(anual: np.ndarray) -> tuple[np.ndarray, dict]:
    """Ajusta a janela 1–3 anos; preserva estoque no ano 7 e total de 40 anos.

    Ajuste regional linear pela origem, pesos iguais por sítio. O observado é
    biomassa lenhosa líquida pré-buffer; usar esse valor para o total de pools
    nesta janela é aproximação conservadora, não equivalência contábil. Sem
    microdados de coorte, não se ajusta taxa por espécie ou P10/P90 empírico.
    """
    anual = np.asarray(anual, dtype=float)
    if anual.ndim != 1 or len(anual) < 8 or not np.isfinite(anual).all() or (anual < 0).any() or anual[0] != 0:
        raise ValueError("curva requer anos 0..7, valores finitos não negativos e estoque inicial zero")
    obs = observacoes_mombak()
    x = np.array([o["idade_projeto_anos"] for o in obs])
    y = np.array([o["remocao_tco2e_ha"] for o in obs])
    beta = float(x @ y / (x @ x))
    acumulado = anual.cumsum()
    limite = min(beta * 3, acumulado[7])
    novo = acumulado.copy()
    novo[:4] = np.arange(4) * limite / 3
    novo[4:8] = np.linspace(limite, acumulado[7], 5)[1:]
    comparacoes = []
    for o in obs:
        antigo = float(np.interp(o["idade_projeto_anos"], np.arange(len(anual)), acumulado))
        ajustado = float(np.interp(o["idade_projeto_anos"], np.arange(len(anual)), novo))
        comparacoes.append(
            {
                **o,
                "previsto_anterior_tco2e_ha": antigo,
                "previsto_ajustado_tco2e_ha": ajustado,
                "diferenca_anterior_tco2e_ha": antigo - o["remocao_tco2e_ha"],
                "diferenca_ajustada_tco2e_ha": ajustado - o["remocao_tco2e_ha"],
            }
        )
    return np.diff(novo, prepend=0), {
        "modelo_versao": versao(),
        "rotulo": "estimativa regional, não medida na fazenda",
        "metodo": "plantio_total",
        "bioma": "Amazônia",
        "calibracao_sitios": 2,
        "validacao_independente": False,
        "taxa_ajustada_tco2e_ha_ano": beta,
        "p10_p90": "mantida incerteza do modelo; dois sítios não estimam quantis regionais",
        "anos_1_3": [
            {"ano": t, "anterior_acumulado": float(acumulado[t]), "ajustado_acumulado": float(novo[t])}
            for t in (1, 2, 3)
        ],
        "comparacoes": comparacoes,
        "limites": fontes()["mombak"]["limites"],
    }
