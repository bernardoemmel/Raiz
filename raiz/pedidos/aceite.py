"""Chance de o dono aceitar, por perfil de fazenda (faixa de tamanho, caminho da terra, estado e forma de pagamento).

A priori sai das premissas (pedidos.yaml); cada contato registrado (aceite ou recusa, com o perfil) puxa a chance do
perfil para o que aconteceu (beta-binomial: a priori vale `peso_a_priori` contatos imaginários). O nível de interesse
já registrado manda mais que o perfil: quem já tem aceite quase certamente fecha; quem recusou sai."""

from __future__ import annotations

import numpy as np
import pandas as pd

from raiz.pedidos.premissas import premissas

POR_NIVEL = {  # chance de chegar ao contrato a partir do nível de agora
    "interessado": 0.65,
    "aceite_fase1": 0.9,
    "contrato_firme": 1.0,
    "recusou": 0.0,
}
SUCESSO = ("aceite_fase1", "contrato_firme")
FRACASSO = ("recusou", "sem_resposta")


def faixa(ha: float, p: dict | None = None) -> int:
    p = p or premissas()
    return int(np.searchsorted(p["aceite"]["faixas_ha"], ha, side="right"))


def perfil(linha: dict, pagamento: str, p: dict | None = None) -> str:
    """Chave do perfil: faixa de tamanho, caminho da terra, estado e forma de pagamento."""
    p = p or premissas()
    return f"{faixa(float(linha.get('ha') or 0), p)}|{linha.get('caminho') or '-'}|{linha.get('uf') or '-'}|{pagamento}"


def a_priori(linha: dict, pagamento: str, p: dict | None = None) -> float:
    p = p or premissas()
    a = p["aceite"]
    base = a["base"]
    base *= a["por_caminho"].get(linha.get("caminho_terra") or "", 1.0)
    base *= a["por_faixa"][faixa(float(linha.get("ha") or 0), p)]
    base *= a["por_pagamento"].get(pagamento, 1.0)
    return float(min(max(base, 0.01), 0.95))


def chances(oferta: pd.DataFrame, niveis: dict[str, str] | None = None, historico: dict[str, tuple[int, int]] | None
            = None, pagamento: str = "participacao") -> np.ndarray:  # fmt: skip
    """Chance de aceite de cada fazenda da oferta. historico: perfil -> (aceites, recusas ou sem resposta)."""
    p = premissas()
    niveis, historico = niveis or {}, historico or {}
    k = float(p["aceite"]["peso_a_priori"])
    out = np.empty(len(oferta))
    for i, li in enumerate(oferta.to_dict("records")):
        nivel = niveis.get(li["cod_imovel"], "sem_contato")
        if nivel in POR_NIVEL:
            out[i] = POR_NIVEL[nivel]
            continue
        prior = a_priori(li, pagamento, p)
        sim, nao = historico.get(perfil(li, pagamento, p), (0, 0))
        out[i] = (prior * k + sim) / (k + sim + nao)
        if nivel == "sem_resposta":
            out[i] *= 0.5
    return out


def historico_do_banco(con, pagamento: str = "participacao") -> dict[str, tuple[int, int]]:
    """Aceites e recusas por perfil, a partir dos eventos de interesse registrados e da oferta (o perfil de cada
    fazenda no momento do cálculo)."""
    from sqlalchemy import text

    p = premissas()
    rs = con.execute(
        text("""select distinct on (e.cod_imovel) e.cod_imovel, e.nivel, o.atributos
                from negocio.interesse_evento e join negocio.oferta o on o.cod_imovel = e.cod_imovel
                where e.nivel = any(:fim)
                order by e.cod_imovel, e.ocorrido_em desc, e.id desc"""),
        {"fim": [*SUCESSO, *FRACASSO]},
    )
    out: dict[str, list[int]] = {}
    for r in rs:
        k = perfil(dict(r.atributos or {}), pagamento, p)
        c = out.setdefault(k, [0, 0])
        c[0 if r.nivel in SUCESSO else 1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}
