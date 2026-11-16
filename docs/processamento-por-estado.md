# Processamento por estado

O painel do mapa mostra municípios prontos, rodando agora e com erro, além da hora
da última mudança e da observação. Os horários da tela são de Brasília. Uma
contagem ausente aparece como **não informada**; um zero publicado é um zero real.
Os municípios disponíveis no mapa continuam sendo apresentados separadamente.
Ter um CSV não comprova que todas as tarefas municipais terminaram.

A fonte padrão é
`https://raw.githubusercontent.com/bernardoemmel/Raiz/status-processamento/processamento.json`.
O navegador consulta a cada 30 segundos quando a aba está visível, sem token nem
credenciais. `VITE_RAIZ_PROCESSAMENTO_URL` permite configurar outra fonte pública;
`VITE_RAIZ_API` usa `GET /processamento/publico`. O build também produz
`amostra/processamento.json`, que pode ser usado como snapshot explícito. Gerar ou
consultar um snapshot não renova a validade da observação original.

O executor publica eventos municipais com código IBGE, situação, unidade, rodada,
tentativa e horários. Esses eventos são agregados municipais; não contêm CAR,
nomes, mensagens de erro, caminhos locais nem segredos. A ref pública exclusiva
`refs/heads/status-processamento` contém apenas esse JSON. Cada gravação usa
compare-and-swap (`force-with-lease` somente nessa ref) e um commit sem pai. Uma
gravação concorrente relê e reúne os eventos antes de tentar novamente. A rotina
não faz checkout, não altera a main, os Releases ou a fila, nem dispara Actions.

O resumo usa a lista oficial de municípios que acompanha o executor e deduplica
cada código IBGE por rodada, tentativa e instante observado. Um worker de rodada
antiga não substitui uma tentativa nova. Municípios ainda não observados entram
como desconhecidos; estados sem evento têm todas as contagens não informadas.
O número de jobs do Actions nunca é usado como número de municípios em execução.

O heartbeat municipal fornece seu próprio prazo de validade. Quando ele vence,
o município passa a desconhecido no próximo resumo. A tela retira a indicação
“rodando agora” assim que a validade estadual vence, inclusive durante falha ou
lentidão da consulta. As demais contagens antigas continuam identificadas como
observações vencidas. Uma fonte que cobre apenas uma unidade é mostrada como
parcial, sem ser apresentada como cobertura completa do estado.

Validação local, sem publicar nada:

```sh
uv run pytest -q testes/test_processamento_publico.py testes/test_status_publico.py
cd front/globo
npm test -- src/processamento-estados.test.ts ../compartilhado/testes/processamento-publicado.test.ts ../compartilhado/testes/download-processamento.test.ts
```

Os testes de concorrência usam dois repositórios e um remoto bare temporário,
todos locais. Eles conferem a retenção das duas observações e a ausência de
histórico encadeado, sem enviar dados ao GitHub.
