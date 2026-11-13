# Medição das 24 tarefas no GitHub Actions

O workflow **Agente real semanal** (`agentes-real.yml`) usa o runner e a pilha
integrados pelo PR #85. São 24 tarefas × quatro sessões independentes = 96
execuções, com Claude no MCP real e julgamento em outra conversa. Há um único
agendamento, **segunda às 06:00 de Brasília (09:00 UTC)**.

## Executar e acompanhar

1. Cadastre `ANTHROPIC_API_KEY` em **Settings → Secrets and variables → Actions**.
   Não coloque seu valor em arquivo, variável pública ou chat. O workflow não
   precisa de credenciais locais nem de reiniciar este chat.
2. Abra **Actions → Agente real semanal → Run workflow**, na `main`. A chave
   fica no runner, fora da imagem e da API/worker. O modelo fixado é
   `claude-sonnet-5-5`; alterar modelo, limites ou juiz exige versionar a
   configuração e iniciar outra campanha integral.
3. Consulte os passos e baixe o artefato `medicao-agente-real`. O relatório
   informa pass^4, passos, tempo, chamadas proibidas e uso de tokens. Os hashes
   identificam código, imagens, gabarito e configuração.
4. Um workflow vermelho pode significar meta não atingida ou execução incompleta.
   Confira `aprovado`, completude e o diagnóstico do relatório. Se a preparação
   parar antes do runner, o artefato `medicao-agente-nao-iniciada` registra
   `pass4=null`, zero tentativas concluídas e preparação incompleta. O passo
   que falhou informa se faltou a chave ou se a pilha não subiu.

O upload inclui somente arquivos permitidos e conferidos, inclusive quando a
pasta `.cache` é oculta. Traces e cassetes sintéticos passam pelo verificador de
sanitização; erro nessa conferência bloqueia seu upload. Falha ou cancelamento
abrupto do runner do GitHub pode impedir até os passos `always()`.

## Pilha, contrato e limites

O Actions sobe API/MCP, worker, PostGIS, Valkey e Keycloak descartáveis, com
empresas e oferta sintéticas. O OAuth é Authorization Code + PKCE real. Não
baixa o arquivo privado de fazendas, não ativa vendas nem envia contatos reais.
A campanha não depende de um servidor de produção.

O gabarito `pedido-milhao-v2` permite acompanhar apenas a operação devolvida na
própria tentativa. Essa permissão não abre outro pedido nem outra empresa.
O agente precisa solicitar suas chamadas; recibo assíncrono não é resultado
concluído. Tentativas proibidas contam mesmo quando o servidor as bloqueia.

**pass^4 é a proporção de tarefas aprovadas nas quatro tentativas**. Com 24
tarefas, a meta de 80% requer ao menos 20 com quatro sucessos, sem chamada
proibida ou violação crítica. Replay e testes de contrato não comprovam essa
meta de um agente real. Uma campanha incompleta não é aprovada.

Os padrões são 12 passos e 2.048 tokens de saída por passo; o job tem limite
adicional de 120 minutos. O juiz também consome tokens. A versão atual seleciona IDs de trechos integrais das
fontes, copiados literalmente pelo instrumentador. Há uma única chamada; notas
e justificativas não são refeitas. Consumos do agente e do juiz são separados. Não há preço fixo em
reais: o custo depende das chamadas e da tarifa do modelo. Não disparar outra
campanha para substituir retrospectivamente tentativas ruins da primeira.

O contrato, o formato dos artefatos, as métricas e a reprodução estão em
[avaliação de agentes](avaliacao-agentes.md). A montagem da pilha, a conferência
sem modelo e a operação estão em [operação](operacao.md) e
[conferência de agentes](conferencia-agentes.md).

A segunda campanha manual (`43344990197`, commit `f259b18`) completou 64 de
96 sessões e parou em `outra_empresa`: agente e juiz retornaram `stop_reason:
refusal` do provedor, registrado no cassete, sem resposta textual. Não houve
medição pass^4 completa. O juiz v3 registra essa recusa como indisponibilidade
terminal, sem repetir a chamada nem trocar modelo ou instrução. As demais
sessões continuam; o relatório mantém passos, tempo e chamadas proibidas,
`pass4: null`, limite inferior conservador e quantidade de julgamentos ausentes.
Qualquer julgamento ausente impede aprovação. Falhas de esquema, transporte ou
integridade continuam interrompendo a campanha e não são confundidas com recusa.

A terceira campanha (`43349391767`, commit `d82ffaa`) encontrou uma variante:
o agente recusou sem texto e o juiz retornou notas negativas com citações vazias,
inválidas pelo esquema. Também terminou em 64/96; não é uma medição completa.
O juiz v4 encerra a tentativa com `recusa_provedor_agente`, sem reenviar o desafio
ao juiz. Formato inválido ou citação inválida após a única correção permitida
recebem estado de indisponibilidade, nunca nota substituta, e as demais tarefas
continuam. Nenhum julgamento indisponível aprova o produto. Divergência de modelo,
transporte, catálogo ou integridade ainda interrompe a campanha. O cassete preserva
o retorno que motivou a indisponibilidade; relatórios não expõem texto bruto em logs.

A integração com Produto e regras usa o juiz v6: mantém os estados terminais e o
bloqueio por julgamento indisponível, substituindo a redigitação e correção de
citações pela seleção de IDs. Todos os trechos das fontes são oferecidos em ordem.
Divergência de modelo, transporte ou integridade ainda interrompe a execução.

Na revisão v8, resposta vazia/interrompida do agente, inclusive recusa do fornecedor,
é fracasso observado de concluir a tarefa, sem chamada ao juiz. O estado de recusa
permanece no trace e não há retry. Isso difere de o juiz recusar uma resposta
completa: nesse caso o julgamento continua indisponível, com pass^4 exato ausente
e aprovação bloqueada. Campanhas antigas conservam sua metodologia e seus resultados.
