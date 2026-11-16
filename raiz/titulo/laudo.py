"""Laudo de título por imóvel (E5 passo 7), em HTML e, com o LibreOffice instalado, em PDF.

Junta, pelo nome das colunas: a nota, a decisão e a triagem (titulo_<mun>.csv), o caminho da terra (terra_<mun>.csv),
a regularização da posse (regularizacao_<mun>.csv), os achados por fase (achados_<mun>.csv; com o banco, os
vigentes com quem confirmou e os de documento avulso, como a localização da sede), a cadeia dominial (banco ou
cadeia_<mun>.csv), as consultas públicas gravadas em WARC e as explicações de cada regra. Nada de nome ou CPF: as
pessoas aparecem como P1, P2 e o documento vem mascarado.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import pandas as pd

VERSAO = "laudo-titulo-2026a"
MODELOS = Path(__file__).resolve().parent / "modelos"
ORDEM_FASES = ["regularizacao", "cadeia", "coerencia", "geometria", "referencia", "formato"]
NOMES_FASE = {
    "regularizacao": "Regularização da posse",
    "cadeia": "Cadeia dominial",
    "coerencia": "Coerência das áreas",
    "geometria": "Geometria (CAR, SIGEF, memorial, sede)",
    "referencia": "Referência (cartório)",
    "formato": "Formato dos documentos",
}
NOMES_SITUACAO = {"ok": "ok", "falta": "falta", "impede": "impede", "conferir": "conferir",
                  "nao_se_aplica": "não se aplica"}  # fmt: skip
NOMES_TRIAGEM = {
    "rapida": "Checagem rápida",
    "completa": "Busca completa no cartório",
    "regularizacao": "Regularização da posse (ainda não há título a buscar)",
}
NOMES_ORIGEM = {
    "chega_a_origem": "chega ao título de origem",
    "falta_ler_origem": "falta ler a matrícula de origem",
    "origem_desconhecida": "origem desconhecida",
}
EXPLICACOES = {
    "Nota de 1 a 5": "parte do caminho da terra e do risco; sobe com fase que reprova, ônus grave e CAR que não "
    "bate com o SIGEF; matrícula cancelada ou divergente põe piso (raiz/regras/padroes/nota_titulo.yaml)",
    "Gravidade": "reprova segura o título até alguém resolver; confirmar pede que alguém olhe; info só informa",
    "Classes D1 a D7": "comparação de polígonos com a tolerância do INCRA (0,50 m, 3,00 m e 7,50 m): D1 e D2 dentro "
    "da tolerância, D3 a D5 sobreposição de 95%, 90% e 70% ou mais, D6 pouca sobreposição, D7 nenhuma",
    "Cadeia até a origem": "a matrícula precisa chegar ao título que tirou a terra do patrimônio público; sem isso, "
    "pede-se a certidão de origem (Lei 6.015/1973, arts. 195 e 237)",
    "Cercas": "quartis e cercas de Tukey contra o município, o cartório e o dono; fora da cerca externa pede "
    "confirmação",
    "Triagem": "checagem rápida só para título limpo pelo que se vê; o resto vai para a busca completa no cartório",
}


NOMES_RISCO = {"baixo": "baixo", "medio": "médio", "alto": "alto"}
NOMES_PARTE = {"pessoa_fisica": "pessoa física", "pessoa_juridica": "empresa", "orgao_publico": "órgão público",
               "instituicao_financeira": "banco", "espolio": "espólio",
               "desconhecido": "tipo desconhecido"}  # fmt: skip


def _num(x, casas: int = 1) -> str:
    from raiz.agentes.textos import num

    try:
        return num(float(x), casas)
    except (TypeError, ValueError):
        return "–"


def _data(x) -> str:
    if not x:
        return ""
    try:
        return dt.date.fromisoformat(str(x)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(x)


def _limpo(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return v


def _linha(f: Path | None, cod_imovel: str) -> dict:
    if f is None or not Path(f).exists():
        return {}
    df = pd.read_csv(f, dtype={"cod_imovel": str}, low_memory=False)
    x = df[df.cod_imovel == cod_imovel]
    return {k: _limpo(v) for k, v in x.iloc[0].items()} if len(x) else {}


def _cadeia_do_arquivo(pasta: Path, cod: int, cod_imovel: str) -> list[dict]:
    from raiz.documentos.certidao.regras import normalizar_cns, normalizar_matricula
    from raiz.titulo import cadeia as CA
    from raiz.titulo.regularizacao import arquivo_documentos

    fc = arquivo_documentos(pasta, cod, "matricula_conferencia")
    fa = arquivo_documentos(pasta, cod, "cadeia")
    if fc is None:
        return []
    conf = pd.read_csv(fc, dtype={"cod_imovel": str, "registro_cns": str, "registro_matricula": str})
    conf = conf[conf.cod_imovel == cod_imovel]
    tipos = {"registro_cns": str, "registro_matricula": str, "origem_matricula": str}
    cad = pd.read_csv(fa, dtype=tipos) if fa is not None else None
    res = CA.resolver(CA.matriculas(cad)) if cad is not None and len(cad) else {}
    out = []
    for r in conf.itertuples(index=False):
        cns, mat = normalizar_cns(r.registro_cns), normalizar_matricula(r.registro_matricula)
        m = dict(cns=cns, matricula=mat, conferencia=_limpo(r.situacao), atos=[])
        if cad is not None:
            g = cad[(cad.registro_cns == cns) & (cad.registro_matricula == mat) & cad.ordem.notna()]
            if len(g):
                p = g.iloc[0]
                m.update(situacao=_limpo(p.matricula_situacao), area_ha=_limpo(p.area_matricula_ha),
                         modelo=_limpo(p.modelo))  # fmt: skip
            for a in g.sort_values("ordem").itertuples(index=False):
                partes = [{"papel": "transmitente", **x} for x in json.loads(a.transmitentes_json or "[]")]
                partes += [{"papel": "adquirente", **x} for x in json.loads(a.adquirentes_json or "[]")]
                m["atos"].append(dict(numero=a.ato_numero, data=_limpo(a.data), natureza=_limpo(a.natureza),
                                      resumo=_limpo(a.resumo), cancelado_por=_limpo(a.cancelado_por),
                                      quebra=bool(a.quebra) if _limpo(a.quebra) is not None else False,
                                      partes=partes))  # fmt: skip
        if (cns, mat) in res:
            m["origem_situacao"] = res[(cns, mat)]["situacao"]
        out.append(m)
    return out


def dados(pasta: str | Path, cod: int, cod_imovel: str, con=None, base_warc: Path | None = None) -> dict:
    """Tudo o que o laudo mostra, num dicionário (também serve para a API)."""
    from raiz.titulo import warc
    from raiz.titulo.achados import COLUNAS

    pasta = Path(pasta)
    i = _linha(pasta / f"imoveis_{cod}.csv", cod_imovel)
    if not i:
        raise KeyError(f"imóvel {cod_imovel} não está em imoveis_{cod}.csv")
    i.update({k: v for k, v in _linha(pasta / f"terra_{cod}.csv", cod_imovel).items() if v is not None})
    t = _linha(pasta / f"titulo_{cod}.csv", cod_imovel)
    r = _linha(pasta / f"regularizacao_{cod}.csv", cod_imovel)
    if r.get("regularizacao_classe") in (None, "nao_se_aplica"):
        r = {}
    sede, cadeia = None, None
    if con is not None:
        from raiz.titulo import banco as TB
        from raiz.titulo import sede as SD

        achados = [dict(a._mapping) for a in TB.do_imovel(con, cod_imovel)]
        cadeia = TB.cadeia_do_imovel(con, cod_imovel)
        sede = SD.ultima(con, cod_imovel)
    else:
        f = pasta / f"achados_{cod}.csv"
        achados = []
        if f.exists():
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
            achados = [{c: (x[c] or None) for c in COLUNAS} for x in df[df.cod_imovel == cod_imovel].to_dict("records")]
    if not cadeia:
        cadeia = _cadeia_do_arquivo(pasta, cod, cod_imovel)
    grav = {"reprova": 0, "confirmar": 1, "info": 2}
    fases = []
    for fase in ORDEM_FASES:
        xs = sorted((a for a in achados if a.get("fase") == fase), key=lambda a: (grav.get(a.get("gravidade"), 3),
                                                                                  a.get("regra") or ""))  # fmt: skip
        if xs:
            fases.append((fase, xs))
    partes = i["cod_imovel"].split("-")
    i["cod_curto"] = "-".join([*partes[:2], partes[2][:4]]) if len(partes) >= 3 else i["cod_imovel"]
    versoes = [v for v in (t.get("titulo_versao"), VERSAO) if v]
    return dict(
        i=i,
        t=t,
        r=r,
        sede=sede,
        fases=fases,
        cadeia=cadeia,
        consultas=warc.consultas(cod_imovel, base_warc),
        triagem_nome=NOMES_TRIAGEM.get(t.get("titulo_triagem"), "sem triagem (rode raiz titulo recalcular)"),
        explicacoes=list(EXPLICACOES.items()),
        versoes=" · ".join(versoes),
        gerado_em=dt.date.today().strftime("%d/%m/%Y"),
    )


def html(d: dict) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(loader=FileSystemLoader(MODELOS), autoescape=select_autoescape(["html", "j2"]))
    env.globals.update(pct=lambda x: f"{float(x):.0%}".replace(".", ","), nomes_fase=NOMES_FASE,
                       nomes_situacao=NOMES_SITUACAO, nomes_origem=NOMES_ORIGEM, nomes_risco=NOMES_RISCO,
                       nomes_parte=NOMES_PARTE)  # fmt: skip
    env.filters.update(num=_num, data=_data)
    return env.get_template("laudo.html.j2").render(**d)


def gravar(pasta: str | Path, cod: int, cod_imovel: str, saida: str | Path, con=None, pdf: bool = False,
           base_warc: Path | None = None) -> dict:  # fmt: skip
    """Escreve laudo_<imóvel>.html (e o .pdf, se pedido e houver LibreOffice). Devolve os caminhos."""
    from raiz.privacidade import mascarar

    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    texto = mascarar(html(dados(pasta, cod, cod_imovel, con, base_warc)))
    f = saida / f"laudo_{cod_imovel}.html"
    f.write_text(texto, encoding="utf-8")
    out = {"html": f}
    if pdf:
        from raiz.documentos.gerados.conversao import para_pdf

        out["pdf"] = para_pdf(f, saida)
    return out
