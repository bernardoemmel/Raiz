# Portão de qualidade dos arquivos publicados

A publicação do motor e da vigilância passa por `raiz/qualidade_dados.py`. A versão do contrato é
`colunas-2026-11-12`, transcrita de `docs/colunas.md`. Pandera (MIT) verifica as tabelas antes do upload.
Uma falha interrompe a publicação; o portão não remove fazendas, não recorta resultados e não troca valores por zero.

Para conferir pacotes prontos, depois de juntar todas as partes `.partNN`, execute:

```sh
uv run python -m raiz.qualidade_dados dados-entrada
```

O diretório deve conter o conjunto completo de arquivos candidatos, incluindo o pacote `imoveis` de referência
para cada município com complementos/geometrias. Diretórios extras, links, arquivos desconhecidos e membros TAR
fora de `<UF>/<arquivo>` impedem a publicação. TAR é lido sem extrair caminhos. O código de saída é 1 em falha.
A saída de erro mostra a regra e, quando disponível, o nome técnico do arquivo, sem valores das células.

## Contratos e faixas

- Todas as colunas estáveis declaradas para cada tabela são obrigatórias. Dado opcional de uma fonte ausente
  permanece nulo; a coluna continua presente. CAR e área de referência não podem ser nulos. Colunas numéricas novas
  são aceitas; texto novo exige inclusão expressa no contrato. O produto continua lendo pelo nome e tolerando adições.
- Áreas de componentes devem ser não negativas e menores ou iguais à área do CAR, incluindo complementos e
  atributos vetoriais. A tolerância de serialização é somente `0,000001 ha`. Áreas da matrícula inteira e do grupo
  são objetos diferentes, descritos no contrato, e não são comparadas com um único CAR. Custo e taxa por hectare
  também não são área. Nenhuma diferença raster/vetor é corrigida silenciosamente.
- Famílias P10/P50/P90 precisam estar completas, conjuntamente preenchidas ou conjuntamente nulas e ordenadas.
  `credito_liquido_tco2_ha_ano` é o P50 sem sufixo. `captura_total_tco2_ha_p50` e `custo_implantacao_ha_p50` são
  caminhos centrais isolados expressamente definidos no contrato; não se inventam faixas para eles.
- Porcentagens (`pct_*` e `*_pct`) ficam entre 0 e 100. TIR pode ser negativa (inclusive −100% quando o projeto
  não se paga), e declividade é uma razão entre distâncias que pode ultrapassar 100%; ambas seguem `docs/colunas.md`.
- Números não finitos, CAR duplicado em tabela com uma linha por imóvel, colunas repetidas e datas inválidas falham.
  Município usa o cadastro IBGE incluído no pacote; nome e código são comparados quando ambos existem.

## Saltos entre municípios

O portão compara a mediana de cada município em indicadores intensivos (taxa de carbono, crédito por hectare,
custo de restauração por hectare, captura, lotação, altura do pasto e uGPP). Com pelo menos cinco municípios do
mesmo tipo de tabela, bloqueia uma mudança acima de dez vezes ou abaixo de um décimo da mediana, quando o desvio
excede também oito MAD normalizados. Uma mediana zero não dispensa a detecção de um salto positivo.

É uma triagem de escala/unidade para revisão do chat **Dados**, não evidência científica de erro, nem comparação
geográfica de municípios necessariamente vizinhos. Totais de área e tamanho das fazendas não entram nessa regra.
Com menos de cinco municípios não há referência suficiente para essa comparação; as demais validações permanecem
ativas. A política deve ser calibrada com dados reais versionados antes de afirmar detecção de toda anomalia espacial.

## Formatos e privacidade

O validador lê CSV, Parquet/GeoParquet, todos os ladrilhos MVT dos PMTiles, JSON, JSONL, o KML público URTX e
`geo_<mun>.geojson`. Inspeciona também metadados Parquet, propriedades/valores vetoriais, chaves JSON repetidas,
comentários/caudas XML e atributos. CRS declarado precisa corresponder ao registro de autoridade conhecido;
IDs opcionais dos membros do datum são tratados como descritores técnicos. O XML não permite entidades externas.

CPF/CNPJ numérico ou alfanumérico reconhecido, contatos, credenciais e colunas pessoais bloqueiam a saída.
Campos técnicos têm domínio ou formato verificável; texto restante passa por Presidio. A classe cartográfica
`Aceiro <largura> m` da URTX tem contrato específico porque o NER a confundia com pessoa. Não há exceção genérica
para nomes em XML. `pagamento_dono` e `dono_rs_ha_ano` são métricas legítimas, não identificação do dono.

Presidio tem falsos negativos e não prova ausência absoluta de nomes livres. Não adicionar identificação pessoal
nem confiar em nome de coluna para tornar seu conteúdo público. Exportações administrativas privadas não possuem
contrato de upload e continuam fora do Release. Os portões específicos de outros Releases são documentados em
operação; a validação do motor não transforma SQLite, Markdown ou calendário em tabela do motor.

## Unidade de publicação e dados históricos

No executor, cada UF tem seus CSV, geometria, metadados, controle e `extra` validados antes do primeiro upload
referente àquela UF. Na vigilância, todos os arquivos públicos candidatos e o resumo são validados antes de tocar o
Release. O conteúdo privado só sai cifrado. Não existe transação distribuída entre assets do GitHub; uma falha de
rede posterior ou conflito no índice pode exigir nova tentativa. Várias UFs são unidades independentes.

Este portão não altera retroativamente assets ou logs remotos. A amostra atual já contém componentes maiores que
a área do CAR. O pacote AC auditado tem `data_atualizacao=0` em 648 de 3.849 imóveis de Acrelândia. O chat **Dados**
precisa tratar a origem, representar ausência como nulo e recalcular as áreas com a regra correta. Não há liberação
especial para republicar dados antigos que falham.
