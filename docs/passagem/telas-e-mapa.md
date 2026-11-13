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
