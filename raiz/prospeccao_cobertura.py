"""Cobertura privada da ficha: carga existente e reindexação, sem executar o motor.

Os checkpoints só avançam depois do trabalho completo. O catálogo pode mudar sem
novo CSV: a sincronização refaz os derivados e registra as transições em lotes.
"""

from __future__ import annotations

from sqlalchemy import text

LOTE = 500
CHAVE = "prospeccao/compromissos"


def travar_municipio(con, cod: int) -> None:
    con.execute(text("select pg_advisory_xact_lock(76031,:m)"), {"m": int(cod)})


def fotografar_municipio(con, cod: int, *, rodadas=(), atualizar=False, origem="carga_depois") -> int:
    """Snapshot antes/depois na transação da carga; inclui os CARs que saíram."""
    from raiz.prospeccao_versoes import registrar_versoes
    from raiz.terra_comprometida import atualizar as atualizar_terra

    ultimo, total = "", 0
    while True:
        codigos = (
            con.execute(
                text("""select cod_imovel from (
                select cod_imovel from funil.vigente where cod_municipio_ibge=:m
                union select cod_imovel from funil.resultado_imovel where rodada_id=any(:rs)
            ) cs where cod_imovel>:ultimo order by cod_imovel limit :limite"""),
                {"m": cod, "rs": list(rodadas), "ultimo": ultimo, "limite": LOTE},
            )
            .scalars()
            .all()
        )
        if not codigos:
            return total
        if atualizar:
            atualizar_terra(con, codigos)
        registrar_versoes(con, codigos, origem=origem)
        total += len(codigos)
        ultimo = codigos[-1]


def _fontes(con) -> dict:
    # Coletas são parciais: uma observação antiga recém-importada pode trazer um
    # objeto que não estava nas mais recentes. Qualquer snapshot novo invalida.
    fontes = con.execute(
        text("""select encode(sha256(convert_to(coalesce(string_agg(
        id::text || ':' || assinatura,'' order by id),''),'UTF8')),'hex')
        from coleta.compromisso_fonte""")
    ).scalar_one()
    contexto = con.execute(
        text("""select encode(sha256(convert_to(coalesce(string_agg(
        encode(sha256(convert_to(jsonb_build_array(id,uf,inicio,fim,fonte,evidencia->>'data')::text,'UTF8')
            || ST_AsEWKB(geom)),'hex'),'' order by id),''),'UTF8')),'hex')
        from geo.redd_programa""")
    ).scalar_one()
    return {"pipeline": 1, "fontes": fontes, "contexto_redd": contexto}


def reindexar(engine, *, forcar: bool = False) -> dict:
    """Atualiza todas as UFs vigentes por município, preservando o derivado anterior.

    Não chama APIs externas. Falhas ficam pendentes no checkpoint e não apagam o
    histórico. Uma fonte que chega durante a execução exige outra volta completa.
    """
    from raiz.carga_continua import _marcar

    res = {"municipios": 0, "imoveis": 0, "falhas": [], "pendente": False, "alterado": False}
    with engine.connect() as guarda:
        ocupado = not guarda.execute(text("select pg_try_advisory_lock(76032,0)")).scalar()
        guarda.commit()
        if ocupado:
            return {**res, "pendente": True}
        try:
            with engine.connect() as con:
                fontes = _fontes(con)
                visto = con.execute(
                    text("select assinatura from funil.arquivo_visto where chave=:c"), {"c": CHAVE}
                ).scalar()
            if not forcar and visto == fontes:
                return res
            ultimo = -1
            while True:
                with engine.begin() as con:
                    cod = con.execute(
                        text("""select min(cod_municipio_ibge) from funil.vigente
                            where cod_municipio_ibge>:ultimo"""),
                        {"ultimo": ultimo},
                    ).scalar()
                if cod is None:
                    break
                ultimo = cod
                try:
                    with engine.begin() as con:
                        travar_municipio(con, cod)
                        fotografar_municipio(con, cod, origem="carga_antes")
                        n = fotografar_municipio(con, cod, atualizar=True)
                    res["municipios"] += 1
                    res["imoveis"] += n
                except Exception as ex:  # noqa: BLE001 - não avança checkpoint e continua os demais
                    res["falhas"].append({"municipio": cod, "erro": type(ex).__name__})
            with engine.begin() as con:
                res["pendente"] = bool(res["falhas"]) or _fontes(con) != fontes
                if not res["pendente"]:
                    _marcar(con, CHAVE, fontes, None)
            res["alterado"] = True
            return res
        finally:
            guarda.execute(text("select pg_advisory_unlock(76032,0)"))
            guarda.commit()


def atualizar_base(engine, *, armazem=None, destino=None, ufs=None, reprocessar=False, congelar=True) -> dict:
    """Backfill idempotente pelo manifesto privado; novas UFs entram na próxima volta."""
    from raiz.executor.sincronizar import carregar

    if armazem is None:
        from raiz.executor.transferencia_privada import arquivo_privado

        armazem = arquivo_privado()
    return carregar(engine, armazem, ufs, destino, congelar=congelar, reprocessar=reprocessar)
