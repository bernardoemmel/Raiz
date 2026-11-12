# Qualidade e segurança — passagem

Entrega inicial de 12/11/2026 (#51); revisão de continuidade em 12/11/2026, até a main `6f49dfc` (#83). Área: CI, E2E, infraestrutura e segurança. Correções em produto são pontuais,
com regressões. Mudanças de contrato/arquitetura ficam para os chats responsáveis abaixo.

## Continuidade desta entrega (12/11/2026)

- **Qualidade e segurança:** portões de publicação Pandera/privacidade, incluindo formatos e metadados, executor,
  motor legado, vigilância, busca, calendário e rodada do Pará. Detalhes em [qualidade dos dados](../qualidade-dados.md)
  e [operação](../operacao.md). Dados inválidos ficam bloqueados; nenhum asset histórico foi apagado ou reescrito.
- **Qualidade e segurança:** contador Valkey compartilhado e atômico, 429/Retry-After, falha fechada 503; logs JSON
  com Presidio, saúde genérica e GlitchTip MIT com evento mínimo. Instância temporária real migrou, respondeu saúde
  e persistiu erro sintético sem a mensagem original. Servidor de produção ainda precisa das variáveis/DNS/TLS do guia.
- **Qualidade e segurança:** Locust MIT no CI, API/PostGIS reais, três rotas, saturação e recuperação. Ensaio local:
  70 chamadas normais e 385 na saturação, 355 respostas 429 válidas, zero falhas, máximo 2,864 s. São medidas do ensaio
  curto, não capacidade máxima de produção. Nove jobs em paralelo e um portão final; nenhuma suíte existente foi removida.
- **MCP, parcial:** o servidor OAuth entrou na main durante o CI desta entrega (#45/#69). O adaptador de testes
  agora usa HTTP/JWKS/RS256 e PostGIS reais, todas as sete ferramentas após #72, latência e Locust. O corpus continua dependendo
  de **Produto e regras**: o MCP oferece ferramentas de pedidos para agentes externos, sem agente leitor de certidão,
  edital ou arquivo. Não se simula essa leitura nem sua aprovação. O fundador autorizou depois **aviso somente
  para essa ausência**, mantendo OAuth, ferramentas, tempo e carga obrigatórios. Quando o leitor estiver ligado,
  o corpus passa a ser obrigatório; falha não vira aviso. Os CIs vermelhos anteriores permanecem registrados abaixo.
- **Revisão contínua:** PRs #53, #56, #67, #54, #68, #70, #71, #73, #74, #55, #75, a integração #45/#69, #72, #77, #79 e #80 revisados,
  com correções pequenas de privacidade, calendário e idempotência abaixo.
  Scanners e testes rodam a cada push. O fundador optou por manter somente essas checagens por push, sem automação horária.

### Achados de dados agora bloqueados — chat Dados

Amostra `imoveis_1504950.csv`: área SIGEF excede o CAR em 69 linhas (excesso máximo 688,177151 ha); pasto em 18
(máximo 0,365093 ha). `imoveis_1507300.csv`: SIGEF em 2.210, assentamento em 1.568, embargo em 33, UC em 19 e
pasto em 1.084 linhas; máximos respectivamente 2.423,632799, 710,894784, 4.368,863691, 56,570659 e 9,078880 ha.
O pacote real AC tem `data_atualizacao=0` em 648/3.849 linhas de Acrelândia. Falhas verificadas sem expor CAR/dono.

**Dados** precisa conferir união de sobreposições, projeção/raster, ausência como nulo e recalcular. Qualidade não
alterou ciência nem aplicou clamp. Esses dados legados não recebem aprovação de qualidade; o arquivo privado pode preservar
os bytes originais, sem liberá-los como produto público. O KML
URTX real foi validado inteiro (1,26 s); o pacote AC foi bloqueado (4,66 s), não aprovado nem usado como benchmark
integral de lote válido. A separação de folhas individuais/HTML privados e projeção pública básica foi entregue
pelo #72; os portões desta continuação validam a projeção antes do primeiro upload público.

As demais pendências maiores seguem atribuídas nas seções históricas, reconciliadas pela revisão da main. O dado
real do Pará já está no arquivo privado: sua integração protegida ao teste é de **Qualidade e segurança**, com contrato
e novos snapshots de **Lote e números**. O critério TIR continua com seu dono; a proteção da main continua manual.

## Entrega inicial (#51)

- CI em seis jobs paralelos, cache uv/npm/Chromium/LanguageTool, Dependabot semanal, Gitleaks em histórico completo,
  licenças com inventários obrigatórios, build igual ao site e suíte Python integral com PostGIS/PDF/LanguageTool.
- Playwright com API/PostGIS reais: link de uso único, milhão de créditos no Pará, três lotes, interesse e Pix local
  de teste; nenhuma credencial real de pagamento. Front com testes sem skips e geometrias determinísticas.
- Cabeçalhos HTTP, limite por IP/login, destino canônico do link, Presidio antes dos logs e diagnósticos persistidos,
  inclusive erros publicados no Release. Pix de teste identificado e sem data 1970 quando não tem validade.
- Correções pequenas encontradas na revisão: rebanho zero, gabarito de certidão em revisão, índice WARC e alertas.
- Procedimento manual da proteção da main em [operação](../operacao.md#proteção-da-main-o-fundador-ativa-à-mão).

## Referência estadual obrigatória e TIR pendente

Nenhum teste foi retirado. A suíte completa é distribuída entre dois jobs, com portão único. O teste opcional preexistente
`test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta` ainda depende das 144 tabelas reais `desenvolvedor` do Pará,
que não estavam preparadas nos ensaios históricos registrados abaixo. A publicação privada integral foi concluída
por **Lote e números**. **Qualidade e segurança** já executou o teste real com download autenticado, hashes e
entradas/geometrias congeladas: 144 municípios, 345.870 imóveis, nenhum skip, em 446,2 s e pico de 6.840,2 MiB.
O teste e o portão desta continuação não aceitam mais a exceção estadual; o job privado e a união dos resultados
também passaram no CI, sem skips. A entrega independente #83 foi integrada à main com os oito jobs aprovados. Nenhum pacote financeiro vai para cache ou artifact
público; a recomendação histórica de cache abaixo está superada.
Além disso, permanece o `xfail` preexistente de TIR do plantio (`test_plantio_da_7_a_9_pct_no_central_r11`):
o teste executa, mas a conta ainda diverge da referência de 7–9%; o chat **Lote e números**, com **Produto e regras**, deve resolver o critério
em `docs/restauracao-rodada11.md`. O portão de resultados recusa qualquer outro skip/xfail novo.
O teste da cena-alvo usa a amostra real do repositório e já roda inteiro, sem esse pré-requisito nacional.

## Integração e operação — responsáveis atuais

- **Telas e mapa / Produto e regras:** a rota interna de mapa `/geo/brasil/*` continua ausente. O #52 publica
  agregados e abre fichas por autorização específica; o #67 entrega contornos somente de fichas já desbloqueadas
  pelo mesmo cliente ativo, revalidando reservas. Esses caminhos resolvem o acesso do site, sem tornar público o
  token interno `VITE_RAIZ_API_TOKEN` nem implementar a rota nacional antiga.
- **Qualidade e segurança:** o limite por processo do #51 foi substituído pela opção compartilhada Valkey desta
  continuação, com concorrência, logs estruturados e GlitchTip testados. Validar IP real/TLS na
  terminação HTTPS. O modelo NER pode deixar nomes livres passar; não registrar texto pessoal bruto. A entrega
  inicial não limpou retroativamente bancos/logs externos.
- **Raiz dados do Brasil:** a proteção da main bloqueará o push direto que atualiza `motor/README.md`; migrar para PR,
  sem bypass geral. As regras da conta não foram alteradas.

## Auditoria dos PRs #35–#45

Verificação pelo GitHub em 12/11/2026, comparada ao checkout da main (8865c7c no início). Os PRs #35–#44 estavam integrados; **#45 não estava na main** (`mergedAt: null`, em andamento). Sua revisão é preventiva, sem incorporar o código em andamento de outro chat.

| PR | Evidência revisada | Resultado |
|---|---|---|
| #35 | Diff E5; cadeia, WARC, triagem, aprendizado e testes | Corrigidos gabarito negativo prematuro (certidão lida com revisão pendente) e motivo pessoal/CPF codificado na URL do índice WARC. Riscos de cadeia/achados abaixo. |
| #36 | Diff completo de publicar-site.yml | Aspas corrigem o YAML; nenhuma nova lógica ou dado pessoal. |
| #37 | Diff do medidor, migração, gravação da nota e mensagens | Contagens/índices não guardam texto de entrada; mensagem pessoal permanece no esquema pessoal. Sem novo bug confirmado. |
| #38 | Diff regras_versao, carga e manifesto | Versão publicada antes da rodada, preservando referência; nenhum novo dado pessoal. Não revalidamos cientificamente o catálogo remoto de camadas. |
| #39 | Diff alertas/backoffice, persistência e respostas | Detalhe JSON não era sanitizado e textos só mascaravam CPF/CNPJ. Agora passam por Presidio antes da persistência; backoffice também filtra dados legados ao responder. |
| #40 | Diff fichas, API, revisão e cartão; consultas e contratos de serialização | A API interna e o cartão por código curto são caminhos distintos. Risco de localização em fichas/rows.json parcialmente tratado pelo #52: site agregado e exportação administrativa declarada privada. Permanecem a garantia de armazenamento privado e o tratamento dos artefatos históricos. |
| #41 | Diff rebanho/restauração/vazamento e contratos; tabela PPM municipal | Corrigido total PPM zero elevado pelo piso de lotação, que inventava gado e metano. Teste inclui propriedade pequena e grande, todas as faixas zeradas. |
| #42 | Diff CI e construção do site | Jobs isolados removiam instalação npm do job de licenças, fazendo o scanner ignorar front. Corrigido pelo trabalho do CI/licenças desta entrega. |
| #43 | Diff completo do limite do executor | Limite 15 consistente entre planejamento e matriz; sem mudança em dados do dono. |
| #44 | Diff cascata, confiança, exportação hub e placar | Cortes vazios mantêm votação; a avaliação é sintética e o hub requer API token. Pontos de validação/correção ampla abaixo. |
| #45 | Diff da API pública, cobrança, privacidade, migração; rechecado no head `9b7f49f` | Ainda aberto. Migração e estorno corrigidos; persistência de texto livre e implantação do limite compartilhado ainda exigem atenção. MCP está retirado até OAuth. |

## Correções pequenas e testes

- `raiz/rebanho.py`: total PPM igual a zero não é elevado ao piso de lotação. `testes/test_rebanho.py`: regressão preserva ambas as propriedades e exige gado/metano P10/P50/P90 zero.
- `raiz/operacao/alertas.py`: Presidio em título/texto/detalhe/nota antes de gravar. `raiz/operacao/backoffice.py`: filtro recursivo no JSON de resposta para alcançar dados legados, além dos logs. `testes/test_operacao_alertas.py`: verifica conteúdo salvo e resposta legado sem endereço de contato.
- `raiz/titulo/triagem.py` e `raiz/titulo/warc.py`: ver detalhamento do PR #35 abaixo.
- `testes/test_titulo.py`: fixture usa imóvel real já presente na amostra e condições explícitas; remove skip condicionado à seleção dinâmica da amostra.

## Mudanças grandes para os chats responsáveis

1. **#40 — exportações administrativas e artefatos históricos (Telas e mapa / Dados), parcialmente resolvido pelo #52:** o build do site passou a publicar somente agregados, retirando fichas, CAR, CSV e geometrias individuais, inclusive sobras de builds anteriores. A exportação `raiz/fichas_lote.py` foi explicitamente classificada como privada; continua contendo `_cod_imovel`, `_plus_code`, `_omaps` e perímetro. Garantir que seu destino permaneça privado e fora de qualquer upload público. O prefixo `_` não protege arquivos. O Release histórico continua público e exige tratamento separado; a alteração no código do site não torna privados os artefatos já publicados.
2. **#41 — validade de resultados anteriores (Lote e números / Produto e regras):** o executor inclui hash de código da tarefa e refaz os rebanhos afetados; execução manual `raiz funil` decide pelo hash de premissas/tabela e precisa de `--refazer` para resultados produzidos antes da correção PPM zero. Não alteramos as premissas científicas de limitar lotação/total.
3. **#44 — calibração da cascata (Documentos, título, vigilância, aprendizado e calendário):** o corte ainda é ligado ao nome do modelo, não automaticamente aos bytes dos pesos/prompt/gramática. O #56 concluiu a avaliação real e rejeitou todos os cortes: 67,92% em intenção e 43,33% em compreensão, abaixo de 95%; a main continua em votação. Há hashes do relatório/GGUF na operação, mas o vínculo automático no carregamento do corte continua pendente. O hash de receita do cache de matrícula do #53 é outro mecanismo; não resolve por si só a cascata.
4. **#45 — conflito de migração resolvido pelo chat Produto e regras:** no head `9b7f49f`, `0027_api_publica.py` declara revision `0027`/down_revision `0026`. O conflito antigo com `0020_alertas_operacao.py` não existe mais. O PR permanece aberto; a API ainda não tem essa migração na main auditada. **Nova colisão após #54:** a main agora possui `0027_calendario.py`; o chat Produto e regras precisa renumerar novamente a migração da API ao integrar o calendário.
5. **#45 — sanitização da API pública (Produto e regras, com correção pontual de Qualidade e segurança após integração):** no head `9b7f49f`, o código passou para `raiz/publica/`. A resposta `ok` já aplica `limpar(sem_dado_pessoal(x))`, mas `limpar` continua regex de CPF/CNPJ numérico/e-mail/telefone, sem Presidio ou nomes livres/CNPJ alfanumérico. `chaves.registrar` usa esse filtro em `agente_modelo` e `atributos` antes de persistir; o logger central não protege essas escritas. Reusar sanitização central com domínios fechados nas fronteiras de persistência/resposta, preservando UUIDs de protocolo. A descrição do PR mencionar Presidio não comprova cobertura dessas gravações.
6. **#45 — cobrança com erro imprevisto corrigida pelo chat Produto e regras:** no head `9b7f49f`, o middleware converte a exceção em 500 genérico e chama o estorno. Há regressão de exceção inesperada, estorno concorrente único e débito concorrente dos três testes. Falha do próprio banco durante o estorno ainda só é registrada; reconciliação durável após indisponibilidade pertence ao desenho de cobrança do chat dono, antes de operação financeira real.
7. **#45 — limite por empresa (Qualidade e segurança, resolvido nesta continuação):** `RAIZ_API_LIMIT_STORAGE_URI` está documentada para Valkey, separadamente do limite global. Duas apps reais de SlowAPI compartilham sete chamadas por empresa sob concorrência, preservam a cota ao reiniciar e mantêm a segunda empresa independente. Recusas são 429 com Retry-After e Problem Details. O teste substitui apenas autenticação/auditoria do banco; o contador usa Valkey real. Falha do backend é 503 sem fallback, coberta pelo conjunto de 13 testes. O padrão `memory://` continua sendo somente para um processo/testes; em produção é necessário configurar as duas URLs compartilhadas. Não confundir esses contadores de chamadas com o saldo em PostgreSQL.

O exame de git/segredos, Release `dados` e site é feito separadamente nesta entrega; não concluir ausência absoluta de dado pessoal a partir de revisão estática ou dos formatos de documentos nacionais.


## Detalhamento do PR #35

Revisão do diff de #35 (E5 e parte E8), das implementações atuais de título/documentos/aprendizado, migrações 0022–0025 e testes correspondentes. PR confirmado como merged na main em 12/11/2026. Publicações do Release, site e histórico de segredos são auditados pelo chat principal; esta nota não afirma cobertura desses artefatos.

## Correções pequenas nesta entrega

- `raiz/titulo/triagem.py`: `gabaritar` aceitava qualquer certidão com todas as matrículas lidas como exemplo negativo ("limpa") se não houvesse problema confirmado. A situação `revisar` também conta como lida e podia ser ilegível/incompleta. Agora, gabarito negativo exige `matricula_conferida`; revisão permanece em aberto. Regressão parametrizada cobre False, None e "false", sem banco real; teste existente de banco preserva problema positivo.
- `raiz/titulo/warc.py`: CPF percent-encoded em URL escapava da verificação anterior, e `motivo` era gravado sem máscara no índice JSONL exibido no laudo. A URL passa por decode antes da verificação; motivo usa mascaramento, `tirar_nomes` existente e Presidio local para nome/contato. Testes verificam recusa antes da rede/arquivo e sanitização antes de escrever o índice. O corpo WARC continua cifrado e sem chave só grava hashes.
- `testes/test_titulo.py`: teste que dependia de procurar dinamicamente um imóvel e podia dar `pytest.skip` agora usa fixture com a linha real `PA-1504950-0E3B...` e filtros correspondentes da amostra. Verifica entrada SIGEF/matrícula, risco médio antes e baixo após a única entrada simulada (certidão conferida). Não muda dados do produto nem fabrica o retorno da regra.

## Pendências maiores para o chat Documentos, título, vigilância, aprendizado e calendário

1. **Achados de matrículas diferentes se sobrepõem na view vigente.** `migracoes/versions/0022_titulo_achados.py:70` usa `DISTINCT ON (cod_imovel, fase, regra)`, mas `cadeia.origem` e achados da certidão são produzidos por matrícula. Para imóvel com duas matrículas, um achado pode esconder o outro no laudo com banco. A confirmação em linhas 74–75 também não compara `registro`/matrícula, propagando uma confirmação a outra matrícula com a mesma regra e valor. Exige nova migração, definição de identidade e regressão de duas matrículas, sem reescrever migração já aplicada.
2. **Decisão recalculada não acompanha confirmações humanas.** `raiz/titulo/tarefa.py:137–144` calcula nota/triagem exclusivamente dos achados recém-gerados em CSV; não lê confirmações do banco. O laudo com conexão mostra achados confirmados, mas a nota lida de `titulo_<mun>.csv` pode continuar anterior. Definir fonte e atualização da decisão após confirmar/corrigir antes de prometer convergência.
3. **Triagem rápida sem comparação geométrica é decisão de produto pendente.** `raiz/titulo/triagem.py:91–95` só reprova classes presentes fora de D1–D4: ausência de comparação não impede rápida; isso está explícito no comentário YAML (`sem comparação não segura`), mas contradiz docstring que pede CAR batendo com SIGEF. Não alterado por ser mudança de critério, não typo.
4. **Multígonos são reduzidos ao componente maior.** `raiz/titulo/tarefa.py:63–65` e `conferir._maior` descartam as outras partes na comparação. Um componente maior coincidente pode ocultar diferença nas partes menores. Exige definição geométrica conjunta e fixtures reais, sem usar esse resultado como validação integral até então.
5. **Privacidade de texto livre ainda depende de heurística.** `tirar_nomes` remove nomes com duas palavras iniciadas em maiúscula, não garante nomes minúsculos/isolados; URLs WARC também podem conter contato; motivo já recebe Presidio nesta entrega. Revisar contrato/allowlist do índice público e cobertura de nomes/contato antes de publicar laudos em lote. Correções acima fecham os casos demonstrados, sem afirmar anonimização completa.
6. **Pareamento do campeão/desafiante não exige mesmo horizonte.** `raiz/aprendizado/campeao.py:48–52` pareia por imóvel/alvo/data_corte e só exige maturidade do campeão. Metadados com horizontes distintos podem comparar tarefas diferentes, antes de o desafiante maturar. Rever chave de comparação e exigir maturidade de ambos.



## Auditoria de publicação — 12/11/2026

## Escopo e evidência

- Release `dados`: inventário de 40 assets (1.206.324.145 bytes), todos baixados para diretório temporário fora do git. Tamanho de cada download confere com o inventário; SHA-256 calculado por arquivo. Manifesto com hashes: [qualidade-release-2026-11-12.json](qualidade-release-2026-11-12.json).
- Release `vigilancia`: ainda não existe (`gh release view vigilancia` respondeu `release not found`); código da publicação examinado.
- Site público `https://bernardoemmel.github.io/Raiz/`: 120 recursos públicos lidos com sucesso, incluindo um CSV de cada tipo disponível por estado (96 CSV), 19 JSON (pontos, índice geográfico e códigos CAR), 2 GeoJSON de imóveis, JavaScript/CSS da página e página do produtor. Os índices por UF e `estados.json` foram lidos para escolher a amostra. Dados descomprimidos examinados: 35.553.677 bytes.
- Último deploy bem-sucedido do Pages: run `43261989677`, commit `e9ade022f8c2000d99f1cd8052102d459cea8d44`, artefato `13965080709`, 317.805.777 bytes. A tentativa de baixar o artefato completo por `gh run download` recebeu HTTP 403 no armazenamento do Actions; por isso a verificação direta do site é amostral, não integral.

## Método e limite

Varredura integral do conteúdo textual de CSV/JSON/KML e colunas string de Parquet, CPF/CNPJ (incluindo dígitos verificadores sem máscara), e-mails e telefones formatados; inspeção de nomes de campos pessoais. PMTiles decodificados para examinar as chaves e os valores textuais dos vetores. Não foram impressos valores pessoais nos relatórios. Reconhecer todo nome livre exige análise semântica; a ausência de padrão/coluna pessoal não prova ausência de qualquer nome escondido em texto livre. Nenhum dado remoto foi alterado.

## Resultados

A varredura integral dos 40 assets do Release terminou sem erro: 3.216 CSV, 22 JSON, 568 Parquet, 203 PMTiles (41.392 ladrilhos vetoriais decodificados) e 1 KML; 2.382.975.670 bytes de conteúdo descompactado. Nenhum CPF/CNPJ sem máscara ou e-mail/telefone reconhecido; os únicos nomes de coluna marcados pela regra ampla foram duas métricas legítimas citadas abaixo. As propriedades dos PMTiles são apenas `camada`, `cod_imovel` e `ha`.

A amostra HTTP do site também não contém CPF/CNPJ sem máscara, e-mail/telefone reconhecido ou coluna de identificação do dono. Os campos `pagamento_dono` e `dono_rs_ha_ano` encontrados nos CSV do Release são métricas de pagamento e não identificação pessoal; não devem ser removidos por uma regra genérica que proíba qualquer palavra `dono`.

## Pendências maiores para passagem

1. O portão de publicação (`raiz/executor/armazem.py`, `_publicar_uf`) só rejeita cabeçalhos CSV por uma lista curta de palavras. Geometrias/PMTiles, JSON de controle e `extra` passam sem uma validação equivalente; `motor/publicar_dados.py` também só verifica o cabeçalho CSV. Não houve vazamento confirmado nos artefatos examinados, mas o portão não impede uma coluna nova (ex.: contato/embargado) ou dado pessoal colocado em mensagem de erro. Padronizar um contrato de publicação com allowlist por produto e validação antes de qualquer upload, preservando métricas legítimas, é agora responsabilidade de **Qualidade e segurança** na continuação, coordenada com **Raiz dados do Brasil** para o contrato.
2. **Qualidade e segurança — vigilância:** `_publicos()` decide o que é público pelo nome do arquivo e `publicar()` envia os bytes sem revalidar o conteúdo. Hoje não há Release para medir exposição. Cobertura de publicação deve verificar dados/erros antes de habilitar a primeira rodada.
3. Contrato de localização/consentimento: parcialmente tratado pelo #52 durante a entrega. O site agora publica somente agregados; a exportação administrativa deve permanecer privada. Ver a atualização do item #40 acima, incluindo artefatos históricos.
4. Teste do Pará inteiro: o pacote publicado `raiz_PA.tar.gz` contém 144 tabelas `imoveis`, 144 `direto`, 144 `filtros`, 144 `mapbiomas`, 143 `certidoes` e nenhum `desenvolvedor`. Baixar esse Release não atende a pré-condição do teste que exige pelo menos 100 CSV `desenvolvedor`.

## Referências

- https://github.com/bernardoemmel/Raiz/releases/tag/dados
- https://bernardoemmel.github.io/Raiz/
- https://github.com/bernardoemmel/Raiz/actions/runs/43261989677


## Viabilidade do teste real do Pará no CI

Medição de 12/11/2026, sem alterar código de produto nem dados de entrada. Pacote `raiz_PA.tar.gz` do Release atual: 144 municípios, 345.870 imóveis, nenhum CSV desenvolvedor. Cada amostra usou todos os CSV originais daquele município e `raiz.restauracao.calcular_municipio(..., fontes_geo=())`, sem geometrias/fontes de rede.

| Município | Imóveis | Cálculo + CSV real |
| --- | ---: | ---: |
| 1501253 (quartil inferior por tamanho) | 864 | 23,130 s |
| 1508357 (mediano) | 1.813 | 53,962 s |

São 77,092 s para 2.677 imóveis; extrapolação simples: 166 minutos por processo para os 345.870, com variação por município. O BLAS usava vários núcleos, portanto dividir esse tempo linearmente pelo número de processos seria otimista.

Repetição do primeiro município com `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`: 19,535 s de relógio e 11,861 s de CPU para 864 imóveis. Nesse caso a extrapolação é 79 minutos de CPU; piso ideal em quatro núcleos, sem custos de leitura/agregação/otimizador, fica em ~20 minutos. Havia outros testes rodando no ambiente, logo CPU é a estimativa melhor para essa repetição.

O estado inteiro não foi executado; os cálculos e arquivos de benchmark ficaram fora do git.

## Opção recomendada

O chat de Dados deve concluir/publicar o conjunto de 144 desenvolvedor com a versão do modelo e a origem dos dados. O CI pode baixar snapshot versionado, conferir SHA-256 e contagens, guardar o pacote no cache e rodar o teste atual sem modificá-lo. O custo pesado fica na preparação do conjunto de referência; o teste continua usando saídas reais.

Até isso existir, gerar tudo em todo PR não atende a CI rápido em runner padrão; um primeiro preenchimento em job próprio com quatro processos/BLAS com um thread pode levar mais de vinte minutos e precisa de cache por versão de dados e modelo. Alternativamente, muitas máquinas em paralelo encurtam o relógio mas consomem dezenas de minutos de runner e não foram medidas. Não apresentar nenhuma dessas projeções como execução concluída.

Trocar o teste por dataset sintético de 144 municípios, gravar CSV vazio para satisfazer a pré-condição, reduzir o conjunto ou apenas renomear o benchmark altera sua semântica. Não fiz isso. Sem publicar/gerar os dados reais, a exigência literal de zero testes pulados continua pendente; falhar explicitamente em vez do skip evidencia a pendência, mas deixa o CI vermelho.


## Atualização da main durante a entrega

O PR #47 (mapa nacional/Pages) entrou na main durante esta auditoria. Os conflitos de CI e lock npm foram
resolvidos preservando as duas verificações de navegador: site estático Pages com fixtures e fluxo real da API.
Playwright foi alinhado em 1.65.0 nas duas ferramentas. O problema de mapa descrito acima refere-se à API
autenticada, não ao mapa estático corrigido pelo #47.

## Segredos no git

Gitleaks 8.24.3 percorreu todo o histórico disponível e o diff desta entrega com os valores ocultos. A única
ocorrência inicial era o identificador `regularizacao_chance_12m` em `docs/colunas.md`; a exceção exige ambos
o identificador exato e esse caminho. Não foi encontrada credencial real que exigisse revogação no material
verificado. Não foram reescritos commits ou logs remotos.

## Validação local da entrega

- Suíte Python completa com PostGIS e LanguageTool: **649 passaram, 1 skip (dados do Pará), 1 xfail preexistente
  (TIR)**. Após o merge do #47 e as últimas regressões de segurança/portão, 48 testes focados adicionais passaram.
  Após integrar #46/#50, mais 65 testes de Markdown/API/executor/cabeçalhos passaram.
- Build completo da fixture Pages (painel + produtor) e **141 testes Vitest passaram, nenhum skip**,
  após integrar também os PRs #46, #50 e #52. O teste de prospecção também passou. Pages e Lighthouse Agentic Browsing passaram em origem local.
- Cena-alvo Playwright/API passou antes e depois da correção de destino do link; a versão integrada é novamente
  executada pelo CI. Teste Pages vindo do #47 permanece no CI, sem remover cobertura anterior.
- Ruff check/format, actionlint e varredura CPF/CNPJ passaram. **624 pacotes** Python/npm/Rust conferidos, sem
  licença proibida ou desconhecida. Gitleaks passou no histórico integrado (151 commits analisados) e no diff.
- O CI remoto deve estar verde no commit da entrega antes de integrar; seu resultado fica no PR.


### Integração dos PRs #46 e #50

As entregas de processamento e páginas para agentes também entraram na main durante a validação. Conflitos
de package.json/lock resolvidos mantendo todos os scripts. A nova checagem de licenças barrou a CLI `sentry`
FSL trazida pelo SDK 11 transitivo do Lighthouse. Override restrito usa SDK 10.78.0 MIT; Lighthouse 13.6.0 e
a categoria Agentic Browsing foram preservados. A telemetria foi testada com transporte em memória (sem envio
externo); a auditoria do site e todas as licenças passaram. A auditoria Lighthouse local não comprova a presença
de llms.txt/robots.txt na raiz do domínio público do Pages, como já explica a passagem Telas e mapa.


### Integração do PR #52

O PR #52 entrou na main imediatamente antes do merge. O conflito em `raiz/api.py` foi resolvido preservando
as novas rotas da ficha paga e o middleware de segurança/CORS. A publicação agregada dessa entrega resolve
parte do achado #40, atualizado acima. Os testes de Pages, prospecção, Lighthouse e cena-alvo da API passaram
novamente; a leitura repetida dos CSV da fixture de pedidos foi reaproveitada para evitar timeout sem ampliar
o limite nem retirar testes. O CI completo é exigido novamente no commit atualizado antes do merge.


### Integração dos PRs #48 e #49

As entregas de aviso à Verra e lote/números também foram integradas antes de concluir o PR. O conflito do plano
foi resolvido mantendo ambas as passagens. O novo workflow `lote-para.yml` prepara a rodada real do Pará;
o teste estadual ainda tem a pré-condição dos arquivos desenvolvedor e permanece como pendência até a rodada
produzir um conjunto utilizável. Não foram disparados envios à Verra nem processamento de produção nesta auditoria.


## Revisão contínua — continuação de 12/11/2026

Marco inicial: merge do #51 (`78e13f7`). Main conferida até `9d5f591`; não foram confundidos PRs abertos com
código integrado. O histórico acima descreve a entrega inicial; esta seção registra mudanças posteriores.

| PR integrado | Diff revisado | Resultado e responsável |
|---|---|---|
| #53 (`7e045e1`) | Cache de matrícula, proveniência, captura/arquivo scd2, reexecução, sobrevivência, cron e Dockerfile | Nenhum bug pequeno confirmado nessa revisão. Captura de atributos usa números e categorias fechadas; fontes arquivadas têm allowlist. Cache exige integridade, receita e gabarito vigente, sem liberar simulado. Contatos usados no modelo não incluem nome/documento/contato do dono. Ativação/calibração e reconciliação de achados seguem com Documentos, título, vigilância, aprendizado e calendário. |
| #56 (`bb6d6c5`) | YAML dos cortes e documentação, após separar a dependência #53 | Resultado real mantém todos os cortes vazios; nenhuma promoção indevida nem resposta bruta de modelo adicionada ao git. O vínculo automático dos pesos à cascata permanece com o chat Documentos, título, vigilância, aprendizado e calendário. |
| #67 (`d98648f`) | Fonte Release/projeção pública, comparação e mapa, contornos autenticados, Playwright e workflows | Confirmado bug de privacidade: texto livre em `o_que_falta`, pendência desconhecida e versão do modelo atravessa a projeção do site; a máscara só remove documentos. Qualidade e segurança preparou correção pequena com lista fechada de frases e regressões. Nenhum vazamento real em arquivo remoto foi afirmado. Geometrias da API revalidam desbloqueio do cliente ativo e reservas. |
| #54 (`a4c1066`) | Calendário: coleta, vínculo, API/feed, função para MCP, cron, front, publicação | Texto do edital não é persistido e títulos da coleta são gerados pelo contrato. Confirmadas duas lacunas pequenas: o site copiava JSON/ICS remotos antes de revalidar e o mapa ignorava prazo de propostas iniciado no passado. Qualidade e segurança aplica projeção fechada antes da cópia, rótulos oficiais no navegador e uso do prazo na marca do mapa. Fonte de banco/consulta continua sem transporte MCP. |

A correção do #67 aceita somente frases do produto com posições numéricas controladas, mantém versões no formato
do motor e substitui conteúdo desconhecido por aviso de revisão. Duas regressões falham na versão integrada;
13 testes do contrato passam com a correção aplicada após integrar a main na entrega de continuidade.
A lista de rótulos também rejeita propriedades herdadas (`__proto__`/`constructor`).

Gitleaks 8.24.3 examinou `78e13f7..d98648f` com valores ocultos: 20 commits, 417.485 bytes, nenhum segredo
reconhecido. `git diff --check` também passou. Essa revisão não repete a auditoria dos 40 assets históricos;
a evidência de Release/site continua datada e com os limites documentados acima.

### Mudança de fluxo da cena-alvo pelo #67

O chat **Telas e mapa** desabilitou contato na interface até a fase final. O Playwright agora valida esse bloqueio,
login, pedido e as três opções; aciona interesse pela API do banco descartável para continuar cobrindo ondas e Pix.
Isso não é o percurso inteiro por cliques originalmente entregue pelo #51. **Produto e regras / Telas e mapa**
decidem quando reabrir contato na interface; **Qualidade e segurança** mantém a cobertura executável correspondente.
O ponteiro do lote ainda ausente não substitui as 144 tabelas reais de desenvolvedor exigidas pelo teste estadual.

### MCP ainda não entregue pelo chat dono

Na main `b63c555` não há servidor MCP. O #54 fornece a função somente leitura `proximos_eventos`, ainda sem transporte. No PR #45 aberto, `raiz/publica/servidor_mcp.py` apenas recusa inicialização
até OAuth 2.1. **Produto e regras** é responsável pelo servidor, catálogo de ferramentas e autorização. **Qualidade e
segurança** responde pelas suítes adversariais, latência e carga; não deve inventar um MCP alternativo nem registrar
um stub como prova de segurança/tempo. A integração dessas suítes exige o servidor real do chat dono.


### Revisão do calendário (#54)

O gate de publicação e a cópia para o Pages devem reconstruir JSON e ICS com o mesmo contrato: somente campos
permitidos, título por tipo/marco/referência numérica, nomes institucionais do manifesto e URL validada. Texto remoto
em campos conhecidos ou extras não pode atravessar por receber uma chave aparentemente pública. O front também
reconstrói os rótulos, aceita IDs/timestamps no formato do contrato e limita links aos hosts oficiais. Falha de validação
de um download interrompe o build; indisponibilidade de rede só reutiliza uma cópia que seja validada novamente.
Nomes livres em URLs ainda exigem cuidado: padrões de documentos/contato e parâmetros pessoais não provam ausência
de todo nome em slug. Sem regra de URL por fonte, não declarar anonimização absoluta; contrato por fonte pertence a
**Documentos, título, vigilância, aprendizado e calendário**, com revisão de **Qualidade e segurança**.

O mapa considera `prazo` quando presente, mantendo o leilão marcado durante propostas/inscrições já iniciadas.
Regressão cobre o intervalo e o desaparecimento após o prazo. As fixtures conservam a natureza sintética e passam a
usar identificadores e fontes no formato real, sem uma exceção de validação para testes.

Validação desta revisão: 22 testes Vitest de calendário/Release e o teste de sincronização do manifesto passaram;
Chromium do calendário (1440/768/360 px) e da prospecção passaram. Gitleaks examinou também `d98648f..a4c1066`:
13 commits, 150.961 bytes, nenhum segredo reconhecido. Três regressões de integração do build também passaram:
JSON/ICS reconstruídos sem texto pessoal, cache offline revalidado e download HTTP 200 inválido interrompendo o build.

A validação da URL foi unificada também em `Evento`, antes de persistir ou devolver a fonte pela API. Sete regressões
falhavam na main: e-mail no nome de arquivo, e-mail com codificação repetida, telefone e parâmetros de contato/nome/
credencial. A correção recusa esses caminhos e remove fragmentos sem alterar o identificador público do ato. Foram
34 testes focados de calendário/site/URL aprovados; a rodada focada excluiu seis testes de banco para não disputar o
PostGIS com a suíte completa em andamento. Não houve skip novo ou retirada desses testes do CI.


### Histórico e últimas integrações (#68, #70, #71, #73 e #74)

- **#68, histórico:** confirmado que texto pessoal em `cod_imovel` passava pela normalização canônica e podia
  ser salvo/publicado no histórico. A validação central de privacidade agora roda antes de gravar o retrato e na
  leitura para publicar, inclusive em registros antigos cuja integridade canônica foi recomposta. Quatro regressões
  cobrem recusa e zero upload. Não foram alterados algoritmos de aprendizado nem retratos históricos remotos.
- **#70, Release básico/calendário:** mantidos os agregados e o bloqueio de tabelas detalhadas antigas. A ausência
  do calendário gera JSON/ICS vazios válidos; coleta/cache recebidos passam pela projeção segura. HTTP 200 inválido
  reprova o build. O teste novo do download foi ajustado para exigir esse bloqueio, sem fallback silencioso.
- **#71, ficha visual:** rotas de geometria, metadados e imagem exigem desbloqueio do cliente ativo. Resposta
  geométrica tem propriedades fechadas e imagem usa cache privado. Não houve bug pequeno adicional confirmado.
- **#73/#74, mobile/domínio:** preservados teclado, axe, Lighthouse e builds em `/Raiz/` e `/`. Domínio/base/URL
  são validados antes do build; não há credencial no CNAME. A exceção Gitleaks de JDBC foi conferida: aponta para
  uma única linha histórica sem usuário/senha; não libera outros caminhos/commits ou segredos do serviço.

**Dados** precisa formalizar em `docs/colunas.md` o novo `imoveis_basicos_<IBGE>.csv`, anunciado pelo Release e
aceito pelo front, mas sem produtor/contrato integrado na main revisada. O portão bloqueia formato sem contrato;
não inventa colunas de área ou aceita tabelas incompletas como se fossem a tabela técnica `imoveis`.
A publicação detalhada do motor exige os campos documentados e a correção das áreas já relatadas.

### Ativação automática do MCP e decisão sobre recorrência

Por orientação explícita do fundador, não há servidor/branch alternativo para testar e não foi criada revisão horária.
O job `mcp` roda em todo PR/push: ausência da implementação produz `::warning`, resumo e artefato com
`ensaios_executados=false`. O stub exato anterior é reconhecido por hash. Entrada MCP alterada, servidor ou dependência
MCP ativam a exigência dos ensaios; erro de OAuth, falta de adaptador, tempo, efeitos ou carga falham o job.

**Produto e regras** entrega com o servidor o adaptador `testes.mcp.produto.integracao()`, conforme
[`testes/mcp/README.md`](../../testes/mcp/README.md), iniciando OAuth/MCP reais e observadores independentes.
**Qualidade e segurança** fornece corpus, auditor, cliente, limite de 5 s por ferramenta, Locust e runner CI já ligados.
A ausência do agente leitor recebeu posteriormente autorização específica de aviso, conforme a atualização
ao fim desta passagem. Isso não cobre falta de adaptador OAuth/MCP, inventário incompleto ou falhas reais.

A correção de concorrência do limite compartilhado executa a sanitização/gravação HTTP fora do loop assíncrono,
sem remover Presidio. O teste usa dois apps, logger JSON real e 50 chamadas concorrentes; exige exatamente sete
admitidas e 43 recusas 429. Falha do Valkey permanece 503, nunca substituída por contador por processo.


### Integração do #55 — retomada privada

A main `3546687` acrescentou a retomada de cinco fatias. Revisados workflow, destino por ID fixo, verificação
`draft=true` antes de cada operação, hashes/comprovantes, extração ZIP/TAR e ausência de cache/artifact de dados.
O orquestrador não chama o publicador aberto; usa modelo/lock originais e preserva dez fatias prontas. Seus **78
testes passaram** no branch integrado. Não foi disparada retomada nem alterado Release nesta revisão.

O arquivo privado em rascunho não deve ser promovido a Release público: contém resultados completos e não passa
pelo contrato público. **Lote e números / Dados** continuam responsáveis por separar uma projeção publicável e
resolver os achados de qualidade; a conclusão do cálculo privado não libera a publicação detalhada bloqueada.


### Validação da continuidade antes da entrada do MCP

- Suíte Python completa com PostGIS, Valkey e LanguageTool reais: **1.250 passaram**, um skip herdado (tabelas
  reais do Pará ainda ausentes) e um xfail herdado (TIR), em 460,86 s. O conferidor de skips aprovou apenas essas
  duas pendências conhecidas. Após integrar #55, seus **78 testes adicionais passaram**. O CI executa o conjunto
  integrado novamente antes do merge.
- **200 testes Vitest**, dez testes de configuração, build painel/produtor e Playwright de Pages, prospecção,
  calendário e cena-alvo passaram. Axe/teclado/celular passaram; Lighthouse mobile teve mediana 97–100 e
  acessibilidade 100. Pages e Lighthouse passaram tanto em `/Raiz/` quanto em `/` com domínio de teste.
- Playwright com API/PostGIS reais: **um fluxo passou** (link único, pedido, três opções, interesse via API após
  validar bloqueio da interface e Pix de teste). Não foi realizada cobrança nem mensagem externa.
- Ruff, formatação de 405 arquivos e actionlint passaram. **670 dependências** sem licença bloqueada/desconhecida;
  **815 arquivos** sem CPF/CNPJ detectado; Gitleaks percorreu **321 commits / 28,98 MB**, sem segredo reconhecido.
- O runner MCP confirmou `estado=ausente`, aviso explícito e `ensaios_executados=false`; não houve aprovação
  fictícia da integração. Valkey concorrente, portões de publicação e observabilidade estão cobertos pela suíte.

Os números descrevem as execuções locais. O resultado remoto e o commit de integração ficam registrados no PR.


### Integração do #75 — fechamento de Telas e mapa

Revisado o diff `3546687..74ab7fc`: somente passagem e plano, sem mudança executável, dado pessoal ou segredo
identificado. Preservadas as notas sobre domínio real, lotes ausentes e publicação coordenada com a migração
privada. A main foi incorporada antes do merge; os oito jobs foram exigidos novamente no commit atualizado.


### Integração da API paga e do MCP (#45/#69)

Os PRs #45/#69 entraram durante a execução do CI do #76. Integração com `9d5f591` preserva os oito jobs, o novo
Playwright de aprovação humana, OAuth/sentinela da ponte interna, CSP mais estrita, Problem Details e CORS do MCP.
Os limites globais e por empresa têm variáveis distintas, ambas documentadas para o mesmo Valkey. Redis-py 6.4.0
satisfaz a interseção das dependências, sob MIT; **683 pacotes** passaram no verificador de licenças.

Foi confirmado e corrigido um bug pequeno de cobrança: consultar disponibilidade, comparar lotes e o fallback de
acompanhar contato criavam UUID novo em cada tentativa. Após timeout, repetir a ferramenta podia criar outro débito.
As três ferramentas agora exigem `idempotency_key` reutilizável. **23 testes passaram**, incluindo Postgres isolado,
504 após commit e repetição da mesma intenção: uma operação, um débito e saldo exato. O GET de acompanhamento não
vira nova submissão. Não foram alterados preços, critérios de negócio nem o agente de outro chat.

O E2E da API paga passou com conta, contrato/sinal, pedido, três opções, aprovação humana e Pix de teste. Respeitou
429 e Retry-After sem ampliar tetos. O Playwright da página de aprovação também passou, sem acesso externo.

A main nova contém seis ferramentas de pedidos, mas nenhuma lê os três tipos de entrada do corpus AgentDojo.
**Produto e regras** deve entregar o agente/leitor e observadores do trajeto real. O adaptador de Qualidade não
inventa um agente que ignora o documento e só chama uma ferramenta, pois isso aprovaria uma defesa não testada.
O runner grava as evidências de latência/carga e falha separadamente pelo corpus não executado. A decisão sobre
uma eventual exceção específica para essa dependência foi encaminhada ao fundador; até resposta, falha é falha.


### Evidências do MCP integrado

Com logs JSON/Presidio ativos: seis ferramentas entre **0,040 e 0,090 s**; Locust normal **195 requisições**, zero
falhas, máximo **558 ms**; saturação **374 requisições**, **281 HTTP 429** com Retry-After válido, zero falhas,
máximo **993 ms**. Todas as ferramentas tiveram respostas válidas em ambas as fases. O orçamento global de teste
é 18 chamadas por janela de dois segundos na saturação; não altera a configuração do produto. Os ensaios repetem
intenções idempotentes e medem resposta/admissão na fila, não conclusão do cálculo pesado nem capacidade máxima.

OAuth usa JWT RS256 descartável, JWKS HTTP local e verificador/vínculo de empresa reais; não é ensaio da tela
ou fluxo de login do Keycloak. Arquivos temporários têm modo 0600; não há .env/credenciais externas, DNS/conexões
externas são bloqueados. **24 testes** focados de adaptador/cliente/runner passaram. O runner completo gravou
medições e terminou **exit 1 por corpus pendente**, sem simular leitura/agente. Esses números não aprovam o corpus.

O CI anterior identificou uma fixture do publicador legado sem comprovante `rodada.json`, obrigatório no Actions.
A fixture passou a criar a rodada sintética e sempre executar com `GITHUB_ACTIONS=true`; a proteção do produto
permaneceu intacta. Também foram recusados parâmetros libpq de redirecionamento (`host`, `hostaddr`, `dbname`,
`service`) nas URLs dos bancos descartáveis de carga/E2E, antes de qualquer migração destrutiva.

### Validação integrada após #45/#69

A suíte Python completa com PostGIS, Valkey e LanguageTool reais terminou com **1.682 testes aprovados** em
495,49 s. O conferidor aceitou somente o skip herdado das tabelas reais do Pará e o xfail herdado da TIR; nenhum
teste novo foi pulado. Os resultados anteriores à entrada do MCP acima permanecem como histórico, não como
aprovação da versão integrada.

No [CI do commit 59e47cb](https://github.com/bernardoemmel/Raiz/actions/runs/43303892861), **sete dos oito jobs
passaram**, incluindo **1.686 testes Python** e os dois E2E; somente o job `mcp` reprovou. Latência e carga do MCP
passaram. O artefato `resultado-mcp` registra as medições e `corpus=false`; o job reprova com a dependência de
**Produto e regras** explícita. Não há merge enquanto o CI estiver vermelho. A passagem não considera o corpus
aprovado nem a leitura de documentos entregue.

A revisão final acrescentou regressões do isolamento do ensaio: `connect_ex` e `sendto` também recusam destinos
externos antes de chamar o sistema, e o registro de tentativas é conferido após encerrar o servidor mesmo quando
o corpus lança sua falha pendente. Uma tentativa de rede não pode ficar escondida por essa pendência. **30 testes
focados de MCP** e **13 testes do limite por empresa** passaram; o segundo conjunto usa duas apps e Valkey real.

### Integração do #72 — arquivo privado e sétima ferramenta

A main `88860b6` retirou a publicação de camadas completas, financeiros e folhas individuais; o Release aberto
fica restrito ao contrato `publico_basico`. Preservada essa fronteira durante os conflitos: não foi restaurado
o upload legado de pacotes completos nem a leitura de snapshots financeiros pelo site. As regressões de texto
pessoal, instruções e propriedades herdadas agora exigem recusar o snapshot inteiro. **219 testes Vitest** e
dez testes de configuração passaram após a integração.

O arquivo bruto autenticado preserva originais para auditoria e reprocessamento, inclusive dados com pendências
conhecidas; isso não aprova as medidas nem autoriza sua exposição. O portão público valida a projeção antes do
upload aberto. A rodada do Pará verifica o destino privado a cada transferência; **39 testes de rodada,
qualidade e transporte privado** passaram, incluindo recusa quando o rascunho deixa de ser privado. O contrato
quantitativo completo e seus testes permanecem disponíveis para revisão dos cálculos. **Dados / Lote e números**
continuam responsáveis pelas áreas/datas inconsistentes já relatadas. O contrato básico foi explicitado em
`docs/colunas.md`, resolvendo a pendência anterior de formato sem produtor integrado.

Revisão de `consultar_ficha`: exige conta ativa, sinal/contrato, escopo, quota e desbloqueio do CAR pela própria
empresa, revalida reserva de terceiro e retorna somente a projeção da ficha, sem cobrar outra compra. Não houve
bypass concreto confirmado. O adaptador usa o desbloqueio real sobre CAR da amostra, com crédito fictício.

Com as **sete ferramentas**, latência máxima **0,262 s**; Locust normal **157 requisições**, zero falhas, máximo
**0,941 s**; saturação **251 requisições**, **152 HTTP 429** válidos, zero falhas, máximo **1,748 s**. Todas tiveram
respostas válidas nas duas fases. **36 testes focados** passaram. O runner continua terminando em exit 1 somente
pelo corpus sem agente leitor, com `latencia=true`, `carga=true`, `corpus=false`; a ficha não lê documentos do corpus.

O portão da projeção passou em **90 testes focados**, além das projeções reais **AC (23 arquivos, 7,28 s)** e
**PA (145 arquivos, 32,46 s)**. No PA, 2.035 CARs usam o nome do município do recorte atual em vez do código
embutido no CAR; a validação aceita estritamente um desses dois nomes oficiais IBGE, sem liberar texto livre.
O resumo público aplica a triagem de saltos à intensidade `tco2_ano_aptas/ha_carbono` e recusa medidas não
suprimidas de grupos pequenos. Nenhum dado foi enviado ao Release por esses ensaios.

Corrigida a saída do importador `raiz.executor.publicar_entrada`: não imprime mais o retorno privado nem
nomes arbitrários de pacotes/membros em erro. Sucesso usa resumo fechado e falha usa mensagem fixa sem traceback.
**Nove regressões** passaram com canários de dado pessoal/segredo em caminhos, retorno e exceções. Os E2E da API/Pix
e da aprovação humana passaram após #72, respeitando o limite por empresa; não houve pagamento ou acesso externo.

O [CI do commit integrado 55b923d](https://github.com/bernardoemmel/Raiz/actions/runs/43308020772) aprovou sete dos
oito jobs, com **1.868 testes Python**, um skip e um xfail herdados. O único job reprovado foi o corpus MCP pendente;
tempo e carga das sete ferramentas passaram também no runner remoto. Esses resultados precedem a integração do #77.

### Integração do #77 — catálogos, proveniência e cota global

Revisados o catálogo público, a catalogação privada, as atestações e a admissão conjunta dos jobs. As dependências
de metadados foram incorporadas ao lock; **709 pacotes** passaram na checagem de licenças. Actionlint 1.7.12,
adotado pela main, foi executado localmente. Não foram iniciados jobs de processamento ou uploads de dados.

Achados pequenos confirmados: nomes de assets privados podiam aparecer em diagnósticos, relatórios e subjects de
atestação; o validador Croissant também emitia o nome do Dataset em WARNING. Os diagnósticos passam a usar textos
fixos/identificadores técnicos. A atestação privada usa somente o digest dos bytes, sem nome ou hash do nome;
o workflow recusa listas legadas antes de chamar a ação de atestação, inclusive em passos `always()`. **Oito
testes do portão de workflow** passaram com canários de nome/contato e subjects inválidos.

Também foi confirmada uma corrida de admissão: a reserva do catálogo podia continuar vinculada à tentativa
anterior e ser removida por um snapshot atrasado de término, liberando indevidamente a 16ª vaga. A confirmação
passa pelo CAS e atualiza o escopo/tentativa, seguindo o protocolo já usado pelos lotes do Pará.
O conjunto integrado de atestação, portão de workflow, cota e lotes teve **55 testes aprovados**. A suíte completa
foi iniciada novamente após estabilizar a integração; os resultados finais ficam também no PR #76.

**Raiz dados do Brasil — integração do finalizador histórico a confirmar:** o teste de finalização de um executor
antigo substitui `conferir_processamento_seguro`. No fluxo real, a própria reserva ainda `in_progress` pode colocar
a ref antiga na lista de executores proibidos, mesmo após terminar o cálculo. É necessário definir como comprovar
essa conclusão sem dispensar a verificação dos demais executores antigos ativos. O preflight não foi relaxado;
esta revisão não declara o fluxo histórico integralmente validado.

## Entrega independente de proveniência, cota e revisão contínua — 12/11/2026

Revisão dos PRs #72/#77 sobre a main `b624b10`. Esta entrega fecha dois vazamentos pequenos e uma corrida de
admissão: o importador e o catálogo podiam imprimir nomes/retornos privados ou mensagens de terceiros; nomes de
assets privados também podiam chegar ao subject público da atestação; uma reexecução do catálogo podia perder
sua reserva ao receber o término da tentativa anterior, admitindo indevidamente o 16º trabalho.

As CLIs usam mensagens fixas, e os diagnósticos do validador Croissant preservam nível e falha sem mostrar o nome
do Dataset. Subjects privados usam somente o SHA256 dos bytes, sem nome nem hash do nome; listas legadas são
convertidas ou recusadas pelo portão dos workflows antes da atestação, inclusive em passos `always()`. A reserva
do catálogo confirma por CAS o escopo e a tentativa atual, mantendo a cota global de 15 trabalhos.

Os testes focados exercitam nomes/contatos e segredos sintéticos no retorno, nos caminhos, nas exceções e nos
warnings; cobrem também listas de atestação legadas, aliases, versões de conteúdo e a corrida de reexecução.
**190 testes focados passaram, sem skips**, em 31,17 s. Ruff e formatação globais, actionlint 1.7.12 e a conferência
do diff passaram. O [CI final do #81](https://github.com/bernardoemmel/Raiz/actions/runs/43315818208) aprovou os seis
jobs e 2.003 testes Python, com o skip estadual e o xfail de TIR então herdados. O merge foi feito em `436c7b6`,
depois de atualizar a main e confirmar o CI verde. Nenhum upload de dados ou processamento de produção foi
disparado por esta validação.

Os demais portões de qualidade dos dados, observabilidade, carga e a integração adversarial do MCP continuam no
**PR #76**. O corpus desse PR permanece explicitamente bloqueado: **Produto e regras** precisa entregar o agente
leitor de certidão, edital e arquivo. Esta entrega independente preserva `ci.yml`, MCP e a política do corpus;
seu resultado não equivale a uma aprovação dos testes de injeção pendentes.

### Revisão dos PRs #79 e #80

Main atualizada até `bea53bd`, sem conflito. O diagnóstico de falha do SIGEF agora passa pelo sanitizador antes
de ser persistido ou retornado: mensagens de rede, parser e banco podem conter nome, contato ou credencial.
O filtro de embargos recusa geometria ausente, vazia ou sem componente poligonal depois do reparo, após selecionar o município e os termos ativos;
antes, um WKT inválido convertido em `None` no espelho podia virar área de restrição zero. A guarda aceita
polígonos reparáveis e mantém a exclusão de cancelados, desembargados e outros municípios.

As regressões falharam antes das correções. **31 testes de SIGEF e E2 passaram**, sem skips; Ruff e formatação
dos quatro arquivos passaram. O retry de download do #80 não apresentou novo achado confirmado: erros de
validação continuam fora da repetição. A revisão não encontrou segredo real no diff; não equivale a uma
auditoria dos novos assets externos ou dos serviços em produção. Não restou achado maior confirmado em #79/#80.

O portão de atestação usa o checkout `publicador-atual` quando o executor está preso a uma referência antiga.
O verificador não existe nessas referências: procurá-lo sempre na raiz bloqueava até a lista já convertida pelo
finalizador atual. **31 testes de atestação passaram**, incluindo execução real do passo em checkout legado,
recusa de subject legado e falha fechada quando o checkout atual falha; actionlint e Ruff passaram.

O [PR #81](https://github.com/bernardoemmel/Raiz/pull/81) foi integrado na main `436c7b6` com os seis checks verdes
no [CI 43315818208](https://github.com/bernardoemmel/Raiz/actions/runs/43315818208): **2.003 testes passaram,
1 skip estadual herdado e 1 xfail de TIR**. A entrega abaixo elimina a exceção do skip estadual.

### Estado atualizado da referência real do Pará

A publicação privada integral já foi concluída por **Lote e números**, conforme sua passagem: 144 municípios e
345.870 imóveis. A pendência histórica acima não é mais produzir as tabelas `desenvolvedor`. **Qualidade e segurança**
está integrando no #76 a preparação autenticada das previsões e entradas/geometrias congeladas, conferência de hashes
e execução do teste estadual. **Lote e números** mantém o contrato, modelo e futuros snapshots. Esses dados financeiros
por imóvel não devem ir para cache ou artifact público; a recomendação histórica de cache público está superada.
O ensaio real posterior passou, conforme a seção seguinte; os resultados anteriores com skip continuam históricos.

### Referência estadual autenticada e limite Valkey — continuação após #81

O teste estadual foi executado com asserções e sensibilidade originais, sem recalcular municípios: **144 municípios,
345.870 imóveis, 446,2 s, pico RSS 6.840,2 MiB**. Download de 334.001.998 bytes em 9,4 s; preparação em 8 s,
com aproximadamente 1,42 GB temporários. O preparador confere manifests, hashes, cenário, modelo, identidades e
geometrias congeladas. O token fica somente no passo de preparação; o teste roda em processo sem credenciais,
com saída e JUnit privados apagados. Timeout e interrupção encerram também os descendentes do processo.
**73 regressões do preparador/supervisor/portão passaram**; não foi criado cache ou artifact público desses dados.
O CI agora exige exatamente um caso estadual aprovado e não aceita mais seu skip. PR de fork é explicitamente
bloqueado antes de acesso ou credenciais; os demais testes continuam sendo executados. O acesso do job privado
e a suíte integral foram confirmados no CI `43324357697`, conforme o resultado abaixo.

Corrigida uma opção de configuração do limitador compartilhado: a query da URL do Valkey não pode substituir
os prazos de conexão/leitura nem habilitar retries ou health checks adicionais. URLs válidas com banco, keepalive
e TLS foram preservadas. **31 testes de limites passaram**, incluindo Valkey real e rejeição antes de criar conexão.

O CI anterior do #76 (`1efc7c3`, run `43311611896`) aprovou sete dos oito jobs e **2.224 testes Python**, com o
skip estadual e o xfail conhecidos. A suíte local desse marco passou com **2.147 testes**, antes de #79/#80.
O único job vermelho daquele CI foi o corpus MCP: latência e carga passaram, mas falta o agente leitor de documentos
de **Produto e regras**. Essa pendência permanece explícita; nenhuma aprovação de corpus ou merge com CI vermelho
foi feita. A entrega independente #81 não altera essa política.

O CI `43319627024` confirmou que `contents: read` não acessa o draft privado: o preparador respondeu somente
"acesso autenticado ao snapshot privado recusado". Os outros **2.327 testes passaram**, sem skips; o estadual
falhou explicitamente e a TIR permaneceu como xfail executado. A documentação do GitHub exige acesso de push
para drafts. A correção isola `contents: write` somente no job `referencia_para`, que baixa e testa a referência;
as actions desse job compartilham essa permissão, por isso ele não executa o restante da suíte. Nenhuma operação
de publicação ou criação de segredo foi adicionada.

O caso estadual roda em paralelo ao restante, que exclui somente esse nó. `checagens` exige ambos os jobs
aprovados, junta seus JUnits e recusa ausência, duplicação ou skip. Fork não executa o job privado e não recebe
aprovação estadual; configuração administrativa de envio de tokens de escrita/segredos a forks continua a ser
confirmada pelo fundador (consulta desta conta recusada com 403). Não há `pull_request_target` nem novo PAT.
Uma interrupção do ambiente matou a primeira suíte local integral perto de 70%, depois de aprovar o estadual;
essa execução não foi registrada como aprovada. A retomada com log persistente terminou com sucesso.

O check final conserva o nome `checagens`; o job geral passa a `testes_python`. Assim, uma proteção da main
que já exige `checagens` continua exigindo a suíte completa, antes mesmo da atualização manual da lista de checks.

O CI `43324357697` aprovou **nove de dez jobs**: **2.360 testes gerais passaram**, um estadual foi executado no job
paralelo (**1 aprovado em 484,76 s**) e a TIR foi executada como xfail conhecido. O portão combinado aprovou os dois
relatórios, sem skips nem duplicação; preparação autenticada e limpeza dos dados privados passaram. O único job
vermelho continuou sendo o corpus MCP sem agente leitor. Depois disso, o nome do portão foi preservado como
`checagens`, com **49 regressões de divisão/portão aprovadas**; nenhuma asserção ou dado do teste estadual mudou.

A suíte local integral da entrega independente terminou com **2.079 aprovados, zero skips, um xfail executado**,
em 1.390,97 s. O JUnit passou no portão obrigatório. Os resultados privados do filho foram apagados; o snapshot
temporário usado para essa validação será removido após concluir a entrega.

### Entrega da referência real do Pará — #83 integrado

O [CI 43327983910](https://github.com/bernardoemmel/Raiz/actions/runs/43327983910) aprovou os oito jobs:
**2.106 testes gerais e um estadual**, sem skips, com a TIR conhecida executada como xfail. O estadual levou
336,65 s; o portão `checagens` confirmou a união dos relatórios sem caso ausente ou duplicado. Após atualizar
a main, o #83 foi integrado em `6f49dfc`. Os dados financeiros não foram publicados nem guardados em artifact/cache.

### Corpus MCP: aviso autorizado e expiração da exceção

Em 12/11/2026, o fundador autorizou **aviso só para a ausência do agente leitor de documentos** e exigiu que
o aviso vire falha automaticamente quando esse leitor estiver ligado ao MCP. Essa decisão supera o bloqueio
registrado nos ensaios históricos acima; não transforma aqueles resultados em aprovações do corpus.

OAuth, todas as sete ferramentas, latência inferior a 5 s e as duas fases de carga continuam obrigatórios.
Somente depois desses ensaios aprovados é permitida a saída parcial com `corpus=false` e aviso explícito.
Erro de transporte, autenticação, adaptador, limite de chamadas, tempo, rede externa ou corpus executado reprova.

**Produto e regras** deve ligar o leitor no ponto canônico `raiz.publica.agente_documentos` e fornecer o adaptador
`testes.mcp.leitor_documentos.integracao`, conforme o README da suíte. A presença de qualquer um exige o corpus;
importação quebrada, fábrica ausente ou integração incompleta falham. Não há flag permanente para desativá-lo.
O aviso também depende da superfície de API/MCP auditada e do inventário completo das ferramentas: mudanças
invalidam a exceção, exigindo a integração ou revisão explícita da ausência do leitor. A referência não deve ser
atualizada automaticamente para obter CI verde. Um agente externo sem registro ou mudança observável no
repositório/servidor fica fora dessa detecção; sua ligação precisa seguir esse contrato.

**43 regressões passaram**: exceção prematura, OAuth, prazo, ambas as cargas, Retry-After, saída do contexto,
leitor registrado/importação quebrada, flag antiga e corpus executado com falha não são convertidos em aviso.
O ensaio HTTP real terminou com código 0 e estado parcial: sete ferramentas, máximo **0,200 s**; carga normal
com **196 chamadas**, saturação com **424 chamadas e 335 respostas 429 válidas**, zero falhas. Todas as ferramentas
responderam nas duas fases; o inventário real correspondeu à referência auditada sem alteração. O aviso e os
JSONs indicam `latencia=true`, `carga=true`, `corpus=false`. Não houve aprovação simulada do corpus.

### Revisão preventiva do #82 e correção de ZIP

O diff do #82 foi revisado no head `7ab48525084c352e71ffe8c4de603a37a6a035e8`, antes do merge. Gitleaks com
redação examinou 14 commits e 301.135 bytes sem reconhecer segredos. Não foram auditados novos assets remotos.
Uma falha de CRC do ZIP MapBiomas podia carregar o nome do membro remoto na exceção `BadZipFile`, depois
impressa pelo motor ou incorporada ao resumo público. A correção pequena troca erros de ZIP por mensagem fixa,
sem encadeamento. Três regressões passaram: CRC inválido, arquivo truncado e extração válida; falhas não salvam
TIFF nem perdem o pedido aceito. A correção foi aplicada à main de base, sem incorporar o #82 ainda aberto.

**Raiz dados do Brasil — finalizador histórico:** o preflight de `scripts/publicar_metadados.py` ainda conta a
própria reserva antiga enquanto o job está em execução, embora a etapa do motor tenha concluído com sucesso.
O finalizador chama esse preflight dentro do mesmo job. O novo gatilho pós-run do #82 atende o catálogo separado,
mas não resolve esse caminho. Reprodução em memória confirmou bloqueio com job `in_progress` e liberação
somente com job `completed`; o teste atual substitui o preflight. O chat dono precisa de teste integrado que permita
o encerramento da própria reserva e preserve o bloqueio de outros executores antigos ativos. Qualidade não alterou
esse protocolo de coordenação.

### Conferência integral dos contêineres de publicação

A revisão final reproduziu um desvio no leitor TAR: conteúdo depois do terminador e um segundo stream gzip
ficavam fora da inspeção, embora os bytes fossem conservados no asset. O portão de upload e a CLI agora usam
o mesmo leitor seguro, com CRC/término gzip, cabeçalhos USTAR, preenchimento e terminador TAR conferidos.
Metadados livres, linkname em arquivo regular, texto após NUL e streams/caudas adicionais são recusados antes
de publicar. A descompressão usa blocos de 64 KiB em arquivo temporário apagado, sem segunda cópia integral
descompactada em memória. Falhas da CLI e do upload preservam mensagem fixa, sem caminhos ou conteúdo privado.
Os produtores e os contratos das tabelas foram preservados; não houve correção silenciosa dos dados históricos.
Diretórios da CLI também precisam ter o nome exato de uma UF real; texto livre ou caminhos normalizados não são
ignorados. **115 testes de publicação, qualidade, projeção e armazenamento passaram**; após a guarda final de
diretórios, **85 testes das duas fronteiras passaram**. As regressões reproduziram as aceitações indevidas antes
das correções. Ruff global, actionlint e a varredura de 953 arquivos por CPF/CNPJ passaram. A suíte integral e os
dez jobs do commit final são exigidos antes do merge; os resultados ficam no [PR #76](https://github.com/bernardoemmel/Raiz/pull/76).

O primeiro CI desse fechamento identificou três possíveis chaves na referência MCP. Conferência dos bytes
provou que eram SHA-256 de `raiz/api.py`, `raiz/publica/api.py` e `raiz/publica/oauth.py`. As exceções de Gitleaks
ficam restritas ao commit `e7074b4`, arquivo e linhas exatos; não liberam hashes/chaves futuras nem o arquivo todo.
Gitleaks passou nos 367 commits (30,55 MB). Um controle sintético em commit novo, no mesmo caminho e linha,
continuou sendo detectado; o diretório temporário desse controle foi apagado.
