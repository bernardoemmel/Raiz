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

## Onde olhar

| O quê | Onde |
|---|---|
| Lote parado ou com falha | Healthchecks (alerta) e `operacao.lote` (estado, duração, fim do log) |
| Custo de modelo por tarefa e por fazenda | Langfuse (sessão = código do CAR) e `operacao.chamada_modelo` |
| Decisões da cascata ABC | `operacao.decisao_cascata` |
| O que precisa de decisão humana | `operacao.fila_revisao` (API: `GET /revisoes`) |
| Mensagens esperando aprovação | `pessoal.mensagem_saida` (API: `GET /mensagens/pendentes`) |
| Acerto das previsões | `uv run raiz aprendizado placar` e `aprendizado.previsao_contra_gabarito` |
