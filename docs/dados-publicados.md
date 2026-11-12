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

## Fichas Croissant 1.1 e schema.org

O publicador do executor gera `croissant_<UF>.json` com o SHA-256 do `raiz_<UF>.tar.gz` efetivamente publicado,
um `FileObject` por CSV e `FileSet` por tabela. Cada CSV preserva seu próprio esquema, inclusive quando um município
tem colunas mais novas que outro. O baker 0.8.3 infere os tipos percorrendo o CSV; o mlcroissant 1.1.1 valida a ficha
sem baixar o pacote. Um teste também carrega registros reais de um tar local pelo mlcroissant.

Pacotes de geometria, camadas e arquivos de controle recebem `croissant_<nome-do-arquivo>.json`; esses arquivos
não tabulares são descritos como distribuições, sem prometer um leitor de registros para formatos não suportados.
`croissant.json` reúne as fichas publicadas. `croissant_estados.json` descreve os bytes do índice, e seu hash
fica apenas no catálogo para evitar autorreferência. As próprias fichas não geram novas fichas recursivamente.

Os pacotes e suas fichas são preparados antes do upload e publicados na mesma trava de UF. O catálogo é gerado
na trava global, com `estados.json` por último. O índice passa a trazer `sha256` (pacote comprimido),
`proveniencia_sha256` (versões/datas dos arquivos), `croissant` e `fichas`; os consumidores antigos podem ignorar
essas colunas adicionais. Os arquivos que já existiam serão atualizados pela publicação retroativa da retomada.

A licença dos dados derivados da Raíz ainda não foi definida. As fichas registram essa condição e remetem aos
créditos e termos das fontes em `NOTICE.md`; não atribuem automaticamente a licença do código ou a do baker aos dados.

## Quantis, versão do modelo e cartão

Cada UF tem `quantis_<UF>.parquet` com `reference_date`, `location`, `target`, `output_type`, `output_type_id`,
`value` e as colunas de proveniência `model_id`, `model_version`, `source_model_version`, `task_version`,
`quantile_method` e `source_file`. Os quantis são números `0.1`, `0.5` e `0.9`; cada alvo informa sua unidade em
`tasks_<UF>.json`. `model_id` segue `raiz-<tarefa>_<hash-da-versao>`.

`hub_<UF>.tar.gz` contém um hub nativo: Parquet com as seis colunas padrão dentro de `model-output/<model_id>/`,
metadados YAML por modelo e `hub-config/` com tasks/admin v6 e o schema de metadados. `modelos_<UF>.json` registra
versões, arquivos de entrada e SHA-256; `diagnosticos_quantis_<UF>.json` aponta dados que não puderam ser exportados,
sem reproduzir valores pessoais. Os arquivos globais `tasks.json`, `modelos.json` e `model-metadata-schema.json`
unem as configurações e identificações estaduais.

A data é o dia UTC da execução registrada na origem, não a data de publicação nem um corte histórico inferido
para todas as fontes. Sem versão ou data confiável, a linha não recebe uma versão inventada. Os P10/P50/P90 do
desenvolvedor são preservados; o P50 legado é o cenário central, que pode diferir da mediana da simulação. FLAG
tem mínimo, central e máximo: o exportador define uma distribuição triangular provisória, versionada e sem
calibração empírica, da qual calcula os quantis. O [cartão do modelo](modelo/cartao.md), também publicado como
`cartao_modelo.md`, detalha métodos, premissas, uso, avaliação e limites.

Os assets da UF são retratos mutáveis. O catálogo de versões conserva metadados, mas não é um histórico completo
de valores previstos. O módulo de aprendizado conserva previsões para comparação longitudinal no seu próprio
armazenamento; para reproduzir um retrato público, guardar arquivos, hashes e atestação correspondentes.

## Cronogramas CAD Trust

`cadt_<UF>.json` descreve o cenário estadual ProFloresta+; `cadt_lotes.json` reúne os estados disponíveis. O objeto
`projeto` usa campos e listas do CAD Trust; proveniência, premissas e diagnósticos ficam no envelope da Raíz.
Cada `estimation` informa `creditingPeriodStart`, `creditingPeriodEnd` e `unitCount` anual em `tCO2e`. Os incrementos
derivam da curva de captura e dos marcos acumulados P50; o arredondamento conserva o total inteiro.

No Actions, `RAIZ_CADT_INICIO_CENARIO` usa **2027-01-01** por padrão e pode ser definida nas variáveis do repositório.
É uma âncora hipotética para comparar cronogramas. `Listed` representa a listagem neste catálogo de cenários;
VM0047 é referência metodológica. O arquivo não afirma registro no CAD Trust/Verra, certificação ou emissão de
créditos. Estado sem lote elegível ou cronograma válido recebe diagnóstico.

## Atestação e atualização dos arquivos existentes

Depois de cada upload concluído, o publicador registra `sha256  nome` em `$RUNNER_TEMP/atestar.txt`. O passo
`actions/attest-build-provenance@v2` usa esse arquivo, OIDC e permissões `id-token: write`/`attestations: write` para
atestar os bytes. Se um nome mudar várias vezes no mesmo job, a assinatura cobre o último upload desse job.
O SHA identifica conteúdo; a atestação vincula esse conteúdo ao workflow, sem certificar a qualidade científica.

Com GitHub CLI atual e o arquivo baixado, verificar, por exemplo:

```bash
gh attestation verify quantis_PA.parquet --repo bernardoemmel/Raiz
```

O workflow `publicar-metadados.yml` preenche os arquivos que já existiam, usando os CSV e as versões publicadas;
não repete a coleta ou o funil geográfico. Ele disputa uma vaga no mesmo teto global de 15 jobs e não começa o
trabalho pesado sem reserva. Mantém as travas de UF e do índice, baixa e verifica bytes para atestar arquivos
inalterados e inclui distribuições avulsas no catálogo. Fichas Croissant não geram fichas recursivas.

Falha ao adquirir uma trava impede a publicação. Esperar por uma trava não prova abandono: o publicador novo
não a apaga por idade. Jobs iniciados com código anterior só adotam essas regras nas próximas execuções.

## Release `vigilancia`

A vigilância diária (`raiz/vigilancia/`, workflow `.github/workflows/vigilancia.yml`) lê os polígonos daqui e publica
no Release `vigilancia` (https://github.com/bernardoemmel/raiz/releases/tag/vigilancia): alertas de imóvel por mês
(`alertas_AAAA-MM.parquet`), espelho dos embargos do Ibama, situação das fontes e rodadas, abertos; projetos,
eventos de perda, marcações e rascunhos de relatório num pacote cifrado (`privado.tar.gz.cifrado`, chave
`RAIZ_VIGILANCIA_CHAVE`). `vigilancia.json` (manifesto) sobe por último. Detalhes em `raiz/vigilancia/README.md`.
