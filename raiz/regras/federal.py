"""Regras federais do Código Florestal por imóvel (caminho novo, E2), lidas da tabela de parâmetros versionada.

Referência executável para a versão em Catala (E2 passo 2): mesmas entradas, mesmas saídas, e os imóveis de teste
(testes/dados/imoveis_teste/) conferem as duas contra o laudo que o motor deu.

Entradas por imóvel (colunas do motor): uf, bioma, ha, m_fiscal, nao_floresta_ha, floresta_rem_ha, desm_total_ha e,
se houver, app_escadinha_ha.
Saídas: pct_RL, pct_RL_alem, deficit_RL80_ha, deficit_RL50_ha, deficit_RL_ha, deficit_RL_alem_ha, alem_RL_ha,
app_recompor_ha, com a explicação de cada uma em português (explicar).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from raiz.regras import Parametros, parametros


def calcular(im: pd.DataFrame, p: Parametros | None = None, data=None) -> pd.DataFrame:
    p = p or parametros()
    out = pd.DataFrame(index=im.index)
    eleg = im.ha - im.nao_floresta_ha  # área que conta para a reserva de floresta
    out["pct_RL"] = [p.rl_percentual(u, b, data) for u, b in zip(im.uf, im.bioma, strict=True)]
    reduzido = p.valor("rl_percentual_reduzido", data, amazonia_legal=True, vegetacao="floresta")
    floresta_80 = p.valor("rl_percentual", data, amazonia_legal=True, vegetacao="floresta")
    out["pct_RL_alem"] = np.where(out.pct_RL == floresta_80, reduzido, out.pct_RL)
    for pct in (80, 50):
        out[f"deficit_RL{pct}_ha"] = (pct / 100 * eleg - im.floresta_rem_ha).clip(lower=0)
    out["deficit_RL_ha"] = (out.pct_RL / 100 * eleg - im.floresta_rem_ha).clip(lower=0)
    out["deficit_RL_alem_ha"] = (out.pct_RL_alem / 100 * eleg - im.floresta_rem_ha).clip(lower=0)
    out["alem_RL_ha"] = (im.desm_total_ha - out.deficit_RL_alem_ha).clip(lower=0)
    limite_67 = p.valor("modulo_fiscal_limite_art67", data)
    pequeno = im.m_fiscal <= limite_67
    out.loc[pequeno, "alem_RL_ha"] = im.desm_total_ha[pequeno]  # art. 67: até 4 MF não deve reserva
    if "app_escadinha_ha" in im:
        teto = [p.teto_61b(mf, data) for mf in im.m_fiscal]
        teto_ha = np.array([np.inf if t is None else t for t in teto]) * im.ha.to_numpy()
        out["app_recompor_ha"] = np.minimum(im.app_escadinha_ha.to_numpy(), teto_ha)
    return out


def explicar(linha: pd.Series, p: Parametros | None = None, data=None) -> list[str]:
    """Passo a passo em português simples para o laudo e para o agente (E2 passo 6 usa isto)."""
    p = p or parametros()
    r = calcular(
        linha.to_frame().T.astype(
            {c: float for c in ("ha", "m_fiscal", "nao_floresta_ha", "floresta_rem_ha", "desm_total_ha")}
        ),
        p,
        data,
    ).iloc[0]
    eleg = linha.ha - linha.nao_floresta_ha
    passos = [
        f"O imóvel tem {linha.ha:.1f} ha; {eleg:.1f} ha contam para a reserva de floresta.",
        f"Em {linha.uf}, no bioma {linha.bioma}, a reserva legal é {r.pct_RL:.0f}% (Código Florestal, art. 12).",
        f"Sobrou {linha.floresta_rem_ha:.1f} ha de floresta; faltam {r.deficit_RL_ha:.1f} ha para a reserva.",
    ]
    if linha.m_fiscal <= p.valor("modulo_fiscal_limite_art67", data):
        passos.append(
            f"Com {linha.m_fiscal:.2f} módulos fiscais (até 4), a reserva é a vegetação de 22/07/2008 "
            f"(art. 67): toda a área aberta, {r.alem_RL_ha:.1f} ha, fica livre para restaurar."
        )
    else:
        passos.append(
            f"Contando a reserva de {r.pct_RL_alem:.0f}% para recomposição, {r.alem_RL_ha:.1f} ha abertos "
            "ficam além da reserva."
        )
    return passos
