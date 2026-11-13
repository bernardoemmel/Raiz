# Passagem — Lote e números

## Entrega de 12/11/2026: cálculo e salvaguardas da rodada 11

Área: `raiz/lote.py`, `raiz/lote_relatorio.py`, `raiz/restauracao*.py`, `raiz/regras/`, testes e documentação.
Sem alteração na API, no MCP ou no código do front. Exceção autorizada pelo fundador: o teste de complementos
passa a exigir arquivos obrigatórios, excluir `certidoes_` e aceitar novos arquivos de uma linha por imóvel.
O workflow novo é a infraestrutura necessária para rodar o pedido no Actions.

- Modelo `restauracao-2026d`: reserva contra reversão nunca abaixo de 20%; inclui hash do código e premissas.
  O ICVCM 9.4(a)(5)(i) prevê essa alternativa; 9.4(a)(5)(ii) também permite ajuste proporcional ao risco.
  A Raíz adota o piso conservador solicitado. Não é uma afirmação de piso universal obrigatório em qualquer padrão.
- Preço mínimo por fazenda para TIR de 12% e 15%, projeto e alavancada, dívida pelo ICSD; corrigida participação do
  dono no período de duas fases. Fluxo do lote e preço por fazenda são conferidos separadamente.
- Três alternativas do mesmo solver: barata, segura e compacta. A compacta não reaplica bônus genérico de vazamento
  sobre créditos que já foram calculados líquidos. Pequenas continuam candidatas, sem corte por tamanho.
- Sobreposição jurisdicional confirmada bloqueia seleção; situação desconhecida permanece potencial, sem liberar
  venda. Camada opcional `jurisdicional_<mun>.csv` e função espacial `cruzar_jurisdicional` com fonte/vigência.
  Lei 15.042, art. 43 §§6,7,11,13: falta comprovar exclusão e período para não contar duas vezes.
- Território tradicional exige CLPI custeada pelo desenvolvedor e partilha comprovada: mínimo 50% para remoção,
  70% para REDD+ de mercado (art. 47). Ausência de consentimento não é autorização.
- Decisões e risco: JSONL com critério textual, versão e ID estável; revisão humana por protocolo persistente
  em SQLite (`pedir_revisao_humana`). A revisão não libera crédito automaticamente. A API para esses pedidos
  não foi alterada, conforme divisão de trabalho.
- Falta de dado de pasto não gera crédito sobre a área livre inteira: situação `pendente_pasto`, sem afirmar que
  a fazenda não tem potencial. Não confundir informação ausente com área zero observada.
- O lote recusa mistura de previsões antigas com fluxos do modelo atual. Fixtures históricas permanecem no git;
  o teste do lote recalcula uma cópia temporária antes de comparar.

## Execução e publicação

O fluxo original `.github/workflows/lote-para.yml`, comando `python -m raiz.restauracao_rodada`, congelou os IDs
e hashes dos pacotes `raiz_PA.tar.gz` e `raiz_geo_PA.tar.gz` do Release `dados` e distribuiu 144 municípios por
15 jobs. Seu publicador público foi desativado na migração descrita abaixo. A continuação protegida confere
versões e cobertura, monta as três opções e preserva pacotes imutáveis no Release privado; não atualiza o
ponteiro público `lote_PA_central_r11.json`. Não substitui os pacotes do motor nem grava dados grandes no git.

Inspeção inicial: 144 municípios e 345.870 imóveis no pacote publicado; sem tabelas de desenvolvedor e terra,
APP pela escadinha presente em 81 municípios. Usa somente dados congelados; não executa downloads geográficos novos.
Piloto de Nova Esperança do Piriá: 880 imóveis reais calculados, três opções e todos os arquivos gerados localmente.
Código mesclado no [PR #49](https://github.com/bernardoemmel/Raiz/pull/49), após os três checks verdes no
[CI 43284244212](https://github.com/bernardoemmel/Raiz/actions/runs/43284244212). A
[execução integral 43285608189](https://github.com/bernardoemmel/Raiz/actions/runs/43285608189), no commit
`31990520b842fd665152b2c7931b3556a66ca180`, foi cancelada externamente às 19:09 UTC: dez das quinze fatias
concluíram com sucesso, cinco foram interrompidas e a publicação não começou. O GitHub registra cancelamento pela
conta `bernardoemmel` e workflow desativado manualmente. A publicação dessa execução não ocorreu; nenhuma saída
parcial foi promovida ao Release. As dez fatias prontas cobrem 98 municípios e 230.295 imóveis; ficaram 46 municípios
e 115.575 imóveis nas cinco interrompidas. Os onze artefatos (entrada e dez resultados) foram depois preservados no
draft privado pelo Actions `43289212685` e removidos do armazenamento público de artifacts. A mesma migração,
conduzida pelo chat Ficha da fazenda, removeu 33 caches de dados, incluindo os quinze caches do lote. As dez fatias
prontas continuam preservadas; os caches parciais das cinco incompletas não estão mais disponíveis.
O fundador esclareceu que o cancelamento não
era intencional para esta entrega e autorizou retomar somente as cinco fatias, aguardando vagas para respeitar o
limite de quinze jobs junto ao processamento dos estados, sem cancelar trabalhos em andamento.

**Origem identificada:** o chat **RAIZ - Ficha da fazenda** (`6af60423-79ec-8191-bf64-3a51a8470005`), no comando
`exec-912e58b0-7e6e-41c0-b64a-931f36538908`, executou `PUT .../actions/workflows/416422657/disable` e
`POST .../actions/runs/43285608189/cancel`. A ação fazia parte da migração autorizada naquele chat para tirar
camadas pagas por imóvel do Release público. Não foi cancelamento automático por concorrência do GitHub.
Para evitar repetição, não pausar em bloco workflows de outros chats: preservar os cálculos e coordenar a troca
do publicador. A ausência de nome/CPF não torna TIR, risco e crédito por imóvel dados abertos.

Repetir os jobs cancelados pelo mecanismo padrão executaria também o publicador público do commit antigo.
A continuação usa `.github/workflows/retomar-lote-para.yml` e `raiz/restauracao_retomada.py`: reutiliza a entrada
e as dez fatias concluídas a partir dos ZIPs privados `actions-<id>-<nome>.zip` e calcula apenas `00`, `01`, `02`,
`05` e `12`. Os comprovantes `artifacts-inventario-43289212685.json` e `artifacts-backup-43289212685.json` vinculam
IDs, execução original, commit de origem, nomes, tamanhos e SHA256; são conferidos antes de aceitar os ZIPs.
As cinco incompletas começam sem os caches antigos removidos e preservam os novos checkpoints no draft privado.
Executa código, amostra e lockfile no commit original, copiando somente o orquestrador privado. Confere hashes de
entrada e saída, modelo, CARs, contagens e a composição exata de cada fatia antes da reunião. Uma conclusão já
preservada é validada e reutilizada; não há novo cálculo só porque um passo posterior precisou ser repetido.
Os arquivos completos têm como destino o Release
autenticado `dados-privados` (draft, ID 443383695), sem publicar o draft nem criar novos artifacts/caches públicos.
Depois da execução documentada abaixo, a integração do PR #72 atualizou o orquestrador para usar
`RAIZ_DADOS_PRIVADOS_URL` e `RAIZ_DADOS_PRIVADOS_TOKEN`, como o arquivo privado da rodada atual;
por preservar as provas históricas, recusa outro repositório/tag ou ausência de token. Sua identidade de origem
fica no próprio orquestrador, sem depender de `REPO` no módulo atual da rodada. O token segue somente no ambiente
do processo autenticado; erros de API e download não expõem URLs assinadas. Motor e lockfile continuam no SHA original.
Nenhuma das dez fatias prontas deve ser recalculada.
O fluxo original foi desativado durante a retirada do publicador público; a continuação protegida
usa o mesmo grupo de concorrência, no máximo cinco jobs de cálculo e dispara apenas quando houver vagas.
Após a integração do PR #72, ambos os workflows estão ativos e o fluxo original também publica apenas no arquivo
privado. Não foi disparada uma nova rodada integral: a entrega reutiliza exatamente as dez fatias anteriores.

A continuação foi integrada no [PR #55](https://github.com/bernardoemmel/Raiz/pull/55), com os seis checks verdes
no [CI 43296782776](https://github.com/bernardoemmel/Raiz/actions/runs/43296782776). A
[retomada 43299409156](https://github.com/bernardoemmel/Raiz/actions/runs/43299409156) foi iniciada às
17h20 de 12/11/2026 (Brasília), no commit `3546687c66ec07ef9bd875d181efcff57ff1d312`, após conferir nove jobs
ativos no repositório. Não foi cancelado nenhum trabalho para abrir vaga. A preparação validou e preservou as
dez fatias prontas; as cinco autorizadas concluíram com sucesso. Motor, amostra e entradas continuam congelados
no commit original, com modelo `restauracao-2026d+a84f9789`.

**Publicação integral concluída:** a retomada terminou com sucesso às 17h47 de 12/11/2026 (Brasília), cobrindo
144 municípios e 345.870 imóveis. Os quatro pacotes foram baixados novamente e conferidos por tamanho e SHA256.
O [Release privado](https://github.com/bernardoemmel/Raiz/releases/tag/untagged-cecbbef1c8d8aa0a27d5) continua em
rascunho e exige autenticação. Os resultados detalhados não foram recolocados no Release público `dados`.
A descrição desse Release contém a nota de auditoria posterior, incluindo a limitação dos campos legados de TIR.

Manifesto: `lote_PA_central_r11_retomada_43299409156_1_b29eb3fe8887a676.json`, asset `741030570`,
SHA256 `b29eb3fe8887a676bbf5ad1ea7a040c68a0cc90d0863b27c5d3bd6e9ff34854c`.
Os nomes abaixo são precedidos por `lote_PA_central_r11_retomada_43299409156_1_`; o manifesto contém o SHA completo
de cada arquivo e os quinze comprovantes de origem, distinguindo dez reutilizações de cinco conclusões novas.

| Pacote privado | Asset | Bytes | Conteúdo |
|---|---|---:|---|
| `barata_387255d9db78dbcf.tar.gz` | `741026329` | 81.877.508 | Lote mais barato, CSV por fazenda, relatório, decisões e ecologia |
| `segura_f9a00ea18159548f.tar.gz` | `741027168` | 81.949.402 | Lote mais seguro, mesmos produtos e critérios |
| `compacta_0d4b6f7925a4f238.tar.gz` | `741028120` | 81.947.222 | Lote mais compacto, mesmos produtos e critérios |
| `previsoes_50dd1bd0501054dc.tar.gz` | `741030043` | 143.253.367 | Previsões imutáveis, fontes, 144 marcas municipais, comparação real e decisões de entrada |

Cada opção contém P10/P50/P90, TIR por fazenda, preços mínimos para TIR de 12% e 15% (projeto e alavancada),
quadro “o que destrava”, hectares e créditos por pendência. As três alternativas não são somáveis; as linhas de
pendência também se sobrepõem. Todos os lotes continuam **potenciais para diligência, sem liberação de venda**.
Os quantis ecológicos permanecem pendentes pelos motivos documentados abaixo, sem substituir nulos por zero.

A auditoria posterior conferiu as 345.870 previsões CSV/JSONL e os 576 hashes municipais, sem perda ou duplicação
de CAR. Reserva observada de 20% a 60%; faixas de crédito ordenadas, preços mínimos TIR15 ≥ TIR12 e limites
físicos de área preservados. Permanecem 27.185 áreas positivas menores que 1 ha, incluindo 1.502 de até 0,05 ha.
As 110.813 ausências de `pasto_ha` têm alternativa publicada `mb_pasto_2025_ha`; não foram convertidas em zero
por falta de informação. As 38.676 inconsistências de área estão sinalizadas nas premissas substitutas e receberam
o limite físico. Os três lotes reconciliam resumo, CSV e manifesto; suas TIRs e quatro preços mínimos por fazenda
estão preenchidos. Foram conferidas 4.579.801 decisões de seleção e entrada, com critério, versão e revisão humana.

**Limitação financeira do modelo congelado:** os campos legados `tir_*_pct_p50` guardam a TIR do caminho central,
não a mediana dos sorteios. Em 1.908 registros estaduais esse valor supera o P90 dos sorteios; nenhum pertence
às fazendas selecionadas ou às linhas de espera dos três lotes. O valor `-100` nesses indicadores é a sentinela
legada de TIR não encontrada pela busca, não uma TIR medida nem prova de perda integral. Não ordenar os três
valores artificialmente nem apresentar a tripla como quantis estatísticos completos. As previsões originais
permanecem imutáveis; a distinção entre cenário central, quantis e TIR não definida fica registrada na auditoria
para evolução do modelo, sem recalcular as dez fatias preservadas. Os quantis de créditos e os valores publicados
de preços/TIRs das selecionadas permanecem inalterados; para elas, “P50” da TIR também significa caminho central.

Auditoria do artefato preservado `calculado-03`: 23.023 imóveis em nove municípios, 36 hashes conferidos,
previsões JSONL consistentes com os CSVs e modelo único `restauracao-2026d+a84f9789`. Nenhuma violação do piso de
20% (faixa observada 20–60%), da ordem dos quantis de crédito, dos preços mínimos TIR15 ≥ TIR12 ou dos limites de área.
Foram mantidas 1.099 áreas positivas menores que 1 ha. Há 3.811 entradas com inconsistência de área sinalizada
e limite físico aplicado; as premissas substitutas de distância, declividade, chuva, solo, acesso e linha de base
estão identificadas. Essa conferência cobre uma fatia e não substitui a validação integral antes da publicação.
Na entrada congelada completa, as 144 tabelas somam 345.870 linhas e 345.870 CARs únicos, sem vazios nem
duplicação entre municípios. O ZIP da fatia auditada também corresponde exatamente ao SHA e tamanho dos
comprovantes privados da migração.

## Comparação com o real

O snapshot publicado de Nova Esperança ainda coincide com a exportação antiga: 222.694 tCO2/ano e 40.325,22 ha de
pasto. O documento `docs/teste-real-2026-11-12.md` relata a coleta atualizada com 209.708 tCO2/ano e 37.736 ha.
São fontes/coleções distintas, não medições de crescimento realizado. Não aplicar um fator de 5,8% à captura.
O relatório identifica a fonte efetivamente usada, compara por CAR e guarda hashes; o registro de previsões é
imutável por modelo e entradas. A publicação de uma coleta mais recente permanece dependente do fluxo de dados.

## Ecologia regional: fontes verificadas e pendências

O fundador confirmou ausência de inventário próprio e autorizou estimativa regional ou pendência quando as fontes
abertas não bastarem. `ecologia_PA.json` contém, por fazenda, os horizontes 3/5/10/15, bioma, método, versão,
fontes e licenças, com o rótulo **“estimativa regional, não medida na fazenda”**. Nesta rodada os quantis de árvores
e espécies ficam nulos com justificativa; nulo não é zero. O modelo ecológico `ecologia-2026b` inclui hash do código
e do YAML; os arquivos publicados são imutáveis por execução para confrontar com inventário futuro.

| Fonte pública examinada | Licença dos dados | Resultado da auditoria |
|---|---|---|
| [IFN/SFB, set/2025](https://dados.florestal.gov.br/dataset/ifn-dap-10-por-uf_disp-set2025) | CC-BY, versão não indicada no portal | Há microdados regionais, mas sem vínculo de idade e método de restauração; DAP10 e regenerantes têm esforços distintos. |
| [Rozendaal 2019, DANS](https://doi.org/10.17026/dans-xh8-gh92) | CC0-1.0; artigo NC apenas citado | Riqueza padronizada em 25 fustes, sem densidade absoluta. Seis sítios usam DAP10; falta confirmar a correspondência S1/S2 para o recorte brasileiro. Não usar como riqueza total por fazenda. |
| [Poorter 2021 / 2ndFOR](https://github.com/dylancraven/MultiDimensional_Recovery) | CC-BY-2.0 no repositório | Recuperação relativa dos atributos; não fornece diretamente árvores/ha ou espécies absolutas por fazenda. |
| [Giles 2024, Zenodo](https://doi.org/10.5281/zenodo.13970371) | CC-BY-4.0 | Candidato de densidade de fustes e riqueza por 100 fustes. CSV v1 tem 514 linhas/22 sítios, distinto das 448 parcelas/24 sítios do artigo. Protocolos misturam DAP, diâmetro basal e áreas aninhadas; o artigo/suplemento diverge sobre 1/3 sítios DAP10. Não incorporados quantis sem harmonização. |
| [MapBiomas, vegetação secundária](https://brasil.mapbiomas.org/downloads/assets-no-google-earth-engine/) | CC-BY, versão não explicitada na brochura oficial | Falta vincular pixels à coorte do projeto. A idade da vegetação existente não se aplica ao pasto que será restaurado; `sec_idade_media` atual vem do YbYrá, não do MapBiomas. A restauração futura começa na idade zero. |
| [Pacto pela Restauração da Mata Atlântica](https://doi.org/10.1177/1940082917697265) | Artigo CC-BY-NC-3.0, somente referência | Protocolo de medição; sem distribuição aberta por idade para gerar quantis. Não foram incorporados texto, código ou coeficientes NC. |
| [Rede de Sementes do Xingu](https://www.sementesdoxingu.org.br/restauracao-ecologica/) e [Freitas 2018](https://repositorio.unb.br/handle/10482/32438) | Licença aberta dos microdados não confirmada | Monitoramento e estudo de 72 áreas/1–10 anos; mistura de espécies semeadas e mudas iniciais não mede sobrevivência futura ou riqueza estabelecida. |

Os SHA256 dos dados candidatos baixados e as referências de licença ficam no YAML. **Pendências:** harmonizar
protocolos e parcelas, identificar árvores distintas de fustes, obter coortes abertas para plantio/semeadura,
vincular idade espacial à área restaurada e validar quantis. Não converter médias/desvios dos artigos nem metas
normativas em P10/P50/P90. A referência SMA/SP de regenerantes permanece separada, sem ser previsão para o Pará.

## Validação

Testes específicos de reserva, preço, salvaguardas, três opções, comparação, persistência e workflow.
Ruff global conferido. A validação local integrada à main `88860b6` teve 1.395 testes aprovados,
232 dependentes do ambiente ignorados e 1 falha histórica esperada. A continuação privada tem 78 testes específicos
aprovados e revisão independente, incluindo recusa de
Release público, origem divergente, alteração do conjunto de CARs e recálculo de fatia pronta. O motor e a amostra
originais foram conferidos em checkout separado. O CI com PostGIS, testes do front e workflows passou antes do merge do PR #49.
A exceção autorizada no teste do front foi validada em 24 testes; nenhum código de produção do front foi alterado.

A varredura de segredos com todos os ramos encontrou um falso positivo no PR #69, commit
`be05cee99ee060b5ca2c9e60d7b077d1fa2a51aa`: URL JDBC sem credenciais em `infra/docker-compose.keycloak.yml:28`.
A main incorporou em `.gitleaksignore` a exceção do fingerprint exato desse commit, arquivo, regra e linha;
a continuação usa essa exceção existente, sem ampliar a allowlist. A varredura de todos os ramos permanece ativa.
Nenhum valor de credencial foi exposto.

## Etapa seguinte 1 — diagnóstico das fazendas selecionadas

`raiz/restauracao_desbloqueio.py` gera JSON, CSV, Markdown e HTML com as travas das titulares e reservas,
sem misturar imóveis em espera ou áreas de mitigação na contagem do lote. Cada trava traz hectares restauráveis,
créditos P10/P50/P90, documento, conferência, responsável, fonte e marco de prazo. Dias permanecem nulos quando
não existe SLA comprovado. Requisitos do projeto e pendências do checklist são separados de sobreposições físicas;
referência documental recebida não libera uma trava. As linhas do quadro se sobrepõem e não são somáveis.

Terra documentada na classificação publicada compreende matrícula conferida ou concessão; `matricula_a_conferir`
não é terra pronta. A meta é repartida sem duplicação entre terra documentada, pendente e oferta faltante,
com excedente separado. O percentual inicial de homologação do edital não é tratado como título conferido sobre
o projeto inteiro. O relatório preserva a classificação do snapshot, sem autenticar documento por conta própria.

As métricas distinguem preço do cenário, custo ponderado pelos créditos, equilíbrio individual ponderado e
equilíbrio do fluxo agregado. A mediana de TIR é entre as fazendas selecionadas, sem ponderação; o caminho central
legado não se transforma em mediana de Monte Carlo e a sentinela `-100` não entra como taxa válida. Falta de métrica
não vira zero. O teste inclui fazenda de 0,01 ha e a preserva integralmente.

O relatório foi conferido contra os três pacotes históricos do Pará. `lote_relatorio.gravar_lote` também o inclui
nas próximas gerações. `raiz/restauracao_complementos.py` e `.github/workflows/desbloqueio-lote.yml` permitem
publicá-lo como complemento privado sem refazer cálculo financeiro ou otimização: verificam manifesto, SHA256,
tamanho, resumo, versão e cenário; mantêm a origem e publicam o manifesto derivado somente depois de conferir o
pacote recuperável. A geração não altera as previsões imutáveis de `restauracao-2026d+a84f9789`.

O workflow usa uma única cota na mesma fila CAS de quinze compartilhada com os estados. A única alteração no
motor é registrar esse workflow na lista de consumidores da fila, para que sua vaga não fique invisível aos
demais trabalhos. Nenhum processamento em curso é cancelado. Não houve mudança na API, MCP ou front.

Próximas entregas, na ordem solicitada: catálogo e lote nacional incremental; comparação ARR com emissões e
calibração apenas em pares comparáveis; sensibilidade com nova seleção; referências ecológicas com unidades,
fontes, licença e suporte amostral explícitos. Pesquisas preparatórias não autorizam tratar resultado projetado
como emissão observada nem riqueza padronizada de uma parcela como riqueza total da fazenda.

A varredura de todos os ramos do PR #86 apontou três hashes SHA-256 de código no commit
`e7074b4a170d745f34a4732072fcd954c0cad6f9`, linhas 3, 5 e 14 de `testes/mcp/sem_leitor_auditado.json`.
Os hashes foram recalculados a partir dos arquivos daquele commit e conferem. A exceção restrita já preparada
na frente de dados foi aplicada somente aos três fingerprints; nenhuma regra foi desativada nem arquivo MCP alterado.
