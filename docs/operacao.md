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
