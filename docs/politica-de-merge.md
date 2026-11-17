# Política de merge

Objetivo: nenhum agente mergeia sozinho algo que possa quebrar o processamento, o site ou os dados publicados,
sem travar o trabalho do dia a dia.

## As duas faixas

| Faixa | O que entra | Quem mergeia |
|---|---|---|
| **Livre** | documentação comum, testes, telas e componentes do front, API, correções pontuais que não tocam a lista abaixo | o próprio agente, com todos os checks obrigatórios verdes |
| **Crítica** | qualquer arquivo da lista abaixo | o agente, **só depois** do fundador pôr o rótulo `aprovado-bernardo` no PR |

Áreas críticas (lista exata em `raiz/operacao/aprovacao_merge.py`, constante `CRITICOS`):

- `motor/` inteiro (motor de dados e fila de processamento);
- `.github/` inteiro (todos os workflows, inclusive CI, processamento, publicação do site e esta trava);
- código que muda dados publicados: `raiz/funil/`, `raiz/comprometida/`, `raiz/ambiental/`, `raiz/coleta/`,
  `raiz/catalogo_publico.py`, `raiz/potencial_publico.py`, `raiz/lotes_publicos.py`, `raiz/lote_publicado.py`,
  `raiz/metadados.py`, `raiz/metadados_lote.py`, `raiz/pacotes_seguros.py`, `raiz/privacidade.py`;
- scripts de publicação e de dados privados: `scripts/publicar_*`, `scripts/migrar_*`,
  `scripts/aliviar_dados_privados.py`, `scripts/atualizar_fila_privada.py`, `scripts/reservar_lote.py`,
  `scripts/verificar_release_dados.py`;
- publicação do site: `front/scripts/construir-site.sh`, `front/scripts/baixar-*`,
  `front/scripts/configurar-publicacao.mjs`, `front/scripts/servidor-publicacao.mjs`, `front/scripts/geo.py`;
- `migracoes/` (banco), `docs/colunas.md` (contrato de dados);
- as próprias regras: `CLAUDE.md`, `AGENTS.md`, `docs/politica-de-merge.md`, `docs/protecao-main.md`,
  `raiz/operacao/aprovacao_merge.py`.

Arquivo renomeado conta pelo caminho antigo também (tirar algo de `motor/` é mexer no motor).

## Como funciona o check `aprovacao`

Workflow `.github/workflows/aprovacao.yml` ("Aprovação de áreas críticas"), obrigatório na proteção da main.

1. Todo PR para a main roda o check. Ele lê pela API a lista de arquivos do PR.
2. Sem arquivo crítico: passa na hora.
3. Com arquivo crítico: falha, mostra no resumo quais arquivos são críticos e põe o rótulo
   `aguardando-bernardo` no PR.
4. O fundador abre o PR, clica em **Labels** (coluna da direita) e marca `aprovado-bernardo`. O check roda de novo
   sozinho, passa e tira `aguardando-bernardo`. O agente então mergeia como sempre.
5. Qualquer push novo no PR tira `aprovado-bernardo` e o check volta a falhar: a aprovação vale só para o que o
   fundador viu.

Lista do que espera o fundador:
<https://github.com/bernardoemmel/Raiz/pulls?q=is%3Aopen+is%3Apr+label%3Aaguardando-bernardo>

Simulação local, sem rede: `python3 -m raiz.operacao.aprovacao_merge --arquivos motor/x.py docs/y.md`.

### Por que rótulo e não "Approve" do GitHub

Os agentes (Claude Code e Codex) abrem os PRs com a conta `bernardoemmel`, a mesma do fundador, que é o único
colaborador do repositório. O GitHub não deixa o autor aprovar o próprio PR, então "Require review from Code Owners"
travaria tudo para sempre. O rótulo resolve com um clique, no celular também.

### Segurança da trava

- `pull_request_target` + checkout do commit da main: o check sempre roda o código da main. Um PR que mexe na
  trava não consegue afrouxá-la para si mesmo (e mexer nela já é área crítica). Nenhum código do PR é executado.
- Vale o último evento que pôs o rótulo: precisa ser de um aprovador (`bernardoemmel`, mais quem estiver na
  variável do repositório `RAIZ_APROVADORES`, separada por vírgula) e não pode ter sido feito por um app
  (`performed_via_github_app`, que o GitHub registra quando o agente age por um app instalado).
- Limite conhecido: um agente com a conta do fundador por um caminho que o GitHub não marca como app conseguiria pôr
  o rótulo. Por isso a regra também está no `CLAUDE.md` e no `AGENTS.md`: **agente nunca põe nem tira
  `aprovado-bernardo`**. Trava mais forte, se um dia for preciso: uma segunda conta humana do fundador como
  aprovadora em `RAIZ_APROVADORES` e os agentes sem acesso a ela.

## Checks obrigatórios para merge

Os 10 jobs do CI (`agentes`, `workflows`, `segredos`, `seguranca`, `testes_python`, `referencia_para`, `checagens`,
`e2e`, `carga`, `mcp`) **mais** `front` (build, testes e desempenho do site) e `aprovacao`. Configuração e passos
de clique em `docs/protecao-main.md`.

## O que não muda

- Os agentes continuam abrindo PR em branch própria e mergeando eles mesmos.
- PR da faixa livre: nada novo, só esperar os checks.
- Nunca desligar, pular ou marcar como opcional um check para conseguir mergear; nunca força-push na main.
- Dependabot: atualização de ação em `.github/` é crítica e pede o rótulo; atualização de pacote fora da lista é livre.
