"""WhatsApp pela Cloud API com PyWa 4 (MIT).

- Entrada: o webhook (/whatsapp) recebe a mensagem; o contato é gravado com BSUID e telefone juntos (o telefone
  pode faltar quando o usuário usa nome de usuário) e a conversa de aceite em andamento é retomada.
- Saída: só mensagens aprovadas pelo fundador são enviadas, para o BSUID quando existe (senão, o telefone).
- Mensagem de quem não tem conversa em andamento vai para a fila de revisão, sem copiar o texto.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import Engine, text

from raiz.config import config
from raiz.pessoal import Cofre, destino_whatsapp, registrar_contato_whatsapp

log = logging.getLogger(__name__)


def criar_cliente(app=None):
    """Cliente PyWa; com `app` (FastAPI), registra o webhook em /whatsapp. None se não estiver configurado."""
    cfg = config()
    if not (cfg.whatsapp_phone_id and cfg.whatsapp_token):
        return None
    from pywa import WhatsApp

    kw = {}
    if app is not None:
        if not (cfg.whatsapp_verify_token and cfg.whatsapp_app_secret):
            raise RuntimeError("webhook do WhatsApp sem RAIZ_WHATSAPP_VERIFY_TOKEN e RAIZ_WHATSAPP_APP_SECRET")
        kw = dict(
            server=app,
            webhook_endpoint="/whatsapp",
            verify_token=cfg.whatsapp_verify_token.get_secret_value(),
            app_secret=cfg.whatsapp_app_secret.get_secret_value(),
            validate_updates=True,
        )
    return WhatsApp(phone_id=cfg.whatsapp_phone_id, token=cfg.whatsapp_token.get_secret_value(), **kw)


def conversa_ativa(con, contato_id: int) -> str | None:
    return con.execute(
        text("""
        select a.cod_imovel from negocio.aceite a
        join pessoal.contato_imovel ci on ci.cod_imovel = a.cod_imovel and ci.contato_id = :c
        where a.estado = 'em_andamento' order by a.atualizado_em desc limit 1"""),
        {"c": contato_id},
    ).scalar()


def receber(
    engine: Engine,
    grafo,
    deps,
    bsuid: str,
    wa_id: str | None,
    texto: str,
    parent_bsuid: str | None = None,
    username: str | None = None,
    cofre: Cofre | None = None,
) -> dict:
    """Trata uma mensagem recebida. Devolve o que aconteceu (sem o texto)."""
    from raiz.agentes import aceite

    with engine.begin() as con:
        contato_id = registrar_contato_whatsapp(con, bsuid, wa_id, parent_bsuid, username, cofre=cofre)
        cod = conversa_ativa(con, contato_id)
    if cod is None:
        _sem_conversa(engine, contato_id, "mensagem de contato sem conversa de aceite em andamento")
        return {"contato_id": contato_id, "acao": "revisao"}
    p = aceite.pausa(grafo, cod, deps)
    if p is None or p.get("etapa") not in aceite.ETAPAS_DO_DONO:
        _sem_conversa(engine, contato_id, f"dono escreveu enquanto a conversa esperava '{(p or {}).get('etapa')}'", cod)
        return {"contato_id": contato_id, "cod_imovel": cod, "acao": "revisao"}
    aceite.responder(grafo, deps, cod, texto)
    return {"contato_id": contato_id, "cod_imovel": cod, "acao": "retomada", "etapa": p["etapa"]}


def imoveis_da_sede(con, contato_id: int) -> list[str]:
    """Imóveis do contato com aceite em andamento ou aceito, o do pedido de localização mais recente primeiro."""
    return list(
        con.execute(
            text("""
            select a.cod_imovel from negocio.aceite a
            join pessoal.contato_imovel ci on ci.cod_imovel = a.cod_imovel and ci.contato_id = :c
            left join lateral (select max(m.id) as pedido from pessoal.mensagem_saida m
                               where m.contato_id = :c and m.cod_imovel = a.cod_imovel and m.tipo = 'pedido_sede') p
                   on true
            where a.estado in ('em_andamento', 'aceito')
            order by p.pedido desc nulls last, a.atualizado_em desc"""),
            {"c": contato_id},
        ).scalars()
    )


def receber_localizacao(
    engine: Engine,
    bsuid: str,
    wa_id: str | None,
    lon: float,
    lat: float,
    parent_bsuid: str | None = None,
    username: str | None = None,
    cofre: Cofre | None = None,
) -> dict:
    """Localização mandada pelo dono: confere se cai dentro de um imóvel dele com aceite (raiz/titulo/sede.py).
    Só o resultado fica guardado, nunca o ponto. Com mais de um imóvel, vale o que contém o ponto; se nenhum
    contém, o resultado fica no imóvel do pedido mais recente."""
    from raiz.titulo import sede

    with engine.begin() as con:
        contato_id = registrar_contato_whatsapp(con, bsuid, wa_id, parent_bsuid, username, cofre=cofre)
        cods = imoveis_da_sede(con, contato_id)
        res = sede.registrar_varios(con, cods, lon, lat) if cods else None
    if res is None:
        _sem_conversa(engine, contato_id, "localização de contato sem imóvel com aceite")
        return {"contato_id": contato_id, "acao": "revisao"}
    return {"contato_id": contato_id, "cod_imovel": res.cod_imovel, "acao": "sede", "sede": res.situacao}


def _sem_conversa(engine: Engine, contato_id: int, motivo: str, cod: str | None = None) -> None:
    from psycopg.types.json import Jsonb

    with engine.begin() as con:
        con.execute(
            text("insert into operacao.fila_revisao (tarefa, chave, motivo, conteudo) values (:t, :c, :m, :x)"),
            dict(
                t="whatsapp",
                c=cod,
                m=motivo,
                x=Jsonb({"contato_id": contato_id, "cod_imovel": cod, "aviso": "texto não copiado: ver no WhatsApp"}),
            ),
        )


def ligar_webhook(wa, obter: Callable[[], tuple]) -> None:
    """`obter()` devolve (engine, grafo, deps) na hora da mensagem (o grafo só existe depois que o serviço sobe)."""

    @wa.on_message()
    def _mensagem(_cliente, msg):  # pragma: no cover - chamado pelo PyWa
        u = msg.from_user
        texto = getattr(msg, "text", None) or ""
        loc = getattr(msg, "location", None)
        try:
            engine, grafo, deps = obter()
            if loc is not None and getattr(loc, "latitude", None) is not None:  # localização da sede (E5 passo 6)
                receber_localizacao(engine, u.bsuid, u.wa_id, loc.longitude, loc.latitude, u.parent_bsuid, u.username)
                return
            receber(engine, grafo, deps, u.bsuid, u.wa_id, texto, u.parent_bsuid, u.username)
        except Exception:  # noqa: BLE001 - o webhook sempre responde 200; o erro fica no log (mascarado)
            log.exception("falha ao tratar mensagem do WhatsApp")


# --- saída: só o que foi aprovado ------------------------------------------------------------------------------


def aprovar(engine: Engine, mensagem_id: int, quem: str) -> None:
    with engine.begin() as con:
        n = con.execute(
            text("""update pessoal.mensagem_saida set estado = 'aprovada', aprovada_por = :q,
                                aprovada_em = now() where id = :i and estado = 'aguardando_aprovacao'"""),
            {"q": quem, "i": mensagem_id},
        ).rowcount
    if n != 1:
        raise ValueError(f"mensagem {mensagem_id} não está aguardando aprovação")


def descartar(engine: Engine, mensagem_id: int, quem: str) -> None:
    with engine.begin() as con:
        con.execute(
            text("""update pessoal.mensagem_saida set estado = 'descartada', aprovada_por = :q,
                            aprovada_em = now() where id = :i and estado = 'aguardando_aprovacao'"""),
            {"q": quem, "i": mensagem_id},
        )


def enviar_aprovadas(
    engine: Engine,
    enviar: Callable[[str, str], str],
    cofre: Cofre | None = None,
    pedir_localizacao: Callable[[str, str], str] | None = None,
) -> int:
    """Envia as mensagens aprovadas. `enviar(destino, texto)` devolve o id da mensagem no WhatsApp. O pedido da
    localização da sede sai por `pedir_localizacao` (o botão "Enviar localização"), quando há."""
    with engine.connect() as con:
        pend = con.execute(
            text("select id, contato_id, tipo, texto from pessoal.mensagem_saida where estado = 'aprovada' order by id")
        ).all()
    n = 0
    for m in pend:
        with engine.begin() as con:
            try:
                f = pedir_localizacao if (m.tipo == "pedido_sede" and pedir_localizacao) else enviar
                wid = f(destino_whatsapp(con, m.contato_id, cofre), m.texto)
                con.execute(
                    text(
                        "update pessoal.mensagem_saida set estado = 'enviada', enviada_em = now(), "
                        "wa_message_id = :w where id = :i"
                    ),
                    {"w": wid, "i": m.id},
                )
                n += 1
            except Exception as ex:  # noqa: BLE001
                con.execute(
                    text("update pessoal.mensagem_saida set estado = 'falhou', erro = :e where id = :i"),
                    {"e": str(ex)[:300], "i": m.id},
                )
    return n


def enviador_pywa(wa) -> Callable[[str, str], str]:
    def enviar(destino: str, texto: str) -> str:
        return wa.send_message(to=destino, text=texto).id

    return enviar


def pedidor_localizacao_pywa(wa) -> Callable[[str, str], str]:  # pragma: no cover - chama a Cloud API
    def pedir(destino: str, texto: str) -> str:
        return wa.request_location(to=destino, text=texto).id

    return pedir
