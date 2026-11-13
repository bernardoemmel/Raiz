"""Processo isolado de inferência GPL-3; não pertence ao pacote distribuído Raíz.

Recebe JSON local de blocos já agregados e escreve JSON, sem servidor HTTP,
credenciais, acesso à base de fazendas ou importação do pacote raiz.
"""

import argparse
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path


def executar(entrada):
    if os.environ.get("RAIZ_SCPI_SERVIDOR") != "1":
        raise RuntimeError("scpi é exclusivo do ambiente de servidor")
    import numpy as np
    import pandas as pd
    from scpi_pkg.scdata import scdata
    from scpi_pkg.scpi import scpi

    painel = pd.DataFrame(entrada["blocos"])
    tratado = entrada["bloco_tratado"]
    corte = int(entrada["periodo_plantio"])
    pre = np.sort(painel.loc[painel.periodo < corte, "periodo"].unique())
    pos = np.sort(painel.loc[painel.periodo >= corte, "periodo"].unique())
    controles = sorted(painel.loc[~painel.tratado, "bloco"].unique())
    if len(pre) < 12 or not len(pos) or len(controles) < 2 or tratado in controles:
        raise ValueError("inferência exige 12 períodos pré, um pós e dois controles não tratados")
    painel = painel[painel.bloco.isin([tratado, *controles])].copy()
    if painel.duplicated(["bloco", "periodo"]).any():
        raise ValueError("bloco/período duplicado")
    matriz = painel.pivot(index="periodo", columns="bloco", values="valor")
    if not np.isfinite(matriz.to_numpy()).all():
        raise ValueError("painel desbalanceado ou não finito")
    simulacoes = int(entrada.get("simulacoes", 1000))
    if not 200 <= simulacoes <= 10000:
        raise ValueError("simulacoes deve estar entre 200 e 10000")
    semente = int(entrada.get("semente", 5511))
    np.random.seed(semente)
    dados = scdata(
        df=painel,
        id_var="bloco",
        time_var="periodo",
        outcome_var="valor",
        period_pre=pre,
        period_post=pos,
        unit_tr=tratado,
        unit_co=controles,
        features=None,
        constant=False,
        cointegrated_data=False,
        verbose=False,
    )
    resultado = scpi(
        dados,
        w_constr={"name": "simplex"},
        sims=simulacoes,
        cores=1,
        u_alpha=0.10,
        e_alpha=0.10,
        e_method="gaussian",
        u_missp=True,
        u_order=1,
        e_order=1,
        u_lags=0,
        e_lags=0,
        verbose=False,
        plot=False,
    )
    intervalo = resultado.CI_all_gaussian
    if intervalo is None or not np.isfinite(intervalo[["Lower", "Upper"]].to_numpy()).all():
        raise RuntimeError("inferência não produziu limites finitos; manter pendência")
    texto = json.dumps(entrada, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {
        "modelo_versao": "scpi-servidor-2026a+" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12],
        "scpi_versao": version("scpi-pkg"),
        "licenca": "GPL-3.0-only; execução só no servidor",
        "entradas_sha256": hashlib.sha256(texto.encode()).hexdigest(),
        "semente": semente,
        "simulacoes": simulacoes,
        "periodos_treino": pre.tolist(),
        "unidade": entrada["unidade"],
        "metodo": "scpi gaussiano, simplex",
        "cobertura_nominal": 0.8,
        "nao_sao_quantis_p10_p90": True,
        "intervalos": [
            {"periodo": int(p), "limite_inferior": float(lo), "limite_superior": float(hi)}
            for p, lo, hi in zip(pos, intervalo.Lower, intervalo.Upper, strict=True)
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("entrada", type=Path)
    parser.add_argument("saida", type=Path)
    args = parser.parse_args()
    args.saida.write_text(
        json.dumps(executar(json.loads(args.entrada.read_text())), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
