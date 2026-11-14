"""Roda o motor município por município, sem editar motor/, com um lote vigiado por tarefa:

    funil   raiz_estado.municipio (CAR e SIGEF pela ponte com o espelho local)  -> saida/<UF>/imoveis_<mun>.csv
    filtros raiz_filtros.filtros                                                -> filtros_<mun>.csv
    direto  raiz_direto.direto (YbYrá e GPW direto dos arquivos públicos)      -> direto_<mun>.csv
    mapbiomas raiz_mapbiomas.por_imovel (API da Plataforma, colunas mb_*)       -> mapbiomas_<mun>.csv
    extras_direto raiz_extras_direto.municipio (JRC TMF e causas da perda)      -> extras_direto_<mun>.csv
    flag    raiz.flag.calcular_municipio (meta FLAG pela GHG LSR, fora do motor)   -> flag_<mun>.csv
    terra   raiz.terra (caminho da terra e risco, fora do motor)                   -> terra_<mun>.csv
    ficha   raiz.imovel_dados (design v1 do front: colunas e camadas no imóvel)   -> ficha_, camadas_<mun>
    rebanho raiz.rebanho (rebanho por fazenda pela PPM e metano, E4, fora do motor) -> rebanho_<mun>.csv
    desenvolvedor raiz.restauracao (valor para quem restaura, fora do motor)      -> desenvolvedor_<mun>.csv
    carga   raiz.carga.carregar_municipio + congelamento das previsões (versão do motor confirmada)

Cada tarefa de cada município pinga o Healthchecks (início, sucesso, falha com log) e fica em operacao.lote.
Falha num município não para os outros. Retoma de onde parou: arquivo pronto é pulado (salvo --refazer).
Vários municípios ao mesmo tempo como o motor (processos com fork; padrão 3 na máquina de 4 núcleos).

Nada passa pelo Earth Engine: cobertura e desmatamento do estado (regeneração no funil e colunas mb_*) vêm da API da
Plataforma MapBiomas, pedidos uma vez por estado antes de repartir os municípios; o TMF e as causas da perda também
são preparados uma vez (índice dos blocos do TMF e arquivo de 295 MB das causas). extras_<mun>.csv é histórico fixo.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from raiz import MOTOR_DIR
from raiz.config import config

log = logging.getLogger(__name__)

TAREFAS = (
    "funil", "filtros", "direto", "mapbiomas", "extras_direto", "flag", "terra", "titulo", "ficha", "rebanho",
    "desenvolvedor",
    "carga",
)  # fmt: skip


@dataclass
class Opcoes:
    uf: str
    tarefas: tuple[str, ...] = TAREFAS
    refazer: bool = False
    data_corte: dt.date = field(default_factory=dt.date.today)
    espelho: str | None = None
    banco_url: str | None = None
    banco: bool = True  # False: sem registro em operacao.lote (o executor no GitHub Actions guarda tudo na marca)


_R = None  # módulo raiz_estado (importado depois do chdir)
_EMB = None  # embargos do Ibama, carregados uma vez antes do fork
_ENGINE = None
_MB_ARQ = None  # GeoTIFFs do MapBiomas do estado (motor/raiz_mapbiomas.exporta_uf), pedidos uma vez antes do fork
_TMF = None  # índice dos blocos do JRC TMF (motor/raiz_extras_direto.tmf_tiles), lido uma vez antes do fork
_CAUSAS = None  # arquivo das causas da perda (motor/raiz_extras_direto.drivers), baixado uma vez antes do fork


def dir_trabalho() -> Path:
    return Path(config().motor_dir_trabalho) if config().motor_dir_trabalho else MOTOR_DIR


def preparar_motor(carregar_embargos: bool = True):
    """chdir para a pasta de trabalho do motor (ele usa caminhos relativos) e importa raiz_estado."""
    global _R, _EMB
    os.chdir(dir_trabalho())
    if str(MOTOR_DIR) not in sys.path:
        sys.path.insert(0, str(MOTOR_DIR))
    import raiz_estado as R

    _R = R
    if carregar_embargos and _EMB is None:
        _EMB = R.embargos()
    return R


def _engine(url: str | None):
    global _ENGINE
    if _ENGINE is None:
        from sqlalchemy import create_engine

        _ENGINE = create_engine(url or config().banco_url, pool_pre_ping=True)
    return _ENGINE


def _escrever_csv(df, caminho: Path, **kw) -> None:
    tmp = caminho.with_suffix(caminho.suffix + f".{os.getpid()}.tmp")
    df.to_csv(tmp, **kw)
    os.replace(tmp, caminho)


def rodar_municipio(cod: int, op: Opcoes, hc=None) -> dict:
    """Roda as tarefas pedidas para um município. Devolve {tarefa: estado}."""
    from raiz.funil.ponte import ler_local, ponte, ponte_vetorial
    from raiz.operacao.healthchecks import Healthchecks
    from raiz.operacao.lotes import lote

    R = _R or preparar_motor()
    hc = hc or Healthchecks()
    eng = _engine(op.banco_url) if op.banco else None
    uf = op.uf.upper()
    pasta = Path(f"saida/{uf}")
    pasta.mkdir(parents=True, exist_ok=True)
    res: dict[str, str] = {}
    captura = None

    def executar(tarefa: str, saida: Path | None, fn) -> bool:
        nonlocal captura
        if tarefa not in op.tarefas:
            return True
        try:
            with lote(eng, hc, tarefa, uf, cod) as reg, contextlib.redirect_stdout(reg.saida):
                if saida is not None and saida.exists() and not op.refazer:
                    reg.pulado = True
                    reg.nota(f"{saida.name} já existe")
                else:
                    from raiz.aprendizado.captura import Captura

                    captura = Captura(uf, cod)
                    with captura.modelos() if captura else contextlib.nullcontext():
                        fn(reg)
                    if eng is not None:
                        with eng.begin() as con:
                            reg.detalhe["historico_aprendizado"] = captura.publicar(con)
                    else:
                        from raiz.aprendizado.retratos import guardar

                        reg.detalhe["historico_aprendizado"] = guardar(captura, tarefa)
            res[tarefa] = "pulado" if reg.pulado else "sucesso"
            return True
        except Exception as ex:  # noqa: BLE001 - o lote já registrou e pingou a falha
            res[tarefa] = f"falha: {type(ex).__name__}"
            return False

    def funil(reg):
        with ponte(R, uf, cod, op.espelho) as origem:
            with captura.motor(R, _EMB) if captura else contextlib.nullcontext():
                c, nome = R.municipio(uf, cod, _EMB, str(pasta))
        reg.detalhe.update(origem=origem)
        if c is None:
            reg.nota(f"{cod}: nenhum imóvel IRU ativo")
            reg.pulado = True
            return
        _escrever_csv(c, pasta / f"imoveis_{cod}.csv")
        reg.detalhe.update(municipio=nome, imoveis=len(c))

    def filtros(reg):
        import raiz_filtros
        from raiz_extras import geometria

        from raiz.funil.filtros import calcular, embargos_ativos
        from raiz.funil.ponte import espelho_padrao

        espelho = Path(op.espelho) if op.espelho else espelho_padrao()
        embargos = ler_local(espelho, "ibama", uf, cod)
        if embargos is None:
            embargos = _EMB if _EMB is not None else R.embargos()
        t = calcular(geometria(uf, cod, str(pasta)), raiz_filtros, embargos_ativos(embargos, cod), conexao_vetorial())
        _escrever_csv(t, pasta / f"filtros_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t), bloqueio=int((t.filtro_territorial == "bloqueio").sum()))

    def direto(reg):
        import raiz_direto
        from raiz_extras import geometria

        from raiz.funil.ponte import ponte_raster

        with ponte_raster(raiz_direto):  # blocos do YbYrá e do GPW em cache no disco
            t = raiz_direto.direto(geometria(uf, cod, str(pasta)))
        _escrever_csv(t, pasta / f"direto_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t))

    def carga(reg):
        from raiz.aprendizado.congelar import congelar_rodada
        from raiz.carga import carregar_municipio, depois_da_carga

        with eng.begin() as con:
            r = carregar_municipio(con, pasta.resolve(), cod, op.data_corte, motor_confirmado=True)
            lh, novo, n = congelar_rodada(con, r.rodada_id)
        depois_da_carga(eng, cod, estrito=True)
        reg.detalhe.update(rodada=r.rodada_id, nova=r.nova, previsoes=n if novo else 0, colunas_novas=r.colunas_novas)

    def mapbiomas(reg):
        import raiz_mapbiomas

        arq = _MB_ARQ or raiz_mapbiomas.exporta_uf(uf)
        t = raiz_mapbiomas.por_imovel(uf, cod, str(pasta), arq)
        _escrever_csv(t, pasta / f"mapbiomas_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t), ano=raiz_mapbiomas.ANO)

    def extras_direto(reg):
        import raiz_extras_direto as X

        tiles = _TMF if _TMF is not None else X.tmf_tiles()
        t = X.municipio(uf, cod, str(pasta), tiles, _CAUSAS or X.drivers())
        _escrever_csv(t, pasta / f"extras_direto_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t), tmf_ano=X.TMF_ANO, com_causa=int(t.causa_perda.between(1, 7).sum()))

    def flag(reg):
        from raiz import flag as F

        f = pasta / f"flag_{cod}.csv"
        if f.exists() and not op.refazer and F.versao_do_arquivo(f) == F.versao():
            reg.pulado = True
            reg.nota(f"{f.name} já está na regra {F.versao()}")
            return
        t = F.calcular_municipio(pasta, cod, F.vigor_do_estado(uf, Path("cache")))
        _escrever_csv(t, f, index=False)
        reg.detalhe.update(imoveis=len(t), regra=F.versao(), flag_tco2_ano=round(float(t.flag_tco2_ano.sum()), 1))

    def terra(reg):
        from raiz import terra as T

        f = pasta / f"terra_{cod}.csv"
        if f.exists() and not op.refazer and T.versao_do_arquivo(f) == T.versao():
            reg.pulado = True
            reg.nota(f"{f.name} já está na regra {T.versao()}")
            return
        reg.detalhe.update(T.escrever_municipio(pasta, cod, Path("cache")), regra=T.versao())

    def titulo(reg):
        from raiz.titulo import tarefa as TT

        f = pasta / f"titulo_{cod}.csv"
        if f.exists() and not op.refazer and TT.versao_do_arquivo(f) == TT.versao():
            reg.pulado = True
            reg.nota(f"{f.name} já está na versão {TT.versao()}")
            return
        reg.detalhe.update(TT.escrever_municipio(pasta, cod), versao=TT.versao())

    def ficha(reg):
        from raiz.imovel_dados import escrever_municipio

        reg.detalhe.update(escrever_municipio(pasta, cod, Path("cache")))

    def rebanho(reg):
        from raiz import rebanho as RB

        f = pasta / f"rebanho_{cod}.csv"
        if f.exists() and not op.refazer and RB.versao_do_arquivo(f) == RB.versao():
            reg.pulado = True
            reg.nota(f"{f.name} já está na versão {RB.versao()}")
            return
        reg.detalhe.update(RB.escrever_municipio(pasta, cod))

    def desenvolvedor(reg):
        from raiz import restauracao as RS

        f = pasta / f"desenvolvedor_{cod}.csv"
        if f.exists() and not op.refazer and RS.versao_do_arquivo(f) == RS.versao():
            reg.pulado = True
            reg.nota(f"{f.name} já está na versão {RS.versao()}")
            return
        reg.detalhe.update(RS.escrever_municipio(pasta, cod, Path("cache")), versao=RS.versao())

    vetorial = ponte_vetorial(R) if {"funil", "filtros"} & set(op.tarefas) else contextlib.nullcontext()
    with vetorial as conexao_vetorial:
        imoveis = pasta / f"imoveis_{cod}.csv"
        if not executar("funil", imoveis, funil) or not imoveis.exists():
            return res
        executar("filtros", pasta / f"filtros_{cod}.csv", filtros)
        executar("direto", pasta / f"direto_{cod}.csv", direto)
        executar("mapbiomas", pasta / f"mapbiomas_{cod}.csv", mapbiomas)
        executar("extras_direto", pasta / f"extras_direto_{cod}.csv", extras_direto)
        executar("flag", None, flag)  # refaz quando a versão da regra muda
        executar("terra", None, terra)  # caminho da terra; refaz quando a regra ou as concessões mudam
        executar("titulo", None, titulo)  # regularização da posse e achados de título; refaz quando a regra muda
        executar("ficha", pasta / f"ficha_{cod}.csv", ficha)
        executar("rebanho", None, rebanho)  # rebanho por fazenda (E4); refaz quando a PPM ou as premissas mudam
        executar("desenvolvedor", None, desenvolvedor)  # refaz quando a versão das premissas ou do cenário muda
        executar("carga", None, carga)
    return res


def _trabalhador(args):
    cod, op = args
    return cod, rodar_municipio(cod, op)


def preparar_estado(op: Opcoes) -> None:
    """Downloads do estado feitos uma vez, antes do fork (senão cada processo pediria o mesmo à API):
    MapBiomas Alerta (WFS público, motor/raiz_estado.garantir_alertas), MapBiomas (todos os temas para as colunas mb_*,
    ou só cobertura e desmatamento para a regeneração do funil), índice do TMF e arquivo das causas da perda.
    Sem o Alerta ou sem o MapBiomas o funil não roda (as colunas problema e frente sairiam erradas sem aviso), como no
    motor: o erro sobe e o estado tenta de novo na próxima rodada. RAIZ_ALERTA_OBRIGATORIO=0 e RAIZ_MB_OBRIGATORIO=0
    deixam seguir sem (no computador). Os processos não pedem de novo cada um (RAIZ_MB_BAIXAR=0)."""
    global _MB_ARQ, _TMF, _CAUSAS
    uf = op.uf.upper()
    if "funil" in op.tarefas and op.espelho is None:
        from raiz.coleta.car_nacional import preparar

        preparar(uf)
    if "funil" in op.tarefas and hasattr(_R, "garantir_alertas"):
        try:
            _R.garantir_alertas(uf)
        except Exception as ex:  # noqa: BLE001
            if os.environ.get("RAIZ_ALERTA_OBRIGATORIO", "1") == "1":
                raise RuntimeError(
                    f"MapBiomas Alerta de {uf} não baixou ({ex}): o funil fica para a próxima rodada"
                ) from ex
            log.warning("MapBiomas Alerta falhou para %s: %s", uf, ex)
    if "mapbiomas" in op.tarefas or "funil" in op.tarefas:
        import raiz_mapbiomas

        temas = None if "mapbiomas" in op.tarefas else ("cobertura", "desmat")
        try:
            arq = raiz_mapbiomas.exporta_uf(uf, temas=temas)
            _MB_ARQ = arq if temas is None else _MB_ARQ
        except Exception as ex:  # noqa: BLE001
            if os.environ.get("RAIZ_MB_OBRIGATORIO", "1") == "1":
                raise RuntimeError(f"MapBiomas de {uf} não baixou ({ex}): fica para a próxima rodada") from ex
            log.warning("API do MapBiomas falhou para %s: %s", uf, ex)
        os.environ["RAIZ_MB_BAIXAR"] = "0"
    if "extras_direto" in op.tarefas:
        import raiz_extras_direto as X

        _TMF, _CAUSAS = X.tmf_tiles(), X.drivers()


def rodar(op: Opcoes, cods: list[int] | None = None, lanes: int | None = None) -> dict[int, dict]:
    """Roda vários municípios (todos da UF se `cods` vier vazio), `lanes` ao mesmo tempo."""
    import multiprocessing as mp

    R = preparar_motor(carregar_embargos=bool({"funil", "filtros"} & set(op.tarefas)))
    cods = cods or R.lista_municipios(op.uf.upper())
    preparar_estado(op)
    lanes = lanes or int(os.environ.get("LANES", "3"))
    if lanes <= 1:
        return {c: rodar_municipio(c, op) for c in cods}
    resultado = {}
    with mp.get_context("fork").Pool(lanes, maxtasksperchild=20) as pool:
        for cod, r in pool.imap_unordered(_trabalhador, [(c, op) for c in cods]):
            resultado[cod] = r
            log.info("%s %s: %s", op.uf, cod, r)
    return resultado
