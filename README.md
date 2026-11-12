# Raíz

A Raíz acha, no Brasil inteiro, fazendas aptas a restauração, carbono, solo e metano usando só dados públicos,
checa o título da terra, pede o aceite do dono e liga a fazenda a quem paga (desenvolvedores de restauração,
empresas com meta FLAG, compradores de crédito, financiadores e governos). Também vende a checagem de título e
geolocalização como produto. Empresa AI First: o fundador opera com agentes de IA, e cada previsão é guardada
e comparada com o resultado real.

## O que já existe

**Motor de dados (`motor/`)**: funil por imóvel do CAR, município por município, para todos os estados. Roda sozinho no
GitHub Actions (`.github/workflows/processar-estados.yml`), 4 estados por vez, e publica no Release `dados`, de onde o
front baixa. Painel com o andamento de cada estado em [`motor/README.md`](motor/README.md).

| Script | O que faz |
|---|---|
| `raiz_estado.py` | funil principal: CAR (SICAR), embargos (Ibama), PRODES, TI, UC e hidrografia (TerraBrasilis), SIGEF (INCRA), MapBiomas, MapBiomas Alerta; reserva legal, APP (escadinha), frentes e carbono |
| `raiz_filtros.py` | quilombos (INCRA), terras indígenas da FUNAI em todas as fases, unidades de conservação do CNUC por grupo |
| `raiz_extras.py` | histórico exportado uma vez do Earth Engine (`motor/gee/`, não precisa rodar de novo): perdas da secundária e anos de fogo até 2024 |
| `raiz_extras_direto.py` | JRC TMF 2025 (Source Cooperative) e causas da perda de floresta (Zenodo), sem Earth Engine |
| `raiz_direto.py` | YbYrá e Global Pasture Watch lidos direto dos arquivos públicos, sem Earth Engine |
| `raiz_mapbiomas.py` | MapBiomas (cobertura, desmatamento, fogo, pasto) pela API da Plataforma, sem login e sem Earth Engine |
| `raiz_app.py` | aplica a escadinha da APP a municípios rodados antes dela |
| `rodar_estado.py` | roda um estado inteiro, etapa por etapa, dentro do prazo do job (é o que o GitHub Actions chama) |
| `publicar_dados.py`, `painel.py` | publicam no Release `dados` e atualizam o painel do motor |
| `raiz_ajustes.py` | ajustes da pesquisa (cenários de carbono etc.) por cima da saída |
| `mapbiomas_alerta.py` | API do MapBiomas Alerta (credenciais em variáveis de ambiente) |
| `iovbench/` | teste da interseção pelo iOverlay (Rust) contra o GEOS nos mesmos pares: 2,1x mais rápido em São Félix do Xingu e Altamira, mesma área |
| `fila*.sh` | filas antigas que rodam o país inteiro num computador só, estado por estado |

Desempenho: cerca de 30 a 40 s por município com 3 municípios ao mesmo tempo (4 núcleos, 15 GB); Brasil inteiro em cerca de 2 dias.

**Amostra (`dados/amostra/`)**: resumo do Pará (144 municípios) e, para Nova Esperança do Piriá (1504950) e São Félix do Xingu (1507300), todos os arquivos por município: imoveis, filtros, certidoes, direto, extras, extras_direto e mapbiomas (sem CPF, CNPJ ou nome).
Os dados completos não ficam no repositório (são grandes); o motor gera de novo.

**Documentos (`raiz/documentos/`)**: leitor de certidão de matrícula pela API da Anthropic, conferido com o
`certidoes_<mun>.csv` do motor (conferida, divergente ou cancelada), busca semanal de registros e editais (Verra, SFB,
Ideflor-Bio, Diário Oficial), documentos em .docx (folha de 3 páginas para o dono, relatório do lote com faixa P10 a
P90, checklist do edital) e aprendizado (cada leitura com a versão do modelo, marcada quando a certidão real confirma ou
desmente). Guia: `docs/documentos.md`.

**Documentação (`docs/`)**: `colunas.md` (o que cada coluna significa; é o contrato entre motor e produto) e
`plano-por-etapa.md` (o que construir, em que ordem, com horas estimadas).

**Produto (`raiz/`)**: pacote Python em cima do motor. Arquitetura aprovada em `docs/arquitetura.md`.

| Peça | O que faz |
|---|---|
| `raiz/contrato.py` | lê as saídas do motor pelo nome das colunas; coluna nova vai para `atributos` em vez de quebrar |
| `raiz/carga.py` | carrega `saida/<UF>/` no PostgreSQL + PostGIS, uma rodada por município, sem duplicar |
| `raiz/aprendizado/` | previsões congeladas (data de corte, horizonte, versões, hash do lote) e previsão contra gabarito |
| `raiz/privacidade.py` | máscara de CPF/CNPJ (inclusive alfanumérico), log mascarado, varredura do repositório |
| `raiz/licencas.py` | derruba o build se alguma dependência tiver licença proibida pelo CLAUDE.md |
| `raiz/coleta/` | E1: manifesto de camadas, checagem HEAD, WFS e ArcGIS com conferência de contagem, CAR e SIGEF incrementais no espelho Parquet por município, histórico scd2 no PostGIS, Ibama sem dado pessoal, MapBiomas pela API da Plataforma, índice de blocos de COG |
| `raiz/funil/` | roda o motor sem editá-lo, lendo CAR e SIGEF do espelho (ponte), com lotes vigiados |
| `raiz/modelos/` | Claude (Sonnet 5.5, Haiku 5.5) e Qwen3-4B no llama.cpp atrás de uma interface; cascata ABC; custo e Langfuse |
| `raiz/agentes/`, `raiz/whatsapp.py`, `raiz/api.py` | aceite do dono no WhatsApp (PyWa 4, BSUID), LangGraph com conversa cifrada, mensagens só com aprovação |
| `raiz/operacao/` | Healthchecks por lote, custo por tarefa, fazenda e município |
| `migracoes/` | esquemas `coleta`, `bruto`, `funil`, `regras`, `titulo`, `negocio`, `aprendizado`, `pessoal`, `operacao` |

**Pedidos do dia 1 (`docs/pedidos/`)**: convênio com o ONR e pedidos de LAI ao SFB e ao INCRA, prontos para enviar.

## Rodar o produto

```bash
uv sync --all-extras                                   # dependências do produto e do motor
docker compose --env-file .env -f infra/docker-compose.yml up -d   # PostGIS (ou um Postgres com PostGIS local)
uv run raiz banco migrar
uv run raiz carregar dados/amostra --data-corte 2026-11-12   # carrega e congela as previsões do motor
uv run raiz aprendizado placar
uv run raiz coleta fontes                              # o que olhar hoje e o que está pendente no manifesto
uv run raiz api                                        # aceites, mensagens a aprovar, revisões, webhook do WhatsApp
uv run pytest                                          # com RAIZ_BANCO_URL_TESTE no .env, testa também o banco
```

## Rodar o motor (dentro do produto: agente Dados)

O motor roda pelo produto, município a município, e grava cada arquivo no armazém com a versão da tarefa e a data.
A marca de concluído por município guarda a versão de cada tarefa: se a máquina reiniciar, ele retoma de onde parou;
se o motor ou uma regra mudar, refaz só o que a mudança afeta.

O armazém de produção é o Release `dados` do GitHub (o mesmo que o front baixa, ver docs/dados-publicados.md). É o
padrão: sem configurar nada, o executor lê de lá; grava só onde há o token do GitHub Actions (`GH_TOKEN` ou
`GITHUB_TOKEN`, só por variável de ambiente). Outros armazéns, pelo `RAIZ_ARMAZEM_URL` no `.env`:

```bash
RAIZ_ARMAZEM_URL=release-github://bernardoemmel/raiz/dados   # padrão (produção)
RAIZ_ARMAZEM_URL=dados/armazem                               # pasta local (desenvolvimento e testes)
RAIZ_ARMAZEM_URL=s3://raiz-motor/producao                    # compatível com S3 (opção futura, ver abaixo)
```

O S3 fica pronto para quando o volume pedir (Cloudflare R2, sem taxa de saída, ou SeaweedFS local: `docker compose
--env-file .env -f infra/docker-compose.yml --profile armazem up -d armazem`), com `RAIZ_S3_ENDPOINT`,
`RAIZ_S3_ACCESS_KEY_ID` e `RAIZ_S3_SECRET_ACCESS_KEY` só no `.env`. Hoje não é usado.

No GitHub Actions (workflow `processar-estados.yml`, explicado com o painel em [`motor/README.md`](motor/README.md)),
`motor/rodar_estado.py --executor` organiza a rodada e chama o executor: escolhe os estados (4 ao mesmo tempo, na
ordem do país), adota o estado publicado antes do executor (com a APP pela escadinha antes, onde faltava), roda
`raiz executor rodar --ufs <UF> --lanes 3 --ate-minutos <o que sobra das 5h30>` com `RAIZ_SEM_BANCO=1`, roda os
extras do Earth Engine se houver GeoTIFF e, se o prazo acabou, dispara a continuação do estado:

```bash
RAIZ_SEM_BANCO=1 GH_TOKEN=... uv run python motor/rodar_estado.py PA --executor
```

Um estado que já está no Release mas foi feito antes do executor (sem marcas): `uv run raiz executor adotar --ufs PA`
grava as marcas a partir do que está publicado, sem rodar o motor de novo (o `--executor` faz isso sozinho).

Um estado à mão:

```bash
uv sync --all-extras
uv run raiz executor plano --uf PA                   # o que rodaria agora, sem rodar
uv run raiz executor rodar --ufs PA --lanes 3        # roda e retoma; pode matar e rodar de novo
uv run raiz executor rodar --ufs PA --municipios 1504950,1507300
uv run raiz executor estado                          # prontos, em andamento, com erro, versão do motor
uv run raiz executor sincronizar --ufs PA            # o back-end espelha o armazém e carrega no banco
```

O Brasil inteiro (27 estados, 5.571 municípios):

```bash
uv run raiz executor rodar --ufs brasil --lanes 3
```

Agenda: `raiz executor ciclo` faz uma volta. A volta é completa (refaz todos os municípios) quando muda a coleção do
MapBiomas que o motor usa (uma vez por ano). No resto do tempo é parcial: refaz só o que mudou, seja a versão de
uma tarefa, seja uma fonte do município (CAR, SIGEF e embargos do espelho, alertas na área dele). Depois de cada
estado, o back-end carrega no banco. Exemplo no cron do servidor:

```bash
# todo dia às 2h40: coleta das fontes diárias e a volta do executor
40 2 * * * cd /srv/raiz && uv run raiz coleta car && uv run raiz coleta ibama && uv run raiz executor ciclo --lanes 3
```

Ou deixar rodando: `uv run raiz executor vigiar --intervalo-h 24 --lanes 3`. O painel fica em
`/painel/processamento` (pede o token da API) e os números em `GET /brasil`, `GET /estados` e `GET /processamento`.

Os scripts do motor (`motor/raiz_estado.py` e os outros) continuam rodando sozinhos como antes, mas o que o site
mostra vem do executor:

```bash
pip install -r requirements.txt
cd motor
python raiz_estado.py PA 1504950      # um município (código IBGE)
python rodar_estado.py PA             # todas as etapas do motor que faltam no estado, na ordem, sem o executor
```

Saída em `motor/saida/<UF>/`. O MapBiomas Alerta do funil vem do WFS público da plataforma, sem login; o
`mapbiomas_alerta.py` (API com login) precisa do `.env` (copie `.env.example` e preencha).

## Etapas do produto

E1 coleta de dados públicos · E2 funil por imóvel · E3 conta de carbono e de dinheiro · E4 rebanho, metano e solo ·
E5 título e geolocalização · E6 quem compra · E7 agentes e operação · E8 aprendizado contínuo · E9 o que as pessoas veem.

Ferramentas de terceiros usadas: ver `NOTICE.md`.
