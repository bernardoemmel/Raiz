# Arquitetura da Raíz

Aprovada pelo fundador em 12/11/2026, com os ajustes das rodadas 8 e 9 de pesquisa. Ordem de construção: `plano-por-etapa.md`.

## Princípios

- **O motor (`motor/`) não é reescrito.** O produto lê as saídas dele pelo nome das colunas (`colunas.md`) e tolera
  colunas novas. Mudança dentro de `motor/` só se for acréscimo de coluna e com ok do fundador.
- **Caminho novo ao lado do motor.** Cruzamentos mais rápidos (iOverlay, rusterize + bincount, DuckDB) nascem como
  módulos novos e são comparados com o motor nos imóveis de teste. O motor é a referência até o novo dar o mesmo
  resultado em menos tempo.
- **Toda previsão é congelada** (código do CAR, data de corte, horizonte, versão do modelo e das entradas, hash do
  lote) e comparada com o gabarito quando ele chega. É assim que a Raíz aprende com os próprios acertos e erros.
- **Modelo de linguagem lê e conversa; código decide.** Número, elegibilidade e nota saem de código determinístico e
  versionado. No começo, toda mensagem para fora passa pela aprovação do fundador.
- **Pequenas se agrupam.** Nenhuma fazenda é descartada por tamanho; grupo de fazendas é entidade própria no banco.
- **Privacidade.** CPF e CNPJ sempre mascarados; nome e CPF nunca em log, treino ou repositório. Dado pessoal
  necessário à operação (telefone, BSUID do WhatsApp) fica cifrado no esquema `pessoal`.
- **Licenças.** Proibidas AGPL, EUPL, SSPL, BSL e não comercial (NC). GPL só em serviço no servidor. Uma checagem
  automática derruba o build se aparecer licença proibida. Dado com licença NC (ex.: Heinrich 2021) só serve para
  comparação, nunca para treino.

## Fluxo

```
fontes públicas ─► COLETA (E1) ─► PostGIS "bruto" (histórico scd2) + espelho Parquet por município (R2)
                     manifesto, sinal de mudança, ETag, cursor, fila nfhl
                        │
                        ▼
                  FUNIL (E2) = motor/ por município + regras legais versionadas
                        │     (ponte: CAR e SIGEF lidos da coleta local, sem editar o motor)
                        ▼
      resultado por imóvel ─► carbono e dinheiro (E3) · rebanho, metano, solo (E4)
                        │      título e geolocalização (E5) · quem compra (E6)
                        ▼
      PREVISÕES CONGELADAS (aprendizado.previsao)  ◄────────────────────────────┐
                        │                                                       │ E8
                        ▼                                                       │
      API ─► telas e agentes ─► aceite, venda, certidão = gabarito ─────────────┘
      OPERAÇÃO (E7): Healthchecks por lote, Langfuse por tarefa e fazenda, backoffice
```

## Banco: PostgreSQL 16 + PostGIS

PostGIS é GPL e roda só no servidor. Um esquema por assunto:

| Esquema | O que guarda |
|---|---|
| `coleta` | manifesto de camadas, replicação (fonte, recorte, cursor, etag, contagem, atualizado_em), calendário, checagens HTTP, fila |
| `bruto` | o que a coleta traz (CAR, SIGEF, embargos, PRODES, DETER...), histórico scd2 e views da versão vigente; Ibama entra sem nome e CPF/CNPJ |
| `funil` | imóvel (código do CAR, geometria), rodada (versão do motor, das regras, hash das entradas), resultado por imóvel |
| `regras` | parâmetros legais com vigência, artigo, URN do LexML e link arquivado |
| `titulo` | registro (CAR + SIGEF + matrícula + CNS), achados (formato CFPB), laudo, cadeia dominial, confirmações |
| `negocio` | grupos de fazendas pequenas, compradores, casamentos fazenda↔comprador, aceites |
| `aprendizado` | previsões congeladas, gabaritos e a visão única previsão contra gabarito |
| `pessoal` | telefone e BSUID do WhatsApp, cifrados, acesso restrito; nunca em log, exportação ou treino |
| `operacao` | lotes, custo por tarefa e por fazenda, alertas |

Colunas conhecidas do contrato viram colunas tipadas (nome em minúsculas). Colunas que o motor criar depois vão para
o campo `atributos` (JSON) da mesma linha: coluna nova nunca quebra a carga, e a carga avisa quais são novas.

Raster e camadas grandes ficam fora do banco: espelho em Parquet **por município** (nunca um arquivo único: com 1% dos
imóveis mudando, um arquivo único regrava 99,9% dos bytes), COG e Zarr, no R2. Hash por imóvel com `hash()` do
DuckDB e gravação com `MERGE INTO ... RETURNING` (DuckDB 1.4).

## Coleta (E1)

- dlt para WFS do GeoServer (SICAR, TerraBrasilis, `geonode:sigef_geo`), ArcGIS REST (Ibama, SFB, IPAAM, ANA) e
  HTTP condicional (CSV do Ibama).
- MapBiomas sem Earth Engine, pela API da Plataforma (`prd.plataforma.mapbiomas.org/api/v1/brazil`, cabeçalho
  `tenant-id: mapbiomas`, sem login): município = categoria 230 (id em `/territories/search/<nome>`);
  `POST /maps/exports` com `territoryId`, `subthemeKey` e `years`; `GET /maps/exports/{id}` até `READY`;
  `GET /maps/exports/{id}/download` devolve ZIP com GeoTIFF. Chaves: `coverage_coverage-30m-droufo`,
  `secondary-vegetation-copy-t41ydh_annual-lfh76u_age`, `pastagem-copia-0dzt61_*`, `fogo-copia-1h7mac_monthly-433exq`,
  `desmatamento-copia-12xxov_annual-c5i7xj`.
- SIGEF: `certificacao.incra.gov.br` fora do ar; usar o WFS `geonode:sigef_geo` e o espelho GeoOne/incra-brasil,
  conferindo sha256.
- SIGMINE: `dadosabertos.anm.gov.br`.
- Fila no molde do `nfhl.py` (osm-geoparquet, MIT): no máximo 200 unidades por rodada, nova tentativa, disjuntor que
  roda completo se mais de 15% estiver sujo, reconciliação completa mensal.

## Backend

Pacote Python `raiz/`: FastAPI, SQLAlchemy 2 + GeoAlchemy2, Alembic, psycopg 3. Trabalhos são comandos
(`raiz carregar`, `raiz coleta checar`, `raiz funil rodar PA 1504950`) que rodam por cron e depois viram assets do
Dagster (E8 passo 7) sem reescrita.

## Agentes (E7)

LangGraph a partir do agent-service-toolkit (MIT), checkpointer no Postgres.

- **Modelos atrás de uma interface única.** Claude pela API (Sonnet 5.5 para conversa e documento, Haiku 5.5 para
  triagem) e, desde o início, Qwen3-4B-Instruct-2507 (Apache-2.0) no llama.cpp com JSON por gramática.
- **Cascata ABC:** dois modelos baratos votam; se concordam, vale a resposta; o desacordo sobe para o Claude ou para a
  fila de revisão.
- **Custo** por tarefa e por fazenda no Langfuse, com preços do genai-prices.
- **WhatsApp:** PyWa 4. O BSUID (identificador do usuário por empresa, mudança obrigatória do WhatsApp) fica junto do
  telefone no esquema `pessoal`.
- Grafos: operador (lotes, saúde, custo), aceite (conversa com o dono, pausa com `interrupt()` usando o código do CAR
  como thread_id, localização da sede, teach-back), título (memorial e matrícula), casamento (fazenda↔comprador),
  aprendiz (previsão contra gabarito, desafiantes).
- Healthchecks hospedado (avisa mesmo se o servidor cair), um check por lote municipal.

## Título (E5)

- Regras próprias em português para o memorial (deste, segue, azimute, rumo, distância, vértice). As regras do
  McWillie só entendem inglês e devolvem vazio sem avisar.
- O gatilho para o modelo de linguagem é a **nota de confiança** da leitura, não "a regex falhou". Fechamento do
  polígono e contagem de vértices sempre como alarme.
- `json_repair` antes do BAML (medido: o BAML devolveu 103 de 260 imóveis sem vértices e sem erro).
- Matrícula digitalizada: MonkeyOCRv2-B (Apache-2.0, CPU). Código Nacional de Matrícula validado localmente
  (python-stdnum, ISO 7064 mod 97-10) antes de pedir certidão.

## Telas

Preact + Vite num único projeto `web/`, com várias entradas:

| Tela | Mapa |
|---|---|
| Backoffice do fundador (saúde, custo contra orçamento, logs, fila de revisão, aprovação de mensagens) | MapLibre |
| Explorador (Brasil → estado → município → imóvel, grupos de pequenas) | MapLibre + PMTiles |
| Portal do comprador (carteira, P90 da carteira, pedido de laudo) | MapLibre + PMTiles |
| Ficha da fazenda (celular fraco) | Leaflet + PMTiles raster (~52 KB contra ~452 KB do MapLibre) |
| Página de aceite do dono (celular fraco) | Leaflet + PMTiles raster |
| Laudo de título (HTML e PDF) | imagem estática |
| Painel de acerto (previsão contra gabarito) | sem mapa |

Vídeo padrão por fazenda: receita direto no FFmpeg (cerca de 4 s para um vídeo de 15 s, sem Chrome).

## Caminho novo ao lado do motor (para comparar)

- Interseção: iOverlay (Rust, MIT/Apache), mantendo o corte em 512 vértices (40 s contra 119 s em teste sintético).
- Soma por imóvel: rusterize + `numpy.bincount` (2,4 s contra 21,8 s do exactextract em 100 mil imóveis).
- Calibração do carbono: GROA (CC BY 4.0). Heinrich 2021 é não comercial: só comparação, fora do treino.

## Onde roda

Uma máquina de 4 núcleos e 15 GB com Docker Compose (`infra/`); arquivos grandes no R2. Segredos só no `.env`.

## Licenças das peças principais

| Peça | Ferramenta | Licença |
|---|---|---|
| Banco | PostgreSQL / PostGIS | PostgreSQL / GPL-2 (só no servidor) |
| Coleta / arquivos | dlt / DuckDB + spatial | Apache-2.0 / MIT |
| API | FastAPI, SQLAlchemy, GeoAlchemy2, Alembic, Pydantic | MIT |
| Driver do Postgres | psycopg 3 | LGPL-3 (biblioteca, no servidor) |
| Agentes / rastros | LangGraph, agent-service-toolkit / Langfuse (núcleo) | MIT |
| Modelo local | Qwen3-4B-Instruct-2507 / llama.cpp | Apache-2.0 / MIT |
| WhatsApp | PyWa | MIT |
| Alertas | Healthchecks / ntfy | BSD-3 / Apache-2.0 |
| Telas | Preact, Vite, Leaflet, MapLibre GL JS, PMTiles | MIT, MIT, BSD-2, BSD-3, BSD-3 |
| Regras / checagens | Catala / Pandera | Apache-2.0 / MIT |

Armadilhas: o Langfuse instalado no próprio servidor pede Redis (hoje SSPL, RSAL ou AGPL) e MinIO (AGPL). Usar Valkey
(BSD-3) e R2 ou SeaweedFS (Apache-2.0).

## Pastas

```
motor/        funil por município (não muda)
dados/amostra amostra do Pará (base dos testes)
raiz/         pacote do produto (config, privacidade, contrato, banco, coleta, funil, regras, titulo,
              carbono, rebanho, compradores, aprendizado, comunicacao, agentes, operacao, api, cli)
migracoes/    Alembic
web/          telas
infra/        docker-compose e scripts do servidor
scripts/      checagens do CI (licenças, CPF/CNPJ)
testes/       pytest com a amostra e respostas gravadas das fontes
docs/         colunas, plano, arquitetura, pedidos (ONR e LAI)
```

A pasta de cada etapa só nasce quando a etapa começa.
