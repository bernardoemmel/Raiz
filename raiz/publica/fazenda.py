"""A explicação de uma fazenda para o cliente e o agente de IA dele (ferramenta explicar_fazenda do MCP).

Sai da mesma linha da ficha (motor, caminho da terra, valor para quem restaura e rebanho, lidos pelo nome), mas só com
o que serve para decidir o lote e nunca com dado pessoal: nem nome, nem CPF ou CNPJ (nem mascarados), nem contato. O
polígono exato fica de fora (vale a regra do link público: depois do aceite do dono)."""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import Engine

NOMES_METODO = {"regeneracao_assistida": "regeneração assistida", "semeadura_direta": "semeadura direta",
                "plantio_total": "plantio total"}  # fmt: skip


def _n(li: dict, k: str) -> float | None:
    try:
        x = float(li.get(k))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)


def de_linha(li: dict) -> dict[str, Any]:
    """A explicação a partir da linha completa da fazenda (sem consulta ao banco; usada também nos testes)."""
    from raiz.pedidos.oferta import CAMINHO_FRONT

    area = _n(li, "restauracao_area_ha") or 0.0
    c = {q: _r((_n(li, f"credito_liquido_tco2_ha_contrato_{q}") or 0.0) * area, 0) for q in ("p10", "p50", "p90")}
    modo = li.get("modo_restauracao")
    caminho = CAMINHO_FRONT.get(str(li.get("caminho_terra") or ""), li.get("caminho_terra"))
    tir = {q: _n(li, f"tir_alavancada_pct_{q}") for q in ("p10", "p50", "p90")}
    eq = _n(li, "preco_equilibrio_usd_t")
    partes = []
    if area > 0 and isinstance(modo, str):
        partes.append(f"{NOMES_METODO.get(modo, modo).capitalize()} em {area:,.0f} ha de pasto fora da reserva legal "
                      "e da APP.".replace(",", "."))  # fmt: skip
    if c["p50"]:
        partes.append(f"Créditos líquidos até o ano 25: {c['p50']:,.0f} no meio da faixa (de {c['p10']:,.0f} a "
                      f"{c['p90']:,.0f}).".replace(",", "."))  # fmt: skip
    if eq is not None:
        partes.append(f"O crédito paga o retorno do capital a partir de US$ {eq:.0f} por tonelada.")
    rot = li.get("caminho_terra_rotulo")
    if isinstance(rot, str) and rot:
        partes.append(f"Terra: {rot}" + (f" (risco {li.get('risco_terra')})." if li.get("risco_terra") else "."))
    reb = _n(li, "rebanho_cab_p50")
    if reb:
        partes.append(f"Gado hoje: cerca de {reb:,.0f} cabeças (PPM espalhada pelo pasto).".replace(",", "."))
    return {
        "cod_imovel": str(li.get("cod_imovel")),
        "municipio": li.get("municipio") if isinstance(li.get("municipio"), str) else None,
        "cod_municipio_ibge": li.get("cod_municipio_ibge"),
        "uf": li.get("uf"), "bioma": li.get("bioma"),
        "hectares": _r(_n(li, "ha") or _n(li, "area")),
        "pequena": li.get("porte") == "pequeno" if isinstance(li.get("porte"), str) else None,
        "area_para_restaurar_ha": _r(area), "metodo": modo,
        "metodo_area_ha": {m: _r(_n(li, f"restauracao_{m}_ha")) for m in NOMES_METODO},
        "caminho_terra": caminho, "caminho_terra_motivo": li.get("caminho_terra_motivo"),
        "risco_terra": li.get("risco_terra"),
        "creditos_ate_ano_25": c,
        "custo_usd_credito": _r(_n(li, "custo_credito_usd"), 2), "preco_equilibrio_usd": _r(eq, 2),
        "tir_com_fundo_clima_pct": tir, "tir_projeto_pct_p50": _n(li, "tir_projeto_pct_p50"),
        "marcos_chance_pct": {k.split("_")[1]: _n(li, k) for k in li
                              if k.startswith("marco_") and k.endswith("_chance_pct")},  # fmt: skip
        "descontos_pct": {k: _n(li, f"{k}_pct") for k in ("desconto_linha_base", "vazamento", "reserva_risco",
                                                          "incerteza")},  # fmt: skip
        "vazamento_motivo": li.get("vazamento_motivo"),
        "rebanho_cabecas": {q: _n(li, f"rebanho_cab_{q}") for q in ("p10", "p50", "p90")},
        "metano_tco2e_ano_p50": _n(li, "metano_tco2e_ano_p50"),
        "embargo": (_n(li, "embargo_ha") or 0) > 0, "problema_no_cadastro": str(li.get("problema")).lower() == "true",
        "versao": li.get("restauracao_versao"),
        "explicacao": " ".join(partes) or "Sem o valor para quem restaura calculado nesta fazenda ainda.",
        "como_falar_com_o_dono": "Pela Raíz: peça o interesse dos donos no pedido de lote (nunca direto).",
    }  # fmt: skip


def explicar(engine: Engine, cod_imovel: str) -> dict | None:
    from raiz.front_api import imoveis_do_municipio
    from raiz.publica.privacidade import sem_dado_pessoal

    lista = imoveis_do_municipio(engine, cod_imovel=cod_imovel)
    if not lista:
        return None
    return sem_dado_pessoal(de_linha(lista[0]))
