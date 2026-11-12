"""O pedido salvo e o caminho até o contrato (docs/cena-alvo.md): cliente e entrada sem senha, pedido com a base e as
3 opções, troca de fazenda, busca de interesse em ondas, andamento, grupo pronto com aviso, reserva com Pix e
exclusividade, vigia do pedido e aprendizado da chance de aceite.

Nome, CPF e contato do dono nunca aparecem: a resposta traz só o nível de interesse. Fazenda reservada por outro
cliente some de tudo (base, opções, andamento) e uma fazenda nunca está em duas reservas ao mesmo tempo."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
import uuid
from collections.abc import Callable

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from raiz.pedidos import aceite as A
from raiz.pedidos import oferta as O
from raiz.pedidos import otimizador as Z
from raiz.pedidos import pix
from raiz.pedidos.campos import CamposPedido, titulo
from raiz.pedidos.premissas import premissas, versao_modelo

ORDEM_NIVEL = {"sem_contato": 0, "contatado": 1, "interessado": 2, "aceite_fase1": 3, "contrato_firme": 4}
NIVEIS = (*ORDEM_NIVEL, "recusou", "sem_resposta")


class ErroPedido(ValueError):
    """Erro de uso (vira 4xx na API), com a mensagem em português."""


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- envio (painel, e-mail e WhatsApp): simulado até haver um enviador configurado --------------------------------

ENVIADORES: dict[str, Callable[[int, str], None] | None] = {"email": None, "whatsapp": None}
ENVIO_LINK: Callable[[str, str], None] | None = None  # (e-mail, link): sem enviador, o link fica só no retorno de teste


def notificar(con, cliente_id: int, pedido_id, tipo: str, texto_: str, canais=("painel", "email", "whatsapp")) -> None:
    for canal in canais:
        envia = ENVIADORES.get(canal)
        estado = "enviada" if canal == "painel" else "simulada"
        if envia is not None:
            try:
                envia(cliente_id, texto_)
                estado = "enviada"
            except Exception:  # noqa: BLE001 - falha de envio não para o pedido; fica registrada
                estado = "falhou"
        con.execute(
            text("""insert into negocio.notificacao (cliente_id, pedido_id, tipo, canal, texto, estado, enviada_em)
                    values (:c, :p, :t, :canal, :tx, :e, case when :e in ('enviada', 'simulada') then now() end)"""),
            {"c": cliente_id, "p": pedido_id, "t": tipo, "canal": canal, "tx": texto_, "e": estado},
        )


# --- cliente e entrada sem senha ----------------------------------------------------------------------------------


def criar_cliente(
    engine: Engine, rotulo: str, email: str | None = None, tipo: str | None = None, cofre=None
) -> tuple[int, str]:
    """Cria o cliente (empresa) e devolve (id, token de sessão). O e-mail fica cifrado no esquema pessoal."""
    token = secrets.token_urlsafe(32)
    with engine.begin() as con:
        cid = con.execute(
            text("insert into negocio.cliente (rotulo, tipo, token_hmac) values (:r, :t, :h) returning id"),
            {"r": rotulo, "t": tipo, "h": _hash("cliente:" + secrets.token_hex(16))},
        ).scalar_one()
        if email:
            _gravar_email(con, cid, email, cofre)
        con.execute(
            text("insert into negocio.sessao (token_hash, cliente_id, expira_em) values (:h, :c, :e)"),
            {"h": _hash(token), "c": cid, "e": _agora() + dt.timedelta(days=30)},
        )
    return cid, token


def _cofre(cofre=None):
    if cofre is not None:
        return cofre
    from raiz.pessoal import Cofre

    return Cofre()


def _gravar_email(con, cliente_id: int, email: str, cofre=None) -> None:
    cf = _cofre(cofre)
    e = email.strip().lower()
    con.execute(
        text("""insert into pessoal.cliente_contato (cliente_id, email_hmac, email_cifrado) values (:c, :h, :x)
                on conflict (cliente_id) do update set email_hmac = excluded.email_hmac,
                email_cifrado = excluded.email_cifrado, atualizado_em = now()"""),
        {"c": cliente_id, "h": cf.indice(e), "x": cf.cifrar(e)},
    )


def pedir_link(engine: Engine, email: str, base_url: str = "", cofre=None) -> str:
    """Manda o link de entrada para o e-mail (cria o cliente na primeira vez). Devolve o token (para o teste e para o
    enviador); a API não devolve o token."""
    e = email.strip().lower()
    if "@" not in e or len(e) > 254:
        raise ErroPedido("e-mail inválido")
    cf = _cofre(cofre)
    token = secrets.token_urlsafe(24)
    with engine.begin() as con:
        cid = con.execute(
            text("select cliente_id from pessoal.cliente_contato where email_hmac = :h"), {"h": cf.indice(e)}
        ).scalar()
        if cid is None:
            cid = con.execute(
                text("insert into negocio.cliente (rotulo, token_hmac) values (:r, :h) returning id"),
                {"r": e.split("@", 1)[1], "h": _hash("cliente:" + secrets.token_hex(16))},
            ).scalar_one()
            _gravar_email(con, cid, e, cf)
        con.execute(
            text("insert into negocio.login_link (token_hash, cliente_id, expira_em) values (:h, :c, :x)"),
            {"h": _hash(token), "c": cid, "x": _agora() + dt.timedelta(minutes=30)},
        )
    if ENVIO_LINK is not None:
        ENVIO_LINK(e, f"{base_url}#/entrar/{token}")
    return token


def confirmar_link(engine: Engine, token: str, cofre=None) -> dict:
    """Troca o link (uso único, 30 minutos) por uma sessão de 30 dias: {token, email}."""
    with engine.begin() as con:
        r = con.execute(
            text("""update negocio.login_link set usado_em = now()
                    where token_hash = :h and usado_em is null and expira_em > now() returning cliente_id"""),
            {"h": _hash(token)},
        ).first()
        if r is None:
            raise ErroPedido("link inválido ou vencido: peça outro")
        sess = secrets.token_urlsafe(32)
        con.execute(
            text("insert into negocio.sessao (token_hash, cliente_id, expira_em) values (:h, :c, :e)"),
            {"h": _hash(sess), "c": r.cliente_id, "e": _agora() + dt.timedelta(days=30)},
        )
        x = con.execute(
            text("select email_cifrado from pessoal.cliente_contato where cliente_id = :c"), {"c": r.cliente_id}
        ).scalar()
    email = _cofre(cofre).decifrar(x) if x is not None else ""
    return {"token": sess, "email": email}


def cliente_da_sessao(engine: Engine, token: str) -> int | None:
    if not token:
        return None
    with engine.connect() as con:
        return con.execute(
            text("""select s.cliente_id from negocio.sessao s join negocio.cliente c on c.id = s.cliente_id
                    where s.token_hash = :h and s.expira_em > now() and c.ativo"""),
            {"h": _hash(token)},
        ).scalar()


# --- leitura: níveis, reservas de outros clientes, oferta -------------------------------------------------------


def niveis(con, cods: list[str] | None = None) -> dict[str, str]:
    """Nível de interesse de agora. Recusa e falta de resposta valem por `recontato_apos_dias` (premissa): depois
    disso a fazenda volta a poder ser contatada, como se não tivesse contato."""
    if cods is not None and not cods:
        return {}
    dias = int(premissas()["ondas"].get("recontato_apos_dias", 365))
    q = "select cod_imovel, nivel, atualizado_em from negocio.interesse_dono" + (
        " where cod_imovel = any(:c)" if cods else "")  # fmt: skip
    limite = _agora() - dt.timedelta(days=dias)
    out = {}
    for r in con.execute(text(q), {"c": cods} if cods else {}):
        vencido = r.nivel in ("recusou", "sem_resposta") and r.atualizado_em < limite
        out[r.cod_imovel] = "sem_contato" if vencido else r.nivel
    return out


def fora_para(con, cliente_id: int) -> set[str]:
    """Fazendas em reserva ativa (ou já em contrato) de OUTRO cliente: somem das buscas, contas e pedidos."""
    return {
        r[0]
        for r in con.execute(
            text("""select rf.cod_imovel from negocio.reserva_fazenda rf join negocio.reserva r on r.id = rf.reserva_id
                where rf.ativa and r.cliente_id <> :c"""),
            {"c": cliente_id},
        )
    }


def _oferta(engine: Engine, c: CamposPedido) -> pd.DataFrame:
    muns = [int(m) for m in c.onde.municipios if str(m).isdigit()] or None
    return O.do_banco(engine, ufs=c.onde.ufs or None, municipios=muns)


def _pagamento(c: CamposPedido) -> str:
    return "participacao"


# --- pedido ---------------------------------------------------------------------------------------------------------


def _salvar_sugestao(con, pedido_id, motivo: str, b: dict, ops: list[dict]) -> None:
    con.execute(
        text("""insert into negocio.pedido_sugestao (pedido_id, motivo, otimizador_versao, premissas_versao, base,
                opcoes) values (:p, :m, :ov, :pv, cast(:b as jsonb), cast(:o as jsonb))"""),
        {
            "p": pedido_id,
            "m": motivo,
            "ov": premissas()["otimizador"]["versao"],
            "pv": versao_modelo(),
            "b": json.dumps(b, default=float),
            "o": json.dumps(ops, default=float),
        },
    )


def base_disponivel(engine: Engine, cliente_id: int, campos: CamposPedido | dict) -> dict:
    """Quanto existe na base para o pedido, sem salvar nada (a primeira pergunta de um agente de IA)."""
    c = campos if isinstance(campos, CamposPedido) else CamposPedido.model_validate(campos)
    with engine.connect() as con:
        nv, fora = niveis(con), fora_para(con, cliente_id)
    return Z.base(_oferta(engine, c), c, nv, fora)


def criar_pedido(engine: Engine, cliente_id: int, campos: CamposPedido | dict) -> dict:
    c = campos if isinstance(campos, CamposPedido) else CamposPedido.model_validate(campos)
    with engine.connect() as con:
        nv, fora = niveis(con), fora_para(con, cliente_id)
        hist = A.historico_do_banco(con)
    b, ops, _ = Z.opcoes(_oferta(engine, c), c, nv, fora, hist, _pagamento(c))
    pid = uuid.uuid4()
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.pedido (id, cliente_id, estado, campos, premissas_versao)
                    values (:id, :c, 'lote_montado', cast(:campos as jsonb), :v)"""),
            {"id": pid, "c": cliente_id, "campos": c.model_dump_json(), "v": versao_modelo()},
        )
        _salvar_sugestao(con, pid, "criado", b, ops)
    return obter_pedido(engine, str(pid), cliente_id)


def _linha_pedido(con, pedido_id: str, cliente_id: int | None):
    try:
        uuid.UUID(str(pedido_id))
    except ValueError as ex:
        raise ErroPedido("pedido não encontrado") from ex
    q = "select * from negocio.pedido where id = :id" + (" and cliente_id = :c" if cliente_id is not None else "")
    r = con.execute(text(q), {"id": pedido_id, "c": cliente_id}).mappings().first()
    if r is None:  # pedido de outro cliente é como se não existisse
        raise ErroPedido("pedido não encontrado")
    return r


def _ultima_sugestao(con, pedido_id) -> dict:
    r = (
        con.execute(
            text("""select base, opcoes, premissas_versao, criada_em from negocio.pedido_sugestao where pedido_id = :p
                order by id desc limit 1"""),
            {"p": pedido_id},
        )
        .mappings()
        .first()
    )
    return dict(r) if r else {"base": {}, "opcoes": [], "premissas_versao": versao_modelo()}


def _reservado_ate(con, pedido_id) -> str | None:
    fim = con.execute(
        text("""select max(fim) from negocio.reserva where pedido_id = :p and estado = 'ativa'"""), {"p": pedido_id}
    ).scalar()
    return fim.isoformat() if fim else None


def _alertas(con, pedido_id) -> list[dict]:
    rs = con.execute(
        text("""select tipo, cod_imovel, detalhe, criado_em from negocio.alerta_pedido
                             where pedido_id = :p order by id desc"""),
        {"p": pedido_id},
    )
    return [
        {
            "tipo": r.tipo,
            "texto": (r.detalhe or {}).get("texto", ""),
            "data": r.criado_em.isoformat(),
            "cod_imovel": r.cod_imovel,
            # desmatamento, embargo, matricula_cancelada, bloqueio, caminho_terra, saiu_da_base (fazenda_com_problema)
            "motivo": (r.detalhe or {}).get("motivo"),
            # fonte, data do evento, área, link da fonte, fazendas novas no lote (lote_melhorou); nada pessoal
            "detalhe": {k: v for k, v in (r.detalhe or {}).items() if k not in ("texto", "chave", "motivo")},
        }
        for r in rs
    ]


def _limpar_opcoes(ops: list[dict], nv: dict[str, str], fora: set[str]) -> list[dict]:
    """Opções na hora de ler: tira fazenda reservada por outro cliente e põe o nível de interesse de agora."""
    out = []
    for o in ops:
        o = dict(o)
        itens = [
            dict(i, interesse=nv.get(i["cod_imovel"], "sem_contato"))
            for i in o.get("itens", [])
            if i["cod_imovel"] not in fora
        ]
        if len(itens) != len(o.get("itens", [])):
            o["observacao"] = "Fazendas reservadas por outro cliente saíram desta opção; refaça o pedido para repor."
        o["itens"] = itens
        out.append(o)
    return out


def obter_pedido(engine: Engine, pedido_id: str, cliente_id: int | None) -> dict:
    with engine.connect() as con:
        p = _linha_pedido(con, pedido_id, cliente_id)
        s = _ultima_sugestao(con, p["id"])
        cods = [i["cod_imovel"] for o in s["opcoes"] for i in o.get("itens", [])]
        nv = niveis(con, cods)
        fora = fora_para(con, p["cliente_id"])
        return {
            "id": str(p["id"]),
            "criado_em": p["criado_em"].isoformat(),
            "campos": p["campos"],
            "status": p["estado"],
            "base": s["base"],
            "opcoes": _limpar_opcoes(s["opcoes"], nv, fora),
            "opcao_escolhida": p["opcao_escolhida"],
            "reservado_ate": _reservado_ate(con, p["id"]),
            "alertas": _alertas(con, p["id"]),
            "versao_modelo": s["premissas_versao"],
        }


def pedidos_do_cliente(engine: Engine, cliente_id: int) -> list[dict]:
    out = []
    with engine.connect() as con:
        for p in con.execute(
            text("select * from negocio.pedido where cliente_id = :c order by criado_em desc"), {"c": cliente_id}
        ).mappings():
            c = CamposPedido.model_validate(p["campos"])
            com = None
            if p["estado"] != "lote_montado":
                a = _progresso(con, p["id"], c)
                com = round(min(a["com_interessado"] / c.meta.valor, 1.0), 3)
            n_al = con.execute(
                text("select count(*) from negocio.alerta_pedido where pedido_id = :p and visto_em is null"),
                {"p": p["id"]},
            ).scalar()
            out.append(
                {
                    "id": str(p["id"]),
                    "criado_em": p["criado_em"].isoformat(),
                    "titulo": titulo(c),
                    "status": p["estado"],
                    "reservado_ate": _reservado_ate(con, p["id"]),
                    "com_interesse": com,
                    "alertas": int(n_al),
                }
            )
    return out


# --- trocar fazenda à mão -----------------------------------------------------------------------------------------


def mudar_lote(engine: Engine, pedido_id: str, cliente_id: int, mudanca: dict) -> dict:
    """Tira uma fazenda do lote da opção ou troca por uma reserva (a indicada ou a melhor); refaz os números."""
    opcao, acao, cod, por = mudanca.get("opcao"), mudanca.get("acao"), mudanca.get("cod_imovel"), mudanca.get("por")
    if acao not in ("tirar", "trocar"):
        raise ErroPedido("acao: tirar ou trocar")
    with engine.connect() as con:
        p = _linha_pedido(con, pedido_id, cliente_id)
        if p["estado"] in ("reservado", "contrato"):
            raise ErroPedido("o grupo já está reservado: a troca passa pela Raíz")
        s = _ultima_sugestao(con, p["id"])
        nv, fora = niveis(con), fora_para(con, cliente_id)
    c = CamposPedido.model_validate(p["campos"])
    ops = [dict(o) for o in s["opcoes"]]
    alvo = next((o for o in ops if o["id"] == opcao), None)
    if alvo is None:
        raise ErroPedido("opção desconhecida")
    lote = [i["cod_imovel"] for i in alvo["itens"] if i["papel"] == "lote"]
    reserva = [i["cod_imovel"] for i in alvo["itens"] if i["papel"] == "reserva" and i["cod_imovel"] not in fora]
    trocas = {i["cod_imovel"]: i.get("trocou") for i in alvo["itens"] if i.get("trocou")}
    if cod not in lote:
        raise ErroPedido("essa fazenda não está no lote desta opção")
    lote.remove(cod)
    if acao == "trocar":
        entra = por or (reserva[0] if reserva else None)
        if entra is None or entra not in reserva:
            raise ErroPedido("sem fazenda de reserva para trocar")
        reserva.remove(entra)
        lote.append(entra)
        trocas[entra] = cod
    oferta = _oferta(engine, c)
    f = oferta[oferta.cod_imovel.isin(lote + reserva)].reset_index(drop=True)
    idx = {k: i for i, k in enumerate(f.cod_imovel)}
    chance = A.chances(f, nv, None, _pagamento(c))
    novo = Z.indicadores(
        f, [idx[k] for k in lote if k in idx], [idx[k] for k in reserva if k in idx], c, opcao, chance, nv, trocas
    )
    novo["solver"] = "troca_manual"
    ops = [novo if o["id"] == opcao else o for o in ops]
    with engine.begin() as con:
        _salvar_sugestao(con, p["id"], f"{acao}:{cod}", s["base"], ops)
        con.execute(text("update negocio.pedido set atualizado_em = now() where id = :id"), {"id": p["id"]})
    return obter_pedido(engine, pedido_id, cliente_id)


# --- interesse do dono --------------------------------------------------------------------------------------------


def registrar_resposta(
    engine: Engine,
    cod_imovel: str,
    nivel: str,
    canal: str | None = None,
    motivo: str | None = None,
    versao_termo: str | None = None,
    pedido_id: str | None = None,
    quando: dt.datetime | None = None,
    avancar_pedidos: bool = True,
) -> str:
    """Registra o que o dono respondeu. O nível só sobe com registro (data, canal e versão do termo); recusa e sem
    resposta valem com motivo. Contrato firme não volta. Guarda o resultado como gabarito da chance de aceite."""
    if nivel not in NIVEIS:
        raise ErroPedido(f"nível desconhecido: {nivel}")
    if nivel in ("interessado", "aceite_fase1", "contrato_firme") and not versao_termo:
        raise ErroPedido("o nível só sobe com a versão do termo aceito (LGPD)")
    quando = quando or _agora()
    with engine.begin() as con:
        atual = (
            con.execute(
                text("select nivel from negocio.interesse_dono where cod_imovel = :c"), {"c": cod_imovel}
            ).scalar()
            or "sem_contato"
        )
        if atual == "contrato_firme" and nivel != "contrato_firme":
            raise ErroPedido("contrato firme não volta de nível")
        if nivel in ORDEM_NIVEL and atual in ORDEM_NIVEL and ORDEM_NIVEL[nivel] < ORDEM_NIVEL[atual]:
            raise ErroPedido(f"o nível só sobe: está em {atual}")
        con.execute(
            text("""insert into negocio.interesse_evento (cod_imovel, nivel, canal, motivo, versao_termo, pedido_id,
                    ocorrido_em) values (:c, :n, :canal, :m, :v, :p, :q)"""),
            {"c": cod_imovel, "n": nivel, "canal": canal, "m": motivo, "v": versao_termo, "p": pedido_id, "q": quando},
        )
        con.execute(
            text("""insert into negocio.interesse_dono (cod_imovel, nivel, atualizado_em) values (:c, :n, :q)
                    on conflict (cod_imovel) do update
                    set nivel = excluded.nivel, atualizado_em = excluded.atualizado_em"""),
            {"c": cod_imovel, "n": nivel, "q": quando},
        )
        if nivel != "contatado":
            con.execute(
                text("""update negocio.contato_fila set estado = :e where cod_imovel = :c
                                and estado in ('na_fila', 'enviado')"""),
                {"e": "sem_resposta" if nivel == "sem_resposta" else "respondido", "c": cod_imovel},
            )
        if nivel in (*A.SUCESSO, "recusou"):
            from raiz.aprendizado.registro import registrar_gabarito

            registrar_gabarito(
                con,
                cod_imovel,
                "aceite_dono",
                quando.date(),
                "contato_dono",
                valor_num=1.0 if nivel in A.SUCESSO else 0.0,
                referencia=f"pedido:{pedido_id}" if pedido_id else None,
            )
        afetados = [
            r[0]
            for r in con.execute(
                text("""select distinct f.pedido_id from negocio.contato_fila f
                    join negocio.pedido p on p.id = f.pedido_id
                    where f.cod_imovel = :c and p.estado = 'buscando_interesse'"""),
                {"c": cod_imovel},
            )
        ]
    if avancar_pedidos:
        for pid in afetados:
            avancar(engine, str(pid))
    return nivel


# --- ondas de contato ---------------------------------------------------------------------------------------------


def _ranking(engine: Engine, con, p, c: CamposPedido) -> pd.DataFrame:
    """Todas as fazendas que podem ser contatadas para o pedido, na ordem: o lote da opção escolhida, as reservas e
    depois as demais pela mesma régua da opção (custo e risco)."""
    nv, fora = niveis(con), fora_para(con, p["cliente_id"])
    oferta = _oferta(engine, c)
    f = Z.filtrar(oferta, c.model_copy(update={"interesse": "qualquer"}), nv, fora).reset_index(drop=True)
    f["chance_aceite"] = A.chances(f, nv, A.historico_do_banco(con), _pagamento(c))
    f["qtd"] = Z.quantidade(f, c.meta.tipo)
    s = _ultima_sugestao(con, p["id"])
    op = next((o for o in s["opcoes"] if o["id"] == (p["opcao_escolhida"] or "segura")), None)
    ordem = {i["cod_imovel"]: k for k, i in enumerate(op["itens"])} if op else {}
    w = premissas()["otimizador"]["pesos"][p["opcao_escolhida"] or "segura"]
    unit = w["custo"] * Z._custo_usd(f) + w["risco"] * Z._risco_usd(f, f.chance_aceite.to_numpy(float), premissas())
    f["ordem_lote"] = [ordem.get(k, len(ordem) + 1) for k in f.cod_imovel]
    f["regua"] = unit
    return f.sort_values(["ordem_lote", "regua"]).reset_index(drop=True)


def _contatados(con, pedido_id) -> pd.DataFrame:
    return pd.DataFrame(
        con.execute(
            text("""select f.cod_imovel, f.onda_id, f.estado, f.chance_aceite, f.canal, f.enviado_em, f.prazo
                from negocio.contato_fila f where f.pedido_id = :p"""),
            {"p": pedido_id},
        )
        .mappings()
        .all(),
        columns=["cod_imovel", "onda_id", "estado", "chance_aceite", "canal", "enviado_em", "prazo"],
    )


def _canal(con, cod_imovel: str) -> str:
    """WhatsApp quando o dono tem contato registrado no esquema pessoal; senão carta (visita: parceiro local)."""
    tem = con.execute(
        text("""select 1 from pessoal.contato_imovel ci join pessoal.contato c on c.id = ci.contato_id
                              where ci.cod_imovel = :c limit 1"""),
        {"c": cod_imovel},
    ).first()
    return premissas()["ondas"]["canal_padrao"] if tem else "carta"


def nova_onda(engine: Engine, pedido_id: str, agora: dt.datetime | None = None) -> int:
    """Contata a próxima onda: bem mais fazendas do que a meta pede (a soma da chance de aceite vezes o que cada uma
    soma tem de passar a meta com folga), sem repetir quem já foi contatado. Devolve quantas foram contatadas."""
    from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote

    agora = agora or _agora()
    pr = premissas()["ondas"]
    with engine.begin() as con:
        p = _linha_pedido(con, pedido_id, None)
        c = CamposPedido.model_validate(p["campos"])
        rk = _ranking(engine, con, p, c)
        ja = _contatados(con, p["id"])
        n_onda = (
            int(
                con.execute(
                    text("select coalesce(max(numero), 0) from negocio.onda where pedido_id = :p"), {"p": p["id"]}
                ).scalar()
            )
            + 1
        )
        nv = niveis(con)
        q_de = dict(zip(rk.cod_imovel, rk.qtd, strict=True))
        ch_de = dict(zip(rk.cod_imovel, rk.chance_aceite, strict=True))
        garantido = sum(q_de.get(k, 0) * A.POR_NIVEL.get(nv.get(k, ""), 0) for k in ja.cod_imovel)
        pendente = sum(
            q_de.get(k, 0) * ch_de.get(k, 0)
            for k, e in zip(ja.cod_imovel, ja.estado, strict=True)
            if e in ("na_fila", "enviado")
        )
        folga = pr["folga"] if n_onda == 1 else pr["folga_seguintes"]
        precisa = folga * c.meta.valor - garantido - pendente
        novos = rk[~rk.cod_imovel.isin(set(ja.cod_imovel)) & (rk.cod_imovel.map(lambda k: nv.get(k)) != "recusou")]
        esc, acc = [], 0.0
        for li in novos.itertuples():
            if acc >= precisa and esc:
                break
            esc.append(li)
            acc += li.qtd * li.chance_aceite
        if not esc:
            return 0
        prazo = agora + dt.timedelta(days=int(pr["prazo_resposta_dias"]))
        oid = con.execute(
            text("""insert into negocio.onda (pedido_id, numero, fazendas, creditos_esperados, prazo, criada_em)
                    values (:p, :n, :f, :ce, :pz, :ag) returning id"""),
            {"p": p["id"], "n": n_onda, "f": len(esc), "ce": acc, "pz": prazo, "ag": agora},
        ).scalar_one()
        termo = premissas()["termo_versao_atual"]
        for li in esc:
            canal = _canal(con, li.cod_imovel)
            con.execute(
                text("""insert into negocio.contato_fila (pedido_id, onda_id, cod_imovel, canal, estado, chance_aceite,
                        simulado, enviado_em, prazo) values (:p, :o, :c, :canal, 'enviado', :ch, :sim, :ag, :pz)"""),
                {
                    "p": p["id"],
                    "o": oid,
                    "c": li.cod_imovel,
                    "canal": canal,
                    "ch": float(li.chance_aceite),
                    "sim": bool(pr["envio_simulado"]),
                    "ag": agora,
                    "pz": prazo,
                },
            )
            if nv.get(li.cod_imovel, "sem_contato") == "sem_contato":
                con.execute(
                    text("""insert into negocio.interesse_evento (cod_imovel, nivel, canal, versao_termo, pedido_id,
                            onda_id, ocorrido_em) values (:c, 'contatado', :canal, :v, :p, :o, :ag)"""),
                    {"c": li.cod_imovel, "canal": canal, "v": termo, "p": p["id"], "o": oid, "ag": agora},
                )
                con.execute(
                    text("""insert into negocio.interesse_dono (cod_imovel, nivel, atualizado_em)
                            values (:c, 'contatado', :ag) on conflict (cod_imovel) do update
                            set nivel = 'contatado', atualizado_em = excluded.atualizado_em
                            where negocio.interesse_dono.nivel = 'sem_contato'"""),
                    {"c": li.cod_imovel, "ag": agora},
                )
        # aprendizado: a chance de aceite de cada fazenda contatada fica congelada, com a versão do modelo
        registrar_lote(
            con,
            [
                Previsao(
                    li.cod_imovel, "aceite_dono", int(pr["prazo_resposta_dias"]), valor_num=float(li.chance_aceite)
                )
                for li in esc
            ],
            Versoes("aceite_dono", versao_modelo(), f"pedido:{p['id']}:onda:{n_onda}", agora.date()),
            f"onda {n_onda} do pedido {p['id']}",
        )
    return len(esc)


def solicitar_interesse(engine: Engine, pedido_id: str, cliente_id: int, opcao: str = "segura") -> dict:
    if opcao not in ("barata", "segura", "compacta"):
        raise ErroPedido("opção desconhecida")
    with engine.begin() as con:
        p = _linha_pedido(con, pedido_id, cliente_id)
        if p["estado"] not in ("lote_montado", "faltou"):
            raise ErroPedido("a busca de interesse já começou")
        s = _ultima_sugestao(con, p["id"])
        op = next((o for o in s["opcoes"] if o["id"] == opcao), None)
        if op is None:
            raise ErroPedido("o pedido não tem essa opção (a base não alcança nenhuma fazenda)")
        con.execute(
            text("""update negocio.pedido set estado = 'buscando_interesse', opcao_escolhida = :o,
                            atualizado_em = now() where id = :id"""),
            {"o": opcao, "id": p["id"]},
        )
        con.execute(text("delete from negocio.pedido_fazenda where pedido_id = :p"), {"p": p["id"]})
        for k, i in enumerate(op["itens"]):
            con.execute(
                text("""insert into negocio.pedido_fazenda (pedido_id, cod_imovel, papel, ordem, trocou)
                                values (:p, :c, :pa, :o, :t) on conflict do nothing"""),
                {"p": p["id"], "c": i["cod_imovel"], "pa": i["papel"], "o": k, "t": i.get("trocou")},
            )
    nova_onda(engine, pedido_id)
    avancar(engine, pedido_id)
    return obter_pedido(engine, pedido_id, cliente_id)


def _progresso(con, pedido_id, c: CamposPedido) -> dict:
    """Quanto da meta já tem dono interessado, com aceite e com contrato (cumulativo), entre os contatados."""
    ja = _contatados(con, pedido_id)
    if not len(ja):
        return {"com_interessado": 0.0, "com_aceite": 0.0, "com_contrato": 0.0, "q": {}}
    nv = niveis(con, list(ja.cod_imovel))
    of = pd.DataFrame(
        con.execute(
            text("select cod_imovel, atributos from negocio.oferta where cod_imovel = any(:c)"),
            {"c": list(ja.cod_imovel)},
        )
        .mappings()
        .all()
    )
    q = {}
    for r in of.to_dict("records") if len(of) else []:
        a = r["atributos"] or {}
        q[r["cod_imovel"]] = {
            "creditos": a.get("credito_p50") or 0,
            "hectares": a.get("area_ha") or 0,
            "flag_t_ano": a.get("flag_t_ano") or 0,
        }[c.meta.tipo]
    soma = {
        n: sum(q.get(k, 0) for k, v in nv.items() if v in grupo)
        for n, grupo in (
            ("com_interessado", Z.INTERESSADOS),
            ("com_aceite", Z.COM_ACEITE),
            ("com_contrato", ("contrato_firme",)),
        )
    }
    return {**soma, "q": q, "niveis": nv}


def avancar(engine: Engine, pedido_id: str, agora: dt.datetime | None = None) -> str:
    """Um passo da busca de interesse: vence quem não respondeu no prazo, fecha o grupo quando os interessados
    alcançam a meta (e avisa o cliente), senão chama a próxima onda; sem mais fazenda, diz o que faltou."""
    agora = agora or _agora()
    with engine.connect() as con:
        p = _linha_pedido(con, pedido_id, None)
    if p["estado"] != "buscando_interesse":
        return p["estado"]
    c = CamposPedido.model_validate(p["campos"])
    with engine.begin() as con:
        vencidos = [
            r[0]
            for r in con.execute(
                text("""select cod_imovel from negocio.contato_fila where pedido_id = :p and estado = 'enviado'
                    and prazo < :ag"""),
                {"p": p["id"], "ag": agora},
            )
        ]
    for cod in vencidos:
        registrar_resposta(
            engine,
            cod,
            "sem_resposta",
            "prazo",
            "não respondeu no prazo",
            None,
            str(p["id"]),
            agora,
            avancar_pedidos=False,
        )
    with engine.connect() as con:
        pg = _progresso(con, p["id"], c)
        pendentes = con.execute(
            text("""select count(*) from negocio.contato_fila where pedido_id = :p
                                        and estado in ('na_fila', 'enviado')"""),
            {"p": p["id"]},
        ).scalar()
    if pg["com_interessado"] >= c.meta.valor:
        _fechar_grupo(engine, p, c, pg, agora)
        return "grupo_pronto"
    if pendentes == 0:
        if nova_onda(engine, pedido_id, agora) == 0:
            _faltou(engine, p, c, pg)
            return "faltou"
    return "buscando_interesse"


def _fechar_grupo(engine: Engine, p, c: CamposPedido, pg: dict, agora: dt.datetime) -> None:
    """Escolhe, entre os interessados, o grupo que fecha a meta pela régua da opção escolhida; marca quem entrou no
    lugar de quem recusou e avisa o cliente (painel, e-mail e WhatsApp)."""
    nv = pg["niveis"]
    interessados = [k for k, v in nv.items() if v in Z.INTERESSADOS]
    oferta = _oferta(engine, c)
    f = oferta[oferta.cod_imovel.isin(interessados)].reset_index(drop=True)
    chance = A.chances(f, nv, None, _pagamento(c))
    r = Z.resolver(f, c, p["opcao_escolhida"] or "segura", chance)
    grupo = list(f.cod_imovel.iloc[r["sel"]])
    with engine.begin() as con:
        orig = [
            x.cod_imovel
            for x in con.execute(
                text("""select cod_imovel from negocio.pedido_fazenda where pedido_id = :p and papel = 'lote'
                    order by ordem"""),
                {"p": p["id"]},
            )
        ]
        saiu = [k for k in orig if k not in grupo]
        entrou = [k for k in grupo if k not in orig]
        trocou = dict(zip(entrou, saiu, strict=False))
        con.execute(text("delete from negocio.pedido_fazenda where pedido_id = :p"), {"p": p["id"]})
        for k, cod in enumerate(grupo):
            con.execute(
                text("""insert into negocio.pedido_fazenda (pedido_id, cod_imovel, papel, ordem, trocou)
                                values (:p, :c, 'lote', :o, :t)"""),
                {"p": p["id"], "c": cod, "o": k, "t": trocou.get(cod)},
            )
        for k, cod in enumerate([x for x in interessados if x not in grupo]):
            con.execute(
                text("""insert into negocio.pedido_fazenda (pedido_id, cod_imovel, papel, ordem)
                                values (:p, :c, 'reserva', :o)"""),
                {"p": p["id"], "c": cod, "o": 1000 + k},
            )
        con.execute(
            text("""update negocio.pedido set estado = 'grupo_pronto', grupo_pronto_em = :ag,
                            atualizado_em = now() where id = :id"""),
            {"ag": agora, "id": p["id"]},
        )
        con.execute(
            text("""update negocio.contato_fila set estado = 'cancelado' where pedido_id = :p
                            and estado in ('na_fila', 'enviado')"""),
            {"p": p["id"]},
        )
        ha = float(f.area_ha.iloc[r["sel"]].sum())
        notificar(
            con,
            p["cliente_id"],
            p["id"],
            "grupo_pronto",
            f"Grupo pronto: {len(grupo)} fazendas com dono interessado, {ha:,.0f} ha, fecham a meta do pedido. "
            "Reserve o grupo para negociar com exclusividade.".replace(",", "."),
        )


def _faltou(engine: Engine, p, c: CamposPedido, pg: dict) -> None:
    with engine.connect() as con:
        nv, fora = niveis(con), fora_para(con, p["cliente_id"])
    oferta = _oferta(engine, c)
    falta = max(c.meta.valor - pg["com_interessado"], 0.0)
    afr = Z.afrouxar(oferta, c, nv, fora, float(Z.quantidade(Z.filtrar(oferta, c, nv, fora), c.meta.tipo).sum()))
    with engine.begin() as con:
        con.execute(
            text("update negocio.pedido set estado = 'faltou', atualizado_em = now() where id = :id"), {"id": p["id"]}
        )
        con.execute(
            text("""insert into negocio.alerta_pedido (pedido_id, tipo, detalhe) values (:p, 'fazenda_com_problema',
                    cast(:d as jsonb))"""),
            {
                "p": p["id"],
                "d": json.dumps(
                    {
                        "texto": f"As fazendas da base acabaram: faltam {falta:,.0f} na meta.",
                        "falta": falta,
                        "afrouxar": [a["texto"] for a in afr],
                    }
                ),
            },
        )
        notificar(
            con,
            p["cliente_id"],
            p["id"],
            "faltou",
            f"A busca de interesse acabou sem fechar a meta: faltam {falta:,.0f}. Veja o que afrouxar no "
            "pedido.".replace(",", "."),
        )


def andamento(engine: Engine, pedido_id: str, cliente_id: int | None) -> dict:
    with engine.connect() as con:
        p = _linha_pedido(con, pedido_id, cliente_id)
        c = CamposPedido.model_validate(p["campos"])
        pg = _progresso(con, p["id"], c)
        ja = _contatados(con, p["id"])
        ondas = []
        for o in con.execute(text("select * from negocio.onda where pedido_id = :p order by numero"), {"p": p["id"]}):
            canais = sorted(set(ja.canal[ja.onda_id == o.id]))
            ondas.append(
                {"numero": o.numero, "data": o.criada_em.isoformat(), "contatados": int(o.fazendas), "canais": canais}
            )
        nv = pg.get("niveis") or {}
        motivos = con.execute(
            text("""select motivo, count(distinct cod_imovel) as n from negocio.interesse_evento
                    where pedido_id = :p and nivel in ('recusou', 'sem_resposta') and motivo is not null
                    group by motivo order by n desc"""),
            {"p": p["id"]},
        ).all()
        pf = {
            r.cod_imovel: (r.papel, r.trocou)
            for r in con.execute(
                text("select cod_imovel, papel, trocou from negocio.pedido_fazenda where pedido_id = :p"),
                {"p": p["id"]},
            )
        }
        fora = fora_para(con, p["cliente_id"])
        prox = con.execute(
            text("""select max(prazo) from negocio.contato_fila where pedido_id = :p
                                   and estado = 'enviado'"""),
            {"p": p["id"]},
        ).scalar()
        alerta_faltou = con.execute(
            text("""select detalhe from negocio.alerta_pedido where pedido_id = :p
                                            and detalhe ? 'afrouxar' order by id desc limit 1"""),
            {"p": p["id"]},
        ).scalar()
    cods = sorted(set(pf) | set(ja.cod_imovel))
    of = _oferta(engine, c)
    of = of[of.cod_imovel.isin(cods) & ~of.cod_imovel.isin(fora)]
    fazendas = []
    for li in of.to_dict("records"):
        papel, trocou = pf.get(li["cod_imovel"], ("reserva", None))
        fazendas.append(Z.fazenda_do_lote(li, papel, nv.get(li["cod_imovel"], "sem_contato"), trocou))
    return {
        "pedido": str(p["id"]),
        "status": p["estado"],
        "meta": c.meta.valor,
        "com_interessado": round(pg["com_interessado"], 0),
        "com_aceite": round(pg["com_aceite"], 0),
        "com_contrato": round(pg["com_contrato"], 0),
        "ondas": ondas,
        "contatados": int(len(ja)),
        "recusas": int(sum(1 for k in ja.cod_imovel if nv.get(k) == "recusou")),
        "sem_resposta": int(sum(1 for k in ja.cod_imovel if nv.get(k) == "sem_resposta")),
        "motivos": [{"motivo": m.motivo, "fazendas": int(m.n)} for m in motivos],
        "fazendas": fazendas,
        "grupo_pronto_em": p["grupo_pronto_em"].isoformat() if p["grupo_pronto_em"] else None,
        "proxima_onda_em": prox.isoformat() if prox and p["estado"] == "buscando_interesse" else None,
        "faltou": {"falta": alerta_faltou.get("falta", 0), "afrouxar": alerta_faltou.get("afrouxar", [])}
        if p["estado"] == "faltou" and alerta_faltou
        else None,
    }


# --- reserva do grupo (Pix) -----------------------------------------------------------------------------------------


def _grupo(con, pedido_id) -> list[str]:
    return [
        r[0]
        for r in con.execute(
            text("""select cod_imovel from negocio.pedido_fazenda where pedido_id = :p
                                              and papel = 'lote' order by ordem"""),
            {"p": pedido_id},
        )
    ]


def _ha_do_grupo(con, cods: list[str]) -> float:
    return float(
        con.execute(
            text("""select coalesce(sum(area_restauracao_ha), 0) from negocio.oferta
                                     where cod_imovel = any(:c)"""),
            {"c": cods},
        ).scalar()
        or 0
    )


def valor_reserva(ha: float) -> float:
    r = premissas()["reserva"]
    return round(max(float(r["minimo_rs"]), float(r["fracao_da_conexao"]) * float(r["conexao_rs_ha"]) * ha), 2)


def _cobranca_json(pedido_id, valor: float, ha: float, dias: int, cob=None, reserva=None, base_url: str = "") -> dict:
    r = premissas()["reserva"]
    expira = cob.expira_em if cob is not None else None
    pendente = bool(cob is not None and cob.estado == "pendente" and expira is not None and expira > _agora())
    aprovar_url = None
    if (
        reserva is not None
        and reserva.estado == "aguardando_confirmacao"
        and reserva.confirmacao_expira is not None
        and reserva.confirmacao_expira > _agora()
        and reserva.preco_valido_ate is not None
        and reserva.preco_valido_ate > _agora()
        and reserva.confirmacao_token_cifrado
    ):
        token = _cofre().decifrar(reserva.confirmacao_token_cifrado)
        aprovar_url = f"{base_url.rstrip('/')}/reservas/confirmar/{token}"
    return {
        "pedido": str(pedido_id),
        "valor_brl": valor,
        "hectares": round(ha, 1),
        "prazo_dias": dias,
        "preco_valido_ate": reserva.preco_valido_ate.isoformat()
        if reserva is not None and reserva.preco_valido_ate
        else None,
        "exclusividade": {"dias": dias, "inicio": "apos_pagamento_confirmado"},
        "abatimento": (
            f"A reserva é abatida da conexão de R$ {r['conexao_rs_ha']:.0f} por hectare quando o contrato "
            "fecha; se o prazo vencer sem contrato, o grupo volta para a base."
        ),
        "pix": {"copia_e_cola": cob.pix_copia_cola, "qr_svg": cob.pix_qr_svg, "expira_em": expira.isoformat()}
        if pendente
        else None,
        "pago": bool(cob is not None and cob.estado == "paga"),
        "recibo_aprovacao": reserva.recibo_aprovacao if reserva is not None else None,
        "aprovacao_url": aprovar_url,
        "reservado_ate": reserva.fim.isoformat() if reserva is not None and reserva.fim else None,
        "modo_teste": bool(cob is not None and cob.modo == "teste"),
        "estado": reserva.estado if reserva is not None else None,
        "aguardando_confirmacao": bool(reserva is not None and reserva.estado == "aguardando_confirmacao"),
        "confirmacao": "Uma pessoa autenticada da empresa aprova pelo link; só então sai o Pix. O agente não paga."
        if aprovar_url
        else None,
    }


def cobranca_do_pedido(engine: Engine, pedido_id: str, cliente_id: int, base_url: str = "") -> dict:
    with engine.connect() as con:
        p = _linha_pedido(con, pedido_id, cliente_id)
        c = CamposPedido.model_validate(p["campos"])
        res = con.execute(
            text("select * from negocio.reserva where pedido_id = :p order by id desc limit 1"), {"p": p["id"]}
        ).first()
        if res is None:
            ha = _ha_do_grupo(con, _grupo(con, p["id"]))
            return _cobranca_json(p["id"], valor_reserva(ha), ha, c.reserva_dias)
        cob = con.execute(
            text("select * from negocio.cobranca where reserva_id = :r order by id desc limit 1"), {"r": res.id}
        ).first()
        return _cobranca_json(p["id"], float(res.valor_rs), res.ha, res.dias, cob, res, base_url)


def _cobrar(con, rid: int, p, valor: float, validade_s: int | None = None) -> None:
    """Cria Pix somente após aprovação humana. Trava da reserva e registro local impedem repetição local."""
    if con.execute(text("select 1 from negocio.cobranca where reserva_id=:r"), {"r": rid}).first():
        return
    validade = int(premissas()["reserva"]["pix_validade_s"])
    if validade_s is not None:
        validade = min(validade, validade_s)
    if validade <= 0:
        raise ErroPedido("preço da reserva vencido: prepare uma nova aprovação")
    cob = pix.criar(valor, f"Reserva Raíz {str(p['id'])[:8]}", validade, chave_idempotencia=f"reserva:{rid}")
    qr = pix.qr_svg(cob.copia_e_cola)
    con.execute(
        text("""insert into negocio.cobranca (reserva_id, provedor, modo, externo_id, valor_rs, estado,
                pix_copia_cola, expira_em, pix_qr_svg)
                values (:r, 'abacatepay', :m, :x, :v, 'pendente', :pc, :e, :qr)"""),
        {
            "r": rid,
            "m": cob.modo,
            "x": cob.externo_id,
            "v": valor,
            "pc": cob.copia_e_cola,
            "e": cob.expira_em,
            "qr": qr,
        },
    )


def mensagem_confirmacao_reserva(pedido_id: str, valor: float, ha: float, dias: int, base_url: str, token: str) -> str:
    """Mensagem humana: formata apenas números, preservando domínio e token do link de aprovação."""
    trocar = str.maketrans(",.", ".,")
    dinheiro = f"{valor:,.2f}".translate(trocar)
    hectares = f"{ha:,.0f}".translate(trocar)
    link = f"{base_url.rstrip('/')}/reservas/confirmar/{token}"
    return (
        f"O agente de IA da sua empresa pediu a reserva do grupo do pedido {str(pedido_id)[:8]} "
        f"(R$ {dinheiro}, {hectares} ha, {dias} dias). Uma pessoa da empresa precisa "
        f"confirmar para gerar o Pix: {link} (vale por 48 horas)."
    )


def mensagem_confirmacao_reserva(pedido_id: str, valor: float, ha: float, dias: int, base_url: str, token: str) -> str:
    """Mensagem humana: formata apenas números, preservando domínio e token do link de aprovação."""
    trocar = str.maketrans(",.", ".,")
    dinheiro = f"{valor:,.2f}".translate(trocar)
    hectares = f"{ha:,.0f}".translate(trocar)
    link = f"{base_url.rstrip('/')}/reservas/confirmar/{token}"
    return (
        f"O agente de IA da sua empresa pediu a reserva do grupo do pedido {str(pedido_id)[:8]} "
        f"(R$ {dinheiro}, {hectares} ha, {dias} dias). Uma pessoa da empresa precisa "
        f"confirmar para gerar o Pix: {link} (vale por 48 horas)."
    )


def reservar(engine: Engine, pedido_id: str, cliente_id: int, por_agente: str | None = None,
             base_url: str = "") -> dict:  # fmt: skip
    """Prepara reserva para uma pessoa da empresa. Agente recebe link, nunca aprova nem paga.

    A reserva e o preço aguardam aprovação por 48 horas. A exclusividade começa apenas quando o Pix é confirmado.
    O caminho legado sem por_agente representa a ação explícita de uma pessoa autenticada e aprova ao final.
    Nenhum callback externo roda durante a preparação: só a notificação interna, sem o segredo do link.
    """
    from raiz import salvaguardas as SG
    from raiz.publica.aprovacao import aprovar

    token = None
    with engine.begin() as con:
        p = _linha_pedido(con, pedido_id, cliente_id)
        p = con.execute(text("select * from negocio.pedido where id=:p for update"), {"p": p["id"]}).mappings().one()
        if p["estado"] != "grupo_pronto":
            raise ErroPedido("a reserva vale para o grupo pronto (todos os donos com interesse)")
        cods = _grupo(con, p["id"])
        if not cods:
            raise ErroPedido("o grupo não tem fazendas para reservar")
        SG.exigir_para_reserva(engine, cods)
        aberta = con.execute(
            text("""select * from negocio.reserva where pedido_id = :p
                    and estado in ('aguardando_pagamento', 'aguardando_confirmacao') order by id desc limit 1"""),
            {"p": p["id"]},
        ).first()
        if (
            aberta is not None
            and aberta.estado == "aguardando_confirmacao"
            and (
                aberta.confirmacao_expira <= _agora()
                or (aberta.preco_valido_ate is not None and aberta.preco_valido_ate <= _agora())
            )
        ):
            con.execute(
                text("""update negocio.reserva set estado='cancelada', confirmacao_hash=null,
                confirmacao_token_cifrado=null where id=:id"""),
                {"id": aberta.id},
            )
            aberta = None
        if aberta is None:
            ocupadas = {
                r[0]
                for r in con.execute(
                    text("select cod_imovel from negocio.reserva_fazenda where ativa and cod_imovel = any(:c)"),
                    {"c": cods},
                )
            }
            if ocupadas:
                raise ErroPedido(f"{len(ocupadas)} fazendas do grupo já estão reservadas: refaça o grupo")
            c = CamposPedido.model_validate(p["campos"])
            ha = _ha_do_grupo(con, cods)
            valor = valor_reserva(ha)
            token = secrets.token_urlsafe(24)
            validade = _agora() + dt.timedelta(hours=48)
            rid = con.execute(
                text("""insert into negocio.reserva (pedido_id, cliente_id, estado, ha, valor_rs, dias, pedida_por,
                        confirmacao_hash, confirmacao_expira, confirmacao_token_cifrado, preco_valido_ate)
                        values (:p, :c, 'aguardando_confirmacao', :ha, :v, :d, :q, :h, :x, :tc, :x) returning id"""),
                {
                    "p": p["id"],
                    "c": cliente_id,
                    "ha": ha,
                    "v": valor,
                    "d": c.reserva_dias,
                    "q": por_agente or "pessoa",
                    "h": _hash(token),
                    "x": validade,
                    "tc": _cofre().cifrar(token),
                },
            ).scalar_one()
            for cod in cods:
                con.execute(
                    text("insert into negocio.reserva_fazenda (reserva_id, cod_imovel) values (:r, :c)"),
                    {"r": rid, "c": cod},
                )
            con.execute(
                text("""insert into negocio.reserva_evento (reserva_id, evento, quem, valor_rs, detalhe)
                values (:r, 'criada', :q, :v, cast(:d as jsonb))"""),
                {
                    "r": rid,
                    "q": f"agente:{por_agente}" if por_agente else f"cliente:{cliente_id}",
                    "v": valor,
                    "d": json.dumps(
                        {"dias": c.reserva_dias, "fazendas": len(cods), "ha": ha, "estado": "aguardando_confirmacao"}
                    ),
                },
            )
            con.execute(
                text("""insert into negocio.notificacao (cliente_id,pedido_id,tipo,canal,texto,estado)
                values (:c,:p,'confirmar_reserva','painel',:t,'enviada')"""),
                {
                    "c": cliente_id,
                    "p": p["id"],
                    "t": "Reserva preparada. Uma pessoa da empresa deve abrir "
                    "a página da reserva para aprovar e gerar o Pix.",
                },
            )
        elif aberta.estado == "aguardando_confirmacao":
            if not aberta.confirmacao_token_cifrado:
                raise ErroPedido("reserva antiga sem link recuperável: aguarde vencer ou peça revisão humana")
            token = _cofre().decifrar(aberta.confirmacao_token_cifrado)
    if not por_agente and token:
        return aprovar(engine, token, cliente_id)
    return cobranca_do_pedido(engine, pedido_id, cliente_id, base_url)


ENVIO_CONFIRMACAO: Callable[[int, str], None] | None = None  # legado; preparação não executa envio externo


def confirmar_reserva(engine: Engine, token: str, quem: str = "pessoa", cliente_id: int | None = None) -> dict:
    """Adaptador interno legado. Rotas públicas usam aprovacao.aprovar com empresa autenticada obrigatória."""
    from raiz.publica.aprovacao import aprovar

    if cliente_id is None:
        with engine.connect() as con:
            cliente_id = con.execute(
                text("select cliente_id from negocio.reserva where confirmacao_hash=:h"), {"h": _hash(token)}
            ).scalar()
        if cliente_id is None:
            raise ErroPedido("link de confirmação inválido, usado ou vencido: peça a reserva de novo")
    return aprovar(engine, token, cliente_id)


def confirmar_pagamento(engine: Engine, externo_id: str, quando: dt.datetime | None = None, quem: str = "pix") -> str:
    """Pagamento entrou: a reserva vale pelo prazo e as fazendas somem para os outros clientes. Se alguma fazenda já
    estiver em outra reserva ativa, a reserva fica em conflito (o dinheiro volta) e o cliente é avisado."""
    quando = quando or _agora()
    with engine.begin() as con:
        cob = con.execute(
            text("select * from negocio.cobranca where externo_id = :x for update"), {"x": externo_id}
        ).first()
        if cob is None:  # cobrança da API pública (recarga do saldo ou sinal da liberação)?
            from raiz.publica import conta as CT

            r = CT.confirmar_cobranca(engine, externo_id, quando)
            if r is not None:
                return r
            raise ErroPedido("cobrança desconhecida")
        if cob.estado == "paga":
            return "ja_paga"
        res = con.execute(text("select * from negocio.reserva where id = :r"), {"r": cob.reserva_id}).first()
        con.execute(
            text("update negocio.cobranca set estado = 'paga', paga_em = :q where id = :id"),
            {"q": quando, "id": cob.id},
        )
    try:
        with engine.begin() as con:
            fim = quando + dt.timedelta(days=int(res.dias))
            con.execute(text("update negocio.reserva_fazenda set ativa = true where reserva_id = :r"), {"r": res.id})
            con.execute(
                text("""update negocio.reserva set estado = 'ativa', inicio = :i, fim = :f where id = :r"""),
                {"i": quando, "f": fim, "r": res.id},
            )
            con.execute(
                text("update negocio.pedido set estado = 'reservado', atualizado_em = now() where id = :p"),
                {"p": res.pedido_id},
            )
            con.execute(
                text("""insert into negocio.reserva_evento (reserva_id, evento, quem, valor_rs, detalhe)
                                values (:r, 'paga', :q, :v, cast(:d as jsonb))"""),
                {
                    "r": res.id,
                    "q": quem,
                    "v": cob.valor_rs,
                    "d": json.dumps({"inicio": quando.isoformat(), "fim": fim.isoformat()}),
                },
            )
            notificar(
                con,
                res.cliente_id,
                res.pedido_id,
                "reservado",
                f"Reserva paga: o grupo é seu com exclusividade até {fim:%d/%m/%Y}.",
            )
        return "ativa"
    except IntegrityError:
        with engine.begin() as con:
            con.execute(text("update negocio.reserva set estado = 'conflito' where id = :r"), {"r": res.id})
            con.execute(
                text("""insert into negocio.reserva_evento (reserva_id, evento, quem, valor_rs)
                                values (:r, 'conflito', :q, :v)"""),
                {"r": res.id, "q": quem, "v": cob.valor_rs},
            )
            notificar(
                con,
                res.cliente_id,
                res.pedido_id,
                "reserva_conflito",
                "Uma fazenda do grupo foi reservada por outro cliente antes do pagamento; o valor será "
                "devolvido e o grupo refeito.",
            )
        return "conflito"


def expirar_reservas(engine: Engine, agora: dt.datetime | None = None) -> int:
    """Reserva que venceu sem contrato: o grupo volta para a base. Reserva do agente que ninguém confirmou em 48 horas
    é cancelada (nada foi cobrado)."""
    agora = agora or _agora()
    with engine.begin() as con:
        for r in con.execute(
            text("""update negocio.reserva set estado = 'cancelada', confirmacao_hash = null,
                    confirmacao_token_cifrado = null
                    where estado = 'aguardando_confirmacao' and confirmacao_expira < :a returning id"""),
            {"a": agora},
        ).all():
            con.execute(
                text("""insert into negocio.reserva_evento (reserva_id, evento, quem)
                        values (:r, 'sem_confirmacao', 'raiz')"""),
                {"r": r.id},
            )
        rs = con.execute(
            text("""update negocio.reserva set estado = 'expirada' where estado = 'ativa' and fim < :a
                                 returning id, pedido_id, cliente_id, valor_rs"""),
            {"a": agora},
        ).all()
        for r in rs:
            con.execute(text("update negocio.reserva_fazenda set ativa = false where reserva_id = :r"), {"r": r.id})
            con.execute(
                text("""update negocio.pedido set estado = 'reserva_vencida', atualizado_em = now()
                                where id = :p"""),
                {"p": r.pedido_id},
            )
            con.execute(
                text("""insert into negocio.reserva_evento (reserva_id, evento, quem, valor_rs)
                                values (:r, 'expirada', 'raiz', :v)"""),
                {"r": r.id, "v": r.valor_rs},
            )
            notificar(
                con,
                r.cliente_id,
                r.pedido_id,
                "reserva_vencida",
                "A reserva venceu sem contrato: as fazendas voltaram para a base.",
            )
    return len(rs)


def converter_reserva(engine: Engine, reserva_id: int, ha_assinados: float, quem: str = "raiz") -> dict:
    """Contrato fechado: a reserva vira contrato e o valor pago é abatido da conexão por hectare do grupo que assinou.
    As fazendas seguem fora da base dos outros clientes."""
    r = premissas()["reserva"]
    with engine.begin() as con:
        res = con.execute(
            text("select * from negocio.reserva where id = :r and estado = 'ativa'"), {"r": reserva_id}
        ).first()
        if res is None:
            raise ErroPedido("reserva ativa não encontrada")
        conexao = float(r["conexao_rs_ha"]) * ha_assinados
        abatido = min(float(res.valor_rs), conexao)
        con.execute(
            text("update negocio.reserva set estado = 'convertida', abatido_rs = :a where id = :r"),
            {"a": abatido, "r": reserva_id},
        )
        con.execute(
            text("update negocio.pedido set estado = 'contrato', atualizado_em = now() where id = :p"),
            {"p": res.pedido_id},
        )
        con.execute(
            text("""insert into negocio.reserva_evento (reserva_id, evento, quem, valor_rs, detalhe)
                            values (:r, 'convertida', :q, :v, cast(:d as jsonb))"""),
            {
                "r": reserva_id,
                "q": quem,
                "v": abatido,
                "d": json.dumps(
                    {"ha_assinados": ha_assinados, "conexao_rs": conexao, "a_pagar_rs": round(conexao - abatido, 2)}
                ),
            },
        )
    return {"conexao_rs": round(conexao, 2), "abatido_rs": round(abatido, 2), "a_pagar_rs": round(conexao - abatido, 2)}


# --- vigia do pedido salvo ----------------------------------------------------------------------------------------

# fazenda com problema num pedido que já tem grupo em formação ou fechado: aviso em todos os canais (e-mail e WhatsApp
# simulados até haver enviador); antes disso, painel e e-mail
CANAIS_PROBLEMA_GRUPO = ("painel", "email", "whatsapp")
CANAIS_PROBLEMA_LOTE = ("painel", "email")
ESTADOS_COM_GRUPO = ("buscando_interesse", "grupo_pronto", "reservado")


def _alerta(
    con, pedido_id, tipo: str, cod: str | None, texto_: str, detalhe: dict | None = None, chave: str | None = None
) -> bool:
    """Grava o alerta sem repetir. Com `chave` (um fato: o alerta da vigilância, a leitura da certidão), o mesmo fato
    nunca é avisado de novo, mesmo depois de visto; sem chave, não repete enquanto o anterior não foi visto."""
    if chave:
        ja = con.execute(
            text("""select 1 from negocio.alerta_pedido where pedido_id = :p and tipo = :t
                    and detalhe->>'chave' = :k"""),
            {"p": pedido_id, "t": tipo, "k": chave},
        ).first()
    else:
        ja = con.execute(
            text("""select 1 from negocio.alerta_pedido where pedido_id = :p and tipo = :t
                    and coalesce(cod_imovel, '') = coalesce(:c, '') and visto_em is null"""),
            {"p": pedido_id, "t": tipo, "c": cod},
        ).first()
    if ja:
        return False
    corpo = {"texto": texto_, **(detalhe or {}), **({"chave": chave} if chave else {})}
    con.execute(
        text("""insert into negocio.alerta_pedido (pedido_id, tipo, cod_imovel, detalhe)
                        values (:p, :t, :c, cast(:d as jsonb))"""),
        {"p": pedido_id, "t": tipo, "c": cod, "d": json.dumps(corpo, default=str)},
    )
    return True


def _motivo_da_oferta(li) -> tuple[str, str]:
    if li.embargo:
        return "embargo", "embargo"
    if li.problema:
        return "desmatamento", "desmatamento ou alerta depois de 2020"
    if li.bloqueio:
        return "bloqueio", "bloqueio territorial"
    return "caminho_terra", "caminho da terra que o pedido não aceita"


def _fazendas_novas(engine: Engine, o: dict, a: dict, desde) -> list[dict]:
    """Fazendas do lote novo que não estavam no lote anterior da mesma opção; `nova_na_base` quando o dado delas
    entrou ou mudou na oferta depois do lote anterior."""
    antes = {i["cod_imovel"] for i in a.get("itens") or [] if i.get("papel") == "lote"}
    entram = [i for i in o.get("itens") or [] if i.get("papel") == "lote" and i["cod_imovel"] not in antes]
    quando = {}
    if entram and desde is not None:
        with engine.connect() as con:
            quando = dict(
                con.execute(
                    text("select cod_imovel, atualizado_em from negocio.oferta where cod_imovel = any(:c)"),
                    {"c": [i["cod_imovel"] for i in entram]},
                ).all()
            )
    out = []
    for i in entram:
        cod = i["cod_imovel"]
        nova = None
        if cod in quando and quando[cod] is not None:
            nova = bool(pd.Timestamp(quando[cod]) > pd.Timestamp(desde))
        out.append(
            {
                "cod_imovel": cod,
                "municipio": i.get("municipio"),
                "uf": i.get("uf"),
                "creditos": i.get("creditos"),
                "custo_usd_credito": i.get("custo_usd_credito"),
                "nova_na_base": nova,
            }
        )
    return out


def vigiar(engine: Engine, fatos_de=None) -> dict:
    """O pedido salvo vira alerta (docs/cena-alvo.md, passo 9):

    - fazenda nova que melhora o lote: refaz a base e as opções com o dado novo; avisa quando o custo por crédito cai
      ao menos 3% ou o lote passa a fechar a meta, dizendo quais fazendas entraram no lote;
    - fazenda do grupo com problema: desmatamento ou embargo novos que a vigilância diária viu depois que o pedido
      foi salvo, matrícula cancelada nas certidões lidas (raiz/vigilancia/pedidos.py), e o que o motor refez
      (embargo, desmatamento, bloqueio, saiu da base, caminho da terra que o pedido não aceita).

    O mesmo fato nunca é avisado duas vezes. `fatos_de(cods, desde)` troca a fonte dos fatos (testes)."""
    if fatos_de is None:
        from raiz.vigilancia.pedidos import fatos as fatos_de
    melhora = float(premissas()["vigia"]["melhora_minima"])
    out = {"pedidos": 0, "lote_melhorou": 0, "fazenda_com_problema": 0, "fatos": {}}
    with engine.connect() as con:
        ps = (
            con.execute(
                text("""select * from negocio.pedido where estado in ('lote_montado', 'buscando_interesse',
                                 'grupo_pronto', 'reservado', 'faltou')""")
            )
            .mappings()
            .all()
        )
    for p in ps:
        out["pedidos"] += 1
        c = CamposPedido.model_validate(p["campos"])
        with engine.connect() as con:
            s = _ultima_sugestao(con, p["id"])
            nv, fora = niveis(con), fora_para(con, p["cliente_id"])
            hist = A.historico_do_banco(con)
            meus = [
                r[0]
                for r in con.execute(
                    text("select cod_imovel from negocio.pedido_fazenda where pedido_id = :p and papel <> 'fora'"),
                    {"p": p["id"]},
                )
            ]
        oferta = _oferta(engine, c)
        if not meus:
            op = next((o for o in s["opcoes"] if o["id"] == (p["opcao_escolhida"] or "barata")), None)
            meus = [i["cod_imovel"] for i in op["itens"]] if op else []
        canais = CANAIS_PROBLEMA_GRUPO if p["estado"] in ESTADOS_COM_GRUPO else CANAIS_PROBLEMA_LOTE
        ok = set(Z.filtrar(oferta, c.model_copy(update={"interesse": "qualquer"}), nv, set()).cod_imovel)
        por_cod = oferta.set_index("cod_imovel")
        novos_alertas: list[tuple[str, str, dict, str | None]] = []
        # 1. o que o motor refez: a fazenda não passa mais no filtro do pedido
        for cod in meus:
            if cod in ok:
                continue
            if cod in por_cod.index:
                motivo, texto_motivo = _motivo_da_oferta(por_cod.loc[cod])
            else:
                motivo, texto_motivo = "saiu_da_base", "saiu da base (matrícula cancelada ou dado do município refeito)"
            novos_alertas.append(
                (cod, f"Fazenda do lote com problema: {texto_motivo}.", {"motivo": motivo, "fonte": "motor"}, None)
            )
        # 2. fatos novos do dia: vigilância (desmatamento, embargo) e certidões (matrícula cancelada)
        desde = (p["criado_em"] or _agora()).date()
        for f in fatos_de(meus, desde):
            novos_alertas.append((f.cod_imovel, f.texto, {"motivo": f.motivo, **f.detalhe}, f.chave))
        with engine.begin() as con:
            for cod, tx, det, chave in novos_alertas:
                if _alerta(con, p["id"], "fazenda_com_problema", cod, tx, det, chave):
                    out["fazenda_com_problema"] += 1
                    out["fatos"][det["motivo"]] = out["fatos"].get(det["motivo"], 0) + 1
                    notificar(con, p["cliente_id"], p["id"], "fazenda_com_problema", tx, canais=canais)
        if p["estado"] not in ("lote_montado", "faltou"):
            continue
        b, ops, _ = Z.opcoes(oferta, c, nv, fora, hist, _pagamento(c))
        antigo = {o["id"]: o for o in s["opcoes"]}
        for o in ops:
            a = antigo.get(o["id"])
            if a is None:
                continue
            c_novo, c_velho = o["custo_usd_credito"]["p50"], (a.get("custo_usd_credito") or {}).get("p50")
            mais_barato = c_novo is not None and c_velho and c_novo <= (1 - melhora) * c_velho
            fechou = o["alcanca_meta"] and not a.get("alcanca_meta")
            if mais_barato or fechou:
                novas = _fazendas_novas(engine, o, a, s.get("criada_em"))
                quais = ""
                if novas:
                    cods = ", ".join(n["cod_imovel"] for n in novas[:3])
                    mais = f" e mais {len(novas) - 3}" if len(novas) > 3 else ""
                    quais = f" Fazendas novas no lote: {cods}{mais}."
                tx = (
                    f"O lote melhorou na opção {o['id']}: custo por crédito de US$ {c_velho:.2f} para US$ {c_novo:.2f}."
                    if mais_barato
                    else f"O lote da opção {o['id']} agora fecha a meta."
                ) + quais
                det = {
                    "opcao": o["id"],
                    "custo_antes_usd": c_velho,
                    "custo_agora_usd": c_novo,
                    "fecha_meta": bool(o["alcanca_meta"]),
                    "fazendas_novas": novas,
                }
                with engine.begin() as con:
                    _salvar_sugestao(con, p["id"], "vigia", b, ops)
                    if _alerta(con, p["id"], "lote_melhorou", None, tx, det):
                        out["lote_melhorou"] += 1
                        notificar(con, p["cliente_id"], p["id"], "lote_melhorou", tx, canais=("painel", "email"))
                break
    return out


def notificacoes(engine: Engine, cliente_id: int) -> list[dict]:
    with engine.connect() as con:
        rs = con.execute(
            text("""select id, pedido_id, tipo, texto, criada_em, lida_em from negocio.notificacao
                                 where cliente_id = :c and canal = 'painel' order by id desc limit 200"""),
            {"c": cliente_id},
        ).all()
    return [
        {
            "id": r.id,
            "pedido": str(r.pedido_id) if r.pedido_id else None,
            "tipo": r.tipo,
            "texto": r.texto,
            "data": r.criada_em.isoformat(),
            "lida": r.lida_em is not None,
        }
        for r in rs
    ]


def pedidos_abertos(engine: Engine) -> list[str]:
    with engine.connect() as con:
        return [
            str(r[0]) for r in con.execute(text("select id from negocio.pedido where estado = 'buscando_interesse'"))
        ]


def contatados_do_pedido(engine: Engine, pedido_id: str) -> list[str]:
    with engine.connect() as con:
        return list(_contatados(con, pedido_id).cod_imovel)


__all__ = [
    "ErroPedido",
    "andamento",
    "avancar",
    "cliente_da_sessao",
    "cobranca_do_pedido",
    "confirmar_link",
    "confirmar_pagamento",
    "converter_reserva",
    "criar_cliente",
    "criar_pedido",
    "expirar_reservas",
    "mudar_lote",
    "notificacoes",
    "nova_onda",
    "obter_pedido",
    "pedidos_do_cliente",
    "pedir_link",
    "registrar_resposta",
    "reservar",
    "solicitar_interesse",
    "vigiar",
]
