"""Carga contínua das saídas do motor: estado por estado, município por município, conforme ficam prontas.

`raiz vigiar` varre saida/<UF>/ (todas as UFs que existirem) a cada intervalo:
- município com arquivos iguais aos da última carga (mesmo tamanho e data) é pulado sem ler nada;
- arquivo mexido há menos de ESTAVEL_S segundos fica para a próxima volta (o motor pode estar escrevendo);
- município novo ou reprocessado vira uma rodada nova (só ele muda; a rodada antiga fica guardada como versão
  anterior, e o vigente passa a apontar para a nova), com as previsões congeladas (E8);
- o resumo da UF (resumo_<UF>.csv) entra do mesmo jeito e põe todos os municípios na busca por nome.

Cada carga é um lote vigiado (operacao.lote e Healthchecks, tarefa "carga"); falha num município não para os outros.
As colunas são lidas pelo nome (raiz/contrato.py), e coluna nova vai para os atributos.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import time
from pathlib import Path

from sqlalchemy import Engine, text

from raiz.carga import (
    arquivos_do_municipio,
    carregar_municipio,
    carregar_resumo,
    depois_da_carga,
    municipios_na_pasta,
)

log = logging.getLogger(__name__)

ESTAVEL_S = 120


def assinatura(arquivos: dict[str, Path]) -> dict:
    return {t: [p.stat().st_size, p.stat().st_mtime_ns] for t, p in sorted(arquivos.items())}


def _estavel(arquivos: dict[str, Path], agora: float, estavel_s: float) -> bool:
    return all(agora - p.stat().st_mtime >= estavel_s for p in arquivos.values())


def _vista(engine: Engine, chave: str) -> dict | None:
    with engine.connect() as con:
        return con.execute(text("select assinatura from funil.arquivo_visto where chave = :c"), {"c": chave}).scalar()


def _marcar(con, chave: str, ass: dict, rodada_id: int | None) -> None:
    con.execute(
        text("""insert into funil.arquivo_visto (chave, assinatura, rodada_id) values (:c, cast(:a as jsonb), :r)
                on conflict (chave) do update set assinatura = excluded.assinatura, rodada_id = excluded.rodada_id,
                visto_em = now()"""),
        {"c": chave, "a": json.dumps(ass), "r": rodada_id},
    )


def ufs_na_saida(saida: Path) -> list[str]:
    if not saida.exists():
        return []
    return sorted(p.name for p in saida.iterdir() if p.is_dir() and re.fullmatch(r"[A-Z]{2}", p.name))


def varrer(
    engine: Engine,
    saida: str | Path,
    ufs: list[str] | None = None,
    data_corte: dt.date | None = None,
    motor_confirmado: bool = False,
    congelar: bool = True,
    estavel_s: float = ESTAVEL_S,
    hc=None,
    reprocessar: bool = False,
    reindexar_fontes: bool = True,
) -> dict:
    """Uma volta pela saída do motor. Devolve o que carregou, pulou, deixou esperando e o que falhou."""
    from raiz.aprendizado.congelar import congelar_rodada
    from raiz.operacao.healthchecks import Healthchecks
    from raiz.operacao.lotes import lote

    saida = Path(saida)
    hc = hc or Healthchecks()
    agora = time.time()
    res: dict = {"carregados": [], "pulados": 0, "esperando": [], "falhas": [], "resumos": []}
    for uf in ufs or ufs_na_saida(saida):
        pasta = saida / uf
        for cod in municipios_na_pasta(pasta):
            arqs = arquivos_do_municipio(pasta, cod)
            chave = f"{uf}/{cod}"
            ass = {**assinatura(arqs), "_pipeline_ficha": 1}
            if not reprocessar and _vista(engine, chave) == ass:
                res["pulados"] += 1
                continue
            if not _estavel(arqs, agora, estavel_s):
                res["esperando"].append(chave)
                continue
            try:
                with lote(engine, hc, "carga", uf, cod) as reg:
                    with engine.begin() as con:
                        r = carregar_municipio(con, pasta.resolve(), cod, data_corte, motor_confirmado=motor_confirmado)
                        if congelar and r.nova:
                            _, _, n = congelar_rodada(con, r.rodada_id)
                            reg.detalhe.update(previsoes=n)
                    depois_da_carga(engine, cod, estrito=True)
                    # Só confirma o checkpoint depois das tarefas pós-commit. A próxima
                    # volta retoma a mesma rodada se a oferta falhar, sem perder a falha.
                    with engine.begin() as con:
                        _marcar(con, chave, ass, r.rodada_id)
                    reg.detalhe.update(rodada=r.rodada_id, nova=r.nova, imoveis=r.imoveis)
                if r.nova:
                    res["carregados"].append(
                        {"chave": chave, "rodada": r.rodada_id, "nova": True, "imoveis": r.imoveis}
                    )
                else:  # data do arquivo mudou, conteúdo igual (mesmo hash): nada a carregar
                    res["pulados"] += 1
            except Exception as ex:  # noqa: BLE001 - o lote já registrou e avisou; segue para o próximo
                res["falhas"].append({"chave": chave, "erro": type(ex).__name__})
                log.warning("carga %s: %s", chave, type(ex).__name__)
        resumo = pasta / f"resumo_{uf}.csv"
        if resumo.exists():
            chave, ass = f"{uf}/resumo", assinatura({"resumo": resumo})
            if _vista(engine, chave) != ass and _estavel({"r": resumo}, agora, estavel_s):
                try:
                    with engine.begin() as con:
                        r = carregar_resumo(con, resumo, uf, data_corte)
                        _marcar(con, chave, ass, r.rodada_id)
                    res["resumos"].append({"uf": uf, "rodada": r.rodada_id, "nova": r.nova})
                except Exception as ex:  # noqa: BLE001 - mantém o checkpoint para tentar novamente
                    res["falhas"].append({"chave": chave, "erro": type(ex).__name__})
    if reindexar_fontes:
        from raiz.prospeccao_cobertura import reindexar

        res["fichas"] = reindexar(engine)
        for falha in res["fichas"]["falhas"]:
            res["falhas"].append({"chave": f"fichas/{falha['municipio']}", "erro": falha["erro"]})
        if res["fichas"]["pendente"] and not res["fichas"]["falhas"]:
            res["falhas"].append({"chave": "fichas", "erro": "ReindexacaoPendente"})
    return res


def vigiar(engine: Engine, saida: str | Path, intervalo_s: float = 300, **kw) -> None:  # pragma: no cover - laço
    while True:
        r = varrer(engine, saida, **kw)
        log.info(
            "carga contínua: %s carregados, %s pulados, %s esperando, %s falhas",
            len(r["carregados"]),
            r["pulados"],
            len(r["esperando"]),
            len(r["falhas"]),
        )
        time.sleep(intervalo_s)
