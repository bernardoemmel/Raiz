"""Lote = uma tarefa num município (funil, filtros, direto, carga...). Registra em operacao.lote e pinga o
Healthchecks com o mesmo rid: início, sucesso, ou falha com o fim do log (mascarado)."""

from __future__ import annotations

import contextlib
import io
import json
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, text

from raiz import RAIZ_REPO
from raiz.logs_seguros import sanitizar_estrutura, sanitizar_log
from raiz.operacao.healthchecks import Healthchecks

log = logging.getLogger(__name__)


def _diagnostico(ex: Exception) -> dict:
    """Localiza a falha sem mensagem livre, fonte, variáveis ou dados pessoais."""
    quadros = []
    tb = ex.__traceback__
    while tb is not None:
        arquivo = Path(tb.tb_frame.f_code.co_filename).resolve()
        if arquivo.is_relative_to(RAIZ_REPO):
            quadros.append({"arquivo": str(arquivo.relative_to(RAIZ_REPO)), "linha": tb.tb_lineno})
        tb = tb.tb_next
    motivo = None
    if isinstance(ex, ValueError) and str(ex) in {
        "embargo ativo sem geometria poligonal válida; cálculo bloqueado",
        "embargo ativo com geometria ausente ou vazia; cálculo de restrições bloqueado",
        "embargo ativo sem geometria poligonal após reparo; cálculo de restrições bloqueado",
    }:
        motivo = "embargo_ativo_sem_geometria_utilizavel"
    return {"tipo": type(ex).__name__, "motivo": motivo, "quadros": quadros[-12:]}


@dataclass
class Registro:
    saida: io.StringIO = field(default_factory=io.StringIO)  # stdout do motor
    detalhe: dict = field(default_factory=dict)
    pulado: bool = False

    def nota(self, texto: str) -> None:
        self.saida.write(texto.rstrip() + "\n")


@contextlib.contextmanager
def lote(engine: Engine | None, hc: Healthchecks, tarefa: str, uf: str | None, cod_municipio: int | None):
    """Sem banco (engine None, ex.: no GitHub Actions), só pinga o Healthchecks: quem guarda o andamento é a marca do
    executor no armazém."""
    rid = str(uuid.uuid4())
    slug = hc.slug(tarefa, uf, cod_municipio)
    t0 = time.time()
    lote_id = None
    if engine is not None:
        with engine.begin() as con:
            lote_id = con.execute(
                text("insert into operacao.lote (tarefa, uf, cod_municipio, rid) values (:t, :u, :c, :r) returning id"),
                dict(t=tarefa, u=uf, c=cod_municipio, r=rid),
            ).scalar_one()
    hc.inicio(slug, rid, f"{tarefa} {uf} {cod_municipio}")
    reg = Registro()
    try:
        yield reg
    except Exception as ex:
        log.warning("falha da tarefa %s %s %s: %s", tarefa, uf, cod_municipio, json.dumps(_diagnostico(ex)))
        fim = sanitizar_log(reg.saida.getvalue()[-4000:] + "\n" + traceback.format_exc()[-4000:])
        _fechar(engine, lote_id, "falha", reg, fim, t0)
        hc.falha(slug, rid, f"{tarefa} {uf} {cod_municipio} FALHOU\n{fim}")
        raise
    else:
        estado = "pulado" if reg.pulado else "sucesso"
        fim = sanitizar_log(reg.saida.getvalue()[-4000:])
        _fechar(engine, lote_id, estado, reg, fim, t0)
        hc.sucesso(slug, rid, f"{tarefa} {uf} {cod_municipio} {estado}\n{json.dumps(reg.detalhe, default=str)}\n{fim}")


def _fechar(engine: Engine | None, lote_id: int | None, estado: str, reg: Registro, fim: str, t0: float) -> None:
    from psycopg.types.json import Jsonb

    if engine is None or lote_id is None:
        return
    with engine.begin() as con:
        con.execute(
            text("""update operacao.lote set estado = :e, detalhe = :d, log_final = :l, terminado_em = now(),
                            duracao_s = :s where id = :i"""),
            dict(
                e=estado,
                d=Jsonb(sanitizar_estrutura(json.loads(json.dumps(reg.detalhe, default=str)))),
                l=sanitizar_log(fim),
                s=round(time.time() - t0, 2),
                i=lote_id,
            ),
        )
