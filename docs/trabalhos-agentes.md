# Operações duráveis dos agentes

`submeter(engine, cliente_id, ferramenta, corpo, chave, lancamento_id=None)` valida o corpo e o `Idempotency-Key`,
confere a liberação, procura a repetição e debita uma única vez na mesma transação. O retorno contém `pedido_id`
(identificador da operação), `estado` e, depois da conclusão, `negocio_pedido_id` (identificador do pedido do lote).
O estado e o resultado são lidos por `obter(engine, cliente_id, pedido_id)`. Não há execução em callback HTTP.
Para lote concluído, o recibo devolve apenas o identificador do pedido. O snapshot completo fica como evidência
interna; `comparar_lotes` aplica novamente a exclusividade e a liberação antes de mostrar qualquer fazenda.

A fila aceita `pedir_lote` (corpo `CamposPedido`) e `preparar_reserva` (corpo com `pedido_id` do lote e `base_url`
configurada pelo servidor). O agente nunca aprova nem paga. A preparação da reserva precisa permanecer local ao
banco: `servico.reservar(..., por_agente="operacao:<id>")` não pode enviar mensagem nem criar Pix antes da pessoa.

O worker `executar_proximo(engine)` reivindica com `FOR UPDATE SKIP LOCKED`, publica `working` e executa mantendo a
linha travada. Serviços recebem uma conexão vinculada: seus blocos `begin()` são savepoints da transação do worker.
Resultado e efeitos de negócio confirmam juntos. O teste encerra abruptamente um processo após inserir o pedido,
sem sair dos contextos Python: o banco reverte o efeito e o worker seguinte recupera a mesma operação. Após 15 minutos, um
worker recupera a operação. Um worker ainda vivo mantém a trava, mesmo que o prazo expire. Não se repete pedido
confirmado: a conclusão já está gravada na mesma transação.

`cancelar(engine, cliente_id, pedido_id)` cancela apenas antes do início e estorna na mesma transação. Depois que o
worker começou, responde conflito; isso não promete desfazer operação em curso nem cancelar uma reserva já criada.
Falha de negócio estorna o lançamento. Retentativa com a mesma chave devolve o mesmo estado, inclusive falha e
cancelamento; uma nova tentativa precisa de outra chave. Mesmo corpo com outra chave é outra operação cobrável.

Não criar cobrança Pix externa na submissão: saldo insuficiente responde 402 e indica `/v1/conta/recarga`, onde uma
pessoa pode gerar o pagamento. Travas de banco na submissão têm limite de 500 ms e comandos, 3 s; indisponibilidade
responde erro recuperável. O cliente HTTP/ASGI deve ainda impor o orçamento total de 5 s.

## Migração necessária

```sql
CREATE TABLE negocio.trabalho_api (
    id uuid PRIMARY KEY,
    cliente_id bigint NOT NULL REFERENCES negocio.cliente(id) ON DELETE CASCADE,
    ferramenta text NOT NULL CHECK (ferramenta IN ('pedir_lote', 'preparar_reserva')),
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
```

A tabela não guarda a chave de idempotência em texto. O corpo vem do esquema do pedido; os dados da resposta passam
pelo filtro de privacidade. Não enviar corpo, chave, token de aprovação ou texto de terceiros para logs.
