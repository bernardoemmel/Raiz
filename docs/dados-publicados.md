# Dados publicados: aberto e pago

Os dados grandes ficam fora do git. Existem dois contratos separados: uma
projeção pública para o mapa e os agregados; e o resultado completo do motor,
acessível somente por processos autorizados do servidor.

## O que é aberto

O Release `dados` distribui o contrato `publico_basico`, versão 1:

| Arquivo | Conteúdo permitido |
|---|---|
| `estados.json` | Cobertura por UF, municípios, datas, versões e endereços dos pacotes públicos |
| `raiz_<UF>.tar.gz` | Resumos por município e `imoveis_basicos_<IBGE>.csv` com `cod_imovel`, `cod_ibge`, `municipio`, `uf`, `situacao_basica` |
| `raiz_geo_<UF>.tar.gz` | Geometria do CAR com apenas `cod_imovel` e `geometry` |

As situações abertas são `apto`, `com_pendencia` e `nao_apto`. São uma triagem,
não certidão de domínio nem garantia de elegibilidade. Municípios e estados
mantêm agregados; valores de grupos pequenos são suprimidos para evitar a
reconstrução de uma ficha. Nenhuma fazenda é retirada por ser pequena.

A lista positiva está em `raiz/executor/publicacao_aberta.py`. Colunas, tabelas
e arquivos novos ficam privados até revisão. As geometrias abertas não carregam
atributos financeiros, históricos ou de risco. A amostra e os testes do site
seguem o mesmo contrato.

O front baixa somente esse contrato para `dados/publicos/`. O download rejeita
manifesto antigo, pacote com campos pagos e destino compartilhado com o espelho
privado. O build e o servidor de desenvolvimento também aplicam a lista positiva.
Sem dados básicos publicados, o site mostra cobertura indisponível; não busca
arquivos antigos completos como alternativa.

### Resumo aberto das três opções de lote

O site também oferece o contrato separado `publico_lotes`, versão 1, em
`amostra/lote_PA_central_r11.json`. A lista positiva contém, por alternativa:
créditos P10/P50/P90 da carteira, hectares, número de fazendas, custo médio em
US$/crédito e quanto da meta tem terra documentada. Contagem, área, créditos e
custo referem-se ao mesmo conjunto de **titulares e reservas**. As três opções
são alternativas, não se somam. Não entram TIR, CAR, localização, contornos,
tabela por fazenda, travas, “o que destrava” ou referências aos pacotes privados.
Medidas de grupos menores que cinco fazendas são suprimidas, sem excluir as
fazendas do lote.

`python -m raiz.lotes_publicos` lê somente o manifesto no arquivo autenticado,
reconfere a visibilidade privada e valida tamanho/digest. Nunca baixa os pacotes
individuais. A projeção grava apenas o resumo em `dados/lotes-publicos/`; o build
e o navegador aplicam outra lista positiva. Não ler `RAIZ_LOTES` nem a pasta
legada `dados/lotes` para publicar. O token existe apenas no passo de projeção
do Actions, nunca no build Vite, cache de dados ou artifact do Pages.

Terra pronta aqui significa matrícula conferida ou concessão documentada no
lote. `oferta.creditos_terra_pronta` é oferta estadual e também inclui matrícula
a conferir no solver: não pode preencher esse indicador. O manifesto atual
confirma zero fazendas documentadas nas três opções; se uma futura publicação
tiver mistura de terra documentada e pendente sem os créditos separados, a
medida permanece desconhecida. Nenhum desses valores libera comercialização.
Data e versão vêm do manifesto privado publicado, e novos filtros não fingem
recalcular um cenário congelado. Composição e diligência continuam na API
autenticada, com os controles por cliente e ficha descritos abaixo.

## O que é pago e permanece privado

Por imóvel: certidão lida por IA, cadeia e pendências detalhadas da terra,
comprometimento conhecido, sobreposições detalhadas, valor e créditos P10/P50/P90,
TIR, risco, restauração estimada, uso e perdas ao longo dos anos. A ausência de
nome ou CPF não torna esses derivados públicos.

O arquivo completo preserva CSV, GeoParquet, camadas internas, controle de
retomada, versões do motor e histórico de vigilância. Cada ficha é montada no
back-end, com fonte, referência temporal e data de corte de cada medida; falta
de dado continua explícita. O servidor exige identidade, liberação paga e limites
contra extração em massa. PDF e comparação passam pelas mesmas verificações.
Nunca são fornecidos nome, CPF ou contato do dono.

## Armazenamento privado e publicação

O destino desta migração é o Release **não publicado** `dados-privados` de
`bernardoemmel/Raiz` (ID 443383695). É um draft autenticado: **não publicar esse
Release**. A credencial de implantação não permitiu criar um repositório privado;
o código também aceita migrar para um Release de repositório privado no futuro.
O servidor confere `repo.private` ou `release.draft` antes de cada leitura e
escrita. Se o draft virar público, a operação falha.

```dotenv
RAIZ_ARMAZEM_URL=release-github://bernardoemmel/Raiz/dados
RAIZ_DADOS_PRIVADOS_URL=release-github://bernardoemmel/Raiz/dados-privados
RAIZ_DADOS_PRIVADOS_TOKEN=<somente no ambiente do servidor>
```

O token deve poder ler o Release privado. Os jobs de publicação usam credencial
com escrita, separada da credencial de leitura do back-end quando possível.
No Actions do próprio repositório, `github.token` permite manter o draft sem
expor token no navegador. Nunca usar variável `VITE_` para esse segredo.

O executor grava primeiro o pacote completo no destino privado; somente depois
projeta e valida os arquivos abertos. Travas por UF e por manifesto preservam
publicações concorrentes. Os nomes canônicos privados (`raiz_<UF>`, `raiz_geo_<UF>`,
`raiz_camadas_<UF>`, controles e `estados.json`) permitem retomar a coleta e carregar
o banco. Snapshots históricos usam nomes imutáveis e não substituem o canônico.
A vigilância por CAR, os cálculos completos do lote e os retratos imutáveis do
aprendizado também usam armazenamento privado. Os Releases diários de histórico
são drafts autenticados, com a visibilidade reconferida na leitura e escrita. Não enviar esses conteúdos como artifacts ou caches de Actions públicos.

## Arquivos históricos encontrados

Inventário inicial do Release `dados`, antes da troca (12/11/2026):

- `raiz_<UF>.tar.gz`: AC, AP, GO, MA, MG, PA, RO, RR e TO. Contêm o motor completo
  e camadas exclusivas, como ficha, desenvolvedor, terra, certidões, regularização,
  filtros, MapBiomas e histórico. Devem ser substituídos pela projeção aberta.
- `raiz_camadas_<UF>.tar.gz`: AC, AP, GO, MA, MG, RO, RR e TO. Somente privados.
- `raiz_geo_<UF>.tar.gz`: AC, AP, GO, MA, MG, PA, RO, RR e TO. O original é
  preservado; o público é reconstruído pela lista positiva de geometria e CAR.
- `raiz_controle_<UF>.json`: AC, AM, AP, GO, MA, MG, MS, MT, PA, RO, RR e TO.
  Controle detalhado de execução fica privado.
- `estados.json`: substituído pelo manifesto básico sem referências a camadas pagas.
- `URTX.kml`: arquivo fora do contrato aberto; preservado no privado, sem republicação automática.

O inventário completo relaciona cada asset e cada membro, colunas, tamanho,
SHA-256 e ID do GitHub. Novos Releases publicados também entram na varredura.
A primeira cópia remota concluiu com sucesso no
[Actions 43286647219](https://github.com/bernardoemmel/Raiz/actions/runs/43286647219):
40 assets, rebaixamento com SHA-256 idêntico e HTTP 404 sem autenticação. O
inventário e o comprovante foram guardados no draft. Essa fase não removeu originais. A troca concluiu no
[Actions 43288984765](https://github.com/bernardoemmel/Raiz/actions/runs/43288984765):
40 originais preservados integralmente, 39 canônicos completos no privado e
22 assets públicos validados (181.847.053 bytes), cobrindo as 12 UFs do manifesto.
Todos os IDs originais foram substituídos ou retirados. Os endereços antigos sem
substituto básico responderam 404. O comprovante final está no draft:
`corte-f53e946687c4f244-concluido-d25320df8bcce9a9.json`.
A retomada, se necessária, usa `corte-f53e946687c4f244-inventario.json`;
nunca reconstruir o completo a partir do Release já reduzido.

Artifacts antigos `entradas-congeladas`, `calculado-*` e `github-pages` também
podem conter dados completos. `scripts/migrar_artifacts_privados.py` seleciona
somente essas famílias, confere o digest oficial, preserva ZIPs imutáveis no
privado e exige rebaixamento/SHA-256/404 antes de remover os IDs originais.
Evidências de testes (`teste-pages`, `site-agentes`, `resultado-pytest`) não são
selecionadas. Caches de dados são descartáveis e serão reconstruídos no privado;
caches de dependências continuam permitidos.

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

### Resultado dos artifacts e caches

O [Actions 43289212685](https://github.com/bernardoemmel/Raiz/actions/runs/43289212685)
concluiu a preservação e remoção de 18 artifacts (2.052.697.385 bytes). A consulta
posterior confirmou zero artifacts dessas famílias. Provas autenticadas no draft:
`artifacts-inventario-43289212685.json`, `artifacts-backup-43289212685.json` e
`artifacts-remocao-43289212685.json`. Evidências de testes foram mantidas.

Depois dessa preservação, 33 caches descartáveis antigos de `motor-uf`,
`motor-comum`, `lote-pa` e `geo` foram removidos (2.798.752.814 bytes). Os caches
de dependências permanecem; novos caches de dados completos usam o destino privado.
A publicação do site também foi pausada durante a limpeza para manter o inventário
estável, sem retirar do ar o site já publicado.

A leitura real do manifesto completo pelo `ArmazemRelease` privado foi conferida
com token de ambiente: 12 UFs e controles de retomada presentes. O site e o
publicador rejeitam snapshots antigos de lotes: as telas de comparação permanecem,
mas medidas detalhadas vêm da API autenticada.

A continuação Dados do Brasil acrescenta os formatos abaixo sem ampliar o contrato aberto. Fichas públicas
só descrevem pacotes básicos, geometrias básicas, manifesto e o cartão metodológico revisado; rejeitam campos,
referências e textos fora desse perfil. `isAccessibleForFree` distingue a projeção aberta dos derivados privados.
As condições de acesso continuam separadas da licença de redistribuição, ainda não definida para os dados da Raíz.

## Fichas Croissant 1.1 e schema.org nos dois destinos

O publicador do executor gera `croissant_<UF>.json` com o SHA-256 do `raiz_<UF>.tar.gz` efetivamente publicado,
um `FileObject` por CSV e `FileSet` por tabela. Cada CSV preserva seu próprio esquema, inclusive quando um município
tem colunas mais novas que outro. O baker 0.8.3 infere os tipos percorrendo o CSV; o mlcroissant 1.1.1 valida a ficha
sem baixar o pacote. Um teste também carrega registros reais de um tar local pelo mlcroissant. Geração e validação
trabalham em partes de até 1.500 campos, com processos isolados e checagem global de IDs/referências; a ficha
publicada continua integral. Isso limita a memória sem retirar campos nem aceitar grafos inconsistentes.

Pacotes de geometria, camadas e arquivos de controle recebem `croissant_<nome-do-arquivo>.json`; esses arquivos
não tabulares são descritos como distribuições, sem prometer um leitor de registros para formatos não suportados.
`croissant.json` reúne as fichas publicadas. `croissant_estados.json` descreve os bytes do índice, e seu hash
fica apenas no catálogo para evitar autorreferência. As próprias fichas não geram novas fichas recursivamente.

Os pacotes e suas fichas são preparados antes do upload e publicados na mesma trava de UF. No destino privado, o catálogo é gerado
na trava global, com `estados.json` por último. Somente o índice privado passa a trazer `sha256` (pacote comprimido),
`proveniencia_sha256` (versões/datas dos arquivos), `croissant` e `fichas`; os consumidores antigos podem ignorar
essas colunas adicionais. No público, as fichas e o catálogo são separados e não alteram o manifesto básico. A atualização retroativa usa o arquivo privado completo e a projeção pública já validada, em espelhos distintos.

A licença dos dados derivados da Raíz ainda não foi definida. As fichas registram essa condição e remetem aos
créditos e termos das fontes em `NOTICE.md`; não atribuem automaticamente a licença do código ou a do baker aos dados.

## Quantis privados, versão do modelo e cartão metodológico

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

Os assets privados da UF são retratos mutáveis. O catálogo de versões conserva metadados, mas não é um histórico completo
de valores previstos. O módulo de aprendizado conserva previsões para comparação longitudinal no seu próprio
armazenamento; para reproduzir um retrato, conservar em armazenamento autorizado arquivos, hashes e atestação correspondentes.

## Cronogramas CAD Trust, no arquivo privado

`cadt_<UF>.json` descreve o cenário estadual ProFloresta+; `cadt_lotes.json` reúne os estados disponíveis. O objeto
`projeto` usa campos e listas do CAD Trust; proveniência, premissas e diagnósticos ficam no envelope da Raíz.
Cada `estimation` informa `creditingPeriodStart`, `creditingPeriodEnd` e `unitCount` anual em `tCO2e`. Os incrementos
derivam da curva de captura e dos marcos acumulados P50; o arredondamento conserva o total inteiro.

No Actions, `RAIZ_CADT_INICIO_CENARIO` usa **2027-01-01** por padrão e pode ser definida nas variáveis do repositório.
É uma âncora hipotética para comparar cronogramas. `Listed` representa a listagem neste catálogo de cenários;
VM0047 é referência metodológica. O arquivo não afirma registro no CAD Trust/Verra, certificação ou emissão de
créditos. Estado sem lote elegível ou cronograma válido recebe diagnóstico.
Resultados do desenvolvedor com versão científica/cenário ausentes, versões misturadas ou sem regra verificável
impedem o projeto estadual. O registro em `raiz/regras/historico/` recupera explicitamente a versão
`restauracao-2026c+421970fd`, com commit e hashes integrais; preserva previsões e curva originais, aplicando o
otimizador e as salvaguardas atuais aos créditos publicados. A regra histórica conserva reserva base de **12%**;
o piso de **20%** de `restauracao-2026d` exige cálculo novo e não é aplicado retroativamente pela exportação.
O carregador histórico independe do construtor e do normalizador atuais, validando os bytes originais antes de
montar o cenário.

A proveniência distingue a regra científica original (`regra_source_versao`, commit e SHA256) das versões atuais
do otimizador, do código do lote e das salvaguardas. Estas últimas também integram a identidade CADT. Sobreposição
jurisdicional confirmada e CLPI recusada impedem a seleção; ausência de comprovação não libera comercialização.
O arquivo declara `comercializacao.situacao: pendente` e não inclui decisões ou identificadores de imóveis.

## Atestação e atualização dos arquivos existentes

Depois de cada upload concluído, o publicador registra `sha256  nome` em `$RUNNER_TEMP/atestar.txt` (públicos).
No canal privado, `atestar-privado.txt` contém somente `sha256  privado-sha256-<mesmo digest dos bytes>`;
nem o nome original nem um hash do nome são publicados. O passo
`actions/attest-build-provenance@v2` usa esse arquivo, OIDC e permissões `id-token: write`/`attestations: write` para
atestar os bytes. No público, se um nome mudar várias vezes no mesmo job, a assinatura cobre seu último upload.
No privado, aliases de bytes iguais compartilham o identificador e versões de conteúdo diferentes permanecem
atestadas. Um portão sem dependências recusa listas privadas legadas/ambíguas antes da ação, mesmo em falha do job.
O SHA identifica conteúdo; a atestação vincula esse conteúdo ao workflow, sem certificar a qualidade científica.

Com GitHub CLI atual e o arquivo baixado, verificar, por exemplo:

```bash
gh attestation verify quantis_PA.parquet --repo bernardoemmel/Raiz
```

O workflow `publicar-metadados.yml` preenche os metadados dos dois destinos. Os CSV e as versões completos
são lidos somente do arquivo autenticado; nunca se tenta reconstruí-los a partir do Release básico. O catálogo
público descreve os bytes públicos existentes e não altera `estados.json`. Quantis, configuração do hub, catálogo
de modelos, diagnósticos, CADT e as fichas desses derivados ficam privados. Fichas não geram fichas recursivas.

A execução reserva uma das 15 vagas globais antes do trabalho pesado e usa as travas de UF e do índice. Código
anterior ao contrato privado não pode executar o motor; o guard roda antes do cache e do cálculo. Uma falha de
consulta bloqueia a publicação, sem cancelar os jobs existentes. Reservas concluídas ou canceladas não autorizam
novas execuções.

Antes de cada UF e dos arquivos globais, o publicador confere a margem da API. Cota insuficiente encerra com
progresso preservado para retomada por UF, ou apenas dos globais. Repetições por quota têm limite de 60 segundos
por job. Substituições preservam o original em cópia imutável autenticada antes do DELETE; nenhum original
privado é enviado como artifact ou cache de Actions público.

A atestação contém nomes somente dos arquivos públicos; para os privados usa identificadores derivados do conteúdo,
SHA-256 e proveniência do build. Não contém os valores dos arquivos nem CARs. Esses identificadores criptográficos podem ser públicos no serviço de atestação do GitHub,
mesmo quando os bytes permanecem privados. As listas de checksums são separadas para não confundir arquivos
homônimos dos dois destinos. Para verificar um arquivo privado, o processo autorizado primeiro o baixa e depois
executa o verificador acima. A ficha privada usa `release-github://repo/tag/nome`, uma URI lógica resolvida pelo
back-end via API autenticada; o leitor genérico mlcroissant não autentica esse protocolo sozinho.
