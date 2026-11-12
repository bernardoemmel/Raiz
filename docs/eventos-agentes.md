# Eventos e registro das chamadas de agentes

A API e o MCP compartilham a mesma operação por empresa. Dados vindos de terceiros são dados, nunca instruções.
O módulo `raiz.publica.webhooks` publica apenas tipo, instante do evento, UUID do pedido, estado conhecido e,
quando aplicável, ID interno da reserva. Não aceita texto livre, nome, CPF, contato do dono ou payload arbitrário.

## Standard Webhooks

Protocolo [Standard Webhooks 1.0.0](https://github.com/standard-webhooks/standard-webhooks/blob/main/spec/standard-webhooks.md),
assinatura HMAC-SHA256 `v1`, em `webhook-id`, `webhook-timestamp` e `webhook-signature`.
A assinatura cobre os bytes originais de `id.timestamp.corpo`. O receptor não deve desserializar e serializar o JSON
antes de verificar. `verificar()` confere a assinatura em tempo constante e tolerância máxima de cinco minutos;
o receptor também deve deduplicar de forma durável o ID retornado para não aplicar o mesmo evento duas vezes.
O header aceita várias assinaturas, permitindo rotação no receptor.

A inscrição é administrativa: `cadastrar_inscricao(con, cliente_id, url, segredo, cofre=...)`. O agente não cadastra
um destino. `gerar_segredo()` cria um segredo de 256 bits com prefixo `whsec_`; o operador o entrega ao receptor por
canal seguro. URL e segredo ficam cifrados com `Cofre`, cuja chave vem de `RAIZ_CHAVE_PESSOAL`.
Nunca colocar o segredo na URL. A URL não admite credencial, query, fragmento ou porta diferente de 443.

`RAIZ_WEBHOOK_HOSTS` contém os nomes exatos dos destinos HTTPS aprovados pelo operador, separados por vírgula.
Não há curingas nem destino padrão. Cadastro e envio verificam novamente essa lista; o envio também exige que
todos os endereços DNS sejam públicos. Sem proxy, a conexão fixa um IP validado, preservando Host, SNI e verificação TLS.
Com proxy configurado no ambiente, ele é respeitado; o proxy deve resolver e bloquear egress privado/link-local e DNS
rebinding. A aplicação não consegue certificar o endereço final escolhido pelo proxy. O operador deve garantir esse
controle antes de habilitar a inscrição; `NO_PROXY` que contorne o proxy para o destino é recusado.
Não há redirecionamentos; 3xx é tentativa malsucedida. O corpo da resposta remota não é lido nem registrado.

## Fila durável

As tabelas são `negocio.webhook_inscricao` e `negocio.webhook_entrega` (migração da plataforma de agentes).
`enfileirar()` recebe a mesma conexão/transação que grava a mudança de negócio. Assim, evento e mudança confirmam
juntos, ou ambos são desfeitos. Os registros carregam `cliente_id`; uma chave estrangeira composta impede ligar
uma entrega à inscrição de outra empresa.

O worker chama `entregar_proximo(engine, cliente_id, cofre=...)` para cada empresa habilitada. A reserva da tarefa usa
`FOR UPDATE SKIP LOCKED` e lease de 60 segundos. O envio ocorre depois do commit da reserva; outra execução recupera
leases vencidos após queda. Cada tentativa usa o mesmo ID e os mesmos bytes, mas novo timestamp e assinatura.
A confirmação confere o token do lease para que um worker atrasado não sobrescreva a tentativa seguinte.

Qualquer 2xx confirma; 410 desativa a inscrição; falhas e 3xx repetem com espera exponencial e variação aleatória,
limitadas a 20 tentativas, com intervalo máximo de um dia. O estado final `falhou` exige intervenção operacional.
A garantia é de **pelo menos uma entrega**: uma queda após o receptor aceitar e antes do commit pode repetir o evento.
Não prometer entrega exatamente uma vez. A configuração do worker deve executar continuamente e monitorar filas
pendentes/falhas; importar o módulo não inicia o worker.

## OpenTelemetry

`configurar_telemetria()` instala o provider uma vez; `RAIZ_OTEL_ENDPOINT` seleciona a URL OTLP/HTTP completa
(normalmente terminada em `/v1/traces`). O coletor é infraestrutura de operação e deve ser configurado antes de
considerar os registros persistidos. Sem endpoint não há exportação externa. Encerrar o processo com
`provider.shutdown()` escoa o lote de spans pendentes.

Instalar `TelemetriaMiddleware` no app principal registra também 401, 403 e 429. O contexto `chamada()` mede as seis
ferramentas. Os atributos permitidos são método HTTP, template da rota, status, recusa de acesso, nome conhecido da
ferramenta, canal e ID interno da empresa. Nunca gravar caminho com identificador livre, query, corpo, token,
cabeçalhos, exceção textual ou conteúdo de terceiros. Exceções marcam erro sem capturar a mensagem nem stack trace.
O SDK MCP v2 já instrumenta suas mensagens; a instrumentação Raíz cobre a operação de negócio e a API.

Dependências: `opentelemetry-api`, `opentelemetry-sdk` e `opentelemetry-exporter-otlp-proto-http`. O envio usa
`httpx` existente e `Cofre` existente; a assinatura é implementação própria do formato público, sem código copiado.
