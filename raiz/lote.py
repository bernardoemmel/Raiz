"""Lote do ProFloresta+ por estado: o cliente pede 1 milhão de créditos e o mapa monta o melhor lote (cena-alvo).

Um só cálculo, do começo ao fim:
 - as fazendas e o valor de cada uma vêm do valor para quem restaura (desenvolvedor_<mun>.csv, raiz/restauracao.py),
   com o método que venceu a disputa da fazenda e o vazamento por vizinha (raiz/vazamento.py);
 - a escolha é o otimizador dos pedidos (raiz/pedidos/otimizador.py, HiGHS, opção mais barata), que põe a
   regeneração antes do plantio que o preço não paga e avisa quando o lote só fecha com ele;
 - titulares: o P50 que cumpre todos os marcos do Anexo IV com a tolerância (o do ano 7 é o mais apertado); reserva: o
   que falta para cumprir com a chance alvo (90%), porque o erro da captura é comum ao lote inteiro;
 - marcos, multa e rescisão no lote (restauracao.cronograma_lote); o fluxo do lote é a soma dos fluxos do P50 das
   fazendas (restauracao.fluxo_p50), com a dívida dimensionada no lote e o crédito além do contrato vendido ao preço
   depois do contrato; daí a TIR e o preço mínimo por crédito para a TIR de 12% e de 15%;
 - em espera: posse em titulação e assentamento, que entram quando a terra destravar (quadro "o que destrava o lote");
 - certidões: matrícula com certidão conferida separada da matrícula a conferir, e quantas certidões pedir para ter
   5% da área homologada na assinatura.
Nunca descarta fazenda por tamanho. Sem nome, CPF ou CNPJ: só o código do CAR.
Unificado com a branch claude/premissas-rodada11 (lote, checklist do edital, relatório e folha do dono; NOTICE.md).
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from raiz import restauracao as R
from raiz.pedidos import aceite as A
from raiz.pedidos import oferta as O
from raiz.pedidos import otimizador as Z
from raiz.pedidos.campos import CamposPedido
from raiz.pedidos.premissas import versao_modelo

PRONTA = ("matricula_conferida", "matricula_a_conferir", "concessao")
EM_ESPERA = ("posse_em_titulacao", "assentamento")
HOMOLOGADA = ("matricula_conferida", "concessao")  # direito documentado: certidão conferida ou contrato de concessão
METODOS = ["regeneracao_assistida", "semeadura_direta", "plantio_total"]
COLUNAS_TABELA = (
    "papel", "cod_imovel", "cod_ibge", "municipio", "area_ha", "ha", "pequena", "modo", "metodo",
    "regeneracao_ha", "semeadura_ha", "plantio_ha", "credito_p10", "credito_p50", "credito_p90", "custo_credito_usd",
    "preco_equilibrio_usd", "abaixo_equilibrio", "tir_p50", "caminho", "caminho_terra", "risco_terra", "matriculas",
    "pedir_certidao", "vazamento_motivo", "vazamento_mitigacao_imovel", "grupo_id", "restauracao_versao",
)  # fmt: skip


def premissas_lote(r: dict | None = None) -> dict:
    return (r or R.regra())["lote"]


def edital(r: dict | None = None) -> dict:
    arq = R.ARQ_REGRA.parent / premissas_lote(r)["edital"]
    return yaml.safe_load(arq.read_text(encoding="utf-8"))


# --- leitura ------------------------------------------------------------------------------------------------------


def _cod_mun(f: Path) -> int:
    return int(f.stem.split("_")[-1])


def matriculas(pasta: Path, cod: int) -> dict[str, int]:
    """Matrículas de cada imóvel (certidoes_<mun>.csv: cartório e número de matrícula das parcelas SIGEF): cada uma é
    uma certidão a pedir no cartório."""
    f = Path(pasta) / f"certidoes_{cod}.csv"
    if not f.exists():
        return {}
    t = pd.read_csv(f, dtype=str)
    out: dict[str, set] = defaultdict(set)
    for cod_im, cns, mat in zip(t.cod_imovel, t.get("registro_cns", ""), t.get("registro_matricula", ""), strict=True):
        cs = str(cns).split(";") if isinstance(cns, str) else [""]
        ms = str(mat).split(";") if isinstance(mat, str) else []
        for i, m in enumerate(ms):
            if m.strip():
                out[str(cod_im)].add((cs[min(i, len(cs) - 1)].strip(), m.strip()))
    return {k: len(v) for k, v in out.items()}


def ler_pasta(pasta: str | Path, uf: str, municipios: list[int] | None = None) -> dict:
    """A oferta de um estado a partir da pasta do motor (imoveis_, desenvolvedor_, terra_, certidoes_ <mun>), só com
    as fazendas que têm área para restaurar (lidas pelo nome das colunas)."""
    pasta = Path(pasta)
    estado = sorted({_cod_mun(f) for f in pasta.glob("imoveis_*.csv")})
    lidos = sorted({_cod_mun(f) for f in pasta.glob("desenvolvedor_*.csv")} & set(estado))
    if municipios:
        lidos = [m for m in lidos if m in set(int(x) for x in municipios)]
    regs, mats = [], {}
    for cod in lidos:
        pts = O.pontos_da_pasta(pasta, cod)
        for li in O.linhas_da_pasta(pasta, cod, so_restauracao=True):
            o = O.de_linha(li, *(pts.get(str(li["cod_imovel"])) or (None, None)))
            if o is not None:
                regs.append(o)
        mats.update(matriculas(pasta, cod))
    oferta = O.tabela(regs)
    oferta["uf"] = oferta.uf.fillna(uf.upper())
    return {"uf": uf.upper(), "pasta": pasta, "oferta": oferta, "municipios_estado": estado,
            "municipios_lidos": lidos, "matriculas": mats}  # fmt: skip


def ler_uf(saida: str | Path, uf: str, municipios: list[int] | None = None) -> dict:
    return ler_pasta(Path(saida) / uf.upper(), uf, municipios)


class Linhas:
    """Linhas de algumas fazendas, lidas sob demanda por município: as entradas para refazer o caminho do P50
    (restauracao.linhas_para_refazer) e as linhas completas, com as colunas gravadas (para a folha do dono)."""

    def __init__(self, pasta: str | Path, oferta: pd.DataFrame):
        self.pasta = Path(pasta)
        self.mun = dict(zip(oferta.cod_imovel.astype(str), oferta.cod_ibge, strict=True))
        self._ent: dict[str, dict] = {}
        self._comp: dict[str, dict] = {}

    def _ler(self, cods, cache: dict, ler) -> dict[str, dict]:
        cods = [str(c) for c in cods]
        por_mun: dict[int, set] = defaultdict(set)
        for c in cods:
            if c not in cache and self.mun.get(c) is not None and not pd.isna(self.mun[c]):
                por_mun[int(self.mun[c])].add(c)
        for m, cs in por_mun.items():
            cache.update(ler(m, cs))
        return {c: cache[c] for c in cods if c in cache}

    def entradas(self, cods) -> dict[str, dict]:
        return self._ler(cods, self._ent, lambda m, cs: R.linhas_para_refazer(self.pasta, m, cs))

    def completas(self, cods) -> dict[str, dict]:
        return self._ler(
            cods,
            self._comp,
            lambda m, cs: {str(li["cod_imovel"]): li for li in O.linhas_da_pasta(self.pasta, m, so=cs)},
        )


# --- montagem -----------------------------------------------------------------------------------------------------


def _pedido(uf: str, meta: float, c: dict, terra=PRONTA) -> CamposPedido:
    return CamposPedido.model_validate({
        "meta": {"tipo": "creditos", "valor": max(float(meta), 1.0)}, "onde": {"ufs": [uf], "biomas": ["Amazônia"]},
        "terra": list(terra), "metodos": METODOS, "dinheiro": {"preco_venda_usd": float(c["preco_usd_t"])},
    })  # fmt: skip


def _media(x: pd.DataFrame, col: str, peso: str = "credito_p50") -> float | None:
    if not len(x):
        return None
    v = pd.to_numeric(x[col], errors="coerce").to_numpy(float)
    w = pd.to_numeric(x[peso], errors="coerce").fillna(0).to_numpy(float)
    ok = np.isfinite(v) & (w > 0)
    return float((v[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else None


def _creditos_regeneracao(x: pd.DataFrame, r: dict) -> float:
    """Parte dos créditos de cada fazenda que vem da regeneração (pela área e o total de 40 anos de cada método)."""
    if not len(x):
        return 0.0
    tot = r["captura_curva"]["total_tco2_ha"]
    pr = x.regeneracao_ha * float(tot["regeneracao_assistida"])
    todos = pr + x.semeadura_ha * float(tot["semeadura_direta"]) + x.plantio_ha * float(tot["plantio_total"])
    return float((x.credito_p50 * (pr / todos.where(todos > 0))).fillna(0).sum())


def _selecionar(oferta: pd.DataFrame, uf: str, precisa50: float, precisa_alvo: float, c: dict,
                terra=PRONTA) -> dict:  # fmt: skip
    """Titulares e reserva pelo otimizador dos pedidos (opção mais barata)."""
    ped = _pedido(uf, precisa50, c, terra)
    f = Z.filtrar(oferta, ped).reset_index(drop=True)
    if not len(f):
        return {"f": f, "tit": f, "res": f, "estado": "sem_fazenda", "ped": ped}
    chance = A.chances(f, {}, None, "participacao")
    rs = Z.resolver(f, ped, "barata", chance, reserva_meta=max(precisa_alvo - precisa50, 0.0))
    return {"f": f, "tit": f.iloc[list(rs["sel"])].copy(), "res": f.iloc[list(rs["reserva"])].copy(),
            "estado": rs["estado"], "ped": ped}  # fmt: skip


def _economia(lote: pd.DataFrame, linhas: Linhas, c: dict, r: dict, volume: float, cron: dict | None,
              partes_cache: dict) -> dict:  # fmt: skip
    """Fluxo do lote (soma das fazendas no P50), TIR no preço do contrato e o preço mínimo para 12% e 15%."""
    cods = [str(x) for x in lote.cod_imovel]
    faltam = [x for x in cods if x not in partes_cache]
    for cod, li in linhas.entradas(faltam).items():
        partes_cache[cod] = R.fluxo_p50(li, c, r)
    partes = [partes_cache[x] for x in cods if x in partes_cache]
    multas = {int(m["ano"]) + 1: m["multa_esperada_rs"] for m in (cron or {}).get("marcos", [])}
    fl = R.fluxo_lote(partes, c, multas, volume=volume)
    t = R.tir_lote(fl, c)
    out = {
        "fazendas_com_fluxo": len(partes),
        "tir_projeto_pct": None if t["tir_projeto"] is None else round(100 * t["tir_projeto"], 1),
        "tir_alavancada_pct": None if t["tir_alavancada"] is None else round(100 * t["tir_alavancada"], 1),
        "vpl_rs": round(t["vpl_rs"], 0), "divida_fracao": round(t["divida_fracao"], 3),
        "pico_capital_rs": round(t["pico_capital_rs"], 0), "excesso_creditos": round(fl["excesso_creditos"], 0),
        "preco_equilibrio_usd": R.preco_para_tir(fl, c, float(c["taxa_desconto"]), alavancada=False),
        "preco_minimo_usd": {}, "metodos": defaultdict(int),
    }  # fmt: skip
    for alvo in (12, 15):
        out["preco_minimo_usd"][str(alvo)] = {
            "alavancada": R.preco_para_tir(fl, c, alvo / 100, alavancada=True),
            "projeto": R.preco_para_tir(fl, c, alvo / 100, alavancada=False),
        }
    for x in partes:
        out["metodos"][x["metodo"]] += 1
    out["metodos"] = dict(out["metodos"])
    return out


def _certidoes(lote: pd.DataFrame, mats: dict[str, int], fracao: float) -> dict:
    """Matrícula com certidão conferida contra a conferir, e quantas certidões pedir (das maiores áreas por certidão
    primeiro) para ter `fracao` da área do lote homologada na assinatura."""
    ha = float(lote.area_ha.sum()) if len(lote) else 0.0
    por = {}
    for cam in (*PRONTA, *EM_ESPERA):
        x = lote[lote.caminho == cam]
        por[cam] = {"fazendas": int(len(x)), "ha": round(float(x.area_ha.sum()), 1)}
    homologada = sum(por[c_]["ha"] for c_ in HOMOLOGADA)
    alvo = fracao * ha
    falta = max(alvo - homologada, 0.0)
    a_conf = lote[lote.caminho == "matricula_a_conferir"].copy()
    a_conf["n_mat"] = pd.Series([int(mats.get(str(x), 0)) for x in a_conf.cod_imovel], index=a_conf.index, dtype=int)
    a_conf["certidoes"] = a_conf.n_mat.clip(lower=1)  # sem número no SIGEF: uma certidão a localizar pelo CAR
    a_conf = a_conf.assign(rend=a_conf.area_ha / a_conf.certidoes).sort_values(["rend", "area_ha"], ascending=False)
    pedir, cert, cob = [], 0, 0.0
    for cod, area, n in zip(a_conf.cod_imovel, a_conf.area_ha, a_conf.certidoes, strict=True):
        if cob >= falta - 1e-9:
            break
        pedir.append(str(cod))
        cert += int(n)
        cob += float(area)
    return {
        "ha_lote": round(ha, 1), "fracao_exigida": fracao, "ha_exigidos": round(alvo, 1),
        "ha_homologados": round(homologada, 1), "falta_ha": round(falta, 1), "por_caminho": por,
        "matriculas_conhecidas": int(a_conf.n_mat.sum()) if len(a_conf) else 0,
        "a_conferir_sem_matricula_sigef": int((a_conf.n_mat == 0).sum()) if len(a_conf) else 0,
        "certidoes_a_pedir": cert, "fazendas_a_pedir": len(pedir), "ha_cobertos": round(cob, 1),
        "cumpre_com_pedidos": bool(cob >= falta - 1e-9), "pedir": pedir,
    }  # fmt: skip


def _em_espera(oferta: pd.DataFrame, uf: str, c: dict, r: dict) -> dict:
    ped = _pedido(uf, 1.0, c, EM_ESPERA)
    esp = Z.filtrar(oferta, ped)
    out = {"fazendas": int(len(esp)), "ha": round(float(esp.area_ha.sum()), 1), "por_caminho": {}}
    for cam in EM_ESPERA:
        x = esp[esp.caminho == cam]
        out["por_caminho"][cam] = {
            "fazendas": int(len(x)), "ha": round(float(x.area_ha.sum()), 1),
            "ha_regeneracao": round(float(x.regeneracao_ha.sum()), 1),
            "fazendas_com_regeneracao": int((x.regeneracao_ha > 0.05).sum()),
            "creditos": round(float(x.credito_p50.sum()), 0),
            "creditos_regeneracao": round(_creditos_regeneracao(x, r), 0),
        }  # fmt: skip
    out["ha_regeneracao"] = round(sum(v["ha_regeneracao"] for v in out["por_caminho"].values()), 1)
    out["creditos_regeneracao"] = round(sum(v["creditos_regeneracao"] for v in out["por_caminho"].values()), 0)
    # quão perto do título está cada uma (raiz/titulo/regularizacao.py): o que dá para destravar primeiro
    out["por_regularizacao"] = {}
    if "regularizacao_classe" in esp.columns:
        for cl, x in esp.groupby(esp.regularizacao_classe.fillna("sem_calculo")):
            out["por_regularizacao"][str(cl)] = {
                "fazendas": int(len(x)), "ha": round(float(x.area_ha.sum()), 1),
                "creditos": round(float(x.credito_p50.sum()), 0),
            }  # fmt: skip
    return {**out, "tabela": esp}


def _resumo_lote(sel: dict, precisa50: float, precisa_alvo: float, volume: float, c: dict, r: dict,
                 linhas: Linhas, partes_cache: dict) -> dict:  # fmt: skip
    tit, res = sel["tit"], sel["res"]
    lote = pd.concat([tit, res], ignore_index=True)
    c_tit, c_lote = float(tit.credito_p50.sum()), float(lote.credito_p50.sum())
    cron_tit = R.cronograma_lote(c_tit, c, r, volume) if c_tit > 0 else None
    cron_lote = R.cronograma_lote(c_lote, c, r, volume) if c_lote > 0 else None
    eco = _economia(lote, linhas, c, r, volume, cron_lote, partes_cache) if len(lote) else None
    ped_alvo = _pedido(sel["ped"].onde.ufs[0], precisa_alvo, c, sel["ped"].terra)
    return {
        "titulares": int(len(tit)), "reservas": int(len(res)),
        "pequenas": int(lote.pequena.sum()) if len(lote) else 0,
        "ha_titulares": round(float(tit.area_ha.sum()), 1), "ha_lote": round(float(lote.area_ha.sum()), 1),
        "ha_por_metodo": {m: round(float(lote[c_].sum()), 1) for m, c_ in
                          (("regeneracao_assistida", "regeneracao_ha"), ("semeadura_direta", "semeadura_ha"),
                           ("plantio_total", "plantio_ha"))} if len(lote) else {},
        "creditos_titulares": round(c_tit, 0), "creditos_lote": round(c_lote, 0),
        "creditos_lote_faixa": {k: round(v, 0) for k, v in Z.faixa_soma(
            lote.credito_p10, lote.credito_p50, lote.credito_p90, rho=1.0).items()} if len(lote) else None,
        "fecha_no_p50": c_tit >= precisa50 - 1e-6, "fecha_com_reserva": c_lote >= precisa_alvo - 1e-6,
        "falta_p50": round(max(precisa50 - c_tit, 0.0), 0), "falta_reserva": round(max(precisa_alvo - c_lote, 0.0), 0),
        "custo_credito_usd_medio": None if (m := _media(lote, "custo_credito_usd")) is None else round(m, 2),
        "preco_equilibrio_usd_medio": None if (m := _media(lote, "preco_equilibrio_usd")) is None else round(m, 2),
        "tir_fazendas_media_pct": None if (m := _media(lote, "tir_p50")) is None else round(m, 1),
        "cronograma_titulares": cron_tit, "cronograma_lote": cron_lote, "economia": eco,
        "abaixo_equilibrio": Z.abaixo_equilibrio(sel["f"], lote, ped_alvo),
        "municipios_no_lote": int(lote.cod_ibge.nunique()) if len(lote) else 0,
        "solver": sel["estado"],
    }  # fmt: skip


def montar(dados: dict, volume: float | None = None, c: dict | None = None, r: dict | None = None,
           chance_alvo: float | None = None) -> dict:  # fmt: skip
    """O lote do estado com reserva, marcos, preço mínimo, o que destrava o lote, certidões e o checklist."""
    r = r or R.regra()
    c = c or R.cenario(r=r)
    lt = premissas_lote(r)
    volume = float(volume or lt["creditos"])
    chance = float(chance_alvo or lt["chance_alvo_reserva"])
    uf, oferta = dados["uf"], dados["oferta"]
    linhas = Linhas(dados["pasta"], oferta)
    partes: dict[str, dict] = {}
    precisa50 = R.contrato_para_marcos(volume, c, r)
    fator = R.fator_captura_alvo(chance, r)
    precisa_alvo = precisa50 / fator
    sel = _selecionar(oferta, uf, precisa50, precisa_alvo, c)
    resumo = _resumo_lote(sel, precisa50, precisa_alvo, volume, c, r, linhas, partes)
    # o que destrava o lote: posse em titulação e assentamento como se virassem título ou parceria
    esp = _em_espera(oferta, uf, c, r)
    destravada = None
    if esp["fazendas"]:
        o2 = oferta.copy()
        vira = o2.cod_imovel.isin(esp["tabela"].cod_imovel)
        o2.loc[vira, "caminho"] = "matricula_a_conferir"
        o2.loc[vira, "risco_terra"] = "medio"
        sel2 = _selecionar(o2, uf, precisa50, precisa_alvo, c)
        r2 = _resumo_lote(sel2, precisa50, precisa_alvo, volume, c, r, linhas, partes)
        usa = pd.concat([sel2["tit"], sel2["res"]]).cod_imovel.isin(esp["tabela"].cod_imovel)
        destravada = {k: r2[k] for k in ("titulares", "reservas", "ha_lote", "creditos_lote", "fecha_no_p50",
                                         "fecha_com_reserva", "falta_reserva", "custo_credito_usd_medio",
                                         "preco_equilibrio_usd_medio", "economia", "abaixo_equilibrio")}  # fmt: skip
        destravada["cronograma_lote"] = r2["cronograma_lote"]
        destravada["fazendas_destravadas_no_lote"] = int(usa.sum())
    lote = pd.concat([sel["tit"].assign(papel="titular"), sel["res"].assign(papel="reserva")], ignore_index=True)
    cert = _certidoes(lote, dados.get("matriculas") or {}, float(lt["area_homologada_assinatura"]))
    # vizinhas que recebem o gado (VMD0054): área de mitigação, sem crédito
    viz = {str(v) for v in lote.vazamento_mitigacao_imovel.dropna() if str(v)} - set(lote.cod_imovel.astype(str))
    mit = oferta[oferta.cod_imovel.isin(viz)].assign(papel="mitigacao")
    faltam_viz = viz - set(mit.cod_imovel)
    if faltam_viz:
        mit = pd.concat([mit, pd.DataFrame({"cod_imovel": sorted(faltam_viz), "papel": "mitigacao"})])
    espera = esp.pop("tabela").assign(papel="em_espera")
    espera = espera[~espera.cod_imovel.isin(mit.cod_imovel)]  # a vizinha que recebe o gado aparece como mitigação
    tabela = pd.concat([lote, mit, espera], ignore_index=True)
    tabela["metodo"] = tabela.cod_imovel.map(lambda x: partes[x]["metodo"] if x in partes else None)
    tabela["abaixo_equilibrio"] = tabela.preco_equilibrio_usd.astype(float) > float(c["preco_usd_t"])
    tabela["matriculas"] = tabela.cod_imovel.map(lambda x: (dados.get("matriculas") or {}).get(str(x), 0))
    tabela["pedir_certidao"] = tabela.cod_imovel.isin(cert.pop("pedir"))
    tabela = tabela[[k for k in COLUNAS_TABELA if k in tabela.columns]]
    em_lote = set(lote.cod_ibge.dropna().astype(int))
    resumo.update({
        "uf": uf, "data": dt.date.today().isoformat(), "cenario": c["cenario"],
        "versao_premissas": r["versao_completa"], "versao_otimizador": versao_modelo(),
        "versao_edital": edital(r).get("versao"), "volume_creditos": volume, "chance_alvo": chance,
        "fator_captura_alvo": round(fator, 4), "creditos_precisa_p50": round(precisa50, 0),
        "creditos_precisa_com_reserva": round(precisa_alvo, 0),
        "preco_contrato_usd": float(c["preco_usd_t"]), "cambio_brl_usd": float(c["cambio_brl_usd"]),
        "preco_contrato_brl": round(float(c["preco_usd_t"]) * float(c["cambio_brl_usd"]), 2),
        "taxa_desconto": float(c["taxa_desconto"]),
        "municipios": {"no_estado": len(dados["municipios_estado"]), "lidos": len(dados["municipios_lidos"]),
                       "com_fazenda_elegivel": int(sel["f"].cod_ibge.nunique()) if len(sel["f"]) else 0,
                       "no_lote": len(em_lote),
                       "sem_calculo": sorted(set(dados["municipios_estado"]) - set(dados["municipios_lidos"]))},
        "oferta": {"fazendas": int(len(oferta)), "ha": round(float(oferta.area_ha.sum()), 1),
                   "fazendas_terra_pronta": int(len(sel["f"])),
                   "creditos_terra_pronta": round(float(sel["f"].credito_p50.sum()), 0) if len(sel["f"]) else 0.0},
        "mitigacao": int(len(mit)), "em_espera": esp, "terra_destravada": destravada, "certidoes": cert,
    })  # fmt: skip
    resumo["o_que_falta"] = o_que_falta(resumo)
    resumo["checklist"] = checklist(resumo, tabela, c, r)
    return {"resumo": resumo, "tabela": tabela, "linhas": linhas}


def _br(x: float, nd: int = 0) -> str:
    s = f"{x:,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def o_que_falta(res: dict) -> list[str]:
    """Frases do que falta para o lote fechar 1 milhão com reserva (vazio quando fecha)."""
    out = []
    v = _br(res["volume_creditos"])
    if not res["fecha_no_p50"]:
        out.append(f"Faltam {_br(res['falta_p50'])} créditos líquidos até o ano 25 (P50) só para cumprir os marcos de "
                   f"{v} créditos: a terra pronta soma {_br(res['oferta']['creditos_terra_pronta'])}.")  # fmt: skip
    if not res["fecha_com_reserva"]:
        out.append(f"Faltam {_br(res['falta_reserva'])} créditos de reserva para {res['chance_alvo']:.0%} de chance de "
                   f"cumprir os marcos (o lote precisa de {_br(res['creditos_precisa_com_reserva'])} no P50 e tem "
                   f"{_br(res['creditos_lote'])}).")  # fmt: skip
    td = res.get("terra_destravada")
    if out and td:
        esp = res["em_espera"]
        if td["fecha_com_reserva"]:
            out.append(f"Fecha se a terra em espera destravar: {_br(esp['fazendas'])} fazendas em posse em titulação "
                       f"e assentamento ({_br(esp['ha'])} ha, {_br(esp['ha_regeneracao'])} ha de regeneração); o lote "
                       f"usaria {_br(td['fazendas_destravadas_no_lote'])} delas.")  # fmt: skip
        pr = esp.get("por_regularizacao") or {}
        perto = sum(pr.get(k, {}).get("fazendas", 0) for k in ("em_titulacao", "pronta_para_pedir"))
        geo = pr.get("falta_georreferenciamento", {}).get("fazendas", 0)
        if perto or geo:
            out.append(f"Da terra em espera, {_br(perto)} fazendas já estão em titulação ou prontas para pedir o "
                       f"título e {_br(geo)} só precisam do georreferenciamento certificado no SIGEF.")  # fmt: skip
        else:
            out.append(f"Nem com a terra em espera destravada fecha: faltariam {_br(td['falta_reserva'])} créditos de "
                       "reserva; é preciso outro estado ou mais municípios calculados.")  # fmt: skip
    if res["municipios"]["sem_calculo"]:
        n = len(res["municipios"]["sem_calculo"])
        out.append(f"{n} {'município' if n == 1 else 'municípios'} do estado ainda sem o valor para quem restaura "
                   "calculado.")  # fmt: skip
    cron = res.get("cronograma_lote")
    if cron and res["fecha_com_reserva"] and cron["chance_todos"] < res["chance_alvo"] - 0.02:
        out.append(f"Com a reserva a chance de cumprir todos os marcos é {cron['chance_todos']:.0%}, abaixo do alvo de "
                   f"{res['chance_alvo']:.0%}.")  # fmt: skip
    return out


# --- checklist do edital ------------------------------------------------------------------------------------------


def _item(st: str, texto: str) -> dict:
    return {"situacao": st, "detalhe": texto}


def checagens(res: dict, tabela: pd.DataFrame, c: dict, r: dict) -> dict[str, dict]:
    """O que dá para conferir com os dados da Raíz. situação: ok, falha, pendente (falta dado ou ação de alguém)."""
    lt = premissas_lote(r)
    lote = tabela[tabela.papel.isin(["titular", "reserva"])]
    out = {}
    ha, minimo = res["ha_lote"], float(lt["area_minima_ha"])
    out["area_minima"] = _item("ok" if ha >= minimo else "falha",
                               f"{_br(ha)} ha no lote com a reserva; mínimo da fase 1: {_br(minimo)} ha")  # fmt: skip
    ce = res["certidoes"]
    if ce["falta_ha"] <= 0:
        texto = (f"{_br(ce['ha_homologados'])} ha com certidão conferida ou concessão (precisa de "
                 f"{_br(ce['ha_exigidos'])} ha); falta o aceite assinado")  # fmt: skip
        out["area_inicial"] = _item("pendente", texto)
    else:
        texto = (f"{_br(ce['ha_homologados'])} ha homologados de {_br(ce['ha_exigidos'])} ha "
                 f"({ce['fracao_exigida']:.0%} do lote): pedir {_br(ce['certidoes_a_pedir'])} certidões de "
                 f"{_br(ce['fazendas_a_pedir'])} fazendas com matrícula a conferir")  # fmt: skip
        out["area_inicial"] = _item("pendente" if ce["cumpre_com_pedidos"] else "falha", texto)
    anos = int(c["horizonte_anos"])
    out["cessao_carbono"] = _item("pendente", f"cada dono assina a cessão irrevogável do carbono no aceite ({anos} "
                                              "anos), pela Raíz")  # fmt: skip
    out["sem_sobreposicao"] = _item("ok", "fazenda sobre projeto de carbono registrado não entra no lote (exclusão "
                                          "padrão do pedido)")  # fmt: skip
    out["contrato_40_anos"] = _item("ok" if anos >= 40 else "falha",
                                    f"contrato com o dono de {anos} anos (longevidade da Verra: 40)")  # fmt: skip
    out["sem_desmatamento"] = _item("ok", "só entram fazendas sem embargo, terra indígena, UC de proteção integral ou "
                                          "bloqueio territorial do motor")  # fmt: skip
    out["metodologia"] = _item("ok", "VM0047 v1.1 da Verra, aprovada pelo ICVCM (CCP)")
    out["creditos_liquidos"] = _item(
        "ok" if float(c["incerteza"]) >= 0.10 else "falha",
        f"ordem: linha de base, vazamento, reserva de risco, incerteza; incerteza de {float(c['incerteza']):.0%}",
    )
    medida = lote.restauracao_versao.notna().sum() if "restauracao_versao" in lote else 0
    out["linha_base"] = _item("pendente", f"linha de base dinâmica medida no YbYrá por município, piso de "
                                          f"{float(c['linha_base_piso']):.0%}; calcular os controles pareados "
                                          f"({_br(medida)} fazendas com cálculo)")  # fmt: skip
    out["reserva_risco"] = _item("pendente", f"reserva de {float(c['reserva_risco']):.0%}; preencher a ferramenta de "
                                             "risco AFOLU por fazenda")  # fmt: skip
    cron = res.get("cronograma_lote")
    if cron:
        ok = cron["chance_todos"] >= res["chance_alvo"] - 1e-9
        texto = (f"chance de cumprir todos os marcos com a reserva: {cron['chance_todos']:.0%} (alvo "
                 f"{res['chance_alvo']:.0%}); rescisão: {cron['chance_rescisao']:.0%}")  # fmt: skip
        out["cronograma"] = _item("ok" if ok else "falha", texto)
    else:
        out["cronograma"] = _item("falha", "o estado não tem fazenda com crédito para montar o lote")
    vz = lote.vazamento_motivo.dropna() if "vazamento_motivo" in lote else pd.Series(dtype=object)
    if len(vz):
        zerado = float(vz.isin(["mitigacao_vizinha", "sem_gado"]).mean())
        out["vazamento"] = _item("ok", f"vazamento calculado por fazenda (VMD0054); zerado em {zerado:.0%} das "
                                       "fazendas do lote")  # fmt: skip
        out["vazamento_mitigacao"] = _item(
            "ok" if zerado >= 1 else "pendente",
            f"{res['mitigacao']} vizinhas como área de mitigação; falta acordo de 5 anos ou mais e laudo de cada uma",
        )
    else:
        out["vazamento"] = _item("pendente", f"vazamento de {float(c['vazamento']):.0%} do cenário; a vizinha de "
                                             "mitigação sai com o contorno das fazendas")  # fmt: skip
        out["vazamento_mitigacao"] = _item("pendente", "sem área de mitigação calculada")
    eco = res.get("economia") or {}
    fr = eco.get("divida_fracao")
    out["estrutura_capital"] = _item(
        "ok" if fr is not None and fr >= float(c.get("fracao_financiada_minima") or 0) - 1e-9 else "pendente",
        f"dívida do Fundo Clima dimensionada no caixa do lote pelo ICSD de {c['icsd_minimo']}: "
        f"{(fr or 0):.0%} do investimento")  # fmt: skip
    out["projeto_agrupado"] = _item("ok", f"uma área de elegibilidade por estado ({res['uf']}); marcar a fazenda "
                                          "inicial na validação")  # fmt: skip
    validade = (dt.date.fromisoformat(res["data"]) + dt.timedelta(days=730)).isoformat()
    out["t0"] = _item("ok", f"foto de t = 0 de {res['data']}, vale até {validade} (VM0047: 2 anos)")
    out["orcamento"] = _item("ok", "custo por fazenda e método com faixa P10 a P90 de fontes publicadas (SFB, "
                                   "Altamira, Systemica, Escolhas)")  # fmt: skip
    eq = eco.get("preco_equilibrio_usd")
    preco = res["preco_contrato_usd"]
    out["preco"] = _item(
        "ok" if eq is not None and preco >= eq else "falha",
        f"preço de equilíbrio do lote: US$ {_br(eq or 0, 2)}/t (retorno de {res['taxa_desconto']:.1%} real); o "
        f"contrato paga US$ {_br(preco, 2)}/t")  # fmt: skip
    out["faixa_p50_p90"] = _item("pendente", "faixa P10 a P90 calculada; falta o atestado de terceiro independente")
    hm = res.get("ha_por_metodo") or {}
    out["modalidade"] = _item("ok", f"{_br(hm.get('regeneracao_assistida', 0))} ha de regeneração, "
                                    f"{_br(hm.get('semeadura_direta', 0))} ha de semeadura e "
                                    f"{_br(hm.get('plantio_total', 0))} ha de plantio")  # fmt: skip
    out["forma_pdf"] = _item("pendente", "relatório do lote em HTML para imprimir em A4; conferir as páginas no PDF")
    out["checklist"] = _item("ok", "este checklist, com gravidade e fonte de cada item")
    return out


def checklist(res: dict, tabela: pd.DataFrame, c: dict, r: dict) -> list[dict]:
    """Todos os itens do edital, na ordem dos blocos, com gravidade, fonte e situação (automática ou a conferir)."""
    auto = checagens(res, tabela, c, r)
    out = []
    for it in edital(r)["itens"]:
        ch = it.get("checagem")
        s = auto.get(ch) if ch else None
        out.append({
            "id": it["id"], "bloco": it["bloco"], "item": it["item"], "gravidade": it["gravidade"],
            "exigido_por": it["exigido_por"], "fonte": it["fonte"],
            "situacao": s["situacao"] if s else "a_conferir",
            "detalhe": s["detalhe"] if s else f"falta construir: {it['falta_construir']}",
        })  # fmt: skip
    return out


def json_seguro(x):
    """Para gravar o resumo em JSON (numpy e NaN viram tipos simples)."""
    if isinstance(x, dict):
        return {str(k): json_seguro(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [json_seguro(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else float(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x
