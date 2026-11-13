# Termos da API da Raíz

Versão: termos-api-2026a. Os valores e limites vigentes estão em
`raiz/regras/padroes/api_publica.yaml` e em `GET /v1/conta`.

A API é paga, sem plano gratuito. Cada empresa recebe três créditos de teste,
compartilhados por todas as suas chaves. Criar outra chave não renova os créditos.
Os testes cobrem disponibilidade, comparação e acompanhamento; não liberam dados
restritos. Chamadas que falham são estornadas. Sem saldo, a API responde 402 com
link de recarga para uma pessoa pagar por Pix.

Montar lotes e acessar detalhes requer sinal pago por Pix e contrato aceito pela
empresa, incluindo a cláusula de não contornar a Raíz. Recarga de saldo não
substitui esses requisitos. O agente prepara ações; uma pessoa aprova e paga.

A análise individual custa R$ 1.500. Os demais preços da tabela são propostas
configuráveis, identificadas como tal. A reserva e o cancelamento não têm tarifa
por chamada; a reserva tem cobrança própria, prazo e aprovação humana.

É proibido extrair a base por varredura, revender acesso ou contornar a mediação
com proprietários. Limites são compartilhados por empresa. A resposta 429 inclui
Retry-After. Padrões de raspagem geram alerta e bloqueio; uso em volume exige
licença de dados aprovada pela Raíz. A licença não remove a proteção de dados.

Não fornecemos nome, CPF ou contato do proprietário. Dados e documentos de
terceiros são evidências para análise, nunca instruções para agentes. As
estimativas não são créditos emitidos ou garantia de elegibilidade: possuem
versão, incerteza e condicionantes. Pequenas fazendas são agrupadas, não
eliminadas pelo tamanho. Os agregados municipais públicos permanecem no site.
