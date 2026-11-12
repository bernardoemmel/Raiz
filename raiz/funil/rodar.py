"""Roda o motor município por município, sem editar motor/, com um lote vigiado por tarefa:

    funil   raiz_estado.municipio (CAR e SIGEF pela ponte com o espelho local)  -> saida/<UF>/imoveis_<mun>.csv
    filtros raiz_filtros.filtros                                                -> filtros_<mun>.csv
    direto  raiz_direto.direto (YbYrá e GPW direto dos arquivos públicos)      -> direto_<mun>.csv
    carga   raiz.carga.carregar_municipio + congelamento das previsões (versão do motor confirmada)

Cada tarefa de cada município pinga o Healthchecks (início, sucesso, falha com log) e fica em operacao.lote.
Falha num município não para os outros. Retoma de onde parou: arquivo pronto é pulado (salvo --refazer).
Vários municípios ao mesmo tempo como o motor (processos com fork; padrão 3 na máquina de 4 núcleos).
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

TAREFAS = ("funil", "filtros", "direto", "mapbiomas", "carga")


@dataclass
class Opcoes:
    uf: str
    tarefas: tuple[str, ...] = TAREFAS
    refazer: bool = False
    data_corte: dt.date = field(default_factory=dt.date.today)
    espelho: str | None = None
    banco_url: str | None = None


_R = None  # módulo raiz_estado (importado depois do chdir)
_EMB = None  # embargos do Ibama, carregados uma vez antes do fork
_ENGINE = None
_MB_ARQ = None  # GeoTIFFs do MapBiomas do estado (motor/raiz_mapbiomas.exporta_uf), pedidos uma vez antes do fork


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
    from raiz.funil.ponte import ponte
    from raiz.operacao.healthchecks import Healthchecks
    from raiz.operacao.lotes import lote

    R = _R or preparar_motor()
    hc = hc or Healthchecks()
    eng = _engine(op.banco_url)
    uf = op.uf.upper()
    pasta = Path(f"saida/{uf}")
    pasta.mkdir(parents=True, exist_ok=True)
    res: dict[str, str] = {}

    def executar(tarefa: str, saida: Path | None, fn) -> bool:
        if tarefa not in op.tarefas:
            return True
        try:
            with lote(eng, hc, tarefa, uf, cod) as reg, contextlib.redirect_stdout(reg.saida):
                if saida is not None and saida.exists() and not op.refazer:
                    reg.pulado = True
                    reg.nota(f"{saida.name} já existe")
                else:
                    fn(reg)
            res[tarefa] = "pulado" if reg.pulado else "sucesso"
            return True
        except Exception as ex:  # noqa: BLE001 - o lote já registrou e pingou a falha
            res[tarefa] = f"falha: {type(ex).__name__}"
            return False

    def funil(reg):
        with ponte(R, uf, cod, op.espelho) as origem:
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

        t = raiz_filtros.filtros(geometria(uf, cod, str(pasta)))
        _escrever_csv(t, pasta / f"filtros_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t), bloqueio=int((t.filtro_territorial == "bloqueio").sum()))

    def direto(reg):
        import raiz_direto
        from raiz_extras import geometria

        t = raiz_direto.direto(geometria(uf, cod, str(pasta)))
        _escrever_csv(t, pasta / f"direto_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t))

    def carga(reg):
        from raiz.aprendizado.congelar import congelar_rodada
        from raiz.carga import carregar_municipio

        with eng.begin() as con:
            r = carregar_municipio(con, pasta.resolve(), cod, op.data_corte, motor_confirmado=True)
            lh, novo, n = congelar_rodada(con, r.rodada_id)
        reg.detalhe.update(rodada=r.rodada_id, nova=r.nova, previsoes=n if novo else 0, colunas_novas=r.colunas_novas)

    def mapbiomas(reg):
        import raiz_mapbiomas

        arq = _MB_ARQ or raiz_mapbiomas.exporta_uf(uf)
        t = raiz_mapbiomas.por_imovel(uf, cod, str(pasta), arq)
        _escrever_csv(t, pasta / f"mapbiomas_{cod}.csv", index=False)
        reg.detalhe.update(imoveis=len(t), ano=raiz_mapbiomas.ANO)

    imoveis = pasta / f"imoveis_{cod}.csv"
    if not executar("funil", imoveis, funil) or not imoveis.exists():
        return res
    executar("filtros", pasta / f"filtros_{cod}.csv", filtros)
    executar("direto", pasta / f"direto_{cod}.csv", direto)
    executar("mapbiomas", pasta / f"mapbiomas_{cod}.csv", mapbiomas)
    executar("carga", None, carga)
    return res


def _trabalhador(args):
    cod, op = args
    return cod, rodar_municipio(cod, op)


def rodar(op: Opcoes, cods: list[int] | None = None, lanes: int | None = None) -> dict[int, dict]:
    """Roda vários municípios (todos da UF se `cods` vier vazio), `lanes` ao mesmo tempo."""
    import multiprocessing as mp

    global _MB_ARQ
    R = preparar_motor(carregar_embargos="funil" in op.tarefas)
    cods = cods or R.lista_municipios(op.uf.upper())
    if "mapbiomas" in op.tarefas:  # 5 pedidos por estado, uma vez, antes de repartir os municípios
        import raiz_mapbiomas

        _MB_ARQ = raiz_mapbiomas.exporta_uf(op.uf.upper())
    lanes = lanes or int(os.environ.get("LANES", "3"))
    if lanes <= 1:
        return {c: rodar_municipio(c, op) for c in cods}
    resultado = {}
    with mp.get_context("fork").Pool(lanes, maxtasksperchild=20) as pool:
        for cod, r in pool.imap_unordered(_trabalhador, [(c, op) for c in cods]):
            resultado[cod] = r
            log.info("%s %s: %s", op.uf, cod, r)
    return resultado
