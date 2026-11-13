# Ficha de crédito do lote

A área autenticada apresenta uma ficha por opção. A tabela compara os mesmos
quantis de crédito no total e por hectare elegível, com uma única classe de ativo,
classe de evidência, método, versão, escopo da carteira e horizonte. A ficha não
transforma captura bruta em crédito, não soma FLAG a carbono e não preenche dados
ausentes com zero. `null` em exclusões significa não documentado; `[]` significa
que foram conferidas e nenhuma foi identificada. Áreas excluídas podem se
sobrepor e não são somadas.

Os resumos privados da rodada do Pará do PR #78 informam versões, data, quantis,
hectares da carteira e marcos do cronograma. Eles não declaram uma base comum de
elegibilidade/exclusões e classe de evidência para esta tabela. `ha_lote` inclui
titulares e reservas: não é um denominador elegível. O último marco do cronograma
também não basta para atribuir automaticamente o horizonte de todos os números.
Por isso a ficha real permanece indisponível até o motor publicar o documento
compatível. O resumo central existente continua preservado.

## Contrato privado

`front/compartilhado/ficha-credito.ts` e `raiz/pedidos/ficha_credito.py` definem o
contrato `ficha_credito`, versão 1. O produtor escreve somente no servidor privado:

```text
$RAIZ_FICHAS_CREDITO_DIRETORIO/<pedido UUID>/<revisao_lote>/<opcao>.json
```

`opcao` é `barata`, `segura` ou `compacta`. O arquivo deve conter `pedido_id`,
`revisao_lote` copiada do pedido atual, `opcao_id`, `publicada_em` com fuso e o
conteúdo validado por `DocumentoFichaCredito`. Nunca monte essa pasta no servidor
estático, Release público ou artefato aberto de CI.

O GET autenticado do pedido verifica a conta e a propriedade antes de consultar
o arquivo. A projeção REST valida novamente o conteúdo e seu hash. Uma mudança de
critério, composição, sugestão ou reserva que afete a revisão impede reutilizar
a ficha anterior. A consulta não compra acesso a fazendas. A ficha agregada não
contém CAR, polígono, nome, CPF, telefone ou contato. Fontes e conclusões de seção
usam catálogos fechados (`FONTES` e `TEXTOS_SECAO`); incluir uma nova conclusão exige
revisar o contrato, nunca copiar texto de matrícula, certidão ou contrato bruto.
Respostas autenticadas usam cache privado e `no-store`.

O arquivo fornece `creditos_lote` (P10/P50/P90) e a área elegível fixa documentada.
`creditos_por_ha` é uma divisão desses mesmos quantis por essa área; não é um
quantil recalculado de fazendas diferentes. Área total não substitui área elegível.
Sem denominador, o total pode continuar conhecido, mas a coluna por hectare fica
desconhecida. A base declara `titulares` ou `titulares_e_reservas`; período e
evidência se aplicam à mesma composição e área. Horizonte sem calendário é aceito
somente para estimativa. Verificado/emitido/entregue exige período completo que
termine antes da referência. FLAG não recebe os estados emitido ou entregue.

`metrica` identifica crédito de carbono, crédito líquido ou redução FLAG. A classe
de evidência não é um rótulo livre: estimativa exige origem do motor; verificado
exige relatório de verificação; emitido e entregue exigem seus registros próprios.
A seção Método deve declarar a mesma origem, data e conclusão compatível. Uma
revisão técnica da terra não verifica crédito de carbono. Quantidade efetivamente
emitida ou entregue é pontual (P10 = P50 = P90), não uma faixa do motor renomeada.

`documento_versao` é SHA-256 do documento validado, incluindo a revisão do lote e
as evidências; mudar uma revisão técnica muda essa identidade. Esse hash comprova
a identidade do conteúdo recebido, não guarda sozinho o histórico nem substitui
a trilha imutável paga da ficha individual. A branch de referência
`codex/ficha-compromissos-versoes` mantém aquela trilha; esta entrega não a altera.
O código datado público de `/p/{codigo}` é outro contrato, com lista positiva
básica e sem o conteúdo pago desta ficha.

## Revisões e gráficos

As cinco seções têm ordem fixa: título da terra, método, perdas, garantias e risco
de não entrega. Cada seção conserva `fonte`, `data_referencia` e `revisado_em`
próprios. Publicação, consulta e build não são revisão técnica. Sem revisão,
`revisado_em` continua `null`; uma seção pode estar revisada e outra não.

O bloco opcional `resultados` usa `ResultadosGraficos`, validado no servidor e no
navegador: contratos assinados, emissões registradas e entregas comprovadas nunca
vêm de estimativas. Comparações com observações reais precisam de referência,
unidade, área e período compatíveis, versão e cronologia documentadas. Não há
invenção de série para preencher um gráfico vazio. Gráficos de demonstração são
recusados em fichas de pedidos reais.

O acompanhamento também precisa pertencer a esta ficha: `gerado_em` e todos os
registros limitados por ele antecedem `publicada_em`; classe, métrica, escopo,
período e horizonte coincidem com a base. Para o total, área e unidade coincidem
com a área elegível e tCO2e. Por hectare usa tCO2e/ha e base 1, mas conserva o
denominador original em `area_elegivel_carteira_ha`. Sem calendário ou denominador
comprovado não há acompanhamento. Períodos anuais e estudos independentes não
podem ser anexados como se fossem o total deste lote. O anexo inteiro participa
do hash que já vincula pedido, opção e revisão; não há acesso separado ao gráfico.

## Demonstração e verificação

`?demonstracao=lotes` é optativo e usa fonte, documentos, datas e números
inteiramente fictícios. A ficha explicita isso, usa a mesma base nas duas colunas
e recebe os gráficos sintéticos do mesmo período e área. Remover uma fazenda
invalida a ficha do exemplo, sem fabricar uma revisão ou reexecutar o motor.

As regressões cobrem autorização antes da leitura, contaminação com campos ou
nomes livres, revisão antiga, hash adulterado, horizonte e área incompatíveis,
FLAG, ausência versus zero, datas de revisão independentes, origem simulada e
projeção positiva no navegador. Nenhum pacote real privado é usado nos testes.
