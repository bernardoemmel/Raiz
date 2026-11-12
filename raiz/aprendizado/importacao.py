"""Importa os retratos reais do executor, preservando observação e registro.

A recepção atrasada reconstrói somente o intervalo da fonte entre duas capturas
reais. Os arquivos de origem permanecem imutáveis; repetir um hash não grava
outra coleta. Arquivo atual sem manifesto segue o arquivamento manual, com a
hora do banco, e não ganha data passada.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from raiz.aprendizado import arquivo_historico as A
from raiz.aprendizado.arquivo_historico import arquivar
from raiz.aprendizado.retratos import quadros, validar_retrato


def importar_retrato(con, arquivo: Path) -> dict:
    obj = validar_retrato(arquivo)
    observacao = {
        k: obj[k] for k in ("observado_em", "tarefa", "tarefa_versao", "captura_versao", "formato", "indisponiveis")
    }
    observacao["retrato_hash"] = arquivo.name.removesuffix(".json.gz")
    r = arquivar(con, quadros(obj["dados"]), obj["uf"], obj["municipio"], exigir_completo=False, _observacao=observacao)
    r.setdefault("situacao", "importado")
    return r


def importar_pasta(engine, pasta: Path, ufs: list[str] | None = None) -> dict:
    """Uma transação por retrato; queda retoma pelos hashes já confirmados no banco."""
    prefixos = [pasta / u.upper() for u in ufs] if ufs else [pasta]
    arquivos = sorted({p for pre in prefixos for p in pre.rglob("*.json.gz")})
    r = {"importados": 0, "ja_importados": 0}
    # Consulta hashes em lotes: uma rodada nova não reabre nem renormaliza todos
    # os retratos imutáveis que o banco já recebeu em meses anteriores.
    for inicio in range(0, len(arquivos), 500):
        lote = arquivos[inicio : inicio + 500]
        hashes = [p.name.removesuffix(".json.gz") for p in lote]
        with engine.connect() as con:
            existe = con.execute(text("select to_regclass(:t)"), {"t": f"{A.ESQUEMA}.coleta"}).scalar()
            coluna = (
                con.execute(
                    text(
                        "select 1 from information_schema.columns where table_schema=:e "
                        "and table_name='coleta' and column_name='retrato_hash'"
                    ),
                    {"e": A.ESQUEMA},
                ).scalar()
                if existe
                else None
            )
            conhecidos = (
                set(
                    con.execute(
                        text(f"select retrato_hash from {A.ESQUEMA}.coleta where retrato_hash=any(:hashes)"),
                        {"hashes": hashes},
                    ).scalars()
                )
                if coluna
                else set()
            )
        for arquivo in lote:
            if arquivo.name.removesuffix(".json.gz") in conhecidos:
                r["ja_importados"] += 1
                continue
            with engine.begin() as con:
                li = importar_retrato(con, arquivo)
            r["ja_importados" if li["situacao"] == "ja_importado" else "importados"] += 1
    return r


def receber(engine, armazem, pasta: Path, ufs: list[str] | None = None) -> dict:
    from raiz.aprendizado.transporte import sincronizar

    baixados = sincronizar(armazem, pasta, ufs)
    return {**importar_pasta(engine, pasta, ufs), "retratos_disponiveis": len(baixados)}
