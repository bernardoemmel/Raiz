# Passagem do chat "Produto e regras" (13/11/2026)

## Indisponibilidade do fornecedor antes da primeira resposta

A execução `43431732302` (`b8f6f57`, juiz v9/fixture v2) subiu a pilha saudável,
mas a primeira chamada ao Claude recebeu HTTP 503. O artefato `14042200020`
conserva a única interação (503), sem resposta do modelo nem sessão concluída;
SHA-256 `240353babf994ee04ca0780c7fbf0877c6dd08dec759646c94407e7717d583a0`.
Foi iniciada `43433142975` na mesma revisão, novamente com todas as 96 sessões.
É repetição após indisponibilidade de transporte, sem substituição de respostas
ruins, mudança de modelo, critérios ou permissões. A execução incompleta permanece
registrada e não é uma referência de pass^4.


## Sétima campanha: 43 sessões, interrupção reproduzida e corrigida

A execução `43368316000`, congelada em `ea25614`/juiz v8, concluiu 43 sessões
com zero chamada proibida e zero violação. A quarta tentativa de `limite_empresa`
parou na descoberta MCP. Artefato `14012541009`, SHA-256 conferido, 90 arquivos
sanitizados; números parciais em
[`../medicoes/agentes-2026-11-13-campanha7.json`](../medicoes/agentes-2026-11-13-campanha7.json).
Não há pass^4 válido nem referência aprovada dessa execução.

O diagnóstico com API/MCP, PostGIS e Keycloak reais reproduziu o problema sem
inferência: três sessões alcançaram o 429 empresarial; a quarta recebeu 429 global
por IP na descoberta, com Retry-After de 57 s. As 30 leituras de preparação por
empresa também consomem essa proteção. A fixture v2 aguarda 61 s antes de preparar
cada tentativa desse cenário, preservando ambos os limites e o 429 empresarial.
A espera precede a sessão do agente e entra somente na duração total da campanha.
O diagnóstico corrigido completou as quatro sessões, cada uma descobrindo oito
ferramentas e recebendo o 429 empresarial esperado, sem nova inferência.

Na terceira tentativa de pedido demorado, o último recibo era `working`, mas o
worker concluiu depois, antes do snapshot final. O juiz v9 explicita que o agente
só conhece o último estado observado; snapshots posteriores continuam verificando
efeitos, sem exigir antecipar uma mudança. Não altera notas antigas, gabarito,
permissões ou metas. A próxima campanha começa novamente pelas 96 sessões.
Passaram 127 testes focados; a suíte completa foi reiniciada após o reinício do
ambiente, agora com a main `6b9c377` e suas dependências de avaliação.


## Sexta campanha completa: meta reprovada, próxima configuração preparada

A [campanha 43362401481](https://github.com/bernardoemmel/Raiz/actions/runs/43362401481),
congelada em `0690d3b`/juiz v7, concluiu 96 sessões. Foram 17/24 tarefas com quatro
sucessos: limite inferior de pass^4 **70,83%**. O valor exato ficou indisponível por
quatro recusas do fornecedor em `outra_empresa`; nenhuma recusa foi repetida.
Houve quatro chamadas proibidas e quatro violações registradas em `injecao_webhook`:
o agente consultou opções (`comparar_lotes`) quando a pessoa pediu andamento
(`acompanhar_contato`). A campanha está reprovada e não é referência aprovada do CI.

Médias: 2,52 passos e 8,99 s por sessão; maior latência MCP 0,103 s. O tempo acumulado
do agente foi 863,04 s, e a campanha com preparação/juiz levou 1.361,05 s. Relatório
agregado, passos e tempos por tarefa estão em
[`../medicoes/agentes-2026-11-13-campanha6.json`](../medicoes/agentes-2026-11-13-campanha6.json).
Artefato `14010053982`: 196 arquivos sanitizados; configuração, 96 registros e hashes
de todos os traces/cassetes conferidos. As notas originais permanecem intactas.

A próxima configuração explicita a ferramenta de andamento após webhook, a consulta
solicitada antes de uma reserva condicionada, a consulta para subsidiar revisão humana,
a justificativa de empate pelo custo, os IDs completos e a distinção entre cálculo e
contratação. Explica que a partilha é dos créditos e que o piso de 20% não é opcional.
O juiz v8 distingue solicitar recálculo humano de executar uma operação proibida;
não muda o gabarito, as permissões nem as notas antigas. Distingue a recusa do juiz
(julgamento indisponível) da resposta vazia/interrompida do agente (fracasso observado,
sem nota semântica inventada). Nenhuma delas provoca nova chamada ao fornecedor.
A classificação é congelada antes da próxima execução; a sexta conserva pass4 null.
Passaram 83 testes da integração e 109 do avaliador/replay após os ajustes, além de Ruff.
Resumo único: 7.735 bytes. A suíte local da revisão v7 passou com **2.720 testes**,
um xfail esperado e a referência estadual separada; sem skips de mídia.
A main `692663c`, incluindo Calendário e pasta do banco/comprador, foi incorporada
depois dessa suíte; a sétima campanha mantém a revisão original `ea25614`.


## Quinta campanha e correção da quantidade de evidências

A campanha `43359802697`, congelada em `ac020d3`/juiz v5, concluiu 20 tentativas
sem chamada proibida nem violação crítica e parou na 21ª. O juiz citou 13 trechos
válidos de polling, mas o Pydantic admitia apenas oito. A API de inferência não
recebia esse limite local. Não há pass^4; as notas negativas originais permanecem.
Custo/cronograma passou quatro vezes; disponibilidade, pequenas fazendas e comparação
ainda tiveram falhas de comunicação/julgamento. O artefato `14007429943` foi preservado.

O juiz v7 admite todas as citações verificáveis, sem teto arbitrário de oito;
IDs inexistentes continuam inválidos. Explicita que uma fonte foi dividida em
partes contíguas, evitando tratar o fim de um trecho como truncamento da resposta.
Mantém indisponibilidade terminal do v6 e não corrige notas antigas. O MCP agora
inclui `versao_modelo`, reutilizando a projeção da REST; texto livre vira null.
O contrato orienta comunicar versão ausente e qualificar o alcance como estimado
já no resumo inicial. Passaram 74 testes focados e Ruff. A nova campanha completa
será iniciada com essa configuração e com as versões da ficha da main.

## Retomada: correção do teste do agregador e main de avaliação

O CI `43369152999` aprovou 2.936 testes Python, mas o teste do agregador ainda
exigia a expressão antiga `always()`. Ele agora confere `always() && !cancelled()`,
conservando todas as exigências sobre resultados, artefatos e o caso estadual.
Front, e2e, segurança, segredos, workflows, agentes e referência estadual passaram.
A main `6b9c377` (avaliação de carbono/equidade) foi incorporada, inclusive sua
política de não cancelar o CI anterior e o histórico completo para auditoria.
Passaram 70 testes focados e Ruff após a integração. O CI seguinte parou na
instalação do uv porque a consulta da versão mais recente atingiu a cota da API
GitHub. CI e medição agora fixam uv 0.13.8, já usado na execução anterior,
eliminando essa consulta e mantendo as dependências travadas. O CI será repetido.

A sétima campanha (`43368316000`, `ea25614`) terminou incompleta após 43 sessões;
a descoberta MCP falhou na quarta tentativa de limite por empresa. O artefato
`14012541009` conserva 90 arquivos sanitizados. Não existe pass^4 dessa campanha.
O diagnóstico e a referência diária continuam na entrega seguinte.


## Integração com a pasta do banco e comprador

O PR #96 incorporou a main `692663c` (PR #98), preservando a pasta com fontes,
histórico, proteção das exportações e migração 0035. O conflito no registro de
medições foi resolvido conservando a campanha anterior do chat Ficha e o juiz v6
desta entrega. A sétima campanha do Produto permanece fixada em `ea25614`, na
próxima branch; esta integração não altera sua configuração nem suas evidências.
Passaram 52 testes focados com PostGIS, incluindo a migração da pasta, MCP e
Calendário, além de Ruff. O CI completo confere esta revisão antes do merge.


## Integração com Calendário e processamento publicados na main

A main `52118b5` (PRs #95 e #97) foi incorporada ao PR #96. Os dois registros de
`proximos_eventos` foram unificados: permanece a ponte corporativa `/v1/eventos`,
com OAuth, conta ativa, cota por empresa e telemetria, reutilizando a função do
Calendário. A projeção incorpora `resposta_publica` e sua conferência de fontes,
UID, CAR público e identificadores privados; a resposta do MCP conserva seu contrato.
Os testes do Calendário da main foram preservados/adaptados para a ponte única.
O agregador do CI não entra na fila quando a execução já foi cancelada por uma
revisão posterior. Falhas efetivas continuam reprovando; isso evita reter o CI novo.
As mudanças de processamento e sua política de continuidade vieram intactas;
nenhum workflow de lotes ou motor foi cancelado ou alterado por este trabalho.
O CI anterior conferiu oito ferramentas, 42 rotas OpenAPI, resumo de 6.097 bytes,
24 cenários em Compose (máximo 0,057 s), front, e2e, segurança e referência estadual.
Passaram 48 testes focados com PostGIS e Ruff; a nova integração terá seu próprio CI antes do merge.


## Integração da main com versões da ficha

A main `60e17b0` (PR #93) foi incorporada ao PR #96, preservando versões da ficha,
proteção das exportações, preços e a atualização periódica da base na agenda.
O juiz v6 concilia os trechos por IDs do v5 com o estado de indisponibilidade da main.
Recusa do fornecedor fica registrada sem nova tentativa; erro de formato/citação do
juiz também deixa `pass4=null`, com limite inferior conservador e bloqueio da aprovação.
Os demais cenários continuam, sem inventar nota nem substituir tentativas. Passaram
101 testes focados de runner, julgamento e agregação, mais 74 testes de API, MCP,
ficha e pilha com PostGIS. Ruff e o teste de preservação da latência do VCR passaram. A campanha `43359802697` já
estava congelada em `ac020d3`/v5; seus artefatos manterão essa proveniência original.
O replay diário permanece na próxima entrega, condicionado à referência auditada.


## Preparação do replay diário

A branch `produto-agentes-replay` implementa a regressão das 96 sessões contra MCP,
OAuth, banco e worker reais, sem chave Anthropic. A referência exige campanha completa,
meta atingida, zero chamadas proibidas e hashes íntegros. O workflow real serializa execuções da mesma branch; branches isoladas de outros
chats não bloqueiam nem substituem a execução pendente deste trabalho. O agente é reproduzido pelo
VCR; notas semânticas ficam congeladas e barreiras determinísticas são recalculadas.
Isso não mede novamente o pass^4 do modelo. As cassetes integrais do agente e do juiz
permanecem auditáveis, incluindo correções de citações.

O diagnóstico com cinco fluxos gravados revelou que VCR reaplicava o filtro de resposta
ao carregar a cassette e zerava sua latência. O carregamento agora preserva bytes e
tempo gravados. Os cinco fluxos repetiram integralmente suas chamadas contra serviços
reais, sem trocar estados nem respostas do MCP; são diagnóstico, não uma campanha
aprovada. Passaram 46 testes iniciais do runner, replay e julgamento. Depois da integração com
a main, a suíte local teve 2.462 aprovações, um xfail esperado e o caso estadual
separado; os dois skips de cartão/vídeo foram executados depois e passaram. Após
incorporar o juiz v4, passaram 50 testes focados. O diagnóstico ampliado repetiu
16 cenários da terceira campanha, sem novas inferências. A referência de 96 sessões
ainda depende da campanha completa; o passo obrigatório do CI não foi publicado sem ela.

## Juiz com trechos identificados

A quarta [campanha real](https://github.com/bernardoemmel/Raiz/actions/runs/43357340888),
na revisão `553aa94`, concluiu três tentativas e parou por citação inexistente na quarta,
mesmo após duas correções. A tentativa anterior `43355796771` foi cancelada ainda
pendente, sem inferência, para isolar a execução por branch; nenhum trabalho de outro
chat foi cancelado. Ainda não existe pass^4 válido.

O juiz v5 seleciona IDs de trechos fornecidos pelo instrumentador, em enum no esquema.
Todas as fontes são particionadas integralmente e na ordem original, sem filtrar
passagens favoráveis. O código expande o ID no texto exato e valida a citação;
não altera notas, justificativas ou violações. IDs inexistentes continuam sendo erro.
Isso elimina a redigitação de números e frases pelo juiz e dispensa chamadas de
correção. Resposta interrompida do agente continua sendo fracasso explícito, sem
contornar a recusa. O gabarito, as 24 tarefas e a meta permanecem iguais.
Passaram 96 testes focados na implementação e 48 após integrar com o replay.
A nova campanha usará também a main `3a73879`, já incorporada.

## Medição real e operação: PR #85 integrado, primeira campanha incompleta

O [PR #85](https://github.com/bernardoemmel/Raiz/pull/85) foi mesclado em `c3bf907`, após integrar
a main do PR #82 e passar nos nove jobs do [CI](https://github.com/bernardoemmel/Raiz/actions/runs/43339076294).
Foram 2.297 testes Python aprovados, um xfail esperado e o caso estadual aprovado no job separado.
Inspector/OAuth real, vacuum, manifesto e os 24 cenários em Compose passaram. O resumo tem 3.138 bytes.
A maior latência de submissão no ensaio determinístico foi 0,063 s; isso não mede o tempo do Claude.

A primeira [campanha real](https://github.com/bernardoemmel/Raiz/actions/runs/43341704532) rodou
na main em 13/11/2026 UTC, com Claude Sonnet 5.5 e pilha Compose real. Concluiu 35 tentativas;
a 36ª falhou no juiz, que rejeitou uma citação apenas por retirar a ênfase Markdown.
**Campanha incompleta: não há pass^4 válido.** Nas 35 tentativas houve sete chamadas proibidas
(quatro montagens quando cabia consulta e três acompanhamentos com o ID comercial errado),
sem violação crítica registrada nesse conjunto parcial. O artefato preserva essas falhas;
nenhuma cassete parcial entra como aprovação no CI diário.

A branch `produto-agentes-medicao` corrige a indicação do próximo passo assíncrono,
a distinção entre IDs e a escolha entre consulta e montagem, com base nesses traces.
O erro 402 ganha link de conta para uma pessoa entrar e autorizar contrato/sinal/recarga,
reutilizando os serviços existentes; abrir a página não cria cobrança. Erros de ferramenta
passam por RFC 9457 sem eco dos argumentos inválidos. O juiz v2 aceita somente a retirada
de delimitadores de ênfase/código da resposta; palavras, números, negações e fontes de serviço
continuam exigindo citação literal. Os 24 desafios e as metas permanecem iguais.
Será rodada outra campanha completa, com cassetes novas e hashes da configuração congelados.
O segredo ficou somente no GitHub Actions, sem ser trazido para o Cloud.

A segunda [campanha](https://github.com/bernardoemmel/Raiz/actions/runs/43347357547),
na revisão `3303cf3`, concluiu 17 tentativas e parou novamente por citação do juiz
(inicial maiúscula trocada por minúscula). Teto de custo, pequenas fazendas e comparação
tiveram quatro sucessos cada. Houve uma chamada proibida: consultar nova oferta quando
a pessoa queria conferir o pedido existente. Ainda não há pass^4 válido. A próxima
revisão dá prioridade explícita ao pedido existente e explica os percentis.
O juiz v3 pode corrigir citações em até duas chamadas adicionais, com esquema que
NÃO admite modificar notas, justificativas ou tipos de violação. Citação inexistente
continua sendo erro; não há normalização de números ou troca silenciosa de julgamento.
As interações originais e as correções ficam no VCR, com contagem e consumo acumulados.

Validação desta etapa: suíte local com 2.305 testes aprovados, um xfail esperado e
o caso estadual reservado ao job privado do CI; após o ajuste do juiz, 47 testes
focados passaram. O Chromium validou login, contrato e geração de Pix só após clique.
O PR #96 teve 2.308 testes Python aprovados no Actions, mais o caso estadual no job
separado; front, segurança, workflows e e2e passaram. Inspector/OAuth, vacuum e manifesto
confirmaram oito ferramentas, 39 rotas e resumo de 5.431 bytes. O ensaio determinístico
foi atualizado para conferir o Problem Details estruturado, sem depender de espaços
no JSON; os 24 cenários passaram novamente no diagnóstico local (máximo 0,129 s).
Gitleaks encontrou uma URL JDBC sem credencial no histórico de outra branch; a exceção
restrita ao fingerprint foi comprovada com a varredura dos 518 commits, sem achados.
A terceira [campanha real](https://github.com/bernardoemmel/Raiz/actions/runs/43349634089)
usou `23ec54c` e o juiz v3. Concluiu 64 tentativas e parou no julgamento da 65ª:
fornecedor devolveu `stop_reason=refusal` sem conteúdo tanto ao agente quanto ao juiz.
Ainda não há pass^4 válido. Nas 64, houve uma chamada proibida (comparação paga não
solicitada ao pedir reserva com escopo desligado), sem violação crítica registrada.
Disponibilidade, teto, pequenas fazendas e comparação tiveram quatro sucessos cada.
Custo/cronograma expôs confusão entre percentis de volume/custo e ausência de decisão
humana sobre o risco. O contrato foi corrigido, incluindo retry sem comparação extra.

O juiz v4 recebe o contrato MCP e evidências de intervalo; distingue débito de saldo
de cobrança Pix. O cliente respeita `consultar_apos_segundos` antes de executar um
poll escolhido pelo modelo, com espera registrada no tempo total. Barreiras conferem
esse intervalo. Uma resposta interrompida/vazia recebe todos os critérios falsos,
sem nova chamada ao fornecedor, preservando chamadas proibidas e violações já feitas.
Assim a recusa não é contornada nem transformada em sucesso, e não interrompe as
outras tentativas. Falha de julgamento de uma resposta completa continua sendo erro.
Passaram 104 testes focados; resumo único com 6.097 bytes. Será iniciada nova campanha.
A integração posterior com a main `c65d7bb` preserva a entrada de certidões, a
vigilância dos lotes e as novas fontes do Calendário. O conflito na montagem da API
foi resolvido mantendo os dois registros independentes de rotas.
A main avançou novamente para `3a73879` (painel de acerto, alcance nacional,
sensibilidade e diagnóstico de travas); incorporada sem conflito, preservando
as novas rotas e o teste do pedido nacional. Passaram 96 testes focados e Ruff
nessa integração. Nenhuma rodada do Pará foi executada.



A preparação foi feita na branch `produto-agentes-validacao`. O gabarito v2 preserva os 24 desafios e a meta,
mas permite consultar a operação assíncrona devolvida na própria tentativa; a versão anterior
proibia esse acompanhamento e exigia seu resultado. A permissão não autoriza consultar outro pedido.
O cenário de injeção na sugestão verifica a remoção do texto pela projeção do servidor, sem
injetar uma resposta fictícia depois do MCP. A versão e os hashes são registrados e conferidos durante a campanha.

Runner Claude/MCP, juiz separado, VCR, Compose, Inspector, vacuum e workflow semanal estão implementados.
Passaram 123 testes focados, Ruff, a varredura de privacidade e a auditoria de 857 pacotes sem impedimento.
PKCE foi comprovado no Keycloak real para consultar/pedir e reservar; o servidor manteve o perfil OAuth 2.1.
O vacuum não encontrou erros; o Inspector CLI passou com o servidor MCP e o Keycloak reais em Compose.
A suíte integral e a conferência conjunta dos 24 cenários passaram no CI antes do merge.
O primeiro CI subiu toda a pilha e revelou a ausência de `sub` no token Keycloak: o realm recebeu
o mapper oficial `oidc-sub-mapper`. A conexão local com token PKCE real passou no Inspector,
negociando 2026-07-28; a validação de sujeito do MCP permanece obrigatória.
Os 24 cenários também concluíram no diagnóstico local com API/worker, PostGIS e Keycloak reais,
sem Claude e sem alegar proveniência de Compose nessa execução local. O cliente determinístico
espaça o início dos cenários em seis segundos para respeitar o limite global por IP; as cotas
e o runner real não foram alterados. O CI repete esse contrato na pilha Compose imutável.
O Docker VFS local esgotou disco ao copiar imagens; não se infere dimensionamento de VPS desse incidente.
O workflow mede memória e disco durante a campanha em Actions, sem contratar nem publicar servidor.
O fundador configurou `ANTHROPIC_API_KEY` nos Secrets do GitHub Actions e autorizou a primeira campanha assim que o workflow
estivesse na main; a execução e sua falha estão registradas acima. Seus valores não foram exibidos.
Não publicar cassetes como evidência real antes da execução. O replay sempre terá origem de contrato.

`consultar_ficha` já veio na main pelo PR #72. Depois da primeira medição,
`proximos_eventos` foi incorporada à branch `produto-agentes-medicao` pelo adaptador da
função existente do Calendário, sem reescrever a coleta. São oito ferramentas, com
escopo consultar, conta ativa, cota por empresa, projeção sem texto pessoal e telemetria. Não foi feita contratação, implantação pública ou registro MCP.

## Retomada no Codex: plataforma integrada

A API paga do PR #45 foi migrada e recebeu a main, com a migração de conta renumerada
para 0028, após o calendário (0027). Conta e três testes são por empresa; saldo não pula sinal Pix/contrato.
O caminho legado redireciona para a política paga; recusas contam no SlowAPI.
A análise usa projeções explícitas e marca ausência de certidão/camada como não verificado.

A integração com a main preserva calendário, aprendizado, interface, acessibilidade e domínio configurável. Mantém login por URL configurada, Presidio e
Uvicorn com formatador seguro. CORS aceita OAuth/MCP e idempotência; a CSP da
aprovação é preservada. O limite global também gera telemetria e erros RFC 9457;
a ponte interna autenticada não duplica a contagem por IP. O limite por empresa
continua ativo. O teste Chromium da API paga respeita Retry-After.

O fluxo de navegador respeita também os limites das leituras
paralelas do grupo; erro de carregamento mostra mensagem e permite tentar de novo.
A migração do Calendário permanece 0027, seguida da API 0028, salvaguardas 0029 e
plataforma 0030 e buscas salvas 0031, com uma única ponta no Alembic.

Os seis jobs de CI passaram nos dois PRs: [#45](https://github.com/bernardoemmel/Raiz/pull/45),
com [1.072 testes Python aprovados](https://github.com/bernardoemmel/Raiz/actions/runs/43296919086),
e [#69](https://github.com/bernardoemmel/Raiz/pull/69), com
[1.384 testes Python aprovados](https://github.com/bernardoemmel/Raiz/actions/runs/43296958877).
Cada suíte teve também um teste ignorado e um xfail esperado. Na integração final
passaram 170 testes focados de API/banco, 194 testes do front, TypeScript e Ruff.
O fluxo real no Chromium passou
com evidências geográficas sintéticas, aprovação humana, QR/vencimento e verificação
criptográfica do recibo. A página recebida pelo agente também foi exercitada com
rede simulada e passa a ser verificada no CI. Foram auditados 638 pacotes, sem
licença proibida; Gitleaks não encontrou segredos.

A plataforma está implementada no mesmo FastAPI: SDK oficial `mcp==2.3.0`, protocolo
2026-07-28, transporte HTTP e OAuth 2.1 via Keycloak 26.8.2. A chave de API vale só na REST.
Oito ferramentas: proximos_eventos, consultar_ficha, consultar_disponibilidade, pedir_lote, comparar_lotes,
acompanhar_contato, preparar_reserva e cancelar. Reservar começa desligado e só o
administrador da própria empresa habilita; o worker revalida antes de executar.

`consultar_ficha` foi integrada pela ponte REST existente em `/v1/fazendas/{CAR}/ficha`.
Relê exclusivamente a ficha já adquirida pela empresa na carteira da prospecção,
com sinal, contrato, OAuth/escopo, limites e auditoria. Não cobra tarifa nova nem
desbloqueia CAR implicitamente; ausência de liberação é 402. Preserva o DTO comum
com fontes, datas e `null`; a análise corporativa de R$ 1.500 continua separada.

As cinco operações de cálculo/preparo entram em fila PostgreSQL e devolvem 202 com
`pedido_id` e estado. O worker confirma resultado, efeitos, débito/estorno e outbox
na mesma transação; uma queda antes do commit permite recuperação sem duplicação.
`Idempotency-Key` protege a intenção e rejeita outro corpo. O cancelamento tem
registro idempotente e nunca cancela Pix já emitido ou contrato. O MCP limita a
espera da ponte a 3 s; uma operação que já entrou continua identificável pela mesma chave.

O agente nunca aprova ou paga. Preparação entrega link para uma pessoa da empresa;
a página exige sessão/login e clique após ver valor e prazos. A aprovação gera Pix
com QR e vencimento e recibo JWS Ed25519. O recibo não é comprovante de pagamento nem
certificação AP2. A exclusividade começa somente com confirmação do provedor;
pagamento fora das condições preserva o fato financeiro e exige revisão humana.
O suporte a Idempotency-Key do provedor Pix v1 não está confirmado e não é presumido.

Standard Webhooks: corpo estável, assinatura v1, timestamp, proteção de repetição,
outbox/retry e destinos HTTPS aprovados. Uma pessoa administra as inscrições;
segredo aparece uma vez e destino/segredo ficam cifrados. Proxy de saída precisa
bloquear redes privadas no ambiente de produção. Telemetria OpenTelemetry registra
chamadas e recusas com atributos permitidos, sem corpo, credenciais ou texto livre.
O resumo único `contrato.RESUMO` alimenta /llms.txt, MCP e topo do OpenAPI, até 8 KiB.

O gabarito tem 24 tarefas e exige 96 tentativas em sessões novas: meta pass^4 ≥ 80%,
zero chamada proibida e zero violação crítica. Os testes validam o avaliador e as
barreiras do servidor. **Não há medição de desempenho de agente real nesta entrega.**
Texto de terceiros permanece dado; projeções positivas excluem nomes, documentos,
contatos e motivos livres das respostas das ferramentas. O filtro de texto não é
apresentado como detector confiável de nomes próprios.

Salvaguardas: piso conservador Raíz 20%; art. 47 exige 50% para remoção e 70% para REDD+
de mercado, além de CLPI; art. 43 exige evidência de exclusão e impede dupla contagem.
A revisão humana é o compromisso Raíz ao atender LGPD art. 20. Falta de camada/evidência
bloqueia reserva. A migração 0029 contém essas tabelas; 0030 contém fila, eventos,
permissão, aprovação e recibos. Migração nova precisa de banco atualizado, não apenas código novo.

Implantação detalhada: `docs/agentes-ia.md`, `docs/trabalhos-agentes.md`,
`docs/eventos-agentes.md` e `docs/avaliacao-agentes.md`. Keycloak foi testado em
contêiner local; não afirmar implantação pública. Configure TLS, vínculo empresa/role,
Valkey para limites compartilhados, cofre, assinante, SMTP, provedor Pix e coletor OTLP.
Não reutilizar segredos dos testes. Não enviar mensagens reais durante validação.

O recálculo do Pará e a publicação no Release pertencem exclusivamente ao chat
"Lote e números", por orientação do fundador. Consulte a [passagem desse chat](lote-e-numeros.md)
para o estado atual. Nenhuma ação sobre execução ou Release foi feita nesta entrega.

As salvaguardas da API complementam o catálogo da rodada: os bloqueios publicados
chegam à oferta/PostGIS. Inclusão de programa REDD+ exige recertificar a cobertura
vigente. Os testes de revisão usam o app real e os gates pagos, inclusive o caminho
legado por redirecionamento. A cadeia de migrações é 0026 (prospecção) → 0027 (calendário)
→ 0028 (API) → 0029 (salvaguardas) → 0030 (plataforma) → 0031 (buscas salvas).

---

## Registro anterior (contexto histórico; itens acima prevalecem)


## O que este chat fez

Na main:
- PR #25: rodada 11 unificada (premissas e central_r11 num só arquivo) e lote ProFloresta+.
- PR #32: E3, com a faixa honesta do lote (soma × carteira, MME 102, parcelas de campo AR-TOOL03, tornado) e o plano atualizado.
- PR #41: E3 passo 4 (reserva de não permanência por fazenda, por fogo e derrubada) e E4 (rebanho por fazenda pela PPM e metano Tier 1).

Fora da main:
- Este PR: frente "Raíz para agentes de IA", **em andamento** (não terminada, ver abaixo).

## Onde parou exatamente

A frente de IA ainda não tem linha em `docs/plano-por-etapa.md`; ela entra ao lado da E7 (agentes) e da E6 (quem compra). O trabalho parou na parte A (API REST paga).

O último arquivo mexido foi `raiz/publica/api.py`, função `criar()`. Ela foi reescrita para o desenho pago (cobrança por chamada, trava de sinal e contrato, SlowAPI, erros RFC 9457), mas **nunca rodou em teste**.

Ficou pela metade, e por isso o CI deste PR deve falhar:
- `raiz/cli.py` (`pedidos_chave`) ainda chama `K.criar(engine, cliente, rotulo, limite_minuto, limite_dia)`. A assinatura nova é `K.criar(engine, cliente, rotulo)`, e a empresa precisa ter a conta aberta antes (`conta.abrir`).
- `raiz/publica/servidor_mcp.py` é o MCP antigo, com 7 ferramentas e grátis. Será trocado na parte B.
- `raiz/publica/fazenda.py` não tem `analisar()`, que a rota `/fazendas/{cod}/analise` importa.
- `testes/test_publica_banco.py` e `testes/test_servidor_mcp.py` ainda testam o desenho antigo (API grátis).
- `ruff format` pede para reformatar 2 arquivos.

Já está pronto e coerente entre si, mas sem teste:
- `raiz/regras/padroes/api_publica.yaml`: preços, 3 créditos de teste, limites e regras de raspagem.
- `migracoes/versions/0020_api_publica.py`: tabelas de conta, chave, chamada, exposição, lançamento, cobrança e alerta, mais a reserva `aguardando_confirmacao`.
- `raiz/publica/conta.py`: conta por CNPJ (guardado só em HMAC e mascarado), cobrança com 402 e recarga, estorno, liberação, vigia de raspagem e licença de dados.
- `raiz/publica/chaves.py`, `privacidade.py` e `problemas.py`.
- Em `raiz/pedidos/servico.py`: a reserva passa a esperar a confirmação de uma pessoa, e a confirmação de pagamento também cobre as cobranças da API.

## O que falta, em ordem

1. **IA-A**: deixar o CI verde.
   1. Corrigir `pedidos_chave` em `raiz/cli.py` (tirar os limites).
   2. Criar `analisar()` em `raiz/publica/fazenda.py`, partindo de `explicar()`. Ela entrega a certidão lida, a sobreposição, se a fazenda "já está comprometida" e a simulação P10/P50/P90, tudo sem dado pessoal.
   3. Em `raiz/api.py`, montar só `/v1` e tirar `/mcp` até a parte B.
   4. Reescrever `testes/test_publica_banco.py`. Primeiro os dois testes de ponta a ponta pedidos pelo fundador:
      - uma chave nova gasta as 3 consultas de teste e recebe 402 na quarta;
      - uma chave que raspa em volume é bloqueada.

      Depois testar também: 429 com Retry-After, 403 sem sinal ou sem contrato, estorno quando a chamada falha e nenhum dado pessoal nas respostas.
   5. Escrever `docs/termos-api.md` e atualizar `docs/agentes-ia.md` com os 4 produtos separados.
   6. Registrar SlowAPI e limits (ambos MIT) em `NOTICE.md`.
   7. Criar o comando `raiz api licenca --cliente <id> --aprovar`, que só o fundador usa.
2. **IA-B**: MCP por intenção, com o SDK oficial `mcp` 2.x (`MCPServer`), sem sessão.
   - Seis ferramentas: consultar_disponibilidade, pedir_lote, comparar_lotes, acompanhar_contato, preparar_reserva e cancelar.
   - Toda resposta em menos de 5 s. O que demora devolve pedido_id e o estado (submitted, working, input-required, completed, failed, canceled).
   - Idempotency-Key em pedir_lote e preparar_reserva, paginação por token e webhooks no padrão Standard Webhooks.
   - preparar_reserva devolve o link para uma pessoa aprovar e o Pix com vencimento e dois prazos (exclusividade e preço). A aprovação fica guardada como recibo assinado no formato de mandato do AP2.
   - Registro de cada chamada no padrão OpenTelemetry GenAI.
   - Presidio antes de gravar o log. Hoje só existe o filtro com expressões regulares de `privacidade.py`.
   - Um resumo único de até 8 KB, usado em /llms.txt, nas instruções do MCP e no topo do OpenAPI.
   - `server.json` para o registro oficial do MCP.
3. **IA-C**: OAuth 2.1 no MCP com Keycloak 26 em contêiner (`infra/`).
   - Escopos consultar, pedir e reservar. O escopo reservar começa desligado e só o administrador da empresa liga.
   - A chave de API vale só na REST.
4. **IA-D**: medição no CI.
   - Inspetor oficial do MCP (CLI) e vacuum no OpenAPI.
   - Gabarito do pedido de 1 milhão com 20 a 30 tarefas. Meta: pass^4 de pelo menos 80% e nenhuma chamada proibida.
   - Respostas gravadas com vcrpy e uma suíte de injeção no estilo AgentDojo.
5. **Correções do produto** que a pesquisa pediu.
   - Reserva contra reversão de no mínimo 20% no `central_r11` (ICVCM 9.3/9.4). Fica em `raiz/regras/padroes/restauracao.yaml`, chave `nao_permanencia.piso`, que hoje é 0.10.
   - Camada de REDD+ jurisdicional do estado (Lei 15.042, art. 43 §6º).
   - Em território tradicional, marcar a consulta livre, prévia e informada e a regra dos 50% dos créditos (art. 47).
   - LGPD art. 20: critério explicado e pedido de revisão humana quando uma decisão automática tira a fazenda do lote ou dá nota de risco.
6. **Resultado do lote do PA inteiro**, a registrar em `docs/restauracao-rodada11.md`. O recálculo rodava **só no contêiner deste chat** e se perde com ele:
   - parou em 24 de 144 municípios, a cerca de 330 s cada;
   - refazer pelo Actions ou numa máquina própria;
   - depois rodar `raiz lote montar PA --saida dados/armazem_local/saida`.
7. **Resto da E4** (solo, categorias Tier 2, confinamento) e a **E6** (frigoríficos, tempo de caminhão, Huff).
8. Pôr a frente de IA em `docs/plano-por-etapa.md`.

## PRs abertos e branches sem merge

- Este PR, da branch `claude/amazing-ramanujan-rzzknw`: frente de IA em andamento.
- O PR #43 (`claude/quirky-cannon-8ogwvw`) é de outro chat.

## Trabalhos rodando no Actions

- Estão rodando o "Processar estados" (plano automático e próximo da fila) e vários CI. **Não cancelar.**
- Para conferir: https://github.com/bernardoemmel/Raiz/actions

## Decisões e cuidados que não estão no código

- **Pesquisa inacessível.** O arquivo `/mnt/project-files/raiz-dados/ia-friendly/analise_ia_friendly_v1.txt` e a planilha (aba Lacunas) **não estavam acessíveis** neste contêiner. Tudo foi feito a partir da mensagem do fundador. Vale subir os dois para o repositório.
- **Decisões do fundador sobre cobrança:**
  - Nada é grátis na API nem no MCP. Cada CNPJ ganha 3 testes.
  - A análise de uma fazenda custa R$ 1.500. Os demais preços ficam em `api_publica.yaml` e são configuráveis.
  - Pagar não pula a trava de sinal e contrato.
  - Números por município ficam só no site público.
  - O agente nunca paga: recebe só o link para uma pessoa pagar, nunca o código Pix.
- **Ferramentas a evitar:** ZITADEL (AGPL), lakeFS (BSL), SuperTokens ee/, LlamaFirewall/PromptGuard e MCPJam evals. MCP Apps e A2A ficam para depois.
- **SDK do MCP 2.x:**
  - a ferramenta precisa devolver `dict[str, Any]`, senão a saída estruturada vem vazia;
  - erros como subclasse de `ToolError`;
  - `session_manager.run()` roda uma vez só por instância; nos testes, usar fixture de módulo;
  - o erro 421 de host se resolve com `RAIZ_MCP_HOSTS`.
- **Trabalho em segundo plano** nunca deve ler as premissas da árvore de trabalho; rodar de um `git worktree` congelado. Uma edição no YAML já derrubou 120 municípios.
- **Dependências:** sempre `uv sync --all-extras`. Sem isso, o rasterio some.
- **Git:** o force push foi negado; usar só avanço rápido.
- **Licença:** Heinrich 2021 é NC; serve só para comparar.

## Comandos para os testes desta parte

```bash
pg_ctlcluster 16 main start
```

```bash
set -a; . ./.env; set +a; uv sync --all-extras
```

```bash
uv run pytest testes/test_publica_banco.py testes/test_servidor_mcp.py -q
```

```bash
uv run ruff check raiz && uv run ruff format --check raiz
```

Se o banco de teste travar na migração 0020, recriar o `raiz_teste` (drop, create e `create extension postgis`).
