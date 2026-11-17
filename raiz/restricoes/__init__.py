"""Restrições nacionais na triagem: SICAR completo, SIGMINE (ANM), autos de infração do Ibama e Lista Suja.

coleta.py   baixa as fontes nacionais, tira nome, CPF e CNPJ na entrada e grava camadas sem dado pessoal numa pasta
            que o workflow coletar-restricoes.yml publica no Release "insumos".
status.py   cruza cada CAR do município com essas camadas e com o CAR completo (povos tradicionais, assentamentos,
            sobreposição entre CARs, RL e APP declaradas) e grava restricoes_<mun>.csv (tarefa própria do executor,
            folha do grafo: mudou a coleta ou a regra, só ela refaz; o funil dos municípios prontos fica).
Regras: raiz/regras/padroes/restricoes_nacionais.yaml. Documentação: docs/lote.md e docs/colunas.md.
"""
