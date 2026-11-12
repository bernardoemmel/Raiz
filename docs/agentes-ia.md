# A Raíz para agentes de IA (API pública e MCP)

A empresa cliente pode fazer o pedido de lote pelo próprio agente de IA, sem abrir o mapa. Exemplo: "preciso de 1
milhão de créditos no Pará, no cronograma do ProFloresta+". O agente usa a **API pública** (`/v1`) ou o **servidor
MCP** (`/mcp`), e os dois chamam o mesmo cálculo do mapa.

Regras que valem para os dois caminhos:

- **Privacidade:** nunca saem nome, CPF, CNPJ ou contato de dono de fazenda. O contato com os donos passa pela Raíz.
- **Dinheiro:** a reserva pedida por agente nasce **aguardando confirmação**. Uma pessoa da empresa confirma pelo link
  enviado ao e-mail cadastrado, e só então sai o Pix. O agente nunca recebe o link nem paga.
- **Registro:** cada chamada fica gravada (empresa, ferramenta, pedido, versão do modelo da Raíz e o modelo do agente)
  em `negocio.chamada_api`, para o limite da chave, a auditoria e o aprendizado. A empresa vê o que o agente dela fez
  em `GET /v1/chamadas`.

## 1. A chave da empresa

Uma pessoa da empresa cria a chave e a passa para o agente. Há dois jeitos:

1. Entrar pelo e-mail (`POST /entrar`) e criar a chave em `POST /v1/chaves`, com o rótulo do agente e os limites.
2. Pedir para a Raíz rodar `raiz pedidos chave --cliente <id> --rotulo "agente de compras"`.

A chave começa com `raiz_` e aparece **uma vez só**: a Raíz guarda apenas o hash dela. Para revogar, use
`DELETE /v1/chaves/{prefixo}`.

O limite padrão é de 30 chamadas por minuto e 2.000 por dia. Quem passa do limite recebe a resposta 429 com
`Retry-After`.

Como mandar a chave:

- no cabeçalho `X-Chave-API: raiz_...`; ou
- no cabeçalho `Authorization: Bearer raiz_...`.

Opcional: o agente pode dizer o modelo que usa no cabeçalho `X-Agente-Modelo`.

## 2. API pública (`/v1`)

- Documentação: `/v1/docs` (Swagger) e `/v1/redoc`.
- OpenAPI completa, em português e com exemplo em cada rota: `/v1/openapi.json`.

O caminho do pedido:

| Passo | Rota | O que faz |
|---|---|---|
| 1 | `POST /v1/base` | Quanto existe na base, sem salvar nada: fazendas, hectares e créditos P10/P50/P90, por caminho da terra e por interesse do dono. Se faltar, diz quanto e o que afrouxar. |
| 2 | `POST /v1/pedidos` | Monta o lote em 3 opções: mais barata, mais segura e mais compacta, cada uma com reserva. |
| 3 | `GET /v1/pedidos/{id}/opcoes` | As 3 opções, com as fazendas de cada uma. |
| 4 | `GET /v1/fazendas/{cod_imovel}` | Explica uma fazenda, sem dado pessoal. |
| 5 | `POST /v1/pedidos/{id}/solicitar-interesse` | A Raíz contata os donos em ondas. |
| 6 | `GET /v1/pedidos/{id}/andamento` | Quanto da meta tem dono interessado, com aceite e com contrato. |
| 7 | `POST /v1/pedidos/{id}/reservar` | Pede a reserva do grupo pronto; fica aguardando a confirmação de uma pessoa. |

Também existem:

- `POST /v1/pedidos/{id}/lote`: tira ou troca uma fazenda numa opção.
- `GET /v1/pedidos` e `GET /v1/pedidos/{id}`: os pedidos da empresa.
- `GET /v1/pedidos/{id}/reserva`: a situação da reserva.

Exemplo do passo 2 com `curl`:

```bash
curl -s https://api.raiz.exemplo/v1/pedidos -H "X-Chave-API: raiz_..." -H "Content-Type: application/json" -d '{"meta": {"tipo": "creditos", "valor": 1000000}, "cronograma": "profloresta", "onde": {"ufs": ["PA"]}}'
```

## 3. Servidor MCP

O servidor MCP usa o SDK oficial do Model Context Protocol em Python (pacote `mcp`, licença MIT). Ele chama a mesma
API, e cada ferramenta vira uma chamada gravada com `via = mcp`.

| Ferramenta | O que faz |
|---|---|
| `buscar_base` | Quanto existe na base para o pedido (meta, estados, municípios, cronograma, custo, métodos, terra, interesse, forma). |
| `montar_lote` | Cria o pedido e devolve o id e as 3 opções. |
| `ver_opcoes` | As 3 opções; com `com_fazendas=true`, cada fazenda do lote e da reserva. |
| `explicar_fazenda` | Uma fazenda, sem dado pessoal. |
| `solicitar_interesse` | A Raíz busca o interesse dos donos de uma opção. |
| `andamento_do_pedido` | O andamento do pedido. |
| `pedir_reserva` | Só pede: uma pessoa da empresa confirma pelo e-mail. |

### Remoto, por HTTP

O endereço é `https://<api da Raíz>/mcp/`, por streamable HTTP, sem estado.

A chave vai no cabeçalho `X-Chave-API`. Para conectores que não mandam cabeçalho, ela pode ir na URL:
`https://<api>/mcp/?chave=raiz_...`. Nesse caso, use uma chave só para o conector, com limite baixo, e revogue quando
quiser.

Em produção, defina os hosts aceitos em `RAIZ_MCP_HOSTS` (por exemplo, `api.raiz.com.br`). Isso liga a proteção
contra DNS rebinding.

### Local, por stdio

```bash
RAIZ_API_URL=https://api.raiz.exemplo RAIZ_CHAVE_API=raiz_... raiz mcp
```

### Ligar no Claude

**Claude Code**, pelo MCP remoto, com a chave no cabeçalho:

```bash
claude mcp add --transport http raiz https://api.raiz.exemplo/mcp/ --header "X-Chave-API: raiz_..."
```

**Claude Code**, local, por stdio:

```bash
claude mcp add raiz -e RAIZ_API_URL=https://api.raiz.exemplo -e RAIZ_CHAVE_API=raiz_... -- raiz mcp
```

**Claude Desktop:** em Configurações, Desenvolvedor, Editar configuração, acrescente em `claude_desktop_config.json`:

```json
{"mcpServers": {"raiz": {"command": "raiz", "args": ["mcp"], "env": {"RAIZ_API_URL": "https://api.raiz.exemplo", "RAIZ_CHAVE_API": "raiz_..."}}}}
```

**Claude.ai** (conector personalizado, em Configurações, Conectores): use a URL do MCP remoto com a chave,
`https://api.raiz.exemplo/mcp/?chave=raiz_...`.

### Ligar no ChatGPT

No ChatGPT, os conectores de MCP remoto ficam em Configurações, Conectores, no modo de desenvolvedor. Para ligar:

1. Crie um conector com a URL `https://api.raiz.exemplo/mcp/?chave=raiz_...`.
2. Escolha a autenticação "sem autenticação": a chave já vai na URL.

As ferramentas aparecem com as descrições em português.

Na API de Respostas da OpenAI, a ferramenta `mcp` aceita `server_url` e `headers`, então dá para mandar a chave no
cabeçalho:

```json
{"type": "mcp", "server_label": "raiz", "server_url": "https://api.raiz.exemplo/mcp/", "headers": {"X-Chave-API": "raiz_..."}, "require_approval": "never"}
```

Os nomes dos menus mudam com as versões do Claude e do ChatGPT. O que vale é a URL do MCP remoto, com a chave no
cabeçalho ou na URL.

## 4. Teste de ponta a ponta

Em `testes/test_publica_banco.py`, um agente de teste (cliente MCP do SDK oficial) liga no servidor da Raíz e
segue o caminho do pedido:

1. Faz o pedido de 1 milhão de créditos no Pará.
2. Recebe as 3 opções.
3. Abre uma fazenda.

O teste confere que nada pessoal sai e que cada chamada ficou gravada com o modelo do agente.

Os outros testes cobrem o limite da chave, a reserva que espera a pessoa e o MCP remoto por HTTP (com a chave no
cabeçalho e na URL).
