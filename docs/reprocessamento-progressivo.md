# Reprocessamento progressivo, estado por estado

O Brasil inteiro precisa ser refeito com as regras novas (classificação da terra, terra já comprometida e
sobreposição com projetos de carbono, vegetação e relevo, filtros estaduais) sem tirar o site do ar e sem impedir
demonstrações. A regra é simples:

> **O site mostra os dados que estão no ar até o estado inteiro ser refeito e conferido. Aí troca o estado de uma vez.**

Nenhum pacote público de um estado é apagado ou trocado enquanto o reprocessamento daquele estado não fechou. A lógica
científica do funil não muda: só muda **quando** o resultado vai para o site.

## O que conta como "regras novas"

- A geração vigente fica em [`raiz/executor/regras_vigentes.json`](../raiz/executor/regras_vigentes.json)
  (hoje `2026-11-17`). Ao mudar uma regra de classificação, troque a data nesse arquivo no mesmo PR.
- Um estado está **atualizado** quando **todos** os municípios dele (lista do IBGE) têm **todas** as tarefas do
  executor (`raiz/executor/tarefas.py`: funil, filtros, MapBiomas, direto, TMF, FLAG, terra, título, ficha, rebanho,
  terra já comprometida, ambiental, desenvolvedor) rodadas na versão do código que publica, sem erro, e o índice do
  estado está completo. Município sem imóvel conta quando o funil rodou na versão atual e ficou vazio.
- A versão de cada tarefa é o hash do código dela (e da regra, quando há uma). Qualquer PR que mexa numa regra muda a
  versão e põe o estado de novo em reprocessamento, sem ninguém precisar lembrar.
- A sobreposição com projetos de carbono entrou na assinatura do funil: quando a coleta de projetos (Release
  `insumos`, `projetos_carbono.tar.gz`) muda, só os municípios que um projeto toca refazem o funil. Antes, a frente
  `ja_tem_projeto` não era refeita nos municípios já processados.

## Como funciona

```
fila (Processar estados) ──► job do estado ──► arquivo privado (sempre, município a município)
                                                    │
                                                    ▼
                                 raiz/executor/reprocessamento.py decide
                                   │                         │
                    estado fechou e conferiu       ainda refazendo, com regras
                    (todos os municípios em dia)   diferentes das que estão no ar
                                   │                         │
                                   ▼                         ▼
                 troca o pacote público do estado   não mexe no pacote público;
                 de uma vez + "atualizado"          grava só o andamento (x de y)
                                   │                         │
                                   └──────► reprocessamento.json (Release aberto) ◄──┘
                                                    │
                                                    ▼
                                     site: selo por estado no painel "Sobre os dados"
```

1. **Privado primeiro.** O executor continua gravando tudo no arquivo privado, como antes. Ao publicar o estado, o
   publicador avalia as marcas de cada município (`avaliar`) e guarda o resultado no índice privado, no campo
   `reprocessamento` (`situacao`, `prontos`, `total`, `motivo`, `versoes`).
2. **Decisão antes do aberto.** `ArmazemRelease._publicar_aberto` chama `decidir` antes de tocar no Release aberto:
   - estado **fechou** (todos em dia, completo) e **não tem menos municípios** do que o que está no ar: troca o pacote
     público inteiro e marca `atualizado` com a geração das regras;
   - estado **sem nada no ar**: publica aos poucos, como antes (não há o que apagar);
   - estado crescendo com **as mesmas versões** que já estão no ar (o funil de um estado novo avançando): publica aos
     poucos, como antes (não há mistura de regras);
   - qualquer outro caso (refazendo com regras diferentes): **segura**. O pacote do estado no ar fica como está; só a
     linha do estado no `reprocessamento.json` muda.
3. **Sem retrabalho.** A projeção atrasada (`defasados_no_aberto`, job `projecao-aberta`) pula os estados segurados,
   então não baixa estado inteiro a cada hora à toa.
4. **Fila sem sobrecarga.** Durante a conclusão dos 27 funis, a manutenção continua suspensa, mas a fila abre até
   `RAIZ_VAGAS_REPROCESSAMENTO` (padrão **2**) vagas para refazer estados que já fecharam o funil. Essas vagas usam o
   código atual da main (não a versão fixada da prioridade) e nunca tiram vaga dos funis: só usam o que sobra das 15.
   Duas por vez porque cada job baixa o estado inteiro e a cota de downloads do GitHub é do repositório todo. A
   continuação de um job que parou pelo prazo de 5h30 segue marcada como reprocessamento (`RAIZ_REPROCESSAR`).
   Quando os 27 funis fecham, o reprocessamento vira a manutenção normal (até 4 por vez).

## Como iniciar

Nada a fazer no dia a dia: a rodada de hora em hora (`Processar estados`) pega sozinha os estados com o funil pronto
que estão com regras antigas, dois por vez, na ordem da Amazônia Legal primeiro.

Para pedir um estado na frente: **Actions → Processar estados (motor) → Run workflow**, campo `ufs` com o estado
(ex.: `AC`). Com o funil do estado pronto, o pedido vira reprocessamento (dentro do limite de vagas). Para mudar o
limite, crie a variável de repositório ou o `env` `RAIZ_VAGAS_REPROCESSAMENTO` (0 desliga).

Para começar uma geração nova de regras: mude a regra no código (o hash da tarefa muda sozinho) e troque a data em
`raiz/executor/regras_vigentes.json`. Os estados que estavam "atualizados" passam a aparecer como "regras antigas"
no site até fecharem de novo.

## Como acompanhar

- **Site**, painel *Sobre os dados → Dados disponíveis no mapa*: cada estado tem um selo **Regras novas**,
  **Reprocessando x/y** ou **Regras antigas**, e uma frase com quantos estados já estão com as regras novas. Na página
  do estado, uma frase explica o que está no ar.
- **Actions**, job `planejar` de cada rodada: a tabela *Plano desta rodada* mostra as unidades em `reprocessamento`, e
  o passo *Situação do reprocessamento estado por estado* lista todos os estados (no site, avaliação, municípios em
  dia, motivo).
- **Linha de comando** (só leitura, com o token do arquivo privado no ambiente):
  `uv run python -m raiz.executor.reprocessamento`.
- **Arquivo público**: `reprocessamento.json` no Release aberto `dados`. Contrato fechado: por estado, só
  `situacao` (`atualizado`, `reprocessando`, `antigo`), `geracao`, `prontos`, `total`, `motivo`, `atualizado_em` e
  `desde`. Nada por imóvel. O publicador (`validar_asset_publico`) e o site (`front/compartilhado/dados/reprocessamento.ts`)
  recusam qualquer campo a mais.

Motivos possíveis de um estado ainda não ter trocado: `falta_municipio` (município sem marca),
`tarefa_com_erro`, `tarefa_desatualizada`, `estado_incompleto` (falta tabela no índice),
`validacao_menos_municipios` (o novo teria menos municípios que o que está no ar) e `sem_avaliacao`.

## O que acontece quando um estado fecha

1. O último job do estado publica o privado; a avaliação dá `atualizado`.
2. `decidir` confere que o novo conjunto não tem menos municípios do que o que está no ar.
3. A projeção aberta do estado é montada e validada pela lista positiva (`publicacao_aberta.py`) e sobe de uma vez
   (`raiz_<UF>.tar.gz`, `raiz_geo_<UF>.tar.gz`, entrada no `estados.json`), dentro da trava do estado.
4. A linha do estado no `reprocessamento.json` vira `atualizado`, com a data.
5. Na próxima publicação do site (a cada 3 horas, ou pelo botão *Publicar o site*), o estado aparece com o selo
   **Regras novas**. Os outros estados continuam como estavam.

Se o job falhar no meio, nada muda no site: o estado continua com os dados antigos e o reprocessamento retoma das
marcas no arquivo privado.

## Demonstrações

O site pode ser demonstrado a qualquer momento: todos os estados continuam com os dados que estavam no ar, e o selo diz
de quais regras eles são. Nenhum estado fica vazio por estar sendo refeito.

## Armazenamento

A decisão (`raiz/executor/reprocessamento.py`) não faz rede nem conhece o armazenamento. O armazém
(`raiz/executor/armazem.py`) só precisa de `manifesto()`, `status_reprocessamento()`,
`gravar_status_reprocessamento()` e das marcas no espelho local. A troca do Release por um balde privado
(docs da Frente 3, `ArmazemBalde`) herda esses métodos sem mudar o fluxo.

## Compatibilidade

- Jobs que ainda rodam código antigo (a versão fixada da prioridade dos funis) não conhecem o `reprocessamento.json`
  e não o tocam; ele é um arquivo separado justamente para não mudar o `estados.json` que esses jobs validam.
- Esses jobs só rodam estados com o funil incompleto; os estados em reprocessamento rodam no código novo.
- O script de corte histórico (`scripts/publicar_projecao_aberta.py`) usa `regras=False`: é uma cópia verificável do
  que já estava publicado, não um reprocessamento.
