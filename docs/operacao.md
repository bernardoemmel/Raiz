# Operação: como saber na hora quando algo parou

## Healthchecks (alerta fora do servidor)

O alerta não pode depender do servidor da Raíz: se ele cair, o aviso tem de sair de outro lugar. Por isso o padrão é
o serviço hospedado (healthchecks.io); uma instância própria também serve, desde que fique em outra máquina.

1. Crie a conta e um projeto "Raíz". Em *Settings*, gere a **ping key** e marque a opção que deixa criar checks pelo
   primeiro ping (auto-provisioning).
2. Ponha a chave no `.env` do servidor: `RAIZ_HEALTHCHECKS_CHAVE_PING=...`.
3. Em *Integrations*, ligue pelo menos dois canais que não passam pelo servidor: e-mail e ntfy (aplicativo no
   celular) ou Telegram.
4. Na primeira rodada, os checks aparecem sozinhos: `raiz-funil`, `raiz-filtros`, `raiz-direto`, `raiz-carga`.
   Ajuste em cada um o período e a tolerância (para a fila nacional, 1 dia e 6 horas é um bom começo): sem ping
   dentro do prazo, o Healthchecks avisa que o trabalho parou mesmo sem erro.

Cada município é uma execução do check com seu próprio `rid`: o painel mostra início, fim, duração e, na falha, o fim
do log (CPF e CNPJ já mascarados). Para um check por UF, use `RAIZ_HEALTHCHECKS_MODELO_SLUG=raiz-{tarefa}-{uf}`; um
check por município (`raiz-{tarefa}-{cod}`) só vale numa instância própria, porque são mais de 5 mil.

## Alertas com escalonamento (E7 passo 9)

O Healthchecks avisa quando um trabalho para de bater ponto, mesmo com o servidor fora do ar. Por dentro, o servidor
olha o resto de 15 em 15 minutos e sobe a escada do que ninguém reconheceu:

```
*/15 * * * *  uv run raiz operacao alertas   # lotes, orçamento, vigilância, prazo da Verra, filas, grupos
```

Para instalar sem depender do diretório e do `PATH` do cron, no servidor e com o usuário da aplicação:

```bash
uv run python scripts/instalar_cron_alertas.py             # mostra o bloco
uv run python scripts/instalar_cron_alertas.py --instalar  # ativa a cada 15 minutos
crontab -l
```

O instalador preserva os outros trabalhos e substitui apenas o bloco marcado da Raíz; pode ser repetido. Usa o
caminho absoluto do `uv`, entra na raiz do repositório (onde a configuração lê o `.env`), exige o lockfile com
`--frozen` e usa `flock` para não sobrepor rodadas. Se existir `.env`, usa `uv run --env-file .env` para exportar
também as variáveis lidas diretamente por `os.environ` na vigilância; não executa o arquivo como código shell.
Precisa de `cron` ativo e `flock` (`util-linux`) no servidor.
Não instala serviços nem preenche credenciais. Sem ntfy e GoAlert, continua em envio simulado; sem banco acessível
e migrado, a rodada falha. A prévia não ativa nada. Um ambiente de desenvolvimento sem acesso ao servidor não
comprova que o agendamento esteja ativo em produção.

O Calendário da Raíz usa um bloco separado no mesmo instalador:

```bash
uv run raiz banco migrar
uv run python scripts/instalar_cron_alertas.py --tarefa calendario            # prévia
uv run python scripts/instalar_cron_alertas.py --tarefa calendario --instalar # diário
```

Ele executa `uv run raiz calendario coletar` todos os dias às **06:47 no fuso configurado no servidor**, com trava
própria, sem alterar o fuso dos demais trabalhos. O banco do `.env` precisa estar acessível e migrado (incluindo
0026). Essa rodada persiste os eventos, cruza CAR/SIGEF, atualiza API/MCP e prepara os avisos do painel; os canais
externos continuam simulados. A rodada do GitHub Actions com `--sem-banco` publica o Release e não substitui esse
agendamento do banco. Instalar ou repetir um bloco preserva o outro. Instale no diretório permanente da aplicação:
`dados/calendario/` guarda o estado da coleta entre as rodadas.

| O que | Gravidade |
|---|---|
| lote que falhou nas últimas 24 h (um alerta por tarefa e dia) | aviso |
| lote que começou e não terminou há mais de 6 h | urgente |
| gasto com modelos a 80% / 100% do orçamento do mês (`RAIZ_ORCAMENTO_MENSAL_USD`) | aviso / urgente |
| vigilância diária sem rodar há mais de 1 dia; fonte da vigilância com erro | urgente; aviso |
| aviso à Verra de um evento de perda vencendo (7 dias) ou vencido; relatório de perda vencido | crítico |
| revisão esperando há mais de 24 h; mensagem para dono esperando aprovação há mais de 12 h | aviso |
| fazenda com problema num grupo pronto ou reservado | urgente |

A escada (raiz/regras/padroes/alertas.yaml, versionada): nível 0 no ntfy na hora; sem reconhecimento, nível 1 em 30
minutos (ntfy urgente) para urgente e crítico; nível 2 em 2 horas para crítico, que vai para a segunda pessoa no
GoAlert quando houver (`RAIZ_GOALERT_URL`) e, sem ela, de novo para o fundador, urgente. O último nível se repete a
cada 4 horas, até 8 envios. Aviso sai uma vez só. Estado que passou (o lote destravou, a vigilância voltou) fecha
sozinho; fato (lote que falhou, grupo com problema) fecha quando alguém resolve.

- ntfy: `RAIZ_NTFY_TOPICO` (nome longo e aleatório: ele funciona como senha), `RAIZ_NTFY_URL` (padrão
  https://ntfy.sh) e, se o servidor do ntfy pedir, `RAIZ_NTFY_TOKEN`. No celular, assinar o mesmo tópico.
- Sem essas variáveis, o envio é simulado: o texto e o nível ficam registrados no alerta (backoffice), nada sai.
- `uv run raiz operacao reconhecer ID` para a escada; `uv run raiz operacao resolver ID --nota "..."` fecha.

## Backoffice do fundador (E7 passo 6)

Só leitura, com o mesmo token da API: `/painel/backoffice` (página que pede o token), `/backoffice/resumo` (saúde,
lotes em 24 h, parados, vigilância, custo do mês contra o orçamento com projeção, filas esperando o fundador, alertas
abertos), `/backoffice/custos?por=tarefa|fazenda|municipio|modelo`, `/backoffice/lotes?estado=falha`,
`/backoffice/alertas` e `/backoffice/fazenda/{cod_imovel}` (chamadas de modelo e custo, decisões da cascata,
revisões, aceite, mensagens só com tipo e estado, pedidos, lotes do município e alertas da vigilância). No terminal:
`uv run raiz operacao painel`.

## Painel de acerto (E7 passo 5)

Toda previsão congelada (aprendizado.previsao) e todo gabarito entram no formato do hub (hubverse):

```bash
uv run raiz aprendizado hub dados/hub     # hub-config, model-output, model-metadata, target-data, painel
uv run raiz aprendizado acerto            # notas por modelo, versão e alvo no terminal
```

Cada (modelo, versão) vira um model_id (`raiz-<modelo>_<versão>`), para comparar versões. Na API, com token:
`/acerto/placar` e a página `/painel/acerto` (WIS, cobertura do P10 a P90, Brier, log score e acerto; a versão na
frente por alvo; o acerto da vigilância). A pasta do hub fica no servidor, fora do git: as previsões de aceite dizem
quem aceitou. Para o painel do hub-dashboard (o mesmo do FluSight), a pasta já traz site-config.yml,
predevals-config.yml e predtimechart-config.yml.

## Cascata por confiança e teste próprio (E7 passo 10)

**Rota** (`raiz/regras/padroes/cascata.yaml`): o Qwen3-4B só faz classificação curta. Isso quer dizer:

- até 6 campos na saída, todos de lista fechada ou sim/não;
- resposta de até 400 tokens;
- nenhuma chamada de ferramenta.

O resto vai para a nuvem: o Haiku responde sozinho e, se falhar, o Sonnet; sem resposta, a fila de revisão.

**Confiança:** o llama-server devolve os logprobs; a confiança é a menor probabilidade entre os tokens dos valores
(`raiz/modelos/confianca.py`). Com corte calibrado para a tarefa, a resposta do Qwen acima do corte vale sozinha (via
`confianca`); abaixo, sobe para a votação com o Haiku, como antes. Só os 20 a 30% menos confiantes sobem. Tarefa sem
corte fica na votação.

**Teste próprio** (`raiz/modelos/avaliacao/banco.yaml`): 120 tarefas do aceite com o prompt de produção, 15% sem
resposta válida (o modelo tem de dizer que não sabe), 3 tentativas seguidas. O relatório traz acerto, acerto nas 3
tentativas, consistência, abstenção correta e custo; fica em `dados/avaliacao/`, fora do git.

No servidor, depois de subir o llama (compilado com llguidance, `infra/llama/Dockerfile`) ou de trocar o modelo ou o
prompt:

```bash
docker compose -f infra/docker-compose.yml up -d --build llama
uv run raiz modelos calibrar        # roda o teste no Qwen e grava raiz/regras/padroes/cascata_cortes.yaml
uv run raiz modelos avaliar --modelo triagem   # o mesmo teste no Haiku, para comparar
```

O GGUF validado para o nome usado no compose é o Q4_K_M de
[Unsloth/Qwen3-4B-Instruct-2507-GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF), revisão
`a06e946bb6b655725eafa393f4a9745d460374c9` (2.497.281.120 bytes), sob Apache-2.0. Salve-o como
`infra/modelos/qwen3-4b-instruct-2507-q4_k_m.gguf`, fora do git, e confira antes de subir:

```bash
sha256sum infra/modelos/qwen3-4b-instruct-2507-q4_k_m.gguf
```

SHA-256 esperado: `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`.
O download verificado em 12/11/2026 veio da revisão acima; trocar a quantização ou o conteúdo do arquivo exige
recalibrar, mesmo que o nome permaneça igual. Guarde esse SHA junto do relatório de avaliação. Antes de rodar as
360 chamadas, `uv run raiz modelos testar --modelo qwen3-4b-instruct-2507` confere a conexão e a saída JSON.

O Dockerfile fixa Rust 1.100.0 e copia o header da mesma revisão do llguidance depois de compilar o Rust. Isso
corrige a falha `llguidance.h: No such file or directory` da combinação b12300/llguidance 1.0.1 com o novo layout
de diretórios do Cargo. Se o ambiente usa proxy TLS, o certificado pode ser montado apenas durante o build:

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -t raiz/llama-server:b12300-llguidance infra/llama
docker compose -f infra/docker-compose.yml up -d --no-build llama
```

Sem proxy, o segredo é opcional e o comando normal do compose continua suficiente. A imagem final não recebe o
certificado do ambiente de construção.

Validação local em 12/11/2026: imagem construída com esse Dockerfile, `llama-server --version` em
`ccd360f` (b12300), `/health` saudável e teste CLI do Qwen respondendo JSON válido em 1.253 ms. A intenção e a
explicação amostradas do teste próprio levaram 3.868 e 7.392 ms, com logprobs disponíveis. Isso confirma o build e
a conexão local; não afirma implantação no servidor nem substitui as 360 respostas da calibração.

O corte só é gravado com o relatório de um modelo local de verdade; se o arquivo do GGUF mudar de nome, os cortes
antigos deixam de valer. Sem servidor nem chave, `--modelo simulado` roda tudo com regras (linha de base). Cada
decisão em `operacao.decisao_cascata` guarda rota, confiança, corte e versão da regra e dos cortes. Se a subida real
sair da faixa por mais de 15 pontos em 7 dias, abre o alerta `cascata_faixa`: recalibrar.

Os 95% exigidos pelo calibrador são o acerto observado no mesmo banco usado para escolher o corte; não há amostra
independente de validação nem garantia estatística desse acerto em produção. As três tentativas medem repetição e
consistência, não equivalem a três mensagens independentes. O runtime confere o nome do modelo; conferir também
SHA do GGUF, versão do llama.cpp e prompt é parte da promoção operacional dos cortes.

### Resultado real do Qwen em 12/11/2026

A rodada terminou às 16h05 de Brasília (19h05 UTC): **120 mensagens do banco próprio, três tentativas por
mensagem, 360 respostas completas**, todas com confiança numérica e nenhuma falha técnica. São mensagens de
teste, não contatos reais de produtores. Banco `banco-pt-2026.11a+01697528`, política
`cascata-2026.11a+fb4a9c2d`, Qwen/llama/GGUF identificados acima, três threads e contexto de 8.192 tokens.

| Tarefa | Mensagens / respostas | Acerto observado | Acerto nas três tentativas | Abstenção correta | Latência mediana |
|---|---|---|---|---|---|
| Intenção do aceite | 80 / 240 | 163/240 (67,92%) | 67,50% | 7,14% | 1.914 ms |
| Compreensão da proposta | 40 / 120 | 52/120 (43,33%) | 42,50% | 25,00% | 5.465 ms |

**Nenhum corte foi aprovado.** No melhor candidato da faixa de subida, a intenção manteria 79,43% de acerto no
que fica no Qwen, com 27,08% subindo; a compreensão manteria 49,47%, com 20,83% subindo. Ambos ficaram abaixo dos
95% exigidos. O arquivo `cascata_cortes.yaml` foi gerado pela CLI com os metadados desta rodada e `cortes: {}`;
as duas tarefas continuam na votação Qwen + Haiku. Não foi ajustado o banco nem forçado um corte para melhorar a
nota. A interpretação continua sendo empírica, no mesmo banco de escolha do corte, conforme a limitação acima.

A soma do tempo de inferência foi de 24 min 27 s; havia outros testes rodando na máquina, portanto os tempos não
são um compromisso de desempenho em produção. A comparação com Haiku ficou pendente: o teste real da CLI
retornou `sem credencial da Anthropic` neste ambiente, sem benchmark simulado nem pedido de chave pelo chat.
Implantação e agendamento no servidor de produção não foram realizados neste ambiente local.

Evidência fora do git, em `dados/avaliacao/qwen-2026-11-12/`:

- Relatório: `2026-11-12T190503_qwen3-4b-instruct-2507.json`, SHA-256
  `0f23332758a33238ee48289caa4cb39b93a1f0d5072ecfc3dd3d2b4b1d6f4c87`.
- Proveniência do peso, imagem, compilador e parâmetros: `proveniencia.json`, SHA-256
  `35a215f3ece2240d5878182a69de8f9fda421fe97b642790fc08fb026c169abe`.
- `verificacao.json` registra a conferência dos 120 IDs, três tentativas por ID, versão do banco, modelo, provedor,
  métricas e decisões do calibrador. As 360 respostas brutas não foram incluídas no repositório.

## Rodar o motor vigiado

```bash
uv run raiz funil rodar PA 1504950                # um município
uv run raiz funil rodar PA                        # a UF inteira, 3 municípios ao mesmo tempo
uv run raiz funil rodar PA --tarefas funil,carga  # só o funil e a carga no banco
```

O comando não edita o motor. Ele lê CAR e SIGEF do espelho local da coleta (`dados/espelho/` ou
`RAIZ_ESPELHO_DIR`) e, quando o município não está no espelho, deixa o motor baixar como sempre, anotando a origem no
lote. Falha num município não para os outros; arquivo pronto é pulado (use `--refazer` para refazer). A carga grava
a rodada com a versão do motor confirmada e congela as previsões.

## Coleta (E1)

Sugestão de cron no servidor (horário de Brasília); cada comando avisa o Healthchecks:

```
10 5 * * *  uv run raiz coleta checar     # HEAD nos arquivos do manifesto (sumiu? mudou?)
20 5 * * *  uv run raiz coleta ibama      # embargos: condicional, sem dado pessoal, CSV limpo para o motor
40 5 * * *  uv run raiz coleta car        # UFs do rodízio do dia; SIGEF dos municípios que mudaram
```

A fila baixa até 200 municípios por rodada; se mais de 15% estiver sujo, roda tudo (disjuntor), e uma vez por mês faz
a reconciliação completa. O espelho fica em `dados/espelho/` (ou `RAIZ_ESPELHO_DIR`), um Parquet por município, e é o
que o `raiz funil rodar` entrega ao motor. O histórico fica em `bruto.car_imovel`, `bruto.sigef_parcela` e nas views
`*_vigente`.

## Langfuse próprio

```bash
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.langfuse.yml up -d
```

Painel em http://127.0.0.1:3000 (só a máquina; acesso de fora por túnel). O compose não sobe sem os segredos do
`.env.example` (gere com `openssl rand -hex 32`). Valkey no lugar do Redis e SeaweedFS no lugar do MinIO, por causa
das licenças; para usar o R2, preencha `LANGFUSE_S3_ENDERECO` e as chaves do R2. As chaves `LANGFUSE_PUBLIC_KEY` e
`LANGFUSE_SECRET_KEY` que você escolher no `.env` criam o projeto na primeira subida e são as mesmas que o produto usa
para mandar os rastros. Volume do banco já existente: crie a base uma vez com `CREATE DATABASE langfuse OWNER raiz;`.

## Cache dos rasters na nuvem

A tarefa `direto` (YbYrá e GPW) lê os blocos dos arquivos na nuvem por pedaços de 1 MB guardados em disco
(`dados/cache_raster/` ou `RAIZ_RASTER_CACHE_DIR`, teto `RAIZ_RASTER_CACHE_GB`, padrão 20). Medido em Nova Esperança do
Piriá: 18 s sem cache, 33 s na primeira rodada com cache e 7 s nas seguintes, com valores idênticos. Se o arquivo
mudar na nuvem (ETag novo), o cache dele é refeito.

## Onde olhar

| O quê | Onde |
|---|---|
| O que mudou na coleta | `coleta.evento` (novos, mudaram, sumiram por município) e `coleta.replicacao` |
| Lote parado ou com falha | Healthchecks (alerta) e `operacao.lote` (estado, duração, fim do log) |
| Custo de modelo por tarefa e por fazenda | Langfuse (sessão = código do CAR) e `operacao.chamada_modelo` |
| Decisões da cascata ABC | `operacao.decisao_cascata` |
| O que precisa de decisão humana | `operacao.fila_revisao` (API: `GET /revisoes`) |
| Mensagens esperando aprovação | `pessoal.mensagem_saida` (API: `GET /mensagens/pendentes`) |
| Acerto das previsões | `uv run raiz aprendizado placar` e `aprendizado.previsao_contra_gabarito` |

## Blocos de 0,5 grau: recalcular só o que mudou (E2 passo 4)

- Cada imóvel tem um bloco (`raiz/funil/grade.py`, mesma grade do cache do motor, como `-47.0_-3.5`), gravado em
  `funil.imovel` e nas tabelas da rodada.
- Depois do histórico, a rodada da coleta lê os arquivos do espelho que mudaram (CAR, SIGEF, embargos) e grava em
  `funil.bloco_manifesto` o hash do que cada camada tem em cada bloco, por município. Mudança só em campo volátil não
  suja o bloco. O resumo da rodada traz a lista `blocos`.
- `manifesto_blocos.sujos(con)` lista os blocos com alguma camada que mudou depois do último cálculo;
  `marcar_calculados` fecha o bloco quando o funil termina. No município 1504950: CAR em 5 blocos, SIGEF em 9,
  embargos em 2; a segunda leitura, sem mudança, leva 4 ms.

## Mapa base do Brasil (design v1 do front, item 5)

- `raiz mapa atualizar` recorta o Brasil até o zoom 14 do build mais recente do Protomaps (go-pmtiles: `go install
  github.com/protomaps/go-pmtiles@latest`), baixa fontes e sprites e grava `manifesto.json` em `RAIZ_MAPA_DIR`
  (padrão `dados/mapa/`). O recorte de 11/11/2026 tem 3,07 GB (4,5 milhões de ladrilhos) e saiu em cerca de 2 minutos.
  Atualizar uma vez por mês basta; o recorte anterior só é apagado depois que o novo terminou.
- Rotas: `/mapa/manifesto.json`, `/mapa/brasil.pmtiles` (Range, nunca recomprimido),
  `/mapa/fontes/{fonte}/{faixa}.pbf` e `/mapa/sprites/{nome}.{json|png}`.

## Imagens de satélite por fazenda (design v1 do front, item 1)

- Rotas `/imoveis/{cod}/imagem/{hoje|hoje-produtor|hoje-celular|simulacao|1985|2008}.webp` e `.json` (metadados).
  Na primeira chamada a imagem é gerada (Sentinel-2 dos últimos 3 meses sem nuvem sobre o imóvel, ou mediana das
  cenas limpas do trimestre; Landsat 5 para 1985 e 2008) e fica em `RAIZ_IMAGENS_DIR` (padrão `dados/imagens/`).
- `raiz satelite gerar --municipio 1504950` adianta as imagens das fazendas aptas. Num imóvel real de 2.491 ha:
  cena de 28/10/2026, 30 s para as quatro de hoje, 144 KB (1024 px), 76,6 KB (720 px, produtor) e ~57 KB (480 px);
  Landsat 1985 e 2008 em 15 s.

## Link público, cartão e vídeo (design v1 do front, item 6)

- Sem token, pelo código curto: `/p/{codigo}` (HTML com Open Graph), `/cartao/{codigo}/{previa.jpg|retrato.jpg|
  adesivo.png}` e `/video/{codigo}.mp4` e `-720p.mp4`. Os cartões também saem em WebP (`previa.webp`, `retrato.webp`,
  `adesivo.webp`), com cerca de metade do peso, para a ficha e o site; a prévia do WhatsApp continua em JPEG. Antes do
  aceite do dono só saem município, hectares, selo e código curto; o código do CAR e a imagem de satélite da fazenda
  só depois do aceite.
- Precisa de `npm ci` em `servicos/cartao` (Takumi) e do `ffmpeg` no servidor. A voz do vídeo liga com
  `uv pip install qwen-tts` (traz torch; o modelo de 0,6 B roda em CPU); sem ela o vídeo sai mudo e o cabeçalho
  `X-Raiz-Aviso: sem voz` avisa. Cache em `RAIZ_PUBLICO_DIR` (padrão `dados/publico/`), refeito quando o selo muda.
- Medido aqui: prévia 41 KB, retrato 63 KB, adesivo 12 KB, vídeo 720p de 6 s em 1,4 s.

## Dados por município (design v1 do front, item 4)

- `GET /municipios/{cod_ibge}`: frase-resumo, funil por etapa e por porte com os 3 maiores motivos de saída, "desde a
  última análise" (foto da etapa de cada imóvel em cada rodada, `funil.etapa_rodada`, gravada pela carga) e área
  urbana da sede. `raiz municipio urbana <cod>` gera o contorno urbano (MapBiomas classe 24, a mancha onde fica a
  sede no OpenStreetMap) e grava em `geo.camada`.
- Em Nova Esperança do Piriá (dado real): 880 imóveis, 793 sem problema, 738 aptos (32.848 ha), 41 com matrícula;
  o que mais tira do funil é a matrícula (697); área urbana da sede 182 ha.

## Fichas em lote (E9, passo 1)

- `raiz ficha lote [--uf PA] [--municipios 1504950,1507300] [--destino pasta] [--refazer]` grava, por município, em
  `RAIZ_FICHAS_DIR` (padrão `dados/fichas/`, fora do git):
  - `<UF>/<cod_ibge>/fichas/<código do CAR sem traços>.json`: a mesma ficha de `GET /imoveis/{cod}/ficha`, para
    servir como arquivo estático (qualquer servidor de arquivos ou o Pages);
  - `<UF>/<cod_ibge>/rows.json`: uma linha por fazenda com os campos do cartão, do vídeo e do texto (os nomes do
    pedido do Takumi). Campo que começa com `_` é interno: o código do CAR só aparece fora dele depois do aceite;
  - `<UF>/<cod_ibge>/manifesto.json` e `indice.json` na raiz: rodada, data de corte, quantas fazendas, quantas aptas
    e quando foi gravado.
- Cada ficha leva a capa (foto de satélite com ThumbHash, quando já foi gerada) e a localização: Plus Code e link curto
  do Organic Maps (`https://omaps.app/...`, abre o app offline) de um ponto dentro do imóvel. No `rows.json`, o ponto
  exato só sai fora do campo interno depois do aceite.
- Só regrava o município cuja rodada vigente mudou. O contexto do município (posição e medianas) é calculado uma vez
  por município, não por fazenda.

## Valor para quem restaura (desenvolvedor de crédito de carbono)

Calculado pelo produto, fora do motor (raiz/restauracao.py e raiz/restauracao_geo.py), por município, em
`saida/<UF>/desenvolvedor_<mun>.csv`; a carga leva ao banco como complemento `desenvolvedor` e a ficha mostra o bloco
"Para quem restaura" (sempre com o aviso de estimativa e as faixas P10 a P90).

- Rodar junto do motor: a tarefa `desenvolvedor` do `raiz funil rodar` (padrão), depois da ficha e antes da carga.
- Refazer quando as premissas mudam: `raiz restauracao recalcular [--ufs PA]` refaz só os municípios gravados com
  outra versão (`restauracao_versao` = versão de raiz/regras/padroes/restauracao.yaml + do cenário + hash dos
  arquivos e da calibração).
- Entradas geográficas com cache em `dados/cache_restauracao/` (ou RAIZ_CACHE_RESTAURACAO_DIR): declividade do
  Copernicus por ladrilho de 1 grau, chuva do CHIRPS por faixa de 5 graus de latitude, solo do SoilGrids por município;
  a distância à mata e a linha de base saem do raster de cobertura do MapBiomas do motor e do YbYrá. Se uma fonte
  falhar, a coluna fica vazia, o cálculo usa a premissa neutra e `restauracao_faltou` diz o que faltou.
- Cenários (no mesmo arquivo das premissas, raiz/regras/padroes/restauracao.yaml, seção 11; um só arquivo e um só
  cálculo): o padrão é `central_r11` (rodada 11 do fundador: captura na forma oficial da URTX escalada para o total do
  método e limitada ao teto do bioma, custos oficiais do SFB com P10 e P90 publicados, descontos em ordem com piso de
  10% na linha de base e vazamento de 10% (zero com vizinha de mitigação), marcos do ProFloresta+ com o último a 100%,
  multa e rescisão medidas no lote, dono pago por 40 anos com piso de R$ 24/ha, Fundo Clima até 50% pelo ICSD 1,3,
  venda a US$ 30 depois do ano 25, WACC de 9,2%); `central_r11_74`, `estresse_r11` (linha de base e vazamento de 40%,
  35% financiado, 20% ao dono), `so_contrato_25` (sem venda depois do contrato) e as premissas antigas em
  `otimista_fundador` e `otimista_fundador_74`. Referência (fazenda de 100 ha no leste do PA, US$ 55, câmbio de R$
  5,40): TIR com financiamento de ~5,5% no plantio e ~13,5% na regeneração assistida (docs/restauracao-rodada11.md).
- Câmbio: `raiz restauracao cambio` mostra a PTAX de venda do Banco Central; `--gravar` grava em
  raiz/regras/padroes/restauracao_cambio.yaml e os cenários com `cambio_ptax` passam a usá-la no lugar dos R$ 5,40 (a
  versão muda e o `recalcular` refaz; rode uma vez por mês, ou quando o câmbio andar).
- Simulador: `GET /imoveis/{cod}/restauracao/simular?cenario=estresse_r11&preco_usd_t=74&pagamento_dono=duas_fases&...`
  (marcos_pct, entregas_anos, volume_contratado, juros_carencia, participacao_dono, piso_dono_rs_ha_ano e os demais
  da lista `editaveis`);
  cenários com a fonte de cada parâmetro em `GET /restauracao/cenarios`. Painel: `GET /municipios/{cod}/imoveis?
  ordem=valor_desenvolvedor&modo=plantio_total&tir_min=20&so_lote_fecha=true` e `GET /municipios/{cod}/lotes`.
- Aprendizado: cada estimativa entra congelada (modelo `restauracao`, com a versão) na carga. Quando um cliente
  informar o real: `raiz restauracao informar <CAR> --fonte "desenvolvedor" --custo-rs-ha 16500 --modo plantio_total`
  (ou `POST /imoveis/{cod}/restauracao/real`). `raiz restauracao comparar` mostra real contra previsto por modo;
  `raiz restauracao recalibrar --gravar` escreve raiz/regras/padroes/restauracao_calibracao.yaml (revise antes de
  subir): a versão muda e o `recalcular` refaz.

## Rebanho por fazenda e metano (E4)

`raiz rebanho recalcular [--saida pasta] [--ufs PA]` grava rebanho_<mun>.csv onde falta ou a versão mudou (a tarefa `rebanho` do invólucro e do executor faz o mesmo, antes do valor para quem restaura). A PPM vem de raiz/regras/padroes/ppm_bovinos.csv (SIDRA 3939, 2025 e 2017); quando o IBGE divulga um ano novo (raiz/coleta/ppm.py), baixe de novo a tabela e suba o ano em rebanho.yaml: a versão muda e tudo se refaz. Reserva de não permanência por fazenda (E3 passo 4): seção nao_permanencia de restauracao.yaml, com o fogo do MapBiomas Fogo e a derrubada da vegetação secundária do município.

## Caminho da terra e terra pública para restaurar

A situação da terra não corta mais o funil: cada imóvel ganha um caminho (privada com matrícula, posse em
titulação, assentamento, pública sob concessão, pública sem destinação, terra indígena ou tradicional) com risco
e motivo, em `saida/<UF>/terra_<mun>.csv` (raiz/terra.py; regra em raiz/regras/padroes/caminho_terra.yaml).

- Preparar uma vez: `raiz terra preparar-cnfp` (baixa o Cadastro Nacional de Florestas Públicas do SFB, 229 MB, e
  grava `dados/terra_publica/cnfp_<UF>.parquet`). Sem ele, o caminho usa só o SIGEF do espelho e as colunas do motor.
- Junto do motor: a tarefa `terra` do `raiz funil rodar` (padrão), antes da ficha. Refazer quando a regra ou as
  concessões mudam: `raiz terra recalcular [--ufs PA]`.
- Camada "Terra pública para restaurar": `raiz terra publica --ufs PA` (gera `terra_publica_<UF>.parquet` e carrega em
  geo.terra_publica; `--reducao 4` mede a distância à mata a 120 m, bom para áreas do tamanho de um estado). API:
  `GET /terra-publica?uf=PA&ordem=desmatado|credito|area&so_com_concessao=true` e
  `GET /geo/{cod_ibge}/terra_publica.geojson`.
- Editais: `raiz terra editais` lê as páginas do SFB e do Ideflor-Bio, guarda cada link com a data em que apareceu
  (`dados/terra_publica/editais_vistos.json`) e lista os novos; o que for concessão de verdade entra em
  raiz/regras/padroes/concessoes.yaml com data e link (a versão da regra muda e o `recalcular` refaz).

## Motor dentro do produto (agente Dados)

O executor (raiz/executor/) roda o motor e as tarefas do produto por estado e por município e grava tudo no
armazém configurado em RAIZ_ARMAZEM_URL. O de produção (e o padrão) é o Release `dados` do GitHub
(`release-github://bernardoemmel/raiz/dados`), no formato de motor/publicar_dados.py: `raiz_<UF>.tar.gz` (CSV e
`_versoes.json`), `raiz_geo_<UF>.tar.gz`, `raiz_camadas_<UF>.tar.gz`, `raiz_controle_<UF>.json` (marcas e estado,
para retomar), `raiz_controle.json` e, por último, `estados.json`. Grava só com o token do Actions (`GH_TOKEN` ou
`GITHUB_TOKEN`); sem token, só lê. Também servem uma pasta local (testes) e o S3 (`s3://`, opção futura: R2 ou
SeaweedFS, sem uso hoje).

- Actions: o workflow `.github/workflows/processar-estados.yml` chama, por estado,
  `raiz executor rodar --ufs <UF> --lanes N --ate-minutos 330` com `RAIZ_SEM_BANCO=1` (sem banco no job) e o token.
  Aos 330 minutos o executor para de começar municípios, termina os que estão em curso e publica; a rodada seguinte
  baixa `raiz_controle_<UF>.json` e continua do ponto em que parou. Durante a rodada ele publica a cada 15 minutos
  (ou a cada 80 arquivos novos), então um job morto perde no máximo esse trecho.
- Estado publicado antes do executor (sem marcas, como o PA): `raiz executor adotar --ufs PA` grava as marcas a partir
  dos `_versoes.json` e dos arquivos que estão no Release, sem rodar o motor.
- Retomada: depois de CADA tarefa de cada município, a marca `marcas/<UF>/<mun>.json` guarda a versão da tarefa, a
  assinatura das entradas e o sha256 das saídas. Matar o processo perde no máximo a tarefa em curso; rodar de novo
  pula o que está em dia. Se a máquina for outra (disco vazio), as entradas de que uma tarefa precisa descem do armazém.
- O que refazer: a tarefa roda quando muda (1) a versão dela (hash do código de que depende e, quando há, da regra:
  FLAG, caminho da terra, premissas de restauração), (2) uma fonte do município (CAR, SIGEF e embargos do espelho,
  alertas na caixa do município, rasters do MapBiomas do estado) ou (3) a saída de uma tarefa anterior. Se uma tarefa
  roda e a saída sai igual, as seguintes não rodam.
- Cada arquivo no armazém leva nos metadados: tarefa, versão, data, município, versão do motor e sha256.
- Andamento por estado em `estado/<UF>.json` (pronto, em andamento, com erro; feitos, erros, versões), lido pelo
  painel (`/painel/processamento`, `GET /processamento`) e por `raiz executor estado`.
- O back-end não lê mais a pasta do motor: `raiz executor sincronizar` espelha o armazém em `dados/armazem_local/`
  e a carga contínua leva ao banco só o que mudou; um imóvel de município ainda não carregado é carregado na hora em
  que alguém pede (`/imoveis/{cod}`). Números do Brasil e dos estados: `GET /brasil` e `GET /estados`.
- Agenda: `raiz executor ciclo` (completa quando a coleção do MapBiomas do motor muda, parcial no resto) ou
  `raiz executor vigiar --intervalo-h 24`, com Healthchecks (raiz-executor). Ver o README para o cron.

## Pedido de lote (docs/cena-alvo.md)

O cliente pede "1 milhão de créditos" e a Raíz monta o melhor lote (raiz/pedidos/, premissas em
raiz/regras/padroes/pedidos.yaml, cada número com a fonte). O contrato com o front é
front/compartilhado/pedidos/tipos.ts.

- Oferta: uma linha por fazenda em `negocio.oferta` (crédito líquido até o ano 25 em P10/P50/P90, custo por crédito,
  TIR, marcos, caminho da terra, onde), refeita sozinha depois da carga de cada município; `raiz pedidos oferta
  [--ufs PA]` refaz do banco. Fazenda sem contorno fica na sede do município (raiz/executor/municipios.csv).
- Entrar: `POST /entrar {email}` manda o link (uso único, 30 minutos) e `POST /entrar/confirmar {token}` devolve a
  sessão (30 dias, `Authorization: Bearer`). O e-mail fica cifrado no esquema pessoal. `raiz pedidos cliente
  --rotulo "Empresa"` cria um cliente direto.
- Pedido: `POST /pedidos` responde na hora quanto existe na base (por caminho da terra e por interesse do dono, com o
  que falta e o que afrouxar) e as 3 opções do solver (HiGHS pelo scipy.optimize.milp: mais barata, mais segura,
  mais compacta), cada uma com fazendas de reserva (15% da meta). Fazenda cujo preço de equilíbrio passa do preço do
  pedido (o plantio que o preço não paga) custa a diferença mais US$ 30 por crédito (`abaixo_equilibrio_usd`), então a
  regeneração vem antes; cada opção traz `abaixo_equilibrio` com o aviso quando o lote só fecha com elas. Os marcos
  do ProFloresta+ e a multa esperada saem do lote inteiro (`restauracao.cronograma_lote`). `POST /pedidos/{id}/lote`
  (ou `PATCH`) tira ou troca uma fazenda e refaz os números. Cada lote sugerido fica em `negocio.pedido_sugestao` com a
  versão do modelo.
- Interesse do dono: `negocio.interesse_dono` (nível de agora) e `negocio.interesse_evento` (cada registro com data,
  canal, motivo e versão do termo); o nível só sobe com a versão do termo; recusa vale um ano. Nome e CPF ficam só no
  esquema pessoal; a API devolve só o nível. Resposta do dono: `POST /interesse/{cod_imovel}` (token da API) ou
  `raiz pedidos resposta`.
- Ondas: `POST /pedidos/{id}/solicitar-interesse {opcao}` contata a 1ª onda (até a soma de chance de aceite vezes
  crédito dar 1,5 vez a meta; envio simulado por enquanto, WhatsApp quando o dono tem contato, senão carta). `raiz
  pedidos ciclo` (de hora em hora no cron) vence quem não respondeu em 15 dias, chama a próxima onda, fecha o grupo
  quando os interessados alcançam a meta (aviso no painel, e-mail e WhatsApp) ou diz o que faltou.
  `GET /pedidos/{id}/andamento` mostra a meta com interessado, aceite e contrato, as ondas, recusas e motivos.
- Reserva: `POST /pedidos/{id}/reservar` cria a cobrança Pix pela AbacatePay somente com `RAIZ_PIX_MODO=producao`
  e `RAIZ_ABACATEPAY_CHAVE`; por padrão é cobrança de teste, paga com `raiz pedidos pagar-teste <id>` ou
  `POST /pagamentos/teste/{id}/pagar`. O aviso de
  pagamento chega em `POST /pagamentos/abacatepay?webhookSecret=...` (`RAIZ_ABACATEPAY_WEBHOOK_SEGREDO`). Paga, as
  fazendas ficam do cliente por 60 dias (`reserva_dias` no pedido) e somem das buscas, contas e pedidos dos outros;
  uma fazenda nunca está em duas reservas (índice único). Venceu sem contrato, voltam para a base (`raiz pedidos
  ciclo`). Contrato fechado: `POST /reservas/{id}/converter {ha_assinados}` abate a reserva da conexão por ha.
  Cada passo fica em `negocio.reserva_evento` (quem, quando, valor e prazo).
- Vigia: o mesmo `raiz pedidos ciclo` refaz os pedidos salvos e avisa "lote melhorou" ou "fazenda do grupo com
  problema" (embargo, desmatamento, bloqueio, saiu da base); `GET /pedidos/{id}/alertas`.
- Aprendizado: cada onda congela a chance de aceite de cada fazenda contatada (aprendizado, alvo `aceite_dono`, com a
  versão do modelo); o aceite ou a recusa viram gabarito, e a chance por perfil (tamanho, caminho da terra, estado e
  forma de pagamento) é atualizada a cada contato.

## API pública e MCP para os agentes de IA dos clientes (docs/agentes-ia.md)

- API pública em `/v1` (OpenAPI em `/v1/openapi.json`, Swagger em `/v1/docs`) e servidor MCP remoto em `/mcp/`
  (streamable HTTP, sem estado); local por stdio com `raiz mcp` (RAIZ_API_URL e RAIZ_CHAVE_API).
- Chave por empresa: `POST /v1/chaves` na sessão do login por e-mail ou `raiz pedidos chave --cliente <id>`; só o hash
  fica em `negocio.chave_api`; limite por minuto e por dia (429 com Retry-After).
- Cada chamada fica em `negocio.chamada_api` (empresa, chave, via api/mcp/sessao, ferramenta, pedido, fazenda, status,
  tempo, versão do modelo e modelo do agente): limite, auditoria (`GET /v1/chamadas`) e aprendizado.
- Reserva pedida por agente: `negocio.reserva.estado = aguardando_confirmacao`, link de uso único (48 horas) no e-mail
  da empresa (`/v1/reservas/confirmar/{token}`); sem confirmação, o `raiz pedidos ciclo` cancela (nada foi cobrado).
- Em produção: `RAIZ_MCP_HOSTS` com os hosts do MCP remoto (liga a proteção contra DNS rebinding).

## Lote do ProFloresta+ por estado (relatório para o desenvolvedor e folha do dono)

`raiz lote montar PA [--saida pasta/saida] [--destino pasta] [--creditos 1000000] [--cenario central_r11]` lê os
`desenvolvedor_<mun>.csv` do estado (só as fazendas com área para restaurar), monta o lote com o mesmo cálculo da ficha
e do pedido (raiz/lote.py) e grava em `<saida>/<UF>/lote/`: `lote_<UF>.csv` (todas as fazendas com o papel: titular,
reserva, mitigação, em espera), `lote_<UF>.json` (resumo, marcos, preço mínimo, terra destravada, certidões e
checklist), `relatorio_lote_<UF>.html` (para imprimir em A4) e `folhas_dono/folha_dono_<cod>.html` (titulares e
reservas). Responde quantos municípios entraram e, se não fecha 1 milhão com reserva, exatamente o que falta.

- Titulares: o P50 de créditos até o ano 25 que cumpre todos os marcos do Anexo IV com a tolerância (o do ano 7 pede
  ~1,14 milhão para um contrato de 1 milhão). Reserva: o que falta para 90% de chance (`lote.chance_alvo_reserva`),
  com o erro da captura comum ao lote (P10 de 0,6): ~1,87 milhão no P50. A escolha é o otimizador dos pedidos
  (opção mais barata, terra pronta: matrícula e concessão).
- Fluxo do lote: a soma dos fluxos do P50 das fazendas (`restauracao.fluxo_p50`, refeito a partir das entradas gravadas
  no `desenvolvedor_<mun>.csv`), com a dívida do Fundo Clima dimensionada no caixa do lote, a multa esperada dos marcos
  e o crédito além do contrato vendido ao preço depois do contrato. Daí a TIR e o preço mínimo por crédito para 12% e
  15% (com e sem dívida).
- O que destrava o lote: posse em titulação e assentamento (fazendas, ha, ha e créditos de regeneração) e o mesmo lote
  montado como se virassem título ou parceria (custo médio por crédito, TIR e chance dos marcos).
- Certidões: matrícula com certidão conferida (etapa `titulo_conferido`) separada da matrícula a conferir, e quantas
  certidões pedir (das maiores áreas por certidão primeiro; cartório e matrícula do `certidoes_<mun>.csv`) para ter 5%
  da área homologada na assinatura (`lote.area_homologada_assinatura`).
- Faixa do lote (E3): créditos até o ano 25 em soma (todas as fazendas errando juntas, a que dimensiona a reserva) e em carteira (um fator comum de Vasicek com 60% da variância, `carteira.fracao_comum`), com os campos da Portaria MME 102/2016 (P50, P90 de excedência, incerteza padrão; revisor independente pendente); a mesma premissa vale no pedido e nos documentos. Parcelas de campo por método (AR-TOOL03: 90% de confiança, 10% de erro, mínimo de 30). Tornado da TIR do lote: captura, custo, preço e câmbio no P10 e no P90.
- Checklist do edital: os 62 itens de raiz/regras/padroes/edital_profloresta.yaml, com a checagem automática quando os
  dados da Raíz dão conta e "a conferir" no resto.
- Folha do dono: tudo passa pela Raíz (contato, dúvidas e assinatura); quanto recebe por ha e por ano (P10 a P90) e o
  total em 40 anos; comparação com a renda do gado na mesma área (venda de bovinos por ha de pasto no município, Censo
  Agro 2017 corrigido pelo IPCA, e a sobra pela margem de referência da CNA) e com o aluguel do Censo. Sem nome, CPF
  ou CNPJ: só o código do CAR.

## Preparar o servidor de fichas e o pagamento de consultas

**Situação desta entrega:** roteiro e código preparados; não há servidor da Raíz implantado por este chat e nenhuma
venda foi ativada. `raiz/regras/padroes/precos.yaml` propõe pacotes de 1, 10 e 50 consultas, com `valor_rs: null`,
`status: provisorio` e o aviso literal **a definir pelo fundador**. Crédito de consulta não é crédito de carbono.

1. Provisionar uma máquina com Python 3.12+, `uv`, PostgreSQL 16/PostGIS 3.5, armazenamento privado e backups.
   O compose em `infra/docker-compose.yml` oferece o banco; sua porta fica em `127.0.0.1:5432`. Escolher o endereço
   HTTPS da API e um proxy que termine TLS; manter a porta do banco e a porta interna da API fora da internet.
2. Instalar a versão revisada do repositório com `uv sync --frozen --all-extras`. Criar um arquivo privado de ambiente
   a partir de `.env.example`, protegido contra leitura de outros usuários. Configurar `RAIZ_BANCO_URL`,
   `RAIZ_API_TOKEN`, `RAIZ_API_ORIGENS` com a origem exata do front e `RAIZ_CHAVE_PESSOAL`. A chave pessoal cifra o
   e-mail do comprador; nome, CPF e contato do dono não entram nas fichas de prospecção.
3. Injetar as variáveis no processo. Nos comandos manuais abaixo, `--env-file .env` faz essa injeção, inclusive para
   os módulos Pix que leem `os.environ`; não basta o arquivo existir. Aplicar as migrações antes de iniciar a API:

   ```bash
   uv run --env-file .env raiz banco migrar
   uv run --env-file .env raiz api --host 127.0.0.1 --porta 8000
   ```

   Em operação contínua, usar um gerenciador de processos com reinício, ambiente privado e logs sem tokens ou corpos
   de webhook. A migração 0026 cria carteira, compras, movimentos, desbloqueios, pedidos de contato e limites. Usar
   `head` para aplicar também as migrações posteriores. Carregar o funil vigente no banco pelo fluxo do executor.
4. Confirmar `/saude` e `GET /prospeccao/planos`. Nesta fase a resposta deve mostrar pacotes provisórios,
   `pix_modo: teste` e `pagamento_disponivel: false`, mesmo se alguém já configurou uma chave da AbacatePay.
   A ficha exige sessão individual e crédito pago; o token operacional não é token de cliente e nunca vai no build
   do front. A publicação estática continua só com agregados. Configurar `VITE_RAIZ_API` com o endereço HTTPS da API
   e reconstruir o front quando o servidor estiver pronto.
5. Preparar o envio real do link de entrada: o serviço de sessões já grava links de uso único e sessões, mas o
   adaptador `raiz.pedidos.servico.ENVIO_LINK` precisa estar ligado a um envio autorizado. Sem ele, o endpoint de
   entrada não entrega e-mail. Validar o ciclo de entrada e saída antes de oferecer fichas aos clientes.

### Catálogo aprovado e chaves reais, somente na futura ativação

O fundador precisa definir os valores e aprovar a política comercial. Depois disso, criar um YAML privado no mesmo
formato de `precos.yaml`, com uma nova `versao`, `status: aprovado`, `aprovado_em` em `AAAA-MM-DD` e os preços reais
positivos, em reais, com até duas casas decimais. `creditos` é a quantidade de consultas de cada pacote e pode ser
alterada no catálogo. Apontar `RAIZ_PRECOS_ARQUIVO` para esse arquivo. Não marcar o YAML provisório do repositório
como aprovado apenas para testar o botão.

O override `RAIZ_PROSPECCAO_PLANOS` aceita o mesmo envelope em JSON (`versao`, `status`, `aprovado_em`, `planos`).
Uma lista JSON no formato antigo continua legível, mas permanece provisória. Aprovação sem data ou sem preço válido
fecha o catálogo com erro; preço ausente nunca vira zero. A compra congela pacote, quantidade e valor no banco.

Na futura ativação autorizada, configurar os valores reais destas variáveis no servidor:

| Variável | Uso |
|---|---|
| `RAIZ_PIX_MODO` | `teste` por padrão; só o literal `producao` permite chamar o provedor. |
| `RAIZ_ABACATEPAY_CHAVE` | Chave privada da conta no ambiente e na versão compatíveis com o adaptador. |
| `RAIZ_ABACATEPAY_WEBHOOK_SEGREDO` | Segredo aleatório privado de pelo menos 32 caracteres, igual ao cadastrado no webhook. |
| `RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA` | Chave pública HMAC publicada pela AbacatePay, copiada da documentação oficial. |
| `RAIZ_PRECOS_ARQUIVO` | Caminho do catálogo aprovado, fora do repositório. |

Uma chave configurada, isoladamente, não ativa a compra. O catálogo precisa estar aprovado, com preços válidos, e o
modo Pix precisa ser explicitamente de produção. Uma resposta `devMode: true` do provedor continua sendo teste e
nunca libera crédito pago. Nenhum teste deste repositório faz pagamento real.

**Compatibilidade do adaptador:** `raiz/pedidos/pix.py` ainda usa a API legada v1 (`pixQrCode/create` e
`pixQrCode/check`, evento `billing.paid`). A documentação oficial atual descreve v2 (`transparents/*`). Conferir
com a conta se as chaves e webhooks v1 continuam disponíveis; se a conta só aceitar v2, manter vendas desativadas
e migrar o adaptador em uma entrega própria. A integração de produção não foi validada com uma conta real.

### Webhook de consultas e conciliação

Para consultas, cadastrar a URL HTTPS `https://<api>/pagamentos/prospeccao/abacatepay` no ambiente e versão
compatíveis do provedor. O webhook antigo `/pagamentos/abacatepay` pertence às reservas de lote; ele não credita
a carteira de consultas. Não chamar os endpoints de teste de reservas para tentar liberar fichas pagas.

O novo webhook exige as duas provas descritas na
[documentação de segurança da AbacatePay](https://docs.abacatepay.com/pages/notificacoes/seguranca):

- `X-Webhook-Secret`, ou o parâmetro legado `webhookSecret`, confere o segredo privado em tempo constante.
- `X-Webhook-Signature` contém HMAC-SHA256 em base64 dos bytes originais do corpo, usando a chave pública do
  provedor. Essa assinatura garante integridade; ela não substitui o segredo privado.

Preservar o corpo bruto no proxy. Preferir o segredo no cabeçalho e retirar a query dos logs quando a versão legada
a exigir. Segredo/assinatura ausentes ou inválidos devolvem 401; corpo acima de 256 KiB devolve 413. Eventos de
teste são ignorados. O código não grava o corpo recebido e não usa preços, quantidade de créditos ou cliente
informados pelo evento: identifica a compra local e confere novamente o pagamento pela API autenticada do provedor.
Somente o estado confirmado como pago credita a carteira. A trava da carteira e o movimento único por compra
impedem crédito duplicado por reentrega, concorrência ou consulta pelo navegador.

O comprador pode recuperar o histórico em `GET /prospeccao/compras` e conferir uma cobrança em
`GET /prospeccao/compras/{id}`, com sua própria sessão. O botão **Conferir pagamento** usa essa conciliação; se for
automatizada, respeitar intervalo de pelo menos 15 segundos e o limite de 15 verificações por minuto. Falha do
provedor no webhook responde 502 para permitir nova entrega; o polling cobre um evento perdido. Cobrança pendente,
expirada ou cancelada não gera saldo. Se o provedor corrigir posteriormente para paga, a conciliação ainda credita
uma única vez.

Antes da futura ativação, validar o fluxo em ambiente separado: assinatura errada não altera saldo, evento de teste
não libera ficha, reentrega não duplica crédito, o último crédito não abre duas fichas concorrentes e outra sessão
não lê a compra. A implementação está coberta por `testes/test_prospeccao_acesso.py` e
`testes/test_prospeccao_webhook.py`. Fontes consultadas para o protocolo:
[segurança](https://docs.abacatepay.com/pages/notificacoes/seguranca),
[Pix v2](https://docs.abacatepay.com/pages/transparents/create) e
[consulta de estado v2](https://docs.abacatepay.com/pages/transparents/check).

### Avisos de buscas salvas

Depois de migrar o banco até `0031` (buscas salvas, após `0030` da plataforma de agentes), executar
`uv run raiz prospeccao verificar-buscas` após cada carga do motor,
ou pelo cron do operador. O comando usa `RAIZ_BANCO_URL`, imprime somente as quantidades verificadas e sai com
erro se a consulta falhar. Para repetir uma única busca: `uv run raiz prospeccao verificar-buscas --busca <UUID>`.
Esta entrega fornece o comando; não instala uma agenda em produção.

A primeira gravação da busca guarda as correspondências sem avisar a base antiga. As próximas verificações
comparam códigos do CAR, independentemente da data do arquivo. Snapshot e avisos são gravados na mesma transação,
com trava por busca; repetir o job ou executá-lo em paralelo não duplica avisos. Os avisos aparecem somente na
conta do cliente e ocultam fazendas reservadas por outro cliente. O job não envia e-mail ou WhatsApp e não libera
fichas pagas. Cada cliente pode manter até 20 buscas salvas; excluir uma remove seu snapshot e seus avisos.

Crédito, risco e caminho da terra são filtros pagos: exigem compra real confirmada com movimento de crédito ou
liberação de ficha com débito auditado. A gravação e cada execução do job conferem essa habilitação; buscas que
a perderem ficam sem novos avisos e entram na contagem `buscas_sem_habilitacao`. Nenhuma nova cobrança é criada
ao filtrar. A pertinência de um CAR a uma faixa é parte desse serviço pago. Combinar filtro avançado com CAR exige
o código completo de uma ficha já liberada; prefixos não permitem deduzir seu valor.

Na lista autenticada, medidas, risco e caminho de uma ficha fechada são nulos. As somas de crédito e área
restaurável abrangem somente as fichas liberadas, com `escopo_metricas=fichas_liberadas` e a quantidade na
cobertura `totais.fichas_liberadas`; contagens, tamanho e sugestões de agrupamento mantêm o universo filtrado.
A ordem da lista é por CAR, sem revelar um ranking de crédito. O agregado regional aberto permanece separado,
sem filtros privados e com a supressão das métricas com menos de cinco fazendas. Os limites persistidos de
consulta continuam valendo para filtros, ficha, comparação e exportação.

## Proteção da main (o fundador ativa à mão)

Depois do primeiro CI desta entrega ficar verde, abra o repositório no GitHub, **Settings → Rules → Rulesets →
New branch ruleset**. Dê o nome `main protegida`, selecione **Active** e inclua o branch `main`.

1. Exija pull request antes de integrar. Para o fundador trabalhar sozinho, não exija aprovação de uma segunda
   pessoa; exija resolver todas as conversas abertas. Se houver revisor, pode exigir uma aprovação e invalidá-la
   quando o código mudar.
2. Em **Require status checks to pass**, selecione os oito checks do workflow **CI**: `workflows`, `segredos`,
   `front`, `seguranca`, `checagens`, `e2e`, `carga` e `mcp`. Prefira a origem **GitHub Actions**, quando disponível. Marque
   **Require branches to be up to date before merging**. Os nomes só aparecem depois de uma execução.
3. Ative **Block force pushes** e **Restrict deletions**. Mantenha a lista de bypass vazia, incluindo para
   administradores, salvo uma política de emergência explícita. Não habilite merge automático do Dependabot
   sem passar pelos mesmos checks.
4. Salve. Confira em um PR de teste que merge com check pendente/vermelho e push direto na main são recusados.
   Para plano sem rulesets, use **Settings → Branches → Add branch protection rule**, padrão `main`, com as
   mesmas exigências e **Do not allow bypassing the above settings**.

A automação atual do motor atualiza `motor/README.md` por push direto. A proteção impedirá esse push: o chat
Dados/operação precisa transformar a atualização em PR. Não conceda bypass geral ao token para contornar isso.
Esta entrega documenta a configuração; não altera as regras da conta do fundador.

Em **Settings → Code security**, habilite **Dependabot alerts**, **Dependabot security updates** e, quando
oferecidos pelo plano, **Secret scanning** e **Push protection**. `.github/dependabot.yml` já agenda atualizações
semanais de uv, npm, Cargo, Actions e imagens Docker. Gitleaks varre todo o histórico acessível em cada PR, mesmo
sem o recurso pago do GitHub; nunca publica o valor encontrado. As exceções verificadas são o nome exato de uma
coluna de `docs/colunas.md`, restrito ao arquivo, e uma ocorrência histórica de `KC_DB_URL` em
`infra/docker-compose.keycloak.yml:28`, commit `be05cee99ee060b5ca2c9e60d7b077d1fa2a51aa`. Esta última contém
somente esquema JDBC, serviço interno, porta e banco, sem usuário, senha ou parâmetros; as credenciais são
variáveis obrigatórias separadas. `.gitleaksignore` restringe a exceção ao fingerprint dessa ocorrência na branch
antiga, sem liberar outras URLs, arquivos ou commits. Credencial real encontrada deve ser revogada primeiro;
retirá-la do último commit não a apaga do histórico.

## CI e controles de segurança

Os oito jobs rodam em paralelo, sem filtro de caminhos nem seleção de testes. `setup-uv` guarda cache pelo
`uv.lock`, `setup-node` guarda o cache npm pelos locks, e o Chromium/LanguageTool têm caches separados. A instalação
continua travada (`uv sync --frozen --all-extras`, `npm ci`). Não se reutiliza `node_modules` de outro lock.

- `front` constrói o mesmo site público e executa os testes unitários, com geometrias de teste determinísticas.
- `checagens` executa toda a coleta pytest, inclusive PostGIS, Rust, cartão, vídeo, PDF, LanguageTool e o conjunto
  privado completo do Pará. O portão exige o caso estadual exatamente uma vez, aprovado, e recusa novos skips/xfails;
  a divergência conhecida de TIR continua executada como `xfail`, detalhada na passagem.
- `e2e` abre Chromium e usa API/PostGIS reais: link de entrada, milhão de créditos no Pará, três opções, interesse
  e reserva Pix local. E-mail e respostas dos donos são controlados; nenhuma credencial de pagamento real é
  aceita. Veja `testes/e2e/README.md`. Não há trace com tokens nos artefatos.
- `seguranca` verifica estilo, CPF/CNPJ e licenças Python instaladas, todos os pacotes dos locks npm e Cargo.
  Inventário ausente/ilegível falha. AGPL, SSPL, Business Source, EUPL e NC são bloqueadas; `BSL-1.0` é a licença
  Boost, permitida, enquanto Business Source (`BUSL-1.1`) é proibida. Exceções manuais não liberam licença proibida.
- `segredos` usa Gitleaks com saída ocultada; `workflows` valida todos os workflows com actionlint.

### Teste estadual com o snapshot privado do Pará

O teste usa as 144 tabelas de desenvolvedor e terra, as entradas e as geometrias congeladas da rodada
`restauracao-2026d+a84f9789`, sem recalcular os municípios nem alterar a sensibilidade do teste. O preparador
`scripts/testar_para_privado.py` fixa o Release draft, os manifests e seus SHA256; confere os pacotes, os hashes
municipais, o modelo, o cenário e a identidade dos 345.870 imóveis. Mudança de modelo exige uma referência
compatível de **Lote e números**; não reetiquetar previsões antigas para fazer o CI passar.

No CI, somente o passo de preparação recebe `RAIZ_DADOS_PRIVADOS_TOKEN=${{ github.token }}`, com permissão
`contents: read`. A suíte recebe apenas a pasta em `$RUNNER_TEMP/raiz-pa` e `RAIZ_TESTE_PA_OBRIGATORIO=1`.
O teste reconfere os arquivos e roda o mesmo caso estadual em subprocesso sem credenciais; stdout, stderr e
JUnit desse filho ficam privados e são apagados. O JUnit público contém apenas o resultado do caso e uma mensagem
fixa se falhar. A pasta tem modo 0700, fica fora do checkout e é removida no passo `always()`.

Não guardar esses arquivos financeiros em Actions cache ou artifact público. PR de fork não recebe credencial
nem os dados: a validação estadual fica explicitamente bloqueada, e o CI não a apresenta como aprovada. Falha
de acesso, hash, modelo ou preparação também deixa o job vermelho; os demais testes ainda são executados.

Para medir localmente, configure as duas variáveis do arquivo privado descritas em `docs/dados-publicados.md` e
execute `uv run python scripts/testar_para_privado.py`. A CLI prepara uma pasta temporária, executa o caso real,
informa somente contagens, tempo e memória e apaga os dados temporários. Para preparar antes da suíte completa,
use `--preparar /caminho/privado/raiz-pa` e forneça somente `RAIZ_TESTE_PA_PASTA` e `RAIZ_TESTE_PA_OBRIGATORIO=1`
ao pytest, retirando as credenciais desse processo; remova a pasta após o ensaio.

A API acrescenta cabeçalhos de proteção e `no-store` nas respostas autenticadas e de pedidos. Por padrão, há
120 chamadas por minuto/IP e 10 chamadas de login por minuto/IP; ajuste `RAIZ_API_LIMITE_MINUTO` e
`RAIZ_API_LOGIN_LIMITE_MINUTO`. O excesso retorna 429 com `Retry-After`. Sem armazenamento configurado, a contagem é por processo. Para vários
workers/réplicas, configure Valkey compartilhado como descrito abaixo. O proxy deve preservar corretamente o IP;
encaminhamentos arbitrários do visitante não devem ser confiados. HSTS depende de HTTPS reconhecido pela API.

Configure `RAIZ_LOGIN_BASE_URL=https://seu-dominio/Raiz/` para o destino canônico do link de entrada; sem ela,
usa-se a primeira origem de `RAIZ_API_ORIGENS`. O cabeçalho `Origin`/`Host` do visitante não escolhe o destino.
HTTP só é aceito para desenvolvimento local. O envio real de e-mail ainda depende da integração do produto.

Presidio e o modelo português instalado pelo lock limpam nomes e contatos nos logs, diagnósticos persistidos,
Healthchecks, Langfuse e erros publicados pelo executor. Se a análise falhar, o texto é suprimido. O access log
padrão do Uvicorn fica desligado para não gravar tokens de links/webhooks nas URLs. Isso não autoriza registrar
texto pessoal bruto: o reconhecimento de nomes tem falsos negativos. Mantenha apenas códigos internos e métricas
nos eventos. Limites da auditoria e pendências estão em `docs/passagem/qualidade-e-seguranca.md`.


## Observabilidade e limite compartilhado

A API e o servidor independente da vigilância escrevem uma linha JSON por registro. Campos fixos: `tempo`,
`nivel`, `logger`, `mensagem`; exceções recebem `excecao`. O log de HTTP tem `evento`, `metodo`, `rota`, `status`,
`duracao_ms` e `requisicao_id` gerado pelo servidor (também em `X-Request-ID`). A rota é o molde do roteador,
como `/pedidos/{pedido_id}`; não registra IP, URL real, query, corpo, cookie ou cabeçalho. O acesso bruto do Uvicorn
continua desligado. Presidio português é aplicado antes de serializar/escrever mensagem e traceback; falha de
NER ou de formatação suprime o original. Extras arbitrários não entram no JSON. Não acrescentar texto de
certidão, dono ou contato aos logs: NER é proteção adicional, não prova de anonimização universal.

`GET /saude` mantém `{"ok": true}` quando consegue consultar o banco. Falha responde 503 com texto genérico;
não expõe DSN nem exceção do driver. A rota também passa pelo limite compartilhado: se o Valkey estiver fora,
responde 503 com `Retry-After: 1`; se o orçamento foi consumido, responde 429. Configure a sonda com IP próprio,
intervalo de 30 s e timeout de 5 s, sem token nem parâmetros pessoais. Logs são JSON no stdout/stderr: encaminhe
pelo journald ou coletor de sua operação, restrinja leitura e defina retenção; não publicar esse fluxo no site.

### Valkey para vários workers

Em desenvolvimento, o contador é local ao processo. Antes de usar vários workers/réplicas, configure todos com:

- `RAIZ_API_LIMITE_STORAGE_URL=redis://:<senha>@127.0.0.1:6380/0` (o protocolo chama-se Redis; o servidor é Valkey BSD-3).
- `RAIZ_API_LIMIT_STORAGE_URI=redis://:<senha>@127.0.0.1:6380/0`: configure também o limite da API paga por empresa (SlowAPI). Sem esta variável, esse contador continua em memória por worker, mesmo com o limite global compartilhado. As duas implementações usam namespaces distintos.
- `RAIZ_API_LIMITE_CHAVE`: segredo aleatório comum, com pelo menos 32 bytes; gere com `python -c 'import secrets; print(secrets.token_hex(32))'`.
- `RAIZ_API_LIMITE_MINUTO=120` e `RAIZ_API_LOGIN_LIMITE_MINUTO=10`, ou tetos acordados para a operação.

A contagem de limite geral/login ocorre na mesma operação atômica. Chaves guardam HMAC do IP, nunca o IP em claro,
e expiram após 60 s. Não trocar o segredo a cada processo: isso separaria os orçamentos. Se o Valkey não responde,
o serviço recusa com 503 e `Retry-After: 1`, sem liberar tráfego por um contador local. Timeout de conexão/comando
é 1 s, sem tentativas automáticas. 429 sempre tem `Retry-After`. A política `noeviction` evita expulsar um contador
ativo para aceitar uma rajada. O AOF persiste o contador; ele não substitui o banco de cobrança/créditos.

O IP é o endereço de conexão visto pelo ASGI. Atrás de um proxy, configure `--forwarded-allow-ips` somente com IPs
dos proxies confiáveis e sobrescreva `X-Forwarded-For` no proxy com o IP observado; nunca confie em `*` nem no
cabeçalho que o visitante forneceu. Use HTTPS no proxy e `rediss://` com validação TLS ao acessar Valkey fora da
máquina/rede privada. Desligue o access log bruto do proxy, ou use formato que não contenha URL/query/IP pessoal.

### GlitchTip próprio

Configuração em `infra/docker-compose.observabilidade.yml`, separada dos dados do produto. Versões:
[GlitchTip 5.2.0 MIT](https://gitlab.com/glitchtip/glitchtip-backend/-/blob/v5.2.0/LICENSE), Valkey 8.1.4 BSD-3 e
PostgreSQL 16 (licença PostgreSQL). O cliente Python `sentry-sdk` é MIT; não se instala o servidor Sentry nem CLI FSL.

1. Guarde no `.env` (fora do git, modo 600) `RAIZ_GLITCHTIP_BANCO_SENHA`, `RAIZ_GLITCHTIP_SECRET_KEY` e
   `RAIZ_VALKEY_SENHA`. Gere cada um separadamente com o comando acima. Hexadecimal evita caracteres que precisem
   de escape na URL. Não usar os valores ilustrativos de testes.
2. Defina `RAIZ_GLITCHTIP_DOMAIN=https://erros.seu-dominio`, `RAIZ_GLITCHTIP_HOSTS=erros.seu-dominio,localhost,127.0.0.1`.
   Proteja o host com HTTPS e acesso administrativo restrito. A publicação do Compose é somente `127.0.0.1:8001`;
   o banco não publica porta. `RAIZ_GLITCHTIP_PORTA` e `RAIZ_VALKEY_PORTA` permitem mudar as portas locais.
3. `docker compose --env-file .env -f infra/docker-compose.observabilidade.yml up -d`.
   O serviço `migrar` precisa concluir antes do web/worker. Confira `ps` e o `/_health/` local do GlitchTip.
4. Crie o administrador com `docker compose --env-file .env -f infra/docker-compose.observabilidade.yml exec web ./manage.py createsuperuser`.
   Cadastro público e criação pública de organizações estão desligados. Crie organização/projeto da API no painel.
   Copie o DSN do projeto para `RAIZ_GLITCHTIP_DSN` no ambiente da API e reinicie os workers.
5. Sem DSN, a API não cria o cliente nem envia eventos. As integrações automáticas do SDK, tracing, perfil,
   corpo, cabeçalhos, usuário, breadcrumbs, variáveis locais e trechos de código estão desligados. Só erros não
   tratados são capturados; antes do transporte, uma allowlist reconstrói tipo da exceção e arquivo/linha do
   código da Raíz. Mensagem da exceção é omitida, inclusive se nela houver dado que o NER não reconheça.
6. Retenção configurada em 30 dias. Faça backup do volume PostgreSQL conforme a política privada. Email está no
   backend nulo: nenhum email de usuário vai para o console e nenhum alerta é enviado automaticamente. Se quiser
   alertas, configure SMTP no serviço sob a política da operação; não usar `consolemail://` em produção.

O serviço e os segredos ainda precisam ser ligados no servidor pelo operador: esta entrega prepara e testa a
configuração, não provisiona DNS/TLS nem envia dados a um serviço remoto.



## Carga da API no CI e no servidor

Usamos Locust 2.47.0, MIT (https://pypi.org/project/locust/2.47.0/ e https://github.com/locustio/locust/blob/2.47.0/LICENSE). Nenhum k6 ou pacote de serviço Locust Cloud foi adicionado. O Locust é dependência de desenvolvimento travada no uv.lock.

```bash
# Banco criado previamente no PostGIS local, exclusivamente para este ensaio.
export RAIZ_BANCO_URL_CARGA=postgresql+psycopg://raiz:raiz@localhost:5432/raiz_carga
uv run python -m testes.carga.rodar --resultado resultado-carga
```

O comando apaga e migra **somente banco local com sufixo `_carga`**. Recusa `raiz`, `raiz_teste`, `_e2e` e destinos remotos. Usa a amostra versionada do repositório, API/FastAPI e consultas PostGIS reais; credenciais, token e chave pessoal são descartáveis, configurações `.env`/integrações externas ficam fora do servidor do teste. Nenhum WhatsApp, Pix, modelo remoto ou e-mail é acionado. O token fica apenas no ambiente do subprocesso e não aparece nos argumentos nem nos relatórios.

A carga consulta `/saude`, `/municipios` e `/municipios/1504950/imoveis` com seis usuários concorrentes. Duas fases de dez segundos: orçamento alto para medir respostas reais sem 429, depois orçamento de seis chamadas por janela de dois segundos para demonstrar saturação. Essa janela curta é injetada somente no servidor de teste; a configuração do produto não é alterada. Ao final, o teste provoca outro 429, espera exatamente o Retry-After mais 100 ms e exige retorno 200.

Reprova se houver menos de 20 requisições por fase, rota sem resposta válida, erro de conteúdo/status, qualquer resposta de 5 s ou mais, 429 na fase normal, ausência de 429 na saturação, Retry-After ausente/inválido ou ausência de recuperação. Os 429 esperados contam como controles atendidos, sem mascarar os outros erros. O teste de regressão também demonstra que um servidor que apenas bloqueia tudo não passa.

`--usuarios N --segundos N` permite ampliar o ensaio no servidor local. O perfil do CI é uma verificação curta de desempenho e dos controles; **não é estimativa de capacidade máxima nem SLA de produção**. O CI publica somente os JSON agregados, sem corpos, tokens, IPs, nomes ou contatos. Logs do servidor são locais e não devem virar artefato público.


## Testes de agentes e ferramentas MCP

O corpus de injeção, os controles limpos, o contrato dos observadores de efeitos e os comandos estão em
[`testes/mcp/README.md`](../testes/mcp/README.md). O auditor exige preservar a tarefa legítima e nenhuma ação
indevida; tentativas recusadas também são examinadas. Cada ferramenta precisa responder em menos de 5 s,
com o inventário completo de `tools/list`, sem selecionar apenas as rápidas.

A main agora inclui o MCP OAuth dos PRs #45/#69 e a ficha do #72. O job testa HTTP, RS256/JWKS local, vínculo de empresa,
as sete ferramentas, prazo e carga com PostGIS descartável. Seu retorno rápido pode ser admissão de trabalho
assíncrono; não é promessa de cálculo completo em cinco segundos. As intenções da carga são idempotentes.

O corpus de certidão/edital/nome de arquivo ainda depende de **Produto e regras**: as ferramentas atuais não
oferecem agente cliente nem leitura dessas entradas. O runner grava resultados parciais e falha explicitamente
pelo corpus ausente. A autorização anterior para pular era somente ausência do servidor, que já não se aplica.
Sem orientação adicional do fundador, essa pendência bloqueia o merge. Não simular agente/leitura para liberar CI.

O código e os requisitos estão em [`testes/mcp/README.md`](../testes/mcp/README.md). As regressões do auditor
não comprovam resistência de um agente de produção. A carga usa `testes/carga/locust_mcp.py`, com credenciais
somente de teste; instruções em [`testes/carga/README.md`](../testes/carga/README.md).

## Portões antes da publicação

O contrato completo, faixas, formatos e triagem de saltos municipais estão em
[`docs/qualidade-dados.md`](qualidade-dados.md). Pandera verifica colunas obrigatórias, área de componentes
contra o CAR, quantis e porcentagens; formatos desconhecidos e violações de privacidade impedem o upload.
O erro informa a regra e o nome técnico do arquivo, sem imprimir a célula. Não truncar áreas nem apagar fazendas
para liberar uma rodada. O chat **Dados** corrige a origem e recalcula; históricos já publicados não são alterados
por este controle. O produtor deve manter a coluna e representar fonte ausente por nulo.

- Motor/executor: arquiva os originais no destino privado autenticado e valida todos os bytes da projeção
  `publico_basico` antes do primeiro upload aberto da UF. O fluxo legado segue a mesma divisão; não envia o pacote
  completo ao Release público. `uv run python -m raiz.qualidade_dados dados-entrada` confere as tabelas completas
  para revisão científica, sem autorizar sua exposição. O contrato básico está em `docs/colunas.md`.
- Vigilância: verifica o conjunto de alertas e o resumo antes de arquivar no destino privado; dados de projeto,
  perdas e marcações também exigem cifra. O #72 retirou a publicação aberta de histórico por CAR.
- Busca: `uv run python -m raiz.qualidade_busca caminho/busca.sqlite caminho/novidades_DATA.md caminho/novidades_DATA.csv`.
  Confere os três arquivos, o esquema e a correspondência dos resultados; recompõe o SQLite aprovado para remover
  restos de linhas apagadas. O workflow executa o portão antes do Release, resumo e issue. Nome rotulado como autor
  não recebe liberação automática. Não foram disparados envios nem issues nesta entrega.
- Calendário: `python3 -m raiz.qualidade_calendario --pasta dados/calendario` valida os originais `estado.json`,
  `eventos.json` e `eventos.ics`, sua correspondência e os campos conhecidos antes do upload. O workflow só publica
  quando esse passo teve sucesso, inclusive quando a coleta parcial termina com erro. O site reconstrói JSON/ICS
  a partir dos campos aprovados e revalida o cache; não copia os bytes remotos. O portão do site usa somente a
  biblioteca padrão do Python, sem instalar as dependências científicas no job do front.
- Rodada do Pará: `raiz.restauracao_rodada.publicar` arquiva lotes, previsões e folhas somente no destino privado;
  a visibilidade é conferida antes de cada transferência. Arquivar o original para auditoria/reprocessamento não
  significa aprovar sua qualidade ou exposição. `raiz.qualidade_rodada` conserva a validação quantitativa do antigo
  contrato público e recusa HTML/folhas individuais; esse contrato não reabre o publicador retirado pelo #72.

Os workflows de publicação do site e da busca também usam dependências travadas pelo `uv.lock`, com cache.
A validação impede nova publicação irregular; não é limpeza retroativa de Releases, bancos ou logs externos.

## Revisão contínua da main

Cada push da main executa os oito jobs de CI, incluindo segredos, licenças, privacidade, testes e carga. A revisão
semântica de cada PR integrado fica registrada em `docs/passagem/qualidade-e-seguranca.md`, com commit e chat dono
dos achados maiores. Correção pequena precisa de regressão e PR com todos os checks verdes.

Por decisão do fundador, ficam somente as checagens por push, sem automação horária. Checagens por push não são
apresentadas como revisão automática de lógica por um agente. A proteção da main continua sendo ativada à mão.
