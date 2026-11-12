"""Cliente do Healthchecks (BSD-3; serviço hospedado em healthchecks.io ou instância própria fora do servidor da Raíz).

Um check por tarefa (modelo de nome configurável, padrão "raiz-{tarefa}"): o plano gratuito do serviço hospedado tem
poucos checks, e o país tem mais de 5 mil municípios. Cada município é uma execução com seu próprio `rid`: início,
sucesso ou falha com o fim do log (mascarado). Checks novos são criados no primeiro ping (?create=1).
Se o Healthchecks não responder, o trabalho segue: alerta nunca derruba o lote.
"""

from __future__ import annotations

import logging

import httpx

from raiz.config import config
from raiz.privacidade import mascarar

log = logging.getLogger(__name__)
LIMITE_LOG = 10_000  # o Healthchecks guarda até 100 kB por ping; o fim do log é o que importa


class Healthchecks:
    def __init__(
        self,
        chave_ping: str | None = None,
        base: str | None = None,
        modelo_slug: str | None = None,
        cliente: httpx.Client | None = None,
    ):
        cfg = config()
        self.chave = chave_ping or (
            cfg.healthchecks_chave_ping.get_secret_value() if cfg.healthchecks_chave_ping else None
        )
        self.base = (base or cfg.healthchecks_url).rstrip("/")
        self.modelo_slug = modelo_slug or cfg.healthchecks_modelo_slug
        self._cliente = cliente or httpx.Client(timeout=10)

    @property
    def ativo(self) -> bool:
        return bool(self.chave)

    def slug(self, tarefa: str, uf: str | None = None, cod_municipio: int | None = None) -> str:
        return self.modelo_slug.format(tarefa=tarefa, uf=(uf or "br"), cod=cod_municipio or "").lower().strip("-")

    def _ping(self, slug: str, sufixo: str, rid: str, corpo: str = "") -> bool:
        if not self.ativo:
            return False
        url = f"{self.base}/{self.chave}/{slug}" + (f"/{sufixo}" if sufixo else "")
        try:
            r = self._cliente.post(
                url, params={"create": 1, "rid": rid}, content=mascarar(corpo)[-LIMITE_LOG:].encode("utf-8")
            )
            return r.status_code < 300
        except httpx.HTTPError as ex:
            log.warning("Healthchecks não respondeu (%s): o lote segue", type(ex).__name__)
            return False

    def inicio(self, slug: str, rid: str, corpo: str = "") -> bool:
        return self._ping(slug, "start", rid, corpo)

    def sucesso(self, slug: str, rid: str, corpo: str = "") -> bool:
        return self._ping(slug, "", rid, corpo)

    def falha(self, slug: str, rid: str, corpo: str = "") -> bool:
        return self._ping(slug, "fail", rid, corpo)
