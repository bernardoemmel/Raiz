# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Desenho do serviço de agentes: checkpointer aberto no início do serviço e retomada do grafo pelo thread_id quando há pausa pendente (reescrito, sem copiar código) | `raiz/api.py`, `raiz/agentes/memoria.py` | MIT, Copyright (c) 2024 Joshua Carroll | https://github.com/JoshuaC215/agent-service-toolkit |
| Leitura paginada do calendário de divulgação do IBGE (API v3, page/nextPage, tipo_id 1), reescrita sem polars | `raiz/coleta/ppm.py` | MIT, PYield | https://pypi.org/project/pyield/ |
| Desenho da fila de coleta: até 200 unidades por rodada, nova tentativa, disjuntor quando mais de 15% está sujo e reconciliação completa mensal (desenho, sem código copiado) | `raiz/coleta/fila.py` | MIT, osm-geoparquet (nfhl.py) | osm-geoparquet |
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |
| Componente do globo (`cobe-globe.tsx`, `cobe-globe-demo.tsx`), copiado sem alterar | `front/globo/src/components/` | licença do autor a confirmar antes de publicar; a biblioteca `cobe` 2.0.1 é MIT | especificação "Cobe Globe — ProfitizeBuild"; https://github.com/shuding/cobe |

Dados públicos lidos pelo motor (cada um com seus termos): SICAR/SFB, Ibama, INPE TerraBrasilis (PRODES),
INCRA (SIGEF, quilombolas), FUNAI, MMA/CNUC (via geobr/Ipea), MapBiomas (cobertura, Fogo, Alerta), YbYrá-BR
(Source Cooperative), Global Pasture Watch (OpenGeoHub), JRC TMF v1.2025 (espelho COG na Source Cooperative,
epoch/jrc-tmf; dado do Joint Research Centre da Comissão Europeia, reempacotado sem alterar valores), causas da
perda de floresta WRI/Google DeepMind v1.2 (Zenodo 15366671, CC BY 4.0).

Dependências usadas sem copiar código: `i_overlay` (MIT/Apache-2.0) e `serde_json` (MIT/Apache-2.0) no teste `motor/iovbench/`.

Extensão `nativo/raiz_iov` (Rust, sem código copiado): `i_overlay` (MIT/Apache-2.0), `pyo3` (MIT/Apache-2.0),
`numpy`/rust-numpy (BSD-2), `ndarray` (MIT/Apache-2.0), `rayon` (MIT/Apache-2.0). A conta da área segue o teste do
fundador em `motor/iovbench/` (EvenOdd, contorno externo menos buracos).

## Catala (compilador, runtime Python e biblioteca padrão)

- Origem: https://github.com/CatalaLang/catala, versão 1.3.0 (pacote `catala` do opam), Inria e contribuidores.
- Licença: Apache-2.0. Inclui o `dates.py` da biblioteca Dates_calc (Inria, Apache-2.0).
- Uso: `raiz/regras/gerado/` tem o runtime Python (`catala_runtime.py`, `dates.py`) e os módulos da biblioteca padrão
  gerados pelo compilador, copiados por `raiz regras gerar`. Mudança feita: os imports absolutos viraram relativos
  (`from catala_runtime import *` para `from .catala_runtime import *`, `import dates` para `from . import dates`),
  e cada arquivo gerado ganhou uma linha de cabeçalho dizendo de onde veio. As regras em `raiz/regras/catala/` são
  próprias da Raíz.

## Extensão spatial do DuckDB

- Origem: https://github.com/duckdb/duckdb-spatial (MIT), baixada de extensions.duckdb.org em tempo de execução, não
  copiada para o repositório. Usa GEOS (LGPL-2.1, como biblioteca), PROJ (MIT) e GDAL (MIT).

## Front (`front/`)

Distribuídas dentro do produto (vão no pacote que o navegador baixa), sem alterar o código:

| O quê | Onde | Licença |
|---|---|---|
| MapLibre GL JS 6.15.0 | `front/globo`, `front/produtor` (mapa) | BSD-3-Clause |
| PMTiles 4.5.0 (leitor em JS) | `front/globo`, `front/produtor` | BSD-3-Clause |
| @protomaps/basemaps 5.7.2 (camadas do mapa base) | `front/globo`, `front/produtor` | BSD-3-Clause |
| React 19, React DOM | `front/globo` | MIT |
| Preact 10.29.8 | `front/produtor` | MIT |
| cobe 2.0.1 | `front/globo` (globo da abertura) | MIT |
| Fonte Inter (@fontsource-variable/inter 5.3.0) | `front/globo` | SIL Open Font License 1.1 |

Gerados por `front/scripts/geo.py` e servidos junto (fora do git): recorte do mapa base do build diário do Protomaps,
com dados © colaboradores do OpenStreetMap (ODbL 1.0, atribuição no canto do mapa); letras dos rótulos Noto Sans
(SIL Open Font License 1.1) de protomaps/basemaps-assets; polígonos do CAR (SICAR/SFB) e camadas do INPE TerraBrasilis.

Métodos reescritos, sem copiar código: frases comparativas por índice no estilo do Census Reporter
(`front/compartilhado/comparacoes.ts`) e caixa de fatos no formato das "fact boxes" de comunicação de risco
(`front/compartilhado/cenario.ts`). Dependências só de desenvolvimento: Vite, TypeScript, Vitest, Oxlint (MIT) e,
no script, requests (Apache-2.0), shapely e pmtiles (BSD-3-Clause).

## OpenStreetMap pelos ladrilhos do Protomaps (cidades e estradas por imóvel)

- `raiz/osm.py` lê as camadas `places` e `roads` do build diário do Protomaps (build.protomaps.com, dados ©
  colaboradores do OpenStreetMap, ODbL 1.0) por faixa de bytes. As colunas derivadas (cidade_proxima,
  cidade_proxima_km, cidade_proxima_direcao, estrada_acesso, estrada_acesso_km) formam uma base derivada do OSM: quando
  publicadas, levam a atribuição "© colaboradores do OpenStreetMap" e seguem a ODbL (oferecer a base derivada sob a
  mesma licença). Bibliotecas: `pmtiles` (BSD-3) e `mapbox-vector-tile` (MIT), sem copiar código.

## Mapa base do Brasil (Protomaps)

- Recorte do build diário do Protomaps (build.protomaps.com), dados © colaboradores do OpenStreetMap (ODbL 1.0),
  feito com o `pmtiles extract` do go-pmtiles (BSD-3, instalado à parte, sem código copiado). Servido em
  /mapa/brasil.pmtiles com a atribuição do manifesto.
- Fontes Noto Sans (SIL Open Font License 1.1) e sprites do protomaps/basemaps-assets, baixados por
  `raiz mapa atualizar` (licença dos sprites a conferir no repositório basemaps-assets antes de publicar).

## Imagens de satélite por fazenda

- Sentinel-2 L2A: "Contains modified Copernicus Sentinel data [ano]" (licença Copernicus, uso livre inclusive
  comercial), COGs abertos na AWS achados pelo catálogo STAC Earth Search da Element 84. A frase vai em cada imagem
  (metadados.json, cabeçalho X-Raiz-Credito).
- Landsat 5 Collection 2 nível 2: domínio público, crédito "Landsat 5, cortesia do USGS", lido pelo Planetary
  Computer da Microsoft (token anônimo de leitura).
- Pillow (HPND) para WebP e desenho; fonte DejaVu Sans do sistema para o selo "Simulação". Nada de EOX, Esri, Planet
  NICFI, Google nem imagem gerada por IA.

## Cartão, adesivo e vídeo da fazenda

- Takumi (`@takumi-rs/core` e `@takumi-rs/helpers` 2.20.0, MIT ou Apache-2.0) em `servicos/cartao/render.mjs`, com a
  fonte Geist que vem embutida (SIL Open Font License). Sem código copiado.
- FFmpeg (GPL, pacote do sistema) só como processo separado no servidor, para juntar as cenas e o áudio em MP4; não
  vai no produto distribuído.
- Voz: Qwen3-TTS (`qwen-tts`, Apache-2.0) quando instalado no servidor (raiz/voz.py).

## Valor para quem restaura (relevo, chuva, solo e vegetação secundária)

Usados como dado de entrada no servidor (raiz/restauracao_geo.py), com cache em disco; nada disso é distribuído
junto do produto.

- **Copernicus DEM GLO-30** (AWS Open Data, `copernicus-dem-30m`): licença de uso gratuito, mundial, inclusive
  comercial, pedindo que se informe a origem. Crédito: "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014
  and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights
  reserved". A Raíz guarda só a declividade derivada.
- **CHIRPS v3** (Climate Hazards Center, UC Santa Barbara): domínio público (renúncia de direitos registrada no
  Creative Commons). Citação pedida: CHIRPS3 Data Repository, doi:10.15780/G2JQ0P.
- **SoilGrids 2.0** (ISRIC World Soil Information): CC BY 4.0. Crédito: "SoilGrids 2.0, ISRIC World Soil
  Information" (Poggio et al. 2021, SOIL 7:217).
- **YbYrá-BR v8.1** (Source Cooperative): idade da vegetação secundária, já usada pelo motor; aqui só para medir a
  linha de base do município.
- **Heinrich et al. 2021** (CC BY-NC): só a taxa que o motor já usa, para comparação; fora de qualquer treino.

## Caminho da terra e terra pública para restaurar

Usados como dado de entrada no servidor (raiz/terra.py, raiz/terra_publica.py); nada é distribuído com o produto.

- **Cadastro Nacional de Florestas Públicas 2025** (Serviço Florestal Brasileiro, Lei 11.284/2006): dado público
  oficial, baixado do portal mapas.florestal.gov.br (item CNFP_2025.zip); o portal não declara licença. Crédito:
  "Cadastro Nacional de Florestas Públicas, Serviço Florestal Brasileiro, atualização 2025".
- **SIGEF** (INCRA): natureza e estado de cada parcela, do espelho que a Raíz já mantém.
- **CNUC** (MMA), **terras indígenas** (FUNAI) e **quilombos** (INCRA): os mesmos arquivos do cache do motor.
- **Editais e contratos de concessão**: páginas públicas do SFB (gov.br/florestal) e do Ideflor-Bio
  (ideflorbio.pa.gov.br), guardadas como link e data em raiz/regras/padroes/concessoes.yaml.

## Lista dos municípios brasileiros (executor do motor)

`raiz/executor/municipios.csv` (código do IBGE, nome e UF dos 5.571 municípios) vem de
github.com/kelvins/municipios-brasileiros, licença MIT, Copyright (c) 2016 Kelvin S. do Prado. Só as três colunas.

## Armazenamento compatível com S3

boto3 e botocore (Apache-2.0) no produto; moto (Apache-2.0) só nos testes. Servidor próprio, quando não se usa o
Cloudflare R2: SeaweedFS (Apache-2.0). MinIO e Garage ficam de fora (AGPL).
