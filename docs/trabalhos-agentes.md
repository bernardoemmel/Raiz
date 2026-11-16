# Operações duráveis dos agentes

`submeter(engine, cliente_id, ferramenta, corpo, chave, lancamento_id=None)` valida o corpo e o `Idempotency-Key`,
confere a conta e a liberação aplicável, procura a repetição e debita uma única vez na mesma transação. O retorno contém `pedido_id`
(identificador da operação), `estado` e, depois da conclusão, `negocio_pedido_id` (identificador do pedido do lote).
O recibo também identifica a `ferramenta`. O estado e o resultado são lidos por
`obter(engine, cliente_id, pedido_id)`, que revalida a conta e a liberação. Não há execução em callback HTTP.
Para lote concluído, o recibo devolve apenas o identificador do pedido. O snapshot completo fica como evidência
interna; `comparar_lotes` aplica novamente a exclusividade e a liberação antes de mostrar qualquer fazenda.

A fila aceita cinco operações:

- `consultar_disponibilidade` e `pedir_lote`: corpo `CamposPedido`.
- `comparar_lotes` e `acompanhar_contato`: somente `pedido_id` do lote.
- `preparar_reserva`: `pedido_id` do lote e `base_url` configurada pelo servidor.

A consulta agregada exige conta válida, mas dispensa sinal e contrato. As demais operações exigem a liberação
comercial, novamente conferida no worker. Antes de preparar uma reserva, o worker também revalida
`reservar_habilitado`: revogação administrativa anterior à execução impede a preparação. A trava compartilhada da
conta mantém essa decisão coerente até o commit. Cada submissão debita o preço ou crédito de teste uma vez; falhas estornam.
Leituras recebem uma chave de idempotência por invocação quando o cliente não fornece uma. O MCP submete o trabalho
imediatamente e consulta o recibo depois, sem bloquear o transporte esperando agregações ou solver.

Comparação e andamento persistem somente contagens, métricas numéricas e categorias conhecidas. Não há códigos de
fazenda, itens, motivos livres ou textos externos no snapshot. A resposta identifica que se trata do resumo do
instante do cálculo, evitando apresentar contagens antigas como disponibilidade atual. Consultas também guardam
somente agregados. Obter o resultado continua condicionado à autorização da empresa.

O agente nunca aprova nem paga. A preparação da reserva permanece local ao banco:
`servico.reservar(..., por_agente="operacao:<id>")` não pode enviar mensagem nem criar Pix antes da pessoa.
Na fila persistem apenas o ID do pedido e se aguarda confirmação. Link de aprovação, token, Pix e recibo assinado
não são guardados no JSON da operação. A API reconstrói a cobrança atual pelo serviço de pedidos após autorizar a
leitura; isso permite renovar o acesso sem guardar um segredo reutilizável em texto claro.

O worker `executar_proximo(engine)` reivindica com `FOR UPDATE SKIP LOCKED`, publica `working` e executa mantendo a
linha travada. Serviços recebem uma conexão vinculada: seus blocos `begin()` são savepoints da transação do worker.
Resultado e efeitos de negócio confirmam juntos. O teste encerra abruptamente um processo após inserir o pedido,
sem sair dos contextos Python: o banco reverte o efeito e o worker seguinte recupera a mesma operação. Após 15 minutos, um
worker recupera a operação. Um worker ainda vivo mantém a trava, mesmo que o prazo expire. Não se repete pedido
confirmado: a conclusão já está gravada na mesma transação.

O cancelamento exige o escopo `pedir` e uma `Idempotency-Key` de 8 a 200 caracteres ASCII visíveis.
`cancelar_idempotente` guarda somente o hash da chave, a empresa, o ID solicitado e a resposta. A mesma chave para
outro ID dá 409; repetições devolvem o recibo anterior. Chaves de empresas diferentes são independentes.

Para uma operação de fila, `cancelar` cancela somente o estado `submitted` e estorna na mesma transação.
Se o worker já começou, a rota devolve `input-required`, sem prometer desfazer trabalho em execução.
Para um pedido de lote, o cancelamento pode encerrar uma pré-reserva ainda sem cobrança e apaga seu link.
Qualquer Pix já emitido, reserva ativa ou contrato devolve `input-required`: uma pessoa precisa decidir a questão
financeira. Ter `pedir` permite interromper essa pré-reserva; não habilita reservar, gerar cobrança ou pagar.
Estado, estorno, evento e recibo idempotente confirmam juntos, sem duplicar efeitos em chamadas concorrentes.

Falha de negócio estorna o lançamento. `ErroSalvaguarda` devolve `input-required`, com instrução controlada para
revisão humana e estorno; não vira aprovação nem pagamento. Retentativa com a mesma chave devolve o mesmo estado, inclusive falha e
cancelamento; uma nova tentativa precisa de outra chave. Mesmo corpo com outra chave é outra operação cobrável.

Não criar cobrança Pix externa na submissão: saldo insuficiente responde 402 e indica `/v1/conta/recarga`, onde uma
pessoa pode gerar o pagamento. Travas de banco na submissão têm limite de 500 ms e comandos, 3 s; indisponibilidade
responde erro recuperável. O cliente HTTP/ASGI deve ainda impor o orçamento total de 5 s.

## Migração necessária

```sql
CREATE TABLE negocio.trabalho_api (
    id uuid PRIMARY KEY,
    cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
    ferramenta text NOT NULL CHECK (ferramenta IN (
        'consultar_disponibilidade', 'comparar_lotes', 'acompanhar_contato', 'pedir_lote', 'preparar_reserva')),
    chave_hash char(64) NOT NULL,
    corpo_hash char(64) NOT NULL,
    corpo jsonb NOT NULL,
    estado text NOT NULL CHECK (estado IN ('submitted', 'working', 'input-required', 'completed', 'failed', 'canceled')),
    lancamento_id bigint UNIQUE REFERENCES negocio.lancamento_api(id),
    negocio_pedido_id uuid,
    resultado jsonb,
    erro jsonb,
    executor_token uuid,
    lease_ate timestamptz,
    tentativas integer NOT NULL DEFAULT 0 CHECK (tentativas >= 0),
    criado_em timestamptz NOT NULL DEFAULT now(),
    atualizado_em timestamptz NOT NULL DEFAULT now(),
    iniciado_em timestamptz,
    concluido_em timestamptz,
    UNIQUE (cliente_id, ferramenta, chave_hash)
);
CREATE INDEX trabalho_api_fila ON negocio.trabalho_api (criado_em)
    WHERE estado IN ('submitted', 'working');
CREATE INDEX trabalho_api_cliente ON negocio.trabalho_api (cliente_id, criado_em DESC);
CREATE TABLE negocio.cancelamento_api (
    cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
    chave_hash char(64) NOT NULL,
    pedido_id uuid NOT NULL,
    resposta jsonb NOT NULL,
    criada_em timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (cliente_id, chave_hash)
);
```

A tabela não guarda a chave de idempotência em texto. O corpo vem do esquema do pedido; os dados da resposta passam
pelo filtro de privacidade. Não enviar corpo, chave, token de aprovação ou texto de terceiros para logs.

## Eventos atômicos

Cada mudança insere `pedido.atualizado` na outbox na mesma transação do estado, débito, estorno ou resultado.
O `pedido_id` do evento identifica a operação da fila; o recibo fornece o pedido de negócio quando disponível.
Os estados públicos dos eventos são: `submitted` → `recebido`, `working` → `processando`, `completed` → `concluido`,
`failed` → `falhou`, `input-required` → `aguardando` e `canceled` → `cancelado`.
Repetir uma submissão ou cancelamento já aplicado não repete o evento. Se a outbox falhar, a mudança é revertida.
A migração precisa incluir também `webhook_inscricao` e `webhook_entrega`, descritas em `docs/eventos-agentes.md`.

## Confirmação financeira e exclusividade

A confirmação de pagamento trava pedido, reserva e cobrança, nessa ordem, e registra o fato financeiro na mesma
transação da decisão de exclusividade. Cobrança repetida não repete evento nem ativa a reserva outra vez.
Estado cancelado/expirado, preço ou Pix vencido, valor divergente, grupo alterado e salvaguarda pendente preservam o pagamento recebido,
mas devolvem `input-required` e registram `pagamento_revisao`, com um motivo controlado. Nenhuma devolução de dinheiro
é prometida automaticamente. O pagamento de uma cobrança antiga não reabre pedido cancelado nem modifica contrato.

A restrição de uma única reserva ativa por fazenda arbitra duas confirmações concorrentes. O conflito reverte
somente a ativação por savepoint; a cobrança permanece paga e a reserva aguardando pagamento passa a `conflito`.
Painel e `reserva.atualizada` na outbox são gravados na transação, sem envio externo durante a confirmação.
Erro de infraestrutura reverte a transação inteira, permitindo repetir o aviso de pagamento com segurança.
Os testes cobrem cancelamento versus pagamento, duas reservas concorrendo pela mesma fazenda, repetição idempotente,
prazos/valores/grupos divergentes e falha de outbox seguida de nova tentativa.

A ordem de travas também vale para aprovação humana, expiração e conversão em contrato. A aprovação busca o pedido
pelo token e só decide depois de travar pedido e reserva e reler token, prazo e estado. A expiração ordena os pedidos
candidatos e revalida as reservas sob trava; a conversão relê o estado depois de esperar o pedido. Assim, um replay
de pagamento não disputa essas rotinas na ordem inversa. Escritas do grupo travam o pedido antes de alterar fazendas;
um fechamento atrasado só prossegue se ainda estiver `buscando_interesse`, preservando reserva ou cancelamento
concluídos enquanto o cálculo rodava.

Antes de conceder exclusividade, a confirmação também executa novamente a verificação real de salvaguardas sobre
as fazendas congeladas na reserva. Evidência vencida ou revogada depois da aprovação humana exige revisão, mesmo
quando o Pix foi pago; o fato financeiro permanece registrado. O teste de regressão vence uma cobertura válida
entre aprovação e pagamento e verifica que nenhuma fazenda se torna exclusiva.
