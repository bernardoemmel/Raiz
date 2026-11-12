# Passagem do chat "Telas e mapa" (12/11/2026)

Sessão: https://claude.ai/code/session_01VGb88MJumyG9PHt2znaaKE. Branch: `claude/upbeat-goodall-iwsrai`.

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
- Validação local: 10 testes de configuração, 131 testes de front (13 pulados), os dois builds e Playwright/Lighthouse
  nos dois caminhos passaram, com zero 404 e sem expor dados individuais. Ruff check e format passaram.
- `robots.txt` e `llms.txt` ficam prontos para a raiz quando o domínio for ativado. O endereço atual de projeto
  continua com a limitação do robots na raiz de `bernardoemmel.github.io`.

## O que falta, em ordem

1. Acompanhar os checks e a publicação dos PRs destas duas entregas; merge somente com CI verde.
2. Configurar a descoberta na raiz de hospedagem quando houver acesso ao site da conta ou domínio próprio,
   sem presumir que o arquivo em `/Raiz/` equivale a `/robots.txt`.
3. E9 passo 3: aguardar as 30 cartas reais anonimizadas e uma avaliação de compreensão, confirmadas como ainda
   indisponíveis pelo fundador. Depois calibrar o portão e gravar a nota no laudo.
4. Continuar os itens E9 na ordem do plano: texto por fazenda no kit ONS/campos abertos, condicionais e extenso,
   KMZ e os demais. A geometria de reserva legal ainda não está nas camadas; não deduzir seu desenho de percentuais.

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
