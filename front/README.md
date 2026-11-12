# Front da Raíz

Três telas, lendo as saídas do motor pelo nome das colunas (`docs/colunas.md`) e tolerando colunas novas.

| Pasta | O que é | Tecnologia |
|---|---|---|
| `globo/` | Painel: abertura com o globo, tela principal (funil, filtros, mapa, lista de aptas) e ficha da fazenda | Vite + React 19 + TypeScript, globo `cobe` 2.0.1, MapLibre GL JS + PMTiles |
| `produtor/` | Ficha leve para o produtor no celular: texto primeiro, mapa só ao tocar | Vite + Preact, MapLibre + PMTiles carregados sob demanda |
| `compartilhado/` | Camada única de dados, regras do funil, formatos, comparações, caixa de fatos, privacidade | TypeScript sem dependência |
| `scripts/geo.py` | Baixa as geometrias públicas e recorta o mapa base | Python (requests, shapely, pmtiles) |
| `referencia/` | Prints aprovados pelo fundador | |

Os componentes em `globo/src/components/` foram copiados sem alterar e continuam assim: a abertura controla o
globo só pelas props `speed` e `theta`.

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

O painel abre em `http://localhost:5173/` (São Félix do Xingu primeiro) e a ficha do produtor em
`http://localhost:5174/?car=<código do CAR>`. Testes da camada de dados: `cd front/globo && npm test`.

- `?sem-abertura` pula a abertura; `?abertura` força. Ela roda uma vez por sessão e nunca com "reduzir movimento".
- A busca fica no topo da abertura, do painel e da ficha (atalho: tecla `/`). Imóvel achado abre a ficha com o mapa
  saindo do Brasil, passando pelo município e pousando na fazenda.
- Rotas do painel: `#/municipio/<código IBGE>` e `#/fazenda/<código do CAR>`.

## Dados

Tudo passa por `compartilhado/dados/` (`FonteDeDados`). As telas não sabem de onde vêm os números.

- **Hoje (amostra):** `dados/amostra/*.csv` e `front/geo/` (gerado pelo script, fora do git). O plugin do Vite
  (`compartilhado/vite-dados.ts`) serve `/amostra/` e `/geo/` como se fosse a API e monta a ficha de cada fazenda em
  `/amostra/fichas/<cod>.json`. Arquivo novo do motor (por exemplo `imoveis_1507300.csv`, `extras_<mun>.csv`) aparece
  sozinho na tela; coluna nova aparece em "Outros dados do motor" na ficha.
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
| `GET /geo/{cod_ibge}/{municipio,imoveis,ti,uc,rios}.geojson` | geometrias |
| `GET /geo/{cod_ibge}/base.pmtiles` | mapa base (precisa responder a `Range`) |

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
