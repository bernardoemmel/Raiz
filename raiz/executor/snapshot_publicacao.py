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


class _Divergiu(Exception):
    pass


def _copiar(local, uf: str, copia) -> None:
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
    if _divergentes(copia, uf):
        raise _Divergiu


def _divergentes(copia, uf: str) -> dict[str, list[str]]:
    """{marca: [tarefas]} cujas saídas declaradas não batem com os bytes copiados."""
    achados = {}
    for chave in copia.listar(f"marcas/{uf}/"):
        marca = json.loads(copia.ler(chave))
        for nome_tarefa, tarefa in marca.get("tarefas", {}).items():
            for nome, digest in (tarefa.get("saidas") or {}).items():
                if not isinstance(nome, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", nome):
                    raise RuntimeError("marca com saída fora do contrato da publicação")
                meta = copia.meta(f"saida/{uf}/{nome}") or {}
                if meta.get("sha256") != digest:
                    achados.setdefault(chave, []).append(nome_tarefa)
                    break
    return achados


def _retirar_conclusoes(copia, divergentes: dict[str, list[str]]) -> int:
    """Divergência que persiste não é corrida: o pacote do estado já chegou assim (saída de outra fatia ou de uma
    execução posterior por cima). A marca deixa de concluir só essas tarefas no retrato publicado; os bytes seguem
    e o planejamento refaz a tarefa depois. Derrubar a publicação inteira travava o estado para sempre."""
    for chave, tarefas in divergentes.items():
        marca = json.loads(copia.ler(chave))
        for t in tarefas:
            marca.get("tarefas", {}).pop(t, None)
        meta = {k: v for k, v in (copia.meta(chave) or {}).items() if k not in ("sha256", "tamanho")}
        copia.por_bytes(chave, json.dumps(marca, ensure_ascii=False).encode("utf-8"), meta)
    return sum(map(len, divergentes.values()))


@contextlib.contextmanager
def congelar(local, uf: str, tentativas: int = 8):
    """Outra lane pode gravar uma saída entre a cópia da marca e a da saída. Em vez de derrubar a publicação
    inteira (e com ela tudo que o job calculou), refaz o retrato até pegar um instante coerente."""
    from raiz.executor.armazem import ArmazemLocal

    for tentativa in range(tentativas):
        with tempfile.TemporaryDirectory(prefix="raiz-publicacao-") as temporaria:
            copia = ArmazemLocal(temporaria)
            try:
                _copiar(local, uf, copia)
            except _Divergiu:
                if tentativa < tentativas - 1:
                    time.sleep(min(5.0, 0.25 * 2**tentativa))
                    continue
                n = _retirar_conclusoes(copia, _divergentes(copia, uf))
                print(f"{uf}: {n} tarefa(s) com saída divergente ficam para refazer; o resto publica", flush=True)
            yield copia
            return
