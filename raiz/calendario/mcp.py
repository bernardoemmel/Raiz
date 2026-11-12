"""Ferramenta pronta para registrar no futuro servidor MCP; somente leitura pública."""

import datetime as dt
from zoneinfo import ZoneInfo

from raiz.calendario.banco import consultar


def proximos_eventos(
    tipo: str | None = None,
    estado: str | None = None,
    dias: int = 90,
    cod_imovel: str | None = None,
    limite: int = 100,
    *,
    engine=None,
    hoje: dt.date | None = None,
) -> dict:
    """Lista eventos dos próximos dias, fonte e confiança; não envia avisos nem altera dados."""
    if not 1 <= dias <= 3660 or not 1 <= limite <= 1000:
        raise ValueError("dias devem estar entre 1 e 3660; limite entre 1 e 1000")
    if engine is None:
        from raiz.banco import engine as padrao

        engine = padrao()
    hoje = hoje or dt.datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    with engine.connect() as con:
        return consultar(
            con,
            tipo=tipo,
            estado=estado.upper() if estado else None,
            cod_imovel=cod_imovel,
            inicio=hoje,
            fim=hoje + dt.timedelta(days=dias),
            limite=limite,
        )
