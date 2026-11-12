# Passagem do chat "Ficha da fazenda"

Atualização de 12/11/2026, branch `codex/dados-privados-e-prospeccao`.
PR desta entrega: https://github.com/bernardoemmel/Raiz/pull/72.
Entrega anterior integrada: [PR #52](https://github.com/bernardoemmel/Raiz/pull/52).

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

Durante o corte, os workflows antigos de motor, lote do Pará, publicação de dados
e vigilância foram pausados: uma execução com checkout antigo poderia republicar
conteúdo completo. Retomar somente depois do CI e da integração do publicador
protegido, usando os checkpoints preservados. CI e testes não foram interrompidos. O workflow do site também foi pausado
para manter o inventário de artifacts estável; o site já publicado permaneceu no ar.

## Preços e operação

`raiz/regras/padroes/precos.yaml` define pacotes de 1, 10 e 50 consultas, todos com
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
passaram em banco novo, com `0028` como revisão final.

A ficha visual integrada da main preserva mapa, Sentinel-2 e linha do tempo junto
com a comparação e o PDF. As rotas `/fichas/{car}/visual`, `/visual/satelite` e
`/visual/satelite.webp` também exigem sessão e desbloqueio da própria conta,
verificam reserva e retornam conteúdo privado sem cache público. A integração
HTTP/visual passou em 44 testes com PostGIS. A junção visual passou nos 201 testes
do front, 17 de geometria, build e todos os cenários de navegador. As melhorias de
acessibilidade e domínio configurável da main também são preservadas; nenhuma
oferta financeira estática é incluída no build aberto.

## Função compartilhada para API e MCP

A passagem `produto-e-regras.md` foi lida na branch do PR #45, onde estava disponível.
Ela exige conta empresarial, sinal, contrato, cobrança e limites do host, OAuth no
MCP e ausência de dados pessoais. O transporte corporativo não foi reescrito.

`raiz.prospeccao_servico.consultar_ficha(engine, cliente_id, codigo_car)` devolve o
mesmo DTO fechado usado pela rota HTTP. A identidade vem de autenticação, nunca
do corpo da ferramenta. O parâmetro opcional `desbloquear=True` pertence ao fluxo
explícito de compra da interface humana; a ferramenta só lê ficha já liberada.

`raiz.prospeccao_mcp.ferramentas()` fornece schemas de `consultar_ficha` e
`comparar_fichas`. `executar` exige contexto OAuth corporativo do host com escopo
`consultar` e callback de autorização dos detalhes, que aplica conta, sinal,
contrato, cobrança, estorno e auditoria. Sessão do navegador e chave REST não
substituem esse contexto. O host preserva seu envelope, erros RFC 9457 e tracing;
o adaptador retorna `content`, `structuredContent` e `isError`, sem transporte novo.
A integração de registro no servidor MCP corporativo continua com Produto e regras.

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
preços aprovados pelo fundador. Verificação local antes da última atualização da main: 1.053 testes Python
passaram, dois pulados e um xfail existente; mais 47 testes focados passaram após
proteger logs de URLs assinadas. Front: 161 testes, build, Pages, prospecção,
Lighthouse e cena-alvo com API/PostGIS reais passaram. Privacidade e 640 licenças
conferidas; Ruff, formatação e actionlint aprovados. O PR #72 concentra o resultado
do CI da revisão final; a integração exige todos os jobs verdes. As provas da
migração remota concluída estão acima e em `dados-publicados.md`.

A atualização da main também trouxe os retratos automáticos do aprendizado. Eles
seguem a mesma fronteira privada, inclusive os pacotes imutáveis e os recibos:
nenhum Release diário público de histórico por CAR pode ser criado. O alerta do
Gitleaks para uma URL JDBC histórica sem credenciais tem exceção restrita ao
fingerprint já revisado e integrado pela main, conforme `operacao.md`. O CI dessa revisão executou 1.174 testes com sucesso;
uma asserção antiga contava dois passos finais protegidos, mas agora existem
três. O teste foi corrigido para conferir a proteção de cada operação, e os
13 testes de transferência passaram. A suíte completa deve ser reconferida na
revisão final integrada.

Após a integração, reativar os cinco workflows pausados, atualizar as refs da fila
com `scripts/atualizar_fila_privada.py` e retomar as unidades interrompidas com o
commit protegido: BA-1 a BA-4, CE-1/2, PI-1/2 e RN-1, sem duplicar reservas ativas.
O lote do Pará tem retomada específica na main (`retomar-lote-para.yml`, PR #55):
a execução 43299409156 já foi iniciada, reutilizando dez fatias preservadas e
calculando só as cinco interrompidas, no privado e com motor/lockfile originais.
Não disparar também o lote genérico de quinze fatias. A compatibilidade do
orquestrador histórico com o armazém atual deve permanecer coberta nos testes.
O site deve ser republicado na main com os 22 assets básicos, sem depender dos
originais preservados.
