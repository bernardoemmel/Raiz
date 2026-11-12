# Raíz

A Raíz acha, no Brasil inteiro, fazendas aptas a restauração, carbono, solo e metano usando só dados públicos,
checa o título da terra, pede o aceite do dono e liga a fazenda a quem paga (desenvolvedores de restauração,
empresas com meta FLAG, compradores de crédito, financiadores e governos). Também vende a checagem de título e
geolocalização como produto. Empresa AI First: o fundador opera com agentes de IA, e cada previsão é guardada
e comparada com o resultado real.

## O que já existe

**Motor de dados (`motor/`)**: funil por imóvel do CAR, município por município, para todos os estados.

| Script | O que faz |
|---|---|
| `raiz_estado.py` | funil principal: CAR (SICAR), embargos (Ibama), PRODES, TI, UC e hidrografia (TerraBrasilis), SIGEF (INCRA), MapBiomas, MapBiomas Alerta; reserva legal, APP (escadinha), frentes e carbono |
| `raiz_filtros.py` | quilombos (INCRA), terras indígenas da FUNAI em todas as fases, unidades de conservação do CNUC por grupo |
| `raiz_extras.py` | histórico exportado uma vez do Earth Engine (`motor/gee/`, não precisa rodar de novo): perdas da secundária e anos de fogo até 2024 |
| `raiz_extras_direto.py` | JRC TMF 2025 (Source Cooperative) e causas da perda de floresta (Zenodo), sem Earth Engine |
| `raiz_direto.py` | YbYrá e Global Pasture Watch lidos direto dos arquivos públicos, sem Earth Engine |
| `raiz_mapbiomas.py` | MapBiomas (cobertura, desmatamento, fogo, pasto) pela API da Plataforma, sem login e sem Earth Engine |
| `raiz_app.py` | aplica a escadinha da APP a municípios rodados antes dela |
| `raiz_ajustes.py` | ajustes da pesquisa (cenários de carbono etc.) por cima da saída |
| `mapbiomas_alerta.py` | API do MapBiomas Alerta (credenciais em variáveis de ambiente) |
| `iovbench/` | teste da interseção pelo iOverlay (Rust) contra o GEOS nos mesmos pares: 2,1x mais rápido em São Félix do Xingu e Altamira, mesma área |
| `fila*.sh` | filas que rodam o país inteiro, estado por estado, retomando de onde pararam |

Desempenho: cerca de 30 a 40 s por município com 3 municípios ao mesmo tempo (4 núcleos, 15 GB); Brasil inteiro em cerca de 2 dias.

**Amostra (`dados/amostra/`)**: resumo do Pará (144 municípios) e, para Nova Esperança do Piriá (1504950) e São Félix do Xingu (1507300), todos os arquivos por município: imoveis, filtros, certidoes, direto, extras, extras_direto e mapbiomas (sem CPF, CNPJ ou nome).
Os dados completos não ficam no repositório (são grandes); o motor gera de novo.

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

## Rodar o motor

```bash
pip install -r requirements.txt
cd motor
python raiz_estado.py PA 1504950      # um município (código IBGE)
python raiz_estado.py PA              # o estado inteiro
python raiz_filtros.py PA
python raiz_direto.py PA
```

Saída em `motor/saida/<UF>/`. Para o MapBiomas Alerta, copie `.env.example` para `.env` e preencha.

## Etapas do produto

E1 coleta de dados públicos · E2 funil por imóvel · E3 conta de carbono e de dinheiro · E4 rebanho, metano e solo ·
E5 título e geolocalização · E6 quem compra · E7 agentes e operação · E8 aprendizado contínuo · E9 o que as pessoas veem.

Ferramentas de terceiros usadas: ver `NOTICE.md`.
