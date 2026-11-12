# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |
| Componente do globo (`cobe-globe.tsx`, `cobe-globe-demo.tsx`), copiado sem alterar | `front/globo/src/components/` | licença do autor a confirmar antes de publicar; a biblioteca `cobe` 2.0.1 é MIT | especificação "Cobe Globe — ProfitizeBuild"; https://github.com/shuding/cobe |

Dados públicos lidos pelo motor (cada um com seus termos): SICAR/SFB, Ibama, INPE TerraBrasilis (PRODES),
INCRA (SIGEF, quilombolas), FUNAI, MMA/CNUC (via geobr/Ipea), MapBiomas (cobertura, Fogo, Alerta), YbYrá-BR
(Source Cooperative), Global Pasture Watch (OpenGeoHub), JRC TMF v1.2025 (espelho COG na Source Cooperative,
epoch/jrc-tmf; dado do Joint Research Centre da Comissão Europeia, reempacotado sem alterar valores), causas da
perda de floresta WRI/Google DeepMind v1.2 (Zenodo 15366671, CC BY 4.0).

Dependências usadas sem copiar código: `i_overlay` (MIT/Apache-2.0) e `serde_json` (MIT/Apache-2.0) no teste `motor/iovbench/`.

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
| Fontes Familjen Grotesk, Atkinson Hyperlegible Next e IBM Plex Mono (@fontsource 5.3.0, só woff2 latino) | `front/globo`; o produtor usa só a Atkinson | SIL Open Font License 1.1 |
| Ícones Lucide (lucide-react e lucide-preact 1.62.0, importados um a um) | `front/globo`, `front/produtor` | ISC |

Gerados por `front/scripts/geo.py` e servidos junto (fora do git): recorte do mapa base do build diário do Protomaps,
com dados © colaboradores do OpenStreetMap (ODbL 1.0, atribuição no canto do mapa); letras dos rótulos Noto Sans
(SIL Open Font License 1.1) de protomaps/basemaps-assets; polígonos do CAR (SICAR/SFB) e camadas do INPE TerraBrasilis.

Métodos reescritos, sem copiar código: frases comparativas por índice no estilo do Census Reporter
(`front/compartilhado/comparacoes.ts`) e caixa de fatos no formato das "fact boxes" de comunicação de risco
(`front/compartilhado/cenario.ts`). Dependências só de desenvolvimento: Vite, TypeScript, Vitest, Oxlint (MIT) e,
no script, requests (Apache-2.0), shapely e pmtiles (BSD-3-Clause).
