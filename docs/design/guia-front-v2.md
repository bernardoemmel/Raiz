# Guia do front da Raíz, v2

Visual aprovado em 13/11/2026 para `front/globo`, analista e comprador. O conteúdo aprovado do pacote
`raiz-visual-v2-telas.zip` está reproduzido integralmente abaixo, acompanhado das condições de aplicação aos
contratos reais. O produtor em `front/produtor` continua claro, com o [guia v1](guia-front-v1.md).

## Escopo e leitura das referências

Este guia substitui, no analista, os itens **1.1, 1.2, 2.1 (somente a base do mapa) e 3.2b** do v1. Também prevalecem
as medidas, disposição dos painéis e as exceções restritas de rótulo descritas aqui quando conflitarem com o v1.
As demais regras continuam, incluindo dados ausentes explícitos, fonte e data, acessibilidade, privacidade,
licenças, proibição de sombra, degradê decorativo, Inter, emoji e travessão. A restauração continua com hachura;
a base escura não transforma um cadastro em fazenda apta.

Os três prints do pacote são as referências visuais para o comparativo Playwright anexado à entrega:

| Referência | Tela | Viewport em pixels CSS |
|---|---|---|
| `print_brasil.png` | Brasil, cartão e controles flutuantes | 1440 × 900 |
| `print_pedido.png` | Pedido e três opções de lote | 1440 × 900 |
| `print_celular.png` | Gaveta e topo compacto | 390 × 844 |

Os arquivos de imagem têm, respectivamente, 2880 × 1800, 2880 × 1800 e 1170 × 2532 pixels físicos.
Números, datas, cobertura e territórios mostrados na maquete são referências de composição: a aplicação usa o
retrato real publicado, com seus valores, nulos, datas e limitações. Não repetir os números do print em constantes.
A maquete usa **Carto apenas para o teste visual**. O produto continua com Protomaps, PMTiles e créditos visíveis.

## Condições factuais de implementação

- O campo `fazendas` de `geo/agregados_brasil.geojson` conta **cadastros do CAR**, não apenas fazendas aptas.
  Enquanto esse contrato não trouxer a aptidão agregada, escrever "cadastros por hexágono" na legenda e
  "cadastros" na etiqueta, mesmo quando o print usar "fazendas aptas". A seleção de situação não pode aparentar
  filtrar esse agregado quando a fonte não oferece o recorte.
- `potencial_ha` é uma soma pública parcial da área medida elegível, sujeita às exclusões e à supressão de células
  com poucos contribuintes. `null` significa desconhecido ou suprimido, nunca zero. A soma de pais H3 preserva
  a indicação de cobertura parcial. Só trocar a escala para hectares quando houver cobertura completa comprovada.
  Exibir a fonte e a data; não interpretar hectares parciais como disponibilidade de venda ou crédito emitido.
- O cartão só chama um número de "aptas" ou "prontas, com título" quando a fonte tiver esse significado.
  Se a medida não estiver publicada, mostrar "não informado" ou "ainda não publicado". Não estimar com proporções
  fixas e não somar cadastros sobrepostos como se fossem área independente.
- A **posição laranja do lote na maquete é ilustrativa**. Não selecionar células por proximidade ou densidade
  para imitar seu desenho. O contorno do lote vem da geometria autorizada da API e do resultado real do otimizador.
  Quando essa geometria faltar, a tela mantém o resumo verdadeiro e informa que o desenho está indisponível.
- No site aberto, os lotes mostram apenas o resumo permitido: P10/P50/P90, hectares, quantidade de fazendas,
  preço médio e parte da meta com terra pronta. Identidade dos integrantes, geometria de seleção, tabela por
  fazenda, travas e "o que destrava" continuam na área autenticada, lidos pela API. Nenhum arquivo pago migra
  para o Release público. Nunca mostrar nome, CPF ou contato do dono. Não ligar simulação automaticamente para
  preencher uma lacuna do banco: nesta entrega, todos os números apresentados como resultado são reais.
- "Buscar interesse dos donos" encaminha à etapa final e ao fluxo autorizado. A mudança visual não dispara
  contatos. "Desenhar área" usa o desenho real do pedido e não uma posição ilustrativa.
- A classe `.rot` é um rótulo em JetBrains Mono. Só ela pode declarar `text-transform: uppercase`; a exceção não
  alcança `.rotulo`, irmãos ou seletores globais. Ponto médio é permitido somente no conteúdo desse rótulo.
  Para partes dinâmicas, usar `RotuloMono` com a propriedade `partes`; seu separador fica dentro de `.rot`.
- Cores CSS V2 são declaradas no `:root` de `front/globo/src/raiz.css`; cores para MapLibre ficam em
  `front/compartilhado/cores.ts`. Os demais estilos consomem variáveis. O v1 continua em `compartilhado/base.css`
  para preservar o produtor. Fontes antigas do produtor não são uma autorização para importá-las no analista.
- A escala de dados do botão Camadas pode ser desenhada em SVG com os seis tons reais. Não usar
  `conic-gradient` decorativo nem abrir uma exceção geral de degradê no verificador.

## Conteúdo aprovado do pacote

### Visual novo da Raíz (v2): instruções para o chat Telas

Aprovado pelo Bernardo em 13/11/2026. Ele achou o visual atual "padrão demais": coluna lateral, letra e bolas verdes. O mapa em si ele aprovou e fica.

Conteúdo deste pacote:
- `print_brasil.png`, `print_pedido.png`, `print_celular.png`: o resultado esperado. A tela tem que ficar igual a eles.
- `maquete/index.html`: a maquete navegável que gerou os prints (MapLibre + h3-js + `agregados_brasil.geojson` real). Para abrir: `cd maquete && python3 -m http.server 8765` e acesse `http://localhost:8765/index.html?tela=brasil` (ou `tela=pedido` ou `tela=celular`). Use como referência de medidas, cores e comportamento. Não copie a maquete para o produto: a base de lá é Carto dark-matter só para teste, e o produto continua com Protomaps.

Onde mexer: `front/globo` (React), principalmente `src/raiz.css`, `src/fontes.css`, `src/App.tsx`, `src/mapa/MapaBrasil.tsx`, `src/partes/PainelBrasil.tsx`, `src/partes/PainelCobertura.tsx`, `src/partes/Cabecalho.tsx` e as telas do pedido (`src/telas/NovoPedido.tsx`, `src/telas/PedidoTela.tsx`, `src/partes/pedido/`).

## 1. Layout: sem coluna lateral

- O mapa ocupa 100% da tela, em todas as larguras.
- **Topo** (flutuando sobre o mapa, a 16 px das bordas, altura 44 px, tudo em pílula com raio 22 px): marca "Raíz", busca "CAR, município ou estado" (até 380 px de largura), filtros em pílulas (`Bioma todos`, `Situação apta`, `Título qualquer`, `Tamanho todas`, com o valor em letra mono cinza), espaço, depois `Minha cadeia`, `Carteira`, botão urucum `Fazer pedido` e o ícone da conta. As outras abas do menu atual (Pedidos, Calendário, Fazendas, Acerto, Projetos agrupados) vão para o menu da conta. Nada quebra linha: `white-space: nowrap`.
- **Cartão do número** (canto inferior esquerdo, largura 400 px, raio 14 px, padding 22 px): rótulo mono "Brasil · terra para restaurar", número gigante "20,4 mi ha" (o número em lima, "ha" menor em branco), uma frase curta, linha fina e três números lado a lado (`imóveis lidos`, `fazendas aptas`, `prontas, com título`). Tudo vem do banco, nunca fixo no código. Ao entrar num estado ou município, o mesmo cartão troca para os números dele, e o caminho Brasil / estado / município fica no rótulo de cima.
- O texto longo da coluna atual (cobertura, processamento por estado, fontes) sai da tela principal. Vai para um "Sobre os dados" aberto por um link pequeno no rodapé do cartão, e o processamento por estado fica na página de cada estado.
- **Camadas** (direita, centralizadas na vertical, estilo Windy): `Fazendas aptas` (ligada), `Uso da terra`, `Título`, `Desmatamento`, `Vizinhos`. Cada uma é um nome em pílula com um círculo de 34 px ao lado. A ligada fica em branco e o círculo mostra as cores da escala. Uma camada de assunto por vez.
- **Legenda** (embaixo, centralizada): "Fazendas aptas por hexágono (cada um ~1.800 km²)", seis hexágonos com a escala e os limites em mono embaixo.
- **Status** (canto inferior direito, mono 11 px, cinza): ponto verde e "1.188 municípios · 17 estados / atualizado 13/11 17:23", com dados reais.
- Todos os painéis flutuantes têm fundo sólido (`--vidro`, 92% opaco ou mais), borda de 1 px `--linha` e nenhuma sombra.

## 2. Hexágonos no lugar das bolas verdes

- Apagar as bolas verdes dos grupos com os dois números empilhados (`src/mapa/marcadores-grupos.ts`, `grupos.worker.ts`, `worker-grupos.ts`, `aquecer-simbolo.ts` e `shader-simbolo.generated.ts`, usados em `MapaBrasil.tsx`). A lista acessível de grupos (`cartografia-grupos-lista`) continua, agora listando hexágonos.
- Fonte: o mesmo `geo/agregados_brasil.geojson` que já é publicado (pontos com `h3` de resolução 5, `fazendas` e `potencial_ha`). O `h3-js` já está nas dependências.
- No Brasil inteiro (zoom menor que 5), agregar para a **resolução 4** com `cellToParent` somando `fazendas` e `potencial_ha`. No estado (zoom 5 a 8), usar a **resolução 5** como vem. Desenhar os polígonos com `cellToBoundary(h3, true)` e fazer o cálculo no worker que já existe.
- Pintar com uma camada `fill` em degraus (step) de 6 tons. Os limites mudam com a resolução:
  - Resolução 4: 1 / 60 / 200 / 500 / 1.100 / 2.500+
  - Resolução 5: 1 / 15 / 40 / 90 / 200 / 450+
  - Cores, do menor para o maior: `#163A2A #1E5E3C #2C8050 #49A363 #7CC47A #C9E88F`.
  - `fill-opacity` 0,92 e linha de 0,5 px na cor do chão (`#111815`), para cada hexágono aparecer separado.
  - Quando `potencial_ha` estiver preenchido em todo o país, pintar por ele e não por `fazendas`. A legenda acompanha.
- Do zoom 9 em diante (município), os hexágonos somem em 300 ms e aparecem os contornos das fazendas, como já é hoje.
- Passar o mouse num hexágono mostra uma etiqueta pequena com fundo sólido: "38 fazendas aptas · 4.120 ha". Clicar aproxima.
- Os hexágonos ficam embaixo dos rótulos de cidade (inserir antes da primeira camada `symbol`).

## 3. Base do mapa: escura

- Continuar com Protomaps (PMTiles), recolorido para escuro: fundo e terra `#111815`, água `#0A0F0E`, divisa de estado `#3A4A42` com 0,8 px, divisa de país `#56665D`. No zoom do Brasil, esconder estradas e trilhos. Rótulos em português (`name:pt`, com `name` como reserva), cinza claro com halo escuro.
- Na ficha da fazenda continua o satélite Sentinel-2.

## 4. Letra

- Sai Familjen Grotesk e Atkinson Hyperlegible Next. Entram **Bricolage Grotesque** (títulos e texto: 400, 500, 600, 700, 800) e **JetBrains Mono** (números, rótulos e códigos: 400, 500, 700). As duas são SIL OFL. Instalar `@fontsource/bricolage-grotesque` e `@fontsource/jetbrains-mono`, servir só woff2 latino, como o `fontes.css` já faz. Registrar no `NOTICE.md` e nas licenças.
- Número gigante: Bricolage 800, 64 px (48 px no celular), espaçamento -0,035em, cor lima.
- Números de tabela e cartão: JetBrains Mono 700, 17 a 18 px, `tabular-nums`.
- Rótulos pequenos: JetBrains Mono 500, 11 px, caixa alta, espaçamento 0,08em, cinza.
- Texto: Bricolage 400, 15 px (16 px no celular).

## 5. Cores (substituem as de `raiz.css`)

```css
:root {
  --chao: #0D1311;      /* fundo do app */
  --vidro: #101714EB;   /* painéis flutuantes */
  --linha: #26312C;     /* bordas finas */
  --tinta: #EEF2EC;     /* texto */
  --pedra: #8E9A92;     /* texto secundário */
  --mata: #7CC47A;      /* verde de dado */
  --lima: #C9E88F;      /* número principal */
  --urucum: #E8713A;    /* ação; texto do botão #1A0D05 */
  --t: "Bricolage Grotesque", system-ui, sans-serif;
  --n: "JetBrains Mono", ui-monospace, monospace;
}
```

As cores de situação (apta, pendência, não apta) e as do MapBiomas, nas telas de município e fazenda, continuam as do guia v1, só ajustadas para contraste sobre o fundo escuro (AA). As telas do produtor (`front/produtor`) **ficam claras**: a mudança vale para o analista e o comprador.

## 6. Pedido (print_pedido.png)

- Ao clicar em `Fazer pedido`, o botão vira `Pedido aberto` e um painel desliza da direita (largura 430 px, de 76 px do topo até 16 px do fim, raio 14 px).
- Cabeçalho do painel: rótulo mono "Pedido · Pará · reserva de 20%", título "1 milhão de créditos." e, na linha de baixo, "3 lotes cobrem o pedido." com "3 lotes" em lima. Embaixo, abas `Mais barato | Mais seguro | Mais compacto`.
- Um cartão por lote: nome, selo "no mapa" ou "ver no mapa", três números (fazendas, hectares a restaurar, créditos prováveis = P50) e uma faixa de P10 a P90 com o ponto no P50, com "pior caso X mi" e "melhor Y mi" embaixo. O lote escolhido tem borda urucum.
- No mapa, os hexágonos do lote escolhido ficam com opacidade 0,95 e contorno urucum de 2,2 px. Os outros caem para 0,35. Uma etiqueta urucum fica em cima do lote: "Lote mais barato · 9.561 ha".
- Rodapé do painel: `Desenhar área` (secundário: o cliente risca no mapa onde quer o lote, como no QuintoAndar) e `Buscar interesse dos donos` (urucum).
- Os números vêm do resultado real do otimizador (`pedidos.ts` e o Release). Nada fixo no código.

## 7. Celular (print_celular.png)

- Topo: só marca, ícone de busca e `Fazer pedido`.
- Mapa inteiro, com o cartão do número como gaveta embaixo (8 px das bordas, raio 18 px em cima): rótulo, número de 48 px, frase e os três números. Arrastar a gaveta para cima mostra o resto.
- Camadas e legenda ficam num botão "Camadas" que abre outra gaveta.

## 8. Guia e verificador

- Criar `docs/design/guia-front-v2.md` com este conteúdo e marcar o v1 como substituído nos itens 1.1, 1.2, 2.1 (base escura) e 3.2b (hexágonos no lugar dos círculos).
- No `front/scripts/verificar-design.mjs`, liberar rótulo em caixa alta só na classe do rótulo mono (`.rot`) e o ponto médio só nos rótulos mono. Proibir Familjen Grotesk e Atkinson no analista. O resto das proibições continua (sombra, degradê de enfeite, Inter, emoji, travessão).

## 9. Conferir antes do PR

- Tirar print com Playwright de `/`, de um pedido aberto e do celular (390x844), e comparar com os 3 prints deste pacote.
- Rodar os testes e o verificador de design. Abrir o PR, resolver conflitos com a main e, com o CI verde, fazer o merge (regra do CLAUDE.md).
