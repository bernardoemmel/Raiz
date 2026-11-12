# Contrato da sensibilidade do lote

A comparação fica na área autenticada do pedido. O site aberto publica somente o resumo permitido das três
alternativas. A demonstração optativa usa dados inteiramente fictícios, identificados na tela e na resposta com
`exemplo: true`; não lê os lotes privados do Pará e não serve para proposta comercial.

## Entradas e resultado da API

`POST /v1/pedidos/{pedido_id}/sensibilidade` exige sessão ou chave, o escopo de consulta ao lote, liberação da
conta e propriedade do pedido. A leitura da grade só acontece depois dessas verificações. A resposta tem
`Cache-Control: private, no-store`. O alias `/pedidos/{pedido_id}/sensibilidade` conserva o portão da API v1.

| Entrada | Unidade e limite |
|---|---|
| `preco_credito_usd` | US$ por crédito, maior que zero e até 1.000 |
| `reserva_reversao` | Fração de 0,20 a 0,90; o motor ainda deve respeitar riscos específicos de cada fazenda |
| `taxa_desconto` | Fração anual de 0 a 0,50 |
| `pessimista` | Booleano; a descrição das premissas vem do produtor do cálculo |

A resposta compartilha o contrato TypeScript `ResultadoSensibilidade`. Contém estado (`disponivel` ou
`indisponivel`), `exemplo`, parâmetros efetivamente aplicados, fonte, data com fuso, versão do modelo, aviso e
três opções. Cada opção traz identificador, créditos P10/P50/P90, hectares, número de fazendas, VPL em US$,
TIR do projeto em fração anual e indicação de alcance da meta no P50. Não contém CAR, contornos ou linhas por fazenda.

Uma TIR não encontrada fica nula. A sentinela legada -100 não é válida neste contrato. TIR é uma propriedade do
fluxo de caixa: mudar apenas a taxa de desconto altera o VPL, sem mudar a TIR do mesmo fluxo. A data da execução
de uma demonstração não é apresentada como data de publicação de dados reais.

## Entrada privada produzida pelo motor

O servidor lê a pasta configurada em `RAIZ_SENSIBILIDADE_DIRETORIO`; ela não deve ficar no diretório do site.
Cada arquivo se chama `<UUID-do-pedido>.json`. A estrutura validada por
`raiz.pedidos.sensibilidade.GradeSensibilidade` é:

- `pedido_id`: UUID do pedido que originou o cálculo.
- `modelo_versao`: exatamente a versão gravada no pedido.
- `atualizado_em`: data da publicação com fuso horário.
- `fonte`: identificação da saída privada e sua procedência, sem URLs assinadas nem dados pessoais.
- `aviso`: premissas do cenário pessimista, alcance e limites do cálculo, inclusive se o solver refez a composição.
- `cenarios`: lista de `{ parametros, opcoes }`, no mesmo formato da resposta.

Cada combinação precisa das três opções completas. Parâmetros duplicados, campo desconhecido, quantis fora de
ordem, número não finito, data sem fuso e pedido/modelo divergentes invalidam a grade inteira. O consumidor não
interpola pontos, não mistura cenários e não extrapola o resumo central. Se o arquivo ou a combinação não existir,
a API responde 200 com `estado: indisponivel` e `opcoes: []`; não converte ausência em zero.

Na publicação do Pará do PR #78, as três listas `sensibilidade` estão vazias. A reunião da rodada chama
`L.montar(..., sensibilidade_ligada=False)`. O tornado existente no motor varia captura/custo/preço/câmbio e não
substitui uma grade conjunta dos quatro controles desta tela. A publicação dessa grade pelo chat Lote e números
continua pendente. Não foi executado recálculo nem promovido artefato privado a público nesta entrega.

## Demonstração e verificações

O exemplo mantém três composições fictícias fixas e fluxos inventados de 25 anos. O cenário pessimista reduz a
captura em 40% e eleva os custos em 30%, exclusivamente para testar a interação. Esses fatores não são inferidos
do Release nem apresentados como calibração do modelo real. Nenhum resultado demonstrativo é persistido no
histórico de aprendizado.

Vitest confere a separação entre desconto e TIR, preço e créditos físicos, reserva, limites e ausência de API.
Pytest verifica grade exata, validação, identidade, modelo e autorização antes da leitura. O Playwright da
cena-alvo exerce os quatro controles, resultado defasado, combinação indisponível, teclado, 360 px e axe WCAG 2.1 AA.
