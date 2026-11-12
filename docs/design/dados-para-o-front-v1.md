# Dados e imagens para o front, v1

Dados e imagens que o back-end e o motor precisam entregar para o redesenho do front (pesquisa de design, rodada 1). O guia do front está em docs/design/guia-front-v1.md. Ler colunas pelo nome (docs/colunas.md) e documentar cada coluna nova lá. Nada de nome ou CPF em imagem, arquivo ou log.

1. IMAGEM DE SATÉLITE POR FAZENDA (gerada no servidor, guardada em cache)
1.1 Fonte: Copernicus Sentinel-2 L2A em COG aberto (catálogo STAC Earth Search da Element 84 na AWS, coleção sentinel-2-l2a). Licença Copernicus: uso livre, inclusive comercial, com o crédito "Contains modified Copernicus Sentinel data [ano]". Não usar EOX cloudless 2018 a 2024, Esri, Planet NICFI nem Google.
1.2 Para cada imóvel: cena mais recente (até 3 meses) sem nuvem sobre o imóvel (máscara SCL), ou mediana das cenas limpas do trimestre; cor natural (B4, B3, B2) levemente dessaturada; recorte com margem de 15% em volta do imóvel.
1.3 Saídas em WebP:
- ficha da fazenda: 1024 px, abaixo de 150 KB, sem desenho (o front desenha contorno e camadas por cima);
- ficha do produtor e cartão: 720 px com o contorno já desenhado na imagem (branco 3 px com borda escura 1 px), entorno escurecido a 45% e a área que pode voltar a ser mata em hachura diagonal, 40 a 80 KB;
- par do antes e depois para o celular: 480 px "hoje" e 480 px "simulação em 10 anos" (a área restaurável pintada com textura de copa e o selo "Simulação" escrito na imagem); nunca foto realista gerada por IA;
- passado: o mesmo recorte em Landsat (domínio público, crédito USGS) para 1985 e 2008, e Sentinel-2 para hoje.
1.4 Gravar com cada imagem: data da cena, satélite e a frase de crédito. Ferramentas: rasterio ou rio-tiler para ler o COG, sharp ou Pillow para WebP, skia-canvas ou Pillow para desenhar contorno e hachura.

2. CAMADAS DENTRO DO IMÓVEL (vetor simplificado, para o mapa e para os desenhos)
Por imóvel, a partir do MapBiomas que o motor já lê: polígonos de mata em pé, área que pode voltar a ser mata (a mesma área que o motor conta como restaurável), pasto, lavoura, água e APP, simplificados para pesar poucos KB, servidos em GeoJSON por imóvel e em PMTiles por município.

3. COLUNAS NOVAS POR IMÓVEL
- cidade_proxima, cidade_proxima_km, cidade_proxima_direcao (N, NE, ...), estrada_acesso (nome ou código da via mais próxima, do OpenStreetMap);
- porte (pequeno, médio, grande, por módulos fiscais);
- etapa_funil (última etapa que alcançou) e motivo_saida (um motivo exclusivo, o primeiro que tirou o imóvel);
- nivel_selo (bronze = achada no CAR, prata = título conferido, ouro = dono aceitou);
- faixas P10, P50 e P90 do carbono por ano e da receita por ano, com a regra escrita;
- composição da área em ha: mata_em_pe, pasto, para_restaurar, agua, sem_dado (somando a área do imóvel);
- serie_uso: porcentagem de mata, pasto, lavoura e água por ano, de 1985 até hoje (MapBiomas pela API, no máximo 20 anos por pedido);
- criterios_aptidao: lista fixa e sempre na mesma ordem, com situação (ok, falta, não se aplica), grupo ("decide" ou "só informa"), fonte e data de cada item;
- o que conta na meta FLAG (silvipastoril, cacau) separado do que vai para crédito Verra ou compensação;
- codigo_curto (6 a 8 caracteres, sem relação com o CAR) para o link público e o cartão.

4. POR MUNICÍPIO
- frase-resumo pronta (com tratamento de dado faltando);
- contorno da área urbana da sede (MapBiomas área urbanizada) para a comparação de tamanho;
- funil por etapa e por porte, em imóveis e em hectares, com os 3 maiores motivos de saída por etapa;
- "desde a última análise": quantos imóveis subiram e quantos desceram de etapa (guardar a foto de cada rodada com a versão do motor).

5. MAPA BASE
Recorte do Brasil do build diário do Protomaps (pmtiles extract, até o zoom 14), servido pela Raíz com resposta a Range, mais fontes e sprites do protomaps/basemaps-assets. Crédito OpenStreetMap. Rios e estradas vêm daqui, não da Base Cartográfica do IBGE (que veda uso comercial).

6. ROTAS NOVAS
- GET /imoveis/{cod}/imagem/{hoje|hoje-produtor|simulacao|1985|2008}.webp
- GET /imoveis/{cod}/camadas.geojson
- GET /cartao/{codigo_curto}/{previa|retrato|adesivo}.(jpg|png): prévia 1200 x 630 abaixo de 250 KB, retrato 1080 x 1350, adesivo PNG transparente abaixo de 300 KB, gerados com o Takumi;
- GET /video/{codigo_curto}.mp4 (e versão 720p), gerado com Takumi renderAnimation + FFmpeg no servidor + voz Qwen3-TTS;
- GET /p/{codigo_curto}: ficha do produtor em HTML pronto no servidor (até 150 KB na primeira tela), com Open Graph do WhatsApp.
O cartão e o link público mostram só município, hectares, selo e código curto; nome do imóvel, código do CAR e polígono exato só depois do aceite do dono.

7. ORDEM
1) Colunas e camadas dentro do imóvel (itens 2 e 3); 2) mapa base Protomaps (item 5); 3) satélite por fazenda (item 1); 4) rotas (item 6); 5) dados do município (item 4). Testes automáticos para cada rota e para o peso das imagens.
