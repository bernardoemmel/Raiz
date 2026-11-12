"""Agenda do agente Dados.

- rodada COMPLETA uma vez por ano, quando muda a coleção do MapBiomas (o ano em motor/raiz_mapbiomas.py, ANO): refaz
  todos os municípios de todos os estados, com a coleção nova;
- rodada PARCIAL no resto do tempo (todo dia, depois da coleta): refaz só o que mudou, seja a versão de uma tarefa
  (motor ou regra do produto), seja uma fonte diária do município (CAR, SIGEF, embargos, alertas);
- depois de cada estado, o back-end espelha o armazém e carrega no banco.
`raiz executor ciclo` faz uma volta; `raiz executor vigiar` repete (ou cron: ver README).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time

from raiz import MOTOR_DIR
from raiz.executor.armazem import Armazem, ler_json, por_json

log = logging.getLogger(__name__)
CHAVE_COLECAO = "estado/colecao_mapbiomas.json"


def colecao_mapbiomas() -> str | None:
    """Ano da coleção do MapBiomas que o motor usa (lido do código, sem importar o motor)."""
    import os

    if os.environ.get("RAIZ_MB_ANO"):  # o motor também aceita o ano por variável de ambiente
        return os.environ["RAIZ_MB_ANO"]
    f = MOTOR_DIR / "raiz_mapbiomas.py"
    if not f.exists():
        return None
    m = re.search(r"^ANO\s*=\s*(?:int\(os\.environ\.get\([^,]+,\s*)?(\d{4})", f.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else None


def precisa_completa(armazem: Armazem, colecao: str | None = None) -> bool:
    colecao = colecao or colecao_mapbiomas()
    feita = (ler_json(armazem, CHAVE_COLECAO) or {}).get("colecao")
    return bool(colecao) and colecao != feita


def ciclo(executor, ufs: list[str], lanes: int = 1, carregar=None, completa: bool | None = None,
          preparar=None) -> dict:  # fmt: skip
    """Uma volta: decide completa ou parcial, roda cada estado (retomando) e, se pedido, carrega no banco."""
    a = executor.a
    colecao = colecao_mapbiomas()
    completa = precisa_completa(a, colecao) if completa is None else completa
    out = {"completa": completa, "colecao": colecao, "estados": {}}
    for uf in ufs:
        r = executor.rodar_uf(uf, refazer=completa, lanes=lanes, preparar=preparar)
        out["estados"][uf] = {k: r[k] for k in ("situacao", "total", "feitos", "rodados", "vazios")} | {
            "erros": len(r["erros"])
        }
        if carregar:
            out["estados"][uf]["carga"] = carregar([uf])
    if completa and colecao and all(e["erros"] == 0 for e in out["estados"].values()):
        por_json(a, CHAVE_COLECAO, {"colecao": colecao, "feita_em": dt.datetime.now(dt.UTC).isoformat()})
    return out


def vigiar(executor, ufs: list[str], intervalo_h: float = 24.0, lanes: int = 1, carregar=None, preparar=None,
           voltas: int | None = None, hc=None) -> None:  # fmt: skip
    """Repete o ciclo a cada intervalo. Pinga o Healthchecks no começo, no fim e na falha de cada volta."""
    import uuid

    from raiz.operacao.healthchecks import Healthchecks

    hc = hc or Healthchecks()
    slug = hc.slug("executor")
    n = 0
    while voltas is None or n < voltas:
        n += 1
        rid = str(uuid.uuid4())
        hc.inicio(slug, rid)
        try:
            r = ciclo(executor, ufs, lanes, carregar, preparar=preparar)
            erros = sum(e["erros"] for e in r["estados"].values())
            (hc.falha if erros else hc.sucesso)(slug, rid, f"{len(r['estados'])} estados, {erros} erros")
        except Exception as e:  # noqa: BLE001
            log.exception("ciclo do executor falhou")
            hc.falha(slug, rid, str(e)[:1000])
        if voltas is None or n < voltas:
            time.sleep(intervalo_h * 3600)
