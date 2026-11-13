# Ficha resumida do lote

Rodada 12. A ficha é aberta pelo botão **Ficha resumida desta opção** no pedido
autorizado, em `#/pedidos/{id}/ficha/{barata|segura|compacta}`. Ela recebe o bloco
`ficha_credito` da mesma opção pela API. O site aberto não consulta essa rota da
API, não monta a ficha e continua mostrando somente o resumo público do lote.
A demonstração exige escolha explícita e identifica números, documentos e datas
como fictícios.

O contrato e as condições para o motor publicar dados reais estão em
[Ficha de crédito do lote](../ficha-credito.md).

## Leitura fixa

A ordem é sempre **Título → Método → Perdas → Garantias → Risco de não entrega**.
Cada seção mostra sua própria revisão técnica, fonte e data de referência. Uma
data ausente aparece como não informada. A publicação do documento, sua versão
e a revisão da composição ficam em um detalhe separado: nenhuma dessas datas
substitui a revisão técnica.

Dentro de Método, a tabela **Fatos do lote** usa tipografia, alinhamento numérico
e regras pretas de diferentes espessuras para facilitar a comparação. A referência
visual é a organização de uma tabela nutricional; não há selo ou alegação de
aprovação da FDA, OSHA, SEC ou de qualquer certificador.

## Duas colunas, uma base

P10, P50 e P90 são apresentados por hectare elegível e para todo o lote. A base
declarada ao lado da tabela fixa horizonte, período quando conhecido, método,
versão do modelo, classe de ativo, classe de evidência e composição (titulares,
ou titulares e reservas). A coluna por hectare usa a área elegível documentada
do mesmo bloco, nunca a área total do CAR nem uma área calculada pela diferença
das exclusões. FLAG e créditos de carbono permanecem separados. Estimativa de
modelo não recebe rótulo de emissão, entrega ou crédito líquido.

O leitor do contrato confere a opção e a revisão do lote antes de exibir os
valores. Documento antigo, horizonte incompatível ou denominador sem evidência
viram **não informado**, sem preencher zero. Exclusões desconhecidas são
diferentes de nenhuma exclusão identificada. Quando existem, cada linha mostra
hectares, fonte e referência; o aviso de sobreposição impede a soma das linhas.

Os gráficos ficam depois das cinco seções. Usam somente o bloco autorizado e
validado de resultados. As tabelas ficam disponíveis antes dos gráficos; ECharts
e Vega-Lite só são carregados quando a pessoa pede a visualização. A ausência de
contrato, emissão, entrega ou observação real é explícita.

## Acesso e apresentação

O bloqueio público acontece antes da consulta ao pedido. Sair da conta desmonta
a ficha privada. A tela não inclui dono, CPF, contato ou ação de pagamento e não
inicia contato com o proprietário. O código público datado do imóvel é uma
publicação básica separada; ele não transforma esta ficha de crédito em página
pública.

A rota e o componente são carregados sob demanda. A tabela cabe em 360 px sem
rolagem horizontal da página, usa cabeçalhos semânticos e mantém o mesmo conteúdo
no celular. A identidade do documento abre com teclado, e os estados de espera,
ausência e acesso recusado são anunciados por tecnologia assistiva.

## Verificação

`node front/scripts/testar-ficha-credito.mjs` inicia Vite e uma API interceptada,
com uma ficha inteiramente fictícia. Confere a ordem fixa, as duas colunas na mesma
base, as revisões por seção, rejeição de horizonte e revisão incompatíveis,
documento ausente, navegação por teclado, saída da conta e bloqueio público.
O teste exige zero erro HTTP/JavaScript, zero violação axe WCAG 2.1 A/AA e ausência
de transbordamento em 360 px. Capturas e relatórios ficam em
`front/.cache/teste-ficha-credito/`. O build executa TypeScript e o verificador de
design antes de gerar os arquivos do site.
