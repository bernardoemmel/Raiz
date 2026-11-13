"""Sensibilidade com nova seleção de toda a oferta elegível e previsão versionada."""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from raiz import lote as L
from raiz import restauracao as R
from raiz.pedidos import oferta as O
from raiz.pedidos import otimizador as Z


def cenarios() -> list[tuple[str, dict]]:
    base = R.cenario("central_r12")
    casos = [("central", base)]
    for preco in (55.33, 55.76, 73.82):
        casos.append((f"preco_{preco}", {**base, "preco_usd_t": preco}))
    for reserva in (0.30, 0.40):
        casos.append((f"reserva_{reserva}", {**base, "reserva_risco": reserva}))
    for taxa in (0.12, 0.15):
        casos.append((f"desconto_{taxa}", {**base, "taxa_desconto": taxa}))
    casos.append(("pessimista", R.cenario("estresse_r12")))
    return casos


def versao(c: dict) -> str:
    material = Path(__file__).read_bytes() + R.versao().encode() + json.dumps(c, sort_keys=True).encode()
    return "sensibilidade-lote-2026a+" + hashlib.sha256(material).hexdigest()[:12]


def executar(dados: dict, destino: Path, *, casos=None, volume: float | None = None) -> dict:
    """Recalcula candidatos, inclusive pequenos, e chama de novo cada solver.

    Apenas critérios invariantes (geografia, salvaguardas e caminho da terra)
    delimitam a população. Não filtra por preço, TIR, crédito ou tamanho. Cada
    cenário tem JSONL comprimido próprio; faixas financeiras omitidas não são
    copiadas do cenário central. Arquivos vinculados ao CAR são privados.
    """
    destino.mkdir(parents=True, exist_ok=True)
    r = R.regra()
    oferta = dados["oferta"]
    if not oferta.restauracao_versao.eq(r["versao_completa"]).all():
        raise ValueError("sensibilidade exige oferta recalculada na versão atual")
    casos = casos or cenarios()
    volume = float(volume or L.premissas_lote(r)["creditos"])
    ped = L._pedido(dados["uf"], 1, R.cenario("central_r12"))
    candidatos = Z.filtrar(oferta, ped).copy()
    if "salvaguardas_planejamento" in candidatos:
        candidatos = candidatos[candidatos.salvaguardas_planejamento.eq(True)]
    candidatos = candidatos.sort_values("cod_imovel").reset_index(drop=True)
    linhas = L.Linhas(dados["pasta"], candidatos)
    entradas = linhas.entradas(candidatos.cod_imovel)
    if len(entradas) != len(candidatos):
        raise ValueError("faltam entradas de candidatos; não publicar estudo parcial")
    h = hashlib.sha256(candidatos.to_json(orient="records").encode())
    for cod in sorted(entradas):
        h.update(json.dumps(L.json_seguro(entradas[cod]), sort_keys=True).encode())
    h.update(json.dumps([volume, dados["uf"]]).encode())
    entrada_hash = h.hexdigest()
    tabelas, provas, conjuntos_base = [], [], {}
    for nome, c in casos:
        inicio = time.monotonic()
        modelo = versao(c) + "-" + entrada_hash[:12]
        caminho = destino / f"previsoes_{modelo.replace('+', '_')}.jsonl.gz"
        checkpoint = caminho.with_suffix(".concluido.json")
        if checkpoint.exists():
            anterior = json.loads(checkpoint.read_text())
            if anterior["prova"]["sha256"] != hashlib.sha256(caminho.read_bytes()).hexdigest():
                raise ValueError("previsões concluídas foram alteradas")
            for nome_decisao, digest in anterior["prova"]["decisoes_sha256"].items():
                if hashlib.sha256((destino / nome_decisao).read_bytes()).hexdigest() != digest:
                    raise ValueError("decisões concluídas foram alteradas")
            for opcao, ids in anterior["selecionadas"].items():
                conjuntos_base.setdefault(opcao, set(ids))
            tabelas.extend(anterior["resultados"])
            provas.append(anterior["prova"])
            continue
        registros = []
        temporario = caminho.with_suffix(".tmp")
        with gzip.open(temporario, "wt", encoding="utf-8") as arquivo:
            for anterior in candidatos.to_dict("records"):
                li = entradas[str(anterior["cod_imovel"])]
                calc, _ = R.calcular(li, c, r, financeiro_p50=True)
                novo = O.de_linha({**li, **calc}, anterior["lon"], anterior["lat"])
                if novo is None:
                    raise ValueError("candidato desapareceu na sensibilidade sem decisão explícita")
                # Preserva salvaguardas, caminho fundiário e identidade espacial.
                campos = (
                    "credito_p10",
                    "credito_p50",
                    "credito_p90",
                    "credito_ano",
                    "custo_credito_usd",
                    "preco_equilibrio_usd",
                    "tir_p10",
                    "tir_p50",
                    "tir_p90",
                    "tir_projeto",
                    "vpl_rs",
                    "pico_rs",
                    "modo",
                    "metodos",
                    "regeneracao_ha",
                    "semeadura_ha",
                    "plantio_ha",
                )
                registros.append({**anterior, **{k: novo[k] for k in campos}})
                registro = {
                    "cod_imovel": anterior["cod_imovel"],
                    "modelo_versao": r["versao_completa"],
                    "estudo_versao": modelo,
                    "entradas_sha256": entrada_hash,
                    "parametros": c,
                    "previsao": calc,
                }
                arquivo.write(json.dumps(L.json_seguro(registro), ensure_ascii=False, allow_nan=False) + "\n")
        if caminho.exists():
            # Arquivo integral de tentativa anterior é preservado. Confere o
            # conteúdo descomprimido (o cabeçalho gzip traz data da tentativa).
            with gzip.open(caminho, "rb") as a, gzip.open(temporario, "rb") as b:
                if hashlib.file_digest(a, "sha256").digest() != hashlib.file_digest(b, "sha256").digest():
                    raise ValueError("previsões existentes divergem; não sobrescrever histórico")
            temporario.unlink()
        else:
            temporario.replace(caminho)
        nova = pd.DataFrame(registros, columns=candidatos.columns)
        cache = {}
        precisa = R.contrato_para_marcos(volume, c, r)
        chance = L.premissas_lote(r)["chance_alvo_reserva"]
        alvo = precisa / R.fator_captura_alvo(chance, r)
        selecionadas, resultados_caso, provas_decisoes = {}, [], {}
        for opcao in L.OPCOES:
            sel = L._selecionar(nova, dados["uf"], precisa, alvo, c, opcao=opcao)
            resumo = L._resumo_lote(sel, precisa, alvo, volume, c, r, linhas, cache)
            ids = set(pd.concat([sel["tit"], sel["res"]]).cod_imovel)
            selecionadas[opcao] = sorted(ids)
            decisoes = destino / f"decisoes_{modelo.replace('+', '_')}_{opcao}.jsonl.gz"
            with gzip.open(decisoes, "wt", encoding="utf-8") as arquivo:
                for decisao in L.decisoes_selecao(nova, sel, c, r, opcao, contexto=modelo):
                    arquivo.write(json.dumps(L.json_seguro(decisao), ensure_ascii=False) + "\n")
            provas_decisoes[decisoes.name] = hashlib.sha256(decisoes.read_bytes()).hexdigest()
            base = conjuntos_base.setdefault(opcao, ids)
            row = {
                "cenario": nome,
                "opcao": opcao,
                "modelo_versao": r["versao_completa"],
                "estudo_versao": modelo,
                "preco_usd_t": c["preco_usd_t"],
                "reserva": c["reserva_risco"],
                "taxa_desconto": c["taxa_desconto"],
                "fazendas": len(ids),
                "pequenas": resumo["pequenas"],
                "hectares": resumo["ha_lote"],
                "creditos": resumo["creditos_lote_faixa"],
                "entraram": len(ids - base),
                "sairam": len(base - ids),
                "economia": resumo["economia"],
                "solver": resumo["solver"],
                "comercializacao": "pendente",
            }
            tabelas.append(row)
            resultados_caso.append(row)
        provas.append(
            {
                "cenario": nome,
                "versao": modelo,
                "previsoes": caminho.name,
                "sha256": hashlib.sha256(caminho.read_bytes()).hexdigest(),
                "decisoes_sha256": provas_decisoes,
                "candidatos_reavaliados": len(candidatos),
                "segundos": time.monotonic() - inicio,
            }
        )
        checkpoint.write_text(
            json.dumps(
                L.json_seguro({"prova": provas[-1], "resultados": resultados_caso, "selecionadas": selecionadas}),
                ensure_ascii=False,
            )
        )
    resultado = {
        "resultados": tabelas,
        "provas": provas,
        "selecao_refeita": True,
        "acesso": "privado",
        "limite": "Uma variável por vez; pessimista combina premissas. Sem liberação comercial.",
    }
    (destino / "sensibilidade.json").write_text(json.dumps(L.json_seguro(resultado), ensure_ascii=False, indent=2))
    plano = [
        {
            **{k: v for k, v in x.items() if k not in ("creditos", "economia")},
            **{q: (x["creditos"] or {}).get(q) for q in ("p10", "p50", "p90")},
        }
        for x in tabelas
    ]
    pd.DataFrame(plano).to_csv(destino / "sensibilidade.csv", index=False)
    return resultado
