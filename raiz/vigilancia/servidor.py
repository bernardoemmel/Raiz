"""Servidor só da vigilância, para usar antes de as rotas entrarem no back-end (raiz/api.py).

    RAIZ_API_TOKEN=... RAIZ_VIGILANCIA_CHAVE=... python -m raiz.vigilancia servir --porta 8010

Com RAIZ_VIGILANCIA_BAIXAR=1 (padrão), baixa o estado publicado no Release ao subir e em POST /vigilancia/atualizar.
Todas as rotas pedem `Authorization: Bearer <RAIZ_API_TOKEN>`; sem o token configurado, ficam fechadas (503), como
no back-end.
"""

from __future__ import annotations

import contextlib
import hmac
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException

from raiz.vigilancia import api, publicacao
from raiz.vigilancia.servico import Vigilancia

log = logging.getLogger(__name__)


def _exigir_token(authorization: str | None = Header(default=None)) -> None:
    esperado = os.environ.get("RAIZ_API_TOKEN")
    if not esperado:
        raise HTTPException(503, "API fechada: defina RAIZ_API_TOKEN")
    dado = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(dado.encode(), esperado.encode()):
        raise HTTPException(401, "token inválido")


def criar_app(servico: Vigilancia | None = None, baixar: bool | None = None) -> FastAPI:
    estado = {"s": servico}
    baixar = os.environ.get("RAIZ_VIGILANCIA_BAIXAR", "1") == "1" if baixar is None else baixar

    def s() -> Vigilancia:
        if estado["s"] is None:
            estado["s"] = Vigilancia()
        return estado["s"]

    def sincronizar() -> dict:
        v = s()
        return publicacao.baixar_estado(v.arm, publicacao.Release(v.cfg), v.cfg.chave)

    @contextlib.asynccontextmanager
    async def ciclo(app: FastAPI):
        if baixar:
            try:
                log.info("estado da vigilância: %s", sincronizar())
            except Exception as ex:  # noqa: BLE001 (sobe com o estado local)
                log.warning("não baixei o estado publicado: %s", type(ex).__name__)
        try:
            yield
        finally:
            if limite is not None:
                await limite.fechar()
            if erros is not None:
                erros.fechar()

    app = FastAPI(title="Raíz: vigilância", lifespan=ciclo)
    from raiz.config import config
    from raiz.limites import do_config as limite_do_config
    from raiz.observabilidade import do_config as erros_do_config
    from raiz.privacidade import configurar_log
    from raiz.seguranca_api import SegurancaAPI

    configurar_log()
    limite = limite_do_config(config())
    erros = erros_do_config(config())
    app.add_middleware(
        SegurancaAPI,
        limite=int(os.environ.get("RAIZ_API_LIMITE_MINUTO", "120")),
        backend=limite,
        erros=erros,
    )
    seguro = [Depends(_exigir_token)]
    app.include_router(api.roteador(s), dependencies=seguro)

    @app.post("/vigilancia/atualizar", dependencies=seguro)
    def atualizar() -> dict:
        r = sincronizar()
        return {k: v for k, v in r.items() if k != "entradas"} | {"entradas": len(r.get("entradas", []))}

    return app
