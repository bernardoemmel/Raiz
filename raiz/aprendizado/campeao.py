"""Campeão e desafiante (E8 passo 6): uma versão nova de modelo só vale quando ganha da atual nos mesmos imóveis.

comparar  pareia as previsões do campeão e do desafiante pelo imóvel, alvo e data de corte, só as que já maturaram
          (passou o horizonte) e têm gabarito, e mede a perda de cada um: Brier para chance (0 a 1), erro de classe
          para texto, erro absoluto para número. A diferença média (desafiante − campeão; negativa = desafiante
          melhor) vem com intervalo de 95% por bootstrap pareado com semente fixa, pesada por 1/chance do sorteio.
portao    promove quando: pares suficientes (N_MIN), o intervalo da diferença fica todo abaixo de zero e, para chance,
          a calibração do desafiante (ECE) fica dentro da tolerância.
promover  grava a promoção (aprendizado.campeao) se o portão deixa, o alvo não está travado e a última promoção
          tem mais de INTERVALO_DIAS (a não ser que gente force). A promoção automática nunca passa pela trava.
voltar    volta atrás, à mão, para o campeão anterior.
travar    trava ou destrava a promoção automática de um alvo.
"""

from __future__ import annotations

import datetime as dt
import json
import random

from sqlalchemy import Connection, text

N_MIN = 30
TOL_ECE = 0.05
INTERVALO_DIAS = 30
BOOTSTRAP = 1000
SEMENTE = 20261112


def campeao_atual(con: Connection, alvo: str):
    return con.execute(text("select * from aprendizado.campeao_vigente where alvo = :a"), {"a": alvo}).first()


def travado(con: Connection, alvo: str) -> bool:
    r = con.execute(
        text("select travado from aprendizado.trava where alvo = :a order by em desc, id desc limit 1"), {"a": alvo}
    ).first()
    return bool(r and r.travado)


def _pares(con: Connection, alvo: str, campeao: tuple[str, str], desafiante: tuple[str, str]) -> list:
    return con.execute(
        text("""
        select c.cod_imovel, c.valor_num as c_num, c.valor_texto as c_txt, d.valor_num as d_num,
               d.valor_texto as d_txt, c.real_num, c.real_texto, g.probabilidade_escolha as prob
        from aprendizado.previsao_contra_gabarito c
        join aprendizado.previsao_contra_gabarito d
          on d.cod_imovel = c.cod_imovel and d.alvo = c.alvo and d.data_corte = c.data_corte
         and d.modelo = :dm and d.modelo_versao = :dv
        join aprendizado.gabarito g on g.id = c.gabarito_id
        where c.alvo = :a and c.modelo = :cm and c.modelo_versao = :cv and c.maturou and c.gabarito_id is not null
          and d.gabarito_id = c.gabarito_id"""),
        {"a": alvo, "cm": campeao[0], "cv": campeao[1], "dm": desafiante[0], "dv": desafiante[1]},
    ).all()


def _perda(prev_num, prev_txt, real_num, real_txt) -> tuple[str, float] | None:
    if prev_num is not None and real_num is not None and 0 <= prev_num <= 1 and real_num in (0.0, 1.0):
        return "brier", (prev_num - real_num) ** 2
    if prev_txt is not None and real_txt is not None:
        return "erro_classe", float(prev_txt != real_txt)
    if prev_num is not None and real_num is not None:
        return "erro_abs", abs(prev_num - real_num)
    return None


def comparar(con: Connection, alvo: str, campeao: tuple[str, str], desafiante: tuple[str, str]) -> dict:
    from raiz.aprendizado.calibracao import ece

    linhas = []
    for r in _pares(con, alvo, campeao, desafiante):
        pc = _perda(r.c_num, r.c_txt, r.real_num, r.real_texto)
        pd = _perda(r.d_num, r.d_txt, r.real_num, r.real_texto)
        if pc and pd and pc[0] == pd[0]:
            linhas.append((pc[0], pc[1], pd[1], 1.0 / r.prob if r.prob else 1.0, r.d_num, r.real_num))
    out = {"alvo": alvo, "campeao": list(campeao), "desafiante": list(desafiante), "pares": len(linhas)}
    if not linhas:
        return out
    medida = linhas[0][0]
    ws = [x[3] for x in linhas]
    sw = sum(ws)
    dif = [x[2] - x[1] for x in linhas]
    media = sum(w * d for w, d in zip(ws, dif, strict=True)) / sw
    rnd = random.Random(SEMENTE)
    n = len(linhas)
    boots = []
    for _ in range(BOOTSTRAP):
        idx = [rnd.randrange(n) for _ in range(n)]
        sw_b = sum(ws[i] for i in idx)
        boots.append(sum(ws[i] * dif[i] for i in idx) / sw_b)
    boots.sort()
    out.update(
        medida=medida,
        perda_campeao=sum(w * x[1] for w, x in zip(ws, linhas, strict=True)) / sw,
        perda_desafiante=sum(w * x[2] for w, x in zip(ws, linhas, strict=True)) / sw,
        diferenca=media,
        ic95=(boots[int(0.025 * BOOTSTRAP)], boots[int(0.975 * BOOTSTRAP) - 1]),
    )
    if medida == "brier":
        out["ece_desafiante"] = ece([x[4] for x in linhas], [x[5] for x in linhas], ws)
    return out


def portao(cmp: dict, n_min: int = N_MIN, tol_ece: float = TOL_ECE) -> tuple[bool, list[str]]:
    motivos = []
    if cmp.get("pares", 0) < n_min:
        motivos.append(f"poucos pares maturados com gabarito ({cmp.get('pares', 0)} de {n_min})")
    elif cmp["ic95"][1] >= 0:
        motivos.append(
            f"o desafiante não ganha com folga: diferença {cmp['diferenca']:+.4f} "
            f"(95%: {cmp['ic95'][0]:+.4f} a {cmp['ic95'][1]:+.4f})"
        )
    if cmp.get("medida") == "brier" and cmp.get("ece_desafiante", 0) > tol_ece:
        motivos.append(f"calibração do desafiante fora da tolerância (ECE {cmp['ece_desafiante']:.3f} > {tol_ece})")
    return not motivos, motivos


def _gravar(con, alvo, modelo, versao, acao, automatico, quem, motivo, medidas) -> int:
    return con.execute(
        text("""insert into aprendizado.campeao (alvo, modelo, modelo_versao, acao, automatico, quem, motivo, medidas)
                values (:a, :m, :v, :ac, :au, :q, :mo, cast(:me as jsonb)) returning id"""),
        dict(
            a=alvo, m=modelo, v=versao, ac=acao, au=automatico, q=quem, mo=motivo, me=json.dumps(medidas, default=str)
        ),  # fmt: skip
    ).scalar_one()


def definir_inicial(con: Connection, alvo: str, modelo: str, versao: str, quem: str) -> int:
    """Primeiro campeão de um alvo (o modelo que já roda)."""
    if campeao_atual(con, alvo) is not None:
        raise ValueError(f"{alvo} já tem campeão")
    return _gravar(con, alvo, modelo, versao, "inicial", False, quem, "modelo em uso", {})


def promover(
    con: Connection,
    alvo: str,
    desafiante: tuple[str, str],
    quem: str = "automatico",
    forcar: bool = False,
    agora: dt.datetime | None = None,
) -> dict:
    """{"promovido": bool, "motivos": [...], "comparacao": {...}}. forcar=True é decisão de gente: passa pela trava e
    pelo intervalo, mas não pelo portão."""
    from raiz.titulo.banco import _QUEM

    if quem != "automatico" and not _QUEM.match(quem):
        raise ValueError("quem: identificador do operador (ex.: fundador), nunca nome")
    agora = agora or dt.datetime.now(dt.UTC)
    atual = campeao_atual(con, alvo)
    if atual is None:
        raise ValueError(f"{alvo} sem campeão: defina o inicial (raiz aprendizado campeao --inicial)")
    automatico = quem == "automatico"
    cmp = comparar(con, alvo, (atual.modelo, atual.modelo_versao), desafiante)
    ok, motivos = portao(cmp)
    if automatico and travado(con, alvo):
        motivos.append("alvo travado para promoção automática")
    if not forcar and atual.acao != "inicial":
        dias = (agora - atual.em).days
        if dias < INTERVALO_DIAS:
            motivos.append(f"última troca há {dias} dias (mínimo {INTERVALO_DIAS})")
    if forcar and automatico:
        raise ValueError("só gente força uma promoção")
    if motivos and not (forcar and ok):
        return {"promovido": False, "motivos": motivos, "comparacao": cmp}
    _gravar(con, alvo, desafiante[0], desafiante[1], "promocao", automatico, quem,
            "ganhou do campeão no portão", cmp)  # fmt: skip
    return {"promovido": True, "motivos": [], "comparacao": cmp}


def voltar(con: Connection, alvo: str, quem: str, motivo: str) -> dict:
    """Volta ao campeão anterior (à mão)."""
    hist = con.execute(
        text("select * from aprendizado.campeao where alvo = :a order by em desc, id desc"), {"a": alvo}
    ).all()
    if len(hist) < 2:
        raise ValueError(f"{alvo} não tem campeão anterior")
    atual = hist[0]
    anterior = next((h for h in hist[1:] if (h.modelo, h.modelo_versao) != (atual.modelo, atual.modelo_versao)), None)
    if anterior is None:
        raise ValueError(f"{alvo} não tem campeão anterior diferente do atual")
    _gravar(con, alvo, anterior.modelo, anterior.modelo_versao, "volta_atras", False, quem, motivo, {})
    return {"modelo": anterior.modelo, "modelo_versao": anterior.modelo_versao}


def travar(con: Connection, alvo: str, quem: str, motivo: str | None = None, travar_: bool = True) -> None:
    con.execute(
        text("insert into aprendizado.trava (alvo, travado, quem, motivo) values (:a, :t, :q, :m)"),
        dict(a=alvo, t=travar_, q=quem, m=motivo),
    )
