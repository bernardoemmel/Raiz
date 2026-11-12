# Passagem do chat "Produto e regras" (12/11/2026)

## Retomada no Codex: plataforma integrada

A API paga do PR #45 foi migrada e recebeu a main, com a migração de conta renumerada
para 0027. Conta e três testes são por empresa; saldo não pula sinal Pix/contrato.
O caminho legado redireciona para a política paga; recusas contam no SlowAPI.
A análise usa projeções explícitas e marca ausência de certidão/camada como não verificado.

A integração com a main 78e13f7 mantém login por URL configurada, Presidio e
Uvicorn com formatador seguro. CORS aceita OAuth/MCP e idempotência; a CSP da
aprovação é preservada. O limite global também gera telemetria e erros RFC 9457;
a ponte interna autenticada não duplica a contagem por IP. O limite por empresa
continua ativo. O teste Chromium da API paga respeita Retry-After.

A plataforma está implementada no mesmo FastAPI: SDK oficial `mcp==2.3.0`, protocolo
2026-07-28, transporte HTTP e OAuth 2.1 via Keycloak 26.8.2. A chave de API vale só na REST.
Seis ferramentas: consultar_disponibilidade, pedir_lote, comparar_lotes,
acompanhar_contato, preparar_reserva e cancelar. Reservar começa desligado e só o
administrador da própria empresa habilita; o worker revalida antes de executar.

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
bloqueia reserva. A migração 0028 contém essas tabelas; 0029 contém fila, eventos,
permissão, aprovação e recibos. Migração nova precisa de banco atualizado, não apenas código novo.

Implantação detalhada: `docs/agentes-ia.md`, `docs/trabalhos-agentes.md`,
`docs/eventos-agentes.md` e `docs/avaliacao-agentes.md`. Keycloak foi testado em
contêiner local; não afirmar implantação pública. Configure TLS, vínculo empresa/role,
Valkey para limites compartilhados, cofre, assinante, SMTP, provedor Pix e coletor OTLP.
Não reutilizar segredos dos testes. Não enviar mensagens reais durante validação.

O recálculo usa o workflow `lote-para.yml` da main (PR #49), sem pipeline duplicado.
A execução 43285608189, commit 3199052, calculou dez de quinze fatias; foi cancelada
externamente em 12/11 às 19:09 UTC e o workflow foi desativado manualmente. Nenhuma
saída parcial foi publicada. Por orientação posterior do fundador, a retomada das
cinco fatias e a publicação pertencem exclusivamente ao chat "Lote e números".
Este chat segue apenas com a API paga e o MCP; não altera o recálculo nem o Release.

As salvaguardas da API complementam o catálogo da rodada: os bloqueios publicados
chegam à oferta/PostGIS. Inclusão de programa REDD+ exige recertificar a cobertura
vigente. Os testes de revisão usam o app real e os gates pagos, inclusive o caminho
legado por redirecionamento. A cadeia de migrações é 0026 (prospecção) → 0027 (API)
→ 0028 (salvaguardas) → 0029 (plataforma).

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
