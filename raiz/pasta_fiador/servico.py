"""Pasta privada por pedido: retificação anexada, autorização atual e geração fechada."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from raiz import prospeccao_acesso as acesso
from raiz import prospeccao_protecao as protecao
from raiz.pedidos.servico import ErroPedido, _linha_pedido, _ultima_sugestao

from .esquema import Pasta, Retificacao
from .validacao import Falha, validar


def _json(dado):
    return json.dumps(dado, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(dado):
    return hashlib.sha256(_json(dado).encode()).hexdigest()


def _pedido(con, pedido_id, cliente_id, *, travar=False):
    try:
        return _linha_pedido(con, str(pedido_id), cliente_id, travar=travar)
    except ErroPedido:
        raise acesso.ErroAcesso(404, "Pedido não encontrado.") from None


def _codigos_lote(con, pedido, opcao):
    if opcao not in ("barata", "segura", "compacta"):
        raise acesso.ErroAcesso(422, "Escolha uma das três opções do lote.")
    if pedido["opcao_escolhida"] == opcao:
        return set(
            con.execute(
                text("""select cod_imovel from negocio.pedido_fazenda
            where pedido_id=:p and papel='lote'"""),
                {"p": pedido["id"]},
            ).scalars()
        )
    op = next((o for o in _ultima_sugestao(con, pedido["id"])["opcoes"] if o["id"] == opcao), None)
    return {i["cod_imovel"] for i in (op or {}).get("itens", []) if i.get("papel") == "lote"}


def _autorizar(con, cliente_id, codigos):
    liberados = set(
        con.execute(
            text("""select distinct d.cod_imovel
        from negocio.prospeccao_desbloqueio d
        join negocio.cliente c on c.id=d.cliente_id and c.ativo
        join funil.vigente v on v.cod_imovel=d.cod_imovel
        where d.cliente_id=:c and d.cod_imovel=any(:cars)
          and not exists(select 1 from negocio.reserva_fazenda rf join negocio.reserva r on r.id=rf.reserva_id
            where rf.cod_imovel=d.cod_imovel and rf.ativa and r.cliente_id<>:c)"""),
            {"c": cliente_id, "cars": sorted(codigos)},
        ).scalars()
    )
    if not codigos or liberados != set(codigos):
        raise acesso.ErroAcesso(403, "A pasta exige acesso pago e vigente a todos os imóveis do lote.")


def registrar(engine: Engine, retificacao: Retificacao) -> dict:
    """Somente operação interna autorizada; clientes não conferem documentos nem enviam modelos."""
    retificacao = Retificacao.model_validate(retificacao.model_dump())
    dados = retificacao.dados
    bruto = dados.model_dump(mode="json")
    rel = validar(dados)
    if retificacao.tipo == "retirada":
        rel.falhas.append(Falha(codigo="retirada", campo="pasta", mensagem="Versão retirada de circulação."))
        rel.pronto = False
    with engine.begin() as con:
        pedido = _pedido(con, dados.pedido_id, None, travar=True)
        codigos = {i.codigo_car for i in dados.imoveis}
        if not codigos or codigos != _codigos_lote(con, pedido, dados.opcao):
            raise acesso.ErroAcesso(409, "A pasta deve conter exatamente os imóveis principais da opção atual do lote.")
        con.execute(
            text("""insert into negocio.pasta_fiador(id,pedido_id,opcao) values(:id,:p,:o)
            on conflict(pedido_id,opcao) do nothing"""),
            {"id": uuid4(), "p": dados.pedido_id, "o": dados.opcao},
        )
        pasta_id = con.execute(
            text("select id from negocio.pasta_fiador where pedido_id=:p and opcao=:o"),
            {"p": dados.pedido_id, "o": dados.opcao},
        ).scalar_one()
        anterior = (
            con.execute(
                text("""select id,numero,dados from negocio.pasta_fiador_versao
            where pasta_id=:p order by numero desc limit 1"""),
                {"p": pasta_id},
            )
            .mappings()
            .first()
        )
        if (anterior and anterior["id"] != retificacao.versao_anterior_id) or (
            not anterior and retificacao.versao_anterior_id
        ):
            raise acesso.ErroAcesso(409, "A pasta mudou; confira a última versão antes de retificar.")
        if (anterior is None) != (retificacao.tipo == "inclusao"):
            raise acesso.ErroAcesso(409, "Inclusão inicia a pasta; alterações exigem tipo e versão anterior.")
        # A identidade do documento não pode passar a apontar para outro arquivo.
        antigos = con.execute(text("select dados from negocio.pasta_fiador_versao where pasta_id=:p"), {"p": pasta_id})
        hashes = {d["id"]: d["sha256"] for row in antigos for d in row.dados["documentos"] if d.get("sha256")}
        if any(d.sha256 and str(d.id) in hashes and hashes[str(d.id)] != d.sha256 for d in dados.documentos):
            raise acesso.ErroAcesso(
                409, "Arquivo substituído exige novo ID de documento; preserve a referência anterior."
            )
        vid = uuid4()
        numero = anterior["numero"] + 1 if anterior else 1
        con.execute(
            text("""insert into negocio.pasta_fiador_versao
            (id,pasta_id,numero,anterior_id,tipo,motivo,dados,validacao,assinatura)
            values(:id,:p,:n,:a,:t,:m,cast(:d as jsonb),cast(:v as jsonb),:h)"""),
            {
                "id": vid,
                "p": pasta_id,
                "n": numero,
                "a": anterior["id"] if anterior else None,
                "t": retificacao.tipo,
                "m": retificacao.motivo,
                "d": _json(bruto),
                "v": rel.model_dump_json(),
                "h": _hash(bruto),
            },
        )
        for imovel in dados.imoveis:
            for credito in imovel.creditos:
                serie = con.execute(
                    text("""select id from negocio.pasta_previsao_serie
                    where pasta_id=:p and codigo_car=:c and metodo=:m"""),
                    {"p": pasta_id, "c": imovel.codigo_car, "m": credito.metodo},
                ).scalar()
                if serie and serie != credito.previsao_id:
                    raise acesso.ErroAcesso(409, "Preserve o ID estável da série de previsão deste imóvel e método.")
                outra = (
                    con.execute(
                        text("select pasta_id,codigo_car,metodo from negocio.pasta_previsao_serie where id=:id"),
                        {"id": credito.previsao_id},
                    )
                    .mappings()
                    .first()
                )
                if outra and (outra["pasta_id"], outra["codigo_car"], outra["metodo"]) != (
                    pasta_id,
                    imovel.codigo_car,
                    credito.metodo,
                ):
                    raise acesso.ErroAcesso(409, "Identidade de previsão já utilizada.")
                if not serie:
                    con.execute(
                        text(
                            "insert into negocio.pasta_previsao_serie(id,pasta_id,codigo_car,metodo) "
                            "values(:id,:p,:c,:m)"
                        ),
                        {"id": credito.previsao_id, "p": pasta_id, "c": imovel.codigo_car, "m": credito.metodo},
                    )
                prev = (
                    con.execute(
                        text("""select id,assinatura from negocio.pasta_previsao_referencia
                    where serie_id=:s order by registrada_em desc limit 1"""),
                        {"s": credito.previsao_id},
                    )
                    .mappings()
                    .first()
                )
                valor = credito.model_dump(mode="json")
                assinatura = _hash(valor)
                # Referência nova somente quando a previsão muda; versões documentais apontam à existente.
                if prev and prev["assinatura"] == assinatura:
                    continue
                con.execute(
                    text("""insert into negocio.pasta_previsao_referencia
                    (id,serie_id,pasta_id,pasta_versao_id,codigo_car,metodo,anterior_id,assinatura,dados)
                    values(:id,:s,:p,:v,:c,:m,:a,:h,cast(:d as jsonb))"""),
                    {
                        "id": uuid4(),
                        "s": credito.previsao_id,
                        "p": pasta_id,
                        "v": vid,
                        "c": imovel.codigo_car,
                        "m": credito.metodo,
                        "a": prev["id"] if prev else None,
                        "h": assinatura,
                        "d": _json(valor),
                    },
                )
    return {
        "pasta_id": str(pasta_id),
        "versao_id": str(vid),
        "numero": numero,
        "validacao": rel.model_dump(mode="json"),
    }


def _ler(con, cliente_id, pedido_id, opcao, versao_id=None):
    pedido = _pedido(con, pedido_id, cliente_id)
    pasta_id = con.execute(
        text("select id from negocio.pasta_fiador where pedido_id=:p and opcao=:o"), {"p": pedido["id"], "o": opcao}
    ).scalar()
    if not pasta_id:
        raise acesso.ErroAcesso(404, "A pasta ainda não foi conferida pela Raíz para esta opção.")
    row = (
        con.execute(
            text(
                """select id,numero,anterior_id,tipo,motivo,dados,assinatura,registrada_em
        from negocio.pasta_fiador_versao where pasta_id=:p"""
                + (" and id=:v" if versao_id else "")
                + " order by numero desc limit 1"
            ),
            {"p": pasta_id, "v": versao_id},
        )
        .mappings()
        .first()
    )
    if not row:
        raise acesso.ErroAcesso(404, "Versão não encontrada.")
    dados = Pasta.model_validate(row["dados"])
    codigos = {i.codigo_car for i in dados.imoveis}
    _autorizar(con, cliente_id, codigos)
    rel = validar(dados)  # Validade de hoje; um relatório antigo não mantém documento vencido pronto.
    if codigos != _codigos_lote(con, pedido, opcao):
        rel.falhas.append(Falha(codigo="lote_alterado", campo="imoveis", mensagem="O lote mudou; atualize a pasta."))
    if row["tipo"] == "retirada":
        rel.falhas.append(Falha(codigo="retirada", campo="pasta", mensagem="Esta versão foi retirada de circulação."))
    rel.pronto = not rel.falhas
    refs = con.execute(
        text("""select distinct on(r.serie_id) r.id,r.serie_id,r.codigo_car,r.metodo,r.anterior_id
        from negocio.pasta_previsao_referencia r join negocio.pasta_fiador_versao v on v.id=r.pasta_versao_id
        where r.pasta_id=:p and v.numero<=:n order by r.serie_id,v.numero desc"""),
        {"p": pasta_id, "n": row["numero"]},
    ).mappings()
    referencias = []
    series = {str(c.previsao_id) for i in dados.imoveis for c in i.creditos}
    for ref in refs:
        if str(ref["serie_id"]) not in series:
            continue
        referencia = {k: str(v) if isinstance(v, UUID) else v for k, v in ref.items()}
        referencia["relacoes"] = [{"tipo": "IsVersionOf", "referencia": f"urn:raiz:previsao:{ref['serie_id']}"}]
        if ref["anterior_id"]:
            referencia["relacoes"].append(
                {"tipo": "IsNewVersionOf", "referencia": f"urn:raiz:previsao-versao:{ref['anterior_id']}"}
            )
        referencia["referencia"] = f"urn:raiz:previsao-versao:{ref['id']}"
        referencias.append(referencia)
    return {
        "pasta_id": str(pasta_id),
        "versao_id": str(row["id"]),
        "numero": row["numero"],
        "anterior_id": str(row["anterior_id"]) if row["anterior_id"] else None,
        "tipo_alteracao": row["tipo"],
        "motivo": row["motivo"],
        "assinatura": row["assinatura"],
        "registrada_em": row["registrada_em"].isoformat(),
        "dados": dados.model_dump(mode="json"),
        "validacao": rel.model_dump(mode="json"),
        "previsoes": referencias,
    }


def consultar(engine: Engine, cliente_id: int, pedido_id: UUID, opcao: str, *, versao_id: UUID | None = None):
    acesso.limitar(engine, f"cliente:{cliente_id}", "pastas", 20)
    with protecao.operacao_vigiada(engine, cliente_id, acao="pasta") as concluir, engine.connect() as con:
        resposta = _ler(con, cliente_id, pedido_id, opcao, versao_id)
        concluir({"imoveis": [{"codigo_car": i["codigo_car"]} for i in resposta["dados"]["imoveis"]]})
        return resposta


def historico(engine: Engine, cliente_id: int, pedido_id: UUID, opcao: str):
    atual = consultar(engine, cliente_id, pedido_id, opcao)
    with engine.connect() as con:
        # Só referências, nunca documentos antigos não autorizados; abrir versão autoriza todos os seus CARs.
        rows = con.execute(
            text("""select id,numero,anterior_id,tipo,motivo,registrada_em
            from negocio.pasta_fiador_versao where pasta_id=:p order by numero desc limit 100"""),
            {"p": atual["pasta_id"]},
        ).mappings()
        return {
            "versoes": [
                {
                    k: v.isoformat() if hasattr(v, "isoformat") else str(v) if isinstance(v, UUID) else v
                    for k, v in r.items()
                }
                for r in rows
            ]
        }


def exportar(engine: Engine, cliente_id: int, pedido_id: UUID, opcao: str) -> bytes:
    from .geracao import gerar

    acesso.limitar(engine, f"cliente:{cliente_id}", "exportacoes", 5)
    with protecao.operacao_vigiada(engine, cliente_id, acao="exportacao_pasta") as concluir:
        marca = protecao.registrar_marca(engine, cliente_id)
        with engine.begin() as con:
            _pedido(con, pedido_id, cliente_id, travar=True)
            resposta = _ler(con, cliente_id, pedido_id, opcao)
            if not resposta["validacao"]["pronto"]:
                raise acesso.ErroAcesso(409, "Pasta com pendências. Consulte o relatório de falhas antes de enviar.")
            conteudo = gerar(resposta, marca)
            concluir({"imoveis": [{"codigo_car": i["codigo_car"]} for i in resposta["dados"]["imoveis"]]})
            return conteudo


def da_ficha(engine: Engine, cliente_id: int, codigo_car: str):
    """Conferência privada do próprio lote, separada do DTO global e de seus snapshots."""
    car = acesso.exigir_desbloqueio(engine, cliente_id, codigo_car)
    acesso.limitar(engine, f"cliente:{cliente_id}", "pastas", 20)
    with protecao.operacao_vigiada(engine, cliente_id, acao="pasta", codigos_car=[car]), engine.connect() as con:
        candidatas = (
            con.execute(
                text("""select p.pedido_id,p.opcao from negocio.pasta_fiador p
            join negocio.pedido pedido on pedido.id=p.pedido_id and pedido.cliente_id=:c
            join lateral (select dados,registrada_em from negocio.pasta_fiador_versao
                where pasta_id=p.id order by numero desc limit 1) v on true
            where exists(select 1 from jsonb_array_elements(v.dados->'imoveis') i where i->>'codigo_car'=:car)
            order by v.registrada_em desc limit 20"""),
                {"c": cliente_id, "car": car},
            )
            .mappings()
            .all()
        )
        pastas = []
        for candidata in candidatas:
            try:
                pasta = _ler(con, cliente_id, candidata["pedido_id"], candidata["opcao"])
            except acesso.ErroAcesso as ex:
                if ex.status in (403, 404):
                    continue
                raise
            imovel = next(i for i in pasta["dados"]["imoveis"] if i["codigo_car"] == car)
            pastas.append(
                {
                    "pedido_id": str(candidata["pedido_id"]),
                    "opcao": candidata["opcao"],
                    "pasta_id": pasta["pasta_id"],
                    "versao_id": pasta["versao_id"],
                    "numero": pasta["numero"],
                    "pronto": pasta["validacao"]["pronto"],
                    "data_corte": pasta["dados"]["data_corte"],
                    "imovel": imovel,
                }
            )
        return {"codigo_car": car, "pastas": pastas}
