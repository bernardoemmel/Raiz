"""Aprendizado do valor para quem restaura: cada estimativa entra congelada com a versão do modelo; quando um cliente
informa o custo e a captura reais, a Raíz compara e propõe a recalibração.

- congelar_restauracao: previsões de custo, captura, crédito líquido e modo por imóvel (modelo "restauracao", versão
  = restauracao_versao do arquivo), no mesmo registro das outras previsões (aprendizado.previsao, hash do lote);
- informar: grava o real do cliente como gabarito (aprendizado.gabarito);
- comparar: real contra previsto por modo (razão mediana, cobertura da faixa P10-P90, acerto do modo);
- recalibrar: fator novo por modo = fator usado x razão mediana encolhida pelo tamanho da amostra
  (1 + (razão - 1) x n / (n + k)); com gravar=True escreve raiz/regras/padroes/restauracao_calibracao.yaml, o que
  muda a versão do modelo e faz `raiz restauracao recalcular` refazer os municípios.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from pathlib import Path

import yaml
from sqlalchemy import Connection, text

from raiz.aprendizado.registro import Previsao, Versoes, registrar_gabarito, registrar_lote

ALVOS = {
    # alvo: (coluna base, horizonte em dias, grupo da calibração)
    "restauracao_custo_rs_ha": ("custo_restauracao_ha", 730, "custo"),
    "restauracao_captura_tco2_ha_ano": ("captura_tco2_ha_ano", 2555, "captura"),
    "restauracao_credito_liquido_tco2_ha_ano": ("credito_liquido_tco2_ha_ano", 2555, None),
}
ALVO_MODO = "restauracao_modo"
K_ENCOLHE = 5  # com 5 casos reais, metade do caminho até a razão observada


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def previsoes(atributos_por_imovel: dict[str, dict]) -> tuple[list[Previsao], str | None]:
    """Previsões de um município a partir das colunas de desenvolvedor_<mun>.csv (só imóveis com área)."""
    from raiz import restauracao as RS

    r = RS.regra()
    out, versao = [], None
    for cod, a in atributos_por_imovel.items():
        area = _f(a.get("restauracao_area_ha")) or 0.0
        modo = a.get("modo_restauracao")
        if area <= 0 or not isinstance(modo, str):
            continue
        versao = versao or a.get("restauracao_versao")
        fatores = {g: RS._cal(r, g, modo) for g in ("custo", "captura")}
        dist = {"modo": modo, "fatores_calibracao": fatores, "area_ha": round(area, 2)}
        for alvo, (base, horiz, _) in ALVOS.items():
            if base == "credito_liquido_tco2_ha_ano":
                p10, p50, p90 = (_f(a.get(f"{base}_p10")), _f(a.get(base)), _f(a.get(f"{base}_p90")))
            else:
                p10, p50, p90 = (_f(a.get(f"{base}_{q}")) for q in ("p10", "p50", "p90"))
            if p50 is not None:
                out.append(Previsao(cod, alvo, horiz, p10=p10, p50=p50, p90=p90, distribuicao=dist))
        out.append(Previsao(cod, ALVO_MODO, 730, valor_texto=modo, distribuicao=dist))
    return out, versao


def congelar_restauracao(con: Connection, rodada_id: int) -> tuple[str | None, bool, int]:
    """Congela as estimativas para quem restaura de uma rodada de município (complemento 'desenvolvedor')."""
    r = con.execute(text("select * from funil.rodada where id = :i"), {"i": rodada_id}).first()
    if r is None:
        raise ValueError(f"rodada {rodada_id} não existe")
    attrs = {
        c: a
        for c, a in con.execute(
            text("""select cod_imovel, atributos from funil.complemento_imovel
                    where rodada_id = :r and tipo = 'desenvolvedor'"""),
            {"r": rodada_id},
        )
    }
    ps, versao = previsoes(attrs)
    if not ps:
        return None, False, 0
    v = Versoes(
        modelo="restauracao",
        modelo_versao=versao or "desconhecida",
        entradas_versao=r.hash_entradas,
        data_corte=r.data_corte,
        regras_versao=r.regras_versao,
        tipo="ao_vivo",
        rodada_id=rodada_id,
    )
    lh, novo = registrar_lote(con, ps, v, f"valor para quem restaura, município {r.cod_municipio}, rodada {rodada_id}")
    return lh, novo, len(ps)


def informar(
    con: Connection,
    cod_imovel: str,
    observado_em: dt.date,
    fonte: str,
    custo_rs_ha: float | None = None,
    captura_tco2_ha_ano: float | None = None,
    credito_liquido_tco2_ha_ano: float | None = None,
    modo: str | None = None,
    referencia: str | None = None,
) -> list[int]:
    """Grava o real informado pelo cliente (desenvolvedor) como gabarito. Devolve os ids gravados."""
    from raiz import restauracao as RS

    if modo is not None and modo not in RS.regra()["modos"]:
        raise ValueError(f"modo desconhecido: {modo}")
    ids = []
    for alvo, v in (
        ("restauracao_custo_rs_ha", custo_rs_ha),
        ("restauracao_captura_tco2_ha_ano", captura_tco2_ha_ano),
        ("restauracao_credito_liquido_tco2_ha_ano", credito_liquido_tco2_ha_ano),
    ):
        if v is not None:
            if not math.isfinite(float(v)) or float(v) < 0:
                raise ValueError(f"valor inválido para {alvo}: {v}")
            ids.append(registrar_gabarito(con, cod_imovel, alvo, observado_em, fonte, valor_num=float(v),
                                          referencia=referencia))  # fmt: skip
    if modo is not None:
        ids.append(registrar_gabarito(con, cod_imovel, ALVO_MODO, observado_em, fonte, valor_texto=modo,
                                      referencia=referencia))  # fmt: skip
    if not ids:
        raise ValueError("nada informado: passe custo, captura, crédito ou modo")
    return ids


def comparar(con: Connection, versao: str | None = None, lotes: list[str] | None = None) -> list[dict]:
    """Real contra previsto, por alvo e modo previsto (vale o gabarito mais perto do horizonte de cada previsão).
    Com versao, só as previsões daquela versão do modelo; sem, todas (cada uma com o fator que usou)."""
    rows = con.execute(
        text("""select alvo, cod_imovel, modelo_versao, p10, p50, p90, real_num, valor_texto, real_texto,
                       (select p.distribuicao from aprendizado.previsao p where p.id = v.previsao_id) as dist
                from aprendizado.previsao_contra_gabarito v
                where modelo = 'restauracao' and gabarito_id is not null
                  and (cast(:v as text) is null or modelo_versao = :v)
                  and (cast(:l as text[]) is null or lote_hash = any(cast(:l as text[])))"""),
        {"v": versao, "l": lotes},
    ).all()
    grupos: dict[tuple[str, str], list] = {}
    for x in rows:
        modo = (x.dist or {}).get("modo") or "?"
        grupos.setdefault((x.alvo, modo), []).append(x)
    out = []
    for (alvo, modo), xs in sorted(grupos.items()):
        if alvo == ALVO_MODO:
            acertos = [x.valor_texto == x.real_texto for x in xs if x.real_texto]
            out.append({"alvo": alvo, "modo": modo, "n": len(acertos),
                        "acerto_modo": sum(acertos) / len(acertos) if acertos else None})  # fmt: skip
            continue
        razoes = [x.real_num / x.p50 for x in xs if x.real_num is not None and x.p50]
        dentro = [x.p10 <= x.real_num <= x.p90 for x in xs if None not in (x.p10, x.p90, x.real_num)]
        fat = [((x.dist or {}).get("fatores_calibracao") or {}).get(ALVOS[alvo][2] or "", 1.0) for x in xs]
        out.append({
            "alvo": alvo,
            "modo": modo,
            "n": len(razoes),
            "razao_mediana": statistics.median(razoes) if razoes else None,
            "cobertura_p10_p90": sum(dentro) / len(dentro) if dentro else None,
            "fator_usado": statistics.median(fat) if fat else 1.0,
            "versoes": sorted({x.modelo_versao for x in xs}),
        })  # fmt: skip
    return out


def recalibrar(
    con: Connection,
    gravar: bool = False,
    arquivo: Path | None = None,
    k: int = K_ENCOLHE,
    versao: str | None = None,
    lotes: list[str] | None = None,
) -> dict:
    """Fatores novos por modo para custo e captura. gravar=True escreve o YAML de calibração (muda a versão)."""
    from raiz import restauracao as RS

    arquivo = Path(arquivo or RS.ARQ_CALIBRACAO)
    atual = yaml.safe_load(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
    novo = {"atualizado_em": dt.date.today().isoformat(), "regra": (
        "fator = fator usado na previsão x (1 + (razão mediana real/previsto - 1) x n / (n + "
        f"{k})); aplicado ao P10, P50 e P90 do modo")}  # fmt: skip
    for g in ("custo", "captura"):
        novo[g] = dict((atual or {}).get(g) or {})
    mudou = []
    for c in comparar(con, versao, lotes):
        grupo = ALVOS.get(c["alvo"], (None, None, None))[2]
        if not grupo or not c["n"] or c["razao_mediana"] is None or c["modo"] == "?":
            continue
        encolhida = 1 + (c["razao_mediana"] - 1) * c["n"] / (c["n"] + k)
        fator = round(c["fator_usado"] * encolhida, 4)
        novo[grupo][c["modo"]] = {
            "fator": fator,
            "n": c["n"],
            "razao_mediana": round(c["razao_mediana"], 4),
            "cobertura_p10_p90": None if c["cobertura_p10_p90"] is None else round(c["cobertura_p10_p90"], 3),
            "aviso_faixa": "faixa P10-P90 estreita demais: alargar" if (c["cobertura_p10_p90"] or 1) < 0.8 else "",
        }
        mudou.append((grupo, c["modo"], fator))
    if gravar and mudou:
        cab = (
            "# Calibração do valor para quem restaura com o real dos clientes (raiz restauracao recalibrar).\n"
            "# Gerado; revise antes de subir. Mudar este arquivo muda a versão do modelo.\n"
        )
        arquivo.write_text(cab + yaml.safe_dump(novo, allow_unicode=True, sort_keys=False), encoding="utf-8")
        RS._ler.cache_clear()
    return {"fatores": novo, "mudou": mudou, "gravado": bool(gravar and mudou), "arquivo": str(arquivo)}
