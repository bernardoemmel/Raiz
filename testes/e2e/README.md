# Cena-alvo com Playwright

O teste sobe Vite, a API FastAPI real e as migrações reais em PostGIS; carrega
`dados/amostra` e passa pela interface até a reserva persistida. Confere o link
de uso único, pedido de **1 milhão de créditos no Pará**, três opções de lote,
busca de interesse, grupo pronto, Pix local de teste, rejeição do pagamento sem
token interno e atualização da tela após o pagamento.

Somente as entradas externas são simuladas: o envio de e-mail entrega o link em
arquivo temporário privado, as respostas dos donos entram pelo serviço de
interesse e a confirmação do Pix usa a rota interna de teste. Não há SMTP,
WhatsApp nem pagamento real. O servidor recusa credenciais da AbacatePay.

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
