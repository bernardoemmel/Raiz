# Ordens da coordenação

A coordenação da Raíz (thread do Bernardo) escreve aqui as ordens para cada chat do Claude Code. Cada chat lê o
próprio arquivo e cumpre como se fosse pedido do Bernardo.

| Chat | Arquivo |
|---|---|
| Raíz · Dados do Brasil | `dados-do-brasil.md` |
| Raíz · Produto e regras | `produto-e-regras.md` |
| Raíz · Telas e mapa | `telas-e-mapa.md` |
| Raíz · Vigilância e alertas | `vigilancia-e-alertas.md` |
| Raíz · Documentos e IA | `documentos-e-ia.md` |

Como cada chat usa:
1. A cada hora (tarefa agendada no próprio chat) e ao terminar cada entrega: `git fetch origin main` e ler
   `docs/ordens/<seu arquivo>.md` na `origin/main`.
2. Cumprir as ordens com `estado: nova`, na ordem. Ao terminar, trocar para `estado: feita (data, PR)` e escrever
   uma linha de resultado embaixo da ordem, no mesmo PR da entrega.
3. Merge você mesmo com o CI verde (regra do CLAUDE.md). Não editar o arquivo de outro chat.
