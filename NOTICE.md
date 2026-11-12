# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |
| Contorno dos estados do Brasil (Natural Earth 1:50m, admin 1), projetado e simplificado para o minimapa em SVG | `front/compartilhado/brasil-estados.ts` (gerado por `front/scripts/geo.py`) | domínio público | https://www.naturalearthdata.com |

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
| Fontes Familjen Grotesk, Atkinson Hyperlegible Next e IBM Plex Mono (@fontsource 5.3.0, só woff2 latino) | `front/globo`; o produtor usa só a Atkinson | SIL Open Font License 1.1 |
| Ícones Lucide (lucide-react e lucide-preact 1.62.0, importados um a um) | `front/globo`, `front/produtor` | ISC |

Gerados por `front/scripts/geo.py` e servidos junto (fora do git): recorte do mapa base do build diário do Protomaps,
com dados © colaboradores do OpenStreetMap (ODbL 1.0, atribuição no canto do mapa); letras dos rótulos Noto Sans
(SIL Open Font License 1.1) de protomaps/basemaps-assets; polígonos do CAR (SICAR/SFB) e camadas do INPE TerraBrasilis,
inclusive o contorno dos 5.570 municípios da tela de entrada (camadas de municípios por bioma, juntadas pelo código
IBGE).

Removidos: o globo da abertura saiu do produto em novembro de 2026 (a tela de entrada passou a ser o mapa plano do
Brasil). Foram apagados a biblioteca `cobe` 2.0.1 (MIT) e os componentes `cobe-globe.tsx` e `cobe-globe-demo.tsx`
(especificação "Cobe Globe — ProfitizeBuild", https://github.com/shuding/cobe), que estavam em
`front/globo/src/components/`. Nenhum código deles ficou no front.

Métodos reescritos, sem copiar código: frases comparativas por índice no estilo do Census Reporter
(`front/compartilhado/comparacoes.ts`) e caixa de fatos no formato das "fact boxes" de comunicação de risco
(`front/compartilhado/cenario.ts`). Dependências só de desenvolvimento: Vite, TypeScript, Vitest, Oxlint (MIT) e,
no script, requests (Apache-2.0), shapely e pmtiles (BSD-3-Clause).

## Vigilância (`raiz/vigilancia/`)

Nenhum código de terceiros copiado. Dependências usadas sem alterar (instaladas por `raiz/vigilancia/requisitos.txt`,
todas no servidor ou no GitHub Actions): pandas, geopandas, shapely, pyproj (BSD-3-Clause), numpy (BSD-3-Clause),
pyarrow (Apache-2.0), requests (Apache-2.0), PyYAML (MIT), cryptography (Apache-2.0 ou BSD-3-Clause, cifra Fernet da
parte privada), FastAPI (MIT), uvicorn (BSD-3-Clause); nos testes, pytest (MIT) e httpx (BSD-3-Clause).

Dados lidos todo dia (cada um com seus termos; nenhum com licença não comercial):

| Fonte | Termos | Citação |
|---|---|---|
| NASA FIRMS, VIIRS 375 m NOAA-20 e NOAA-21 (VJ114IMGTDL_NRT, VJ214IMGTDL_NRT) | dado aberto da NASA, sem restrição de uso | "LANCE FIRMS, NASA EOSDIS" |
| MapBiomas Alerta (API v2, com conta) | CC BY 4.0 segundo os termos do Alerta (o site geral do MapBiomas cita CC BY-SA; conferir antes de redistribuir derivado) | "MapBiomas Alerta, plataforma.alerta.mapbiomas.org, acesso em <data>" |
| INPE TerraBrasilis: DETER (Amazônia e Cerrado) e PRODES (Amazônia Legal e Cerrado) | dado público do INPE | "INPE, TerraBrasilis" |
| Ibama, termos de embargo (dados abertos) | dado público; nome, CPF/CNPJ, nome do imóvel e textos livres são descartados na leitura | "Ibama, dados abertos" |

Estrutura do rascunho do relatório de perda: títulos das seções do Loss Event Report Template v5.0 da Verra
(modelo obrigatório para quem reporta perda ao VCS), preenchidos com texto próprio. Regra dos prazos: Verra,
Registration and Issuance Process v4.4, seção 5.3, e errata de 14/02/2023.
