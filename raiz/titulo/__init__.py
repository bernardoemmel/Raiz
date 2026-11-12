"""Título e geolocalização (E5): chave do registro, achados no formato do CFPB, confirmações e regularização da posse.

- achados.py        chave do registro (CAR + parcelas SIGEF + matrícula + CNS) e o achado (registro, regra, campo,
                    valor, gravidade, fase), com os achados da certidão (raiz/documentos) no mesmo formato;
- regularizacao.py  para cada imóvel em posse ou assentamento: o que falta para o título sair, com a evidência de
                    ocupação por satélite, a classe (em titulação, pronta para pedir, falta georreferenciamento,
                    pendente, impedida), o próximo passo e a chance a priori, congelada como previsão;
- banco.py          titulo.achado e titulo.confirmacao: quem confirmou ou descartou cada achado, e quando.

Nada de nome ou CPF: o registro é o código do CAR, a matrícula e o CNS; quem confirma é um identificador de operador.
"""
