# Vigilância dos lotes do Brasil processado

A rodada diária lê DETER, MapBiomas Alerta e focos VIIRS de NOAA-20/21 e cruza somente CARs de pedidos ativos.
Entram lote e reserva; enquanto não há escolha, vale a opção barata salva, como no vigia do pedido. Contratos
continuam monitorados. Pedidos cancelados, clientes inativos e fazendas retiradas não entram. Fazenda pequena
permanece no recorte. O catálogo guarda só `cliente_id`, `pedido_id`, data de criação e CAR, sem nome ou contato.

Um lote não é um projeto registrado na Verra. Proponente, registro, causa, área afetada confirmada e perda de
carbono ficam a preencher pelo desenvolvedor. O cliente interno identifica o dono do pedido.

## Coleta e cobertura

O workflow `vigilancia.yml` roda às **6h17 de Brasília** com `rodar --lotes`. Usa `RAIZ_BANCO_URL`, se configurada;
senão, lê `lotes-vigilancia.json` no arquivo privado autenticado. O snapshot vale 36 horas. Catálogo ausente,
vencido ou inválido interrompe a rodada sem trocar o recorte por todas as fazendas ou apagar estado anterior.
Catálogo vazio significa zero alvos, não o Brasil inteiro. Cenários CAD Trust por UF não substituem o catálogo:
não identificam o desenvolvedor dono de um pedido.

Polígonos e catálogo usam `RAIZ_DADOS_PRIVADOS_URL`. O consumidor reconfere repositório privado ou Release draft.
CAR sem polígono processado fica na contagem de cobertura incompleta. Mudança nos CARs invalida o cursor: fazenda
nova entra mesmo sem publicação nova da fonte. CAR citado pelo MapBiomas não amplia esse universo.

DETER e MapBiomas são indícios com sobreposição geométrica efetiva. **Foco NOAA não confirma incêndio, área
queimada ou perda de carbono.** Registros NOAA-20/21 do mesmo CAR/dia ficam em um aviso, com evidências separadas,
sem somar áreas de pixels. Nova passagem atualiza o rascunho sem outro aviso. Falha de um satélite preserva o outro
e marca cobertura parcial. HTML de erro ou CSV inválido nunca vira “zero focos”.

Erro, cobertura parcial ou MapBiomas sem credencial deixam a execução vermelha depois de guardar o resultado
útil. O resumo do Actions contém somente contagens e estado das fontes, sem cliente, pedido ou CAR.

## Ponte automática com o servidor

Configurar no ambiente do servidor `RAIZ_BANCO_URL`, `RAIZ_DADOS_PRIVADOS_URL`, `RAIZ_DADOS_PRIVADOS_TOKEN` e
`RAIZ_VIGILANCIA_CHAVE`. A chave cifra os rascunhos. MapBiomas exige `MAPBIOMAS_ALERTA_EMAIL` e
`MAPBIOMAS_ALERTA_SENHA`; `FIRMS_MAP_KEY` é opcional, pois NOAA-20/21 oferecem arquivos públicos.

```bash
uv run python scripts/instalar_cron_alertas.py --tarefa vigilancia_lotes
uv run python scripts/instalar_cron_alertas.py --tarefa vigilancia_lotes --instalar
```

O cron executa `python -m raiz.vigilancia lotes-ciclo --publicar` a cada 15 minutos, com trava e `.env` carregado
pelo `uv`: renova o catálogo do banco no draft e importa rascunhos da última rodada para o painel. Não exige
exportação manual diária nem cria segundo coletor concorrente. `exportar-lotes --publicar` serve para uma
conferência pontual. Sem acesso ao servidor e à configuração, preparar o instalador não significa instalar o cron.
Não criar catálogo artificial para tornar a rodada verde.

## Rascunhos e isolamento

Rascunhos ficam em `privado/rascunhos_lotes.json`, dentro do estado cifrado no destino privado. A importação trava
o pedido e reconfere cliente ativo, titularidade, cancelamento e participação do CAR. Só então grava o alerta e
uma notificação **no painel**. Não chama enviador de e-mail, WhatsApp, webhook ou Verra. Repetição e concorrência
não duplicam a notificação.

As rotas exigem sessão de uma pessoa da empresa, liberação paga e titularidade. Uma chave de agente não substitui
a sessão. Respostas usam `Cache-Control: no-store`:

- `GET /v1/pedidos/{pedido_id}/vigilancia/relatorios`
- `GET /v1/pedidos/{pedido_id}/vigilancia/relatorios/{relatorio_id}.md`

Duas empresas podem ter o mesmo CAR: cada uma tem seu rascunho, sem acesso ao pedido da outra. Correção de
titularidade não entrega ao novo titular documento congelado de outra empresa.

## Evidência e limites

Sondagens reais em 12/11/2026: os CSV públicos [NOAA-20](https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_America_48h.csv)
e [NOAA-21](https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_America_48h.csv)
responderam HTTP 200 com cabeçalho geográfico. O [WFS TerraBrasilis](https://terrabrasilis.dpi.inpe.br/geoserver/ows)
retornou `FeatureCollection` DETER. A [API MapBiomas](https://plataforma.alerta.mapbiomas.org/api/v2/graphql)
informou a última publicação, mas a consulta de alertas sem autenticação respondeu “Token de acesso inválido”.
O status público da publicação não comprova permissão para baixar alertas.

O draft autenticado `dados-privados` foi conferido: contém `cadt_lotes.json`, mas não `lotes-vigilancia.json` nem
`vigilancia.json` neste instante. Não havia catálogo real de clientes/pedidos para iniciar uma rodada completa.
Os testes cobrem polígonos, fazenda menor que um hectare, recorte, catálogo vencido, mudança de lote, NOAA duplicado,
falha parcial, duas empresas e concorrência em PostgreSQL/PostGIS. Fixtures verificam funcionamento; não são
conjunto real para medir acerto nem dados reais de clientes.
