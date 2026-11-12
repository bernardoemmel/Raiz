"""Pedido de lote (docs/cena-alvo.md): o cliente pede "1 milhão de créditos" e o mapa monta o melhor lote.

- oferta.py: uma linha por fazenda com o que o pedido usa (crédito, custo, TIR, marcos, caminho da terra, onde);
- campos.py: o pedido (o contrato com o front em front/compartilhado/pedidos/tipos.ts);
- aceite.py: chance de aceite do dono por perfil, que aprende com cada contato;
- otimizador.py: quanto existe na base, o que falta e o que afrouxar, e as 3 opções (HiGHS) com reserva;
- servico.py: pedido salvo, ondas de contato, andamento, grupo pronto, reserva com Pix, vigia;
- pix.py: cobrança Pix pela AbacatePay (modo de teste sem chave);
- api.py: as rotas.

Nome, CPF e contato do dono nunca passam por aqui: o nível de interesse é o único dado do dono que a API devolve.
"""
