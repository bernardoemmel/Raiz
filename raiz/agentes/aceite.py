"""Grafo do aceite do dono (LangGraph). thread_id = código do CAR.

    convite -> [dono responde] -> intenção (cascata ABC)
        aceita -> [fundador anexa a proposta, se ainda não há] -> proposta + teach-back
                  -> [dono explica com as próprias palavras] -> entendimento (cascata ABC)
                        entendeu -> código de confirmação -> [dono manda o código] -> aceito
                        faltou algo -> reexplica (até 2 vezes) -> revisão
        recusa -> recusado          dúvida -> fila de revisão (o fundador responde) e segue esperando
        outro / cascata sem acordo -> revisão

- Cada pausa é um interrupt(); a retomada traz o texto do dono (WhatsApp) ou a proposta (backoffice).
- Nenhuma mensagem sai direto: tudo entra em pessoal.mensagem_saida esperando aprovação.
- O código de confirmação é conferido por código (sem modelo) e só o hash fica no estado.
- Aceite e recusa viram gabarito (alvo aceite_dono) para o aprendizado (E8).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import Engine, text

from raiz.agentes import textos
from raiz.aprendizado.registro import registrar_gabarito
from raiz.legibilidade import medir
from raiz.modelos.base import Pedido
from raiz.modelos.cascata import Cascata
from raiz.pessoal import registrar_consentimento

ETAPAS_DO_DONO = {"convite", "explicacao", "codigo"}
MAX_EXPLICACOES = 2
MAX_CODIGOS = 3

ESQ_INTENCAO = {
    "type": "object",
    "properties": {"intencao": {"type": "string", "enum": ["aceita", "recusa", "duvida", "outro"]}},
    "required": ["intencao"],
    "additionalProperties": False,
}
ESQ_ENTENDIMENTO = {
    "type": "object",
    "properties": {
        "entendeu_area": {"type": "boolean"},
        "entendeu_prazo": {"type": "boolean"},
        "entendeu_pagamento": {"type": "boolean"},
        "desistiu": {"type": "boolean"},
    },
    "required": ["entendeu_area", "entendeu_prazo", "entendeu_pagamento", "desistiu"],
    "additionalProperties": False,
}
SISTEMA_INTENCAO = (
    "Você classifica a resposta de um produtor rural a um convite da Raíz para restaurar mata na fazenda com "
    "pagamento por carbono. Responda só com a intenção: 'aceita' (quer seguir ou saber mais), 'recusa' (não quer), "
    "'duvida' (fez uma pergunta) ou 'outro' (assunto diferente ou não dá para saber)."
)


class Estado(TypedDict, total=False):
    cod_imovel: str
    contato_id: int
    etapa: str
    proposta: dict | None
    resposta: str | None
    intencao: str | None
    entendimento: dict | None
    tentativas: int
    codigo_hash: str | None
    resultado: str | None


@dataclass
class Dependencias:
    engine: Engine
    cascata: Cascata


def _deps(config) -> Dependencias:
    return config["configurable"]["deps"]


def _hash_codigo(cod_imovel: str, codigo: str) -> str:
    return hashlib.sha256(f"{cod_imovel}|{codigo}".encode()).hexdigest()


def _enfileirar(con, estado: Estado, tipo: str, texto: str) -> None:
    """A mensagem entra esperando aprovação, com a nota de legibilidade (todas as versões) para quem aprova."""
    from psycopg.types.json import Jsonb

    con.execute(
        text("""insert into pessoal.mensagem_saida (contato_id, cod_imovel, tipo, texto, legibilidade)
                        values (:c, :i, :t, :x, :l)"""),
        dict(c=estado["contato_id"], i=estado["cod_imovel"], t=tipo, x=texto, l=Jsonb(medir(texto))),
    )


def _aceite(con, cod: str, **campos) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in campos)
    extra = ", encerrado_em = now()" if campos.get("estado") in {"aceito", "recusado", "revisao", "cancelado"} else ""
    con.execute(
        text(f"update negocio.aceite set {sets}, atualizado_em = now(){extra} where cod_imovel = :cod"),
        dict(cod=cod, **campos),
    )


def _revisao(con, estado: Estado, motivo: str, conteudo: dict | None = None) -> None:
    from psycopg.types.json import Jsonb

    base = {
        "cod_imovel": estado["cod_imovel"],
        "etapa": estado.get("etapa"),
        "aviso": "conversa com dado pessoal: ver no WhatsApp",
    }
    con.execute(
        text("insert into operacao.fila_revisao (tarefa, chave, motivo, conteudo) values (:t, :c, :m, :x)"),
        dict(t="aceite", c=estado["cod_imovel"], m=motivo, x=Jsonb({**base, **(conteudo or {})})),
    )


def _gabarito(con, cod: str, valor: str) -> None:
    registrar_gabarito(con, cod, "aceite_dono", dt.date.today(), "aceite_whatsapp", valor_texto=valor)


# --- nós -------------------------------------------------------------------------------------------------------


def convidar(estado: Estado, config) -> dict:
    d = _deps(config)
    with d.engine.begin() as con:
        ficha = (
            con.execute(
                text("select * from funil.resultado_vigente where cod_imovel = :c"), {"c": estado["cod_imovel"]}
            )
            .mappings()
            .first()
        )
        if ficha is None:
            _revisao(con, estado, "imóvel sem resultado do funil: não há o que oferecer")
            _aceite(con, estado["cod_imovel"], estado="revisao", etapa="sem_ficha", motivo="sem resultado do funil")
            return {"etapa": "sem_ficha", "resultado": "revisao"}
        _enfileirar(con, estado, "convite", textos.convite(dict(ficha)))
        _aceite(con, estado["cod_imovel"], etapa="convite")
    return {"etapa": "convite", "tentativas": 0}


def ouvir(estado: Estado) -> dict:
    """Só pausa (ao retomar, o nó roda de novo do começo: nada de efeito colateral aqui)."""
    resposta = interrupt({"cod_imovel": estado["cod_imovel"], "etapa": estado["etapa"]})
    return {"resposta": resposta}


def pedido_intencao(resposta: str, cod_imovel: str | None = None) -> Pedido:
    """O pedido de classificação da resposta ao convite (o mesmo do teste próprio, raiz/modelos/avaliacao)."""
    return Pedido(
        "aceite.intencao", SISTEMA_INTENCAO, resposta, ESQ_INTENCAO, cod_imovel=cod_imovel, max_tokens=200, pessoal=True
    )


def sistema_explicacao(proposta: dict) -> str:
    return (
        "Um produtor rural recebeu uma proposta e explicou com as próprias palavras o que entendeu. Diga se ele "
        f"entendeu cada ponto. Proposta: área de {proposta['area_ha']} hectares; prazo de {proposta['prazo_anos']} "
        f"anos; pagamento: {proposta['pagamento']}. Considere entendido se o sentido estiver certo, mesmo com palavras "
        "simples ou números arredondados. Marque desistiu=true só se ele disser que não quer mais."
    )


def pedido_explicacao(proposta: dict, resposta: str, cod_imovel: str | None = None) -> Pedido:
    """O pedido que confere o teach-back (o mesmo do teste próprio, raiz/modelos/avaliacao)."""
    return Pedido(
        "aceite.explicacao",
        sistema_explicacao(proposta),
        resposta,
        ESQ_ENTENDIMENTO,
        cod_imovel=cod_imovel,
        max_tokens=300,
        pessoal=True,
    )


def classificar(estado: Estado, config) -> dict:
    d = _deps(config)
    p = pedido_intencao(str(estado.get("resposta") or ""), estado["cod_imovel"])
    with d.engine.begin() as con:
        r = d.cascata.decidir(p, con)
    intencao = r.dados["intencao"] if r.dados else "sem_acordo"
    return {"intencao": intencao, "resposta": None}


def apos_intencao(estado: Estado) -> str:
    return {"aceita": "interessado", "recusa": "recusar", "duvida": "duvida"}.get(estado["intencao"], "revisao")


def interessado(estado: Estado, config) -> dict:
    if estado.get("proposta"):
        return {}
    with _deps(config).engine.begin() as con:
        _revisao(con, estado, "dono interessado: montar a proposta (área, prazo, pagamento) e enviar pelo backoffice")
        _aceite(con, estado["cod_imovel"], etapa="aguardando_proposta")
    return {"etapa": "aguardando_proposta"}


def esperar_proposta(estado: Estado) -> dict:
    if estado.get("proposta"):
        return {}
    proposta = interrupt({"cod_imovel": estado["cod_imovel"], "etapa": "aguardando_proposta"})
    return {"proposta": proposta}


def apresentar_proposta(estado: Estado, config) -> dict:
    with _deps(config).engine.begin() as con:
        _enfileirar(con, estado, "proposta", textos.proposta(estado["proposta"]))
        _aceite(con, estado["cod_imovel"], etapa="explicacao")
    return {"etapa": "explicacao", "tentativas": 0}


def avaliar_explicacao(estado: Estado, config) -> dict:
    d = _deps(config)
    p = pedido_explicacao(estado["proposta"], str(estado.get("resposta") or ""), estado["cod_imovel"])
    with d.engine.begin() as con:
        r = d.cascata.decidir(p, con)
    return {"entendimento": r.dados, "resposta": None, "tentativas": estado.get("tentativas", 0) + 1}


def apos_explicacao(estado: Estado) -> str:
    e = estado.get("entendimento")
    if e is None:
        return "revisao"
    if e["desistiu"]:
        return "recusar"
    if e["entendeu_area"] and e["entendeu_prazo"] and e["entendeu_pagamento"]:
        return "pedir_codigo"
    return "reexplicar" if estado.get("tentativas", 0) < MAX_EXPLICACOES else "revisao"


def reexplicar(estado: Estado, config) -> dict:
    e = estado["entendimento"]
    faltou = [
        k
        for k, c in (("area", "entendeu_area"), ("prazo", "entendeu_prazo"), ("pagamento", "entendeu_pagamento"))
        if not e[c]
    ]
    with _deps(config).engine.begin() as con:
        _enfileirar(con, estado, "reexplicacao", textos.reexplicar(estado["proposta"], faltou))
    return {"etapa": "explicacao"}


def pedir_codigo(estado: Estado, config) -> dict:
    codigo = f"{secrets.randbelow(10**6):06d}"
    with _deps(config).engine.begin() as con:
        _enfileirar(con, estado, "codigo", textos.pedir_codigo(codigo))
        _aceite(con, estado["cod_imovel"], etapa="codigo")
    return {"etapa": "codigo", "tentativas": 0, "codigo_hash": _hash_codigo(estado["cod_imovel"], codigo)}


def conferir_codigo(estado: Estado, config) -> dict:
    resposta = str(estado.get("resposta") or "")
    digitos = re.findall(r"\d{6}", resposta.replace(" ", ""))
    ok = any(_hash_codigo(estado["cod_imovel"], d) == estado["codigo_hash"] for d in digitos)
    nao = bool(re.search(r"\bn[aã]o\b", resposta.lower())) and not digitos
    return {
        "resultado": "codigo_ok" if ok else ("codigo_nao" if nao else "codigo_errado"),
        "resposta": None,
        "tentativas": estado.get("tentativas", 0) + (0 if ok else 1),
    }


def apos_codigo(estado: Estado) -> str:
    r = estado["resultado"]
    if r == "codigo_ok":
        return "aceitar"
    if r == "codigo_nao":
        return "recusar"
    return "codigo_errado" if estado.get("tentativas", 0) < MAX_CODIGOS else "revisao"


def codigo_errado(estado: Estado, config) -> dict:
    with _deps(config).engine.begin() as con:
        _enfileirar(con, estado, "codigo_errado", textos.codigo_errado())
    return {}


def aceitar(estado: Estado, config) -> dict:
    with _deps(config).engine.begin() as con:
        registrar_consentimento(con, estado["contato_id"])
        _enfileirar(con, estado, "aceito", textos.aceito())
        _aceite(con, estado["cod_imovel"], estado="aceito", etapa="aceito")
        _gabarito(con, estado["cod_imovel"], "sim")
    return {"etapa": "aceito", "resultado": "aceito", "codigo_hash": None}


def recusar(estado: Estado, config) -> dict:
    with _deps(config).engine.begin() as con:
        _enfileirar(con, estado, "recusa", textos.recusado())
        _aceite(con, estado["cod_imovel"], estado="recusado", etapa="recusado")
        _gabarito(con, estado["cod_imovel"], "não")
    return {"etapa": "recusado", "resultado": "recusado", "codigo_hash": None}


def duvida(estado: Estado, config) -> dict:
    with _deps(config).engine.begin() as con:
        _revisao(con, estado, "dono fez uma pergunta: responder pelo WhatsApp")
        _enfileirar(con, estado, "duvida", textos.duvida_recebida())
    return {}


def revisao(estado: Estado, config) -> dict:
    with _deps(config).engine.begin() as con:
        _revisao(con, estado, f"aceite parou na etapa {estado.get('etapa')}: decidir à mão")
        _enfileirar(con, estado, "em_analise", textos.em_analise())
        _aceite(con, estado["cod_imovel"], estado="revisao", motivo=f"etapa {estado.get('etapa')}")
    return {"resultado": "revisao", "codigo_hash": None}


def apos_ouvir(estado: Estado) -> str:
    return {"convite": "classificar", "explicacao": "avaliar_explicacao", "codigo": "conferir_codigo"}[estado["etapa"]]


def construir(checkpointer=None):
    g = StateGraph(Estado)
    for nome, fn in [
        ("convidar", convidar),
        ("ouvir", ouvir),
        ("classificar", classificar),
        ("interessado", interessado),
        ("esperar_proposta", esperar_proposta),
        ("apresentar_proposta", apresentar_proposta),
        ("avaliar_explicacao", avaliar_explicacao),
        ("reexplicar", reexplicar),
        ("pedir_codigo", pedir_codigo),
        ("conferir_codigo", conferir_codigo),
        ("codigo_errado", codigo_errado),
        ("aceitar", aceitar),
        ("recusar", recusar),
        ("duvida", duvida),
        ("revisao", revisao),
    ]:
        g.add_node(nome, fn)
    g.add_edge(START, "convidar")
    g.add_conditional_edges("convidar", lambda e: END if e.get("resultado") == "revisao" else "ouvir")
    g.add_conditional_edges("ouvir", apos_ouvir)
    g.add_conditional_edges("classificar", apos_intencao)
    g.add_edge("interessado", "esperar_proposta")
    g.add_edge("esperar_proposta", "apresentar_proposta")
    g.add_edge("apresentar_proposta", "ouvir")
    g.add_conditional_edges("avaliar_explicacao", apos_explicacao)
    g.add_edge("reexplicar", "ouvir")
    g.add_edge("pedir_codigo", "ouvir")
    g.add_conditional_edges("conferir_codigo", apos_codigo)
    g.add_edge("codigo_errado", "ouvir")
    g.add_edge("duvida", "ouvir")
    for fim in ("aceitar", "recusar", "revisao"):
        g.add_edge(fim, END)
    return g.compile(checkpointer=checkpointer)


# --- operações (usadas pela API, pelo WhatsApp e pela linha de comando) -----------------------------------------


def _config(cod_imovel: str, deps: Dependencias) -> dict:
    return {"configurable": {"thread_id": cod_imovel, "deps": deps}}


def pausa(grafo, cod_imovel: str, deps: Dependencias) -> dict | None:
    """Em que pausa a conversa está (None se terminou ou não começou)."""
    st = grafo.get_state(_config(cod_imovel, deps))
    for t in st.tasks:
        if getattr(t, "interrupts", None):
            return t.interrupts[0].value
    return None


def iniciar(grafo, deps: Dependencias, cod_imovel: str, contato_id: int, proposta: dict | None = None) -> Any:
    from raiz.pessoal import vincular_imovel

    with deps.engine.begin() as con:
        existe = con.execute(
            text("select estado from negocio.aceite where cod_imovel = :c"), {"c": cod_imovel}
        ).scalar()
        if existe == "em_andamento":
            raise ValueError(f"já há um aceite em andamento para {cod_imovel}")
        con.execute(
            text("""insert into negocio.aceite (cod_imovel, contato_id) values (:c, :ct)
                            on conflict (cod_imovel) do update set contato_id = excluded.contato_id,
                            estado = 'em_andamento', etapa = 'convite', motivo = null, iniciado_em = now(),
                            atualizado_em = now(), encerrado_em = null"""),
            {"c": cod_imovel, "ct": contato_id},
        )
        vincular_imovel(con, contato_id, cod_imovel)
    # uma conversa por imóvel (thread_id = código do CAR); recomeçar zera todo o estado da conversa anterior
    entrada: Estado = {
        "cod_imovel": cod_imovel,
        "contato_id": contato_id,
        "proposta": proposta,
        "etapa": "convite",
        "resposta": None,
        "intencao": None,
        "entendimento": None,
        "tentativas": 0,
        "codigo_hash": None,
        "resultado": None,
    }
    return grafo.invoke(entrada, _config(cod_imovel, deps))


def retomar(grafo, deps: Dependencias, cod_imovel: str, valor: Any, etapas: set[str] | None = None) -> Any:
    from langgraph.types import Command

    p = pausa(grafo, cod_imovel, deps)
    if p is None:
        raise ValueError(f"a conversa de {cod_imovel} não está esperando nada")
    if etapas is not None and p["etapa"] not in etapas:
        raise ValueError(f"a conversa de {cod_imovel} espera '{p['etapa']}', não isto")
    return grafo.invoke(Command(resume=valor), _config(cod_imovel, deps))


def responder(grafo, deps: Dependencias, cod_imovel: str, texto: str) -> Any:
    return retomar(grafo, deps, cod_imovel, texto, ETAPAS_DO_DONO)


def enviar_proposta(grafo, deps: Dependencias, cod_imovel: str, proposta: dict) -> Any:
    faltam = {"area_ha", "prazo_anos", "pagamento"} - set(proposta)
    if faltam:
        raise ValueError(f"proposta incompleta: falta {sorted(faltam)}")
    return retomar(grafo, deps, cod_imovel, proposta, {"aguardando_proposta"})
