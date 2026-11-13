# Passagem do chat "Ficha da fazenda"

Atualização de 13/11/2026 (UTC). Rodada 12 implementada na branch
`codex/pasta-fiador`, com integração da main `3a73879` e da continuação
`codex/ficha-compromissos-versoes`.
PR desta continuação: [#93](https://github.com/bernardoemmel/Raiz/pull/93), aguardando CI e merge.
Entregas anteriores integradas pelos [PR #72](https://github.com/bernardoemmel/Raiz/pull/72)
e [PR #80](https://github.com/bernardoemmel/Raiz/pull/80), commit `bea53bd`.
Entrega anterior integrada: [PR #52](https://github.com/bernardoemmel/Raiz/pull/52).

## Rodada 12: pasta do fiador e comprador

Implementada na branch `codex/pasta-fiador`, sobre a continuação do PR #93.
Contrato e operação em [docs/pasta-fiador.md](../pasta-fiador.md). Serviço privado
novo `raiz/pasta_fiador/`, migração 0035, YAML próprio e grade Tabulator 6.7.1 MIT.
Duas apresentações Jinja 3.1.6 BSD do mesmo retrato, fontes por campo, preços
completos e validação antes de gerar. Modelo externo e campos de pessoa/contato
são recusados pelo contrato. Não são copiados dados de concorrentes.

A pasta só fica pronta com garantia, titularidade, área, previsão e preço
conferidos. Documentos vencidos/dispensados/substituídos têm tratamento explícito;
a exportação revalida datas, composição atual, conta, desbloqueios e exclusividade.
Retificação não sobrescreve: ID da pasta e da série permanece; versão de previsão
recebe referência nova ligada à anterior. Triggers impedem UPDATE/DELETE.
ZIP contém banco/comprador em HTML imprimível, dados, validação e hashes, todos
marcados por licença. Não inclui certidão bruta. A ficha individual mantém seu PDF.

Acesso pela tela do pedido, sem reescrever mapa ou API. A amostra do Pará usa só os
agregados/CAR básicos públicos; demais estados abertos continuam disponíveis.
O DTO global `consultar_ficha` e a ponte MCP permanecem compatíveis: pasta é dado
do pedido/cliente e não contamina snapshots globais da terra.

Validação local: 76 testes de pasta/API/PostGIS passaram, cobrindo
concorrência, imutabilidade, troca de documento, fonte/validade, preço incompleto,
proibição de contato/modelo e isolamento entre contas. O CLI também invalida um
relatório antigo quando a entrada seguinte falha, sem ecoar valores. A suíte
completa passou em 2.462 testes, com um xfail conhecido de TIR e o caso original
do Pará separado para o job que dispõe do snapshot privado. Os dois testes de
mídia inicialmente pulados passaram após instalar Takumi e executar com PostGIS.
Depois de incorporar a main, build e 275 testes do front passaram;
170 testes focados de pasta, API, pedidos, certidões e vigilância também passaram.
Chromium desktop 1440 e celular 360 passaram
com teclado, axe, bloqueio por pendência, exportação e troca de sessão. Capturas
sintéticas em `/tmp/raiz-pasta-fiador-final`; o CI publica o artefato `pasta-fiador`.
A regressão da prospecção no Chromium também passou após a integração.
Ruff/formatação, privacidade (1.063 arquivos), licenças (859 pacotes, nenhum
problema), Gitleaks (444 commits) e empacotamento dos modelos/YAML passaram.
CI verde e merge continuam sendo condições da entrega, sem cancelar workflows.

## Continuação: terra comprometida, versões e proteção

A ficha ganha `terra_comprometida`, `versao_ficha` e `o_que_mudou`. O mesmo serviço
continua atendendo interface, REST e MCP. Os detalhes permanecem pagos e privados;
não há novos campos exclusivos no Release público ou em arquivos estáticos do site.

- Compromissos: evidências territoriais versionadas, cruzamento com o CAR, união
  das áreas para evitar soma duplicada e fonte/data/certeza por evidência. Um
  catálogo sem polígono não confirma compromisso do imóvel. Programas estaduais
  de REDD+ entram como contexto, inclusive os já cadastrados em `geo.redd_programa`.
  Ausência ou falha de cobertura não significa terra livre. Coleta e limitações
  reais das fontes estão em `docs/terra-comprometida.md`.
- Versões: a carga preserva o estado antes e depois, incluindo imóveis removidos.
  O conteúdo é imutável e deduplicado; voltar de A para B para A gera nova
  observação sem duplicar a versão A. A última leitura pertence à conta e só
  avança após resposta/renderização concluída. Comparação e PDF mantêm esse cuidado.
- Avisos: buscas monitoram mudanças da terra e entrada/saída de filtros e dos
  lotes da própria conta. O job não altera a última leitura do cliente. Detalhes
  dos avisos continuam exigindo desbloqueio e visibilidade; nenhuma reserva ou
  lote de outra conta é revelado. Não envia e-mail ou WhatsApp nesta entrega.
- Cobertura: `raiz prospeccao atualizar-base` descobre as UFs no manifesto privado;
  `reindexar` atualiza os derivados após mudança de fontes, mesmo sem CSV novo.
  Falhas da carga não avançam o checkpoint. O fluxo existente de sincronização
  e vigilância local chama os mesmos hooks. A agenda Compose também atualiza a
  base e confere buscas a cada 15 minutos. Não recalcula o motor do Pará.
- Exportações: PDF com marca d'água em cada página e linha-sentinela; JSON e CSV
  com a mesma marca pseudônima, separada das medidas da terra. A marca não inclui
  nome, documento ou contato. Sem chave do servidor a exportação retorna 503;
  a leitura normal da ficha continua independente da chave de marcação.
- Proteção: tentativas bem-sucedidas e recusadas entram no detector persistido
  de volume/diversidade, sequência de CAR e paginação. O alerta é indício para
  análise, deduplicado e com regras versionadas; licenças de dados autorizadas
  não recebem alerta por navegação bem-sucedida em volume. Correções de falha
  posterior à renderização preservam a trilha e reavaliam o alerta.

Migrações desta continuação: **0032** (fontes/compromissos) → **0033** (versões e
avisos) → **0034** (marcas e proteção), após a 0031. As chaves
`RAIZ_PROTECAO_CHAVES` e `RAIZ_PROTECAO_VERSAO` ficam só no servidor; a rotação
preserva as versões antigas para rastreio. A consulta operacional usa
`raiz prospeccao alertas-protecao` e `rastrear-marca`.

Rotas adicionais autenticadas: `GET /prospeccao/fichas/{car}/historico` e
`GET /prospeccao/fichas/{car}/exportar?formato=json|csv`. O PDF mantém sua rota.
Todos os formatos passam pelo mesmo desbloqueio, exclusividade e limites.

O catálogo passa a propor **por ficha (1 crédito), por lote (10) e assinatura
mensal (50)**. As quantidades/ciclo são propostas e os preços permanecem nulos,
com “a definir pelo fundador”. Assinatura não pode ser vendida como um pacote
avulso; permanece fechada até haver gestão real de ciclos. O simulador
`raiz prospeccao simular-receita` calcula receita por cliente/mês e ano, carteira,
consumo e margem quando os custos são informados, sem persistir hipóteses ou
chamar o Pix. Ver `docs/precos-e-receita.md`.

A medição usa o workflow único `.github/workflows/agentes-real.yml`, integrado
pelo PR #85: manual e segunda às 06:00 de Brasília, 24 tarefas × quatro tentativas,
com `ANTHROPIC_API_KEY` apenas no Actions. A conciliação mantém seu runner, Compose,
OAuth real, juiz, evidências sanitizadas e gabarito v2. Não adiciona segunda campanha
semanal. Este PR garante também artefato de diagnóstico se a preparação falhar,
e upload explícito dos arquivos conferidos que estão dentro de `.cache`.

A execução 43341704532 chamou Claude e publicou o artefato 14000228551. Concluiu
35 de 96 tentativas e parou ao julgar `liberacao_pendente`, tentativa 4: a citação
da resposta omitiu marcadores Markdown e falhou na conferência literal. O relatório
permanece incompleto (`aprovado=false`); não há pass^4 válido. A evidência da campanha
deve ser preservada, e qualquer correção do juiz exige nova campanha integral.
Este PR inclui `julgamento-independente-v2`: instrução explícita sobre Markdown
e uma única nova conversa quando a citação é inválida, com consumo e tentativas
registrados. Não repete nota válida nem flexibiliza a verificação literal.
Os 39 testes do runner/juiz passaram, incluindo falha repetida e nota negativa.
Ver `docs/medicao-agentes-actions.md`. A pilha de produção não foi implantada.

Validações locais antes da conciliação: 2.227 testes Python aprovados e uma falha
exclusiva da referência estadual sem snapshot privado; 230 testes do front;
navegador/celular/axe; integração PostGIS de marcas, histórico e rollback. O teste
estadual exige o snapshot privado preparado pelo job `referencia_para`; não se
substitui por fixture pequena. O CI completo é obrigatório antes do merge.
Após conciliar a main: 223 testes focados aprovados, mais 11 da agenda/pilha;
Ruff e privacidade aprovados; 857 pacotes auditados sem licença proibida.

## Publicação aberta e arquivo privado

O contrato aberto agora permite agregado por município/UF e CAR com situação
básica (`apto`, `com_pendencia`, `nao_apto`) e geometria sem atributos pagos.
Mapa, busca estática, download, Vite e build usam somente `publico_basico` v1.
A ficha do produtor também não pode reconstruir dados pagos com CSV público.
A lista positiva e a supressão de agregados pequenos estão em
`raiz/executor/publicacao_aberta.py`; nenhum imóvel pequeno é descartado.

O arquivo completo usa token de ambiente e Release privado ou draft autenticado.
O destino preparado é `bernardoemmel/Raiz`, draft `dados-privados`, ID 443383695:
**nunca publicar esse draft**. Repositório privado também é suportado. O guard
confere a privacidade em cada operação; leitura usa o endpoint autenticado de
assets, não URL aberta. O executor grava o completo antes da projeção pública;
os checkpoints e versões completos continuam disponíveis para retomada.

O inventário inicial encontrou 40 assets públicos, cerca de 1,21 GB. Todos os
Releases publicados são varridos, incluindo arquivos fora do manifesto. A cópia
privada é rebaixada e comparada por SHA-256; o download anônimo deve responder
404. Só depois os IDs originais são substituídos ou removidos. Provas e snapshots
imutáveis ficam privados. Arquivos, contratos, comandos e resultado operacional
estão em [dados-publicados.md](../dados-publicados.md).

Migração do Release concluída no Actions 43288984765: 40 originais preservados,
39 canônicos privados e 22 assets básicos públicos (181.847.053 bytes).
O Actions 43289212685 preservou e retirou mais 18 artifacts, e 33 caches de dados
antigos foram descartados. Caches de dependências e evidências de testes ficaram.
A leitura autenticada real confirmou o manifesto completo com 12 UFs. Prova
privada `corte-f53e946687c4f244-concluido-d25320df8bcce9a9.json`.

Durante o corte, motor, lote do Pará, publicação de dados, vigilância e site
foram pausados para impedir republicação por checkouts antigos. Os cinco workflows
foram **reativados após o merge com CI verde**. A fila recebeu o commit protegido
`88860b6`; as reservas ativas foram preservadas. A rodada 43305564503 retomou
BA-1 a BA-4, CE-1/2, PI-1/2 e RN-1. RN-2 também foi desbloqueada na fila, pois sua
execução havia sido cancelada durante o mesmo corte. O planejador confirmou o
arquivo privado antes de iniciar o preparo dos insumos.

## Preços e operação

`raiz/regras/padroes/precos.yaml` define as três modalidades propostas acima, todas com
`valor_rs: null` e **a definir pelo fundador**. Não há preço comercial inventado.
`RAIZ_PIX_MODO=teste` é o padrão, mesmo se houver chave. Catálogo provisório não
abre venda. Produção exige catálogo aprovado, ativação explícita e credenciais.
O webhook valida segredo, assinatura, cobrança e valor no provedor; a carteira
continua idempotente. Nada foi implantado ou vendido nesta entrega.

O passo a passo de banco, migrações, servidor, chaves, assinatura do webhook,
conciliação, proxy e CORS está em [operacao.md](../operacao.md). O adaptador Pix
v1 existente exige conferência de compatibilidade da conta antes da ativação.

## Ficha, comparação, PDF e buscas salvas

A ficha continua um DTO fechado de dados da terra em
`raiz/ficha_prospeccao_dados.py`: fonte, unidade, data de referência, data de corte
e indicação de estimativa em cada medida. Ausência permanece `null`; data de
carga não substitui data da fonte. Nunca nome, CPF ou contato do dono.

- Comparação de duas a cinco fichas já liberadas. Todas são autorizadas antes
  da resposta; nenhuma compra ocorre implicitamente.
- PDF gerado no servidor com a mesma ficha, lista positiva em todos os níveis,
  fontes/datas e ausências. Sessão, pagamento, reserva e limite são reavaliados.
- Até 20 buscas salvas por conta (migração `0031`, após `0030` da plataforma de agentes). O primeiro snapshot é silencioso; CAR novo que
  passar pelos filtros gera aviso no painel, uma única vez. Avisos não liberam
  ficha e respeitam reserva de outra conta. Excluir busca remove seu histórico.
- `raiz prospeccao verificar-buscas` deve rodar após cargas e periodicamente no
  servidor, conforme operação. Não há envio de e-mail ou WhatsApp nesta função.
- A comparação, avisos, seleção e respostas da conta anterior são descartados
  quando a sessão muda. O download PDF usa autenticação e não URL pública.

| Método e rota nova | Contrato |
|---|---|
| `POST /prospeccao/comparar` | `{codigos_car: [2 a 5 CARs]}` → `{fichas: [...]}` |
| `GET /prospeccao/fichas/{car}/pdf` | PDF privado, mesma liberação da ficha |
| `GET /prospeccao/buscas-salvas` | Lista somente da conta autenticada |
| `POST /prospeccao/buscas-salvas` | `{nome, filtros}`; snapshot inicial sem avisos |
| `DELETE /prospeccao/buscas-salvas/{id}` | Exclusão somente do titular da busca |
| `GET /prospeccao/avisos` | Cursor `depois`, `limite` até 100; novidades sem dados pagos |
| `POST /prospeccao/avisos/{id}/ler` | Marca leitura de aviso da própria conta |
| `POST /pagamentos/prospeccao/abacatepay` | Webhook assinado e reconferido no provedor |

As rotas anteriores de saldo, compra, desbloqueio e pedido de contato permanecem.
Uma consulta paga libera um CAR para uma conta; releitura não debita novamente.
Pedir contato só registra pedido na Raíz, sem consultar ou enviar contato pessoal.
Limites persistem no Postgres entre processos: 60 consultas/minuto, 30 fichas/minuto,
10 comparações/minuto, 5 PDFs/minuto, 100 tentativas de liberação/dia. HTTP 429 inclui
`Retry-After`; respostas privadas têm `Cache-Control: private, no-store`.

A busca autenticada também respeita a fronteira paga: crédito, risco, caminho
detalhado e restauração ficam ocultos até a liberação daquele CAR, inclusive nas
somas. Os totais informam quantas fichas liberadas contribuíram; a ordenação por
CAR não revela ranking financeiro. Filtros avançados exigem pagamento real
comprovado e continuam descobrindo imóveis novos. Eles revelam pertinência à
faixa escolhida, sem entregar a medida exata; não fazem cobrança adicional.
CAR combinado com filtro avançado exige código completo já liberado. A mesma
habilitação vale ao salvar e ao reavaliar buscas; saldo arbitrário ou Pix de teste
não habilitam filtros pagos.

A integração das telas de lote da main preserva os comparadores e mapas, mas
rejeita qualquer snapshot financeiro antigo no build público. No retorno de
pedidos, valores por CAR também exigem liberação da própria conta; `ficha_liberada`
distingue bloqueio de ausência, e a projeção remove campos inesperados. Totais,
interesse, reservas e cálculo persistido foram preservados, sem cobrança nova.
A integração das telas, antes da nova ficha visual, passou em 186 testes do front, build, Pages, prospecção,
cena-alvo e Lighthouse, preservando também o calendário recém-integrado.
Onze testes de pedidos com PostGIS e 76 testes da integração de fichas e migrações
passaram em banco novo, então com `0028` como revisão final; buscas salvas foram renumeradas para `0031`
na integração posterior da API corporativa, preservando as migrações `0028` a `0030` da main.

A ficha visual integrada da main preserva mapa, Sentinel-2 e linha do tempo junto
com a comparação e o PDF. As rotas `/fichas/{car}/visual`, `/visual/satelite` e
`/visual/satelite.webp` também exigem sessão e desbloqueio da própria conta,
verificam reserva e retornam conteúdo privado sem cache público. A integração
HTTP/visual passou em 44 testes com PostGIS. A junção visual passou nos 201 testes
do front, 17 de geometria, build e todos os cenários de navegador. As melhorias de
acessibilidade e domínio configurável da main também são preservadas; nenhuma
oferta financeira estática é incluída no build aberto.

## Função compartilhada para API e MCP

A passagem `produto-e-regras.md` e o servidor real dos PRs #45/#69 foram integrados.
O MCP oficial registra `consultar_ficha`, com OAuth e escopo `consultar`, e usa a
ponte existente para `GET /v1/fazendas/{CAR}/ficha`. Conta empresarial, sinal,
contrato, limites e auditoria do host continuam obrigatórios.

`raiz.prospeccao_servico.consultar_ficha(engine, cliente_id, codigo_car)` devolve o
mesmo DTO fechado usado pela rota HTTP. A identidade vem de autenticação, nunca
do corpo da ferramenta. O parâmetro opcional `desbloquear=True` pertence ao fluxo
explícito de compra da interface humana; a ferramenta só lê ficha já liberada.

Essa operação é uma **releitura de ficha já adquirida**, sem tarifa adicional,
consumo dos testes corporativos ou desbloqueio implícito. Sem liberação daquele
CAR pela própria conta, devolve 402. A análise corporativa de R$ 1.500 permanece
produto separado. REST e MCP preservam fontes, datas, `null`, cache privado,
exposição para controle de raspagem e limites compartilhados com a prospecção.

O adaptador Python `raiz.prospeccao_mcp` permanece disponível para hosts internos
que forneçam contexto OAuth e autorização corporativa; não abre servidor alternativo.
Comparação de fichas continua na API autenticada da prospecção; somente
`consultar_ficha` foi acrescentada ao catálogo MCP corporativo nesta integração.

## Validação e limites reais

Testes focados cobrem leitura paga, concorrência, isolamento, reserva, ausência de
PII, PDF, comparação, snapshots, webhook e catálogo provisório. O smoke do Pages
confere situação básica e filtros, CAR/IBGE/nome, geometrias sem campos pagos,
Range, zoom e zero 404. O smoke de prospecção verifica comparação, PDF, busca
salva/aviso, preço indefinido, troca de conta e tela de 360 px com API de teste.

A cobertura nacional significa capacidade de buscar todos os estados processados,
não processamento completo do país. Estimativas não garantem emissão ou retorno.
Os dados brutos de fontes públicas permanecem públicos nas respectivas origens.
A implantação do servidor e a venda real dependem do roteiro operacional e dos
preços aprovados pelo fundador.

Validação final do PR #72 no [CI 43303447583](https://github.com/bernardoemmel/Raiz/actions/runs/43303447583):
os seis jobs passaram, com **1.626 testes Python aprovados**, uma ausência conhecida
do conjunto real completo do Pará e um xfail já documentado da TIR. A integração
MCP foi verificada com o SDK oficial; o E2E cobriu conta paga, pedido no Pará e
aprovação humana com Pix simulado. Foram conferidos 655 pacotes sem licença
proibida, Ruff, privacidade e Gitleaks.

Front: 213 testes e dez de configuração de publicação passaram, junto de Pages,
prospecção, calendário, cena-alvo, aprovação humana, axe e Lighthouse. Nas cinco
telas móveis, desempenho ficou entre 98 e 100 e acessibilidade em 100. O build
com os dados públicos reais passou: 365 municípios com desenho, 712.601 registros
básicos, nenhum CSV com coluna paga, nenhuma ficha completa estática; 1.596 arquivos,
cerca de 175 MB. Nenhum domínio real foi configurado.

Os retratos automáticos do aprendizado também ficam privados, inclusive pacotes
imutáveis e recibos. Os passos finais do motor conferem a proteção do checkout
antes de publicar, guardar cache ou continuar a fila.

As duas tentativas iniciais de republicação do site (43305357204) pararam na
mesma falha de rede ao baixar Rondônia, após processar o pacote maior do Pará.
O mesmo build real já havia passado localmente. A correção faz até três tentativas para falhas de transporte e HTTP
transitório. Pacote inválido, JSON malformado, 404 e colunas fora do contrato
continuam sendo erros; não há alternativa com arquivos legados ou privados.
A correção passou em 226 testes do front, incluindo 19 cenários locais de download
(conexão/corpo interrompidos, HTTP transitório, limite, 404 e conteúdo inválido).

O lote do Pará tem retomada específica na main (`retomar-lote-para.yml`, PR #55):
a execução 43299409156 concluiu, reutilizando dez fatias preservadas e
calculando só as cinco interrompidas, no privado e com motor/lockfile originais:
144 municípios e 345.870 imóveis no conjunto privado.
Não disparar também o lote genérico de quinze fatias. A compatibilidade do
orquestrador histórico com o armazém atual deve permanecer coberta nos testes.
O site foi republicado na main pela execução 43311812890, com os 22 assets
básicos e sem depender dos originais preservados. O download de Rondônia
precisou da segunda tentativa e concluiu. Foram verificados no endereço público
os arquivos básicos e os 404 dos antigos caminhos de ficha, imóvel e certidão.

### Continuidade da medição em 13/11/2026 UTC

Campanha `43344990197`: 64/96 sessões; agente e juiz recusaram o cenário seguinte
no provedor. Artefato preservado, sem pass^4 completo. Tratamento explícito de
`refusal` permite terminar as demais sessões sem contornar o bloqueio; julgamento
indisponível reprova a campanha e deixa pass^4 nulo, com limite inferior separado.
O CI do commit `f259b18` aprovou Python, front, referência privada original do
Pará, Compose, E2E, segurança e licenças; o único problema foi falso positivo
histórico da URL JDBC sem credenciais, com fingerprint específico documentado.
Nenhum workflow foi desligado ou cancelado nesta entrega.

A campanha `43349391767` também concluiu 64/96: a recusa do agente produziu resposta
vazia e o juiz respondeu com citações vazias, rejeitadas pelo esquema. O juiz v4
não reenvia desafios recusados ao juiz e isola julgamentos inválidos por tentativa,
sempre como indisponíveis (pass^4 nulo; limite inferior separado; aprovação falsa).
Não aceita citação vazia e não troca modelo, instrução ou regra para obter aprovação.
