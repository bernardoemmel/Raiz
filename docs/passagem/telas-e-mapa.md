# Passagem do chat "Telas e mapa" (12/11/2026)

Sessão: https://claude.ai/code/session_01VGb88MJumyG9PHt2znaaKE. Branch: `claude/upbeat-goodall-iwsrai`.

## Redesenho cartográfico e rodada 12: PR #90 (13/11/2026 UTC)

- **MapLibre mantido após a comparação corrigida com OpenLayers**. Nos dois imóveis reais, a
  abertura do laboratório OL foi 41,28%/42,63% mais rápida, mas o imóvel com sobreposição reprovou
  a interação: p95 de quadros 82,08 ms contra 20,12 ms e seleção 58,98 ms contra 34,81 ms.
  A regra exigia os dois casos sem essa regressão, portanto não houve troca nem expansão para a
  prova nacional. São proxies de render/RAF em Chrome 157/SwiftShader, não uma nota Lighthouse.
  As 16 observações corrigidas foram preservadas; 12 terminaram antes do reinício do ambiente e
  as quatro restantes completaram a ordem prevista, sem refazer as anteriores. O caso com
  sobreposição inteiro antecede a interrupção. A primeira série, sem o plugin de céu transparente
  do produto, fica explicitamente exploratória. A corrigida verifica os bytes do plugin, shader
  e bundles, além de oito ensaios de paridade. O acabamento completo e a cena nacional não foram
  avaliados; o resultado não autoriza migração. [Plano, amostras e prints](../design/evidencias/comparacao-openlayers-r12/README.md).
- A revisão remota **`91e33ce` terminou com os nove jobs verdes** no
  [CI `43485577728`](https://github.com/bernardoemmel/Raiz/actions/runs/43485577728): entrada nacional
  **96/96/96**, seis medianas **96/99/98/98/98/100**, acessibilidade 100 nas 18 amostras e sete axe
  sem violações. A auditoria para agentes foi **1,00**, com CLS **0,001758130519118656**.
  **3.528 testes Python passaram**, com um deselecionado, um xfailed e nenhum skip; a referência do Pará
  passou separadamente. As medições da fixture são distintas do snapshot real local reprovado abaixo.
  A composição seguinte exige seu próprio CI e auditoria da publicação, registrados no PR. Nenhum run foi cancelado.
- **`75d733c` corrige seleção entre municípios**: popup, hover, seleção e máscara são encerrados
  antes da troca das geometrias e no teardown, inclusive quando fontes já foram removidas. O destaque
  da tabela também é limpo. O teste novo reproduziu o defeito no build anterior: popup e seleção
  antigos permaneciam, sem máscara. A correção passou em 588 testes, TSC/lint, builds e Pages em
  `/` e `/Raiz/`, com reseleção, teclado, zero 404/erros e axe 360 sem violações. `c2e6677` faz o
  roteiro esperar o enquadramento real antes de reprojetar o clique, sem atraso fixo.
- **`bdfe2bb` corrige a publicação diária bloqueada pela malha antiga**. O run `43478574515` tinha
  406 desenhos de Boa Esperança do Norte no Release, mas faltava seu código `5101837` na malha
  TerraBrasilis de 5.570 municípios. O exportador agora identifica a UF com códigos ausentes e
  substitui sua divisão inteira pela edição oficial mais recente do IBGE, incluindo os municípios
  de origem. Não há lista fixa nem exceção para esse código. A prova com MT/2025 passou para **5.571
  municípios únicos**, MT com 142, sem sobrepor o município novo a Sorriso/Nova Ubiratã e mantendo
  as outras UFs idênticas. ZIPs, hashes, CARs e bases são preservados; retomada funciona sem rede.
  O índice público ganha apenas `malhas`, contrato fechado por UF de fonte/ano/hash; fonte, edição
  e generalização aparecem em `fontes.md`, sem atribuir 2025 a todo o país. A licença da edição foi
  conferida na nota oficial, página 9: CC BY 4.0, inclusive comercial. Passaram 27 testes Python,
  37 de front focados, TypeScript e Ruff. [Prova e fontes](../design/evidencias/malha-ibge-2025/README.md).
  A composição com a seleção passou em **601 testes do front**, TSC, builds do painel/produtor,
  verificador de design, lint e Pages `/Raiz/`: 199 pedidos, zero 404/erros e axe 360 sem violações.
  Ruff passou no escopo completo do CI, com 637 arquivos formatados. Não houve Lighthouse adicional
  para essas mudanças de interação/proveniência; o próximo CI e a publicação real são verificações próprias.
- Referência funcional e de desempenho **`7fe3539`**, com 588 testes do front, TypeScript, lint, builds e Pages
  em **`/` e `/Raiz/`**, incluindo busca, overzoom, privacidade e zero 404/erros. A auditoria oficial
  do site para agentes passou com nota 100 e **CLS 0,001758**. A série móvel de 18 medições passou
  na fixture: medianas **94/98/98/98/98/100**, acessibilidade 100 e sete auditorias axe sem violações;
  a entrada marcou **94/92/96**. Porém o snapshot real marcou **78/88/89, mediana 88**, acessibilidade
  100 e CLS zero: **desempenho real reprovado**, sem descarte ou repetição para escolher nota.
  As capturas desta revisão documentam o funcionamento; não representam aprovação desse desempenho.
- O [CI `43473084402`](https://github.com/bernardoemmel/Raiz/actions/runs/43473084402), head `03eccd8`,
  terminou com sete jobs verdes: **3.528 testes Python**, 1 deselected, 1 xfailed, nenhum skip, e a
  referência do Pará aprovada separadamente. Falharam Gitleaks e o CLS desktop do site para agentes.
  A etapa Lighthouse móvel foi pulada após o CLS; não há nota móvel remota desta execução.
  Gitleaks confundiu dois SHA-256 de relatórios com tokens; os hashes foram recalculados e a correção
  `437f08a` admite somente as duas linhas do commit histórico. A varredura redigida passou por 620
  commits sem achados. Os metadados futuros usam nomes `relatorio_*_sha256`, preservando os valores.
- O CLS foi corrigido em `56ab91d`: resumo e cobertura reservam espaço durante suas consultas
  independentes, preservando a posição e a identidade do painel de processamento. Resumo tardio
  reduziu CLS de **0,112004 para 0,001828**; cobertura e andamento deslocaram cerca de 23 px, e apenas
  3 px com cobertura tardia. Foco, detalhes abertos, 27 linhas e rolagem permanecem estáveis. A reserva
  termina em sucesso, vazio ou erro; o painel pronto permanece visualmente igual. O teste oficial
  agora conserva Trace e DevtoolsLog também quando reprova.
- `7fe3539` antecipa as três fontes já usadas na entrada: Familjen 600 e Atkinson 400/700. O ensaio
  A/B/B/A antecipou sua descoberta de 103–131 ms para 14–17 ms e reduziu trabalho de layout, com
  mesmos bytes, uma transferência por fonte e pixels iguais. FCP e tempo total se sobrepõem entre
  amostras; não atribuir ganho total garantido ao preload. Vite resolve os caminhos nas duas bases.
  MapLibre permanece no produto. A comparação com OpenLayers foi iniciada separadamente conforme a
  condição do fundador: imóveis reais com e sem sobreposição, paridade visual e prova nacional antes
  de qualquer troca. Uma comparação incompleta não autoriza substituir o motor.
- A correção de CLS também passou em `e3b7f09` na fixture (**94/94/95**, mediana 94; seis rotas
  **94/98/97/97/98/100**), mas reprovou no snapshot real em **83/87/95, mediana 87**. Acessibilidade
  100 em todas. Os perfis variam entre pintura, importação e intervalos nativos sem CPU; não comprovam
  uma regressão das reservas CSS. Todas as séries e os limites de atribuição foram preservados.
- Entrega registrada no [PR #90](https://github.com/bernardoemmel/Raiz/pull/90), com implementação,
  evidências e resultados locais descritos abaixo. O resultado remoto do CI, merge e auditoria da
  publicação é registrado no próprio PR. A main `e959023` (PR #105) está integrada em `9a37e3b`:
  retomadas/cotas preservadas e leitores públicos aceitando as subdivisões de até quatro dígitos.
  O único conflito foi o pin do `uv`; a revisão `110773f` alinha os cinco jobs à versão 0.13.6
  compartilhada pela main e exigida pelo teste de retomadas, sem consultar `latest`. O CI
  [`43439869332`](https://github.com/bernardoemmel/Raiz/actions/runs/43439869332), head `dee13fe`,
  passou em oito dos nove jobs, incluindo 3.474 testes Python gerais, referência original do Pará,
  segurança e cenários reais de API/agentes. O front passou nos fluxos funcionais, mas reprovou
  Lighthouse nacional: **82/87/87, mediana 87**, acessibilidade 100 nas três amostras.
  Esse CI não autoriza o merge. Nenhum workflow foi cancelado ou desativado.
- A integração encontrou uma regressão na prioridade da fila: catálogo e lotes eram tratados como UFs
  fora da frente, tinham sua referência substituída e consumiam o limite de três estados. A correção
  `4785ac7` restringe essas regras às 27 UFs oficiais, preserva referências/bloqueios auxiliares e continua
  contando todas as reservas no teto global de 15. Passaram **280 testes focados**, incluindo dez
  regressões novas, HTTP, hashes/Release concorrente, checkpoint, H3, status e pins, além de Ruff.
  Nenhum run, reserva viva ou dado publicado foi alterado durante a validação. As atualizações automáticas
  da main até `1b4a896` também foram integradas; alteram somente o painel em `motor/README.md`.
- Validação local histórica do código **`c1d42a4` aprovada**: 587 testes do front, TypeScript, lint,
  build e Pages com zero 404/erros. As 18 medições fixas da fixture deram medianas
  **92/98/97/98/97/100**, acessibilidade 100, e sete auditorias axe/teclado sem violações a 360 px.
  A entrada marcou **89/95/92**; o snapshot real de 444 municípios/13 UFs marcou **84/91/95,
  mediana 91**, acessibilidade 100. Todas as amostras foram mantidas, sem repetição para escolher nota.
  A dispersão permanece: a aprovação é pela mediana de três, não significa 90 em toda abertura.
  A imagem nacional não mudou. Ruff passou no escopo do CI, com 637 arquivos formatados; a fila
  alterada também passou no lint. Os nove jobs do CI completo são obrigatórios para o merge;
  a auditoria do artefato e do site publicado conclui a entrega, com evidências no PR.
  O candidato solicita `desynchronized` pela API pública do MapLibre e evita
  calcular a data do calendário nacional sem agenda carregada. No ensaio A/B/B/A, tarefas nativas de
  apresentação de 80/119 ms passaram para 74/57 ms, ainda com espera residual; imagens nacionais e
  após zoom permaneceram idênticas, com o mesmo alinhamento dos grupos e zero erros. A sugestão pode
  ser ignorada pelo navegador; esse ensaio não substitui Lighthouse nem comprova todos os drivers.
  A revisão estática de compatibilidade e semântica passou. O Pages confere a solicitação e registra o
  atributo efetivo, sem exigir que todo navegador aceite a sugestão.
- A revisão **`b52be9b` passou nos fluxos funcionais, mas reprovou na fixture de desempenho**, com **587 testes do front**, TypeScript, lint e
  revisão independente aprovados. Um adaptador nacional prepara as quatro variantes gráficas no
  cache real assim que há uma configuração de bucket, incluindo o texto antes de seu bucket chegar.
  Mantém o renderizador e os valores atuais dos buckets, sem alterar desenhos, frames ou readiness.
  Guardas recusam estilos desconhecidos, ícones, efeitos e depuração. A versão/hash do fornecedor são
  conferidos no build. Os testes usam as classes reais e verificam GLSL, cache, cor/opacidade e cleanup.
  O ensaio A/B/B/A reduziu os maiores frames de 68,1/42,9 ms para 30/27,2 ms, com zero pixels diferentes
  e zero erros; não é nota Lighthouse. Fill/line variam somente na ordem de flags sem valores e sem
  duplicatas, com todo o restante idêntico. A configuração estadual fixa preserva os bytes exatos do
  SDF aquecido. Build e Pages passaram, incluindo busca, overzoom, ordem dos programas e zero 404/erros.
  A série nacional marcou **81/84/95, mediana 84**, acessibilidade 100 e sete auditorias axe sem violações.
  O gate parou nessa rota; as outras cinco e a série real não foram executadas. Na primeira amostra,
  uma tarefa nativa de apresentação durou 100,1 ms, usando só 2,1 ms de CPU; na segunda, o trabalho de
  React/importação pesou com CPU menos favorável. O perfil não identifica um comando gráfico específico
  como causa. Todas as amostras estão preservadas; não atribuir a falha novamente ao link do símbolo.
  Capturas finais, CI completo e merge continuam pendentes.
- A composição **`4b72f85` passou nos testes funcionais, mas reprovou no desempenho real**, com
  559 testes do front aprovados e Pages em `/Raiz/` e `/` sem 404/erros. A fixture reforçada passou
  nas 18 medições: medianas **92/98/97/98/98/100**, nacional **92/88/94**, acessibilidade 100;
  sete auditorias axe sem violações. O snapshot real marcou **78/82/82, mediana 82**, acessibilidade
  100, com todas as amostras preservadas. A preparação gráfica
  aquece o `symbolSDF` exato em um worker, antes do MapLibre assumir o contexto. Geração, versão, hashes
  e licença passam pelo build; o Pages verifica os shaders reais. A fixture agora contém o rótulo e
  a cobertura do Pará, exercitando o caminho de glifos que faltava nas medições anteriores.
  O experimento fixo A/B/B/A na página real reduziu a consulta síncrona do símbolo de 70,3/75 ms
  para 34,4/7,4 ms, com zero pixels diferentes e zero erros. Isso não substitui o Lighthouse:
  é evidência causal para a correção, cujo benefício depende do driver. A extensão KHR paralela foi
  descartada antes de implementar, pois não existe no Chrome/SwiftShader usado no CI.
  Os três perfis reais ainda mostram longas esperas gráficas; a redução do símbolo não significa
  eliminar a espera total. Capturas finais e merge permanecem pendentes.
- A revisão **`6e23883` passou nos testes funcionais, mas reprovou no desempenho real**.
  Foram 546 testes do front, Pages em `/Raiz/` e `/` com zero 404/erros e sete auditorias axe sem
  violações. As 18 medições da fixture passaram: medianas **95/98/97/97/98/100**, nacional
  **95/93/95**, acessibilidade 100. No snapshot real a série foi **78/80/93, mediana 80**,
  acessibilidade 100; todas as amostras permanecem preservadas. A imagem nacional permaneceu idêntica.
  O perfil distingue espera gráfica de trabalho JavaScript: a maior tarefa da primeira medição real
  teve 137 ms de parede e apenas 2,24 ms de CPU da thread. Uma instrumentação independente encontrou
  45,3 ms na consulta síncrona de link do programa de rótulos; esse valor não é uma atribuição direta
  dos 137 ms. Está em avaliação compilar esses programas sem bloquear a interface.
- O índice Supercluster agora fica em worker próprio,
  com a mesma implementação, parâmetros e somas do MapLibre; só os grupos visíveis voltam à interface.
  Retirada a fonte invisível duplicada. Os contornos estaduais são lidos por URL pelo worker do mapa,
  sem serializar novamente toda a geometria na thread principal; fontes antigas mantêm o fallback.
  As tarefas de abertura cedem a execução entre etapas, o estilo interno é validado obrigatoriamente
  no build e a sessão leve deixa a fábrica de pedidos fora da entrada nacional (menos 32.324 bytes
  no grafo estático, 12.995 bytes gzip). Não há espera artificial ou identificação de auditoria.
- O resumo municipal preserva agora a identidade do painel de processamento: a regressão confirmou
  as mesmas 27 linhas, links, foco de teclado e detalhe aberto após a chegada dos dados. Expiração
  e atualização da telemetria continuam funcionando. A revisão anterior desmontava esse painel.
- Séries intermediárias preservadas: divisão das tarefas + sessão leve reprovou a fixture em
  **88/89/92, mediana 89**; worker próprio passou na fixture (**90/92/95**, mediana 92;
  seis rotas **92/98/97/97/95/100**), mas reprovou no snapshot real em **82/83/91, mediana 83**.
  Acessibilidade 100 em todas essas amostras. Não houve repetição de código inalterado para escolher nota.
  A revisão com URL dos estados e preservação do painel foi medida separadamente, com resultado acima.
- Histórico da revisão cartográfica **`650db81`**, após investigar os perfis do CI: o enquadramento passou para
  `fitBounds` imediatamente após criar o mapa, eliminando um redimensionamento redundante, e as fontes/
  camadas nacionais passaram a compor um único estilo inicial. Dados, camadas, ordem, centro e zoom
  foram preservados; comparação de 360 px sem pixels diferentes. O Pages passou com zero 404/erros,
  e os 508 testes unitários do front passaram nessa composição.
  A bateria local dessa revisão, em Chrome 157, passou nas seis rotas: medianas **90/98/97/96/97/100**,
  acessibilidade **100 nas 18 amostras**, sete verificações axe/teclado sem violações. A entrada da fixture
  marcou **88/90/94**; o snapshot real de 444 municípios/13 UFs marcou **82/90/90 (mediana 90)**,
  acessibilidade 100 nas três. Todas as amostras foram mantidas. Há dispersão e pouca folga; não há
  garantia de 90 em toda abertura. As capturas e relatórios daquela etapa identificam a revisão e o snapshot.
  A nova execução do CI e a conferência da publicação continuam obrigatórias antes de fechar a entrega.
- O CI `43431157242`, anterior a essas duas correções, também reprovou o front com **81/85/85**.
  A comparação com o CI verde de `d00ea94` encontrou os mesmos assets, dados, Chrome 157 e simulação,
  mas CPU do runner menos favorável. Os perfis orientaram mudanças concretas; a execução não foi
  repetida para selecionar notas. O resize isolado passou na fixture, mas reprovou o snapshot real
  em **86/86/92**; por isso não encerrou a revisão. O estilo único reduz validações e mensagens, embora
  parte do trabalho mude de fase: os perfis não atribuem toda a melhora ao patch. A série final válida
  dessa etapa foi a de `650db81` acima, e não a melhor nota dos experimentos anteriores.
- O [CI `43369596942`](https://github.com/bernardoemmel/Raiz/actions/runs/43369596942), head `d00ea94`,
  concluiu os nove jobs com sucesso: 3.075 testes Python gerais e a referência original do Pará em job
  separado; 508 testes do front, API/MCP real, segurança, licenças e navegação aprovados. Lighthouse
  mobile no CI: medianas **91/98/97/96/97/100**, acessibilidade **100 nas 18 amostras**. As verificações
  de Pages e domínio na raiz passaram com zero 404. Antes do merge, a main avançou para `6b9c377`
  (PR #100); a integração dessa revisão preserva o front e requer seu próprio CI completo.
- A entrada usa MapLibre com países, oceano e estados: verde-claro com municípios lidos/esperados;
  cinza e “ainda não processado” onde faltam dados. O SVG grande foi retirado e o pequeno minimapa permanece.
  O fundo chega primeiro; polígonos e base municipal só são carregados quando necessários. Municípios novos
  são a diferença em relação ao último índice realmente publicado, nunca uma contagem inventada na sessão.
- A rodada 12 substitui a exibição dos hexágonos por pontos agrupados com Supercluster (ISC), em worker
  próprio usando a mesma implementação do MapLibre. Cada grupo informa quantidade de fazendas e hectares conhecidos; quantidade de células
  não vira quantidade de fazendas, e medidas ausentes não viram zero. A lista equivalente funciona pelo
  teclado. As molduras municipais aparecem ao aproximar. A partir de zoom 12, fazendas sem preenchimento,
  contorno de 1 px, hover, máscara ao selecionar e ficha breve. Pendência em
  urucum depende do filtro; “não apto” tem contorno cinza discreto. CARs maiores ficam abaixo dos menores.
  O tracejado identifica um CAR com interseção confirmada, não o perímetro exato da área sobreposta.
- Potencial é a medida conhecida `carbono_ha`, sem misturar métricas ou deduzir desenho restaurável.
  O projetor autenticado confere hashes/proveniência dos pares CSV/GeoParquet, deduplica CARs, verifica
  interseções reais e soma apenas contribuintes não sobrepostos. Cada célula numérica exige cinco
  contribuintes positivos; ausências não viram zero. H3 permanece como unidade interna de agregação,
  sem expor CAR ou atributos individuais; o índice nacional usa somente o centro e medidas dessas células.
- Snapshot verificado: 13 UFs, 6.787 células distintas, 3.717 com valor, 147.762 contribuintes e
  1.572.045,21 hectares conhecidos, com cobertura parcial. H3 comprimido: 560.434 bytes. Os 444 arquivos
  públicos mantêm 912.853 contornos e recebem somente o booleano de sobreposição, sem medidas pagas.
  Fontes publicadas entre `2026-11-12T19:27:40Z` e `2026-11-13T00:35:56Z`; detalhes em `docs/mapa-potencial.md`.
  A projeção nacional tem 6.787 pontos e 215.591 bytes comprimidos, com a mesma soma conhecida.
- Medição do projetor sobre uma rodada posterior real: 13 UFs, 6.949 células, 279,77 segundos e pico de
  memória de 2.835.704 KiB (2,70 GiB). Foram revalidados 20 assets em cache (927 MB) e baixados seis
  (380 MB). Isso mede o processo completo com cache parcial, não uma transferência fria nem um limite
  de memória imposto por contêiner; a execução do publicador no CI ainda deve ser conferida.
- O mosaico aberto usa **Sentinel-2 histórico 2016/2017**, vintage EOxCloudless 2016, CC BY 4.0 com uso
  comercial conferido nas páginas oficiais. O ano e o crédito completo ficam visíveis. Não usar os anos
  recentes da EOX com licença não comercial. Documento: `docs/design/satelite-publico.md`.
- Hachura verde exige geometria de restauração medida e autorizada. O mapa geral aberto não baixa essa
  camada paga; a ficha autenticada conserva a leitura pela API. Não desenhar uma fração fictícia do CAR.
- Revisão visual detectou e corrigiu a base detalhada/satélite encobrindo os contornos; o Playwright agora
  verifica também a ordem das camadas. Os grupos visíveis são botões HTML, com índice Supercluster no worker;
  a legenda única recolhida preserva as contagens em 360 px. O build evita compilar céu totalmente transparente
  no MapLibre, com versão/hash conferidos e licença completa distribuída. Não remove dados para a auditoria.
- A série anterior no snapshot real, frontend `1412642`, marcou desempenho **88/98/92 (mediana 92)** e
  acessibilidade **100/100/100**, em 360 px com CPU/rede simuladas. LCP 1,46/1,43/1,49 s; TBT
  431,5/152/319 ms. As três amostras foram preservadas, inclusive a de 88; não houve repetição para escolher
  notas melhores nem alteração do portão. A inicialização gráfica ainda varia entre execuções. Os 399 testes
  do front passaram. Prints nacionais antes/depois, 360 px e detalhe real estão em
  [evidências da rodada 12](../design/evidencias/mapa-r12/README.md). O CI mantém três medições em cada uma
  de seis páginas e precisa ter todos os nove jobs verdes antes do merge, além da conferência da publicação.
- O mesmo gate executado localmente com a fixture completa passou nas seis rotas: Brasil 94, entrada 98,
  novo pedido 97, prospecção 96, acerto 97 e produtor 100, sempre com acessibilidade mínima 100. As sete
  auditorias axe tiveram zero violações, incluindo teclado, gaveta mobile e produtor sem JavaScript.
  Os textos completos de MIT/ISC do agrupamento foram conferidos nos dois sites compilados.
- O primeiro CI completo desta composição (`43362021791`, head `ba541cd`) identificou dois ajustes antes do
  merge: Lighthouse nacional 82/86/72 (mediana 82) num runner mais lento e uma regra antiga que admitia somente
  o XML como artifact Python. Os outros 2.849 testes Python passaram. A regra agora permite exatamente o XML
  e a pasta das capturas sintéticas da ficha pública; o job com referência privada continua limitado ao XML,
  com os mesmos bloqueios de cache/caminho. Seus oito testes passaram. Os três perfis nacionais passam a ser
  guardados pelo CI, sem alterar o cálculo das notas ou repetir medições para selecionar resultados.
- O fundo sólido nacional passa ao CSS, mantendo o raster e os dados no MapLibre; a comparação em 360 px
  encontrou zero pixels diferentes e confirmou a retirada do programa gráfico redundante. O fundo GL normal
  retorna na escala regional. O experimento separado de preparação de stencil não sustentou ganho e foi
  descartado. A composição final com processamento e busca entre UFs tem 504 testes do front aprovados;
  O portão local completo no frontend `f0a7c96` passou nas seis páginas: medianas de desempenho
  **98/98/97/97/97/100**, com acessibilidade 100 nas 18 amostras. As sete verificações axe/teclado
  a 360 px passaram sem violações; o percurso Pages terminou sem 404 ou erros de execução.
  A série fixa no snapshot real marcou **82/95/95 (mediana 95)**, acessibilidade 100 nas três,
  LCP 1,49/1,43/1,43 s e TBT 709/232,5/261 ms. A amostra 82 está preservada: ainda há variação
  na inicialização gráfica. O portão de mediana passou sem repetição ou redução do mínimo;
  os nove jobs do CI e a publicação continuam pendentes para esta revisão.
- A publicação posterior `43358821157` da main parou fechada quando o Release passou a incluir
  `processamento` em GO/MT/RN, antes desconhecido pelo leitor. A correção inicial validou os oito campos
  desse contrato público v1, contagens, UF e cronologia; seus 47 testes e o manifesto real de 22.659 bytes
  e 16 UFs foram conferidos naquela etapa, antes do painel. A integração da main `52118b5` (PR #95)
  agora preserva essa telemetria validada para o painel público, usando `lerProcessamentoPublicado` como
  contrato único. Campos livres e cache inválido continuam interrompendo a leitura, sem ecoar valores.
  A última publicação bem-sucedida até essa conferência é a auditada do PR #89. Nenhum workflow foi cancelado
  ou desativado.
- O painel integrado lista as 27 UFs e distingue execução observada, cobertura do mapa e aptidão. Mantém
  as datas originais da fonte: atualizar o site ou baixar novamente não renova `valido_ate`; observação
  vencida não sustenta a contagem “rodando agora”. Uma unidade/fatia não vira total estadual, e ausência
  não vira zero. O manifesto atualiza ou remove a observação mesmo quando o pacote não mudou.
  O fallback `amostra/processamento.json` sai de projeção positiva; o CI usa essa fixture nos builds
  `/Raiz/` e `/`. A entrada continua em MapLibre com agregados públicos e minimapa pequeno, com cobertura
  acima do andamento. A integração passou em 494 testes do front, 122 testes Python focados, Ruff e
  actionlint. Os builds e o Playwright passaram nos dois caminhos, com 27 UFs, busca, camadas, calendário,
  controles de acesso e zero 404 ou erros no navegador. O painel nacional passou em 360 px com teclado,
  gaveta, 32 regras axe e zero violações WCAG 2.1 A/AA ou largura excedida. A composição final
  `f0a7c96` passou no Lighthouse local descrito acima; os nove jobs do CI continuam pendentes.
- A transferência pública completa encontrou um CAR cadastrado na Paraíba no recorte de Serra Negra do Norte
  (RN). O leitor agora confere separadamente UF/IBGE do CAR e UF/IBGE do recorte, preservando o identificador.
  Os 49 testes do downloader e os 85 CSV do pacote RN passaram. A execução real terminou com 692 CSV básicos
  e 692 GeoParquet, 1.353.246 linhas básicas, 13 UFs com dados entre 16 anunciadas e nenhum campo pago.
  Não faltava geometria municipal; uma geometria extra no PA é excluída pela projeção positiva do site.
  CE/PI tinham um arquivo municipal a mais que o contador do manifesto: a cobertura cartográfica usa os
  arquivos efetivos, sem assumir que esse contador é completo. São dados de validação local, não prova de
  nova publicação. A auditoria territorial registra expressamente a regra de divisa antecipada do PR #99.
- MapLibre foi mantido. OpenLayers só poderá substituí-lo após vencer o teste comparativo pedido, com
  um imóvel sobreposto e outro sem sobreposição; esse teste de troca não foi realizado. Não foi usado bpmn-js.
- E9 continua aguardando as cartas reais. Contato com donos apenas na fase final; nenhuma identidade ou
  contato pessoal foi acrescentado aos mapas.

## O que este chat fez

- Front inteiro do design v1: entrada com o mapa do Brasil por estado, painel, funil, ficha da fazenda, ficha leve do
  produtor (Preact), busca, pedido de lote (cena-alvo). Commits com a linha `Claude-Session` acima:
  `git log --oneline --grep session_01VGb88MJumyG9PHt2znaaKE`.
- PR #18: dados de todos os estados e pedido de lote (merge).
- PR #31: site público no GitHub Pages lendo o Release "dados" e o E9 do plano conferido contra a main (merge).
- PR #33: conserto do YAML do publicar-site (fechado sem merge; o mesmo conserto entrou pelo #36 de outro chat).
- PR #37: medidor de legibilidade (E9 passo 1): `raiz/legibilidade.py`, migração 0019, `raiz legibilidade` (merge).
- PR #40 (merge):
  - cartão WebP pelo Takumi;
  - `raiz ficha lote` (`raiz/fichas_lote.py`);
  - revisor LanguageTool (`raiz/revisor.py`, `infra/languagetool`);
  - capa de satélite com ThumbHash (`raiz/thumbhash.py`, `front/produtor/src/Ficha.tsx`);
  - Plus Code e link do Organic Maps (`raiz/localizacao.py`);
  - lock da ficha do produtor consertado.
- PR #42 (este): CI de todo PR com três jobs, `workflows` (actionlint), `front` (`front/scripts/construir-site.sh`
  sem os dados, mais os testes do front) e `checagens` (Python). O publicar-site usa o mesmo script.
- Site no ar: https://bernardoemmel.github.io/Raiz/ e a ficha do produtor em
  https://bernardoemmel.github.io/Raiz/produtor/?car=<código do CAR>. Publicado pelo merge do #40, conferido no
  navegador: 6 estados, 256 municípios, 638.754 imóveis, sem erro no console.

## Continuação no Codex (12/11/2026)

- PR #42 já integrado em 12/11. A regressão esperada do CI foi desfeita antes do merge.
- PR #47 integrado com os três jobs do CI verdes: correção do mapa público. `baixar-dados.mjs --geo --exigir` baixa tabelas e polígonos do Release
  antes de `geo.py --dados dados/estados`; não há mais lista fixa de dois municípios. O exportador usa só CAR e
  geometria dos GeoParquet, preserva fazendas pequenas e registra município cujo desenho ainda falta.
- Polígonos gzip por município: a medição do Pará deu 35 MB para 144 municípios (Parauapebas: 2.194 polígonos,
  aproximadamente 209 KB). Não precisa de tippecanoe com este volume. As bases PMTiles por UF são compartilhadas;
  `base_brasil.pmtiles` cobre todo o país até z6 e continua por overzoom. O detalhe estadual vai até z10 com overzoom.
- O build copia só arquivos anunciados no índice, limita fichas pré-geradas a 10 mil (municípios inteiros; restante
  montado no navegador) e falha acima de 950 MB. O índice das fichas impede tentativas que geravam 404.
- A busca da fonte estática roda no navegador por nome, IBGE e CAR normalizado; a fonte API conserva `/busca`.
  Município sem contorno mostra aviso. O CI serve o build em `/Raiz/`, sem fallback de SPA, e testa nome/IBGE/CAR,
  aproximação até z13, polígonos verdes/amarelos, base visível por Range e zero 404.
- Segunda entrega: `llms.txt` com menos de 8 KB, `robots.txt` permitindo os agentes atuais, alternates HTML e
  Markdown do Brasil, estados, municípios, produtor, serviço, fontes e privacidade. JSON-LD declara Dataset só de
  UFs disponíveis e Service/Offer com preço sob proposta. API negocia `Accept: text/markdown`, respeita `q=0`,
  prioridade e `Vary`; mantém Bearer e a mesma projeção pública. `/p/{codigo}.md` preserva o aceite.
- O Lighthouse **tem** a categoria experimental `agentic-browsing` desde 13.3.0; a dependência foi fixada em 13.6.0.
  CI verifica HTTP 200 e links sob `/Raiz/`, executa a auditoria oficial e guarda HTML/JSON. WebMCP e ARD não
  implementados são relatados como não aplicáveis, sem simular aprovação.
- Limite real de hospedagem: `/Raiz/robots.txt` não governa a origem. O arquivo deve também existir em
  `https://bernardoemmel.github.io/robots.txt` no site da conta, ou o produto usar domínio próprio. O gatherer do
  Lighthouse procura `/llms.txt` na raiz da origem, então o CI audita uma origem local com o artefato na raiz,
  além de conferir os links reais de `/Raiz/`; não é evidência da descoberta na raiz pública.
- Snapshot real conferido: 365 municípios em 9 UFs, 712.601 desenhos, sem CAR da tabela faltando no GeoParquet.
  Mapas referenciados: 160,34 MB; build completo: aproximadamente 585 MiB, 13.987 arquivos.
- Validação da segunda entrega: 627 testes Python passaram com PostGIS (2 pulados e 1 xfail); 104 testes de front;
  Playwright no Pages e Lighthouse oficial passaram. Relatórios ficam em front/.cache/teste-agentes e nos artefatos do CI.
- E9 posterior: a calibração do portão depende de 30 cartas reais anonimizadas e avaliação de compreensão,
  sem conjunto pronto segundo resposta do fundador em 12/11. Não usar o corte dos testes sintéticos como calibrado.

## Preparação do domínio próprio (entrega 5, 12/11/2026)

- `front/scripts/configurar-publicacao.mjs` centraliza base, URL canônica e hostname. `RAIZ_DOMINIO` vazio mantém
  o Pages derivado de `GITHUB_REPOSITORY`; preenchido usa `/`, HTTPS e `site/CNAME`. Recusa protocolo, caminho,
  porta, IP, hostname inválido e configuração que mandaria os arquivos para um subcaminho do domínio.
- `construir-site.sh` passa a mesma configuração aos dois builds; produtor não usa mais `/Raiz/` como fallback.
  HTML do painel e do produtor anunciam canonical; Markdown, JSON-LD, assets e dados acompanham a base.
- O workflow lê a variável de Actions `RAIZ_DOMINIO`. Nenhum domínio real foi definido. Antes de ligá-la:
  verificar o domínio na conta, apontar DNS, cadastrar em Settings > Pages > Custom domain e habilitar HTTPS.
  O CNAME no artefato não configura DNS nem substitui a configuração do Pages.
- CI executa testes de configuração e duas publicações reais da fixture: `/Raiz/` e `/`, a segunda com o hostname
  reservado `raiz.example`. Playwright e auditoria de agentes verificam ambos; na raiz, também CNAME e canonical.
- Validação integrada das entregas 1 a 5: 10 testes de configuração, 176 testes de front sem skips, os dois builds
  e Playwright/Lighthouse Agentic nos dois caminhos passaram, com zero 404 e sem expor dados individuais.
  O formulário nativo do produtor conserva o caminho também com JavaScript desligado. Actionlint aprovou os dois
  workflows; os seis jobs, E2E com API, cena-alvo e as 15 medições fixas de Lighthouse mobile foram preservados.
- `robots.txt` e `llms.txt` ficam prontos para a raiz quando o domínio for ativado. O endereço atual de projeto
  continua com a limitação do robots na raiz de `bernardoemmel.github.io`.

## Verificação real após a migração do Release

- Em 12/11, o cadastro básico atual produziu 365 municípios com desenho em 9 estados e site público de 91 MB.
  Playwright conferiu busca por Parauapebas, zoom 13 com HTTP Range, pedido no Pará e 360 px, com zero 404.
- A consulta atual confirma 345.870 fazendas lidas em 144 municípios do Pará. O total de hectares passou a
  aparecer como desconhecido quando há células ausentes ou suprimidas no novo pacote. A medição de hectares
  registrada antes nesta passagem pertence ao pacote anterior; não deve substituir a disponibilidade atual.
- As cinco entregas foram integradas à main com os seis checks verdes em cada PR:
  [cena-alvo #67](https://github.com/bernardoemmel/Raiz/pull/67),
  [cobertura #70](https://github.com/bernardoemmel/Raiz/pull/70),
  [ficha visual #71](https://github.com/bernardoemmel/Raiz/pull/71),
  [celular e acessibilidade #73](https://github.com/bernardoemmel/Raiz/pull/73) e
  [domínio e Markdown #74](https://github.com/bernardoemmel/Raiz/pull/74).
- A suíte Python da entrega final passou com 1.043 testes, um skip e um xfail já aceitos pelo portão do CI.
  Lighthouse no CI: desempenho entre 98 e 100; acessibilidade 100 nas cinco páginas.
- A publicação é coordenada com a migração privada do [PR #72](https://github.com/bernardoemmel/Raiz/pull/72),
  do chat Ficha da fazenda. O workflow foi pausado durante a limpeza de artifacts/caches; a retomada dos
  publicadores pertence a essa migração. Não confundir merge do código com publicação efetiva:
  conferir a última execução de [Publicar o site](https://github.com/bernardoemmel/Raiz/actions/workflows/publicar-site.yml).

## Situação das cinco entregas e próximos passos

Cena-alvo ligada ao Release, cobertura diária sem lista fixa, ficha visual com acesso controlado, navegação
mobile com portão Lighthouse e domínio configurável estão na main. Os resultados e hashes de cada entrega
estão nos PRs acima. A revisão final também corrigiu totais Markdown incompletos e não encontrou outros
problemas acionáveis de autorização da ficha, navegação ou caminhos do domínio.

1. Publicação após #72 conferida na seção abaixo; acompanhar as rodadas diárias, datas da cobertura,
   municípios novos e caminhos públicos. Não alterar o PR do chat Ficha da fazenda.
2. Os três lotes do Pará foram concluídos no **Release privado**, conforme #78. O ponteiro completo não deve
   voltar ao Release público. A próxima entrega publica somente uma projeção explícita dos resumos autorizados;
   seleção de fazendas, desenho dos lotes, tabela individual, travas e “o que destrava” vêm da API autenticada.
3. E9 passo 3: aguardar as 30 cartas reais anonimizadas e uma avaliação de compreensão, confirmadas como ainda
   indisponíveis pelo fundador. Depois calibrar o portão e gravar a nota no laudo. Contato com o dono somente na fase final.
4. Quando houver domínio real, configurar DNS e Pages e preencher `RAIZ_DOMINIO`; conferir HTTPS, CNAME,
   `robots.txt` e `llms.txt` na raiz. Nenhum domínio real foi escolhido ou ativado nesta entrega.
5. Continuar os demais itens E9 na ordem do plano: texto por fazenda no kit ONS/campos abertos, condicionais e
   extenso, KMZ e os demais. A geometria de reserva legal ainda não está nas camadas; não deduzir seu desenho de percentuais.

## Continuação: publicação após #72 e fronteira aberto/pago (12/11/2026)

- **Entrega 1 feita:** #72 já estava mesclado; não foi alterado por este chat. O workflow `publicar-site.yml`
  estava ativo e a publicação [43311812890](https://github.com/bernardoemmel/Raiz/actions/runs/43311812890)
  concluiu com sucesso após o conserto de downloads do #80. A publicação diária continua ativa, sem lista fixa.
- Conferência independente no [site ao vivo](https://bernardoemmel.github.io/Raiz/): busca por Parauapebas,
  contornos básicos coloridos, aproximação com fundo recebido por HTTP Range 206, novo pedido e tela de 360 px.
  **Zero HTTP 404 e zero erros de JavaScript** nessas navegações. A cobertura publicada era de 365 municípios,
  9 estados e 712.601 registros básicos; índice gerado em `2026-11-12T21:47:25+00:00`.
- O artefato efetivamente publicado foi baixado novamente: 1.596 arquivos, 365 CSV básicos e 365 GeoJSON,
  com 712.601 contornos. Cada CSV passou pela lista positiva; cada contorno contém somente CAR e geometria.
  Não há ficha, certidão, tabela financeira individual, lote completo ou identificador de fazenda em agregado.
  SHA256 do `artifact.tar`: `0965c217d1619fd830962d3e8c1eafff78997e94973e6093965c9248b00bb1d6`.
- Também foram baixados e validados **todos os 36 assets** então presentes no Release público `dados`
  (199.862.136 bytes), incluindo os novos estados e as fichas metodológicas Croissant. Todos passaram pela
  função `validar_asset_publico`; nenhum pacote de camadas pagas ou de lotes completos estava publicado.
  Contagens do Release mais recente podem superar as do site até a próxima publicação.
- O cadastro básico de todas as fazendas permanece aberto, conforme #72. Isso não autoriza revelar quais
  fazendas compõem um lote: os resumos comerciais terão contrato próprio, sem CAR nem geometria da seleção.
  Respostas 404 ao tentar endereços antigos de camadas pagas são a retirada esperada, não falhas de navegação.
- Uma atualização foi disparada e concluiu na execução
  [43331843113](https://github.com/bernardoemmel/Raiz/actions/runs/43331843113), sobre a main `6f49dfc`.
  A nova publicação incorporou automaticamente **444 municípios, 13 estados e 912.853 fazendas básicas**,
  com índice de `2026-11-12T23:54:43+00:00`. A mesma navegação ao vivo passou novamente com zero 404/erros.
  O novo artefato tem 1.849 arquivos, 444 CSV básicos e 444 geometrias; todos foram revalidados sem medidas pagas.
  SHA256 do tar: `c0a32ce66a78872c417e850ede2ae930154796a75bc1730070ffe3eefc7dec52`.
- Próximas entregas, nesta ordem: resumo aberto/detalhes por API; sensibilidade; pedido por UF, bioma ou Brasil;
  painel de acerto por versão. A rodada privada do Pará não calculou sensibilidade (`sensibilidade_ligada=False`);
  a demonstração ficará identificada até haver resultados reais. E9 continua aguardando as cartas reais.
- O CI encontrou três falsos positivos no histórico de outra branch remota: hashes de código do atestado MCP
  no commit `e7074b4a`. Foram comparados byte a byte aos arquivos versionados e permitidos somente pelos três
  fingerprints exatos em `.gitleaksignore`. A varredura de todas as branches e as regras oficiais permanecem.

## Nova entrega 1: cena-alvo ligada ao Release (12/11/2026)

- Contrato conferido no código do chat Lote e números (`4f7c558c`, `raiz/restauracao_rodada.py`): ponteiro
  `lote_PA_central_r11.json`, com `resumos.barata/segura/compacta`; pacotes por execução ficam no Release.
- Na conferência desta implementação, o ponteiro ainda não existia. `baixar-lotes.mjs` grava ausência explícita;
  erro de rede ou formato interrompe a publicação. A data de publicação vem do arquivo remoto, separada da conferência.
- O build projeta somente agregados conhecidos para `amostra/lote_PA_central_r11.json`, inclusive no servidor de
  desenvolvimento. Nunca copia os pacotes individuais, CARs ou folhas de contato. O JSON sempre existe no site com dados.
- Sem API, o site salva os critérios no navegador e mostra o cenário publicado ou sua ausência. Retirado o fluxo
  de resultados inventados como padrão. O snapshot não finge ter aplicado teto de custo nem outros filtros novos.
- Comparação e quadro “o que destrava” preservam dados ausentes como desconhecidos. TIR é a do fluxo alavancado do
  lote, não média das TIRs individuais; P10/P90 de TIR não são fabricados quando só há valor central.
- Mapa com verde, azul e ocre, e padrões de linha diferentes, permite comparar as três opções. A API acrescenta
  geometria somente para fichas já desbloqueadas pelo cliente ativo; revalida reserva/exclusividade a cada leitura.
  O Pages continua agregado. Falta de autorização ou desenho produz aviso, sem abrir detalhes por contorno público.
- Botão de contato permanece desabilitado nesta fase. As 30 cartas reais ainda não estão disponíveis para E9.
- Verificação: 869 testes Python passaram após incorporar a rodada 11 (2 pulados e 1 xfail); 160 testes do front
  passaram após integrar a entrega de qualidade. Playwright confere ausência/publicação do lote, três cores por
  pixels, teclado, 360 px e zero 404. O E2E com API e PostGIS preserva os testes da fase posterior de interesse/Pix
  por preparação isolada no servidor de teste, mantendo o botão de contato desabilitado na tela do produto.

## Nova entrega 2: cobertura diária do mapa (12/11/2026)

- O cron diário existente (10:41 UTC) continua lendo `estados.json` e os pacotes de todas as UFs do Release.
  A geração não tem lista fixa de municípios. O teste incremental usa três rodadas com o mesmo cache: acrescenta
  um município e uma UF; depois acrescenta o desenho que estava faltando, que deixa de aparecer como pendência.
- `geo/indice.json` preserva `gerado_em` e recebe `dados_publicados_em` do manifesto do Release. O build aberto
  calcula `cobertura` só dos arquivos anunciados e presentes, com códigos municipais, sem CAR ou caminhos privados.
  Cache de município fora do manifesto não aumenta a contagem.
- O painel do Brasil mostra municípios e estados com desenho na base; o painel estadual mostra sua própria
  contagem. Municípios processados continuam como medida separada. Datas do mapa e do Release são distintas,
  em horário de Brasília; ausência é escrita como “data não informada”.
- A main passou a publicar só agregados no PR #52. A cobertura não reabre geometrias individuais: explica que
  a ficha com acesso pago contém os desenhos. Município com desenho na origem recebe esse aviso; município
  cujo desenho falta recebe o aviso de indisponibilidade. Não confundir restrição de acesso com falta de dado.
- Validação local: 9 testes de geometria passaram, 133 testes do front passaram (13 pulados), lint e formato
  Python passaram. O Playwright do build verifica cobertura, datas e ausência de vazamento de dados individuais.
- Verificação adicional no navegador com dados reais do Release: a consulta do Pará mostrou 144 municípios,
  345.870 fazendas lidas e 9.484.092 ha com potencial de restauração, sem 404 ou erro de JavaScript. Créditos e TIR
  continuam pendentes da publicação dos lotes. O texto do estado ausente agora diferencia explicitamente a base
  territorial disponível da oferta de créditos e da avaliação da terra que ainda aguardam o lote.

- O Release migrou em 12/11 às 19:25 UTC para `imoveis_basicos_<código>.csv`. O leitor e o exportador aceitam
  esse contrato; no escopo `publico_basico`, não usam tabelas técnicas antigas. O download remove CSVs retirados
  do pacote somente após extração bem-sucedida, conservando a geometria da mesma versão. Regressões cobrem
  migração de formato, município retirado e preservação de fazenda pequena. A falha de publicação após #67
  preservou o site anterior; esta correção recompõe a rodada diária.
- O CI encontrou um falso positivo em URL JDBC sem credenciais de outra branch. A exceção em `.gitleaksignore`
  identifica exatamente commit, arquivo, regra e linha; mantém a varredura de todas as refs e as demais regras.

- A integração com o Calendário da main também publica JSON de ausência explícita quando sua primeira coleta
  ainda não existe. Isso elimina o 404 observado na navegação real, sem inventar eventos nem data de coleta;
  falha de atualização preserva os bytes da última coleta disponível. Teste HTTP cobre JSON e ICS em `/Raiz/`.
- Validação do novo contrato real: 365/365 municípios com desenho, 9 UFs, 74,2 MB de geometrias internas e
  91 MB no site público agregado. Após incorporar Calendário: 174 testes de front e 12 testes de geometria
  passaram; as regressões da ausência de agenda também passaram.

## Referências conferidas para a segunda entrega

- llms.txt: https://llmstxt.org/ (proposta v2; permite subcaminho e `rel="describedby"`).
- Lighthouse: https://github.com/GoogleChrome/lighthouse/releases/tag/v13.6.0 e
  https://developer.chrome.com/docs/lighthouse/agentic-browsing/scoring (experimental, Chrome 150+).
- OpenAI: https://developers.openai.com/api/docs/bots.
- Anthropic: https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler.
- Perplexity: https://docs.perplexity.ai/docs/resources/perplexity-crawlers.
- Google: https://developers.google.com/crawling/docs/crawlers-fetchers/google-common-crawlers#google-extended.
- Apple: https://support.apple.com/en-us/119829; Common Crawl: https://commoncrawl.org/ccbot.
- Alcance do robots.txt: https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.

## PRs abertos e branches sem merge

- #42: já integrado; a lista abaixo é histórico da passagem anterior e deve ser conferida antes de atuar.
- #35 (outro chat, E5): cria `migracoes/versions/0019_titulo_achados.py` com revision "0019". A 0019 deste chat
  (`0019_legibilidade.py`) já está na main, então o #35 tem de virar 0020 (revision "0020", down_revision "0019").
  Senão o Alembic fica com duas cabeças e os testes com banco falham.
- #39 (outro chat, E7 backoffice): aberto quando este chat parou.

## Trabalhos rodando no Actions e como conferir

- "Processar estados" (de outro chat): várias rodadas com até 18 jobs. Ocupam os runners, e por isso o CI dos PRs
  fica na fila por 10 a 20 minutos. Não cancelar.
- "Publicar o site": roda a cada push na main que mexe em `front/**` e todo dia às 10:41 UTC. A última rodada (do
  merge do #40) publicou.
- Para conferir:

  ```bash
  curl -s "https://api.github.com/repos/bernardoemmel/Raiz/actions/runs?status=in_progress" | python3 -c "import json,sys; [print(r['id'], r['name'], r['head_branch']) for r in json.load(sys.stdin)['workflow_runs']]"
  ```

  Ou pelo GitHub MCP: `actions_list`, method `list_workflow_runs`.

## Decisões e cuidados que não estão no código

- O relato de negação automática de binários era do ambiente anterior. No ambiente Codex atual, dependências
  travadas foram instaladas normalmente e PostGIS roda em Docker para a suíte Python. Actionlint segue no CI.
- `npm ci` falhou no site por lock fora de sincronia. Para mexer em dependência do front: `npm install` na pasta e
  conferir um `npm ci` numa cópia limpa (`package.json` e `package-lock.json` numa pasta vazia).
- Para testar com banco aqui (não há Docker):
  - instalar e ligar: `apt-get install -y postgresql-16-postgis-3` e `pg_ctlcluster 16 main start`;
  - criar o banco: `create role raiz login password 'raiz' superuser; create database raiz_teste owner raiz;`;
  - apontar os testes: `RAIZ_BANCO_URL_TESTE=postgresql+psycopg://raiz:raiz@localhost:5432/raiz_teste`.
- O LanguageTool é LGPL e roda só como serviço (`infra/languagetool`). O texto do dono vai só para o servidor
  próprio, nunca para api.languagetool.org. A API pública foi usada uma vez, com uma frase neutra de exemplo.
- `raiz/thumbhash.py` usa o arredondamento do JavaScript (metade para cima), senão o hash não bate com o pacote npm
  `thumbhash` do front. O teste fixa um hash conferido com o npm.
- O link do Organic Maps segue `libs/ge0/url_generator.cpp` do repositório organicmaps (o caminho antigo `ge0/` dá
  404). O teste usa os casos de teste deles.
- Privacidade nos arquivos públicos: código do CAR, foto de satélite, Plus Code e link do Organic Maps só depois do
  aceite. No `rows.json`, antes do aceite eles ficam em campos que começam com `_`.
- Gunning Fog: a lista de palavras comuns da Linguateca (que o ALT usa) não tem licença clara e não foi copiada. Sem
  `RAIZ_PALAVRAS_COMUNS`, a palavra complexa é a de 4 sílabas ou mais.
- O build do site sem dados é `RAIZ_BUILD_DADOS=0`: o plugin `vite-dados.ts` só grava dado no `closeBundle`.

## Comandos para os testes desta parte

```bash
uv run ruff check raiz testes scripts migracoes && uv run ruff format --check raiz testes scripts migracoes
```

```bash
RAIZ_BANCO_URL_TESTE=postgresql+psycopg://raiz:raiz@localhost:5432/raiz_teste uv run pytest -q testes/test_legibilidade.py testes/test_revisor.py testes/test_fichas_lote.py testes/test_thumbhash.py testes/test_localizacao.py testes/test_satelite.py testes/test_publico.py testes/test_aceite.py testes/test_front_api.py
```

```bash
cd front/globo && npm test
```

```bash
RAIZ_BUILD_DADOS=0 front/scripts/construir-site.sh
```

## Continuação: ficha visual da terra (entrega 3)

- A rota do CAR continua na `FichaTerra` paga do PR #52. Não reabrir a antiga ficha estática para fornecer o mapa.
- `GET /prospeccao/fichas/{car}/visual` entrega um contrato fechado: `imovel`, `mascara`, `camadas` (GeoJSON),
  fonte do perímetro e das camadas, data de corte, data da fonte quando disponível e avisos. Todas as geometrias
  vêm do banco; as camadas são intersectadas com o CAR, preservando furos. Só `camada` sai nas propriedades.
- `GET .../visual/satelite` reutiliza o gerador Sentinel-2 existente e devolve a caixa geográfica, fonte e data
  da cena. Uma ausência conhecida devolve um estado explícito com HTTP 200. `GET .../visual/satelite.webp`
  serve a imagem com sessão, crédito liberado, exclusividade e `private, no-store`. A URL do blob é revogada ao
  sair da ficha; token nunca vai na URL ou em um arquivo do site.
- `MapaFichaTerra` põe a imagem recente sob o perímetro duplo, máscara e hachura diagonal. A hachura só usa
  `pode_voltar` medido, não a área restaurável da tabela. Sem camada medida, aparece aviso. Fonte e data das
  camadas ficam consultáveis; a coleção/data ausente não recebe um ano presumido.
- A linha do tempo reúne cobertura e perdas por ano, com texto e fonte/data além das cores; mantém as tabelas
  completas e navegação por teclado. O mapa se reenquadra ao mudar a largura da tela, incluindo 360 px.
- Validação focada: 32 testes Python com PostGIS, incluindo geometrias com furos, recorte e privacidade;
  Chromium confere satélite de teste explicitamente sintético, camadas, controle de hachura, linha do tempo,
  acesso antes/depois do crédito, troca de conta e 360 px. `test:prospeccao`, já no CI, guarda as capturas.
- Teste externo validado com CAR e geometria do Release de Parauapebas: imagem Sentinel-2 de 132.586 bytes,
  1024 × 938 px, composta pela mediana das cenas de 06/09/2026 a 23/10/2026. O mapa renderizou o recorte,
  contorno e máscara em 1100 e 360 px. Sem camadas medidas nesse imóvel, exibiu o aviso, sem inventar hachura.
  A legenda preserva o período inteiro e identifica a composição mediana, em vez de tratá-la como uma foto
  de data única. Os testes determinísticos do CI continuam identificados como imagem sintética.
- Em ambiente cujo GDAL não reconheça a CA do proxy, configurar `RAIZ_SATELITE_LEITOR_HTTP=blocos` na API.
  Só as novas rotas visuais usam então o leitor Range já existente em `raiz.coleta.blocos`, com requests,
  a CA/proxy herdados e cache de 1 GB em `dados/imagens/.cog`. O gerador e as outras rotas permanecem iguais.
  A validação real usou esse leitor sem desativar TLS e baixou 95 MB de blocos, sem baixar cenas inteiras.
- A suíte completa local foi interrompida após 321 testes aprovados para evitar competição com a suíte
  de integração do chat principal; os testes focados passaram. Rodar a suíte completa no checkout integrado.
- A imagem real depende da disponibilidade de cena no Sentinel-2 e dos polígonos/camadas carregados na API.
  A publicação estática mantém apenas agregados. Não transformar o teste de imagem sintética em evidência
  de disponibilidade orbital para todas as fazendas. O contato com o dono continua na fase final.

### Validação da ficha após integrar as entregas 1 e 2

- Integrada a cobertura do mapa (`fb8c796`), incluindo a cena-alvo e os seis jobs de qualidade do CI.
  O único conflito estava no plano; todas as entregas e as seções de qualidade e continuidade foram preservadas.
- A API do pedido continua retornando apenas contornos já desbloqueados pela própria conta, sem nova cobrança.
  Sugestões antigas perdem a geometria antes de conferir novamente a autorização e a exclusividade.
- Checagens no ambiente próprio da ficha: Ruff e formatação, TypeScript, 166 testes de front, 53 testes de
  API/ficha/satélite com PostGIS e dois testes de autorização dos contornos do lote aprovados, sem skips.
  Chromium conferiu o mapa, hachura, linha do tempo, crédito, troca de conta e 360 px. A suíte Python completa
  permanece a cargo da integração do chat principal; não foi repetida nesta rodada.

### Integração da ficha com o cadastro básico e o Calendário

- A entrega 3 incorpora a descoberta de `imoveis_basicos_<IBGE>.csv` no Release e a main com o Calendário
  (`a4c1066`). A ficha mantém o mapa privado, a linha do tempo e o selo de leilão da agenda; imagem e vínculo
  do calendário só são consultados depois do desbloqueio da ficha.
- Ruff e formatação passaram em 361 arquivos. TypeScript, 177 testes do front e 91 testes Python focados
  em visual/satélite/ficha/API/acesso passaram, sem skips. Playwright conferiu a ficha com o calendário
  e a agenda em 1440, 768 e 360 px, incluindo o aviso de coleta ausente.

## Entrega 4: celular, teclado e desempenho (12/11/2026)

- A escala nacional usa SVG Natural Earth já existente no repositório, com estados coloridos pela cobertura real,
  nomes acessíveis, links por estado e a mesma busca. Escolher estado ou município carrega MapLibre e a base PMTiles;
  depois o mapa detalhado permanece montado nas trocas. Isso reduz o JS inicial de cerca de 1,6 MB para 267 KB
  (aproximadamente 86 KB gzip), sem baixar contornos municipais na abertura nacional.
- Menus continuam disponíveis a 360 px. Atalho de teclado pula para o conteúdo, as rotas levam foco ao main,
  a alça da gaveta e os controles têm 48 px, os resultados da busca quebram linha e tabelas roláveis recebem foco e rótulo.
- `npm run test:acessibilidade` serve o artefato com gzip/Range, verifica teclado (pular conteúdo, gaveta e busca),
  largura de 360 px e axe WCAG 2.1 A/AA no Brasil, município, login com erro, novo pedido (filtros fechados/abertos)
  prospecção pública e produtor. `test:prospeccao` também audita a ficha desbloqueada e a busca autenticada. Não expõe dados pessoais.
- Lighthouse 13.6.0 mede as categorias oficiais performance e accessibility em mobile de 360 px, com throttling
  `simulate` padrão. São **três execuções fixas** por página: Brasil, entrar, novo pedido, prospecção e produtor: exige mediana de desempenho >= 90
  e acessibilidade >= 90 em cada execução. Erro de coleta, nota ausente/nula e troca para desktop/rede sem simulação
  reprovam. Salva todas as amostras HTML/JSON, axe e capturas em `front/.cache/teste-acessibilidade` e no CI.
- A série fixa final deu medianas de desempenho de 100 no Brasil, 96 na entrada, 98 em novo pedido,
  98 em prospecção e 100 no produtor; acessibilidade 100 nas quinze medições. Todas as amostras ficam preservadas,
  inclusive os outliers de desempenho 73 no Brasil e 72 em novo pedido. Runners concorrentes afetam TBT: a mediana
  tem três amostras fixas, sem repetir até passar ou escolher a melhor.
- Ficam pendentes avaliação humana completa WCAG e a calibração E9 com cartas reais. O teste automatizado não é
  declaração de conformidade total e não inicia contato com proprietários.

Validação local integrada das entregas 1 a 4: build com dependências travadas, 175 testes do front sem skips,
Pages com zero 404, cena-alvo pública/autorizada e prospecção/ficha com axe, além do Lighthouse Agentic Browsing.
Os sete cenários do auditor mobile tiveram zero violações axe e nenhuma largura acima de 360 px. Os quinze
relatórios Lighthouse passaram pelo portão fixo. E9 real não foi calibrado e a suíte Python completa cabe ao chat principal.


### Integração das entregas 1 a 4

- `fonte.geo.cobertura()` lê apenas o índice leve, com cache, para mostrar contagem e datas na entrada em SVG.
  Os GeoJSON nacionais continuam adiados até escolher estado/município. A API ainda não publica esse manifesto;
  nesse modo a cobertura fica indisponível, sem inferir desenhos a partir dos resumos e sem chamar uma rota inexistente.
- Formulário fechado, consulta pública sem fazendas e ficha antes do desbloqueio não baixam MapLibre.
  O mapa específico carrega ao desenhar uma área, receber lotes autorizados ou abrir a ficha desbloqueada.
- `test:cena` executa axe WCAG 2.1 AA também na comparação pública e nos três lotes autorizados a 360 px;
  `test:prospeccao` conserva o teste de Sentinel-2 sintético, hachura e linha do tempo junto da auditoria axe.

- A entrada do produtor entrega cabeçalho, instrução e formulário como HTML nativo; funciona sem JavaScript.
  Preact e o leitor da ficha só carregam com `?car=`, preservando o caminho e os controles de acesso existentes.
  A auditoria confirma a leitura e o envio nativo do formulário com JavaScript desligado.
- O portão Lighthouse inclui também `#/pedidos/novo` e `#/prospeccao`, sem substituir o backend público por fixture: são 15 medições fixas ao todo.
- Revisão visual da ficha a 360 px: escala no alto à esquerda e atribuição inteira no rodapé, sem sobreposição.
  O estilo dos detalhes da ficha não atinge mais o controle interno do MapLibre, eliminando o botão de informação
  redundante; os botões de zoom têm 48 px. Playwright verifica a legenda Copernicus completa com imagem sintética,
  as caixas sem interseção, o crédito visível e axe/360 px. TypeScript e verificador de design passaram.

### Integração do Calendário com a navegação acessível

- Calendário também usa carregamento por tela, conserva o foco no conteúdo e mantém seus filtros, feed e aviso
  de coleta ausente. O quarto link do menu continua visível a 360 px, sem rolagem horizontal.
- A auditoria do Calendário entra no CI: três larguras (1440, 768 e 360 px), teclado e axe WCAG 2.1 AA.
  TypeScript, design, actionlint, 186 testes do front e Playwright de cena-alvo e ficha passaram após o merge.
- Os seis jobs do CI e as quinze medições fixas de Lighthouse foram preservados; a integração não reduziu
  categorias, notas mínimas nem o conjunto de páginas do portão.

### Domínio após integrar Calendário e cadastro básico

- As duas bases, `/Raiz/` e `/`, passaram pelo build e pelo Playwright com calendário/feed ICS, busca,
  acesso pago por CAR, overzoom e formulário do produtor sem JavaScript; zero 404 nas duas publicações.
- Dez testes de configuração e 187 testes do front passaram. Actionlint aprovou os workflows.
  A fixture de calendário é usada também no segundo build do CI, sem depender da agenda remota.

### Conferência final com o Release real

- O conjunto final passou novamente pela busca Parauapebas, zoom 13 por HTTP Range, pedido no Pará e 360 px,
  com zero 404. Lighthouse das cinco páginas no artefato real: desempenho mediano 100/98/95/95/100;
  acessibilidade mínima 100 em todas as quinze medições fixas. Não houve repetição para escolher notas.
- A revisão corrigiu o Markdown estadual/municipal: medidas ausentes permanecem desconhecidas e zero
  explícito continua zero. Um total incompleto não é apresentado como completo; contagem desconhecida
  não libera medidas de grupos cujo tamanho mínimo não pode ser confirmado. Dezenove testes focados passaram.
- A atualização da main para o histórico automático foi incorporada; preservadas a nota do Calendário
  sobre o runner e a exceção exata de URL JDBC sem credenciais.

## Continuação, entrega 2: lotes abertos e detalhes autenticados (13/11/2026 UTC)

- `raiz.lotes_publicos` lê **somente o manifesto privado**, depois de conferir a visibilidade autenticada,
  tamanho e hash. A projeção `publico_lotes` v1 publica apenas os sete indicadores autorizados; não baixa
  os pacotes por fazenda. Token restrito ao passo do Actions, sem variável `VITE_`, cache ou artifact privado.
  O build e o navegador reaplicam a lista positiva. O formato completo antigo é recusado.
- Fonte real: rodada `central_r11`, modelo `restauracao-2026d+a84f9789`, publicada em
  `2026-11-12T20:47:42Z`, 144 municípios e 345.870 fazendas calculadas no Pará. Pedido de referência:
  um milhão de créditos, contrato de US$ 55 por crédito. Alterar os critérios não recalcula esse snapshot.
- A comparação aberta usa o mesmo conjunto de titulares **e fazendas de reserva** em cada medida:

| Opção | P10 / P50 / P90 de créditos | Hectares | Fazendas | Custo médio por crédito |
|---|---|---:|---:|---:|
| Mais barata | 1.298.148 / 1.871.150 / 2.309.231 | 9.561,3 | 95 | US$ 26,83 |
| Mais segura | 1.310.708 / 1.891.833 / 2.332.670 | 9.942,8 | 270 | US$ 27,68 |
| Mais compacta | 1.339.520 / 1.950.679 / 2.426.929 | 10.838,4 | 25 | US$ 33,29 |

- **Terra documental pronta: zero créditos e 0% da meta nas três opções.** O indicador exige matrícula
  conferida ou concessão; não usa a oferta estadual do solver, que também aceita matrícula a conferir.
  Uma futura mistura sem quantis separados permanece desconhecida: não ratear créditos por hectares ou fazendas.
  Isso não afirma que uma concessão ou matrícula por si só libera a venda; os lotes continuam sujeitos à diligência.
- A tela aberta não mostra TIR, composição, CAR, mapa da seleção, tabela por fazenda, travas ou “o que destrava”.
  O cadastro básico geral permanece aberto, separado da identidade das fazendas de cada lote.
- Na área autenticada, os detalhes usam o transporte e o DTO da API. Sem servidor, a opção explícita
  “Conhecer a demonstração da área logada” abre uma sessão separada e dados inteiramente fictícios, com IDs
  `DEMONSTRACAO-*` e contornos artificiais. Não lê o Release privado, não libera fichas reais, não cobra e não
  inicia contato. Uma API configurada sempre prevalece sobre essa demonstração.
- Quadro “o que destrava” usa somente a opção consultada; sem dado específico, informa ausência. Não reutiliza
  as estatísticas gerais como se fossem a diligência daquele lote. Pequenas fazendas continuam incluídas.
- Verificação: seis testes do projetor privado, 233 testes do front, TypeScript, Ruff, design e actionlint;
  Playwright integrou resumo ausente/legado/permitido, demonstração, três lotes autorizados, ficha bloqueada,
  teclado e axe a 360 px, sem 404. Pages também passou com publicação básica e zero erros no navegador.
  Revisões independentes da projeção e do acesso não encontraram vazamento. O rótulo “custo médio” distingue
  o custo estimado do preço de venda de US$ 55. E9 continua aguardando as cartas reais.

## Continuação, entrega 3: sensibilidade do lote (12/11/2026, Brasília)

- A comparação autenticada ganha controles de preço do crédito, reserva contra reversão (mínimo 20%),
  taxa de desconto e cenário pessimista. Mostra as três opções, quantis de créditos, área, fazendas, VPL e
  TIR do projeto, com fonte, data, versão e premissas. Desconto altera VPL; não altera a TIR do mesmo fluxo.
- O endpoint exige identidade, escopo, liberação e propriedade do pedido antes de ler qualquer arquivo.
  A grade privada é exata, sem interpolação: combinações inexistentes respondem ausência explícita, sem 404.
  Pedido, modelo, critérios e composição precisam corresponder à revisão do lote; uma edição invalida a
  comparação antiga. O componente limpa resultados defasados e descarta respostas em voo de outra revisão.
- A rodada real do Pará publicou `sensibilidade: []`. O quadro informa essa ausência; a demonstração optativa
  usa composições e fluxos inteiramente fictícios, sem ler dados pagos nem registrar resultados no aprendizado.
  Publicar a grade real continua pendente no motor; não apresentamos o exemplo como previsão calibrada.
- Contrato operacional em `docs/sensibilidade-lote.md`. Testes cobrem limites, grade exata, autorização antes
  da leitura, ausência, distinção entre desconto/TIR e invalidação após editar o lote. Playwright cobre os quatro
  controles, teclado, axe/360 px e respostas indisponíveis sem 404.

## Continuação, entrega 4: pedido por estado, bioma ou Brasil (12/11/2026, Brasília)

- Novo pedido permite as 27 UFs, seis biomas ou Brasil inteiro. Trocar o alcance limpa município, desenho e
  raio ocultos da seleção anterior. Nenhuma lista de estados processados é fixa: a disponibilidade vem do
  manifesto atual, com data, municípios lidos/esperados, estados parciais, ausentes e desconhecidos.
- Os critérios seguem para a API existente, que filtra as fazendas pelo recorte. No modo aberto, cobertura
  estadual não vira oferta do bioma: totais de fazendas/hectares ficam desconhecidos quando o recorte exato
  não foi publicado. Municípios são deduplicados e informação suprimida não vira zero.
- O resumo do Pará continua identificado como cenário publicado; não é extrapolado para outro estado,
  bioma, Brasil inteiro ou novos filtros financeiros. A demonstração também conserva seu aviso fictício.
- Testes cobrem estado recém-processado, disponibilidade parcial, troca de alcance e ausência. Playwright
  passou por estado, bioma e Brasil com teclado, axe em 1440/360 px e zero 404; entra no CI junto da cena-alvo.

## Continuação, entrega 5: acerto do modelo por versão (12/11/2026, Brasília)

- O painel `#/acerto` compara previsões com observações elegíveis, separadas por modelo, versão, alvo,
  horizonte e tipo de avaliação. Explica erro/viés, faixas e probabilidades na unidade adequada; não inventa
  uma taxa geral nem elege um vencedor entre tarefas diferentes. WIS/Brier menores indicam menor erro.
- API e exportador publicam somente agregados com pelo menos cinco imóveis distintos. CAR, resultados
  individuais, fontes livres e medidas de grupos pequenos não entram no DTO aberto. O placar completo
  permanece no endpoint operacional protegido. Cache público curto, fontes/data e limite de cobertura visíveis.
- A avaliação exige valor/gabarito válidos e referência temporal compatível com a previsão. “Ao vivo” exige
  prova de que a previsão foi congelada antes da observação; ausência de cronologia não vira comprovação.
  A projeção não altera os retratos históricos nem os registros originais do aprendizado.
- Ainda não há placar real anunciado no Release público. Sem `RAIZ_ACERTO_URL` ou API com dados elegíveis,
  o site mostra ausência explícita, nunca 0% de acerto. O contrato e a operação estão em `docs/painel-acerto.md`.
- Testes cobrem supressão, valores desconhecidos, proveniência e período. Playwright/axe passou em 1440/360 px
  nas bases `/` e `/Raiz/`, sem 404. O painel também entra na série fixa de três medições Lighthouse no CI.

## Integração das entregas 2 a 5 (12/11/2026, Brasília)

- Reunidas no [PR #89](https://github.com/bernardoemmel/Raiz/pull/89), integrado à main em 13/11/2026 UTC
  pelo commit `0f947677`, com os nove checks verdes no run `43351801849`. A main foi incorporada,
  preservando a separação aberto/pago e os novos jobs do CI.
  Os percursos integrados passaram em 13 auditorias axe, com teclado, 360 px, zero 404 e nenhum contato.
- No CI, as seis páginas tiveram medianas de desempenho 100, 98, 97, 97, 92 e 100, com acessibilidade 100
  em todas as medições. A abertura direta em MapLibre tem validação própria no PR #90; essas notas não a cobrem.
- A publicação `43355137460` terminou com sucesso. O artefato `14006865531` foi aberto e conferido:
  2.345 arquivos, 608 CSV básicos, 608 geometrias e 1.299.160 fazendas/contornos em 13 UFs, sem município
  publicado sem desenho. O resumo aberto do Pará passou na lista positiva; composição, travas, certidões e
  demais arquivos pagos não estavam no pacote. Os 380 Markdown não continham códigos CAR completos.
  SHA-256 do tar: `099c97b291d7a72d5b42a2a5ebcf639fc7568adcbe71bca0924d631d387b2b95`.
  Às 03:33 UTC de 13/11, sete arquivos públicos responderam 200 e eram idênticos ao artefato; o PMTiles
  respondeu 206 ao pedido de intervalo. Três caminhos antigos de arquivos pagos responderam 404, recusas
  esperadas verificadas separadamente dos percursos normais. O índice traz atualização 03:06:59 UTC e fonte
  pública 00:05:47 UTC. Essa auditoria antecede a publicação do novo mapa do PR #90.
- O E2E da API foi ajustado aos rótulos do formulário nacional, conservando as verificações de Pará, meta,
  pagamento, autorização e privacidade. O fluxo inteiro passou localmente com API/PostGIS e novamente no CI.
- A varredura completa do histórico encontrou outra URL JDBC interna no compose de avaliação do commit
  `e0e8ccd`, linha 46: `KC_DB_URL`, host local e porta 5432, sem usuário nem senha na URL. A exceção é somente
  esse fingerprint; as regras oficiais, a ocultação dos valores e a varredura de todas as branches continuam.
- Rodada 12 recebida: Supercluster nacional/estadual, ficha de créditos com base de comparação explícita,
  versão pública datada, sequência de risco e gráficos. Essa continuação conserva o MapLibre e o acesso pago;
  não cancela nem desliga workflows. E9 permanece aguardando o conjunto de cartas reais.

## Rodada 12: fichas privadas, versão pública datada e gráficos (13/11/2026 UTC)

As três partes estão integradas ao PR #90, junto do mapa. Os resultados de CI e Lighthouse da seção
anterior pertencem ao PR #89; não são notas desta rodada. Fichas e gráficos usam dados sintéticos nos testes;
a validação visual do mapa usa o snapshot real identificado no início desta passagem.

### Ficha privada e base de comparação

- O pedido autorizado abre `#/pedidos/{id}/ficha/{barata|segura|compacta}` pelo botão **Ficha resumida desta
  opção**. A tela recebe `opcao.ficha_credito` pela API. A fonte pública bloqueia a consulta antes do GET e
  continua exibindo somente o resumo aberto dos lotes. A ficha agregada não contém identificação ou desenho
  das fazendas nem dá acesso implícito a fichas individuais.
- A tabela **Fatos do lote**, inspirada na organização de um rótulo nutricional, compara P10/P50/P90 por
  hectare elegível e para o total da mesma opção. Não há selo de aprovação de órgão regulador. As duas colunas
  têm a mesma classe de ativo/evidência, métrica, método, versão, horizonte e composição declarada
  (`titulares` ou `titulares_e_reservas`). Por hectare é a divisão dos mesmos quantis por um denominador
  elegível fixo e documentado. Área total do CAR não substitui esse denominador. Exclusões podem se sobrepor;
  não se somam nem se subtraem para fabricar área elegível. Desconhecido permanece diferente de zero.
- A sequência é sempre **Título → Método → Perdas → Garantias → Risco de não entrega**. Cada seção conserva
  fonte, data de referência e revisão técnica próprias. Publicação e hash do documento aparecem separados;
  uma data de consulta, build ou publicação nunca preenche revisão ausente.
- Fontes e conclusões usam catálogos fechados. Estimativa exige origem do motor; verificado exige relatório
  de verificação; emitido exige registro de emissão; entregue exige registro de entrega. O Método precisa
  concordar com a classe, origem e data dos números. Revisão técnica da terra não verifica crédito de carbono.
  Quantidade emitida ou entregue é pontual, com P10=P50=P90; faixas do motor não recebem outro rótulo para
  parecer emissão. FLAG permanece separado e não recebe estado emitido/entregue de crédito.
- O servidor lê somente depois de conferir a conta dona do pedido. O arquivo privado é
  `$RAIZ_FICHAS_CREDITO_DIRETORIO/<pedido UUID>/<revisao_lote>/<opcao>.json`. Critério, composição ou sugestão
  alterados invalidam o documento anterior. O hash abrange o conteúdo validado, incluindo gráficos, opção e
  revisão; identifica o documento, mas não substitui armazenamento histórico imutável. O histórico pago da
  ficha individual continua sendo contrato separado do chat Ficha da fazenda. A projeção REST revalida o
  documento e usa `private, no-store`, sem publicar a pasta privada ou arquivos do Release privado.

Contrato: [docs/ficha-credito.md](../ficha-credito.md). Apresentação:
[docs/design/ficha-credito.md](../design/ficha-credito.md). Arquivos principais:
`raiz/pedidos/ficha_credito.py`, `front/compartilhado/ficha-credito.ts` e
`front/globo/src/telas/FichaLote.tsx`.

### Código público datado

- `/p/{codigo}` oferece a versão datada quando há aceite vigente. O endereço é
  `/p/{codigo}/v/{AAAA-MM-DD}-r{rodada_id}-{sha256}`, também disponível em `.md` ou por negociação Markdown.
  O retrato básico contém somente código curto, município/UF, área do CAR, situação básica, rodada, fonte e
  data de corte. A data de registro aparece separada: registrar hoje uma rodada antiga não prova que a página
  existia naquela data. O retrato não inclui CAR completo, imagem, contorno, carbono, área elegível, TIR ou
  outros números pagos. O hash também não contém esses campos.
- A versão usa a linha histórica de `resultado_imovel` e a foto de `etapa_rodada` preservada na carga. Não
  completa ausências com o cadastro atual nem reaplica regras atuais ao passado. Rótulos de município e UF
  precisam corresponder ao catálogo IBGE; nomes livres, divergências e etapas desconhecidas permanecem não
  informados. O conteúdo congelado não aceita UPDATE/DELETE; correções exigem outra rodada. Uma versão antiga
  avisa de outra posterior pela data de corte e, em empate, pelo id da rodada, sem alterar seus fatos.
- Toda leitura confere `negocio.aceite.estado = 'aceito'`, inclusive links antigos. Revogação ou ausência
  bloqueiam a consulta. Não foi inventado prazo de consentimento a partir de login, reserva ou Pix. A ficha
  atual também falha fechada se o aceite mudar durante sua consulta. Respostas, cartões, vídeo e imagem
  voltam ao servidor sem cache reutilizável; uma cópia já baixada não pode ser recolhida.
- A ficha atual preserva o portão anterior de CAR/satélite após aceite. Seu número compartilhável de hectares
  passa a ser apenas área do CAR, com projeção positiva para cartões e vídeos. Essa publicação básica não
  abre a ficha privada do lote. A migração `0036_publico_eprel` cria a tabela e o bloqueio de alteração;
  ainda deve ser aplicada no ambiente de publicação antes de servir a funcionalidade real.

Contrato e operação: [docs/ficha-publica-versionada.md](../ficha-publica-versionada.md).
Implementação: `raiz/publico_versoes.py`, `raiz/publico.py` e `testes/test_publico_versoes.py`.

### Gráficos com evidência documental

- ECharts mostra contratado, emitido e entregue como três séries acumuladas, sem empilhar ou somar etapas.
  Cada número exige natureza documental, fonte do catálogo, data e registro compatíveis. Banco de aprendizado
  não comprova contrato, emissão ou entrega. Ausência deixa lacuna; zero continua visível.
- Vega-Lite mostra P10/P90, P50 e observado por método. Cada par deve ter a mesma classe, métrica, unidade,
  escala, área, escopo e período. Avaliação ao vivo exige previsão congelada antes do dia observado, com a
  observação na data-alvo exata; backtest fica declarado. Não se anuncia vencedor nem se interpreta o placar
  público agregado como observações individuais.
- O envelope inteiro é conferido contra a ficha: geração e registros não podem ser posteriores à publicação;
  classe, métrica, calendário, horizonte, escopo e área elegível devem coincidir. A escala por hectare mantém
  a área original da carteira, além da base 1. Calendário ou denominador desconhecidos impedem acompanhar
  o lote. Um estudo de outra área/período não pode ser anexado como acompanhamento desta opção.
- Tabelas HTML, cabeçalhos, fontes e datas ficam disponíveis antes do desenho. Cada gráfico só carrega
  bibliotecas quando a pessoa pede para abri-lo; falhas conservam a tabela. Os gráficos não entram no pacote
  inicial da ficha ou do mapa. O runtime Vega rejeita fontes externas, e a API não aceita URLs, expressões ou
  especificações executáveis de gráfico.
- ECharts 6.1.0 usa Apache-2.0; zrender 6.1.0, Vega-Lite 6.5.0 e Vega 6.4.0 usam BSD-3-Clause. Atribuições em
  `NOTICE.md` e textos completos em `front/globo/public/licencas/graficos.txt`. Não há exceção para licença
  restritiva nesta entrega.

Contrato, acessibilidade e desenho: [docs/design/graficos-resultados.md](../design/graficos-resultados.md).

### Dados reais, testes e continuidade

- O resumo privado do PR #78 tem quantis, versões, hectares de titulares/carteira e marcos de cronograma.
  Ainda não declara a base comum de evidência, elegibilidade e exclusões exigida pela ficha. `ha_lote` inclui
  reservas; último marco não comprova o horizonte de todos os números. Portanto a ficha real permanece
  indisponível até existir documento compatível. A API atual também não entrega as séries reais de contrato,
  emissão, entrega e pares por método neste formato. Não converter notas agregadas de acerto em observações.
- `?demonstracao=lotes` é optativo: números, fontes, documentos e datas são fictícios, sem leitura do Release.
  A ficha e os gráficos compartilham área/período do exemplo, mas não comprovam resultado real. Retirar uma
  fazenda invalida a ficha simulada, sem inventar outra revisão. Nenhum contato ou cobrança é iniciado.
- As regressões cobrem autorização, campos pessoais, revisão/hash adulterados, denominador/horizonte
  incompatíveis, inflação de classe de evidência e anexo futuro ou de outra carteira. Playwright/axe da ficha
  e dos gráficos foi incorporado ao CI, com teclado, 360 px, ausência, bloqueio público e erros HTTP/JavaScript.
  Comandos: `node front/scripts/testar-ficha-credito.mjs` e `node front/scripts/testar-graficos.mjs`.
  Os artefatos do CI ficam em `front/.cache/teste-ficha-credito` e `front/.cache/teste-graficos`. Os testes de
  navegador usam fixtures sintéticas; não comprovam disponibilidade de dados reais nem substituem Lighthouse
  do conjunto final. A ficha pública datada também tem smoke com HTML real, 360/1440 px, teclado, axe e
  aviso de nova versão; recusas esperadas após revogação são registradas separadamente dos erros de navegação.
- Validação local integrada: 390 testes do front, build dos dois sites, Ruff global e varredura de 492 commits
  sem segredos. A suíte Python teve 2.624 aprovações e identificou uma asserção antiga que desconhecia a ficha
  ausente e um marcador numérico fictício recusado pelo verificador de privacidade. Ambos foram corrigidos;
  o conjunto de 197 regressões, incluindo essas duas, projeção pública, EPREL e contratos, passou. Os três
  testes de dependências de sistema ausentes localmente e a referência estadual são executados no CI.
  As datas civis de evidência usam UTC: representar o mesmo instante com outro fuso não muda a aceitação.
  O CI completo permanece obrigatório antes do merge; a publicação precisa ser conferida depois dele.
- E9 continua sem as 30 cartas reais anonimizadas e avaliações de compreensão. Não houve calibração humana
  nem contato com proprietários nesta rodada. Após CI verde e merge, conferir a publicação autorizada sem
  expor arquivos privados; registrar as evidências efetivamente obtidas, sem reaproveitar notas antigas.
- Integração com a main `60e17b0` (incluindo os PRs #86 e #93): a migração ainda inédita
  `0035_publico_eprel` passa a descender de `0034`, preservando a sequência da ficha individual. Banco vazio
  passou por upgrade, downgrade até a base e novo upgrade, com uma única cabeça. As 169 regressões de ficha,
  versões, proteção, gráficos e autorização passaram; Ruff conferiu o conjunto Python. Nenhuma migração
  foi aplicada em banco de produção nesta conferência.
- A main avançou depois para `3b962e7` (PR #97, Calendário no MCP) e foi integrada sem conflitos.
  Passaram 205 testes focados de calendário/MCP, OAuth, telemetria, privacidade, EPREL e ficha de crédito,
  além de Ruff e actionlint dos workflows envolvidos. O CI já iniciado é preservado até terminar; só depois
  a branch é atualizada para a validação completa da integração, sem cancelar a execução anterior.
- A integração seguinte incorpora a main `52118b5` (PR #95), com o painel de processamento municipal.
  O leitor preserva telemetria pública válida, incluindo o cache com pacote inalterado, e mantém a recusa
  dos metadados privados, das contagens incoerentes e das datas inválidas. Os testes de transporte UTF-8
  com BOM, repetição limitada a falhas transitórias, cache inválido e CAR de fronteira foram conservados.
  Os contratos integrados passaram em 494 testes do front e 122 testes Python, além de Ruff e actionlint.
  Build e Playwright passaram em `/Raiz/` e `/`, com dados públicos, 27 UFs e zero 404/erros. O painel
  nacional com as 27 UFs passou em teclado e axe a 360 px (32 regras, zero violações ou largura excedida).
  A composição final `f0a7c96`, incluindo a busca entre UFs e o fundo nacional em CSS, passou nas 18
  medições Lighthouse locais (medianas 98/98/97/97/97/100, acessibilidade 100) e na série real
  82/95/95 (mediana 95, acessibilidade 100), mantendo todas as amostras. Os nove jobs do CI ainda
  precisam passar; esta integração não reaproveita notas anteriores nem interrompe processamento.
- Integração da main `692663c` (PR #98, pasta do banco e comprador), a partir de `faf319a`: preservadas
  a ficha resumida `/pedidos/{id}/ficha/{opcao}` e a pasta `/pedidos/{id}/pasta/{opcao}`, com login
  obrigatório para a pasta e controles de conta, crédito e lote na API. A conferência documental da pasta
  não alimenta por inferência os quantis ou gráficos da ficha R12: continuam valendo horizonte, evidência,
  escopo e revisão próprios. Nenhum arquivo da pasta foi acrescentado à publicação estática.
  A migração EPREL ainda não publicada foi renomeada para `0036_publico_eprel`, com pai `0035` (pasta),
  evitando duas heads após `0034`. Um banco isolado novo passou por upgrade, downgrade à base e novo
  upgrade; nenhuma migração de produção foi executada. Os conflitos de dependências, rotas e avisos foram
  resolvidos preservando Tabulator, ECharts/Vega, Supercluster e seus testes. O registro de módulos do
  ECharts recebeu apenas o alias `registrarECharts`, para o lint não confundir seu `use` com um Hook React.
  Passaram 508 testes do front, 248 regressões Python, TypeScript, lint, Ruff, actionlint e a conferência
  de 927 pacotes sem problema de licença. Os smokes da pasta, ficha de crédito, gráficos, prospecção e
  ficha pública datada passaram com teclado e axe em celular, incluindo as recusas esperadas após retirar
  o aceite e a troca de sessão.
  O mapa, a entrada e as evidências não foram alterados nesta integração: os prints e notas Lighthouse
  acima continuam atribuídos a `f0a7c96`; não representam uma medição do novo conjunto. O CI completo
  medirá este HEAD antes de merge e publicação, sem cancelar workflows.

- Integração da main `6b9c377` (PR #100), depois do CI verde de `d00ea94`: conflitos de NOTICE e
  dependências resolvidos preservando H3, gráficos e avaliação de modelos; lock conferido com 251 pacotes.
  O front não mudou. A revisão confirmou CRPS interno, métricas públicas em lista fechada, autorização
  paga e EPREL preservados. Passaram 279 testes focados e Ruff em 608 arquivos; dois testes locais de
  cartão/vídeo foram pulados por ausência de Takumi/FFmpeg no ambiente retomado. O CI completo instala
  essas ferramentas e continua exigindo a suíte inteira, sem tratar esses skips locais como aprovação.
  Nenhum workflow foi cancelado; a política da main mantém `cancel-in-progress: false` no CI.

- A main `6947f2d` (PR #103) também foi integrada, sem conflito: coleta do Calendário pelo manifesto
  público validado e repositório explícito nos comandos de Release. Não altera o mapa ou o contrato pago.
  No CI `43431157242`, cinco jobs pararam antes dos testes porque `setup-uv` consultou `latest` quando
  a API do GitHub já estava no limite de requisições; os portões de código não foram flexibilizados.
  O CI agora fixa `uv` **0.13.8**, exatamente a versão do CI aprovado `43369596942`. O código da action
  confirma que a versão explícita dispensa a consulta à API de versões. Actionlint 1.7.12 passou com
  os mesmos argumentos do CI. A execução em andamento é preservada até terminar, sem cancelamento;
  a próxima revisão precisa concluir todos os nove jobs antes do merge.

- A main `929b4f3` (PR #99) foi integrada sem conflitos, após as evidências cartográficas finais.
  Não altera o front: a fonte das capturas e medições continua `650db81`. Foram preservadas as leituras
  privadas por ID congelado, conferência de hashes e pares CSV/GeoParquet, publicação por projeção
  positiva e admissão global de 15 jobs. Ibis permanece no extra opcional de conferência, sem substituir
  a ingestão. Passaram **319 testes focados**, sem falhas/skips, incluindo ambos os projetores públicos,
  leitura concorrente, retomadas, checkpoints, publicação, promoção e Ibis em DuckDB/SQLite. Ruff passou
  em 617 arquivos e o lock foi conferido (256 pacotes). Nenhum workflow foi cancelado ou desligado.
  A revisão completa será enviada ao CI; merge e auditoria do site continuam condicionados aos seus
  resultados, sem reaproveitar o CI de um HEAD anterior como aprovação da integração.

- Integração seguinte da main `fea0dd2` (PR #102, formatos imutáveis do Lote PA), sem conflito ou
  alteração do front/dependências/workflows. Passaram **440 testes focados**, sem falhas/skips, cobrindo
  formatos, quantis, metadados, histórico, CADT, atestação, verificador e nossos resumos públicos/ficha
  de crédito; Ruff passou nos 19 arquivos alterados. Os derivados e seus cartões de modelo continuam
  privados. Eles **não criam o anexo `ficha_credito v1`** nem a base comum de área elegível, exclusões e
  evidência exigida pela ficha; o aviso de ausência real permanece correto, sem inferir esses campos.
  Relatórios/caches do verificador privado não devem ir ao PR ou ao Pages. As evidências públicas do mapa
  continuam ligadas a `650db81`, sem repetir medições pela integração de arquivos do servidor.


## Visual V2 aprovado (13/11/2026)

O pacote `raiz-visual-v2-telas.zip` substitui o redesenho anterior ainda não entregue.
`LEIA-ME-TELAS.md` foi lido inteiro, os três prints foram inspecionados e o guia foi
incorporado em `docs/design/guia-front-v2.md`. A maquete não foi copiada para o produto:
o fundo continua Protomaps e os dados continuam nos contratos públicos/autenticados.

- [x] Comparação visual dos três prints registrada em [evidências V2](../design/evidencias-v2/README.md),
  com [Brasil](../design/evidencias-v2/depois-brasil.png), [pedido público](../design/evidencias-v2/depois-pedido.png),
  [celular](../design/evidencias-v2/depois-celular.png), antes/depois e [relatório de capturas](../design/evidencias-v2/relatorio-capturas.json).
  As capturas registraram zero erros HTTP, JavaScript, console e requisições falhas.
  Capturas finais `site-v2-13`, em 13/11/2026 às 21:09 de Brasília, Chromium 158;
  mesmo viewport/DPR das referências. Desempenho detalhado abaixo; CI final pendente.

A entrada ocupa a tela inteira, com base escura, fontes locais Bricolage Grotesque e
JetBrains Mono, cartão territorial e pedido flutuantes. H3 r4 no Brasil e r5 ao aproximar
substituem os círculos; a construção/consulta ocorre em worker. A escala identifica a
medida que realmente existe. O campo `fazendas` do agregado conta cadastros do CAR,
não apenas aptos, e grupos com medida ausente não viram zero. Não se presume bioma,
título ou porte a partir da localização. O produtor permanece claro.

O cartão soma os resumos municipais do motor; o contador cartográfico tem cobertura
própria. No snapshot público auditado usado para conferir o visual: 20.357.288 ha,
992.019 imóveis, 574.373 aptas e 102.621 com matrícula identificada nos resumos;
os desenhos abrangem 1.188 municípios/17 UFs. Esses valores são leitura dos arquivos,
não constantes do código. A data exibida vem do manifesto.

O painel compara os três lotes reais da publicação, com escala comum para P10/P50/P90,
hectares, número de fazendas, preço médio e fração da meta com terra pronta. O resumo
aberto não contém localização/composição; o destaque laranja fictício da maquete não
foi usado. O desenho autorizado depende de sessão real, API e liberação da ficha.
Reserva não informada continua ausente, em vez de copiar os 20% ilustrativos.
Desenhar área cria um critério editável; não recalcula os resumos estáticos nem envia
mensagem aos donos. E9 continua pendente das cartas reais, ainda não fornecidas.

Validação da revisão final do [PR #107](https://github.com/bernardoemmel/Raiz/pull/107):

- **647 testes do front em 62 arquivos**, TypeScript, build e verificador de design
  passaram. Main `a32523d` incorporada, preservando catálogo, API/MCP, produtor Preact
  e atualizações de dependências. A nova busca encontra estado, município e CAR;
  não depende da rota `/busca` do Pages.
- Playwright Pages completo: H3 r4/r5, Parauapebas, zoom, base com overzoom,
  satélite, filtros, hover, máscara, fontes atrasadas e privacidade; zero 404/JS.
  Entrada: 45 verificações, teclado e telas 360/390 px. Créditos recolhidos em botão
  de 48 px no celular, acessíveis por toque/teclado, sem esconder as fontes.
- Cena-alvo pública e autenticada passou: comparação em 390 px, axe, área transferida
  ao pedido, polígonos somente da API autorizada, bloqueio de ficha não liberada,
  troca de opção, fechamento e logout. Zoom 12 mantém o pedido e a autorização.
  Zero erros HTTP/JavaScript e zero envios de contato.
- Calendário, agentes, pasta, Acerto, pedido nacional, ficha de crédito e gráficos
  passaram, com 17 relatórios axe sem violações. Acerto foi novamente validado após
  estabilizar a ajuda durante o carregamento; teclado, versões e resposta atrasada.
- O portão Lighthouse local configurado no CI passou nas seis rotas, três amostras
  fixas por rota: medianas **Brasil 94, entrar 96, novo pedido 95, prospecção 95,
  Acerto 96, produtor 100**; acessibilidade mínima **100**. Esse portão usa a amostra
  controlada dos testes; não representa toda a base pública.
- Com o **retrato público completo**, a série final marcou **84/86/81** em desempenho
  (mediana **84**) e **100** em acessibilidade. A meta de 90 nesse cenário permanece
  pendente. As oito séries, incluindo as falhas, estão em
  [lighthouse-series.json](../design/evidencias-v2/lighthouse-series.json).
  Não houve redução do portão, cancelamento de workflow ou mudança das flags para
  favorecer a medição.

As otimizações mantêm mapa e dados disponíveis desde a abertura: GeoJSON serializado
no worker e lido por Blob pelo MapLibre; preparação das variantes gráficas reais;
montagem progressiva do estilo com a mesma ordem final; conteúdo extenso montado só
quando aberto. Os testes conferem estilo equivalente e cancelamento imediato dos
workers da aplicação. O dispatcher global nativo do MapLibre é reutilizado, sem
crescimento a cada navegação.

Ruff passou em 640 arquivos. A execução Python local registrou 3.241 aprovações,
319 skips, um xfail e uma falha pela ausência de `RAIZ_TESTE_PA_PASTA`. O CI da
revisão anterior do mesmo PR executou os serviços: **3.560 testes passaram**, um
excluído e um xfail; referência privada do Pará também passou. Esses resultados
não substituem o CI da revisão final. O merge permanece condicionado a todos os
checks verdes no HEAD enviado, sem force-push na main.

## Correção do CI após #107 (14/11/2026)

A execução `43533354039` da main anterior (`22e825c`, antes do visual V2) falhou
no Lighthouse com mediana 85. A execução `43536277877` do merge #107 (`59dac98`)
falhou antes, no teste Pages: a busca por Pará perdeu o foco e fechou os resultados
enquanto o efeito de navegação terminava. O passo Lighthouse foi ignorado nessa execução.

A correção preserva o foco em campos que a pessoa já está usando quando a rota
termina de carregar. Pages reproduz explicitamente a volta ao Brasil com foco na
busca antes do efeito da rota e exige que ele seja mantido. Limites, amostras e
configuração do Lighthouse permanecem intactos; nenhum arquivo de `motor/` mudou.

Na busca móvel, o foco é instalado junto com a abertura do diálogo, antes da
próxima pintura. Um evento `close` antigo não fecha um diálogo que já foi reaberto.
O teste de teclado aguarda o campo efetivamente focado antes de digitar.

Validação local da correção: Pages passou com zero 404/erros e o passo completo
de 360 px, teclado, axe e Lighthouse passou. Medianas: Brasil 94, entrar 96,
novo pedido 95, prospecção 95, Acerto 96 e produtor 100; acessibilidade mínima 100.
O CI do novo PR deve confirmar a revisão antes do merge.

Também passaram 647 testes do front e Ruff (683 arquivos formatados). O pytest
local foi interrompido na coleta por dependências ausentes (`cvxpy`, `pulp`,
`pysyncon`) no ambiente reutilizado; a suíte Python completa permanece obrigatória
no CI com o ambiente travado. Não foram alterados código nem dependências do motor.
