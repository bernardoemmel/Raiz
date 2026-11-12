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
        try:
            engine, grafo, deps = obter()
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


def enviar_aprovadas(engine: Engine, enviar: Callable[[str, str], str], cofre: Cofre | None = None) -> int:
    """Envia as mensagens aprovadas. `enviar(destino, texto)` devolve o id da mensagem no WhatsApp."""
    with engine.connect() as con:
        pend = con.execute(
            text("select id, contato_id, texto from pessoal.mensagem_saida where estado = 'aprovada' order by id")
        ).all()
    n = 0
    for m in pend:
        with engine.begin() as con:
            try:
                wid = enviar(destino_whatsapp(con, m.contato_id, cofre), m.texto)
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
