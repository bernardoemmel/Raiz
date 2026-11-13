# Medição das 24 tarefas no GitHub Actions

O workflow **Medição de agentes (24 tarefas)** (`medir-agentes.yml`) executa o
modelo Anthropic de verdade contra o MCP da Raíz. São 24 tarefas × quatro
sessões independentes = 96 tentativas, com julgamento em outra conversa. O
contrato e a meta continuam em [avaliação de agentes](avaliacao-agentes.md).
Testes locais com respostas simuladas verificam o runner; não são uma medição.

## Ativar e executar

1. No repositório, abra **Settings → Secrets and variables → Actions → New
   repository secret** e cadastre `ANTHROPIC_API_KEY`. O valor vai apenas ao passo
   que chama a Anthropic. Não coloque a chave em arquivo, variável pública ou chat.
2. Em **Actions → Medição de agentes (24 tarefas) → Run workflow**, escolha a
   `main` e informe o ID exato do modelo. O juiz pode usar outro ID; se vazio,
   usa o mesmo modelo em conversa separada, sem memória do agente.
3. Para o agendamento, variáveis opcionais `RAIZ_AVALIACAO_MODELO` e
   `RAIZ_AVALIACAO_JUIZ` escolhem os modelos. O padrão acompanha o modelo do
   projeto, `claude-sonnet-5-5`; o runner confere o ID pela API antes de gerar
   respostas. ID ausente/alias divergente não produz resultado aprovado.
4. A execução semanal ocorre **segunda às 06:00 de Brasília (09:00 UTC)**.
   Só existe uma campanha por vez; outra solicitação aguarda na fila.
5. Baixe o artefato `medicao-agentes-<run_id>-<tentativa_do_workflow>` na página
   da execução. Um workflow vermelho também publica o relatório, quando o
   runner do GitHub ainda consegue concluir o passo `always()`.

Não depende de reiniciar este chat nem de credenciais locais. O segredo da
Anthropic não é usado por PRs ou forks. O workflow não modifica Releases,
carteiras reais, reservas reais nem o site.

## Pilha e cenários

O Actions sobe PostGIS, Valkey e Keycloak em portas loopback. Migra um banco
modelo vazio e cria uma cópia descartável por tentativa; cada uma tem empresa,
conta, oferta e pedidos sintéticos. Nenhum dado do arquivo privado é baixado.
Cada tentativa também cria um realm OAuth próprio, autentica via Chromium com
Authorization Code + PKCE S256 e remove o realm ao terminar. A configuração de
identidade mapeia explicitamente `sub`, exigido pelo verificador da API.

O callback HTTPS de teste é interceptado no navegador, antes de qualquer acesso
à rede, e conferido por `state` e PKCE; não é um site externo. O template de
produção não perde políticas de autenticação. Tokens e credenciais sintéticas
trafegam em memória/pipes privados; nunca são publicados.

A API e o worker usam o código real. O processo de serviço recebe somente
configuração local permitida, sem chave Anthropic ou credenciais de produção,
e suas conexões são limitadas a loopback. O serviço de contato e o provedor Pix
não são ativados. O cenário 429 preenche o limitador real por leituras gratuitas
da conta imediatamente antes da primeira chamada do agente; essas chamadas
fazem parte da preparação da fixture, não de seu desempenho.

Antes do modelo, `scripts/verificar_pilha_avaliacao.py` confere OAuth, sete
ferramentas, execução do worker, 402, 429, preparação humana e idempotência. Essa
verificação faz acompanhamento explícito para testar a pilha, sem produzir
pontuação. Na campanha, só chamadas solicitadas pelo modelo são feitas: o
runner não consulta resultados em segredo nem amplia as ferramentas permitidas
pelo gabarito.

## Relatório e interpretação

- `relatorio.json`: pass^4, aprovação, chamadas proibidas, violações, total de
  passos, tempo, tokens, completude, hashes da configuração/gabarito e limitações.
- `metricas.json`: tempo e passos de cada tentativa; chamadas tentadas,
  autorizadas ou proibidas, erros, duração e hashes de argumentos/resultados.
- `execucoes.jsonl`: evidência fechada aceita pelo avaliador existente, incluindo
  todos os critérios julgados e todas as tentativas de ferramenta.

**pass^4 é a proporção de tarefas aprovadas nas quatro tentativas**, não a média
individual elevada a quatro nem a melhor das quatro. Uma chamada proibida conta
mesmo se o servidor a recusar. Ferramentas inventadas não executam código ou
acessam URLs; são registradas como tentativa proibida por identificador opaco.
O juiz não recebe autoridade para executar ações.

Uma tentativa do modelo que termina por limite de passos, chamadas, tamanho,
tokens ou tempo recebe todos os critérios falsos: encerramento sem resultado
completo é falha objetiva, não sucesso inferido. Erros de preparação, julgamento
inválido ou indisponibilidade do provedor tornam a campanha incompleta. Chave
ausente gera `motivo=segredo_ausente`, 96 tentativas não executadas e `pass4=null`.
Uma campanha incompleta nunca aprova a meta.

Limites padrão: 12 passos e 24 chamadas de ferramenta por tentativa, 300 segundos,
60 mil tokens por tentativa e quatro milhões por campanha, contando agente e
juiz; no máximo 2.048 tokens de saída por resposta. Há reserva conservadora do
orçamento antes de cada chamada e nenhuma repetição automática de erro da
Anthropic. O job tem limite adicional de 180 minutos. Isso limita o consumo,
mas **não é um preço fixo em reais**: a cobrança depende do modelo e dos tokens
reais. Para mudar limites, versionar a configuração e iniciar outra campanha.

O artefato contém apenas campos fechados e hashes. Respostas, prompts, argumentos
integrais, tokens e logs de contêiner não são publicados. O juiz examina os
traces brutos em memória; eles são descartados depois. Portanto, os hashes
permitem vincular os registros, mas o artefato sozinho não permite reconstruir
cada resposta para uma nova auditoria sem reexecutar a campanha.

## Limitações do contrato atual que a medição deve expor

Algumas tarefas permitem somente a ferramenta que submete o trabalho e proíbem
`acompanhar_contato`, embora o resultado seja assíncrono. O runner não preenche
essa lacuna: recibo `submitted` não conta como comparação ou faixa concluída.
Cancelar uma operação já em `working` devolve `input-required` para revisão,
enquanto o gabarito pede cancelamento confirmado. Essas divergências podem
reprovar tarefas e devem aparecer no relatório, sem mudar o gabarito para elevar
a nota. Corrigir o produto ou versionar o gabarito exige nova campanha.

## Reproduzir a verificação local sem gastar com modelo

Em checkout sem `.env`, depois de instalar as dependências travadas e Chromium:

```bash
docker compose -f infra/docker-compose.avaliacao.yml up -d --wait
uv run python -m scripts.verificar_pilha_avaliacao
uv run pytest -q testes/test_medicao_runner.py testes/test_avaliacao_agentes.py
docker compose -f infra/docker-compose.avaliacao.yml down --volumes
```

Para a campanha real use `uv run python -m scripts.medir_agentes --modelo ID_EXATO`,
com o segredo somente no ambiente. Os códigos de saída são `0` para meta aprovada,
`1` para campanha completa reprovada e `2` para incompleta/configuração inválida.
Não publique um relatório anterior como se pertencesse a uma nova execução.
