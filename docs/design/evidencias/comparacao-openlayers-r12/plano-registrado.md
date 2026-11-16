# Plano prévio: MapLibre e OpenLayers

Estado: aprovado pelo agente coordenador em 13/11/2026, com ajustes registrados abaixo antes de medir. Nenhuma alteração do produto autorizada nesta etapa.

## Escopo e dados

- Comparar somente os renderizadores em um mesmo laboratório independente, sem React/painéis; não atribuir ao OpenLayers o custo removido da aplicação. A comparação não será Lighthouse e não substituirá nenhum gate do produto.
- MapLibre 6.15.0 instalado no HEAD 7fe3539, incluindo seu patch existente e otimizações públicas aplicáveis, como desynchronized=true. OpenLayers 10.11.0 fixado, licença declarada BSD-2-Clause; conferir LICENSE do pacote e todas as dependências instaladas antes de executar. Ferramentas locais em /tmp, nunca dependências novas no produto.
- Snapshot público congelado /tmp/raiz-fontes-final-real-site. A fonte dos dois imóveis é geo/imoveis_1505536.geojson.gz, SHA256 bf9e2634c586275a54bd2f1ad75c244806f677cae5a29c82b52bf592a2b06c6b. Apenas código CAR, indicador público sobreposto e geometria, sem pessoas ou composição de lotes.
- Seleção prévia: entre geometrias válidas com dimensão máxima entre 0,002 e 0,02 grau, ordenar por tamanho serializado e código e escolher a mediana de complexidade, confirmando interseção positiva com Shapely. Evita escolher formas que favoreçam um motor ou imóvel tão pequeno que precise zoom além de 16.
- Com sobreposição: PA-1505536-D2B09F9982D146B689FB0604539AC352, índice 1780, 212 bytes de geometria, 3 interseções positivas no snapshot (índices 1199, 178, 1581). Sem sobreposição: PA-1505536-7732C1F0A1784452A42A2C3FF72273CA, índice 1012, 212 bytes, nenhuma interseção positiva.
- Mesma coleção nos dois motores e casos: todos os 2.194 CARs da fonte municipal, incluindo todos os vizinhos. Nenhuma simplificação adicional em um motor só. Registrar contagens, vértices e hashes antes do teste.

## Paridade obrigatória antes de medir

- Dois adaptadores em HTML/CSS compartilhado; viewport principal de 360×740 CSS px, área do mapa 360×640, DPR 1; confirmação visual funcional 960×640, projeção EPSG:3857, pitch/bearing 0, extent e resolução idênticos (não igualar numericamente zoom, pois as convenções diferem). Converter por metros/px e conferir 5 pontos de controle com erro <= 1 CSS px.
- Mesmo mosaico EOxCloudless 2016/2017, licença CC BY 4.0 já verificada no produto, crédito e vintage visíveis. Congelar somente tiles necessários localmente com origem, licença e hash registrados; ambos consomem bytes iguais. Satélite cru + véu #FAFAF7 30% iguais no laboratório; a dessaturação/contraste do produto ficam explicitamente fora desse microteste e terão de ser reproduzidos na integração se houver candidata vencedora.
- CARs maiores embaixo, menores por cima, contorno 1 px #15231B com opacidade comum; sobrepostos tracejado [3,3], nenhum preenchimento visível. Hover acende #1D6B44; seleção mantém contorno e aplica máscara mundo com furo #0F1A14 45%. Interior transparente deve ser selecionável. Pendências apenas quando filtro explícito; não inventar bloqueios privados ausentes do snapshot.
- Seleção determinística do menor CAR no ponto quando sobreposto. Confirmar resultado com teste geométrico independente e pontos interior, exterior, cruzamento e borda. Conferir ambos os estados selecionados em prints e cores amostradas; textos/créditos/teclado iguais.
- Paridade sem erro JS/rede e zero 404 é condição obrigatória. Falha não corrigida impede declarar vencedor.

## Desenho experimental fixo

- Chrome for Testing 157.0.8103.78, mesmos flags já usados no projeto: --no-sandbox --disable-dev-shm-usage --use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader. Nenhum Chrome ou build concorrente.
- Sessão nova de navegador por observação, cache HTTP desabilitado, servidor local único. CPU 4× via CDP, latência 150 ms e 1,6 Mbit/s para recursos do laboratório. Esse ambiente usa SwiftShader; resultado não promete desempenho em GPU real.
- Ordem por caso A B B A A B B A (A MapLibre, B OpenLayers): quatro observações por motor, sem descartar outlier e sem repetir para obter nota. Um ensaio funcional de cada adaptador, claramente separado, precede a série e não entra nas métricas.
- Instante inicial: antes do import dinâmico do motor. Medir import, construção, primeiro desenho completo (geometrias + tiles presentes, evento de render completo + próximo RAF; proxy sem prova da apresentação física), requisições e bytes. Relatar também uma marca após import para distinguir distribuição/compilação e renderização.
- Depois da primeira apresentação: mesma sequência controlada de pan em 60 passos, zoom em 60 passos e seleção/limpeza em 20 pontos, usando centros/resoluções compartilhados, um update por RAF. Repetir sequência interna exatamente três vezes. A vista inicial está carregada; o primeiro pan/zoom pode buscar tiles que entram na tela e esse custo permanece integralmente nos resultados. As demais passagens aproveitam apenas o cache interno normal de cada motor. Registrar as requisições de interação, sem excluir a primeira sequência. Medir intervalo de quadros p50/p95, fração > 33,3 ms, tempo JS do update e latência evento→primeiro render que contém o estado. Não confundir evento de câmera com pintura na tela; anotar limite de precisão do RAF.
- Long tasks e CDP Performance metrics separados. JSHeapUsedSize é diagnóstico da main thread e não inclui todos os workers/GPU; não será critério de vitória. Se a medição de memória total confiável não estiver disponível, declarar indisponível.

## Prova nacional adicional

- Usar as mesmas 27 geometrias de UF e os 6.787 agregados públicos. Supercluster da implementação ClusterTileIndex de @maplibre/geojson-vt 6.3.1, ISC, existente no produto, e overlay HTML compartilhado nos dois motores; mesma câmera e código de rótulos.
- Incluir fundo nacional e rótulos em paridade somente se puderem ser reproduzidos sem simplificar um dos motores. Caso essa paridade dependa de uma reescrita extensa de PMTiles/estilo/símbolos, registrar a prova nacional como NÃO CONCLUÍDA. Nesse caso, vencer nos imóveis autoriza apenas uma candidata de integração isolada, nunca substituir o produto.
- Separar import do motor, ingestão dos estados, primeiro desenho e recomputação dos grupos. Não comparar laboratório OL contra app completo MapLibre. Os resultados reais já existentes do app servem apenas de contexto.

## Regra de decisão registrada antes de medir

1. Toda a paridade, seleção correta e rede sem erro deve passar nos dois imóveis.
2. OpenLayers precisa reduzir em pelo menos 20% a mediana de primeira apresentação completa em CADA imóvel e vencer essa métrica em pelo menos 3 das 4 observações emparelhadas pela ordem de ocorrência de cada motor.
3. Não pode regredir interação: em CADA imóvel, p95 de quadros e seleção não deve piorar mais que o maior entre 10% e 4 ms; fração de quadros >33,3 ms não pode aumentar mais de 2 pontos percentuais.
4. Se houver prova nacional completa, exigir melhora de pelo menos 15% na mediana de primeira apresentação e nenhuma regressão acima dos limites anteriores em pan/zoom/grupos. Sem prova nacional completa, resultado se limita a candidato para integração e não a autorização de troca.
5. Somente uma candidata que passe tudo acima pode seguir para uma integração isolada, conservando todos os recursos e os gates reais/fixture e acessibilidade do projeto. Sem isso, manter MapLibre. Nunca declarar que o microbenchmark resolve Lighthouse >=90.

Entregáveis: manifesto/lockfile/licenças, scripts do laboratório, dados públicos mínimos com hashes, todas as observações JSON, comparativos por caso, prints dos dois motores e relatório de limites. Nenhum arquivo grande ou dependência entra no git do produto nesta etapa.

## Ajustes aprovados antes da série

O acabamento real (dessaturação/contraste) e a prova nacional completa são requisitos para uma eventual vitória de produção; se não forem viáveis, o resultado é inconclusivo e MapLibre permanece. A série principal usa 360 px, sem posterior escolha de viewport favorável.

## Revisão estática e ensaio funcional antes da série

- MapLibre preserva feature-state para hover/seleção, desynchronized e aquecimento GPU; o estilo do laboratório foi validado separadamente com style-spec 26.6.0 antes de validateStyle:false. O preparo de programas nacionais não é aplicável ao estilo dos imóveis.
- Cada render registra a câmera efetivamente desenhada, além dos RAFs do controlador. Comandos não confirmados e no-op permanecem identificáveis. Seleção espera a fonte atualizada e idle/rendercomplete + RAF; isso é proxy de oportunidade de apresentação, não uma medição física do compositor/GPU.
- O tracejado do Canvas replica a escala física observada no MapLibre: 3 × 2^fração(zoomML) px para cada traço e intervalo. A textura do MapLibre usa transform.tileZoom inteiro. A amostragem do segmento real encontrou períodos de 10,44/10,69 px a360 e8,27/8,27 px a960, com diferenças de antialias/quantização registradas.
- net::ERR_ABORTED somente em URLs de tiles locais existentes, por image/fetch, é registrado em cancelamentos esperados da câmera; qualquer outro requestfailed, HTTP>=400, erro de fonte ou JS reprova. As tentativas de ensaio que revelaram essa diferença do coletor foram preservadas e não entram nas métricas.
- As oito confirmações funcionais finais (dois imóveis × dois motores ×360/960) passaram projeção, hit-test, máscara, hover e Enter/Escape. Quatro delas também percorreram todas as interações. O maior erro entre pontos de controle foi<4e-9 px. A série medida ainda não havia iniciado ao registrar esta revisão.

## Nova série tecnicamente corrigida, registrada antes de medir

A série original de 16 observações permanece em /tmp/raiz-comparacao-openlayers e é exploratória: o Vite isolado omitiu maplibreCeuTransparente(), um plugin do build do produto. A referência à preservação desse patch no plano original estava errada.

Nesta nova série, /tmp/raiz-comparacao-openlayers-corrigida, muda somente a aplicação do mesmo plugin do produto ao MapLibre. Nenhuma amostra anterior será substituída. Mantêm-se dados, cores, câmera, sequências, 360 px, Chrome 157, flags, rede/CPU, ordem ABBAABBA por imóvel, quatro observações por motor e todos os critérios numéricos. Não haverá alteração de gate nem repetição para escolher nota.

Antes de medir: validar pin de versão e hash do módulo original; comparar transformação exata com o plugin; conferir a guarda do céu transparente no bundle/sourcemap e a fonte do shader; conferir os hashes dos auxiliares de GPU contra 7fe3539; ensaio funcional de paridade necessário. Se um caso reprovar, manter MapLibre e não ampliar para o nacional.

A série aguarda liberação explícita de CPU/Chrome do coordenador.
