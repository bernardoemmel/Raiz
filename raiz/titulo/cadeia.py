"""Origem da cadeia dominial (E5 passo 6): a matrícula chega ao título de origem, o destaque do patrimônio público?

Lê o cadeia_<mun>.csv (raiz/documentos, uma linha por ato) e o matricula_conferencia_<mun>.csv (que liga cada
matrícula ao imóvel do CAR). Para cada matrícula lida, segue a matrícula de origem dentro do que já foi lido (mesmo
cartório) e diz onde a cadeia para:
  chega_a_origem       a origem é título público (INCRA, Estado, União) ou usucapião, ou há na cadeia um ato
                       originário (titulação pública, legitimação fundiária, usucapião, desapropriação): ok;
  falta_ler_origem     a matrícula vem de outra matrícula ou transcrição ainda não lida: pedir essa certidão;
  origem_desconhecida  a certidão não diz de onde a matrícula veio.
Sai como achado da fase cadeia (regra "cadeia.origem"). A continuidade do registro é a da Lei 6.015/1973 (arts. 195 e
237): nenhum registro sem o título anterior registrado. Na Amazônia, terra sem destaque do patrimônio público é o
caminho da grilagem; por isso a cadeia precisa chegar à origem, não só ser contínua.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from raiz.titulo.achados import COLUNAS, Achado, chave_registro

VERSAO = "cadeia-origem-2026a"
ORIGINARIOS = {"titulacao_publica", "legitimacao_fundiaria", "usucapiao", "desapropriacao"}
ORIGEM_OK = {"titulo_publico", "usucapiao"}
BASE = "continuidade do registro (Lei 6.015/1973, arts. 195 e 237)"
MAX_SALTOS = 12


def _ler(f: Path | None, **kw) -> pd.DataFrame | None:
    if f is None or not Path(f).exists():
        return None
    return pd.read_csv(f, **kw)


def matriculas(cadeia: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por matrícula (a leitura do arquivo), com originario = há ato originário na cadeia."""
    cadeia = cadeia.copy()
    cadeia["originario"] = cadeia.natureza.isin(ORIGINARIOS)
    g = cadeia.groupby(["registro_cns", "registro_matricula"], sort=False)
    m = g.first().reset_index()
    m["originario"] = g.originario.any().values
    return m


def resolver(m: pd.DataFrame) -> dict[tuple[str, str], dict]:
    """(cns, matrícula) -> situacao, para_em, saltos e origem final, seguindo origem_matricula no mesmo cartório."""
    por = {(r.registro_cns, r.registro_matricula): r for r in m.itertuples(index=False)}
    out = {}
    for k in por:
        atual, saltos, vistos = por[k], 0, {k}
        while True:
            if atual.origem in ORIGEM_OK or bool(atual.originario):
                sit = "chega_a_origem"
                break
            prox = (atual.registro_cns, str(atual.origem_matricula)) if pd.notna(atual.origem_matricula) else None
            if atual.origem in ("matricula_anterior", "transcricao_anterior"):
                if prox in por and prox not in vistos and saltos < MAX_SALTOS:
                    atual, saltos = por[prox], saltos + 1
                    vistos.add(prox)
                    continue
                sit = "falta_ler_origem"
            else:
                sit = "origem_desconhecida"
            break
        out[k] = dict(
            situacao=sit,
            para_em=atual.registro_matricula,
            saltos=saltos,
            origem=atual.origem,
            origem_referencia=atual.origem_referencia if pd.notna(atual.origem_referencia) else None,
        )
    return out


def _achado(cod: str, cns: str, mat: str, r: dict) -> Achado:
    s = r["situacao"]
    via = f" (passando por {r['saltos']} matrícula(s) de origem)" if r["saltos"] else ""
    if s == "chega_a_origem":
        msg = f"a cadeia da matrícula {mat} chega ao título de origem{via}"
        sit, grav = "ok", "info"
    elif s == "falta_ler_origem":
        ref = r["origem_referencia"] or "de origem"
        tipo = "transcrição" if r["origem"] == "transcricao_anterior" else "matrícula"
        msg = (
            f"a matrícula {r['para_em']} vem da {tipo} {ref}, que ainda não foi lida: pedir essa certidão para chegar "
            f"ao título de origem (destaque do patrimônio público)"
        )
        sit, grav = "conferir", "confirmar"
    else:
        msg = f"a certidão da matrícula {r['para_em']} não diz de onde a matrícula veio: conferir a origem no cartório"
        sit, grav = "conferir", "confirmar"
    return Achado(
        chave_registro(cod, [(cns, mat)]), cod, "cadeia", "cadeia.origem", sit, grav, msg, "origem", s,
        "certidão de inteiro teor (cadeia dominial)", BASE, regra_versao=VERSAO,
    )  # fmt: skip


def achados_da_cadeia(pasta: str | Path, cod: int) -> pd.DataFrame:
    from raiz.titulo.regularizacao import arquivo_documentos

    pasta = Path(pasta)
    tipos = {"registro_cns": str, "registro_matricula": str, "origem_matricula": str}
    cadeia = _ler(arquivo_documentos(pasta, cod, "cadeia"), dtype=tipos)
    conf = _ler(arquivo_documentos(pasta, cod, "matricula_conferencia"), dtype={**tipos, "cod_imovel": str})
    if cadeia is None or conf is None or cadeia.empty or conf.empty:
        return pd.DataFrame(columns=COLUNAS)
    from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula

    res = resolver(matriculas(cadeia))
    out = []
    for r in conf.itertuples(index=False):
        k = (normalizar_cns(r.registro_cns), normalizar_matricula(r.registro_matricula))
        if k in res:
            out.append(_achado(r.cod_imovel, k[0], k[1], res[k]).linha())
    return pd.DataFrame(out, columns=COLUNAS)
