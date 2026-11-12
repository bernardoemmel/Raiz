"""Bandeiras de contexto e testes de auditoria do título (E5 passo 6), no padrão Cardinal: cada número é comparado
com os do mesmo município, do mesmo cartório e do mesmo dono, por quartis e cercas de Tukey (Q1 − k·IQR e Q3 + k·IQR;
cerca interna k = 1,5, externa k = 3). Passar da cerca interna é informação; da externa, pede confirmação. Grupo pequeno
(menos de MIN_GRUPO valores) não tem cerca: a bandeira não sai.

Medidas (só das matrículas já lidas, matricula_conferencia_<mun>.csv e cadeia_<mun>.csv de raiz/documentos):
  soma das glebas    soma das áreas das matrículas do imóvel ÷ área do CAR, quando todas as matrículas foram lidas.
                     Auditoria fixa: acima de 1,10 as matrículas passam do CAR (título sobreposto ou CAR menor); abaixo
                     de 0,90 parte do CAR está sem matrícula (posse junto do título). Contexto: a razão contra as do
                     município (regra "contexto.municipio").
  área redonda       área da matrícula inteira e múltipla de 5 ha, ou um número inteiro de alqueires (múltiplo de 5):
                     medida antiga ou declarada, não medida em campo. Georreferenciada e redonda pede confirmação.
  cartório           parte das matrículas lidas do cartório que saiu divergente ou cancelada, contra os outros cartórios
                     do município ("contexto.cartorio", fase referência).
  dono               área somada das matrículas do mesmo documento mascarado no município, contra os outros donos
                     ("contexto.dono", fase cadeia). A máscara guarda 6 dígitos: dois donos podem coincidir, por isso
                     a bandeira só pede confirmação. Nunca nome.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from raiz.titulo.achados import COLUNAS, Achado, chave_registro

VERSAO = "contexto-2026a"
MIN_GRUPO = 8
INTERNA, EXTERNA = 1.5, 3.0
GLEBAS_MAX, GLEBAS_MIN = 1.10, 0.90
ALQUEIRES = {"paulista": 2.42, "mineiro ou goiano": 4.84, "do norte": 2.72, "baiano": 9.68}
RUIM = {"divergente", "cancelada"}
PISO_RAZAO, PISO_TAXA, PISO_AREA_HA = 0.05, 0.10, 50.0  # IQR mínimo de cada medida


def cercas(valores, piso: float = 0.0) -> dict | None:
    """Quartis e cercas. piso: IQR mínimo, para o grupo em que quase todos são iguais (ex.: todos os cartórios com
    0% de divergência) não marcar qualquer diferença nem deixar de marcar o que destoa muito."""
    v = pd.Series(valores, dtype=float).dropna()
    if len(v) < MIN_GRUPO:
        return None
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    iqr = max(q3 - q1, piso)
    return dict(q1=q1, q3=q3, iqr=iqr, n=len(v), int_min=q1 - INTERNA * iqr, int_max=q3 + INTERNA * iqr,
                ext_min=q1 - EXTERNA * iqr, ext_max=q3 + EXTERNA * iqr)  # fmt: skip


def posicao(x: float, c: dict | None) -> str | None:
    """None (dentro), 'interna_alta', 'externa_alta', 'interna_baixa' ou 'externa_baixa'."""
    if c is None or x is None or (isinstance(x, float) and math.isnan(x)) or c["iqr"] <= 0:
        return None
    if x > c["ext_max"]:
        return "externa_alta"
    if x > c["int_max"]:
        return "interna_alta"
    if x < c["ext_min"]:
        return "externa_baixa"
    if x < c["int_min"]:
        return "interna_baixa"
    return None


def area_redonda(ha: float | None) -> str | None:
    """'X ha' ou 'X alqueires (tipo)' quando a área é redonda; None quando não é."""
    if ha is None or (isinstance(ha, float) and math.isnan(ha)) or ha < 10:
        return None
    if abs(ha - round(ha)) < 1e-6 and round(ha) % 5 == 0:
        return f"{_br(round(ha), 0)} ha"
    for nome, k in ALQUEIRES.items():
        n = ha / k
        if n >= 5 and abs(n - round(n)) < 1e-3 and round(n) % 5 == 0:
            return f"{round(n)} alqueires ({nome})"
    return None


def _br(x: float, casas: int = 1) -> str:
    from raiz.agentes.textos import num

    return num(x, casas)


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _verdade(v) -> bool | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v).strip().lower() in ("true", "1", "sim", "t")


def _ach(cod, mats, fase, regra, sit, grav, msg, campo, valor, fonte):
    return Achado(chave_registro(cod, mats), cod, fase, regra, sit, grav, msg, campo, valor, fonte,
                  regra_versao=VERSAO).linha()  # fmt: skip


def _texto_cerca(pos: str, c: dict, fmt) -> str:
    lado = "acima" if pos.endswith("alta") else "abaixo"
    cerca = "externa" if pos.startswith("externa") else "interna"
    lim = c["ext_max" if lado == "acima" and cerca == "externa" else "int_max" if lado == "acima" else
              "ext_min" if cerca == "externa" else "int_min"]  # fmt: skip
    return f"{lado} da cerca {cerca} ({fmt(lim)}; quartis {fmt(c['q1'])} a {fmt(c['q3'])}, {c['n']} valores)"


def achados_de_contexto(pasta: str | Path, cod: int) -> pd.DataFrame:
    from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula
    from raiz.titulo.regularizacao import arquivo_documentos

    pasta = Path(pasta)
    f = arquivo_documentos(pasta, cod, "matricula_conferencia")
    fi = pasta / f"imoveis_{cod}.csv"
    if f is None or not fi.exists():
        return pd.DataFrame(columns=COLUNAS)
    conf = pd.read_csv(f, dtype={"cod_imovel": str, "registro_cns": str, "registro_matricula": str})
    if conf.empty:
        return pd.DataFrame(columns=COLUNAS)
    for c in ("situacao", "area_matricula_ha"):  # arquivo antigo ou parcial: tolera a coluna que falta
        if c not in conf.columns:
            conf[c] = None
    conf["area_matricula_ha"] = pd.to_numeric(conf.area_matricula_ha, errors="coerce")
    conf["cns"] = conf.registro_cns.map(normalizar_cns)
    conf["mat"] = conf.registro_matricula.map(normalizar_matricula)
    conf["lida"] = conf.situacao.fillna("a_conferir") != "a_conferir"
    im = pd.read_csv(fi, dtype={"cod_imovel": str})
    col_ha = "ha" if "ha" in im.columns else "area"
    ha_car = dict(zip(im.cod_imovel, pd.to_numeric(im[col_ha], errors="coerce"), strict=True))
    georef = {}
    fc = arquivo_documentos(pasta, cod, "cadeia")
    cadeia = None
    if fc is not None:
        cadeia = pd.read_csv(fc, dtype={"registro_cns": str, "registro_matricula": str})
        if len(cadeia):
            primeira = cadeia.groupby(["registro_cns", "registro_matricula"], sort=False).first()
            georef = {k: _verdade(v) for k, v in primeira.georreferenciado.items()}
    out = []

    # --- soma das glebas (auditoria) e razão contra o município (contexto) ------------------------------------
    razoes = {}
    for c, g in conf.groupby("cod_imovel"):
        if not g.lida.all() or g.area_matricula_ha.isna().any():
            continue
        car = ha_car.get(c)
        if not car or car <= 0:
            continue
        razoes[c] = (float(g.area_matricula_ha.sum()) / car, list(zip(g.cns, g.mat, strict=True)), car)
    cm = cercas([r[0] for r in razoes.values()], piso=PISO_RAZAO)
    for c, (r, mats, car) in razoes.items():
        soma = r * car
        base = f"as {len(mats)} matrícula(s) somam {_br(soma)} ha para {_br(car)} ha do CAR (razão {_br(r, 2)})"
        if r > GLEBAS_MAX:
            out.append(_ach(c, mats, "coerencia", "auditoria.soma_glebas", "conferir", "confirmar",
                            f"{base}: o título passa do CAR (título sobreposto ou CAR menor que a terra)",
                            "razao", f"{r:.3f}", "certidões lidas e CAR"))  # fmt: skip
        elif r < GLEBAS_MIN:
            out.append(_ach(c, mats, "coerencia", "auditoria.soma_glebas", "conferir", "info",
                            f"{base}: parte do CAR está sem matrícula (posse junto do título)",
                            "razao", f"{r:.3f}", "certidões lidas e CAR"))  # fmt: skip
        else:
            out.append(_ach(c, mats, "coerencia", "auditoria.soma_glebas", "ok", "info", base, "razao", f"{r:.3f}",
                            "certidões lidas e CAR"))  # fmt: skip
        pos = posicao(r, cm)
        if pos:
            out.append(_ach(c, mats, "coerencia", "contexto.municipio", "conferir",
                            "confirmar" if pos.startswith("externa") else "info",
                            f"razão título ÷ CAR de {_br(r, 2)}, {_texto_cerca(pos, cm, lambda x: _br(x, 2))} do "
                            f"município", "razao", pos, "imóveis do município com certidão lida"))  # fmt: skip

    # --- área redonda (auditoria) -------------------------------------------------------------------------------
    for r in conf[conf.lida].itertuples(index=False):
        red = area_redonda(_num(r.area_matricula_ha))
        if red is None:
            continue
        geo = georef.get((r.cns, r.mat))
        grav = "confirmar" if geo else "info"
        texto = f"área redonda na matrícula {r.mat} ({red}): medida antiga ou declarada, não medida em campo"
        if geo:
            texto += "; a matrícula diz que é georreferenciada, o que não combina com área redonda"
        out.append(_ach(r.cod_imovel, [(r.cns, r.mat)], "coerencia", "auditoria.area_redonda", "conferir", grav,
                        texto, "area_matricula_ha", f"{_num(r.area_matricula_ha):.4f}", "certidão lida"))  # fmt: skip

    # --- cartório: parte divergente ou cancelada contra os outros cartórios ---------------------------------------
    lidas = conf[conf.lida].drop_duplicates(["cns", "mat"])
    por_cart = lidas.groupby("cns").situacao.agg(lambda s: (s.isin(RUIM).mean(), len(s)))
    taxas = {k: v for k, v in por_cart.items() if v[1] >= 3}
    cc = cercas([v[0] for v in taxas.values()], piso=PISO_TAXA)
    for cns, (taxa, n) in taxas.items():
        pos = posicao(taxa, cc)
        if pos not in ("interna_alta", "externa_alta"):
            continue
        for r in conf[conf.cns == cns].itertuples(index=False):
            out.append(_ach(r.cod_imovel, [(r.cns, r.mat)], "referencia", "contexto.cartorio", "conferir",
                            "confirmar" if pos == "externa_alta" else "info",
                            f"o cartório {cns} tem {_br(100 * taxa, 0)}% das {n} matrículas lidas divergentes ou "
                            f"canceladas, "
                            f"{_texto_cerca(pos, cc, lambda x: _br(100 * x, 0) + '%')} dos cartórios", "taxa",
                            f"{taxa:.3f}",
                            "certidões lidas do município"))  # fmt: skip

    # --- dono: área somada do mesmo documento mascarado ----------------------------------------------------------
    if cadeia is not None and len(cadeia) and "proprietarios_json" in cadeia.columns:
        primeira = cadeia.groupby(["registro_cns", "registro_matricula"], sort=False).first().reset_index()
        donos: dict[str, list] = {}
        for r in primeira.itertuples(index=False):
            area = _num(r.area_matricula_ha)
            for p in json.loads(r.proprietarios_json or "[]"):
                doc = p.get("documento")
                if doc and doc != "[documento]" and area:
                    donos.setdefault(doc, []).append(((r.registro_cns, r.registro_matricula), area))
        tot = {d: sum(a for _, a in xs) for d, xs in donos.items()}
        cd = cercas(list(tot.values()), piso=PISO_AREA_HA)
        for d, xs in donos.items():
            pos = posicao(tot[d], cd)
            if pos not in ("interna_alta", "externa_alta"):
                continue
            chaves = {k for k, _ in xs}
            for r in conf[[(a, b) in chaves for a, b in zip(conf.cns, conf.mat, strict=True)]].itertuples(index=False):
                out.append(_ach(r.cod_imovel, [(r.cns, r.mat)], "cadeia", "contexto.dono", "conferir", "confirmar",
                                f"o mesmo dono (documento {d}) tem {len(xs)} matrícula(s) que somam {_br(tot[d], 0)} "
                                f"ha no município, {_texto_cerca(pos, cd, lambda x: _br(x, 0) + ' ha')} dos donos; a "
                                f"máscara pode juntar donos diferentes: confirmar", "area_dono_ha", f"{tot[d]:.1f}",
                                "certidões lidas do município"))  # fmt: skip
    return pd.DataFrame(out, columns=COLUNAS)
