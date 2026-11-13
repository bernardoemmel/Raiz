# Evidência do redesenho do mapa

Capturas de dados reais, em Chromium com janela de 1440 × 1000 px. Os sete PNGs preservam a imagem produzida pelo navegador, sem retoque. O enquadramento de detalhe foi escolhido para mostrar a seleção de um imóvel; não compara a mesma fazenda entre as duas versões.

| Escala | Antes | Depois |
|---|---|---|
| Brasil inicial | — | [MapLibre na entrada](brasil-depois.png) |
| Pará | [Estado](estado-antes.png) | [Potencial agregado](estado-depois.png) |
| Parauapebas | [Município](municipio-antes.png) | [Potencial e limite municipal](municipio-depois.png) |
| Fazenda aproximada | [Detalhe](fazenda-antes.png) | [Satélite, contornos e seleção](fazenda-depois.png) |

## Origem do snapshot

O “antes” foi capturado no site publicado em 12/11/2026, durante esta entrega. O “depois” usa a compilação da frente integrada `fa7a83b`, com a navegação Acerto, o renderer do mapa, o satélite público e a inicialização nacional otimizada. O mapa principal da entrada é um canvas MapLibre; a pequena miniatura de localização no cabeçalho do painel continua independente. O satélite e o fundo estadual ficam abaixo das camadas cartográficas.

Os dados abertos vêm do artefato de publicação gerado em **12/11/2026 às 23:54:43 UTC**, com **444 municípios e 13 estados**. O H3 e a sinalização de sobreposição foram produzidos por `486ef71`, em **13/11/2026 às 00:35:56 UTC**, depois da conferência dos hashes das geometrias contra o pacote de medidas de cada uma das 13 UFs. O snapshot tem **6.787 células únicas**, sendo **3.717 com potencial conhecido**. Células compartilhadas entre arquivos de estados não são somadas novamente.

As células representam uma alocação estatística de potencial conhecido, com cobertura parcial e ao menos cinco contribuintes. Elas não são o recorte geográfico de restauração. Fazendas com sobreposição ou sem medida continuam no cadastro, fora dessa soma; ausência não é zero. O tracejado indica um limite com sobreposição detectada, não desenha a área exata da interseção.

## Verificação das imagens e da rede

O roteiro abriu o Brasil e o Pará, buscou **Parauapebas** e selecionou uma fazenda pública sem sobreposição detectada nesse snapshot. O clique ocorreu no interior realmente renderizado do CAR; em seguida o mapa enquadrou o imóvel efetivamente escolhido, no **zoom 14,32**. Foram **108 requisições, zero respostas 404 e zero erros de JavaScript/console**. As nove imagens pedidas ao serviço real de satélite responderam HTTP 200. Também foi conferida a ordem das camadas: o raster, o véu e o fundo estadual não podem encobrir H3, limites, contornos ou máscara.

A imagem pública é o **Sentinel-2 cloudless 2016/2017 da EOX**, histórico, sob **CC BY 4.0**. Ano, licença e atribuição ficam visíveis no detalhe. Ela não representa a situação atual da terra. Não houve consulta a endpoints de ficha, visual, certidão ou desenvolvimento pagos. Os PNGs mostram somente cadastro público e situação básica, sem nome, CPF ou contato de proprietário.

No zoom aproximado, o preenchimento dos imóveis é zero; o clique recorta a máscara para manter o imóvel escolhido em evidência. A fonte de restauração autorizada permaneceu vazia, como esperado no site aberto. **Estas capturas não demonstram hachura de restauração no mapa geral:** ali o contrato está preparado, mas a carga do recorte autorizado ainda não está ligada. A ficha paga existente consulta sua geometria pela API quando disponível, sem derivá-la do limite do CAR.

O painel distingue o resumo de aptidão disponível para **365 municípios em 9 estados** da cobertura cartográfica atual de **444 municípios em 13 estados**. A data própria dos resumos não está no pacote; essa ausência é informada, sem atribuir a eles a data do índice cartográfico. No Pará, ter dados nos 144 municípios não transforma automaticamente a classificação parcial do conjunto estadual em completa.

Os totais, a verificação de rede e os hashes dos sete PNGs estão em [snapshot.json](snapshot.json). Estas imagens registram aparência e comportamento; não são uma medição de Lighthouse nem substituem a validação do site publicado após o merge.
