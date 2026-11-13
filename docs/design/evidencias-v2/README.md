# Comparação visual V2 com dados públicos

As três telas foram capturadas com Playwright e comparadas aos arquivos
`print_brasil.png`, `print_pedido.png` e `print_celular.png` do pacote aprovado
`raiz-visual-v2-telas.zip`. O resultado mantém mapa inteiro, base escura, hexágonos,
fontes Bricolage Grotesque/JetBrains Mono e painéis flutuantes. As diferenças de dados,
acesso público e cartografia estão registradas abaixo; não se declara igualdade de pixels.

O [relatório de capturas](relatorio-capturas.json) registra **147 respostas HTTP,
zero 404, zero erro HTTP, zero erro JavaScript, zero erro de console e zero requisição
falha** nessa navegação. As três telas não tiveram rolagem horizontal. A medição de
Lighthouse e o CI da entrega continuam separados e pendentes nesta evidência.

## Arquivos, dimensões e origem

| Tela | Antes publicado | V2 | Viewport da V2 / DPR |
|---|---|---|---|
| Brasil | [antes-brasil.png](antes-brasil.png), 1440 × 1000, DPR 1 | [depois-brasil.png](depois-brasil.png) | 1440 × 900 / 2 |
| Pedido | Não havia painel equivalente nesta captura | [depois-pedido.png](depois-pedido.png) | 1440 × 900 / 2 |
| Celular | [antes-celular.png](antes-celular.png), 360 × 800, DPR 1 | [depois-celular.png](depois-celular.png) | 390 × 844 / 3 |

As imagens V2 têm as mesmas dimensões e DPR dos três prints aprovados: 2880 × 1800
nos dois casos desktop e 1170 × 2532 no celular. Os registros anteriores têm outras
dimensões; a comparação entre antes e depois é de composição e comportamento.

Os cinco PNGs foram copiados sem edição, redimensionamento ou recompressão. Somam
3,89 MB, com SHA-256 e tamanho individual no relatório. Isso preserva os números e
rótulos pequenos. As respostas de rede foram publicadas apenas com caminho e status;
a origem localhost e o caminho temporário de trabalho foram retirados do relatório.

- **Antes:** publicação do [PR #90](https://github.com/bernardoemmel/Raiz/pull/90),
  main `c9d6302646f40e7d6a3eb3a1d3a0c4d669301aab`, capturada em 13/11/2026 às
  19:18 de Brasília no site público.
- **Depois:** build local `site-v2-6`, capturado em 13/11/2026 entre 20:10:57 e
  20:11:09 de Brasília, Chrome for Testing 157.0.8103.78, contexto anônimo e movimento
  reduzido. O servidor de validação responde HTTP Range para os PMTiles.
- **Dados:** artefato público auditado da publicação anterior, 4.511 arquivos,
  SHA-256 `5590d75b8de2c10cd7e2bc2f49ce638822ed9b7982c2441eac7abca16101a92a`.
  A V2 usa esse retrato fixo para permitir conferência; a captura não afirma ser o
  retrato mais recente que o processamento possa ter publicado depois.

## Comparação com cada print aprovado

| Referência | O que corresponde | Diferenças visíveis e motivo |
|---|---|---|
| `print_brasil` | Mapa sem coluna lateral; base escura; topo em pílulas; H3 r4 em seis tons; cartão de 400 px com número lima; legenda e camadas flutuantes. | Protomaps substitui o Carto de teste, conforme o guia, por isso rótulos e limites diferem. A camada diz **Fazendas cadastradas** e o filtro começa em **todas**: o agregado não contém apenas aptas. O cartão mostra valores reais com uma casa decimal, descrição de matrícula e acesso a **Sobre os dados**; é mais alto que o da maquete. Controles de zoom, ajuda e atribuição permanecem acessíveis. |
| `print_pedido` | Painel à direita, 430 px, três opções, seleção urucum, números mono e faixa P10/P50/P90 em escala comum. | O título informa que os três lotes alcançam a meta **no P50**, sem afirmar garantia no P10. O painel público acrescenta preço médio e terra pronta; mantém rolagem para informações adicionais. Não pinta os 22 hexágonos escolhidos ilustrativamente na maquete nem mostra composição. O cartão territorial acompanha o Pará e continua no desktop. A reserva não informada não recebe os 20% ilustrativos. |
| `print_celular` | Viewport 390 × 844, mapa inteiro com H3, marca/busca/pedido no topo e cartão inferior com número de 48 px. | Busca e conta abrem diálogos/menu acessíveis; alça, ajuda, Camadas e zoom permanecem disponíveis. O cartão mostra **com matrícula** e o link **Sobre os dados**; a frase complementar aparece ao expandir. Os alvos de toque do topo são de 48 px. A gaveta encosta no rodapé, enquanto a referência tem recuo de 8 px. |

Essas comparações registram o estado efetivamente capturado. O cartão e o pedido
não copiam os números da maquete; arredondamento e texto refletem o contrato disponível.
As fontes são locais, apenas woff2 latino, com licenças SIL OFL no produto. O tema
claro do produtor não foi alterado.

## Números e datas conferidos no retrato

O cartão nacional soma os resumos de aptidão de **724 municípios em 13 estados**:
20.357.288 ha, 992.019 imóveis lidos, 574.373 aptas e 102.621 com matrícula identificada.
O manifesto desses dados foi publicado em 13/11/2026 às 17:05:30 de Brasília.

A cobertura dos desenhos básicos é outra medida: **1.188 municípios em 17 estados**,
com manifesto de 13/11/2026 às 17:23:26 de Brasília. O H3 contém 8.871 células r5,
2.331.082 cadastros e 4.142 células sem medida suficiente de hectares, gerado às
17:31:34 de Brasília. A escala permanece na contagem de cadastros; valores ausentes
não viram zero e hectares do resumo não são atribuídos artificialmente aos hexágonos.

O pedido usa `amostra/lote_PA_central_r11.json`, contrato `publico_lotes`, cenário
`central_r11`, modelo `restauracao-2026d+a84f9789`, atualizado em 12/11/2026 às 17:47:42
de Brasília. A meta publicada é 1 milhão de créditos. Os três lotes são alternativas;
não devem ser somados nem tratados como um pedido recalculado pelos filtros da tela.

| Opção | Fazendas | Hectares | P10 | P50 | P90 | US$/crédito |
|---|---:|---:|---:|---:|---:|---:|
| Mais barato | 95 | 9.561,3 | 1.298.148 | 1.871.150 | 2.309.231 | 26,83 |
| Mais seguro | 270 | 9.942,8 | 1.310.708 | 1.891.833 | 2.332.670 | 27,68 |
| Mais compacto | 25 | 10.838,4 | 1.339.520 | 1.950.679 | 2.426.929 | 33,29 |

A fração da meta com terra pronta é zero nas três opções desse arquivo. Reserva
percentual não foi informada. A captura não acessa a API paga, não identifica os
imóveis que compõem os lotes e não exibe nome, CPF ou contato de proprietário.
Nenhum clique de envio de contato foi realizado.

## Telas capturadas

### Brasil

![Brasil V2, mapa escuro com hexágonos e cartão territorial público](depois-brasil.png)

[Ver a tela nacional anterior](antes-brasil.png).

### Pedido público

![Pedido V2, três alternativas reais sem desenho da composição privada](depois-pedido.png)

### Celular

![Celular V2, mapa inteiro e cartão inferior com valores públicos](depois-celular.png)

[Ver a tela de celular anterior](antes-celular.png).

## Limites desta evidência

O relatório comprova a navegação e os arquivos efetivamente capturados. Não substitui
os testes de autorização, a auditoria completa da publicação, o teste de teclado/axe,
a medição Lighthouse ou o CI. **Desempenho e CI da entrega permanecem pendentes.**
