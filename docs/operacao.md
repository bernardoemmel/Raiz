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
  adesivo.png}` e `/video/{codigo}.mp4` e `-720p.mp4`. Antes do aceite do dono só saem município, hectares, selo e
  código curto; o código do CAR e a imagem de satélite da fazenda só depois do aceite.
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
- Cenários (raiz/regras/padroes/cenarios_restauracao.yaml): o padrão é `central_r11` (rodada 11 do fundador: captura
  em curva na forma da URTX, custos oficiais do SFB, descontos em ordem com piso de 10% na linha de base e vazamento de
  10%, marcos do ProFloresta+ com multa e rescisão, dono pago por 40 anos, Fundo Clima até 50% pelo ICSD 1,3, venda a
  US$ 30 depois do ano 25, WACC de 9,2%); `central_r11_74`, `estresse_r11` (linha de base e vazamento de 40%) e as
  premissas antigas em `otimista_fundador` e `otimista_fundador_74`. Referência (fazenda de 100 ha no leste do PA, US$
  55, câmbio de R$ 5,40): TIR com financiamento de ~6,8% no plantio e ~14,6% na regeneração assistida.
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
  mais compacta), cada uma com fazendas de reserva (15% da meta). `POST /pedidos/{id}/lote` (ou `PATCH`) tira ou troca
  uma fazenda e refaz os números. Cada lote sugerido fica em `negocio.pedido_sugestao` com a versão do modelo.
- Interesse do dono: `negocio.interesse_dono` (nível de agora) e `negocio.interesse_evento` (cada registro com data,
  canal, motivo e versão do termo); o nível só sobe com a versão do termo; recusa vale um ano. Nome e CPF ficam só no
  esquema pessoal; a API devolve só o nível. Resposta do dono: `POST /interesse/{cod_imovel}` (token da API) ou
  `raiz pedidos resposta`.
- Ondas: `POST /pedidos/{id}/solicitar-interesse {opcao}` contata a 1ª onda (até a soma de chance de aceite vezes
  crédito dar 1,5 vez a meta; envio simulado por enquanto, WhatsApp quando o dono tem contato, senão carta). `raiz
  pedidos ciclo` (de hora em hora no cron) vence quem não respondeu em 15 dias, chama a próxima onda, fecha o grupo
  quando os interessados alcançam a meta (aviso no painel, e-mail e WhatsApp) ou diz o que faltou.
  `GET /pedidos/{id}/andamento` mostra a meta com interessado, aceite e contrato, as ondas, recusas e motivos.
- Reserva: `POST /pedidos/{id}/reservar` cria a cobrança Pix pela AbacatePay (`RAIZ_ABACATEPAY_CHAVE`; sem chave,
  cobrança de teste, paga com `raiz pedidos pagar-teste <id>` ou `POST /pagamentos/teste/{id}/pagar`). O aviso de
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
