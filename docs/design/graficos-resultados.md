# Gráficos de resultados na ficha autorizada

A ficha de crédito de uma opção recebe `resultados` opcional no formato `raiz.resultados.graficos.v1`.
Os gráficos ficam em **Acompanhamento dos resultados**, depois de Título, Método, Perdas, Garantias e Risco.
A API atual não fornece séries reais de contratos, emissões e entregas, nem pares de observação por método
nesse formato. A interface explica a ausência. O placar aberto de acerto contém notas agregadas, sem os valores
por método; não se pode reconstruir observações a partir dessas notas nem publicar o hub interno.

- ECharts: três séries acumuladas, contratado, emitido e entregue, sem empilhamento ou soma entre etapas.
  Contrato exige `contrato_assinado`; emissão exige `emissao_registrada`; entrega exige `entrega_comprovada`.
  Cada valor tem fonte do catálogo, data e identificador do registro. `null` produz lacuna; zero continua zero.
- Vega-Lite: faixa P10/P90, ponto circular P50 e losango para o observado. Cada par comprova a mesma classe
  (crédito ou FLAG), métrica, unidade, escala, área de referência, início, fim e horizonte em dias.
  A previsão ao vivo foi congelada antes do dia observado, e o gabarito corresponde à data-alvo exata.
  Reexecuções retrospectivas são declaradas e separadas. Versões e métodos ficam escritos na tabela;
  o desenho não seleciona vencedor nem comprova superioridade entre populações diferentes.

O validador Python `raiz/pedidos/resultados_graficos.py` recusa campos extras, booleanos como números,
valores não finitos, datas incoerentes, registros duplicados e fontes livres. O parser TypeScript
`front/compartilhado/graficos-resultados.ts` reconstrói uma projeção fechada. Não há campos de proprietário,
CAR, coordenadas, URLs, especificações de gráfico ou expressões recebidas da API. As fontes documentais
são identificadas por catálogo e registro; nomes livres de certificados não são enviados ao navegador.
O carregador do runtime Vega recusa qualquer leitura de rede ou arquivo.

`origem: demonstracao` exige todas as fontes marcadas como **Demonstração sintética**. A marca também
aparece no bloco da ficha. `graficos-demonstracao.ts` só atende o modo simulado, usando a área, o período e a
faixa da opção fictícia. Não lê o Release nem serve como evidência de contratos, emissões ou aprendizado reais.
Não há exportação estática desse subcontrato: o acesso e a revisão da opção continuam sob responsabilidade
da API da ficha. A comparação deve usar os registros autorizados daquele documento, sem copiar números
privados para o placar público.

## Desempenho e acessibilidade

As tabelas são HTML, com cabeçalhos, unidades, fontes e datas. Podem ser percorridas com teclado e roladas
horizontalmente em 360 px. Os desenhos SVG equivalentes são ocultos da árvore acessível para evitar repetição.
Linhas, pontos e legendas diferenciam séries também por forma, sem depender apenas de cor. Não há animação.

ECharts usa apenas linha, eixos, legenda e SVG. Vega-Lite usa `compile`, e Vega usa `parse`/`View`.
Os módulos de gráficos são importações dinâmicas ativadas pelo botão de cada painel. Não entram na árvore
estática da ficha nem do mapa inicial. Falhas no desenho conservam as tabelas e exibem aviso.

`node front/scripts/testar-graficos.mjs` gera um harness temporário com a fixture sintética e build de produção,
verifica a ausência das bibliotecas na árvore estática, abre cada painel pelo teclado, confere SVG, largura
360/1280 px, zero erros HTTP/JavaScript e WCAG 2.1 AA pelo axe. Os prints e o relatório ficam em
`/tmp/raiz-graficos-e2e` (configurável por `RAIZ_GRAFICOS_EVIDENCIAS`). O harness é apagado ao terminar.
O teste não substitui a medição Lighthouse do site completo integrado nem uma avaliação com dados reais.
