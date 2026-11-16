"""SIGEF por município (parcelas que tocam o retângulo do município no CAR), gravado no espelho por município.

Mesmo recorte que o motor usa (retângulo do CAR, eixo lat/lon com urn no WFS 2.0). A assinatura inclui esse
retângulo, contagem e data_aprovacao mais nova. Verifica mesmo quando o CAR não mudou; a assinatura só avança
depois de o espelho aceitar o retrato completo. Reconciliação periódica continua necessária para alterações que
não mexem na contagem nem na maior data (por exemplo, trocar uma parcela cancelada por outra).
"""

from __future__ import annotations

import datetime as dt
import json
import math
from dataclasses import dataclass

import pandas as pd
import requests
from sqlalchemy import Connection

from raiz.coleta import wfs
from raiz.coleta.espelho import Diferenca, Espelho, registrar_alertas
from raiz.coleta.manifesto import carregar
from raiz.coleta.replicacao import atualizar, estado, evento
from raiz.logs_seguros import sanitizar_log

FONTE = "sigef_parcelas"


@dataclass
class ResultadoSIGEF:
    acao: str
    diferenca: Diferenca | None = None
    contagem: int | None = None
    erro: str | None = None


def camada() -> wfs.Camada:
    f = carregar().fonte(FONTE)
    return wfs.Camada(f.url, f.model_extra["camada"], f.model_extra.get("versao_wfs", "2.0.0"))


def bbox_municipio(espelho: Espelho, uf: str, cod: int) -> str | None:
    """Caixa do CAR aceito, na mesma ordem lat/lon usada pela coleta e pelo motor."""
    car = espelho.ler("car", uf, cod)
    if car is None or not len(car):
        return None
    x0, y0, x1, y1 = car.to_crs(4674).total_bounds
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise ValueError("CAR sem retângulo válido para consultar SIGEF")
    return f"{y0},{x0},{y1},{x1},urn:ogc:def:crs:EPSG::4674"


def assinatura(s: requests.Session, bbox: str) -> tuple[str, int, str | None]:
    """Dois pedidos pequenos, sempre no mesmo recorte usado pelo download."""
    n, data = wfs.assinatura(s, camada(), "data_aprovacao", bbox=bbox).split("|", 1)
    n = int(n)
    ass = json.dumps({"bbox": bbox, "contagem": n, "mais_novo": data or None}, sort_keys=True)
    return ass, n, data or None


def coletar_municipio(
    s: requests.Session,
    espelho: Espelho,
    uf: str,
    cod: int,
    *,
    bbox: str | None = None,
    contagem: int | None = None,
    liberar: bool = False,
) -> Diferenca | None:
    bbox = bbox or bbox_municipio(espelho, uf, cod)
    if bbox is None:
        return None
    pagina = carregar().fonte(FONTE).model_extra.get("pagina", 5000)
    g = wfs.ler(s, camada(), "parcela_codigo", None, pagina, bbox=bbox)
    if contagem is not None and len(g) != contagem:
        raise wfs.LeituraIncompleta(f"SIGEF: recebidas {len(g)} de {contagem} parcelas da assinatura")
    if not len(g) and "parcela_codigo" not in g:
        g["parcela_codigo"] = pd.Series(dtype="string")
    if "parcela_codigo" not in g or g.parcela_codigo.isna().any() or g.parcela_codigo.duplicated().any():
        raise wfs.LeituraIncompleta("SIGEF: chave de parcela ausente ou repetida no retrato recebido")
    return espelho.gravar("sigef", uf, cod, g, "parcela_codigo", liberar=liberar)


def _falha(con: Connection, recorte: str, ex: Exception, agora: dt.datetime) -> str:
    e = estado(con, FONTE, recorte)
    # Erros de rede, parser ou banco podem carregar dados da fonte e credenciais.
    # Limpa antes de persistir o diagnóstico ou devolvê-lo ao chamador.
    erro = sanitizar_log(f"{type(ex).__name__}: {ex}")
    atualizar(
        con,
        FONTE,
        recorte,
        sujo=True,
        tentativas=(e.tentativas if e else 0) + 1,
        ultimo_erro=erro,
        verificado_em=agora,
    )
    evento(con, FONTE, recorte, "falha", detalhe={"erro": erro[:200]})
    return erro


def verificar_municipio(s: requests.Session, con: Connection, espelho: Espelho, uf: str, cod: int) -> bool:
    """Marca a fila sem substituir a assinatura do último retrato aceito."""
    uf, agora = uf.upper(), dt.datetime.now(dt.UTC)
    recorte = f"{uf}/{cod}"
    try:
        bbox = bbox_municipio(espelho, uf, cod)
        if bbox is None:
            return False
        ass, _, _ = assinatura(s, bbox)
        e = estado(con, FONTE, recorte)
        sujo = e is None or e.assinatura != ass or not espelho.caminho("sigef", uf, cod).exists()
        sujo = sujo or bool(e and e.sujo)
        atualizar(con, FONTE, recorte, sujo=sujo, verificado_em=agora)
        return sujo
    except Exception as ex:  # noqa: BLE001 - falha preserva a assinatura e volta à fila
        _falha(con, recorte, ex, agora)
        return True


def atualizar_municipio(
    s: requests.Session,
    con: Connection,
    espelho: Espelho,
    uf: str,
    cod: int,
    *,
    forcar: bool = False,
) -> ResultadoSIGEF:
    """Aceita uma nova versão por inteiro, ou mantém assinatura e espelho anteriores."""
    uf, agora = uf.upper(), dt.datetime.now(dt.UTC)
    recorte = f"{uf}/{cod}"
    try:
        bbox = bbox_municipio(espelho, uf, cod)
        if bbox is None:
            return ResultadoSIGEF("sem_recorte")
        ass, n, data = assinatura(s, bbox)
        e = estado(con, FONTE, recorte)
        if (
            not forcar
            and e is not None
            and not e.sujo
            and not getattr(e, "liberado", False)
            and e.assinatura == ass
            and espelho.caminho("sigef", uf, cod).exists()
        ):
            atualizar(con, FONTE, recorte, sujo=False, verificado_em=agora, tentativas=0, ultimo_erro=None)
            return ResultadoSIGEF("sem_mudanca", contagem=n)
        dif = coletar_municipio(
            s, espelho, uf, cod, bbox=bbox, contagem=n, liberar=bool(e and getattr(e, "liberado", False))
        )
        registrar_alertas(con, FONTE, recorte, dif)
        if dif.travado:
            msg = f"versão SIGEF travada; conferir e liberar com 'raiz coleta liberar {FONTE} {recorte}'"
            atualizar(con, FONTE, recorte, sujo=True, ultimo_erro=msg, verificado_em=agora)
            evento(con, FONTE, recorte, "alerta", detalhe={"trava": "arquivo", "fracao": round(dif.fracao, 3)})
            return ResultadoSIGEF("travado", dif, n, msg)
        atualizar(
            con,
            FONTE,
            recorte,
            assinatura=ass,
            contagem=n,
            cursor=data,
            sujo=False,
            liberado=False,
            tentativas=0,
            ultimo_erro=None,
            verificado_em=agora,
            coletado_em=agora,
        )
        for tipo, chaves in (("novos", dif.novos), ("mudaram", dif.mudaram), ("sumiram", dif.sumiram)):
            if chaves:
                evento(con, FONTE, recorte, tipo, len(chaves))
        return ResultadoSIGEF("completo", dif, n)
    except Exception as ex:  # noqa: BLE001 - o chamador encerra a transação antes de sinalizar a falha no lote
        return ResultadoSIGEF("falha", erro=_falha(con, recorte, ex, agora))
