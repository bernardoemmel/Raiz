"""Dossiê executivo do lote por município: o que o Bot Agro montava na mão para Paragominas, agora automático.

Pedido do desenvolvedor ("lotes em <município>") -> dossiê já filtrado, com lotes por vizinhança, ressalvas claras e o
checklist do que ainda precisa de gente. Lê só o que o processamento já calculou (imoveis, filtros, terra, comprometida,
restricoes, desenvolvedor e geo do município) e os limites de projetos de carbono do Release `insumos`; não recalcula o
funil nem as previsões. Regras e limiares: raiz/regras/padroes/dossie_lote.yaml; critérios em docs/lote.md.

Modos (pedido do fundador, 17/11/2026):
  estrito  sobreposição real com projeto de carbono e gleba federal não destinada acima de 10% do CAR tiram do lote;
           posse sem matrícula também fica fora.
  normal   os mesmos casos ficam no lote com ressalva explícita (forte).
Em qualquer modo saem: PRODES desde 2016, alerta MapBiomas, embargo, TI, UC, quilombo, assentamento e terra pública.
KML regional (agrupado ou acima de 500 mil ha) nunca exclui: vira "risco de sobreposição a conferir", com a distância
até a instância pública conhecida do mesmo projeto. Limite a menos de 100 m, sem cruzar: ressalva leve.
Restrições nacionais: exclusão (Lista Suja, lavra, território tradicional) sai em qualquer modo; ressalvas por peso.
Nenhum imóvel sai por tamanho. Nada de nome, CPF ou CNPJ: só o código público do CAR e números.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import math
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from raiz import terra as T
from raiz.agentes.textos import num

ARQ_REGRA = Path(__file__).parent / "regras" / "padroes" / "dossie_lote.yaml"
MODOS = ("normal", "estrito")
PRONTIDAO = ("alta", "media", "baixa")
NOME_PRONTIDAO = {"alta": "alta", "media": "média", "baixa": "baixa"}


@lru_cache
def _ler(caminho: str, _marca: tuple) -> dict:
    texto = Path(caminho).read_bytes()
    r = yaml.safe_load(texto)
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(texto).hexdigest()[:8]}"
    return r


def regra(arquivo: Path | None = None) -> dict:
    a = Path(arquivo or ARQ_REGRA)
    return _ler(str(a), (a.stat().st_mtime_ns, a.stat().st_size))


def _n(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# --- leitura do que já foi calculado ---------------------------------------------------------------------------


def ler_municipio(pasta: str | Path, cod: int) -> list[dict]:
    from raiz.pedidos.oferta import linhas_da_pasta

    return linhas_da_pasta(Path(pasta), int(cod))


def ler_geo(pasta: str | Path, cod: int):
    import geopandas as gpd

    f = Path(pasta) / f"geo_{int(cod)}.parquet"
    if not f.exists():
        return None
    g = gpd.read_parquet(f)[["cod_imovel", "geometry"]]
    g["cod_imovel"] = g.cod_imovel.astype(str)
    return g.set_crs(4674) if g.crs is None else g


def ler_limites(pasta: str | Path | None = None):
    """Todos os limites coletados, inclusive os regionais (que a camada 'já comprometida' deixa fora do cruzamento)."""
    import geopandas as gpd

    from raiz.comprometida import status as ST

    f = Path(pasta or ST.pasta_limites()) / "comprometida_limites.parquet"
    if not f.exists():
        return None
    g = gpd.read_parquet(f)
    return g.set_crs(4326) if g.crs is None else g


# --- projetos de carbono ----------------------------------------------------------------------------------------


def _regional(lim, r: dict):
    c = r["carbono"]
    area = pd.to_numeric(lim.get("area_ha"), errors="coerce") if "area_ha" in lim else None
    # do agrupado, o KML oficial é a região; polígono de outra fonte do mesmo projeto é instância (fazenda) conhecida
    reg = lim.objeto_id.astype(str).isin(c["agrupados_regionais"])
    if "certeza" in lim:
        reg &= lim.certeza.astype(str) == "poligono_oficial"
    for col in ("limite_suspeito", "limite_amplo"):
        if col in lim:
            reg |= lim[col].fillna(False).astype(bool)
    if area is not None:
        reg |= area.fillna(0) > c["regional_ha"]
    return reg


def carbono(geo, limites, r: dict | None = None) -> dict[str, dict]:
    """Por CAR: sobreposição real (oficial e indício), áreas regionais a conferir e divisas a menos de 100 m."""
    import shapely

    r = r or regra()
    c = r["carbono"]
    if geo is None or limites is None or not len(limites):
        return {}
    lim = limites.copy()
    lim = lim[~lim.situacao.astype(str).str.lower().isin(c["situacoes_inativas"])]
    lim["regional"] = _regional(lim, r)
    lim = lim.to_crs(5880)
    im = geo.to_crs(5880)
    # instâncias públicas conhecidas: polígonos não regionais de cada projeto regional (de qualquer fonte), inteiros,
    # para medir a distância mesmo fora do município
    ids_reg = set(lim.objeto_id[lim.regional].astype(str))
    locais: dict[str, list] = {}
    for pid, g, reg in zip(lim.objeto_id.astype(str), lim.geometry.values, lim.regional, strict=True):
        if pid in ids_reg and not reg and g is not None:
            locais.setdefault(pid, []).append(g)
    # o resto é recortado na caixa do município (+ margem) antes de validar: KML regional de milhões de ha vira um
    # pedaço pequeno e a conta fica rápida
    x0, y0, x1, y1 = im.total_bounds
    m = 2 * c["divisa_m"] + 1000
    b = lim.geometry.bounds
    lim = lim[(b.minx <= x1 + m) & (b.maxx >= x0 - m) & (b.miny <= y1 + m) & (b.maxy >= y0 - m)].copy()
    lim["geometry"] = shapely.make_valid(shapely.clip_by_rect(lim.geometry.values, x0 - m, y0 - m, x1 + m, y1 + m))
    lim = lim[~lim.geometry.is_empty].reset_index(drop=True)
    shapely.prepare(lim.geometry.values)
    geoms, regs = lim.geometry.values, lim.regional.to_numpy()
    pids, certs = lim.objeto_id.astype(str).to_numpy(), lim.certeza.astype(str).to_numpy()
    tree = shapely.STRtree(geoms)
    out = {}
    for cod, g in zip(im.cod_imovel.astype(str), im.geometry.values, strict=True):
        d = {"oficial_ha": 0.0, "indicio_ha": 0.0, "projetos": [], "regionais": [], "divisas": []}
        out[cod] = d
        if g is None or g.is_empty:
            d["sem_geometria"] = True
            continue
        g = shapely.make_valid(g)
        oficial, indicio = [], []
        for j in tree.query(g.buffer(c["divisa_m"])):  # só caixa: o teste fino vem abaixo
            pid, x = pids[j], geoms[j]
            if regs[j]:
                # KML regional: basta tocar o interior (prepared, rápido); a área cruzada não importa
                if (
                    pid not in [y["projeto"] for y in d["regionais"]]
                    and shapely.intersects(x, g)
                    and not shapely.touches(x, g)
                ):
                    dist = min((float(g.distance(y)) for y in locais.get(pid, [])), default=None)
                    d["regionais"].append({"projeto": pid, "distancia_instancia_m": dist})
                continue
            if not shapely.intersects(x, g.buffer(c["divisa_m"])):
                continue
            inter = g.intersection(x) if shapely.intersects(x, g) else None
            ha = inter.area / 1e4 if inter is not None and not inter.is_empty else 0.0
            if ha > c["sobreposicao_min_ha"]:
                (oficial if certs[j] == "poligono_oficial" else indicio).append(inter)
                if pid not in d["projetos"]:
                    d["projetos"].append(pid)
            else:
                dist = float(g.distance(x))
                if dist <= c["divisa_m"] and pid not in [y["projeto"] for y in d["divisas"]]:
                    d["divisas"].append({"projeto": pid, "distancia_m": round(dist), "borda_ha": round(ha, 2)})
        # as interseções já estão recortadas no CAR: a união é pequena
        u_of = shapely.union_all(oficial) if oficial else None
        if u_of is not None:
            d["oficial_ha"] = round(u_of.area / 1e4, 2)
        if indicio:
            u = shapely.union_all(indicio)
            if u_of is not None:
                u = u.difference(u_of)
            d["indicio_ha"] = round(u.area / 1e4, 2)
        # projeto que cruza não é também "divisa"
        d["divisas"] = [y for y in d["divisas"] if y["projeto"] not in d["projetos"]]
    return out


# --- avaliação de cada imóvel -----------------------------------------------------------------------------------


def _matricula(linha: dict) -> dict:
    cam = linha.get("caminho_terra") if isinstance(linha.get("caminho_terra"), str) else None
    if cam is None:
        cam = T.caminho(linha)["caminho_terra"]
    reg = _n(linha.get("terra_sigef_registrada_ha"))
    if reg is None:
        reg = _n(linha.get("matricula_ha")) or 0.0
    posse, tit = _n(linha.get("terra_sigef_posse_ha")), _n(linha.get("terra_sigef_titulacao_ha"))
    if posse is None and tit is None:  # sem terra_<mun>.csv: parcela do SIGEF sem matrícula nem assentamento
        cert = max((_n(linha.get("sigef_ha")) or 0.0) - (_n(linha.get("matricula_ha")) or 0.0)
                   - (_n(linha.get("assentamento_ha")) or 0.0), 0.0)  # fmt: skip
    else:
        cert = (posse or 0.0) + (tit or 0.0)
    if cam == "privada_matricula":
        return {"caminho": cam, "situacao": "matricula", "texto": "matrícula no SIGEF (registrada)", "ha": reg}
    if cam == "posse_em_titulacao" and cert > 0.01:
        return {"caminho": cam, "situacao": "so_certificado", "texto": "só certificado no SIGEF: pedir inteiro teor",
                "ha": cert}  # fmt: skip
    if cam == "posse_em_titulacao":
        return {"caminho": cam, "situacao": "posse", "texto": "posse declarada no CAR, sem matrícula", "ha": 0.0}
    rotulo = {
        "assentamento": "lote de assentamento",
        "publica_sem_destinacao": "pública sem destinação",
        "terra_indigena_ou_tradicional": "indígena ou tradicional",
        "publica_concessao": "pública sob concessão",
    }
    return {"caminho": cam, "situacao": cam, "texto": rotulo.get(cam, (cam or "sem caminho").replace("_", " ")),
            "ha": reg}  # fmt: skip


def _area_restauravel(linha: dict) -> tuple[float | None, str]:
    for col, fonte in (("restauracao_area_ha", "previsão de restauração"),
                       ("compensacao_restauravel_ha", "área aberta restaurável do motor")):  # fmt: skip
        v = _n(linha.get(col))
        if v is not None:
            return v, fonte
    return None, "sem estimativa"


@lru_cache(maxsize=1)
def _textos_restricoes() -> dict[str, str]:
    from raiz.restricoes import status as RS

    m = RS.regra()["motivos"]
    return {k: " ".join(str(v).split()).rstrip(".") for grupo in ("exclusao", "ressalva") for k, v in m[grupo].items()}


def _restricoes(linha: dict, r: dict, fora: list, forte: list, media: list, leve: list) -> None:
    """Restrições nacionais (SICAR completo, SIGMINE, autos do Ibama, Lista Suja): exclusão sai em qualquer modo."""
    st = linha.get("restricao_nacional")
    if st not in ("exclusao", "ressalva", "livre"):
        media.append("restrições nacionais não verificadas (SICAR completo, SIGMINE, Ibama, Lista Suja)")
        return
    motivos = [m for m in str(linha.get("restricao_motivos") or "").split("|") if m]
    textos, peso = _textos_restricoes(), r.get("restricoes") or {}
    for m in motivos:
        txt = f"restrição nacional: {textos.get(m, m.replace('_', ' '))}"
        if st == "exclusao" and m in RS_EXCLUSAO:
            fora.append(txt)
        elif m in peso.get("fortes", ()):
            forte.append(txt)
        elif m in peso.get("leves", ()):
            leve.append(txt)
        elif m not in RS_EXCLUSAO:
            media.append(txt)
    if st == "exclusao" and not any(m in RS_EXCLUSAO for m in motivos):
        fora.append("restrição nacional (motivo não informado)")


RS_EXCLUSAO = ("lista_suja", "mineracao_lavra", "territorio_tradicional")


def avaliar(linha: dict, carb: dict | None, modo: str = "normal", r: dict | None = None) -> dict:
    """Situação de um imóvel no dossiê: fora (com os motivos) ou no lote (com as ressalvas por peso)."""
    if modo not in MODOS:
        raise ValueError("modo do dossiê: normal ou estrito")
    r = r or regra()
    tol = r["tolerancia_ha"]
    fora, forte, media, leve = [], [], [], []
    for col, nome in r["exclusoes"].items():
        v = _n(linha.get(col))
        if v is not None and v > tol:
            fora.append(f"{nome} ({num(v, 1)} ha)")
    mat = _matricula(linha)
    if mat["caminho"] in r["caminhos_fora"]:
        fora.append(f"terra: {mat['texto']}")
    ha = _n(linha.get("ha")) or 0.0
    # gleba federal não destinada (CNFP), critério de 10% do CAR
    gf = T.gleba_federal(linha)
    if gf["gleba_federal"]:
        txt = f"{num(100 * gf['gleba_federal_fracao'], 0)}% do CAR em gleba federal não destinada"
        (fora if modo == "estrito" else forte).append(txt)
    elif gf["gleba_federal"] is None:
        media.append("gleba federal não medida")
    # carbono
    proj_ha = _n(linha.get("projeto_carbono_ha")) or 0.0
    if carb is None:
        st = linha.get("status_sobreposicao")
        if st == "ja_comprometida":
            (fora if modo == "estrito" else forte).append(
                f"já em projeto de carbono ({linha.get('projeto_id') or '?'})"
            )
        elif st == "risco_sobreposicao":
            forte.append("indício de sobreposição com projeto de carbono")
        else:
            media.append("sobreposição com projetos de carbono não verificada")
    else:
        proj_ha = max(proj_ha, carb["oficial_ha"])
        ids = ", ".join(carb["projetos"])
        if carb["oficial_ha"] > tol:
            pct = f"{num(100 * carb['oficial_ha'] / ha, 0)}%, " if ha else ""
            txt = f"sobreposição com projeto de carbono {ids} ({pct}{num(carb['oficial_ha'], 1)} ha, limite oficial)"
            (fora if modo == "estrito" else forte).append(txt)
        elif carb["indicio_ha"] > tol:
            txt = f"sobreposição com limite secundário de projeto {ids} ({num(carb['indicio_ha'], 1)} ha), a conferir"
            (fora if modo == "estrito" else forte).append(txt)
        for x in carb["regionais"]:
            d = x["distancia_instancia_m"]
            dist = f"instância pública conhecida a {num(d / 1000, 1)} km" if d is not None else "sem instância pública"
            media.append(f"dentro da área regional do {x['projeto']}: risco de sobreposição a conferir ({dist})")
        for x in carb["divisas"]:
            if x.get("borda_ha"):
                leve.append(f"divisa com o {x['projeto']} ({num(x['borda_ha'], 2)} ha de borda entre as bases)")
            else:
                leve.append(f"divisa a {x['distancia_m']} m do {x['projeto']}")
    _restricoes(linha, r, fora, forte, media, leve)
    # matrícula
    if mat["situacao"] == "so_certificado":
        media.append("só certificado no SIGEF: pedir inteiro teor")
    elif mat["situacao"] == "posse":
        (fora if modo == "estrito" else forte).append("posse sem matrícula nem SIGEF")
    if (_n(linha.get("uc_apa_ha")) or 0) > tol:
        leve.append(f"APA em {num(_n(linha.get('uc_apa_ha')), 1)} ha (admite terra privada)")
    rest, fonte_rest = _area_restauravel(linha)
    if not fora and not (rest and rest > 0):
        fora.append("sem área restaurável estimada")
    prontidao = "baixa" if forte else ("media" if media or leve else "alta")
    return {
        "cod_imovel": str(linha["cod_imovel"]),
        "ha": ha,
        "ha_restauravel": rest,
        "fonte_restauravel": fonte_rest,
        "matricula": mat["texto"],
        "matricula_situacao": mat["situacao"],
        "projeto_carbono_ha": round(proj_ha, 2),
        "gleba_federal_pct": None if gf["gleba_federal_fracao"] is None else round(100 * gf["gleba_federal_fracao"], 1),
        "fora": fora,
        "ressalvas_fortes": forte,
        "ressalvas_medias": media,
        "ressalvas_leves": leve,
        "prontidao": prontidao,
        "no_lote": not fora,
    }


# --- lotes por vizinhança ---------------------------------------------------------------------------------------


def _pontos(geo) -> dict[str, tuple[float, float]]:
    if geo is None:
        return {}
    c = geo.to_crs(5880).geometry.representative_point().to_crs(4674)
    return {k: (p.x, p.y) for k, p in zip(geo.cod_imovel.astype(str), c, strict=True) if p is not None}


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def agrupar(aptos: list[dict], pontos: dict, r: dict | None = None) -> list[dict]:
    """Lotes gulosos por vizinhança: o maior restaurável abre o lote e puxa quem está a até raio_km dele.
    Sem ponto (sem polígono), o imóvel fica num lote próprio com "localização pendente"."""
    r = r or regra()
    raio = r["lotes"]["raio_km"]
    lotes = []
    # prontos primeiro: imóveis sem ressalva forte formam lotes entre si; os de ressalva forte (só no modo normal)
    # formam lotes à parte, para a ressalva de um não derrubar a prontidão do lote inteiro
    for faixa in (("alta", "media"), ("baixa",)):
        resto = sorted((a for a in aptos if a["prontidao"] in faixa),
                       key=lambda x: (-(x["ha_restauravel"] or 0), x["cod_imovel"]))  # fmt: skip
        lotes += _lotes_da_faixa(resto, pontos, raio)
    lotes.sort(key=lambda x: (x["prontidao"] == "baixa", -x["ha_restauravel"], x["imoveis"][0]["cod_imovel"]))
    for i, x in enumerate(lotes, start=1):
        x["lote"] = i
    return lotes


def _lotes_da_faixa(resto: list[dict], pontos: dict, raio: float) -> list[dict]:
    lotes = []
    while resto:
        semente = resto.pop(0)
        membros = [semente]
        if semente["cod_imovel"] in pontos:
            p0 = pontos[semente["cod_imovel"]]
            fica = []
            for x in resto:
                p = pontos.get(x["cod_imovel"])
                (membros if p is not None and _km(p0, p) <= raio else fica).append(x)
            resto = fica
        lotes.append(_resumo_lote(membros, pontos))
    return lotes


def _resumo_lote(membros: list[dict], pontos: dict) -> dict:
    ps = [(pontos[m["cod_imovel"]], m["ha_restauravel"] or 0) for m in membros if m["cod_imovel"] in pontos]
    centro = raio = None
    if ps:
        peso = sum(w for _, w in ps) or len(ps)
        centro = (sum(p[0] * (w or 1) for p, w in ps) / peso, sum(p[1] * (w or 1) for p, w in ps) / peso)
        raio = max(_km(centro, p) for p, _ in ps)
    pior = max(PRONTIDAO.index(m["prontidao"]) for m in membros)
    ressalvas: dict[str, int] = {}
    for m in membros:
        for t in m["ressalvas_fortes"] + m["ressalvas_medias"] + m["ressalvas_leves"]:
            chave = _tema(t)
            ressalvas[chave] = ressalvas.get(chave, 0) + 1
    return {
        "imoveis": sorted(membros, key=lambda m: m["cod_imovel"]),
        "n": len(membros),
        "ha": round(sum(m["ha"] for m in membros), 1),
        "ha_restauravel": round(sum(m["ha_restauravel"] or 0 for m in membros), 1),
        "centro": centro,
        "raio_km": None if raio is None else round(raio, 1),
        "localizacao_pendente": len(ps) < len(membros),
        "ressalvas": sorted(ressalvas.items(), key=lambda kv: (-kv[1], kv[0])),
        "prontidao": PRONTIDAO[pior],
    }


def _tema(texto: str) -> str:
    """Agrupa ressalvas parecidas para a tabela dos lotes (o anexo traz o texto inteiro)."""
    for chave, tema in (("área regional", "KML regional a conferir"), ("divisa", "divisa com projeto < 100 m"),
                        ("inteiro teor", "pedir inteiro teor"), ("gleba federal não medida", "gleba não medida"),
                        ("gleba federal", "gleba federal > 10%"), ("limite secundário", "indício de projeto"),
                        ("projeto de carbono", "sobreposição com projeto"), ("posse", "posse sem matrícula"),
                        ("APA", "APA")):  # fmt: skip
        if chave in texto:
            return tema
    return texto


# --- o dossiê ---------------------------------------------------------------------------------------------------


def nome_municipio(cod: int) -> tuple[str, str]:
    import csv

    with (Path(__file__).parent / "executor" / "municipios.csv").open(encoding="utf-8") as f:
        for li in csv.DictReader(f):
            if int(li["codigo_ibge"]) == int(cod):
                uf = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
                      "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
                      "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
                      "51": "MT", "52": "GO", "53": "DF"}[str(li["codigo_uf"])]  # fmt: skip
                return li["nome"], uf
    return str(cod), ""


def montar(pasta: str | Path, cod: int, *, modo: str = "normal", limites=None, linhas: list[dict] | None = None,
           geo=None, hoje: str | None = None, r: dict | None = None) -> dict:  # fmt: skip
    """Dossiê de um município a partir da pasta do estado (saida/<UF>/). `limites`: GeoDataFrame dos projetos
    (padrão: Release insumos baixado em cache/comprometida); False força o uso só de comprometida_<mun>.csv."""
    if modo not in MODOS:
        raise ValueError("modo do dossiê: normal ou estrito")
    r = r or regra()
    pasta = Path(pasta)
    linhas = linhas if linhas is not None else ler_municipio(pasta, cod)
    geo = geo if geo is not None else ler_geo(pasta, cod)
    if limites is None:
        limites = ler_limites()
    elif limites is False:
        limites = None
    carb = carbono(geo, limites, r) if limites is not None else {}
    avaliados = [avaliar(li, carb.get(str(li["cod_imovel"])) if carb else None, modo, r) for li in linhas]
    aptos = [a for a in avaliados if a["no_lote"]]
    pontos = _pontos(geo)
    lotes = agrupar(aptos, pontos, r)
    n = r["lotes"]["no_dossie"]
    principais, demais = lotes[:n], lotes[n:]
    motivos: dict[str, int] = {}
    for a in avaliados:
        for t in a["fora"]:
            k = t.split(" (")[0]
            motivos[k] = motivos.get(k, 0) + 1
    colunas = set().union(*(li.keys() for li in linhas)) if linhas else set()
    nome, uf = nome_municipio(cod)
    return {
        "municipio": nome,
        "uf": uf,
        "cod_ibge": int(cod),
        "modo": modo,
        "gerado_em": hoje or dt.date.today().isoformat(),
        "regra_versao": r["versao_completa"],
        "carbono_verificado": bool(carb),
        "gleba_nao_medida": sum(1 for a in avaliados if a["gleba_federal_pct"] is None),
        "imoveis_lidos": len(avaliados),
        "imoveis_aptos": len(aptos),
        "ha_aptos": round(sum(a["ha"] for a in aptos), 1),
        "ha_restauravel_aptos": round(sum(a["ha_restauravel"] or 0 for a in aptos), 1),
        "fora_por_motivo": sorted(motivos.items(), key=lambda kv: (-kv[1], kv[0])),
        "filtros_sem_dado": [nome for col, nome in r["exclusoes"].items() if col not in colunas],
        "lotes": principais,
        "potencial_adicional": {
            "lotes": len(demais),
            "imoveis": sum(x["n"] for x in demais),
            "ha_restauravel": round(sum(x["ha_restauravel"] for x in demais), 1),
        },
        "validacao_humana": list(r["validacao_humana"]),
        "versoes": {
            k: sorted({str(li[k]) for li in linhas if li.get(k)})[:3]
            for k in ("terra_regra_versao", "comprometida_versao", "restricoes_versao", "restauracao_versao")
        },  # fmt: skip
    }


def _ressalvas_texto(lote: dict) -> str:
    return "; ".join(f"{t} ({n})" if n > 1 else t for t, n in lote["ressalvas"][:3]) or "nenhuma"


def _centro_texto(lote: dict) -> str:
    if lote["centro"] is None:
        return "localização pendente"
    lon, lat = lote["centro"]
    return f"{num(lote['raio_km'], 1)} km em torno de {lat:.4f}, {lon:.4f}"


def markdown(d: dict) -> str:
    total_ha = sum(x["ha_restauravel"] for x in d["lotes"])
    n_im = sum(x["n"] for x in d["lotes"])
    plural = "lote" if len(d["lotes"]) == 1 else "lotes"
    linhas = [
        f"# {d['municipio']}: {len(d['lotes'])} {plural} de restauração para avaliação",
        "",
        f"Gerado em {d['gerado_em']} pela Raíz, modo **{d['modo']}**, regra `{d['regra_versao']}`. Uso restrito.",
        "",
        "## Oferta",
        "",
        f"- **{num(total_ha, 0)} ha restauráveis em {n_im} imóveis**, em {len(d['lotes'])} {plural} por vizinhança.",
        f"- {d['imoveis_lidos']} imóveis do município lidos; {d['imoveis_aptos']} passaram nos filtros "
        f"({num(d['ha_restauravel_aptos'], 0)} ha restauráveis).",
        "- Já filtrado: " + ("; ".join(f"{k} ({n})" for k, n in d["fora_por_motivo"]) or "nenhum imóvel saiu") + ".",
        "- Nenhum imóvel saiu por tamanho: pequenas entram no lote mais próximo.",
        "",
        "## Lotes",
        "",
        "| Lote | Imóveis | ha restauráveis | Raio / centro | Principais ressalvas | Prontidão |",
        "|---|---:|---:|---|---|---|",
    ]
    for x in d["lotes"]:
        linhas.append(f"| {x['lote']} | {x['n']} | {num(x['ha_restauravel'], 0)} | {_centro_texto(x)} | "
                      f"{_ressalvas_texto(x)} | {NOME_PRONTIDAO[x['prontidao']]} |")  # fmt: skip
    if not d["lotes"]:
        linhas.append("| — | 0 | 0 | — | nenhum imóvel passou nos filtros | — |")
    linhas += ["", "## O que já foi checado (dados públicos)", ""]
    checados = [
        "PRODES desde 2016 = 0 ha dentro do CAR",
        "MapBiomas Alerta = 0",
        "Sem embargo, terra indígena, UC, quilombo nem assentamento dentro do polígono",
    ]
    gleba = "Gleba federal não destinada (CNFP/SFB) até 10% do CAR" + (
        " (acima disso: fora)" if d["modo"] == "estrito" else " (acima disso: ressalva)"
    )
    sem_gleba = d.get("gleba_nao_medida", 0)
    pendentes = list(d["filtros_sem_dado"])
    if sem_gleba:
        pendentes.append(f"{gleba}: {sem_gleba} imóveis sem a medição do CNFP")
    else:
        checados.append(gleba)
    checados += [
        'Projetos de carbono: KML oficial Verra (inclusive "Other"), InfoAmazonia, base científica, REDD+ do Pará; '
        "KML regional e acima de 500 mil ha só como risco a conferir; divisa a menos de 100 m como ressalva leve"
        if d["carbono_verificado"]
        else "Projetos de carbono: limites não disponíveis nesta execução; vale o status por CAR já calculado",
        "Matrícula: SIGEF; sem SIGEF, a cobertura de matrícula da tabela de imóveis",
    ]
    linhas += [f"- [x] {t}" for t in checados]
    linhas += [f"- [ ] {t}: não disponível nos dados, conferir" for t in pendentes]
    linhas += ["", "## O que falta (validação humana)", ""]
    linhas += [f"- [ ] {t}" for t in d["validacao_humana"]]
    p = d["potencial_adicional"]
    linhas += [
        "",
        "## Potencial adicional no município",
        "",
        f"Fora dos {len(d['lotes'])} lotes acima: {p['lotes']} grupos, {p['imoveis']} imóveis, "
        f"{num(p['ha_restauravel'], 0)} ha restauráveis que também passaram nos filtros.",
        "",
        "## Anexo: imóveis por lote",
        "",
    ]
    for x in d["lotes"]:
        linhas += [f"### Lote {x['lote']}", "", "| CAR | ha | ha restauráveis | Matrícula | Observações |",
                   "|---|---:|---:|---|---|"]  # fmt: skip
        for m in x["imoveis"]:
            obs = "; ".join(m["ressalvas_fortes"] + m["ressalvas_medias"] + m["ressalvas_leves"]) or "sem ressalva"
            linhas.append(f"| {m['cod_imovel']} | {num(m['ha'], 0)} | {num(m['ha_restauravel'], 0)} | "
                          f"{m['matricula']} | {obs} |")  # fmt: skip
        linhas.append("")
    linhas += [
        "---",
        "Estimativas de planejamento a partir de dados públicos. Não é certidão de terra livre nem garantia de "
        "crédito; não libera venda. Versões: " + "; ".join(f"{k} {', '.join(v)}" for k, v in d["versoes"].items() if v),
    ]
    return "\n".join(linhas) + "\n"


def pdf_bytes(d: dict) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, invariant=1)  # fmt: skip
    st = getSampleStyleSheet()
    corpo = []
    tabela: list[list] = []
    for li in markdown(d).splitlines():
        if li.startswith("|"):
            if set(li.replace("|", "").strip()) <= set("-: "):
                continue
            tabela.append([Paragraph(escape(c.strip()), st["BodyText"]) for c in li.strip("|").split("|")])
            continue
        if tabela:
            t = Table(tabela, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, "#999999"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            corpo += [t, Spacer(1, 4 * mm)]
            tabela = []
        if not li.strip():
            continue
        estilo = "Title" if li.startswith("# ") else "Heading2" if li.startswith("## ") else (
            "Heading3" if li.startswith("### ") else "BodyText")  # fmt: skip
        texto = escape(li.lstrip("#").strip()).replace("**", "")
        corpo.append(Paragraph(texto, st[estilo]))
    if tabela:
        corpo.append(Table(tabela, repeatRows=1))
    doc.build(corpo)
    return buf.getvalue()


def docx_bytes(d: dict) -> bytes:
    from docx import Document

    doc = Document()
    tabela = None
    for li in markdown(d).splitlines():
        if li.startswith("|"):
            if set(li.replace("|", "").strip()) <= set("-: "):
                continue
            cels = [c.strip() for c in li.strip("|").split("|")]
            if tabela is None:
                tabela = doc.add_table(rows=0, cols=len(cels))
                tabela.style = "Table Grid"
            for cel, texto in zip(tabela.add_row().cells, cels, strict=False):
                cel.text = texto
            continue
        tabela = None
        if not li.strip():
            continue
        if li.startswith("#"):
            nivel = len(li) - len(li.lstrip("#"))
            doc.add_heading(li.lstrip("#").strip(), level=min(nivel - 1, 3) if nivel > 1 else 0)
        elif li.startswith("- "):
            doc.add_paragraph(li[2:].replace("**", ""), style="List Bullet")
        else:
            doc.add_paragraph(li.replace("**", ""))
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def gravar(d: dict, saida: str | Path, nome: str) -> dict[str, Path]:
    import json

    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    arquivos = {
        "md": saida / f"{nome}.md",
        "pdf": saida / f"{nome}.pdf",
        "docx": saida / f"{nome}.docx",
        "json": saida / f"{nome}.json",
    }
    arquivos["md"].write_text(markdown(d), encoding="utf-8")
    arquivos["pdf"].write_bytes(pdf_bytes(d))
    arquivos["docx"].write_bytes(docx_bytes(d))
    arquivos["json"].write_text(json.dumps(d, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return arquivos
