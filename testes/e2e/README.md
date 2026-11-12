# Cena-alvo com Playwright

O teste sobe Vite, a API FastAPI real e as migrações reais em PostGIS; carrega
`dados/amostra` e passa pela interface até a reserva persistida. Confere o link
de uso único, abertura da conta paga com CNPJ sintético e três créditos de teste,
recusa **403** antes do sinal e contrato e redirecionamento **307** do caminho
antigo para `/v1`. Uma pessoa aceita o contrato, gera sinal e recarga e confirma
somente os Pix locais de teste. Então o cenário continua com o pedido de
**1 milhão de créditos no Pará**, já selecionado no formulário, e três opções
de lote. O botão de contato permanece desabilitado na tela, sem disparar pedido.
As etapas posteriores de busca de interesse, grupo pronto e Pix da reserva são
exercitadas pela API do servidor de teste, com atualização da tela após pagamento.
A assinatura Ed25519 do recibo é verificada com a chave pública da API; também são
conferidos o QR, o vencimento e a ausência de exclusividade antes do pagamento.

Somente as entradas externas são simuladas: o envio de e-mail entrega o link em
arquivo temporário privado, as respostas dos donos entram pelo serviço de
interesse e a confirmação do Pix usa a rota interna de teste. Conta, contrato,
sinal, recarga, cobrança por chamada e saldo passam pelos serviços reais da API;
não há liberação direta no banco nem desativação dos limites. O teste confere a
rejeição da confirmação de pagamento sem o token interno. Não há SMTP, WhatsApp
nem pagamento real. O servidor recusa credenciais da AbacatePay.

A fixture completa a amostra com polígonos arbitrários e evidências sintéticas de cobertura e verificação
territorial, registradas pelos serviços de salvaguardas. As validações reais continuam ativas; não se infere ausência
de sobreposição pela falta de uma camada. Esses polígonos e documentos existem somente no banco descartável do E2E
e não representam imóveis ou revisões reais. As chaves do cofre e do recibo são efêmeras, geradas ao iniciar o servidor.

As etapas humanas rodam em sequência; se a leitura final da lista atingir o
limite de 30 chamadas por minuto da empresa, o teste aguarda o `Retry-After`
antes de repetir. Esse limite permanece ativo durante todo o cenário.

Preparação, a partir da raiz:

```sh
uv sync --frozen --all-extras
npm --prefix front/globo ci
cd front/globo
npx playwright install --with-deps chromium
RAIZ_BANCO_URL_TESTE=postgresql+psycopg://raiz:raiz@localhost:5432/raiz_e2e npm run test:e2e:api
```

Crie antes o banco descartável `raiz_e2e` em um PostgreSQL com PostGIS. O teste
recusa banco remoto ou nome que não termine em `_e2e`, pois desfaz e reaplica
todas as migrações. Esse banco deve ser separado do `raiz_teste` usado por pytest.

O teste não depende de dados do Release, mapas externos ou dados de produção.
O token interno é aleatório e só vale no servidor local do teste. Traces ficam
desligados para não publicar links e tokens; screenshots só saem quando há
falha e usam os dados de teste. A caixa postal temporária é apagada ao terminar.

O cenário verifica as três opções na interface, sem afirmar cobertura do mapa
nacional na API: `fonte-api.ts` pede `/geo/brasil/*`, enquanto a API existente
aceita somente códigos municipais numéricos nessas rotas. Além disso, a fonte
de mapas/dados ainda requer o token interno, separado da sessão do cliente.
Essas integrações maiores constam na passagem de qualidade e segurança.

Os scripts visuais anteriores continuam disponíveis em `npm run test:e2e`.
Eles verificam a amostra no navegador e precisam de `front/geo` previamente
gerado; não substituem o cenário com API e banco reais.
