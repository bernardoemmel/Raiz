"""Fila durável e idempotente da API paga; trabalho pesado roda no worker, nunca depois de timeout HTTP.

A transação do worker inclui todos os efeitos de banco dos serviços e sua conclusão. Uma queda reverte ambos.
Não há pagamento, envio externo ou execução de texto de terceiros neste módulo.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from contextlib import contextmanager
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from raiz.pedidos import servico as S
from raiz.pedidos.campos import CAMINHOS, METODOS, CamposPedido
from raiz.publica import conta as CT
from raiz.publica import webhooks as W
from raiz.publica.privacidade import sem_dado_pessoal
from raiz.publica.telemetria import chamada
from raiz.salvaguardas import ErroSalvaguarda

FERRAMENTAS = frozenset(
    {"consultar_disponibilidade", "comparar_lotes", "acompanhar_contato", "pedir_lote", "preparar_reserva"}
)
_ESTADOS_EVENTO = {
    "submitted": "recebido",
    "working": "processando",
    "completed": "concluido",
    "failed": "falhou",
    "input-required": "aguardando",
    "canceled": "cancelado",
}
LEASE_SEGUNDOS = 900


class ErroTrabalho(CT.ErroConta):
    """Erro público com status HTTP, sem mensagem do driver nem conteúdo de documento."""


class ConexaoVinculada:
    """Interface de Engine usada pelos serviços sem abrir/confirmar transações independentes."""

    def __init__(self, conexao: Connection):
        self.conexao = conexao

    @contextmanager
    def connect(self):
        yield self.conexao

    @contextmanager
    def begin(self):
        with self.conexao.begin_nested():
            yield self.conexao


def _erro(slug: str, detalhe: str, status: int = 422, **extra) -> ErroTrabalho:
    return ErroTrabalho(slug, detalhe, "confira os dados e o estado da operação antes de repetir", status, **extra)


def _id(valor: str) -> str:
    try:
        return str(uuid.UUID(str(valor)))
    except (ValueError, TypeError, AttributeError) as ex:
        raise _erro("operacao_nao_encontrada", "operação não encontrada", 404) from ex


def _corpo(ferramenta: str, corpo: dict) -> tuple[dict, str]:
    if ferramenta not in FERRAMENTAS:
        raise _erro("ferramenta_invalida", "essa ferramenta não aceita execução em fila")
    if not isinstance(corpo, dict):
        raise _erro("corpo_invalido", "o corpo deve ser um objeto JSON")
    try:
        # Hash do corpo recebido, antes dos padrões: reutilizar a chave com qualquer corpo diferente é conflito.
        bruto = json.dumps(corpo, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(bruto.encode()) > 65536:
            raise _erro("corpo_grande", "o pedido excede 64 KB", 413)
        if ferramenta in {"pedir_lote", "consultar_disponibilidade"}:
            valor = CamposPedido.model_validate(corpo).model_dump(mode="json")
        else:
            permitidos = {"pedido_id", "base_url"} if ferramenta == "preparar_reserva" else {"pedido_id"}
            if set(corpo) - permitidos or "pedido_id" not in corpo:
                raise _erro("corpo_invalido", "a ferramenta exige pedido_id; campos desconhecidos são recusados")
            valor = {"pedido_id": _id(corpo["pedido_id"])}
            if ferramenta == "preparar_reserva":
                valor["base_url"] = corpo.get("base_url", "")
                if not isinstance(valor["base_url"], str) or len(valor["base_url"]) > 2048:
                    raise _erro("corpo_invalido", "base_url inválida")
    except (ValidationError, TypeError, ValueError) as ex:
        if isinstance(ex, ErroTrabalho):
            raise
        raise _erro("corpo_invalido", "pedido inválido para a ferramenta") from ex
    return valor, hashlib.sha256(bruto.encode()).hexdigest()


def _recibo(r) -> dict[str, Any]:
    resultado = sem_dado_pessoal(r["resultado"])
    # O snapshot é evidência interna. Detalhes atuais passam por comparar_lotes e suas exclusões de reservas.
    if r["ferramenta"] == "pedir_lote" and resultado is not None:
        resultado = {"id": str(r["negocio_pedido_id"])}
    recibo = {
        "pedido_id": str(r["id"]),
        "ferramenta": r["ferramenta"],
        "estado": r["estado"],
        "negocio_pedido_id": str(r["negocio_pedido_id"]) if r["negocio_pedido_id"] else None,
        "resultado": resultado,
        "erro": r["erro"],
    }
    if r["estado"] in {"submitted", "working"}:
        recibo.update(
            consultar_apos_segundos=1,
            acompanhamento={"ferramenta": "acompanhar_contato", "argumentos": {"pedido_id": str(r["id"])}},
        )
    return recibo


def _acesso(engine: Engine, cliente_id: int, ferramenta: str) -> None:
    if ferramenta == "consultar_disponibilidade":
        CT.exigir(engine, cliente_id)
    else:
        CT.exigir_liberacao(engine, cliente_id)


def _evento(con: Connection, r) -> None:
    W.enfileirar(con, r["cliente_id"], "pedido.atualizado", str(r["id"]), _ESTADOS_EVENTO[r["estado"]])


def _numeros(valor: dict, campos: tuple[str, ...]) -> dict:
    """Projeção positiva: strings e listas sob nomes numéricos nunca atravessam a fila."""
    return {
        k: v
        for k in campos
        if (v := valor.get(k)) is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v))
    }


def _faixa(valor) -> dict | None:
    return _numeros(valor, ("p10", "p50", "p90")) if isinstance(valor, dict) else None


def _resumo_base(resultado: dict) -> dict:
    out = _numeros(resultado, ("fazendas", "hectares", "falta", "na_unidade_da_meta"))
    out["creditos"] = _faixa(resultado.get("creditos"))
    out["alcanca_meta"] = resultado.get("alcanca_meta") is True
    for campo, etiqueta, permitidos, numeros in (
        ("por_caminho", "caminho", CAMINHOS, ("fazendas", "hectares", "creditos")),
        (
            "por_interesse",
            "nivel",
            ("sem_contato", "contatado", "interessado", "aceite_fase1", "contrato_firme", "sem_resposta"),
            ("fazendas", "creditos"),
        ),
    ):
        out[campo] = [
            {etiqueta: x[etiqueta], **_numeros(x, numeros)}
            for x in resultado.get(campo, [])
            if isinstance(x, dict) and x.get(etiqueta) in permitidos
        ]
    campos = {
        "terra",
        "metodos",
        "interesse",
        "dinheiro.custo_max_usd_credito",
        "dinheiro.tir_min",
        "onde",
        "onde.biomas",
        "onde.ufs",
        "onde.so_fornecedores_cadeia",
        "base",
    }
    out["afrouxar"] = [
        {"campo": x["campo"], **_numeros(x, ("ganho",))}
        for x in resultado.get("afrouxar", [])
        if isinstance(x, dict) and x.get("campo") in campos
    ]
    return out


def _resumo_opcoes(resultado: dict) -> dict:
    opcoes = []
    for opcao in resultado.get("opcoes", []):
        if not isinstance(opcao, dict) or opcao.get("id") not in {"barata", "segura", "compacta"}:
            continue
        out = {
            "id": opcao["id"],
            **_numeros(
                opcao,
                (
                    "fazendas",
                    "hectares",
                    "pequenas",
                    "pico_caixa_usd",
                    "multa_esperada_usd",
                    "falta",
                    "chance_fechar_com_aceite",
                    "aceite_medio",
                    "reserva_creditos",
                    "vpl_rs",
                ),
            ),
        }
        out["alcanca_meta"] = opcao.get("alcanca_meta") is True
        for faixa in ("creditos", "tir", "custo_usd_credito", "creditos_com_aceite"):
            out[faixa] = _faixa(opcao.get(faixa))
        out["marcos"] = [
            _numeros(m, ("ano", "fracao", "chance", "multa_esperada_rs"))
            for m in opcao.get("marcos", [])
            if isinstance(m, dict)
        ]
        out["mistura_terra"] = [
            {"caminho": x["caminho"], **_numeros(x, ("fracao",))}
            for x in opcao.get("mistura_terra", [])
            if isinstance(x, dict) and x.get("caminho") in CAMINHOS
        ]
        out["metodos"] = [
            {"metodo": x["metodo"], **_numeros(x, ("fazendas",))}
            for x in opcao.get("metodos", [])
            if isinstance(x, dict) and x.get("metodo") in METODOS
        ]
        opcoes.append(out)
    return {"opcoes": opcoes, "referencia": "resumo_do_instante_do_calculo_sem_identificadores_de_fazendas"}


def _resumo_andamento(resultado: dict) -> dict:
    out = _numeros(
        resultado, ("meta", "com_interessado", "com_aceite", "com_contrato", "contatados", "recusas", "sem_resposta")
    )
    out["ondas"] = [
        _numeros(onda, ("numero", "contatados")) for onda in resultado.get("ondas", []) if isinstance(onda, dict)
    ]
    if isinstance(resultado.get("faltou"), dict):
        out["faltou"] = _numeros(resultado["faltou"], ("falta",))
    out["referencia"] = "resumo_do_instante_do_calculo_sem_identificadores_de_fazendas"
    return out


def _debitar(con: Connection, conta, cliente_id: int, ferramenta: str) -> int | None:
    """Somente livro-caixa local; falta de saldo nunca abre chamada ao provedor de Pix."""
    regras = CT.premissas()
    valor = Decimal(str(regras["precos"].get(ferramenta, 0)))
    if not valor.is_finite() or valor < 0:
        raise _erro("preco_indisponivel", "preço da ferramenta indisponível", 503)
    if valor == 0:
        return None
    teste = ferramenta in regras["teste"]["vale_para"] and conta["testes_restantes"] > 0
    if teste:
        con.execute(
            text("update negocio.conta_api set testes_restantes = testes_restantes - 1 where cliente_id=:c"),
            {"c": cliente_id},
        )
    elif conta["saldo_rs"] >= valor:
        con.execute(
            text("update negocio.conta_api set saldo_rs = saldo_rs - :v where cliente_id=:c"),
            {"c": cliente_id, "v": valor},
        )
    else:
        raise _erro(
            "saldo_insuficiente",
            "saldo insuficiente; uma pessoa precisa recarregar a conta",
            402,
            recarga={"acao": "/v1/conta/recarga", "pagador": "pessoa"},
        )
    return con.execute(
        text("""insert into negocio.lancamento_api
        (cliente_id, tipo, valor_rs, ferramenta, versao_precos) values (:c, :t, :v, :f, :vp) returning id"""),
        {
            "c": cliente_id,
            "t": "teste" if teste else "debito",
            "v": 0 if teste else -valor,
            "f": ferramenta,
            "vp": regras["versao_completa"],
        },
    ).scalar_one()


def _conferir_lancamento(con: Connection, cliente: int, ferramenta: str, lancamento: int) -> None:
    r = (
        con.execute(
            text("""select cliente_id, ferramenta, tipo, estornado_em from negocio.lancamento_api
        where id=:id for update"""),
            {"id": lancamento},
        )
        .mappings()
        .first()
    )
    if (
        r is None
        or r["cliente_id"] != cliente
        or r["ferramenta"] != ferramenta
        or r["tipo"] not in {"teste", "debito"}
        or r["estornado_em"] is not None
    ):
        raise _erro("lancamento_invalido", "lançamento não pertence à empresa e à ferramenta", 409)
    ligado = con.execute(text("select 1 from negocio.trabalho_api where lancamento_id=:id"), {"id": lancamento}).first()
    if ligado:
        raise _erro("lancamento_em_uso", "lançamento já pertence a outra operação", 409)


def submeter(
    engine: Engine, cliente_id: int, ferramenta: str, corpo: dict, chave: str, lancamento_id: int | None = None
) -> dict[str, Any]:
    """Aceita uma operação em transação curta. Repetições não executam nem cobram outra vez."""
    if not isinstance(chave, str) or not re.fullmatch(r"[\x21-\x7e]{8,200}", chave):
        raise _erro("idempotencia_obrigatoria", "Idempotency-Key deve ter de 8 a 200 caracteres ASCII sem espaços")
    valor, corpo_hash = _corpo(ferramenta, corpo)
    chave_hash = hashlib.sha256(chave.encode()).hexdigest()
    erro = None
    try:
        with engine.begin() as con:
            con.execute(text("select set_config('lock_timeout', '500ms', true)"))
            con.execute(text("select set_config('statement_timeout', '3000ms', true)"))
            vinculo = ConexaoVinculada(con)
            # Uma trava por empresa ordena livro-caixa e chave de idempotência, inclusive chamadas concorrentes.
            conta = (
                con.execute(text("select * from negocio.conta_api where cliente_id=:c for update"), {"c": cliente_id})
                .mappings()
                .first()
            )
            _acesso(vinculo, cliente_id, ferramenta)
            anterior = (
                con.execute(
                    text("""select * from negocio.trabalho_api where cliente_id=:c
                and ferramenta=:f and chave_hash=:h"""),
                    {"c": cliente_id, "f": ferramenta, "h": chave_hash},
                )
                .mappings()
                .first()
            )
            if anterior:
                if lancamento_id is not None and lancamento_id != anterior["lancamento_id"]:
                    _conferir_lancamento(con, cliente_id, ferramenta, lancamento_id)
                    CT.estornar(vinculo, lancamento_id)
                if anterior["corpo_hash"] != corpo_hash:
                    # A exceção sai após o commit do eventual estorno do lançamento legado.
                    erro = _erro("idempotencia_conflito", "essa Idempotency-Key já foi usada com outro corpo", 409)
                retorno = _recibo(anterior)
            else:
                if lancamento_id is not None:
                    _conferir_lancamento(con, cliente_id, ferramenta, lancamento_id)
                else:
                    lancamento_id = _debitar(con, conta, cliente_id, ferramenta)
                r = (
                    con.execute(
                        text("""insert into negocio.trabalho_api
                    (id,cliente_id,ferramenta,chave_hash,corpo_hash,corpo,estado,lancamento_id)
                    values (:id,:c,:f,:ch,:bh,cast(:b as jsonb),'submitted',:l) returning *"""),
                        {
                            "id": uuid.uuid4(),
                            "c": cliente_id,
                            "f": ferramenta,
                            "ch": chave_hash,
                            "bh": corpo_hash,
                            "b": json.dumps(valor, allow_nan=False),
                            "l": lancamento_id,
                        },
                    )
                    .mappings()
                    .one()
                )
                _evento(con, r)
                retorno = _recibo(r)
    except DBAPIError as ex:
        raise _erro("fila_indisponivel", "a fila está ocupada; repita com a mesma Idempotency-Key", 503) from ex
    if erro:
        raise erro
    return retorno


def obter(engine: Engine, cliente_id: int, pedido_id: str) -> dict[str, Any]:
    with engine.connect() as con:
        r = (
            con.execute(
                text("select * from negocio.trabalho_api where id=:id and cliente_id=:c"),
                {"id": _id(pedido_id), "c": cliente_id},
            )
            .mappings()
            .first()
        )
    if r is None:
        raise _erro("operacao_nao_encontrada", "operação não encontrada", 404)
    _acesso(engine, cliente_id, r["ferramenta"])
    return _recibo(r)


def cancelar(engine: Engine, cliente_id: int, pedido_id: str) -> dict[str, Any]:
    """Cancela somente antes do worker; não desfaz silenciosamente pedido, reserva nem pagamento."""
    try:
        with engine.begin() as con:
            con.execute(text("select set_config('lock_timeout', '500ms', true)"))
            con.execute(text("select set_config('statement_timeout', '3s', true)"))
            r = (
                con.execute(
                    text("""select * from negocio.trabalho_api where id=:id and cliente_id=:c
                for update"""),
                    {"id": _id(pedido_id), "c": cliente_id},
                )
                .mappings()
                .first()
            )
            if r is None:
                raise _erro("operacao_nao_encontrada", "operação não encontrada", 404)
            if r["estado"] == "canceled":
                return _recibo(r)
            if r["estado"] != "submitted":
                raise _erro("operacao_iniciada", "a operação já iniciou; seu cancelamento requer revisão", 409)
            CT.estornar(ConexaoVinculada(con), r["lancamento_id"])
            r = (
                con.execute(
                    text("""update negocio.trabalho_api set estado='canceled', atualizado_em=now(),
                concluido_em=now() where id=:id returning *"""),
                    {"id": r["id"]},
                )
                .mappings()
                .one()
            )
            _evento(con, r)
            return _recibo(r)
    except DBAPIError as ex:
        raise _erro("operacao_ocupada", "o worker está executando a operação; consulte seu estado", 409) from ex


def _reivindicar(engine: Engine):
    with engine.begin() as con:
        r = con.execute(
            text("""select id, cliente_id from negocio.trabalho_api
            where estado='submitted' or (estado='working' and lease_ate < now())
            order by criado_em, id for update skip locked limit 1""")
        ).first()
        if r is None:
            return None
        token = uuid.uuid4()
        con.execute(
            text("""update negocio.trabalho_api set estado='working', executor_token=:t,
            lease_ate=now()+(:s * interval '1 second'), iniciado_em=coalesce(iniciado_em, now()),
            tentativas=tentativas+1, atualizado_em=now() where id=:id"""),
            {"t": token, "s": LEASE_SEGUNDOS, "id": r.id},
        )
        _evento(con, {"id": r.id, "cliente_id": r.cliente_id, "estado": "working"})
        return r.id, token


def _executar(vinculo: ConexaoVinculada, r) -> tuple[dict, str, str | None]:
    _acesso(vinculo, r["cliente_id"], r["ferramenta"])
    corpo = r["corpo"]
    if r["ferramenta"] == "consultar_disponibilidade":
        return _resumo_base(S.base_disponivel(vinculo, r["cliente_id"], corpo)), "completed", None
    if r["ferramenta"] == "comparar_lotes":
        return (
            _resumo_opcoes(S.obter_pedido(vinculo, corpo["pedido_id"], r["cliente_id"])),
            "completed",
            corpo["pedido_id"],
        )
    if r["ferramenta"] == "acompanhar_contato":
        return (
            _resumo_andamento(S.andamento(vinculo, corpo["pedido_id"], r["cliente_id"])),
            "completed",
            corpo["pedido_id"],
        )
    if r["ferramenta"] == "pedir_lote":
        resultado = S.criar_pedido(vinculo, r["cliente_id"], r["corpo"])
        return resultado, "completed", resultado["id"]
    # A permissão pode ser revogada entre submissão e execução. A trava compartilhada
    # lineariza a preparação com a alteração administrativa até o commit do worker.
    permitido = vinculo.conexao.execute(
        text("select reservar_habilitado from negocio.conta_api where cliente_id=:c for share"),
        {"c": r["cliente_id"]},
    ).scalar()
    if not permitido:
        raise _erro("reserva_desabilitada", "um administrador da empresa precisa habilitar reservar", 403)
    corpo = r["corpo"]
    resultado = S.reservar(
        vinculo,
        corpo["pedido_id"],
        r["cliente_id"],
        por_agente=f"operacao:{r['id']}",
        base_url=corpo.get("base_url", ""),
    )
    # Não persistir link de aprovação, Pix nem recibo assinado. A API reconstitui a cobrança atual após autorizar.
    aguardando = resultado.get("aguardando_confirmacao") is True
    resumo = {"pedido": corpo["pedido_id"], "aguardando_confirmacao": aguardando}
    return resumo, "input-required" if aguardando else "completed", corpo["pedido_id"]


def executar_proximo(engine: Engine) -> dict[str, Any] | None:
    """Executa uma operação; múltiplos workers não disputam a mesma linha. Queda é recuperada por lease."""
    reivindicado = _reivindicar(engine)
    if reivindicado is None:
        return None
    id_, token = reivindicado
    with engine.begin() as con:
        r = (
            con.execute(
                text("""select * from negocio.trabalho_api where id=:id and executor_token=:t
            and estado='working' for update"""),
                {"id": id_, "t": token},
            )
            .mappings()
            .first()
        )
        if r is None:
            return None
        vinculo = ConexaoVinculada(con)
        try:
            # Erro normal reverte só o trabalho; o estorno e o estado failed confirmam na transação externa.
            with chamada(r["ferramenta"], "worker", r["cliente_id"]), con.begin_nested():
                resultado, estado, pedido = _executar(vinculo, r)
                resultado_json = json.dumps(jsonable_encoder(sem_dado_pessoal(resultado)), allow_nan=False)
        except Exception as ex:
            CT.estornar(vinculo, r["lancamento_id"])
            # Não gravar ex/texto de terceiros: diagnóstico público é um código e instrução controlados.
            salvaguarda = isinstance(ex, ErroSalvaguarda)
            estado_erro = "input-required" if salvaguarda else "failed"
            erro = {
                "type": "https://raiz.eco/problemas/" + ("salvaguarda_pendente" if salvaguarda else "operacao_falhou"),
                "title": "Não foi possível concluir a operação",
                "status": ex.status if isinstance(ex, CT.ErroConta) else (422 if isinstance(ex, S.ErroPedido) else 500),
                "detail": (
                    "Uma pessoa precisa conferir as salvaguardas. A cobrança desta operação foi estornada."
                    if salvaguarda
                    else "Confira a liberação e o estado do pedido. A cobrança desta operação foi estornada."
                ),
            }
            r = (
                con.execute(
                    text("""update negocio.trabalho_api set estado=:estado, erro=cast(:e as jsonb),
                lease_ate=null, atualizado_em=now(), concluido_em=now() where id=:id returning *"""),
                    {"e": json.dumps(erro), "id": id_, "estado": estado_erro},
                )
                .mappings()
                .one()
            )
        else:
            r = (
                con.execute(
                    text("""update negocio.trabalho_api set estado=:s, negocio_pedido_id=:p,
                resultado=cast(:r as jsonb), erro=null, lease_ate=null, atualizado_em=now(), concluido_em=now()
                where id=:id returning *"""),
                    {"s": estado, "p": pedido, "r": resultado_json, "id": id_},
                )
                .mappings()
                .one()
            )
        _evento(con, r)
        return _recibo(r)
