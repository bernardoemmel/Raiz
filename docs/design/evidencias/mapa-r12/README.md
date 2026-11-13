# Mapa: grupos nacionais e detalhe real

Capturas reais de Chromium, em 1440 × 1000 px no desktop e 360 × 800 px no celular, sem retoque. A entrada passa do SVG publicado para o mapa MapLibre com agrupamento Supercluster. Cada círculo mostra a quantidade de fazendas e os hectares conhecidos do agregado; ao aproximar, os grupos se abrem e dão lugar aos limites reais do CAR.

| Escala | Antes | Depois |
|---|---|---|
| Brasil | [SVG do site publicado](brasil-antes.png) | [Grupos no MapLibre](brasil-depois.png) |
| Pará | — | [Grupos estaduais](estado-depois.png) |
| Parauapebas | — | [Município](municipio-depois.png) |
| Fazenda selecionada | — | [Satélite e contorno sem preenchimento](fazenda-depois.png) |
| Brasil a 360 px | — | [Entrada móvel](brasil-360-depois.png) |
| Processamento | — | [Ausência de telemetria no snapshot](processamento-depois.png) |

O “antes” foi capturado em `https://bernardoemmel.github.io/Raiz/`, em 13/11/2026 às 02:14:31 UTC, com zero erros de rede ou JavaScript. Os seis “depois” foram capturados entre 04:52:25 e 04:52:31 UTC do mesmo dia, com o frontend integrado `f0a7c96`, incluindo as fichas da rodada 12, o painel de processamento da main e o fundo sólido em CSS. O Supercluster permanece no worker do MapLibre; os grupos visíveis são botões HTML posicionados pelo mapa, com contagem, hectares, toque e teclado. A camada transparente mantém a consulta espacial sem compilar o programa gráfico dos círculos. O exportador histórico do agregado público é `6bc77c1`.

A [entrada em 360 px](brasil-360-depois.png) foi aberta em um contexto novo, com enquadramento inicial próprio. Há uma só legenda recolhível, para que a explicação não cubra a contagem. O SVG permanece apenas no minimapa da barra lateral. As [imagens da etapa H3](../mapa/README.md) ficam como registro histórico; os hexágonos não são a visualização nacional desta rodada.

## Dados e limites

As seis imagens novas compartilham o snapshot público cujo índice cartográfico foi gerado em 12/11/2026 às 23:54:43 UTC, com dados publicados às 23:46:50 UTC: **444 municípios e 13 estados**. O índice, os agregados normal e gzip e o manifesto dos estados foram conferidos byte a byte contra a fonte congelada. A entrada nacional usa **6.787 pontos públicos**, deduplicados globalmente, em **1.227.580 bytes no GeoJSON normal**, lido diretamente pelo worker; o fallback de publicações anteriores ocupa **215.591 bytes comprimidos**. São os centros das células H3 já agregadas, nunca a localização individual de uma fazenda. O Supercluster incorporado no worker do MapLibre soma as contagens e hectares conhecidos, sem criar um segundo índice na interface.

O conjunto agrega 1.626.268 CARs nas células publicadas; esse número não representa cobertura completa do território. As 3.717 células com medida somam apenas áreas conhecidas, positivas e sem sobreposição detectada, com ao menos cinco contribuintes. Células suprimidas não entram nessa contagem. Os grupos sem medida dizem “Sem medida”, e a parcela desconhecida não vira zero. Os centros são uma alocação estatística; não desenham áreas de restauração. O período deste snapshot é preservado para a comparação, mesmo quando a próxima publicação contém mais dados.

O painel distingue a cobertura cartográfica deste snapshot do resumo de aptidão de **365 municípios em 9 estados**, cuja data própria não veio no pacote. A contagem do mapa não transforma esse resumo parcial em completo.

O snapshot não contém observações de execução. Para registrar o painel integrado sem misturar dados vivos com a comparação congelada, o build consulta uma projeção local em `amostra/processamento.json`: **27 UFs sem telemetria**, com todas as contagens e datas de observação, mudança e validade nulas. A captura e o DOM confirmam 27 avisos “Sem informação de processamento” e 81 contagens “Não informado”. O `gerado_em` de 13/11/2026 às 04:49:46 UTC é a criação dessa projeção, não a data de uma observação. Nenhuma consulta ao RAW vivo foi feita; os 444 municípios do mapa não foram convertidos em municípios prontos nesse painel.

## Verificação

O roteiro abriu Brasil e Pará, buscou Parauapebas e clicou no interior renderizado de uma fazenda pública sem sobreposição detectada. A seleção enquadrou o CAR efetivamente escolhido no zoom 14,32. Foram **108 requisições no roteiro desktop e 55 na entrada móvel, todas respondidas com HTTP 200 ou 206, zero 404 e zero erros de JavaScript/console**. Nove imagens reais de satélite responderam HTTP 200. Não houve interceptação de rede nem consulta a endpoints pagos de ficha, visual, certidão ou desenvolvimento; os PNGs não mostram nome, CPF ou contato de proprietário.

O detalhe conserva contornos de 1 px sem preenchimento, tracejado nos limites com sobreposição detectada e máscara fora do imóvel selecionado. A imagem pública é o mosaico **Sentinel-2 cloudless 2016/2017 da EOX**, histórico, sob **CC BY 4.0**; ano e atribuição aparecem na captura. Ela não descreve a situação atual da terra. O fundo e o satélite ficam abaixo dos limites, contornos e máscara.

Nenhuma hachura de restauração foi criada a partir do CAR. A fonte autorizada está vazia no mapa aberto; a ficha paga consulta a geometria real pela API quando disponível. A carga desse recorte no mapa geral continua pendente, portanto estas capturas não demonstram essa integração.

O Playwright Pages do build final passou. Seu roteiro confere grupos com medida ausente, rótulos reais, abertura por Enter com foco preservado no mapa, reutilização do botão após atualização, transição para município sem perder o zoom e remoção dos marcadores no detalhe. Confere também fallback gzip, alerta e ausência de marcadores quando o GeoJSON falha, 360 px e zero 404 na navegação normal. As sete verificações axe da fixture terminaram sem violações WCAG 2.1 AA. A proteção contra resposta tardia após troca de fonte foi revisada pelo contador de geração.

## Desempenho

A série final fixa de três execuções Lighthouse mobile com estes dados reais obteve **82, 95 e 95 em desempenho (mediana 95)** e **100 em acessibilidade nas três**. O gate usa mediana de desempenho ≥ 90 e acessibilidade mínima ≥ 90. A amostra 82 continua registrada; não foi descartada. LCP: 1,495 / 1,426 / 1,428 s; TBT: 709 / 232,5 / 261 ms. A inicialização gráfica ainda varia neste ambiente.

O mesmo build passou as 18 medições da fixture sintética do CI: três por rota, com medianas de desempenho **Brasil 98, entrar 98, novo pedido 97, prospecção 97, acerto 97 e produtor 100**. Todas obtiveram acessibilidade 100. Esses resultados da fixture permanecem separados da série com dados reais.

O perfil identificou cerca de 100 ms reais na compilação e vinculação do programa dos círculos. Os botões visíveis eliminaram essa compilação mantendo o índice no worker. O fundo sólido também passou a CSS (`ce9f24f`), preservando as camadas geográficas; a comparação de 360 px desse experimento teve zero pixels diferentes. Como histórico, a série isolada dos botões, antes da legenda única, foi 91 / 93 / 97; a série anterior era 78 / 84 / 90. Não houve temporizador artificial, identificação do Lighthouse ou troca de motor de mapa.

As imagens e a rede registram o build local; não substituem a inspeção do site publicado. A medição corresponde ao frontend integrado `f0a7c96` e ao snapshot congelado de 444 municípios, não à publicação diária mais recente. Resultados estão em [lighthouse.json](lighthouse.json); datas, configuração de build e hashes em [snapshot.json](snapshot.json).
