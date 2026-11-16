"""Referências abertas com esforço amostral explícito, sem inventar inventário."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

ARQUIVO = Path(__file__).parent / "regras/padroes/ecologia_referencias_abertas.json"


@lru_cache
def _ler(marca):
    return json.loads(ARQUIVO.read_text())


def catalogo() -> dict:
    return _ler((ARQUIVO.stat().st_mtime_ns, ARQUIVO.stat().st_size))


def versao() -> str:
    return (
        "ecologia-regional-2026d+" + hashlib.sha256(Path(__file__).read_bytes() + ARQUIVO.read_bytes()).hexdigest()[:12]
    )


def referencias(linha: dict, idade_anos: int) -> list[dict]:
    """Contexto do mesmo bioma/método/região; não preenche previsão local.

    Regeneração assistida pode consultar regeneração natural como contexto,
    mantendo a diferença de método. Fisionomia desconhecida não é equivalência.
    """
    modo = linha.get("modo_restauracao", linha.get("modo"))
    metodos = {
        "regeneracao_assistida": {"regeneracao"},
        "plantio_total": {"plantio_biodiverso"},
    }.get(modo, set())
    for md, ref in (("regeneracao_assistida", "regeneracao"), ("plantio_total", "plantio_biodiverso")):
        try:
            if float(linha.get(f"restauracao_{md}_ha", 0) or 0) > 0:
                metodos.add(ref)
        except (TypeError, ValueError):
            pass
    uf = linha.get("uf")
    resultado = []
    for ref in catalogo()["referencias"]:
        ufs = ref["uf"] if isinstance(ref["uf"], list) else [ref["uf"]]
        if (
            ref["bioma"] == linha.get("bioma")
            and ref["metodo_restauracao"] in metodos
            and ref["idade_alvo_anos"] == idade_anos
            and uf in ufs
        ):
            resultado.append(
                {
                    **ref,
                    "referencia_versao": versao(),
                    "peso_inventario_local": 0,
                    "previsao_validada_em_fazenda": False,
                    "nao_multiplicar_por_area": True,
                }
            )
    return resultado
