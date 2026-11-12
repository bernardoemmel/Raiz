"""Por que a fazenda é (ou não é) apta, item por item, com o número que decide.

Mesmas regras e textos de front/compartilhado/motivos.ts e das categorias de front/compartilhado/dados/funil.ts (que
seguem o motor): a ficha servida pela API já leva a explicação, para qualquer cliente (front, agente do WhatsApp,
laudo) e para nunca mostrar um imóvel não apto sem dizer por quê.
"""

from __future__ import annotations

import math

CATEGORIAS = {
    "apta_matricula": "Apta, com matrícula",
    "apta_titulo": "Apta, título a conferir",
    "apta_assentamento": "Apta, assentamento para agrupar",
    "sem_area": "Sem área apta agora",
    "bloqueio": "Embargo, TI ou desmate recente",
}


def _num(linha: dict, c: str) -> float | None:
    v = linha.get(c)
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _n0(linha: dict, c: str, padrao: float = 0.0) -> float:
    x = _num(linha, c)
    return padrao if x is None else x


def _bool(linha: dict, c: str) -> bool | None:
    v = linha.get(c)
    if isinstance(v, bool) or v is None:
        return v
    s = str(v).strip().lower()
    if s in {"true", "1", "sim", "s", "yes"}:
        return True
    if s in {"false", "0", "não", "nao", "n", "no"}:
        return False
    return None


def _int_br(n: float) -> str:
    return f"{math.floor(abs(n) + 0.5) * (1 if n >= 0 else -1):,}".replace(",", ".")


def fmt_ha(n: float) -> str:
    """Como o fmtHa do front: 12.345 ha; 0,5 ha; 0 ha."""
    if abs(n) >= 10 or n == 0:
        return f"{_int_br(n)} ha"
    s = f"{n:.1f}".rstrip("0").rstrip(".")
    return f"{s.replace('.', ',')} ha"


def ler(linha: dict) -> dict:
    """Os campos que as regras usam, com os mesmos padrões de lerImovel do front."""
    ha = _n0(linha, "ha", _n0(linha, "area"))
    carbono_ha = _n0(linha, "carbono_ha") if "carbono_ha" in linha else _n0(linha, "alem_RL_ha")
    problema = _bool(linha, "problema")
    if problema is None:
        problema = any(_n0(linha, c) > 1 for c in ("embargo_ha", "ti_ha", "desm_pos2020_ha", "alerta_pos2020_ha"))
    desm16 = _num(linha, "desm_pos2016_ha")
    f_matricula = _num(linha, "f_matricula")
    if f_matricula is None:
        f_matricula = _n0(linha, "matricula_ha") / ha if ha > 0 else 0
    apta = (not problema) and carbono_ha > 0 and (desm16 or 0) <= 5
    assentamento = linha.get("frente") == "assentamento_agrupado" or (
        ha > 0 and _n0(linha, "assentamento_ha") / ha >= 0.5
    )
    return {
        "ha": ha,
        "carbono_ha": carbono_ha,
        "problema": problema,
        "apta": apta,
        "com_matricula": apta and f_matricula >= 0.5,
        "assentamento": assentamento,
    }


def categoria(i: dict) -> str:
    if i["problema"]:
        return "bloqueio"
    if i["com_matricula"]:
        return "apta_matricula"
    if i["apta"] and i["assentamento"]:
        return "apta_assentamento"
    if i["apta"]:
        return "apta_titulo"
    return "sem_area"


def motivos(linha: dict) -> list[dict]:
    """Lista de itens {id, ok, texto, detalhe, bloqueia}, na ordem do front."""
    i = ler(linha)
    n = lambda c: _n0(linha, c)  # noqa: E731
    embargo, ti, d20, alerta, d16 = (
        n("embargo_ha"),
        n("ti_ha"),
        n("desm_pos2020_ha"),
        n("alerta_pos2020_ha"),
        n("desm_pos2016_ha"),
    )
    ano = _num(linha, "alerta_ultimo_ano")
    lista = [
        {
            "id": "embargo",
            "ok": embargo <= 1,
            "texto": "Sem embargo do Ibama" if embargo <= 1 else "Tem embargo do Ibama",
            "detalhe": f"{fmt_ha(embargo)} embargados (limite: 1 ha)",
            "bloqueia": True,
        },
        {
            "id": "ti",
            "ok": ti <= 1,
            "texto": "Fora de terra indígena" if ti <= 1 else "Sobrepõe terra indígena",
            "detalhe": f"{fmt_ha(ti)} em terra indígena (limite: 1 ha)",
            "bloqueia": True,
        },
        {
            "id": "desmate2020",
            "ok": d20 <= 1,
            "texto": "Sem desmatamento depois de 2020" if d20 <= 1 else "Desmatamento depois de 2020",
            "detalhe": f"{fmt_ha(d20)} no PRODES desde 2021 (limite: 1 ha)",
            "bloqueia": True,
        },
        {
            "id": "alerta",
            "ok": alerta <= 1,
            "texto": "Sem alerta de desmatamento depois de 2020"
            if alerta <= 1
            else "Alerta de desmatamento depois de 2020",
            "detalhe": f"{fmt_ha(alerta)} em alertas do MapBiomas (limite: 1 ha)"
            if alerta <= 1
            else f"{fmt_ha(alerta)} em alertas do MapBiomas" + (f", o último em {int(ano)}" if ano else ""),
            "bloqueia": True,
        },
        {
            "id": "desmate2016",
            "ok": d16 <= 5,
            "texto": "Pouco ou nenhum desmate nos últimos 10 anos" if d16 <= 5 else "Desmate nos últimos 10 anos",
            "detalhe": f"{fmt_ha(d16)} desmatados no PRODES desde 2016 (limite para carbono: 5 ha)",
            "bloqueia": True,
        },
        {
            "id": "alem",
            "ok": i["carbono_ha"] > 0,
            "texto": "Tem área aberta além da reserva legal onde a mata volta sozinha"
            if i["carbono_ha"] > 0
            else "Sem área para a mata voltar além da reserva legal",
            "detalhe": f"{fmt_ha(n('alem_RL_ha'))} abertos além da reserva legal; "
            f"{fmt_ha(n('pasto_ate1km_ha'))} de pasto a até 1 km de floresta",
            "bloqueia": True,
        },
    ]
    if n("uc_ha") > 1:
        lista.append(
            {
                "id": "uc",
                "ok": False,
                "texto": "Sobrepõe unidade de conservação",
                "detalhe": f"{fmt_ha(n('uc_ha'))} em UC: conferir a categoria (proteção integral ou uso sustentável)",
                "bloqueia": False,
            }
        )
    if n("deficit_RL_ha") > 1:
        pct = _num(linha, "pct_RL")
        pct_txt = "—" if pct is None else f"{pct:g}"
        lista.append(
            {
                "id": "reserva",
                "ok": False,
                "texto": "Falta reserva legal",
                "detalhe": f"{fmt_ha(n('deficit_RL_ha'))} de reserva legal a recompor ({pct_txt}% do imóvel); "
                "não impede o carbono na área além da reserva",
                "bloqueia": False,
            }
        )
    if n("app_desmatada_ha") > 1:
        app = _num(linha, "app_recompor_ha")
        lista.append(
            {
                "id": "app",
                "ok": False,
                "texto": "Beira de rio aberta (APP)",
                "detalhe": f"{fmt_ha(n('app_desmatada_ha') if app is None else app)} de APP a recompor pela regra "
                "da escadinha",
                "bloqueia": False,
            }
        )
    eudr = _bool(linha, "eudr_ok")
    if eudr is not None:
        lista.append(
            {
                "id": "eudr",
                "ok": eudr,
                "texto": "Passa na regra europeia (sem desmate depois de 2020)"
                if eudr
                else "Não passa na regra europeia",
                "detalhe": "Regulamento europeu contra desmatamento (EUDR): corte em 31/12/2020",
                "bloqueia": False,
            }
        )
    credito = _bool(linha, "credito_rural_ok")
    if credito is not None:
        lista.append(
            {
                "id": "credito",
                "ok": credito,
                "texto": "Pode ter crédito rural" if credito else "Crédito rural travado",
                "detalhe": "Sem embargo, terra indígena ou unidade de conservação",
                "bloqueia": False,
            }
        )
    territorial = linha.get("filtro_territorial")
    if territorial and territorial != "ok":
        lista.append(
            {
                "id": "territorial",
                "ok": False,
                "texto": "Bloqueio territorial" if territorial == "bloqueio" else "Atenção territorial",
                "detalhe": "Quilombo, terra indígena da FUNAI em qualquer fase ou UC de proteção integral sobre o "
                "imóvel. O funil do motor ainda não tira o imóvel por isso: conferir antes do contrato.",
                "bloqueia": False,
            }
        )
    return lista


def situacao(linha: dict) -> dict:
    """Categoria do mapa, se é apta e, se não for, os itens que tiram a fazenda do funil (sempre ao menos um)."""
    i = ler(linha)
    cat = categoria(i)
    ms = motivos(linha)
    porque = [m["texto"] for m in ms if m["bloqueia"] and not m["ok"]]
    return {
        "categoria": cat,
        "rotulo": CATEGORIAS[cat],
        "apta": i["apta"],
        "com_matricula": i["com_matricula"],
        "frente": linha.get("frente"),
        "status_imovel": linha.get("status_imovel"),
        "porque_nao_apta": porque if not i["apta"] else [],
    }
