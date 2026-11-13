# Mapa: grupos nacionais e detalhe real

Capturas reais de Chromium, em 1440 × 1000 px, sem retoque. A entrada passa do SVG publicado para o mapa MapLibre com agrupamento Supercluster. Cada círculo mostra a quantidade de fazendas e os hectares conhecidos do agregado; ao aproximar, os grupos se abrem e dão lugar aos limites reais do CAR.

| Escala | Antes | Depois |
|---|---|---|
| Brasil | [SVG do site publicado](brasil-antes.png) | [Grupos no MapLibre](brasil-depois.png) |
| Pará | — | [Grupos estaduais](estado-depois.png) |
| Parauapebas | — | [Município](municipio-depois.png) |
| Fazenda selecionada | — | [Satélite e contorno sem preenchimento](fazenda-depois.png) |

O “antes” foi capturado em `https://bernardoemmel.github.io/Raiz/`, em 13/11/2026 às 02:14:31 UTC, com zero erros de rede ou JavaScript. O “depois” usa o frontend `971e1b1`, que inclui o renderer Supercluster `c2aae73`, e o exportador nacional `550af32`. As [imagens da etapa H3](../mapa/README.md) permanecem como registro histórico; os hexágonos não são a visualização nacional desta rodada.

## Dados e limites

As quatro imagens novas compartilham o snapshot público de 12/11/2026 às 23:54:43 UTC: **444 municípios e 13 estados**. A entrada nacional usa **6.787 pontos públicos**, deduplicados globalmente, em **215.591 bytes comprimidos**. São os centros das células H3 já agregadas, nunca a localização individual de uma fazenda. O Supercluster incorporado no worker do MapLibre soma as contagens e hectares conhecidos, sem criar um segundo índice na interface.

O conjunto agrega 1.626.268 CARs nas células publicadas; esse número não representa cobertura completa do território. As 3.717 células com medida somam apenas áreas conhecidas, positivas e sem sobreposição detectada, com ao menos cinco contribuintes. Células suprimidas não entram nessa contagem. Os grupos sem medida dizem “Sem medida”, e a parcela desconhecida não vira zero. Os centros são uma alocação estatística; não desenham áreas de restauração. O período deste snapshot é preservado para a comparação, mesmo quando a próxima publicação contém mais dados.

O painel distingue a cobertura cartográfica atual do resumo de aptidão de 365 municípios em 9 estados, cuja data própria não veio no pacote. A contagem de municípios processados continua no mapa e no painel, sem transformar um conjunto parcial em completo.

## Verificação

O roteiro abriu Brasil e Pará, buscou Parauapebas e clicou no interior renderizado de uma fazenda pública sem sobreposição detectada. A seleção enquadrou o CAR efetivamente escolhido no zoom 14,32. Foram **107 requisições, zero respostas 404 e zero erros de JavaScript/console**. Nove imagens reais de satélite responderam HTTP 200. Não houve consulta a endpoints pagos de ficha, visual, certidão ou desenvolvimento; os PNGs não mostram nome, CPF ou contato de proprietário.

O detalhe conserva contornos de 1 px sem preenchimento, tracejado nos limites com sobreposição detectada e máscara fora do imóvel selecionado. A imagem pública é o mosaico **Sentinel-2 cloudless 2016/2017 da EOX**, histórico, sob **CC BY 4.0**; ano e atribuição aparecem na captura. Ela não descreve a situação atual da terra. O fundo e o satélite ficam abaixo dos limites, contornos e máscara.

Nenhuma hachura de restauração foi criada a partir do CAR. A fonte autorizada está vazia no mapa aberto; a ficha paga consulta a geometria real pela API quando disponível. A carga desse recorte no mapa geral continua pendente, portanto estas capturas não demonstram essa integração.

O teste Playwright também usa grupos com medida ausente para conferir soma correta, abertura pelo teclado, transição para município sem perder o zoom, polígonos só no detalhe, 360 px, zero violações axe WCAG 2.1 AA e zero 404. Os quatro testes unitários incluem o Supercluster e o formatador de números reais do MapLibre. As imagens registram aparência e navegação; **não são uma medição de Lighthouse** nem substituem a inspeção do site depois da publicação. Metadados e hashes estão em [snapshot.json](snapshot.json).
