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

## O que falta, em ordem

1. Concluir as cinco entregas solicitadas: cena-alvo, cobertura diária do mapa, ficha visual, celular/acessibilidade
   com Lighthouse ≥90 nas duas categorias e configuração de domínio próprio. Integrar cada uma com CI verde.
2. Conferir a chegada do ponteiro `lote_PA_central_r11.json` no Release; a rotina diária já o incorpora quando existir.
3. E9 passo 3: aguardar as 30 cartas reais anonimizadas e uma avaliação de compreensão, confirmadas como ainda
   indisponíveis pelo fundador. Depois calibrar o portão e gravar a nota no laudo.
4. Continuar os itens E9 na ordem do plano: texto por fazenda no kit ONS/campos abertos, condicionais e extenso,
   KMZ e os demais. A geometria de reserva legal ainda não está nas camadas; não deduzir seu desenho de percentuais.

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
