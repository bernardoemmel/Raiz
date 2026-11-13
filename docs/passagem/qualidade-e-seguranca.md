# Qualidade e segurança — passagem

Entrega de 12/11/2026. Área: CI, E2E, infraestrutura e segurança. Correções em produto são pontuais,
com regressões. Mudanças de contrato/arquitetura ficam para os chats responsáveis abaixo.

## Entregue

- CI em seis jobs paralelos, cache uv/npm/Chromium/LanguageTool, Dependabot semanal, Gitleaks em histórico completo,
  licenças com inventários obrigatórios, build igual ao site e suíte Python integral com PostGIS/PDF/LanguageTool.
- Playwright com API/PostGIS reais: link de uso único, milhão de créditos no Pará, três lotes, interesse e Pix local
  de teste; nenhuma credencial real de pagamento. Front com testes sem skips e geometrias determinísticas.
- Cabeçalhos HTTP, limite por IP/login, destino canônico do link, Presidio antes dos logs e diagnósticos persistidos,
  inclusive erros publicados no Release. Pix de teste identificado e sem data 1970 quando não tem validade.
- Correções pequenas encontradas na revisão: rebanho zero, gabarito de certidão em revisão, índice WARC e alertas.
- Procedimento manual da proteção da main em [operação](../operacao.md#proteção-da-main-o-fundador-ativa-à-mão).

## Estado dos testes: Pará obrigatório e TIR pendente

Nenhum teste foi retirado para acelerar o CI. O teste estadual roda isolado em paralelo aos demais e o portão
reúne os dois relatórios. O teste antes opcional
`test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta` passou a exigir o snapshot privado real de 144 municípios,
publicado por **Lote e números**. A execução real foi demonstrada e a entrega independente abaixo integra a
preparação autenticada no CI; sem snapshot ou com skip, o resultado falha. Dados financeiros por imóvel nunca
entram em cache/artifact público. O GitHub recusou o token somente de leitura para acessar o draft; o acesso
necessário fica restrito ao job estadual interno, e a aprovação integral do CI permanece exigida antes do merge.
Além disso, permanece o `xfail` preexistente de TIR do plantio (`test_plantio_da_7_a_9_pct_no_central_r11`):
o teste executa, mas a conta ainda diverge da referência de 7–9%; **Lote e números / Produto e regras** devem resolver o critério
em `docs/restauracao-rodada11.md`. O portão de resultados recusa qualquer outro skip/xfail novo.
O teste da cena-alvo usa a amostra real do repositório e já roda inteiro, sem esse pré-requisito nacional.

## Integração e operação que exigem outro chat

- **Telas/API:** a fonte de mapas pede `/geo/brasil/*`, mas a API atual só aceita município numérico. A sessão
  cliente autoriza pedidos, enquanto os dados/mapas ainda exigem o token interno `VITE_RAIZ_API_TOKEN`. Não publicar
  esse token no build público. O E2E usa token descartável restrito ao ambiente local; não declara mapa nacional
  autenticado resolvido nem oculta as rotas ausentes.
- **Operação:** o limite desta entrega é por processo. Antes de vários workers/réplicas, usar controle compartilhado
  no proxy e testar concorrência. Validar IP real/TLS na terminação HTTPS. O modelo NER pode deixar nomes livres
  passar; não registrar texto pessoal bruto. Não houve limpeza retroativa de bancos/logs externos nesta entrega.
- **Dados/operação:** a proteção da main bloqueará o push direto que atualiza `motor/README.md`; migrar para PR,
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
| #45 | Diff da API pública, cobrança, privacidade, migração | PR aberto; conflitos e lacunas abaixo devem ser resolvidos pelo chat dono antes do merge. |

## Correções pequenas e testes

- `raiz/rebanho.py`: total PPM igual a zero não é elevado ao piso de lotação. `testes/test_rebanho.py`: regressão preserva ambas as propriedades e exige gado/metano P10/P50/P90 zero.
- `raiz/operacao/alertas.py`: Presidio em título/texto/detalhe/nota antes de gravar. `raiz/operacao/backoffice.py`: filtro recursivo no JSON de resposta para alcançar dados legados, além dos logs. `testes/test_operacao_alertas.py`: verifica conteúdo salvo e resposta legado sem endereço de contato.
- `raiz/titulo/triagem.py` e `raiz/titulo/warc.py`: ver detalhamento do PR #35 abaixo.
- `testes/test_titulo.py`: fixture usa imóvel real já presente na amostra e condições explícitas; remove skip condicionado à seleção dinâmica da amostra.

## Mudanças grandes para os chats responsáveis

1. **#40 — exportações administrativas e artefatos históricos (Telas e mapa / Dados), parcialmente resolvido pelo #52:** o build do site passou a publicar somente agregados, retirando fichas, CAR, CSV e geometrias individuais, inclusive sobras de builds anteriores. A exportação `raiz/fichas_lote.py` foi explicitamente classificada como privada; continua contendo `_cod_imovel`, `_plus_code`, `_omaps` e perímetro. Garantir que seu destino permaneça privado e fora de qualquer upload público. O prefixo `_` não protege arquivos. O Release histórico continua público e exige tratamento separado; a alteração no código do site não torna privados os artefatos já publicados.
2. **#41 — validade de resultados anteriores (Produto/regras):** o executor inclui hash de código da tarefa e refaz os rebanhos afetados; execução manual `raiz funil` decide pelo hash de premissas/tabela e precisa de `--refazer` para resultados produzidos antes da correção PPM zero. Não alteramos as premissas científicas de limitar lotação/total.
3. **#44 — calibração da cascata (Vigilância/aprendizado):** o corte é ligado ao nome do modelo, mas não à versão dos pesos, prompt ou gramática. Há alerta posterior de desvio de subida; trocar pesos mantendo alias pode reutilizar um corte inválido. Versionar artefato/prompt no corte e exigir reavaliação real antes de promovê-lo. Sem corte preenchido na main, o caminho continua em votação.
4. **#45 — conflito de migração (Produto/regras):** nova `0020_api_publica.py` declara revision `0020`/down_revision `0019`, identificador já usado por `0020_alertas_operacao.py` da main. Rebase e renumeração são necessários antes de integrar; não foi alterado o PR de outro chat.
5. **#45 — sanitização da API pública (Produto/regras):** `sem_dado_pessoal` remove nomes de chaves recursivamente, mas retorna strings livres sem limpeza; `limpar` usa regex e não Presidio, nem reconhece nome livre/CNPJ alfanumérico. Reusar a função central de sanitização desta entrega nas fronteiras de persistência/resposta e cobrir entrada indireta dos modelos, erros e atributos.
6. **#45 — cobrança com erro imprevisto (Produto/regras):** a dependência cobra antes de executar a rota e a restituição só ocorre depois de `await call_next`; exceção não tratada pode sair antes do estorno. Fazer transação/compensação idempotente testada em falhas de infraestrutura antes de ativar cobrança real.
7. **#45 — limite por empresa:** armazenamento `memory://` do SlowAPI é por processo; múltiplos workers ou reinícios não compartilham contagem mensal/diária. Para promessa de limite por empresa em produção, usar armazenamento compartilhado e teste concorrente.

O exame de git/segredos, Release `dados` e site é feito separadamente nesta entrega; não concluir ausência absoluta de dado pessoal a partir de revisão estática ou dos formatos de documentos nacionais.


## Detalhamento do PR #35

Revisão do diff de #35 (E5 e parte E8), das implementações atuais de título/documentos/aprendizado, migrações 0022–0025 e testes correspondentes. PR confirmado como merged na main em 12/11/2026. Publicações do Release, site e histórico de segredos são auditados pelo chat principal; esta nota não afirma cobertura desses artefatos.

## Correções pequenas nesta entrega

- `raiz/titulo/triagem.py`: `gabaritar` aceitava qualquer certidão com todas as matrículas lidas como exemplo negativo ("limpa") se não houvesse problema confirmado. A situação `revisar` também conta como lida e podia ser ilegível/incompleta. Agora, gabarito negativo exige `matricula_conferida`; revisão permanece em aberto. Regressão parametrizada cobre False, None e "false", sem banco real; teste existente de banco preserva problema positivo.
- `raiz/titulo/warc.py`: CPF percent-encoded em URL escapava da verificação anterior, e `motivo` era gravado sem máscara no índice JSONL exibido no laudo. A URL passa por decode antes da verificação; motivo usa mascaramento, `tirar_nomes` existente e Presidio local para nome/contato. Testes verificam recusa antes da rede/arquivo e sanitização antes de escrever o índice. O corpo WARC continua cifrado e sem chave só grava hashes.
- `testes/test_titulo.py`: teste que dependia de procurar dinamicamente um imóvel e podia dar `pytest.skip` agora usa fixture com a linha real `PA-1504950-0E3B...` e filtros correspondentes da amostra. Verifica entrada SIGEF/matrícula, risco médio antes e baixo após a única entrada simulada (certidão conferida). Não muda dados do produto nem fabrica o retorno da regra.

## Pendências maiores para Documentos, título e aprendizado

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

1. O portão de publicação (`raiz/executor/armazem.py`, `_publicar_uf`) só rejeita cabeçalhos CSV por uma lista curta de palavras. Geometrias/PMTiles, JSON de controle e `extra` passam sem uma validação equivalente; `motor/publicar_dados.py` também só verifica o cabeçalho CSV. Não houve vazamento confirmado nos artefatos examinados, mas o portão não impede uma coluna nova (ex.: contato/embargado) ou dado pessoal colocado em mensagem de erro. Padronizar um contrato de publicação com allowlist por produto e validação antes de qualquer upload, preservando métricas legítimas, envolve o chat de dados.
2. Vigilância: `_publicos()` decide o que é público pelo nome do arquivo e `publicar()` envia os bytes sem revalidar o conteúdo. Hoje não há Release para medir exposição. Cobertura de publicação deve verificar dados/erros antes de habilitar a primeira rodada.
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
do diff passaram. O CI integral será exigido no PR antes do merge. Nenhum upload de dados ou processamento de produção foi
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
integra a referência em entrega independente a partir de `436c7b6`, preservando toda a cobertura anterior em oito
jobs. O job geral passa a se chamar `testes_python`, com 30 minutos; `referencia_para` executa o estadual e
`checagens` passa a ser o portão final, mantendo o nome do check obrigatório antigo. Não há novas dependências.
**Lote e números** mantém o contrato, modelo e futuros snapshots. Dados
financeiros por imóvel não devem ir para cache ou artifact público; a recomendação histórica de cache está superada.

A execução estadual real, com entradas, geometrias e sensibilidade completas, passou em **446,2 s**, com pico de
RSS de **6.840,2 MiB**, cobrindo os 144 municípios e 345.870 imóveis. A cópia dos cinco arquivos de preparação,
supervisão e regressões foi conferida por SHA-256. Não houve novo benchmark isolado; a suíte integral desta entrega
inclui o caso estadual uma vez. A tentativa inicial de CI com `contents: read` foi recusada pelo GitHub, como registra
o [run 43319627024 do #76](https://github.com/bernardoemmel/Raiz/actions/runs/43319627024): 2.327 outros testes
passaram, o estadual falhou explicitamente por falta de preparação e a divergência conhecida de TIR continuou
como xfail. O corpus MCP desse PR continua uma falha separada e não foi dispensado.

A correção da permissão foi comprovada no [job estadual do CI 43324357697](https://github.com/bernardoemmel/Raiz/actions/runs/43324357697/job/131552929571):
preparação autenticada aprovada, **1 teste estadual passou em 484,76 s**, e limpeza dos dados temporários aprovada.
Isso comprova o acesso ao draft no job isolado, mas não substitui a aprovação da suíte completa e do CI desta
entrega independente antes do merge.

Releases em rascunho exigem acesso de escrita/push. Somente `referencia_para`, para código interno, recebe
`contents: write`; os demais jobs mantêm leitura. Essa permissão alcança também as actions do job, não apenas
o passo que recebe o token no ambiente. Não foi criada credencial estática nem adicionada operação de publicação.
O checkout não persiste credenciais; o processo pytest recebe apenas a pasta preparada. Seu subprocesso usa
ambiente restrito e diagnósticos/JUnit privados apagados ao terminar. O JUnit público recebe
mensagem fixa em falhas; os dados temporários são apagados por `always()`. Sem preparação válida, caso ausente,
duplicado, pulado ou falho, o portão recusa o resultado. O caso estadual é a única exclusão do job geral, pois
é executado no job paralelo; uma regressão compara a coleção real com e sem esse seletor. O portão exige ambos
os jobs aprovados e exatamente um estadual no conjunto dos dois XMLs, sem permitir que um relatório esconda
falha do outro. O xfail conhecido de TIR também precisa executar: `xfail(run=False)` reprova.

Fork não executa o job privilegiado e o portão sinaliza a validação privada ausente. Dependabot também pode
receber token restrito a leitura; alterações revisadas precisam ser promovidas para uma branch confiável para
essa validação. As opções administrativas de enviar escrita/segredos a forks não foram verificadas (consulta
recusada com 403) nem alteradas; devem permanecer desativadas, conforme o guia manual. O workflow alterável
por um PR não substitui essa fronteira do GitHub. Operação: [teste estadual privado](../operacao.md#teste-estadual-privado-do-pará).

A primeira suíte local desta worktree foi interrompida pelo reinício do ambiente perto de 70%, depois de
executar o estadual; ela não é contabilizada como suíte aprovada. O resultado aprovado é o da retomada abaixo,
registrado em log persistente.

A retomada integral terminou com **2.079 testes aprovados, nenhum skip e 1 xfail conhecido de TIR**, em
**1.390,97 s (23 min 10 s)**, com PostGIS, LanguageTool e o snapshot estadual real. Após essa execução, a partição
do CI foi atualizada para o job privado isolado e o portão conjunto; o corpo científico do teste, seu helper e
os arquivos do snapshot permaneceram idênticos. **106 testes focados do preparador, supervisor, seleção e portão
passaram**, em 6,29 s; Ruff global (473 arquivos), actionlint e diff passaram. O portão novo também aprovou o XML
real da suíte integral, aceitando somente o xfail de TIR executado. O CI da entrega independente ainda é exigido
antes do merge.

Os demais portões, observabilidade, carga e corpus permanecem no PR #76. O corpus continua bloqueado; esta entrega
não altera sua política nem equivale a aprovação dos testes de injeção pendentes.
