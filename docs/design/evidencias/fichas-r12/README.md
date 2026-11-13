# Ficha e gráficos da rodada 12

Capturas diretas do Chromium em 13/11/2026 UTC, sem retoque, dos testes automatizados.
Os documentos, fontes, datas e números são **inteiramente sintéticos**. Nenhum resultado real do Release
é representado por estas imagens; elas conferem a interface e o contrato.

- [Ficha a 1440 px](ficha-sintetica.png): mesma área, classe de evidência e horizonte no total e por hectare; cinco seções em ordem fixa e revisão própria.
- [Gráficos a 1280 px](graficos-sinteticos.png): contratado/emitido/entregue sem somar etapas; faixa P10/P50/P90 e observação por método.

Os scripts `front/scripts/testar-ficha-credito.mjs` e `front/scripts/testar-graficos.mjs` também verificam 360 px,
teclado, ausência de dados, separação público/pago, carregamento sob demanda e axe WCAG 2.1 AA.
As imagens registram o aspecto visual, não calibram o motor e não comprovam resultados de carbono.
Os gráficos da primeira imagem continuam recolhidos até a abertura explícita. Os relatórios e capturas
completas de cada execução ficam nos artifacts do CI.

A faixa P10–P90 tem contraste de 6,20:1 contra o fundo. Círculo e losango usam halo opaco de 2 px,
com contrastes de 8,50:1 e 6,33:1; formas, legenda e tabela conservam a informação sem depender apenas da cor.
