"""A conta da empresa na API pública e no MCP: nada grátis.

- A empresa abre a conta com o CNPJ (validado; só o HMAC e a forma mascarada ficam guardados) e aceita os termos de
  uso; ganha 3 créditos de teste por CNPJ (abrir outra chave ou outra conta não dá mais testes).
- Depois, cada chamada custa o preço da tabela versionada (raiz/regras/padroes/api_publica.yaml) e sai do saldo. Sem
  saldo, a chamada responde 402 com o link de uma recarga por Pix, que uma pessoa paga (nunca o agente).
- Liberação, igual ao app: montar lote e ver o detalhe da fazenda só depois do sinal pago por Pix e do contrato aceito
  com a cláusula de não contornar. Pagar a API não pula essa trava.
- Anti-raspagem: fazendas vistas e municípios consultados por mês; passou do alerta, o fundador é avisado; passou do
  bloqueio, a conta para até virar licença de dados (preço separado, aprovação do fundador).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import secrets
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import Engine, text

ARQ = Path(__file__).resolve().parents[1] / "regras" / "padroes" / "api_publica.yaml"


class ErroConta(ValueError):
    """Erro que a empresa (ou o agente dela) precisa corrigir."""

    def __init__(self, slug: str, detalhe: str, corrigir: str, status: int = 422, **extra):
        super().__init__(detalhe)
        self.slug, self.detalhe, self.corrigir, self.status, self.extra = slug, detalhe, corrigir, status, extra


@lru_cache(maxsize=4)
def _ler(arq: str, _marca: float) -> dict:
    r = yaml.safe_load(Path(arq).read_text(encoding="utf-8"))
    r["versao_completa"] = f"{r['versao']}+{hashlib.sha256(Path(arq).read_bytes()).hexdigest()[:8]}"
    return r


def premissas(arq: Path | None = None) -> dict:
    a = Path(arq or ARQ)
    return _ler(str(a), a.stat().st_mtime)


def preco(ferramenta: str) -> float:
    return float(premissas()["precos"].get(ferramenta, 0) or 0)


# --- CNPJ ---------------------------------------------------------------------------------------------------------


def so_digitos(x: str) -> str:
    return re.sub(r"\D", "", x or "")


def cnpj_valido(cnpj: str) -> bool:
    d = so_digitos(cnpj)
    if len(d) != 14 or d == d[0] * 14:
        return False
    for n in (12, 13):
        pesos = list(range(n - 7, 1, -1)) + list(range(9, 1, -1))
        s = sum(int(x) * w for x, w in zip(d[:n], pesos, strict=True))
        dv = 0 if s % 11 < 2 else 11 - s % 11
        if int(d[n]) != dv:
            return False
    return True


def mascarar_cnpj(cnpj: str) -> str:
    """12.***.***/0001-** (só a raiz parcial e a filial, como pede a regra da Raíz)."""
    d = so_digitos(cnpj)
    return f"{d[:2]}.***.***/{d[8:12]}-**"


def _indice_cnpj(cnpj: str, cofre=None) -> str:
    from raiz.pessoal import Cofre

    return (cofre or Cofre()).indice("cnpj:" + so_digitos(cnpj))


# --- conta --------------------------------------------------------------------------------------------------------


def abrir(engine: Engine, cliente_id: int, cnpj: str, aceito_termos: bool, cofre=None) -> dict:
    """Abre a conta da empresa (uma vez). 3 créditos de teste para um CNPJ que nunca usou a API."""
    if not aceito_termos:
        raise ErroConta("termos_nao_aceitos", "é preciso aceitar os termos de uso da API",
                        f"leia GET /v1/termos e mande aceito_termos=true ({premissas()['termos_versao']})")  # fmt: skip
    if not cnpj_valido(cnpj):
        raise ErroConta("cnpj_invalido", "CNPJ inválido", "mande o CNPJ da empresa com os 14 dígitos")
    h = _indice_cnpj(cnpj, cofre)
    p = premissas()
    with engine.begin() as con:
        atual = con.execute(text("select cliente_id from negocio.conta_api where cnpj_hmac = :h"), {"h": h}).scalar()
        if atual is not None and int(atual) != int(cliente_id):
            raise ErroConta("cnpj_em_uso", "este CNPJ já tem conta na Raíz",
                            "peça uma chave a quem administra a conta da empresa", status=409)  # fmt: skip
        if atual is None:
            ja = con.execute(text("select 1 from negocio.conta_api where cliente_id = :c"), {"c": cliente_id}).first()
            if ja is not None:
                raise ErroConta("conta_com_outro_cnpj", "esta conta já está ligada a outro CNPJ",
                                "use a conta da empresa certa", status=409)  # fmt: skip
            con.execute(
                text("""insert into negocio.conta_api (cliente_id, cnpj_hmac, cnpj_mascarado, termos_versao,
                        testes_restantes) values (:c, :h, :m, :t, :n)"""),
                {"c": cliente_id, "h": h, "m": mascarar_cnpj(cnpj), "t": p["termos_versao"],
                 "n": int(p["teste"]["creditos"])},
            )  # fmt: skip
    return ver(engine, cliente_id)


def ver(engine: Engine, cliente_id: int) -> dict | None:
    with engine.connect() as con:
        r = con.execute(text("select * from negocio.conta_api where cliente_id = :c"), {"c": cliente_id}).mappings()
        c = r.first()
    if c is None:
        return None
    p = premissas()
    return {
        "cnpj": c["cnpj_mascarado"], "termos_versao": c["termos_versao"],
        "testes_restantes": int(c["testes_restantes"]), "saldo_rs": float(c["saldo_rs"]),
        "liberada": bool(c["contrato_aceito_em"] and c["sinal_pago_em"]),
        "contrato_aceito_em": c["contrato_aceito_em"].isoformat() if c["contrato_aceito_em"] else None,
        "sinal_pago_em": c["sinal_pago_em"].isoformat() if c["sinal_pago_em"] else None,
        "licenca_dados": bool(c["licenca_dados_aprovada_em"]),
        "bloqueada": bool(c["bloqueada_em"]), "bloqueio_motivo": c["bloqueio_motivo"],
        "precos": p["precos"], "versao_precos": p["versao_completa"],
    }  # fmt: skip


def exigir(engine: Engine, cliente_id: int) -> dict:
    c = ver(engine, cliente_id)
    if c is None:
        raise ErroConta("sem_conta", "a empresa ainda não abriu a conta da API",
                        "uma pessoa da empresa abre a conta com o CNPJ em POST /v1/conta", status=403)  # fmt: skip
    if c["bloqueada"]:
        raise ErroConta("conta_bloqueada", f"conta bloqueada: {c['bloqueio_motivo']}",
                        "uso em volume é licença de dados, com preço separado: fale com a Raíz", status=403)  # fmt: skip  # noqa: E501
    return c


def exigir_liberacao(engine: Engine, cliente_id: int) -> dict:
    c = exigir(engine, cliente_id)
    if not c["liberada"]:
        falta = []
        if not c["contrato_aceito_em"]:
            falta.append("uma pessoa da empresa aceita o contrato com a cláusula de não contornar "
                         "(POST /v1/conta/contrato, no login por e-mail)")  # fmt: skip
        if not c["sinal_pago_em"]:
            falta.append("uma pessoa da empresa paga o sinal por Pix (POST /v1/conta/sinal gera o link)")
        raise ErroConta("liberacao_pendente", "montar lote e ver o detalhe da fazenda pedem o sinal pago e o "
                        "contrato aceito (igual ao app); pagar a API não pula essa trava", "; ".join(falta),
                        status=403)  # fmt: skip
    return c


def aceitar_contrato(engine: Engine, cliente_id: int) -> dict:
    exigir(engine, cliente_id)
    with engine.begin() as con:
        con.execute(
            text("""update negocio.conta_api set contrato_versao = :v, contrato_aceito_em = now()
                    where cliente_id = :c"""),
            {"v": premissas()["liberacao"]["contrato_versao"], "c": cliente_id},
        )
    return ver(engine, cliente_id)


# --- cobrança por chamada --------------------------------------------------------------------------------------------


def cobrar(engine: Engine, cliente_id: int, ferramenta: str, base_url: str = "") -> int | None:
    """Tira o preço da chamada do crédito de teste ou do saldo; devolve o lançamento (para estornar se a chamada
    falhar). Sem saldo: ErroConta 402 com o link da recarga por Pix."""
    p = premissas()
    valor = preco(ferramenta)
    exigir(engine, cliente_id)
    if valor <= 0:
        return None
    with engine.begin() as con:
        c = con.execute(text("select * from negocio.conta_api where cliente_id = :c for update"),
                        {"c": cliente_id}).mappings().first()  # fmt: skip
        if ferramenta in p["teste"]["vale_para"] and c["testes_restantes"] > 0:
            con.execute(text("update negocio.conta_api set testes_restantes = testes_restantes - 1 where cliente_id = "
                             ":c"), {"c": cliente_id})  # fmt: skip
            return con.execute(
                text("""insert into negocio.lancamento_api (cliente_id, tipo, valor_rs, ferramenta, versao_precos)
                        values (:c, 'teste', 0, :f, :v) returning id"""),
                {"c": cliente_id, "f": ferramenta, "v": p["versao_completa"]},
            ).scalar_one()
        if float(c["saldo_rs"]) >= valor:
            con.execute(text("update negocio.conta_api set saldo_rs = saldo_rs - :v where cliente_id = :c"),
                        {"v": valor, "c": cliente_id})  # fmt: skip
            return con.execute(
                text("""insert into negocio.lancamento_api (cliente_id, tipo, valor_rs, ferramenta, versao_precos)
                        values (:c, 'debito', :val, :f, :v) returning id"""),
                {"c": cliente_id, "val": -valor, "f": ferramenta, "v": p["versao_completa"]},
            ).scalar_one()
        saldo = float(c["saldo_rs"])
    falta = max(valor - saldo, float(p["recarga"]["minimo_rs"]))
    cob = criar_cobranca(engine, cliente_id, "recarga", falta, base_url)
    raise ErroConta("saldo_insuficiente", f"a chamada {ferramenta} custa R$ {valor:.2f} e o saldo é R$ {saldo:.2f} "
                    "(os créditos de teste acabaram)", "uma pessoa da empresa paga a recarga pelo link (o agente não "
                    "paga) e a chamada pode ser repetida", status=402, recarga=cob)  # fmt: skip


def estornar(engine: Engine, lancamento_id: int | None) -> None:
    """Chamada que falhou não custa: devolve o crédito de teste ou o valor."""
    if lancamento_id is None:
        return
    with engine.begin() as con:
        lc = con.execute(text("select * from negocio.lancamento_api where id = :i"), {"i": lancamento_id}).first()
        if lc is None or lc.tipo not in ("teste", "debito"):
            return
        if lc.tipo == "teste":
            con.execute(text("update negocio.conta_api set testes_restantes = testes_restantes + 1 where cliente_id = "
                             ":c"), {"c": lc.cliente_id})  # fmt: skip
        else:
            con.execute(text("update negocio.conta_api set saldo_rs = saldo_rs + :v where cliente_id = :c"),
                        {"v": -float(lc.valor_rs), "c": lc.cliente_id})  # fmt: skip
        con.execute(
            text("""insert into negocio.lancamento_api (cliente_id, tipo, valor_rs, ferramenta, versao_precos)
                    values (:c, :t, :v, :f, :vp)"""),
            {"c": lc.cliente_id, "t": "estorno_teste" if lc.tipo == "teste" else "estorno", "v": -float(lc.valor_rs),
             "f": lc.ferramenta, "vp": lc.versao_precos},
        )  # fmt: skip


# --- cobranças Pix (recarga e sinal): uma pessoa paga pelo link -----------------------------------------------------


def criar_cobranca(engine: Engine, cliente_id: int, finalidade: str, valor: float, base_url: str = "") -> dict:
    """Cria (ou reaproveita a pendente) a cobrança Pix e devolve o link da página onde uma pessoa paga. O código Pix
    não vai para o agente."""
    from raiz.pedidos import pix

    p = premissas()
    with engine.begin() as con:
        aberta = con.execute(
            text("""select id from negocio.cobranca_api where cliente_id = :c and finalidade = :f and estado = 'pendente'  # noqa: E501
                    and expira_em > now() and valor_rs >= :v order by id desc limit 1"""),
            {"c": cliente_id, "f": finalidade, "v": valor},
        ).scalar()
        token = secrets.token_urlsafe(24)
        if aberta is not None:
            con.execute(text("update negocio.cobranca_api set link_hash = :h where id = :i"),
                        {"h": _hash(token), "i": aberta})  # fmt: skip
            cid = aberta
        else:
            cob = pix.criar(valor, f"Raíz API: {finalidade}", int(p["recarga"]["validade_pix_s"]))
            cid = con.execute(
                text("""insert into negocio.cobranca_api (cliente_id, finalidade, valor_rs, modo, externo_id, estado,
                        pix_copia_cola, link_hash, expira_em) values (:c, :f, :v, :m, :x, 'pendente', :pc, :h, :e)
                        returning id"""),
                {"c": cliente_id, "f": finalidade, "v": valor, "m": cob.modo, "x": cob.externo_id,
                 "pc": cob.copia_e_cola, "h": _hash(token), "e": cob.expira_em},
            ).scalar_one()  # fmt: skip
        r = con.execute(text("select * from negocio.cobranca_api where id = :i"), {"i": cid}).first()
    return {"id": int(r.id), "finalidade": finalidade, "valor_rs": float(r.valor_rs), "estado": r.estado,
            "link_para_uma_pessoa": f"{base_url}/v1/cobrancas/{token}",
            "expira_em": r.expira_em.isoformat() if r.expira_em else None,
            "modo_teste": r.modo == "teste"}  # fmt: skip


def _hash(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def cobranca_pelo_link(engine: Engine, token: str) -> dict | None:
    with engine.connect() as con:
        r = con.execute(text("select * from negocio.cobranca_api where link_hash = :h"), {"h": _hash(token)}).first()
    if r is None:
        return None
    return {"finalidade": r.finalidade, "valor_rs": float(r.valor_rs), "estado": r.estado,
            "pix_copia_cola": r.pix_copia_cola if r.estado == "pendente" else None, "externo_id": r.externo_id,
            "modo_teste": r.modo == "teste"}  # fmt: skip


def confirmar_cobranca(engine: Engine, externo_id: str, quando: dt.datetime | None = None) -> str | None:
    """Pagamento entrou (webhook do Pix ou pagamento de teste): recarga vira saldo; sinal libera a conta (com o
    contrato aceito). None se a cobrança não é da API."""
    with engine.begin() as con:
        r = con.execute(text("select * from negocio.cobranca_api where externo_id = :x for update"),
                        {"x": externo_id}).first()  # fmt: skip
        if r is None:
            return None
        if r.estado == "paga":
            return "ja_paga"
        con.execute(text("update negocio.cobranca_api set estado = 'paga', paga_em = coalesce(:q, now()) where id = :i"),  # noqa: E501
                    {"q": quando, "i": r.id})  # fmt: skip
        if r.finalidade == "recarga":
            con.execute(text("update negocio.conta_api set saldo_rs = saldo_rs + :v where cliente_id = :c"),
                        {"v": float(r.valor_rs), "c": r.cliente_id})  # fmt: skip
        else:
            con.execute(text("update negocio.conta_api set sinal_pago_em = coalesce(:q, now()) where cliente_id = :c"),
                        {"q": quando, "c": r.cliente_id})  # fmt: skip
        con.execute(
            text("""insert into negocio.lancamento_api (cliente_id, tipo, valor_rs, cobranca_id, versao_precos)
                    values (:c, :t, :v, :i, :vp)"""),
            {"c": r.cliente_id, "t": r.finalidade, "v": float(r.valor_rs), "i": r.id,
             "vp": premissas()["versao_completa"]},
        )  # fmt: skip
    return "paga"


def extrato(engine: Engine, cliente_id: int, limite: int = 200) -> list[dict]:
    with engine.connect() as con:
        return [{**dict(r), "valor_rs": float(r["valor_rs"]), "criado_em": r["criado_em"].isoformat()}
                for r in con.execute(text("""select tipo, valor_rs, ferramenta, versao_precos, criado_em
                                              from negocio.lancamento_api where cliente_id = :c order by id desc
                                              limit :n"""), {"c": cliente_id, "n": limite}).mappings()]  # fmt: skip


# --- anti-raspagem --------------------------------------------------------------------------------------------------


def registrar_exposicao(engine: Engine, chamada_id: int | None, cliente_id: int, cods: list[str]) -> None:
    """Quem viu qual fazenda (código do CAR): registro contra raspagem e para auditoria."""
    cods = [c for c in dict.fromkeys(str(x) for x in cods if x)]
    if not cods:
        return
    with engine.begin() as con:
        con.execute(
            text("""insert into negocio.exposicao_api (chamada_id, cliente_id, cod_imovel)
                    select :ch, :c, unnest(cast(:cods as text[]))"""),
            {"ch": chamada_id, "c": cliente_id, "cods": cods},
        )


def vigiar_raspagem(engine: Engine, cliente_id: int) -> str:
    """Padrão de quem está copiando a base: fazendas vistas e municípios consultados no mês, municípios no dia.
    Devolve "ok", "alerta" (o fundador é avisado uma vez por dia por regra) ou "bloqueada"."""
    p = premissas()["raspagem"]
    with engine.connect() as con:
        c = con.execute(text("select licenca_dados_aprovada_em, bloqueada_em from negocio.conta_api where cliente_id "
                             "= :c"), {"c": cliente_id}).first()  # fmt: skip
        if c is None or c.licenca_dados_aprovada_em is not None:
            return "ok"
        if c.bloqueada_em is not None:
            return "bloqueada"
        fz = con.execute(text("""select count(distinct cod_imovel) from negocio.exposicao_api where cliente_id = :c
                                 and criada_em >= date_trunc('month', now())"""), {"c": cliente_id}).scalar()
        mm, md, cm = con.execute(text("""
            select count(distinct m) filter (where criada_em >= date_trunc('month', now())),
                   count(distinct m) filter (where criada_em >= date_trunc('day', now())),
                   count(distinct id) filter (where criada_em >= date_trunc('month', now()))
            from negocio.chamada_api, jsonb_array_elements_text(coalesce(alcance->'municipios', '[]'::jsonb)) as m
            where cliente_id = :c and ferramenta = 'consultar_disponibilidade'"""), {"c": cliente_id}).one()
        consultas = con.execute(text("""select count(*) from negocio.chamada_api where cliente_id = :c
                                        and ferramenta = 'consultar_disponibilidade'
                                        and criada_em >= date_trunc('month', now())"""), {"c": cliente_id}).scalar()
    bloqueio = [("fazendas_vistas_mes", fz, p["fazendas_vistas_mes_bloqueio"]),
                ("municipios_consultados_mes", mm, p["municipios_consultados_mes_bloqueio"])]  # fmt: skip
    alerta = [("fazendas_vistas_mes", fz, p["fazendas_vistas_mes_alerta"]),
              ("municipios_consultados_dia", md, p["municipios_consultados_dia_alerta"]),
              ("consultas_mes", consultas, p["consultas_mes_alerta"])]  # fmt: skip
    for regra, v, lim in bloqueio:
        if v >= lim:
            _alertar(engine, cliente_id, "raspagem_bloqueio", regra, v, lim)
            with engine.begin() as con:
                con.execute(text("""update negocio.conta_api set bloqueada_em = now(), bloqueio_motivo = :m
                                    where cliente_id = :c and bloqueada_em is null"""),
                            {"m": f"padrão de raspagem ({regra}: {v} de {lim}); uso em volume é licença de dados",
                             "c": cliente_id})  # fmt: skip
            return "bloqueada"
    estado = "ok"
    for regra, v, lim in alerta:
        if v >= lim:
            _alertar(engine, cliente_id, "raspagem_alerta", regra, v, lim)
            estado = "alerta"
    return estado


def _alertar(engine: Engine, cliente_id: int, tipo: str, regra: str, valor: float, limite: float) -> None:
    import logging

    with engine.begin() as con:
        ja = con.execute(text("""select 1 from negocio.alerta_api where cliente_id = :c and tipo = :t and regra = :r
                                 and criado_em >= date_trunc('day', now())"""),
                         {"c": cliente_id, "t": tipo, "r": regra}).first()  # fmt: skip
        if ja is None:
            con.execute(text("""insert into negocio.alerta_api (cliente_id, tipo, regra, valor, limite)
                                values (:c, :t, :r, :v, :l)"""),
                        {"c": cliente_id, "t": tipo, "r": regra, "v": valor, "l": limite})  # fmt: skip
            logging.getLogger("raiz.publica").warning("API: %s da empresa %s (%s: %s de %s)", tipo, cliente_id, regra,
                                                      valor, limite)  # fmt: skip


def aprovar_licenca(engine: Engine, cliente_id: int) -> None:
    """O fundador aprova a licença de dados (uso em volume, preço separado): desbloqueia e para de vigiar volume."""
    with engine.begin() as con:
        con.execute(text("""update negocio.conta_api set licenca_dados_aprovada_em = now(), bloqueada_em = null,
                            bloqueio_motivo = null where cliente_id = :c"""), {"c": cliente_id})
        con.execute(text("""insert into negocio.alerta_api (cliente_id, tipo, regra) values (:c, 'licenca',
                            'aprovada pelo fundador')"""), {"c": cliente_id})


def alertas(engine: Engine, cliente_id: int | None = None) -> list[dict]:
    filtro = "where cliente_id = :c" if cliente_id is not None else ""
    with engine.connect() as con:
        return [dict(r) for r in con.execute(text(f"select * from negocio.alerta_api {filtro} order by id"),
                                             {"c": cliente_id}).mappings()]  # fmt: skip
