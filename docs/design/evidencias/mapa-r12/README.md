# Mapa: grupos nacionais e detalhe real

**O desempenho com dados reais continua reprovado: 78/88/89, mediana 88, abaixo do portão 90.** As seis capturas desta revisão comprovam o percurso funcional; não aprovam o desempenho. A fixture sintética passou com mediana nacional 94 e acessibilidade 100.

O [CI posterior `43485577728`](https://github.com/bernardoemmel/Raiz/actions/runs/43485577728),
head `91e33ce`, terminou com **nove jobs verdes e 3.528 testes Python aprovados**:
**96/96/96 na entrada**, medianas
96/99/98/98/98/100 nas seis rotas, acessibilidade 100 nas 18 amostras e sete axe sem
violações. A categoria para agentes foi 1,00, com CLS 0,001758. São dados da fixture
do CI e não substituem a série real acima. Relatórios e hashes estão no histórico JSON.

Depois dessas capturas, a [regressão de seleção entre municípios](selecao.json) foi
reproduzida no build antigo e corrigida. A ida/volta, nova seleção e saída do mapa
passaram nas duas bases, com zero 404/erros. A [atualização da malha de MT pelo IBGE](../malha-ibge-2025/README.md)
também foi integrada; sua prova e seu crédito são posteriores às seis imagens abaixo.
As capturas conservam seus hashes e a revisão original, sem serem reatribuídas ao novo build.

Capturas reais de Chrome for Testing 157.0.8103.78, em 1440 × 1000 px no desktop e 360 × 800 px no celular, sem retoque. A entrada passa do SVG publicado para o MapLibre com Supercluster. Cada círculo mostra a quantidade de fazendas e os hectares conhecidos do agregado; ao aproximar, os grupos se abrem e dão lugar aos limites reais do CAR.

| Escala | Antes | Depois |
|---|---|---|
| Brasil | [SVG do site publicado](brasil-antes.png) | [Grupos no MapLibre](brasil-depois.png) |
| Pará | [Referência anterior](../mapa/estado-antes.png) | [Grupos estaduais](estado-depois.png) |
| Parauapebas | [Referência anterior](../mapa/municipio-antes.png) | [Município](municipio-depois.png) |
| Fazenda selecionada | [Referência anterior](../mapa/fazenda-antes.png) | [Satélite e contorno sem preenchimento](fazenda-depois.png) |
| Brasil a 360 px | — | [Entrada móvel](brasil-360-depois.png) |
| Processamento | — | [Ausência de telemetria no snapshot](processamento-depois.png) |

O “antes” nacional foi capturado em `https://bernardoemmel.github.io/Raiz/`, em **12/11/2026 às 23:14:31, horário de Brasília**, com zero erros de rede ou JavaScript. Esse PNG permanece intacto. Os seis “depois” foram capturados em **13/11/2026 entre 15:36:54 e 15:37:00, horário de Brasília**, com o frontend e runtime `7fe3539`: fichas da rodada 12, painel de processamento, Supercluster em worker próprio, estabilidade do painel durante a carga e preload das três fontes da entrada nacional. Os horários ISO em UTC e hashes estão em [snapshot.json](snapshot.json).

O Supercluster usa um worker próprio, com a mesma implementação, parâmetros e somas da versão usada pelo MapLibre; só os grupos visíveis recebem botões HTML, com contagem, hectares, toque e teclado. A fonte invisível duplicada foi retirada do MapLibre. O roteiro observa os grupos retornados e os botões reais, sem alterar os dados. A [entrada em 360 px](brasil-360-depois.png) usa contexto novo e enquadramento próprio, com uma legenda recolhível. O SVG permanece apenas no minimapa da barra lateral.

As demais imagens “antes” pertencem à [etapa histórica do mapa](../mapa/README.md), com suas próprias fontes e datas. O detalhe anterior e o atual mostram a mesma escala, mas não a mesma fazenda. Os hexágonos daquela etapa não são a visualização nacional desta rodada.

## Dados e limites

As seis imagens novas compartilham o snapshot público cujo índice cartográfico foi gerado em **12/11/2026 às 20:54:43, horário de Brasília**, com dados publicados às **20:46:50**: **444 municípios e 13 estados**. O índice, os agregados normal e gzip, o manifesto dos estados e a projeção de processamento foram conferidos byte a byte contra a fonte congelada. O exportador histórico do agregado é `6bc77c1`; essa referência não é a versão atual do painel.

A entrada nacional usa **6.787 pontos públicos**, deduplicados globalmente, em **1.227.580 bytes no GeoJSON normal**, lido diretamente pelo worker próprio. O fallback de publicações anteriores ocupa **215.591 bytes comprimidos**. São centros das células H3 já agregadas, nunca a localização individual de uma fazenda. O Supercluster soma contagens e hectares conhecidos, sem criar um segundo índice na interface.

O conjunto agrega **1.626.268 CARs** nas células publicadas; esse número não representa cobertura completa do território. As **3.717 células com medida** somam apenas áreas conhecidas, positivas e sem sobreposição detectada, com ao menos cinco contribuintes. Células suprimidas não entram nessa contagem. Grupos sem medida dizem “Sem medida”; a parcela desconhecida não vira zero. Os centros são uma alocação estatística e não desenham áreas de restauração.

O painel distingue a cobertura cartográfica deste snapshot do resumo de aptidão de **365 municípios em 9 estados**, cuja data própria não veio no pacote. A contagem do mapa não transforma esse resumo parcial em completo. O período do snapshot permanece congelado para a comparação, mesmo quando a publicação diária contém dados mais novos.

O snapshot não contém observações de execução. O build consulta uma projeção local em `amostra/processamento.json`: **27 UFs sem telemetria**, com contagens e datas de observação, mudança e validade nulas. A captura e o DOM confirmam 27 avisos “Sem informação de processamento” e 81 contagens “Não informado”. O `gerado_em` de **13/11/2026 às 01:49:46, horário de Brasília**, é a criação dessa projeção, não a data de uma observação. Nenhuma consulta ao RAW vivo foi feita; os 444 municípios do mapa não foram convertidos em municípios prontos nesse painel.

## Verificação

O roteiro abriu Brasil e Pará, buscou Parauapebas e clicou no interior renderizado de uma fazenda pública sem sobreposição detectada. A seleção enquadrou o CAR efetivamente escolhido no zoom **14,32**. Foram **103 requisições no desktop e 50 na entrada móvel**, todas respondidas com **HTTP 200 ou 206**: zero 404, erros de JavaScript/console ou falhas de rede. Não houve cancelamento de requisição nessa captura. **Nove imagens reais de satélite** responderam HTTP 200.

Não houve interceptação de rede nem consulta a endpoints pagos ou exportações de pasta. Os PNGs não mostram nome, CPF ou contato de proprietário. O roteiro também conferiu o processamento local, a ausência de consulta ao RAW vivo e a posição das camadas do fundo e do satélite abaixo dos contornos e da máscara.

O detalhe conserva contornos de 1 px sem preenchimento, tracejado nos limites com sobreposição detectada e máscara fora do imóvel selecionado. A imagem pública é o mosaico **Sentinel-2 cloudless 2016/2017 da EOX**, histórico, sob **CC BY 4.0**; ano e atribuição aparecem na captura. Ela não descreve a situação atual da terra.

Nenhuma hachura de restauração foi criada a partir do CAR. A fonte autorizada está vazia no mapa aberto; a ficha paga consulta a geometria real pela API quando disponível. A carga desse recorte no mapa geral continua pendente, portanto estas capturas não demonstram essa integração.

O Playwright Pages passou com a revisão `7fe3539` nos dois caminhos, `/` e `/Raiz/`, com zero 404 e zero erro no navegador. A conferência de fontes confirmou uma transferência por arquivo antecipado, usando os mesmos arquivos do CSS. O roteiro confere grupos com medida ausente, soma e rótulos, abertura por Enter com foco preservado, reutilização do botão, transição para município e remoção dos marcadores no detalhe. Também verifica fallback gzip, alerta e ausência de marcadores quando o GeoJSON falha. As **sete verificações axe** da fixture terminaram sem violações WCAG 2.1 AA em 360 px, com teclado e gaveta móvel.

## Desempenho

A série fixa de três execuções Lighthouse mobile da revisão **`7fe3539`** com estes dados reais obteve **78, 88 e 89 em desempenho (mediana 88, REPROVADO)** e **100 em acessibilidade nas três**. LCP: **0,755 / 1,666 / 0,754 s**; TBT: **966,2 / 439,0 / 428,0 ms**; CLS: **zero nas três**. As três amostras estão preservadas, sem descarte ou repetição. O portão continua exigindo mediana de pelo menos 90; os prints e o CLS corrigido não suprem essa reprovação.

A fixture sintética completa passou suas **18 medições fixas**, três por rota: medianas **Brasil 94, entrar 98, novo pedido 98, prospecção 98, acerto 98 e produtor 100**. A série nacional foi **94/92/96**. Acessibilidade foi **100 nas 18 amostras**; sete auditorias axe terminaram sem violações. A fixture inclui nome e cobertura estadual efetivamente desenhados. Ela não substitui a série com dados reais. Ambas permanecem separadas em [lighthouse.json](lighthouse.json), com todas as notas, datas e hashes dos relatórios.

A auditoria oficial para agentes passou localmente na mesma revisão: categoria **`agentic-browsing` 1,00**, com **CLS 0,001758**. Essa categoria avalia o acesso por agentes, não o desempenho mobile. A correção do painel mantém a cobertura, a identidade dos elementos, o foco e a rolagem enquanto os dados chegam. O preload antecipa os três arquivos de fontes da primeira tela, sem duplicar transferências.

A revisão conserva o enquadramento e as camadas. Distribui a inicialização em tarefas cooperativas, mantém o índice de grupos em worker próprio, aquece o shader SDF dos rótulos em worker e prepara as quatro variantes nacionais no cache do renderizador, na thread principal, antes dos desenhos. O contexto WebGL solicita `desynchronized` pela API pública; a aceitação depende do navegador. A abertura também evita cálculos de datas enquanto não há calendário carregado. Não houve temporizador artificial, identificação do Lighthouse, troca de dados, redução do portão ou troca de motor de mapa.

As séries abaixo pertencem a revisões anteriores. Os resultados reprovados foram preservados e não são atribuídos ao candidato final:

| Revisão / ambiente | Nacional: três amostras | Mediana | Resultado daquele conjunto |
|---|---|---|---|
| CI inicial `43362021791`, fixture | 82 / 86 / 72 | 82 | Reprovado |
| `d00ea94`, fixture no CI `43369596942` | 91 / 92 / 78 | 91 | Aprovado; nove jobs verdes naquela revisão |
| `b35b490`, fixture no CI `43431157242` | 81 / 85 / 85 | 85 | Reprovado |
| `acb140c`, snapshot real, dimensionamento isolado | 86 / 86 / 92 | 86 | Reprovado |
| `650db81`, snapshot real, estilo inicial em lote | 82 / 90 / 90 | 90 | Aprovado localmente naquela revisão |
| `dee13fe`, fixture no CI `43439869332` | 82 / 87 / 87 | 87 | Reprovado; oito dos nove jobs passaram |
| `7be0b64`, fixture, cooperação e sessão leve | 88 / 89 / 92 | 89 | Reprovado; demais rotas não executadas |
| `d082f43`, snapshot real, worker próprio | 82 / 83 / 91 | 83 | Reprovado; fixture nacional tinha mediana 92 |
| `6e23883`, snapshot real, estados por URL e painel estável | 78 / 80 / 93 | 80 | Reprovado; fixture nacional tinha mediana 95 |
| `4b72f85`, snapshot real, preparação dos rótulos | 78 / 82 / 82 | 82 | Reprovado; fixture nacional tinha mediana 92 |
| `b52be9b`, fixture, preparação dos programas nacionais | 81 / 84 / 95 | 84 | Reprovado; demais rotas e série real não executadas |
| `c1d42a4`, snapshot real, preparação gráfica e desynchronized | 84 / 91 / 95 | 91 | Aprovado localmente naquela revisão; fixture nacional 89/95/92, mediana 92 |
| `e3b7f09`, snapshot real, estabilidade do painel | 83 / 87 / 95 | 87 | Reprovado; fixture nacional 94/94/95, mediana 94 |

Acessibilidade foi 100 nas amostras dessa tabela. O JSON conserva também as séries locais mais antigas, as 18 medições das fixtures completas e a proveniência da revisão `650db81`, medida antes de seu commit. Cada mudança foi medida separadamente; não houve nova execução do mesmo candidato para selecionar uma nota melhor.

O CI remoto de `03eccd8`, execução [43473084402](https://github.com/bernardoemmel/Raiz/actions/runs/43473084402), terminou com sete jobs verdes e dois reprovados. A auditoria para agentes mediu CLS **0,134395**, acima de 0,1; a categoria **0,93 não é uma nota de desempenho**. A etapa Lighthouse mobile ficou **skipped**, sem notas. O Gitleaks confundiu dois SHA256 destes metadados com tokens; a correção `437f08a` restringiu as exceções aos dois fingerprints históricos e as chaves correntes passaram a usar `relatorio_real_sha256` e `relatorio_fixture_sha256`, mantendo os valores. O CLS foi corrigido em `56ab91d` e conferido localmente nas revisões seguintes. Os **3.528 testes Python passaram**, com um deselecionado e um xfailed, zero skipped; a referência estadual do Pará passou em job separado. Esses resultados permanecem no histórico e não são atribuídos ao novo candidato.

As seis capturas desta revisão usam o mesmo build da série real `7fe3539`. Foram conferidos os hashes de **21 fontes, 64 artefatos compilados e seis arquivos de dados**; os relatórios brutos não foram alterados. As imagens nacional, móvel, de processamento, do Pará e do detalhe são byte a byte iguais às da captura `c1d42a4`; Parauapebas foi recapturada com pequenas diferenças de renderização. As seis têm horários novos e hashes próprios registrados. O PNG “antes” continua intacto, e os metadados e arquivos das capturas anteriores continuam recuperáveis no histórico Git.

As imagens e medições correspondem ao **build local com snapshot congelado**, não à publicação diária mais recente. O CI remoto e a inspeção do site publicado continuam verificações separadas. A ausência de telemetria de processamento é real neste snapshot e não foi preenchida com atividade simulada.
