"""Consulta local equivalente à ferramenta registrada no MCP; somente leitura pública."""

import datetime as dt
from zoneinfo import ZoneInfo

from raiz.calendario.banco import consultar


def resposta_publica(dados: dict) -> dict:
    """Projeção positiva do calendário: preserva UID/CAR, nunca texto livre ou identificador privado."""
    from raiz.calendario.arquivos import envelope, validar

    if not isinstance(dados, dict) or not all(isinstance(dados.get(k), list) for k in ("eventos", "fontes")):
        raise ValueError("resposta do calendário inválida")
    eventos, fontes = validar(dados)
    total = dados.get("total")
    if type(total) is not int or total < len(eventos):
        raise ValueError("total de eventos inválido")
    resultado = envelope(eventos, fontes, limite=len(eventos) or 1)
    resultado["total"] = total
    return resultado


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
