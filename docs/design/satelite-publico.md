# Satélite no mapa público

O fundo de aproximação usa o mosaico **histórico Sentinel-2 2016/2017**, vintage EOxCloudless 2016,
resolução de 10 m. O ano aparece no mapa: essa imagem ajuda a localizar o imóvel, mas não comprova o uso
atual da terra. A imagem recente da ficha continua sendo produzida pelo serviço autorizado com Sentinel-2 L2A.

## Licença conferida em 12/11/2026

- A [licença por ano da EOX](https://cloudless.eox.at/license-non-commercial) declara **CC BY 4.0** para 2016
  e identifica a composição com cenas de 2016 e 2017. O mesmo texto reserva 2018–2025 ao uso não comercial.
- O [FAQ oficial](https://cloudless.eox.at/documentation/faq) permite que aplicações comerciais incorporem
  a camada de 2016 e usem seu endpoint público com atribuição e tráfego razoável, sem garantia de disponibilidade.
- O [WMTS Capabilities](https://tiles.maps.eox.at/wmts/1.0.0/WMTSCapabilities.xml) identifica exatamente
  `s2cloudless_3857` como a camada de 2016 e informa CC BY 4.0. Não se usa um alias de “último ano”.
- Crédito completo, com links, acompanha a imagem e precisa permanecer nas capturas e demais exportações.
  A autorização não cobre redistribuir o mosaico bruto como produto GIS separado.

## Renderização e falhas

`satelite-publico.ts` contém o ano, a atribuição, as URLs e o dia da conferência. O raster só é solicitado em
z12 ou mais próximo, com blocos de 256 px e apenas para o enquadramento visível. O overzoom a partir de z14
evita sugerir resolução maior do que os 10 m de origem. A aplicação não baixa estados inteiros nem faz prefetch.

Um véu claro de 30% e leve dessaturação deixam os dados legíveis. O raster e o véu ficam abaixo dos contornos
e dos rótulos. Falha da fonte retira ambas as camadas e mantém a base vetorial; a interface avisa que o satélite
está indisponível. Não troca silenciosamente por uma fonte com licença diferente.

O tile real de Parauapebas `12/2117/1480.jpg` respondeu 200, `image/jpeg`, com 19.386 bytes e CORS `*` na
conferência. Este tamanho é uma observação daquele tile, não um limite geral. O teste automatizado cobre o
vintage fixo, o limiar de zoom, o overzoom, a atribuição e o retorno à base após erro.

A prova no Chromium usou a fonte real em 1440, 768 e 360 px: nenhum pedido de satélite no zoom 10,
24 respostas 200 após aproximar para z13, atribuição visível, nenhum 404, nenhum erro de JavaScript e nenhuma
rolagem horizontal. A variação dos pixels também foi conferida para não aceitar um fundo liso como satélite.
