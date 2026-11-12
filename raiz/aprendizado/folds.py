"""Teste por tempo (E8 passo 5): folds anuais que só leem o que se sabia na data de corte.

- como_estava: SQL do histórico scd2 da coleta (bruto.<tabela>, dlt) como estava num dia: linha aberta antes do
  corte e ainda não fechada (_dlt_valid_from <= corte e _dlt_valid_to vazio ou depois do corte). É o que um modelo
  novo usa para refazer a previsão de um ano passado sem espiar o futuro.
- cortes_anuais: um corte por ano, na mesma data.
- calibracao_por_tempo: para cada corte C, ajusta a calibração só com os gabaritos observados até C (com
  pelo_registro, também já registrados até C) e
  testa nas previsões feitas no ano seguinte (corte em (C, C + 1 ano]), contra a chance sem calibração. As
  previsões recalibradas do teste ficam congeladas como backtest (modelo <modelo>+calibracao, a versão do mapa, a
  entrada "fold:<C>"), para o portão campeão e desafiante (raiz/aprendizado/campeao.py) comparar com o campeão nos
  mesmos imóveis.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Connection, text

from raiz.aprendizado import calibracao as C


def como_estava(tabela: str, esquema: str = "bruto") -> str:
    """SELECT da tabela scd2 como estava em :corte (parâmetro de data/hora)."""
    if not tabela.replace("_", "").isalnum() or not esquema.replace("_", "").isalnum():
        raise ValueError("nome de tabela inválido")
    return (
        f"select * from {esquema}.{tabela} where _dlt_valid_from <= :corte "
        f"and (_dlt_valid_to is null or _dlt_valid_to > :corte)"
    )


def cortes_anuais(inicio: dt.date, fim: dt.date) -> list[dt.date]:
    out, c = [], inicio
    while c <= fim:
        out.append(c)
        try:
            c = c.replace(year=c.year + 1)
        except ValueError:  # 29 de fevereiro
            c = c.replace(year=c.year + 1, day=28)
    return out


def _proximo(c: dt.date) -> dt.date:
    try:
        return c.replace(year=c.year + 1)
    except ValueError:
        return c.replace(year=c.year + 1, day=28)


def calibracao_por_tempo(
    con: Connection,
    modelo: str,
    alvo: str,
    cortes: list[dt.date],
    congelar: bool = True,
    minimo_treino: int = 30,
    pelo_registro: bool = False,
) -> list[dict]:
    from raiz.aprendizado.registro import Previsao, Versoes, registrar_lote

    out = []
    for c in cortes:
        fim = _proximo(c)
        treino = C.pontos(con, modelo, alvo, ate=c, pelo_registro=pelo_registro)
        teste = C.pontos(con, modelo, alvo, corte_de=c, corte_ate=fim)
        linha = {"corte": c, "ate": fim, "n_treino": len(treino), "n_teste": len(teste)}
        if len(treino) < minimo_treino or not teste:
            linha["situacao"] = "pouco_dado"
            out.append(linha)
            continue
        mapa = C.ajustar(treino)
        base, cal = C.medir(teste), C.medir(teste, mapa)
        linha.update(situacao="ok", versao=mapa["versao"], brier_base=base["total"]["brier"],
                     brier_calibrado=cal["total"]["brier"], ece_base=base["total"]["ece"],
                     ece_calibrado=cal["total"]["ece"])  # fmt: skip
        if congelar:
            por_corte: dict[dt.date, list] = {}
            hz = {
                r.cod_imovel: r.horizonte_dias
                for r in con.execute(
                    text(
                        """select distinct on (cod_imovel) cod_imovel, horizonte_dias from aprendizado.previsao
                           where modelo = :m and alvo = :a and data_corte > :de and data_corte <= :ate
                           order by cod_imovel, data_corte desc"""
                    ),
                    {"m": modelo, "a": alvo, "de": c, "ate": fim},
                )
            }
            for x in teste:
                por_corte.setdefault(x.data_corte, []).append(
                    Previsao(
                        x.cod_imovel, alvo, hz.get(x.cod_imovel, 365), valor_num=C.calibrar(mapa, x.p, x.uf, x.porte)
                    )  # fmt: skip
                )
            for dc, ps in por_corte.items():
                registrar_lote(con, ps, Versoes(f"{modelo}+calibracao", mapa["versao"], f"fold:{c.isoformat()}", dc,
                                                tipo="backtest"),
                               f"calibração de {modelo} ({alvo}) treinada até {c}, teste por tempo")  # fmt: skip
        out.append(linha)
    return out
