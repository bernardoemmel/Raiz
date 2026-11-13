# Conferência dos contratos para agentes

O CI usa o **MCP Inspector oficial 2.15.0**, pela CLI, e **vacuum 0.40.1**. O npm lock de
`servicos/conferencia-agentes` fixa as dependências e suas integridades. O conjunto exige Node 24.22.1 ou posterior
na linha 24, ou 26.12.1 ou posterior. A auditoria de licenças inclui esse lock. O CI também confere o SHA-256 do
binário Linux x86_64 do vacuum: o instalador npm o baixa separadamente do pacote. O binário foi comparado com o
arquivo oficial da versão 0.40.1, cujo SHA-256 é `22d29c3184043eee53a6fc759fd4acc42095c030db9c4765199580bd85d20678`.

```bash
npm --prefix servicos/conferencia-agentes ci --no-audit --no-fund
uv run python -m scripts.verificar_protocolo_agentes
```

Esse comando gera o OpenAPI da **aplicação real em `/v1`**, confere que seu topo contém o resumo comum de até
8 KiB e executa as regras recomendadas do vacuum. Erros reprovam o CI; avisos de documentação ficam no relatório
e não são suprimidos. A aplicação administrativa em `/openapi.json` não é o contrato público dos agentes.

Com a pilha de teste e uma empresa sintética preparada, a conferência completa é:

```bash
uv run python -m scripts.verificar_protocolo_agentes \
  --openapi-url http://localhost:18000/v1/openapi.json \
  --mcp-url http://localhost:18000/mcp/ \
  --token-file .cache/agentes/token-mcp.txt
```

O token vem do Keycloak de teste, nunca de produção. O Inspector negocia a era moderna, exige o protocolo
2026-07-28, compara o resumo e o catálogo, verifica portabilidade dos esquemas com `--strict` e executa uma
consulta de disponibilidade. Acompanha o pedido pelo MCP até o worker concluir, antes de liberar a base para o
replay seguinte. Essa consulta consome um crédito sintético. A configuração temporária tem permissão
0600 e é removida ao terminar; token não entra em argumentos, logs nem relatório. Falha do Inspector reprova o CI.

## Manifesto do registro MCP

`infra/mcp/server.json.template` contém o nome `io.github.bernardoemmel/raiz`, o repositório e o transporte
Streamable HTTP. O esquema oficial de 11/12/2025 fica versionado em `infra/mcp/server.schema.2025-12-11.json`,
com SHA-256 conferido, para validar o manifesto sem rede. A versão do esquema do **registro** é independente
da versão 2026-07-28 do **protocolo**.

Sem domínio, o CI renderiza `.cache/protocolo-agentes/server.json` com `https://raiz.invalid/mcp/`, um endereço
reservado que não anuncia servidor. Para preparar o arquivo com o domínio escolhido:

```bash
uv run python -m scripts.verificar_protocolo_agentes --dominio https://api.DOMINIO-ESCOLHIDO
```

O comando exige a origem HTTPS e rejeita credenciais, parâmetros e caminhos; **não publica**. A publicação no
registro só poderá ocorrer depois de configurar domínio, TLS, servidor, OAuth e provar acesso real. Também será
necessário autenticar o publicador como proprietário do namespace GitHub. Não há workflow de publicação nesta entrega.

Fontes conferidas em 12/11/2026:

- [CLI oficial do Inspector](https://github.com/modelcontextprotocol/inspector/blob/main/clients/cli/README.md) e
  [teste em CI](https://github.com/modelcontextprotocol/inspector/blob/main/docs/cli-smoke-testing.md).
- [vacuum](https://github.com/daveshanley/vacuum) e [pacote oficial npm](https://www.npmjs.com/package/@quobix/vacuum).
- [Formato server.json](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/generic-server-json.md),
  [esquema versionado](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json) e
  [exigências do registro oficial](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/official-registry-requirements.md).

Inspector e esquema do registro: Apache-2.0, preservando contribuições anteriores MIT; documentação upstream CC-BY-4.0.
vacuum: MIT. As licenças completas acompanham os pacotes; esta documentação não copia exemplos de implementação upstream.

## CI sem modelo e campanha semanal

O job `agentes` do CI sobe a pilha real, cria uma empresa sintética, obtém um token por PKCE e executa o Inspector.
Também prepara os 24 cenários pela pilha real, confere descoberta, worker e os estados de erro/resultado esperados
com chamadas determinísticas; essa verificação é marcada como contrato e não mede o desempenho de um agente.
Na entrega inicial, a suíte Python confere o contrato do runner e do VCR com respostas sintéticas. **O replay
integral das 96 tentativas só entra no PR seguinte**, depois da primeira campanha real e da revisão dos cassetes;
esta entrega não contém um passo que pule silenciosamente uma gravação ausente. No replay, cassette ausente ou
requisição divergente falha sem acesso alternativo ao modelo. Seu relatório será evidência de regressão, não uma
nova medição de pass^4 de agente real.

O workflow `agentes-real.yml` roda às **06h de segunda-feira em America/Sao_Paulo** e admite execução manual.
Usa o snapshot fixo `claude-sonnet-5-5`, 24 tarefas e quatro sessões novas por tarefa. O segredo
`ANTHROPIC_API_KEY` precisa ser cadastrado em **Settings → Secrets and variables → Actions** no repositório.
Sem ele, a execução falha explicitamente antes de subir a pilha. O segredo é disponibilizado somente nas etapas
de conferência da sua presença e execução do modelo, sem passá-lo aos serviços de API, banco ou OAuth.

Os artefatos do Actions guardam os relatórios técnicos e de recursos. Não incluem `.env`, tokens, traces brutos
ou os cassetes da nova campanha. Mudanças aprovadas nos cassetes do CI são revisadas por PR, nunca sobrescritas
automaticamente por um workflow. Nenhum desses workflows publica no registro MCP ou contrata servidor.

A medição de recursos semanal ocorre **durante** a campanha: Docker amostrado a cada dez segundos até o agente
terminar, além do disco dos volumes e das imagens. O código de saída do agente é preservado; falha do medidor
também reprova o job. O maior valor amostrado não garante o pico entre amostras nem dimensiona a base nacional.
