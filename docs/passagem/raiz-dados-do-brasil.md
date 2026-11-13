# Passagem do chat "Raíz · Dados do Brasil" (processamento de dados)

Passagem original de 12/11/2026, 13h20 de Brasília. Retomada pelo Codex na mesma data, a partir da main.
Formatos e procedência foram integrados pelo #77; as seis pendências E1/E2, pelo #79.
Branch da entrega operacional: `codex/dados-operacao`.

## O que este chat fez

| PR | O quê | Situação |
|---|---|---|
| #21 | `.github/workflows/processar-estados.yml`: o motor roda sozinho no GitHub Actions e publica no Release `dados`. Estão nele o orquestrador `motor/rodar_estado.py` (planejar, preparar, `--executor`, continuar), `motor/raiz_situacao.py`, `motor/painel.py`, `publicar_dados.py --subir` com trava, e o executor (`raiz/executor/`) pronto para o Actions | mesclado (o fundador fez o merge) |
| #30 | Até 18 jobs, estados grandes em fatias por longitude (62 unidades), duas filas (novo antes de manutenção, manutenção até 4), trava por estado na publicação, `motor.fatias` no `estados.json` | mesclado |
| #38 | Situação de E1 e E2 no `docs/plano-por-etapa.md`; versão nomeada das regras (`regras-2026b+hash`) em cada previsão (`raiz/versoes.py`, `raiz/carga.py`); manifesto com os 4 produtos do YbYrá e os subtemas da API do MapBiomas | mesclado |
| #43 | Limite padrão de 15 jobs de processamento (5 máquinas livres para CI e site), mais esta passagem | mesclado em 12/11, 13h30 de Brasília; CI de push e PR verdes |
| #46 | Teto global de 15, reserva atômica, fila persistente de pedidos e continuações, consulta paginada e bloqueio de admissão se a API falhar | mesclado; os três checks do run `43281492727` passaram |
| #77 | Itens 2–7: Croissant 1.1/schema.org, quantis hubverse, cartão, actions/attest e cronogramas CAD Trust; publicação sob as travas do estado e do índice | mesclado em `b624b108`; CI do PR `43304760101` verde, 1.859 testes; CI de push `43308323363` também verde |
| #79 | As seis pendências E1/E2 do item 8, na ordem de dependência | mesclado em `6a53cfbf`; CI do PR `43305894156` verde, 1.936 testes; CI de push `43308991599` também verde |

## Onde parou

- **#43 fechado e conferido:** os runs `43256751563` (PR) e `43256738203` (push) terminaram com sucesso.
  Na retomada havia 13 jobs de processamento ativos. Nenhum foi cancelado pela retomada. A revisão encontrou caminhos que
  ainda furavam o limite (pedidos explícitos, `refazer`, continuações, planejadores concorrentes e falha da API).
  A entrega 1 fecha esses caminhos com `motor/fila_processamento.py` e a ref `raiz-fila-processamento`.
  Reservas só são liberadas depois de o Actions confirmar o job concluído, incluindo seus passos finais.
  A agenda de 15 minutos apenas drena pedidos pendentes; a rodada semanal mantém seu escopo.
- **Itens 2–7 implementados:** fichas validadas antes do upload, quantis e hub nativo por UF, metadados globais,
  cartão do modelo, checksums para atestação OIDC e cronogramas CAD Trust. O preenchimento dos assets existentes e
  a verificação das assinaturas ainda dependem da execução retroativa após o término natural dos escritores
  anteriores ao #77. O código já está na main. As fichas não concedem
  licença presumida aos dados, e o cartão diferencia cenário central, quantil e hipótese triangular de FLAG.
  A rodada `43305564503`, iniciada após a reativação, usa o contrato privado do #72, mas ainda as travas antigas.
  Às 22h38 UTC, oito jobs de BA, CE e PI continuavam ativos, além de um RN em rodada posterior: nove vagas
  ocupadas de quinze. O preflight confirmou essa rodada antiga como único bloqueio à catalogação.
  Nenhum job foi cancelado por este chat.
- **E1/E2 implementados:** fontes ArcGIS no manifesto e CLI/replicação, assinaturas SIGEF/PRODES, Ibama no SCD2,
  alertas de qualidade e DuckDB/restrições no funil de produção. Não confundir código com operação agendada:
  a coleta com PostGIS continua sem servidor permanente. Pendências maiores do plano que não estavam nos seis
  itens desta passagem continuam explícitas no plano, como changelog oficial Ibama, cubo e grade raster.
- **Retomada autorizada e efetivada:** o workflow foi reativado às 20h57 UTC na integração da Ficha. RN-1 e RN-2
  terminaram com status de sucesso, mas sem avanço: uma resposta HTTP 422 do MapBiomas era tratada apenas como
  aviso antes dos municípios. Sem CSV, a tentativa não entrava no índice; a fila voltava a selecionar RN.
  A correção operacional foi validada localmente; sua confirmação em produção continua pendente.
  Sucesso do job não deve ser usado como evidência de dados produzidos.

## Prioridade urgente — processamento, 12/11/2026 à noite

O fundador priorizou esta sequência sobre a extensão dos formatos: corrigir a falha real de RN/PI, preservar
resultados mesmo quando a publicação falhar, retomar várias UFs/fatias em paralelo até o teto global de 15,
registrar a proibição de desativar/cancelar no `AGENTS.md` e publicar o painel de andamento municipal por estado.
Não iniciar estimativa de conclusão do Brasil por simples contagem de jobs: medir municípios concluídos e
comparar escopo/versões, incluindo os erros e o tempo efetivo após a correção.

- **#82 mesclado:** `cf306256e0b562b1e05415b8ca0df1ca835c2155`, CI `43335410339` com oito checks verdes,
  incluindo Pará completo. Workflow do motor consultado e ativo. Nenhum job cancelado por este chat.
- **Causa comprovada RN-1 (`43316654812`):** a projeção pública rejeitou um CAR cadastrado em PB no recorte RN.
  PI também contém um CAR válido de PE. Todos os identificadores desses dois pacotes têm formato e prefixos
  IBGE coerentes; UF do recorte e origem cadastral são campos distintos. Não descartar nem alterar esses CARs.
  A publicação privada ocorre antes dessa projeção; os pacotes e controles privados conferidos são recuperáveis.
- **Outras falhas PI-2:** HTTP 502 ao conferir o Release privado interrompeu uma publicação periódica; CHIRPS
  respondeu 429 em tarefas municipais. A exceção de publicação saía de `anota()` e encerrava o Pool de trabalho.
  O cache salvo pelo workflow contém fontes, mas não garante a preservação de todas as saídas e retratos locais.
  Um checkpoint privado independente da catalogação está sendo implementado para fechar essa lacuna.
- **Retratos:** o passo de preservação falhou na validação local. As tags diárias consultadas não comprovaram
  preservação remota; a causa de normalização ainda está sendo reproduzida. Não chamar esses retratos de válidos
  nem enfraquecer a validação. O checkpoint deve preservar os bytes sem afirmar validação científica.
- **Correção local da projeção:** 16 testes passaram; a validação dos pacotes reais preservou 185.791 registros
  em 130 CSVs de PI e 56.217 em 84 CSVs de RN, inclusive os dois identificadores de outra UF. Nenhum upload nessa prova.
- **Cópia estável:** a publicação agora lê pacote, Croissant, quantis, CADT e projeção básica da mesma cópia privada.
  Fecha a corrida observada em RN (ficha com 44 CSVs, pacote com 41); outras lanes continuam no espelho original.
  Bytes e SHA do sidecar precisam corresponder antes da cópia. O preflight mantém comparação exata do publicador:
  publicadores antigos devem terminar naturalmente; não liberar o catálogo por uma exceção de compatibilidade.
- **Ainda a fazer nesta urgência:** completar checkpoint/telemetria/painel, atualizar a promoção auditada para
  a referência fixa corrigida, executar suíte/CI, merge e admissão das vagas disponíveis pela fila CAS. Conferir
  dados realmente publicados, medir vazão e só então estimar estados por dia e conclusão do Brasil.

## O que falta, em ordem (formatos, após a prioridade urgente)

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
de testes únicos. A suíte integrada com PostGIS passou em **1.588 testes, 2 pulados e 1 xfail**, no commit `1b0f57c`.
A atualização posterior da API/MCP/Ficha foi incorporada com os testes complementares registrados abaixo;
Ruff e a descoberta dos comandos `raiz coleta` também passaram após essa integração.
Os 21 testes de ArcGIS/CLI e da ponte de produção E2 passaram novamente após integrar a API/MCP final.

Os endpoints reais de ArcGIS responderam às allowlists dos três serviços. O INCRA respondeu à consulta FES
com bbox/`data_aprovacao`; o catálogo PRODES foi lido sem baixar rasters. Testes automatizados usam respostas
controladas e não dependem da disponibilidade desses serviços. A licença pendente do SFB/INPE continua marcada
como não habilitada para treino no manifesto.

## PRs abertos e branches sem merge

- **#43, #46, #77 e #79:** mesclados com CI verde. A próxima entrega reúne a promoção auditada de continuações,
  o gatilho de catalogação após o término natural e a correção do loop de falhas das fontes.

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
  relêem e juntam), com sufixo privado no destino autenticado. O publicador novo falha sem upload quando não
  consegue adquirir a trava e não a apaga pelo tempo de espera. Idade não comprova que uma trava ficou órfã.
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
  públicos concluídos registram SHA-256 e nome em `RUNNER_TEMP/atestar.txt`. No canal privado, a lista separada
  usa somente `privado-sha256-<digest dos bytes>`, nunca o nome original; aliases do mesmo conteúdo colapsam,
  mas versões distintas permanecem atestadas. O gate do #81 impede atestar uma lista privada legada inválida.
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

## Validação de escala e modelos na retomada

- Suíte integrada após atualizar a main: 854 testes passaram com PostGIS (2 pulados, 1 xfail).
- RO real: 521 CSVs, 14.020 campos e 5.073.915 linhas de quantis; 3.476 diagnósticos de faixas financeiras cruzadas,
  sem ordenar ou inventar valores. A ficha Croissant permanece byte a byte idêntica após limitar a memória.
- Baker e mlcroissant são executados em partes, em filhos sequenciais; checagens globais conferem IDs e referências.
  No RO, o pico simultâneo pai+filho foi 314 MiB, ante 1,083 GiB na geração anterior.
- Escala MG sintética: cabeçalhos reais replicados em 853 municípios, sem linhas de dados; 8.530 CSVs e
  230.310 campos. Ficha integral de 120.286.760 bytes, 157 partes baker e 158 validações mlcroissant em 840 s.
  Pico de 519 MiB durante geração/validação e 919 MiB na serialização final, com apenas o processo principal.
- O registro histórico fechado da regra `restauracao-2026c+421970fd` recupera os YAMLs do commit
  `8eebc6a90bc20bce585520cee81bbebdd1ff93df` e confere hashes integrais. RO gerou 25 estimativas CAD Trust sem
  diagnósticos, com soma e marcos conferidos; repetido em 120 s com as salvaguardas da nova main. A seleção usa
  o otimizador e as salvaguardas atuais, identificados separadamente;
  previsões individuais e curva histórica são preservadas.

## Histórico da pausa externa (12/11, 19h UTC; reativada às 20h57 UTC)

- A API registrou `processar-estados.yml` como `disabled_manually` às 19h09min20s UTC. Os runs
  `43285999423` e `43286899548`, além dos cancelamentos de BA/PI/CE desse intervalo, têm a anotação
  `The run was canceled by @bernardoemmel.` Isso identifica a conta, sem identificar pessoa, interface ou token.
  Este chat não solicitou os cancelamentos. O fundador posteriormente autorizou expressamente reativar e retomar.
- O cancelamento automático de BA-1 em `43256269335`, às 18h42min05s, antecede o merge #46 às 18h43min39s.
  Não houve evidência de duplicação causada pela fila nova. Reservas canceladas passam a pedidos bloqueados na
  reconciliação; não devem ser confundidas com solicitações ainda ativas.
- O publicador retroativo reserva uma vaga global sem consumir pedidos de UF. Confere cota antes de cada UF e
  dos globais; a margem de 250 requisições adia trabalho com relatório, sem ocupar a vaga esperando uma hora.
  Repetições de respostas de quota têm limite conjunto de 60 segundos. Falhas comuns de permissão não se repetem.
- Substituições preservam e reconferem os bytes originais no arquivo privado antes do DELETE. Os backups remotos
  `recuperacao-<identidade>-<sha256>.bin/.json` são imutáveis e permanecem disponíveis após a troca. A pasta local
  contém apenas marcadores de recuperação, nunca originais enviados a artifacts públicos. Falha interrompe a
  publicação; o relatório privado `catalogo-relatorio-<run>-<tentativa>.json` permite retomar UFs pendentes.
  `somente_globais` retoma apenas o final.
- Execuções futuras de `processar-estados.yml` com ciência fixada em commit antigo usam o publicador do SHA do
  workflow em checkout e ambiente separados. O finalizador confere a reserva original e usa a mesma vaga e prazo,
  preservando a versão científica, o cache e a continuação. O gate compara SHA-256 do código do publicador,
  inclusive após squash de PR, e recusa referências com contratos de publicação incompatíveis.
  Runs já iniciados precisam da retropublicação.

## Mudança de contrato coordenada com Ficha da fazenda

Durante a retomada, o fundador determinou no chat “RAIZ - Ficha da fazenda” que cálculos detalhados por CAR
ficassem privados. A pausa do motor faz parte dessa migração, não de uma falha do teto de jobs.
O Actions `43288984765` preservou os originais no draft autenticado `dados-privados` (não publicar esse draft) e
substituiu o Release `dados` por 22 arquivos básicos. A retomada de Dados não reativa os publicadores antigos.

A entrega de metadados passou a ter dois escopos: Croissant básico e cartão metodológico no público; quantis,
tasks, modelos, diagnósticos, CADT e fichas completas no privado. O catálogo aberto não reescreve o manifesto
básico, e backups de arquivos privados nunca usam artifacts públicos. O contrato da Ficha foi integrado pelo #72
antes do merge #77. A implementação anterior foi validada em 1.141 testes com
PostGIS (2 skips, 1 xfail), além de 52 testes das atualizações posteriores de calendário/pedidos; a integração
privada teve validações adicionais e os CIs finais registrados no início desta passagem.

O fundador autorizou explicitamente reativar o processamento e retomar os lotes pendentes. A integração da Ficha
reativou o motor e reabriu RN-1/RN-2 usando o contrato privado do #72. As rodadas seguintes já usam #77/#79;
a rodada inicial precisa terminar naturalmente antes da catalogação retroativa. O teto global permanece em 15.

## Capacidade conjunta com o Lote do Pará

O #55 acrescentou `retomar-lote-para.yml`, com cinco fatias. Os dois workflows do Lote passam a reservar cotas na
mesma ref CAS do motor e do catálogo, antes de instalar dependências ou ler dados. A concorrência da matriz usa
apenas as cotas obtidas; preparo, checkpoints e publicação ficam cobertos até o término confirmado da rodada.
Reruns conferem cotas por tentativa antes de acessar os dados; uma reexecução parcial sem reserva falha sem calcular.

A rodada `43299409156`, iniciada pelo chat do Lote no SHA `3546687c66ec07ef9bd875d181efcff57ff1d312`, terminou com sucesso.
Esse workflow imutável foi conferido e ocupou cinco vagas durante toda a execução. Outros Lotes legados desconhecidos
consomem conservadoramente as 15 vagas até terminar. Nenhuma reserva é liberada por idade ou por cancelamento solicitado.
RN-1 e RN-2, cancelados na pausa externa, foram reabertos com autorização; a falha de fonte está descrita acima.

Entradas congeladas, fatias intermediárias e checkpoints do Lote ficam fora da retrocatalogação, assim como caches e
backups. Os produtos finais continuam elegíveis a ficha e atestação; o processamento científico do outro chat não muda.

## Validação final antes do PR dos formatos

- Suíte completa do publicador integrado: **1.511 passaram, 2 pulados e 1 xfail**, com PostGIS, no commit `57c6c04`.
  As duas incompatibilidades da migração local foram corrigidas antes dessa execução.
- Integração posterior da API/MCP: 544 testes complementares passaram; o contrato de resposta da Ficha foi
  incorporado do #72 e os 93 testes finais de ficha, pedidos, Pix, webhook, apresentação e MCP passaram.
  Banco novo e downgrade/upgrade conferiram a cadeia até `0031`, sem alterar as revisões já na main.
- Ruff, actionlint, varredura de CPF/CNPJ e licenças passaram; 681 pacotes foram conferidos sem problema de licença.
- Conferência somente de leitura dos Releases, antes da catalogação: 22 arquivos públicos e 39 canônicos privados
  (1.205.637.082 bytes privados), todos com SHA-256 real igual ao digest do GitHub. Os 22 públicos passaram na
  lista positiva. As fichas e assinaturas ainda serão preenchidas pelo workflow após o merge.
- O run do Lote `43299409156` terminou com sucesso por conta própria. Não foi cancelado, reexecutado ou alterado
  por este chat; a reserva conservadora de cinco vagas deixa de pesar após a confirmação do término pela API.

## Continuidade depois dos merges #77 e #79

- Uma migração manual da fila não alcança continuações que um job antigo ainda vai enfileirar. A admissão CAS
  promove somente pedidos não bloqueados de continuação ou retentativa entre referências exatas, sem seguir
  a main: as cinco origens `88860b64`, `b624b108`, `6a53cfbf`, `bea53bd0` e `436c7b63` passam
  ao destino fixo `be452620`. Ele inclui E1/E2 do #79, a aquisição corrigida, as proteções operacionais do #81
  e as guardas de embargo e adoção descritas abaixo.
  Preserva ID, parâmetros, contador e falhas; registra origem e destino.
  Reservas vivas não mudam. O catálogo aplica a mesma promoção antes do preflight, para não depender da ordem
  entre o último job e o cron de 15 minutos.
- A evidência está em `auditoria-promocao-publicador.json`. A aquisição mantém fórmulas, temas e ano do MapBiomas.
  A prova declara as mudanças de versão por origem e a entrada intencional de E1/E2 nos pedidos anteriores ao #79.
  Nas duas origens anteriores ao #79, mudam as 11 versões de tarefa: `rodar.py` integra o hash compartilhado
  do histórico. A guarda de adoção permite esse avanço sem atribuir a ciência nova a arquivos antigos. Tarefas com versão
  alterada e saídas sem versão comprovada seguem para o recálculo normal; checkpoints, prazos e limite de 15
  continuam valendo. Previsões históricas conservam suas versões; não se usa HEAD móvel como destino.
- O `workflow_run` da catalogação é restrito ao término de `43305564503`, no SHA `88860b64` completo, branch main
  e repositório de origem igual ao atual. Executa o código da main e não baixa artifacts do gatilho. O preflight
  continua exigindo a ausência de qualquer escritor antigo, antes de reservar uma das 15 vagas.
  O disparo automático é uma tentativa: falta de vaga, cota ou outro escritor antigo exige retomar manualmente
  `publicar-metadados.yml` após resolver a condição, sem cancelar trabalhos nem afrouxar o gate.
- RN expôs uma falha anterior: HTTP 422 em `/maps/exports` era aviso, não falha do job; a tentativa sem CSV não
  chegava ao índice e `continuar` disparava outro planejamento. O frontend oficial do MapBiomas associa 422 a
  limite temporário de geração; os temas, ano 2025 e `exportType=range` conferem com seu catálogo e interface.
  Referência: [bundle oficial](https://plataforma.mapbiomas.org/assets/index-DkZM_66U.js), SHA-256
  `ea2e4ae615bb44b8cc03d5b7dc0064c2aed812f25bb5c0d4a85a4a3ca71cbe4c`. O corpo da resposta que afetou RN não
  ficou registrado; seu motivo específico não foi confirmado. O cliente novo só repete 422 com indicação
  explícita de limite de geração; validação de ano/campo e respostas ambíguas falham com diagnóstico sanitizado.
  A correção operacional reaproveita e consome exports aceitos antes de abrir novos, respeita prazo e retries,
  registra a tentativa no índice privado e impede o encadeamento imediato de jobs com erro e avanço zero.
  Não se deve mudar ano, omitir fonte obrigatória ou declarar dados concluídos para contornar essa resposta.
  A aquisição integra o hash da tarefa MapBiomas: pedidos novos com essa correção terão nova versão de tarefa,
  embora o cálculo por imóvel permaneça igual. A promoção auditada inclui a aquisição corrigida no destino
  fixo; não se atribui a versão nova a previsões já publicadas.
- Conferência real somente por GET: os caches privados de RN-1/RN-2 tiveram visibilidade e SHA-256 conferidos;
  contêm os mesmos três pedidos aceitos, um READY e dois QUEUED. O export pronto foi baixado sem criar pedidos:
  ZIP de 8.429.316 bytes, GeoTIFF de 8.425.445 bytes, uma banda em EPSG:4326, todas as janelas lidas sem erro.
  Nenhum dado foi publicado nessa validação. O resultado prova que havia uma exportação pronta ainda não
  consumida pelo fluxo antigo; não confirma o motivo específico da recusa do quarto pedido.
- O registro de tentativa fica em módulo separado (`raiz/executor/rodadas.py`), usando as mesmas travas e o mesmo
  publicador. `armazem.py` permanece idêntico ao #77, preservando a conferência estrita de compatibilidade.
  A promoção final e o catálogo passaram em 155 testes de integração, com Ruff e actionlint 1.7.12.
- Suíte completa da integração protegida (`56a6354`, mesma árvore de código de `be452620`): **2.115 passaram,
  2 pulados e 1 xfail**, com PostGIS, em 1.102,57 s. Takumi e os testes de cartões/vídeo estavam disponíveis.
  Skips: dados do Pará inteiro e servidor LanguageTool; xfail: TIR central r11 já documentada. A execução anterior
  interrompida pela reinicialização da interface não foi contada. Depois da promoção final, **285 testes** de integração de fila, catálogo, fontes, atestação e guardas
  passaram. Ruff (476 arquivos) e actionlint 1.7.12 passaram; o novo CI será conferido antes do merge. Atestações e arquivos reais ainda exigem a execução retroativa.

## Proteções incorporadas à retomada operacional

- O CI do #82 na referência `7ab4852` passou. Antes do merge, foi incorporado o #83 da main, que torna
  obrigatória a referência privada completa do Pará e exige sua execução exatamente uma vez no CI.
  Os 256 testes locais relacionados passaram após essa integração; o CI atualizado ainda será conferido.
- O Gitleaks dessa rodada encontrou três SHA-256 de código no commit externo `e7074b4`, examinado por `--all`.
  Cada valor foi conferido contra os bytes do arquivo correspondente. Foram incluídos somente os três
  fingerprints exatos em `.gitleaksignore`; nenhuma regra foi desativada. A reprodução com Gitleaks 8.24.3
  passou sem achados. O novo push espera o término natural do CI anterior, para não cancelá-lo por concorrência.
- O #81 foi integrado antes da atualização final do PR #82: atestação privada identificada somente pelo digest
  dos bytes, sanitização de erros e reserva do catálogo por rodada/tentativa. O catálogo não libera uma vaga
  com base no término de uma tentativa anterior. A combinação passou em 174 testes focados; um cenário de
  14 jobs mais o catálogo não admitiu um 16º job, mesmo com promoção pendente e snapshot antigo do Actions.
- O caminho legado do funil também descartava embargo ativo sem WKT, produzindo falsa ausência de restrição.
  A guarda portável exige geometria poligonal utilizável antes dos cálculos, sem eliminar fazendas pequenas.
  Áreas válidas e reparáveis mantêm o cálculo anterior; geometria ausente, vazia ou sem área bloqueia o município.
- A adoção exige versão comprovada e hashes das saídas. Arquivo sem versão ou de outra versão permanece intacto
  e segue para o recálculo normal, sem ser carimbado como resultado atual. Marcas adotadas anteriores também são
  revalidadas. A data original é preservada; `adotado_em` registra separadamente a adoção. Essas guardas passaram
  em 74 testes focados antes da integração, com revisão cruzada.

## Validação offline dos demais produtos privados

- Além do RO real já validado, oito pacotes do cache autenticado tiveram SHA-256 e conteúdo conferidos sem rede
  nem publicação: AC, AP, GO, MA, MG, PA, RR e TO. As cópias temporárias privadas incluíram as geometrias reais.
  Foram 44 operações sem falha inesperada: 2.696 CSVs, 57.863 campos Croissant e 4.283.214 linhas de quantis;
  423,886 s somados e pico de cerca de 302 MiB, com um gerador por vez.
- Faixas cruzadas permaneceram como diagnóstico, sem reordenação: GO 8.898, MG 1.366 e TO 190. PA não contém
  tabelas financeiras/FLAG; AM, MS e MT não têm pacote tabular privado. A ausência não gera previsões inventadas.
- CADT de GO/MG indicou ausência de lote elegível. AC/AP/MA/RR/TO usam uniformemente
  `restauracao-2026b+cenarios-2026b+dbc2776a`, cenário `central_r11`; o registro fechado dessa versão está sendo
  recuperado no Git antes de gerar seus cronogramas. Os cálculos individuais publicados permanecem preservados.
