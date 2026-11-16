"""Camada "já comprometida" no processamento: o que já está em projeto de carbono ou concessão, por CAR.

coleta.py   baixa os limites públicos (Verra, SFB, base científica do Zenodo) e publica no Release "insumos";
status.py   cruza cada CAR com esses limites e grava comprometida_<mun>.csv (tarefa própria do executor, com versão
            própria: mudou a coleta ou a regra, só esta tarefa refaz; o funil dos municípios prontos fica).
Documentação: docs/terra-comprometida.md e docs/colunas.md.
"""
