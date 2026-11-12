# Aprendizado por tempo

O backtest refaz as versões atuais do motor, FLAG e restauração contra as entradas
que a Raíz conhecia em cada corte. Não afirma que aquela versão do código já era
usada naquele ano. Cada lote guarda modelo, versão, corte, horizonte, hash das
entradas e hash da receita como `backtest`, no mesmo registro do campeão e do
desafiante. Não altera a oferta nem as rodadas de produção.

## Fontes históricas do motor

`raiz/aprendizado/reexecucao.py` chama o `municipio()` real do motor. Todas as suas
fontes vêm do scd2, com `_dlt_valid_from <= corte` e `_dlt_valid_to > corte` ou nulo.
Uma fonte vazia e uma fonte sem histórico são situações distintas. Para aceitar
uma camada vazia, precisa existir uma conferência da coleta completa naquele
período. Não há reserva para download ou cache atual.

O contrato `FONTES` no módulo define as colunas públicas e estas fontes:

| Arquivo no retrato | Conteúdo |
|---|---|
| `car.parquet` | CAR, com o `_hash` daquela versão e geometria |
| `sigef.parquet` | Parcelas, matrícula e cartório, sem dados de pessoas |
| `ibama.parquet` | Embargos e situação, com WKT, sem dados de pessoas |
| `biomas.parquet` | Cartografia dos biomas |
| `yd.parquet`, `acc.parquet` | PRODES anual e acumulado |
| `nf.parquet`, `hy.parquet` | Não floresta e hidrografia |
| `ti.parquet`, `uc.parquet` | Terras indígenas e unidades de conservação |
| `projetos.parquet` | Polígonos de projetos registrados |
| `alertas.parquet` | Alertas do MapBiomas com ano de detecção |
| `regeneracao.parquet` | Pasto, secundária e pasto a até 1 km da mata por CAR |

As camadas espaciais são GeoParquet com CRS e coluna `geometry`. As demais são
Parquet. A chave `car_hash` da regeneração precisa corresponder ao `_hash` do CAR
usado no zonal. O ano do raster, sozinho, não prova que o dado estava disponível
no corte. Um imóvel pequeno continua no resultado do motor.

### Começar a guardar os retratos completos

```bash
uv run raiz aprendizado arquivar-fold --pasta dados/retrato/PA/1504950 \
  --uf PA --municipio 1504950 --catalogo dados/folds/1504950.json
```

A pasta de destino do catálogo precisa existir. O comando só lê as colunas
permitidas. Todas as fontes são validadas antes da primeira gravação; publica o
conjunto na mesma transação, no esquema separado `historico_modelos`. Não toca o
`bruto`. A data de conhecimento é a hora do banco: o comando não tem opção de
retrodatá-la. Repetições confirmam a coleta sem duplicar versões; camada que
ficou vazia fecha suas versões anteriores. As tabelas são criadas pelo arquivador,
como as tabelas dinâmicas da coleta dlt; não há nova revisão do Alembic.

O catálogo gerado descreve a cobertura efetivamente arquivada por município. Para
usar fontes de outro arquivo scd2, o JSON tem `fontes`, com uma entrada por nome
da tabela acima: `desde`, `ate` (instantes ISO com fuso), `referencia` da conferência,
`esquema`, e opcionalmente `tabela` e `por_municipio`. Não declarar cobertura para
um período que não foi coletado ou para o qual não existe evidência.

### Reexecutar os folds

```bash
uv run raiz aprendizado reexecutar --catalogo dados/folds/1504950.json \
  --uf PA --municipio 1504950 --inicio 2027-01-01 --fim 2028-01-01
```

As datas são exemplos de cortes futuros: o comando só funcionará quando estiverem
dentro da cobertura arquivada. Cada corte anual é às 00:00 UTC. Pode-se escolher
`--modelos motor,flag` e usar `--no-congelar` para conferir a rodada sem registrar
previsões. Pela API Python, `reexecutar()` também aceita instantes exatos com fuso.
O terminal usa uma transação `REPEATABLE READ`, mantendo o mesmo retrato do banco
durante a execução inteira.

A restauração usa as premissas fixas versionadas e não lê a calibração nem a PTAX
gravadas hoje. Isso é uma linha de base sem recalibração. Treinar os ajustes de
cada fold exige gabaritos disponíveis até seu corte. O comando existente
`aprendizado folds` continua fazendo o backtest temporal da calibração.

### Limite operacional atual

A coleta existente guarda CAR, SIGEF e Ibama no scd2. A captura e exportação
agendada do conjunto completo acima ainda precisam ser ligadas ao executor.
`arquivar-fold` torna o armazenamento e a reexecução executáveis, mas não fabrica
arquivos nem safras históricas. Sem essas entradas, o fold falha explicitamente.
Não foi feita uma avaliação real de anos anteriores nesta entrega. Outros
modelos, além dos três adaptadores acima e da sobrevivência abaixo, precisam de
adaptadores e do histórico de todas as suas entradas antes de entrar nesse teste.

## Tempo até o aceite

```bash
uv run raiz aprendizado sobrevivencia-aceite --horizonte 14
uv run raiz aprendizado sobrevivencia-aceite --horizonte 14 --congelar
uv run raiz aprendizado sobrevivencia-placar
```

O modelo usa somente contatos reais enviados, separados por pedido e CAR. O
relógio começa no envio. Aceite e recusa são eventos competitivos: a recusa não é
tratada como simples censura, que aumentaria artificialmente a chance de aceitar.
Contatos ainda abertos são censurados no corte. Entram apenas eventos ocorridos
e registrados até esse instante; não se lê a situação atual da oferta para
reconstruir o passado. `--corte` aceita um instante ISO com fuso e grava como
`backtest` quando combinado a `--congelar`.

O ajuste exige pelo menos 30 contatos reais e 5 aceites. É uma estimativa agrupada,
sem calibração por perfil. O retorno distingue chance zero de falta de seguimento
para aquele horizonte. Cada previsão conserva pedido, envio, corte, prazo, curva,
versão do código e versão do lifelines. O placar Brier confere a mesma pergunta
por pedido e prazo, deixando à parte eventos anteriores ao corte que só ficaram
conhecidos depois. Nenhuma curva simulada é promovida a evidência de qualidade.

O otimizador mantém a chance beta-binomial por perfil enquanto o modelo temporal
acumula e mede previsões reais. SQLMesh e Dagster continuam fora desta entrega;
o executor próprio permanece conforme a decisão anterior.
