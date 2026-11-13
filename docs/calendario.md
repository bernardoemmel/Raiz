# Calendário da Raíz

O calendário reúne datas explicitamente publicadas por fontes oficiais. Cada evento traz tipo, data, prazo quando houver, UF, código IBGE do município quando inferível do CAR, fonte, link, instante de coleta, confiança de extração, situação e códigos do CAR vinculados. Não é agenda nacional completa nem substitui o edital: horários, fuso e condições continuam na fonte.

## Coleta e operação

A migração `0027`, posterior às migrações do título `0022` a `0025` e à `0026` da prospecção, cria o esquema `calendario`. Aplicar `uv run raiz banco migrar` antes da primeira coleta no servidor.

```bash
uv run raiz calendario coletar
uv run raiz calendario coletar --fontes djen,fomento_pr,icvcm,eudr
uv run raiz calendario importar dados/calendario/estado.json
uv run raiz calendario proximos --estado PA --dias 90
```

`coletar` usa o banco configurado, atualiza vínculos de imóveis e prepara avisos dos pedidos. Grava `eventos.json`, `eventos.ics` e `estado.json` em `dados/calendario/`, fora do git. `--sem-banco` permite gerar o snapshot público; `--anterior` conserva eventos e sequências da rodada anterior. `importar` aceita apenas fontes/links do manifesto, repõe rótulos institucionais e nunca confia em texto livre do arquivo. Sem `--fontes`, seleciona as fontes nacionais e os diários das UFs com ao menos um município processado no manifesto público `estados.json`; `--manifesto-estados` permite usar a cópia baixada pelo workflow. Não exige área ou quantidade mínima de fazendas.

O workflow `.github/workflows/calendario.yml` coleta diariamente às 06h11 de Brasília, publica os três arquivos no Release `calendario` e permite execução manual por fonte na branch padrão. Uma fonte totalmente indisponível deixa o job vermelho **depois** de salvar/publicar os resultados úteis das demais. O estado anterior só pode ser omitido se o Release ainda não existe; erro ao recuperá-lo aborta para não perder histórico. O site publica após essa coleta terminar. O cron do servidor deve rodar o comando com banco para alimentar API/MCP e pedidos; a publicação no GitHub, sozinha, não altera o Postgres.

As requisições têm quatro fontes em paralelo, máximo de visitas por fonte, limite de bytes por resposta, até 250 páginas por PDF e redirecionamentos limitados aos hosts oficiais do manifesto. Falhas transitórias de conexão, HTTP 429 e 5xx recebem tentativas limitadas com espera; `Retry-After` acima do orçamento interrompe a tentativa. HTTP 401/403 não provoca contorno nem troca para extração terceirizada. `FIRECRAWL_API_KEY` é opcional para falhas transitórias de HTML. Falhas ficam em mensagens fixas, sem texto da exceção ou do edital.

PDFs escaneados podem passar por Poppler e Tesseract no servidor, com limites de páginas, tamanho da imagem e tempo. Texto e imagens permanecem em memória; atingir um limite mantém a fonte parcial, sem usar um recorte incompleto como prova. O workflow instala Poppler, Tesseract e português. A extração de CAR exige formato literal: não converte letras ambíguas do OCR em números.

## Fontes e cobertura

O manifesto `raiz/calendario/fontes.yaml` registra os endereços oficiais, termos e limites de páginas. Não contém prazos codificados manualmente.

| Frente | Fonte inicial | Limite observado |
|---|---|---|
| Leilões rurais e penhoras | DJEN/CNJ, TRF2, TRT16, CAIXA, Banco do Brasil, Fomento Paraná, DOU e diários das UFs processadas | CAIXA usa CSV nacional filtrado por tipo rural e UF; BB e TRT16 têm cobertura parcial explícita. DJEN continua HTTP 403 neste ambiente. |
| Diários estaduais | AC, AP, BA, CE, GO, MA, MG, PA, PI, RN, RO, RR e TO na cobertura observada; MT disponível manualmente | Índices/APIs oficiais, PDFs e consulta HTML pública. Cadastro da fonte não prova disponibilidade da edição. UF nova sem adaptador gera erro de cobertura sem interromper as outras fontes. |
| Editais e crédito | BNDES Florestas, ProFloresta+, Fundo Amazônia, BNDES Créditos de Carbono | Só datas explícitas; página institucional sem prazo não cria evento. |
| Concessões florestais | Serviço Florestal Brasileiro e Ideflor-Bio | Cobertura inicial, sem declaração de cobertura de todos os estados. |
| Regulação e padrões | Fazenda/SBCE, Verra, ICVCM, SBTi e Comissão Europeia/EUDR | São consultas e prazos publicados, sem previsão de datas ainda não anunciadas. |

Os estados são `ok`, `parcial`, `erro` e `sem_data`. `ok` significa apenas que as páginas visitadas foram processadas; os limites de páginas, falhas ou atos com data não reconhecida aparecem como cobertura parcial. A coleta sem eventos não prova inexistência de editais. A busca dos diários é uma janela móvel de sete dias. Edições inteiras sem separação reconhecível de editais não são cruzadas com CAR para evitar vínculos falsos.

O extrator separa anúncios por blocos conhecidos, elimina repetição de data no mesmo ato e exclui datas de edição de leis citadas. Portais florestais só geram concessão quando o texto a identifica; pregões comuns de compra/serviço não herdam esse tipo. ICVCM usa os cartões do índice oficial, sem duplicar consultas por traduções, PDFs e fusos diferentes das páginas de detalhe. Testes guardam trechos oficiais de ICVCM, EUDR, SBTi e Fomento Paraná capturados em 12/11/2026. O trecho de Fomento conserva apenas os títulos e cláusulas de data/objeto; pessoas e outros elementos foram omitidos. O quadro EUDR usa linhas de aplicação, excluindo a entrada em vigor e a data histórica de corte de desmatamento. A confiança `0.85` é um rótulo heurístico de extração de data explícita, não uma probabilidade calibrada.

## Imóveis e avisos

O vínculo usa CAR explícito; na ausência dele, exige CNS **e** matrícula compatíveis com `titulo.matricula_imovel` e a rodada de `funil.vigente`, ou parcela SIGEF sobreposta ao imóvel vigente com área de interseção positiva. Matrícula sem CNS não determina um CAR. Vínculos derivados são revalidados ao importar/coletar o evento; uma matrícula corrigida ou removida da rodada vigente não mantém o CAR anterior. Não existe corte de tamanho da fazenda. Município é um código IBGE, sem nomes de pessoas ou inferência pelo endereço do titular. Evento sem chave suficiente fica `pendente` e aparece sem selo de leilão para um imóvel específico.

Nos leilões CAIXA, uma matrícula pública só pode complementar o CAR quando o PDF pertence ao mesmo identificador do imóvel e seu cabeçalho confirma a matrícula anunciada. A prova precisa identificar o próprio imóvel, com CAR único e UF compatível; CAR de confrontante ou texto ambíguo não serve. `car_fonte_url` guarda a fonte dessa prova, validada nos mesmos hosts do manifesto, e aparece na consulta pública/feed quando há CAR explícito. Editais de vários bens são separados antes da associação; número da primeira/segunda praça é conservado mesmo se apenas uma delas estiver publicada.

Avisos de leilão futuro e penhora entram nos pedidos ativos que contêm o CAR. Deduplicação usa evento, versão e imóvel; o painel fica disponível e email/WhatsApp ficam **simulados**, mesmo se outro módulo tiver enviador configurado. Nenhuma mensagem externa é enviada pela coleta ou importação.

Retificações na mesma publicação conservam o UID e aumentam `SEQUENCE`. Cancelamento sem repetir a data reaproveita o ato anterior quando há a mesma referência na mesma URL, a mesma referência e CAR em outra publicação, ou o mesmo permalink individual. Sem vínculo seguro, o coletor não adivinha qual ato cancelar e registra cobertura incompleta. Na mesma coleta, cancelamento prevalece sobre o edital original mesmo que a resposta ou a paginação o apresentem primeiro. Desaparecer da página não equivale a cancelamento. Histórico anterior é conservado, inclusive quando uma fonte falha.

## API, feed e MCP

`GET /eventos` é público e devolve `{eventos, total, coletado_em, fontes}`. Filtros: `tipo`, `estado`, `inicio`, `fim`, `cod_imovel`, `limite` (1–1000, padrão 100) e `deslocamento`. Estado inclui eventos nacionais (UF nula). O filtro público `cod_imovel` considera somente CAR explícito no ato publicado; não consulta os vínculos internos enriquecidos por matrícula/SIGEF. Período compara o prazo, quando presente, ou a data. CAR aceita pontuação de apresentação e é normalizado antes da consulta. Tipos:

```text
leilao_imovel, penhora, edital_bndes, profloresta, fundo_amazonia,
concessao, leilao_credito, sbce, verra, icvcm, sbti, eudr
```

`GET /eventos.ics` aplica os mesmos filtros, usa dias inteiros, UID estável, sequência e cancelamento RFC 5545. Não embute token. Acima de 20 mil eventos pede filtro mais restrito em vez de truncar silenciosamente.

`raiz.calendario.mcp.proximos_eventos(tipo, estado, dias, cod_imovel, limite)` usa a mesma consulta pública, somente leitura. A função do calendário ainda não está registrada em transporte MCP; o servidor pago em `/mcp` mantém seu catálogo próprio. O CLI `proximos` permite verificar a função imediatamente.

## Privacidade e validação

HTML/PDF são lidos somente em memória. Banco, snapshots, feed, histórico e avisos recebem campos fechados, identificadores de imóvel e links institucionais; nunca texto bruto, nome, CPF ou CNPJ. Links que contêm documentos pessoais ou parâmetros de nome/email/token são recusados, inclusive chaves percent-encoded. Os nomes de fonte vêm do manifesto, não dos editais. Objetos internos do parser PDF não são enviados ao log.

`eventos.json` e o feed excluem CNS, matrícula, SIGEF e CAR enriquecido, mantendo apenas CAR explícito no ato público. API, snapshot e MCP aplicam a mesma regra, também ao filtrar por CAR. Isso preserva o acesso pago à ficha da terra definido na main de 12/11/2026.

`estado.json` inclui os identificadores necessários ao vínculo no servidor. Quando gerado com banco, é arquivo administrativo e pode conter enriquecimento: não publicar esse arquivo em armazenamento aberto. O workflow público usa exclusivamente `--sem-banco`, portanto seu `estado.json` contém apenas campos extraídos da fonte pública, sem enriquecimento da base de imóveis. Os testes exercitam páginas gravadas, datas, isolamento entre editais, cancelamento, privacidade, erro de fonte, PostGIS, CAR/CNS/SIGEF, idempotência dos avisos, API, feed e consulta MCP.

## Verificação operacional de 12/11/2026

A primeira coleta completa visitou as 17 fontes dentro dos limites do manifesto. A auditoria encontrou comparação quadrática de árvores HTML, datas de leis citadas, pregões comuns classificados como concessão e repetição de datas no mesmo ato. A revisão independente também identificou uma contratação da SBTi indevidamente incluída e uma consulta ainda não reconhecida. Após corrigir esses pontos, as cinco fontes afetadas foram coletadas novamente. O resultado consolidado foi de **43 eventos, 6 futuros, em 102 páginas consultadas**; nenhum CAR explícito apareceu nessa rodada. A ausência de CAR não virou vínculo inventado. A revisão do número de edital também passou a distinguir cabeçalho de numeração interna do texto.

| Fonte | Páginas | Eventos | Situação |
|---|---:|---:|---|
| BNDES Florestas | 3 | 0 | sem_data |
| BNDES Créditos de Carbono | 6 | 12 | parcial |
| Diário de Justiça Eletrônico Nacional (CNJ) | 4 | 0 | erro |
| Diário Oficial de Mato Grosso | 6 | 0 | parcial |
| Diário Oficial do Pará | 4 | 0 | erro |
| Diário Oficial da União | 15 | 0 | parcial |
| Comissão Europeia (EUDR) | 6 | 3 | parcial |
| Fomento Paraná | 8 | 11 | parcial |
| Fundo Amazônia | 1 | 0 | sem_data |
| ICVCM | 1 | 2 | ok |
| Ideflor-Bio | 8 | 5 | parcial |
| BNDES ProFloresta+ | 3 | 0 | sem_data |
| Ministério da Fazenda (SBCE) | 8 | 0 | parcial |
| SBTi | 8 | 2 | parcial |
| Serviço Florestal Brasileiro | 1 | 0 | sem_data |
| Justiça Federal da 2ª Região | 12 | 0 | parcial |
| Verra | 8 | 8 | parcial |

O diagnóstico direto confirmou **HTTP 403 no DJEN** e **HTTP 500 no DOE PA**. Essas fontes não foram contornadas. A rodada preservou os dados úteis e saiu com código 1 para sinalizar as falhas. Os quatro `sem_data` significam ausência de prazo extraído nas páginas visitadas, sem afirmar ausência de editais ou cobertura completa.

Os arquivos JSON público, estado e feed passaram na varredura de CPF/CNPJ. Não houve nomes, texto bruto, envio de avisos, atualização de produção ou publicação de Release. Vínculos CAR/CNS/SIGEF, matrícula corrigida/removida, cancelamento independente da ordem, consulta pública sem enriquecimento e fonte indisponível estão cobertos pelos 28 testes do calendário com PostGIS.

A revisão independente confirmou os seis prazos futuros nos textos oficiais: consultas SBTi em 04/12/2026 e 06/12/2026; ICVCM em 04/12/2026; aplicação EUDR em 30/12/2026, 30/06/2027 e 30/12/2027. A contratação SBTi de 30/11/2026 foi excluída. Esses dias são evidência da rodada, não prazos fixados no código; a coleta seguinte volta às fontes.

## Continuação: fontes e PDFs (12/11/2026, Brasília)

O DOE PA foi recuperado pelo índice oficial `https://www.ioepa.com.br/pages/2026/` e pelo PDF
`https://www.ioepa.com.br/pages/2026/2026.11.12.DOE.pdf`: 137 páginas e texto legível, sem guardar o conteúdo bruto.
A confirmação final, já no leitor isolado, visitou índice e dois PDFs sem falha HTTP; zero eventos nessa amostra.
O limite de três visitas deixou a cobertura parcial, não completa.

Amapá respondeu pela API/PDF oficial em HTTP, sem credenciais. Ceará respondeu pelos cadernos oficiais da SEPLAG;
a capa enumera os volumes da mesma edição. Edições extras continuam fora dessa enumeração e a fonte fica parcial.
Goiás, Maranhão e Roraima tiveram leitura real de edição; RR usa o formulário público na mesma sessão.
Bahia oferece HTML público, mas PDF/FLIP exige cadastro: não se usa esse download. BA, MG e TO apresentaram
indisponibilidade de origem nesta verificação e não foram declarados recuperados.

TRT16 respondeu no índice e nos dois PDFs mais recentes. Um imóvel rural do edital de 16/09/2026 entrou como evento
histórico, matrícula identificada e CAR pendente. CAIXA teve páginas e matrículas individuais reais acessíveis;
os PDFs examinados eram escaneados e o OCR não confirmou CAR. Mesmo um CAR sintaticamente válido vindo só de OCR
permanece sem vínculo, sem matrícula/SIGEF para inferir vínculo e com cobertura parcial. Não foi inventado selo por CAR.

DJEN permanece bloqueado com **HTTP 403**, tanto nas consultas quanto no caderno público. O portal e a configuração
pública confirmam `https://comunicaapi.pje.jus.br/api/v1`; a documentação de homologação não é fonte de publicações
reais. Retentativas atendem falhas transitórias, não autorização negada. A recuperação do DJEN depende de uma resposta
pública válida no ambiente de execução; não há afirmação de que essa parte esteja concluída.

A revisão acrescentou isolamento de PDF/OCR em processos com 1 GiB de memória, 60 segundos de CPU, prazo de parede
e saída limitada durante a leitura. `stderr` é descartado. CAR de confrontante não comprova o imóvel, atos homônimos
no mesmo PDF conservam identidades distintas e segunda praça conserva UID quando a primeira desaparece.
Ao retirar uma matrícula/CAR ambíguo de um único evento já publicado, preserva o UID e corrige o registro vigente.
A releitura real dos oito documentos/páginas da Fomento Paraná confirmou 11 eventos sem criar quatro duplicatas
nem manter as matrículas descartadas. Uma correspondência com mais de um ato permanece sem resolução automática.
As regressões são sintéticas e verificam contratos; não constituem conjunto real de certidões nem medem acerto do modelo.

A sondagem posterior dos 13 diários, limitada a duas visitas por fonte, mostrou acesso oscilante: AP/CE/GO/MA
responderam dentro desse orçamento; AC/PI/RN/RO tiveram leitura incompleta; BA/MG/TO falharam; RR restringiu acesso;
o índice do PA também falhou nessa rodada. O coletor agora consulta diretamente os PDFs ordinários oficiais do PA
se o índice falhar, e lê a edição descoberta antes de consultar outra data. Isso não comprova a cobertura de extras.
A situação atual é sempre a do JSON da rodada, não uma promessa permanente de disponibilidade da fonte.
