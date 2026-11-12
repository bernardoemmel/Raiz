# Raíz · Dados do Brasil

Ordens da coordenação para este chat. Leia o README desta pasta. Regras de sempre: CLAUDE.md, docs/cena-alvo.md, merge você mesmo com CI verde.

## 1. Paralelismo máximo e filas separadas (12/11)
estado: nova

O Brasil está lento: 257 de 5.571 municípios; com 4 estados por vez e ~2 min por município, são ~2 dias.
- Repositório público no GitHub aceita até 20 jobs ao mesmo tempo. Suba o paralelismo para perto disso; nos estados
  grandes (MG, BA, SP, RS, PR, GO) divida em fatias de municípios em jobs separados.
- Separe as filas: completar tarefa nova em estado já feito (PA, RO, AC) não pode segurar vaga de estado que nem
  começou. Os estados que não começaram entram já, em paralelo.
- Não quebre a trava do estados.json nem a publicação. Teste, PR, merge e redispare a fila.
- Escreva aqui o novo tempo estimado para o Brasil inteiro.

## 2. Plano atualizado e próximos passos de E1 e E2 (12/11)
estado: nova

Em docs/plano-por-etapa.md, marque "feito" o que já está na main em E1 (coleta) e E2 (funil); o plano está
desatualizado (10 de 182 passos marcados). Depois siga os próximos passos de E1 e E2 pela ordem de dependência.
