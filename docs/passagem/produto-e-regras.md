# Passagem do chat "Produto e regras" (12/11/2026)

## Preparação do replay diário

A branch `produto-agentes-replay` implementa a regressão das 96 sessões contra MCP,
OAuth, banco e worker reais, sem chave Anthropic. A referência exige campanha completa,
meta atingida, zero chamadas proibidas e hashes íntegros. O agente é reproduzido pelo
VCR; notas semânticas ficam congeladas e barreiras determinísticas são recalculadas.
Isso não mede novamente o pass^4 do modelo. As cassetes integrais do agente e do juiz
permanecem auditáveis, incluindo correções de citações.

O diagnóstico com cinco fluxos gravados revelou que VCR reaplicava o filtro de resposta
ao carregar a cassette e zerava sua latência. O carregamento agora preserva bytes e
tempo gravados. Os cinco fluxos repetiram integralmente suas chamadas contra serviços
reais, sem trocar estados nem respostas do MCP; são diagnóstico, não uma campanha
aprovada. Passaram 46 testes do runner, replay e julgamento. A referência de 96 sessões
ainda depende da campanha completa; o passo obrigatório do CI não foi publicado sem ela.

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
usa `23ec54c` e o juiz v3; aguarda-se o relatório completo, sem antecipar pass^4.
A integração posterior com a main `c65d7bb` preserva a entrada de certidões, a
vigilância dos lotes e as novas fontes do Calendário. O conflito na montagem da API
foi resolvido mantendo os dois registros independentes de rotas.



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
