# Avaliação da cascata por documento

`raiz modelos avaliar-cascata` mede a decisão e o custo de API da cascata completa por hash da entrada.
O modelo local responde primeiro quando a entrada cabe na política de classificação curta. Sem corte aprovado,
com confiança insuficiente ou resposta inválida, chama o Haiku. A regra de acordo, juiz e revisão da produção é
preservada: uma discordância não vira automaticamente uma leitura correta.

Documentos longos, saída extensa/livre e PDF com imagem ou página sem texto passam ao Haiku com o motivo registrado.
O relatório não declara que o Qwen executou quando essa etapa foi dispensada. Para PDF curto com texto completo,
o Qwen lê o texto extraído; o Haiku e o juiz recebem o PDF inteiro quando chamados. A confiança dos logprobs não
é uma probabilidade de acerto. Os cortes atuais continuam vazios: a avaliação anterior não aprovou nenhum.

## Entradas reais

Não há conjunto de certidões reais pronto. O comando não o cria nem trata a previsão do motor como gabarito.
O manifesto fica em pasta privada, fora do git, junto aos PDFs/TXTs reais (até 32 MiB por documento). Seu contrato é:

| Campo | Conteúdo |
|---|---|
| `origem` | `documentos_reais`, declaração de quem preparou a avaliação |
| `documentos` | Lista não vazia; conteúdo repetido é rejeitado pelo hash |
| `arquivo` | Caminho do PDF/TXT relativo ao manifesto, ou caminho absoluto privado |
| `tarefa` | Identificador estável da tarefa, como `certidao.classificacao` |
| `sistema`, `pedido`, `esquema` | Prompt e esquema JSON de produção; nunca o gabarito no prompt |
| `max_tokens` | Limite da saída, de 1 a 64.000; padrão 400 |
| `gabarito` | Objeto completo revisto por gente; omitido, o acerto fica desconhecido |
| `gabarito_origem` | `revisao_humana_integral`, obrigatório quando há gabarito |
| `gabarito_confirmado_em` | Data da revisão com fuso, não futura; obrigatória quando há gabarito |

O programa valida a declaração e o formato; não consegue provar sozinho que o arquivo é real ou que a revisão
humana aconteceu. A origem dos documentos e a revisão precisam ser auditáveis no fluxo de entrada da certidão.

```bash
RAIZ_LLAMA_URL=http://localhost:18080 uv run raiz modelos avaliar-cascata \
  --documentos /caminho/privado/manifesto.json --tentativas 1 \
  --saida dados/avaliacao/certidoes
```

`ANTHROPIC_API_KEY` é a variável padrão; `RAIZ_ANTHROPIC_API_KEY` também é aceita no ambiente ou `.env`.
Sem chave, o comando para antes de rodar o conjunto e identifica esses nomes, sem imprimir valores. Em 12/11/2026,
a chave não estava disponível no processo nem nos `.env` conhecidos do ambiente deste chat; o teste de conexão
retornou a ausência de `ANTHROPIC_API_KEY`. Nenhum acerto ou custo Haiku foi medido nessa condição.

## Benchmark técnico distinto

As 120 tarefas já existentes testam o agente de aceite. Não são documentos nem certidões, e o relatório usa
`tipo=benchmark_aceite` e `unidade=tarefa`. Servem para comparar a cascata com os modelos isolados, não para afirmar
qualidade da leitura de matrícula.

```bash
RAIZ_LLAMA_URL=http://localhost:18080 uv run raiz modelos avaliar-cascata \
  --benchmark-aceite --tentativas 3 --saida dados/avaliacao/aceite
```

## Medidas e preços

O relatório privado (permissão `0600`) não inclui nome de arquivo, texto, valores do gabarito, saída do modelo
nem corpo livre de erro. Registra hash do conjunto/entrada, política/corte, cada modelo efetivo, tokens de entrada,
saída e cache, preço aplicado, duração, caminho da decisão e acerto. O acerto integral usa igualdade do objeto
com o gabarito; também há contagem de campos corretos. Revisões contam como não resolvidas no acerto total e ficam
fora do acerto das decisões automáticas. Sem gabarito, ambos os acertos ficam `null`.

Os preços vêm do `genai-prices`, com versão da biblioteca e tarifa por chamada registradas. A
[tabela oficial da Anthropic](https://platform.claude.com/docs/en/about-claude/pricing), conferida em **12/11/2026**,
mostra Haiku 5.5 a US$ 0,10/0,50 por milhão de tokens de entrada/saída até 100 mil tokens no prompt; acima disso,
US$ 0,50/2,50. O limiar inclui leituras e escritas de cache. Cache de cinco minutos custa US$ 0,125 para escrita e
US$ 0,01 para leitura por milhão na faixa inicial; na faixa longa, US$ 0,625/0,05. A configuração atual usa pedidos
síncronos globais, sem Batch ou residência regional. Trocar essa configuração exige refletir seus modificadores.

Uso ou preço ausente gera custo `null`, nunca zero. Custos conhecidos parciais aparecem separados. O custo por
entrada inclui todas as chamadas (Qwen, Haiku e eventual juiz) e informa total e média por tentativa. Zero em API
local não significa máquina gratuita: duração local é medida, mas seu custo monetário fica indisponível sem uma
tarifa real de execução. Valores são em USD; não há conversão presumida para reais.

Falhas técnicas deixam o comando com saída não zero e relatório de cobertura incompleta. Falha de autenticação
não constitui avaliação. Os testes automatizados usam fixtures sintéticas somente para verificar essas regras.
