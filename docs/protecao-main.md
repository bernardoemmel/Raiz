# Proteção da branch main

Regra: todo código entra na `main` por PR, com o CI verde. Sem push direto, sem force-push, sem apagar a branch,
inclusive para administradores. Não há "Approve" obrigatório do GitHub (os agentes abrem PR com a conta do fundador,
que não pode aprovar o próprio PR). Em áreas críticas, a aprovação é o rótulo `aprovado-bernardo`, conferido pelo
check `aprovacao` (`docs/politica-de-merge.md`).

## Checks obrigatórios

Jobs do `CI` (`.github/workflows/ci.yml`): agentes, workflows, segredos, front, seguranca, testes_python,
referencia_para, checagens, e2e, carga, mcp. Mais `aprovacao` (`.github/workflows/aprovacao.yml`).

Situação em 17/11/2026: gravados os 10 primeiros; `front` e `aprovacao` faltam ser marcados pelo fundador.

## Passos de clique (fundador)

1. Abra <https://github.com/bernardoemmel/Raiz/settings/branches> e clique em **Edit** na regra `main`.
2. Em "Require status checks to pass before merging", na caixa de busca digite `front` e clique no resultado
   `front` (GitHub Actions). Ele aparece na lista abaixo da caixa.
3. Na mesma caixa digite `aprovacao` e clique no resultado.
4. Desça até o fim da página e clique em **Save changes** (sem isso a escolha some).

Se `aprovacao` não aparecer na busca: ele só aparece depois de rodar uma vez num PR; abra a lista de PRs e confira
se algum PR novo já mostra o check "aprovacao".

`strict` desligado: o PR não precisa estar em dia com a main para mergear (evita rebase em fila entre chats).
`testes_python` é o agregador das 4 partes paralelas (`testes_python (parte k de 4)`); as partes não precisam
entrar na lista, porque o agregador só aprova com todas verdes e completas.
Quem renomear ou remover um job do CI precisa atualizar esta lista na proteção, senão os PRs ficam presos esperando
um check que não existe mais.

## Configuração pela API (precisa de token de administrador)

```bash
gh api -X PUT repos/bernardoemmel/raiz/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": false, "checks": [
    {"context": "agentes"}, {"context": "workflows"}, {"context": "segredos"}, {"context": "front"},
    {"context": "seguranca"}, {"context": "testes_python"}, {"context": "referencia_para"},
    {"context": "checagens"}, {"context": "e2e"}, {"context": "carga"}, {"context": "mcp"},
    {"context": "aprovacao"}]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 0},
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

## Automações e a main

Levantamento de 17/11/2026: a única automação que gravava direto na main era o painel do `motor/README.md`
(`motor/painel.py`, chamado por `processar-estados` e `publicar-dados`), com 43 commits
"Painel do motor atualizado pelo GitHub Actions" em 5 dias. Ele passou a não gravar na main; a situação dos estados
continua no `estados.json` do Release `dados`. Os demais workflows com `contents: write` usam isso para Releases e
tags de trava (`trava-*`), que a proteção da main não afeta. Nenhum workflow faz merge automático de PR.
O `claude.yml` (tarefas por issue) já trabalha em branch próprio e abre PR. O workflow `aprovacao.yml` só põe e
tira rótulos; não grava arquivos nem mergeia.
