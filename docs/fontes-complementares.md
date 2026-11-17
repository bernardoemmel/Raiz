# Fontes complementares na triagem

Crédito rural, quilombos, territórios tradicionais, restauração fora dos registros de carbono e as certidões da CNIB e
do SAEC. Quando um lote é montado ou um imóvel é triado, estas fontes entram sozinhas como **exclusão** ou
**ressalva**, ao lado das restrições nacionais (`docs/restricoes-nacionais.md`) e da terra já comprometida
(`docs/terra-comprometida.md`). Segue o mesmo padrão de camada:

| status (`complementar_status`) | o que acontece no lote |
|---|---|
| `exclusao` | sai do lote (bloqueio na oferta; o motivo vai para a decisão explicada, LGPD art. 20) |
| `ressalva` | fica no lote, marcado, com o motivo; o checklist do lote (`fontes_complementares`) conta as ressalvas |
| `livre` | as fontes essenciais (SICOR e localidades quilombolas do IBGE) cobriram o imóvel e nada cruzou |
| `nao_verificado` | faltou fonte essencial; ausência de dado nunca vira terra livre |

Código: `raiz/complementares/coleta.py` (coleta e importação), `raiz/complementares/status.py` (cruzamento por imóvel,
tarefa `complementares` do executor, folha do grafo), regras em `raiz/regras/padroes/complementares.yaml`, colunas em
`docs/colunas.md` (`complementares_<mun>.csv`). CNIB e SAEC: `raiz/documentos/certidao/onr.py`.

## O que cada fonte filtra e o critério

"Passa do limiar" = a sobreposição tem pelo menos **1 ha** ou **5% do imóvel** (imóvel pequeno conta pela fração;
ninguém sai por tamanho). Abaixo de **0,1 ha** é ruído de contorno.

| fonte | exclusão | ressalva |
|---|---|---|
| **SICOR** (Banco Central): operações de crédito rural ligadas ao CAR | — | crédito ainda não vencido ligado ao CAR ou gleba de operação ativa passa do limiar (`credito_rural_ativo`: a área pode estar dada em garantia e em uso financiado; conferir hipoteca ou penhor na certidão) |
| **SICOR**: glebas financiadas | — | gleba emitida nos últimos 3 anos passa do limiar, sem crédito ativo (`uso_agricola_recente`: área produtiva, custo de oportunidade maior) |
| **SICOR**: crédito para floresta | — | florestamento, recuperação ambiental, integração lavoura-pecuária-floresta ou extrativismo, vigente ou dos últimos 3 anos (`credito_rural_floresta`: restauração talvez já financiada; conferir adicionalidade e dupla contagem) |
| **Localidades quilombolas** (IBGE, Censo 2022) com a certificação da **Fundação Palmares** | localidade dentro do imóvel (`localidade_quilombola_dentro`; OIT 169 e Lei 15.042/2024, art. 47) | localidade a até 2 km (`localidade_quilombola_proxima`) |
| **Fundação Palmares** (planilha oficial de comunidades certificadas) | — | não marca o imóvel sozinha (a planilha não tem coordenada): vira contagem do município (`palmares_certificadas_municipio`, `palmares_sem_titulo_municipio`) e o ponto do IBGE diz se a comunidade é certificada (`quilombola_certificada_fcp`) |
| **Territórios tradicionais do MPF** (Plataforma de Territórios Tradicionais) | território passa do limiar (`territorio_tradicional_mpf`) | só na borda (`territorio_tradicional_mpf_borda`) |
| **Observatório da Restauração** e **Restor** | — | projeto de restauração passa do limiar (`restauracao_existente`: adicionalidade, dupla contagem; quem restaura ali pode ser parceiro) ou só na borda (`restauracao_existente_borda`) |

Os quilombos já delimitados pelo INCRA continuam no motor (`quilombo_ha`, `raiz_filtros.py`); o CAR de povos e
comunidades tradicionais entra pelas restrições nacionais (`territorio_tradicional`). As localidades do IBGE cobrem o
que falta: comunidades sem território delimitado (7.160 das 8.441 localidades estão fora de território oficial).

## Fontes, acesso e o que fica de fora

| fonte | como chega | atualização | licença | dado pessoal |
|---|---|---|---|---|
| [SICOR, microdados](https://www.bcb.gov.br/estabilidadefinanceira/tabelas-credito-rural-proagro) (`SICOR_OPERACAO_BASICA_ESTADO_<ano>`, `SICOR_PROPRIEDADES`, `SICOR_GLEBAS_WKT_<ano>`, `Empreendimento.csv`) | download direto, workflow semanal | o BCB regrava aos domingos | ODbL ([dados abertos do BCB](https://dadosabertos.bcb.gov.br/dataset/matrizdadoscreditorural)) | `SICOR_PROPRIEDADES` traz CPF/CNPJ do tomador: a coluna nem é lida (`usecols`). Saem só código do CAR, datas, finalidade, área financiada e polígono. Nenhum valor em reais |
| [Localidades quilombolas 2022](https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/localidades_quilombolas_2022/) (IBGE) | CSV com coordenadas | por censo | uso livre com citação do IBGE | nome da comunidade sai; ficam códigos e marcações |
| [Comunidades certificadas](https://www.gov.br/palmares/pt-br/departamentos/protecao-preservacao-e-articulacao/certificacao-quilombola) (Fundação Cultural Palmares) | planilha Google oficial exportada em CSV (link na própria página da FCP) | mensal | dado público do governo | nome e processos saem; fica a contagem por município |
| [Plataforma de Territórios Tradicionais](https://www.mpf.mp.br/atuacao/populacoes-indigenas-e-comunidades-tradicionais/territorios-vivos/plataforma-de-territorios-tradicionais) (MPF/CNPCT) | **sem download público**: o acesso é decidido pelo Conselho Gestor; pedido em `docs/pedidos/mpf-territorios.md` | — | a definir no acesso | só id, segmento, situação e polígono |
| [Observatório da Restauração e Reflorestamento](https://observatoriodarestauracao.org.br/) (Coalizão Brasil) | shapefile pedido por e-mail (já enviado) | — | a definir na resposta | só id, categoria, ano de início e polígono |
| [Restor](https://restor.eco/) | **os termos de uso proíbem copiar os dados sem permissão**; API só no plano Enterprise; pedido em `docs/pedidos/restor.md` | — | só com autorização escrita | só id, categoria, ano de início e polígono |

### Quando o arquivo do Observatório (ou do MPF, ou da Restor) chegar

Rodar o workflow **Fontes complementares** (`coletar-complementares.yml`) à mão, com:

- `importar_fonte`: `observatorio` (ou `mpf_territorios`, `restor`);
- `importar_url`: link direto do arquivo (zip do shapefile, GeoPackage ou GeoJSON);
- `autorizacao`: quem autorizou, quando e por qual meio (ex.: "e-mail da Coalizão Brasil de 20/11/2026").

A importação lê só as colunas técnicas (os nomes aceitos estão em `_CAMPOS`), grava o arquivo e um
`complementares_<fonte>_meta.json` com a autorização e publica no Release `insumos`. As coletas semanais seguintes
trazem o importado de volta antes de publicar, então ele não se perde. Localmente:
`uv run raiz complementares importar arquivo.zip --fonte observatorio --saida pasta --autorizacao "..."`.

Alternativas enquanto não chega: os projetos com registro já entram pela terra comprometida (Verra, InfoAmazonia,
Zenodo); o crédito rural de florestamento e recuperação do SICOR (`credito_rural_floresta`) pega parte das
iniciativas financiadas; e o CAR de povos e comunidades tradicionais (restrições nacionais) mais as localidades do
IBGE cobrem parte do que a plataforma do MPF traz.

## CNIB e SAEC no fluxo de certidões

`raiz/documentos/certidao/onr.py`. Nenhuma das duas roda sem **autorização do dono** registrada para o imóvel e o
escopo (`cnib`, `saec`), com o hash do termo ou aceite como evidência, validade de 90 dias e revogação.

- **CNIB** (indisponibilidade de bens): a consulta é pelo CPF ou CNPJ do dono. O documento só existe em memória
  durante a chamada; fica a situação (`sem_ordem`, `com_ordem`, `pendente`, `sem_autorizacao`), o número de ordens, a
  data e o hash do protocolo. Ordem de indisponibilidade = falha no checklist ("não contratar até baixar").
- **SAEC** (ONR): pedido da certidão de inteiro teor (até 30 dias) pelo cartório (CNS) e pela matrícula, que já vêm do
  SIGEF ou do dono. Quando chega, o PDF entra pelo fluxo de `docs/primeira-certidao.md`.
- **Sem convênio com o ONR** (pedido em `docs/pedidos/onr-convenio.md`), o transporte é manual: a função devolve a
  instrução do que pedir e onde (indisponibilidade.onr.org.br, registradores.onr.org.br) e o checklist marca
  "pendente". Quando a documentação técnica do convênio chegar, basta implementar `Transporte`.
- No lote, o item `cnib_saec` do checklist diz quantas fazendas ainda não têm consulta e se alguma tem ordem.

## Como roda

- `coletar-complementares.yml` (quintas, 06h17) coleta e publica no Release `insumos`. `processar-estados.yml` baixa
  as camadas (das glebas, só a da UF) para `motor/cache/complementares`.
- A tarefa `complementares` do executor é folha do grafo (depende só do funil): coleta nova ou regra nova refaz só
  ela. Os municípios **não** foram recalculados agora; entram no próximo processamento ou com
  `raiz complementares baixar --ufs PA` e `raiz complementares recalcular [--ufs PA] [--municipios 1507300]`.
- A coleta confere, antes de publicar, que nenhum CPF ou CNPJ ficou nos arquivos (`conferir_sem_documento`).
- `complementares_<mun>.csv` é privado (não entra na publicação aberta).

## Conferência com dado real (17/11/2026)

- SICOR 2026 (até a coleta do BCB de 15/11): 1.998.956 operações; 1.861.239 ligadas a CAR (93%), em 818.866 CARs.
  Em Paragominas, 190 CARs com crédito emitido em 2026; em São Félix do Xingu, 448. A leitura do
  `SICOR_PROPRIEDADES` (500 MB) leva cerca de 1 minuto e nenhum documento sai.
- IBGE: 8.441 localidades quilombolas; 1.281 dentro de território oficial; 3.846 com processo na Fundação Palmares.
  Nenhuma em Paragominas ou São Félix do Xingu (os 6 CARs da conferência de Paragominas ficam a mais de 110 km da
  mais próxima).
- Palmares: 3.662 certidões em 1.125 municípios; 3.525 sem título.
- O BCB às vezes responde com uma página "Requisição inválida!" e código 200: a coleta confere o início do gzip e
  trata como falha da fonte (o ano fica em `anos_falharam`, a cobertura fica `parcial`).
