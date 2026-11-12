"""Triagem do título (E5 passo 8): checagem rápida ou busca completa, com o registro da previsão para comparar com
as certidões depois. Regra em raiz/regras/padroes/triagem_titulo.yaml.

Três saídas por imóvel:
  rapida         título limpo pelo que se vê: nota até 2, sem achado que reprova, matrícula lida e conferida, cadeia
                 até o título de origem, sem ônus grave e CAR batendo com o SIGEF;
  completa       falta algum desses itens: os motivos e o que pedir no cartório vão junto;
  regularizacao  posse ou assentamento: ainda não há título a buscar, segue o passo da regularização.
A chance de a busca completa achar problema é a priori (congelada como previsão, modelo triagem_titulo, alvo
titulo_problema_na_busca). O gabarito vem quando todas as matrículas do imóvel forem lidas: 1 se a certidão saiu
divergente ou cancelada, com quebra na cadeia ou ônus grave; 0 se saiu conferida e limpa.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from functools import lru_cache
from pathlib import Path

import yaml

ARQ = Path(__file__).resolve().parents[1] / "regras" / "padroes" / "triagem_titulo.yaml"
ALVO = "titulo_problema_na_busca"
MODELO = "triagem_titulo"
HORIZONTE_DIAS = 365
SAIDAS = ("rapida", "completa", "regularizacao")


@lru_cache
def _ler(arq: Path, _marca: tuple) -> dict:
    texto = arq.read_bytes()
    r = yaml.safe_load(texto)
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(texto).hexdigest()[:8]}"
    return r


def regra(arq: Path | None = None) -> dict:
    a = Path(arq or ARQ)
    return _ler(a, (str(a), a.stat().st_mtime_ns, a.stat().st_size))


def versao() -> str:
    return regra()["versao_completa"]


def _s(v) -> str | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v)


def _verdade(v) -> bool | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "sim", "t")
    return bool(v)


def triar(linha: dict, achados: list[dict], r: dict | None = None) -> dict:
    """linha: caminho_terra, matricula_conferida, matricula_onus_graves, titulo_nota, titulo_reprova e, na posse,
    regularizacao_proximo_passo. achados: os do imóvel (fase, regra, valor, situacao, gravidade, mensagem)."""
    r = r or regra()
    R, M = r["rapida"], r["motivos"]
    cam = _s(linha.get("caminho_terra")) or "sem_caminho"
    pedir: list[str] = []
    motivos: list[str] = []
    if cam in r["caminhos_regularizacao"] and not _verdade(linha.get("matricula_conferida")):
        saida = "regularizacao"
        passo = _s(linha.get("regularizacao_proximo_passo"))
        if passo:
            pedir.append(r["pedir_regularizacao"].format(passo=passo.rstrip(".")))
        chance = None
    else:
        if cam not in r["caminhos_titulo"]:
            motivos.append(M["caminho"].format(caminho=cam.replace("_", " ")))
        nota = linha.get("titulo_nota")
        if nota is None or (isinstance(nota, float) and math.isnan(nota)) or int(nota) > R["nota_max"]:
            motivos.append(M["nota_max"])
        if R["sem_reprova"] and int(linha.get("titulo_reprova") or 0) > 0:
            motivos.append(M["sem_reprova"])
        if R["matricula_conferida"] and not _verdade(linha.get("matricula_conferida")):
            motivos.append(M["matricula_conferida"])
        origens = [a for a in achados if a.get("regra") == "cadeia.origem"]
        if R["cadeia_chega_a_origem"] and (not origens or any(a.get("valor") != "chega_a_origem" for a in origens)):
            motivos.append(M["cadeia_chega_a_origem"])
        if R["sem_onus_grave"] and _verdade(linha.get("matricula_onus_graves")):
            motivos.append(M["sem_onus_grave"])
        geo = [str(a.get("valor")) for a in achados if a.get("regra") == "geometria.car_sigef"]
        ruins = [g for g in geo if g not in R["geometria_ok"]]
        if ruins:
            motivos.append(M["geometria_ok"].format(classe=ruins[0]))
        saida = "completa" if motivos else "rapida"
        if saida == "completa":
            pedir += list(r["pedir"])
            for a in origens:
                if a.get("valor") == "falta_ler_origem":
                    msg = str(a.get("mensagem") or "")
                    ref = msg.split(" vem da ", 1)[1].split(",", 1)[0] if " vem da " in msg else "de origem"
                    pedir.append(r["pedir_origem"].format(ref=ref))
        chance = float(r["chance_problema"][saida])
    return {
        "titulo_triagem": saida,
        "titulo_triagem_motivos": "; ".join(dict.fromkeys(motivos)) or None,
        "titulo_triagem_pedir": "; ".join(dict.fromkeys(pedir)) or None,
        "titulo_triagem_chance_problema": chance,
        "titulo_triagem_versao": r["versao_completa"],
    }


# --- previsão e gabarito -------------------------------------------------------------------------------------------


def congelar_triagem(con, rodada_id: int) -> tuple[str | None, bool, int]:
    """Congela a chance de problema na busca de cada imóvel com título a buscar (complemento 'titulo')."""
    from sqlalchemy import text

    from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote

    r = con.execute(text("select * from funil.rodada where id = :i"), {"i": rodada_id}).first()
    if r is None:
        raise ValueError(f"rodada {rodada_id} não existe")
    ps, versoes = [], set()
    for cod, a in con.execute(
        text("select cod_imovel, atributos from funil.complemento_imovel where rodada_id = :r and tipo = 'titulo'"),
        {"r": rodada_id},
    ):
        a = a or {}
        ch = a.get("titulo_triagem_chance_problema")
        if ch is None or (isinstance(ch, float) and math.isnan(ch)):
            continue
        versoes.add(a.get("titulo_triagem_versao") or "desconhecida")
        ps.append(Previsao(cod, ALVO, HORIZONTE_DIAS, valor_num=float(ch), valor_texto=a.get("titulo_triagem")))
    if not ps:
        return None, False, 0
    v = Versoes(
        modelo=MODELO,
        modelo_versao=",".join(sorted(versoes)),
        entradas_versao=r.hash_entradas,
        data_corte=r.data_corte,
        regras_versao=r.regras_versao,
        tipo="ao_vivo",
        rodada_id=rodada_id,
    )
    lh, novo = registrar_lote(con, ps, v, f"triagem do título, município {r.cod_municipio}, rodada {rodada_id}")
    return lh, novo, len(ps)


def gabaritar(con, hoje: dt.date | None = None) -> dict:
    """Quando uma rodada depois do corte traz todas as matrículas do imóvel lidas (complemento 'matricula'): 1 se
    alguma saiu divergente ou cancelada, com quebra na cadeia ou ônus grave; 0 se todas conferidas e limpas."""
    from sqlalchemy import text

    from raiz.aprendizado.registro import registrar_gabarito

    hoje = hoje or dt.date.today()
    pend = con.execute(
        text("""select distinct on (p.cod_imovel) p.cod_imovel, p.data_corte
                from aprendizado.previsao p
                where p.modelo = :m and p.alvo = :a
                  and not exists (select 1 from aprendizado.gabarito g where g.cod_imovel = p.cod_imovel
                                  and g.alvo = p.alvo and g.observado_em > p.data_corte)
                order by p.cod_imovel, p.data_corte desc"""),
        {"m": MODELO, "a": ALVO},
    ).all()
    n1 = n0 = 0
    for cod, corte in pend:
        m = con.execute(
            text("""select c.atributos as a, c.rodada_id from funil.complemento_imovel c
                    join funil.rodada r on r.id = c.rodada_id
                    where c.tipo = 'matricula' and c.cod_imovel = :c and r.data_corte > :d
                    order by r.data_corte desc, r.id desc limit 1"""),
            {"c": cod, "d": corte},
        ).first()
        if m is None:
            continue
        a = m.a or {}
        total, lidas = a.get("matriculas_total"), a.get("matriculas_lidas")
        if not total or lidas is None or int(lidas) < int(total):
            continue
        problema = (
            a.get("matricula_situacao") in ("divergente", "cancelada")
            or bool(_verdade(a.get("matricula_quebra_cadeia")))
            or bool(_verdade(a.get("matricula_onus_graves")))
        )
        registrar_gabarito(
            con,
            cod,
            ALVO,
            max(hoje, corte + dt.timedelta(days=1)),
            "certidao_lida",
            valor_num=1.0 if problema else 0.0,
            valor_texto=a.get("matricula_situacao"),
            referencia=f"rodada:{m.rodada_id}",
        )
        n1 += problema
        n0 += not problema
    return {"com_problema": n1, "limpas": n0, "em_aberto": len(pend) - n1 - n0}
