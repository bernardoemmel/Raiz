# Identidade das empresas no MCP

O contêiner usa Keycloak 26.8.2 (Apache 2.0). O realm `raiz` exige Authorization Code com PKCE S256, aplica o perfil
`oauth-2-1-for-public-client` e desliga password grant, implicit e service accounts. O callback é uma URI exata,
configurada em `RAIZ_OAUTH_REDIRECT_URI`. Não use curingas. O MCP aceita JWT RS256 com audiência `RAIZ_MCP_RESOURCE`,
emissor `RAIZ_OAUTH_ISSUER` e acesso com validade curta; não aceita chave da API.

1. Defina as variáveis exigidas no compose, incluindo as senhas apenas no ambiente. `RAIZ_KEYCLOAK_URL` é a origem
   externa HTTPS; `RAIZ_OAUTH_ISSUER` é essa origem seguida de `/realms/raiz`. `RAIZ_MCP_RESOURCE` é a URL pública do
   MCP, sem barra final (por exemplo `https://api.raiz.exemplo/mcp`).
2. Suba `docker compose --env-file .env -f infra/docker-compose.keycloak.yml up -d`. O banco OAuth é separado.
   Mantenha 8180 acessível apenas ao proxy local. O proxy termina TLS e deve substituir os cabeçalhos X-Forwarded.
3. No console administrativo, vincule cada usuário à empresa já cadastrada com o atributo `empresa_id`. O atributo
   não é editável pelo usuário. Não ofereça seleção livre de empresa no formulário nem no token.
4. Atribua a role **de cliente** `raiz-api/admin_empresa` somente à pessoa administradora daquela empresa. Uma role
   global do realm não substitui essa atribuição. Cadastros e concessões precisam de revisão do operador.
5. `consultar` e `pedir` são os escopos padrão. `reservar` é opcional e também exige `conta_api.reservar_habilitado`,
   inicialmente falso. Só a rota administrativa autenticada permite alterar essa coluna. Solicitar o escopo ao
   Keycloak sozinho não habilita reserva; desligar a autorização no banco retira o escopo dos JWT ainda válidos.
6. Confira `/.well-known/oauth-protected-resource/mcp`: emissor, recurso e três escopos devem corresponder à instalação.

O import de realm só acontece na primeira criação. Mudanças futuras exigem import/migração administrativa deliberada;
o arquivo não altera automaticamente realms existentes. Não publique o console administrativo sem controle de acesso.
Nenhum cliente fictício, usuário, senha ou vínculo de empresa é criado pelo realm.

Fontes: [release](https://github.com/keycloak/keycloak/releases/tag/26.8.2),
[OAuth 2.1 e PKCE](https://www.keycloak.org/securing-apps/oidc-layers),
[metadados de recurso do MCP](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
