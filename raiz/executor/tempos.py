"""Medições agregadas a partir de controles privados; não publica marcas ou CAR.

Legado: soma dos tempos das últimas tarefas concluídas por município, não tempo
corrido da execução. Estado inteiro: só execução completa, sem retomada parcial,
com todos os municípios calculados na mesma rodada. Quantil linear (tipo 7).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from raiz.executor.armazem import sha256_arquivo


def estatistica(valores: list[float]) -> dict:
    if not valores:
        return {"amostras": 0, "mediana_s": None, "p95_s": None}
    ordem = sorted(valores)

    def quantil(p):
        indice = (len(ordem) - 1) * p
        baixo = math.floor(indice)
        alto = math.ceil(indice)
        return round(ordem[baixo] + (ordem[alto] - ordem[baixo]) * (indice - baixo), 6)

    return {"amostras": len(ordem), "mediana_s": quantil(0.5), "p95_s": quantil(0.95)}


def _numero(valor) -> bool:
    return type(valor) in (float, int) and math.isfinite(valor) and valor >= 0


def _totais() -> dict[str, int]:
    from motor.raiz_situacao import COD_UF

    por = {str(codigo): uf for uf, codigo in COD_UF.items()}
    totais = defaultdict(int)
    with Path(__file__).with_name("municipios.csv").open() as f:
        for r in csv.DictReader(f):
            totais[por[r["codigo_uf"]]] += 1
    return dict(totais)


def medir(controles: list[dict]) -> dict:
    grupos = {}
    totais = _totais()
    vistos = set()
    for controle in controles:
        estado = controle.get("estado") or {}
        uf = estado.get("uf")
        versoes = estado.get("versoes") or {}
        if uf not in totais or not versoes:
            continue
        identidade = hashlib.sha256(json.dumps(versoes, sort_keys=True).encode()).hexdigest()
        grupo = grupos.setdefault(
            (uf, identidade),
            {
                "uf": uf,
                "versoes": versoes,
                "versoes_sha256": identidade,
                "municipios": {},
                "estados": [],
                "rodadas_com_adocao": [],
                "excluidos": set(),
            },
        )
        medidos_neste_controle = set()
        for cod, marca in (controle.get("marcas") or {}).items():
            if not re.fullmatch(r"\d{7}", str(cod)):
                continue
            tarefas = marca.get("tarefas") or {}
            # Vazio é conclusivo só para a primeira tarefa; não se inventam tempos
            # para tarefas dispensadas, adotadas ou interrompidas.
            nomes = {"funil"} if (tarefas.get("funil") or {}).get("vazio") else set(versoes)
            amostras = [tarefas.get(nome) or {} for nome in nomes]
            validas = bool(nomes) and all(
                not t.get("erro")
                and not t.get("adotado")
                and t.get("versao") == versoes.get(nome)
                and _numero(t.get("segundos"))
                for nome, t in zip(nomes, amostras, strict=True)
            )
            if validas:
                medidos_neste_controle.add(str(cod))
                # Diferentes snapshots não duplicam o mesmo município/versões.
                data = max(str(t.get("data") or "") for t in amostras)
                anterior = grupo["municipios"].get(str(cod))
                if anterior is None or data >= anterior[0]:
                    grupo["municipios"][str(cod)] = (data, sum(t["segundos"] for t in amostras))
            else:
                grupo["excluidos"].add(str(cod))
        chave = (uf, identidade, estado.get("inicio"), estado.get("fim"))
        if (
            chave not in vistos
            and estado.get("situacao") == "pronto"
            and not estado.get("erros")
            and estado.get("total") == estado.get("rodados") == totais[uf]
            and estado.get("feitos") == totais[uf]
            and estado.get("inicio")
            and estado.get("fim")
        ):
            segundos = estado.get("segundos_executor")
            if segundos is None:
                try:
                    inicio, fim = (dt.datetime.fromisoformat(estado[k]) for k in ("inicio", "fim"))
                    segundos = (fim - inicio).total_seconds() if inicio.tzinfo and fim.tzinfo else None
                except (ValueError, TypeError):
                    segundos = None
            if _numero(segundos):
                vistos.add(chave)
                categoria = "estados" if len(medidos_neste_controle) == totais[uf] else "rodadas_com_adocao"
                grupo[categoria].append(segundos)
    saida = []
    for chave in sorted(grupos):
        g = grupos[chave]
        municipios = g.pop("municipios")
        g["municipio_soma_tarefas"] = estatistica([x[1] for x in municipios.values()])
        g["datas_tarefas"] = {
            "primeira": min((x[0] for x in municipios.values()), default=None),
            "ultima": max((x[0] for x in municipios.values()), default=None),
        }
        g["estado_inteiro"] = estatistica(g.pop("estados"))
        g["estado_rodada_sem_medicao_integral"] = estatistica(g.pop("rodadas_com_adocao"))
        g["municipios_excluidos"] = len(g.pop("excluidos") - municipios.keys())
        saida.append(g)
    return {"versao": 1, "quantil": "linear tipo 7", "grupos": saida}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("controles", type=Path, nargs="+")
    p.add_argument("--saida", type=Path, required=True)
    args = p.parse_args()
    r = medir([json.loads(f.read_text()) for f in args.controles])
    r["fontes_sha256"] = sorted({sha256_arquivo(f) for f in args.controles})
    args.saida.write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n")
    print(f"Medição agregada: {len(r['grupos'])} grupos UF/versões.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
