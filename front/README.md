# Front da Raíz

Três telas, lendo as saídas do motor pelo nome das colunas (`docs/colunas.md`) e tolerando colunas novas.

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
python front/scripts/geo.py 1507300 1504950
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
- **Fazenda** (`#/fazenda/<código do CAR>`): a ficha. A busca fica no topo de todas as telas (atalho: tecla `/`):
  código do CAR vai direto para a ficha, com o mapa saindo do município e pousando na fazenda; nome de município vai
  para o mapa dele, inclusive de estado ainda não processado (o painel avisa).

Testes: `cd front/globo && npm test` (dados, funil, busca, rotas, design, ausência do globo e dados por estado: estado
completo, incompleto, estados.json baixado, cache dos pontos, queda para a amostra sem RAIZ_DADOS e sem internet, CPF
e CNPJ mascarados) e `npm run test:e2e` (sem internet o predev avisa e segue; sobe o Vite com a amostra e confere no
Chromium a entrada por estado, o toque no estado e no município, a busca por município e por CAR e a gaveta no
celular; precisa do Playwright com o Chromium e de `front/geo/` gerado).

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

  O `vite build` grava tudo em `dist/`, com uma ficha por fazenda (a ficha leve do produtor sem servidor): com os 6
  estados publicados hoje são 638.754 fichas e 3,1 GB. Com o Brasil inteiro, o caminho é a API (abaixo).
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
