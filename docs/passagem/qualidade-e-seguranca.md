# Qualidade e segurança — passagem

Entrega de 12/11/2026. Área: CI, E2E, infraestrutura e segurança. Correções em produto são pontuais,
com regressões. Mudanças de contrato/arquitetura ficam para os chats responsáveis abaixo.

## Entregue

- CI em seis jobs paralelos, cache uv/npm/Chromium/LanguageTool, Dependabot semanal, Gitleaks em histórico completo,
  licenças com inventários obrigatórios, build igual ao site e suíte Python integral com PostGIS/PDF/LanguageTool.
- Playwright com API/PostGIS reais: link de uso único, milhão de créditos no Pará, três lotes, interesse e Pix local
  de teste; nenhuma credencial real de pagamento. Front com 81 testes sem skips e geometrias determinísticas.
- Cabeçalhos HTTP, limite por IP/login, destino canônico do link, Presidio antes dos logs e diagnósticos persistidos,
  inclusive erros publicados no Release. Pix de teste identificado e sem data 1970 quando não tem validade.
- Correções pequenas encontradas na revisão: rebanho zero, gabarito de certidão em revisão, índice WARC e alertas.
- Procedimento manual da proteção da main em [operação](../operacao.md#proteção-da-main-o-fundador-ativa-à-mão).

## Pendência explícita: zero testes pulados

Nenhum teste foi retirado ou selecionado parcialmente para acelerar o CI. O teste opcional preexistente
`test_lote_do_para_inteiro_fecha_ou_diz_o_que_falta` ainda depende das 144 tabelas reais `desenvolvedor` do Pará,
que não existem no Release atual. Portanto a exigência literal de zero skips **não está concluída**.
O chat Dados precisa publicar o conjunto versionado; então o CI deverá baixar/conferir/cachear o snapshot.
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
| #40 | Diff fichas, API, revisão e cartão; consultas e contratos de serialização | A API interna e o cartão por código curto são caminhos distintos. Encontrado risco de publicação de localização exata via fichas/rows.json; mudança de contrato registrada abaixo. Sem CPF/nome de dono confirmado no diff. |
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

1. **#40 — localização e consentimento em exportações (Telas e mapa / Dados):** `raiz/fichas_lote.py::linha_do_cartao` inclui `_cod_imovel`, `_plus_code`, `_omaps` antes do aceite. Prefixar `_` não impede leitura de rows.json; `gravar_municipio` também grava fichas com perímetro e localização exata. Isso conflita com a regra explicitada em `raiz/publico.py` de que a localização exata só vai a público depois do aceite. Separar artefato interno/público e aplicar o consentimento no servidor e no produtor do arquivo, incluindo expiração/revogação. Publicar somente depois de definir o contrato. É risco demonstrado no código; o escopo da auditoria de artefatos públicos desta entrega é descrito separadamente.
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
3. Contrato de localização/consentimento: o auditor dos PRs apontou `rows.json` com `_cod_imovel`, `_plus_code` e `_omaps` antes do aceite; prefixo `_` não torna um arquivo privado. Alinhar arquivos públicos com o contrato de aceite requer revisão pelo chat responsável (E9).
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
