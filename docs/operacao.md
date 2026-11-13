# Operação: como saber na hora quando algo parou

## Ficha: fontes, versões, cobertura e rastreio

Antes de iniciar esta continuação no servidor, aplique `uv run --env-file .env raiz
banco migrar` até a ponta atual (0035 nesta entrega). A API, o sincronizador e os
jobs precisam usar o mesmo PostGIS. As migrações 0032–0034 guardam fontes e
compromissos privados, versões/observações da terra, baselines das contas, marcas
de exportação e detecção de varredura. Não publicar esses dados no site ou em
artifacts abertos do Actions.

Com `RAIZ_DADOS_PRIVADOS_URL` e `RAIZ_DADOS_PRIVADOS_TOKEN` no ambiente do servidor:

```bash
uv run --env-file .env raiz prospeccao atualizar-base
uv run --env-file .env raiz prospeccao coletar-compromissos
uv run --env-file .env raiz prospeccao coletar-compromissos --fonte verra --limite-verra 25
uv run --env-file .env raiz prospeccao verificar-buscas
```

`atualizar-base` lê o manifesto privado inteiro, descobre UFs novas e carrega
somente o que mudou. `--ufs PA,RO` restringe uma intervenção manual; não usar uma
lista fixa no job nacional. O mesmo fluxo do `raiz vigiar` preserva o estado
antes/depois da carga e refaz compromissos quando as fontes mudam. Falha na
carga ou no processamento posterior deixa o checkpoint pendente para a próxima
volta. Não é necessário recalcular o motor para preparar a ficha.

Na pilha Compose, a agenda executa `atualizar-base` e `verificar-buscas` a cada
15 minutos, com retomada após falha e arquivos `.env`/espelho privados. Fora da
pilha, configure uma única agenda com trava de processo. A coleta de compromissos
pode rodar semanalmente; a fase Verra é explícita para controlar o tráfego e
pode ser repartida com `--limite-verra`. Para continuar uma coleta parcial,
`--retomar-desde AAAA-MM-DD` pula projetos Verra persistidos com sucesso desde
esse dia UTC. Uma rodada nova sem esse argumento revisita os registros e pode
identificar retiradas. Não tratar um checkpoint antigo como dispensa permanente
de atualização. As fontes disponíveis e limites da cobertura estão em
[terra-comprometida.md](terra-comprometida.md).

`reindexar` refaz os derivados quando o catálogo de fontes ou os programas
estaduais cadastrados mudarem, sem executar o motor. `--forcar` permite uma
conferência completa. Um retorno `pendente` ou uma fonte indisponível exige
acompanhar a próxima tentativa; não significa que a terra esteja livre.
O sincronizador não publica dados pagos e nunca usa o pacote público reduzido
como substituto do arquivo completo. A implantação e os agendamentos deste
servidor não foram executados no ambiente de desenvolvimento.

Para habilitar **exportações** (PDF/JSON/CSV), configure no cofre/ambiente:

- `RAIZ_PROTECAO_CHAVES`: objeto JSON de versão para segredo aleatório de ao menos
  32 bytes. Não reutilize segredos de teste nem coloque o valor em variável `VITE_`.
- `RAIZ_PROTECAO_VERSAO`: chave ativa desse objeto. A rotação exige versão nova;
  mantenha as antigas para conferência e preserve o registro privado das marcas.
- `RAIZ_PROTECAO_REGRAS`: opcional, caminho privado do YAML de limiares e retenção.

Sem chave, a exportação retorna 503; a leitura autenticada normal continua
funcionando. A marca é um identificador pseudônimo, não o nome ou documento do
cliente ou do dono. A sentinela é explicitamente administrativa: não é uma
fazenda fictícia nem modifica hectares, créditos, TIR ou séries históricas.
Ela permite rastrear uma cópia; não impede captura de tela ou remoção manual.

```bash
uv run --env-file .env raiz prospeccao alertas-protecao
uv run --env-file .env raiz prospeccao alertas-protecao --apenas-ativos
uv run --env-file .env raiz prospeccao rastrear-marca 'MARCA_ENCONTRADA_NA_COPIA'
uv run --env-file .env raiz prospeccao limpar-eventos-protecao
```

Esses comandos são administrativos e exigem acesso ao ambiente privado do
servidor. Os alertas registram regra, versão, janela, métricas e reavaliação;
são indícios para análise e não prova de abuso. Uma licença de dados aprovada
preserva o uso autorizado em volume. A retenção padrão dos eventos brutos é de
90 dias; marcas e alertas auditados são preservados. O detector não envia
mensagens externas nem muda automaticamente a licença comercial.

## Pilha API/MCP, OAuth e processamento

A pilha `infra/docker-compose.agentes.yml` sobe PostGIS, banco separado do Keycloak, Keycloak 26.8.2,
Valkey, migração, API/MCP no mesmo processo, worker e agenda. Todos usam o código e as dependências travadas do
mesmo checkout. A imagem final roda como usuário sem privilégios, com sistema de arquivos somente leitura;
`dados/` e os bancos têm volumes persistentes. Não inclui publicação de domínio, compra de VPS ou ativação de Pix.

### Teste local descartável

Com Docker Engine, Compose **2.24.4 ou superior** e Python 3.12:

```bash
python3 scripts/pilha_agentes.py teste
```

O comando gera `.env.agentes-teste` com permissões `0600` e segredos aleatórios, constrói a imagem, sobe as
bases e aplica as migrações antes de iniciar API e worker. Repeti-lo conserva os segredos e os volumes. As fontes ficam congeladas na imagem; `/app/proveniencia.json`
registra seus hashes e os rótulos Docker identificam a revisão e se o checkout estava alterado. A API fica
em `http://localhost:18000`, MCP em `/mcp/`, Keycloak em `http://localhost:18180` e PostGIS na porta local `15432`,
base `raiz_agentes_teste`. Os endereços só escutam loopback. O realm mantém Authorization Code/PKCE S256, sem
password grant para agentes; a instrumentação cria somente identidades e empresas sintéticas por Admin API.
O override compartilha a rede da API com o Keycloak para validar o emissor `localhost` sem exceção de segurança
no código de OAuth. Em produção são contêineres de rede independentes e URLs HTTPS.

API, MCP, fila e banco são reais. Pix fica obrigatoriamente em teste; SMTP e credenciais externas não são
herdados do host. A agenda exercita seu ciclo sem coletar a internet nem enviar avisos no modo de teste.
O modo `--desenvolvimento` monta fontes do checkout somente para depuração e é recusado pelo runner de campanhas
reais. A chave Anthropic pertence ao runner fora dos contêineres: não entra na imagem, API, worker ou arquivo de teste.

```bash
python3 scripts/pilha_agentes.py medir --teste --amostras 12 --intervalo 5 \
  --saida dados/operacao/recursos-agentes.json
python3 scripts/pilha_agentes.py parar --teste
```

`parar` conserva os volumes. Não use `down -v` em uma instalação com dados. O teste de recursos traz RAM e CPU por
serviço, picos **amostrados**, tamanhos dos volumes e soma conservadora das imagens; esta última não desconta
camadas compartilhadas. Faça uma amostragem durante a campanha além do repouso. O relatório não contém env,
credenciais ou dados de empresas. Um catálogo sintético não dimensiona o processamento dos 144 municípios.

### Preparar a produção

1. Reserve um checkout da revisão aprovada e Docker com Compose 2.24.4+. Copie
   `infra/agentes.env.example` para `producao.env` e restrinja a leitura (`chmod 600 producao.env`). Nunca use
   `.env.agentes-teste` na produção. Gere senhas diferentes, por exemplo com `openssl rand -hex 32`;
   a senha do banco deve usar apenas letras ASCII, números, hífen e sublinhado, com pelo menos 24 caracteres.
2. Configure `RAIZ_CHAVE_PESSOAL` com uma chave Fernet nova (`uv run raiz pessoal gerar-chave`) e
   `RAIZ_RECIBO_CHAVE` com 32 bytes aleatórios codificados em base64url, sem padding. Guarde cópias em cofre fora da
   VPS: perder a primeira impede abrir os dados cifrados; trocar o assinante exige manter as chaves públicas antigas
   para verificar recibos emitidos. `RAIZ_API_TOKEN` é exclusivo do backoffice e não autentica o MCP.
3. Preencha URLs HTTPS reais: `RAIZ_KEYCLOAK_URL`, seu `/realms/raiz` em `RAIZ_OAUTH_ISSUER`,
   `RAIZ_MCP_RESOURCE` terminado em `/mcp`, `RAIZ_API_PUBLICA_URL` com a origem da API (sem `/v1`),
   `RAIZ_LOGIN_BASE_URL`, `RAIZ_FRONT_URL`, `RAIZ_API_ORIGENS` e callback exato em `RAIZ_OAUTH_REDIRECT_URI`.
   Não use curinga. Um proxy HTTPS da VPS encaminha a API para `127.0.0.1:8000` e o Keycloak para
   `127.0.0.1:8180`; deve substituir, não acrescentar valores arbitrários de `X-Forwarded-*`. Não exponha os bancos,
   Valkey ou a porta de administração/saúde 9000. Restrinja o console administrativo OAuth ao operador.
4. Configure SMTP com SSL ou STARTTLS, remetente e autenticação. Sem SMTP, o login por e-mail permanece
   indisponível. Configure o coletor OTLP/HTTP em `RAIZ_OTEL_ENDPOINT` para persistir a telemetria; a ausência de
   coletor não constitui registro externo. Use destinos de webhook HTTPS exatos em `RAIZ_WEBHOOK_HOSTS` e
   política de saída no proxy/firewall que bloqueie IPs privados, loopback, link-local e metadados após DNS.
   O allowlist de nomes, sozinho, não protege contra DNS rebinding.
5. Configure o arquivo privado de dados em `RAIZ_DADOS_PRIVADOS_URL` e o token só no servidor, carregue as ofertas
   no PostGIS e importe as evidências territoriais vigentes. Ficha paga, reserva e contrato continuam bloqueados
   quando falta habilitação ou evidência; nenhum dado de proprietário deve entrar em URLs ou logs.
6. Use somente a pilha local de teste até a conferência do provedor. Para produção, configure `RAIZ_ABACATEPAY_CHAVE`,
   `RAIZ_ABACATEPAY_WEBHOOK_SEGREDO`, `RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA` e só então `RAIZ_PIX_MODO=producao`.
   O webhook de pedidos fica em `/pagamentos/abacatepay`; confirme a rota e o contrato de assinatura no OpenAPI da
   revisão instalada. A ficha individual usa o webhook próprio de prospecção, documentado abaixo: não misture os
   dois produtos nem seus segredos. Não ative `RAIZ_ABACATEPAY_IDEMPOTENCIA_SUPORTADA` sem confirmação contratual.
   O agente só prepara um link; uma pessoa autenticada aprova e o provedor confirma o pagamento. O recibo JWS
   comprova aprovação, não liquidação financeira.
7. Com o `.env` pronto e o proxy configurado, um comando constrói e sobe a pilha completa:

   ```bash
   python3 scripts/pilha_agentes.py subir --env-file producao.env
   ```

   O comando recusa placeholders de domínio, HTTP e Pix simulado na produção; exige as credenciais do provedor. Ele espera os healthchecks e a migração
   `head` (incluindo checkpointer cifrado do LangGraph) antes de liberar API/worker/agenda. Para usar uma imagem já
   construída da mesma revisão, acrescente `--sem-build`; `RAIZ_IMAGEM_TAG` deve identificar a revisão publicada
   internamente pelo operador. Não reutilize `local` entre versões sem reconstruir.
8. No Keycloak, crie usuários e vincule `empresa_id` à empresa já aberta na API. O usuário não pode editar esse
   atributo. Atribua `raiz-api/admin_empresa` somente ao administrador daquela empresa. O cliente `raiz-agentes`
   usa PKCE S256 e escopos `consultar`/`pedir`; `reservar` é opcional, começa desabilitado também na conta e só
   o administrador da empresa habilita. Confira `/.well-known/oauth-protected-resource/mcp`, emissor, audiência,
   expiração, `sub` e callback com o cliente real. O escopo padrão `raiz-identidade` inclui o mapper
   `oidc-sub-mapper` (Subject), com `access.token.claim=true`; sem ele o Keycloak 26.8 emite um token
   sem sujeito e o MCP o recusa. Em realms existentes, adicione esse mapper por administração antes
   de testar a conexão. O import inicial não altera realms já existentes; mudanças exigem
   migração administrativa deliberada. Remova/rotacione o administrador de bootstrap depois do provisionamento.

### Atualizações, agenda e recuperação

Antes de atualizar, guarde backup consistente dos dois bancos, volume `dados`, realm/configuração e chaves em
armazenamento privado fora da VPS. Restrinja os arquivos de backup com `umask 077`; use `pg_dump -Fc` e ensaie
`pg_restore` em banco separado. Arquivo SQL completo ou dump nunca é artefato público de CI. Não basta copiar
um volume PostgreSQL enquanto ele escreve. Confira espaço para WAL, backup e duas versões de imagem.

Para atualizar a mesma instalação: pare `api`, `worker` e `agenda` com o compose e o mesmo `--env-file`, construa
na revisão aprovada e repita `subir`. O serviço `migrar` precisa terminar com sucesso; uma falha impede os outros
serviços de iniciar. Não reverta schema automaticamente nem inicialize volumes vazios sobre o banco existente.
Depois, confira `/saude`, descoberta OAuth/MCP, uma consulta autorizada, fila/outbox e recibo de aprovação de teste.

A agenda `scripts/agendar_servicos.py` reutiliza as CLIs existentes: alertas a cada 15 minutos, ciclo dos pedidos
por hora, atualização de fichas e buscas salvas a cada 15 minutos e Calendário diariamente às 06h47 no fuso `RAIZ_AGENDA_FUSO`
(padrão `America/Sao_Paulo`). Ela mantém uma trava exclusiva e horários concluídos no volume `dados`, não duplica
horário concluído após reinício e repete falhas depois de cinco minutos. Tarefas distintas podem executar juntas,
mas a mesma tarefa nunca se sobrepõe. Instale somente uma agenda para esse volume; não deixe os mesmos trabalhos
ativos também no crontab. A agenda do motor estadual/Pará continua pertencendo ao chat “Lote e números”.

O worker processa fila e Standard Webhooks continuamente. Seu healthcheck confirma acesso ao banco, não prova
avanço dos pedidos; monitore idade de `submitted/working`, vencimento de leases, outbox e alertas no backoffice.
A agenda tem heartbeat próprio. Docker reinicia processos que saem, mas não reinicia automaticamente todo processo
marcado `unhealthy`: um monitor externo deve avisar o operador. Os logs Docker têm rotação de três arquivos de
10 MiB por contêiner; não habilite access log bruto com query strings ou tokens.

As amostras reais e seus limites devem acompanhar o relatório da campanha no Actions e a passagem de Produto e
regras. O teste local construiu a imagem e validou migrações, API e descoberta OAuth; a tentativa de manter a pilha
inteira foi interrompida pelo espaço do Docker VFS do ambiente. VFS copia camadas inteiras por contêiner e os
erros de criação deixaram resíduos: isso não representa o consumo de uma VPS com overlay2. Nenhuma medição de RAM
completa ou recomendação numérica de VPS é atribuída a essa tentativa. A campanha no Actions usa a imagem
congelada e amostra recursos durante as tarefas, incluindo identificação das imagens. Para dimensionar
uma VPS, some margem de sistema operacional, PostgreSQL/WAL, concorrência dos workers e crescimento dos dados;
repita a medição com o catálogo e a simultaneidade pretendidos. Esta entrega não contrata nem publica servidor.

Primeira referência medida no [CI do PR #85](https://github.com/bernardoemmel/Raiz/actions/runs/43339076294),
em cinco amostras após os 24 cenários sintéticos: soma dos picos por contêiner de **1.192 MiB**, volumes
de **177,8 MiB** e imagens de **3,18 GiB** sem deduplicar camadas. Os dados brutos estão no artefato
`contratos-agentes/recursos.json`. Essa coleta curta, após o ensaio, não cobre o pico da campanha Claude;
o workflow real amostra também enquanto o Claude executa as tarefas.

Medições durante as campanhas reais no Actions (13/11/2026 UTC), com sete serviços ativos:

| Campanha | Amostras | Pico simultâneo de RAM | Soma dos picos por serviço | Volumes | Imagens |
|---|---:|---:|---:|---:|---:|
| [1, interrompida após 35 tentativas](https://github.com/bernardoemmel/Raiz/actions/runs/43341704532) | 44 | 1.162,3 MiB | 1.181,9 MiB | 193,7 MiB | 3,18 GiB |
| [2, interrompida após 17 tentativas](https://github.com/bernardoemmel/Raiz/actions/runs/43347357547) | 27 | 1.175,1 MiB | 1.186,4 MiB | 193,7 MiB | 3,18 GiB |
| [3, interrompida após 64 tentativas](https://github.com/bernardoemmel/Raiz/actions/runs/43349634089) | 81 | 1.225,3 MiB | 1.276,4 MiB | 194,1 MiB | 3,18 GiB |
| [5, interrompida após 20 tentativas](https://github.com/bernardoemmel/Raiz/actions/runs/43359802697) | 31 | 1.126,8 MiB | 1.137,8 MiB | 193,8 MiB | 3,18 GiB |
| [6, 96 sessões; comportamento reprovado](https://github.com/bernardoemmel/Raiz/actions/runs/43362401481) | 110 | 1.240,3 MiB | 1.289,0 MiB | 194,8 MiB | 3,18 GiB |
| [7, interrompida após 43 tentativas](https://github.com/bernardoemmel/Raiz/actions/runs/43368316000) | 58 | 1.148,0 MiB | 1.202,2 MiB | 194,4 MiB | 3,18 GiB |

As interrupções invalidam pass^4, mas não apagam as amostras de recursos: `recursos.json` está no artefato
`medicao-agente-real` de cada execução. A terceira coleta cobriu 02h36min32s–02h53min15s UTC. A soma de CPU
atingiu 153,58% nas coletas relacionadas (100% representa aproximadamente um núcleo). Os picos são amostrados,
sem cobrir toda a inicialização; o runner Claude/juiz e o host não entram na RAM dos contêineres.

Para um **piloto com carga equivalente**, o ponto inicial recomendado é **2 vCPU, 4 GiB de RAM e 40 GiB SSD**,
com Docker overlay2. Isso é uma recomendação com margem, não capacidade concorrente comprovada. A RAM inclui
folga acima dos 1,26 GiB de picos somados para sistema, proxy, WAL/cache e variação de carga. O disco reserva
espaço para sistema, duas revisões de imagem, WAL, logs com rotação e backup temporário; backups duráveis ficam
fora da VPS. Os limites individuais do Compose não são uma reserva conjunta de RAM e podem somar mais que 4 GiB.
Antes de aumentar workers, carregar catálogo privado maior ou habilitar coletas reais, repita a medição com essa
carga e dimensione os dados separadamente. O ensaio usa 60 ofertas sintéticas, uma sessão de agente por vez e
agenda sem coleta/envio externo; não mede processamento estadual, OCR, documentos grandes ou operação nacional.


## Healthchecks (alerta fora do servidor)

O alerta não pode depender do servidor da Raíz: se ele cair, o aviso tem de sair de outro lugar. Por isso o padrão é
o serviço hospedado (healthchecks.io); uma instância própria também serve, desde que fique em outra máquina.

1. Crie a conta e um projeto "Raíz". Em *Settings*, gere a **ping key** e marque a opção que deixa criar checks pelo
   primeiro ping (auto-provisioning).
2. Ponha a chave no `.env` do servidor: `RAIZ_HEALTHCHECKS_CHAVE_PING=...`.
3. Em *Integrations*, ligue pelo menos dois canais que não passam pelo servidor: e-mail e ntfy (aplicativo no
   celular) ou Telegram.
4. Na primeira rodada, os checks aparecem sozinhos: `raiz-funil`, `raiz-filtros`, `raiz-direto`, `raiz-carga`.
   Ajuste em cada um o período e a tolerância (para a fila nacional, 1 dia e 6 horas é um bom começo): sem ping
   dentro do prazo, o Healthchecks avisa que o trabalho parou mesmo sem erro.

Cada município é uma execução do check com seu próprio `rid`: o painel mostra início, fim, duração e, na falha, o fim
do log (CPF e CNPJ já mascarados). Para um check por UF, use `RAIZ_HEALTHCHECKS_MODELO_SLUG=raiz-{tarefa}-{uf}`; um
check por município (`raiz-{tarefa}-{cod}`) só vale numa instância própria, porque são mais de 5 mil.

## Alertas com escalonamento (E7 passo 9)

O Healthchecks avisa quando um trabalho para de bater ponto, mesmo com o servidor fora do ar. Por dentro, o servidor
olha o resto de 15 em 15 minutos e sobe a escada do que ninguém reconheceu:

```
*/15 * * * *  uv run raiz operacao alertas   # lotes, orçamento, vigilância, prazo da Verra, filas, grupos
```

Para instalar sem depender do diretório e do `PATH` do cron, no servidor e com o usuário da aplicação:

```bash
uv run python scripts/instalar_cron_alertas.py             # mostra o bloco
uv run python scripts/instalar_cron_alertas.py --instalar  # ativa a cada 15 minutos
crontab -l
```

O instalador preserva os outros trabalhos e substitui apenas o bloco marcado da Raíz; pode ser repetido. Usa o
caminho absoluto do `uv`, entra na raiz do repositório (onde a configuração lê o `.env`), exige o lockfile com
`--frozen` e usa `flock` para não sobrepor rodadas. Se existir `.env`, usa `uv run --env-file .env` para exportar
também as variáveis lidas diretamente por `os.environ` na vigilância; não executa o arquivo como código shell.
Precisa de `cron` ativo e `flock` (`util-linux`) no servidor.
Não instala serviços nem preenche credenciais. Sem ntfy e GoAlert, continua em envio simulado; sem banco acessível
e migrado, a rodada falha. A prévia não ativa nada. Um ambiente de desenvolvimento sem acesso ao servidor não
comprova que o agendamento esteja ativo em produção.

O Calendário da Raíz usa um bloco separado no mesmo instalador:

```bash
uv run raiz banco migrar
uv run python scripts/instalar_cron_alertas.py --tarefa calendario            # prévia
uv run python scripts/instalar_cron_alertas.py --tarefa calendario --instalar # diário
```

Ele executa `uv run raiz calendario coletar` todos os dias às **06:47 no fuso configurado no servidor**, com trava
própria, sem alterar o fuso dos demais trabalhos. O banco do `.env` precisa estar acessível e migrado (incluindo
0026). Essa rodada persiste os eventos, cruza CAR/SIGEF, atualiza API/MCP e prepara os avisos do painel; os canais
externos continuam simulados. A rodada do GitHub Actions com `--sem-banco` publica o Release e não substitui esse
agendamento do banco. Instalar ou repetir um bloco preserva o outro. Instale no diretório permanente da aplicação:
`dados/calendario/` guarda o estado da coleta entre as rodadas.

| O que | Gravidade |
|---|---|
| lote que falhou nas últimas 24 h (um alerta por tarefa e dia) | aviso |
| lote que começou e não terminou há mais de 6 h | urgente |
| gasto com modelos a 80% / 100% do orçamento do mês (`RAIZ_ORCAMENTO_MENSAL_USD`) | aviso / urgente |
| vigilância diária sem rodar há mais de 1 dia; fonte da vigilância com erro | urgente; aviso |
| aviso à Verra de um evento de perda vencendo (7 dias) ou vencido; relatório de perda vencido | crítico |
| revisão esperando há mais de 24 h; mensagem para dono esperando aprovação há mais de 12 h | aviso |
| fazenda com problema num grupo pronto ou reservado | urgente |

A escada (raiz/regras/padroes/alertas.yaml, versionada): nível 0 no ntfy na hora; sem reconhecimento, nível 1 em 30
minutos (ntfy urgente) para urgente e crítico; nível 2 em 2 horas para crítico, que vai para a segunda pessoa no
GoAlert quando houver (`RAIZ_GOALERT_URL`) e, sem ela, de novo para o fundador, urgente. O último nível se repete a
cada 4 horas, até 8 envios. Aviso sai uma vez só. Estado que passou (o lote destravou, a vigilância voltou) fecha
sozinho; fato (lote que falhou, grupo com problema) fecha quando alguém resolve.

- ntfy: `RAIZ_NTFY_TOPICO` (nome longo e aleatório: ele funciona como senha), `RAIZ_NTFY_URL` (padrão
  https://ntfy.sh) e, se o servidor do ntfy pedir, `RAIZ_NTFY_TOKEN`. No celular, assinar o mesmo tópico.
- Sem essas variáveis, o envio é simulado: o texto e o nível ficam registrados no alerta (backoffice), nada sai.
- `uv run raiz operacao reconhecer ID` para a escada; `uv run raiz operacao resolver ID --nota "..."` fecha.

## Backoffice do fundador (E7 passo 6)

Só leitura, com o mesmo token da API: `/painel/backoffice` (página que pede o token), `/backoffice/resumo` (saúde,
lotes em 24 h, parados, vigilância, custo do mês contra o orçamento com projeção, filas esperando o fundador, alertas
abertos), `/backoffice/custos?por=tarefa|fazenda|municipio|modelo`, `/backoffice/lotes?estado=falha`,
`/backoffice/alertas` e `/backoffice/fazenda/{cod_imovel}` (chamadas de modelo e custo, decisões da cascata,
revisões, aceite, mensagens só com tipo e estado, pedidos, lotes do município e alertas da vigilância). No terminal:
`uv run raiz operacao painel`.

## Painel de acerto (E7 passo 5)

Toda previsão congelada (aprendizado.previsao) e todo gabarito entram no formato do hub (hubverse):

```bash
uv run raiz aprendizado hub dados/hub     # hub-config, model-output, model-metadata, target-data, painel
uv run raiz aprendizado acerto            # notas por modelo, versão e alvo no terminal
```

Cada (modelo, versão) vira um model_id (`raiz-<modelo>_<versão>`), para comparar versões. Na API, com token:
`/acerto/placar` e a página `/painel/acerto` (WIS, cobertura do P10 a P90, Brier, log score e acerto; a versão na
frente por alvo; o acerto da vigilância). A pasta do hub fica no servidor, fora do git: as previsões de aceite dizem
quem aceitou. Para o painel do hub-dashboard (o mesmo do FluSight), a pasta já traz site-config.yml,
predevals-config.yml e predtimechart-config.yml.

## Cascata por confiança e teste próprio (E7 passo 10)

**Rota** (`raiz/regras/padroes/cascata.yaml`): o Qwen3-4B só faz classificação curta. Isso quer dizer:

- até 6 campos na saída, todos de lista fechada ou sim/não;
- resposta de até 400 tokens;
- nenhuma chamada de ferramenta.

O resto vai para a nuvem: o Haiku responde sozinho e, se falhar, o Sonnet; sem resposta, a fila de revisão.

**Confiança:** o llama-server devolve os logprobs; a confiança é a menor probabilidade entre os tokens dos valores
(`raiz/modelos/confianca.py`). Com corte calibrado para a tarefa, a resposta do Qwen acima do corte vale sozinha (via
`confianca`); abaixo, sobe para a votação com o Haiku, como antes. Só os 20 a 30% menos confiantes sobem. Tarefa sem
corte fica na votação.

**Teste próprio** (`raiz/modelos/avaliacao/banco.yaml`): 120 tarefas do aceite com o prompt de produção, 15% sem
resposta válida (o modelo tem de dizer que não sabe), 3 tentativas seguidas. O relatório traz acerto, acerto nas 3
tentativas, consistência, abstenção correta e custo; fica em `dados/avaliacao/`, fora do git.

No servidor, depois de subir o llama (compilado com llguidance, `infra/llama/Dockerfile`) ou de trocar o modelo ou o
prompt:

```bash
docker compose -f infra/docker-compose.yml up -d --build llama
uv run raiz modelos calibrar        # roda o teste no Qwen e grava raiz/regras/padroes/cascata_cortes.yaml
uv run raiz modelos avaliar --modelo triagem   # o mesmo teste no Haiku, para comparar
```

O GGUF validado para o nome usado no compose é o Q4_K_M de
[Unsloth/Qwen3-4B-Instruct-2507-GGUF](https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF), revisão
`a06e946bb6b655725eafa393f4a9745d460374c9` (2.497.281.120 bytes), sob Apache-2.0. Salve-o como
`infra/modelos/qwen3-4b-instruct-2507-q4_k_m.gguf`, fora do git, e confira antes de subir:

```bash
sha256sum infra/modelos/qwen3-4b-instruct-2507-q4_k_m.gguf
```

SHA-256 esperado: `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`.
O download verificado em 12/11/2026 veio da revisão acima; trocar a quantização ou o conteúdo do arquivo exige
recalibrar, mesmo que o nome permaneça igual. Guarde esse SHA junto do relatório de avaliação. Antes de rodar as
360 chamadas, `uv run raiz modelos testar --modelo qwen3-4b-instruct-2507` confere a conexão e a saída JSON.

O Dockerfile fixa Rust 1.100.0 e copia o header da mesma revisão do llguidance depois de compilar o Rust. Isso
corrige a falha `llguidance.h: No such file or directory` da combinação b12300/llguidance 1.0.1 com o novo layout
de diretórios do Cargo. Se o ambiente usa proxy TLS, o certificado pode ser montado apenas durante o build:

```bash
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -t raiz/llama-server:b12300-llguidance infra/llama
docker compose -f infra/docker-compose.yml up -d --no-build llama
```

Sem proxy, o segredo é opcional e o comando normal do compose continua suficiente. A imagem final não recebe o
certificado do ambiente de construção.

Validação local em 12/11/2026: imagem construída com esse Dockerfile, `llama-server --version` em
`ccd360f` (b12300), `/health` saudável e teste CLI do Qwen respondendo JSON válido em 1.253 ms. A intenção e a
explicação amostradas do teste próprio levaram 3.868 e 7.392 ms, com logprobs disponíveis. Isso confirma o build e
a conexão local; não afirma implantação no servidor nem substitui as 360 respostas da calibração.

O corte só é gravado com o relatório de um modelo local de verdade; se o arquivo do GGUF mudar de nome, os cortes
antigos deixam de valer. Sem servidor nem chave, `--modelo simulado` roda tudo com regras (linha de base). Cada
decisão em `operacao.decisao_cascata` guarda rota, confiança, corte e versão da regra e dos cortes. Se a subida real
sair da faixa por mais de 15 pontos em 7 dias, abre o alerta `cascata_faixa`: recalibrar.

Os 95% exigidos pelo calibrador são o acerto observado no mesmo banco usado para escolher o corte; não há amostra
independente de validação nem garantia estatística desse acerto em produção. As três tentativas medem repetição e
consistência, não equivalem a três mensagens independentes. O runtime confere o nome do modelo; conferir também
SHA do GGUF, versão do llama.cpp e prompt é parte da promoção operacional dos cortes.

### Resultado real do Qwen em 12/11/2026

A rodada terminou às 16h05 de Brasília (19h05 UTC): **120 mensagens do banco próprio, três tentativas por
mensagem, 360 respostas completas**, todas com confiança numérica e nenhuma falha técnica. São mensagens de
teste, não contatos reais de produtores. Banco `banco-pt-2026.11a+01697528`, política
`cascata-2026.11a+fb4a9c2d`, Qwen/llama/GGUF identificados acima, três threads e contexto de 8.192 tokens.

| Tarefa | Mensagens / respostas | Acerto observado | Acerto nas três tentativas | Abstenção correta | Latência mediana |
|---|---|---|---|---|---|
| Intenção do aceite | 80 / 240 | 163/240 (67,92%) | 67,50% | 7,14% | 1.914 ms |
| Compreensão da proposta | 40 / 120 | 52/120 (43,33%) | 42,50% | 25,00% | 5.465 ms |

**Nenhum corte foi aprovado.** No melhor candidato da faixa de subida, a intenção manteria 79,43% de acerto no
que fica no Qwen, com 27,08% subindo; a compreensão manteria 49,47%, com 20,83% subindo. Ambos ficaram abaixo dos
95% exigidos. O arquivo `cascata_cortes.yaml` foi gerado pela CLI com os metadados desta rodada e `cortes: {}`;
as duas tarefas continuam na votação Qwen + Haiku. Não foi ajustado o banco nem forçado um corte para melhorar a
nota. A interpretação continua sendo empírica, no mesmo banco de escolha do corte, conforme a limitação acima.

A soma do tempo de inferência foi de 24 min 27 s; havia outros testes rodando na máquina, portanto os tempos não
são um compromisso de desempenho em produção. A comparação com Haiku ficou pendente: o teste real da CLI
retornou `sem credencial da Anthropic` neste ambiente, sem benchmark simulado nem pedido de chave pelo chat.
Implantação e agendamento no servidor de produção não foram realizados neste ambiente local.

Evidência fora do git, em `dados/avaliacao/qwen-2026-11-12/`:

- Relatório: `2026-11-12T190503_qwen3-4b-instruct-2507.json`, SHA-256
  `0f23332758a33238ee48289caa4cb39b93a1f0d5072ecfc3dd3d2b4b1d6f4c87`.
- Proveniência do peso, imagem, compilador e parâmetros: `proveniencia.json`, SHA-256
  `35a215f3ece2240d5878182a69de8f9fda421fe97b642790fc08fb026c169abe`.
- `verificacao.json` registra a conferência dos 120 IDs, três tentativas por ID, versão do banco, modelo, provedor,
  métricas e decisões do calibrador. As 360 respostas brutas não foram incluídas no repositório.

## Rodar o motor vigiado

```bash
uv run raiz funil rodar PA 1504950                # um município
uv run raiz funil rodar PA                        # a UF inteira, 3 municípios ao mesmo tempo
uv run raiz funil rodar PA --tarefas funil,carga  # só o funil e a carga no banco
```

O comando não edita o motor. Ele lê CAR e SIGEF do espelho local da coleta (`dados/espelho/` ou
`RAIZ_ESPELHO_DIR`) e, quando o município não está no espelho, deixa o motor baixar como sempre, anotando a origem no
lote. Falha num município não para os outros; arquivo pronto é pulado (use `--refazer` para refazer). A carga grava
a rodada com a versão do motor confirmada e congela as previsões.

## Coleta (E1)

Sugestão de cron no servidor (horário de Brasília); cada comando avisa o Healthchecks:

```
10 5 * * *  uv run raiz coleta checar     # HEAD nos arquivos do manifesto (sumiu? mudou?)
20 5 * * *  uv run raiz coleta ibama      # embargos: condicional, sem dado pessoal, CSV limpo para o motor
40 5 * * *  uv run raiz coleta car        # UFs do rodízio do dia; SIGEF dos municípios que mudaram
```

A fila baixa até 200 municípios por rodada; se mais de 15% estiver sujo, roda tudo (disjuntor), e uma vez por mês faz
a reconciliação completa. O espelho fica em `dados/espelho/` (ou `RAIZ_ESPELHO_DIR`), um Parquet por município, e é o
que o `raiz funil rodar` entrega ao motor. O histórico fica em `bruto.car_imovel`, `bruto.sigef_parcela` e nas views
`*_vigente`.

## Langfuse próprio

```bash
docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.langfuse.yml up -d
```

Painel em http://127.0.0.1:3000 (só a máquina; acesso de fora por túnel). O compose não sobe sem os segredos do
`.env.example` (gere com `openssl rand -hex 32`). Valkey no lugar do Redis e SeaweedFS no lugar do MinIO, por causa
das licenças; para usar o R2, preencha `LANGFUSE_S3_ENDERECO` e as chaves do R2. As chaves `LANGFUSE_PUBLIC_KEY` e
`LANGFUSE_SECRET_KEY` que você escolher no `.env` criam o projeto na primeira subida e são as mesmas que o produto usa
para mandar os rastros. Volume do banco já existente: crie a base uma vez com `CREATE DATABASE langfuse OWNER raiz;`.

## Cache dos rasters na nuvem

A tarefa `direto` (YbYrá e GPW) lê os blocos dos arquivos na nuvem por pedaços de 1 MB guardados em disco
(`dados/cache_raster/` ou `RAIZ_RASTER_CACHE_DIR`, teto `RAIZ_RASTER_CACHE_GB`, padrão 20). Medido em Nova Esperança do
Piriá: 18 s sem cache, 33 s na primeira rodada com cache e 7 s nas seguintes, com valores idênticos. Se o arquivo
mudar na nuvem (ETag novo), o cache dele é refeito.

## Onde olhar

| O quê | Onde |
|---|---|
| O que mudou na coleta | `coleta.evento` (novos, mudaram, sumiram por município) e `coleta.replicacao` |
| Lote parado ou com falha | Healthchecks (alerta) e `operacao.lote` (estado, duração, fim do log) |
| Custo de modelo por tarefa e por fazenda | Langfuse (sessão = código do CAR) e `operacao.chamada_modelo` |
| Decisões da cascata ABC | `operacao.decisao_cascata` |
| O que precisa de decisão humana | `operacao.fila_revisao` (API: `GET /revisoes`) |
| Mensagens esperando aprovação | `pessoal.mensagem_saida` (API: `GET /mensagens/pendentes`) |
| Acerto das previsões | `uv run raiz aprendizado placar` e `aprendizado.previsao_contra_gabarito` |

## Blocos de 0,5 grau: recalcular só o que mudou (E2 passo 4)

- Cada imóvel tem um bloco (`raiz/funil/grade.py`, mesma grade do cache do motor, como `-47.0_-3.5`), gravado em
  `funil.imovel` e nas tabelas da rodada.
- Depois do histórico, a rodada da coleta lê os arquivos do espelho que mudaram (CAR, SIGEF, embargos) e grava em
  `funil.bloco_manifesto` o hash do que cada camada tem em cada bloco, por município. Mudança só em campo volátil não
  suja o bloco. O resumo da rodada traz a lista `blocos`.
- `manifesto_blocos.sujos(con)` lista os blocos com alguma camada que mudou depois do último cálculo;
  `marcar_calculados` fecha o bloco quando o funil termina. No município 1504950: CAR em 5 blocos, SIGEF em 9,
  embargos em 2; a segunda leitura, sem mudança, leva 4 ms.

## Mapa base do Brasil (design v1 do front, item 5)

- `raiz mapa atualizar` recorta o Brasil até o zoom 14 do build mais recente do Protomaps (go-pmtiles: `go install
  github.com/protomaps/go-pmtiles@latest`), baixa fontes e sprites e grava `manifesto.json` em `RAIZ_MAPA_DIR`
  (padrão `dados/mapa/`). O recorte de 11/11/2026 tem 3,07 GB (4,5 milhões de ladrilhos) e saiu em cerca de 2 minutos.
  Atualizar uma vez por mês basta; o recorte anterior só é apagado depois que o novo terminou.
- Rotas: `/mapa/manifesto.json`, `/mapa/brasil.pmtiles` (Range, nunca recomprimido),
  `/mapa/fontes/{fonte}/{faixa}.pbf` e `/mapa/sprites/{nome}.{json|png}`.

## Imagens de satélite por fazenda (design v1 do front, item 1)

- Rotas `/imoveis/{cod}/imagem/{hoje|hoje-produtor|hoje-celular|simulacao|1985|2008}.webp` e `.json` (metadados).
  Na primeira chamada a imagem é gerada (Sentinel-2 dos últimos 3 meses sem nuvem sobre o imóvel, ou mediana das
  cenas limpas do trimestre; Landsat 5 para 1985 e 2008) e fica em `RAIZ_IMAGENS_DIR` (padrão `dados/imagens/`).
- `raiz satelite gerar --municipio 1504950` adianta as imagens das fazendas aptas. Num imóvel real de 2.491 ha:
  cena de 28/10/2026, 30 s para as quatro de hoje, 144 KB (1024 px), 76,6 KB (720 px, produtor) e ~57 KB (480 px);
  Landsat 1985 e 2008 em 15 s.

## Link público, cartão e vídeo (design v1 do front, item 6)

- Sem token, pelo código curto: `/p/{codigo}` (HTML com Open Graph), `/cartao/{codigo}/{previa.jpg|retrato.jpg|
  adesivo.png}` e `/video/{codigo}.mp4` e `-720p.mp4`. Os cartões também saem em WebP (`previa.webp`, `retrato.webp`,
  `adesivo.webp`), com cerca de metade do peso, para a ficha e o site; a prévia do WhatsApp continua em JPEG. Antes do
  aceite do dono só saem município, hectares, selo e código curto; o código do CAR e a imagem de satélite da fazenda
  só depois do aceite.
- Precisa de `npm ci` em `servicos/cartao` (Takumi) e do `ffmpeg` no servidor. A voz do vídeo liga com
  `uv pip install qwen-tts` (traz torch; o modelo de 0,6 B roda em CPU); sem ela o vídeo sai mudo e o cabeçalho
  `X-Raiz-Aviso: sem voz` avisa. Cache em `RAIZ_PUBLICO_DIR` (padrão `dados/publico/`), refeito quando o selo muda.
- Medido aqui: prévia 41 KB, retrato 63 KB, adesivo 12 KB, vídeo 720p de 6 s em 1,4 s.

## Dados por município (design v1 do front, item 4)

- `GET /municipios/{cod_ibge}`: frase-resumo, funil por etapa e por porte com os 3 maiores motivos de saída, "desde a
  última análise" (foto da etapa de cada imóvel em cada rodada, `funil.etapa_rodada`, gravada pela carga) e área
  urbana da sede. `raiz municipio urbana <cod>` gera o contorno urbano (MapBiomas classe 24, a mancha onde fica a
  sede no OpenStreetMap) e grava em `geo.camada`.
- Em Nova Esperança do Piriá (dado real): 880 imóveis, 793 sem problema, 738 aptos (32.848 ha), 41 com matrícula;
  o que mais tira do funil é a matrícula (697); área urbana da sede 182 ha.

## Fichas em lote (E9, passo 1)

- `raiz ficha lote [--uf PA] [--municipios 1504950,1507300] [--destino pasta] [--refazer]` grava, por município, em
  `RAIZ_FICHAS_DIR` (padrão `dados/fichas/`, fora do git):
  - `<UF>/<cod_ibge>/fichas/<código do CAR sem traços>.json`: a mesma ficha de `GET /imoveis/{cod}/ficha`, para
    servir como arquivo estático (qualquer servidor de arquivos ou o Pages);
  - `<UF>/<cod_ibge>/rows.json`: uma linha por fazenda com os campos do cartão, do vídeo e do texto (os nomes do
    pedido do Takumi). Campo que começa com `_` é interno: o código do CAR só aparece fora dele depois do aceite;
  - `<UF>/<cod_ibge>/manifesto.json` e `indice.json` na raiz: rodada, data de corte, quantas fazendas, quantas aptas
    e quando foi gravado.
- Cada ficha leva a capa (foto de satélite com ThumbHash, quando já foi gerada) e a localização: Plus Code e link curto
  do Organic Maps (`https://omaps.app/...`, abre o app offline) de um ponto dentro do imóvel. No `rows.json`, o ponto
  exato só sai fora do campo interno depois do aceite.
- Só regrava o município cuja rodada vigente mudou. O contexto do município (posição e medianas) é calculado uma vez
  por município, não por fazenda.

## Valor para quem restaura (desenvolvedor de crédito de carbono)

Calculado pelo produto, fora do motor (raiz/restauracao.py e raiz/restauracao_geo.py), por município, em
`saida/<UF>/desenvolvedor_<mun>.csv`; a carga leva ao banco como complemento `desenvolvedor` e a ficha mostra o bloco
"Para quem restaura" (sempre com o aviso de estimativa e as faixas P10 a P90).

- Rodar junto do motor: a tarefa `desenvolvedor` do `raiz funil rodar` (padrão), depois da ficha e antes da carga.
- Refazer quando as premissas mudam: `raiz restauracao recalcular [--ufs PA]` refaz só os municípios gravados com
  outra versão (`restauracao_versao` = versão de raiz/regras/padroes/restauracao.yaml + do cenário + hash dos
  arquivos e da calibração).
- Entradas geográficas com cache em `dados/cache_restauracao/` (ou RAIZ_CACHE_RESTAURACAO_DIR): declividade do
  Copernicus por ladrilho de 1 grau, chuva do CHIRPS por faixa de 5 graus de latitude, solo do SoilGrids por município;
  a distância à mata e a linha de base saem do raster de cobertura do MapBiomas do motor e do YbYrá. Se uma fonte
  falhar, a coluna fica vazia, o cálculo usa a premissa neutra e `restauracao_faltou` diz o que faltou.
- Cenários (no mesmo arquivo das premissas, raiz/regras/padroes/restauracao.yaml, seção 11; um só arquivo e um só
  cálculo): o padrão é `central_r11` (rodada 11 do fundador: captura na forma oficial da URTX escalada para o total do
  método e limitada ao teto do bioma, custos oficiais do SFB com P10 e P90 publicados, descontos em ordem com piso de
  10% na linha de base e vazamento de 10% (zero com vizinha de mitigação), marcos do ProFloresta+ com o último a 100%,
  multa e rescisão medidas no lote, dono pago por 40 anos com piso de R$ 24/ha, Fundo Clima até 50% pelo ICSD 1,3,
  venda a US$ 30 depois do ano 25, WACC de 9,2%); `central_r11_74`, `estresse_r11` (linha de base e vazamento de 40%,
  35% financiado, 20% ao dono), `so_contrato_25` (sem venda depois do contrato) e as premissas antigas em
  `otimista_fundador` e `otimista_fundador_74`. Referência (fazenda de 100 ha no leste do PA, US$ 55, câmbio de R$
  5,40): TIR com financiamento de ~5,5% no plantio e ~13,5% na regeneração assistida (docs/restauracao-rodada11.md).
- Câmbio: `raiz restauracao cambio` mostra a PTAX de venda do Banco Central; `--gravar` grava em
  raiz/regras/padroes/restauracao_cambio.yaml e os cenários com `cambio_ptax` passam a usá-la no lugar dos R$ 5,40 (a
  versão muda e o `recalcular` refaz; rode uma vez por mês, ou quando o câmbio andar).
- Simulador: `GET /imoveis/{cod}/restauracao/simular?cenario=estresse_r11&preco_usd_t=74&pagamento_dono=duas_fases&...`
  (marcos_pct, entregas_anos, volume_contratado, juros_carencia, participacao_dono, piso_dono_rs_ha_ano e os demais
  da lista `editaveis`);
  cenários com a fonte de cada parâmetro em `GET /restauracao/cenarios`. Painel: `GET /municipios/{cod}/imoveis?
  ordem=valor_desenvolvedor&modo=plantio_total&tir_min=20&so_lote_fecha=true` e `GET /municipios/{cod}/lotes`.
- Aprendizado: cada estimativa entra congelada (modelo `restauracao`, com a versão) na carga. Quando um cliente
  informar o real: `raiz restauracao informar <CAR> --fonte "desenvolvedor" --custo-rs-ha 16500 --modo plantio_total`
  (ou `POST /imoveis/{cod}/restauracao/real`). `raiz restauracao comparar` mostra real contra previsto por modo;
  `raiz restauracao recalibrar --gravar` escreve raiz/regras/padroes/restauracao_calibracao.yaml (revise antes de
  subir): a versão muda e o `recalcular` refaz.

## Rebanho por fazenda e metano (E4)

`raiz rebanho recalcular [--saida pasta] [--ufs PA]` grava rebanho_<mun>.csv onde falta ou a versão mudou (a tarefa `rebanho` do invólucro e do executor faz o mesmo, antes do valor para quem restaura). A PPM vem de raiz/regras/padroes/ppm_bovinos.csv (SIDRA 3939, 2025 e 2017); quando o IBGE divulga um ano novo (raiz/coleta/ppm.py), baixe de novo a tabela e suba o ano em rebanho.yaml: a versão muda e tudo se refaz. Reserva de não permanência por fazenda (E3 passo 4): seção nao_permanencia de restauracao.yaml, com o fogo do MapBiomas Fogo e a derrubada da vegetação secundária do município.

## Caminho da terra e terra pública para restaurar

A situação da terra não corta mais o funil: cada imóvel ganha um caminho (privada com matrícula, posse em
titulação, assentamento, pública sob concessão, pública sem destinação, terra indígena ou tradicional) com risco
e motivo, em `saida/<UF>/terra_<mun>.csv` (raiz/terra.py; regra em raiz/regras/padroes/caminho_terra.yaml).

- Preparar uma vez: `raiz terra preparar-cnfp` (baixa o Cadastro Nacional de Florestas Públicas do SFB, 229 MB, e
  grava `dados/terra_publica/cnfp_<UF>.parquet`). Sem ele, o caminho usa só o SIGEF do espelho e as colunas do motor.
- Junto do motor: a tarefa `terra` do `raiz funil rodar` (padrão), antes da ficha. Refazer quando a regra ou as
  concessões mudam: `raiz terra recalcular [--ufs PA]`.
- Camada "Terra pública para restaurar": `raiz terra publica --ufs PA` (gera `terra_publica_<UF>.parquet` e carrega em
  geo.terra_publica; `--reducao 4` mede a distância à mata a 120 m, bom para áreas do tamanho de um estado). API:
  `GET /terra-publica?uf=PA&ordem=desmatado|credito|area&so_com_concessao=true` e
  `GET /geo/{cod_ibge}/terra_publica.geojson`.
- Editais: `raiz terra editais` lê as páginas do SFB e do Ideflor-Bio, guarda cada link com a data em que apareceu
  (`dados/terra_publica/editais_vistos.json`) e lista os novos; o que for concessão de verdade entra em
  raiz/regras/padroes/concessoes.yaml com data e link (a versão da regra muda e o `recalcular` refaz).

## Motor dentro do produto (agente Dados)

O executor (raiz/executor/) roda o motor e as tarefas do produto por estado e por município e grava tudo no
armazém configurado em RAIZ_ARMAZEM_URL. O de produção (e o padrão) é o Release `dados` do GitHub
(`release-github://bernardoemmel/raiz/dados`), no formato de motor/publicar_dados.py: `raiz_<UF>.tar.gz` (CSV e
`_versoes.json`), `raiz_geo_<UF>.tar.gz`, `raiz_camadas_<UF>.tar.gz`, `raiz_controle_<UF>.json` (marcas e estado,
para retomar), `raiz_controle.json` e, por último, `estados.json`. Grava só com o token do Actions (`GH_TOKEN` ou
`GITHUB_TOKEN`); sem token, só lê. Também servem uma pasta local (testes) e o S3 (`s3://`, opção futura: R2 ou
SeaweedFS, sem uso hoje).

- Actions: o workflow `.github/workflows/processar-estados.yml` chama, por estado,
  `raiz executor rodar --ufs <UF> --lanes N --ate-minutos 330` com `RAIZ_SEM_BANCO=1` (sem banco no job) e o token.
  Aos 330 minutos o executor para de começar municípios, termina os que estão em curso e publica; a rodada seguinte
  baixa `raiz_controle_<UF>.json` e continua do ponto em que parou. Durante a rodada ele publica a cada 15 minutos
  (ou a cada 80 arquivos novos), então um job morto perde no máximo esse trecho.
- Estado publicado antes do executor (sem marcas, como o PA): `raiz executor adotar --ufs PA` grava as marcas a partir
  dos `_versoes.json` e dos arquivos que estão no Release, sem rodar o motor.
- Retomada: depois de CADA tarefa de cada município, a marca `marcas/<UF>/<mun>.json` guarda a versão da tarefa, a
  assinatura das entradas e o sha256 das saídas. Matar o processo perde no máximo a tarefa em curso; rodar de novo
  pula o que está em dia. Se a máquina for outra (disco vazio), as entradas de que uma tarefa precisa descem do armazém.
- O que refazer: a tarefa roda quando muda (1) a versão dela (hash do código de que depende e, quando há, da regra:
  FLAG, caminho da terra, premissas de restauração), (2) uma fonte do município (CAR, SIGEF e embargos do espelho,
  alertas na caixa do município, rasters do MapBiomas do estado) ou (3) a saída de uma tarefa anterior. Se uma tarefa
  roda e a saída sai igual, as seguintes não rodam.
- Cada arquivo no armazém leva nos metadados: tarefa, versão, data, município, versão do motor e sha256.
- Andamento por estado em `estado/<UF>.json` (pronto, em andamento, com erro; feitos, erros, versões), lido pelo
  painel (`/painel/processamento`, `GET /processamento`) e por `raiz executor estado`.
- O back-end não lê mais a pasta do motor: `raiz executor sincronizar` espelha o armazém em `dados/armazem_local/`
  e a carga contínua leva ao banco só o que mudou; um imóvel de município ainda não carregado é carregado na hora em
  que alguém pede (`/imoveis/{cod}`). Números do Brasil e dos estados: `GET /brasil` e `GET /estados`.
- Agenda: `raiz executor ciclo` (completa quando a coleção do MapBiomas do motor muda, parcial no resto) ou
  `raiz executor vigiar --intervalo-h 24`, com Healthchecks (raiz-executor). Ver o README para o cron.

## Pedido de lote (docs/cena-alvo.md)

O cliente pede "1 milhão de créditos" e a Raíz monta o melhor lote (raiz/pedidos/, premissas em
raiz/regras/padroes/pedidos.yaml, cada número com a fonte). O contrato com o front é
front/compartilhado/pedidos/tipos.ts.

- Oferta: uma linha por fazenda em `negocio.oferta` (crédito líquido até o ano 25 em P10/P50/P90, custo por crédito,
  TIR, marcos, caminho da terra, onde), refeita sozinha depois da carga de cada município; `raiz pedidos oferta
  [--ufs PA]` refaz do banco. Fazenda sem contorno fica na sede do município (raiz/executor/municipios.csv).
- Entrar: `POST /entrar {email}` manda o link (uso único, 30 minutos) e `POST /entrar/confirmar {token}` devolve a
  sessão (30 dias, `Authorization: Bearer`). O e-mail fica cifrado no esquema pessoal. `raiz pedidos cliente
  --rotulo "Empresa"` cria um cliente direto.
- Pedido: `POST /pedidos` responde na hora quanto existe na base (por caminho da terra e por interesse do dono, com o
  que falta e o que afrouxar) e as 3 opções do solver (HiGHS pelo scipy.optimize.milp: mais barata, mais segura,
  mais compacta), cada uma com fazendas de reserva (15% da meta). Fazenda cujo preço de equilíbrio passa do preço do
  pedido (o plantio que o preço não paga) custa a diferença mais US$ 30 por crédito (`abaixo_equilibrio_usd`), então a
  regeneração vem antes; cada opção traz `abaixo_equilibrio` com o aviso quando o lote só fecha com elas. Os marcos
  do ProFloresta+ e a multa esperada saem do lote inteiro (`restauracao.cronograma_lote`). `POST /pedidos/{id}/lote`
  (ou `PATCH`) tira ou troca uma fazenda e refaz os números. Cada lote sugerido fica em `negocio.pedido_sugestao` com a
  versão do modelo.
- Interesse do dono: `negocio.interesse_dono` (nível de agora) e `negocio.interesse_evento` (cada registro com data,
  canal, motivo e versão do termo); o nível só sobe com a versão do termo; recusa vale um ano. Nome e CPF ficam só no
  esquema pessoal; a API devolve só o nível. Resposta do dono: `POST /interesse/{cod_imovel}` (token da API) ou
  `raiz pedidos resposta`.
- Ondas: `POST /pedidos/{id}/solicitar-interesse {opcao}` contata a 1ª onda (até a soma de chance de aceite vezes
  crédito dar 1,5 vez a meta; envio simulado por enquanto, WhatsApp quando o dono tem contato, senão carta). `raiz
  pedidos ciclo` (de hora em hora no cron) vence quem não respondeu em 15 dias, chama a próxima onda, fecha o grupo
  quando os interessados alcançam a meta (aviso no painel, e-mail e WhatsApp) ou diz o que faltou.
  `GET /pedidos/{id}/andamento` mostra a meta com interessado, aceite e contrato, as ondas, recusas e motivos.
- Reserva: `POST /pedidos/{id}/reservar` cria a cobrança Pix pela AbacatePay somente com `RAIZ_PIX_MODO=producao`
  e `RAIZ_ABACATEPAY_CHAVE`; por padrão é cobrança de teste, paga com `raiz pedidos pagar-teste <id>` ou
  `POST /pagamentos/teste/{id}/pagar`. O aviso de
  pagamento chega em `POST /pagamentos/abacatepay?webhookSecret=...` (`RAIZ_ABACATEPAY_WEBHOOK_SEGREDO`). Paga, as
  fazendas ficam do cliente por 60 dias (`reserva_dias` no pedido) e somem das buscas, contas e pedidos dos outros;
  uma fazenda nunca está em duas reservas (índice único). Venceu sem contrato, voltam para a base (`raiz pedidos
  ciclo`). Contrato fechado: `POST /reservas/{id}/converter {ha_assinados}` abate a reserva da conexão por ha.
  Cada passo fica em `negocio.reserva_evento` (quem, quando, valor e prazo).
- Vigia: o mesmo `raiz pedidos ciclo` refaz os pedidos salvos e avisa "lote melhorou" ou "fazenda do grupo com
  problema" (embargo, desmatamento, bloqueio, saiu da base); `GET /pedidos/{id}/alertas`.
- Aprendizado: cada onda congela a chance de aceite de cada fazenda contatada (aprendizado, alvo `aceite_dono`, com a
  versão do modelo); o aceite ou a recusa viram gabarito, e a chance por perfil (tamanho, caminho da terra, estado e
  forma de pagamento) é atualizada a cada contato.

## API pública e MCP para os agentes de IA dos clientes (docs/agentes-ia.md)

- API pública em `/v1` (OpenAPI em `/v1/openapi.json`, Swagger em `/v1/docs`) e servidor MCP remoto em `/mcp/`
  (streamable HTTP, sem estado); local por stdio com `raiz mcp` (RAIZ_API_URL e RAIZ_CHAVE_API).
- Chave por empresa: `POST /v1/chaves` na sessão do login por e-mail ou `raiz pedidos chave --cliente <id>`; só o hash
  fica em `negocio.chave_api`; limite por minuto e por dia (429 com Retry-After).
- Cada chamada fica em `negocio.chamada_api` (empresa, chave, via api/mcp/sessao, ferramenta, pedido, fazenda, status,
  tempo, versão do modelo e modelo do agente): limite, auditoria (`GET /v1/chamadas`) e aprendizado.
- Reserva pedida por agente: `negocio.reserva.estado = aguardando_confirmacao`, link de uso único (48 horas) no e-mail
  da empresa (`/v1/reservas/confirmar/{token}`); sem confirmação, o `raiz pedidos ciclo` cancela (nada foi cobrado).
- Em produção: `RAIZ_MCP_HOSTS` com os hosts do MCP remoto (liga a proteção contra DNS rebinding).

## Lote do ProFloresta+ por estado (relatório para o desenvolvedor e folha do dono)

`raiz lote montar PA [--saida pasta/saida] [--destino pasta] [--creditos 1000000] [--cenario central_r11]` lê os
`desenvolvedor_<mun>.csv` do estado (só as fazendas com área para restaurar), monta o lote com o mesmo cálculo da ficha
e do pedido (raiz/lote.py) e grava em `<saida>/<UF>/lote/`: `lote_<UF>.csv` (todas as fazendas com o papel: titular,
reserva, mitigação, em espera), `lote_<UF>.json` (resumo, marcos, preço mínimo, terra destravada, certidões e
checklist), `relatorio_lote_<UF>.html` (para imprimir em A4) e `folhas_dono/folha_dono_<cod>.html` (titulares e
reservas). Responde quantos municípios entraram e, se não fecha 1 milhão com reserva, exatamente o que falta.

- Titulares: o P50 de créditos até o ano 25 que cumpre todos os marcos do Anexo IV com a tolerância (o do ano 7 pede
  ~1,14 milhão para um contrato de 1 milhão). Reserva: o que falta para 90% de chance (`lote.chance_alvo_reserva`),
  com o erro da captura comum ao lote (P10 de 0,6): ~1,87 milhão no P50. A escolha é o otimizador dos pedidos
  (opção mais barata, terra pronta: matrícula e concessão).
- Fluxo do lote: a soma dos fluxos do P50 das fazendas (`restauracao.fluxo_p50`, refeito a partir das entradas gravadas
  no `desenvolvedor_<mun>.csv`), com a dívida do Fundo Clima dimensionada no caixa do lote, a multa esperada dos marcos
  e o crédito além do contrato vendido ao preço depois do contrato. Daí a TIR e o preço mínimo por crédito para 12% e
  15% (com e sem dívida).
- O que destrava o lote: posse em titulação e assentamento (fazendas, ha, ha e créditos de regeneração) e o mesmo lote
  montado como se virassem título ou parceria (custo médio por crédito, TIR e chance dos marcos).
- Certidões: matrícula com certidão conferida (etapa `titulo_conferido`) separada da matrícula a conferir, e quantas
  certidões pedir (das maiores áreas por certidão primeiro; cartório e matrícula do `certidoes_<mun>.csv`) para ter 5%
  da área homologada na assinatura (`lote.area_homologada_assinatura`).
- Faixa do lote (E3): créditos até o ano 25 em soma (todas as fazendas errando juntas, a que dimensiona a reserva) e em carteira (um fator comum de Vasicek com 60% da variância, `carteira.fracao_comum`), com os campos da Portaria MME 102/2016 (P50, P90 de excedência, incerteza padrão; revisor independente pendente); a mesma premissa vale no pedido e nos documentos. Parcelas de campo por método (AR-TOOL03: 90% de confiança, 10% de erro, mínimo de 30). Tornado da TIR do lote: captura, custo, preço e câmbio no P10 e no P90.
- Checklist do edital: os 62 itens de raiz/regras/padroes/edital_profloresta.yaml, com a checagem automática quando os
  dados da Raíz dão conta e "a conferir" no resto.
- Folha do dono: tudo passa pela Raíz (contato, dúvidas e assinatura); quanto recebe por ha e por ano (P10 a P90) e o
  total em 40 anos; comparação com a renda do gado na mesma área (venda de bovinos por ha de pasto no município, Censo
  Agro 2017 corrigido pelo IPCA, e a sobra pela margem de referência da CNA) e com o aluguel do Censo. Sem nome, CPF
  ou CNPJ: só o código do CAR.

## Preparar o servidor de fichas e o pagamento de consultas

**Situação desta entrega:** roteiro e código preparados; não há servidor da Raíz implantado por este chat e nenhuma
venda foi ativada. `raiz/regras/padroes/precos.yaml` propõe pacotes de 1, 10 e 50 consultas, com `valor_rs: null`,
`status: provisorio` e o aviso literal **a definir pelo fundador**. Crédito de consulta não é crédito de carbono.

1. Provisionar uma máquina com Python 3.12+, `uv`, PostgreSQL 16/PostGIS 3.5, armazenamento privado e backups.
   O compose em `infra/docker-compose.yml` oferece o banco; sua porta fica em `127.0.0.1:5432`. Escolher o endereço
   HTTPS da API e um proxy que termine TLS; manter a porta do banco e a porta interna da API fora da internet.
2. Instalar a versão revisada do repositório com `uv sync --frozen --all-extras`. Criar um arquivo privado de ambiente
   a partir de `.env.example`, protegido contra leitura de outros usuários. Configurar `RAIZ_BANCO_URL`,
   `RAIZ_API_TOKEN`, `RAIZ_API_ORIGENS` com a origem exata do front e `RAIZ_CHAVE_PESSOAL`. A chave pessoal cifra o
   e-mail do comprador; nome, CPF e contato do dono não entram nas fichas de prospecção.
3. Injetar as variáveis no processo. Nos comandos manuais abaixo, `--env-file .env` faz essa injeção, inclusive para
   os módulos Pix que leem `os.environ`; não basta o arquivo existir. Aplicar as migrações antes de iniciar a API:

   ```bash
   uv run --env-file .env raiz banco migrar
   uv run --env-file .env raiz api --host 127.0.0.1 --porta 8000
   ```

   Em operação contínua, usar um gerenciador de processos com reinício, ambiente privado e logs sem tokens ou corpos
   de webhook. A migração 0026 cria carteira, compras, movimentos, desbloqueios, pedidos de contato e limites. Usar
   `head` para aplicar também as migrações posteriores. Carregar o funil vigente no banco pelo fluxo do executor.
4. Confirmar `/saude` e `GET /prospeccao/planos`. Nesta fase a resposta deve mostrar pacotes provisórios,
   `pix_modo: teste` e `pagamento_disponivel: false`, mesmo se alguém já configurou uma chave da AbacatePay.
   A ficha exige sessão individual e crédito pago; o token operacional não é token de cliente e nunca vai no build
   do front. A publicação estática continua só com agregados. Configurar `VITE_RAIZ_API` com o endereço HTTPS da API
   e reconstruir o front quando o servidor estiver pronto.
5. Preparar o envio real do link de entrada: o serviço de sessões já grava links de uso único e sessões, mas o
   adaptador `raiz.pedidos.servico.ENVIO_LINK` precisa estar ligado a um envio autorizado. Sem ele, o endpoint de
   entrada não entrega e-mail. Validar o ciclo de entrada e saída antes de oferecer fichas aos clientes.

### Catálogo aprovado e chaves reais, somente na futura ativação

O fundador precisa definir os valores e aprovar a política comercial. Depois disso, criar um YAML privado no mesmo
formato de `precos.yaml`, com uma nova `versao`, `status: aprovado`, `aprovado_em` em `AAAA-MM-DD` e os preços reais
positivos, em reais, com até duas casas decimais. `creditos` é a quantidade de consultas de cada pacote e pode ser
alterada no catálogo. Apontar `RAIZ_PRECOS_ARQUIVO` para esse arquivo. Não marcar o YAML provisório do repositório
como aprovado apenas para testar o botão.

O catálogo agora distingue `por_ficha`, `por_lote` e `assinatura`, com hipóteses de 1, 10 e 50 consultas;
o ciclo mensal da assinatura também é proposto. Fórmulas de receita e parâmetros de simulação ficam em
`docs/precos-e-receita.md`. A assinatura permanece indisponível mesmo com preço aprovado e Pix de produção:
cobrança e direitos por ciclo ainda precisam ser implementados. Preencher o YAML não ativa recorrência nem
autoriza tratar uma compra pontual de cinquenta consultas como assinatura. Conferir `pagamento_disponivel`
por item, além do indicador geral do catálogo.

O override `RAIZ_PROSPECCAO_PLANOS` aceita o mesmo envelope em JSON (`versao`, `status`, `aprovado_em`, `planos`).
Uma lista JSON no formato antigo continua legível, mas permanece provisória. Aprovação sem data ou sem preço válido
para ficha ou lote fecha o catálogo com erro; preço ausente nunca vira zero. A assinatura ainda não vendável pode
continuar sem preço. A compra congela pacote, quantidade e valor no banco, e a conciliação ou repetição idempotente
de compras antigas independe da mudança dos IDs no catálogo.

Na futura ativação autorizada, configurar os valores reais destas variáveis no servidor:

| Variável | Uso |
|---|---|
| `RAIZ_PIX_MODO` | `teste` por padrão; só o literal `producao` permite chamar o provedor. |
| `RAIZ_ABACATEPAY_CHAVE` | Chave privada da conta no ambiente e na versão compatíveis com o adaptador. |
| `RAIZ_ABACATEPAY_WEBHOOK_SEGREDO` | Segredo aleatório privado de pelo menos 32 caracteres, igual ao cadastrado no webhook. |
| `RAIZ_ABACATEPAY_WEBHOOK_CHAVE_PUBLICA` | Chave pública HMAC publicada pela AbacatePay, copiada da documentação oficial. |
| `RAIZ_PRECOS_ARQUIVO` | Caminho do catálogo aprovado, fora do repositório. |

Uma chave configurada, isoladamente, não ativa a compra. O catálogo precisa estar aprovado, com preços válidos, e o
modo Pix precisa ser explicitamente de produção. Uma resposta `devMode: true` do provedor continua sendo teste e
nunca libera crédito pago. Nenhum teste deste repositório faz pagamento real.

**Compatibilidade do adaptador:** `raiz/pedidos/pix.py` ainda usa a API legada v1 (`pixQrCode/create` e
`pixQrCode/check`, evento `billing.paid`). A documentação oficial atual descreve v2 (`transparents/*`). Conferir
com a conta se as chaves e webhooks v1 continuam disponíveis; se a conta só aceitar v2, manter vendas desativadas
e migrar o adaptador em uma entrega própria. A integração de produção não foi validada com uma conta real.

### Webhook de consultas e conciliação

Para consultas, cadastrar a URL HTTPS `https://<api>/pagamentos/prospeccao/abacatepay` no ambiente e versão
compatíveis do provedor. O webhook antigo `/pagamentos/abacatepay` pertence às reservas de lote; ele não credita
a carteira de consultas. Não chamar os endpoints de teste de reservas para tentar liberar fichas pagas.

O novo webhook exige as duas provas descritas na
[documentação de segurança da AbacatePay](https://docs.abacatepay.com/pages/notificacoes/seguranca):

- `X-Webhook-Secret`, ou o parâmetro legado `webhookSecret`, confere o segredo privado em tempo constante.
- `X-Webhook-Signature` contém HMAC-SHA256 em base64 dos bytes originais do corpo, usando a chave pública do
  provedor. Essa assinatura garante integridade; ela não substitui o segredo privado.

Preservar o corpo bruto no proxy. Preferir o segredo no cabeçalho e retirar a query dos logs quando a versão legada
a exigir. Segredo/assinatura ausentes ou inválidos devolvem 401; corpo acima de 256 KiB devolve 413. Eventos de
teste são ignorados. O código não grava o corpo recebido e não usa preços, quantidade de créditos ou cliente
informados pelo evento: identifica a compra local e confere novamente o pagamento pela API autenticada do provedor.
Somente o estado confirmado como pago credita a carteira. A trava da carteira e o movimento único por compra
impedem crédito duplicado por reentrega, concorrência ou consulta pelo navegador.

O comprador pode recuperar o histórico em `GET /prospeccao/compras` e conferir uma cobrança em
`GET /prospeccao/compras/{id}`, com sua própria sessão. O botão **Conferir pagamento** usa essa conciliação; se for
automatizada, respeitar intervalo de pelo menos 15 segundos e o limite de 15 verificações por minuto. Falha do
provedor no webhook responde 502 para permitir nova entrega; o polling cobre um evento perdido. Cobrança pendente,
expirada ou cancelada não gera saldo. Se o provedor corrigir posteriormente para paga, a conciliação ainda credita
uma única vez.

Antes da futura ativação, validar o fluxo em ambiente separado: assinatura errada não altera saldo, evento de teste
não libera ficha, reentrega não duplica crédito, o último crédito não abre duas fichas concorrentes e outra sessão
não lê a compra. A implementação está coberta por `testes/test_prospeccao_acesso.py` e
`testes/test_prospeccao_webhook.py`. Fontes consultadas para o protocolo:
[segurança](https://docs.abacatepay.com/pages/notificacoes/seguranca),
[Pix v2](https://docs.abacatepay.com/pages/transparents/create) e
[consulta de estado v2](https://docs.abacatepay.com/pages/transparents/check).

### Avisos de buscas salvas

Depois de migrar o banco até `0031` (buscas salvas, após `0030` da plataforma de agentes), executar
`uv run raiz prospeccao verificar-buscas` após cada carga do motor,
ou pelo cron do operador. O comando usa `RAIZ_BANCO_URL`, imprime somente as quantidades verificadas e sai com
erro se a consulta falhar. Para repetir uma única busca: `uv run raiz prospeccao verificar-buscas --busca <UUID>`.
Esta entrega fornece o comando; não instala uma agenda em produção.

A primeira gravação da busca guarda as correspondências sem avisar a base antiga. As próximas verificações
comparam códigos do CAR, independentemente da data do arquivo. Snapshot e avisos são gravados na mesma transação,
com trava por busca; repetir o job ou executá-lo em paralelo não duplica avisos. Os avisos aparecem somente na
conta do cliente e ocultam fazendas reservadas por outro cliente. O job não envia e-mail ou WhatsApp e não libera
fichas pagas. Cada cliente pode manter até 20 buscas salvas; excluir uma remove seu snapshot e seus avisos.

Crédito, risco e caminho da terra são filtros pagos: exigem compra real confirmada com movimento de crédito ou
liberação de ficha com débito auditado. A gravação e cada execução do job conferem essa habilitação; buscas que
a perderem ficam sem novos avisos e entram na contagem `buscas_sem_habilitacao`. Nenhuma nova cobrança é criada
ao filtrar. A pertinência de um CAR a uma faixa é parte desse serviço pago. Combinar filtro avançado com CAR exige
o código completo de uma ficha já liberada; prefixos não permitem deduzir seu valor.

Na lista autenticada, medidas, risco e caminho de uma ficha fechada são nulos. As somas de crédito e área
restaurável abrangem somente as fichas liberadas, com `escopo_metricas=fichas_liberadas` e a quantidade na
cobertura `totais.fichas_liberadas`; contagens, tamanho e sugestões de agrupamento mantêm o universo filtrado.
A ordem da lista é por CAR, sem revelar um ranking de crédito. O agregado regional aberto permanece separado,
sem filtros privados e com a supressão das métricas com menos de cinco fazendas. Os limites persistidos de
consulta continuam valendo para filtros, ficha, comparação e exportação.

## Proteção da main (o fundador ativa à mão)

Depois do primeiro CI desta entrega ficar verde, abra o repositório no GitHub, **Settings → Rules → Rulesets →
New branch ruleset**. Dê o nome `main protegida`, selecione **Active** e inclua o branch `main`.

1. Exija pull request antes de integrar. Para o fundador trabalhar sozinho, não exija aprovação de uma segunda
   pessoa; exija resolver todas as conversas abertas. Se houver revisor, pode exigir uma aprovação e invalidá-la
   quando o código mudar.
2. Em **Require status checks to pass**, selecione os oito checks do workflow **CI**: `workflows`, `segredos`,
   `front`, `seguranca`, `testes_python`, `referencia_para`, `checagens` e `e2e`. O check obrigatório antigo
   `checagens` agora é o portão final: reúne os dois relatórios e exige a aprovação estadual, preservando a
   proteção de quem já o exigia antes da divisão. Prefira a origem
   **GitHub Actions**, quando disponível. Marque
   **Require branches to be up to date before merging**. Os nomes só aparecem depois de uma execução.
3. Ative **Block force pushes** e **Restrict deletions**. Mantenha a lista de bypass vazia, incluindo para
   administradores, salvo uma política de emergência explícita. Não habilite merge automático do Dependabot
   sem passar pelos mesmos checks.
4. Salve. Confira em um PR de teste que merge com check pendente/vermelho e push direto na main são recusados.
   Para plano sem rulesets, use **Settings → Branches → Add branch protection rule**, padrão `main`, com as
   mesmas exigências e **Do not allow bypassing the above settings**.

A automação atual do motor atualiza `motor/README.md` por push direto. A proteção impedirá esse push: o chat
Dados/operação precisa transformar a atualização em PR. Não conceda bypass geral ao token para contornar isso.
Esta entrega documenta a configuração; não altera as regras da conta do fundador.

Em **Settings → Actions → General**, mantenha desabilitado o envio de tokens de escrita e de segredos para
workflows de PRs de forks, se essas opções forem oferecidas. A consulta administrativa dessa configuração
retornou 403 para a integração usada nesta entrega; seu estado não foi confirmado nem alterado. A guarda no
workflow não substitui a restrição de permissões do GitHub, porque um PR pode alterar seu próprio workflow.

Em **Settings → Code security**, habilite **Dependabot alerts**, **Dependabot security updates** e, quando
oferecidos pelo plano, **Secret scanning** e **Push protection**. `.github/dependabot.yml` já agenda atualizações
semanais de uv, npm, Cargo, Actions e imagens Docker. Gitleaks varre todo o histórico acessível em cada PR, mesmo
sem o recurso pago do GitHub; nunca publica o valor encontrado. As exceções verificadas são o nome exato de uma
coluna de `docs/colunas.md`, restrito ao arquivo, e uma ocorrência histórica de `KC_DB_URL` em
`infra/docker-compose.keycloak.yml:28`, commit `be05cee99ee060b5ca2c9e60d7b077d1fa2a51aa`. Esta última contém
somente esquema JDBC, serviço interno, porta e banco, sem usuário, senha ou parâmetros; as credenciais são
variáveis obrigatórias separadas. `.gitleaksignore` restringe a exceção ao fingerprint dessa ocorrência na branch
antiga, sem liberar outras URLs, arquivos ou commits. Credencial real encontrada deve ser revogada primeiro;
retirá-la do último commit não a apaga do histórico.

## CI e controles de segurança

São oito jobs: os testes gerais e o caso estadual rodam em paralelo; o portão final reúne seus resultados.
Não há filtro de caminhos nem retirada de testes. `setup-uv` guarda cache pelo
`uv.lock`, `setup-node` guarda o cache npm pelos locks, e o Chromium/LanguageTool têm caches separados. A instalação
continua travada (`uv sync --frozen --all-extras`, `npm ci`). Não se reutiliza `node_modules` de outro lock.

- `front` constrói o mesmo site público e executa os testes unitários, com geometrias de teste determinísticas.
- `testes_python` executa os testes Python gerais, inclusive PostGIS, Rust, cartão, vídeo, PDF e LanguageTool. Seu
  único `--deselect` é o caso estadual executado em `referencia_para`; uma regressão confere a seleção real para
  impedir que esse seletor esconda um teste vizinho. O corpo original do teste estadual é preservado.
- `checagens` exige os dois jobs aprovados e confere seus JUnits juntos: exatamente um estadual aprovado,
  nenhum caso duplicado, resultado ausente, falha ou skip novo. Permanece somente o xfail conhecido de TIR,
  que precisa ter executado; `xfail(run=False)` também reprova.
- `e2e` abre Chromium e usa API/PostGIS reais: link de entrada, milhão de créditos no Pará, três opções, interesse
  e reserva Pix local. E-mail e respostas dos donos são controlados; nenhuma credencial de pagamento real é
  aceita. Veja `testes/e2e/README.md`. Não há trace com tokens nos artefatos.
- `seguranca` verifica estilo, CPF/CNPJ e licenças Python instaladas, todos os pacotes dos locks npm e Cargo.
  Inventário ausente/ilegível falha. AGPL, SSPL, Business Source, EUPL e NC são bloqueadas; `BSL-1.0` é a licença
  Boost, permitida, enquanto Business Source (`BUSL-1.1`) é proibida. Exceções manuais não liberam licença proibida.
- `segredos` usa Gitleaks com saída ocultada; `workflows` valida todos os workflows com actionlint.

### Teste estadual privado do Pará

O teste usa as previsões reais e as entradas/geometrias congeladas da rodada `central_r11`: **144 municípios e
345.870 imóveis**, modelo `restauracao-2026d+a84f9789`. `scripts/testar_para_privado.py` ancora o manifesto e o plano
em SHA-256, confere os pacotes, o modelo, a cobertura e as identidades por município. Alteração de bytes, conjunto
incompleto ou modelo incompatível falha. O cálculo municipal não é repetido nem substituído por dados sintéticos.
**Lote e números** mantém a referência e precisa publicar uma nova versão compatível quando o modelo mudar.

O GitHub exige [acesso de escrita/push para ler releases em rascunho](https://docs.github.com/en/rest/releases/releases#list-releases);
a tentativa com `contents: read` foi recusada.
Por isso, somente o job interno `referencia_para` usa `contents: write`. Os demais mantêm leitura. A permissão é
do job inteiro, incluindo suas actions, que podem [acessar `github.token` implicitamente](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token#using-the-github_token-in-a-workflow); uma variável de ambiente
em um passo não reduz essa permissão. Não há operação de publicação nem credencial estática nova.

Apenas o processo de preparação recebe `RAIZ_DADOS_PRIVADOS_TOKEN=${{ github.token }}`. Ele executa
`uv run python scripts/testar_para_privado.py --preparar "$RUNNER_TEMP/raiz-pa"`, usando
`RAIZ_DADOS_PRIVADOS_URL=release-github://bernardoemmel/Raiz/dados-privados`. O checkout não persiste credenciais.
O pytest recebe somente `RAIZ_TESTE_PA_PASTA` e `RAIZ_TESTE_PA_OBRIGATORIO=1`; seu subprocesso usa um ambiente
restrito sem credenciais. Token ausente, acesso recusado, referência inválida ou falha de teste deixam o CI vermelho.

PR de fork não executa o job privilegiado, e `checagens` reprova explicitamente a validação estadual ausente.
Não se usa `pull_request_target` para executar código do PR. O token de execuções originadas pelo Dependabot
também pode permanecer limitado a leitura; nesse caso, depois de revisar a alteração, um mantenedor a promove
para uma branch confiável do repositório para executar a validação privada. Não conceder escrita ou segredos a
forks para contornar esse bloqueio.

O caso estadual ainda é tentado após falha da preparação, enquanto o job não estiver cancelado, e registra uma
falha fixa. Os testes gerais continuam no job independente. O caso estadual roda em subprocesso; stdout, stderr e JUnit internos
ficam em diretório privado temporário e são apagados também após erro, timeout ou interrupção. O JUnit público
recebe apenas sucesso ou mensagem fixa de falha; nomes, CARs, métricas por imóvel e diagnósticos internos não são
publicados. O portão final exige exatamente esse caso no conjunto dos dois relatórios, sem skip/xfail ou resultado ausente.

O snapshot fica fora do checkout, em pasta `0700`, sem cache ou artifact público. A etapa `always()` apaga
`$RUNNER_TEMP/raiz-pa`, inclusive após preparação incompleta. Os caches uv/npm/Chromium/LanguageTool continuam
restritos às dependências. Para executar localmente, prepare uma pasta privada fora do checkout com o mesmo CLI,
retire as credenciais do ambiente antes de executar o pytest com as duas variáveis `RAIZ_TESTE_PA_*` e apague a
pasta ao terminar; não publique o conteúdo nem os diagnósticos do subprocesso.

A execução real de referência levou **446,2 s (7 min 26 s)**, com pico de RSS de **6.840,2 MiB**. Download e preparo
levaram 9,4 s e 8 s, respectivamente; o conjunto preparado ocupou cerca de 1,42 GB. `testes_python` mantém o limite
de **30 minutos**; `referencia_para` tem **25 minutos**, em paralelo, e o portão `checagens` tem 5 minutos. A suíte anterior
levou 13 min 29 s; isolar o caso estadual evita somar seus 7 min 26 s ao caminho dos testes gerais. Essas medições
locais orientam o orçamento; o CI da entrega precisa confirmar o acesso ao draft e a duração no runner.

A API acrescenta cabeçalhos de proteção e `no-store` nas respostas autenticadas e de pedidos. Por padrão, há
120 chamadas por minuto/IP e 10 chamadas de login por minuto/IP; ajuste `RAIZ_API_LIMITE_MINUTO` e
`RAIZ_API_LOGIN_LIMITE_MINUTO`. O excesso retorna 429 com `Retry-After`. A contagem é por processo: com vários
workers/réplicas, configure também limite compartilhado no proxy. O proxy deve preservar corretamente o IP;
encaminhamentos arbitrários do visitante não devem ser confiados. HSTS depende de HTTPS reconhecido pela API.

Configure `RAIZ_LOGIN_BASE_URL=https://seu-dominio/Raiz/` para o destino canônico do link de entrada; sem ela,
usa-se a primeira origem de `RAIZ_API_ORIGENS`. O cabeçalho `Origin`/`Host` do visitante não escolhe o destino.
HTTP só é aceito para desenvolvimento local. O envio real de e-mail ainda depende da integração do produto.

Presidio e o modelo português instalado pelo lock limpam nomes e contatos nos logs, diagnósticos persistidos,
Healthchecks, Langfuse e erros publicados pelo executor. Se a análise falhar, o texto é suprimido. O access log
padrão do Uvicorn fica desligado para não gravar tokens de links/webhooks nas URLs. Isso não autoriza registrar
texto pessoal bruto: o reconhecimento de nomes tem falsos negativos. Mantenha apenas códigos internos e métricas
nos eventos. Limites da auditoria e pendências estão em `docs/passagem/qualidade-e-seguranca.md`.

### Conta e liberação por uma pessoa

`/v1/conta/gerenciar` é o destino humano dos erros 402 e de liberação pendente. Exige
SMTP e `RAIZ_API_PUBLICA_URL` configurados para o link de login voltar à origem oficial.
A página reutiliza a sessão da empresa, o contrato e as cobranças existentes. Só um
clique após ver os termos/valor aceita contrato ou gera Pix; abrir o link não paga nem
confirma nada. A confirmação financeira continua exclusivamente no webhook do provedor.

## Avaliação de modelos e arquivo cego (rodada 12)

O procedimento, contratos e comandos estão em [avaliação da rodada 12](modelo/avaliacao-rodada12.md).
Antes de treinar um candidato, o custodiante fixa plano, conjunto cego, previsões antigas, política de equidade
e controle estável. O CLI exige recibo anterior e reprova dados insuficientes, mudança de denominador, regressão
por subgrupo ou controle instável. Conservar o arquivo em armazenamento privado imutável com backup; separar a
conta de treino da conta que lê gabaritos. O portão emite decisão, não altera automaticamente o campeão atual.
A integração com a promoção e o retorno transacional é a pendência de Produto e regras indicada na passagem.

O CI executa os ensaios sintéticos no pytest completo, inclusive o solver real nas três opções. O job `seguranca`
confere os esquemas e constrói/inspeciona o wheel para bloquear scpi/vegan, inclusive dependências indiretas.
Esses resultados demonstram o funcionamento das checagens; não são métricas de acerto empírico do carbono.
O CI não cancela uma execução anterior ao chegar outro commit (`cancel-in-progress: false`).
A auditoria de promoções reexecuta o commit histórico fechado em um checkout isolado. O job Python usa
histórico Git completo; em clone local raso, execute `git fetch --unshallow` antes da suíte. Não substitua os
hashes do registro antigo pelos hashes da main nem altere as referências dos executores em andamento.

## Medição semanal de agentes

O workflow **Agente real semanal** (`agentes-real.yml`) usa `ANTHROPIC_API_KEY` dos segredos
do repositório, com acionamento manual e segunda às 06:00 de Brasília. Instruções
de ativação, limites, artefatos e códigos de saída estão em
[medicao-agentes-actions.md](medicao-agentes-actions.md). O banco da campanha é
descartável e sintético; não depende do servidor de produção nem usa o arquivo
privado. Sem a chave, o relatório indica campanha incompleta, não aprovação.

## Pasta do banco fiador (rodada 12)

Aplicar a migração **0035** pelo comando de migração já usado no servidor, depois
de 0032–0034. Guardar documentos/JSON/relatórios fora do diretório público. O
operador confere os documentos e usa `python -m raiz.pasta_fiador.operacao` para
validar e anexar versões; contrato e exemplos de comando em
[docs/pasta-fiador.md](pasta-fiador.md). Não há upload de modelo ou alteração de
conferência pelo cliente. Rascunho pode ter pendências, mas a geração falha enquanto
houver campo/documento obrigatório sem comprovação.

Exportações dependem das chaves `RAIZ_PROTECAO_CHAVES` e `RAIZ_PROTECAO_VERSAO`
configuradas no back-end. A API verifica acesso pago a todos os CARs e recalcula
validade/composição no momento da entrega. Testar com conta sintética, abrir os
HTML do banco e comprador e conferir referência, impressão e marca. As rotas
não enviam ao banco; o operador lê o relatório antes de entregar. Não ativam Pix,
assinatura ou envio a terceiros. O catálogo conservador Raíz não substitui as
exigências que um banco específico fornecer para revisão de regras.
