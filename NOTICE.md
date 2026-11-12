# Código e dados de terceiros

| O quê | Onde é usado | Licença | Origem |
|---|---|---|---|
| Desenho do serviço de agentes: checkpointer aberto no início do serviço e retomada do grafo pelo thread_id quando há pausa pendente (reescrito, sem copiar código) | `raiz/api.py`, `raiz/agentes/memoria.py` | MIT, Copyright (c) 2024 Joshua Carroll | https://github.com/JoshuaC215/agent-service-toolkit |
| Leitura paginada do calendário de divulgação do IBGE (API v3, page/nextPage, tipo_id 1), reescrita sem polars | `raiz/coleta/ppm.py` | MIT, PYield | https://pypi.org/project/pyield/ |
| Desenho da fila de coleta: até 200 unidades por rodada, nova tentativa, disjuntor quando mais de 15% está sujo e reconciliação completa mensal (desenho, sem código copiado) | `raiz/coleta/fila.py` | MIT, osm-geoparquet (nfhl.py) | osm-geoparquet |
| Regras da escadinha do art. 61-A (`faixa_rio_consolidada`) e do teto do art. 61-B (`limite_61b`), reescritas | `motor/raiz_estado.py`, `motor/raiz_app.py` | MIT, Copyright (c) 2022 GeoOne | https://github.com/OpenGeoOne/GeoCAR |
| Contorno dos estados do Brasil (Natural Earth 1:50m, admin 1), projetado e simplificado para o minimapa em SVG | `front/compartilhado/brasil-estados.ts` (gerado por `front/scripts/geo.py`) | domínio público | https://www.naturalearthdata.com |
| Contagem de letras, palavras, sílabas e frases e as fórmulas do ALT (Análise de Legibilidade Textual: Flesch, Flesch-Kincaid, Gunning Fog, ARI, Coleman-Liau, Gulpease e o resultado), copiadas do alt-python 0.1.2 sem a leitura de PDF e Word; a lista de palavras comuns da Linguateca não foi copiada (sem licença clara). As fórmulas de Martins et al. (1996, NILC-USP) e a do LanguageTool para o português (LGPL; só os coeficientes, sem código) foram reimplementadas | `raiz/legibilidade.py` | MIT, Copyright (c) 2025 Marco Polo Moreno de Souza | https://github.com/marcopolomoreno/alt-python |
| ThumbHash: codificador e decodificador (rgbaToThumbHash e thumbHashToRGBA) portados para Python, com o arredondamento do JavaScript para o hash sair igual ao do pacote npm | `raiz/thumbhash.py` | MIT, Copyright (c) 2023 Evan Wallace | https://github.com/evanw/thumbhash |
| Link curto do Organic Maps (formato ge0: zoom e coordenada em 10 caracteres, nome com %XX), reimplementado a partir de libs/ge0/url_generator.cpp e conferido com os casos de teste dele; Plus Code pela especificação aberta do Open Location Code | `raiz/localizacao.py` | Apache-2.0 (Organic Maps; Open Location Code) | https://github.com/organicmaps/organicmaps e https://github.com/google/open-location-code |
| Códigos dos 5.571 municípios por estado (IBGE, Divisão Territorial Brasileira 2025, data base 31/12/2025), só os códigos | `front/compartilhado/ibge-municipios.ts` (gerado por `front/scripts/geo.py`) | dado público do IBGE, uso livre com citação da fonte | https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/divisao_territorial/ |

Dados públicos lidos pelo motor e pelo produto (cada um com seus termos): IBGE (Pesquisa da Pecuária Municipal, SIDRA 3939, e Censo Agro 2017, SIDRA 6899, 6753, 6881 e 6910), SICAR/SFB, Ibama, INPE TerraBrasilis (PRODES),
INCRA (SIGEF, quilombolas), FUNAI, MMA/CNUC (via geobr/Ipea), MapBiomas (cobertura, Fogo, Alerta), YbYrá-BR
(Source Cooperative), Global Pasture Watch (OpenGeoHub), JRC TMF v1.2025 (espelho COG na Source Cooperative,
epoch/jrc-tmf; dado do Joint Research Centre da Comissão Europeia, reempacotado sem alterar valores), causas da
perda de floresta WRI/Google DeepMind v1.2 (Zenodo 15366671, CC BY 4.0). MapBiomas Alerta lido pelo WFS público da
plataforma (maps.alerta.mapbiomas.org, camada dashboard-alert-shapefile, só alertas publicados). Lista de municípios
do IBGE em CSV de https://github.com/kelvins/municipios-brasileiros (MIT), baixada para o cache, sem copiar código.

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

## LanguageTool (revisor de estilo, só no servidor)

- Origem: https://languagetool.org, versão 6.6, baixada pelo `infra/languagetool/Dockerfile` ao montar o contêiner.
- Licença: LGPL-2.1 ou posterior. Roda só como serviço separado no servidor (`revisor` em `infra/docker-compose.yml`);
  nenhum código dele é copiado para o produto. `raiz/revisor.py` só chama a API HTTP dele.

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
| Fontes Familjen Grotesk, Atkinson Hyperlegible Next e IBM Plex Mono (@fontsource 5.3.0, só woff2 latino) | `front/globo`; o produtor usa só a Atkinson | SIL Open Font License 1.1 |
| Ícones Lucide (lucide-react e lucide-preact 1.62.0, importados um a um) | `front/globo`, `front/produtor` | ISC |
| Radix Primitives: @radix-ui/react-tabs 1.2.1 e @radix-ui/react-dialog 1.3.1 (abas das opções do lote e janela do Pix; e as dependências deles: aria-hidden, react-remove-scroll, use-callback-ref, use-sidecar, get-nonce, detect-node-es, MIT; tslib, 0BSD) | `front/globo` | MIT |
| NumberFlow (@number-flow/react 0.6.2 e number-flow, esm-env) nos números do andamento | `front/globo` | MIT |
| uqr 0.1.3 (código QR do Pix em SVG) | `front/globo` | MIT |
| thumbhash 0.1.1 (borrão da capa enquanto a foto de satélite chega) | `front/produtor` | MIT |

Gerados por `front/scripts/geo.py` e servidos junto (fora do git): recorte do mapa base do build diário do Protomaps,
com dados © colaboradores do OpenStreetMap (ODbL 1.0, atribuição no canto do mapa); letras dos rótulos Noto Sans
(SIL Open Font License 1.1) de protomaps/basemaps-assets; polígonos do CAR (SICAR/SFB) e camadas do INPE TerraBrasilis,
inclusive o contorno dos 5.570 municípios da tela de entrada (camadas de municípios por bioma, juntadas pelo código
IBGE) e o dos 27 estados (os mesmos municípios juntados por estado).

Removidos: o globo da abertura saiu do produto em novembro de 2026 (a tela de entrada passou a ser o mapa plano do
Brasil). Foram apagados a biblioteca `cobe` 2.0.1 (MIT) e os componentes `cobe-globe.tsx` e `cobe-globe-demo.tsx`
(especificação "Cobe Globe — ProfitizeBuild", https://github.com/shuding/cobe), que estavam em
`front/globo/src/components/`. Nenhum código deles ficou no front.

Métodos reescritos, sem copiar código: frases comparativas por índice no estilo do Census Reporter
(`front/compartilhado/comparacoes.ts`) e caixa de fatos no formato das "fact boxes" de comunicação de risco
(`front/compartilhado/cenario.ts`). Dependências só de desenvolvimento: Vite, TypeScript, Vitest, Oxlint (MIT) e,
no script, requests (Apache-2.0), shapely e pmtiles (BSD-3-Clause). Teste do site estático no Chromium:
Playwright 1.65.0 (Apache-2.0) e pngjs 7.0.0 (MIT), usados como bibliotecas, sem código copiado. Auditoria
Agentic Browsing: Lighthouse 13.6.0 (Apache-2.0), somente no desenvolvimento/CI. O arquivo llms.txt segue a
proposta do llmstxt.org; JSON-LD usa o vocabulário schema.org, sem copiar código de implementação.

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
github.com/kelvins/municipios-brasileiros, licença MIT, Copyright (c) 2016 Kelvin S. do Prado. Só as colunas de
código, nome, UF, latitude e longitude da sede (o pedido de lote põe na sede a fazenda que ainda não tem contorno).

## Otimizador do pedido de lote

`raiz/pedidos/otimizador.py` escolhe as fazendas com o HiGHS (MIT, Copyright (c) 2016-2025 Julian Hall, Ivet Galabova,
Leona Gottwald e Michael Feldmeier; https://highs.dev), pelo `scipy.optimize.milp` do SciPy (BSD-3-Clause), que traz o
HiGHS dentro. Sem código copiado. A cobrança Pix da reserva usa a API da AbacatePay (serviço, sem SDK; só HTTP).

## Lote do ProFloresta+ unificado com a branch claude/premissas-rodada11

- Origem: branch `claude/premissas-rodada11` deste mesmo repositório (outra sessão de trabalho da Raíz, sem PR):
  `raiz/desenvolvedor.py`, `raiz/desenvolvedor_lote.py`, `raiz/desenvolvedor_relatorio.py`, `raiz/restauracao.py`
  (vazamento por fazenda vizinha), `raiz/regras/padroes/edital_profloresta.yaml` e
  `motor/premissas/restauracao_v2026_11.yaml`. Mesmo dono e mesma licença do produto; nada de terceiros.
- Uso: `raiz/lote.py` (montagem por custo, reserva pela chance alvo, checagens do edital), `raiz/lote_relatorio.py`
  (CSS, leque em SVG, relatório do lote e folha do dono), `raiz/vazamento.py` (VMD0054 por vizinha),
  `raiz/restauracao.py` (`cronograma_lote`, `contrato_para_marcos`, `fator_captura_alvo`, curva oficial da URTX, teto
  por bioma, P10/P90 de custo publicados) e `raiz/regras/padroes/edital_profloresta.yaml` (copiado; o cabeçalho aponta
  para `raiz/lote.py`). As premissas foram juntadas num só arquivo, `raiz/regras/padroes/restauracao.yaml`, e o
  cálculo num só motor: a escolha das fazendas passou a ser o otimizador dos pedidos e o fluxo do lote a soma dos
  fluxos do P50 das fazendas.
- Fontes dos números (cada uma citada no YAML): IDEFLOR-Bio (URTX, Anexo 20), BNDES (minuta e especificação técnica
  do ProFloresta+), SFB (Bom Futuro e Altamira), Systemica/B3, Instituto Escolhas, Inesc, IBGE (Censo Agro 2017,
  SIDRA 6899, 6753, 6910 e 6881), Banco Central (IPCA, série 433; PTAX), CNA (Campo Futuro), Verra (VM0047, VMD0054,
  VCS v5.0).

## Armazenamento compatível com S3

boto3 e botocore (Apache-2.0) no produto; moto (Apache-2.0) só nos testes. Servidor próprio, quando não se usa o
Cloudflare R2: SeaweedFS (Apache-2.0). MinIO e Garage ficam de fora (AGPL).

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
| reportlab | PDF privado da ficha da fazenda e PDF de exemplo dos testes | BSD |

Programas e serviços chamados de fora, sem embutir código: LibreOffice (MPL-2.0) converte .docx em PDF no servidor;
Firecrawl só pela API hospedada (o código do Firecrawl é AGPL: não instalar nem hospedar). Fontes públicas da busca
semanal, cada uma com seus termos: registro da Verra (VCS), portal gov.br do Serviço Florestal Brasileiro (API do
Plone), páginas de licitações e concessões do Ideflor-Bio e busca do Diário Oficial da União (in.gov.br).

Métodos reescritos, sem copiar código: cadeia dominial com quebras e ônus ativos (desenho do TitleChain citado no plano,
E5 passo 7); normal de dois lados nos P10, P50 e P90 e soma ao lado da carteira (E3); regra provisória das faixas
(faixas-2026a) igual à do back-end (`raiz/regras/padroes/faixas.yaml`).

## Título (`raiz/titulo/`)

Nenhum código de terceiros copiado. Geodésia pelo `pyproj.Geod` (MIT, já dependência do geopandas), o mesmo cálculo do
GeographicLib; regra da bússola (Bowditch) e escala D1 a D7 escritas pela Raíz. Gerador de memorial próprio: o
LFTools e o GeoPlanta (plugins do QGIS) são GPL e não entram no produto. Planilha ODS lida com `zipfile` e
`xml.etree` da biblioteca padrão. Desenhos seguidos, sem código: tabela de achados no formato do CFPB, reprova contra
confirmar do HMDA, N/A do Pelican, nota com bandeiras do Collateral Underwriter e decisão em quatro saídas da
subscrição de seguro. Tolerâncias de georreferenciamento do INCRA (0,50 m artificial e 3,00 m natural, como em
estudo do próprio INCRA; 7,50 m inacessível). Base legal da regularização da posse em
`raiz/regras/padroes/regularizacao.yaml`, com a marca do que o jurídico ainda não conferiu.

## Aprendizado no formato do hub (`raiz/aprendizado/hub.py`, `raiz/aprendizado/acerto.py`)

Nenhum código copiado. O formato das pastas e arquivos segue a documentação do hubverse (hubverse-org/hubDocs, esquemas
v6.0.0 em hubverse-org/schemas) para que hubData, hubEvals, hubPredEvalsData e o hub-dashboard leiam as previsões da
Raíz. A configuração do painel (site-config.yml, predevals-config.yml, predtimechart-config.yml) segue o molde do
reichlab/flusight-dashboard, que é CC0 1.0. O WIS foi escrito a partir da fórmula de Bracher et al. (2021, PLOS
Computational Biology 17(2): e1008618).

## Modelo local com llguidance e cascata por confiança (`infra/llama/Dockerfile`, `raiz/modelos/`)

O servidor do modelo local é o llama.cpp (ggml-org/llama.cpp, licença MIT) compilado com o llguidance
(guidance-ai/llguidance, licença MIT), que entra pela construção do próprio llama.cpp (LLAMA_LLGUIDANCE=ON). Roda
como serviço no servidor; nada dele é embutido no produto distribuído. O `infra/llama/Dockerfile` segue o molde do
`.devops/cpu.Dockerfile` do llama.cpp (MIT, Copyright (c) 2023-2026 The ggml authors), sem a interface web. A
confiança dos logprobs, a calibração do corte e o banco de tarefas em português foram escritos para a Raíz, sem
código copiado.

## Sanitização de logs (`raiz/logs_seguros.py`)

Microsoft Presidio Analyzer e Anonymizer ([microsoft/presidio](https://github.com/microsoft/presidio), MIT) são usados
como bibliotecas, sem código copiado. O reconhecimento de nomes em português usa spaCy (MIT) e o modelo
[pt_core_news_sm 3.8.0](https://github.com/explosion/spacy-models/releases/tag/pt_core_news_sm-3.8.0), da Explosion,
licença **CC BY-SA 4.0**, sem alterações. A atribuição e as licenças das fontes UD Portuguese Bosque e WikiNER
acompanham o pacote em `LICENSES_SOURCES`; a ficha do modelo está em <https://spacy.io/models/pt#pt_core_news_sm>.
O modelo roda só no servidor, instalado do Release oficial com hash no `uv.lock`.

## Ferramentas de qualidade e segurança

Gitleaks 8.24.3 (MIT, https://github.com/gitleaks/gitleaks) e actionlint 1.7.7
(MIT, https://github.com/rhysd/actionlint) verificam o repositório no CI. Playwright 1.65.0
(Apache-2.0, https://github.com/microsoft/playwright) executa o navegador de teste. Usados como ferramentas,
sem código-fonte copiado para o produto.

## Lighthouse e SDK de telemetria

Lighthouse **13.6.0** ([GoogleChrome/lighthouse](https://github.com/GoogleChrome/lighthouse), Apache-2.0) mantém
as auditorias Agentic Browsing. Seu SDK transitivo de telemetria é fixado, por `overrides` somente na árvore do
Lighthouse, em **@sentry/node 10.78.0** ([getsentry/sentry-javascript](https://github.com/getsentry/sentry-javascript),
MIT). Nenhum código desses pacotes foi copiado ou substituído.

A série 11.x solicitada pelo Lighthouse traz `@sentry/bundler-plugins` e a CLI `sentry` sob FSL, licença restritiva
que não é aceita pelo projeto. A versão 10.78.0 evita essa dependência e mantém as APIs de telemetria usadas por
`core/lib/sentry.js`: inicialização, tags, contexto, breadcrumbs, mensagens e exceções. O pin fica fora da faixa
original do Lighthouse; sua compatibilidade é verificada com o teste de agentes e com eventos de telemetria
capturados em transporte local, sem envio ao Sentry. Ao atualizar o Lighthouse ou esse pin, repetir essas
verificações e a checagem integral de licenças; não liberar FSL nem instalar a CLI como exceção.
