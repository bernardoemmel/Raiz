# Dados do motor publicados (Release `dados`)

Os dados grandes nunca entram no git. O motor roda sozinho no GitHub Actions e publica direto no Release `dados`
(https://github.com/bernardoemmel/raiz/releases/tag/dados), de onde o front baixa. Ninguém baixa nem sobe nada à mão.
Painel e detalhes: [`motor/README.md`](../motor/README.md).

## Caminho automático

1. O workflow `.github/workflows/processar-estados.yml` roda toda segunda-feira e quando alguém dispara (Actions,
   "Processar estados (motor)"). O plano (`motor/rodar_estado.py --planejar`) lê o `estados.json` publicado e escolhe,
   na ordem do país, os estados que não começaram, os incompletos, os de antes do executor, os que têm tarefa com
   código mudado e os completos que não rodam há 6 dias, em duas filas (estado novo primeiro; manutenção só com o que
   sobra, até 4). Estado com mais de 120 municípios roda em fatias, em jobs separados. Até 15 jobs ao mesmo tempo,
   somando todas as rodadas.
2. Cada estado roda num job (`motor/rodar_estado.py <UF> --executor`) pelo executor do produto (`raiz executor`): ele
   lê do Release o que já está publicado do estado (pacotes e marcas de retomada), roda o motor e as tarefas do
   produto só onde falta ou mudou, e publica: `raiz_<UF>.tar.gz` (os CSV, com `<UF>/_versoes.json`: tarefa, versão,
   data e sha256 de cada arquivo), `raiz_geo_<UF>.tar.gz` (os polígonos), `raiz_camadas_<UF>.tar.gz` (camadas dentro
   do imóvel), `raiz_controle_<UF>.json` (marcas por município e andamento) e, por último, o `estados.json`, relido e
   regravado dentro de uma trava (tag `trava-publicar-dados`) para que dois estados que terminam juntos não apaguem um
   ao outro. Nada sobe com coluna de nome, CPF, CNPJ ou contato. Depois, o painel em `motor/README.md` é atualizado.
3. Se o job parou pelo prazo de 5h30, ele dispara o workflow de novo só para aquele estado; se terminou, passa a vez ao
   próximo estado da fila.
4. O front baixa sozinho: `npm run dev` roda antes `front/scripts/baixar-dados.mjs`, que lê o `estados.json` publicado
   e baixa só os estados novos ou mudados para `dados/estados/<UF>/` (fora do git). `npm run dados -- --geo` também
   baixa os polígonos. `RAIZ_SEM_DOWNLOAD=1` pula o download. O back-end espelha o Release com
   `raiz executor sincronizar`.
5. O plugin do Vite (`front/compartilhado/vite-dados.ts` e `pasta-dados.ts`) lê `dados/estados/` sozinho quando
   existe (ou a pasta de `RAIZ_DADOS`); sem ela, a amostra. O mapa do Brasil diz, por estado, o que o `estados.json`
   baixado diz (completo, incompleto com a contagem, ainda não processado), sem recontar.
6. O site público (https://bernardoemmel.github.io/Raiz/) é refeito todo dia pelo workflow `publicar-site.yml`, que
   baixa este Release no build (ver `front/README.md`, "Site público").

## Caminho antigo (motor rodado no computador)

`python motor/publicar_dados.py motor/saida dados-entrada [UF ...]` monta os pacotes em `dados-entrada/` (pacote acima
de 90 MB vai em partes `.part00`, `.part01`...). Commit de `dados-entrada/` num branch de trabalho
(`git add -f dados-entrada`) e push: o workflow `publicar-dados.yml` junta as partes, sobe os pacotes e mescla no
`estados.json` publicado só as entradas dos estados que têm pacote (`publicar_dados.py --indice`). No commit seguinte,
`git rm -r dados-entrada`. Com o `gh` autenticado dá para pular o git: `--subir`. Estado do executor (com
`controle` no `estados.json`) não é publicado por aqui, para não perder as tabelas do produto: `raiz executor publicar`.

## `estados.json`

Uma entrada por estado:

| Campo | O que é |
|---|---|
| `municipios` | municípios com `imoveis_<cod>.csv` |
| `sem_imoveis` | municípios sem nenhum imóvel IRU no CAR (na marca do executor, `vazio`; no motor sozinho, `sem_imoveis_<UF>.csv`); contam como prontos |
| `total_ibge` | municípios do estado (IBGE) |
| `funil_completo` | funil rodado em todos os municípios |
| `completo` | funil, filtros, MapBiomas, direto, TMF e causas, APP pela escadinha e, no estado do executor, FLAG, caminho da terra, ficha e desenvolvedor em todos os municípios com imóvel (extras do Earth Engine e certidões não entram) |
| `faltam` | quantos municípios faltam em cada etapa (`imoveis`, `filtros`, `mapbiomas`, `direto`, `extras_direto`, `app`, `flag`, `terra`, `ficha`, `desenvolvedor`) |
| `tabelas` | quantos municípios têm cada tabela (`imoveis`, `direto`, `filtros`, `extras`, `extras_direto`, `mapbiomas`, `certidoes`, `app`) |
| `versao`, `tamanho`, `url`, `atualizado_em` | pacote dos CSV: sha256 do conteúdo, bytes, endereço e quando o conteúdo mudou |
| `geo` | o mesmo para o pacote dos polígonos |
| `versoes`, `motor_versao`, `situacao`, `controle` | do executor: versão de cada tarefa (hash do código e da regra), versão do motor, andamento (`pronto`, `parado_no_prazo`, `com_erro`) e endereço das marcas de retomada |
| `motor` | quem rodou: `commit` (sha do commit da rodada), `versao`, `etapas` (versão por tarefa), `legado` (tarefas adotadas de antes do executor, como estavam), `rodada` (endereço do job, início, fim, continuação, se parou pelo prazo e quantos municípios avançou) e, em estado grande, `fatias` (por fatia: `rodada`, `completo`, `faltam`, `erros`, `municipios`) |
| `erros` | erros da última rodada (etapa, município, mensagem; sem CPF nem CNPJ), até 50 |

O aprendizado compara previsões entre versões do motor pelo `motor.etapas[tabela].versao` (muda só quando o código
daquela tabela muda, sem contar comentários) e chega ao código exato pelo `commit`.

São dados de fontes públicas (CAR, MapBiomas, INPE, FUNAI, INCRA, ICMBio), sem nome, CPF ou CNPJ.

## Release `vigilancia`

A vigilância diária (`raiz/vigilancia/`, workflow `.github/workflows/vigilancia.yml`) lê os polígonos daqui e publica
no Release `vigilancia` (https://github.com/bernardoemmel/raiz/releases/tag/vigilancia): alertas de imóvel por mês
(`alertas_AAAA-MM.parquet`), espelho dos embargos do Ibama, situação das fontes e rodadas, abertos; projetos,
eventos de perda, marcações e rascunhos de relatório num pacote cifrado (`privado.tar.gz.cifrado`, chave
`RAIZ_VIGILANCIA_CHAVE`). `vigilancia.json` (manifesto) sobe por último. Detalhes em `raiz/vigilancia/README.md`.

## Migração verificável do histórico

`scripts/migrar_dados_privados.py` inventaria todos os Releases **publicados** e seus assets, inclusive arquivos
históricos fora do manifesto atual. Drafts são excluídos da origem para não copiar o próprio backup de novo. A fase
`inventariar` baixa os originais para uma pasta fora do git, confere tamanho e SHA256 informado pelo GitHub e registra
caminho, tamanho, SHA256 e cabeçalho/esquema de cada membro de pacote. Não grava valores de linhas nem extrai tar no
filesystem; links, dispositivos e caminhos que escapam do pacote são recusados.

O snapshot completo é privado. Arquivos do motor, certidões, caminho da terra, regularização, estimativas de
restauração/crédito, ficha, MapBiomas, séries e camadas internas não viram públicos pela simples remoção de nomes ou
CPF. A projeção aberta é separada, definida em `raiz/executor/publicacao_aberta.py`: CSV básico com CAR, município,
UF e situação básica; geometria com CAR; resumos permitidos com supressão de grupos pequenos. Arquivos desconhecidos
ficam privados até revisão. Nunca substituir o snapshot pela projeção reduzida.

As fases são separadas e repetíveis, sem sobrescrever backups existentes:

```bash
uv run python scripts/migrar_dados_privados.py inventariar --origem bernardoemmel/Raiz --diretorio /tmp/raiz-migracao
uv run python scripts/migrar_dados_privados.py copiar --destino bernardoemmel/Raiz --tag dados-privados --diretorio /tmp/raiz-migracao
uv run python scripts/migrar_dados_privados.py verificar --destino bernardoemmel/Raiz --tag dados-privados --diretorio /tmp/raiz-migracao
uv run python scripts/migrar_dados_privados.py remover --destino bernardoemmel/Raiz --tag dados-privados --diretorio /tmp/raiz-migracao
```

`copiar` e `remover` são **dry-run** sem `--executar`. O repositório e o Release de destino devem ser criados
explicitamente. O destino precisa ser um repositório privado **ou um Release draft**, conferido novamente antes de
cada operação. O draft nunca deve ser publicado. Um Release draft é encontrado pela listagem autenticada e pelo ID;
a rota de Release por tag pode responder 404 mesmo para uma credencial autorizada.

Os backups recebem nomes imutáveis `historico-<release_id>-<asset_id>-<nome>`. `copiar --executar` baixa de novo cada
backup, confere o SHA256 e exige HTTP 404 no endereço de download sem cabeçalho de autenticação. Essa verificação
deve rodar no GitHub Actions ou em ambiente sem proxy que injete credenciais: o proxy do ambiente de desenvolvimento
não comprova anonimato. `verificar` repete as provas e grava `backup-verificado.json`.

A remoção gera primeiro `plano-remocao.json` para revisão. `remover --executar` reconfere **todos** os backups antes do
primeiro DELETE e recusa alterações de fingerprint da origem, assets novos ou mudança na lista de Releases
publicados. Cada DELETE usa o ID original e nova leitura de metadados; o progresso fica em
`remocao-progresso.json`. Se o original já tiver sido removido, ele não é apagado outra vez. A publicação da projeção
aberta acontece separadamente, após a cópia integral validada. Preserve também `inventario.json` e
`backup-verificado.json` no armazenamento privado para reconstruir o histórico.

Inventário local inicial em 12/11/2026: um Release publicado (`dados`, ID 442821475), 40 assets e cerca de 1,21 GB.
Foram encontrados 3.249 membros de camadas pagas, 365 CSV completos do motor, 365 arquivos de geometria básica,
9 resumos e 23 arquivos de controle ou formatos sem allowlist. Esses números descrevem a leitura daquele instante;
novas rodadas podem trocar assets. O inventário e os hashes atualizados ficam fora do git, em `/tmp/raiz-migracao/`.
