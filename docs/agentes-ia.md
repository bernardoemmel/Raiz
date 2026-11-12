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

O MCP antigo foi retirado nesta entrega. A próxima etapa reabre `/mcp` no mesmo
aplicativo com SDK oficial Python v2, OAuth 2.1/Keycloak e seis ferramentas por
intenção. Até lá não há conector MCP por chave ou acesso anônimo.
