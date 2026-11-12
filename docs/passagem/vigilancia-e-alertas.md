# Passagem do chat "Vigilância e alertas"

Escrita em 12/11/2026, ao parar por fim de cota. Ramo: `claude/sharp-shannon-i0nhua`.

## O que este chat fez

| PR | O quê |
|---|---|
| #23 | Vigilância diária das fazendas e dos projetos (`raiz/vigilancia/`): MapBiomas Alerta, FIRMS, Ibama, DETER e PRODES cruzados com os polígonos do Release `dados`; regra da Verra (prazo, rascunho do relatório de perda, aviso ao cliente); rotas `/vigilancia/imovel/{cod}` e `/vigilancia/projeto/{id}`; agenda diária; aprendizado com a versão da regra |
| #22 | Regra no CLAUDE.md: cada chat junta a main, abre o PR e faz o merge com o CI verde |
| #34 | Plano E7 atualizado e alerta do pedido salvo da cena-alvo: fazenda nova que melhora o lote; fazenda do grupo com desmatamento, embargo ou matrícula cancelada |
| #39 | Backoffice do fundador, só leitura (E7 passo 6), e alertas de operação com escada ntfy e GoAlert (E7 passo 9); migração 0020 |
| #44 | Previsões no formato do hub e painel de acerto (E7 passo 5); cascata por confiança, rota do Qwen, teste próprio em português e llama.cpp com llguidance (E7 passo 10); migração 0021; esta nota |

## Onde parou

- E7 do `docs/plano-por-etapa.md`: passos 1 a 6, 9 e 10 feitos. O passo 8 está em parte: falta o cache calibrado da
  leitura de matrícula.
- O último código escrito é a cascata por confiança:
  - `raiz/modelos/cascata.py` (`Cascata.decidir` e `_nuvem`);
  - `raiz/modelos/rota.py`, `raiz/modelos/confianca.py`, `raiz/modelos/avaliacao/`;
  - `raiz/operacao/alertas.py` (`_cascata`).
- Está completa e testada. Os cortes de confiança estão vazios (`raiz/regras/padroes/cascata_cortes.yaml`), então a
  cascata segue na votação Qwen e Haiku até a calibração no servidor (tarefas 1 e 2 abaixo).

## O que falta, em ordem

1. **No servidor, subir o llama.cpp com llguidance.**
   - Ponha o GGUF `qwen3-4b-instruct-2507-q4_k_m.gguf` em `infra/modelos/`.
   - Rode `docker compose -f infra/docker-compose.yml up -d --build llama`.
   - Confira com `uv run raiz modelos testar --modelo qwen3-4b-instruct-2507`.
   - O Dockerfile (`infra/llama/Dockerfile`, tag b12300) nunca foi construído aqui. Se a construção falhar:
     - confira as opções do cmake na tag;
     - `LLAMA_BUILD_UI`, `LLAMA_USE_PREBUILT_UI` e `LLAMA_OPENSSL` desligadas só geram aviso na b12300.
2. **No servidor, calibrar a cascata.**
   - Rode `uv run raiz modelos calibrar`: roda as 120 tarefas x 3 tentativas no Qwen e grava
     `raiz/regras/padroes/cascata_cortes.yaml`.
   - Abra um PR só com esse arquivo.
   - Se uma tarefa sair "sem corte, fica na votação", é porque o acerto do que fica no Qwen não chegou a 95%. Isso é
     o esperado quando o Qwen erra muito: deixe assim.
3. **Comparar com o Haiku.** Rode `uv run raiz modelos avaliar --modelo triagem`. O relatório vai para
   `dados/avaliacao/` (fora do git). Anote o resultado no PR do passo 2.
4. **Agendar os alertas.** Ponha no cron do servidor `uv run raiz operacao alertas` de 15 em 15 minutos (veja
   `docs/operacao.md`, "Alertas com escalonamento"). Sem `RAIZ_NTFY_TOPICO` e `RAIZ_GOALERT_URL`, o envio é simulado
   e fica só registrado em `operacao.alerta`.
5. **Segredos que o fundador ainda precisa pôr** (no `.env` do servidor e nos segredos do GitHub para
   `.github/workflows/vigilancia.yml`):
   - `MAPBIOMAS_ALERTA_EMAIL` e `MAPBIOMAS_ALERTA_SENHA`;
   - `RAIZ_VIGILANCIA_CHAVE` (Fernet);
   - `RAIZ_PROJETOS_PRIVADO`;
   - opcionais: `FIRMS_MAP_KEY`, `RAIZ_NTFY_TOPICO`/`RAIZ_NTFY_TOKEN` e `RAIZ_GOALERT_URL`.
   - Não peça a chave ao fundador no chat: ele pediu envio simulado até lá.
6. **Prazo real da Verra.** O evento de perda `URTX_LE1` tem aviso à Verra (registry@verra.org) até 15/11/2026.
   O alerta `verra_aviso:URTX_LE1` sai como crítico. Confira em `/vigilancia/projeto/URTX` e lembre o fundador.
7. **E7 passo 8, cache calibrado da matrícula.** O código é do chat de Documentos (`raiz/documentos/certidao/`).
   Combine com ele antes de mexer.
   - Hoje a leitura traz `confianca` só como alta, media ou baixa.
   - A ideia: um escore numérico por leitura e um corte calibrado nos gabaritos (`raiz/documentos/aprendizado.py`).
   - Use o mesmo molde do `calibrar` da cascata: risco controlado no que não é relido. Só a leitura abaixo do corte
     volta a ser lida.
   - O plano pede MAPIE (BSD-3), que ainda não está no `uv.lock`.
8. **WhatsApp real e chaves de produção:** ficam para depois, por decisão do fundador.

## PRs abertos e ramos sem merge

- #44 é deste chat. Se estiver aberto, o motivo está no próprio PR. Com o CI verde, faça o squash merge.
- Os ramos locais `entrega3` e `entrega4` e o worktree `/home/user/raiz-e4` foram só de trabalho. O conteúdo deles
  está todo no #44; somem com o contêiner.

## Trabalhos no GitHub Actions

- **Vigilância diária** (`.github/workflows/vigilancia.yml`): todo dia às 09:17 UTC, publica no Release
  `vigilancia`.
- **Processar estados** (`processar-estados.yml`): é de outro chat. Não cancele: ele ocupa os runners e deixa o CI
  dos PRs na fila por até 40 minutos.
- **Como conferir:** pela aba Actions do repositório ou com a ferramenta `mcp__github__actions_list`
  (`list_workflow_runs`, `resource_id` igual ao nome do arquivo).

## Decisões e cuidados que não estão no código

- **Migrações:** antes de juntar a main, olhe `migracoes/versions/` dela. Duas sessões criaram a 0019 ao mesmo tempo;
  a nossa virou 0020, e a 0021 é a da cascata.
- **Banco de teste local:** depois de trocar de ramo, ele pode ficar numa revisão que o ramo não conhece (erro
  "Can't locate revision"). A saída é recriar:
  `psql -h /tmp -p 5433 -U raiz -d postgres -c "drop database raiz_teste" -c "create database raiz_teste owner raiz"`.
- **`uv run` com `UV_PROJECT_ENVIRONMENT` apontando para o .venv de outra pasta** reinstala o pacote `raiz` daquela
  pasta. Num worktree, crie um .venv próprio com `uv sync --frozen --all-extras`.
- **`testes/test_coleta_car.py`** falha aqui (dlt com banco por socket) e passa no CI. Rode a suíte local com
  `--deselect testes/test_coleta_car.py`.
- **CPF e CNPJ em teste:** escrever um literal derruba a varredura do CI. Gere os números na hora (`gerar_cpf` e
  `gerar_cnpj` no conftest).
- **Ações negadas neste ambiente:** clonar e compilar o llama.cpp e baixar o GGUF do Qwen. Por isso a rodada real é no
  servidor.
- **Força bruta no git:** force-push e amend de commit já enviado foram negados. Corrija a mensagem no squash do
  merge.
- **Confiança do Qwen:** é a menor probabilidade entre os tokens dos valores, com o softmax antes da gramática (padrão
  do llama-server sem `post_sampling_probs`). Não é calibrada; o corte é que é. O corte vale só para o modelo do
  arquivo (`modelo_local`): mudou o GGUF, recalibre.
- **`raiz modelos calibrar`** não grava cortes de relatório que não seja do modelo local (o simulado só mostra, salvo
  com `--cortes CAMINHO`).
- **O modelo simulado** (`raiz/modelos/simulado.py`) foi escrito junto com o banco e acerta 100% da intenção. É linha
  de base e teste de ponta a ponta; não mede qualidade.
- **Rótulos do banco de teste** (`raiz/modelos/avaliacao/banco.yaml`): mensagens que caberiam em dois rótulos ficaram
  de fora de propósito (por exemplo, "quero sim, quanto paga?"). Ao acrescentar tarefas, mantenha os 15% sem resposta
  válida.
- **Documentação do hubverse:** a busca pelas páginas dava 404. Lemos os repositórios clonados (hubDocs, schemas,
  flusight-dashboard). Esquemas: v6.0.0 das tarefas e v1.1.0 do predevals.
- **FastAPI:** importar `Request` dentro da função faz o FastAPI tratá-lo como parâmetro de consulta. Importe no topo
  do módulo.
- **`alertas.registrar(..., agora=)`:** usa o relógio da rodada em `criado_em`; os testes não dependem do dia.

## Comandos para rodar os testes desta parte

```bash
export RAIZ_BANCO_URL_TESTE="postgresql+psycopg://raiz@/raiz_teste?host=/tmp&port=5433"
uv run pytest -q testes/test_cascata_confianca.py testes/test_cascata.py testes/test_aceite.py
uv run pytest -q testes/test_operacao_alertas.py testes/test_aprendizado_hub.py testes/test_pedidos_banco.py
uv run pytest -q raiz/vigilancia/testes
uv run raiz modelos avaliar --modelo simulado --saida /tmp/avaliacao   # teste próprio sem servidor nem chave
uv run ruff check raiz testes scripts migracoes && uv run ruff format --check raiz testes scripts migracoes
uv run raiz privacidade varrer && uv run python scripts/checar_licencas.py
```
