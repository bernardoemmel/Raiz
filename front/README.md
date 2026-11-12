# Front da Raíz

Três telas, lendo as saídas do motor pelo nome das colunas (`docs/colunas.md`) e tolerando colunas novas.

## Ficha da terra e prospecção

`#/prospeccao` abre a busca nacional; `#/fazenda/<CAR>` abre a ficha de prospecção. O mapa continua nos mesmos
componentes e recebe apenas agregados. A ficha mostra caminho da terra, pendências, sobreposições, embargos,
histórico de uso e perdas, restauração, crédito líquido P10/P50/P90, TIR e risco. Cada medida mostra fonte e data;
ausência de dado não vira zero. Nunca há nome, documento ou contato do proprietário.

Com `VITE_RAIZ_API`, a prospecção usa `/prospeccao/*` e o token da sessão de cliente dos pedidos. O mapa continua
lendo os agregados estáticos; nunca recebe o token operacional da API. O build recusa `VITE_RAIZ_API_TOKEN` e
`VITE_RAIZ_TOKEN`. Sem API, somente o agregado está disponível: compras, débito e pedidos de contato não são
simulados no navegador.

O agregado aberto aceita recortes territoriais e protege grupos com menos de cinco fazendas. Entrar libera a lista
e os filtros de tamanho e crédito; abrir a ficha completa exige um crédito pago. O débito é feito no servidor,
somente ao apertar "Desbloquear por 1 crédito". Reabrir a mesma ficha não cobra novamente. "Pedir contato" registra
um pedido na Raíz para tratamento posterior, sem enviar mensagem ao proprietário. Planos aparecem com os valores
configurados no servidor; nenhuma tarifa é inventada pelo front. Compras pendentes são recuperadas do histórico.

Teste de navegador: `cd front/globo && npm run test:prospeccao`. Usa Chromium/Playwright com uma API de teste
controlada e confere bloqueio, débito, contato, recompra, recuperação do Pix, troca de sessão e largura de 360 px.
`RAIZ_PRINTS` escolhe a pasta dos prints (padrão `/tmp/raiz-ficha-prospeccao`).

| Pasta | O que é | Tecnologia |
|---|---|---|
| `globo/` | Painel do analista: tela de entrada (mapa do Brasil com a busca no topo), painel do município (funil em barras ligado ao mapa, tabela de fazendas) e ficha da fazenda. A pasta guarda o nome antigo; não tem mais globo | Vite + React 19 + TypeScript, MapLibre GL JS + PMTiles |
| `produtor/` | Ficha leve para o produtor no celular: texto primeiro, mapa só ao tocar | Vite + Preact, MapLibre + PMTiles carregados sob demanda |
| `compartilhado/` | Camada única de dados, regras do funil, formatos, comparações, caixa de fatos, privacidade | TypeScript sem dependência |
| `scripts/geo.py` | Baixa as geometrias públicas, recorta o mapa base do Brasil, junta os municípios em estados e grava a lista de municípios do IBGE (`compartilhado/ibge-municipios.ts`) e o contorno dos estados do minimapa | Python (requests, shapely, pmtiles) |
| `scripts/baixar-dados.mjs` | Roda sozinho antes do `npm run dev` (predev): baixa do Release "dados" os estados que o motor publicou para `dados/estados/` (fora do git), só o que mudou; sem internet, avisa e segue | Node, sem dependência |
| `referencia/` | Prints aprovados pelo fundador | |

## Rodar

```bash
pip install requests shapely pmtiles
node front/scripts/baixar-dados.mjs --geo --exigir
python front/scripts/geo.py --dados dados/estados
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
  pela situação e abre o painel com o funil em barras: tocar numa barra deixa só aquelas fazendas coloridas; tocar no
  contorno mostra quem saiu, pela cor do motivo. No celular o painel é uma gaveta que sobe de baixo.
- **Fazenda** (`#/fazenda/<código do CAR>`): a ficha de terra, com acesso pago no servidor e link para o município
  no mapa. "Fazendas" no menu abre a busca nacional e a entrada direta por CAR. A busca do topo mantém a navegação
  por município, inclusive em estado ainda não processado.

- **Pedidos** (`#/pedidos`): sem API, consultas locais ao cenário real publicado no Release, sem login simulado.
  "Novo pedido" parte de um milhão de créditos no Pará e permite um teto de custo. A comparação informa
  P10/P50/P90, TIR, hectares, fazendas, pendências e o que destrava. Com API, os pedidos usam a sessão do cliente.
  Contato com donos fica para a fase final; nenhum botão desta cena inicia contato agora.

Testes: `cd front/globo && npm test` valida dados e contratos. `npm run test:pages` abre o build estático com
busca, overzoom e zero 404; `npm run test:cena` verifica Release ausente/presente, três lotes autorizados em cores
com pixels reais, teclado e 360 px. As fixtures são isoladas, nunca publicadas como resultados reais.
`npm run test:e2e` executa a entrada e essa mesma cena. O script antigo `testar-pedido.mjs`, com ondas e Pix
simulados, permanece como referência da fase posterior e não integra a validação atual.

## Dados

Tudo passa por `compartilhado/dados/` (`FonteDeDados`). As telas não sabem de onde vêm os números.

- **Hoje (pasta do motor):** o plugin do Vite (`compartilhado/vite-dados.ts`, com a leitura em `pasta-dados.ts`)
  serve os CSV como se fosse a API. De onde, nesta ordem:
  1. a pasta da variável `RAIZ_DADOS` (no ambiente ou no `.env` da raiz), separada por estado como o motor grava:
     `<pasta>/<UF>/imoveis_<cod>.csv`, `direto_`, `filtros_`, `extras_`, `mapbiomas_`, `certidoes_` e `resumo_<UF>.csv`;
  2. sem ela, `dados/estados/`, que o `npm run dev` baixa sozinho do Release "dados" (`docs/dados-publicados.md`),
     com o `estados.json` que diz, por estado, quantos municípios há, de quantos, e se está completo;
  3. sem nenhuma das duas (por exemplo, sem internet), `dados/amostra/`, como sempre. `RAIZ_DADOS=dados/amostra`
     força a amostra.

  Rotas (iguais nos três casos; o nome do arquivo diz o estado): `/amostra/estados.json` (os 27 estados; com o
  `estados.json` baixado, os números vêm dele, sem recontar; sem ele, conta os arquivos e compara com a lista do IBGE
  em `compartilhado/ibge-municipios.ts`), `/amostra/indice_<UF>.json` (os CSV do estado), `/amostra/<arquivo>.csv`
  (limpo: sem coluna pessoal, CPF e CNPJ mascarados), `/amostra/pontos_<UF>.json` (as aptas do estado para os
  círculos do mapa), `/amostra/car_<UF>.json` (códigos do CAR que o motor pôs no arquivo de outro município; 0,6% no
  Pará), `/amostra/fichas/<cod>.json` e `/busca?q=`. Nada é lido de uma vez: os pontos de cada estado são montados uma
  vez (em segundo plano, logo que o servidor sobe; o Pará leva uns 8 s), guardados em `front/.cache/` (fora do git) e
  refeitos só quando um CSV ou contorno daquele estado muda. Arquivo novo do motor aparece sozinho na tela; coluna nova
  aparece em "Outros dados do motor" na ficha. As geometrias continuam em `front/geo/` (gerado pelo script, fora do git).

  O `vite build` publica somente resumos municipais por uma lista de colunas permitidas, estados e pontos
  agregados, limites municipais/estaduais e mapa base. Não publica fichas, códigos do CAR, CSV individuais nem
  geometrias de imóveis. O plugin remove sobras de builds anteriores; o servidor de desenvolvimento aplica a mesma
  restrição, inclusive ao acesso direto aos arquivos. Grupos com menos de cinco imóveis têm números suprimidos.
  `RAIZ_BUILD_DADOS=0` não grava dados, mas mantém páginas explicativas em Markdown; `RAIZ_BASE` muda o caminho do site; `VITE_RAIZ_DADOS_BASE` escolhe a pasta dos
  agregados. A ficha antiga do produtor não é reconstruída a partir de dados públicos.

## Site público (GitHub Pages)

`.github/workflows/publicar-site.yml` publica o painel em https://bernardoemmel.github.io/Raiz/ e a ficha do produtor
em https://bernardoemmel.github.io/Raiz/produtor/?car=<código do CAR>. Roda a cada mudança do front na main, todo dia
(dados novos do motor) e quando alguém dispara. O build baixa o Release "dados" com `baixar-dados.mjs --geo --exigir`, exporta os polígonos de todos os
municípios com `geo.py --dados dados/estados` e gera fundos PMTiles compartilhados por estado. A base nacional
continua por overzoom; o município cujo desenho não consta no Release recebe aviso. Falha de download ou de
cobertura da base interrompe a publicação, preservando o site anterior. Uma vez só, no repositório: Settings, Pages, Source "GitHub Actions" (o token do Actions não liga
o Pages sozinho).

O build do site é um script só, `front/scripts/construir-site.sh` (npm ci, build do painel e da ficha, pasta `site/`).
O CI de todo PR usa dados fictícios isolados em `RAIZ_DADOS`/`RAIZ_GEO`, executa o mesmo build e testa o artefato
como Pages pelo Playwright (subcaminho `/Raiz/`, busca por Parauapebas, mapa agregado, zoom, Range e zero 404).
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

Os testes de navegador pressupõem a fixture preparada por `preparar-teste-site.mjs`, `RAIZ_DADOS`/`RAIZ_GEO`
apontando para ela no build e `VITE_RAIZ_TESTE_MAPA=1`.

O que funciona sem back-end: mapa, estados, municípios e resumos agregados. Ficha completa, busca por fazenda,
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

Sem API, `scripts/baixar-lotes.mjs` lê o ponteiro `lote_PA_central_r11.json` do Release `dados`, publicado
pelo fluxo `restauracao_rodada`. `RAIZ_LOTES` escolhe a pasta de entrada (padrão `dados/lotes`, ignorada pelo git).
O plugin de build projeta somente agregados para `amostra/lote_PA_central_r11.json`: não copia CARs, matrículas,
folhas de contato ou os pacotes individuais. Ausência de publicação gera aviso com a cobertura territorial real;
falhas de rede/formato interrompem a publicação. O cenário é uma referência: mudar teto de custo ou outro filtro
exige recálculo pela API. Dado desconhecido permanece desconhecido, inclusive nos totais suprimidos.

As três opções têm cores e traços diferentes. Na API, a geometria vem junto do item apenas quando a ficha já foi
desbloqueada pelo mesmo cliente ativo; a autorização e a exclusividade são revalidadas a cada leitura. Consultar
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
