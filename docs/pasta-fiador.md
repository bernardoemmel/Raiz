# Pasta do banco fiador e do comprador

Implementação da rodada 12. A pasta parte do mesmo lote privado
conferido, produz duas apresentações e mantém a referência de cada campo. Não
contém nome, documento pessoal ou contato do proprietário. Os modelos Jinja
são internos, versionados; nenhuma rota aceita modelo, expressão ou código de
terceiro. Dados faltantes impedem a geração e aparecem no relatório de validação.

O catálogo inicial de campos é conservador e pertence à Raíz. Requisitos de um
banco específico podem ser incorporados como regras revisadas no repositório.
Isso não representa certificação nem envio no XML hipotecário MISMO/UCD.

Referências de projeto conferidas em 13/11/2026 (UTC):

- [Jinja](https://jinja.palletsprojects.com/en/stable/api/): BSD-3-Clause,
  `StrictUndefined` e escape automático.
- [Tabulator](https://github.com/tabulator-tables/tabulator): MIT, grade local
  dos campos já autorizados, sem exportação de contatos.
- [Uniform Closing Dataset](https://singlefamily.fanniemae.com/delivering/uniform-mortgage-data-program/uniform-closing-dataset):
  catálogo de campos, regras e relatório de falhas antes da entrega. A adaptação
  é para dados da terra e do lote, não para crédito hipotecário americano.
- [Price Paid Data](https://www.gov.uk/guidance/about-the-price-paid-data) e
  [Crossref](https://www.crossref.org/documentation/principles-practices/best-practices/versioning/):
  alterações tipadas e identificadores rastreáveis, preservando observações
  anteriores. Não se importa cadastro de transações ou conteúdo de terceiros.
- [DataCite](https://support.datacite.org/docs/versioning): versões de previsão
  com referências próprias ligadas à anterior. IDs internos da Raíz não são DOIs.
- [EDGAR Company Facts](https://www.sec.gov/search-filings/edgar-application-programming-interfaces):
  cada preço com moeda, unidade, período, natureza e documento de origem.

Regrid, CoStar, Agrotools, PitchBook e TTR são referências de produto/comercial,
sem cópia de seus dados. A amostra gratuita utiliza apenas o contrato público de
agregados e situação básica; histórico, exportação e alertas detalhados continuam
pagos. Os preços citados pelo fundador (Soli R$ 24,90; TerraCheck R$ 69,90 a 159,90;
FarmGeo R$ 279) são referências informadas, não preços conferidos para publicidade.
O diferencial a apresentar é crédito por método, nível de conferência do título
e composição do lote, com fontes e incertezas, sem prometer certificação ou emissão.

## Contrato e geração

`raiz/pasta_fiador/esquema.py` é o catálogo fechado. O lote é identificado por
pedido e opção (`barata`, `segura`, `compacta`); contém exatamente seus imóveis
principais atuais, inclusive pequenos. Cada imóvel exige área elegível positiva,
título com conferência concluída, garantia conferida, previsão por método e preço.
Ausência continua ausência: nunca é convertida em zero. Métodos alternativos sobre
a mesma área não são somados. P10 ≤ P50 ≤ P90, com período e versão do modelo.

Cada valor e seus metadados recebem `fontes`: ID do documento, página/campo e data
de referência. Documento conferido exige referência técnica, hash SHA-256, emissão,
conferência com fuso e validade ou declaração explícita de ausência de vencimento.
Referências não transportam texto de certidão, caminho de arquivo, URL privada ou
contato. Cada preço usa valor decimal exato, BRL/USD/EUR, unidade (ha, tCO2e ou lote),
início/fim, natureza `realizado`/`estimado` e documento do tipo preço.

A política `raiz/regras/padroes/pasta_fiador.yaml` substitui a necessidade de motor
Drools nesta pasta. YAML é lido como dados, de caminho interno fixo, sem expressão
executável ou regra enviada pelo cliente. Titularidade e garantia nunca são
dispensáveis. Documento complementar pode ser dispensado com motivo e documento
válido de autorização. Documento substituído mantém seu ID no histórico, aponta
para o sucessor do mesmo tipo e exige atualizar as fontes que ainda o citam.
Cadeia cíclica, sucessor ausente, revogado, não conferido ou vencido bloqueia entrega.

`validacao.campos` lista as referências campo a campo, incluindo unidade, natureza,
moeda, período, método e versão. `validacao.falhas` identifica campo, código e motivo.
O relatório é inspirado no controle de completude/proveniência do UCD; não é XML
MISMO e não declara aceite por banco específico. Nenhum envio automático é feito.

A exportação retorna um ZIP com `banco.html`, `comprador.html`,
`dados-conferidos.json`, `validacao.json` e `manifesto.json` com hashes dos arquivos e dos três modelos internos.
Os HTML têm estilos de impressão e podem ser salvos em PDF pelo navegador. A ficha
individual conserva seu PDF próprio. As duas apresentações Jinja usam o mesmo ID
de versão, assinatura, fontes e catálogo de documentos. Só os modelos locais da
Raíz são carregados; `SandboxedEnvironment`, `StrictUndefined` e escape automático
continuam obrigatórios. Modelos não recebem scripts, recursos remotos ou dados pessoais.
Todos os arquivos levam a marca por cliente e a linha-sentinela; as páginas HTML
incluem marca d'água fixa também na impressão. Não são anexadas certidões brutas.

## Versões e acesso

Migração **0035**, após 0034: pasta com ID estável por pedido/opção; versões anexadas
com tipo, motivo, antecessor, hash e relatório. Bloqueio no pedido e comparação do
antecessor impedem que duas retificações sobrescrevam a mesma base. UPDATE e DELETE
de versões e referências são bloqueados por trigger. Retirada cria nova versão,
sem apagar a anterior, e bloqueia exportação. Mudar os bytes de um documento exige
novo ID. A previsão mantém ID de série por pasta/CAR/método; mudança de conteúdo ou
fonte gera referência nova `urn:raiz:previsao-versao:UUID`, com `IsNewVersionOf` e
`IsVersionOf`. Correção só de preço conserva a referência da previsão inalterada.

Consultas e exportações exigem sessão do titular do pedido e acesso pago vigente a
todos os CARs daquela versão. Exclusividade de outra conta impede a leitura. O
histórico lista referências; abrir a versão antiga revalida seus próprios imóveis.
A validade documental é recalculada na leitura e na geração: relatório antigo não
mantém documento vencido pronto. Mudança da composição do lote exige retificação.
Só se exporta a versão atual. Leituras não debitam nem desbloqueiam fichas.

Rotas, no FastAPI existente, sem mudança do DTO global `consultar_ficha`:

- `GET /prospeccao/fichas/{car}/pastas`: conferência deste imóvel nos lotes da própria conta, aberta pela ficha individual.
- `GET /prospeccao/pastas/{pedido_id}/{opcao}`; `versao_id` opcional para revisão.
- `GET /prospeccao/pastas/{pedido_id}/{opcao}/historico` (até 100 versões recentes).
- `GET /prospeccao/pastas/{pedido_id}/{opcao}/exportar` (ZIP da versão atual).

A pasta é específica do pedido/cliente e não entra nos snapshots globais da terra,
no Release público, no site estático ou no MCP de outra conta. Recebe limites de
consulta/exportação e eventos do mesmo detector de raspagem. A grade Tabulator
carrega apenas o pacote autorizado: área elegível, estágio, nível do título,
documento, situação e validade. Sem módulos de download/clipboard/upload; exportar
passa pelo back-end. Troca de conta ou de opção cancela leituras pendentes e limpa
o conteúdo anterior. A tela é aberta pelo pedido, em `#/pedidos/{id}/pasta`.

## Operação interna

O operador confere os documentos e prepara um JSON conforme `Retificacao`
(`tipo`, `motivo`, `versao_anterior_id`, `dados`). O catálogo pode ser obtido com
`Retificacao.model_json_schema()`, sem inventar campos de banco. Não usar templates
recebidos, copiar conteúdo pessoal ou trocar dados ausentes por estimativas próprias.

```sh
uv run python -m raiz.pasta_fiador.operacao /diretorio-privado/pasta.json --relatorio /diretorio-privado/falhas.json
uv run python -m raiz.pasta_fiador.operacao /diretorio-privado/pasta.json --registrar --relatorio /diretorio-privado/registro.json
```

O segundo comando exige ambiente operacional com acesso ao banco. Não há rota de
importação pelo cliente. Rascunho válido no esquema pode ser registrado com
pendências, para acompanhamento, mas não exportado. Falhas de formato geram
relatório sanitizado campo a campo, com `pronto: false`; não reutilizam aprovação
antiga. Relatórios são criados com permissão 0600, sem conteúdo no log.

Amostra aberta: o link para o Pará na prospecção mostra agregados e situação básica
já públicos. Não reduz a cobertura aberta dos demais estados nem publica amostra
completa das camadas pagas. Histórico, exportação e alertas detalhados usam os
créditos já adquiridos; não foi criada cobrança oculta ou nova assinatura. Preços
continuam a definir pelo fundador e o Pix não foi ativado.
