# Restrições nacionais na triagem

Quatro fontes nacionais entram na triagem de cada imóvel e chegam sozinhas ao lote: **SICAR completo**, **SIGMINE
(ANM)**, **autos de infração do Ibama** e **Lista Suja do trabalho escravo**. Cada imóvel recebe um status:

| status | o que acontece no lote |
|---|---|
| `exclusao` | sai do lote (vira bloqueio na oferta; o motivo vai para a decisão explicada, LGPD art. 20) |
| `ressalva` | fica no lote, marcado, com o motivo; o checklist do lote conta as ressalvas |
| `livre` | todas as fontes essenciais cobriram o imóvel e nada cruzou |
| `nao_verificado` | faltou fonte; ausência de dado nunca vira terra livre |

Código: `raiz/restricoes/coleta.py` (coleta), `raiz/restricoes/status.py` (cruzamento por imóvel, tarefa
`restricoes` do executor), regras em `raiz/regras/padroes/restricoes_nacionais.yaml`. Colunas em `docs/colunas.md`
(`restricoes_<mun>.csv`).

## O que cada fonte filtra e o critério

"Passa do limiar" = a sobreposição tem pelo menos **1 ha** ou **5% do imóvel** (imóvel pequeno conta pela fração;
ninguém sai por tamanho). Abaixo de **0,1 ha** é ruído de contorno e não marca nada.

| fonte | exclusão | ressalva |
|---|---|---|
| SICAR: povos e comunidades tradicionais (CAR tipo PCT) | PCT sobreposto passa do limiar (`territorio_tradicional`; OIT 169, Lei 15.042/2024 art. 47) | PCT só na borda (`territorio_tradicional_borda`) |
| SICAR: assentamentos (CAR tipo AST) | — | AST sobreposto passa do limiar (`assentamento_sobreposto`; conferir com o INCRA) |
| SICAR: sobreposição entre CARs | — | outro CAR de imóvel rural passa do limiar (`car_sobreposto`) |
| SICAR: situação do cadastro | — | CAR suspenso ou cancelado (`car_suspenso`), pendente (`car_pendente`) |
| SICAR: RL e APP declaradas | — | RL ou APP declarada por **outro** CAR dentro do imóvel passa do limiar (`rl_app_alheia`); a RL e a APP do próprio imóvel ficam medidas (`rl_declarada_ha`, `app_declarada_ha`) |
| SIGMINE (ANM) | processo em fase de lavra (concessão, lavra garimpeira, licenciamento, registro de extração e os requerimentos de lavra) passa do limiar (`mineracao_lavra`) | lavra só na borda (`mineracao_lavra_borda`); pesquisa, requerimento de pesquisa ou disponibilidade (`mineracao_pesquisa`) |
| Autos de infração do Ibama | — | auto não cancelado desde 2008 dentro do imóvel (`ibama_auto`); de Flora nos últimos 5 anos (`ibama_auto_flora_recente`) |
| Lista Suja (MTE) | auto ou embargo do Ibama de infrator listado dentro do imóvel (`lista_suja`) | polígono do infrator listado só na borda (`lista_suja_borda`) |

O embargo do Ibama já sai do funil antes (motor). Aqui entram os autos, que não embargam a área mas mostram
histórico de infração.

## LGPD

- Nome, CPF, CNPJ e endereço **nunca saem da coleta**. SIGMINE perde o titular; os autos perdem nome e documento.
- A Lista Suja é cruzada **dentro da coleta, em memória**: o documento do empregador listado é comparado com o do
  infrator dos autos e embargos do Ibama (CPF inteiro ou raiz do CNPJ, que pega as filiais). O que sai é só o
  polígono ou ponto do auto/embargo (o vínculo geográfico) e a contagem por município. No imóvel fica só "há vínculo".
- A coleta confere, antes de publicar, que nenhum CPF ou CNPJ ficou nos arquivos (`conferir_sem_documento`).
- `restricoes_<mun>.csv` é privado (não entra na publicação aberta).

## Como roda

- `coletar-restricoes.yml` (quartas, 05h41) coleta e publica no Release `insumos`. `processar-estados.yml` baixa as
  camadas para `motor/cache/restricoes`.
- A tarefa `restricoes` do executor é folha do grafo (depende só do funil): coleta nova ou regra nova refaz só ela.
  Os municípios **não** foram recalculados agora; entram no próximo processamento ou com
  `raiz restricoes recalcular [--ufs PA] [--municipios 1507300]`.
- O CAR completo (todos os tipos) vem do CAR nacional (`raiz/coleta/car_nacional.py`); o funil guarda só o imóvel rural.

## No lote

- **Lote nacional** (`raiz/restauracao_nacional.py`, `lote-nacional.yml`): o índice traz `restricao_nacional`,
  `restricao_exclusao`, `restricao_ressalva` e `restricao_motivos` (nulo = não verificado). A rodada refaz
  `restricoes_<mun>.csv` que falte ou esteja velho (`completar_restricoes`, com a coleta do Release `insumos`), a
  consulta tira as exclusões (o motivo vai para a decisão gravada), conta ressalvas e não verificadas em cada opção e
  devolve `restricoes_nacionais` com `verificada`, `parcial` ou `nao_verificada` e os motivos agregados (sem CAR).
- **Dossiê do município** (`raiz/dossie_lote.py`, `docs/lote.md`): exclusão sai em qualquer modo; ressalva entra com
  peso (forte: borda de Lista Suja ou lavra, território tradicional na borda, auto de Flora recente, CAR suspenso;
  leve: RL/APP de outro CAR; o resto, média). Sem verificação: ressalva média, nunca "livre".

## Pendências conhecidas

- **RL e APP declaradas**: a base de downloads do SICAR fica atrás de captcha. O pedido de LAI 02303.031114/2026-60
  ao SFB pede a coleta em lote. `converter_car_temas()` já lê os shapefiles; até lá `car_temas` aparece em
  `restricoes_nao_verificadas` (não impede o "livre", é complemento).
- **SIGMINE**: na primeira coleta no GitHub Actions (17/11/2026) as 27 UFs falharam. O portal `app.anm.gov.br`
  derruba a conexão vinda de fora do Brasil (reset), e o ArcGIS `geo.anm.gov.br` manda o certificado sem o
  intermediário ("unable to get local issuer certificate"). A coleta agora completa a cadeia pelo endereço do emissor
  gravado no certificado (AIA), com a verificação ligada, e desiste cedo de um servidor que cai em duas UFs seguidas
  (a primeira rodada levou 85 minutos só em tentativas). Se o ArcGIS ainda falhar, o SIGMINE fica `nao_verificado` e
  precisa de uma coleta a partir do Brasil.

## Teste com dado real (São Félix do Xingu, 17/11/2026)

Coleta real: 503 empregadores na Lista Suja (460 com município), 217.788 autos do Ibama desde 2008, 93 vínculos
geográficos (67 autos e 26 embargos). Sem nenhum CPF ou CNPJ nos arquivos. Cruzamento dos 9.703 CARs de São Félix
(com o CAR completo do WFS, sem SIGMINE): 6 exclusões por Lista Suja, 8.738 com ressalva (5.627 CAR suspenso ou
cancelado, 4.838 sobreposição entre CARs, 2.914 sobre assentamento, 2.158 CAR pendente, 670 com auto do Ibama),
959 não verificados; 10 s para o município.

## Padrão para novas camadas

Outras fontes (estaduais, IBGE, SICOR...) seguem o mesmo desenho: coleta sem dado pessoal publicada no Release
`insumos` com um `*_cobertura.json`; tarefa folha do executor que grava `<camada>_<mun>.csv` com status por imóvel
(`exclusao | ressalva | livre | nao_verificado`), motivos em códigos com o texto num YAML de `raiz/regras/padroes/`,
e o nome do arquivo em `raiz/contrato.py` (`COMPLEMENTOS`) para chegar à oferta e ao lote.
