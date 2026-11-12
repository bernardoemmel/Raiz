"""Resumo público do aprendizado, sem linhas, imóveis ou detalhes pagos.

As notas usam somente previsões maturadas, com gabarito posterior ao corte e
não futuro. Horizontes e tipos de nota não são misturados. Um grupo só aparece
com cinco imóveis distintos observados; nenhuma contagem de grupos suprimidos
é divulgada. O placar interno e o hub completo continuam autenticados.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Engine, text

from raiz.aprendizado import acerto

MINIMO_IMOVEIS = 5
IDENTIFICADOR = re.compile(r"[A-Za-z][A-Za-z0-9_.+:-]{0,119}\Z")


def _dia(valor) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def resumir(linhas: Iterable[Mapping], agora: dt.datetime | None = None) -> dict:
    """Allowlist positiva: só métricas agregadas, versões e datas do grupo."""
    agora = agora or dt.datetime.now(dt.UTC)
    grupos: dict[tuple, list] = defaultdict(list)
    for r in linhas:
        ids = tuple(str(r.get(k, "")) for k in ("modelo", "modelo_versao", "alvo"))
        # Versões podem começar por dígitos, mas não recebem texto livre.
        if not IDENTIFICADOR.fullmatch(ids[0]) or not IDENTIFICADOR.fullmatch(ids[2]):
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+:-]{0,119}", ids[1]):
            continue
        avaliacao = r.get("tipo")
        if avaliacao not in {"ao_vivo", "backtest"}:
            continue
        horizonte = r.get("horizonte_dias")
        corte, fim, observado = (_dia(r.get(k)) for k in ("data_corte", "horizonte_em", "observado_em"))
        if not isinstance(horizonte, int) or horizonte < 0 or not corte or not fim or fim > agora.date():
            continue
        if not observado or not corte < observado <= agora.date() or not r.get("gabarito_id"):
            continue
        if not r.get("cod_imovel") or not r.get("gabarito_fonte"):
            continue
        numeros = [r.get(k) for k in ("valor_num", "real_num", "p10", "p50", "p90")]
        if any(v is not None and not math.isfinite(v) for v in numeros):
            continue
        if all(r.get(k) is not None for k in ("p10", "p50", "p90")) and not r["p10"] <= r["p50"] <= r["p90"]:
            continue
        nota = acerto.nota(r)
        if nota is None or any(not math.isfinite(v) for k, v in nota.items() if k != "tipo"):
            continue
        grupos[(*ids, horizonte, nota["tipo"], avaliacao)].append((r, nota))
    versoes = []
    for (modelo, versao, alvo, horizonte, tipo, avaliacao), pares in sorted(grupos.items()):
        if len({r["cod_imovel"] for r, _ in pares}) < MINIMO_IMOVEIS:
            continue
        metricas = {m: round(sum(n[m] for _, n in pares) / len(pares), 6) for m in acerto.METRICAS[tipo]}
        versoes.append(
            {
                "modelo": modelo,
                "versao": versao,
                "alvo": alvo,
                "horizonte_dias": horizonte,
                "tipo": tipo,
                "avaliacao": avaliacao,
                "comparacoes": len(pares),
                "imoveis_observados": len({r["cod_imovel"] for r, _ in pares}),
                "primeiro_corte": str(min(_dia(r["data_corte"]) for r, _ in pares)),
                "ultimo_corte": str(max(_dia(r["data_corte"]) for r, _ in pares)),
                "ultima_observacao": str(max(_dia(r["observado_em"]) for r, _ in pares)),
                "metricas": metricas,
            }
        )
    return {
        "schema": "raiz.acerto.publico.v1",
        "gerado_em": agora.isoformat(),
        "fonte": "Banco de aprendizado da Raíz",
        "minimo_imoveis": MINIMO_IMOVEIS,
        "versoes": versoes,
    }


def ler(engine: Engine) -> dict:
    with engine.connect() as con:
        # Empurra o corte para o banco antes de parear/materializar previsões ainda sem resultado.
        linhas = con.execute(
            text("""
            select modelo, modelo_versao, alvo, tipo, horizonte_dias, cod_imovel,
                   data_corte, horizonte_em, observado_em, gabarito_id, gabarito_fonte,
                   valor_num, valor_texto, real_num, real_texto, p10, p50, p90
            from aprendizado.previsao_contra_gabarito
            where horizonte_em <= current_date
              and observado_em > data_corte and observado_em <= current_date
              and gabarito_id is not null and gabarito_fonte is not null and gabarito_fonte <> ''
              and tipo in ('ao_vivo', 'backtest')
        """)
        ).mappings()
        return resumir(linhas)


def exportar(engine: Engine, destino: str | Path) -> None:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(ler(engine), ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def roteador(engine_de):
    r = APIRouter(tags=["aprendizado"])
    cache = {}
    trava = threading.Lock()

    @r.get("/acerto/resumo")
    def resumo(request: Request):
        # Guarda apenas a projeção pública por cinco minutos; concorrência não repete a varredura.
        engine = engine_de(request)
        with trava:
            if cache.get("engine") is not engine or time.monotonic() >= cache.get("expira", 0):
                dado = ler(engine)
                cache.update(engine=engine, dado=dado, expira=time.monotonic() + 300)
            return JSONResponse(cache["dado"], headers={"Cache-Control": "public, max-age=300"})

    return r
