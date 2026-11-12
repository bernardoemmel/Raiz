"""Rotas que o front espera (front/README.md, "Depois (API)"; front/compartilhado/dados/fonte-api.ts), servidas do
PostGIS que a carga do motor já preenche. Mesmo contrato da amostra: as colunas saem com os nomes dos CSV do motor
(docs/colunas.md), não com os nomes em minúsculas do banco, para as telas não saberem de onde veio o dado.

    GET /municipios                         uma linha por município (resumo da UF vigente) mais uf
    GET /municipios/{cod_ibge}/imoveis      imoveis_ + filtros_ + complementos + mb_* (404 se ainda não rodou)
    GET /imoveis/{cod_imovel}               um imóvel
    GET /imoveis/{cod_imovel}/ficha         FichaJson (front/compartilhado/dados/ficha.ts)
    GET /imoveis/{cod_imovel}/certidoes     cartório (CNS) e matrícula das parcelas SIGEF
    GET /geo/{cod_ibge}/{camada}.geojson    municipio | imoveis | ti | uc | rios
    GET /geo/{cod_ibge}/base.pmtiles        mapa base, com Range

Privacidade: coluna com cara de dado pessoal não sai, e todo texto passa pela máscara de CPF/CNPJ (a mesma de
raiz/privacidade.py). A ficha segue as regras do funil do front (front/compartilhado/dados/funil.ts), que são as do
motor: apta = sem problema, área de carbono > 0 e até 5 ha desmatados depois de 2016.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections import defaultdict
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import Engine, text

from raiz import contrato
from raiz import flag as flag_mod
from raiz import motivos as motivos_mod
from raiz import restauracao as restauracao_mod
from raiz import terra as terra_mod
from raiz import terra_publica as terra_publica_mod
from raiz.busca import normalizar_codigo, normalizar_nome
from raiz.privacidade import colunas_pessoais, mascarar

# nome no banco (minúsculo) -> nome no CSV do motor
_ORIGINAL = {
    contrato.coluna_banco(k): k
    for d in (contrato.IMOVEIS, contrato.FILTROS, contrato.RESUMO, contrato.CERTIDOES)
    for k in d
}
_INTERNAS = {"rodada_id", "atributos", "bloco", "data_corte", "motor_versao", "regras_versao"}
SIMPLIFICAR_GRAUS = 0.00002  # a mesma tolerância de front/scripts/geo.py para os polígonos do CAR


# só texto com número de cara de documento passa pela máscara completa (mesma ideia do limpar() do front)
_TALVEZ_DOC = re.compile(r"\d{11}|\d{3}\.\d{3}|[0-9A-Z]{2}\.[0-9A-Z]{3}\.|[0-9A-Z]{12}\d{2}")


@lru_cache(maxsize=4096)
def _pessoal(coluna: str, permitir: tuple[str, ...]) -> bool:
    return bool(colunas_pessoais([coluna], permitir=permitir))


def _valor(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, str):
        return mascarar(v) if _TALVEZ_DOC.search(v) else v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _limpa(d: dict, permitir: tuple[str, ...] = ()) -> dict:
    return {k: _valor(v) for k, v in d.items() if not _pessoal(k, permitir)}


def _json(dado) -> Response:
    """JSON direto (sem o codificador genérico do FastAPI, lento em listas de 10 mil imóveis)."""
    return Response(json.dumps(dado, ensure_ascii=False, separators=(",", ":")), media_type="application/json")


def _linha_banco(m: dict, faltando: set[str] = frozenset()) -> dict:
    """Linha tipada do banco nos nomes do CSV, mais os atributos (colunas sem contrato, já com o nome original).
    Coluna do contrato que não veio no arquivo do motor não aparece (como no CSV)."""
    out = {}
    for k, v in m.items():
        if k in _INTERNAS:
            continue
        nome = _ORIGINAL.get(k, k)
        if nome in faltando:
            continue
        out[nome] = v
    out.update(m.get("atributos") or {})
    return out


def _faltando(con, rodadas: set[int]) -> dict[int, set[str]]:
    if not rodadas:
        return {}
    rs = con.execute(
        text("select id, colunas_faltando from funil.rodada where id = any(:ids)"), {"ids": list(rodadas)}
    ).all()
    return {r.id: {c.split(".", 1)[1] for c in r.colunas_faltando if "." in c} for r in rs}


def imoveis_do_municipio(engine: Engine, cod_ibge: int | None = None, cod_imovel: str | None = None) -> list[dict]:
    """Uma linha por imóvel, como o front monta da amostra: complementos primeiro, a linha principal ganha.
    O imóvel é achado pelo código normalizado (com ou sem pontos e traços, em qualquer caixa)."""
    if cod_imovel is not None:
        filtro, par = "v.cod_busca = :b", {"b": normalizar_codigo(cod_imovel)}
    else:
        filtro, par = "v.cod_municipio_ibge = :c", {"c": cod_ibge}
    with engine.connect() as con:
        principais = [
            dict(r._mapping)
            for r in con.execute(
                text(f"""select r.*, v.rodada_id as _rodada from funil.vigente v
                         join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                         where {filtro} order by v.cod_imovel"""),
                par,
            )
        ]
        if not principais:
            return []
        rodadas = {p["rodada_id"] for p in principais}
        cods = [p["cod_imovel"] for p in principais]
        faltando = _faltando(con, rodadas)
        comp: dict[str, dict] = defaultdict(dict)
        par = {"r": list(rodadas), "cs": cods}
        for r in con.execute(
            text("select * from funil.filtro_imovel where rodada_id = any(:r) and cod_imovel = any(:cs)"), par
        ):
            comp[r.cod_imovel].update(_linha_banco(dict(r._mapping)))
        for r in con.execute(
            text("""select cod_imovel, atributos from funil.complemento_imovel
                    where rodada_id = any(:r) and cod_imovel = any(:cs) order by tipo"""),
            par,
        ):
            comp[r.cod_imovel].update(r.atributos or {})
        for r in con.execute(
            text("""select cod_imovel, indicador, ano, valor_num, valor_texto from funil.mapbiomas_imovel
                    where rodada_id = any(:r) and cod_imovel = any(:cs)"""),
            par,
        ):
            v = r.valor_num if r.valor_texto is None else r.valor_texto
            comp[r.cod_imovel][contrato.coluna_mb(r.indicador, r.ano)] = v
    out = []
    for p in principais:
        p.pop("_rodada", None)
        linha = dict(comp.get(p["cod_imovel"], {}))
        linha.update(_linha_banco(p, faltando.get(p["rodada_id"], set())))
        out.append(_limpa(linha))
    return out


def versao(engine: Engine, cod_imovel: str) -> dict | None:
    """De qual rodada vem o dado do imóvel (as rodadas antigas do município continuam guardadas)."""
    with engine.connect() as con:
        r = con.execute(
            text("""select ro.id, ro.data_corte, ro.carregada_em, ro.motor_versao, ro.regras_versao, ro.origem,
                           (select count(*) from funil.rodada x where x.tipo = 'municipio'
                            and x.cod_municipio = ro.cod_municipio) as rodadas_do_municipio
                    from funil.vigente v join funil.rodada ro on ro.id = v.rodada_id where v.cod_busca = :b"""),
            {"b": normalizar_codigo(cod_imovel)},
        ).first()
    if r is None:
        return None
    return {
        "rodada": r.id,
        "data_corte": r.data_corte.isoformat(),
        "carregada_em": r.carregada_em.isoformat(),
        "motor_versao": r.motor_versao,
        "regras_versao": r.regras_versao,
        "rodadas_do_municipio": r.rodadas_do_municipio,
    }


SELOS = {"bronze": "achada no CAR", "prata": "título conferido ou concessão", "ouro": "dono aceitou"}


def do_banco(engine: Engine, cod_imovel: str) -> dict:
    """O que só o banco sabe do imóvel: código curto, aceite do dono, data do dado e série de uso."""
    with engine.connect() as con:
        r = con.execute(
            text("""select k.codigo, a.estado, ro.data_corte from funil.vigente v
                    join funil.rodada ro on ro.id = v.rodada_id
                    left join negocio.codigo_curto k on k.cod_imovel = v.cod_imovel
                    left join negocio.aceite a on a.cod_imovel = v.cod_imovel
                    where v.cod_imovel = :c"""),
            {"c": cod_imovel},
        ).first()
        serie = con.execute(
            text("""select ano, mata_pct, pasto_pct, lavoura_pct, agua_pct, colecao from funil.serie_uso
                    where cod_imovel = :c order by ano"""),
            {"c": cod_imovel},
        ).all()
    return {
        "codigo_curto": r.codigo if r else None,
        "aceite": r.estado if r else None,
        "data_corte": r.data_corte.isoformat() if r and r.data_corte else None,
        "serie_uso": {
            "anos": [x.ano for x in serie],
            "mata_pct": [x.mata_pct for x in serie],
            "pasto_pct": [x.pasto_pct for x in serie],
            "lavoura_pct": [x.lavoura_pct for x in serie],
            "agua_pct": [x.agua_pct for x in serie],
            "fonte": f"MapBiomas ({serie[0].colecao})" if serie else None,
        }
        if serie
        else None,
    }


def selo_e_etapa(linha: dict, banco: dict) -> tuple[str, str | None]:
    """Selo: bronze (achada no CAR), prata (título conferido), ouro (dono aceitou). A etapa do funil vem da ficha
    do motor e sobe para "aceite" quando o dono aceita."""
    etapa = linha.get("etapa_funil")
    if banco.get("aceite") == "aceito":
        return "ouro", "aceite"
    if terra_mod.selo_prata(linha):  # prata só para matrícula conferida ou terra pública sob concessão
        return "prata", etapa
    return "bronze", etapa


def nao_achado(engine: Engine, cod_imovel: str) -> dict:
    """Corpo do 404: diz o que se sabe do código (município conhecido? já processado?), nunca uma resposta vazia."""
    b = normalizar_codigo(cod_imovel)
    out = {"cod_imovel": cod_imovel, "codigo_normalizado": b, "achado": False}
    m = re.match(r"^([A-Z]{2})(\d{7})", b)
    if not m:
        out["mensagem"] = "Código do CAR fora do formato UF-municipio-código (ex.: PA-1504950-0016...)."
        return out
    with engine.connect() as con:
        mun = con.execute(
            text("select cod_ibge, municipio, uf, imoveis from funil.municipio_busca where cod_ibge = :c"),
            {"c": int(m.group(2))},
        ).first()
    if mun is None:
        out["mensagem"] = "O município deste código ainda não foi processado pelo motor da Raíz."
    elif not mun.imoveis:
        out["municipio"] = {"cod_ibge": str(mun.cod_ibge), "municipio": mun.municipio, "uf": mun.uf}
        out["mensagem"] = f"{mun.municipio} ({mun.uf}) ainda não teve os imóveis processados pelo motor."
    else:
        out["municipio"] = {"cod_ibge": str(mun.cod_ibge), "municipio": mun.municipio, "uf": mun.uf}
        out["mensagem"] = (
            f"O motor processou {mun.municipio} ({mun.uf}), mas este imóvel não está na saída: pode estar cancelado, "
            "não ser imóvel rural (IRU) ou o código pode estar errado."
        )
    return out


# --- regras do funil do front (front/compartilhado/dados/funil.ts), em raiz/motivos.py ---------------------------


def ler_imovel(linha: dict) -> dict:
    """ha, carbono_ha e apta, com as mesmas regras de lerImovel do front."""
    return motivos_mod.ler(linha)


def mediana(xs: list[float]) -> float:
    if not xs:
        return 0
    s = sorted(xs)
    m = len(s) >> 1
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _arredonda_js(x: float) -> int:
    return math.floor(x + 0.5)  # Math.round do JavaScript (meio sobe), não o arredondamento bancário do Python


def polyline(pontos: list[tuple[float, float]], casas: int = 6) -> str:
    """Mesmo algoritmo de front/compartilhado/polyline.ts (pares [lon, lat], 6 casas)."""
    fator = 10**casas
    saida, lat0, lon0 = [], 0, 0

    def parte(v: int) -> str:
        n = ~(v << 1) if v < 0 else v << 1
        s = []
        while n >= 0x20:
            s.append(chr((0x20 | (n & 0x1F)) + 63))
            n >>= 5
        s.append(chr(n + 63))
        return "".join(s)

    for lon, lat in pontos:
        la, lo = _arredonda_js(lat * fator), _arredonda_js(lon * fator)
        saida.append(parte(la - lat0) + parte(lo - lon0))
        lat0, lon0 = la, lo
    return "".join(saida)


def _aneis_externos(geojson: dict | None) -> list[list[tuple[float, float]]]:
    if not geojson:
        return []
    if geojson["type"] == "Polygon":
        return [geojson["coordinates"][0]]
    if geojson["type"] == "MultiPolygon":
        return [p[0] for p in geojson["coordinates"]]
    return []


_COLUNAS_CONTEXTO = (
    "rodada_id, ha, area, carbono_ha, alem_rl_ha, problema, embargo_ha, ti_ha, desm_pos2020_ha, "
    "alerta_pos2020_ha, desm_pos2016_ha"
)


def linhas_para_contexto(engine: Engine, cod_ibge: int) -> list[dict]:
    """Só as colunas que o contexto da ficha usa, de todos os imóveis do município (rápido em São Félix)."""
    with engine.connect() as con:
        rs = [
            dict(r._mapping)
            for r in con.execute(
                text(f"select {_COLUNAS_CONTEXTO} from funil.resultado_vigente where cod_municipio_ibge = :c"),
                {"c": cod_ibge},
            )
        ]
        faltando = _faltando(con, {r["rodada_id"] for r in rs})
    return [_linha_banco(r, faltando.get(r["rodada_id"], set())) for r in rs]


def montar_ficha(
    alvo: dict, todos: list[dict], geometria: dict | None, versao_dado: dict | None = None, banco: dict | None = None
) -> dict:
    """FichaJson: a linha, o contexto do município e o perímetro em polyline (front/compartilhado/dados/ficha.ts).
    A mais, para qualquer cliente: situacao (apta ou não, e por quê), motivos item por item e versao_dado (rodada)."""
    lidos = [ler_imovel(i) for i in todos]
    eu = ler_imovel(alvo)
    meu = eu["carbono_ha"] if eu["apta"] else 0
    carbonos = [x["carbono_ha"] if x["apta"] else 0 for x in lidos]
    aneis = _aneis_externos(geometria)
    xs = [p[0] for a in aneis for p in a]
    ys = [p[1] for a in aneis for p in a]
    n = len(todos)
    return {
        "versao": 1,
        "imovel": alvo,
        "contexto": {
            "cod_ibge": str(alvo.get("cod_municipio_ibge") or ""),
            "municipio": alvo.get("municipio") or "",
            "uf": alvo.get("uf") or "",
            "n_imoveis": n,
            "posicao_carbono": sum(c < meu for c in carbonos) / n if n else 0,
            "mediana_carbono_ha_aptas": mediana([x["carbono_ha"] for x in lidos if x["apta"]]),
            "mediana_ha": mediana([x["ha"] for x in lidos]),
        },
        "perimetro": [polyline(a) for a in aneis] if aneis else None,
        "caixa": [min(xs), min(ys), max(xs), max(ys)] if xs else None,
        "situacao": motivos_mod.situacao(alvo),
        "motivos": motivos_mod.motivos(alvo),
        # meta FLAG (GHG LSR v1.1) separada de crédito/compensação, com requisitos e versão da regra
        "flag": flag_mod.bloco_ficha(alvo),
        # caminho da terra (não corta): caminho, risco, aviso do que falta e base legal
        "caminho_terra": terra_mod.bloco_ficha(alvo),
        # valor para quem restaura com crédito de carbono (estimativa em faixa P10-P90, sempre com aviso)
        "para_quem_restaura": restauracao_mod.bloco_ficha(alvo),
        **_do_design_v1(alvo, banco or {}),
        "versao_dado": versao_dado,
    }


def _do_design_v1(alvo: dict, banco: dict) -> dict:
    """Campos do design v1 do front que dependem do banco ou viram lista (docs/design/dados-para-o-front-v1.md)."""
    selo, etapa = selo_e_etapa(alvo, banco)
    return {
        "codigo_curto": banco.get("codigo_curto"),
        "nivel_selo": selo,
        "nivel_selo_texto": SELOS[selo],
        "etapa_funil": etapa,
        "criterios_aptidao": motivos_mod.criterios(alvo, banco.get("data_corte")),
        "serie_uso": banco.get("serie_uso"),
    }


# --- busca --------------------------------------------------------------------------------------------------------

_COLUNAS_SITUACAO = (
    "r.rodada_id, r.cod_imovel, r.municipio, r.status_imovel, r.ha, r.area, r.carbono_ha, r.alem_rl_ha, r.problema, "
    "r.embargo_ha, r.ti_ha, r.desm_pos2020_ha, r.alerta_pos2020_ha, r.desm_pos2016_ha, r.f_matricula, "
    "r.matricula_ha, r.frente, r.assentamento_ha, r.pasto_ate1km_ha, r.uc_ha, r.deficit_rl_ha, r.pct_rl, "
    "r.app_desmatada_ha, r.app_recompor_ha"
)


UFS = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul", "MT": "Mato Grosso", "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí",
    "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia", "RR": "Roraima",
    "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo", "TO": "Tocantins",
}  # fmt: skip
MAX_IMOVEIS = MAX_MUNICIPIOS = 8
_CAR = re.compile(r"^([A-Z]{2})-?(\d{0,7})(?:-?([0-9A-F]{0,32}))?$")


def normalizar_car(q: str) -> str | None:
    """Como normalizarCar do front: "pa 1507300 f293.cd17" vira "PA-1507300-F293CD17"."""
    s = re.sub(r"[\s.]", "", q.upper())
    m = _CAR.match(s)
    if not m:
        return None
    uf, mun, cauda = m.group(1), m.group(2), m.group(3) or ""
    if not mun:
        return uf + "-"
    if len(mun) < 7:
        return f"{uf}-{mun}"
    return f"{uf}-{mun}-{cauda}"


def buscar(engine: Engine, q: str, limite: int = MAX_IMOVEIS) -> dict:
    """GET /busca?q= com o contrato de front/compartilhado/dados/busca.ts (que é a especificação): tipo, situacao,
    mensagem pronta, até 8 imóveis (maior área de carbono primeiro) e até 8 municípios."""
    q = (q or "").strip()

    def vazia(tipo: str, situacao: str, mensagem: str, municipios=None) -> dict:
        return {"q": q, "tipo": tipo, "situacao": situacao, "mensagem": mensagem, "imoveis": [],
                "municipios": municipios or []}  # fmt: skip

    def mun(m) -> dict:
        carregados = m.imoveis or 0
        return {
            "cod_ibge": str(m.cod_ibge),
            "municipio": m.municipio,
            "uf": m.uf,
            "imoveis": carregados or (m.imoveis_resumo or 0),
            "tem_imoveis": carregados > 0,
        }

    with engine.connect() as con:
        ufs = [u for (u,) in con.execute(text("select distinct uf from funil.municipio_busca order by uf"))]
        nomes_ufs = ", ".join(UFS.get(u, u) for u in ufs) or "nenhum"
        if re.match(r"^[A-Za-z]{2}\s*-?\s*\d", q):
            cod = normalizar_car(q)
            uf = q[:2].upper()
            if uf not in UFS:
                return vazia(
                    "car",
                    "formato_invalido",
                    f'"{uf}" não é sigla de estado. O código do CAR começa assim: PA-1507300-…',
                )
            if not cod:
                return vazia(
                    "car",
                    "formato_invalido",
                    "Código do CAR fora do formato. Ele tem a sigla do estado, os 7 números do município e 32 letras e "
                    "números, por exemplo PA-1507300-F293CD17…",
                )
            if uf not in ufs:
                return vazia(
                    "car",
                    "estado_nao_processado",
                    f"{UFS[uf]} ainda não foi processado pela Raíz. Por enquanto: {nomes_ufs}.",
                )
            if len(cod) < 10:
                return vazia("car", "curta", "Continue digitando: depois da sigla vêm os 7 números do município.")
            completo = len(cod) == 43
            b = normalizar_codigo(cod)
            linhas = [
                dict(x._mapping)
                for x in con.execute(
                    text(f"""select v.uf as _uf, v.cod_municipio_ibge as _cod_ibge, {_COLUNAS_SITUACAO}
                             from funil.vigente v
                             join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                             where {"v.cod_busca = :b" if completo else "v.cod_busca like :p"}
                             order by r.carbono_ha desc nulls last, v.cod_busca limit :n"""),
                    {"b": b, "p": b + "%", "n": limite},
                )
            ]
            if linhas:
                faltando = _faltando(con, {x["rodada_id"] for x in linhas})
                imoveis = []
                for x in linhas:
                    linha = _linha_banco(x, faltando.get(x["rodada_id"], set()))
                    sit = motivos_mod.situacao(linha)
                    lido = motivos_mod.ler(linha)
                    imoveis.append(
                        {
                            "cod_imovel": x["cod_imovel"],
                            "municipio": x["municipio"],
                            "cod_ibge": str(x["_cod_ibge"]),
                            "uf": x["_uf"],
                            "ha": lido["ha"],
                            "carbono_ha": lido["carbono_ha"],
                            "apta": lido["apta"],
                            "categoria": sit["categoria"],
                            "porque_nao_apta": sit["porque_nao_apta"],  # a mais: o motivo, item por item
                        }
                    )
                return {"q": q, "tipo": "car", "situacao": "ok", "mensagem": None, "imoveis": imoveis, "municipios": []}
            cod_mun = cod[3:10]
            m = con.execute(
                text("select * from funil.municipio_busca where cod_ibge = :c"), {"c": int(cod_mun)}
            ).first()
            if m is not None and not m.imoveis:
                return vazia(
                    "car",
                    "municipio_sem_imoveis",
                    f"{m.municipio} ({m.uf}) já tem o funil do município, mas os imóveis por fazenda ainda não foram "
                    "processados. Este código aparece quando forem.",
                    [mun(m)],
                )
            if m is None:
                return vazia(
                    "car",
                    "nao_encontrado",
                    f"Nenhum município de {UFS[uf]} com o código {cod_mun} nos dados da Raíz. Confira os 7 números "
                    "depois da sigla.",
                )
            return vazia(
                "car",
                "nao_encontrado",
                f"Nenhum imóvel com este código em {m.municipio}. Pode ser CAR cancelado, de assentamento coletivo ou "
                "terra indígena (a Raíz só analisa imóvel rural), ou um erro de digitação."
                if completo
                else f"Nenhum código de {m.municipio} começa assim. Confira as letras e números depois do município.",
            )
        t = normalizar_nome(q)
        if len(t) < 3:
            return vazia("texto", "curta", "Digite pelo menos 3 letras do município ou o começo do código do CAR.")
        ms = con.execute(
            text("""select * from funil.municipio_busca
                    where nome_busca like :meio or cast(cod_ibge as text) = :t
                    order by (cast(cod_ibge as text) = :t) desc, (nome_busca like :inicio) desc,
                             greatest(imoveis, coalesce(imoveis_resumo, 0)) desc, municipio
                    limit :n"""),
            {"meio": f"%{t}%", "inicio": f"{t}%", "t": t, "n": MAX_MUNICIPIOS},
        ).all()
        if not ms:
            return vazia(
                "texto",
                "nao_encontrado",
                f'Nenhum município com "{q}" nos estados processados ({nomes_ufs}). Para um imóvel, digite o código do '
                "CAR.",
            )
        return {"q": q, "tipo": "texto", "situacao": "ok", "mensagem": None, "imoveis": [],
                "municipios": [mun(m) for m in ms]}  # fmt: skip


_TRAVAS: dict[str, object] = {}


def _imagem(engine: Engine, cod_imovel: str, tipo: str) -> tuple[dict, object]:
    """Metadados e arquivo da imagem; gera na hora se ainda não existe (uma geração por imóvel de cada vez)."""
    import threading

    import shapely

    from raiz import satelite

    if tipo not in satelite.TIPOS:
        raise HTTPException(404, f"imagem desconhecida: {tipo} (há {', '.join(satelite.TIPOS)})")
    b = normalizar_codigo(cod_imovel)
    meta = satelite.metadados(b).get(tipo)
    f = satelite.pasta() / b / f"{tipo}.webp"
    if meta and f.exists():
        return meta, f
    with engine.connect() as con:
        g = con.execute(
            text("""select ST_AsBinary(i.geom),
                           (select ST_AsBinary(ST_Union(c.geom)) from geo.camada_imovel c
                            where c.cod_imovel = v.cod_imovel and c.camada = 'pode_voltar')
                    from funil.vigente v join funil.imovel i on i.cod_imovel = v.cod_imovel
                    where v.cod_busca = :b and i.geom is not null"""),
            {"b": b},
        ).first()
    if g is None:
        corpo = nao_achado(engine, cod_imovel)
        if imoveis_do_municipio(engine, cod_imovel=cod_imovel):
            corpo = {**corpo, "achado": True, "mensagem": "Este imóvel ainda não tem o polígono carregado."}
        raise HTTPException(404, corpo)
    trava = _TRAVAS.setdefault(b, threading.Lock())
    with trava:
        meta = satelite.metadados(b).get(tipo)
        if not (meta and f.exists()):
            geom = shapely.from_wkb(bytes(g[0]))
            pv = shapely.from_wkb(bytes(g[1])) if g[1] is not None else None
            try:
                satelite.gerar(b, geom, pv, tipos=[tipo])
            except LookupError as ex:
                raise HTTPException(404, {"mensagem": f"Sem imagem de satélite boa para esta fazenda: {ex}."}) from ex
            meta = satelite.metadados(b)[tipo]
    return meta, f


def arquivo_camadas(engine: Engine, cod_ibge: int):
    """camadas_<mun>.pmtiles na pasta saida/<UF>/ do motor (a UF vem da tabela de municípios)."""
    from raiz.funil.rodar import dir_trabalho

    with engine.connect() as con:
        uf = con.execute(text("select uf from funil.municipio_busca where cod_ibge = :c"), {"c": cod_ibge}).scalar()
    if not uf:
        return None
    f = dir_trabalho() / "saida" / uf / f"camadas_{int(cod_ibge)}.pmtiles"
    return f if f.exists() else None


# --- rotas --------------------------------------------------------------------------------------------------------


def roteador(engine_de) -> APIRouter:
    """engine_de(request) devolve o Engine (o da aplicação)."""
    r = APIRouter()

    @r.get("/municipios")
    def municipios(request: Request) -> list[dict]:
        eng = engine_de(request)
        with eng.connect() as con:
            linhas = con.execute(
                text("""
                select ro.uf, m.* from funil.resumo_municipio m
                join funil.rodada ro on ro.id = m.rodada_id
                where ro.id in (select distinct on (uf) id from funil.rodada where tipo = 'resumo_uf'
                                order by uf, data_corte desc, id desc)
                order by ro.uf, m.cod_ibge""")
            ).all()
        out = []
        for x in linhas:
            m = dict(x._mapping)
            d = _linha_banco(m)
            d["uf"] = m["uf"]
            out.append(_limpa(d))
        return out

    @r.get("/municipios/{cod_ibge}")
    def municipio(cod_ibge: int, request: Request) -> Response:
        """Frase-resumo, funil por etapa e por porte com os maiores motivos de saída, desde a última análise e área
        urbana da sede (design v1 do front, item 4)."""
        from raiz import municipio_dados

        d = municipio_dados.dados(engine_de(request), cod_ibge)
        if d is None:
            raise HTTPException(404, {"mensagem": "Município ainda não processado pela Raíz."})
        return _json(d)

    @r.get("/municipios/{cod_ibge}/urbana.geojson")
    def urbana(cod_ibge: int, request: Request) -> Response:
        """Contorno da área urbanizada da sede (MapBiomas), para comparar o tamanho das fazendas."""
        with engine_de(request).connect() as con:
            fc = con.execute(
                text("""select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                            json_build_object('type', 'Feature', 'properties', propriedades,
                                              'geometry', ST_AsGeoJSON(geom, 6)::json)), '[]'::json))
                        from geo.camada where cod_ibge = :c and camada = 'urbana'"""),
                {"c": cod_ibge},
            ).scalar()
        if not fc or not fc["features"]:
            raise HTTPException(404, {"mensagem": "Contorno urbano ainda não gerado (raiz municipio urbana)."})
        return Response(json.dumps(fc, separators=(",", ":")), media_type="application/geo+json")

    @r.get("/municipios/{cod_ibge}/imoveis")
    def imoveis(
        cod_ibge: int,
        request: Request,
        ordem: str | None = None,
        modo: str | None = None,
        tir_min: float | None = None,
        so_lote_fecha: bool = False,
    ) -> Response:
        """Imóveis do município. Para o painel de quem restaura: ordem=valor_desenvolvedor (ou vpl_ha,
        tir_alavancada, credito), filtro por modo de restauração, TIR com financiamento mínima (P50, em %) e só os
        lotes que fecham o contrato de referência. Sem parâmetros, a lista de sempre."""
        lista = imoveis_do_municipio(engine_de(request), cod_ibge=cod_ibge)
        if not lista:
            raise HTTPException(404, "município ainda sem imóveis carregados")
        try:
            lista = restauracao_mod.ordenar_filtrar(lista, ordem, modo, tir_min, so_lote_fecha)
        except ValueError as ex:
            raise HTTPException(422, {"mensagem": str(ex)}) from ex
        return _json(lista)

    @r.get("/municipios/{cod_ibge}/lotes")
    def lotes(cod_ibge: int, request: Request) -> Response:
        """Lotes de fazendas vizinhas para quem restaura: quantos ha e créditos cada lote fecha."""
        lista = imoveis_do_municipio(engine_de(request), cod_ibge=cod_ibge)
        if not lista:
            raise HTTPException(404, "município ainda sem imóveis carregados")
        return _json(restauracao_mod.lotes(lista))

    @r.get("/terra-publica")
    def terra_publica(
        request: Request, uf: str, ordem: str = "desmatado", so_com_concessao: bool = False, limite: int = 200
    ) -> Response:
        """Terra pública para restaurar no estado: glebas não destinadas e UC de uso sustentável de domínio público,
        com hectares desmatados, custo, captura e crédito líquido estimados e a concessão ou edital (data e link)."""
        colunas = {"desmatado": "desmatado_ha", "credito": "credito_liquido_tco2_ano", "area": "ha"}
        if ordem not in colunas:
            raise HTTPException(422, {"mensagem": f"ordem desconhecida: {ordem} (use {', '.join(colunas)})"})
        with engine_de(request).connect() as con:
            linhas = [
                {k: (float(v) if hasattr(v, "is_finite") else v) for k, v in dict(x._mapping).items()}
                for x in con.execute(
                    text(f"""select {", ".join(c for c in terra_publica_mod.COLUNAS_BANCO)},
                                    round(ST_Y(ST_PointOnSurface(geom))::numeric, 5) as lat,
                                    round(ST_X(ST_PointOnSurface(geom))::numeric, 5) as lon
                             from geo.terra_publica where uf = :u
                               and (not :so or concessao is not null)
                             order by {colunas[ordem]} desc nulls last limit :n"""),
                    {"u": uf.upper(), "so": so_com_concessao, "n": max(1, min(limite, 2000))},
                )
            ]
        if not linhas:
            msg = f"Terra pública de {uf.upper()} ainda não gerada (raiz terra publica)."
            raise HTTPException(404, {"mensagem": msg})
        return _json({"uf": uf.upper(), "aviso": restauracao_mod.regra()["aviso"], "areas": linhas,
                      "regra": terra_mod.regra()["caminhos"]["publica_sem_destinacao"]["aviso"]})  # fmt: skip

    @r.get("/restauracao/cenarios")
    def cenarios_restauracao() -> Response:
        """Cenários do fluxo de caixa (ProFloresta+...), cada parâmetro com a fonte, para o simulador."""
        return _json(restauracao_mod.cenarios_publicos())

    @r.get("/imoveis/{cod_imovel}/restauracao/simular")
    def simular_restauracao(cod_imovel: str, request: Request) -> Response:
        """Refaz o valor para quem restaura com os parâmetros do cenário editados (preco_usd_t, prazo_anos,
        entregas_anos=7,12,17, fracao_financiada, juros_ano, carencia_anos, amortizacao_anos, taxa_desconto,
        cambio_brl_usd, manutencao_rs_ha_ano, arrendamento_rs_ha_ano...), com o fluxo ano a ano."""
        eng = engine_de(request)
        alvo = imoveis_do_municipio(eng, cod_imovel=cod_imovel)
        if not alvo:
            raise HTTPException(404, nao_achado(eng, cod_imovel))
        try:
            nome, muda = restauracao_mod.parametros_da_consulta(dict(request.query_params))
            return _json(restauracao_mod.simular(alvo[0], nome, **muda))
        except ValueError as ex:
            raise HTTPException(422, {"mensagem": str(ex)}) from ex

    @r.post("/imoveis/{cod_imovel}/restauracao/real")
    async def restauracao_real(cod_imovel: str, request: Request) -> Response:
        """O cliente informa custo e captura reais: vira gabarito para comparar com o que a Raíz previu."""
        from raiz import restauracao_aprendizado as RA

        eng = engine_de(request)
        alvo = imoveis_do_municipio(eng, cod_imovel=cod_imovel)
        if not alvo:
            raise HTTPException(404, nao_achado(eng, cod_imovel))
        try:
            b = await request.json()
            if not isinstance(b, dict) or not str(b.get("fonte") or "").strip():
                raise ValueError("informe a fonte (quem mediu: desenvolvedor, parcela, nota fiscal)")
            quando = dt.date.fromisoformat(b["observado_em"]) if b.get("observado_em") else dt.date.today()
            with eng.begin() as con:
                ids = RA.informar(con, alvo[0]["cod_imovel"], quando, str(b["fonte"])[:200],
                                  custo_rs_ha=b.get("custo_rs_ha"), captura_tco2_ha_ano=b.get("captura_tco2_ha_ano"),
                                  credito_liquido_tco2_ha_ano=b.get("credito_liquido_tco2_ha_ano"),
                                  modo=b.get("modo"), referencia=b.get("referencia"))  # fmt: skip
        except (ValueError, TypeError, KeyError) as ex:
            raise HTTPException(422, {"mensagem": str(ex)}) from ex
        return _json({"gravados": len(ids), "observado_em": quando.isoformat()})

    @r.get("/imoveis/{cod_imovel}")
    def imovel(cod_imovel: str, request: Request) -> Response:
        eng = engine_de(request)
        lista = imoveis_do_municipio(eng, cod_imovel=cod_imovel)
        if not lista:
            raise HTTPException(404, nao_achado(eng, cod_imovel))
        linha = lista[0]
        banco = do_banco(eng, linha["cod_imovel"])
        selo, etapa = selo_e_etapa(linha, banco)
        linha.update(codigo_curto=banco["codigo_curto"], nivel_selo=selo, etapa_funil=etapa)
        return _json(linha)

    @r.get("/imoveis/{cod_imovel}/ficha")
    def ficha(cod_imovel: str, request: Request) -> Response:
        eng = engine_de(request)
        alvo = imoveis_do_municipio(eng, cod_imovel=cod_imovel)
        if not alvo:
            raise HTTPException(404, nao_achado(eng, cod_imovel))
        cod_ibge = alvo[0].get("cod_municipio_ibge")
        todos = linhas_para_contexto(eng, int(cod_ibge)) if cod_ibge else alvo
        cod = alvo[0]["cod_imovel"]  # o código como está no banco (o pedido pode vir sem traços ou em minúsculas)
        with eng.connect() as con:
            g = con.execute(
                text("""select ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :t), 6) from funil.imovel
                        where cod_imovel = :c and geom is not null"""),
                {"c": cod, "t": SIMPLIFICAR_GRAUS},
            ).scalar()
        banco = do_banco(eng, cod)
        return _json(montar_ficha(alvo[0], todos, json.loads(g) if g else None, versao(eng, cod), banco))

    @r.get("/imoveis/{cod_imovel}/flag/simular")
    def simular_flag(
        cod_imovel: str, request: Request, silvipastoril_ha: float = 0.0, cacau_ha: float = 0.0
    ) -> Response:
        """Simulador: hectares escolhidos para a meta FLAG; o resto fica para crédito ou compensação, sem somar."""
        eng = engine_de(request)
        alvo = imoveis_do_municipio(eng, cod_imovel=cod_imovel)
        if not alvo:
            raise HTTPException(404, nao_achado(eng, cod_imovel))
        return _json(flag_mod.simular(alvo[0], silvipastoril_ha, cacau_ha))

    @r.get("/imoveis/{cod_imovel}/camadas.geojson")
    def camadas_imovel(cod_imovel: str, request: Request) -> Response:
        """Mata em pé, área que pode voltar a ser mata, pasto, lavoura, água e APP dentro do imóvel."""
        eng = engine_de(request)
        with eng.connect() as con:
            fc = con.execute(
                text("""
                select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                    json_build_object('type', 'Feature',
                        'properties', json_build_object('camada', c.camada, 'ha', c.ha),
                        'geometry', ST_AsGeoJSON(c.geom, 6)::json) order by c.camada), '[]'::json))
                from funil.vigente v join geo.camada_imovel c on c.cod_imovel = v.cod_imovel
                where v.cod_busca = :b"""),
                {"b": normalizar_codigo(cod_imovel)},
            ).scalar()
        if not fc or not fc["features"]:
            corpo = nao_achado(eng, cod_imovel)
            if imoveis_do_municipio(eng, cod_imovel=cod_imovel):
                corpo = {**corpo, "achado": True, "mensagem": "As camadas deste imóvel ainda não foram geradas."}
            raise HTTPException(404, corpo)
        return Response(json.dumps(fc, separators=(",", ":")), media_type="application/geo+json")

    @r.get("/geo/{cod_ibge}/camadas.pmtiles")
    def camadas_municipio(cod_ibge: int, request: Request) -> Response:
        """PMTiles do município (contorno dos imóveis e camadas dentro deles), com Range."""
        f = arquivo_camadas(engine_de(request), cod_ibge)
        if f is None:
            raise HTTPException(404, "camadas do município ainda não geradas (raiz ficha gerar)")
        return FileResponse(f, media_type="application/vnd.pmtiles")

    @r.get("/imoveis/{cod_imovel}/imagem/{tipo}.webp")
    def imagem(cod_imovel: str, tipo: str, request: Request) -> Response:
        """Satélite da fazenda (Sentinel-2 hoje, Landsat 1985 e 2008), gerado na primeira vez e guardado."""
        meta, f = _imagem(engine_de(request), cod_imovel, tipo)
        return FileResponse(
            f,
            media_type="image/webp",
            headers={
                "X-Raiz-Data-Cena": meta["data_cena"],
                "X-Raiz-Satelite": meta["satelite"],
                "X-Raiz-Credito": meta["credito"],
                "Cache-Control": "private, max-age=86400",
            },
        )

    @r.get("/imoveis/{cod_imovel}/imagem/{tipo}.json")
    def imagem_meta(cod_imovel: str, tipo: str, request: Request) -> Response:
        """Data da cena, satélite, frase de crédito, recorte (lon/lat), tamanho e peso da imagem."""
        meta, _ = _imagem(engine_de(request), cod_imovel, tipo)
        return _json(meta)

    @r.get("/imoveis/{cod_imovel}/certidoes")
    def certidoes(cod_imovel: str, request: Request) -> list[dict]:
        with engine_de(request).connect() as con:
            linhas = con.execute(
                text("""select c.* from funil.vigente v
                        join titulo.certidao_alvo c on c.cod_imovel = v.cod_imovel and c.rodada_id = v.rodada_id
                        where v.cod_busca = :b order by c.registro_cns, c.registro_matricula"""),
                {"b": normalizar_codigo(cod_imovel)},
            ).all()
        return [_limpa(_linha_banco(dict(x._mapping))) for x in linhas]

    @r.get("/busca")
    def busca(request: Request, q: str = "", limite: int = 8) -> Response:
        """Código do CAR (inteiro ou começo, com ou sem pontos e traços) e nome de município (sem acento)."""
        return _json(buscar(engine_de(request), q, max(1, min(limite, MAX_IMOVEIS))))

    @r.get("/mapa/manifesto.json")
    def mapa_manifesto() -> Response:
        """Qual recorte do Protomaps está no ar (build, tamanho, zoom, crédito)."""
        from raiz import mapa_base

        m = mapa_base.manifesto()
        if not m:
            raise HTTPException(404, "mapa base ainda não gerado (raiz mapa atualizar)")
        return _json(m)

    @r.get("/mapa/brasil.pmtiles")
    def mapa_brasil() -> Response:
        """Mapa base do Brasil até o zoom 14, com Range (o leitor do PMTiles pede por faixa de bytes)."""
        from raiz import mapa_base

        f = mapa_base.arquivo_atual()
        if f is None:
            raise HTTPException(404, "mapa base ainda não gerado (raiz mapa atualizar)")
        return FileResponse(f, media_type="application/vnd.pmtiles")

    @r.get("/mapa/fontes/{fonte}/{faixa}.pbf")
    def mapa_fonte(fonte: str, faixa: str) -> Response:
        from raiz import mapa_base

        if fonte not in mapa_base.FONTES or not re.fullmatch(r"\d+-\d+", faixa):
            raise HTTPException(404, "fonte ou faixa desconhecida")
        f = mapa_base.pasta() / "fontes" / fonte / f"{faixa}.pbf"
        if not f.exists():
            raise HTTPException(404, "faixa de letras não baixada")
        return FileResponse(f, media_type="application/x-protobuf")

    @r.get("/mapa/sprites/{nome}.{ext}")
    def mapa_sprite(nome: str, ext: str) -> Response:
        from raiz import mapa_base

        base = nome.removesuffix("@2x")
        if base not in mapa_base.SPRITES or ext not in ("json", "png"):
            raise HTTPException(404, "sprite desconhecido")
        f = mapa_base.pasta() / "sprites" / f"{nome}.{ext}"
        if not f.exists():
            raise HTTPException(404, "sprite não baixado")
        return FileResponse(f, media_type="application/json" if ext == "json" else "image/png")

    @r.get("/geo/{cod_ibge}/base.pmtiles")
    def base(cod_ibge: int) -> Response:
        from raiz.geo import arquivo_base

        f = arquivo_base(cod_ibge)
        if f is None:
            raise HTTPException(404, "mapa base ainda não gerado (front/scripts/geo.py)")
        # FileResponse do Starlette responde a Range (206) e manda Accept-Ranges, como o PMTiles precisa
        return FileResponse(f, media_type="application/vnd.pmtiles")

    @r.get("/geo/{cod_ibge}/{camada}.geojson")
    def geo(cod_ibge: int, camada: str, request: Request) -> Response:
        eng = engine_de(request)
        with eng.connect() as con:
            if camada == "imoveis":
                fc = con.execute(
                    text("""
                    select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                        json_build_object(
                            'type', 'Feature',
                            'properties', json_build_object('cod_imovel', i.cod_imovel, 'area', v.area,
                                                            'm_fiscal', v.m_fiscal, 'status_imovel', v.status_imovel),
                            'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(i.geom, :t), 6)::json)
                        order by i.cod_imovel), '[]'::json))
                    from funil.imovel i join funil.resultado_vigente v on v.cod_imovel = i.cod_imovel
                    where v.cod_municipio_ibge = :c and i.geom is not null"""),
                    {"c": cod_ibge, "t": SIMPLIFICAR_GRAUS},
                ).scalar()
            elif camada == "terra_publica":
                # terra pública para restaurar dentro do município (a divisa vem de geo.camada 'municipio'; sem ela,
                # a caixa dos imóveis do município)
                fc = con.execute(
                    text("""
                    with m as (
                        select coalesce(
                            (select ST_Union(geom) from geo.camada where cod_ibge = :c and camada = 'municipio'),
                            (select ST_Envelope(ST_Collect(i.geom)) from funil.imovel i
                             join funil.vigente v on v.cod_imovel = i.cod_imovel where v.cod_municipio_ibge = :c)
                        ) as g)
                    select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                        json_build_object('type', 'Feature', 'properties', json_build_object(
                            'id', t.id, 'nome', t.nome, 'fonte', t.fonte, 'destinacao', t.destinacao,
                            'categoria', t.categoria, 'ha', t.ha, 'desmatado_ha', t.desmatado_ha,
                            'credito_liquido_tco2_ano', t.credito_liquido_tco2_ano, 'tradicional', t.tradicional,
                            'concessao_situacao', t.concessao_situacao),
                            'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_Intersection(t.geom, m.g), :t),
                                                     6)::json)
                        order by t.desmatado_ha desc nulls last), '[]'::json))
                    from geo.terra_publica t, m where m.g is not null and ST_Intersects(t.geom, m.g)"""),
                    {"c": cod_ibge, "t": SIMPLIFICAR_GRAUS * 3},
                ).scalar()
            elif camada in ("municipio", "ti", "uc", "rios"):
                fc = con.execute(
                    text("""
                    select json_build_object('type', 'FeatureCollection', 'features', coalesce(json_agg(
                        json_build_object('type', 'Feature', 'properties', propriedades,
                                          'geometry', ST_AsGeoJSON(geom, 6)::json) order by id), '[]'::json))
                    from geo.camada where cod_ibge = :c and camada = :k"""),
                    {"c": cod_ibge, "k": camada},
                ).scalar()
            else:
                raise HTTPException(404, f"camada desconhecida: {camada}")
        if not fc or not fc["features"]:
            raise HTTPException(404, f"sem {camada} para {cod_ibge}")
        lugar = ("nome",) if camada != "imoveis" else ()  # nome de TI, UC e município é nome de lugar
        for f in fc["features"]:
            f["properties"] = _limpa(f["properties"] or {}, lugar)
        return Response(json.dumps(fc, separators=(",", ":")), media_type="application/geo+json")

    return r
