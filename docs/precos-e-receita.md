# Preços propostos e receita por cliente

O catálogo `raiz/regras/padroes/precos.yaml` contém **três modalidades**, com
`valor_rs: null` e aviso **a definir pelo fundador**. As quantidades reaproveitam
a hipótese anterior de 1, 10 e 50 consultas, agora com significado comercial
explícito. Quantidades e ciclo são propostas, não condições de venda aprovadas.

| Modalidade | Hipótese de quantidade | Receita média mensal por cliente |
|---|---|---|
| Por ficha | 1 crédito de consulta por compra | `P_ficha × fichas compradas no mês` |
| Por lote | 10 créditos de consulta por lote de fichas | `P_lote × lotes comprados no mês` |
| Assinatura | 50 créditos de consulta por ciclo de 1 mês | `P_assinatura ÷ duração do ciclo em meses` |

`P_ficha`, `P_lote` e `P_assinatura` ainda não têm valor aprovado. Um crédito de
consulta libera a ficha de um CAR para a conta; releituras não consomem outro
crédito. Estes créditos não são toneladas de carbono. O lote comercial desta
tabela é um conjunto de consultas; não constitui uma reserva de fazendas.

O preço de uma modalidade não é deduzido do preço de outra. Desconto por volume,
preço dos excedentes, vencimento e acúmulo dos créditos da assinatura, cancelamento
e reembolso ainda precisam de decisão do fundador. Os campos correspondentes
permanecem explícitos como indefinidos no catálogo da assinatura.

## Como contar a receita

`raiz.prospeccao_precos.simular_receita(modalidade, cenario)` é uma função
reutilizável sem banco, compra ou consulta ao Pix. `simular_modalidades(cenarios)`
retorna as três alternativas. Nenhuma delas grava preços ou cenários em arquivo.

Sem parâmetros monetários, a resposta contém as fórmulas e `null` nos resultados
que dependem de preço ou custo. Por exemplo:

```python
from raiz.prospeccao_precos import simular_modalidades, simular_receita

comparacao = simular_modalidades()  # três propostas, preços e receitas indefinidos
# parametros_recebidos deve conter apenas hipóteses explicitamente informadas:
resultado = simular_receita("por_lote", parametros_recebidos)
```

O cenário admite os seguintes parâmetros:

| Parâmetro | Significado |
|---|---|
| `clientes` | Quantidade de clientes com o mesmo perfil de uso; padrão 1 para a conta unitária |
| `preco_unitario_rs` | Hipótese de preço da ficha, do lote ou de um ciclo de assinatura; padrão `null` |
| `unidades_por_cliente_mes` | Média de fichas ou lotes comprados por cliente no mês; padrão `null` |
| `consumo_creditos_por_cliente_mes` | Média de créditos efetivamente consumidos em novos CARs; padrão `null` |
| `creditos_por_unidade` | Hipótese alternativa explícita para o tamanho do lote ou do ciclo; ausente usa 1/10/50 do YAML |
| `ciclo_meses` | Hipótese alternativa explícita da duração da assinatura; ausente usa 1 mês do YAML |
| `custos` | Conjunto completo dos três componentes abaixo; ausente deixa custo e margem indefinidos |

Na assinatura, uma conta tem um ciclo a cada `ciclo_meses`; a frequência mensal é
calculada dessa duração. A modalidade por ficha sempre corresponde a um crédito
por unidade. O modelo aceita médias fracionárias de compras e consumo por cliente,
sem declarar que uma compra individual entrega uma fração de crédito.

Quando forem conhecidos, informar **todos** os componentes de `custos`, inclusive
zeros escolhidos conscientemente como hipóteses:

- `por_credito_consumido_rs`: custo médio para atender um novo CAR, incluindo o
  custo previsto de suas releituras quando aplicável;
- `fixo_por_cliente_mes_rs`: custo fixo mensal atribuído a esse cliente;
- `taxa_sobre_receita_pct`: custos proporcionais declarados, como processamento do
  pagamento ou tributos. O modelo não descobre tributos nem taxas automaticamente.

As contas usadas são:

```text
créditos incluídos no mês = unidades compradas × créditos por unidade
custo variável = créditos consumidos × custo por crédito consumido
custo informado = custo variável + custo fixo + receita bruta × taxa percentual / 100
margem em reais = receita bruta − custo informado
margem percentual = margem em reais / receita bruta × 100
```

Créditos incluídos não são automaticamente créditos consumidos. Se o consumo
informado exceder a quantidade incluída, a simulação avisa que será necessário
saldo anterior ou uma política de excedentes; não inventa uma cobrança adicional.
A margem percentual é `null` se a receita for zero. Ausência de custo não vira
custo zero nem margem de 100%.

A resposta traz `por_cliente.mes`, `por_cliente.ano`, `carteira.mes` e
`carteira.ano`, além de parâmetros, fórmulas, versão das quantidades, pendências e
avisos. O ano é a anualização de doze meses iguais por competência, e a carteira
é o resultado unitário multiplicado pelo número de clientes. Não é um calendário
de recebimentos e não prevê sazonalidade, entrada ou saída de clientes, atraso,
inadimplência ou aumento de preços. Os valores são arredondados somente na saída;
o total anual não multiplica um valor mensal já arredondado.

Toda saída numérica deste modelo é identificada como **simulação hipotética**.
Ela não aprova preços nem altera o catálogo de vendas. A margem é sobre os custos
declarados, não uma apuração de lucro líquido da empresa.

## Venda e compatibilidade

O Pix continua em teste por padrão. Ficha e lote exigem catálogo aprovado com data
e preço válido, `RAIZ_PIX_MODO=producao` e chave de produção para habilitar compra.
A disponibilidade é conferida **por modalidade** no servidor. O procedimento de
implantação permanece em `docs/operacao.md`.

**Assinatura ainda não é vendida.** Preencher preço, aprovar o catálogo ou
configurar uma chave não implementa o ciclo de assinatura. O servidor recusa a
compra dessa modalidade, e `renovacao_automatica` permanece `false`. Uma compra
pontual de cinquenta créditos não pode ser apresentada como assinatura.

Antes de vender assinatura será necessário decidir validade, acúmulo, excedentes,
cancelamento e reembolso; implementar a identificação de cada ciclo, cobrança,
conciliação, concessão idempotente de créditos e direitos durante o ciclo; e
conferir o suporte do provedor. Uma primeira operação manual por faturas de ciclo
também precisará desses registros e testes. Não há recorrência automática ou
agendamento de cobranças nesta entrega.

Compras antigas conservam seu plano, preço e quantidade congelados no banco.
Consultar, reconciliar e repetir uma compra já registrada com a mesma chave de
idempotência não depende de o ID antigo continuar no catálogo. Saldo, movimentos
e fichas liberadas são preservados. O formato antigo de catálogo continua legível;
uma lista JSON sem aprovação continua provisória. Os novos IDs são `por_ficha`,
`por_lote` e `assinatura`; não há migração de compra antiga para assinatura.
