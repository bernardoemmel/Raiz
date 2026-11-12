"""Fatos novos sobre as fazendas de um pedido salvo, para o vigia do pedido (docs/cena-alvo.md, passo 9):

    desmatamento        alerta de desmatamento ou degradação da vigilância diária (MapBiomas Alerta, DETER, PRODES)
                        que a Raíz viu depois que o pedido foi salvo
    embargo             termo de embargo do Ibama novo e ainda ativo sobre a fazenda
    matricula_cancelada leitura de certidão que diz que a matrícula foi encerrada, cancelada ou transportada
                        (matricula_<mun>.csv do leitor de certidões, raiz/documentos)

Cada fato tem uma chave estável (fonte e identificador do alerta ou da leitura): o vigia nunca avisa duas vezes o
mesmo fato. Fica de fora o que a vigilância já marcou como falso, a sobreposição de borda e o que entrou só como
linha de base (alerta velho achado na primeira leitura de uma fonte). Nada pessoal: só código do CAR, fonte, data e
área.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd

from raiz.vigilancia.fontes import data as _data

log = logging.getLogger(__name__)

TIPOS_DESMATAMENTO = ("desmatamento", "degradacao")
NOME_FONTE = {
    "mapbiomas_alerta": "MapBiomas Alerta",
    "deter": "DETER do INPE",
    "prodes": "PRODES do INPE",
    "ibama_embargo": "Ibama",
}


@dataclass(frozen=True)
class Fato:
    cod_imovel: str
    motivo: str  # desmatamento | embargo | matricula_cancelada
    chave: str
    data: dt.date | None
    texto: str
    detalhe: dict = field(default_factory=dict)


def _br(d: dt.date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "data não informada"


def _ha(x) -> str:
    try:
        return f"{float(x):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "?"


def fatos_vigilancia(
    cods: Iterable[str], desde: dt.date, armazem=None, ativo_ibama: dict[str, bool] | None = None
) -> list[Fato]:
    """Desmatamento e embargo vistos pela vigilância desde `desde` nas fazendas `cods`."""
    from raiz.vigilancia import aprendizado
    from raiz.vigilancia.armazem import Armazem
    from raiz.vigilancia.config import config

    cods = {str(c) for c in cods}
    if not cods:
        return []
    arm = armazem or Armazem(config().estado)
    al = arm.alertas("imovel")
    if not len(al):
        return []
    al = al[al["alvo_id"].isin(cods)]
    if not len(al):
        return []
    marc = arm.marcacoes()
    pend = arm.pendentes("marcacao")
    if pend:
        marc = pd.concat([marc, pd.DataFrame(pend)], ignore_index=True) if len(marc) else pd.DataFrame(pend)
    vig = aprendizado.vigentes(marc)
    falsos = set(vig.loc[~vig["verdadeiro"].astype(bool), "alerta_id"]) if len(vig) else set()
    if ativo_ibama is None:
        e = arm.espelho_ibama()
        ativo_ibama = dict(zip(e["seq_tad"].astype(str), e["ativo"], strict=False)) if e is not None else {}
    out: list[Fato] = []
    for _, a in al.iterrows():
        visto = _data(a["visto_em"])
        if visto is None or visto < desde or a["alerta_id"] in falsos or bool(a["borda"]) or not bool(a["novo"]):
            continue
        tipo = a["tipo"]
        fonte = NOME_FONTE.get(a["fonte"], a["fonte"])
        evento = _data(a["data_evento"])
        base = {
            "fonte": a["fonte"],
            "alerta_id": a["alerta_id"],
            "data_evento": evento.isoformat() if evento else None,
            "visto_em": visto.isoformat(),
            "area_ha": None if pd.isna(a["area_sobreposta_ha"]) else round(float(a["area_sobreposta_ha"]), 4),
            "confianca": float(a["confianca"]),
            "link": a.get("link") if isinstance(a.get("link"), str) else None,
        }
        if tipo in TIPOS_DESMATAMENTO:
            nome = "derrubada" if tipo == "desmatamento" else "degradação da floresta"
            out.append(
                Fato(
                    a["alvo_id"],
                    "desmatamento",
                    f"vigilancia:{a['alerta_id']}",
                    evento,
                    f"Fazenda do grupo com {nome}: {_ha(a['area_sobreposta_ha'])} ha, imagem de {_br(evento)} "
                    f"({fonte}).",
                    {**base, "tipo": tipo},
                )
            )
        elif tipo == "embargo" and ativo_ibama.get(str(a["chave"]), True):
            out.append(
                Fato(
                    a["alvo_id"],
                    "embargo",
                    f"vigilancia:{a['alerta_id']}",
                    evento,
                    f"Fazenda do grupo com embargo novo do Ibama, de {_br(evento)}"
                    + (f", sobre {_ha(a['area_sobreposta_ha'])} ha." if a["area_sobreposta_ha"] else "."),
                    {**base, "tipo": tipo},
                )
            )
    return out


def fatos_matricula(cods: Iterable[str], achar=None) -> list[Fato]:
    """Matrícula cancelada segundo as certidões lidas (matricula_<mun>.csv, colunas lidas pelo nome)."""
    if achar is None:
        try:
            from raiz.documentos.tabelas import achar
        except ImportError:  # pragma: no cover - o pacote de documentos vem junto do produto
            return []
    por_mun: dict[str, set[str]] = {}
    for c in cods:
        partes = str(c).split("-")
        if len(partes) >= 2 and partes[1].isdigit():
            por_mun.setdefault(partes[1], set()).add(str(c))
    out: list[Fato] = []
    for mun, lista in por_mun.items():
        arq = achar("matricula", mun)
        if arq is None:
            continue
        cab = pd.read_csv(arq, nrows=0).columns
        if "cod_imovel" not in cab or "matricula_situacao" not in cab:
            continue
        usar = [c for c in ("cod_imovel", "matricula_situacao", "matricula_lido_em", "matricula_motivo") if c in cab]
        t = pd.read_csv(arq, usecols=usar, dtype=str)
        t = t[t["cod_imovel"].isin(lista) & (t["matricula_situacao"].str.lower() == "cancelada")]
        for _, r in t.iterrows():
            lido = r.get("matricula_lido_em") if isinstance(r.get("matricula_lido_em"), str) else ""
            out.append(
                Fato(
                    r["cod_imovel"],
                    "matricula_cancelada",
                    f"matricula:{r['cod_imovel']}:{lido[:19]}",
                    _data(lido),
                    "Fazenda do grupo com matrícula encerrada ou cancelada na certidão lida"
                    + (f" em {_br(_data(lido))}." if _data(lido) else "."),
                    {"fonte": "certidao", "lido_em": lido or None},
                )
            )
    return out


def fatos(cods: Iterable[str], desde: dt.date, armazem=None, achar=None) -> list[Fato]:
    """Todos os fatos novos das fazendas. Fonte fora do ar (estado da vigilância ou certidões indisponíveis) não para
    o vigia: só fica de fora e o log avisa."""
    cods = [str(c) for c in cods]
    out: list[Fato] = []
    for nome, f in (
        ("vigilância", lambda: fatos_vigilancia(cods, desde, armazem)),
        ("certidões", lambda: fatos_matricula(cods, achar)),
    ):
        try:
            out += f()
        except Exception as ex:  # noqa: BLE001
            log.warning("vigia do pedido sem %s: %s", nome, type(ex).__name__)
    return sorted(out, key=lambda x: (x.cod_imovel, x.motivo, x.chave))


def atualizar_estado() -> dict:
    """Traz o estado publicado da vigilância (parte aberta; com RAIZ_VIGILANCIA_CHAVE, também as marcações). Usado
    pelo ciclo dos pedidos antes do vigia; sem rede, segue com o estado local."""
    from raiz.vigilancia import publicacao
    from raiz.vigilancia.armazem import Armazem
    from raiz.vigilancia.config import config

    cfg = config()
    try:
        return publicacao.baixar_estado(Armazem(cfg.estado), publicacao.Release(cfg), cfg.chave)
    except Exception as ex:  # noqa: BLE001
        log.warning("estado da vigilância não baixou: %s", type(ex).__name__)
        return {"erro": type(ex).__name__}
