"""Premissas históricas fechadas e verificadas para interpretar previsões já publicadas.

Não procura versões por prefixo nem executa código histórico. Uma versão desconhecida
devolve None; o exportador pode diagnosticá-la sem aplicar as premissas atuais.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import yaml

from raiz import restauracao as R

PASTA = Path(__file__).parent
_REGISTROS = {
    "restauracao-2026c+421970fd": "00a4d29577c96fde1a897f52e9e0dab96a300623831bb01b6592d9946be110d5",
}
_ARQUIVOS = ("restauracao.yaml", "restauracao_cambio.yaml", "edital_profloresta.yaml")
_ERRO = "registro histórico de restauração inválido"


def carregar(versao: str) -> tuple[dict, dict] | None:
    """Devolve (regra, proveniência), com hash integral e versão exata, ou None se não cadastrada.

    O manifesto tem hash fixado no código, os três YAMLs têm hashes individuais e
    a regra/câmbio repetem a composição original. A ausência de calibração também
    é conferida, para nunca misturar parâmetros locais com a versão histórica.
    """
    esperado = _REGISTROS.get(versao)
    if esperado is None:
        return None
    try:
        pasta = PASTA / versao
        bruto = (pasta / "manifesto.json").read_bytes()
        if hashlib.sha256(bruto).hexdigest() != esperado:
            raise ValueError(_ERRO)
        manifesto = json.loads(bruto)
        if (
            manifesto["versao"] != versao
            or manifesto["arquivos_combinados"] != list(_ARQUIVOS[:2])
            or manifesto["separador_hex"] != "0a2d2d0a"
            or manifesto["calibracao"] != {"arquivo": "restauracao_calibracao.yaml", "presente": False}
        ):
            raise ValueError(_ERRO)
        textos = {}
        for nome in _ARQUIVOS:
            textos[nome] = (pasta / nome).read_bytes()
            if hashlib.sha256(textos[nome]).hexdigest() != manifesto["arquivos"][nome]["sha256"]:
                raise ValueError(_ERRO)
        combinado = hashlib.sha256(b"\n--\n".join(textos[n] for n in _ARQUIVOS[:2])).hexdigest()
        if combinado != manifesto["sha256_combinado"]:
            raise ValueError(_ERRO)
        calibracao = pasta / "restauracao_calibracao.yaml"
        if calibracao.exists():
            raise ValueError(_ERRO)
        # Todos os caminhos são explícitos: a calibração ausente não cai no arquivo padrão da instalação.
        regra = R.regra(pasta / "restauracao.yaml", calibracao, pasta / "restauracao_cambio.yaml")
        if regra["versao_completa"] != versao:
            raise ValueError(_ERRO)
        edital = yaml.safe_load(textos["edital_profloresta.yaml"])
        proveniencia = {
            "regra_source_commit": manifesto["commit"],
            "regra_source_sha256": combinado,
            "regra_source_versao": versao,
            "regra_source_edital_versao": edital["versao"],
            "regra_source_edital_sha256": manifesto["arquivos"]["edital_profloresta.yaml"]["sha256"],
            "regra_source_manifesto_sha256": esperado,
            "versao_tarefa_referencia": manifesto["versao_tarefa"],
        }
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        # Não publica valores de arquivos ou mensagens do parser em diagnósticos.
        raise ValueError(_ERRO) from None
    return copy.deepcopy(regra), proveniencia
