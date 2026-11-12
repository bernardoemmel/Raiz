# Passagem do chat "Produto e regras" (12/11/2026)

## Retomada no Codex

Integração atual: main `a4c1066`, incluindo aprendizado, avaliação Qwen,
cena do lote e Calendário. A API paga é a migração **0028**, depois de
`0027_calendario`; a sequência continua única. Mantidos os controles pagos e
a revalidação dos desenhos: só aparecem contornos desbloqueados pela empresa,
e nunca os reservados por outra empresa. O E2E combina a conta paga com a
nova cena do lote, mantendo a fase de interesse/reserva isolada no teste.
O recálculo do Pará pertence ao chat Lote e números; não será executado aqui.
Validação da integração: 89 testes de API, banco, autorização dos contornos e
Calendário passaram em banco vazio; 167 testes do front passaram. Ruff,
formatação, privacidade e licenças de 652 pacotes passaram.

Integração mais recente: main `78e13f7` (qualidade e segurança). Mantém o login
com URL pública configurada, aliases 307 para a política paga, sanitização
Presidio e `uvicorn` sem access log e sem substituir o formatador seguro.
O teste de ponta a ponta passa a abrir conta, verificar recusa sem liberação,
aceitar contrato e confirmar sinal/recarga exclusivamente por Pix local de teste.
Não há liberação direta no banco nem retorno ao desenho grátis. Os 58 testes
específicos de API/login/logs e os 141 testes do front passaram após a integração.
O teste Chromium de conta paga até reserva passou, respeitando `Retry-After`
sem desligar limites; 636 pacotes Python/npm/Rust foram conferidos sem problema.
O CI reforçado da main executa a suíte completa, E2E, Gitleaks e licenças.

Nova integração com a main `3199052`: preserva a ficha da terra paga e a busca
nacional, a rodada do Pará e as passagens consolidadas dos PRs 48, 49 e 52.
A migração da API é agora `0027`, depois de `0026_prospeccao_acesso`. A sequência
é única e mantém os dois produtos. O teste de complementos adota a versão da
main: exige os arquivos obrigatórios e tolera colunas/arquivos novos do motor.
Validação desta integração: 67 testes de API paga, prospecção, privacidade e
reserva passaram em banco vazio, com `0027` como única ponta das migrações;
130 testes do front passaram. Ruff, formatação, privacidade e licenças aprovados.

O PR #45 incorporou também a main `3b21e78` (mapa nacional e busca estática).
O único conflito era a formatação da lista de complementos no teste do front;
a comparação exata, incluindo regularização, foi preservada. As funcionalidades
da API paga permaneceram intactas. Ruff, privacidade, licenças e os 80 testes
do front e a navegação em Chromium passaram após essa integração. A suíte local
completa (637 aprovados, 2 pulados e 1 xfail) encontrou uma falha intermitente:
o filtro de privacidade reconhecia números dentro de UUIDs como telefone.
UUIDs completos agora são preservados; o teste de pedido pago usa um UUID
fixo que reproduz a falha e verifica o acompanhamento e o isolamento entre empresas.
Texto com contatos ao redor continua filtrado. O CI completo volta a validar o merge.

O PR #45 foi atualizado com a main. A migração da API passou de 0020 para 0027,
porque 0020 já pertencia aos alertas e 0026 ao acesso pago da ficha da terra. Cobrança, estorno idempotente e
limites compartilhados por empresa recebem testes de integração em PostGIS.
CLI e análise da fazenda foram migrados. O adaptador MCP grátis foi retirado;
nenhuma chave em URL ou rota antiga permanece como atalho.

A API mantém três créditos de teste por empresa, sinal Pix e contrato para
montagem/detalhes, anti-raspagem e ausência de dados pessoais. Os termos estão em
`docs/termos-api.md`. A análise informa quando faltam certidão/camada; não inventa
conferência. A licença administrativa usa `raiz api licenca --cliente ID --aprovar`.

Próxima entrega: SDK MCP 2.3.0/protocolo 2026-07-28 no mesmo app; Keycloak OAuth
2.1; seis ferramentas; fila persistida e idempotência; Standard Webhooks;
OpenTelemetry e resumo único; aprovação humana com Pix e recibo assinado;
gabarito com pass^4. Reservar começa desabilitado por empresa.

Correções legais verificadas: piso 20% como política conservadora Raíz; art.47
exige mínimo 50% para remoção e 70% para REDD+ de mercado, além de CLPI; art.43
requer evidência de exclusão e impede dupla contagem; revisão humana é compromisso
Raíz ao atender LGPD art.20. Não confundir falta de camada com ausência de risco.

O Pará tem 144 municípios no pacote publicado. O recálculo será apenas no Actions,
com fonte e premissas congeladas, validação dos municípios e publicação no Release.
Não cancelar outros workflows em execução. Não calcular o lote no contêiner.

Validação local da entrega IA-A: 629 testes passaram, 4 pulados, 1 xfail;
27 testes específicos passaram após os ajustes finais e 9 testes do caminho
legado passaram. Ruff, formatação, varredura de documentos e licenças aprovados.
Rotas legadas redirecionam à API paga; recusas também contam no limitador.
PR: https://github.com/bernardoemmel/Raiz/pull/45. Merge condicionado ao CI verde.
Registrar os resultados do lote/Release na próxima entrega.

O CI do PR #45 detectou que a lista esperada no teste do front não incluía
`regularizacao_1504950.csv`, amostra incorporada pela main. A expectativa foi
atualizada mantendo a comparação exata dos complementos; `npm ci` e `npm test`
em `front/globo` passaram (70 testes aprovados, 13 pulados, 7 arquivos).

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
