# Mapa: grupos nacionais e detalhe real

Capturas reais de Chromium, em 1440 × 1000 px, sem retoque. A entrada passa do SVG publicado para o mapa MapLibre com agrupamento Supercluster. Cada círculo mostra a quantidade de fazendas e os hectares conhecidos do agregado; ao aproximar, os grupos se abrem e dão lugar aos limites reais do CAR.

| Escala | Antes | Depois |
|---|---|---|
| Brasil | [SVG do site publicado](brasil-antes.png) | [Grupos no MapLibre](brasil-depois.png) |
| Pará | — | [Grupos estaduais](estado-depois.png) |
| Parauapebas | — | [Município](municipio-depois.png) |
| Fazenda selecionada | — | [Satélite e contorno sem preenchimento](fazenda-depois.png) |

O “antes” foi capturado em `https://bernardoemmel.github.io/Raiz/`, em 13/11/2026 às 02:14:31 UTC, com zero erros de rede ou JavaScript. O “depois” usa o frontend integrado `1412642`, incluindo as fichas e painéis da rodada 12 e a integração da main. O Supercluster permanece no worker do MapLibre; os grupos visíveis são botões HTML posicionados pelo mapa, com contagem, hectares, toque e teclado. A camada transparente mantém a consulta espacial sem compilar o programa gráfico dos círculos. O exportador público é `6bc77c1`.

A [entrada em 360 px](brasil-360-depois.png) foi aberta em um contexto novo, com enquadramento inicial próprio. Há uma só legenda recolhível, para que a explicação não cubra a contagem. O SVG permanece apenas no minimapa da barra lateral. As [imagens da etapa H3](../mapa/README.md) ficam como registro histórico; os hexágonos não são a visualização nacional desta rodada.

## Dados e limites

As cinco imagens novas compartilham o snapshot público de 12/11/2026 às 23:54:43 UTC: **444 municípios e 13 estados**. A entrada nacional usa **6.787 pontos públicos**, deduplicados globalmente, em **1.227.580 bytes no GeoJSON normal**, lido diretamente pelo worker; o fallback de publicações anteriores ocupa **215.591 bytes comprimidos**. São os centros das células H3 já agregadas, nunca a localização individual de uma fazenda. O Supercluster incorporado no worker do MapLibre soma as contagens e hectares conhecidos, sem criar um segundo índice na interface.

O conjunto agrega 1.626.268 CARs nas células publicadas; esse número não representa cobertura completa do território. As 3.717 células com medida somam apenas áreas conhecidas, positivas e sem sobreposição detectada, com ao menos cinco contribuintes. Células suprimidas não entram nessa contagem. Os grupos sem medida dizem “Sem medida”, e a parcela desconhecida não vira zero. Os centros são uma alocação estatística; não desenham áreas de restauração. O período deste snapshot é preservado para a comparação, mesmo quando a próxima publicação contém mais dados.

O painel distingue a cobertura cartográfica atual do resumo de aptidão de 365 municípios em 9 estados, cuja data própria não veio no pacote. A contagem de municípios processados continua no mapa e no painel, sem transformar um conjunto parcial em completo.

## Verificação

O roteiro abriu Brasil e Pará, buscou Parauapebas e clicou no interior renderizado de uma fazenda pública sem sobreposição detectada. A seleção enquadrou o CAR efetivamente escolhido no zoom 14,32. Foram **107 requisições no roteiro desktop, zero respostas 404 e zero erros de JavaScript/console**. A entrada móvel também terminou sem erros HTTP ou JavaScript. Nove imagens reais de satélite responderam HTTP 200. Não houve consulta a endpoints pagos de ficha, visual, certidão ou desenvolvimento; os PNGs não mostram nome, CPF ou contato de proprietário.

O detalhe conserva contornos de 1 px sem preenchimento, tracejado nos limites com sobreposição detectada e máscara fora do imóvel selecionado. A imagem pública é o mosaico **Sentinel-2 cloudless 2016/2017 da EOX**, histórico, sob **CC BY 4.0**; ano e atribuição aparecem na captura. Ela não descreve a situação atual da terra. O fundo e o satélite ficam abaixo dos limites, contornos e máscara.

Nenhuma hachura de restauração foi criada a partir do CAR. A fonte autorizada está vazia no mapa aberto; a ficha paga consulta a geometria real pela API quando disponível. A carga desse recorte no mapa geral continua pendente, portanto estas capturas não demonstram essa integração.

O teste Playwright usa grupos com medida ausente para conferir soma correta, rótulos reais, abertura por Enter com foco preservado no mapa, reutilização do botão após atualização, transição para município sem perder o zoom e remoção dos marcadores no detalhe. Confere também o fallback gzip, alerta e ausência de marcadores quando o GeoJSON falha, 360 px, zero violações axe WCAG 2.1 AA e zero 404 na navegação normal. Os seis testes unitários dos grupos incluem o Supercluster real, medidas desconhecidas, números pequenos e formatação. A proteção contra resposta tardia após troca de fonte foi revisada pelo contador de geração.

## Desempenho

A série final fixa de três execuções Lighthouse mobile com estes dados reais obteve **88, 98 e 92 em desempenho (mediana 92)** e **100 em acessibilidade nas três**. O gate usa mediana de desempenho ≥ 90 e acessibilidade mínima ≥ 90. A amostra 88 continua registrada; não foi descartada. LCP: 1,464 / 1,430 / 1,490 s; TBT: 431,5 / 152 / 319 ms. A inicialização gráfica ainda varia neste ambiente.

O perfil identificou cerca de 100 ms reais na compilação e vinculação do programa dos círculos. Os botões visíveis eliminaram essa compilação mantendo o índice no worker. A série isolada dessa mudança, antes da legenda única, foi 91 / 93 / 97; a série anterior era 78 / 84 / 90. Não houve temporizador artificial, identificação do Lighthouse ou troca de motor de mapa.

As imagens registram aparência e navegação; não substituem a inspeção do site publicado. A medição corresponde ao build integrado `1412642` e ao snapshot congelado de 444 municípios, não à publicação diária mais recente. Resultados estão em [lighthouse.json](lighthouse.json); metadados e hashes em [snapshot.json](snapshot.json).
