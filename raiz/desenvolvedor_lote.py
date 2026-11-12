"""Lote para a proposta do ProFloresta+ e checklist do edital, por estado (área de elegibilidade da Verra).

Lê os desenvolvedor_<mun>.csv da UF pelo nome das colunas e monta o lote pelo custo líquido por crédito (o método de
cada fazenda já é o que ganhou a disputa em raiz/restauracao.py):
 - titulares: as fazendas mais baratas por crédito até cumprir todos os marcos do Anexo IV no P50, com a tolerância;
 - reserva: as seguintes até cumprir os marcos com a chance alvo (P90 dos leilões de energia);
 - mitigação: as vizinhas que recebem o gado das titulares e reservas (VMD0054); entram no lote sem crédito;
 - em espera: as que só entram quando a terra ficar pronta (posse em titulação, assentamento), mostradas à parte.
Pequena nunca sai por tamanho. Sem nome, CPF ou CNPJ: só o código do CAR.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import numpy as np
import yaml

from raiz import desenvolvedor as D

ARQ_EDITAL = Path(__file__).parent / "regras" / "padroes" / "edital_profloresta.yaml"
COLUNAS_LOTE = (
    "papel", "cod_imovel", "cod_municipio_ibge", "restauracao_area_ha", "modo_restauracao",
    "restauracao_regeneracao_assistida_ha", "restauracao_plantio_total_ha", "credito_liquido_t",
    "credito_liquido_contrato_t", "custo_liquido_por_credito", "tir_desenvolvedor", "pico_caixa_ha", "icsd_minimo",
    "vazamento_pct", "vazamento_motivo", "vazamento_mitigacao_imovel", "caminho_terra", "caminho_terra_situacao",
    "risco_terra", "projeto_carbono_ha", "pagamento_dono", "restauracao_versao",
)  # fmt: skip


def edital(arq: Path | None = None) -> dict:
    return yaml.safe_load(Path(arq or ARQ_EDITAL).read_text(encoding="utf-8"))


def _verdade(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def ler_uf(saida: str | Path, uf: str):
    """Todos os desenvolvedor_<mun>.csv da UF numa tabela (sem colunas pessoais)."""
    import pandas as pd

    from raiz.privacidade import remover_colunas_pessoais

    pasta = Path(saida) / uf.upper()
    partes = []
    for f in sorted(pasta.glob("desenvolvedor_*.csv")):
        t = pd.read_csv(f, low_memory=False, dtype={"cod_imovel": str})
        if "cod_municipio_ibge" not in t:
            t["cod_municipio_ibge"] = int(f.stem.split("_")[-1])
        partes.append(t)
    if not partes:
        raise FileNotFoundError(f"nenhum desenvolvedor_<mun>.csv em {pasta} (rode `raiz restauracao recalcular`)")
    df, _ = remover_colunas_pessoais(pd.concat(partes, ignore_index=True))
    df["uf"] = uf.upper()
    return df


def _fator_alvo(chance: float, p: dict) -> float:
    """Fator de captura que o lote precisa aguentar para cumprir com a chance alvo (P10 para 90%)."""
    return float(np.percentile(D.fatores_captura(p), 100 * (1 - chance)))


def montar(df, volume: float | None = None, so_pronta: bool = True, p: dict | None = None,
           c: dict | None = None) -> dict:  # fmt: skip
    """Lote de uma UF pelo custo líquido por crédito, com reservas, mitigação e o cronograma do contrato."""
    import pandas as pd

    p = p or D.premissas()
    c = c or D.cenario(p=p)
    volume = float(volume or p["contrato"]["creditos"])
    chance = float(D._valor(p["lote"]["chance_alvo_reserva"]))
    t = df.copy()
    t["credito_liquido_t"] = _col(t, "credito_liquido_t").fillna(0.0)
    t["custo_liquido_por_credito"] = _col(t, "custo_liquido_por_credito", vazio=np.nan)
    elegivel = t["elegivel_lote"].map(_verdade) if "elegivel_lote" in t else t["grupo_id"].notna()
    pool = t[elegivel & (t.credito_liquido_t > 0) & t.custo_liquido_por_credito.notna()].copy()
    situ = pool["caminho_terra_situacao"] if "caminho_terra_situacao" in pool else pd.Series(None, index=pool.index)
    pronta = situ.isna() | (situ == "pronta_agora")
    espera = pool[~pronta] if so_pronta else pool.iloc[0:0]
    pool = pool[pronta] if so_pronta else pool
    tir = _col(pool, "tir_desenvolvedor", vazio=np.nan).fillna(-100)
    pool = pool.assign(_tir=tir).sort_values(["custo_liquido_por_credito", "_tir"], ascending=[True, False])
    precisa50 = D.creditos_40_necessarios(volume, p)
    precisa_alvo = D.creditos_40_necessarios(volume, p, fator=_fator_alvo(chance, p))
    acum = pool.credito_liquido_t.cumsum()
    antes = acum - pool.credito_liquido_t
    pool["papel"] = np.where(antes < precisa50, "titular", np.where(antes < precisa_alvo, "reserva", "fora"))
    lote = pool[pool.papel != "fora"].copy()
    # vizinhas que recebem o gado (VMD0054): entram como área de mitigação, sem crédito
    viz = set()
    if "vazamento_mitigacao_imovel" in lote:
        viz = {str(v) for v in lote.vazamento_mitigacao_imovel.dropna() if str(v) and str(v) != "nan"}
    viz -= set(lote.cod_imovel)
    mit = t[t.cod_imovel.isin(viz)].copy()
    mit["papel"] = "mitigacao"
    esp = espera.copy()
    esp["papel"] = "em_espera"
    tabela = pd.concat([lote, mit, esp], ignore_index=True)
    tabela = tabela[[c_ for c_ in COLUNAS_LOTE if c_ in tabela.columns]]
    tit = lote[lote.papel == "titular"]
    com_res = lote[lote.papel.isin(["titular", "reserva"])]
    preco_brl = c["preco_contrato_usd_t"] * c["cambio_brl_usd"]

    def soma(x, col):
        return float(_col(x, col).fillna(0).sum()) if len(x) else 0.0

    def media_pond(x, col, peso="credito_liquido_t"):
        v = _col(x, col, vazio=np.nan)
        w = _col(x, peso).fillna(0)
        ok = v.notna() & (w > 0)
        return float((v[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else None

    cred_tit = soma(tit, "credito_liquido_t")
    cred_res = soma(com_res, "credito_liquido_t")
    fk = D.fatores_captura(p)
    resumo = {
        "uf": str(t["uf"].iloc[0]) if "uf" in t and len(t) else None,
        "data": dt.date.today().isoformat(),
        "versao_premissas": p["versao_completa"],
        "cenario": c["cenario"],
        "volume_creditos": volume,
        "chance_alvo": chance,
        "creditos_40_precisa_p50": round(precisa50, 0),
        "creditos_40_precisa_com_reserva": round(precisa_alvo, 0),
        "titulares": int(len(tit)),
        "reservas": int((lote.papel == "reserva").sum()),
        "mitigacao": int(len(mit)),
        "em_espera": int(len(esp)),
        "em_espera_ha": round(soma(esp, "restauracao_area_ha"), 1),
        "ha_titulares": round(soma(tit, "restauracao_area_ha"), 1),
        "ha_com_reserva": round(soma(com_res, "restauracao_area_ha"), 1),
        "ha_regeneracao_titulares": round(soma(tit, "restauracao_regeneracao_assistida_ha"), 1),
        "ha_plantio_titulares": round(soma(tit, "restauracao_plantio_total_ha"), 1),
        "creditos_40_titulares": round(cred_tit, 0),
        "creditos_40_com_reserva": round(cred_res, 0),
        "creditos_contrato_titulares_p10_p50_p90": [
            round(cred_tit * D.fracao_ate(int(p["contrato"]["prazo_anos"]), p) * float(np.percentile(fk, q)), 0)
            for q in (10, 50, 90)
        ],
        "fecha_no_p50": cred_tit >= precisa50,
        "fecha_com_reserva": cred_res >= precisa_alvo,
        "custo_liquido_por_credito_medio": media_pond(tit, "custo_liquido_por_credito"),
        "custo_liquido_por_credito_usd_medio": (media_pond(tit, "custo_liquido_por_credito") or 0)
        / c["cambio_brl_usd"],
        "tir_desenvolvedor_media": media_pond(tit, "tir_desenvolvedor"),
        "preco_contrato_brl_t": preco_brl,
        "cronograma_titulares": D.cronograma(cred_tit, preco_brl, p, volume) if cred_tit > 0 else None,
        "cronograma_com_reserva": D.cronograma(cred_res, preco_brl, p, volume) if cred_res > 0 else None,
    }
    resumo["checklist"] = checklist(resumo, tabela, p, c)
    return {"resumo": resumo, "tabela": tabela}


# --- checklist do edital -----------------------------------------------------------------------------------------


def _item(st: str, texto: str) -> dict:
    return {"situacao": st, "detalhe": texto}


def _col(df, nome: str, vazio: float = 0.0):
    """Coluna numérica pelo nome (`vazio` quando não existe)."""
    import pandas as pd

    if nome not in df:
        return pd.Series(vazio, index=df.index, dtype=float)
    return pd.to_numeric(df[nome], errors="coerce")


def _br(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def checagens(resumo: dict, tabela, p: dict, c: dict) -> dict[str, dict]:
    """O que dá para conferir com os dados da Raíz. situação: ok, falha, pendente (falta dado ou ação de alguém)."""
    import pandas as pd

    tit = tabela[tabela.papel == "titular"] if len(tabela) else tabela
    out = {}
    ha = resumo["ha_titulares"]
    minimo = float(p["contrato"]["area_minima_ha"])
    texto = f"{_br(ha)} ha nas titulares; mínimo da fase 1: {_br(minimo)} ha"
    out["area_minima"] = _item("ok" if ha >= minimo else "falha", texto)
    pct = float(p["contrato"]["assinatura"]["area_homologada_min_pct"])
    risco = tit["risco_terra"] if "risco_terra" in tit else pd.Series(dtype=object)
    area_tit = _col(tit, "restauracao_area_ha")
    conferida = float(area_tit[risco == "baixo"].sum()) if len(tit) and "risco_terra" in tit else 0.0
    precisa = pct * ha
    if ha > 0 and conferida >= precisa:
        texto = f"{_br(conferida)} ha com título de risco baixo (precisa de {_br(precisa)} ha); falta o aceite assinado"
        out["area_inicial"] = _item("pendente", texto)
    else:
        texto = (f"{_br(conferida)} ha com título de risco baixo; a assinatura pede {pct:.0%} do lote "
                 f"({_br(precisa)} ha) homologados e com aceite")  # fmt: skip
        out["area_inicial"] = _item("falha" if risco.notna().any() else "pendente", texto)
    texto = f"cada dono das titulares assina a cessão irrevogável do carbono no aceite ({c['prazo_dono_anos']} anos)"
    out["cessao_carbono"] = _item("pendente", texto)
    n_proj = int((_col(tit, "projeto_carbono_ha").fillna(0) >= 1).sum())
    texto = "nenhuma titular sobre projeto de carbono registrado" if not n_proj else f"{n_proj} titulares sobre projeto"
    out["sem_sobreposicao"] = _item("ok" if not n_proj else "falha", texto)
    texto = f"contrato com o dono de {c['prazo_dono_anos']} anos (longevidade da Verra: 40)"
    out["contrato_40_anos"] = _item("ok" if c["prazo_dono_anos"] >= 40 else "falha", texto)
    texto = "só entram fazendas sem embargo, terra indígena, desmatamento depois de 2020 ou alerta (elegivel_lote)"
    out["sem_desmatamento"] = _item("ok", texto)
    out["metodologia"] = _item("ok", "VM0047 v1.1 da Verra, aprovada pelo ICVCM (CCP)")
    texto = "ordem: " + ", ".join(p["descontos"]["ordem"]) + f"; incerteza de {c['incerteza']:.0%}"
    out["creditos_liquidos"] = _item("ok" if c["incerteza"] >= 0.10 else "falha", texto)
    texto = f"linha de base de {c['linha_base']:.0%} (premissa do cenário); calcular os controles pareados"
    out["linha_base"] = _item("pendente", texto)
    texto = f"reserva de {c['reserva_risco']:.0%}; preencher a ferramenta de risco AFOLU por fazenda"
    out["reserva_risco"] = _item("pendente", texto)
    cron = resumo.get("cronograma_com_reserva")
    if cron:
        ok = cron["chance_cumprir_todos"] >= resumo["chance_alvo"]
        texto = (f"chance de cumprir todos os marcos com a reserva: {cron['chance_cumprir_todos']:.0%} (alvo "
                 f"{resumo['chance_alvo']:.0%}); rescisão: {cron['chance_rescisao']:.0%}")  # fmt: skip
        out["cronograma"] = _item("ok" if ok else "falha", texto)
    else:
        out["cronograma"] = _item("falha", "o estado não tem fazenda com crédito para montar o lote")
    vz = tit["vazamento_motivo"] if "vazamento_motivo" in tit and len(tit) else None
    if vz is not None:
        zerado = float(vz.isin(["mitigacao_vizinha", "sem_gado"]).mean())
        out["vazamento"] = _item(
            "ok", f"vazamento calculado por fazenda (VMD0054); zerado em {zerado:.0%} das titulares"
        )
        texto = (f"{resumo['mitigacao']} vizinhas como área de mitigação; falta acordo de 5 anos ou mais e laudo "
                 "independente de cada uma")  # fmt: skip
        out["vazamento_mitigacao"] = _item("ok" if zerado >= 1 else "pendente", texto)
    else:
        out["vazamento"] = _item("pendente", "vazamento ainda não calculado")
        out["vazamento_mitigacao"] = _item("pendente", "sem área de mitigação")
    icsd = _col(tit, "icsd_minimo").dropna() if "icsd_minimo" in tit else pd.Series(dtype=float)
    ok = len(icsd) and bool((icsd >= c["icsd_minimo"] - 1e-6).all())
    out["estrutura_capital"] = _item(
        "ok" if ok else "pendente", f"dívida limitada pelo ICSD mínimo de {c['icsd_minimo']}"
    )
    texto = f"uma área de elegibilidade por estado ({resumo.get('uf')}); marcar a fazenda inicial na validação"
    out["projeto_agrupado"] = _item("ok", texto)
    validade = (dt.date.fromisoformat(resumo["data"]) + dt.timedelta(days=730)).isoformat()
    out["t0"] = _item("ok", f"foto de t = 0 de {resumo['data']}, vale até {validade} (VM0047: 2 anos)")
    out["orcamento"] = _item("ok", "custo por fazenda e método com faixa P10 a P90 (premissas da rodada 11)")
    preco = resumo["custo_liquido_por_credito_medio"] or 0.0
    contrato = resumo["preco_contrato_brl_t"]
    texto = (f"preço de equilíbrio médio das titulares: R$ {_br(preco)}/t; o contrato paga R$ {_br(contrato)}/t "
             f"(US$ {c['preco_contrato_usd_t']:.0f}), {'acima' if contrato >= preco else 'abaixo'} do equilíbrio "
             f"(retorno de {c['taxa_desconto']:.1%} real)")  # fmt: skip
    out["preco"] = _item("ok" if preco and contrato >= preco else "falha", texto)
    out["faixa_p50_p90"] = _item("pendente", "faixa P10 a P90 calculada; falta o atestado de terceiro independente")
    texto = (f"{_br(resumo['ha_regeneracao_titulares'])} ha de regeneração e {_br(resumo['ha_plantio_titulares'])} ha "
             "de plantio")  # fmt: skip
    out["modalidade"] = _item("ok", texto)
    out["forma_pdf"] = _item("pendente", "relatório do lote em HTML para imprimir em A4; conferir as 40 páginas no PDF")
    out["checklist"] = _item("ok", "este checklist, com gravidade e fonte de cada item")
    return out


def checklist(resumo: dict, tabela, p: dict | None = None, c: dict | None = None) -> list[dict]:
    """Todos os itens do edital, na ordem dos blocos, com gravidade, fonte e situação (automática ou a conferir)."""
    p = p or D.premissas()
    c = c or D.cenario(p=p)
    auto = checagens(resumo, tabela, p, c)
    out = []
    for it in edital()["itens"]:
        ch = it.get("checagem")
        s = auto.get(ch) if ch else None
        out.append({
            "id": it["id"], "bloco": it["bloco"], "item": it["item"], "gravidade": it["gravidade"],
            "exigido_por": it["exigido_por"], "fonte": it["fonte"],
            "situacao": s["situacao"] if s else "a_conferir",
            "detalhe": s["detalhe"] if s else f"falta construir: {it['falta_construir']}",
        })  # fmt: skip
    return out
