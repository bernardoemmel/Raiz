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

## Carga MCP real

O MCP OAuth dos PRs #45/#69/#72 está na main e o adaptador `testes/mcp/produto.py` o exercita com banco, emissor
JWKS e credenciais descartáveis. A carga exige manifesto que cubra exatamente `tools/list`; o corpus de agente
leitor continua pendente, conforme a seção de integração abaixo. Para um sandbox local já iniciado:

```bash
export RAIZ_MCP_TESTE_URL=http://127.0.0.1:8767/mcp/
export RAIZ_MCP_TESTE_PROTOCOLO=2026-07-28
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

O job MCP executa esse perfil real com as sete ferramentas, incluindo `consultar_ficha`. O CAR da amostra já foi
adquirido pela própria empresa mediante débito do crédito sintético da fixture; o GET passa pelos gates reais e
relê a ficha com saldo zerado, sem compra implícita. As demais ferramentas conservam a chave da mesma intenção
durante os replays. A aprovação de tempo/carga não equivale à aprovação do corpus de leitura de documentos, que continua explicitamente pendente.


## Integração disponível após #45/#69/#72

`testes/mcp/produto.py` agora inicia o MCP e a API reais com PostGIS local, JWT/JWKS descartáveis e logs sanitizados
ativos. `uv run python scripts/testar_mcp_ci.py` produz medições de todas as ferramentas e as duas fases Locust;
exige `RAIZ_BANCO_URL_MCP_TESTE` apontando ao banco local `raiz_mcp_teste`, que é apagado/migrado.
O fundador autorizou aviso específico quando faltar o agente leitor, somente depois de tempo/carga aprovados;
os relatórios não aprovam esse corpus. Com o leitor ligado, o corpus é obrigatório e qualquer falha reprova.
Veja `testes/mcp/README.md` para a pendência e a distinção entre tempo de resposta da
ferramenta e execução assíncrona do cálculo. A carga repete intenções idempotentes, sem pagamentos externos.

Ensaio local após #72, em 12/11/2026: sete ferramentas responderam pela integração real; a maior chamada isolada
foi `consultar_ficha`, em 0,262 s. A fase normal teve 157 requisições, zero falhas e máximo de 0,941 s; a saturação
teve 251 requisições, 152 respostas 429 esperadas, zero falhas e máximo de 1,748 s. Todas as ferramentas tiveram
sucesso nas duas fases. Não foi necessário mudar o teto próprio de leitura de fichas nesse ensaio.
Relatórios locais: `/tmp/raiz-mcp-sete-ferramentas/`. O runner retornou 1 exclusivamente pelo corpus pendente,
com `latencia=true`, `carga=true` e `corpus=false`; estes resultados não são aprovação do agente leitor.
