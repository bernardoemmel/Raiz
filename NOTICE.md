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

## Documentos (`raiz/documentos/`)

Dependências usadas como biblioteca, sem copiar nem alterar o código (`raiz/documentos/requirements.txt`):

| O quê | Para quê | Licença |
|---|---|---|
| anthropic (SDK Python) | leitura de certidão e edital pela API da Anthropic | Apache-2.0 |
| docxtpl | modelos .docx com campos Jinja (usado como biblioteca, sem alteração) | LGPL-2.1 |
| python-docx | monta os modelos .docx | MIT |
| Jinja2 (dependência do docxtpl) | campos dos modelos | BSD-3-Clause |
| pypdf | conta páginas do PDF | BSD-3-Clause |
| beautifulsoup4 | links das páginas de editais | MIT |
| requests | páginas e APIs públicas | Apache-2.0 |
| pandas, numpy | tabelas do motor e faixa P10 a P90 da carteira | BSD-3-Clause |
| reportlab | PDF de exemplo dos testes | BSD |

Programas e serviços chamados de fora, sem embutir código: LibreOffice (MPL-2.0) converte .docx em PDF no servidor;
Firecrawl só pela API hospedada (o código do Firecrawl é AGPL: não instalar nem hospedar). Fontes públicas da busca
semanal, cada uma com seus termos: registro da Verra (VCS), portal gov.br do Serviço Florestal Brasileiro (API do
Plone), páginas de licitações e concessões do Ideflor-Bio e busca do Diário Oficial da União (in.gov.br).

Métodos reescritos, sem copiar código: cadeia dominial com quebras e ônus ativos (desenho do TitleChain citado no plano,
E5 passo 7); normal de dois lados nos P10, P50 e P90 e soma ao lado da carteira (E3); regra provisória das faixas
(faixas-2026a) igual à do back-end (`raiz/regras/padroes/faixas.yaml`).

