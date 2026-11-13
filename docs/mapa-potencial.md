# Potencial conhecido no mapa

## Pontos nacionais para agrupamento na tela

O build deriva `geo/agregados_brasil.geojson` e sua versão `.gz` exclusivamente das coleções H3 públicas
já aprovadas. As duas representações saem do mesmo JSON sanitizado, anunciado em
`geo/indice.json.agregados`: `arquivo`/`bytes`/`sha256` descrevem o gzip; `normal` contém os mesmos três
campos para o GeoJSON sem compressão; `bytes_total` soma o espaço das duas representações e `metadados`
traz a fonte, a data e as contagens públicas. O build limita o gzip a 560.000 bytes, o JSON normal a
2.500.000 bytes e a soma a 3.060.000 bytes.

`FonteDeDados.geo.agregados()` lê o índice uma vez e, quando o anúncio normal é válido, entrega uma
URL estática da mesma origem ao mapa. Somente o caminho público `geo/agregados_brasil.geojson`, sob a
base configurada, é aceito. Um worker próprio busca e interpreta o arquivo sem credenciais ou
redirecionamentos. Ele mantém o índice Supercluster e devolve somente os grupos do enquadramento ou
o zoom de expansão, sem devolver o GeoJSON à thread principal nem criar uma fonte duplicada no MapLibre.
Os hashes registram os
bytes conferidos no build; não significam verificação criptográfica pelo navegador. O transporte pode
usar compressão HTTP conforme o servidor, sem alterar o arquivo publicado. Índices antigos continuam
usando o gzip e o parser com projeção positiva no navegador, que envia os pontos ao mesmo worker.
Essa compatibilidade antiga ainda envolve o GeoJSON na thread principal. Sem anúncio, a fonte retorna ausência sem
tentar caminhos estaduais ou provocar 404.

Cada ponto tem apenas `h3`, `fazendas` e `potencial_ha`. Sua coordenada é o centro da célula H3,
reconstruído no build, e não a localização de uma fazenda. Cópias idênticas das células de fronteira
entram uma única vez no nacional; valores conflitantes ou execuções misturadas impedem o build.
O agrupamento na tela pode somar esses pontos sem duplicar os CARs contados entre estados.

A contagem significa **fazendas no agregado**, não todas as fazendas do território. Células com menos
de cinco CARs continuam omitidas. Hectares são somente o potencial conhecido, com cobertura parcial;
um grupo deve preservar a contagem de células com valor desconhecido, sem transformar `null` em uma
afirmação de área zero. Os metadados registram essas regras, a fonte/data, o número de células sem
medida e a população representada. Não se publicam totais de hectares suprimidos.

Conferência com a projeção pública das 13 UFs, de 13/11/2026: **215.591 bytes no gzip**,
**1.227.580 bytes no JSON normal** e **1.443.171 bytes somados**, com 6.787 pontos únicos,
dos quais 3.717 têm hectares conhecidos; 1.626.268 fazendas representadas no agregado e
1.572.045,21 ha conhecidos. A conversão conserva as contagens e medidas publicadas, sem nova leitura
de dados privados. Os hexágonos permanecem a unidade interna de agregação; o arquivo nacional
permite mostrar círculos agrupados sem baixar ou desenhar suas geometrias na entrada do site.

O worker usa a mesma implementação Supercluster de `@maplibre/geojson-vt` 6.3.1 utilizada pelo MapLibre,
com os mesmos parâmetros, somas e precisão. As consultas incluem a margem dos botões nas bordas e as
cópias do mundo; respostas e cliques de um índice substituído são descartados. Somente os grupos visíveis ganham
botões HTML ancorados no mapa, com contagem, hectares e nome acessível; a navegação por teclado abre
o mesmo grupo. Os botões existentes são reutilizados e somem quando a fonte falha ou chega o detalhe
de zoom 12. A consulta não depende de uma camada invisível de círculos ou de copiar o índice à interface.
A legenda única começa recolhida e deixa as contagens visíveis também em 360 px.

Os contornos estaduais também podem ser lidos diretamente pelo worker do MapLibre, pelo arquivo
`brasil_estados.geojson` da mesma origem. As cores de cobertura usam filtros por UF e os rótulos usam
27 pontos; atualizar contagens não reenvia os polígonos. A geometria já lida pelo adaptador continua
disponível para enquadramento, e fontes antigas sem URL preservam o envio do objeto GeoJSON.

A preparação gráfica aquece no `OffscreenCanvas` de um worker o mesmo `symbolSDF` usado pelos rótulos
nacionais. O arquivo é gerado a partir do MapLibre 6.15.0, com versão, hash e licença conferidos no build;
o teste do navegador compara os shaders efetivamente usados. Contexto e programa ficam vivos até o
MapLibre assumir, sem transferir handles nem alterar o desenho. O ganho depende do cache do driver.
Falha de compilação mantém o caminho normal; o limite de cinco segundos só destrava uma preparação
sem resposta e é cancelado assim que ela termina. Não há espera fixa, identificação do Lighthouse ou
retirada de rótulos. A fixture do CI também desenha nome e cobertura do Pará e baixa seus glifos.

Um adaptador restrito ao mapa nacional usa o construtor e o cache reais do MapLibre para preparar
clipping, preenchimento, linhas e texto assim que chega uma configuração de bucket, sem aguardar
o bucket de texto. Só aceita pintura uniforme, projeção Mercator e as camadas nacionais conhecidas;
ícones, efeitos, terreno e depuração seguem o renderizador original. A configuração estadual fixa
mantém o SDF idêntico ao aquecido no worker. Em fill/line, a ordem das flags independentes pode variar:
os testes permitem somente essa permutação e exigem todo o restante do GLSL idêntico. Cor, opacidade
e demais valores continuam vindo dos buckets reais em cada desenho. O adaptador não desenha, não
agenda frames e não altera `loaded`/`idle`; restaura a função original ao concluir, recusar ou sair.
O pin obrigatório do fornecedor e os testes das classes reais protegem esse uso de interfaces internas.

O canvas solicita `desynchronized` pela API pública do MapLibre, permitindo ao navegador reduzir a
espera pela apresentação. É uma sugestão: sem suporte, o caminho normal continua válido. Máscara e
geometrias permanecem no mesmo canvas; os grupos HTML continuam ancorados pela projeção do mapa.
O ensaio com Chrome 157 preservou os pixels e o alinhamento após aproximar. Isso não garante o mesmo
ganho em outros drivers nem sincronização perfeita entre canvas e HTML durante toda animação.

As consultas de resumo e cobertura reservam espaço enquanto carregam, para não empurrar o painel de
processamento já visível. Seus estados de carregamento são independentes; a cobertura e as 27 linhas
mantêm a identidade quando chegam as respostas, com foco, detalhes abertos e rolagem preservados.
A reserva termina também em vazio ou erro e não altera o painel pronto. As três faces usadas na
entrada são antecipadas por `preload`, com os mesmos arquivos de fonte e reutilização pelo CSS.

## Fonte e cálculo do H3

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
Na escala até zoom 11, grupos de pontos substituem os detalhes; nenhuma hachura de restauração é inventada.

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
O contrato conserva a escala da visualização H3 anterior (0, 100, 1.000, 10.000 e 50.000 hectares).
Na entrada atual, os grupos usam uma cor e escrevem o número de hectares, sem pintar cada célula.

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
