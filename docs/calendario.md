# Calendário da Raíz

O calendário reúne datas explicitamente publicadas por fontes oficiais. Cada evento traz tipo, data, prazo quando houver, UF, código IBGE do município quando inferível do CAR, fonte, link, instante de coleta, confiança de extração, situação e códigos do CAR vinculados. Não é agenda nacional completa nem substitui o edital: horários, fuso e condições continuam na fonte.

## Coleta e operação

A migração `0026`, posterior às migrações do título `0022` a `0025`, cria o esquema `calendario`. Aplicar `uv run raiz banco migrar` antes da primeira coleta no servidor.

```bash
uv run raiz calendario coletar
uv run raiz calendario coletar --fontes djen,fomento_pr,icvcm,eudr
uv run raiz calendario importar dados/calendario/estado.json
uv run raiz calendario proximos --estado PA --dias 90
```

`coletar` usa o banco configurado, atualiza vínculos de imóveis e prepara avisos dos pedidos. Grava `eventos.json`, `eventos.ics` e `estado.json` em `dados/calendario/`, fora do git. `--sem-banco` permite gerar o snapshot público; `--anterior` conserva eventos e sequências da rodada anterior. `importar` aceita apenas fontes/links do manifesto, repõe rótulos institucionais e nunca confia em texto livre do arquivo.

O workflow `.github/workflows/calendario.yml` coleta diariamente às 06h11 de Brasília, publica os três arquivos no Release `calendario` e permite execução manual por fonte na branch padrão. Uma fonte totalmente indisponível deixa o job vermelho **depois** de salvar/publicar os resultados úteis das demais. O estado anterior só pode ser omitido se o Release ainda não existe; erro ao recuperá-lo aborta para não perder histórico. O site publica após essa coleta terminar. O cron do servidor deve rodar o comando com banco para alimentar API/MCP e pedidos; a publicação no GitHub, sozinha, não altera o Postgres.

As requisições usam o HTTP já existente da busca documental, com quatro fontes em paralelo, máximo de páginas por fonte, 16 MiB por resposta, até 250 páginas por PDF e redirecionamentos limitados aos hosts oficiais do manifesto. `FIRECRAWL_API_KEY` é opcional, para o mesmo serviço hospedado usado pela busca documental. A API DJEN não usa esse fallback. Falhas ficam em mensagens fixas, sem texto da exceção ou do edital.

## Fontes e cobertura

O manifesto `raiz/calendario/fontes.yaml` registra os endereços oficiais, termos e limites de páginas. Não contém prazos codificados manualmente.

| Frente | Fonte inicial | Limite observado |
|---|---|---|
| Leilões rurais e penhoras | DJEN/CNJ, TRF2, Fomento Paraná, DOU, DOE PA e MT | A API pública DJEN respondeu HTTP 403 na verificação de 12/11/2026. Não houve contorno do bloqueio; seu parser tem teste do contrato JSON, não captura real de resposta. |
| Editais e crédito | BNDES Florestas, ProFloresta+, Fundo Amazônia, BNDES Créditos de Carbono | Só datas explícitas; página institucional sem prazo não cria evento. |
| Concessões florestais | Serviço Florestal Brasileiro e Ideflor-Bio | Cobertura inicial, sem declaração de cobertura de todos os estados. |
| Regulação e padrões | Fazenda/SBCE, Verra, ICVCM, SBTi e Comissão Europeia/EUDR | São consultas e prazos publicados, sem previsão de datas ainda não anunciadas. |

Os estados são `ok`, `parcial`, `erro` e `sem_data`. `ok` significa apenas que as páginas visitadas foram processadas; os limites de páginas, falhas ou atos com data não reconhecida aparecem como cobertura parcial. A coleta sem eventos não prova inexistência de editais. A busca dos diários é uma janela móvel de sete dias. PDF escaneado sem camada de texto não passa por OCR nesta entrega. Edições inteiras sem separação reconhecível de editais não são cruzadas com CAR para evitar vínculos falsos.

O extrator separa anúncios por blocos conhecidos. ICVCM usa os cartões do índice oficial, sem duplicar consultas por traduções, PDFs e fusos diferentes das páginas de detalhe. Testes guardam trechos oficiais de ICVCM, EUDR e Fomento Paraná capturados em 12/11/2026. O trecho de Fomento conserva apenas os títulos e cláusulas de data/objeto; pessoas e outros elementos foram omitidos. O quadro EUDR usa linhas de aplicação, excluindo a entrada em vigor e a data histórica de corte de desmatamento. A confiança `0.85` é um rótulo heurístico de extração de data explícita, não uma probabilidade calibrada.

## Imóveis e avisos

O vínculo usa CAR explícito; na ausência dele, exige CNS **e** matrícula compatíveis com `titulo.matricula_imovel` e a rodada de `funil.vigente`, ou parcela SIGEF sobreposta ao imóvel vigente com área de interseção positiva. Matrícula sem CNS não determina um CAR. Vínculos derivados são revalidados ao importar/coletar o evento; uma matrícula corrigida ou removida da rodada vigente não mantém o CAR anterior. Não existe corte de tamanho da fazenda. Município é um código IBGE, sem nomes de pessoas ou inferência pelo endereço do titular. Evento sem chave suficiente fica `pendente` e aparece sem selo de leilão para um imóvel específico.

Avisos de leilão futuro e penhora entram nos pedidos ativos que contêm o CAR. Deduplicação usa evento, versão e imóvel; o painel fica disponível e email/WhatsApp ficam **simulados**, mesmo se outro módulo tiver enviador configurado. Nenhuma mensagem externa é enviada pela coleta ou importação.

Retificações na mesma publicação conservam o UID e aumentam `SEQUENCE`. Cancelamento sem repetir a data reaproveita o ato anterior quando há a mesma referência na mesma URL, a mesma referência e CAR em outra publicação, ou o mesmo permalink individual. Sem vínculo seguro, o coletor não adivinha qual ato cancelar e registra cobertura incompleta. Na mesma coleta, cancelamento prevalece sobre o edital original mesmo que a resposta ou a paginação o apresentem primeiro. Desaparecer da página não equivale a cancelamento. Histórico anterior é conservado, inclusive quando uma fonte falha.

## API, feed e MCP

`GET /eventos` é público e devolve `{eventos, total, coletado_em, fontes}`. Filtros: `tipo`, `estado`, `inicio`, `fim`, `cod_imovel`, `limite` (1–1000, padrão 100) e `deslocamento`. Estado inclui eventos nacionais (UF nula). O filtro público `cod_imovel` considera somente CAR explícito no ato publicado; não consulta os vínculos internos enriquecidos por matrícula/SIGEF. Período compara o prazo, quando presente, ou a data. CAR aceita pontuação de apresentação e é normalizado antes da consulta. Tipos:

```text
leilao_imovel, penhora, edital_bndes, profloresta, fundo_amazonia,
concessao, leilao_credito, sbce, verra, icvcm, sbti, eudr
```

`GET /eventos.ics` aplica os mesmos filtros, usa dias inteiros, UID estável, sequência e cancelamento RFC 5545. Não embute token. Acima de 20 mil eventos pede filtro mais restrito em vez de truncar silenciosamente.

`raiz.calendario.mcp.proximos_eventos(tipo, estado, dias, cod_imovel, limite)` usa a mesma consulta pública, somente leitura. Está pronta para registrar em um servidor MCP; este repositório ainda não tem transporte/servidor MCP. O CLI `proximos` permite verificar a função imediatamente.

## Privacidade e validação

HTML/PDF são lidos somente em memória. Banco, snapshots, feed, histórico e avisos recebem campos fechados, identificadores de imóvel e links institucionais; nunca texto bruto, nome, CPF ou CNPJ. Links que contêm documentos pessoais ou parâmetros de nome/email/token são recusados, inclusive chaves percent-encoded. Os nomes de fonte vêm do manifesto, não dos editais. Objetos internos do parser PDF não são enviados ao log.

`eventos.json` e o feed excluem CNS, matrícula, SIGEF e CAR enriquecido, mantendo apenas CAR explícito no ato público. API, snapshot e MCP aplicam a mesma regra, também ao filtrar por CAR. Isso preserva o acesso pago à ficha da terra definido na main de 12/11/2026.

`estado.json` inclui os identificadores necessários ao vínculo no servidor. Quando gerado com banco, é arquivo administrativo e pode conter enriquecimento: não publicar esse arquivo em armazenamento aberto. O workflow público usa exclusivamente `--sem-banco`, portanto seu `estado.json` contém apenas campos extraídos da fonte pública, sem enriquecimento da base de imóveis. Os testes exercitam páginas gravadas, datas, isolamento entre editais, cancelamento, privacidade, erro de fonte, PostGIS, CAR/CNS/SIGEF, idempotência dos avisos, API, feed e consulta MCP.
