"""Reexecuta modelos em retratos scd2 sem ler fontes ou caches atuais.

O catálogo informa a cobertura histórica conferida de cada fonte. Ausência de
histórico não significa ausência de embargo, floresta ou projeto: interrompe o
fold. As camadas ainda não arquivadas pela coleta precisam entrar no scd2 antes
de um backtest completo; nunca se substituem pelo arquivo disponível hoje.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from sqlalchemy import Connection, text

from raiz import MOTOR_DIR
from raiz.aprendizado.folds import como_estava
from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote


class HistoricoInsuficiente(ValueError):
    """Não há evidência histórica suficiente para calcular o fold."""


@dataclass(frozen=True)
class Especificacao:
    tabela: str
    campos: tuple[str, ...]
    chave: str | None = None
    municipal: bool = True
    geometria: bool = False
    campos_json: tuple[str, ...] = ()


# Lista fechada: nenhuma coluna de pessoa, mesmo se estiver presente no bruto.
FONTES = {
    "car": Especificacao("car_imovel", ("cod_imovel", "status_imovel", "tipo_imovel", "municipio", "m_fiscal",
                                       "_hash"), "cod_imovel", geometria=True),
    "sigef": Especificacao("sigef_parcela", ("parcela_codigo", "registro_matricula", "registro_cns",
                                            "situacao_informada", "natureza"), "parcela_codigo", geometria=True),
    "ibama": Especificacao("ibama_embargo", ("seq_tad", "cod_municipio", "sit_cancelado", "sit_desembargo",
                                             "geom_area_embargada"), "seq_tad"),
    "biomas": Especificacao("bioma", ("bioma",), municipal=False, geometria=True),
    "yd": Especificacao("prodes_anual", ("year", "main_class"), geometria=True),
    "acc": Especificacao("prodes_acumulado", (), geometria=True),
    "nf": Especificacao("nao_floresta", (), geometria=True),
    "hy": Especificacao("hidrografia", (), geometria=True),
    "ti": Especificacao("terra_indigena", (), geometria=True),
    "uc": Especificacao("unidade_conservacao", (), geometria=True),
    "projetos": Especificacao("projeto_carbono", (), geometria=True),
    "alertas": Especificacao("mapbiomas_alerta", ("anodetec",), geometria=True),
    # Zonal calculado com a geometria do CAR daquela versão (car_hash), arquivado
    # na data em que raster e CAR estavam disponíveis. Não basta o ano do raster.
    "regeneracao": Especificacao("mapbiomas_regeneracao", ("cod_imovel", "car_hash", "pasto_ha",
                                                            "secundaria_ha", "pasto_ate1km_ha"), "cod_imovel"),
}  # fmt: skip
FONTES_MOTOR = tuple(FONTES)
MODELOS = ("motor", "flag", "restauracao", "regularizacao", "triagem", "rebanho")
for _modelo in MODELOS[1:]:
    FONTES[f"entrada_{_modelo}"] = Especificacao(
        f"entrada_{_modelo}",
        ("cod_imovel", "atributos", "contexto"),
        "cod_imovel",
        campos_json=("atributos", "contexto"),
    )


def fontes_dos_modelos(modelos: tuple[str, ...]) -> tuple[str, ...]:
    if not modelos or set(modelos) - set(MODELOS):
        raise ValueError(f"modelos aceitos: {', '.join(MODELOS)}")
    nomes = set(FONTES_MOTOR) if "motor" in modelos else set()
    nomes.update(f"entrada_{m}" for m in modelos if m != "motor")
    return tuple(sorted(nomes))


@dataclass(frozen=True)
class Fonte:
    """Cobertura contínua conferida, inclusive das coletas que voltaram vazias."""

    desde: dt.datetime
    ate: dt.datetime
    referencia: str
    tabela: str | None = None
    esquema: str = "bruto"
    por_municipio: bool | None = None

    def __post_init__(self):
        if self.desde.tzinfo is None or self.ate.tzinfo is None:
            raise ValueError("a cobertura histórica exige data/hora com fuso")
        if self.desde > self.ate or not self.referencia.strip():
            raise ValueError("cobertura histórica inválida ou sem referência da conferência")
        for nome in (self.tabela or "bruto", self.esquema):
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", nome):
                raise ValueError("nome de tabela ou esquema inválido")


@dataclass
class Retrato:
    corte: dt.datetime
    cod_municipio: int
    uf: str
    dados: dict[str, pd.DataFrame]
    entradas_hash: str


def ler_catalogo(caminho: Path) -> dict[str, Fonte]:
    bruto = json.loads(caminho.read_text(encoding="utf-8"))
    if set(bruto) != {"fontes"}:
        raise ValueError("catálogo deve conter somente fontes")
    out = {}
    for nome, v in bruto["fontes"].items():
        if nome not in FONTES:
            raise ValueError(f"fonte desconhecida: {nome}")
        out[nome] = Fonte(
            **{**v, "desde": dt.datetime.fromisoformat(v["desde"]), "ate": dt.datetime.fromisoformat(v["ate"])}
        )
    return out


def ler_retrato(
    con: Connection,
    corte: dt.datetime,
    uf: str,
    cod_municipio: int,
    fontes: dict[str, Fonte],
    requeridas: tuple[str, ...] = FONTES_MOTOR,
) -> Retrato:
    """Cada consulta usa o intervalo [valid_from, valid_to), com o mesmo corte UTC."""
    if corte.tzinfo is None:
        raise ValueError("corte exige data/hora com fuso")
    faltam = set(requeridas) - set(fontes)
    if faltam:
        raise HistoricoInsuficiente(f"fontes sem cobertura histórica: {', '.join(sorted(faltam))}")
    corte = corte.astimezone(dt.UTC)
    dados, hashes = {}, {}
    for nome in requeridas:
        esp = FONTES[nome]
        f = fontes[nome]
        if not f.desde <= corte <= f.ate:
            raise HistoricoInsuficiente(f"{nome}: corte fora da cobertura histórica conferida")
        tabela = f.tabela or esp.tabela
        campos = list(esp.campos)
        if esp.geometria:
            campos.append("ST_AsBinary(geom) as geometry")
        q = como_estava(tabela, f.esquema).replace("select *", f"select {', '.join(campos)}", 1)
        if f.por_municipio if f.por_municipio is not None else esp.municipal:
            q += " and cod_municipio_ibge = :municipio"
        # Erro de tabela/coluna ausente sobe; nunca se tenta a view _vigente.
        df = pd.DataFrame(
            con.execute(text(q), {"corte": corte, "municipio": cod_municipio}).mappings().all(),
            columns=[*esp.campos, *(["geometry"] if esp.geometria else [])],
        )
        if esp.chave and (df[esp.chave].isna().any() or df[esp.chave].duplicated().any()):
            raise HistoricoInsuficiente(f"{nome}: chaves nulas ou versões sobrepostas no corte")
        serial = df.copy()
        if esp.geometria:
            serial["geometry"] = serial.geometry.map(lambda x: bytes(x).hex() if x is not None else None)
            geoms = shapely.from_wkb([bytes(x) if x is not None else None for x in df.geometry])
            df = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=geoms, crs=4674)
        # A ordem física e o fechamento posterior do scd2 não mudam o hash do retrato.
        linhas = sorted(
            json.dumps(r, sort_keys=True, default=str, ensure_ascii=False) for r in serial.to_dict("records")
        )
        hashes[nome] = hashlib.sha256("\n".join(linhas).encode()).hexdigest()
        dados[nome] = df
    if "car" in dados and dados["car"].empty:
        raise HistoricoInsuficiente("CAR sem imóveis no corte; não gerar lote vazio")
    manifesto = {
        "corte": corte.isoformat(),
        "uf": uf.upper(),
        "municipio": cod_municipio,
        "fontes": hashes,
        "cobertura": {n: fontes[n].referencia for n in requeridas},
    }
    h = hashlib.sha256(json.dumps(manifesto, sort_keys=True).encode()).hexdigest()
    return Retrato(corte, cod_municipio, uf.upper(), dados, h)


def _sem_rede(*args, **kwargs):
    raise HistoricoInsuficiente("o fold tentou consultar uma fonte atual")


def _motor_isolado():
    """Nova instância do módulo: não altera os caches globais do motor de produção."""
    spec = importlib.util.spec_from_file_location("raiz_estado_fold", MOTOR_DIR / "raiz_estado.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def motor_no_retrato(retrato: Retrato) -> pd.DataFrame:
    """Executa municipio() real; todas as leituras vêm do retrato, sem downloads."""
    d = retrato.dados
    car = d["car"].copy()
    if d["biomas"].empty:
        raise HistoricoInsuficiente("cartografia histórica dos biomas vazia")
    reg = d["regeneracao"].set_index("cod_imovel")
    hashes_car = car.set_index("cod_imovel")["_hash"].to_dict()
    for cod, h in reg.car_hash.items():
        if pd.isna(h) or hashes_car.get(cod) != h:
            raise HistoricoInsuficiente("zonal do MapBiomas não corresponde à versão histórica do CAR")
    numericas = ["pasto_ha", "secundaria_ha", "pasto_ate1km_ha"]
    valores = reg[numericas].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(valores).all() or (valores < 0).any():
        raise HistoricoInsuficiente("zonal histórico incompleto ou inválido")
    R = _motor_isolado()
    R.get = R.tb = R.garantir_alertas = R.mapbiomas = _sem_rede
    R.PROJ = d["projetos"].copy()
    R.car_mun = lambda uf, cod: car.drop(columns="_hash").copy()
    R.nome_municipio = lambda cod: str(cod)
    R.sigef = lambda bbox: d["sigef"].copy()
    R.biomas = lambda: d["biomas"].copy()
    R.camadas = lambda uf, bbox, so=None: (
        {n: d[n].copy() for n in ("yd", "acc", "nf", "hy", "ti", "uc")},
        list(d["biomas"].bioma.unique()),
    )
    R.alertas = lambda uf, bbox: d["alertas"].rename(columns={"anodetec": "ANODETEC"}).copy()

    def regeneracao(c, uf, min_ha=1):
        alvo = c.frente.isin(["carbono", "regularizar_antes", "assentamento_agrupado"])
        if not alvo.any():
            return c
        if any(cod not in reg.index for cod in c.index[alvo]):
            raise HistoricoInsuficiente("falta o zonal histórico de imóvel na frente de regeneração")
        for campo in numericas:
            c[campo] = reg[campo].reindex(c.index).where(alvo)
        c["carbono_ha"] = np.minimum(c.alem_RL_ha, c.pasto_ate1km_ha.fillna(0))
        c.loc[(c.frente == "carbono") & (c.pasto_ate1km_ha < min_ha), "frente"] = "carbono_so_plantio"
        return c

    R.regeneracao = regeneracao
    ibama = d["ibama"].rename(columns={c: c.upper() for c in d["ibama"].columns}).copy()
    ibama["COD_MUNICIPIO"] = pd.to_numeric(ibama.COD_MUNICIPIO, errors="raise").astype("Int64").astype(str)
    with tempfile.TemporaryDirectory(prefix="raiz-fold-") as pasta, contextlib.redirect_stdout(io.StringIO()):
        df, _ = R.municipio(retrato.uf, retrato.cod_municipio, ibama, pasta)
    if df is None:
        raise HistoricoInsuficiente("nenhum CAR IRU ativo no corte")
    df = df.reset_index()
    df["uf"] = retrato.uf
    return df


def _previsoes_motor(df: pd.DataFrame) -> list[Previsao]:
    from raiz.aprendizado.congelar import ALVOS_MOTOR, _valor

    out = []
    for a in ALVOS_MOTOR:
        if a.tabela != "resultado":
            continue
        # Contrato SQL usa minúsculas; o motor mantém RL no nome do CSV.
        coluna = {c.lower(): c for c in df.columns}.get(a.coluna)
        if coluna is None and a.coluna == "carbono_ha":
            # municipio() só gera esta coluna quando há frente de regeneração.
            continue
        if coluna is None:
            raise HistoricoInsuficiente(f"motor não entregou a coluna {a.coluna}")
        for cod, valor in df[["cod_imovel", coluna]].itertuples(index=False, name=None):
            vn, vt = _valor(a, valor)
            if vn is not None or vt is not None:
                out.append(Previsao(cod, a.nome, a.horizonte_dias, valor_num=vn, valor_texto=vt))
    return out


def _entradas(retrato: Retrato, modelo: str):
    from raiz.aprendizado.captura import sanitizar_entrada

    nome = f"entrada_{modelo}"
    if nome not in retrato.dados or retrato.dados[nome].empty:
        raise HistoricoInsuficiente(f"sem entradas históricas de {modelo}")
    for row in retrato.dados[nome].itertuples(index=False):
        atributos, contexto = sanitizar_entrada(nome, row.atributos, row.contexto)
        if atributos.get("cod_imovel") not in (None, row.cod_imovel):
            raise HistoricoInsuficiente("CAR da entrada não corresponde à chave do registro")
        yield {**atributos, "cod_imovel": row.cod_imovel}, contexto


def prever(retrato: Retrato, modelos: tuple[str, ...] = ("motor", "flag", "restauracao")) -> dict[str, tuple]:
    """Modelos atuais contra entradas históricas, como desafiantes.

    Cada modelo recebe sua entrada completa observada, inclusive complementos do
    MapBiomas e parâmetros geográficos; não troca falta de histórico por zero.
    Restauração não carrega a calibração nem a PTAX de hoje.
    """
    from raiz import flag, rebanho, restauracao
    from raiz.titulo import regularizacao, triagem
    from raiz.versoes import motor_versao

    fontes_dos_modelos(modelos)
    out = {}
    if "motor" in modelos:
        out["motor"] = (_previsoes_motor(motor_no_retrato(retrato)), motor_versao())
    if "flag" in modelos:
        ps = []
        for li, ctx in _entradas(retrato, "flag"):
            a = flag.por_imovel(li, ctx.get("pasto_baixo_vigor_ha"))
            ps.append(Previsao(li["cod_imovel"], "flag_tco2_ano", 365, valor_num=a["flag_tco2_ano"]))
        out["flag"] = (ps, flag.versao())
    if "restauracao" in modelos:
        from raiz.restauracao_aprendizado import ALVO_MODO, ALVOS

        ps = []
        with tempfile.TemporaryDirectory(prefix="raiz-fold-regra-") as pasta:
            vazio = Path(pasta) / "ausente.yaml"
            r = restauracao.regra(calibracao=vazio, cambio=vazio)
            for li, _ in _entradas(retrato, "restauracao"):
                a = restauracao.por_imovel(li, r=r)
                if a["restauracao_area_ha"] <= 0:
                    continue
                for alvo, (base, horizonte, _) in ALVOS.items():
                    ps.append(
                        Previsao(
                            li["cod_imovel"],
                            alvo,
                            horizonte,
                            p10=a[f"{base}_p10"],
                            p50=a.get(f"{base}_p50", a.get(base)),
                            p90=a[f"{base}_p90"],
                        )
                    )
                ps.append(Previsao(li["cod_imovel"], ALVO_MODO, 730, valor_texto=a["modo_restauracao"]))
        out["restauracao"] = (ps, f"{r['versao_completa']}-sem-calibracao")
    if "regularizacao" in modelos:
        ps = []
        for li, _ in _entradas(retrato, "regularizacao"):
            a, _ = regularizacao.avaliar(li)
            ch = a.get("regularizacao_chance_12m")
            if ch is not None:
                ps.append(
                    Previsao(
                        li["cod_imovel"],
                        regularizacao.ALVO,
                        regularizacao.HORIZONTE_DIAS,
                        valor_num=float(ch),
                        valor_texto=a["regularizacao_classe"],
                    )
                )
        out["regularizacao"] = (ps, regularizacao.versao())
    if "triagem" in modelos:
        ps = []
        for li, ctx in _entradas(retrato, "triagem"):
            a = triagem.triar(li, ctx["achados"])
            ch = a["titulo_triagem_chance_problema"]
            if ch is not None:
                ps.append(
                    Previsao(
                        li["cod_imovel"],
                        triagem.ALVO,
                        triagem.HORIZONTE_DIAS,
                        valor_num=float(ch),
                        valor_texto=a["titulo_triagem"],
                    )
                )
        out[triagem.MODELO] = (ps, triagem.versao())
    if "rebanho" in modelos:
        entradas = list(_entradas(retrato, "rebanho"))
        contextos = {json.dumps(ctx, sort_keys=True) for _, ctx in entradas}
        if len(contextos) != 1:
            raise HistoricoInsuficiente("totais históricos do rebanho divergem no mesmo município")
        totais = entradas[0][1]["totais"]
        linhas = rebanho.espalhar([li for li, _ in entradas], retrato.cod_municipio, totais=totais)
        ps = []
        for li in linhas:
            if "rebanho_cab_p50" in li:
                for alvo in ("rebanho_cab", "metano_tco2e_ano"):
                    ps.append(
                        Previsao(
                            li["cod_imovel"],
                            alvo,
                            365,
                            p10=li[f"{alvo}_p10"],
                            p50=li[f"{alvo}_p50"],
                            p90=li[f"{alvo}_p90"],
                        )
                    )
        out["rebanho"] = (ps, rebanho.versao())
    modulos = {
        "flag": flag,
        "restauracao": restauracao,
        "regularizacao": regularizacao,
        triagem.MODELO: triagem,
        "rebanho": rebanho,
    }
    for nome, modulo in modulos.items():
        if nome in out:
            ps, versao = out[nome]
            codigo = hashlib.sha256(Path(modulo.__file__).read_bytes()).hexdigest()[:12]
            out[nome] = (ps, f"{versao}+codigo-{codigo}")
    return out


def reexecutar(
    con: Connection,
    cortes: list[dt.datetime],
    uf: str,
    cod_municipio: int,
    fontes: dict[str, Fonte],
    modelos: tuple[str, ...] = ("motor", "flag", "restauracao"),
    congelar: bool = True,
) -> list[dict]:
    """Lotes separados por modelo e fold, idempotentes e imutáveis no registro E8."""
    from raiz import flag, rebanho, restauracao
    from raiz.aprendizado import captura
    from raiz.titulo import regularizacao, triagem

    fontes_dos_modelos(modelos)
    out = []
    receita = hashlib.sha256(
        b"\n".join(
            Path(p).read_bytes()
            for p in (
                __file__,
                captura.__file__,
                flag.__file__,
                restauracao.__file__,
                regularizacao.__file__,
                triagem.__file__,
                rebanho.__file__,
            )
        )
    ).hexdigest()
    for corte in cortes:
        for selecionado in modelos:
            try:
                retrato = ler_retrato(con, corte, uf, cod_municipio, fontes, fontes_dos_modelos((selecionado,)))
                previstos = prever(retrato, (selecionado,))
            except HistoricoInsuficiente as ex:
                out.append(
                    {
                        "corte": corte.isoformat(),
                        "modelo": selecionado,
                        "situacao": "historico_insuficiente",
                        "motivo": str(ex),
                        "previsoes": 0,
                        "novo": False,
                    }
                )
                continue
            for modelo, (ps, versao) in previstos.items():
                v = Versoes(
                    modelo,
                    versao,
                    retrato.entradas_hash,
                    corte.astimezone(dt.UTC).date(),
                    regras_versao=versao,
                    receita_hash=receita,
                    tipo="backtest",
                )
                lh, novo = (
                    registrar_lote(con, ps, v, f"reexecução scd2, município {cod_municipio}, corte {corte.isoformat()}")
                    if congelar and ps
                    else (None, False)
                )
                out.append(
                    {
                        "corte": corte.isoformat(),
                        "modelo": modelo,
                        "situacao": "ok",
                        "modelo_versao": versao,
                        "entradas_versao": retrato.entradas_hash,
                        "previsoes": len(ps),
                        "lote_hash": lh,
                        "novo": novo,
                    }
                )
    return out
