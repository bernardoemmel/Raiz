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
