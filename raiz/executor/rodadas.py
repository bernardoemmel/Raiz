"""Registro operacional de tentativas sem resultado, usando o contrato privado do armazém."""

import datetime as dt

from raiz.executor.armazem import ArmazemRelease, _juntar_entrada


def registrar_tentativa(armazem: ArmazemRelease, uf: str, extra: dict) -> None:
    """Guarda a rodada privada antes do primeiro CSV, sem fabricar um pacote nem alterar hashes científicos.

    As outras fatias são preservadas sob as mesmas travas de UF/índice do publicador. O planejador e o painel
    conhecem também a tentativa que parou nas fontes, evitando tratar o estado como nunca tentado.
    """
    armazem.verificar_publicacao()
    armazem._exigir_privado()
    uf = uf.upper()
    with armazem._trava(f"trava-publicar-{uf}", 1800):
        anterior = armazem.manifesto(fresco=True).get("estados", {}).get(uf, {})
        info = _juntar_entrada(anterior, extra)
        info["atualizado_em"] = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
        armazem._gravar_indice({uf: info})
