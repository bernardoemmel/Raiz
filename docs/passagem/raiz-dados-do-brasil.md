# Passagem do chat "Raíz · Dados do Brasil" (processamento de dados)

Passagem original de 12/11/2026, 13h20 de Brasília. Retomada pelo Codex na mesma data, a partir da main.
Branch da entrega de formatos e procedência: `codex/dados-croissant`.
Branch seguinte, com as seis pendências E1/E2: `codex/dados-e1-e2`.

## O que este chat fez

| PR | O quê | Situação |
|---|---|---|
| #21 | `.github/workflows/processar-estados.yml`: o motor roda sozinho no GitHub Actions e publica no Release `dados`. Estão nele o orquestrador `motor/rodar_estado.py` (planejar, preparar, `--executor`, continuar), `motor/raiz_situacao.py`, `motor/painel.py`, `publicar_dados.py --subir` com trava, e o executor (`raiz/executor/`) pronto para o Actions | mesclado (o fundador fez o merge) |
| #30 | Até 18 jobs, estados grandes em fatias por longitude (62 unidades), duas filas (novo antes de manutenção, manutenção até 4), trava por estado na publicação, `motor.fatias` no `estados.json` | mesclado |
| #38 | Situação de E1 e E2 no `docs/plano-por-etapa.md`; versão nomeada das regras (`regras-2026b+hash`) em cada previsão (`raiz/versoes.py`, `raiz/carga.py`); manifesto com os 4 produtos do YbYrá e os subtemas da API do MapBiomas | mesclado |
| #43 | Limite padrão de 15 jobs de processamento (5 máquinas livres para CI e site), mais esta passagem | mesclado em 12/11, 13h30 de Brasília; CI de push e PR verdes |
| #46 | Teto global de 15, reserva atômica, fila persistente de pedidos e continuações, consulta paginada e bloqueio de admissão se a API falhar | mesclado; os três checks do run `43281492727` passaram |
| Retomada, entrega 2 | Itens 2–7: Croissant 1.1/schema.org, quantis hubverse, cartão, actions/attest e cronogramas CAD Trust; publicação sob as travas do estado e do índice | implementado; workflow de preenchimento retroativo será executado após CI e merge |
| Retomada, entrega 3 | As seis pendências E1/E2 do item 8, na ordem de dependência | implementado; integração e testes PostGIS na entrega seguinte |

## Onde parou

- **#43 fechado e conferido:** os runs `43256751563` (PR) e `43256738203` (push) terminaram com sucesso.
  Na retomada havia 13 jobs de processamento ativos. Nenhum foi cancelado. A revisão encontrou caminhos que
  ainda furavam o limite (pedidos explícitos, `refazer`, continuações, planejadores concorrentes e falha da API).
  A entrega 1 fecha esses caminhos com `motor/fila_processamento.py` e a ref `raiz-fila-processamento`.
  Reservas só são liberadas depois de o Actions confirmar o job concluído, incluindo seus passos finais.
  A agenda de 15 minutos apenas drena pedidos pendentes; a rodada semanal mantém seu escopo.
- **Itens 2–7 implementados:** fichas validadas antes do upload, quantis e hub nativo por UF, metadados globais,
  cartão do modelo, checksums para atestação OIDC e cronogramas CAD Trust. O preenchimento dos assets existentes e
  a verificação das assinaturas ainda dependem da execução do novo workflow após merge. As fichas não concedem
  licença presumida aos dados, e o cartão diferencia cenário central, quantil e hipótese triangular de FLAG.
  A suíte da entrega passou com PostGIS (711 testes, 2 pulados, 1 xfail); correções adicionais de proveniência e
  os novos formatos passaram em 88 testes focados. A atualização retroativa verifica o término natural de
  runs anteriores à trava por UF. MA, run `43239448949`, terminou com sucesso; conferido às 19h02 UTC, sem cancelamento.
- **E1/E2 implementados:** fontes ArcGIS no manifesto e CLI/replicação, assinaturas SIGEF/PRODES, Ibama no SCD2,
  alertas de qualidade e DuckDB/restrições no funil de produção. Não confundir código com operação agendada:
  a coleta com PostGIS continua sem servidor permanente. Pendências maiores do plano que não estavam nos seis
  itens desta passagem continuam explícitas no plano, como changelog oficial Ibama, cubo e grade raster.

## O que falta, em ordem

1. **Fechar o #43 — feito.** Merge e os dois CIs conferidos. O complemento da retomada torna 15 um teto global,
   inclusive com pedidos simultâneos, e preserva na fila os pedidos que ainda não cabem. Não cancelar os jobs.
2. **Croissant — feito no código.**
   - Criar `raiz/metadados.py` com `croissant_uf(pasta, uf, entrada)`. Ele roda o `croissant-baker` (0.8.3, MIT) na
     pasta do espelho do estado (`dados/armazem_local/saida/<UF>/`) e troca a `distribution` por um `FileObject` do
     `raiz_<UF>.tar.gz` (url do Release, sha256), mais `FileSet` por tabela (`<UF>/imoveis_*.csv`, `filtros_*`, ...)
     com `containedIn`.
   - Validar com o `mlcroissant` 1.1.1 (Apache-2.0).
   - Pôr o `croissant-baker` num extra do `pyproject.toml`. Ele traz h5py, nibabel, pydicom, wfdb, pillow, openpyxl e
     xlrd. Rodar `uv run python scripts/checar_licencas.py`.
3. **Publicar a ficha junto do pacote — feito no código.** Em `raiz/executor/armazem.py`, `ArmazemRelease._publicar_uf`, subir também
   `croissant_<UF>.json`, dentro da trava do estado. Depois, um `croissant.json` geral do Release, que aponta para as
   fichas de cada estado (subir dentro da trava do `estados.json`, `_gravar_indice`).
4. **Quantis hubverse — feito no código.**
   - Converter as colunas P10/P50/P90 do `desenvolvedor_<mun>.csv` (valor para quem restaura) e do `flag_<mun>.csv`
     para o formato longo do hubverse: `reference_date` (dia UTC da execução registrada), `location` (cod_imovel), `target` (ex.:
     `credito_liquido_tco2`), `output_type="quantile"`, `output_type_id` em {0.1, 0.5, 0.9} e `value`.
   - `model_id = "raiz-<tarefa>_<hash da versão>"`. O padrão do hubverse só aceita `[A-Za-z0-9_+]` dos dois lados do
     hífen. Cada versão vira um "modelo", o que deixa o aprendizado comparar versões.
   - Gravar em `quantis_<UF>.parquet` junto do pacote, mais a configuração do hub (`tasks.json`) e os metadados do
     modelo, com `model_version`.
   - Antes, conferir os nomes exatos das colunas P10/P50/P90 em `dados/amostra/desenvolvedor_1504950.csv` e em
     `raiz/flag.py`.
5. **Cartão do modelo — feito no código.** `docs/modelo/cartao.md` (formato de Mitchell et al.): o funil (motor), o valor para
   quem restaura, FLAG e caminho da terra; uso pretendido, dados, métricas, limites, versões. Publicar no Release como
   `cartao_modelo.md`.
6. **Assinatura com `actions/attest` — implementada; verificar após execução.**
   - Em `processar-estados.yml`, dar ao job `processar` as permissões `id-token: write` e `attestations: write`.
   - Fazer o `_publicar_uf` gravar em `$RUNNER_TEMP/atestar.txt` uma linha `sha256  nome` por arquivo que subiu.
   - Somar um passo `actions/attest-build-provenance@v2` com `subject-checksums` apontando para esse arquivo
     (conferir no `action.yml` da versão escolhida se o campo existe; o `subject-path` também serve se os arquivos
     forem gravados em disco).
7. **Cronograma dos lotes no CAD Trust — feito no código.**
   - Para cada estado, `raiz/lote.py` (`ler_uf` + `montar`) dá o lote do ProFloresta+.
   - Converter `resumo["cronograma_lote"]["marcos"]` (ano, `acumulado_p50`) e a curva de captura em um projeto do CAD
     Trust com `estimations`: `creditingPeriodStart`, `creditingPeriodEnd`, `unitCount` por ano, em `tCO2e`.
   - Campos do projeto: `projectId`, `originProjectId`, `registryOfOrigin`, `projectName`, `projectLink`,
     `projectDeveloper`, `sector`, `projectType`, `coveredByNDC`, `projectStatus`, `projectStatusDate`, `unitMetric`,
     `methodology`.
   - Valores das listas do CAD Trust:
     - `sector` = "Agriculture; forestry and fishing";
     - `projectType` = "Reforestation and Revegetation";
     - `coveredByNDC` = "Unknown";
     - `projectStatus` = "Listed";
     - `unitMetric` = "tCO2e";
     - `methodology` = "VCS - VM0047" (texto livre: a VM0047 não está na lista).
   - Publicar `cadt_lotes.json` no Release e registrar o CAD Trust (Apache-2.0, Chia-Network/cadt) no `NOTICE.md`.
8. **E1 e E2 — feito no código**, pela ordem de dependência do plano:
   - fontes oficiais ArcGIS: CNFP 2025 e snapshot Ibama no SFB têm `lastEditDate`; PAMGIA não tem e exige releitura;
   - SIGEF: bbox + contagem + `data_aprovacao`, com filtro FES validado no serviço real; fila independente do CAR
     e reconciliação por UF. PRODES: hash do catálogo oficial (link/created/enabled), incluindo remoção/desativação;
   - `raiz coleta arcgis`: fonte/UF/município/bbox explícitos, allowlist, snapshot GeoParquet e replicação. Confere
     edição, esquema, contagem e OIDs; falha/trava não avança cursor;
   - Ibama no SCD2 e view vigente, retry mesmo após 304; encerramento vazio só no município indicado. Pacotes
     pendentes do dlt são aplicados antes da extração atual, sem marcar como carregado um snapshot ignorado;
   - queda de contagem, coluna removida/vazia e geometria EMPTY produzem eventos/Healthchecks sem valores da fonte.
     CSV malformado não perde linhas silenciosamente; travas preservam cache, ETag e assinatura. Hash ordenado
     SHA-256 substitui XOR, que podia anular mudanças uniformes em quantidade par de linhas;
   - ponte R.ov de produção usa DuckDB/SPATIAL_JOIN + iOverlay, com conexão por município e limpeza em finally.
     Filtros acrescentam áreas exclusivas `restricao_*_ha`; mantêm sobreposições brutas, evidência legal e pequenas
     propriedades. Hashes das tarefas incluem os módulos novos, e a assinatura do Ibama usa o espelho municipal.

### Validação da entrega E1/E2

Testes focados passaram com PostGIS em bancos separados: ArcGIS/CLI (32), SIGEF/PRODES/CAR/WFS (49), Ibama/qualidade
e retomada dlt (23), além dos testes vetoriais e de produção E2. Os conjuntos têm interseções; não somar como total
de testes únicos. A suíte integrada e o CI do PR registram o resultado da entrega completa.

Os endpoints reais de ArcGIS responderam às allowlists dos três serviços. O INCRA respondeu à consulta FES
com bbox/`data_aprovacao`; o catálogo PRODES foi lido sem baixar rasters. Testes automatizados usam respostas
controladas e não dependem da disponibilidade desses serviços. A licença pendente do SFB/INPE continua marcada
como não habilitada para treino no manifesto.

## PRs abertos e branches sem merge

- **#43 e #46:** mesclados. As entregas da retomada seguem PR, CI verde e merge; o PR corrente aparece nos artefatos do chat.

## Trabalhos rodando no Actions e como conferir

- O workflow "Processar estados (motor)" roda sozinho. Cada job de estado ou fatia para antes de 5h30, publica, e
  dispara a continuação ou o próximo da fila. Às 16h UTC rodavam:
  - PA inteiro (APP pela escadinha nos 144 e adoção), TO inteiro e MA inteiro, ainda com o código de antes das fatias;
  - AM, MS, GO-1 a 3, MG-1 a 7, MT-1 e MT-2.
- Não cancelar nada.
- **Conferir:**
  - a aba Actions do repositório;
  - o painel em `motor/README.md`, que o Actions atualiza com commits "Painel do motor atualizado pelo GitHub
    Actions";
  - o andamento por estado, com `curl -sSL https://github.com/bernardoemmel/raiz/releases/download/dados/estados.json`;
  - o plano da próxima rodada: `uv run python motor/rodar_estado.py --planejar` (só lê).
- **Prazo estimado para o funil do Brasil inteiro:** perto das 22h de 12/11 (Brasília), a uns 45 municípios por hora
  por job. Com 15 jobs, uns 20% mais tarde.

## Decisões e cuidados que não estão no código

- **Versões e assinaturas no executor.**
  - O executor compara versões de tarefa por hash do código. O motor sozinho (`rodar_estado.py` sem `--executor`) usa
    hash sem comentários.
  - A assinatura de raster e arquivo nacional é pelo **tamanho**, sem a data: o cache do Actions volta com outra data e
    refaria o estado inteiro.
  - O `adotar` grava a caixa do município; sem ela, todo alerta novo refaria o funil adotado.
- **Espelho do Release:** não troca o que a máquina gravou e não publicou (meta `gravado_aqui`).
- **Travas:** tags `trava-publicar-dados` (o `estados.json`) e `trava-publicar-<UF>` (o pacote do estado; as fatias
  relêem e juntam). Não apagar essas tags à mão, salvo se ficarem órfãs mais de 30 min.
  O publicador novo falha sem upload quando não consegue adquirir a trava e não a apaga pelo tempo de espera.
- **Fila de processamento:** `raiz-fila-processamento` contém reservas e pedidos pendentes, atualizada com
  compare-and-swap (`force-with-lease` somente nessa ref; nunca na main). Não apagar nem liberar por idade:
  a reconciliação consulta o estado real dos jobs. Falha de autenticação, rede ou leitura impede novas admissões.
- **Estado do executor** (com `controle` no `estados.json`): não publicar pelo `motor/publicar_dados.py`, porque
  perderia as tabelas do produto. Usar `raiz executor publicar`.
- **Funil sem Alerta ou MapBiomas:** não roda sem o MapBiomas Alerta (WFS público, `garantir_alertas`) nem sem o
  MapBiomas (cobertura e desmatamento). Para rodar no computador sem eles: `RAIZ_ALERTA_OBRIGATORIO=0` e
  `RAIZ_MB_OBRIGATORIO=0`.
- **MapBiomas e YbYrá:** a API da Plataforma não separa os 9 produtos do Fogo Col. 5. O YbYrá é CC BY 4.0.
- **Croissant:** a licença dos dados da Raíz no Release não foi decidida. Na ficha, citar as licenças das fontes
  (`NOTICE.md`) e deixar a da Raíz para o fundador escolher.
- **Croissant 1.1 confirmado em leitura:** `containedIn` usa o vocabulário `cr:`. O mlcroissant 1.1.1 lê os CSV
  contidos no tar com `FileObject` por CSV; os `FileSet` por tabela continuam para descoberta. Cada CSV tem seu
  próprio RecordSet, preservando colunas diferentes entre municípios. O baker presume CC BY por padrão: essa
  licença é removida, e `conditionsOfAccess` explica a pendência. Nenhum exemplo de valores entra na ficha.
- **Hashes do Release:** `sha256` identifica os bytes do pacote comprimido; `versao` mantém a assinatura de
  conteúdo anterior. `proveniencia_sha256` detecta mudanças de versão/data mesmo quando o CSV é igual. Asset
  ausente é republicado, e digests da API prevalecem sobre o índice quando jobs antigos ainda publicam.
- **Quantis:** FLAG usa a distribuição triangular versionada (mínimo/moda/máximo); não apenas renomeia limites.
  Desenvolvedor preserva as colunas publicadas; P50 é o cenário central legado, não necessariamente a mediana.
  Sem versão/data confiável, registra diagnóstico. `reference_date` é dia UTC da execução, não corte histórico das
  fontes. `quantis_<UF>.parquet` e `hub_<UF>.tar.gz` são retratos mutáveis; catálogo de versões não é histórico de valores.
- **CAD Trust:** o Actions usa início hipotético `2027-01-01`, configurável. Incrementos anuais conservam o total
  P50 arredondado; ausência de lote/cronograma gera diagnóstico. `Listed` é apenas o catálogo da Raíz, sem registro,
  certificação ou emissão. Referência do vocabulário: CADT `58927db8f4b4fe558842a688d33f173c41944279`.
  Versão científica/cenário ausentes ou diferentes nos CSV impedem o projeto da UF, com diagnóstico.
- **Atestação:** `actions/attest-build-provenance@v2` aceita `subject-checksums` (action.yml conferido). Os uploads
  concluídos registram SHA-256 em `RUNNER_TEMP/atestar.txt`; a última versão de cada nome no job é atestada.
- **Rede desta retomada:** GitHub conectado e `gh` autenticado; Docker/PostGIS local disponível para testes.
  Não pressupor que os bloqueios da sessão original ainda valem: conferir a fonte antes de concluir indisponibilidade.
- **Fila de máquinas:** com 18 jobs, o CI dos PRs ficou na fila por dezenas de minutos. Daí o limite de 15.
- **Coleta sem agendamento:** a coleta (`raiz coleta ...`) não está agendada; precisa de um Postgres permanente, que não
  existe.

## Comandos de teste desta parte

```bash
uv sync --frozen --all-extras
uv run pytest -q testes/test_processar_estados.py testes/test_armazem_release.py testes/test_executor.py
uv run pytest -q testes/test_regras_parametros.py testes/test_coleta_manifesto.py
uv run pytest -q                      # tudo (sem RAIZ_BANCO_URL_TESTE, os testes de banco são pulados)
uv run ruff check raiz testes scripts migracoes && uv run ruff format --check raiz testes scripts migracoes
uv run raiz privacidade varrer && uv run python scripts/checar_licencas.py
uv run python motor/rodar_estado.py --planejar   # o plano da próxima rodada, só lendo o estados.json publicado
```
