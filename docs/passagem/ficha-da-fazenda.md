# Passagem do chat "Ficha da fazenda"

Entrega de 12/11/2026. Branch `codex/ficha-da-fazenda`.

## O que foi entregue

- Ficha de prospecção por CAR, separada da ficha do produtor. O contrato fechado
  de `raiz/imovel_dados.py::ficha_prospeccao` e `raiz/ficha_prospeccao_dados.py`
  permite apenas dados da terra: área, restauração, caminho e pendências,
  sobreposições, embargos, uso e perdas anuais, crédito líquido P10/P50/P90,
  TIR e risco. Não repassa atributos livres, nomes, documentos ou contatos do dono.
- Cada medida tem valor (ou `null`), unidade, fonte, data de referência, data de
  corte da carga e indicação de estimativa. A data de corte não substitui a data
  ausente da fonte. Captura bruta não vira crédito líquido e intervalos ausentes
  não são inventados. O crédito contratual e o anual permanecem separados.
- Busca nacional em `raiz/busca.py`, restrita à cobertura efetivamente processada:
  UF, município, bioma, área, caminho e situação da terra, crédito e risco. O
  filtro de crédito usa P50 líquido **total do contrato**. A paginação limita a
  resposta, sem limitar as somas da seleção. Fazendas pequenas e assentamentos
  continuam na base, com sugestões de agrupamento por município e bioma; isso
  não comprova vizinhança nem viabilidade do lote.
- Rotas de cliente em `raiz/prospeccao_api.py`, usando a sessão individual já
  existente. O token operacional da API não serve como sessão de cliente.
- Carteira e compras de créditos de consulta (distintos de créditos de carbono)
  em `raiz/prospeccao_acesso.py`, migração `0026`. Um crédito pago libera um CAR
  para uma conta; releituras não debitam novamente. Trava de carteira, movimentos
  e chaves únicas protegem confirmação e débito contra repetição e concorrência.
- Compra Pix via integração AbacatePay existente; confirmação consulta o provedor
  e aceita somente cobrança de produção. Simulação ou corpo enviado pelo cliente
  não liberam créditos. Compras ficam persistidas para recuperar depois de fechar
  a tela. Valores e quantidades vêm do catálogo do servidor.
- "Pedir contato" cria um pedido idempotente em `negocio.prospeccao_contato`.
  Não consulta contato pessoal, não cria onda de contato e não envia mensagens.
  Fazenda reservada por outro cliente fica invisível também nas releituras.
- Tela `#/prospeccao` e nova ficha pelo link de CAR. Reutilizam navegação para o
  município no mapa, sem reescrever componentes de mapa. Ficha completa não usa
  CSV ou simulação no navegador. Sem API configurada, ficam apenas agregados.
- Publicação do site e servidor de desenvolvimento deixam de distribuir listas
  por CAR, fichas, CSV individuais e geometrias individuais. Mantêm resumos,
  pontos agregados por município, limites geográficos e mapa-base. A ficha antiga
  por CAR também passa pelo acesso pago; a ficha estática do produtor deixa de
  reconstruir detalhes públicos até existir autenticação própria do produtor.

## Contrato HTTP

| Método e rota | Acesso e efeito |
|---|---|
| `GET /prospeccao/planos` | Aberto; catálogo configurado e disponibilidade do pagamento |
| `GET /prospeccao/agregado` | Aberto; dimensões regionais/terra/risco, sem CAR ou intervalos numéricos |
| `GET /prospeccao/busca` | Sessão; filtros completos e resumos de até 50 fazendas por página |
| `GET /prospeccao/saldo` | Sessão; créditos de consulta e número de fichas liberadas |
| `POST /prospeccao/compras` | Sessão; `{plano, chave_idempotencia}`, preço definido no servidor |
| `GET /prospeccao/compras` | Sessão; últimas compras da própria conta |
| `GET /prospeccao/compras/{id}` | Sessão; confere Pix e credita uma única vez |
| `GET /prospeccao/fichas/{car}` | Sessão e desbloqueio prévio; 402 se não liberada |
| `POST /prospeccao/fichas/{car}/desbloquear` | Sessão; debita um crédito e retorna a ficha; retry não duplica débito |
| `POST /prospeccao/contatos` | Sessão e ficha liberada; `{codigo_car}`, registra pedido interno |

O agregado público suprime valores para grupos com menos de cinco fazendas;
somas exigem cinco valores conhecidos. Grupos pequenos continuam na busca
autenticada. Não se aceita CAR ou faixa numérica no agregado aberto para isolar
uma ficha. A busca autenticada tem até 200 páginas; o total não é truncado.
P10/P90 somados no agregado não são quantis simulados de um lote. A busca usa
a classificação de terra persistida; a ficha pode derivá-la de evidências já
medidas, identificando essa origem. Até 100 grupos são retornados, com indicação
explícita quando há outros grupos na seleção.

Os limites são persistidos no Postgres e compartilhados entre processos: 60
consultas por minuto por conta, 30 buscas por minuto, 100 tentativas de
desbloqueio por dia, 20 pedidos de contato por minuto, cinco compras por minuto
e 15 conferências de pagamento por minuto. O aberto limita 60 consultas por
minuto por endereço da conexão (guardado como hash). Resposta 429 informa
`Retry-After`; dados autenticados usam `Cache-Control: private, no-store`.
Não se confia em `X-Forwarded-For` arbitrário: configurar proxy confiável no ASGI
ao implantar para que o endereço represente o cliente real.

## Configuração de operação

1. Aplicar migrações do banco até `0026` antes de subir a API.
2. Configurar `RAIZ_PROSPECCAO_PLANOS` como lista JSON com objetos contendo `id`,
   `nome`, `creditos` (inteiro positivo) e `valor_rs` (positivo, duas casas).
   Não há preço comercial presumido. Sem catálogo ou chave de produção, a tela
   informa indisponibilidade; não simula compra paga.
3. Configurar `RAIZ_ABACATEPAY_CHAVE` no servidor, sessão/e-mail já existentes e
   CORS. Nenhum segredo pode entrar no front ou no git.
4. Configurar `VITE_RAIZ_API` para ligar as telas à API. Não compilar token
   operacional `VITE_RAIZ_API_TOKEN` em publicação pública.
5. Arquivos gerados por `raiz ficha lote` são saída administrativa: guardar em
   armazenamento privado. A nova ficha paga é montada no servidor e não é
   exportada no build estático.

## Limitações e continuação

- **O Release histórico `dados` continua público**, inclusive CSV e derivados
  anteriores. Este PR fecha a distribuição individual pelo site e protege as
  novas rotas; não torna privados arquivos já publicados nem impede reconstruir
  números a partir das fontes públicas. O executor nacional ainda usa o Release
  como armazenamento. Para tornar também os derivados confidenciais, coordenar
  com o chat de dados uma migração para pacotes cifrados ou armazenamento privado,
  mantendo só agregados abertos. Não apagar pacotes nem interromper a coleta.
- A cobertura nacional descreve a abrangência da busca, não a conclusão do
  processamento de todos os CARs. Ausências de série, estimativa ou data são
  mostradas explicitamente. A TIR e os créditos são estimativas existentes do
  modelo, sem garantia comercial.
- Não há campanha de contato nesta entrega. O próximo serviço consome os pedidos
  internos, com os controles e termos previstos na cena-alvo.
- O acesso privado do produtor ao próprio imóvel precisa de fluxo separado;
  reabrir JSON público por CAR contornaria o acesso pago de prospecção.

## Verificação

Validação local desta entrega: suíte completa com PostGIS, 674 testes aprovados,
dois ignorados e um xfail já existente; após as últimas correções, os 92 testes
dos quatro módulos de prospecção passaram. Front: 83 testes aprovados, 13
ignorados, build dos dois aplicativos aprovado. Chromium confirmou bloqueio,
desbloqueio, pedido de contato, recuperação de compra, recompra, troca de sessão
e largura de 360 px, usando API controlada de teste. O script reproduzível é
`front/scripts/testar-prospeccao.mjs` (`npm run test:prospeccao`). Sem arquivos
`front/geo` neste ambiente, não foi possível conferir o mapa real completo no
navegador; os testes de publicação usam geometrias de teste.

Testes unitários e com PostGIS cobrem contrato sem dados pessoais, ausência de
dados, filtros combinados, exclusividade, agregados, concorrência de compra e
desbloqueio, idempotência, limites e fronteira HTTP. Front verifica contratos e
publicação sem arquivos individuais. Rodar as mesmas checagens do CI:

```bash
uv run ruff check raiz testes scripts migracoes
uv run ruff format --check raiz testes scripts migracoes
RAIZ_BANCO_URL_TESTE=postgresql+psycopg://raiz:raiz@localhost:5432/raiz_teste uv run pytest -q
uv run raiz privacidade varrer
uv run python scripts/checar_licencas.py
RAIZ_BUILD_DADOS=0 front/scripts/construir-site.sh
cd front/globo && npm test
```
