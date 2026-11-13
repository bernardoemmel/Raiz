# Potencial conhecido no mapa

O mapa agrega o **potencial conhecido de regeneração além da reserva legal**, com cobertura parcial.
A medida é `carbono_ha` do motor: o menor entre a área além da reserva legal e o pasto próximo da floresta.
Não é a área total restaurável do desenvolvedor, um lote selecionado, a superfície disponível para venda
ou uma declaração de elegibilidade. A fonte original está descrita em `docs/colunas.md`.

`python -m raiz.potencial_publico` lê os pacotes canônicos no Release privado, com autenticação,
verificação de visibilidade, tamanho e SHA-256. Os IDs dos assets são congelados antes da leitura.
Os hashes de cada GeoParquet são conferidos contra `_versoes.json` do pacote de medidas;
um par misturado durante uma publicação é recusado e a leitura daquela UF é repetida.
As datas dos metadados são datas de publicação dos pacotes, não datas universais de medição no campo.
O processo não escreve os pacotes completos em `front/geo`, caches ou artifacts públicos. Para avaliação
local de um espelho já autorizado, existe `--dados-privados /caminho/do/espelho`; sem essa opção, a leitura é remota.

A publicação segue estes passos:

1. Deduplicar o código do CAR globalmente. Repetição idêntica não soma hectares nem fazendas; geometria
   ou medida contraditória torna a medida desconhecida.
2. Verificar interseção de área entre todos os CARs válidos, inclusive os sem medida, cruzando municípios
   e estados. Encostar na divisa não conta; uma interseção apenas de caixas envolventes também não conta.
3. Atribuir cada imóvel a uma única célula H3, resolução 5, pelo ponto interior de seu contorno.
4. Somar apenas medidas positivas conhecidas de imóveis sem sobreposição detectada. Liberar hectares
   somente quando houver pelo menos cinco contribuintes positivos distintos na célula. As outras células
   com pelo menos cinco CARs mostram valor desconhecido; células menores são omitidas.

Nenhuma fazenda, pequena ou grande, é apagada do cadastro por essas regras. A exclusão da soma é uma
limitação da cobertura desta visualização. Como não existe o desenho medido da restauração para todo o país,
a área dos CARs sobrepostos **não é rateada, descontada proporcionalmente ou somada duas vezes**. Valores
zero do motor também não são prova de ausência de potencial: algumas entradas ainda faltam.

O ponto interior é uma alocação estatística do imóvel inteiro. Portanto, a cor **não mede hectares
fisicamente contidos dentro do hexágono** e não deve ser usada como densidade por área da célula.
Na escala até zoom 11, o hexágono substitui os detalhes; nenhuma hachura de restauração é inventada.

## Contrato e proteção dos dados

`front/geo/potencial_indice.json` anuncia os arquivos `potencial_<UF>.geojson.gz`. O build incorpora essas
referências em `geo/indice.json`, nas chaves `potencial` e `potencial_metadados`. Cada coleção traz `metadados`
com fonte, datas das fontes, data de geração, resolução, método, aviso de cobertura parcial e contagens globais
(incluídas, sem medida, com sobreposição e sem geometria). As contagens de ausência e sobreposição podem se
sobrepor; não são parcelas de um total exclusivo.

Cada feição contém somente `h3`, `potencial_ha` (número ou `null`) e `fazendas` (CARs distintos na célula).
Não há CAR, tabela por imóvel, TIR, crédito, preço, dono ou vínculo com os três lotes nessa camada.
Células na fronteira de UFs são repetidas integralmente, com os mesmos valores, nos arquivos das UFs
correspondentes: o consumidor deduplica pelo identificador H3. Não há subtotal estadual da mesma célula.
A escala de cores é fixa no país: limites em 0, 100, 1.000, 10.000 e 50.000 hectares.

O build valida novamente o contrato e reconstrói a geometria a partir do identificador H3. Não copia uma
geometria arbitrária da entrada, campos extras ou textos livres da fonte. Os totais de medidas suprimidas e
as identidades que permitem conferir conservação de massa permanecem apenas na execução privada.

O mínimo de cinco é uma regra de supressão por célula e por snapshot, **não uma garantia formal de anonimato**.
Comparar versões com poucas mudanças pode permitir inferências por diferença. Não há proteção temporal
nem orçamento de privacidade diferencial nesta entrega; esse desenho exige uma decisão de produto separada.

## Sobreposição no cadastro básico

O contorno do CAR pode receber apenas o booleano `sobreposto`, calculado pela mesma interseção espacial.
É um fato inferível dos limites já públicos, sem hectares ou indicadores pagos associados ao CAR.
O contorno tracejado significa “CAR com sobreposição confirmada”; ele não é o desenho da área sobreposta.
Um sinal ausente não comprova a inexistência de conflito fundiário. Os limites do CAR são declaratórios.

## Verificação

Os testes cobrem deduplicação, registros contraditórios, interseção real versus toque na borda, imóvel sem
medida sobrepondo um contribuinte, fronteira estadual, mínimo de cinco contribuintes positivos, ausência
mantida como desconhecida, conservação da massa disponível e exclusão de identidades/campos pagos na saída.
A auditoria do build também testa a reconstrução do hexágono e a recusa de células repetidas ou inválidas.
