# Front da Raíz

Três telas, lendo as saídas do motor pelo nome das colunas (`docs/colunas.md`) e tolerando colunas novas.

## Ficha da terra e prospecção

`#/prospeccao` abre a busca nacional; `#/fazenda/<CAR>` abre a ficha de prospecção. O mapa continua nos mesmos
componentes e recebe agregados e a situação básica de cada CAR (apto, com pendência ou não apto). A ficha mostra caminho da terra, pendências, sobreposições, embargos,
histórico de uso e perdas, restauração, crédito líquido P10/P50/P90, TIR e risco. Cada medida mostra fonte e data;
ausência de dado não vira zero. Nunca há nome, documento ou contato do proprietário.

Com `VITE_RAIZ_API`, a prospecção usa `/prospeccao/*` e o token da sessão de cliente dos pedidos. O mapa continua
lendo a publicação mínima estática; nunca recebe o token operacional da API. O build recusa `VITE_RAIZ_API_TOKEN` e
`VITE_RAIZ_TOKEN`. Sem API, o mapa básico e os agregados estão disponíveis: compras, débito e pedidos de contato não são
simulados no navegador.

O agregado aberto aceita recortes territoriais e protege grupos com menos de cinco fazendas. Entrar libera a lista
e o filtro de tamanho. Crédito, risco e caminho da terra exigem pagamento confirmado ou liberação auditada;
filtrar não debita crédito, mas só as fichas liberadas exibem métricas individuais. Na busca autenticada, crédito
e área restaurável agregados também somam apenas essas fichas, com cobertura explícita. Abrir uma ficha completa
exige um crédito pago. O débito é feito no servidor,
somente ao apertar "Desbloquear por 1 crédito". Reabrir a mesma ficha não cobra novamente. "Pedir contato" registra
um pedido na Raíz para tratamento posterior, sem enviar mensagem ao proprietário. Planos aparecem com os valores
configurados no servidor; nenhuma tarifa é inventada pelo front. Compras pendentes são recuperadas do histórico. Enquanto o catálogo estiver provisório, os pacotes de
1, 10 e 50 consultas mostram “a definir pelo fundador” e não geram cobrança.

Na mesma página, “Comparar fazendas” reúne de duas a cinco fichas previamente liberadas, sem novo débito e sem
resultado parcial quando uma delas estiver bloqueada. A tabela conserva as fontes e datas de cada medida.
A ficha liberada oferece PDF baixado com a sessão no cabeçalho, sem expor o token em links públicos.
“Buscas salvas e avisos” guarda no servidor os filtros aplicados, aceita até 20 buscas por conta e permite reabrir
ou excluir a busca. O primeiro snapshot não cria avisos para a base antiga. Novas correspondências aparecem no
painel após o job de atualização; o painel consulta avisos a cada minuto enquanto está visível e oferece atualização
manual e paginação. Marcar como lido não libera a ficha nem envia mensagem a proprietários. Ao trocar de conta,
resultados, comparações e avisos da sessão anterior são descartados.

Teste de navegador: `cd front/globo && npm run test:prospeccao`. Usa Chromium/Playwright com uma API de teste
controlada e confere bloqueio, débito, contato, recompra, recuperação do Pix, preços provisórios, PDF, comparação, buscas salvas/avisos, troca de sessão e largura de 360 px.
`RAIZ_PRINTS` escolhe a pasta dos prints (padrão `/tmp/raiz-ficha-prospeccao`).

| Pasta | O que é | Tecnologia |
|---|---|---|
| `globo/` | Painel do analista: tela de entrada (mapa do Brasil com a busca no topo), painel do município (funil em barras ligado ao mapa, tabela de fazendas) e ficha da fazenda. A pasta guarda o nome antigo; não tem mais globo | Vite + React 19 + TypeScript, MapLibre GL JS + PMTiles |
| `produtor/` | Ficha leve para o produtor no celular: texto primeiro, mapa só ao tocar | Vite + Preact, MapLibre + PMTiles carregados sob demanda |
| `compartilhado/` | Camada única de dados, regras do funil, formatos, comparações, caixa de fatos, privacidade | TypeScript sem dependência |
| `scripts/geo.py` | Baixa as geometrias públicas, recorta o mapa base do Brasil, junta os municípios em estados e grava a lista de municípios do IBGE (`compartilhado/ibge-municipios.ts`) e o contorno dos estados do minimapa | Python (requests, shapely, pmtiles) |
| `scripts/baixar-dados.mjs` | Roda sozinho antes do `npm run dev` (predev): baixa do Release "dados" os estados que o motor publicou para `dados/publicos/` (fora do git), só o que mudou; sem internet, avisa e segue | Node, sem dependência |
| `referencia/` | Prints aprovados pelo fundador | |

## Rodar

```bash
pip install requests shapely pmtiles
node front/scripts/baixar-dados.mjs --geo --exigir
python front/scripts/geo.py --dados dados/publicos
```

```bash
cd front/globo && npm install && npm run dev
```

```bash
cd front/produtor && npm install && npm run dev
```

O painel abre em `http://localhost:5173/` e a ficha do produtor em `http://localhost:5174/?car=<código do CAR>`.

- **Tela de entrada** (`#/`): o mapa plano do Brasil, sem animação, pintado por estado: município processado em mata
  clara, o resto em cinza, e cada estado com o que a Raíz já leu dele ("todos os 144 municípios", "8 de 139
  municípios" ou "ainda não processado"). Nenhuma fazenda carrega nessa escala.
- **Estado** (`#/estado/<UF>`): tocar num estado aproxima e carrega só as fazendas aptas dele, agrupadas em círculos
  com o número; o painel diz se o estado está completo. Dentro do estado, tocar num município abre o município.
- **Município** (`#/municipio/<código IBGE>`): o mapa voa até ele (sem passar por zoom de mundo), pinta as fazendas
  pela situação básica e abre a lista de CARs, com filtro por situação. Nenhuma fazenda é excluída por tamanho.
  O clique no imóvel abre a ficha paga. No celular o painel é uma gaveta que sobe de baixo.
- **Fazenda** (`#/fazenda/<código do CAR>`): a ficha de terra, com acesso pago no servidor e link para o município
  no mapa. "Fazendas" no menu abre a busca nacional e a entrada direta por CAR. A busca do topo mantém a navegação
  por município, inclusive em estado ainda não processado.

- **Pedidos** (`#/pedidos`): sem API, critérios locais e cobertura agregada por município/UF, sem login simulado.
  "Novo pedido" parte de um milhão de créditos no Pará e permite um teto de custo. A comparação informa
  P10/P50/P90, TIR, hectares, fazendas, pendências e o que destrava somente quando a API autenticada retorna
  o pedido autorizado. O site aberto não lê cenários financeiros do Release.
  Contato com donos fica para a fase final; nenhum botão desta cena inicia contato agora.

Testes: `cd front/globo && npm test` valida dados e contratos. `npm run test:pages` abre o build estático com
busca, overzoom e zero 404; `npm run test:cena` verifica cobertura pública, rejeição de snapshot financeiro legado e três lotes autorizados em cores
com pixels reais, teclado e 360 px. As fixtures são isoladas, nunca publicadas como resultados reais.
`npm run test:e2e` executa a entrada e essa mesma cena. O script antigo `testar-pedido.mjs`, com ondas e Pix
simulados, permanece como referência da fase posterior e não integra a validação atual.

## Dados

Tudo passa por `compartilhado/dados/` (`FonteDeDados`). As telas não sabem de onde vêm os números.

- **Publicação mínima:** `baixar-dados.mjs` aceita somente manifesto `versao_publicacao: 1`,
  `escopo: "publico_basico"`, em `dados/publicos/`. Os pacotes por UF contêm resumos agregados,
  `sem_imoveis_<UF>.csv` e `imoveis_basicos_<cod>.csv`, com apenas
  `cod_imovel,cod_ibge,municipio,uf,situacao_basica`. Os GeoParquet separados contêm só CAR e geometria.
  O downloader confere o manifesto, nomes de arquivos e cabeçalhos; pacotes legados são recusados.
- **Fonte:** `RAIZ_DADOS` aponta a pasta explícita. Sem ela, usa `dados/publicos/`; sem publicação baixada,
  a amostra local entrega somente agregados. Uma pasta explicitamente configurada e vazia não cai na amostra.
- **Build e desenvolvimento:** o plugin publica os resumos por allowlist e os básicos somente com manifesto
  público válido. As geometrias individuais passam por projeção para `cod_imovel` e contorno, cruzadas com a lista
  básica. Índices `car_<UF>.json` guardam apenas as exceções de município já presentes nessa lista. Nenhum hectare,
  área comprometida, crédito, TIR, risco, certidão ou histórico por CAR entra no pacote público. As fichas completas
  são servidas pela API com sessão e saldo. Um novo campo do motor não entra automaticamente na publicação.
- **Rotas estáticas:** `/amostra/estados.json`, `indice_<UF>.json`, `resumo_<UF>.csv.gz`,
  `imoveis_basicos_<cod>.csv.gz`, `pontos_<UF>.json` e `car_<UF>.json`. O estado declara
  `acesso: "publico_basico"`. A busca do topo consulta esses arquivos sem API e abre a ficha paga pelo CAR.
  `FonteDeDados.basicos()` usa um tipo próprio; `imoveis()`, `ficha()` e `certidoes()` não leem dados completos
  dessa publicação. Markdown/JSON-LD continuam apenas com agregados, sem fichas individuais.
- `RAIZ_BUILD_DADOS=0` não grava dados, mas mantém páginas explicativas em Markdown. `RAIZ_BASE` muda o caminho
  do site; `VITE_RAIZ_DADOS_BASE` escolhe a pasta pública. A ficha antiga do produtor não é reconstruída desses dados.

## Site público (GitHub Pages)

`.github/workflows/publicar-site.yml` publica o painel em https://bernardoemmel.github.io/Raiz/ e a ficha do produtor
em https://bernardoemmel.github.io/Raiz/produtor/?car=<código do CAR>. Roda a cada mudança do front na main, todo dia
(dados novos do motor) e quando alguém dispara. O build baixa o Release "dados" com `baixar-dados.mjs --geo --exigir`, exporta os polígonos de todos os
municípios com `geo.py --dados dados/publicos` e gera fundos PMTiles compartilhados por estado. A base nacional
continua por overzoom; o município cujo desenho não consta no Release recebe aviso. Falha de download ou de
cobertura da base interrompe a publicação, preservando o site anterior. Uma vez só, no repositório: Settings, Pages, Source "GitHub Actions" (o token do Actions não liga
o Pages sozinho).

O build do site é um script só, `front/scripts/construir-site.sh` (npm ci, build do painel e da ficha, pasta `site/`).
O CI de todo PR usa dados fictícios isolados em `RAIZ_DADOS`/`RAIZ_GEO`, executa o mesmo build e testa o artefato
como Pages pelo Playwright (subcaminho `/Raiz/`, busca por Parauapebas, mapa básico, três situações, geometrias sem campos pagos, zoom, Range e zero 404).
Actionlint, lock fora de sincronia e erros de compilação também deixam o PR vermelho.

O site oferece `llms.txt`, `robots.txt` e `index.md` ao lado dos dois HTMLs, com links alternativos. O catálogo em
`dados/index.md` leva aos Markdown de estados/municípios; números suprimidos no agregado continuam suprimidos no
Markdown e no JSON-LD, sem links para CSV ou geometrias individuais. `servico.md`, `fontes.md` e `privacidade.md` explicam o
produto. JSON-LD no HTML lista Dataset somente dos estados publicados, Service e Offer com valores sob proposta.
`RAIZ_SITE_URL` define a URL canônica (mesmo caminho de `RAIZ_BASE`). A API aceita `Accept: text/markdown` nas leituras textuais,
sem alterar autenticação; a ficha pública também oferece `/p/{codigo}.md` com a mesma regra de aceite.

`npm run test:agentes` confere arquivos e links sob `/Raiz/` e roda Lighthouse 13.6.0 (`agentic-browsing`, experimental).
O portão exige `llms.txt`, árvore de acessibilidade e CLS até 0,1. WebMCP e ARD são apenas relatados. O gatherer busca
`/llms.txt` na raiz da origem, por isso a auditoria usa outra origem local com o artefato na raiz. No Pages de projeto,
`/Raiz/robots.txt` não governa a origem: o site da conta precisa publicar também `/robots.txt`, ou usar domínio próprio.
O relatório local não comprova esses arquivos na raiz pública.

### Domínio próprio

O build deriva o endereço do Pages de `GITHUB_REPOSITORY`; o nome `Raiz` não está fixo nos caminhos de produção.
Sem configuração no ambiente local, a base é `/`. `RAIZ_BASE=/outro/` permite testar um subcaminho.

Quando o domínio existir, configurar a variável de Actions **RAIZ_DOMINIO** com apenas o hostname (por exemplo,
`mapa.suaempresa.com`, sem `https://`, porta ou caminho). O mesmo `construir-site.sh` então usa `/`, grava
`site/CNAME`, define a URL HTTPS canônica no HTML do painel e do produtor e no JSON-LD, e publica `robots.txt` e
`llms.txt` na raiz. A configuração rejeita domínio inválido, subcaminho junto do domínio e URL canônica divergente.
Sem a variável, não gera CNAME e conserva o Pages de projeto.

Ainda é preciso apontar o DNS, verificar o domínio na conta e cadastrá-lo em **Settings > Pages > Custom domain**,
com HTTPS, antes de ativar a variável e executar a publicação. O CNAME dentro do artefato não faz essas alterações
na conta nem no provedor de DNS. Nenhum domínio real foi presumido ou configurado nesta entrega.

O CI valida as duas publicações: o subcaminho do Pages e a raiz com `RAIZ_DOMINIO=raiz.example` (domínio reservado
só para o teste local). Nas duas, Playwright confere navegação e HTTP Range sem 404; a auditoria verifica links,
Markdown e arquivos para agentes. Na raiz também exige CNAME e URLs canônicas coerentes. Para reproduzir:

```bash
node --test front/scripts/configurar-publicacao.test.mjs
RAIZ_DOMINIO=raiz.example front/scripts/construir-site.sh
cd front/globo
RAIZ_BASE=/ RAIZ_DOMINIO=raiz.example npm run test:pages
RAIZ_BASE=/ RAIZ_DOMINIO=raiz.example npm run test:agentes
```

Os testes de navegador pressupõem a fixture preparada por `preparar-teste-site.mjs`, `RAIZ_DADOS`/`RAIZ_GEO`/`RAIZ_CALENDARIO_DADOS`
apontando para ela no build e `VITE_RAIZ_TESTE_MAPA=1`.

O que funciona sem back-end: mapa, CAR e situação básica, estados, municípios e resumos agregados. Ficha completa, busca com métricas pagas,
créditos, Pix e pedidos de contato precisam do back-end (`raiz/`, FastAPI com PostgreSQL e PostGIS). Os componentes
antigos de exemplos de pedidos continuam no código, mas não recebem listas individuais no site público.
- **Depois (API):** defina `VITE_RAIZ_API` no `.env` do front (nunca no git). Rotas que a fonte da API espera, com
  as mesmas colunas dos CSV:

| Rota | Devolve |
|---|---|
| `GET /municipios` | uma linha por município, colunas do `resumo_<UF>.csv` mais `uf` |
| `GET /municipios/{cod_ibge}/imoveis` | imóveis com as colunas de `imoveis_` e `filtros_` (404 se ainda não rodou) |
| `GET /imoveis/{cod_imovel}` | um imóvel |
| `GET /imoveis/{cod_imovel}/ficha` | `FichaJson` (`compartilhado/dados/ficha.ts`): linha, contexto do município e perímetro em polyline |
| `GET /imoveis/{cod_imovel}/certidoes` | cartório (CNS) e matrícula das parcelas SIGEF |
| `GET /busca?q=` | `RespostaBusca` (`compartilhado/dados/busca.ts`): `situacao`, `mensagem`, `imoveis`, `municipios` |
| `GET /geo/{cod_ibge}/{municipio,imoveis,ti,uc,rios}.geojson` | geometrias; `ti` e `uc` recortadas na divisa do município, com `nome` |
| `GET /geo/{cod_ibge}/base.pmtiles` | mapa base (precisa responder a `Range`) |
| `GET /estados` | `Estados` (`compartilhado/dados/tipos.ts`): os 27 estados, quantos municípios o motor processou, de quantos na lista do IBGE, `situacao` (`completo`, `incompleto`, `sem_dados`) e os municípios com lista por fazenda |
| `GET /estados/{uf}/pontos` | fazendas aptas do estado para os círculos do mapa: `{campos, pontos: [[lon, lat, situacao, ha, cod_ibge, n]]}`; `n` maior que 1 é a soma do município, no meio dele |
| `GET /geo/brasil/municipios.geojson` | os municípios do Brasil, simplificados (`cod_ibge`, `nome`, `uf`) |
| `GET /geo/brasil/estados.geojson` | os 27 estados (`uf`, `cod`, `rotulo`: o ponto do nome) |
| `GET /geo/brasil/base.pmtiles` | mapa base único, do país (zoom 0 a 6) ao município (até 14), com `Range` |

A busca (`GET /busca?q=`) aceita o código do CAR inteiro ou o começo dele, com ou sem os pontos do recibo
(`PA-1507300-F293.CD17...`), e o nome ou o código IBGE do município. Quando não acha, diz por quê:
`estado_nao_processado`, `municipio_sem_imoveis` (o município tem funil, mas a lista por fazenda não foi processada),
`nao_encontrado`, `formato_invalido` ou `curta`. A regra está em `compartilhado/dados/busca.ts`, com testes; o
back-end pode portar a mesma função. Na amostra, o plugin do Vite responde a rota; no build estático, a mesma função
roda no navegador.

Colunas que o front já sabe usar quando o motor entregar: `matricula_conferida` (troca o selo "matrícula a
conferir" por "conferida"), `rebanho_cabecas` (linha de gado na caixa de fatos), `fogo_anos_max` e `mb_fogo_<ano>_ha` (camada de fogo, já ligada). A frente Cacau e o raio do
frigorífico ficam desligados de propósito, mesmo quando as colunas chegarem.

## Pedido de lote (cena-alvo)

O contrato com o back-end está em `compartilhado/pedidos/tipos.ts` (rotas no comentário do topo): `POST /entrar`,
`POST /entrar/confirmar`, `GET /pedidos`, `POST /pedidos`, `GET /pedidos/{id}`, `POST /pedidos/{id}/lote` (tirar ou
trocar), `POST /pedidos/{id}/solicitar-interesse`, `GET /pedidos/{id}/andamento`, `POST /pedidos/{id}/reservar` e
`GET /pedidos/{id}/reserva`, com o token da sessão no cabeçalho. Com `VITE_RAIZ_API`, as telas falam com essas rotas.

Sem API, o front salva apenas os critérios no navegador e mostra a cobertura agregada por estado e município.
O build ignora qualquer `lote_PA_central_r11.json` financeiro encontrado em `RAIZ_LOTES` ou `dados/lotes`;
publica somente um marcador de acesso privado para clientes estáticos antigos. O navegador também ignora caches
legados, sem baixar o ponteiro do Release. `scripts/baixar-lotes.mjs` permanece como compatibilidade: não usa
rede nem lê ou altera snapshots financeiros locais. O workflow do site não executa esse downloader.
A comparação real, os ganhos por pendência e os desenhos dos lotes vêm exclusivamente da API autenticada.
O cenário sintético do teste de navegador é interceptado somente pelo Playwright e nunca entra no build público.

As três opções têm cores e traços diferentes. Na API, a geometria vem junto do item apenas quando a ficha já foi
desbloqueada pelo mesmo cliente ativo; medidas individuais de itens fechados chegam como `null`, com
`ficha_liberada: false`, e a tela indica a ficha paga sem inventar zeros. A autorização e a exclusividade são
revalidadas a cada leitura. Consultar
o mapa não gera débito novo. Sem desenho autorizado, a tela mostra aviso e nunca busca contornos privados no Pages.
A simulação antiga continua exportada somente para testes explícitos, sem ser o padrão da aplicação.

## Regras que as telas seguem

- **Guia de design** (`docs/design/guia-front-v1.md`): cores só pelas variáveis de `compartilhado/base.css` (o
  TypeScript usa o espelho `compartilhado/cores.ts`, conferido por teste), fontes Familjen Grotesk, Atkinson
  Hyperlegible Next e IBM Plex Mono, ícones Lucide. O verificador `scripts/verificar-design.mjs` roda no
  `npm run build` dos dois apps e no `npm test`, e recusa sombra, borda esquerda colorida, degradê de enfeite, caixa
  alta, cor fora das variáveis, a Inter, emoji, travessão, seta e "A · B" em texto da interface. Rodar à mão:
  `node front/scripts/verificar-design.mjs`.

- **Funil igual ao do motor:** apta = sem problema, área de carbono > 0 e até 5 ha desmatados desde 2016; com
  matrícula = apta e ≥ 50% do CAR com parcela SIGEF com matrícula. O teste confere com o `resumo_PA.csv`.
- **Nenhuma fazenda sai por tamanho:** pequenas (até 4 módulos fiscais) e assentamentos vão para "Agrupar".
- **Caixa de fatos:** três colunas fixas (o que se mede, não fazer nada, restaurar), a cada 100 ha do imóvel, em
  10 anos. Linha sem coluna no motor some e volta quando a coluna chegar; a renda entra com a etapa E3.
- **Comparações:** campo de futebol de 105 × 68 m; metano de boi pelo fator do IPCC (56 kg de CH₄ por cabeça por ano
  × 27); posição e índice contra o município no método do Census Reporter.
- **Privacidade:** colunas pessoais saem na leitura (mesma regra de `raiz/privacidade.py`) e todo texto passa pela
  máscara de CPF/CNPJ. Nenhum nome aparece nas telas.

## Leveza da ficha do produtor

Primeira abertura: cerca de 18 KB compactados (HTML, CSS e JS) mais o JSON da fazenda, com o contorno desenhado a
partir do perímetro em polyline. MapLibre (cerca de 300 KB) e o PMTiles só são baixados quando o produtor toca em
"ver no mapa". O cartão WebP e o ThumbHash da miniatura entram quando o lote anual do E9 (passos 3 e 4) gerar.

## Calendário

A aba `#/calendario` reúne os eventos públicos coletados diariamente, com filtros por tipo, estado e período,
paginação, fonte e data da coleta. Eventos nacionais continuam visíveis ao filtrar um estado. O período considera o prazo quando informado, senão a data do evento.
O feed `.ics` baixa a seleção na API; no site estático, baixa a agenda completa publicada.

Com `VITE_RAIZ_API`, consulta `GET /eventos` e `GET /eventos.ics`. Sem API, lê
`calendario/eventos.json`: `baixar-calendario.mjs` baixa o JSON e o feed do Release `calendario` no `predev` e no
build do site (`RAIZ_BUILD_DADOS=0` pula o download no CI). A pasta `globo/public/calendario/` é ignorada pelo git.
`RAIZ_CALENDARIO_DADOS` fornece uma pasta local com os dois arquivos (a fixture do CI usa esta opção sem rede);
`RAIZ_CALENDARIO_URL` troca a origem no build; `VITE_RAIZ_EVENTOS_URL` e `VITE_RAIZ_EVENTOS_ICS_URL` permitem
usar um snapshot publicado em outro endereço. Sem primeira coleta, a tela avisa explicitamente. Coleta com mais de
dois dias e fontes com falha também aparecem como avisos.

Leilões previstos com data de hoje ou futura marcam os CAR publicados nos editais na ficha desbloqueada.
Eventos cancelados ou adiados não geram a marca. O mapa aberto permanece agregado, sem polígonos individuais,
e o calendário não desbloqueia a ficha paga. O selo não altera a aptidão do imóvel nem exclui fazendas pequenas.
`npm run test:calendario` confere tela, filtros, falta de coleta e celular no Chromium; `test:prospeccao` confere
o selo depois do desbloqueio e sua remoção ao trocar de conta. A suíte `npm test` cobre o contrato, paginação,
máscara e seleção dos leilões.
