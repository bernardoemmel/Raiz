"""Faixas P10, P50 e P90 do carbono e da receita, por imóvel e por lote.

Por imóvel, nesta ordem: (1) o valor para quem restaura (desenvolvedor_<mun>.csv, raiz/restauracao.py): crédito
líquido por ano P10/P50/P90 da área para restaurar, do Monte Carlo da E3, e a receita no preço do contrato do cenário;
(2) as colunas da ficha do produto (carbono_tco2_ano_p10/_p50/_p90, receita_ano_p10/_p50/_p90,
receita_moeda, faixas_versao, faixas_regra). Sem a ficha, a mesma regra provisória do produto (faixas-2026a,
raiz/regras/padroes/faixas.yaml no back-end): P50 = carbono_tco2_ano do motor; P10 = 0,6 e P90 = 1,4 vezes o P50;
receita = carbono vezes R$ 40, 75 e 120 por tonelada. A regra escrita vai junto em todo documento.

Por lote, lado a lado (como pede a E3):
  soma      soma dos P10 e dos P90 de cada imóvel: vale se todos errarem para o mesmo lado (correlação 1);
  carteira  Monte Carlo: cada imóvel sorteado numa normal de dois lados ajustada aos seus P10, P50 e P90, com
            correlação ρ entre imóveis (padrão: a fração comum do lote, restauracao.yaml); a receita usa um preço
            comum a todos. A faixa da carteira é mais
            estreita que a soma, porque erros independentes se compensam.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Z90 = 1.2815515655446004  # P90 da normal padrão

REGRA_PROVISORIA = dict(
    versao="faixas-2026a",
    fator_p10=0.6,
    fator_p90=1.4,
    moeda="BRL",
    preco=(40.0, 75.0, 120.0),
    regra=(
        "Carbono por ano: P50 é a área de carbono vezes a taxa da região (motor); P10 é 0,6 e P90 é 1,4 vezes o P50, "
        "faixa provisória até a conta com incerteza da E3. Receita por ano: carbono vezes R$ 40 (P10), R$ 75 (P50) e "
        "R$ 120 (P90) por tonelada, antes de custos e da parte do desenvolvedor; só o crédito da restauração."
    ),
)


@dataclass
class Faixa:
    p10: float | None
    p50: float | None
    p90: float | None

    @property
    def vazia(self) -> bool:
        return self.p50 is None


@dataclass
class FaixasImovel:
    carbono: Faixa
    receita: Faixa
    moeda: str
    versao: str
    regra: str
    fonte: str  # valor_para_quem_restaura | ficha | motor | sem_dado


def _f(v) -> float | None:
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _do_valor_para_quem_restaura(linha: dict) -> FaixasImovel | None:
    """Faixa do Monte Carlo do valor para quem restaura (a mesma conta da ficha, do pedido e do lote)."""
    area, c50 = _f(linha.get("restauracao_area_ha")), _f(linha.get("credito_liquido_tco2_ano"))
    if not area or c50 is None:
        return None
    # fazenda que não pode gerar crédito hoje (embargo, terra indígena, UC de proteção integral, bloqueio do motor,
    # cadastro com problema) fica com a conta do motor, que diz por quê (as mesmas exclusões do pedido de lote)
    bloqueada = any((_f(linha.get(k)) or 0) > 0 for k in ("embargo_ha", "ti_ha", "uc_protecao_integral_ha"))
    if bloqueada or str(linha.get("filtro_territorial") or "").lower() == "bloqueio":
        return None
    if str(linha.get("problema")).strip().lower() in ("true", "1", "1.0", "sim"):
        return None
    from raiz import restauracao as R

    p10h, p90h = _f(linha.get("credito_liquido_tco2_ha_ano_p10")), _f(linha.get("credito_liquido_tco2_ha_ano_p90"))
    c = Faixa(p10h * area if p10h is not None else c50, c50, p90h * area if p90h is not None else c50)
    try:
        cen = R.cenario(linha.get("restauracao_cenario") or None)
    except KeyError:
        cen = R.cenario()
    preco = float(cen["preco_usd_t"]) * float(cen["cambio_brl_usd"])
    regra = (
        f"Crédito líquido por ano da área para restaurar ({fmt_br(area)} ha de pasto fora da reserva legal e da APP), "
        "depois da linha de base, do vazamento, da reserva de risco e da incerteza; P10 e P90 do Monte Carlo do custo "
        f"e da captura (cenário {cen['cenario']}). Receita por ano: esse crédito vezes o preço do contrato, US$ "
        f"{fmt_br(float(cen['preco_usd_t']))} a R$ {fmt_br(float(cen['cambio_brl_usd']), 2)} por dólar, antes de "
        "custos e da parte do desenvolvedor."
    )
    rec = Faixa(c.p10 * preco, c.p50 * preco, c.p90 * preco)
    versao = str(linha.get("restauracao_versao") or "restauracao")
    return FaixasImovel(c, rec, "BRL", versao, regra, "valor_para_quem_restaura")


def fmt_br(x: float, nd: int = 0) -> str:
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def do_imovel(linha: dict) -> FaixasImovel:
    vr = _do_valor_para_quem_restaura(linha)
    if vr is not None:
        return vr
    if _f(linha.get("carbono_tco2_ano_p50")) is not None:
        return FaixasImovel(
            Faixa(
                _f(linha.get("carbono_tco2_ano_p10")),
                _f(linha["carbono_tco2_ano_p50"]),
                _f(linha.get("carbono_tco2_ano_p90")),
            ),
            Faixa(_f(linha.get("receita_ano_p10")), _f(linha.get("receita_ano_p50")), _f(linha.get("receita_ano_p90"))),
            linha.get("receita_moeda") or "BRL",
            linha.get("faixas_versao") or "ficha",
            linha.get("faixas_regra") or "faixa da ficha do produto",
            "ficha",
        )
    r = REGRA_PROVISORIA
    p50 = _f(linha.get("carbono_tco2_ano"))
    if p50 is None:
        return FaixasImovel(
            Faixa(None, None, None), Faixa(None, None, None), r["moeda"], r["versao"], r["regra"], "sem_dado"
        )
    c = Faixa(p50 * r["fator_p10"], p50, p50 * r["fator_p90"])
    pr = r["preco"]
    return FaixasImovel(
        c, Faixa(c.p10 * pr[0], c.p50 * pr[1], c.p90 * pr[2]), r["moeda"], r["versao"], r["regra"], "motor"
    )


def soma(faixas: list[Faixa]) -> Faixa:
    fs = [f for f in faixas if not f.vazia]
    if not fs:
        return Faixa(None, None, None)
    return Faixa(sum(f.p10 or f.p50 for f in fs), sum(f.p50 for f in fs), sum(f.p90 or f.p50 for f in fs))


def _sorteios(faixas: list[Faixa], rho: float, n: int, rng: np.random.Generator) -> np.ndarray:
    """Matriz (n, imóveis) de sorteios correlacionados, normal de dois lados por imóvel, sem valor negativo."""
    p10 = np.array([f.p10 if f.p10 is not None else f.p50 for f in faixas])
    p50 = np.array([f.p50 for f in faixas])
    p90 = np.array([f.p90 if f.p90 is not None else f.p50 for f in faixas])
    s_baixo, s_alto = (p50 - p10) / Z90, (p90 - p50) / Z90
    comum = rng.standard_normal((n, 1))
    proprio = rng.standard_normal((n, len(faixas)))
    z = np.sqrt(rho) * comum + np.sqrt(1 - rho) * proprio
    x = np.where(z < 0, p50 + z * s_baixo, p50 + z * s_alto)
    return np.clip(x, 0, None)


def rho_padrao() -> float:
    """Parte da variância comum aos imóveis: a mesma do lote e do pedido (restauracao.yaml, carteira.fracao_comum)."""
    from raiz import restauracao as R

    return float(R.regra()["carteira"]["fracao_comum"])


def carteira(faixas: list[Faixa], rho: float | None = None, n: int = 20000, semente: int = 20261112) -> Faixa:
    rho = rho_padrao() if rho is None else rho
    fs = [f for f in faixas if not f.vazia]
    if not fs:
        return Faixa(None, None, None)
    tot = _sorteios(fs, rho, n, np.random.default_rng(semente)).sum(axis=1)
    return Faixa(*(float(np.percentile(tot, q)) for q in (10, 50, 90)))


def receita_carteira(
    carbonos: list[Faixa],
    preco: tuple[float, float, float],
    rho: float | None = None,
    n: int = 20000,
    semente: int = 20261112,
) -> Faixa:
    """Receita do lote = carbono total (carteira) vezes um preço comum a todos (normal de dois lados nos P10/50/90)."""
    rho = rho_padrao() if rho is None else rho
    fs = [f for f in carbonos if not f.vazia]
    if not fs:
        return Faixa(None, None, None)
    rng = np.random.default_rng(semente)
    tot = _sorteios(fs, rho, n, rng).sum(axis=1)
    p = _sorteios([Faixa(*preco)], 0.0, n, rng)[:, 0]
    rec = tot * p
    return Faixa(*(float(np.percentile(rec, q)) for q in (10, 50, 90)))


def metodo_carteira(rho: float, n: int = 20000) -> str:
    sorteios = f"{n:,}".replace(",", ".")
    correlacao = f"{rho:.1f}".replace(".", ",")
    return (
        f"soma = soma dos P10, P50 e P90 de cada imóvel (todos errando para o mesmo lado). Carteira = {sorteios} "
        f"sorteios (semente fixa) com correlação {correlacao} entre imóveis, cada um numa normal de dois lados "
        "ajustada aos seus P10, P50 e P90; a receita da carteira usa um preço comum a todos os imóveis."
    )
