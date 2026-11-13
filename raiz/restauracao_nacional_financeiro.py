"""Fluxo agregado nacional a partir das entradas congeladas das selecionadas."""

from pathlib import Path

import pandas as pd

from raiz import lote as L
from raiz import restauracao as R


class EntradasSelecionadas:
    """Resolve cada município sem materializar as entradas do país inteiro."""

    def __init__(self, tabela, origens):
        self.tabela, self.origens = tabela, origens

    def entradas(self, codigos):
        selecionadas = self.tabela[self.tabela.cod_imovel.isin(codigos)]
        saida = {}
        for cod, grupo in selecionadas.groupby("cod_ibge", sort=True):
            if int(cod) not in self.origens:
                raise ValueError("Entrada municipal das selecionadas ausente; fluxo parcial recusado.")
            ids = set(grupo.cod_imovel)
            linhas = R.linhas_para_refazer(self.origens[int(cod)], int(cod), so=ids)
            if set(linhas) != ids:
                raise ValueError("Entradas não cobrem todas as fazendas selecionadas; fluxo parcial recusado.")
            saida.update(linhas)
        return saida


def economia_selecionadas(tabela_parquet: Path, origens: dict[int, Path], *, c: dict, r: dict, volume: float) -> dict:
    """Soma fluxos, recalcula dívida do projeto e preserva multas e limite do contrato.

    A conferência dos hashes das fontes é feita pelo chamador contra o catálogo.
    Este adaptador não usa média de TIR nem dá preço do contrato ao excedente.
    """
    t = pd.read_parquet(tabela_parquet)
    exigidas = {"cod_imovel", "cod_ibge", "papel", "restauracao_versao", "restauracao_cenario", "credito_p50"}
    if not exigidas <= set(t):
        raise ValueError("Tabela selecionada sem campos financeiros obrigatórios.")
    if t.cod_imovel.isna().any() or not t.cod_imovel.is_unique or not t.papel.isin(["titular", "reserva"]).all():
        raise ValueError("Seleção duplicada, sem identidade ou com papel inválido.")
    if len(t) and (
        not t.restauracao_versao.eq(r["versao_completa"]).all() or not t.restauracao_cenario.eq(c["cenario"]).all()
    ):
        raise ValueError("Versão/cenário da seleção diverge das premissas do fluxo.")
    if t.empty:
        return {"situacao": "sem_selecionadas", "fazendas_com_fluxo": 0}
    cron = R.cronograma_lote(float(t.credito_p50.sum()), c, r, volume)
    resultado = L._economia(t, EntradasSelecionadas(t, origens), c, r, volume, cron, {})
    return {"situacao": "calculada", "modelo_versao": r["versao_completa"], **resultado}
