# Guia do front da Raíz, v1

Redesenho do front da Raíz (pesquisa de design, rodada 1). Isto é o resumo do que aplicar, já com as escolhas feitas. Aplicar em front/globo (analista, React) e front/produtor (produtor, Preact). Todo texto da interface em português do Brasil.

OBJETIVO
Hoje as telas têm cara de "feito por IA": cartões brancos iguais com sombra, Inter em tudo, raio 14 px em tudo, números grandes soltos, tudo com o mesmo peso, e o mapa mostra o polígono sozinho num fundo liso. A direção nova é "Cartografia de campo": a Raíz parece um bom mapa de levantamento de campo, não um painel de software. A primeira tela é o mapa plano do Brasil, já com fazendas e números, sem animação nem clique (item 3).

1. BASE (fazer primeiro, muda todas as telas de uma vez)
1.1 Trocar as variáveis de raiz.css e estilo.css por estas (apagar as antigas, inclusive --sombra e --raio 14):
```css
:root {
  --papel: #FAFAF7; --superficie: #FFFFFF; --tinta: #15231B; --pedra: #555D56; --nevoa: #E7EAE4;
  --mata: #1D6B44; --mata-texto: #16543A; --urucum: #C2521A; --urucum-texto: #9E3F0E;
  --agua: #1D69A6; --agua-texto: #175A8C; --terra: #A8741A; --terra-texto: #7E5510;
  --situacao-apta: #1D6B44; --situacao-pendencia: #E3A21A; --situacao-nao-apta: #C9C4BA; --restaurar: #5FA36E;
  --fonte-titulo: "Familjen Grotesk", system-ui, sans-serif; --fonte-texto: "Atkinson Hyperlegible Next", system-ui, sans-serif; --fonte-codigo: "IBM Plex Mono", ui-monospace, monospace;
  --t-legenda: 13px; --t-texto: 16px; --t-texto-produtor: 18px; --t-subtitulo: 21px; --t-titulo: 28px; --t-numero: 40px; --t-numero-produtor: 56px;
  --e1: 4px; --e2: 8px; --e3: 12px; --e4: 16px; --e5: 24px; --e6: 32px; --e7: 48px; --e8: 64px;
  --raio-botao: 6px; --raio-imagem: 2px; --raio-selo: 999px; --linha: 1px solid var(--nevoa);
  --curva: cubic-bezier(0.33, 1, 0.68, 1); --rapido: 200ms; --medio: 300ms;
}
* { box-shadow: none !important; }
body { background: var(--papel); color: var(--tinta); font: 400 var(--t-texto)/1.5 var(--fonte-texto); }
.numero, table td.num { font-variant-numeric: tabular-nums; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0ms !important; animation-duration: 0ms !important; } }
```
1.2 Fontes (todas SIL OFL 1.1, servir woff2 só do subconjunto latino, font-display: swap, hospedadas pela própria Raíz, via @fontsource):
- Familjen Grotesk 500 e 600 nos títulos (letter-spacing -0,01em).
- Atkinson Hyperlegible Next 400 e 700 no texto e em todos os números (tabular-nums em tabela e caixa de fatos).
- IBM Plex Mono 400 só para código do CAR, matrícula e coordenadas, no computador.
- Tirar a Inter do projeto inteiro. Não usar Geist, Fraunces nem nenhuma outra na interface (Fraunces fica só como opção para cartão e vídeo gerados no servidor).
1.3 Regras de forma:
- Seções separadas por espaço (48 px entre seções) e uma linha de 1 px var(--nevoa). Nada de cartão com sombra, nada de grade de cartões iguais.
- Raio por função: botão e campo 6 px, selo de situação em pílula, mapa e imagem 2 px. Seção não tem raio.
- Aviso = ícone e texto sobre fundo var(--nevoa), ou o formato do GOV.UK Warning text (círculo escuro com "!" e uma frase em negrito com a consequência). Proibido borda esquerda colorida e caixa vermelha.
- Proibido: rosa, magenta, roxo, degradê de enfeite, creme com terracota, texto sobre mapa ou satélite sem fundo sólido, CAIXA ALTA espaçada em rótulo, numeração 01/02/03 que não é etapa de verdade, "A · B · C" com ponto médio, seta em todo botão, emoji, travessão no texto.
- Um elemento principal por tela (o mapa ou o número principal), maior e mais pesado; o resto recua.
- Área de toque de pelo menos 48 px no celular. Texto nunca abaixo de 16 px no celular (18 px na ficha do produtor e no aceite).
- Urucum (#C2521A) é a cor de ação (botão principal com texto branco) e de número grande; nunca em letra pequena (para letra pequena usar --urucum-texto).
1.4 Verificador automático no repositório (script de lint rodado no build e nos testes) que falha se achar: box-shadow diferente de none, border-left colorido, linear-gradient de enfeite, text-transform: uppercase em rótulo, cor fora das variáveis, a fonte Inter, emoji ou travessão em texto da interface.
1.5 Ícones: lucide-react em front/globo e lucide-preact em front/produtor, importando ícone por ícone (20 px junto de texto, 24 px sozinho, traço 1,75 no computador e 2 no celular, cor currentColor). Gado e campo: SVG solto do Phosphor (Cow, Barn, Farm) ou Health Icons (animal-cow, agriculture, village), redesenhados no traço do Lucide; nunca o componente React do Phosphor. Ícone só ao lado do texto que ele explica, nunca sozinho em cima de cada bloco.
1.6 Números: sempre Intl.NumberFormat("pt-BR") (ponto no milhar, vírgula no decimal). Hectares inteiros a partir de 10 ha, uma casa abaixo de 10. Carbono e dinheiro com 2 algarismos significativos no destaque ("R$ 42 mil por ano", "4.200 t"), valor exato em "Ver como calculamos". Sempre unidade e período. Faixa para o analista: "cerca de 420 t por ano (de 310 a 530)" com barra clara de P10 a P90 e ponto escuro no P50. Faixa para o produtor: "Pelo menos R$ 31 mil por ano. Pode chegar a R$ 55 mil. Não é promessa." Nunca "R$ 42k". No máximo uma comparação por número, local e com fonte (nada de piscina olímpica).
1.7 Tom de voz: frase curta, ordem direta, voz ativa, número com unidade, nome completo antes da sigla ("Cadastro Ambiental Rural (CAR)"), dizer o que falta sem culpa ("Falta atualizar o CAR."), decisão com o dono ("Você decide. Nada acontece sem o seu aceite."). Evitar "solução inovadora", "potencialize", "jornada", "desbloqueie". Régua: art. 5º da Lei 15.263/2025 (linguagem simples).
1.8 Estados vazio, carregando e erro desenhados em todas as telas (inclusive "sem internet" na ficha do produtor, que mostra a última versão salva, e "município sem fazendas aptas").

2. MAPA (todas as telas com mapa)
2.1 Camadas, de baixo para cima:
(1) Fundo: no painel do município, base vetorial Protomaps (recorte do Brasil em PMTiles, estilo "white" recolorido com a paleta: terra #F1F2EE, água #CADDE6, rio #7FAFC4 com 0,6 px no zoom 8, 1,4 no 12 e 3 no 15; estrada #D2D4CE com miolo branco), com rios, estradas e nomes de cidade. Fontes e sprites do protomaps/basemaps-assets servidos junto do PMTiles. Crédito "© OpenStreetMap" visível. Na ficha da fazenda (zoom 12 a 16), recorte de satélite Sentinel-2 recente e sem nuvem da própria fazenda (o back-end gera; ver o outro bloco), cor natural levemente dessaturada (raster-saturation, raster-contrast), com o crédito "Contains modified Copernicus Sentinel data [ano]".
(2) Máscara fora do imóvel: polígono "mundo com furo" com #0F1A14 a 45% sobre satélite ou #F1F2EE a 60% sobre a base clara. Vizinhos continuam visíveis, apagados.
(3) Dentro do imóvel: mata em pé em verde chapado; área que pode voltar a ser mata SEMPRE em hachura diagonal a 45 graus (linha de 1,5 px a cada 8 px, #1D6B44 sobre base clara ou #B5DD7A sobre satélite), feita com fill-pattern (map.addImage de um canvas ou sprite); nunca só cor. A hachura diagonal quer dizer só isso e só aparece dentro da fazenda. Rio e APP em linha azul.
(3b) No painel do município, o chão sem imóvel do CAR (área sem imóvel, terra indígena, unidade de conservação) fica em névoa lisa, sem hachura, com a divisa fina tracejada e o nome por cima ("Terra indígena Kayapó", "Parque Estadual do Xingu"). Terra indígena e unidade de conservação vêm recortadas na divisa do município: nada pintado fora do contorno.
(4) Vizinhos do CAR: só contorno fino claro, sem preenchimento, a partir do zoom 12, tocáveis mostrando só situação e hectares (nunca nome nem CPF). Linha fixa embaixo do mapa: "Limites do CAR são declarados pelo dono e podem ter erro."
(5) Contorno duplo do imóvel: linha de fora branca de 6 px a 0,9 de opacidade e linha de dentro de 2,5 px #E9A23B sobre satélite (#15231B sobre base clara). Pode ser uma camada só com line-gap-width.
(6) Etiquetas em HTML com fundo sólido: nome do imóvel e cidade mais próxima com distância ("A 23 km de São Félix do Xingu"). Rótulos do mapa com halo de 1,5 px da cor do fundo.
(7) Escala: ScaleControl do MapLibre em km, mais uma linha para leigo: "412 ha, do tamanho de 577 campos de futebol" (1 campo = 0,714 ha); quando houver contorno urbano, preferir "do tamanho de 1,4 vez a área urbana de X".
(8) Minimapa "onde fica": SVG estático de 96 a 120 px (contorno dos estados em névoa, o estado destacado e um ponto no município ou na fazenda em urucum), no canto superior esquerdo com fundo sólido; nunca um segundo mapa WebGL. No celular vira uma linha: mini SVG de 64 px e "Fica no Pará, perto de São Félix do Xingu".
2.2 Cores de uso da terra (MapBiomas adaptado, com crédito "cores adaptadas do MapBiomas"): floresta #1F8D49, savana e campo nativo numa classe só #A9D38F, pasto #EDDE8E, lavoura numa classe só #B8892A com hachura (a legenda oficial pinta lavoura de rosa: proibido), água #2F6FD6, área urbana #8D8F88. Situação no município: apta #1D6B44, com pendência #E3A21A (rótulo escuro por cima), não apta #C9C4BA com hachura cruzada, área a restaurar #5FA36E. Toda cor de situação também tem rótulo ou textura.
2.3 Seletor de camadas: em vez de lista técnica, botões grandes com nome: Situação, Uso da terra, Título, Vizinhos. Uma camada de assunto por vez; o resto em cinza claro. Cada camada com menu de fonte, data e resolução ("MapBiomas coleção 11, 30 m, 2025").
2.4 Ícones no mapa: Maki e Temaki (CC0) num sprite feito com spreet, 15 px, #15231B com halo branco de 1 px (cidade, sede, nascente). Padrões do OSM Carto (CC0) para mata e área úmida, se ajudar.
2.5 Embaixo de todo mapa colorido, uma frase que diz o que a cor significa ("Verde-escuro é mata em pé; as listras são o pasto que pode voltar a ser mata.").

3. TELA DE ENTRADA (mapa do Brasil)
3.1 A primeira tela é o mapa plano do Brasil (base do item 2.1, Protomaps recolorido) com a busca "Código do CAR ou município" fixa no topo. Quem chega já vê fazendas e números, sem animação nem clique. A Raíz só trabalha no Brasil: a primeira tela não gasta tempo para dizer isso.
3.2 Sem busca: o Brasil inteiro. Municípios já processados com preenchimento leve em mata; os demais em névoa. Fazendas aptas agrupadas em círculos com o número dentro ("5,4 mil", nunca "5.4k") até a escala do município; polígonos só a partir dela. Ao lado (embaixo, no celular), uma frase com número real do banco ("A Raíz já leu 144 municípios (Pará): 345.870 imóveis do CAR..."), três números e os municípios com mais área para restaurar. Tocar num município faz o mesmo que buscar por ele.
3.3 Busca de município: o mapa vai até ele com flyTo (speed 1.2, curve 1.42, maxDuration 2.500 ms; acima disso o MapLibre pula direto), sem passar por zoom de mundo. As fazendas aparecem pintadas pela situação (apta, com pendência, não apta com hachura cruzada; item 2.2), o município escolhido perde o preenchimento e os círculos dele somem (quem fala ali é cada fazenda). Abre o painel do município (item 4), com a frase antes de qualquer número e o funil em barras ligado ao mapa. Município só com o resumo mostra o funil sem a lista; município de estado ainda não processado mostra onde fica e diz que ainda não foi lido. A busca acha também os municípios sem dados pelo nome (estão no contorno do Brasil).
3.4 Busca de código do CAR: direto para a ficha da fazenda. Do município à fazenda: fitBounds com padding 48 px em 900 a 1.200 ms; só depois do moveend acender máscara e contorno em 250 a 300 ms. Total abaixo de 4 s.
3.5 Movimento: a primeira carga enquadra sem voo (jumpTo). Aparelho fraco (deviceMemory até 2, hardwareConcurrency até 4 ou saveData) ou "reduzir movimento": sempre jumpTo. Nunca essential: true em animação decorativa. pixelRatio no máximo 2, fadeDuration 150, sem 3D nem inclinação.
3.6 "Onde fica" é o minimapa em SVG do item 2.1 (8), no canto do mapa e ao lado do nome do município.
3.7 Celular (360 px): busca no topo, mapa no resto da tela, painel como gaveta que sobe de baixo. Sem município, a gaveta fica baixa (só o título); com município, sobe até a metade; tocar ou arrastar a alça leva até quase a tela toda. O voo enquadra o município na parte do mapa que a gaveta não cobre.
3.8 No cabeçalho, duas portas: "Sou comprador ou desenvolvedor" e "Sou produtor rural".

4. PAINEL DO MUNICÍPIO
4.1 Topo: frase gerada a partir dos dados, no lugar da fileira de cartões ("Dos 9.703 imóveis no CAR de São Félix do Xingu, 297 estão prontos para conversar; a maior perda está na falta de matrícula."). Testar com dado faltando (nunca "Em {ano}").
4.2 Funil como barras horizontais que afinam, alinhadas à esquerda, com o nome da etapa em palavras simples, o número e a % da etapa anterior. O que saiu em cada etapa fica como contorno claro do tamanho da etapa anterior, com os 2 ou 3 motivos escritos ao lado ("820 sobrepõem unidade de conservação, 312 com embargo do Ibama"). Cada barra dividida por porte (pequeno, médio, grande) em três tons do mesmo verde, porque os pequenos vão para o projeto agrupado. Botão "imóveis | hectares". Nada de funil em cone. Desenhar em SVG próprio ou visx.
4.3 Ligar funil e mapa: tocar numa barra deixa só aqueles imóveis coloridos e o resto em branco com a divisa em névoa (não somem; a névoa é do chão sem imóvel); tocar no contorno de perda mostra os excluídos coloridos pelo motivo. Responder em menos de 200 ms.
4.4 Cabine apagada: o que está normal fica sem cor; só o que pede ação acende, num contador no topo ("7 fazendas pedem atenção") que abre os grupos e depois a fazenda no mapa. Quadro "Desde a última análise" (quantas subiram e quantas desceram de etapa).
4.5 Lista de fazendas aptas como tabela de colunas fixas (fazenda, hectares a restaurar, carbono por ano, título, situação), números à direita em tabular-nums, frase de ajuda curta no cabeçalho de cada coluna e linha "Total da seleção" que acompanha os filtros e bate com o último número do funil. Passar o mouse numa linha acende o polígono no mapa e vice-versa; botão "só o que está no mapa".
4.6 Modo "agrupar": pequenas fazendas aptas vizinhas ganham o mesmo contorno e uma etiqueta com a soma ("5 vizinhas, 380 ha juntas"), usando a regra de agrupamento do motor.
4.7 Selo de nível em cada fazenda da lista, escrito por extenso: bronze = achada no CAR, prata = título conferido, ouro = dono aceitou (cores de metal discretas, nunca só a cor).
4.8 Componentes de aba, janela e dica: Radix Primitives estilizados pelo guia (nunca o tema padrão do shadcn). Lista que reordena com AutoAnimate (3,4 KB) e números que mudam com NumberFlow (5,1 KB), só nos 2 ou 3 números principais.

5. FICHA DA FAZENDA (analista)
5.1 Ordem fixa dos blocos (molde do laudo do MapBiomas Alerta): faixa escura no topo com nome da fazenda, município e estado; veredito; o mapa no satélite (elemento principal); caixa de fatos; antes e depois; "por que é apta" item a item; situação do título; fonte e método no fim; botão "versão para imprimir" (A4) e PDF.
5.2 Veredito no topo: Apta, Apta com pendência ou Não apta, com o principal motivo numa frase, e um título em linguagem de anúncio gerado dos dados ("Fazenda de pasto com nascente e 40 ha de mata ciliar para recompor"). Um único número principal ("312 ha podem voltar a ser mata") com uma frase embaixo; carbono e floresta em pé descem para uma linha secundária.
5.3 Caixa de fatos como rótulo nutricional: preto sobre branco; título "Fatos da fazenda" em Familjen 600; logo abaixo "a cada 100 ha desta fazenda, em 10 anos"; barra de 10 px; duas colunas "Se nada mudar" e "Se restaurar" (só a segunda com cor de destaque); blocos sempre na mesma ordem separados por barra de 4 px: TERRA (mata nativa em pé, ha; área que volta a ser mata, ha), CLIMA (gás carbônico tirado do ar, t, com a faixa em letra pequena), DINHEIRO (receita possível, R$; custo de restaurar, R$), LEI (o que falta para ficar em dia com o Código Florestal, ha); filete de 1 px entre linhas; números à direita em tabular-nums com a unidade em peso normal; nenhuma célula vazia ("0" ou "não se aplica"); rodapé com fontes, data e "conferir no dado público". Embaixo, um gráfico de duas linhas em 10 anos ("se nada mudar" e "se restaurar") com a área entre elas rotulada como o ganho. Separar o que conta na meta FLAG da empresa (silvipastoril, cacau) do que vai para crédito Verra ou compensação (restauração, reserva legal, APP, capoeira); nunca somar as duas na mesma tonelada.
5.4 Composição da área: barra única com mata em pé, pasto, para restaurar, água e "sem dado", com os hectares escritos ao lado; grade 10 x 10 em SVG (cada quadradinho é 1 ha da base de 100 ha) com as três classes em blocos contínuos (mata em pé verde escuro, pode voltar listrado, continua pasto areia), sempre com o número escrito ao lado; faixa fina do uso da terra ano a ano (1985 até hoje).
5.5 "Por que é apta": lista de 8 a 13 linhas fixas, na mesma ordem em todas as fazendas (embargo Ibama, terra indígena, unidade de conservação, quilombo, CAR ativo, matrícula, desmatamento recente, alerta, etc.), em dois grupos com título: "Decide" (tira a fazenda da lista) e "Só informa". Cada linha com ícone de forma (certo, alerta, x; não só cor), fonte e data, e as quatro partes fixas: título curto, o que significa, o que fazer, detalhe técnico (fechado). Item que não pesa fica em cinza. Nunca célula vazia. Fecha com "O que falta resolver", com o próximo passo de cada pendência. Sem pendência: uma linha só, "Sem pendências: apta para restaurar".
5.6 Bloco fixo "Informações que mudam a decisão": tipo de posse (matrícula, posse, assentamento), matrícula, sobreposições, embargos, sempre os mesmos campos na mesma ordem, com "Ainda não conferido" quando faltar dado.
5.7 Antes e depois: cortina com @maplibre/maplibre-gl-compare (ISC, 3,5 KB) ou maplibre-gl-swipe, lado esquerdo "Hoje, [ano]" com o satélite e lado direito "Se restaurar (simulação)" com a área que pode voltar desenhada em textura de copa e o selo "Simulação"; instrução "Arraste para comparar"; régua com 1985, 22/07/2008, hoje e daqui a 10 anos. Nunca foto realista gerada por IA do futuro. No mapa geral, até três letras (A, B, C) sobre os lugares que importam (nascente sem mata, pasto degradado, mata em pé); tocar abre o par antes e depois com o ano escrito.
5.8 Toda imagem de satélite com legenda fixa de uma linha: título curto, (mês/ano, fonte), uma frase com o lugar e o que olhar.
5.9 Rodapé com a faixa de fontes públicas (CAR, MapBiomas, INPE, Ibama, INCRA) e o código do CAR com link para conferência pública.

6. FICHA DO PRODUTOR (front/produtor, celular Android barato, link do WhatsApp)
6.1 Peso: HTML pronto no servidor que se lê sem JavaScript; até 150 KB comprimidos na primeira tela (HTML com CSS embutido até 20 KB, uma foto de satélite WebP de 40 a 80 KB com o contorno já desenhado na imagem, SVG embutido até 5 KB, JavaScript opcional até 15 KB). Fonte: Atkinson 400 e 700 em subconjunto latino; com o cabeçalho Save-Data ou economia de dados, usar system-ui (Roboto no Android, zero KB). Sem mapa interativo de início: o Leaflet com PMTiles só carrega quando ele tocar em "Abrir no mapa". Medir o peso a cada publicação (teste automático que falha acima do orçamento).
6.2 O link abre direto na fazenda dele, nunca na página inicial.
6.3 Ordem: (1) a foto da terra dele vista de cima com o contorno, o nome do imóvel e o município, como capa de certificado; (2) o número principal grande (56 px) "212 hectares da sua terra podem voltar a ser mata", uma frase de comparação e uma linha de situação ("Pode entrar" ou "Falta 1 coisa"), com a grade 10 x 10; (3) "O que você já fez certo": 2 ou 3 fatos reais do dado (omitir se não houver); (4) "O que você pode ganhar": "Pelo menos R$ X por ano. Pode chegar a R$ Y. Não é promessa, depende do comprador.", em duas colunas "Deixar como está | Restaurar" com as mesmas linhas e um "Ver como calculamos" fechado; (5) "O que falta ficar em dia": lista no molde GOV.UK Task list, só 2 ou 3 estados escritos em palavra (Em dia, Falta resolver, Depende de outra etapa), o que está em dia sem cor, cada situação do SICAR e do INCRA traduzida numa frase fixa com "o que você precisa fazer" (muitas vezes "nada por enquanto"); número sensível (déficit de reserva legal) numa linha com uma única marca escrita "a lei pede a partir daqui", sem semáforo; (6) "Onde fica": distância e direção da cidade ("a 14 km de X, pela estrada Y"), mini mapa do estado em SVG; (7) "Em que pé está": caminho vertical de 5 passos com "Você está aqui" (Encontrada, Conferida, Você aceitou, Comprador interessado, Mata voltando), datas quando houver; (8) "De onde vêm estes dados": CAR que ele mesmo declarou, MapBiomas, INPE, com a data, "Ninguém entrou na sua terra" e "Nada acontece na sua terra sem a sua assinatura", com botão "Conferir no governo" para o demonstrativo público do CAR; (9) dois botões grandes: "Mandar para a família no WhatsApp" (wa.me com a frase e o link) e "Quero conversar" (vai para o aceite), mais "Falar com uma pessoa".
6.4 Blocos que só aparecem quando importam (pendência, aviso), como no aplicativo de clima. Botões A+ e A- para letra maior. Texto 18 px, entrelinha 1,5, contraste de pelo menos 7:1.
6.5 Antes e depois sem mapa: duas imagens WebP de 480 px (hoje e "como pode ficar em 10 anos, simulação") dentro do img-comparison-slider (MIT, 3,6 KB), com rótulo fixo e fundo sólido em cada lado e a barra começando no meio; sem JavaScript, as duas aparecem uma embaixo da outra com legenda.
6.6 Guardar para ver sem internet: service worker com cache da página e da foto, com "Atualizado em [data]" bem visível.
6.7 Open Graph para o WhatsApp: og:title com nome do imóvel e município, og:description com a frase principal (até 80 caracteres), og:image com o cartão de 1200 x 630 abaixo de 250 KB, head nos primeiros 300 KB do HTML, og:url sem dado pessoal.

7. ACEITE
7.1 Antes do termo, uma folha-resumo com perguntas fixas, sempre na mesma ordem: O que você aceita, O que você não está prometendo, Qual parte da fazenda, O que você precisa fazer, O que pode mudar, Como desistir (sempre visível). Cada uma com 1 a 3 linhas geradas com os dados da fazenda e um botão "Não entendi" que manda a dúvida para a equipe. A mesma folha vira PDF de uma página.
7.2 Uma pergunta por tela (é sua esta fazenda? os limites estão certos? aceita aparecer para compradores?), com "Voltar", a pergunta como título grande e "Não sei, quero falar com alguém" (abre o WhatsApp). Telas no mesmo arquivo leve, trocando só o conteúdo.
7.3 Tela "Confira antes de aceitar" com 4 ou 5 linhas (fazenda, área, o que será mostrado, quem vai ver) e "Mudar" em cada uma; acima do botão, a foto pequena da fazenda e os 4 fatos, para ele saber sobre qual terra está aceitando. Botão diz exatamente o que acontece ("Aceito que a Raíz mostre minha fazenda a compradores").
7.4 Confirmação: número do aceite, "o que acontece agora" em 3 passos com prazo, telefone de contato e botão (fora do painel) para salvar o comprovante como imagem.
7.5 Mesmo pacote leve da ficha do produtor; zero JavaScript obrigatório para ler.

8. CARTÃO DO WHATSAPP (gerado no servidor com o Takumi, que já está no projeto)
8.1 Três saídas por fazenda: prévia de link 1200 x 630 abaixo de 250 KB (o WhatsApp descarta acima de cerca de 300 KB); cartão em retrato 1080 x 1350 de 150 a 350 KB; adesivo PNG transparente (contorno da fazenda e um número) abaixo de 300 KB, para o produtor pôr sobre a foto dele no Status.
8.2 Desenho: município e estado em cima; satélite da fazenda no meio com contorno branco de 3 px e borda escura de 1 px, área a restaurar em hachura verde, entorno esmaecido; embaixo, sobre fundo liso (nunca texto sobre a imagem), um número de 110 a 130 px ("212 hectares podem voltar a ser mata") e no máximo dois números de apoio; rodapé com logotipo pequeno, "Dados públicos: CAR, MapBiomas, INPE", crédito do satélite e link curto. Nenhum texto abaixo de 40 px na arte de 1080 px.
8.3 Privacidade: o cartão compartilhável mostra município, hectares, selo e um código curto que abre a ficha pública; local como mancha aproximada. Nome do imóvel, código do CAR e polígono exato só depois do aceite do dono, e só dentro da ficha.

9. VÍDEO POR FAZENDA (30 s, gerado no servidor)
9.1 Takumi renderAnimation + FFmpeg (no servidor) + voz Qwen3-TTS lendo exatamente o texto da tela. Sem Remotion, sem ffmpeg.wasm.
9.2 1080 x 1920, 30 quadros por segundo, H.264 perfil High, yuv420p, CRF 26 com teto de 2,5 Mbps, AAC mono 96 kbps, +faststart; também 720 x 1280 com teto de 1,2 Mbps. Comando base: ffmpeg -i quadros_%04d.png -i voz.wav -c:v libx264 -profile:v high -pix_fmt yuv420p -r 30 -crf 26 -maxrate 2500k -bufsize 5000k -c:a aac -b:a 96k -ac 1 -movflags +faststart fazenda.mp4
9.3 Roteiro em 6 quadros: 0 a 3 s Brasil com ponto no município; 3 a 7 s aproximação até o satélite e o contorno se desenhando ("São 480 hectares"); 7 a 13 s camadas uma a uma ("Hoje: 30% mata, 70% pasto"); 13 a 20 s a hachura de restauração cresce a partir da beira do rio ("212 hectares podem voltar a ser mata"); 20 a 26 s um número por vez com comparação ("Em 10 anos: cerca de 21 mil toneladas de carbono"); 26 a 30 s quadro final igual ao cartão, com o link e "Dados públicos: CAR, MapBiomas, INPE" e o crédito do satélite.
9.4 Legenda queimada: no máximo 2 linhas de 42 caracteres, até 13 a 15 caracteres por segundo, 56 a 64 px peso 700 em branco sobre faixa #15231B a 88%, no terço de baixo e fora dos 250 px de cima e 300 px de baixo. Uma informação nova a cada 3 a 6 s, câmera lenta e contínua.

10. IDENTIDADE (pode ir em paralelo)
10.1 Logotipo: "raíz" em minúsculas na Familjen ajustada, com o acento agudo virando um pequeno ramo, e um símbolo de linhas que se ramificam para baixo, que é ao mesmo tempo raiz e rio com afluentes. Uma cor, legível a 16 px e dentro de círculo (foto do WhatsApp). Passa no teste do graveto (dá para desenhar no chão). Propor 3 versões em SVG.
10.2 Ilustração: pranchas botânicas da Flora Brasiliensis (domínio público pela idade), uma espécie nativa por bioma, em uma cor (#15231B ou #1D6B44), WebP de 600 px. Só usar arquivo com selo de domínio público conferido item a item (Wikimedia Commons ou Biodiversity Heritage Library; crédito "Image from the Biodiversity Heritage Library. Contributed by [instituição]"). Não baixar do site do CRIA (reuso não confirmado). Nada de unDraw, Open Peeps ou ilustração de pessoa genérica.
10.3 Página de créditos e licenças (MapBiomas CC BY 4.0 com a citação no formato deles, Copernicus, OpenStreetMap, fontes OFL, BHL quando usar).

11. LICENÇAS (proibido no produto)
Satélite EOX cloudless 2018 a 2024 (não comercial), Esri World Imagery, Planet NICFI (acabou em 1/4/2025), Base Cartográfica do IBGE (veda comercialização; tirar rios e estradas do OpenStreetMap), ApexCharts, Highcharts, Handsontable, AG Grid Enterprise, amCharts, Grafana e Metabase (AGPL), tldraw, Remotion, ffmpeg.wasm (GPL no navegador), GSAP, editor do Theatre.js (AGPL), OpenMoji (CC BY-SA), Remix Icon, unDraw, CARTOColors e Colorcet (exigem crédito), fonte Rawline (sem licença conferida). Registrar no NOTICE.md tudo que for copiado.

12. ORDEM DE TRABALHO
1) Base: variáveis, fontes, ícones, regras de forma e o verificador (item 1).
2) Mapa: Protomaps recolorido, contorno duplo, máscara, etiqueta da cidade, escala e minimapa (itens 2.1 e 2.2); depois satélite por fazenda quando o back-end entregar.
3) Painel do município: frase, funil em barras ligado ao mapa, tabela, cabine apagada (item 4).
4) Ficha da fazenda: veredito, caixa de fatos, por que é apta, composição (itens 5.1 a 5.6); depois antes e depois (5.7).
5) Ficha do produtor e aceite (itens 6 e 7).
6) Cartão e vídeo (itens 8 e 9).
7) Tela de entrada: mapa do Brasil com a busca no topo (item 3).
8) Identidade: logotipo e ilustração (item 10).
Abrir um PR por etapa, com print antes e depois de cada tela (computador 1440 px e celular 360 px).

COMO CONFERIR CADA TELA
- Teste dos 5 segundos: uma pessoa de fora diz onde fica a fazenda e o que tem em volta olhando só o mapa.
- Pergunta "isso sairia igual para qualquer outro produto?": se sim, refazer aquela parte.
- Lighthouse em celular simulado com rede lenta: ficha do produtor abre em menos de 3 s em 3G.
- Simulador de daltonismo (protanopia, deuteranopia, tritanopia) sem duas classes iguais.
- Verificador do item 1.4 passando em todas as telas.
