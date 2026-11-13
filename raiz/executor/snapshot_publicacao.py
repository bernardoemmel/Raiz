"""Cópia estável dos insumos de uma publicação enquanto outras lanes continuam.

O instante entre arquivos pode variar. Cada arquivo conserva seus bytes e sua
proveniência, e todos os produtos da publicação leem a mesma cópia privada.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import tempfile
import time


def _ler_coerente(local, chave: str) -> tuple[bytes, dict] | None:
    # O escritor troca os bytes e depois o sidecar por rename. A janela entre
    # ambos não pode atribuir a versão anterior aos bytes novos.
    for tentativa in range(5):
        antes = local.meta(chave)
        dados = local.ler(chave)
        depois = local.meta(chave)
        if dados is None and antes is None and depois is None:
            return None
        if dados is not None and antes == depois and depois is not None:
            digest = depois.get("sha256")
            if digest == hashlib.sha256(dados).hexdigest():
                return dados, depois
        if tentativa < 4:
            time.sleep(0.01)
    raise RuntimeError("arquivo mudou durante a cópia da publicação; nenhum produto foi enviado")


@contextlib.contextmanager
def congelar(local, uf: str):
    from raiz.executor.armazem import ArmazemLocal

    with tempfile.TemporaryDirectory(prefix="raiz-publicacao-") as temporaria:
        copia = ArmazemLocal(temporaria)
        # O controle antecede a listagem dos dados: o avanço posterior das
        # outras lanes não anuncia conclusões novas nesse retrato.
        chaves = [*local.listar(f"marcas/{uf}/"), f"estado/{uf}.json"]
        for grupo in (chaves, None):
            for chave in local.listar(f"saida/{uf}/") if grupo is None else grupo:
                lido = _ler_coerente(local, chave)
                if lido is None:
                    continue
                dados, meta = lido
                destino = copia._p(chave)
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(dados)
                destino.chmod(0o600)
                lateral = destino.with_name(destino.name + ".meta.json")
                lateral.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                lateral.chmod(0o600)
        for chave in copia.listar(f"marcas/{uf}/"):
            marca = json.loads(copia.ler(chave))
            for tarefa in marca.get("tarefas", {}).values():
                for nome, digest in (tarefa.get("saidas") or {}).items():
                    if not isinstance(nome, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", nome):
                        raise RuntimeError("marca com saída fora do contrato da publicação")
                    meta = copia.meta(f"saida/{uf}/{nome}") or {}
                    if meta.get("sha256") != digest:
                        raise RuntimeError("marca e saídas mudaram durante a cópia; nenhum produto foi enviado")
        yield copia
