# Plano de construção por etapa

Gerado da rodada 8 de pesquisa (12/11/2026). Ordem geral: E1 → E2 → E5 → E7 (em paralelo) → E3/E4 → E6 → E8 → E9.
Pedidos que só o fundador faz, no dia 1: convênio com o ONR e pedidos por LAI ao SFB e ao INCRA.

## Ordem geral

| Ordem | O quê | Depende de | Horas | Por quê |
|---|---|---|---|---|
| 1 | E1 passos 1 a 4 (coleta que pega só o que mudou) | nada | 20 a 33 | Tudo depende de dado atualizado e versionado. |
| 2 | E2 passos 1 a 5 (funil rápido sobre a coleta) | E1 | 15 a 30 | Destrava todas as outras etapas e ataca os 9 dias de fila. |
| 3 | E5 passos 1 a 4 (laudo de título por imóvel) | E1 e E2 | 33 a 53 | Já é produto vendável, inclusive para quem faz solo e metano. |
| 4 | E7 passos 1, 3 e 4 (operação vigiada), em paralelo desde o começo | nada | 11 a 19 | Quem opera sozinho precisa saber na hora quando algo parou. |
| 5 | E3 e E4 (conta com faixa honesta; rebanho e metano) | E2 | 85 a 138 | Dependem das áreas por fazenda que o funil entrega. |
| 6 | E6 (quem compra, por tempo de caminhão) | E4 | 34 a 59 | Precisa do rebanho por fazenda. |
| 7 | E8 (aprendizado), assim que houver previsões gravadas | E1 a E6 | 40 a 64 | Só aprende quando há previsão guardada para comparar. |
| 8 | E9 (ficha, texto, cartão, vídeo e voz) | E2, E3 e E5 | 46 a 80 | Mostra o que as etapas anteriores calculam. |
| 9 | No dia 1, em paralelo: pedir convênio ao ONR e fazer os pedidos de LAI ao SFB e ao INCRA | nada | 3 a 5 | Têm prazo de resposta de terceiros; quanto antes, melhor. |

Observação do motor atual (12/11, à tarde): o funil roda o Brasil por município (motor/) pelo executor do produto, no GitHub
Actions, com até 15 jobs ao mesmo tempo e os estados grandes em fatias; a coleta incremental (dlt scd2 do CAR e do SIGEF)
e o banco (PostGIS, migrações 0001 a 0018) existem, mas a coleta ainda não está agendada. Atualizado no fim do dia 12/11:
E3, E5, E7, E8 e E9 têm a coluna Situação conferida contra a main; E1 e E2 também (abaixo).

## Entregas de Dados do Brasil

Retomada em 12/11/2026, seguindo a passagem `docs/passagem/raiz-dados-do-brasil.md`.

| Ordem | Entrega | Situação |
|---|---|---|
| 1 | Limite global de 15 jobs de processamento, sem cancelar os existentes | **feito**: #43 mesclado com CI de push e PR verdes; admissão atômica na ref `raiz-fila-processamento`, incluindo pedidos manuais e continuações; falha de consulta bloqueia novas vagas. Pedidos sem vaga ficam persistidos e são retomados a cada 15 minutos |
| 2–3 | Fichas Croissant 1.1/schema.org e publicação no Release | a fazer |
| 4 | Quantis públicos no formato hubverse, com versão do modelo | a fazer |
| 5 | Cartão do modelo | a fazer |
| 6 | Atestação dos arquivos publicados pelo Actions | a fazer |
| 7 | Cronograma dos lotes no vocabulário CAD Trust | a fazer |
| 8 | Pendências E1/E2 da passagem, na ordem de dependência | a fazer |

## E1. Coleta de dados públicos

Conferido contra a main em 12/11/2026: "feito" quer dizer que o código está na main; "parcial" diz o que existe e o
que falta, com as horas do que falta. A coleta ainda não está agendada em lugar nenhum (`raiz coleta ...` existe, sem
workflow nem servidor).

| Ordem | Passo | Depende de | Horas | Situação |
|---|---|---|---|---|
| 1 | Montar o manifesto de camadas (YAML ou JSON): endereço por ano de cobertura Col. 11 e Col. 10, nove produtos do Fogo Col. 5, quatro produtos do YbYrá, altura e uGPP do GPW, com fonte alternativa (Earth Engine) para as camadas fechadas. | nada | 1 a 2 | **feito** com o que as fontes publicam: `raiz/coleta/manifesto.yaml` (17 fontes; validação e licença em `manifesto.py`); os 4 produtos do YbYrá (CC BY 4.0, 1986 a 2024) e os subtemas de fogo, pasto e secundária da API da Plataforma conferidos em /themes. A Plataforma não separa os 9 produtos do Fogo Col. 5 (publica anual, por período, monitor e mensal) nem endereço por ano (o ano vai no pedido) |
| 1 | Criar a tabela de replicação (fonte, recorte, cursor, etag, contagem, atualizado_em) e o calendário por fonte (Ibama diário, DETER sábado, MapBiomas segunda, PRODES outubro, CAR em rodízio semanal) | nada | 2 a 4 | **feito**: `coleta.replicacao` e `coleta.fonte` (migrações 0006 e 0007), calendário por fonte e rodízio do CAR (`raiz/coleta/manifesto.py`, `replicacao.py`) |
| 1 | Gatilho da PPM pelo calendário do IBGE (produto 9107), copiando a função do PYield | conferir robots e termos do servicodados | 2 a 3 | parcial: `raiz/coleta/ppm.py` acha a divulgação no calendário do IBGE; faltam baixar a tabela e o comando; espera a conferência de robots e termos do servicodados (1 a 2) |
| 1 | Fazer a tabela de 'sinal de mudança' de cada fonte: SICAR com data_atualizacao em 15 UFs e sem o campo em 12; DETER com view_date; PRODES por ano; ArcGIS do Ibama e SFB com editingInfo.lastEditDate; SIGEF e acervo sem campo (usar hash) | nada | 2 a 4 | parcial: campo `sinal` de cada fonte no manifesto (SICAR com data_atualizacao conferida por UF, DETER, PRODES, SIGEF, ETag); faltam as fontes ArcGIS (Ibama, SFB) com lastEditDate (1) |
| 2 | Job de checagem: HEAD em cada endereço, grava bytes, ETag e Last-Modified numa tabela; avisa no Healthchecks se faltar arquivo ou mudar ETag (rodar fora deste ambiente, que bloqueia os buckets). | passo 1 | 2 a 3 | **feito**: `raiz/coleta/checagem.py` e `raiz coleta checar` (HEAD ou 1 byte, ETag, Last-Modified, aviso no Healthchecks); falta agendar fora deste ambiente |
| 2 | Assinatura barata por município antes de baixar: resultType=hits mais 1 linha ordenada pela data (SICAR, Geoportal INCRA); If-None-Match no Ibama; nome do arquivo e last_update_date.json no PRODES | passo 1 | 3 a 5 | parcial: SICAR (`wfs.assinatura`: contagem e o mais novo) e Ibama (If-None-Match) feitos; faltam INCRA e PRODES (2 a 3) |
| 2 | Escrever uma fonte dlt para WFS do GeoServer (SICAR e TerraBrasilis): paginação count/startIndex com sortBy, CQL_FILTER por município e por data quando houver, requests-cache que não guarda resposta de erro | passo 1 | 6 a 10 | **feito** sem o dlt como fonte: `raiz/coleta/wfs.py` (count/startIndex, sortBy, CQL, confere numberMatched) e cache que só guarda resposta 200 (`http.py`); o TerraBrasilis segue pelo motor e pela vigilância |
| 3 | Índice de blocos: ler uma vez o cabeçalho de cada arquivo (tifffile ou GDAL /vsicurl) e salvar a tabela de offsets em Parquet; calcular bytes por município com a lógica do fetch_size.py. | passo 2 | 3 a 5 | **feito**: `raiz/coleta/blocos.py` (índice em Parquet, bytes num retângulo) e `raiz coleta indice` |
| 3 | CAR incremental: 15 UFs por data_atualizacao maior que o cursor menos 2 dias; 12 UFs por dat_criacao e coleta cheia do município quando a contagem muda; dlt scd2 com merge_key=cod_municipio_ibge | passo 2 | 6 a 10 | **feito**: `raiz/coleta/car.py` (cursor menos 2 dias, coleta cheia quando a contagem muda) e `bruto.py` (dlt scd2 por município); `raiz coleta car` |
| 3 | Escrever uma fonte dlt para ArcGIS REST (Ibama, SFB, IPAAM, ANA) no molde do ArcGISFeatureServerSpider: ler detalhes da camada, pular se lastEditDate não mudou, paginar por OBJECTID e conferir a contagem total | passo 1 | 4 a 8 | parcial: `raiz/coleta/arcgis.py` (pula se lastEditDate não mudou, pagina por OBJECTID, confere a contagem); falta ligar a fontes do manifesto, ao estado da replicação e a um comando (2 a 4) |
| 4 | Leitor por blocos no funil: pedir só os blocos do município com HTTP Range agrupado e cache local; calcular transições Col. 11 a partir de dois anos de cobertura. | passo 3 | 4 a 6 | parcial: leitura por blocos com cache em disco no direto (`blocos.abrir_com_cache`, `raiz/funil/ponte.py`); falta a transição Col. 11 a partir de dois anos de cobertura (2 a 3) |
| 4 | Ibama: pedido condicional do CSV, carga só de linhas com DAT_ULT_ALTERACAO ou DAT_ULT_ALTER_GEOM novos, carga do termo_embargo_historico.csv como changelog, descarte de nome e CPF/CNPJ na entrada | passo 1 | 3 a 5 | parcial: pedido condicional, nome e CPF/CNPJ descartados na entrada, espelho por município (`raiz/coleta/ibama.py`); faltam o histórico (endereço desconhecido) e a carga no scd2 (2 a 3) |
| 4 | Gravar no PostGIS com scd2: merge_key = município, hash próprio de campos estáveis e geometria normalizada, boundary_timestamp = data da extração; criar view da versão vigente | passos 2 e 3 | 4 a 6 | **feito** para CAR e SIGEF: `bruto.carregar` (hash próprio, geometria normalizada, data da extração) e view da versão vigente; falta o Ibama (passo acima) |
| 5 | Manter a exportação anual do Earth Engine só para desmatamento e vegetação secundária v5, vigor, idade e biomassa do pasto, já gravando COG com overviews (rio-cogeo) no armazenamento da Raíz e registrando no mesmo manifesto. | passo 1 | 2 a 4 | parcial, quase todo substituído: desmatamento, secundária e pasto vêm da API da Plataforma MapBiomas (`motor/raiz_mapbiomas.py`); a biomassa do pasto está na API (subtema no manifesto), falta coletar; falta o COG no armazenamento (2 a 4) |
| 5 | DETER no sábado com janela de 30 dias e chave composta; recarga completa anual depois do PRODES; MapBiomas Alerta por PublishedAt com janela de 35 dias e releitura de statusAt | passo 1 | 4 a 6 | parcial: DETER com chave composta e MapBiomas Alerta por PublishedAt e statusAt na vigilância diária (`raiz/vigilancia/fontes/`); falta a recarga anual do DETER depois do PRODES e passar pelo estado da coleta (2 a 3) |
| 5 | Guardar estado por camada x município no estado do dlt (como o Aqueduct) e criar backfill em blocos (UF ou mês) com checkpoint | passo 4 | 4 a 6 | parcial: estado por fonte e recorte em `coleta.replicacao` e fila com disjuntor e reconciliação (`raiz/coleta/fila.py`); falta o backfill em blocos com checkpoint (3 a 4) |
| 6 | Cubo por estado (Zarr ou referências do tifffile) com os 41 anos em cada bloco, para idade, transição e frequência de fogo por fazenda numa leitura. | passo 4 | 4 a 8 | a fazer |
| 6 | INCRA: Geoportal sigef_geo por data_aprovacao maior que o cursor e anti-junção semanal de parcela_codigo por município para achar canceladas; voltar aos ZIP com ETag quando o host voltar | passo 2 | 4 a 6 | parcial: SIGEF por município quando o CAR muda, com o que sumiu no espelho (`raiz/coleta/sigef.py`); faltam o cursor por data_aprovacao, a anti-junção semanal e os ZIP com ETag (depende do pedido de LAI) (3 a 4) |
| 6 | Guardas de qualidade: contagem recebida contra numberMatched ou count da camada, alerta de queda forte de contagem por município (como o notify-on-record-change da Nextstrain) e de colunas que ficaram vazias | passo 4 | 3 a 5 | parcial: contagem contra numberMatched e count (`wfs.paginas`, `arcgis.ler`) e trava de 25%; faltam o alerta de queda forte por município e o de coluna vazia (2 a 3) |
| 7 | Manifesto público no GitHub (CSV e GeoJSON) gerado a cada checagem e, se fizer sentido, catálogo estático com Portolan no R2. | passo 2 | 2 a 3 | a fazer |
| 7 | Gerar o 'diff da semana' por município (no molde do ArchiveDiffer da Delphi) e publicar a lista de municípios alterados para a E8 | passos 4 e 6 | 3 a 5 | a fazer (a base existe: `coleta.evento` e a diferença do espelho) |
| 8 | Pedidos por LAI ao SFB (data_atualizacao nas 12 UFs e camada de exclusões) e ao INCRA (novo endereço dos ZIP e lista de canceladas), citando LINZ, SDMX e o índice diário da SEC | nada | 1 a 2 | **feito** o texto (`docs/pedidos/lai-sfb.md`, `lai-incra.md`); o envio é do fundador |
| 4 | (rodada 10) Antes do hash, normalizar a geometria: precisão fixa e vértices em ordem padrão | passo 4 | 1 a 2 | **feito**: `raiz/coleta/espelho.py` (`geometria_canonica`) |
| 4 | (rodada 10) Resumo por município (contagem + hash do conjunto); comparar imóvel a imóvel só onde o resumo mudou | passo 4 | 1 a 2 | **feito**: `Espelho.gravar` (resumo.json por município) |
| 5 | (rodada 10) Marcador da paginação só anda depois da página gravada (camadas grandes e backfill) | passo 4 | 2 a 3 | a fazer |
| 6 | (rodada 10) Trava de versão: arquivo que muda mais de 25% ou conjunto que muda mais de 15% não é publicado sem revisão | passo 4 | 1 a 2 | **feito**: `espelho.LIMITE_MUDANCA`, trava da UF (`raiz/coleta/rodada.py`) e `raiz coleta liberar` |
| 1 | (rodada 10) MapBiomas só pela API da Plataforma, por estado (categoria 214), como motor/raiz_mapbiomas.py: o armazenamento público fechou (403) | nada | feito | **feito** |

## E2. Funil por imóvel

Conferido contra a main em 12/11/2026. O funil de produção ainda é o motor (`motor/`), rodado pelo executor; as peças
novas da E2 (regras em Catala, restrições, DuckDB) estão testadas mas fora desse caminho.

| Ordem | Passo | Depende de | Horas | Situação |
|---|---|---|---|---|
| 1 | Montar a tabela de parâmetros legais versionada: percentuais de RL por UF, bioma e fitofisionomia, faixas da escadinha, teto do 61-B, corte de 22/07/2008 e de 2002, cada linha com vigência, artigo, URN do LexML e link arquivado (formato vat-rates ou ParamTools) | tabela de módulos fiscais do SNCR e tabela de percentuais do DCF Guidebook (rodadas anteriores) | 4 a 6 | **feito**: `raiz/regras/parametros/federal.yaml` (regras-2026b, vigência, artigo, URN do LexML, data de adoção), publicada no esquema `regras`; faltam o link arquivado, o corte de 2002 e as tabelas do SNCR e do DCF como tabela |
| 1 | Montar a bancada própria copiando o geobenchmark (BSD-3): CAR de um estado grande (por exemplo Mato Grosso) contra UC, TI e embargos, medindo tempo e memória de geofileops, DuckDB lendo GeoParquet e geopandas com Arrow na máquina de 16 GB | E1 (CAR e camadas em disco) | 4 a 8 | parcial: `raiz/funil/bancada.py` (um município, GEOS x iOverlay x DuckDB) e `motor/iovbench/`; faltam o estado inteiro com UC, TI e embargos e a memória (2 a 4) |
| 1 | Trocar Fiona por pyogrio em toda leitura e gravação e guardar as camadas em GeoParquet | nada | 1 a 2 | **feito**: sem Fiona; espelho e blocos em GeoParquet |
| 2 | Escrever as regras federais em Catala (arts. 4, 12, 15, 61-A, 61-B, 67 e 68), usando o BCAE7 como molde de pastas, prólogo e testes, e gerar o Python | passo 1 | 12 a 20 | **feito**: `raiz/regras/catala/` (arts. 4, 12, 15, 61-A, 61-B, 67 e 68) e o Python gerado, conferido com o motor nos testes |
| 2 | Limpar as camadas de restrição antes do cruzamento (desenho do wdpar): consertar geometria, unir e apagar sobreposições por prioridade (TI, UC de proteção integral, UC de uso sustentável, embargo) com geofileops | passo 1 | 3 a 6 | parcial: `raiz/funil/restricoes.py` (conserta, une e apaga sobreposição por prioridade) com teste; falta usar no funil (1 a 2) |
| 2 | Reescrever os cruzamentos vetoriais no DuckDB com só o predicado espacial na junção e filtros depois; conferir no EXPLAIN que aparece 'Spatial Join' | passo 1 | 3 a 6 | parcial: `raiz/funil/duck.py` com o 'Spatial Join' conferido no EXPLAIN; usado só na bancada (2 a 4) |
| 3 | Criar 60 a 100 imóveis de teste com laudo esperado (snapshot, como no mon-entreprise) e testes em YAML por UF; somar testes de propriedade com Hypothesis (já conhecido) para faixas de módulos e larguras de rio | passo 2 | 6 a 10 | **feito** para o PA: 72 casos em `testes/dados/imoveis_teste/PA.yaml` e testes com Hypothesis; faltam outras UFs |
| 3 | Separar camadas densas (MapBiomas, YbYrá, pasto) de esparsas (incremento do PRODES, embargos, fogo) e definir a chave de bloco (0,5 grau ou prefixo de quadkey) gravada em todas as tabelas | passo 2 | 1 a 2 | **feito**: `densidade` no manifesto, `raiz/funil/grade.py` e coluna `bloco` nas tabelas (migração 0010) |
| 3 | Calcular uma vez a tabela (CAR, pixel ou célula, fração) com exactextract ou rusterize e aplicar cada ano do MapBiomas como junção ou numpy.bincount | passo 2 | 4 a 8 | a fazer |
| 4 | Validação cruzada num município piloto: rodar a Raíz, o GeoCAR (regras copiadas, MIT) e o landschaft (no servidor, GPL) nos mesmos imóveis e comparar com o quadro de áreas do SICAR (num_area_reserva_legal_minima_lei); investigar cada diferença, como no Tax-Calculator | passos 2 e 3 | 6 a 10 | parcial: `raiz/regras/validacao.py` e `raiz regras validar`; falta a comparação real (o quadro de áreas do SICAR depende do pedido de LAI; o landschaft só no servidor) |
| 4 | Camadas densas: rasterizar o CAR por bloco com rasterix e motor rusterize alinhado à grade de 30 m e somar com flox xarray_reduce (expected_groups = imóveis do bloco, reindex esparso); tratar imóveis sobrepostos em camadas separadas | passo 3 | 8 a 12 | a fazer |
| 4 | Repartir o país em blocos fixos com manifesto (bloco, hash, data) e recalcular só os blocos tocados por mudanças da coleta | passos 2 e 3; coleta com data ou hash (E1) | 6 a 10 | parcial: `raiz/funil/manifesto_blocos.py` (blocos sujos, migração 0011); o executor refaz por município e ainda não lê os blocos sujos (2 a 3) |
| 5 | Camada estadual: regras de PRA e exceções por UF (começar por PA, MT e SP; incluir Piauí 30% no Cerrado) com nível, área de validade e vigência, no padrão aides-velo e Catala archives | passos 1 a 4 | 4 a 8 por estado | parcial: o mecanismo existe (`raiz/regras/parametros/estadual/` PA, MT, SP e PI); falta a leitura das leis (valores pendentes) |
| 5 | Camadas esparsas: motor 'pixels em polígonos' (só pixels marcados, STRtree.contains com os imóveis do bloco, somas parciais em Parquet ordenado por id do imóvel, junção por faixa de id) | passo 3 | 8 a 12 | a fazer |
| 5 | Montar o teste de velocidade no estilo do geobenchmark com o CAR de um estado e rodar a cada troca de ferramenta | passo 1 | 3 a 5 | parcial: a bancada; faltam o estado inteiro e rodar a cada troca de ferramenta |
| 6 | Marcar cada resultado como completo ou incompleto, com a lista de fatos que faltam (ideia do Fact Graph), e gerar a explicação passo a passo em português simples para o laudo e para o agente de WhatsApp | passo 2 | 4 a 6 | parcial: explicação passo a passo (`raiz/regras/federal.py`, `explicar`) e motivos de não apto (`raiz/motivos.py`); falta marcar completo ou incompleto com os fatos que faltam |
| 6 | Área exata só onde importa: exactextract sobre VRT para imóveis pequenos e para limites legais (APP, reserva legal) perto do corte | passos 4 e 5 | 3 a 5 | a fazer |
| 7 | Changelog próprio no estilo Overture (added, removed, data_changed, unchanged, columns_changed, tipo de mudança da OS) e lista de imóveis e células sujas para o funil recalcular só elas | passos 3 a 6 | 5 a 8 | parcial: novos, mudaram e sumiram no espelho e em `coleta.evento`; faltam as categorias do Overture e a lista de imóveis sujos que o funil consome |
| 7 | Versão nomeada das regras (ex.: regras-2026b, como no tz) gravada em cada previsão, com as duas datas do OpenL (vigência legal e quando a Raíz passou a usar) | passo 1 | 2 a 4 | **feito**: `regras_versao()` devolve `regras-2026b+hash` (`raiz/versoes.py`) e a carga publica a versão em `regras.versao` antes de gravar a rodada e as previsões (`raiz/carga.py`) |
| 7 | Fila retomável e incremental: um alvo por bloco num Makefile gerado em Python (desenho do WSIM) ou no SQLMesh; arquivo 'BUSY_' e pular saída existente (desenho do cropclassification); refazer só blocos cujo CAR ou camada mudou (comparação de versões como no RPG da França) | passos 4 a 6 | 6 a 10 | **feito** por município: o executor (`raiz/executor/`) com marca por tarefa, retomada e refazer só o que mudou, rodando no GitHub Actions em até 15 jobs; falta por bloco |
| 8 | Pasta de reformas: cada projeto de lei ou decreto novo vira um arquivo de diferença (padrão Tax-Calculator) para simular o efeito sobre os imóveis antes de valer | passos 1 e 7 | 3 a 5 | a fazer |
| 8 | Conferência: comparar flox, 'pixels em polígonos' e exactextract em 1.000 imóveis sorteados e publicar a diferença no painel; checagem de mistura de classes por imóvel (desenho FOI do JRC) | passo 7 | 3 a 5 | a fazer |
| 7 | (rodada 10) Mudança de geometria menor que 0,5 ha não volta ao funil (entra no changelog, não na lista de sujos) | passo 7 | 1 | a fazer |

## E3. Conta de carbono e de dinheiro

| Ordem | Passo | Depende de | Horas |
|---|---|---|---|
| 1 | Instalar metalog-jax e trocar as entradas PERT por metalog SPT montada de P10/P50/P90 de cada entrada | conta de carbono atual em OpenTURNS | 2 a 4 |
| 1 | Escrever a conta de carbono por fazenda como função pura (área elegível por classe, taxa de acúmulo, fator raiz, fração de carbono, 44/12), no formato da cadeia do Carbon_MRV, com testes Dado/Quando/Então de 20 fazendas-modelo | saída do funil E2 (áreas por classe por fazenda) | feito (raiz/restauracao.py: área por modo, captura em curva com raiz, descontos em ordem e crédito líquido; testes com fazendas-modelo em testes/test_restauracao.py) |
| 2 | Gravar cada fazenda como coeficientes metalog mais índices HDR em JSON (formato inspirado no SIPmath, sem usar a marca) | E3 passo 1 | 3 a 5 |
| 2 | Montar as distribuições das entradas (inclusive a partir de P10, P50 e P90 de especialista, como o HIIPAPP) e as correlações (cópula ou generateCorrelatedSamples do PVDeg) | passo 1 | 3 a 5 |
| 3 | Somar a carteira à moda do PRMS: Monte Carlo com correlação por bioma e município e saída lado a lado P90_soma e P90_carteira | E3 passo 2 | feito (restauracao.faixa_lote: soma e carteira lado a lado com um fator comum de 60% da variância, a mesma premissa no lote, no pedido e nos documentos) |
| 3 | Escolher o número de sorteios com OpenTURNS QuantileConfidence (P10 com 95% de confiança) | passo 2 | 2 a 3 |
| 4 | Modelar a perda por fogo e derrubada com aggregate (frequência vezes severidade) e repartir a reserva por fazenda | E3 passo 3 e mapas de risco já temos | feito (restauracao.nao_permanencia: fogo do MapBiomas Fogo e derrubada da vegetação secundária do município, menos a mitigação, mais o risco interno e externo; reserva por fazenda nunca abaixo da do cenário) |
| 4 | Rodar o Monte Carlo por município com sorteio comum dos fatores globais (preço, fração de carbono) e sorteio próprio dos locais, no padrão CLIMADA unsequa (uma coluna por fazenda); gravar P10, P50, P90 e hash da função em Parquet | passo 3 | feito em parte (400 sorteios comuns a todos os imóveis, P10/P50/P90 e versão com hash das premissas em desenvolvedor_<mun>.csv; falta separar o fator global do local e gravar em Parquet) |
| 5 | Acrescentar ao laudo os campos da Portaria MME 102/2016 (P50, P90, incerteza padrão, revisor independente) com teste de independência | E3 passo 3 | feito no lote (P50, P90 de excedência na carteira e na soma, incerteza padrão; revisor independente marcado como pendente) |
| 5 | Dinheiro: VPL e TIR por sorteio com PyXIRR e partilha dono/desenvolvedor/Raíz no padrão pyscnomics; caminhos de preço com as dinâmicas do rangekeeper | passo 4 | feito em parte (VPL e TIR por sorteio, sem e com Fundo Clima, com TIR vetorizada própria; parte do dono por crédito, piso, aluguel e duas fases; conexão da Raíz por ha nos pedidos; falta o caminho de preço) |
| 6 | Sensibilidade: SALib delta sobre a mesma amostra (como bicrs-lca), uma vez por bioma, para o tornado e a decomposição da incerteza no laudo | passo 4 | em parte (tornado da TIR do lote, uma entrada por vez: captura, custo, preço e câmbio, refeito fazenda a fazenda; falta o delta do SALib por bioma) |
| 7 | Desconto de incerteza da VM0047 e oferta de "quantas parcelas medir" (Carbon_MRV 04_sampling_design); snapshot das fazendas-modelo no CI | passos 4 e 6 | feito (desconto de incerteza de 10% em ordem; parcelas por método no lote pelo AR-TOOL03; fazendas-modelo nos testes) |
| 3 | (rodada 10) Monte Carlo com sequência de Sobol (scipy.stats.qmc) no lugar do sorteio simples | passo 2 | em parte (fator comum da faixa do lote em Sobol embaralhado; os 400 sorteios por fazenda seguem pseudoaleatórios) |
| 3 | (rodada 10) Cópula vine (pyvinecopulib, conferir licença) no lugar da gaussiana para a correlação entre entradas | passo 2 | 3 a 5 |
| 3 | (rodada 10) P90 da carteira pelo modelo de Vasicek (fator comum por bioma e município) ao lado do Monte Carlo | passo 3 | feito (um fator comum no lote; falta separar o fator por bioma e município) |
| 7 | (rodada 10) Amostragem de campo do grupo pela norma do MDL: 90% de confiança, 10% de erro, mínimo de 30 parcelas | passo 6 | feito (restauracao.parcelas_campo, no relatório do lote) |
| 1 | (GHG LSR v1.1, vale a partir de 1/1/2027; o SBTi FLAG segue) Meta FLAG separada de crédito: flag_<mun>.csv com silvipastoril, cacau e tCO2 com faixa; restauração, RL, APP e capoeira vão para crédito Verra ou compensação; regra versionada em raiz/regras/padroes/ghg_lsr.yaml, gravada em cada cálculo e refeita quando muda (`raiz flag recalcular`); ficha e simulador sem somar os dois blocos | motor (pasto, RL, APP, MapBiomas) | feito |
| 2 | (GHG LSR v1.1) Calibrar as faixas de remoção de silvipastoril e de SAF de cacau (GROA, CC BY, e literatura da Amazônia) e trocar a viabilidade do cacau por bioma pelo zoneamento de risco climático do cacau (ZARC/MAPA) por município | passo anterior | 4 a 8 |
| 3 | (GHG LSR v1.1) Requisitos por fazenda com dado de verdade: vínculo CAR com frigorífico (fornecedor direto) para o rastreio; medição de campo com nova amostragem a cada 5 anos, gravada como gabarito (E8); direito de reportar no contrato (E6) | E6, E8 | 8 a 12 |
| 4 | (GHG LSR v1.1) Requirement 7 (floresta ligada à produção: mesmo dono, mesmo plano de manejo, vizinha, ligada à produção) já modelado e desligado; ligar quando o padrão incluir floresta, só trocando ativo e a versão na tabela | nada | 0,5 |
| 5 | Valor para quem restaura (desenvolvedor de crédito: Systemica, re.green, brCarbon, Mombak, Biomas): modo por regra escrita (distância à mata, idade e vigor do pasto, fogo, declividade), custo e captura P10/P50/P90 com ajustes (acesso OSM, Copernicus, CHIRPS, SoilGrids), linha de base dinâmica VM0047 medida no YbYrá, crédito líquido, fluxo de caixa do ProFloresta+ (VPL, TIR sem e com Fundo Clima, pico de capital), lotes de vizinhas, bloco na ficha e painel ordenado; estimativas congeladas e recalibração com o real do cliente | motor, E8 | feito |
| 6 | Rodada 11 como cenário padrão (central_r11): captura em curva (forma da URTX, 588,8 t em 40 anos no plantio e 442,8 t na regeneração, teto por bioma), custos oficiais do SFB por ano, descontos em ordem (linha de base com piso de 10%, vazamento VMD0054 de 10%, reserva, incerteza), marcos do ProFloresta+ com chance de cumprir, multa esperada e rescisão, pagamento ao dono comparado com o aluguel do Censo Agro 2017 e o aceite em duas fases, Fundo Clima pelo ICSD 1,3, venda depois do ano 25, PTAX do Banco Central; premissas antigas no otimista_fundador | passo anterior | feito |
| 6b | Calibrar o valor para quem restaura com custo e captura reais dos primeiros clientes e medir o vazamento (VMD0054) fazenda a fazenda | passo anterior e clientes | 4 a 8 |
| 7 | Caminho da terra no lugar do corte por matrícula: seis caminhos com risco e motivo (Verra VCS 5.0 3.6.2; Lei 15.042/2024 arts. 43, 47 e 49; ProFloresta+ fase 1), sobreposição com SIGEF do espelho, CNFP do SFB, CNUC, TI e quilombos; etapa "Caminho da terra" no funil com barras pronta agora, em espera e só mostrar; selo prata só para matrícula conferida ou concessão; camada de terra pública para restaurar com custo, captura e crédito; concessões e editais com data e link | motor, espelho SIGEF, CNFP | feito |
| 8 | Carregar o polígono exato das concessões do Ideflor-Bio (página "Concessão Florestal, Shapes") e do SFB, e o processo de titulação do Iterpa e do INCRA por imóvel (hoje só o estado da parcela no SIGEF) | passo anterior | em parte (polígono das áreas de restauração da URTX no caminho da terra e na terra pública; faltam as outras concessões e a titulação) |
| 9 | Motor dentro do produto (agente Dados): executor por estado e município com marca de concluído por tarefa (versão, assinatura, sha das saídas), retomada depois de matar, refazer só o afetado (versão da tarefa, fonte do município, saída anterior), armazém no Release "dados" do GitHub (produção; S3 com R2 ou SeaweedFS como opção futura) com versão e data em cada arquivo, workflow processar-estados chamando `raiz executor rodar --ate-minutos`, back-end lendo o armazém (sincronizar, carga do que mudou, sob demanda por imóvel), /brasil, /estados, painel do processamento, agenda anual (coleção do MapBiomas) e parcial | E1, E2 | feito |
| 10 | Pedido de lote (docs/cena-alvo.md): oferta por fazenda (negocio.oferta, refeita a cada carga), pedido com os campos da cena-alvo, quanto existe na base por caminho da terra e interesse do dono com P10/P50/P90, o que falta e o que afrouxar, 3 opções do mesmo solver (HiGHS pelo scipy: mais barata, mais segura, mais compacta, com forma do lote e vazamento zero com fazenda de mitigação) e 10 a 20% de reserva, troca de fazenda, entrar sem senha, interesse do dono por nível (só o nível sai na API), ondas de contato dimensionadas pela chance de aceite (envio simulado), andamento, grupo pronto com aviso (painel, e-mail, WhatsApp), reserva com Pix da AbacatePay (modo de teste) e exclusividade de 60 dias, contrato com abatimento, vigia do pedido salvo e chance de aceite que aprende com cada contato | passos 6 e 9 | feito |
| 10b | Rodada 11 unificada (um só arquivo de premissas e um só cálculo, com a branch premissas-rodada11: curva oficial da URTX, teto por bioma, P10/P90 de custo publicados, último marco a 100%, vazamento por vizinha VMD0054, renda do gado do Censo) e lote do ProFloresta+ por estado (`raiz lote montar`): titulares e reserva pela chance de 90% com erro comum da captura, fluxo do lote pela soma das fazendas, preço mínimo para TIR de 12% e 15%, o que destrava o lote (posse e assentamento), certidões para os 5% homologados, checklist do edital, relatório para o desenvolvedor e folha do dono; o otimizador põe a regeneração antes do plantio que o preço não paga | passos 6 e 10 | feito |
| 10c | Lote e números: piso20 de reversão, três opções, preços TIR12/15 por fazenda, salvaguardas jurisdicionais/CLPI/partilha, decisões explicadas e revisão humana, previsões versionadas e comparação real; workflow PA144 com separação entre aberto e pago | 10b | **código feito no PR #49, CI verde**; Actions 43285608189 interrompido pelo chat Ficha da fazenda durante migração dos dados pagos. Retomada autorizada só das cinco fatias faltantes, reutilizando dez prontas, limite total de quinze jobs e publicação completa autenticada; execução integral ainda pendente. Uma fatia de 23.023 imóveis auditada. Fontes/licenças e quatro horizontes regionais auditados; quantis ecológicos pendentes de harmonização de parcelas, unidades e métodos (**parcial**, conforme autorização do fundador). Detalhes em `docs/passagem/lote-e-numeros.md` |
| 11 | Ligar o envio de verdade das ondas (agente de aceite no WhatsApp com o termo, carta e parceiro local) e a chave de produção da AbacatePay; calibrar a chance de aceite e o valor da conexão com os primeiros pedidos | passo 10 e clientes | 6 a 10 |

## E4. Rebanho, metano e solo

| Ordem | Passo | Depende de | Horas |
|---|---|---|---|
| 1 | Montar as entradas: PPM por município (SIDRA 3939), Censo Agro 2017 por grupo de área e de cabeças (SIDRA 8986 e 8987), pasto do MapBiomas, vigor e idade do pasto, densidade do GPW; imputar células com 'X' do SIDRA (ideia do FLAPS) e alinhar a malha municipal entre anos (ideia do NHGIS) | E1 | em parte (gatilho da PPM pelo calendário do IBGE em raiz/coleta/ppm.py; Censo Agro 2017 por município com pasto, cabeças e venda de bovinos em raiz/regras/padroes/censo_agro_2017_pecuaria.csv; pasto, vigor e idade do MapBiomas e GPW no motor; PPM 2025 e 2017 por município baixada em raiz/regras/padroes/ppm_bovinos.csv; faltam os grupos de área) |
| 2 | Base rápida: pyDasymetric com peso pasto x vigor e máscara de pasto fora de áreas restritas, separando rebanho a pasto e em confinamento (regra do PIK); somar por imóvel com exactextract e arredondar para inteiros preservando o total (IntPopGrids) | passo 1 e E2 (máscara) | feito (raiz/rebanho.py: PPM 2025 espalhada por pasto x produtividade do GPW ou vigor, total preservado em inteiros; falta separar o confinamento) |
| 3 | Baixar raster de gado a pasto (1 km) e pontos de operações de gado da Climate TRACE e comparar com o rebanho espalhado da Raíz | disaggregation do E4 rodando | 4 a 6 |
| 3 | Calibrar o peso: testar pares de expoentes (desenho LitPop) e floresta aleatória (pypopRF) contra o Censo Agro 2017 por município, com validação cruzada por estado | passo 2 | 6 a 10 |
| 4 | Ajuste de credibilidade por município com statsmodels MixedLM | passo 3 | 3 a 5 |
| 4 | Faixa de erro: disaggregation (R-INLA) por estado ou bioma com pasto como raster de agregação; antes, rodar o teste com rebanho simulado (ideia do CattleSlaughtering) e escolher covariáveis na bancada disagapp | passo 3 | 10 a 16 |
| 5 | Ajustar cada sorteio ao total oficial (raking do IHME LBD) e guardar P10, P50 e P90 por imóvel | passo 4 | em parte (P10/P50/P90 por imóvel de três desenhos do peso e do Censo contra a PPM; falta o sorteio com raking) |
| 6 | Fazendas sintéticas por município (humanleague QIS ou PopulationSim em dois anos, como o psrc/mazpop) para dividir as cabeças em vacas, novilhas, bois e bezerros e dar faixa de tamanho | passo 5 | 8 a 12 |
| 7 | Metano: fator de emissão por categoria (IPCC Tier 2 ou ABC+Calc, já conhecidos) vezes cabeças em cada sorteio; conferência grossa por microrregião com TROPOMI | passo 6 | em parte (Tier 1 do IPCC 2006 por cabeça, P10/P50/P90; falta o Tier 2 por categoria e a conferência com o TROPOMI) |
| 8 | Solo e pasto degradado: estatística zonal do MapBiomas Solo por imóvel e sorteio de proporções do Censo Agro dentro do município (desenho DSMART); segunda estimativa de rebanho pelo GPW levado a 30 m (desenho dissever) para marcar imóveis com grande divergência | passos 2 e 5 | 6 a 10 |

## E5. Título e geolocalização

| Ordem | Passo | Depende de | Horas | Situação |
|---|---|---|---|---|
| 1 | Montar o conjunto de teste: sortear cerca de 200 parcelas do acervo fundiário, gerar o memorial de cada uma com LFTools ou GeoPlanta e guardar o par polígono e texto. | acervo fundiário já baixado (E1) | 3 a 5 | **feito**: `raiz titulo conjunto-teste` sorteia parcelas do SIGEF do espelho e escreve o memorial nos estilos SIGEF e por rumo com gerador próprio (LFTools e GeoPlanta são GPL); `avaliar_conjunto` dá o placar do leitor (`raiz/titulo/conferir.py`) |
| 1 | Definir o registro e a chave (código do CAR + parcelas SIGEF + matrícula + CNS, o código do cartório no Conselho Nacional de Justiça) e a tabela de achados no formato do CFPB (registro, regra, campo, valor, gravidade, fase) | E1 e E2 | 2 a 3 | **feito**: chave do registro (`raiz/titulo/achados.py`, `car:...|sigef:...|mat:CNS/matrícula`) e tabela de achados no formato do CFPB (`achados_<mun>.csv`, `titulo.achado`, migração 0022), com as fases formato, geometria, coerência, referência, cadeia e regularização |
| 2 | Leitor de memorial em duas camadas: regex em português (vértice, coordenadas, azimute, rumo, distância, confrontante) e modelo de IA só quando a regex falhar, com fila de revisão (desenho do McWillie Deed Sketcher). | passo 1 | 6 a 10 | **feito**: `raiz/titulo/memorial.py`; o modelo entra pela nota de confiança da leitura, não por "a regex falhou", e a nota baixa vira achado a confirmar |
| 2 | Gravar em WARC (warcio capture_http) todas as consultas públicas usadas em cada laudo | coletor dlt existente | 3 a 5 | **feito**: `raiz/titulo/warc.py` grava pedido e resposta de cada consulta pública num WARC (warcio) cifrado com a chave pessoal (a página do SIGEF pode trazer nome); o índice e o laudo guardam só URL, data e hash SHA-256 (`raiz titulo warc`). O WARC é montado da resposta, não pelo capture_http, que só grava se for importado antes do requests |
| 2 | Escrever as checagens em Pandera ou Pointblank por fase: formato, validade da geometria, coerência (áreas CAR x SIGEF x matrícula), referência (cartório existe), com N/A quando não se aplica (como o Pelican) | passo 1 | 8 a 12 | **feito** com motor próprio, sem Pandera: achados por fase (formato, geometria, coerência, referência, cadeia, regularização), situação `nao_se_aplica` e gravidade, para certidão, memorial, planilha, CAR x SIGEF e regularização |
| 3 | Geometria e fechamento: azimute e distância para coordenadas no elipsoide (GeographicLib, por causa do sistema local do SIGEF), erro de fechamento, precisão relativa e ajuste pela regra da bússola (cogokit). | passo 2 | 4 a 6 | **feito**: `raiz/titulo/geometria.py` (pyproj.Geod no GRS80, erro de fechamento, precisão 1:N e regra da bússola) |
| 3 | Separar checagens que reprovam das que pedem confirmação (padrão HMDA) e gravar quem confirmou e quando | passo 2 | 3 a 4 | **feito**: gravidade reprova, confirmar e info em todo achado; `titulo.confirmacao` grava quem (identificador do operador, nunca nome), a decisão e quando (`raiz titulo confirmar`), só com linhas novas |
| 4 | Comparar memorial, SIGEF e CAR com as tolerâncias de 0,50 m, 3,00 m e 7,50 m e as classes D1 a D7, e gerar o laudo por imóvel no Pointblank. | passo 3 | 4 a 8 | **feito**: escala D1 a D7 própria (definida em `docs/titulo.md`), tolerâncias 0,50, 3,00 e 7,50 m; CAR x SIGEF na tarefa do município, memorial e planilha por `raiz titulo memorial|planilha`; laudo por imóvel fica para o passo 7 |
| 4 | Nota de risco 1 a 5 por imóvel com bandeiras (padrão Collateral Underwriter) e decisão em quatro saídas (padrão subscrição de seguro) | passo 3 | 3 a 5 | **feito**: `titulo_<mun>.csv` com nota, bandeiras e decisão em quatro saídas (`raiz/titulo/nota.py`, `nota_titulo.yaml`) |
| 5 | Leitor e validador da planilha ODS (colunas do GeoINCRA, zip mais ElementTree). | nenhum | 2 a 4 | **feito**: `raiz/titulo/planilha.py` (zip + ElementTree); colunas achadas pelo cabeçalho, layout a conferir com uma planilha real |
| 5 | Regras legais em Catala no molde do BCAE7 (reserva legal, APP escadinha, art. 67) ou em Publicodes em camadas (federal, estadual, municipal), com testes de fazendas-modelo e snapshot | passo 1 | 12 a 20 | **feito** na E2 passo 2: `raiz/regras/catala/` (arts. 12, 15, 61-A, 61-B, 67 e 68), gerado para Python e conferido com o motor |
| 6 | Modelo de dados da cadeia dominial em Postgres (ato, imóvel do ato, parte só com tipo e CNPJ, referência ao ato anterior), no molde do ACRIS e do Sistema de Cadeia Dominial. | nenhum | 4 a 6 | **feito**: migração 0023 com `titulo.matricula`, `titulo.ato` (com o ato anterior), `titulo.ato_parte` (só tipo e documento mascarado; o banco recusa documento sem máscara), `titulo.matricula_imovel` e `titulo.cadeia_origem`; a carga lê o `cadeia_<mun>.csv` de `raiz/documentos`; achado `cadeia.origem` (`raiz/titulo/cadeia.py`) |
| 6 | Bandeiras de contexto por dono, cartório e município com quartis e cercas (padrão Cardinal) e testes de auditoria (áreas redondas, soma das glebas) | passo 2 | 4 a 6 | **feito**: `raiz/titulo/contexto.py`, quartis e cercas de Tukey por município, cartório e dono (documento mascarado) e auditoria de soma das glebas e área redonda (ha e alqueires) |
| 6 | No robô de aceite, pedir a localização da sede com o botão do WhatsApp e testar se o ponto cai dentro do polígono | robô de aceite (E7) e polígono do imóvel | 3 a 6 | **feito**: o robô pede a localização com o botão do WhatsApp depois do aceite; o webhook confere o ponto contra o polígono do CAR e guarda só o resultado (`raiz/titulo/sede.py`, achado `sede.dentro_do_imovel`), nunca o ponto |
| 7 | Extrator de certidão de inteiro teor (OCRmyPDF mais modelo com esquema fixo) que monta a cadeia, marca quebras e buracos e guarda o recorte da página de cada achado (molde do TitleChain). | passo 6 | 8 a 12 | **feito** (PR #24): `raiz/documentos/certidao/`; o modelo da Anthropic lê o PDF, inclusive escaneado, no lugar do OCRmyPDF, e guarda a página de cada ato (não o recorte) |
| 7 | Laudo HTML ou PDF por imóvel a partir da tabela de achados, da nota e das explicações | passos 4 a 6 | 4 a 6 | **feito**: `raiz titulo laudo` (`raiz/titulo/laudo.py`): HTML e PDF pelo LibreOffice, com nota, decisão, triagem, terra, regularização, sede, achados por fase com quem confirmou, cadeia ato por ato sem nome, consultas em WARC e explicações |
| 8 | Regra de triagem 'checagem rápida ou busca completa' (estilo Fannie Mae) e registro da previsão para comparar com a certidão depois. | passo 7 | 2 a 3 | **feito**: `raiz/titulo/triagem.py` (regra `triagem_titulo.yaml`): rápida, completa (com motivos e o que pedir) ou regularização; a chance de problema é congelada como previsão (`triagem_titulo`) e o gabarito vem quando todas as certidões do imóvel forem lidas |
| 9 | Pedir convênio ao ONR (oficioeletronico@onr.org.br), testar na homologação e ligar o Monitor Registral às matrículas acompanhadas. | nenhum (pode começar no dia 1) | 2 a 3 de trabalho, mais a espera da resposta do ONR | parcial: pedido pronto em `docs/pedidos/onr-convenio.md`; o envio é do fundador |

Novo, para destravar a posse (o maior gargalo dos lotes): **regularização da posse** por imóvel (`raiz/titulo/regularizacao.py`, `regularizacao_<mun>.csv`): classe (em titulação, pronta para pedir, falta georreferenciamento, pendente, impedida), órgão, próximo passo, evidência de ocupação antes de 22/07/2008 pelo PRODES, gratuidade, alternativa de usucapião, chance e prazo a priori congelados como previsão e gabarito automático quando a matrícula aparece; entra na oferta e no quadro "o que destrava o lote". A matrícula conferida (`raiz/documentos`) agora chega à carga e baixa o risco da terra (selo prata).

Feito na main fora desta tabela: caminho da terra com risco por imóvel (`raiz/terra.py`, `terra_<mun>.csv`), terra pública para restaurar (`raiz/terra_publica.py`) e conferência da certidão com o `certidoes_<mun>.csv` e saída `matricula_<mun>.csv` (`raiz/documentos/`). Situação conferida em 12/11/2026.

## E6. Quem compra

| Ordem | Passo | Depende de | Horas |
|---|---|---|---|
| 1 | Baixar o CSV do SIGSIF, filtrar ativos, contar por classe e geocodificar por CEP e endereço | nada | 3 a 6 |
| 1 | Subir um OSRM local com perfil de caminhão a partir do OpenStreetMap do Brasil (por região se a máquina não aguentar o país inteiro) | nada | 4 a 8 |
| 2 | Subir GraphHopper com o PBF do Brasil, perfil truck e estrada de terra mais lenta; gerar isócronas de 2, 4, 6 e 8 horas por frigorífico | E6 passo 1 | 4 a 8 |
| 2 | Montar a matriz fazenda (centroide do CAR) até frigorífico, laticínio e curtume (Trase facilities) pelo serviço Table em lotes retomáveis, copiando build_osrm_matrix.py do Ontario | E6 passo 1; E2 (centroides) | 4 a 6 |
| 3 | Medir a cobertura de OSM (taginfo e pyosmium), Overture e FSQ contra o SIGSIF com junção por nome e distância (receita World-POI) | E6 passo 1 | 4 a 8 |
| 3 | Rodar o Huff ponderado pela capacidade da planta (copiar planning.py do Ontario, ou a biblioteca huff com a matriz pronta) | E6 passo 2; E4 (rebanho por fazenda) | 4 a 8 |
| 4 | Calibrar o Huff com as áreas observadas da Trase e a capacidade de abate (método T-Huff), com limite de distância do jordan-hsa | E6 passos 2 e 3 | 6 a 10 |
| 4 | Calibrar lambda e gama com as supply sheds da Trase como fluxo observado (máxima verossimilhança por fluxos da huff, roteiro do T-Huff ou fit do scikit-mobility) | E6 passo 3 | 6 a 10 |
| 5 | Desenhar bacias de compra pelos fluxos com Leiden restrito (graspologic) e calcular o índice de localização de cada bacia | E6 passo 4 e dados de fluxo da Trase | 4 a 8 |
| 5 | Coletor do ComexStat por município (NCM 0201 e 0202), só quando a data de atualização mudar | nenhum | 4 a 6 |
| 5 | Aplicar a restrição de capacidade (CFLP do spopt-r ou a mesma formulação em PuLP) para não mandar mais boi do que a planta abate | E6 passo 4 | 6 a 10 |
| 6 | Coletor incremental do PNCP pelos endpoints /atualizacao com janela de 10 dias e pedaços atômicos | nenhum | 4 a 8 |
| 6 | Adicionar o índice 2SFCA (pressão de compra) e o Monte Carlo de risco de capacidade (queueing.py do Ontario) e gravar cada previsão com data para a E8 | E6 passo 5; E8 | 3 a 5 |
| 7 | Ranking de compradores com CatBoostRanker usando cat_features | passos 5 e 6 | 4 a 6 |

## E7. Agentes e operação

| Ordem | Passo | Depende de | Horas |
|---|---|---|---|
| 1 | Clonar o agent-service-toolkit, trocar o agente de exemplo pelo grafo da Raíz e ligar o checkpointer Postgres; rodar o smoke_test.sh. Feito no desenho do toolkit (MIT), sem clonar: API FastAPI (raiz/api.py), grafo do aceite do dono em LangGraph (raiz/agentes/aceite.py), checkpointer no Postgres cifrado com AES no esquema pessoal (raiz/agentes/memoria.py); o smoke test é testes/test_aceite.py | nada | feito |
| 2 | Pausar o pedido de aceite com interrupt() e expor a retomada {resume, thread_id} usando o código do CAR como thread_id (padrão do GeopoliticAI). Feito: cada espera do dono é um interrupt(), thread_id = código do CAR, retomada por /aceites/{cod_imovel}/responder e /proposta e pelo webhook do WhatsApp; nenhuma mensagem sai sem aprovação | E7 passo 1 | feito |
| 3 | Ligar o Langfuse e medir custo por fazenda e por município a partir dos rastros (como o Ezra mede custo por turno). Feito: Langfuse próprio (infra/docker-compose.langfuse.yml), uma geração por chamada com sessão = código do CAR e texto mascarado (raiz/modelos/rastro.py); custo com o genai-prices em operacao.chamada_modelo, somado por tarefa, fazenda, município e modelo (`raiz operacao custo`) | E7 passo 1 | feito |
| 4 | Colocar um check do Healthchecks por lote municipal (início, sucesso, falha com log) e um canal de alerta que não dependa do próprio servidor. Feito: raiz/operacao/healthchecks.py e lotes.py (um rid por município, fim do log mascarado, check criado no primeiro ping), usados pelo funil, coleta, carga e executor; canal fora do servidor = healthchecks.io com e-mail e ntfy (docs/operacao.md) | E7 passo 1 | feito |
| 4 | (vigilância) Vigilância diária das fazendas e dos projetos (raiz/vigilancia/): MapBiomas Alerta, FIRMS NOAA-20/21, embargos do Ibama, DETER e PRODES cruzados com os polígonos do Release dados e dos projetos; perda em área de projeto com o prazo da Verra (aviso em 30 dias, relatório em 2 anos), rascunho do relatório no modelo v5.0 e aviso ao cliente; cada alerta com a versão da regra e marcação verdadeiro ou falso; rotas /vigilancia/... e agenda diária no GitHub Actions publicando no Release vigilancia (privado cifrado) | Release dados | feito |
| 4 | (cena-alvo, passo 9) Alerta do pedido salvo: fazenda nova que melhora o lote (diz quais entraram e se são novas na base) e fazenda do grupo com desmatamento ou embargo novos da vigilância diária, matrícula cancelada nas certidões lidas (raiz/vigilancia/pedidos.py) ou problema que o motor refez; o mesmo fato nunca repete; aviso no painel e e-mail e, com grupo em formação ou fechado, também WhatsApp (simulado até haver enviador); `raiz pedidos ciclo` traz o estado da vigilância antes do vigia | vigilância, pedido de lote (E3 passo 10) | feito |
| 5 | Gravar as previsões no formato do hub e publicar o painel de acerto copiando a configuração do flusight-dashboard. Feito: `raiz aprendizado hub PASTA` grava aprendizado.previsao e os gabaritos no formato do hubverse (esquemas v6.0.0: hub-config, model-output por modelo e versão, model-metadata, target-data/oracle-output.csv; faixa P10/P50/P90 como quantile, chance e categoria como pmf, número como mean) e o site-config, predevals-config e predtimechart-config no molde do flusight-dashboard (CC0); painel de acerto com WIS, cobertura do P10 a P90, Brier, log score e acerto por modelo, versão e alvo, a versão na frente por alvo e o acerto da vigilância (/acerto/placar com token e /painel/acerto; `raiz aprendizado acerto`). Fica no servidor (as previsões dizem quem aceitou) | E7 passo 3; E8 | feito |
| 6 | Montar o backoffice do fundador (saúde, custo do mês contra orçamento, logs por fazenda) no estilo do Ezra, só leitura. Feito: raiz/operacao/backoffice.py com /backoffice/resumo (saúde, lotes em 24 h e parados, vigilância, custo do mês contra o orçamento com projeção, filas, alertas abertos), /custos, /lotes, /alertas e /fazenda/{cod} (modelos e custo, cascata, revisões, aceite, mensagens sem texto, pedidos, lotes, vigilância), página /painel/backoffice e `raiz operacao painel` | E7 passos 3 e 4 | feito |
| 8 | Extração de matrícula com BAML (SAP) e cache calibrado com MAPIE. Feito com extrator estruturado próprio: a extração existe sem BAML (raiz/documentos/certidao: leitura pela API da Anthropic com esquema fixo, conferência por regras com o certidoes_<mun>.csv, situação conferida, divergente, cancelada ou revisar, e placar por modelo e versão); **feito no código:** cache por PDF/receita em `raiz/documentos/certidao/cache.py`, escore numérico, MAPIE LTT e decisões auditadas; só reutiliza acima do corte da conferência integral aleatória, reconferindo motor/regras/data. Operação: colher gabaritos reais e calibrar; sem corte aprovado, relê | Langfuse para medir antes e depois | feito no código; ativação por gabaritos reais |
| 9 | Escalonamento de alertas (Healthchecks para ntfy e, se houver segunda pessoa, GoAlert). Feito: raiz/operacao/alertas.py e escada versionada em raiz/regras/padroes/alertas.yaml (ntfy na hora, ntfy urgente em 30 min, segunda pessoa no GoAlert em 2 h, repetição até 8 envios), um alerta por problema (lote que falhou ou travou, orçamento, vigilância atrasada ou com erro, prazo da Verra, filas paradas, grupo com fazenda com problema), estado que passou fecha sozinho, reconhecer e resolver pela API e pelo terminal; sem tópico do ntfy, envio simulado e registrado | Healthchecks | feito |
| 10 | (rodada 10) Qwen3-4B só para classificação curta; tarefa com várias chamadas de ferramenta vai ao Haiku ou ao Sonnet. Feito: rota em raiz/regras/padroes/cascata.yaml e raiz/modelos/rota.py (até 6 campos de lista fechada ou sim/não, até 400 tokens, sem ferramenta); o resto vai ao Haiku sozinho (via direto), com o Sonnet de reserva; Pedido.ferramentas conta as chamadas | passo 1 | feito |
| 10 | (rodada 10) Teste próprio em português: 30 a 200 tarefas, 3 tentativas seguidas por tarefa, 15% das tarefas sem resposta válida (o modelo tem de dizer que não sabe). Feito: raiz/modelos/avaliacao/banco.yaml (120 tarefas do aceite com o prompt de produção, 18 sem resposta válida) e `raiz modelos avaliar` (acerto, acerto nas 3 tentativas, consistência, abstenção correta, custo); rodada real concluída em 12/11/2026: 360 respostas, intenção 67,92% e compreensão 43,33%, sem falhas técnicas; Haiku pendente por ausência de credencial local | passo 3 | feito |
| 10 | (rodada 10) Cascata por confiança: só os 20 a 30% menos confiantes sobem de modelo (corte calibrado no teste acima). Feito: confiança dos logprobs do llama.cpp (raiz/modelos/confianca.py), via confianca na cascata, `raiz modelos calibrar` grava cascata_cortes.yaml (só de modelo local, com acerto mínimo de 95% no que fica), migração 0021 e alerta quando a subida sai da faixa. Rodada real de 12/11/2026 rejeitou todos os cortes: nenhum atingiu 95% no acerto retido. YAML gerado com metadados reais e cortes vazios; mantém votação. Medida empírica no mesmo banco, sem garantia fora da amostra | teste acima | feito |
| 10 | (rodada 10) llama.cpp compilado com llguidance para a gramática JSON. Feito: infra/llama/Dockerfile (tag b12300, LLAMA_LLGUIDANCE=ON) no serviço llama do docker-compose; build real validado em cloud: corrigido cabeçalho do llguidance, Rust 1.100.0 e CA efêmera; `/health`, versão e JSON Qwen reais passaram. Instalação em produção depende de acesso | passo 1 | feito |

## IA. Plataforma para agentes das empresas

| Ordem | Entrega | Situação |
|---|---|---|
| A | API paga: 3 testes por empresa, sinal Pix e contrato, cobrança/estorno, limite SlowAPI, CLI e privacidade | **feito no código**, PR #45 com CI verde (1.072 testes Python); migração 0028 após o calendário |
| B | MCP oficial Python 2.3.0/protocolo 2026-07-28 no mesmo app, sete ferramentas e resumo único até 8 KiB | **feito no código**, base do PR #69 com CI verde (1.384 testes Python), acrescida de `consultar_ficha` para releitura de CAR já adquirido, sem nova tarifa; descoberta e chamadas testadas com o cliente oficial |
| C | OAuth 2.1/Keycloak; consultar/pedir/reservar, reserva desligada até administrador da empresa habilitar | **feito no código**; JWT, emissor, audiência, PKCE e isolamento testados; produção depende da configuração da instalação |
| D | Fila durável, Idempotency-Key, Standard Webhooks, aprovação humana/Pix/JWS, OpenTelemetry | **feito no código**; testes de concorrência, queda do processo, assinatura e prazo; conta/API/worker precisam da mesma base e cofre |
| E | Gabarito de 24 tarefas, quatro sessões por tarefa, meta pass^4 ≥ 80% e zero chamada proibida | **feito**: gabarito e avaliador; desempenho de agente real ainda não medido |
| F | Piso de reversão 20%, REDD+ jurisdicional, CLPI 50%/70% e revisão humana | **feito no código**, com evidência vigente e bloqueio quando falta dado; camada oficial precisa ser carregada pelo operador |
| G | Recálculo dos 144 municípios do Pará pelo Actions e publicação no Release | responsabilidade exclusiva do chat "Lote e números", por orientação do fundador; este chat não altera execução nem Release |

Operação e limites: `docs/agentes-ia.md`, `docs/trabalhos-agentes.md`, `docs/eventos-agentes.md` e
`docs/avaliacao-agentes.md`. O Pix só é gerado após aprovação de uma pessoa autenticada. Recibo Ed25519
comprova aprovação, não pagamento. Sem SMTP, chave de assinatura ou evidência territorial, a ação fica indisponível.


## E8. Aprendizado contínuo

| Ordem | Passo | Depende de | Horas | Situação |
|---|---|---|---|---|
| 1 | Criar o projeto SQLMesh a partir do pipeline dlt (sqlmesh init -t dlt) apontando para o PostGIS | E1 passo 4 | 2 a 4 | a fazer (o back-end seguiu com executor próprio, sem SQLMesh) |
| 2 | Modelos do funil por município (INCREMENTAL_BY_PARTITION por cod_municipio) e resultados por imóvel (INCREMENTAL_BY_UNIQUE_KEY cod_imovel e ano); interseções caras pré-calculadas em modelo próprio (como o brewgis) | passo 1 | 8 a 12 | parcial: o executor refaz por município só o que mudou e a carga grava por rodada no esquema `funil` (`raiz/executor/`, `raiz/carga.py`), sem SQLMesh |
| 3 | Fila de municípios ou células sujas alimentada pelo diff da E1, job que esvazia a fila em lotes e reconciliação completa semanal (padrão osmpbudynkiv2 e osm2pgsql) | passo 2 e E1 passo 7 | 6 a 10 | **feito**: `raiz/coleta/fila.py` (sujos primeiro, disjuntor de 15%, reconciliação mensal em vez de semanal), `raiz/funil/manifesto_blocos.py` e `raiz/executor/agenda.py` |
| 4 | Tabela única de previsões: previsão ao vivo e folds de backtest juntos, com model_version, data de corte, horizonte e hash da receita (padrão OCF e PostHog) | passo 2 | 4 a 6 | **feito**: `aprendizado.previsao` e `aprendizado.lote_previsao` (migração 0002), `raiz/aprendizado/registro.py` e `congelar.py` |
| 5 | Teste por tempo: folds anuais que só leem dados 'como estavam' na data de corte (filtro _dlt_valid_from <= corte e _dlt_valid_to > corte no scd2) | passo 4 e E1 passo 4 | 8 a 12 | parcial: `raiz/aprendizado/folds.py` com `como_estava` (scd2 da coleta num dia) e folds anuais da calibração (`raiz aprendizado folds`), que só usam gabarito observado até o corte e congelam o recalibrado como backtest; **feito no código:** captura automática no executor com banco e reexecução do motor, FLAG, restauração, regularização, triagem e rebanho a partir de retratos scd2, sem ler fontes/caches atuais (`raiz aprendizado reexecutar`); `arquivar-fold` grava retratos com hora real e catálogo. Captura também em Actions sem banco: retratos imutáveis, publicação periódica/final em Releases diários e importação na sincronização, com datas observada/registrada separadas e intervalos preservados na chegada atrasada. Falta acumular histórico real desde as próximas execuções; não retrodata tarefas antigas. Modelos só rodam com todas as fontes disponíveis no corte |
| 6 | Campeão e desafiante: portão de promoção com score probabilístico e calibração dentro de tolerância, promoção automática com intervalo, trava e volta atrás manual; nota só quando o horizonte amadurecer | passo 5 | 6 a 10 | **feito**: migração 0025 e `raiz/aprendizado/campeao.py`: portão com pares maturados, bootstrap pareado e ECE, promoção automática com trava e intervalo de 30 dias, volta atrás à mão (`raiz aprendizado campeao/promover/voltar/travar`) |
| 7 | Orquestração: Dagster com sensor de dado novo, partições município x ano, condição de automação 'needs_updating' e memória declarada por asset (ou cron com sqlmesh run, se preferir não usar Dagster) | passos 3 e 6 | 6 a 10 | parcial: agenda por cron (`raiz executor vigiar`, `raiz/executor/agenda.py`), sem Dagster |
| 10 | Modelo de sobrevivência do aceite do dono (lifelines) e regra de canário para modelos novos no SQLMesh | histórico de contatos | 5 a 8 | parcial: chance de aceite por perfil, beta-binomial (`raiz/pedidos/aceite.py`); **feito no código:** tempo até aceite com lifelines, recusa competitiva e censura, corte temporal estrito, previsões congeladas e placar Brier (`raiz/pedidos/sobrevivencia.py`); exige 30 contatos reais/5 aceites e seguimento suficiente. Otimizador mantém beta-binomial até avaliação real |
| 1 | (rodada 10) Gravar a chance de escolha em cada conferência (gabarito), para pesar a amostra | nada | feito no esquema | **feito** no esquema (migração 0007) |
| 6 | (rodada 10) Sorteio das conferências em duas metades: uma aleatória e uma dirigida aos mais duvidosos | passo 4 | 2 a 4 | **feito**: migração 0024 e `raiz/aprendizado/sorteio.py`: metade aleatória e metade dirigida (PPS pela dúvida), chance de escolha no gabarito, `raiz aprendizado sortear` com as matrículas a pedir |
| 6 | (rodada 10) Calibração por UF e faixa de área (MCGrad, conferir licença) | passo 5 | 4 a 6 | **feito** sem MCGrad (licença não conferida): `raiz/aprendizado/calibracao.py`, medida e isotônica por UF e porte puxada para o total (`raiz aprendizado calibracao`) |
| 6 | (rodada 10) Área apta com intervalo pelo estimador de Olofsson (mapaccuracy, conferir licença) | sorteio acima | 3 a 5 | **feito** sem mapaccuracy: `olofsson` em `raiz/aprendizado/sorteio.py` (`raiz aprendizado olofsson`); com fazendas muito grandes o intervalo cobre ~85%, não 95% |

Feito na main fora desta tabela: aprendizado do valor para quem restaura (`raiz/restauracao_aprendizado.py`), da vigilância (`raiz/vigilancia/aprendizado.py`) e das leituras de documento (`raiz/documentos/aprendizado.py`), todos gravando no mesmo `aprendizado.previsao`. Situação conferida em 12/11/2026.

## E9. O que as pessoas veem

As cinco entregas de Telas e mapa foram integradas com CI verde em 12/11/2026: cena-alvo (#67), cobertura diária
(#70), ficha visual (#71), celular/acessibilidade (#73) e domínio/Markdown (#74). A publicação do site acompanha
a retomada coordenada da migração privada (#72). Lotes ainda ausentes no Release, domínio real e calibração
com cartas reais permanecem explicitamente pendentes; contato com o dono fica na fase final.

Cena-alvo com publicação real (12/11/2026): **feito no código**. O formulário parte de um milhão de créditos no
Pará e permite teto em US$ por crédito. O site lê o ponteiro `lote_PA_central_r11.json`, publicado pelo chat
Lote e números, e apresenta as três alternativas, P10/P50/P90, TIR do fluxo, hectares, fazendas, pendências e
“o que destrava”. O cenário publicado fica identificado como referência; um novo teto ou filtro exige recálculo
na API. Sem publicação, aparecem a cobertura territorial real e o aviso, sem resultados simulados.
Mapa das três opções com cores e traços distintos aceita somente geometrias autorizadas pela API, de fichas já
desbloqueadas pelo próprio cliente e fora de reserva alheia. Consultar o mapa não consome novos créditos.
Contato com donos permanece reservado à fase final. A calibração E9 com 30 cartas reais continua pendente.

Entrega do chat **Ficha da fazenda** (12/11/2026; detalhes em
`docs/passagem/ficha-da-fazenda.md`):

| Entrega | Situação |
|---|---|
| Ficha de prospecção pelo CAR, só terra, caminho/pendências, sobreposições, embargos, séries, restauração, crédito líquido P10/P50/P90, TIR e risco, com fonte e data por medida | **feito** no código: contrato fechado, ausências explícitas, sem dados pessoais |
| Busca nacional combinando estado, município, bioma, área, terra, crédito e risco; pequenas preservadas e agrupamentos indicados | **feito** sobre a cobertura processada; vizinhança do agrupamento ainda precisa de conferência |
| Botão pedir contato, registro interno na Raíz | **feito**; não envia contato nesta etapa |
| Créditos pagos, Pix confirmado no provedor, débito atômico/idempotente, limites persistidos contra raspagem | **feito** no código; operação exige catálogo de preços e chave Pix de produção |
| Agregados abertos no site, nova ficha completa só na API autenticada e paga | **feito** no site e nas rotas novas; migração do Release histórico e contrato básico descritos na continuação abaixo |
| Integração da nova ficha com navegação do mapa | **feito**, sem reescrever o mapa; produtor precisa de autenticação própria para voltar a acessar detalhes no site |

Continuação de Ficha da fazenda (12/11/2026; validação e operação na passagem):

| Entrega | Situação |
|---|---|
| Contrato aberto com agregado municipal/estadual e CAR/situação básica; camadas exclusivas e retratos históricos do aprendizado no arquivo privado | **feito**: 40 originais preservados no privado e 22 assets básicos publicados; SHA-256 e bloqueio anônimo conferidos, provas em `docs/dados-publicados.md`; 18 artifacts preservados/removidos e 33 caches antigos descartados; retomada do Pará reutiliza as dez fatias preservadas |
| Preços em YAML provisório, Pix em teste e roteiro de ativação no servidor | **feito**; valores a definir pelo fundador, venda real fechada |
| Comparar até cinco fichas pagas, salvar busca/avisos internos e PDF com fontes/datas | **feito** no código; buscas salvas na migração 0031 após 0030 da plataforma de agentes; agendar verificação no servidor ao implantar |
| `consultar_ficha` compartilhado pela API e MCP oficial, alinhado à passagem Produto e regras | **feito**; ferramenta registrada no servidor corporativo, com OAuth, gates e releitura de CAR já pago, sem tarifa nova |

Site legível por agentes (12/11/2026): **feito** — `llms.txt`, `robots.txt`, páginas Markdown do Brasil, estados,
municípios, produtor, serviço, fontes e privacidade; alternates no HTML; JSON-LD `Dataset`, `Service` e `Offer`
sem transformar premissa em preço comercial. API aceita `text/markdown` nas leituras, preservando Bearer e
privacidade da ficha pública. Lighthouse 13.6.0, categoria experimental `agentic-browsing`, no CI com verificação
separada de arquivos, links e dados estruturados. No Pages de projeto, `robots.txt` em `/Raiz/` não controla a raiz
da origem; isso depende do site da conta ou de domínio próprio.

A publicação Markdown segue a mesma regra do site agregado: nenhuma ficha individual aberta por CAR.

Celular e acessibilidade (12/11/2026): **feito** no código. Entrada nacional em SVG com estados acessíveis,
sem baixar WebGL ou geometria municipal antes de aproximar; rotas carregadas ao abrir. Navegação disponível a 360 px,
atalho para o conteúdo, foco após troca de tela, alça e controles com 48 px, tabelas roláveis pelo teclado.
A entrada do produtor já entrega o formulário em HTML e carrega a ficha apenas ao receber um código do CAR.
CI verifica axe WCAG 2.1 A/AA, busca e gaveta pelo teclado, novo pedido com filtros, comparação pública,
lotes autorizados, ficha desbloqueada e prospecção. A contagem do mapa vem de um índice leve, antes de carregar os contornos.
Lighthouse mobile a 360 px conserva rede/CPU simuladas: três execuções fixas por página (Brasil, entrar, novo pedido, prospecção e produtor),
mediana de desempenho >= 90 e acessibilidade >= 90 em todas. A série integrada teve medianas 100/96/98/98/100
e acessibilidade 100 nas quinze medidas; 175 testes do front, Pages, cena-alvo e ficha/prospecção passaram.
Relatórios completos (incluindo outliers), axe e capturas ficam nos artefatos.
A revisão visual da ficha mantém escala e atribuição em posições separadas, crédito inteiro e zoom com 48 px;
Playwright cobre a legenda Copernicus longa a 360 px, além de axe.
As verificações automatizadas não substituem avaliação humana de todos os critérios WCAG; a calibração E9 de
compreensão com 30 cartas reais continua pendente e nenhum contato com dono é disparado por estes testes.

Domínio próprio configurável (entrega 5 de Telas e mapa, 12/11/2026): **feito no código**. `RAIZ_DOMINIO` validado
gera CNAME, base `/` e URLs canônicas HTTPS do painel, produtor e JSON-LD. Sem domínio, o build deriva o caminho
do repositório e mantém o Pages atual. CI cobre subcaminho e raiz, com navegação, Range, Markdown, robôs e CNAME;
o formulário nativo do produtor funciona sem JavaScript nos dois caminhos. Os seis jobs de qualidade e o portão
mobile de 15 medições são preservados antes da segunda publicação de teste.
Ativação do domínio, DNS e HTTPS permanece pendente de um domínio real; nenhum foi inventado nem configurado.

Entrega do mapa nacional (12/11/2026): o workflow publica os desenhos de todos os municípios com dados no Release,
reaproveitando os GeoParquet do motor como GeoJSON gzip. Fundo PMTiles compartilhado por UF e base nacional em
overzoom; busca estática por nome/IBGE/CAR e aviso de desenho ausente. CI com Playwright em `/Raiz/`: Parauapebas,
zoom, polígonos coloridos, HTTP Range e zero 404. Build limita fichas pré-geradas e publica só o manifesto de geometrias,
com portão de 950 MB. Polígonos permanecem por município enquanto couberem; não foi necessário tippecanoe nesta rodada.

A entrega da ficha mantém as bases e limites do mapa nacional, mas restringe os detalhes por CAR à API paga;
a publicação pública usa agregados municipais e situação básica por CAR, sem camadas exclusivas.

Cobertura diária do mapa (12/11/2026): **feito no código**. A rodada diária descobre municípios e UFs do Release,
incluindo os novos sem lista fixa. O painel do Brasil e de cada estado informa quantos municípios têm desenho
na base e quantos ainda aguardam; separa esses totais dos municípios processados. A data de geração do mapa e
a data dos dados publicados no Release aparecem separadas, sem substituir data ausente pela data de hoje.
O manifesto aberto expõe só cobertura por município, mantendo os desenhos individuais no acesso pago.
Teste incremental cobre município novo, UF nova e chegada posterior do desenho; Playwright confere contagem,
datas e avisos de acesso restrito ou desenho ausente. A migração do Release para cadastro básico é reconhecida
pelo leitor e pela geração de geometria; CSVs retirados não sobrevivem no cache da rodada seguinte.
A agenda ainda sem coleta é publicada como indisponível, evitando 404 na navegação do mapa.

A verificação no navegador com o Release real conferiu a consulta do Pará: 144 municípios, 345.870 fazendas e
9.484.092 ha com potencial de restauração, zero 404 e zero erro de JavaScript. Oferta de créditos e TIR continuam
pendentes; o texto da ausência não apresenta o cenário como já publicado.

Conferido contra a main em 12/11/2026: "feito" quer dizer que o código está na main; "parcial" diz o que existe e o
que falta, com as horas do que falta. O site público (https://bernardoemmel.github.io/Raiz/) mostra o que o front já
faz sem back-end.

| Ordem | Passo | Depende de | Horas |
|---|---|---|---|
| 1 | Medidor de legibilidade: copiar contagem e fórmulas do ALT (sem PyMuPDF), calcular as três versões do Flesch (ALT, LanguageTool, Martins) e guardar todas | nada | feito (raiz/legibilidade.py, docs/legibilidade.md; nota guardada em cada mensagem ao dono e em cada aviso; `raiz legibilidade`); falta uma lista aberta de palavras comuns para o Gunning Fog |
| 1 | Gerar a ficha de cada fazenda em JSON (rows.json) a partir do funil, com os campos que o vídeo, o cartão e o texto vão usar | E2, E3, E5 | feito (`raiz ficha lote`, raiz/fichas_lote.py: a ficha de cada fazenda, o rows.json do cartão e do vídeo, o manifesto e o índice, só do município que mudou) |
| 1 | Trocar o cartão da ficha de Satori + resvg para Takumi com saída WebP (manter Satori só onde precisar de SVG) | modelo do cartão já existente | feito (servicos/cartao/render.mjs e raiz/publico.py: prévia, retrato e adesivo também em WebP, com cerca de metade do peso; a prévia do WhatsApp segue em JPEG; não há Satori no código) |
| 2 | Servidor LanguageTool em contêiner, só com as regras de estilo e legibilidade do português, chamado antes de todo envio | passo 1 | feito (infra/languagetool, serviço "revisor" do compose; raiz/revisor.py guarda os avisos de estilo com a nota de cada mensagem ao dono e de cada aviso) |
| 2 | Produzir a imagem antes e depois de cada fazenda (Sentinel-2 por STAC, lógica do Sentinel2Timelapse-QGIS) e o mapa do imóvel | E9 passo 1 | feito (raiz/satelite.py: Sentinel-2 hoje, Landsat em 1985 e 2008, simulação; testes/test_satelite.py) |
| 2 | Ficha em Preact com 'mapa sob demanda' (padrão Uber Lite): texto, cartão WebP e ThumbHash na primeira abertura; MapLibre e PMTiles só no toque | passo 1 | feito (front/produtor/src/Ficha.tsx: capa de satélite WebP com o borrão do ThumbHash na primeira abertura, texto e contorno pela polyline sem baixar mapa, MapLibre e PMTiles só no toque; raiz/thumbhash.py e a capa em raiz/satelite.py; a página do servidor usa o mesmo borrão sem JavaScript) |
| 3 | Portão no estilo da lei da Flórida: nota mínima calibrada com 30 cartas reais, sem contar termos do glossário e tabelas, nota gravada no laudo | passos 1 e 2 | pendente: fundador confirmou em 12/11 que ainda não há conjunto pronto das 30 cartas; não calibrar com exemplos sintéticos |
| 3 | Escrever o texto por fazenda e por município com frases comparativas por índice (método do Census Reporter) dentro do kit do ONS, com modelo de campos abertos como o do g1 | E9 passo 1 | parcial: frases por índice e posição (front/compartilhado/comparacoes.ts) e frase do município (raiz/municipio_dados.py); falta o kit do ONS com campos abertos (4 a 6) |
| 3 | Gravar no lote anual, por fazenda: ThumbHash da miniatura, perímetro em polyline (6 casas), Plus Code da porteira e link omaps.app | funil E2 com o polígono final | feito (`raiz ficha lote`: polyline de 6 casas, ThumbHash da capa, Plus Code e link omaps.app de um ponto dentro do imóvel em cada ficha, raiz/localizacao.py; o ponto exato só sai no rows.json depois do aceite; a porteira de verdade vem do dono ou da visita) |
| 4 | Modelos de texto com campos condicionais no formato do GOV.UK Notify, mais extenso.js ou num2words, pluralizador e verbecc; aviso curto na ordem fonte, fato, fazenda, prazo, o que fazer | passo 3 | parcial: o aviso curto na ordem fonte, fato, fazenda, prazo e o que fazer existe (raiz/vigilancia/aviso.py, raiz/agentes/textos.py); faltam os campos condicionais e o número por extenso (3 a 6) |
| 4 | Gerar cartão PNG e laudo PDF por fazenda com Takumi (takumi-js e takumi-pdf) a partir do mesmo modelo | E9 passos 2 e 3 | parcial: cartões pelo Takumi (raiz/publico.py) e laudo PDF por docxtpl e LibreOffice (raiz/documentos/); falta o mesmo modelo para os dois (2 a 4) |
| 4 | Gerar KMZ por fazenda (perímetro, reserva legal e APP com cor) e o link do pacote regional do Organic Maps no envio do WhatsApp | passo 3 | 2 a 4 |
| 5 | Voz: criar uma voz fixa da Raíz no Qwen3-TTS (VoiceDesign) e gerar o áudio de cada carta em lote; Kokoro pf_dora como segunda opção no servidor | passo 4 | parcial: o vídeo é narrado pelo Qwen3-TTS com falante pronto (raiz/voz.py); faltam a voz fixa (VoiceDesign), o lote de cartas e o Kokoro (3 a 5) |
| 5 | Montar a composição do HyperFrames com data-var-text e data-var-src e rodar render --batch com --strict-variables e manifest.json | E9 passos 1 a 3 | 6 a 10 |
| 5 | Carga adaptativa: escolher vídeo HyperFrames ou cartão WebP pelo tipo de rede, economia de dados e memória (react-adaptive-hooks via preact/compat) | passo 2 | 2 a 3 |
| 6 | QR Code em cada documento levando a página com resumo, áudio e três perguntas prontas (desenho do SOFIA) | passo 5 | 2 a 4 |
| 6 | Envolver o render com cache e trava por CAR e ano (padrão do GitHub Unwrapped) e ligar ao envio por pessoa (padrão de planilha do GOV.UK Notify) | E9 passo 5; E7 | parcial: cache por código curto (raiz/publico.py) e trava por imóvel nas imagens de satélite; faltam a trava do cartão e do vídeo, a chave por ano e o envio por pessoa (2 a 3) |
| 7 | WhatsApp: mensagem com botão para o dono ligar (grátis) e agente de voz no Pipecat atendendo; baixar a tabela CSV em reais no painel da Meta para orçar as chamadas da Raíz | passo 5 | 6 a 10 |
| 7 | Manter tiles em MVT dentro do PMTiles; reavaliar MLT quando o caminho colunar (#8985) entrar no MapLibre GL JS | nada | feito (raiz/tiles.py e front/scripts/geo.py gravam MVT); reavaliar o MLT quando entrar no MapLibre |
| 8 | Passo de teach-back no aceite: o dono explica com as próprias palavras, o agente confere prazo, área e pagamento e só então pede a confirmação separada (código ou assinatura) | passo 7 | feito (raiz/agentes/aceite.py: avaliar_explicacao, reexplicar e pedir_codigo; testes/test_aceite.py), por texto no WhatsApp |
| 8 | Pacote offline mensal por município para técnicos: pmtiles extract e remendo com zstd --patch-from | PMTiles do Brasil e PWA com Workbox | 4 a 8 |
| 9 | Opcional: treinar uma voz Piper do zero só com dados CC0 (sem a voz lessac) para rodar em CPU e no celular | passo 5 | 6 a 10 de trabalho, mais o tempo de GPU |
| 11 | Página de aceite do dono com componentes do gov.br DS, grade de ícones (PyWaffle) e motivos específicos de 'não apto' | Preact | parcial: os motivos específicos de 'não apto' existem (front/compartilhado/motivos.ts, raiz/motivos.py); faltam a página de aceite e a grade de ícones (5 a 8) |
| 1 | (API do front) Rotas que o front espera (front/README.md, "Depois (API)"): /municipios, /municipios/{cod_ibge}/imoveis, /imoveis/{cod_imovel}, /ficha, /certidoes, /geo/{cod_ibge}/{municipio,imoveis,ti,uc,rios}.geojson e base.pmtiles com Range, servidas do PostGIS com os nomes de coluna dos CSV, CPF/CNPJ mascarados e Bearer; camadas do mapa carregadas por `raiz geo carregar` | carga do motor (fundação) | feito |
| 2 | (API do front) Cache por rodada (ETag pelo hash da rodada) e lista de imóveis em pedaços ou em formato colunar para município grande (São Félix: 2,8 MB comprimidos, 3,4 s) | passo anterior | 2 a 4 |
| 2 | (API do front) Divisa, TI, UC e rios vindos da coleta (E1) direto no PostGIS, no lugar dos arquivos do front/scripts/geo.py; um mapa base PMTiles do Brasil servido com Range | E1 | parcial: o mapa base do Brasil com Range está feito (raiz/mapa_base.py, /mapa/brasil.pmtiles); as camadas ainda vêm do front/scripts/geo.py (2 a 3) |
| 6 | (API do front) Fichas em JSON do lote anual (passo 1) servidas como arquivo estático; a API fica para o painel interno e para o que muda no dia | passo 1 | feito o lote administrativo (`raiz ficha lote`, dados/fichas/ em armazenamento privado). A entrega Ficha da fazenda retira fichas e CSV individuais do site; a ficha de prospecção passa pela API com sessão/crédito pago, e o site publica só agregados |
| 1 | (busca) Busca nacional pela API pelo código do CAR (inteiro ou começo, com ou sem pontos e traços) e pelo nome do município, no contrato de front/compartilhado/dados/busca.ts; índice por código normalizado; 6,7 milhões de imóveis sintéticos: pior resposta 0,49 s | carga contínua | feito |
| 1 | (busca pública) Busca no navegador por nome e código IBGE do município, sem depender de `/busca` no Pages; CAR leva à ficha paga | mapa nacional | feito |
| 1 | (busca) Carga contínua das saídas do motor por estado (`raiz vigiar`), só o município que mudou, com a versão anterior guardada | carga do motor | feito |

## Telas e mapa: ficha visual da terra

Entrega 3 da continuação de 12/11/2026, sobre a ficha paga do PR #52.

| Entrega | Situação |
|---|---|
| Mapa do imóvel com Sentinel-2, máscara e restauração hachurada | **feito**: a ficha autorizada carrega perímetro e camadas medidas pela API de prospecção. A máscara respeita furos do CAR e a hachura é recortada ao imóvel. A cena Sentinel-2 usa o gerador existente; composição mediana preserva o período inteiro e o método. Ausência de cena ou camada fica explícita, sem inventar desenho a partir de hectares. Recorte real de Parauapebas validado em 360 px; integração com o cadastro básico do Release e o selo do Calendário validada com 91 testes Python focados, 177 testes de front e Playwright. |
| Linha do tempo de uso e perdas | **feito**: anos disponíveis, medidas e fontes da ficha paga, além das tabelas completas. Ausência e zero são diferentes; a data de corte não substitui a data da fonte. |
| Acesso à imagem e ao desenho | **feito**: sessão individual e desbloqueio pago conferidos em todas as rotas, incluindo exclusividade. A imagem é buscada com Bearer, sem token na URL, com `private, no-store`; nenhuma lista ou imagem individual vai ao Pages. |
| Calibração E9 com cartas reais | **pendente**: ainda não existe o conjunto de 30 cartas anonimizadas com avaliação de compreensão. Esta entrega não inicia contato com proprietários. |

## Qualidade e segurança (12/11/2026)

| Entrega | Situação |
|---|---|
| Auditoria PRs #35–#44 integrados e revisão preventiva #45 ainda aberto; correções pequenas com regressões; Release completo e amostra do site | **feito**; evidência e limites em `docs/passagem/qualidade-e-seguranca.md` |
| Playwright no CI: link, milhão de créditos no Pará, 3 opções, interesse e Pix de teste com API/PostGIS | **feito**; serviços externos controlados, sem pagamento real |
| Dependabot, Gitleaks no histórico, licenças Python/npm/Rust obrigatórias, cabeçalhos, limite de chamadas e Presidio nos logs | **feito**; opção Valkey compartilhada, Presidio e restrições operacionais na passagem |
| CI paralelo com cache uv/npm/Chromium/LanguageTool, build público e coleção completa de testes | **feito**; zero skips ainda **parcial**: falta conjunto real de 144 tabelas desenvolvedor do Pará; demais dependências opcionais instaladas no CI |
| Instruções para proteger a main | **feito** em `docs/operacao.md`; ativação manual pelo fundador |

## Continuidade de documentos, vigilância e calendário (12/11/2026)

- **Feito:** aviso inicial à Verra em JSON e `.eml`, pela API, CLI e rodada diária, separado do relatório de perda. Preparar não envia nem registra `verra_avisada`. Rascunho URTX_LE1 para o desenvolvedor cliente em `docs/pedidos/urtx-le1-aviso-verra.md`, prazo **15/11/2026** registrado no projeto e no alerta interno. Campos desconhecidos: “a preencher pelo proponente”. A Raíz não é proponente e nunca envia; não depende de estado privado.
- **Feito:** passagens unificadas em `docs/passagem/continuidade-raiz.md`; PRs #35 e #44 já integrados; migrações do título/aprendizado corrigidas para 0022–0025.

- **Feito:** instalador idempotente de cron dos alertas a cada 15 minutos (`scripts/instalar_cron_alertas.py`), com trava de execução e caminho do ambiente. Instalação real no servidor continua pendente de acesso; nenhuma notificação externa foi enviada.

## Calendário da Raíz

| Entrega | Situação |
|---|---|
| Eventos com tipo, data/prazo, UF/município, fonte/link, coleta e confiança | **feito**: esquema `calendario`, migração 0027 após 0022–0025 do título/aprendizado e 0026 da prospecção; histórico, UID e sequência preservados nas retificações |
| Coleta diária de leilões rurais, penhoras, BNDES, ProFloresta+, Fundo Amazônia, concessões, crédito e SBCE/Verra/ICVCM/SBTi/EUDR | **feito**: 17 fontes oficiais em `raiz/calendario/fontes.yaml`, HTTP/PDF/Firecrawl opcional, workflow diário com snapshot no Release `calendario`; cobertura inicial e falhas explícitas, sem inventar prazos |
| Vínculo de leilão/penhora ao CAR | **feito**: CAR explícito, CNS+matrícula vigente ou interseção SIGEF; sem corte por tamanho; vínculo insuficiente fica pendente; CAR inferido fica interno, só CAR explícito no edital aparece na consulta pública; nenhum nome ou documento pessoal persistido |
| API e integração | **feito**: `GET /eventos` com tipo/estado/período/CAR, `GET /eventos.ics` e função Python `proximos_eventos` pronta; o calendário ainda não está registrado no transporte MCP, e o servidor pago oferece sete ferramentas, incluindo releitura de ficha já adquirida |
| Site e pedidos | **feito**: aba Calendário, filtros, fonte/data de coleta, feed, selos no mapa/ficha/tabela e aviso deduplicado aos lotes; ficha individual mantém acesso por créditos, e-mail/WhatsApp permanecem simulados. Publicação do site após a coleta |
| Agenda no servidor | **feito no código**: `scripts/instalar_cron_alertas.py --tarefa calendario --instalar`, diário com banco, trava e `.env`; instalação em produção depende de acesso ao servidor |

Limites verificados em 12/11/2026: DJEN/CNJ respondeu HTTP 403; diários estaduais começam por PA/MT; PDF escaneado sem texto ainda não tem OCR. Erro de fonte não elimina os eventos anteriores. Testes com trechos oficiais gravados e PostGIS; detalhes em `docs/calendario.md`.

## Continuidade de qualidade e segurança (12/11/2026)

| Entrega | Situação |
|---|---|
| Portões de dados/privacidade antes de publicar, Pandera MIT, colunas obrigatórias, faixas, áreas e saltos municipais | **feito**; resultados inválidos e arquivos privados sem contrato ficam bloqueados; Dados corrige/recalcula a origem |
| Locust MIT no CI com API/PostGIS real, latência, 429/Retry-After e recuperação | **feito**; perfil curto não é capacidade máxima de produção |
| Logs JSON com Presidio, /saude, limite compartilhado Valkey e GlitchTip próprio MIT | **feito**; testado localmente, configuração de produção documentada em operação |
| Injeção/latência/carga das ferramentas MCP | **parcial**; MCP/OAuth real com seis ferramentas, tempo e Locust verificados; corpus pronto, agente leitor de documentos aguarda Produto e regras |
| Revisão contínua dos novos merges | PRs #53/#56/#67/#54/#68/#70/#71/#73/#74 revisados e pequenos bugs corrigidos com teste; CI por push ativo, revisão horária não ativada por decisão do fundador |

- [x] Integração da entrega mobile com o Calendário: rota sob demanda, quatro links visíveis a 360 px, filtros
  com 48 px e teste CI de teclado/axe em três larguras; 186 testes do front e fluxos de ficha/lote aprovados.

- [x] Domínio integrado ao Calendário e ao cadastro básico: builds em `/Raiz/` e `/` e Playwright com feed ICS
  passaram sem 404; 187 testes do front e 10 de configuração aprovados. Domínio real continua não configurado.

A primeira execução no Actions identificou ausência de `rg` no runner; a verificação do Release inicial usa agora
`grep`, disponível na imagem padrão, preservando a interrupção em erros que não sejam Release inexistente.

- [x] Markdown do site preserva medidas ausentes e zeros explícitos; totais incompletos não são apresentados
  como totais completos. Regressões cobrem páginas estaduais/municipais e proteção de grupos pequenos.
