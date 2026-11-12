"""Dados por município para o front (docs/design/dados-para-o-front-v1.md, item 4).

- funil por etapa e por porte, em imóveis e em hectares, com os 3 maiores motivos de saída de cada etapa;
- "desde a última análise": quantos imóveis subiram e quantos desceram de etapa entre as duas últimas rodadas do
  município (foto em funil.etapa_rodada, com a versão do motor na rodada);
- frase-resumo pronta, que diz o que falta quando falta dado;
- contorno da área urbanizada da sede (MapBiomas classe 24, a mancha onde fica a sede no OpenStreetMap), para a
  comparação de tamanho, guardado em geo.camada ('urbana').
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import Engine, text

from raiz.imovel_dados import ETAPAS

ROTULOS_ETAPA = {
    "cadastro": "no CAR",
    "sem_problema": "sem embargo, TI ou desmate recente",
    "apta": "aptas para a mata voltar",
    "com_matricula": "com matrícula",
    "titulo_conferido": "com título conferido",
    "aceite": "com aceite do dono",
}
TEXTO_MOTIVO = {
    "embargo": "embargo do Ibama",
    "ti": "sobreposição com terra indígena",
    "desmate2020": "desmatamento depois de 2020",
    "alerta": "alerta de desmatamento depois de 2020",
    "desmate2016": "desmate nos últimos 10 anos",
    "alem": "falta de área para a mata voltar além da reserva legal",
    "matricula": "menos da metade do CAR com matrícula",
    "titulo": "matrícula ainda não conferida",
    "aceite": "dono ainda não aceitou",
}
URBANA = 24  # MapBiomas: área urbanizada


def _fmt(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _linhas(engine: Engine, cod_ibge: int) -> list[dict]:
    """Etapa, motivo, porte e área de cada imóvel vigente (da foto da rodada vigente e da ficha, se houver)."""
    with engine.connect() as con:
        return [
            dict(r._mapping)
            for r in con.execute(
                text("""
                select v.cod_imovel, e.etapa, e.motivo_saida, r.ha, r.carbono_ha, r.m_fiscal,
                       coalesce(c.atributos->>'porte',
                                case when r.m_fiscal is null then null when r.m_fiscal <= 4 then 'pequeno'
                                     when r.m_fiscal <= 15 then 'médio' else 'grande' end) as porte,
                       a.estado as aceite
                from funil.vigente v
                join funil.resultado_imovel r on r.rodada_id = v.rodada_id and r.cod_imovel = v.cod_imovel
                left join funil.etapa_rodada e on e.rodada_id = v.rodada_id and e.cod_imovel = v.cod_imovel
                left join funil.complemento_imovel c
                       on c.rodada_id = v.rodada_id and c.cod_imovel = v.cod_imovel and c.tipo = 'ficha'
                left join negocio.aceite a on a.cod_imovel = v.cod_imovel
                where v.cod_municipio_ibge = :m"""),
                {"m": cod_ibge},
            )
        ]


def funil(linhas: list[dict]) -> dict:
    """Quantos imóveis e hectares alcançaram cada etapa (no total e por porte) e os 3 maiores motivos de saída."""
    ordem = {e: i for i, e in enumerate(ETAPAS)}
    for x in linhas:
        if x.get("aceite") == "aceito":
            x["etapa"], x["motivo_saida"] = "aceite", None
        x["etapa"] = x.get("etapa") or "cadastro"

    def contar(grupo):
        out = []
        for e in ETAPAS:
            chegaram = [x for x in grupo if ordem.get(x["etapa"], 0) >= ordem[e]]
            area = "carbono_ha" if ordem[e] >= ordem["apta"] else "ha"
            out.append({"etapa": e, "rotulo": ROTULOS_ETAPA[e], "imoveis": len(chegaram),
                        "ha": round(sum(float(x[area] or 0) for x in chegaram), 1), "medida_ha": area})  # fmt: skip
        return out

    por_porte = defaultdict(list)
    for x in linhas:
        por_porte[x.get("porte") or "sem_dado"].append(x)
    motivos = {}
    for e in ETAPAS:
        pararam = [x for x in linhas if x["etapa"] == e and x.get("motivo_saida")]
        cont = Counter(x["motivo_saida"] for x in pararam)
        ha = Counter()
        for x in pararam:
            ha[x["motivo_saida"]] += float(x["ha"] or 0)
        motivos[e] = [{"motivo": m, "texto": TEXTO_MOTIVO.get(m, m), "imoveis": n, "ha": round(ha[m], 1)}
                      for m, n in cont.most_common(3)]  # fmt: skip
    return {
        "etapas": contar(linhas),
        "por_porte": {p: contar(g) for p, g in sorted(por_porte.items())},
        "motivos_saida": motivos,
    }


def desde_ultima(engine: Engine, cod_ibge: int) -> dict | None:
    """Subiram, desceram, iguais, novos e saíram entre as duas últimas rodadas do município."""
    with engine.connect() as con:
        rods = con.execute(
            text("""select id, data_corte, motor_versao from funil.rodada
                    where tipo = 'municipio' and cod_municipio = :m order by data_corte desc, id desc limit 2"""),
            {"m": cod_ibge},
        ).all()
        if len(rods) < 2:
            return None
        nova, velha = rods
        fotos = {
            rid: dict(
                con.execute(
                    text("select cod_imovel, etapa from funil.etapa_rodada where rodada_id = :r"), {"r": rid}
                ).all()
            )  # fmt: skip
            for rid in (nova.id, velha.id)
        }
    if not fotos[velha.id] or not fotos[nova.id]:  # rodada carregada antes de existir a foto: não dá para comparar
        return None
    ordem = {e: i for i, e in enumerate(ETAPAS)}
    a, b = fotos[velha.id], fotos[nova.id]
    subiram = sum(1 for c in a.keys() & b.keys() if ordem.get(b[c], 0) > ordem.get(a[c], 0))
    desceram = sum(1 for c in a.keys() & b.keys() if ordem.get(b[c], 0) < ordem.get(a[c], 0))
    return {
        "subiram": subiram,
        "desceram": desceram,
        "iguais": len(a.keys() & b.keys()) - subiram - desceram,
        "novos": len(b.keys() - a.keys()),
        "sairam": len(a.keys() - b.keys()),
        "de": {"rodada": velha.id, "data_corte": velha.data_corte.isoformat(), "motor_versao": velha.motor_versao},
        "para": {"rodada": nova.id, "data_corte": nova.data_corte.isoformat(), "motor_versao": nova.motor_versao},
    }


def frase(nome: str, uf: str, f: dict | None, resumo: dict | None, desde: dict | None) -> str:
    """Frase-resumo pronta, que diz o que falta quando falta dado."""
    onde = f"{nome} ({uf})" if uf else nome
    if not f or not f["etapas"] or not f["etapas"][0]["imoveis"]:
        if resumo and resumo.get("imoveis"):
            return (f"Em {onde}, o motor contou {_fmt(resumo['imoveis'])} imóveis rurais e "
                    f"{_fmt(resumo.get('aptas_carbono') or 0)} aptos para a mata voltar; a análise por fazenda "
                    "ainda não foi carregada.")  # fmt: skip
        return f"A Raíz ainda não analisou os imóveis de {onde}."
    e = {x["etapa"]: x for x in f["etapas"]}
    partes = [f"Em {onde}, a Raíz analisou {_fmt(e['cadastro']['imoveis'])} imóveis rurais do CAR"]
    partes.append(f"{_fmt(e['sem_problema']['imoveis'])} estão sem embargo, terra indígena ou desmate recente")
    if e["apta"]["imoveis"]:
        partes.append(f"{_fmt(e['apta']['imoveis'])} têm área para a mata voltar ({_fmt(e['apta']['ha'])} ha)")
    else:
        partes.append("nenhum tem área para a mata voltar por enquanto")
    if e["com_matricula"]["imoveis"]:
        partes.append(f"{_fmt(e['com_matricula']['imoveis'])} com matrícula")
    texto = partes[0] + ": " + ", ".join(partes[1:-1]) + (" e " if len(partes) > 2 else "") + partes[-1] + "."
    todos = [m for ms in f["motivos_saida"].values() for m in ms]
    if todos:
        maior = max(todos, key=lambda m: m["imoveis"])
        texto += f" O que mais tira fazendas do funil é {maior['texto']} ({_fmt(maior['imoveis'])} imóveis)."
    if desde and (desde["subiram"] or desde["desceram"]):
        texto += (
            f" Desde a última análise, {_fmt(desde['subiram'])} subiram e {_fmt(desde['desceram'])} desceram de etapa."
        )
    return texto


def dados(engine: Engine, cod_ibge: int) -> dict | None:
    with engine.connect() as con:
        m = con.execute(text("select * from funil.municipio_busca where cod_ibge = :c"), {"c": cod_ibge}).first()
        resumo = con.execute(
            text("""select r.imoveis, r.aptas_carbono, r.ha_carbono from funil.resumo_municipio r
                    join funil.rodada ro on ro.id = r.rodada_id where r.cod_ibge = :c
                    order by ro.data_corte desc, ro.id desc limit 1"""),
            {"c": cod_ibge},
        ).first()
        urbana_ha = con.execute(
            text("""select sum(ST_Area(geom::geography)) / 1e4 from geo.camada
                    where cod_ibge = :c and camada = 'urbana'"""),
            {"c": cod_ibge},
        ).scalar()
    if m is None and resumo is None:
        return None
    linhas = _linhas(engine, cod_ibge)
    f = funil(linhas) if linhas else None
    d = desde_ultima(engine, cod_ibge) if linhas else None
    r = dict(resumo._mapping) if resumo else None
    nome, uf = (m.municipio, m.uf) if m else ("", "")
    return {
        "cod_ibge": str(cod_ibge),
        "municipio": nome,
        "uf": uf,
        "frase": frase(nome, uf, f, r, d),
        "funil": f,
        "desde_ultima_analise": d,
        "area_urbana_ha": round(float(urbana_ha), 1) if urbana_ha else None,
        "resumo_motor": r,
    }


def urbana(engine: Engine, cod_ibge: int, cobertura_tif, osm_dia: str | None = None, raio_graus: float = 0.15):
    """Contorno da mancha urbana (MapBiomas 24) onde fica a sede (cidade do OSM com o nome do município)."""
    import shapely
    from rasterio import open as abrir
    from rasterio.features import shapes
    from rasterio.windows import from_bounds

    from raiz import osm
    from raiz.busca import normalizar_nome

    with engine.connect() as con:
        m = con.execute(
            text("select municipio from funil.municipio_busca where cod_ibge = :c"), {"c": cod_ibge}
        ).first()
        caixa = con.execute(
            text("""select ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) from (
                      select ST_Extent(i.geom) e from funil.vigente v join funil.imovel i on i.cod_imovel = v.cod_imovel
                      where v.cod_municipio_ibge = :c) s"""),
            {"c": cod_ibge},
        ).first()
    if m is None or caixa is None or caixa[0] is None:
        return None
    lugares, _ = osm.lugares_e_estradas(tuple(caixa), osm_dia)
    alvo = normalizar_nome(m.municipio)
    sede = next((x for x in lugares if normalizar_nome(x["nome"]) == alvo), None)
    if sede is None:
        return None
    p = sede["geom"]
    with abrir(cobertura_tif) as r:
        w = from_bounds(p.x - raio_graus, p.y - raio_graus, p.x + raio_graus, p.y + raio_graus, r.transform)
        w = w.round_offsets().round_lengths()
        a = r.read(1, window=w, boundless=True, fill_value=0)
        tr = r.window_transform(w)
    urb = (a == URBANA).astype("uint8")
    polis = [shapely.geometry.shape(g) for g, v in shapes(urb, mask=urb > 0, transform=tr)]
    if not polis:
        return None
    u = shapely.union_all(polis)
    partes = list(shapely.get_parts(u))
    mancha = min(partes, key=lambda g: g.distance(p))
    mancha = shapely.set_precision(mancha.simplify(0.0002, preserve_topology=True), 1e-6)
    with engine.begin() as con:
        con.execute(text("delete from geo.camada where cod_ibge = :c and camada = 'urbana'"), {"c": cod_ibge})
        con.execute(
            text("""insert into geo.camada (cod_ibge, camada, propriedades, geom, fonte)
                    values (:c, 'urbana', cast(:p as jsonb), ST_SetSRID(ST_GeomFromText(:g), 4674), 'MapBiomas')"""),
            {
                "c": cod_ibge,
                "p": f'{{"nome": "{sede["nome"]}", "fonte": "MapBiomas área urbanizada"}}',
                "g": mancha.wkt,
            },
        )
    return mancha
