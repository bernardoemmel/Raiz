"""Resposta ecológica por CAR, com a unidade e a ausência de evidência explícitas.

CAR, carbono e área de pasto não determinam densidade de árvores ou riqueza de
espécies. Sem inventário ou referência regional harmonizada, os horizontes ficam pendentes.
Os patamares de monitoramento de SP são apresentados separadamente e nunca viram
P10/P50/P90 amazônicos. Plantio inicial também não equivale a árvores sobreviventes.

Uma projeção local pode entrar em ``ecologia_projecao``: fonte, data_corte,
modelo_versao, tipo (cenario_planejamento ou projecao_calibrada), populacao,
riqueza_unidade e horizontes (ano -> densidade_arvores_ha e numero_especies,
ambos com p10/p50/p90). O tipo e a origem acompanham cada resposta publicada.
"""

from __future__ import annotations

import copy
import hashlib
import math
from functools import lru_cache
from pathlib import Path

import yaml

ARQUIVO = Path(__file__).parent / "regras" / "padroes" / "restauracao_ecologia.yaml"
Q = ("p10", "p50", "p90")
TIPOS_PROJECAO = {"cenario_planejamento", "projecao_calibrada"}
ROTULO_REGIONAL = "estimativa regional, não medida na fazenda"
SEM_DADO = (
    "Sem inventário, composição de espécies e trajetória de sobrevivência/recrutamento locais: "
    "não há base para quantificar a densidade de árvores ou o número de espécies desta fazenda. "
    "A incerteza não foi quantificada; valores ausentes não significam zero."
)


@lru_cache(maxsize=4)
def _regra(marca: tuple) -> dict:
    bruto = ARQUIVO.read_bytes()
    r = yaml.safe_load(bruto)
    h = hashlib.sha256(bruto + Path(__file__).read_bytes()).hexdigest()[:12]
    r["versao_completa"] = f"{r['versao']}+{h}"
    return r


def regra() -> dict:
    marca = tuple((p.stat().st_mtime_ns, p.stat().st_size) for p in (ARQUIVO, Path(__file__)))
    return copy.deepcopy(_regra(marca))


def _numero(valor, campo: str) -> float:
    if isinstance(valor, bool):
        raise ValueError(f"{campo}: precisa ser um número finito não negativo")
    try:
        n = float(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{campo}: precisa ser um número finito não negativo") from exc
    if not math.isfinite(n) or n < 0:
        raise ValueError(f"{campo}: precisa ser um número finito não negativo")
    return n


def _faixa(valor, campo: str) -> dict:
    if not isinstance(valor, dict) or not all(q in valor for q in Q):
        raise ValueError(f"{campo}: informe p10, p50 e p90")
    faixa = {q: _numero(valor[q], f"{campo}.{q}") for q in Q}
    if not faixa["p10"] <= faixa["p50"] <= faixa["p90"]:
        raise ValueError(f"{campo}: p10 deve ser menor ou igual a p50 e p90")
    return faixa


def _projecao(linha: dict) -> dict | None:
    p = linha.get("ecologia_projecao")
    if p is None:
        return None
    if not isinstance(p, dict):
        raise ValueError("ecologia_projecao precisa ser um objeto")
    for campo in ("fonte", "data_corte", "modelo_versao", "populacao", "riqueza_unidade", "incerteza"):
        if not isinstance(p.get(campo), str) or not p[campo].strip():
            raise ValueError(f"projeção ecológica sem {campo}")
    if p.get("tipo") not in TIPOS_PROJECAO:
        raise ValueError("tipo deve ser cenario_planejamento ou projecao_calibrada")
    if p["riqueza_unidade"] != "especies_distintas_na_area_restaurada":
        raise ValueError("a riqueza deve ser de espécies distintas na área restaurada, nunca por hectare")
    if not isinstance(p.get("horizontes"), dict):
        raise ValueError("projeção ecológica sem horizontes")
    if any(str(a) not in {"3", "5", "10", "15"} for a in p["horizontes"]):
        raise ValueError("horizonte ecológico deve ser 3, 5, 10 ou 15 anos")
    return p


def projetar(linha: dict, modelo_versao: str) -> dict:
    """Quatro respostas por fazenda, mesmo para área pequena e sem projeção local.

    Riqueza é número de espécies distintas da área restaurada e não cresce por
    multiplicação pelos hectares. Densidade refere-se à população descrita na
    fonte; o total de indivíduos usa somente a área que será restaurada.
    """
    if not isinstance(modelo_versao, str) or not modelo_versao.strip():
        raise ValueError("informe a versão do modelo de restauração")
    cod = linha.get("cod_imovel")
    if not isinstance(cod, str) or not cod.strip():
        raise ValueError("informe cod_imovel")
    cod = cod.strip()
    area = linha.get("restauracao_area_ha", linha.get("area_ha"))
    area = None if area is None else _numero(area, "restauracao_area_ha")
    r = regra()
    ref = r["referencia_monitoramento"]
    projecao = _projecao(linha)
    horizontes = []
    for ano in r["horizontes_anos"]:
        entrada = None if projecao is None else projecao["horizontes"].get(str(ano), projecao["horizontes"].get(ano))
        densidade, riqueza = dict.fromkeys(Q), dict.fromkeys(Q)
        status = "sem_previsao_local"
        if entrada is not None:
            if not isinstance(entrada, dict):
                raise ValueError(f"horizonte {ano}: precisa ser um objeto")
            densidade = _faixa(entrada.get("densidade_arvores_ha"), f"ano {ano}, densidade")
            riqueza = _faixa(entrada.get("numero_especies"), f"ano {ano}, espécies")
            status = projecao["tipo"]
        total = {q: None if densidade[q] is None or area is None else round(densidade[q] * area, 2) for q in Q}
        horizontes.append(
            {
                "ano": ano,
                "situacao": status,
                "situacao_regional": "pendente_harmonizacao_de_dados_abertos"
                if entrada is None
                else "projecao_documentada",
                "rotulo_regional": ROTULO_REGIONAL if entrada is None else None,
                "pendencias_regionais": r["pendencias_regionais"] if entrada is None else [],
                "incerteza": projecao["incerteza"] if entrada is not None else SEM_DADO,
                "densidade_arvores_ha": densidade,
                "numero_arvores_area_restaurada": total,
                "numero_especies": riqueza,
                "referencia_monitoramento": {
                    "tipo": "referencia_comparativa_sp_nao_previsao_pa",
                    "regenerantes_ha_adequado_acima_de": ref["adequado"][ano]["regenerantes_ha"],
                    "especies_adequado_acima_de": ref["adequado"][ano]["especies"],
                    "populacao": ref["populacao"],
                    "riqueza_unidade": ref["riqueza_unidade"],
                    "fonte": ref["url"],
                },
            }
        )
    return {
        "cod_imovel": cod,
        "area_restaurada_ha": area,
        "bioma": linha.get("bioma"),
        "metodo": linha.get("modo_restauracao", linha.get("modo")),
        "modelo_versao": modelo_versao,
        "ecologia_versao": r["versao_completa"],
        "projecao_versao": projecao["modelo_versao"] if projecao else None,
        "fonte_projecao": projecao["fonte"] if projecao else None,
        "data_corte_projecao": projecao["data_corte"] if projecao else None,
        "populacao": projecao["populacao"] if projecao else "árvores; classe de tamanho ainda não definida em campo",
        "riqueza_unidade": "especies_distintas_na_area_restaurada",
        "idade_inicial_anos": 0,
        "idade_referencia": (
            "Anos após iniciar restauração na área aberta; a idade da vegetação secundária existente "
            "não é atribuída ao pasto a restaurar. MapBiomas mede idade da cobertura, não árvores ou espécies."
        ),
        "fontes_publicas_avaliadas": r["fontes_publicas"],
        "base_regional_candidata": r["base_regional"],
        "incerteza": projecao["incerteza"] if projecao else SEM_DADO,
        "horizontes": horizontes,
        "referencias": [
            {"fonte": ref["fonte"], "url": ref["url"], "limite": ref["abrangencia"]},
            {k: v for k, v in r["plantio_inicial"].items()},
            r["recuperacao_diversidade"],
            *r["fontes_publicas"],
        ],
        "proximo_passo": (
            "Inventariar parcelas por método com classe de tamanho e área amostrada explícitas; "
            "identificar espécies, sobrevivência e recrutamento; ajustar e validar a trajetória local."
        ),
    }


def tabela(linhas, modelo_versao: str) -> list[dict]:
    """Quatro linhas por CAR para o CSV do comprador, sem dados pessoais."""
    saida = []
    for linha in linhas:
        p = projetar(linha, modelo_versao)
        for h in p["horizontes"]:
            item = {
                k: p[k]
                for k in (
                    "cod_imovel",
                    "bioma",
                    "idade_inicial_anos",
                    "idade_referencia",
                    "fontes_publicas_avaliadas",
                    "base_regional_candidata",
                    "area_restaurada_ha",
                    "metodo",
                    "modelo_versao",
                    "ecologia_versao",
                    "projecao_versao",
                    "fonte_projecao",
                    "data_corte_projecao",
                    "populacao",
                    "riqueza_unidade",
                    "incerteza",
                )
            }
            item.update(ano=h["ano"], situacao=h["situacao"], incerteza=h["incerteza"])
            item.update({k: h[k] for k in ("situacao_regional", "rotulo_regional", "pendencias_regionais")})
            for campo in ("densidade_arvores_ha", "numero_arvores_area_restaurada", "numero_especies"):
                item.update({f"{campo}_{q}": h[campo][q] for q in Q})
            ref = h["referencia_monitoramento"]
            item.update({f"referencia_sp_{k}": v for k, v in ref.items()})
            saida.append(item)
    return saida
