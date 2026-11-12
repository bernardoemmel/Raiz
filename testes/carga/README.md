## Carga da API (entregue e executada)

Usamos Locust 2.47.0, MIT (https://pypi.org/project/locust/2.47.0/ e https://github.com/locustio/locust/blob/2.47.0/LICENSE). Nenhum k6 ou pacote de serviço Locust Cloud foi adicionado. O Locust é dependência de desenvolvimento travada no uv.lock.

```bash
# Banco criado previamente no PostGIS local, exclusivamente para este ensaio.
export RAIZ_BANCO_URL_CARGA=postgresql+psycopg://raiz:raiz@localhost:5432/raiz_carga
uv run python -m testes.carga.rodar --resultado resultado-carga
```

O comando apaga e migra **somente banco local com sufixo `_carga`**. Recusa `raiz`, `raiz_teste`, `_e2e` e destinos remotos. Usa a amostra versionada do repositório, API/FastAPI e consultas PostGIS reais; credenciais, token e chave pessoal são descartáveis, configurações `.env`/integrações externas ficam fora do servidor do teste. Nenhum WhatsApp, Pix, modelo remoto ou e-mail é acionado. O token fica apenas no ambiente do subprocesso e não aparece nos argumentos nem nos relatórios.

A carga consulta `/saude`, `/municipios` e `/municipios/1504950/imoveis` com seis usuários concorrentes. Duas fases de dez segundos: orçamento alto para medir respostas reais sem 429, depois orçamento de seis chamadas por janela de dois segundos para demonstrar saturação. Essa janela curta é injetada somente no servidor de teste; a configuração do produto não é alterada. Ao final, o teste provoca outro 429, espera exatamente o Retry-After mais 100 ms e exige retorno 200.

Reprova se houver menos de 20 requisições por fase, rota sem resposta válida, erro de conteúdo/status, qualquer resposta de 5 s ou mais, 429 na fase normal, ausência de 429 na saturação, Retry-After ausente/inválido ou ausência de recuperação. Os 429 esperados contam como controles atendidos, sem mascarar os outros erros. O teste de regressão também demonstra que um servidor que apenas bloqueia tudo não passa.

`--usuarios N --segundos N` permite ampliar o ensaio no servidor local. O perfil do CI é uma verificação curta de desempenho e dos controles; **não é estimativa de capacidade máxima nem SLA de produção**. O CI publica somente os JSON agregados, sem corpos, tokens, IPs, nomes ou contatos. Logs do servidor são locais e não devem virar artefato público.

Execução local em 12/11/2026:

| Fase | Requisições | Falhas | 429 esperados | Maior resposta |
|---|---:|---:|---:|---:|
| Normal | 70 | 0 | 0 | 2,864 s |
| Saturação | 385 | 0 | 355 | 1,276 s |

As três rotas tiveram respostas válidas nas duas fases. A recuperação observou 429 com `Retry-After: 1`, seguido de 200 após a espera. Relatórios locais em `/tmp/raiz-resultado-carga/`. As 33 regressões do contrato de carga e transporte MCP passaram.

## Carga MCP (estrutura pronta; bloqueada pelo produto)

Dono da dependência: **chat Produto/regras**. A main não contém servidor MCP. O PR #45 retirou sua implementação antiga até concluir OAuth; o servidor retirado não foi copiado para simular cobertura. A carga abaixo exige servidor MCP real local, token OAuth descartável e manifesto de argumentos que cubra exatamente o inventário `tools/list`. Sem isso, o comando falha explicitamente. Nenhuma execução do MCP do produto nem latência/carga de suas ferramentas é alegada nesta entrega.

Depois que o chat dono entregar o sandbox sem ações externas:

```bash
export RAIZ_MCP_TESTE_URL=http://127.0.0.1:8767/mcp
# Definir RAIZ_MCP_TESTE_TOKEN por variável secreta local, sem gravá-lo no repositório.
export RAIZ_MCP_TESTE_CASOS=/caminho/privado/casos-mcp.json
export RAIZ_CARGA_FASE=normal
export RAIZ_CARGA_RELATORIO=/tmp/carga-mcp-normal.json
uv run locust -f testes/carga/locust_mcp.py --headless --users 6 --spawn-rate 6 --run-time 10s --only-summary
```

Formato do manifesto compartilhado com a suíte de latência:

```json
{"ferramentas": {"nome_da_ferramenta_real": {"argumentos": {}}}}
```

Use o conjunto completo de ferramentas realmente publicadas, IDs e dados descartáveis; preparar/criar/reservar/cancelar só pode operar dentro desse sandbox. O protocolo padrão é `2025-06-18`; `RAIZ_MCP_TESTE_PROTOCOLO` permite definir a versão que o servidor realmente suporta. O handshake deve negociar exatamente essa versão. O cliente valida initialize/initialized, sessão, paginação, IDs JSON-RPC, JSON ou SSE incremental; erro HTTP, `isError`, inventário vazio/incompleto ou resposta inválida reprovam. A sessão não registra resposta, texto do documento ou credencial.

Repita com `RAIZ_CARGA_FASE=limite` e orçamento baixo configurado pelo servidor do sandbox, usando outro arquivo de relatório. Essa fase exige ao menos um 429 com Retry-After positivo (até 60 s) e ao menos uma resposta válida de cada ferramenta; a fase normal recusa qualquer 429. O Locust aplica deadline de 4,9 s por chamada MCP, além do portão de tempo <5 s. O ensaio de latência separado usa deadline de relógio, independente do timeout de inatividade HTTP.

O job MCP completo só deve ser habilitado junto do servidor OAuth, seus dados descartáveis e os casos de todas as ferramentas. O CI atual executa as regressões do transporte e dos critérios de auditoria; isso não é aprovação de um MCP inexistente.
