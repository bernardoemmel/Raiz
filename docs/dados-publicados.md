# Dados do motor publicados (Release `dados`)

Os dados grandes nunca entram no git. O motor roda sozinho no GitHub Actions e publica direto no Release `dados`
(https://github.com/bernardoemmel/raiz/releases/tag/dados), de onde o front baixa. Ninguém baixa nem sobe nada à mão.
Painel e detalhes: [`motor/README.md`](../motor/README.md).

## Caminho automático

1. O workflow `.github/workflows/processar-estados.yml` roda toda segunda-feira e quando alguém dispara (Actions,
   "Processar estados (motor)"). O plano (`motor/rodar_estado.py --planejar`) lê o `estados.json` publicado e escolhe,
   na ordem do país, os estados que não começaram, os incompletos e os que têm tabela feita com código antigo. Ficam 4
   estados rodando ao mesmo tempo, somando todas as rodadas.
2. Cada estado roda num job: baixa do Release o que já está publicado dele para `motor/saida/<UF>/` (retoma de onde
   parou), roda as etapas na ordem (`motor/rodar_estado.py <UF>`) e grava `saida/<UF>/rodada.json` com o que fez.
3. `python motor/publicar_dados.py motor/saida dados-entrada <UF> --subir` monta `raiz_<UF>.tar.gz` (os CSV) e
   `raiz_geo_<UF>.tar.gz` (os polígonos), confere que nenhum CSV tem coluna de nome, CPF, CNPJ ou contato, sobe os
   pacotes que mudaram e, por último, relê o `estados.json` publicado, troca só a entrada deste estado e regrava, dentro
   de uma trava (tag `trava-publicar-dados`), para que dois estados que terminam juntos não apaguem um ao outro. Depois
   atualiza o painel em `motor/README.md`.
4. Se o job parou pelo prazo de 5h30, ele dispara o workflow de novo só para aquele estado; se terminou, passa a vez ao
   próximo estado da fila.
5. O front baixa sozinho: `npm run dev` roda antes `front/scripts/baixar-dados.mjs`, que lê o `estados.json` publicado
   e baixa só os estados novos ou mudados para `dados/estados/<UF>/` (fora do git). `npm run dados -- --geo` também
   baixa os polígonos. `RAIZ_SEM_DOWNLOAD=1` pula o download.

## Caminho antigo (motor rodado no computador)

`python motor/publicar_dados.py motor/saida dados-entrada [UF ...]` monta os pacotes em `dados-entrada/` (pacote acima
de 90 MB vai em partes `.part00`, `.part01`...). Commit de `dados-entrada/` num branch de trabalho
(`git add -f dados-entrada`) e push: o workflow `publicar-dados.yml` junta as partes, sobe os pacotes e mescla no
`estados.json` publicado só as entradas dos estados que têm pacote (`publicar_dados.py --indice`). No commit seguinte,
`git rm -r dados-entrada`. Com o `gh` autenticado dá para pular o git: `--subir`.

## `estados.json`

Uma entrada por estado:

| Campo | O que é |
|---|---|
| `municipios` | municípios com `imoveis_<cod>.csv` |
| `sem_imoveis` | municípios sem nenhum imóvel IRU no CAR (lista em `sem_imoveis_<UF>.csv`); contam como prontos |
| `total_ibge` | municípios do estado (IBGE) |
| `funil_completo` | funil rodado em todos os municípios |
| `completo` | funil, filtros, MapBiomas, direto, TMF e causas e APP pela escadinha em todos os municípios (extras do Earth Engine e certidões não entram) |
| `faltam` | quantos municípios faltam em cada etapa (`imoveis`, `filtros`, `mapbiomas`, `direto`, `extras_direto`, `app`) |
| `tabelas` | quantos municípios têm cada tabela (`imoveis`, `direto`, `filtros`, `extras`, `extras_direto`, `mapbiomas`, `certidoes`, `app`) |
| `versao`, `tamanho`, `url`, `atualizado_em` | pacote dos CSV: sha256 do conteúdo, bytes, endereço e quando o conteúdo mudou |
| `geo` | o mesmo para o pacote dos polígonos |
| `motor` | versão do motor que gerou os dados: `commit` (sha do commit que rodou por último), `versao` (hash do código do motor), `etapas` (por tabela: `versao` = hash do código de que ela depende, `commit` e `desde`), `legado` (tabelas publicadas antes da automação, adotadas como estavam) e `rodada` (endereço do job, início, fim, continuação, se parou pelo prazo e quantos arquivos novos fez) |
| `erros` | erros da última rodada (etapa, município, mensagem; sem CPF nem CNPJ), até 50 |

O aprendizado compara previsões entre versões do motor pelo `motor.etapas[tabela].versao` (muda só quando o código
daquela tabela muda, sem contar comentários) e chega ao código exato pelo `commit`.

São dados de fontes públicas (CAR, MapBiomas, INPE, FUNAI, INCRA, ICMBio), sem nome, CPF ou CNPJ.
