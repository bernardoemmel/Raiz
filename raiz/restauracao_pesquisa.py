"""Relatório reproduzível das confrontações científicas da rodada 12."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from raiz import restauracao as R
from raiz import restauracao_evidencias as E
from raiz import restauracao_validacao_arr as A


def relatorio() -> dict:
    r = R.regra()
    bruto = 329303.66
    verificado = E.cenario_contabil("verificado_5511", bruto, planejamento=False)
    original = R.forma_curva(r) * r["captura_curva"]["total_tco2_ha"]["plantio_total"]
    _, mombak = E.calibrar_inicio_plantio(original)
    return {
        "modelo_versao": R.versao(),
        "cenario_aplicacao": "central_r12",
        "comparador_versao": E.versao(),
        "vcs5511": {
            **verificado,
            "observado_tco2e": 230119.90,
            "erro_reproducao_tco2e": verificado["liquido_tco2e"] - 230119.90,
        },
        "conservador_plantio_pasto": E.cenario_contabil("conservador_plantio_pasto", 100),
        "verificado_5511_com_piso_prospectivo": E.cenario_contabil("verificado_5511", bruto),
        "mombak": mombak,
        "dryad": {
            "status": "pendente_download_publico",
            "licenca": "CC0-1.0",
            "fonte": "https://doi.org/10.5061/dryad.6t1g1jxdp",
            "erro_mg_ha_por_idade": None,
            "motivo": "Download 401/403; nenhum erro de campo foi fabricado.",
        },
        "linha_base_sintetica": {
            "status": "implementada_testada_em_painel_sintetico",
            "aplicacao_real": "pendente painel fixo pré/pós e controles elegíveis",
        },
        "credito_classe": "modelado",
        "estagio_contrato": "sem_contrato",
        "habilita_comercializacao": False,
    }


def gravar(destino: Path) -> dict:
    destino.mkdir(parents=True, exist_ok=True)
    dado = relatorio()
    bruto = json.dumps(dado, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    sha = hashlib.sha256(bruto).hexdigest()
    caminho = destino / f"rodada12_{sha}.json"
    if caminho.exists() and caminho.read_bytes() != bruto:
        raise ValueError("relatório existente alterado")
    if not caminho.exists():
        caminho.write_bytes(bruto)
    comparacoes = A.avaliar_referencias(json.loads(A.REFERENCIAS.read_text()), destino / "arr")
    return {"arquivo": caminho.name, "sha256": sha, "modelo_versao": R.versao(), "comparacoes_arr": len(comparacoes)}
