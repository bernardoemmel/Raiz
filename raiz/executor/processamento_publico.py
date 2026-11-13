"""Projeção pública da telemetria: somente contagens municipais observadas.

``feitos`` do executor inclui falhas e pode cobrir apenas uma fatia. A existência
de CSV e o estado de um job do Actions não comprovam municípios em execução.
Este módulo, por isso, aceita apenas a telemetria explícita com prazo de validade.
"""

from __future__ import annotations

import datetime as dt
import re

UFS = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
CONTAGENS = ("prontos", "em_execucao", "com_erro", "pendentes", "desconhecidos")
MAX_LEASE = dt.timedelta(hours=1)


def _data(valor: object) -> dt.datetime | None:
    if not isinstance(valor, str) or len(valor) > 40:
        return None
    try:
        data = dt.datetime.fromisoformat(valor)
    except ValueError:
        return None
    return data.astimezone(dt.UTC) if data.tzinfo is not None else None


def _inteiro(valor: object) -> bool:
    return type(valor) is int and 0 <= valor <= 6000


def sanitizar_processamento(uf: str, dado: object) -> dict | None:
    """Extrai a allowlist; uma observação ambígua não vira contagem zero.

    O produtor garante exclusividade das cinco classes e deduplicação municipal
    no escopo declarado. Uma fatia nunca é reclassificada como estado inteiro.
    Campos adicionais internos (eventos, erros, caminhos) não são publicados.
    """
    if uf not in UFS or not isinstance(dado, dict) or type(dado.get("versao")) is not int or dado["versao"] != 1:
        return None
    escopo, unidade = dado.get("escopo"), dado.get("unidade")
    if escopo not in ("uf", "unidade") or not isinstance(unidade, str):
        return None
    if not re.fullmatch(rf"{uf}(?:-[1-9][0-9]{{0,3}})?", unidade) or (escopo == "uf" and unidade != uf):
        return None
    total, municipios = dado.get("municipios_total"), dado.get("municipios")
    if not _inteiro(total) or not isinstance(municipios, dict):
        return None
    if any(not _inteiro(municipios.get(c)) for c in CONTAGENS):
        return None
    if sum(municipios[c] for c in CONTAGENS) != total:
        return None
    tempos = {k: _data(dado.get(k)) for k in ("observado_em", "ultima_mudanca_em", "valido_ate")}
    observado, mudanca, validade = tempos.values()
    if any(t is None for t in tempos.values()):
        return None
    if not mudanca <= observado < validade or validade - observado > MAX_LEASE:
        return None
    return {
        "versao": 1,
        "escopo": escopo,
        "unidade": unidade,
        "municipios_total": total,
        "municipios": {c: municipios[c] for c in CONTAGENS},
        **{k: v.isoformat() for k, v in tempos.items()},
    }


def estado_publico(uf: str, dado: object, *, agora: dt.datetime) -> dict:
    """Mantém os tempos da fonte; consultar ou publicar não renova seu lease."""
    limpo = sanitizar_processamento(uf, dado)
    if limpo is None or _data(limpo["observado_em"]) > agora + dt.timedelta(seconds=30):
        return {
            "uf": uf,
            "escopo": "indisponivel",
            "unidade": None,
            "municipios_total": None,
            "municipios": dict.fromkeys(CONTAGENS),
            "observado_em": None,
            "ultima_mudanca_em": None,
            "valido_ate": None,
            "situacao": "sem_telemetria",
        }
    atual = _data(limpo["valido_ate"]) > agora
    # Uma execução observada no passado não é uma execução acontecendo agora.
    if not atual:
        limpo["municipios"]["em_execucao"] = None
    limpo.pop("versao")
    return {"uf": uf, **limpo, "situacao": "atual" if atual else "desatualizado"}


def painel_publico(entradas: dict, *, agora: dt.datetime | None = None) -> dict:
    agora = agora or dt.datetime.now(dt.UTC)
    return {
        "versao": 1,
        "gerado_em": agora.isoformat(),
        "estados": [estado_publico(uf, entradas.get(uf, {}).get("processamento"), agora=agora) for uf in UFS],
    }


def ler_painel(armazem) -> dict:
    """Release: um manifesto fresco, sem baixar pacotes privados por estado."""
    from raiz.executor.armazem import ler_json

    if hasattr(armazem, "manifesto"):
        entradas = armazem.manifesto(fresco=True).get("estados", {})
    else:
        entradas = {uf: ler_json(armazem, f"estado/{uf}.json") or {} for uf in UFS}
    if not isinstance(entradas, dict) or any(not isinstance(e, dict) for e in entradas.values()):
        raise ValueError("observação de processamento indisponível")
    return painel_publico(entradas)
