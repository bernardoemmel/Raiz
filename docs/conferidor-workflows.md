# Conferidor de etapas: nenhuma falha crítica passa despercebida

Workflow `.github/workflows/conferir-workflows.yml` (código em `raiz/operacao/conferidor_workflows.py`).
Ele roda sozinho toda vez que um destes workflows termina na `main`:

| Workflow | Arquivo |
|---|---|
| Processar estados (motor) | `processar-estados.yml` |
| Terra comprometida (coleta diária dos limites públicos) | `coletar-comprometida.yml` |
| Vigilância diária | `vigilancia.yml` |
| Calendário diário da Raíz | `calendario.yml` |
| Publicar o site | `publicar-site.yml` |

## O que ele faz

- **Falhou** (`failure`, `timed_out` ou `startup_failure`): abre uma issue com o rótulo `falha-workflow`,
  o link da execução e os jobs e passos que caíram. Se a issue daquele workflow já está aberta, o texto é
  atualizado com a última falha e a contagem de falhas seguidas. Comentário novo sai no máximo uma vez a cada
  24 horas, para não lotar a caixa de e-mail.
- **Passou**: comenta "voltou a passar" e fecha a issue.
- **Cancelado ou pulado**: nada muda (cancelamento por concorrência não é falha).
- **Registro em arquivo**: cada evento vira uma linha JSON em `registro/falhas-workflows.jsonl` na branch
  `registro-workflows` (só de registro; a `main` protegida não recebe commits do conferidor). Guarda as
  últimas 5.000 linhas.

Sempre existe no máximo **uma issue aberta por workflow**. Para ver o que está quebrado agora:
[issues abertas com `falha-workflow`](https://github.com/bernardoemmel/raiz/issues?q=is%3Aissue+is%3Aopen+label%3Afalha-workflow).

## E-mail

Issue aberta pelo GitHub Actions já gera e-mail para quem acompanha o repositório (o dono acompanha por
padrão). Para garantir: GitHub > Settings > Notifications > "Watching" ligado por e-mail, e o repositório em
"Watch > All activity" ou "Custom > Issues".

## Para conferir mais um workflow

Acrescente o `name:` exato dele na lista `workflows:` do `conferir-workflows.yml` e o arquivo no teste
`testes/test_conferidor_workflows.py`. O conferidor não muda nada nos workflows conferidos.

O registro só tem nomes de workflow, job e passo, números de execução e links. Nada pessoal.
