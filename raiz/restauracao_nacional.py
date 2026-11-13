"""Consulta nacional sobre catálogo privado: UF/bioma/Brasil explícitos, sem refazer previsões.

A saída é planejamento sobre a cobertura publicada, não autorização de venda.
Tabelas/decisões por imóvel ficam em Parquet privado; o retorno em memória contém
apenas agregados e caminhos, mesmo quando a meta exige muitas fazendas.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import pyarrow as pa

from raiz import restauracao_catalogo as C
from raiz import restauracao_selecao as S
from raiz.pedidos.campos import CamposPedido
from raiz.pedidos.premissas import premissas

UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
BIOMAS = ("Amazônia", "Caatinga", "Cerrado", "Mata Atlântica", "Pampa", "Pantanal")
OPCOES = ("barata", "segura", "compacta")


@dataclass(frozen=True)
class Recorte:
    ufs: tuple[str, ...] = ()
    biomas: tuple[str, ...] = ()
    municipios: tuple[int, ...] = ()
    brasil: bool = False


def normalizar_recorte(*, ufs=None, biomas=None, municipios=None, brasil=False) -> Recorte:
    us = tuple(sorted(set(str(u).strip().upper() for u in (ufs or ()))))
    bs = tuple(sorted(set(str(b).strip() for b in (biomas or ()))))
    ms = tuple(sorted(set(int(m) for m in (municipios or ()))))
    if set(us) - set(UFS) or set(bs) - set(BIOMAS) or any(m < 1000000 or m > 9999999 for m in ms):
        raise ValueError("UF, bioma ou município inválido.")
    if brasil and (us or bs or ms):
        raise ValueError("Brasil não pode esconder filtros; escolha Brasil ou um recorte explícito.")
    if not brasil and not (us or bs or ms):
        raise ValueError("Informe UF/bioma/município ou brasil=True explicitamente.")
    return Recorte(us, bs, ms, bool(brasil))


def versao_nacional() -> str:
    h = hashlib.sha256(Path(__file__).read_bytes() + Path(S.__file__).read_bytes())
    h.update(C._json(premissas()))
    financeiro = Path(__file__).with_name("restauracao_nacional_financeiro.py")
    if financeiro.exists():
        h.update(financeiro.read_bytes())
    return "lote-nacional-1+" + h.hexdigest()[:12]


def _sql(valor) -> str:
    return "'" + str(valor).replace("'", "''") + "'"


def _lista(valores) -> str:
    return "[" + ",".join(_sql(x) for x in valores) + "]"


def _filtro_recorte(recorte: Recorte) -> str:
    filtros = []
    for coluna, valores in (("uf", recorte.ufs), ("bioma", recorte.biomas), ("cod_ibge", recorte.municipios)):
        if valores:
            filtros.append(f"cast({coluna} as varchar) in (select unnest({_lista(valores)}))")
    return " AND ".join(filtros) or "true"


def _regras_pedido(pedido: CamposPedido, modelo: str, cenario: str, comercializaveis: bool) -> list[tuple[str, str]]:
    f = [
        ("Versão financeira diferente ou ausente", f"restauracao_versao={_sql(modelo)}"),
        ("Cenário diferente ou ausente", f"restauracao_cenario={_sql(cenario)}"),
        ("Previsão não compatível", "situacao_previsao='compativel'"),
        ("Elegibilidade da fonte não comprovada", "elegivel"),
        ("Salvaguardas impedem planejamento", "salvaguardas_planejamento"),
        ("Problema impeditivo sinalizado", "not problema"),
        ("Caminho da terra fora do pedido ou ausente", f"caminho in (select unnest({_lista(pedido.terra)}))"),
        ("Método aceito não disponível", f"list_has_any(metodos, {_lista(pedido.metodos)})"),
        ("Interesse recusado ou sem classificação", "nivel_interesse != 'recusou'"),
    ]
    quantidade = {"creditos": "credito_p50", "hectares": "area_ha", "flag_t_ano": "flag_t_ano"}[pedido.meta.tipo]
    f.append(("Quantidade positiva não estimada; sem piso de tamanho", f"{quantidade}>0"))
    for ex in pedido.exclusoes:
        f.append((f"Exclusão solicitada: {ex}", f"not {ex}"))
    if comercializaveis:
        f.append(("Salvaguardas para comercialização pendentes", "salvaguardas_comercializavel"))
    if pedido.dinheiro.custo_max_usd_credito is not None:
        f.append(("Custo acima do limite ou ausente", f"custo_credito_usd <= {pedido.dinheiro.custo_max_usd_credito}"))
    if pedido.dinheiro.tir_min is not None:
        f.append(("TIR abaixo do mínimo ou ausente", f"tir_p50 >= {pedido.dinheiro.tir_min}"))
    if pedido.interesse != "qualquer":
        niveis = ["aceite_fase1", "contrato_firme"]
        if pedido.interesse == "interessados":
            niveis.append("interessado")
        f.append(
            ("Aceite ou interesse exigido não comprovado", f"nivel_interesse in (select unnest({_lista(niveis)}))")
        )
    if pedido.onde.so_fornecedores_cadeia:
        f.append(
            (
                "Fora da cadeia de fornecedores indicada",
                f"cod_imovel in (select unnest({_lista(pedido.onde.fornecedores)}))",
            )
        )
    # Filtros espaciais são aplicados ao índice de pontos, com incerteza explícita.
    if pedido.onde.raio or pedido.onde.poligono:
        f.append(
            ("Localização fora do recorte ou não comprovada", "cod_imovel in (select cod_imovel from filtro_espacial)")
        )
    return f


def _filtro_pedido(pedido: CamposPedido, modelo: str, cenario: str, comercializaveis: bool) -> str:
    return (
        "coalesce(("
        + " AND ".join(q for _, q in _regras_pedido(pedido, modelo, cenario, comercializaveis))
        + "), false)"
    )


def _motivos_pedido(pedido, modelo, cenario, comercializaveis):
    casos = [
        f"case when not coalesce(({q}),false) then {_sql(texto)} end"
        for texto, q in _regras_pedido(pedido, modelo, cenario, comercializaveis)
    ]
    return "concat_ws('; '," + ",".join(casos) + ")"


def _espacial(con, pedido):
    if not (pedido.onde.raio or pedido.onde.poligono):
        return
    pontos = con.sql("select cod_imovel, lon, lat, local_aproximado from recorte").fetchdf()
    ok = pontos.lon.notna() & pontos.lat.notna() & ~pontos.local_aproximado
    if pedido.onde.raio:
        r = pedido.onde.raio
        ok &= S.distancia_km(pontos.lon.to_numpy(float), pontos.lat.to_numpy(float), r.lon, r.lat) <= r.km
    if pedido.onde.poligono:
        import shapely

        poligono = shapely.Polygon(pedido.onde.poligono)
        if not poligono.is_valid:
            raise ValueError("Polígono inválido.")
        ok &= shapely.covers(poligono, shapely.points(pontos.lon.to_numpy(float), pontos.lat.to_numpy(float)))
    con.register("filtro_espacial", pa.Table.from_pandas(pontos.loc[ok, ["cod_imovel"]], preserve_index=False))


def _cobertura(catalogo, recorte, con, modelo, cenario):
    ufs = set(recorte.ufs or UFS)
    if recorte.municipios and not recorte.ufs:
        prefixos = {str(m)[:2] for m in recorte.municipios}
        mapa = dict(
            zip(
                UFS,
                (
                    "12",
                    "27",
                    "16",
                    "13",
                    "29",
                    "23",
                    "53",
                    "32",
                    "52",
                    "21",
                    "51",
                    "50",
                    "31",
                    "15",
                    "25",
                    "41",
                    "26",
                    "22",
                    "33",
                    "24",
                    "43",
                    "11",
                    "14",
                    "42",
                    "35",
                    "28",
                    "17",
                ),
                strict=True,
            )
        )
        ufs = {u for u in UFS if mapa[u] in prefixos}
    presente, esperado, vazio = set(), set(), set()
    for uf in ufs:
        c = catalogo["cobertura"].get(uf, {})
        presente.update(c.get("presentes", []))
        esperado.update(c.get("esperados", []))
        vazio.update(c.get("sem_imoveis", []))
    if recorte.municipios:
        esperado = set(recorte.municipios)
        presente &= esperado
        vazio &= esperado
    ausentes = sorted(esperado - presente - vazio)
    desconhecidas = sorted(ufs - set(catalogo["cobertura"]))
    numeros = (
        con.sql(f"""select count(*) imoveis,
        count(*) filter(where restauracao_versao={_sql(modelo)} and restauracao_cenario={_sql(cenario)}
          and situacao_previsao='compativel') previsoes_compativeis,
        count(*) filter(where situacao_previsao='previsao_ausente') previsoes_ausentes,
        count(*) filter(where pequena) pequenas,
        count(*) filter(where area_ha>0 and area_ha<1) areas_positivas_menores_1ha
        from recorte""")
        .fetchdf()
        .iloc[0]
        .to_dict()
    )
    numeros = {k: int(v) for k, v in numeros.items()}
    numeros["previsoes_incompativeis"] = (
        numeros["imoveis"] - numeros["previsoes_compativeis"] - numeros["previsoes_ausentes"]
    )
    return {
        "recorte": asdict(recorte),
        "ufs_sem_catalogo": desconhecidas,
        "municipios_presentes": sorted(presente),
        "municipios_esperados_identificados": len(esperado),
        "municipios_sem_imoveis_comprovados": sorted(vazio),
        "municipios_faltantes_identificados": ausentes,
        "totalidade_bioma_depende_cobertura_municipal": bool(recorte.biomas),
        "cobertura_completa": not desconhecidas
        and not ausentes
        and numeros["previsoes_incompativeis"] == 0
        and numeros["previsoes_ausentes"] == 0,
        **numeros,
    }


def _prior_sql(p):
    a = p["aceite"]
    terra = (
        "case caminho_terra "
        + " ".join(f"when {_sql(k)} then {v}" for k, v in a["por_caminho"].items())
        + " else 1 end"
    )
    fs, vs = a["faixas_ha"], a["por_faixa"]
    faixa = "case " + " ".join(f"when ha<{limiar} then {vs[i]}" for i, limiar in enumerate(fs)) + f" else {vs[-1]} end"
    prior = f"least(0.95, greatest(0.01, {a['base']} * ({terra}) * ({faixa}) * {a['por_pagamento']['participacao']}))"
    return (
        "case nivel_interesse when 'contrato_firme' then 1 when 'aceite_fase1' then 0.9 "
        f"when 'interessado' then 0.65 when 'sem_resposta' then ({prior})*0.5 else {prior} end"
    )


def _agregar_grupos(con, pedido):
    p = premissas()
    o = p["otimizador"]
    maxc = con.sql("select greatest(100,coalesce(max(custo_credito_usd),100))*1.5 from elegiveis").fetchone()[0]
    custo = f"coalesce(custo_credito_usd, {maxc})"
    terra = (
        "case risco_terra "
        + " ".join(f"when {_sql(k)} then {v}" for k, v in o["risco_terra"].items())
        + f" else {o['risco_terra']['alto']} end"
    )
    risco = (
        f"({terra}) + (1-coalesce(marcos_todos,0))*{o['risco_marcos_usd']} "
        f"+ (1-({_prior_sql(p)}))*{o['risco_aceite_usd']}"
    )
    preco = pedido.dinheiro.preco_venda_usd
    penalidade = (
        f"case when preco_equilibrio_usd>{preco} then preco_equilibrio_usd-{preco}"
        f"+{o['abaixo_equilibrio_usd']} else 0 end"
    )
    q = {"creditos": "credito_p50", "hectares": "area_ha", "flag_t_ano": "flag_t_ano"}[pedido.meta.tipo]
    return con.sql(f"""select g.grupo_id, count(*) membros, sum({q}) quantidade, sum(area_ha) area_ha,
        sum(credito_p50) credito_p50, sum(({custo})*credito_p50) custo_total,
        sum(({risco})*credito_p50) risco_total, sum(({penalidade})*credito_p50) penalidade_total,
        first(g.grupo_lon) grupo_lon, first(g.grupo_lat) grupo_lat, first(g.grupo_raio_km) grupo_raio_km
        from elegiveis e join grupos g using(cod_imovel) group by g.grupo_id order by g.grupo_id""").fetchdf()


def _gravar_parquet(con, consulta, arquivo):
    C._diretorio(arquivo.parent)
    temporario = arquivo.with_name(f".{uuid.uuid4().hex}.parquet")
    try:
        con.sql(f"COPY ({consulta}) TO {_sql(temporario)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        temporario.chmod(0o600)
        os.replace(temporario, arquivo)
    finally:
        temporario.unlink(missing_ok=True)
    return {"caminho": str(arquivo), "sha256": C.sha256(arquivo), "bytes": arquivo.stat().st_size}


def _resumo_faixas(con):
    # Mesma aproximação analítica de pedidos.otimizador.faixa_soma; não soma quantis marginais.
    from raiz.pedidos.otimizador import fracao_comum

    x = con.sql("""select coalesce(sum(credito_p50),0),
        coalesce(sum(greatest(credito_p50-credito_p10,0)),0),
        coalesce(sum(greatest(credito_p90-credito_p50,0)),0),
        coalesce(sum(pow(greatest(credito_p50-credito_p10,0),2)),0),
        coalesce(sum(pow(greatest(credito_p90-credito_p50,0),2)),0) from escolhidos""").fetchone()
    f = fracao_comum()
    baixo, alto = math.sqrt(f * x[1] ** 2 + (1 - f) * x[3]), math.sqrt(f * x[2] ** 2 + (1 - f) * x[4])
    return {
        "p10": max(0.0, x[0] - baixo),
        "p50": x[0],
        "p90": x[0] + alto,
        "metodo": "aproximacao_normal_assimetrica_com_fator_comum",
        "fracao_comum": f,
        "calibracao": "premissa_do_modelo; sem alegar medição regional",
    }


def preparar_contrato(pedido: CamposPedido, modelo: str, cenario: str, chance_alvo=None):
    """Traduz volume contratado em oferta necessária, com as mesmas premissas do lote estadual."""
    from raiz import restauracao as R

    if modelo == R.versao():
        premissa = R.cenario(cenario)
        if not math.isclose(premissa["preco_usd_t"], pedido.dinheiro.preco_venda_usd) or not math.isclose(
            premissa["fracao_financiada"], pedido.dinheiro.fracao_financiada
        ):
            raise ValueError(
                "Preço/dívida diferentes exigem reavaliar a oferta; não reutilizar TIR do cenário original."
            )
    efetivo = pedido.model_copy(deep=True)
    contrato = {
        "volume_solicitado": float(pedido.meta.valor),
        "unidade": pedido.meta.tipo,
        "cronograma": pedido.cronograma,
        "necessario_p50": float(pedido.meta.valor),
    }
    if pedido.meta.tipo != "creditos" or pedido.cronograma == "livre":
        contrato["validado"] = False
        return efetivo, contrato, None, None
    r = R.regra()
    if modelo != r["versao_completa"]:
        raise ValueError(
            "Marcos exigem a mesma versão do modelo das previsões; não se aplicam regras novas ao histórico."
        )
    c = R.cenario(cenario, r=r)
    if pedido.cronograma == "proprio":
        marcos = pedido.marcos_proprios or []
        anos = [m.ano for m in marcos]
        fracoes = [m.fracao for m in marcos]
        if not marcos or anos != sorted(set(anos)) or any(a > c["prazo_anos"] for a in anos):
            raise ValueError("Marcos próprios precisam ser únicos, ordenados e dentro do prazo do cenário.")
        if fracoes != sorted(fracoes) or any(not 0 < f <= 1 for f in fracoes) or fracoes[-1] != 1:
            raise ValueError("Frações acumuladas dos marcos devem crescer até 100%.")
        c = {**c, "entregas_anos": anos, "marcos_pct": [100 * f for f in fracoes]}
    chance = float(chance_alvo if chance_alvo is not None else r["lote"]["chance_alvo_reserva"])
    if not 0 < chance < 1:
        raise ValueError("Chance alvo deve ficar entre zero e um.")
    fator = R.fator_captura_alvo(chance, r)
    if fator <= 0:
        raise ValueError("As premissas não permitem a chance alvo escolhida.")
    necessario = R.contrato_para_marcos(pedido.meta.valor, c, r)
    com_reserva = necessario / fator
    efetivo.meta.valor = necessario
    contrato.update(
        validado=True,
        necessario_p50=necessario,
        necessario_com_reserva=com_reserva,
        reserva_necessaria=max(0.0, com_reserva - necessario),
        chance_alvo=chance,
        fator_captura_alvo=fator,
        versao_premissas=modelo,
    )
    return efetivo, contrato, r, c


def _conferir_origens_selecionadas(con, catalogo, origens):
    presentes = {int(x[0]) for x in con.sql("select distinct cod_ibge from escolhidos").fetchall()}
    por_municipio = {p["municipio"]: p for p in catalogo["particoes"]}
    for cod in presentes:
        if cod not in origens:
            raise ValueError("Falta entrada congelada de município selecionado para agregar o fluxo.")
        fonte = por_municipio[cod]["fontes"]
        atual = {p.name: C.sha256(p) for p in C._fontes(origens[cod], cod)}
        if atual != {nome: meta["sha256"] for nome, meta in fonte.items()}:
            raise ValueError("Entrada financeira mudou desde o índice; não misturar previsões e fluxo de outra fonte.")


def montar_tres_opcoes(
    catalogo: str | Path,
    pedido: CamposPedido,
    recorte: Recorte,
    *,
    modelo: str,
    cenario: str,
    destino: str | Path,
    limites: S.LimitesSelecao | None = None,
    somente_comercializaveis: bool = False,
    conferir_hashes: bool = True,
    diametro_grupo_km: float = 15.0,
    max_membros_grupo: int = 128,
    chance_alvo: float | None = None,
    origens: dict[int, str | Path] | None = None,
) -> dict:
    """Planeja as três opções; tabelas contêm TIR/preços já publicados por fazenda.

    ProFloresta usa os marcos e a reserva do mesmo modelo da previsão. Entradas
    completas são lidas só para os membros selecionados, quando origens é informado.
    """
    inicio = time.monotonic()
    recorte = normalizar_recorte(**asdict(recorte))
    if not modelo or not cenario:
        raise ValueError("Modelo e cenário são obrigatórios.")
    destino = Path(destino)
    C._diretorio(destino)
    pedido = pedido.model_copy(deep=True)
    pedido.onde.ufs, pedido.onde.biomas = list(recorte.ufs), list(recorte.biomas)
    pedido.onde.municipios = [str(m) for m in recorte.municipios]
    catalogo_dados, arquivos = C.abrir_catalogo(catalogo, conferir_hashes=conferir_hashes)
    pedido_efetivo, contrato, regra, cenario_financeiro = preparar_contrato(pedido, modelo, cenario, chance_alvo)
    fontes_selecionadas = {int(k): Path(v) for k, v in (origens or {}).items()}
    tempos = {"abrir_catalogo_s": time.monotonic() - inicio}
    consulta = {
        "catalogo_id": catalogo_dados["id"],
        "pedido": pedido.model_dump(),
        "recorte": asdict(recorte),
        "modelo": modelo,
        "cenario": cenario,
        "versao": versao_nacional(),
        "somente_comercializaveis": somente_comercializaveis,
        "limites": asdict(limites or S.LimitesSelecao()),
        "diametro_grupo_km": diametro_grupo_km,
        "max_membros_grupo": max_membros_grupo,
        "contrato": contrato,
        "fluxos_com_entradas": bool(fontes_selecionadas),
    }
    chave = hashlib.sha256(C._json(consulta)).hexdigest()
    pasta = destino / chave
    C._diretorio(pasta)
    # O resultado permanece imutável: nova medição pode usar outro diretório de destino.
    if (pasta / "resultado.json").exists():
        cache = json.loads((pasta / "resultado.json").read_text())
        for item in [cache["auditoria"], *[op["tabela"] for op in cache["opcoes"].values()]]:
            arquivo = Path(item["caminho"])
            if not arquivo.is_relative_to(pasta) or not arquivo.exists() or C.sha256(arquivo) != item["sha256"]:
                raise ValueError("Resultado em cache divergente do catálogo privado.")
        return cache
    with (
        tempfile.TemporaryDirectory(prefix="spill-lote-", dir=destino) as spill,
        duckdb.connect(config={"memory_limit": "1GB", "threads": 2, "temp_directory": spill}) as con,
    ):
        if arquivos:
            con.from_parquet(arquivos).create_view("oferta")
        else:
            con.register("oferta", pa.Table.from_pylist([], schema=C.SCHEMA))
        con.sql(f"CREATE TEMP VIEW recorte AS SELECT * FROM oferta WHERE {_filtro_recorte(recorte)}")
        _espacial(con, pedido)
        filtro = _filtro_pedido(pedido, modelo, cenario, somente_comercializaveis)
        con.sql(f"CREATE TEMP VIEW elegiveis AS SELECT * FROM recorte WHERE {filtro}")
        cobertura = _cobertura(catalogo_dados, recorte, con, modelo, cenario)
        t = time.monotonic()
        pontos = con.sql("select cod_imovel,lon,lat,pequena,local_aproximado from elegiveis").fetchdf()
        agrupados = S.agrupar_oferta(
            pontos,
            diametro_km=min(diametro_grupo_km, pedido.forma.distancia_max_km)
            if pedido.forma.distancia_max_km
            else diametro_grupo_km,
            max_membros=max_membros_grupo,
        )
        del pontos
        con.register("grupos", pa.Table.from_pandas(agrupados, preserve_index=False))
        del agrupados
        grupos = _agregar_grupos(con, pedido)
        tempos["filtrar_agrupar_s"] = time.monotonic() - t
        resultados, rotulos = {}, []
        for opcao in OPCOES:
            t = time.monotonic()
            selecao = S.selecionar_grupos(
                grupos, pedido_efetivo, opcao, limites=limites, reserva_meta=contrato.get("reserva_necessaria")
            )
            linhas = [
                {"grupo_id": g, "papel": papel}
                for papel, ids in (("titular", selecao["titulares"]), ("reserva", selecao["reservas"]))
                for g in ids
            ]
            tabela = pa.Table.from_pylist(linhas, schema=pa.schema([("grupo_id", pa.string()), ("papel", pa.string())]))
            con.register("selecao", tabela)
            con.sql(
                "CREATE OR REPLACE TEMP VIEW escolhidos AS SELECT e.*, g.grupo_id, g.agrupamento_pendente, s.papel "
                "FROM elegiveis e JOIN grupos g USING(cod_imovel) JOIN selecao s USING(grupo_id)"
            )
            totais = (
                con.sql(
                    "select count(*) fazendas, count(*) filter(where pequena) pequenas, "
                    "coalesce(sum(area_ha),0) area_ha from escolhidos"
                )
                .fetchdf()
                .iloc[0]
                .to_dict()
            )
            tabela_info = _gravar_parquet(
                con, "select * from escolhidos order by cod_imovel", pasta / f"{opcao}.parquet"
            )
            faixa = _resumo_faixas(con)
            extras = {}
            if regra is not None:
                from raiz import restauracao as R

                v = contrato["volume_solicitado"]
                tit, res = selecao["quantidade_titulares"], selecao["quantidade_reservas"]
                cron_tit = R.cronograma_lote(tit, cenario_financeiro, regra, v)
                cron_lote = R.cronograma_lote(tit + res, cenario_financeiro, regra, v)
                for cron in (cron_tit, cron_lote):
                    for marco in cron["marcos"]:
                        marco["falta_p50"] = max(0.0, marco["limiar"] - marco["acumulado_p50"])
                extras.update(
                    cronograma_titulares=cron_tit,
                    cronograma_lote=cron_lote,
                    falta_p50=max(0.0, contrato["necessario_p50"] - tit),
                    falta_com_reserva=max(0.0, contrato["necessario_com_reserva"] - tit - res),
                    chance_alvo_atingida=cron_lote["chance_todos"] >= contrato["chance_alvo"],
                )
                if fontes_selecionadas:
                    from raiz.restauracao_nacional_financeiro import economia_selecionadas

                    _conferir_origens_selecionadas(con, catalogo_dados, fontes_selecionadas)
                    extras["economia"] = economia_selecionadas(
                        Path(tabela_info["caminho"]), fontes_selecionadas, c=cenario_financeiro, r=regra, volume=v
                    )
                else:
                    extras["economia"] = {
                        "situacao": "entradas_selecionadas_pendentes",
                        "motivo": "Fluxo agregado exige as entradas congeladas; não se usa média de TIR.",
                    }
            resultados[opcao] = {k: v for k, v in selecao.items() if k not in ("titulares", "reservas")}
            resultados[opcao].update(
                tabela=tabela_info,
                creditos=faixa,
                fazendas=int(totais["fazendas"]),
                pequenas=int(totais["pequenas"]),
                area_ha=float(totais["area_ha"]),
            )
            resultados[opcao].update(extras)
            rotulos.extend({"grupo_id": x["grupo_id"], "opcao": opcao, "papel": x["papel"]} for x in linhas)
            tempos[f"{opcao}_s"] = time.monotonic() - t
        con.register(
            "rotulos",
            pa.Table.from_pylist(
                rotulos, schema=pa.schema([("grupo_id", pa.string()), ("opcao", pa.string()), ("papel", pa.string())])
            ),
        )
        criterios = "Critérios do pedido: " + json.dumps(consulta, ensure_ascii=False, sort_keys=True)
        consulta_trilha = f"""select r.cod_imovel, r.restauracao_versao modelo_versao, g.grupo_id,
            {_sql(chave)} consulta_id, true revisao_humana_disponivel,
            'LGPD art. 20' fundamento_revisao,
            case when not ({filtro}) then
                {_motivos_pedido(pedido, modelo, cenario, somente_comercializaveis)}
                else 'Grupo indivisível avaliado por custo/risco/compacidade. Busca limitada; sem corte por tamanho.'
                end criterio_texto,
            {_sql(criterios)} parametros_texto,
            coalesce(max(case when s.opcao='barata' then s.papel end),'nao_selecionada') barata,
            coalesce(max(case when s.opcao='segura' then s.papel end),'nao_selecionada') segura,
            coalesce(max(case when s.opcao='compacta' then s.papel end),'nao_selecionada') compacta
            from recorte r left join grupos g using(cod_imovel) left join rotulos s using(grupo_id)
            group by all"""
        t = time.monotonic()
        auditoria = _gravar_parquet(con, consulta_trilha, pasta / "decisoes.parquet")
        tempos["auditoria_s"] = time.monotonic() - t
        pendencias = (
            con.sql(
                "select pendencias, count(*) fazendas, coalesce(sum(area_ha),0) hectares, "
                "coalesce(sum(credito_p50),0) creditos_centrais from recorte "
                "where pendencias != '' group by pendencias order by fazendas desc"
            )
            .fetchdf()
            .to_dict("records")
        )
    tempos["total_s"] = time.monotonic() - inicio
    resultado = {
        "acesso": "privado",
        "id": chave,
        **consulta,
        "cobertura": cobertura,
        "opcoes": resultados,
        "auditoria": auditoria,
        "pendencias": pendencias,
        "tempos": tempos,
        "cronograma_contratual_validado": regra is not None,
        "aviso": "Planejamento sobre cobertura disponível. Consulte os marcos e pendências antes de contratar. "
        "TIR P50 legada é central, não mediana; TIR do lote só existe com fluxo agregado.",
    }
    C.gravar_json(pasta / "resultado.json", resultado)
    return resultado
