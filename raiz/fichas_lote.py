"""Ficha de cada fazenda gravada em lote (E9, passo 1), a partir do funil vigente no banco.

Por município, em <destino>/<UF>/<cod_ibge>/:

    fichas/<cod_busca>.json   FichaJson, a mesma de GET /imoveis/{cod}/ficha (front/compartilhado/dados/ficha.ts),
                              para servir como arquivo estático (o site e a ficha do produtor leem sem a API)
    rows.json                 uma linha por fazenda com os campos que o cartão, o vídeo e o texto usam (mesmos nomes
                              do pedido do Takumi em servicos/cartao/render.mjs); campo com "_" na frente é interno e
                              nunca vai para imagem, vídeo ou página antes do aceite do dono (o código do CAR, a foto
                              de satélite, o Plus Code e o link do Organic Maps, que dão o ponto exato)
    manifesto.json            rodada, data de corte, versão das fichas, quantas fazendas e quando foi gravado

e <destino>/indice.json com um resumo por município. Só regrava o município cuja rodada vigente mudou (ou com
--refazer), e grava cada arquivo num temporário antes de trocar, para quem lê nunca pegar arquivo pela metade.

O contexto do município (posição e medianas) é calculado uma vez por município, não por fazenda. Nome, CPF e CNPJ não
entram: a linha passa pela mesma limpeza da API (raiz/front_api.py) e o texto pela máscara.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from pathlib import Path

from sqlalchemy import Engine, text

from raiz import RAIZ_REPO
from raiz import front_api as api
from raiz.publico import fmt_ha

VERSAO_FICHAS = 1


def pasta_padrao() -> Path:
    return Path(os.environ.get("RAIZ_FICHAS_DIR") or RAIZ_REPO / "dados" / "fichas")


def _gravar(caminho: Path, dado) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dado, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    tmp.replace(caminho)


def municipios(engine: Engine, uf: str | None = None, cods: list[int] | None = None) -> list[dict]:
    """Municípios com imóvel vigente: código, UF e a rodada vigente (a mais nova, se houver mais de uma)."""
    filtros, par = [], {}
    if uf:
        filtros.append("v.uf = :uf")
        par["uf"] = uf.upper()
    if cods:
        filtros.append("v.cod_municipio_ibge = any(:cods)")
        par["cods"] = list(cods)
    onde = ("where " + " and ".join(filtros)) if filtros else ""
    with engine.connect() as con:
        rs = con.execute(
            text(f"""select v.cod_municipio_ibge as cod, max(v.uf) as uf, max(v.rodada_id) as rodada, count(*) as n
                     from funil.vigente v {onde} group by v.cod_municipio_ibge order by 1"""),
            par,
        ).all()
    return [{"cod_ibge": r.cod, "uf": r.uf, "rodada": r.rodada, "imoveis": r.n} for r in rs if r.cod is not None]


def _do_banco_em_lote(engine: Engine, cods: list[str]) -> dict[str, dict]:
    """O mesmo que front_api.do_banco, para todas as fazendas do município de uma vez."""
    out: dict[str, dict] = {}
    with engine.connect() as con:
        for r in con.execute(
            text("""select v.cod_imovel, k.codigo, a.estado, ro.data_corte from funil.vigente v
                    join funil.rodada ro on ro.id = v.rodada_id
                    left join negocio.codigo_curto k on k.cod_imovel = v.cod_imovel
                    left join negocio.aceite a on a.cod_imovel = v.cod_imovel
                    where v.cod_imovel = any(:cs)"""),
            {"cs": cods},
        ):
            out[r.cod_imovel] = {
                "codigo_curto": r.codigo,
                "aceite": r.estado,
                "data_corte": r.data_corte.isoformat() if r.data_corte else None,
                "serie_uso": None,
            }
        series: dict[str, list] = defaultdict(list)
        for r in con.execute(
            text("""select cod_imovel, ano, mata_pct, pasto_pct, lavoura_pct, agua_pct, colecao from funil.serie_uso
                    where cod_imovel = any(:cs) order by cod_imovel, ano"""),
            {"cs": cods},
        ):
            series[r.cod_imovel].append(r)
    for cod, serie in series.items():
        if cod in out:
            out[cod]["serie_uso"] = {
                "anos": [x.ano for x in serie],
                "mata_pct": [x.mata_pct for x in serie],
                "pasto_pct": [x.pasto_pct for x in serie],
                "lavoura_pct": [x.lavoura_pct for x in serie],
                "agua_pct": [x.agua_pct for x in serie],
                "fonte": f"MapBiomas ({serie[0].colecao})",
            }
    return out


def _versoes(engine: Engine, cods: list[str]) -> tuple[dict[str, int], dict[int, dict]]:
    """Rodada vigente de cada fazenda e a versão do dado de cada rodada (o mesmo que front_api.versao)."""
    with engine.connect() as con:
        por_cod = {
            r.cod_imovel: r.rodada_id
            for r in con.execute(
                text("select cod_imovel, rodada_id from funil.vigente where cod_imovel = any(:cs)"), {"cs": cods}
            )
        }
        rodadas = {}
        for r in con.execute(
            text("""select ro.id, ro.data_corte, ro.carregada_em, ro.motor_versao, ro.regras_versao,
                           (select count(*) from funil.rodada x where x.tipo = 'municipio'
                            and x.cod_municipio = ro.cod_municipio) as rodadas_do_municipio
                    from funil.rodada ro where ro.id = any(:ids)"""),
            {"ids": sorted(set(por_cod.values()))},
        ):
            rodadas[r.id] = {
                "rodada": r.id,
                "data_corte": r.data_corte.isoformat(),
                "carregada_em": r.carregada_em.isoformat(),
                "motor_versao": r.motor_versao,
                "regras_versao": r.regras_versao,
                "rodadas_do_municipio": r.rodadas_do_municipio,
            }
    return por_cod, rodadas


def _geometrias(engine: Engine, cods: list[str]) -> dict[str, dict]:
    with engine.connect() as con:
        return {
            r.cod_imovel: json.loads(r.g)
            for r in con.execute(
                text("""select cod_imovel, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, :t), 6) as g
                        from funil.imovel where cod_imovel = any(:cs) and geom is not null"""),
                {"cs": cods, "t": api.SIMPLIFICAR_GRAUS},
            )
        }


def linha_do_cartao(ficha: dict) -> dict:
    """Os campos do cartão, do vídeo e do texto (servicos/cartao/render.mjs e raiz/publico.py) tirados da ficha.
    Antes do aceite só município, hectares, frase, selo e código curto; o código do CAR vai em "_cod_imovel"."""
    imovel = ficha["imovel"]
    lido = api.ler_imovel(imovel)
    restauravel = lido["carbono_ha"]
    ha = restauravel if restauravel > 0 else lido["ha"]
    aceito = ficha.get("nivel_selo") == "ouro"
    linha = {
        "codigo": ficha.get("codigo_curto"),
        "municipio": ficha["contexto"]["municipio"],
        "uf": ficha["contexto"]["uf"],
        "hectares": fmt_ha(ha),
        "hectares_num": round(ha, 2),
        "frase": "podem voltar a ser mata" if restauravel > 0 else "de fazenda no Cadastro Ambiental Rural",
        "frase_curta": "podem voltar a ser mata" if restauravel > 0 else "no CAR",
        "selo": ficha.get("nivel_selo"),
        "selo_texto": ficha.get("nivel_selo_texto"),
        "etapa_funil": ficha.get("etapa_funil"),
        "apta": lido["apta"],
        "posicao_carbono": round(ficha["contexto"]["posicao_carbono"], 4),
        "aceito": aceito,
        "_cod_imovel": imovel["cod_imovel"],
    }
    loc = ficha.get("localizacao") or {}
    if aceito:  # depois do aceite o código do CAR, a foto de satélite e o ponto exato podem aparecer
        linha["cod_imovel"] = imovel["cod_imovel"]
        if ficha.get("capa"):
            linha["capa_thumbhash"] = ficha["capa"]["thumbhash"]
        if loc:
            linha.update(plus_code=loc["plus_code"], omaps=loc["omaps"])
    elif loc:
        linha.update(_plus_code=loc["plus_code"], _omaps=loc["omaps"])
    return linha


def gravar_municipio(engine: Engine, cod_ibge: int, destino: Path) -> dict:
    """Grava as fichas, o rows.json e o manifesto de um município. Devolve o manifesto."""
    todos = api.imoveis_do_municipio(engine, cod_ibge)
    if not todos:
        return {"cod_ibge": cod_ibge, "imoveis": 0}
    cods = [i["cod_imovel"] for i in todos]
    contexto = api.contexto_municipio(todos)
    banco = _do_banco_em_lote(engine, cods)
    rodada_de, rodadas = _versoes(engine, cods)
    geoms = _geometrias(engine, cods)
    uf = (todos[0].get("uf") or "").upper()
    pasta = destino / uf / str(cod_ibge)
    rows = []
    for alvo in todos:
        cod = alvo["cod_imovel"]
        b = {**banco.get(cod, {}), "capa": api.capa_da_ficha(cod)}
        ficha = api.montar_ficha(alvo, todos, geoms.get(cod), rodadas.get(rodada_de.get(cod)), b, contexto)
        _gravar(pasta / "fichas" / f"{api.normalizar_codigo(cod)}.json", ficha)
        rows.append(linha_do_cartao(ficha))
    _gravar(pasta / "rows.json", rows)
    rodada = max(rodada_de.values()) if rodada_de else None
    manifesto = {
        "cod_ibge": cod_ibge,
        "municipio": todos[0].get("municipio") or "",
        "uf": uf,
        "rodada": rodada,
        "data_corte": (rodadas.get(rodada) or {}).get("data_corte"),
        "versao_fichas": VERSAO_FICHAS,
        "imoveis": len(todos),
        "com_contorno": len(geoms),
        "aptas": sum(r["apta"] for r in rows),
        "gravado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    _gravar(pasta / "manifesto.json", manifesto)
    return manifesto


def _manifesto(destino: Path, uf: str, cod_ibge: int) -> dict | None:
    f = destino / uf / str(cod_ibge) / "manifesto.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def gravar(
    engine: Engine,
    destino: Path | None = None,
    uf: str | None = None,
    cods: list[int] | None = None,
    refazer: bool = False,
    aviso=lambda _texto: None,
) -> dict:
    """O lote: grava os municípios cuja rodada vigente mudou desde a última gravação e atualiza o índice."""
    destino = destino or pasta_padrao()
    feitos, iguais = [], 0
    for m in municipios(engine, uf, cods):
        antes = _manifesto(destino, m["uf"], m["cod_ibge"])
        if (
            not refazer
            and antes
            and antes.get("rodada") == m["rodada"]
            and antes.get("versao_fichas") == VERSAO_FICHAS
            and antes.get("imoveis") == m["imoveis"]
        ):
            iguais += 1
            continue
        man = gravar_municipio(engine, m["cod_ibge"], destino)
        feitos.append(man)
        aviso(f"{man.get('municipio')} ({man.get('uf')}): {man['imoveis']} fichas")
    indice = []
    for pasta_uf in sorted(p for p in destino.iterdir() if p.is_dir()) if destino.exists() else []:
        for pasta_mun in sorted(p for p in pasta_uf.iterdir() if p.is_dir()):
            man = _manifesto(destino, pasta_uf.name, int(pasta_mun.name)) if pasta_mun.name.isdigit() else None
            if man:
                indice.append({k: man.get(k) for k in ("cod_ibge", "municipio", "uf", "rodada", "data_corte",
                                                        "imoveis", "aptas", "gravado_em")})  # fmt: skip
    _gravar(destino / "indice.json", {"versao_fichas": VERSAO_FICHAS, "municipios": indice})
    fichas = sum(m["imoveis"] for m in feitos)
    return {"gravados": len(feitos), "iguais": iguais, "fichas": fichas, "destino": str(destino)}
