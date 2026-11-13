"""Premissas históricas fechadas e verificadas para interpretar previsões já publicadas.

Não procura versões por prefixo nem executa código histórico. Uma versão desconhecida
devolve None; o exportador pode diagnosticá-la sem aplicar as premissas atuais.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import yaml

PASTA = Path(__file__).parent
_VERSAO_2026B = "restauracao-2026b+cenarios-2026b+dbc2776a"
_REGISTROS = {
    _VERSAO_2026B: "ef4e3d9c2b2c8a1112c5b21b95558db4718c3321e7212e7d51b6ff93cd4a9b52",
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
    if versao == _VERSAO_2026B:
        return _carregar_2026b(esperado)
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
        # O algoritmo desta versão usava somente regra/câmbio. R.regra atual também inclui o código no hash;
        # reconstruímos o formato dos dados verificados, sem executar o cálculo nem carregar defaults atuais.
        regra = yaml.safe_load(textos["restauracao.yaml"])
        regra["cenarios"] = {
            "padrao": regra.pop("padrao"),
            "cenarios": regra["cenarios"],
            "monte_carlo": regra.pop("monte_carlo"),
        }
        regra["calibracao"] = {}
        regra["cambio"] = yaml.safe_load(textos["restauracao_cambio.yaml"])
        regra["versao_completa"] = f"{regra['versao']}+{combinado[:8]}"
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


def _carregar_2026b(esperado: str) -> tuple[dict, dict]:
    """Recompõe o formato separado original, sem incluir regras de versões posteriores."""
    try:
        pasta = PASTA / _VERSAO_2026B
        bruto = (pasta / "manifesto.json").read_bytes()
        if hashlib.sha256(bruto).hexdigest() != esperado:
            raise ValueError(_ERRO)
        manifesto = json.loads(bruto)
        nomes = ("restauracao.yaml", "cenarios_restauracao.yaml", "restauracao_cambio.yaml")
        if (
            manifesto["versao"] != _VERSAO_2026B
            or manifesto["perfil"] != "separado_2026b"
            or manifesto["arquivos_combinados"] != list(nomes)
            or manifesto["separador_hex"] != "0a2d2d0a"
        ):
            raise ValueError(_ERRO)
        for chave, nome in (("calibracao", "restauracao_calibracao.yaml"), ("edital", "edital_profloresta.yaml")):
            if manifesto[chave] != {"arquivo": nome, "presente": False} or (pasta / nome).exists():
                raise ValueError(_ERRO)
        textos = {}
        for nome in nomes:
            textos[nome] = (pasta / nome).read_bytes()
            if hashlib.sha256(textos[nome]).hexdigest() != manifesto["arquivos"][nome]["sha256"]:
                raise ValueError(_ERRO)
        combinado = hashlib.sha256(b"\n--\n".join(textos[nome] for nome in nomes)).hexdigest()
        if combinado != manifesto["sha256_combinado"]:
            raise ValueError(_ERRO)
        regra = yaml.safe_load(textos["restauracao.yaml"])
        regra["cenarios"] = yaml.safe_load(textos["cenarios_restauracao.yaml"])
        regra["calibracao"] = {}
        regra["cambio"] = yaml.safe_load(textos["restauracao_cambio.yaml"])
        regra["versao_completa"] = f"{regra['versao']}+{regra['cenarios']['versao']}+{combinado[:8]}"
        if regra["versao_completa"] != _VERSAO_2026B:
            raise ValueError(_ERRO)
        codigo = manifesto["codigo"]["raiz/restauracao.py"]
        proveniencia = {
            "regra_source_commit": manifesto["commit"],
            "regra_source_sha256": combinado,
            "regra_source_versao": _VERSAO_2026B,
            "regra_source_manifesto_sha256": esperado,
            "versao_tarefa_referencia": manifesto["versao_tarefa"],
            "regra_source_perfil": manifesto["perfil"],
            "regra_source_codigo_sha256": codigo["sha256"],
            "regra_source_codigo_git_blob": codigo["git_blob"],
            "regra_source_curva_ast_sha256": manifesto["ast"]["funcoes_sha256"]["forma_curva"],
        }
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise ValueError(_ERRO) from None
    return copy.deepcopy(regra), proveniencia


def forma_curva_2026b(r: dict) -> np.ndarray:
    """Forma anual fechada de 2026b: interpola os pontos e declina até completar o total.

    Aceita somente a regra canônica integral. A curva atual tem outro algoritmo;
    esta reconstrução explícita não executa módulos históricos nem recalcula imóveis.
    """
    try:
        if not isinstance(r, dict) or r.get("versao_completa") != _VERSAO_2026B:
            raise ValueError(_ERRO)
        registro = carregar(_VERSAO_2026B)
        if registro is None or r != registro[0]:
            raise ValueError(_ERRO)
        cc = r["captura_curva"]
        n_anos = int(cc["anos"])
        pontos = sorted((int(ano), float(valor)) for ano, valor in cc["pontos"])
        valores = np.zeros(n_anos + 1)
        for (a0, v0), (a1, v1) in zip(pontos, pontos[1:], strict=False):
            for ano in range(a0 + 1, a1 + 1):
                valores[ano] = v0 + (v1 - v0) * (ano - a0) / (a1 - a0)
        pico, valor_pico = pontos[-1]
        restante = float(cc["total_referencia"]) - float(valores[: pico + 1].sum())
        anos_restantes = n_anos - pico
        if anos_restantes > 0:
            queda = (anos_restantes * valor_pico - restante) / (anos_restantes * (anos_restantes + 1) / 2)
            for indice, ano in enumerate(range(pico + 1, n_anos + 1), 1):
                valores[ano] = max(valor_pico - queda * indice, 0.0)
        return valores / valores.sum()
    except (ValueError, TypeError, KeyError):
        raise ValueError(_ERRO) from None


def cenario(nome: str, r: dict) -> dict:
    """Dados normalizados do central_r11 histórico, sem aplicar o piso ou defaults de modelos novos.

    Este registro fechado tem todos os campos do cenário já declarados no YAML.
    A normalização só ordena marcos, converte os tipos e aplica a PTAX registrada;
    não recalcula crédito, reserva, custo ou fluxo individual.
    """
    try:
        if nome != "central_r11" or not isinstance(r, dict):
            raise ValueError(_ERRO)
        registro = carregar(r.get("versao_completa"))
        if registro is None or r != registro[0]:
            raise ValueError(_ERRO)
        bruto = r["cenarios"]["cenarios"][nome]
        c = {k: copy.deepcopy(v["valor"] if isinstance(v, dict) and "valor" in v else v) for k, v in bruto.items()}
        c["cenario"] = nome
        prazo = int(c["prazo_anos"])
        c["horizonte_anos"] = max(int(c["horizonte_anos"]), prazo)
        marcos = sorted(
            (int(ano), float(pct))
            for ano, pct in zip(c["entregas_anos"], c["marcos_pct"], strict=True)
            if 0 < int(ano) <= prazo
        )
        c["entregas_anos"] = [ano for ano, _ in marcos]
        c["marcos_pct"] = [pct for _, pct in marcos]
        c["entregas_pos_contrato_anos"] = sorted(
            int(ano) for ano in c["entregas_pos_contrato_anos"] if prazo < int(ano) <= c["horizonte_anos"]
        )
        c["desembolso_custo"] = [float(valor) for valor in c["desembolso_custo"]]
        if c["cambio_ptax"]:
            c["cambio_brl_usd"] = float(r["cambio"]["ptax"])
            c["cambio_data"] = r["cambio"]["data"]
        return c
    except (ValueError, TypeError, KeyError):
        raise ValueError(_ERRO) from None
