# Mapa: grupos nacionais e detalhe real

Capturas reais de Chrome for Testing 157.0.8103.78, em 1440 × 1000 px no desktop e 360 × 800 px no celular, sem retoque. A entrada passa do SVG publicado para o MapLibre com Supercluster. Cada círculo mostra a quantidade de fazendas e os hectares conhecidos do agregado; ao aproximar, os grupos se abrem e dão lugar aos limites reais do CAR.

| Escala | Antes | Depois |
|---|---|---|
| Brasil | [SVG do site publicado](brasil-antes.png) | [Grupos no MapLibre](brasil-depois.png) |
| Pará | [Referência anterior](../mapa/estado-antes.png) | [Grupos estaduais](estado-depois.png) |
| Parauapebas | [Referência anterior](../mapa/municipio-antes.png) | [Município](municipio-depois.png) |
| Fazenda selecionada | [Referência anterior](../mapa/fazenda-antes.png) | [Satélite e contorno sem preenchimento](fazenda-depois.png) |
| Brasil a 360 px | — | [Entrada móvel](brasil-360-depois.png) |
| Processamento | — | [Ausência de telemetria no snapshot](processamento-depois.png) |

O “antes” nacional foi capturado em `https://bernardoemmel.github.io/Raiz/`, em **12/11/2026 às 23:14:31, horário de Brasília**, com zero erros de rede ou JavaScript. Esse PNG permanece intacto. Os seis “depois” foram capturados em **13/11/2026 entre 10:55:35 e 10:55:42, horário de Brasília**, com o frontend `650db81`: fichas da rodada 12, painel de processamento, fundo sólido em CSS, dimensionamento único na criação do mapa e composição das camadas nacionais no estilo inicial. Os horários ISO em UTC e hashes estão em [snapshot.json](snapshot.json).

O Supercluster permanece no worker do MapLibre; só os grupos visíveis recebem botões HTML, com contagem, hectares, toque e teclado. A camada transparente mantém a consulta espacial sem compilar o programa gráfico dos círculos. A [entrada em 360 px](brasil-360-depois.png) usa contexto novo e enquadramento próprio, com uma legenda recolhível. O SVG permanece apenas no minimapa da barra lateral.

As demais imagens “antes” pertencem à [etapa histórica do mapa](../mapa/README.md), com suas próprias fontes e datas. O detalhe anterior e o atual mostram a mesma escala, mas não a mesma fazenda. Os hexágonos daquela etapa não são a visualização nacional desta rodada.

## Dados e limites

As seis imagens novas compartilham o snapshot público cujo índice cartográfico foi gerado em **12/11/2026 às 20:54:43, horário de Brasília**, com dados publicados às **20:46:50**: **444 municípios e 13 estados**. O índice, os agregados normal e gzip, o manifesto dos estados e a projeção de processamento foram conferidos byte a byte contra a fonte congelada. O exportador histórico do agregado é `6bc77c1`; essa referência não é a versão atual do painel.

A entrada nacional usa **6.787 pontos públicos**, deduplicados globalmente, em **1.227.580 bytes no GeoJSON normal**, lido diretamente pelo worker. O fallback de publicações anteriores ocupa **215.591 bytes comprimidos**. São centros das células H3 já agregadas, nunca a localização individual de uma fazenda. O Supercluster soma contagens e hectares conhecidos, sem criar um segundo índice na interface.

O conjunto agrega **1.626.268 CARs** nas células publicadas; esse número não representa cobertura completa do território. As **3.717 células com medida** somam apenas áreas conhecidas, positivas e sem sobreposição detectada, com ao menos cinco contribuintes. Células suprimidas não entram nessa contagem. Grupos sem medida dizem “Sem medida”; a parcela desconhecida não vira zero. Os centros são uma alocação estatística e não desenham áreas de restauração.

O painel distingue a cobertura cartográfica deste snapshot do resumo de aptidão de **365 municípios em 9 estados**, cuja data própria não veio no pacote. A contagem do mapa não transforma esse resumo parcial em completo. O período do snapshot permanece congelado para a comparação, mesmo quando a publicação diária contém dados mais novos.

O snapshot não contém observações de execução. O build consulta uma projeção local em `amostra/processamento.json`: **27 UFs sem telemetria**, com contagens e datas de observação, mudança e validade nulas. A captura e o DOM confirmam 27 avisos “Sem informação de processamento” e 81 contagens “Não informado”. O `gerado_em` de **13/11/2026 às 01:49:46, horário de Brasília**, é a criação dessa projeção, não a data de uma observação. Nenhuma consulta ao RAW vivo foi feita; os 444 municípios do mapa não foram convertidos em municípios prontos nesse painel.

## Verificação

O roteiro abriu Brasil e Pará, buscou Parauapebas e clicou no interior renderizado de uma fazenda pública sem sobreposição detectada. A seleção enquadrou o CAR efetivamente escolhido no zoom **14,32**. Foram **109 requisições no desktop e 56 na entrada móvel**, todas respondidas com **HTTP 200 ou 206**: zero 404, erros de JavaScript/console ou falhas de rede. Não houve cancelamento de requisição nessa captura. **Nove imagens reais de satélite** responderam HTTP 200.

Não houve interceptação de rede nem consulta a endpoints pagos ou exportações de pasta. Os PNGs não mostram nome, CPF ou contato de proprietário. O roteiro também conferiu o processamento local, a ausência de consulta ao RAW vivo e a posição das camadas do fundo e do satélite abaixo dos contornos e da máscara.

O detalhe conserva contornos de 1 px sem preenchimento, tracejado nos limites com sobreposição detectada e máscara fora do imóvel selecionado. A imagem pública é o mosaico **Sentinel-2 cloudless 2016/2017 da EOX**, histórico, sob **CC BY 4.0**; ano e atribuição aparecem na captura. Ela não descreve a situação atual da terra.

Nenhuma hachura de restauração foi criada a partir do CAR. A fonte autorizada está vazia no mapa aberto; a ficha paga consulta a geometria real pela API quando disponível. A carga desse recorte no mapa geral continua pendente, portanto estas capturas não demonstram essa integração.

O Playwright Pages passou com a revisão final. O roteiro confere grupos com medida ausente, soma e rótulos, abertura por Enter com foco preservado, reutilização do botão, transição para município e remoção dos marcadores no detalhe. Também verifica fallback gzip, alerta e ausência de marcadores quando o GeoJSON falha. As **sete verificações axe** da fixture terminaram sem violações WCAG 2.1 AA em 360 px, com teclado e gaveta móvel.

## Desempenho

A única série fixa de três execuções Lighthouse mobile da revisão `650db81` com estes dados reais obteve **82, 90 e 90 em desempenho (mediana 90)** e **100 em acessibilidade nas três**. LCP: **0,758 / 1,797 / 0,753 s**; TBT: **716,1 / 341,5 / 407,5 ms**. A amostra 82 está preservada, sem descarte ou repetição para escolher nota. O resultado alcança exatamente o mínimo do portão por mediana, **sem folga**; não comprova que toda abertura individual chegue a 90.

A fixture sintética completa também passou suas **18 medições fixas**, três por rota: medianas **Brasil 90, entrar 98, novo pedido 97, prospecção 96, acerto 97 e produtor 100**. A série nacional da fixture foi **88/90/94**, preservada integralmente. Acessibilidade foi **100 nas 18 amostras**. Fixture e dados reais permanecem separados em [lighthouse.json](lighthouse.json).

A revisão elimina um redimensionamento redundante do canvas e prepara as fontes/camadas nacionais no estilo inicial, mantendo a chegada dos dados pelos mesmos efeitos. A comparação controlada de 360 px com a revisão anterior teve **zero pixels diferentes**, enquadramento, fontes e ordem das camadas iguais. A série real intermediária, apenas com o ajuste de dimensionamento, deu **86/86/92 (mediana 86)** e foi reprovada; esse resultado continua no histórico. Não houve temporizador artificial, identificação do Lighthouse ou troca de motor de mapa.

A série real foi executada com os arquivos exatos da revisão `650db81` antes de gravar o commit. Os hashes das três fontes foram conferidos no checkout e registrados nos metadados; os relatórios brutos não foram alterados. As imagens e medições correspondem ao build local e ao snapshot congelado, não à publicação diária mais recente. O CI e a inspeção do site publicado continuam verificações separadas.
