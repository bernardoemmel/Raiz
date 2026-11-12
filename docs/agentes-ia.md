# A Raíz para agentes de IA

A API paga `/v1` atende ao pedido de 1 milhão de créditos no Pará com as mesmas
premissas do produto. Não há plano grátis: são três créditos de teste por empresa,
seguidos de cobrança por uso. Veja [termos-api.md](termos-api.md).

## Quatro produtos

1. Análise de fazenda: certidão lida quando disponível, situação da terra,
   sobreposições verificadas e comprometimentos conhecidos. Ausência de leitura
   ou camada é informada como não verificada.
2. Valor de restauração: métodos, hectares, créditos P10/P50/P90, custos, retorno
   e descontos de risco.
3. Interesse do dono: progresso até o contrato, sem identidade ou contato.
4. Previsões confrontadas com resultados reais e versão do modelo.

Uma pessoa abre a conta com CNPJ e aceite dos termos em `POST /v1/conta`, usando
sua sessão. O CNPJ fica em HMAC e mascarado. Só uma sessão humana cria chaves em
`POST /v1/chaves`; a chave aparece uma vez, e só seu hash é armazenado. A REST
aceita `X-Chave-API` ou `Authorization: Bearer raiz_...`, nunca chave na URL.

| Operação | Rota |
|---|---|
| Disponibilidade | `POST /v1/disponibilidade` |
| Montar pedido | `POST /v1/pedidos` |
| Comparar opções | `GET /v1/pedidos/{id}/opcoes` |
| Analisar fazenda | `GET /v1/fazendas/{cod}/analise` |
| Buscar interesse | `POST /v1/pedidos/{id}/solicitar-interesse` |
| Acompanhar | `GET /v1/pedidos/{id}/andamento` |
| Preparar reserva | `POST /v1/pedidos/{id}/reservar` |
| Previsões | `GET /v1/previsoes/precisao` |

Detalhes e montagem exigem sinal Pix e contrato, mesmo com saldo. Limites SlowAPI
são por empresa e compartilhados entre chaves; 429 inclui Retry-After. Saldo
insuficiente gera 402. Erros usam RFC 9457. O agente recebe um link para uma
pessoa aprovar a reserva; não paga. Nunca saem dados pessoais do dono.

OpenAPI: `/v1/openapi.json`; documentação: `/v1/docs`. Conta, extrato e histórico
ficam em `/v1/conta`, `/v1/conta/extrato` e `/v1/chamadas`.

## MCP e execução dos pedidos

`/mcp/` está no mesmo aplicativo da REST, com o SDK oficial Python **mcp 2.3.0**,
transporte HTTP sem sessão e especificação **2026-07-28**. Exige OAuth 2.1 do
Keycloak; chave da API, chave na URL e stdio não autenticam o MCP. JWTs têm
assinatura RS256, emissor, audiência, validade e vínculo ativo com a empresa
verificados. A identidade passa à REST por estado interno ASGI, sem aceitar
cabeçalhos externos que pretendam escolher uma empresa.

| Ferramenta | Escopo | Comportamento |
|---|---|---|
| `consultar_disponibilidade` | `consultar` | Enfileira totais P10/P50/P90; consome teste ou saldo |
| `pedir_lote` | `pedir` | Enfileira montagem; exige sinal, contrato e `idempotency_key` |
| `comparar_lotes` | `consultar` | Enfileira comparação agregada das opções; exige liberação |
| `acompanhar_contato` | `consultar` | Consulta uma operação ou enfileira andamento agregado do pedido |
| `preparar_reserva` | `reservar` | Enfileira preparação da aprovação humana; exige `idempotency_key` |
| `cancelar` | `pedir` | Cancela trabalho pendente ou pedido sem reserva paga; exige `idempotency_key` |

O trabalho computacional fica no worker. A chamada HTTP devolve `pedido_id` e
`estado`; o objetivo é responder em menos de 5 segundos, verificado nos testes de
integração locais, sem afirmar um SLA de produção. Os estados são `submitted`,
`working`, `input-required`, `completed`, `failed` e `canceled`. Na REST, consulte
`GET /v1/operacoes/{pedido_id}`. `negocio_pedido_id`, quando preenchido, identifica
o pedido comercial resultante; não confunda esse ID com o da operação.

As cinco operações computacionais também aceitam `POST /v1/agentes/{ferramenta}`.
`POST /v1/pedidos` e `POST /v1/pedidos/{id}/reservar` usam a mesma fila para chaves
de API. O cabeçalho `Idempotency-Key` das mutações corresponde ao argumento MCP
`idempotency_key`. Mesma empresa, ferramenta, chave e corpo retornam a operação
original, inclusive entre REST e MCP; reaproveitar a chave com outro corpo dá 409.
Os limites SlowAPI também são compartilhados entre esses dois canais.
Se o adaptador devolver 504 ao atingir o prazo de três segundos, a requisição
interna já iniciada pode concluir. Repita com a mesma chave idempotente para
consultar a mesma intenção; o adaptador não dispara outra tentativa por conta própria.

`reservar` começa desligado na conta. A pessoa com a role de cliente
`raiz-api/admin_empresa` pode chamar `PUT /v1/conta/permissoes/reservar` com seu
Bearer OAuth e `{"habilitado":true}` ou `false`. A mudança vale somente para a
empresa vinculada ao token e fica registrada. Role global do realm, chave REST
ou simples pedido do escopo não habilitam reserva. Desligar a permissão impede
novas chamadas mesmo com JWT ainda válido.

## Aprovação, dados e eventos

`preparar_reserva` não paga nem representa aprovação de uma pessoa. Ao terminar,
o acompanhamento devolve `input-required` e o link para a página de aprovação.
Uma pessoa autenticada da própria empresa confere o resumo e aprova. Só então
são gerados o Pix, o QR, o vencimento e o recibo Ed25519 em JWS compacto. O recibo
afirma **aprovação**, nunca pagamento; a chave pública está em
`/v1/recibos/jwks.json`. A exclusividade começa após a confirmação do provedor.
O formato é próprio, sem declaração de certificação AP2.

Snapshots da fila usam projeções de campos permitidos e resultados agregados;
links de aprovação, Pix e recibos são reconstituídos da cobrança atual após
autorizar o acesso. Nome, CPF e contato do dono não integram as respostas. Texto
de documento, site ou mensagem de terceiro permanece dado: não altera escopo,
cobrança, instruções ou autorização. Identificadores, Pix e assinaturas válidos
precisam ser preservados sem máscaras que corrompam o protocolo.

Eventos são persistidos na mesma transação da mudança de estado e entregues pelo
worker com `webhook-id`, `webhook-timestamp` e `webhook-signature`, conforme
Standard Webhooks. O receptor deve verificar assinatura e timestamp e deduplicar
`webhook-id`. Uma pessoa administra as inscrições com `POST /v1/webhooks` (Idempotency-Key),
`GET /v1/webhooks` e `DELETE /v1/webhooks/{id}`. O segredo aparece uma vez;
não há ferramenta MCP de cadastro. Veja [eventos-agentes.md](eventos-agentes.md).
Somente hosts HTTPS exatos previamente autorizados são aceitos. O operador deve
restringir também o tráfego de saída quando usar proxy.

Cada requisição HTTP passa pelo middleware OpenTelemetry, inclusive recusas.
Spans usam atributos operacionais permitidos; não gravam corpos, credenciais,
nomes nem contato pessoal. O middleware OTel padrão do SDK é substituído para
excluir nomes de ferramenta livres, IDs JSON-RPC e texto de exceção. Propaga-se
somente `traceparent`, nunca `tracestate` ou `baggage` de terceiros. As projeções
positivas do domínio excluem nomes; o filtro textual não é detector universal de
pessoas. Sem exportador configurado, não há armazenamento
externo dos traces. O resumo único em `raiz/publica/contrato.py`, de até **8 KiB
UTF-8**, é o conteúdo de `/llms.txt`, as instruções do MCP e o início da descrição
do OpenAPI.

## Instalação e configuração

São processos separados: API, worker, Keycloak e seu PostgreSQL, banco do produto
com PostGIS, Valkey para limites compartilhados entre processos e um coletor OTLP
para persistir telemetria. O [compose OAuth](../infra/docker-compose.keycloak.yml)
inclui somente Keycloak e o banco OAuth. Não é uma implantação completa do produto.

Instale com `uv sync --all-extras`, aplique `uv run raiz banco migrar` no banco
selecionado e inicie `uv run raiz api --host 127.0.0.1 --porta 8000`. Em outro
processo, com o mesmo ambiente e banco, rode `uv run raiz api worker`. A opção
`--uma` executa um ciclo. Sem worker ativo, operações permanecem na fila; ele não
é iniciado automaticamente pela API.

| Variável | Uso |
|---|---|
| `RAIZ_BANCO_URL` | PostgreSQL/PostGIS do produto, migrado até a revisão 0029 |
| `RAIZ_CHAVE_PESSOAL` | Chave do cofre, igual na API e no worker; gere com `uv run raiz pessoal gerar-chave` e guarde fora do git |
| `RAIZ_API_PUBLICA_URL` | Origem HTTPS pública, sem `/v1`; usada nos links de aprovação |
| `RAIZ_OAUTH_ISSUER` | URL externa do Keycloak seguida de `/realms/raiz` |
| `RAIZ_MCP_RESOURCE` | URL pública exata do recurso, terminando em `/mcp`; também é a audiência do JWT |
| `RAIZ_MCP_HOSTS` | Hosts aceitos no MCP, separados por vírgula; quando ausente, usa o host do recurso |
| `RAIZ_OAUTH_JWKS_URL` | Opcional; por padrão, `<issuer>/protocol/openid-connect/certs`; exige a mesma origem do emissor |
| `RAIZ_OAUTH_ROLES_CLIENT` | Opcional; cliente que contém a role administrativa, padrão `raiz-api` |
| `RAIZ_API_LIMIT_STORAGE_URI` | Valkey do limitador, por exemplo `redis://valkey:6379/0`; o protocolo usa o cliente Python `redis` (MIT), não o servidor Redis; `memory://` padrão limita apenas um processo |
| `RAIZ_OTEL_ENDPOINT` | URL OTLP/HTTP completa, por exemplo `http://coletor:4318/v1/traces`, sem credenciais ou query |
| `RAIZ_RECIBO_CHAVE` | Chave privada Ed25519: 32 bytes em base64url, fornecida pelo cofre operacional |
| `RAIZ_WEBHOOK_HOSTS` | Hosts HTTPS de destinatários autorizados, separados por vírgula |
| `RAIZ_ABACATEPAY_CHAVE`, `RAIZ_ABACATEPAY_WEBHOOK_SEGREDO` | Integração de pagamento; sem chave, o Pix é de teste e não paga nada |
| `RAIZ_SMTP_HOST`, `RAIZ_SMTP_FROM` | Servidor SMTP e remetente para enviar o link de login humano |
| `RAIZ_SMTP_PORT`, `RAIZ_SMTP_TLS` | Porta e proteção SMTP; padrão 465 com `ssl`; também aceita `starttls` |
| `RAIZ_SMTP_USER`, `RAIZ_SMTP_PASSWORD` | Credenciais SMTP quando exigidas pelo serviço |
| `RAIZ_FRONT_URL` | URL pública do painel para o login humano |

As variáveis OAuth, limitador e telemetria devem estar no ambiente dos processos,
não apenas escritas em um arquivo que o launcher não exporta. O MCP permanece
fechado com 503 enquanto emissor e recurso não estiverem configurados.

Para o compose, configure ainda `RAIZ_KEYCLOAK_URL`,
`RAIZ_KEYCLOAK_BANCO_SENHA`, `RAIZ_KEYCLOAK_ADMIN`,
`RAIZ_KEYCLOAK_ADMIN_SENHA` e `RAIZ_OAUTH_REDIRECT_URI`. Este último deve ser o
callback HTTPS exato do cliente, sem curinga. Suba com:

```bash
docker compose --env-file .env -f infra/docker-compose.keycloak.yml up -d
```

O proxy termina TLS e encaminha para `127.0.0.1:8180`, substituindo os cabeçalhos
de encaminhamento. Siga o [procedimento do realm](../infra/keycloak/README.md)
para vincular usuários às empresas e atribuir administradores. O realm importado
não cria usuários, vínculos ou senhas. `empresa_id` só é editável pelo operador.
O import acontece na criação do realm; não atualiza automaticamente um realm já
existente.

O Keycloak **26.8.2** foi iniciado e o realm importado em contêiner de teste nesta
entrega: discovery respondeu, PKCE S256 foi exigido e password grant foi recusado.
Isso não declara implantação pública, teste com contas reais nem prontidão do
provedor de pagamentos. Antes de operar pagamentos reais, confira o contrato
vigente do provedor e a configuração de seus callbacks. O envio de login humano
por e-mail é configurado por `raiz.publica.email_login` quando `RAIZ_SMTP_HOST`
existe; exige SSL ou STARTTLS. Sem serviço de envio configurado, a entrada pela
página de aprovação responde 503. Valkey usa BSD-3-Clause; não instalar versões
do servidor Redis sob SSPL, RSAL ou AGPL.

## Evidência e meta dos agentes

Os testes HTTP usam o aplicativo completo, JWTs assinados e PostgreSQL/PostGIS
descartável. Cobrem as seis ferramentas, identidade e escopos, liberação comercial,
fila, idempotência entre REST/MCP, limite por empresa, cancelamento, retorno de
aprovação e preservação/verificação do recibo. Erros de autenticação são RFC 9457.
Não use o banco do produto: a fixture de testes desmonta e recria o banco indicado
por `RAIZ_BANCO_URL_TESTE`.

O [gabarito](avaliacao-agentes.md) tem **24 tarefas** do pedido de 1 milhão e exige
quatro sessões independentes por tarefa: **96 execuções**, meta **pass^4 ≥ 80%** e
**zero chamada proibida**, incluindo tentativas bloqueadas. O avaliador e seus
testes estão entregues; a campanha de um agente real **ainda não foi medida**.
Testes de contrato sintéticos não aprovam essa meta nem substituem a auditoria dos
traces.
