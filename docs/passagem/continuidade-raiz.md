# Passagem única: documentos, título, vigilância, aprendizado e calendário

Atualizada em 13/11/2026. Substitui `documentos-titulo-e-aprendizado.md` e `vigilancia-e-alertas.md`.
O plano de entrega está em `docs/plano-por-etapa.md`; esta passagem guarda contexto, decisões e pendências.

## Urgência: URTX_LE1

**Prazo registrado: 15/11/2026** para o aviso do proponente a `registry@verra.org`. A Raíz não é proponente do
URTX: prepara somente o rascunho para o desenvolvedor cliente e **nunca envia o aviso**. Não existe estado
privado do URTX a restaurar. Campos desconhecidos ficam como **a preencher pelo proponente**; não pedir novos
dados sobre isso. O prazo em `raiz/vigilancia/projetos.yaml` aparece no projeto e no alerta crítico interno
`verra_aviso:URTX_LE1`, sem fabricar uma perda ou deduzir descoberta/área/causa.

Rascunho pronto em `docs/pedidos/urtx-le1-aviso-verra.md`, gerado por API/CLI/rodada diária em JSON e `.eml`.
Preparação não registra `verra_avisada`; envio e preenchimento cabem exclusivamente ao proponente.

## O que já está na main

- Documentos (#24): leitor de certidão pela Anthropic, conferência com `certidoes_<mun>.csv`, busca semanal,
  documentos docxtpl e aprendizado de leituras, em `raiz/documentos/`.
- Título/E8 (#35, merge confirmado em 12/11): regularização/achados, memorial/ODS/geometria D1 a D7/nota de risco,
  cadeia dominial, contexto/auditoria, sede pelo WhatsApp, laudo HTML/PDF, WARC cifrado e triagem; sorteio,
  Hájek/Olofsson, calibração por UF/porte, folds anuais da calibração e campeão/desafiante.
- Vigilância (#23): MapBiomas Alerta, FIRMS, Ibama, DETER/PRODES, cruzamento com os polígonos do Release `dados`,
  regra Verra, relatório de perda e aviso ao cliente, API, agenda diária e aprendizado por versão.
- Pedidos salvos (#34): alertas de fazenda nova que melhora lote e problemas no grupo.
- Operação (#39): backoffice só leitura, alertas e escada ntfy/GoAlert, migração 0020.
- Modelos (#44, merge confirmado em 12/11): previsões no formato hub e painel de acerto; cascata por confiança,
  rota curta Qwen, banco de 120 tarefas em português, Dockerfile llama.cpp/llguidance, migração 0021.
- Migrações corrigidas do título/aprendizado: **0022** achados, **0023** cadeia, **0024** sorteio, **0025** campeão.
  As antigas numerações das duas passagens não valem mais. #35 e #44 não precisam de novo merge.

## O que falta e quem pode concluir

1. **Aviso Verra:** entregue como rascunho ao desenvolvedor cliente; prazo registrado em 15/11/2026 e campos “a preencher pelo proponente”. A Raíz nunca envia. Não há pendência de estado privado URTX.
2. **E7 passo 8:** cache calibrado da matrícula implementado em `raiz/documentos/certidao/cache.py`. Escore numérico
   por leitura, corte calibrado em gabaritos da leitura integral e risco controlado; sem calibração suficiente,
   reler. Confiança declarada alta/média/baixa não prova acerto. MAPIE LTT implementado; ver `docs/cache-matricula.md`. Coletar a amostra real e calibrar antes da ativação.
3. **E8:** reexecutar motor/outros modelos por fold com scd2 `folds.como_estava`, e sobrevivência do aceite
   (tempo até aceite; lifelines MIT), implementados. Captura automática no executor com banco e seis adaptadores: motor, FLAG, restauração, regularização, triagem e rebanho. Catálogo parcial aceita só modelos com todas as fontes do corte. Actions sem banco também captura retratos imutáveis, guarda periodicamente/ao finalizar em Releases **privados em rascunho** `historico-AAAA-MM-DD` e importa na sincronização, sem nomes ou documentos pessoais. Datas observada e registrada são separadas; chegada atrasada preserva intervalos scd2, com deduplicação por hash. O histórico acumula desde as próximas execuções, sem retrodatação de tarefas antigas. Sobrevivência exige 30 contatos reais/5 aceites. Ver `docs/aprendizado-por-tempo.md`. Não usar camadas de hoje nos folds históricos.
4. **Servidor/modelos:** build local de llama.cpp b12300 com llguidance e Rust 1.100.0 corrigido e validado.
   Avaliação real concluída em 12/11/2026: 120 tarefas × 3, nenhuma falha técnica, 67,92% de acerto em intenção
   e 43,33% em compreensão. Nenhum corte atingiu 95%; o YAML gerado mantém cortes vazios e votação Qwen + Haiku.
   Relatório e hashes em `docs/operacao.md`; evidência bruta fora do git. Restam implantação em produção,
   sem acesso neste ambiente, e comparação com Haiku, sem credencial local. Nova calibração só com avaliação real;
   não forçar cortes para cumprir a faixa de subida.
5. **Cron operacional:** `uv run raiz operacao alertas` a cada 15 minutos; sem ntfy/GoAlert, simulado e registrado.
   Este ambiente não tem acesso SSH, banco ou credenciais de produção. Instalador idempotente pronto: `uv run python scripts/instalar_cron_alertas.py` mostra a prévia; `--instalar` aplica no servidor. Preparar o script não equivale a instalar no servidor.
6. **Segredos operacionais da passagem:** `MAPBIOMAS_ALERTA_EMAIL`, `MAPBIOMAS_ALERTA_SENHA`, `RAIZ_VIGILANCIA_CHAVE`,
   `RAIZ_PROJETOS_PRIVADO` somente quando existirem projetos privados (não exigido para URTX); opcionais `FIRMS_MAP_KEY`, `RAIZ_NTFY_TOPICO`, `RAIZ_NTFY_TOKEN`, `RAIZ_GOALERT_URL`.
   O estado dos secrets de produção/GitHub não pôde ser conferido neste ambiente. Configurar os que faltarem
   no servidor e na vigilância do GitHub, sem pedir valores no chat. Envio externo continua simulado.
7. **Calendário da Raíz:** implementado com migração 0027, 17 fontes oficiais, coleta diária Actions/Release,
   API `/eventos`, `.ics`, função MCP `proximos_eventos`, aba do site, selos por CAR e avisos de lotes simulados.
   Cancelamentos/retificações preservam UID; nenhuma pessoa ou documento pessoal persistido. CAR inferido por
   matrícula/SIGEF fica interno; consulta pública só mostra CAR explícito no edital. Ficha mantém acesso pago. Fonte sem chave
   CAR/CNS/SIGEF fica pendente. DJEN segue 403; DOE PA foi recuperado, diários selecionados pela cobertura real e PDFs/OCR isolados. Ver continuação abaixo.
   Ver `docs/calendario.md`. Site publica depois da coleta. No servidor, instalar o cron com
   `uv run python scripts/instalar_cron_alertas.py --tarefa calendario --instalar` após migrar o banco;
   não foi instalado em produção por ausência de acesso. `proximos_eventos` está registrada em `/mcp`, exige OAuth
   com `consultar` e só acessa o calendário já público, sem cobrança/aquisição de ficha ou relatório privado.
8. **Decisões já reservadas ao fundador:** SQLMesh/Dagster (o executor próprio continua nos E8 1/2/7); envio do
   convênio ONR (`docs/pedidos/onr-convenio.md`, E5 9); WhatsApp real e chaves de produção continuam adiados.
   MCGrad/mapaccuracy só após licença conferida; calibração e Olofsson próprios já implementados, sem depender deles.

## Decisões técnicas que precisam sobreviver à passagem

- CAR pendente (`PE`) não segura regularização; ocupação e limite de área a conferir seguram “pronta”.
- Geometria D3 a D7 por IoU; área e afastamento ficam na mensagem. Matrícula Python/SQL têm de normalizar igual:
  `5178.0` vira `5178`; `5.000` vira `5000`.
- `capture_http` do warcio não serve com requests já importado; WARC montado da resposta e cifrado por
  `RAIZ_CHAVE_PESSOAL`, pois o SIGEF pode trazer nome.
- Sorteio grava probabilidade de inclusão; Olofsson com fazendas muito grandes teve cobertura de cerca de 85%,
  não 95%. Folds por padrão exigem gabarito observado até corte; `--pelo-registro` exige também registro até lá.
- Confiança Qwen é a menor probabilidade dos tokens dos valores, softmax antes da gramática, sem
  `post_sampling_probs`. Corte vale só para o modelo calibrado; troca de GGUF exige recalibração.
- O simulado foi escrito com o banco de tarefas e não mede qualidade. Não gravar seus cortes em produção.
- Rotas FastAPI: importar `Request` no topo. Alertas usam o relógio da rodada em `criado_em`.
- Testes de dados de carga usam coluna `teste_marca`/datas próprias; triagem exige linhas novas.
  Gerar CPF/CNPJ de teste em memória; literal válido derruba a varredura.
- Cada worktree usa `.venv` próprio (`uv sync --frozen --all-extras`); não compartilhar `UV_PROJECT_ENVIRONMENT`.
- Antes de cada entrega, buscar main, conferir migrações e `uv run alembic heads`: uma cabeça só. Resolver
  conflitos, abrir PR e fazer merge com CI verde. Em entregas encadeadas, preservar a ancestralidade evita
  reapresentar alterações já revisadas. Sem force-push na main.
- Não cancelar “Processar estados” para liberar CI. “Vigilância diária” roda às 09:17 UTC; dados de clientes e rascunhos devem permanecer no arquivo privado; “Busca semanal” também já existe. Filas do CI podem levar até 40 minutos.

## Verificação de entrega

```bash
uv run ruff check raiz testes scripts migracoes
uv run ruff format --check raiz testes scripts migracoes
uv run raiz privacidade varrer
uv run python scripts/checar_licencas.py
uv run alembic heads
uv run pytest -q
```

A suíte de banco exige PostGIS e `RAIZ_BANCO_URL_TESTE` num banco **exclusivo de testes**: o fixture desfaz e
recria o esquema. Agentes em paralelo precisam de bancos separados. O teste de coleta CAR falhava no ambiente
antigo por conexão via socket; preferir TCP e executar a suíte inteira, como no CI.

## Continuação em ordem: entrega 1 — fontes

- DOE PA recuperado no índice `/pages/2026/` e PDF oficial de 12/11/2026. Leitura real de 137 páginas;
  verificação integrada com três visitas sem falha HTTP. Zero eventos nessa amostra não significa ausência de editais.
- Diários escolhidos diariamente por `estados.json` com `escopo=publico_basico`, município processado > 0:
  AC/AP/BA/CE/GO/MA/MG/PA/PI/RN/RO/RR/TO. UFs com zero não entram; não há piso de área ou número de fazendas.
  Uma nova UF sem fonte produz `cobertura_diarios=erro`, conservando as demais coletas.
- CAIXA: CSV nacional e detalhe individual; prova pública de matrícula só do mesmo bem. BB: destaques parciais.
  TRT16: índice + dois editais reais lidos; um leilão rural histórico, CAR pendente. Sem relação inequívoca ao CAR,
  o evento pode existir na agenda, mas nunca gera selo/alerta de uma fazenda presumida.
- HTTP transitório tem retentativas com espera; 401/403/CAPTCHA não têm contorno. PDF/OCR em RAM e subprocessos
  limitados; OCR sozinho e CAR de confrontante não confirmam vínculo. Identidade separa editais homônimos e praças.
  Retirar identificador ambíguo corrige o evento de correspondência única, conservando UID; não duplica a agenda
  nem conserva matrícula descartada como vigente. Releitura real da Fomento confirmou a correção.
- **Pendências externas:** DJEN continua 403 na API e caderno oficiais; BA/MG/TO tiveram indisponibilidade.
  A sondagem posterior também registrou leitura incompleta em AC/PI/RN/RO e restrição em RR. O índice PA oscilou;
  há consulta direta de PDFs ordinários oficiais como alternativa, mantendo extras/cobertura parcial explícitos.
  Não substituir a API de produção pelo ambiente de homologação. Não marcar fonte saudável só porque o índice abre.
- Evidência e limites em `docs/calendario.md`; resultado integrado em `/workspace/entregas/calendario-fontes/`, fora do git.
  Próximas entregas: avaliação/custo por documento, vigilância dos lotes e percurso da primeira certidão real.
- Coleta integral local conferida em 12/11/2026, depois da correção de UIDs: **50 eventos, 11 futuros, 198 visitas**,
  sem duplicatas exatas. Foram consultadas 31 fontes reais e a cobertura dos diários; o snapshot conserva também
  o estado histórico de MT (33 entradas de cobertura). PA parcial em 14 visitas; DJEN/BA/MG/TO em erro.
  Nenhum dos 50 eventos confirmou CAR; não se gerou alerta de fazenda presumida nem envio externo.
  Evidência: `/workspace/entregas/calendario-integracao-completa/`, fora do git. Isso é validação local;
  o resultado operacional publicado deve ser conferido na execução do workflow na main.
- `ANTHROPIC_API_KEY` ausente/vazia neste processo. Consulta de nomes de secrets no GitHub foi negada por escopo
  da integração (403), portanto não prova presença nem ausência em produção. Nunca pedir ou imprimir seu valor.
- Release `dados` agora contém somente cadastro básico/agregados. `dados-privados` e históricos completos são
  **rascunhos privados**; nunca publicar esses Releases nem usar `dados/amostra` como previsão real de certidão.

## Entrega 2 — avaliação da cascata

- `raiz modelos avaliar-cascata --documentos <manifesto-privado>` pronto. Qwen primeiro nas tarefas curtas
  compatíveis; confiança baixa/sem corte aprovado chama Haiku. PDF visual/entrada longa registra o motivo da
  rota direta. Toda tentativa/modelo/tokens/cache/preço/duração entra no custo por hash do documento.
- Acerto exige gabarito humano integral com origem e data. Sem rótulo, acerto é `null`; uso ou preço não informado
  deixa custo desconhecido. Custo da máquina local é separado da tarifa de API e não foi presumido gratuito.
- As 120 tarefas de aceite continuam explicitamente um benchmark de tarefas, nunca um conjunto de certidões.
  Tentativa real do comando em 12/11/2026 parou antes das chamadas: `ANTHROPIC_API_KEY` ausente/vazia;
  `RAIZ_ANTHROPIC_API_KEY` também não encontrada. Nenhuma medição Haiku foi produzida.
- Detalhes, contrato do manifesto privado e comando de retomada: `docs/avaliacao-cascata-documentos.md`.
  Os cortes locais continuam vazios; nenhuma avaliação sintética os aprovou.

## Entrega 3 — vigilância dos lotes

- Workflow diário às 06h17 de Brasília usa `rodar --lotes`, DETER, MapBiomas Alerta e FIRMS NOAA-20/21.
  Recorta os polígonos pelas fazendas de pedidos não cancelados de clientes ativos, sem excluir fazendas pequenas.
  Geometria ausente é cobertura parcial, nunca licença para ampliar o monitoramento a todos os imóveis.
- Banco real identifica o dono. Sem banco, exige `lotes-vigilancia.json` no Release privado em rascunho,
  renovado há no máximo 36 horas. `lotes-ciclo --publicar` e o instalador de cron `vigilancia_lotes` fazem a ponte
  automática servidor/Actions/painel a cada 15 minutos; implantação real ainda depende de acesso ao servidor.
- Relatórios na rota `/v1/pedidos/{id}/vigilancia/relatorios` e `.md`, somente pessoa autenticada da empresa
  liberada e dona do pedido. A projeção genérica de alertas não expõe o rascunho. Revalida dono/fazenda ao importar.
- Um rascunho por fato/dono; NOAA no mesmo CAR/dia não soma pixels como área queimada. Foco é indício, não perda
  confirmada. Causa, estoque, área afetada, proponente e prazo regulatório ficam a conferir; nenhum projeto Verra
  é fabricado a partir de um lote. Todas as evidências falsas descartam também o rascunho já preparado.
- **Operação pendente:** o arquivo privado acessível não tinha `lotes-vigilancia.json` nem `vigilancia.json`;
  sem banco/servidor real não é possível atribuir lotes a clientes por suposição. NOAA-20/21 e DETER responderam
  em consultas reais; MapBiomas retornou “Token de acesso inválido” para alertas, apesar do índice público abrir.
  Exige as credenciais MapBiomas já documentadas. Nada foi enviado a clientes, proprietários ou Verra.
- Contrato e ativação em `docs/vigilancia-lotes.md`; dados privados nunca vão ao Release público ou ao cache do Actions.

## Entrega 4 — quando chegar a primeira certidão

- API principal recebe PDF em `POST /documentos/certidoes`, com sessão de pessoa da empresa liberada,
  pedido e CAR autorizado. Original e previsão ficam cifrados em armazém privado separado por empresa.
  Nunca usar `dados/amostra` como previsão real; na API, a projeção vem da rodada vigente do PostGIS.
- Previsão é congelada antes de ler, com hash/data. Validação de PDF isolada (20 MiB, 100 páginas, sem senha,
  conteúdo ativo ou anexos), idempotência, limites de armazenamento, leitura explícita e recuperação de interrupção.
- Leitura/gabarito/sincronização exigem operação interna. Gabarito humano separado da previsão, com origem/data,
  campos técnicos fechados e declaração de conferência. Um cliente ou modelo não pode promover sua saída a verdade.
  Sem previsão anterior, não grava suposto erro do motor; sem custo informado, não grava zero inventado.
- Referências E8 incluem a empresa; data de captura impede retrodatação pela emissão da certidão.
  Original fica cifrado para leitura e prova; a API não devolve o PDF bruto com CPF/CNPJ. A pessoa revisora usa a via
  recebida do proponente. Nenhum PDF, nome, CPF/CNPJ ou texto bruto vai a treino/log/site.
- **Ainda falta a primeira certidão real** e sua conferência humana. Os testes não constituem conjunto de avaliação
  nem autorizam calibrar E7/E8. Procedimento completo e rotas: `docs/primeira-certidao.md`.

As entregas desta continuação estão nos PRs [fontes #87](https://github.com/bernardoemmel/Raiz/pull/87),
[cascata #88](https://github.com/bernardoemmel/Raiz/pull/88),
[vigilância #91](https://github.com/bernardoemmel/Raiz/pull/91) e
[primeira certidão #92](https://github.com/bernardoemmel/Raiz/pull/92), nessa ordem.

## Fechamento da integração MCP do calendário

- `proximos_eventos` aparece na descoberta do SDK oficial; tipos, UF, período, CAR e limite são validados.
  A ponte chama exclusivamente `GET /eventos`, com as mesmas proteções de OAuth/escopo/prazo do servidor.
- Projeção positiva conferida pelo manifesto de fontes preserva UID e CAR íntegros. Não expõe CNS, matrícula,
  SIGEF, CAR inferido, nome do proprietário nem textos livres; o nome institucional vem do manifesto revisado.
- É a consulta do calendário já público, sem consumo de crédito ou liberação de ficha. Os requisitos comerciais
  das demais ferramentas continuam sendo aplicados nas suas próprias rotas.
- Alterações do coletor/workflow na main disparam uma rodada, além da agenda diária. Conferir seu resultado
  publicado: indisponibilidade externa pode deixar o job vermelho depois de publicar o snapshot útil.

## Compatibilidade da publicação — 13/11/2026

- PR #97 integrado com CI verde. A árvore final, incluindo a main do PR #93, passou nos 129 testes de calendário/MCP.
  O CI aprovou 2.580 testes gerais, o caso real do Pará e a conferência dos relatórios. A nova execução somente da
  conferência final preservou os oito jobs aprovados; nenhuma exigência de teste foi removida.
- A coleta automática `43362263763` parou antes de consultar as fontes: `gh release download dados` respondeu
  `release not found`. O manifesto continuava acessível no endereço público. O workflow passa a usar
  `carregar_manifesto`, com limite de bytes e validação de cobertura. As operações do Release do calendário
  fixam o repositório pelo contexto do workflow e conservam o estado anterior.
- A publicação `43362263677` parou no manifesto público: GO já tinha o campo agregado `processamento`, ainda não
  reconhecido pelo leitor. O PR #95 foi integrado à main durante a verificação e corrigiu essa compatibilidade:
  versão, UF/unidade, soma das contagens, intervalos e fusos explícitos; extras privados são recusados antes de
  baixar qualquer pacote. A correção própria desta continuação ficou restrita ao acesso ao manifesto na coleta.
- O leitor também confere a origem cadastral do CAR e o recorte por seus códigos IBGE; não presume que a UF de
  cadastro tenha de coincidir com o recorte. Uma observação nova ou retirada atualiza o cache sem renovar seus horários.
- O download real dos 16 pacotes públicos foi conferido com o leitor do PR #95; o calendário seleciona as 13 UFs
  que têm municípios processados. Nenhum pacote privado foi publicado ou convertido em público.
- A publicação do site `43364180632` passou na main do PR #95. Os JSON/ICS servidos continuavam iguais ao
  snapshot anterior: 43 eventos, seis futuros. Isso não foi confundido com a coleta ampliada local.
- Nova coleta real em 13/11, com o coletor já integrado: 50 eventos, 11 futuros, 191 visitas nesta rodada
  (197 no retrato que inclui o histórico de MT), 31 fontes consultadas e a conferência de cobertura dos diários.
  Zero duplicatas exatas e zero CAR confirmado. JSON, estado e ICS passaram na validação e no mascaramento.
  PA parcial; DJEN/BA/MG/TO continuam em erro, sem simular sucesso ou atribuir evento a fazenda presumida.
- O upload local ao Release público retornou 401 após remover os assets anteriores. As duas cópias foram
  preservadas e o site continuou servindo o retrato anterior. A execução operacional `43366965069` restaurou
  os três arquivos públicos com sucesso; hashes do Release conferidos byte a byte contra a coleta validada.
  A publicação do site `43367227736` passou: JSON e ICS do site têm os mesmos hashes da coleta e do Release,
  com 50 eventos, 11 futuros. Não repetir upload local com `--clobber` neste ambiente:
  a autenticação funcionou em `api.github.com`, mas foi recusada em `uploads.github.com`.
  Evidências em `/workspace/entregas/calendario-13nov-main/`, fora da branch de produto.
- Validação local antes do PR: 2.890 testes Python aprovados, um teste opcional pulado e uma divergência esperada,
  incluindo a referência real do Pará; 338 testes do front e build na base #95. Ruff/formatação, actionlint,
  privacidade, gitleaks e 857 licenças conferidos. Main #98 incorporada sem conflito, preservando a migração 0035;
  a correção do calendário não acrescenta migração. Na árvore atualizada passaram 205 testes de calendário/MCP,
  pasta e API, mais 341 testes do front e build. O teste local pulado requer `RAIZ_LANGUAGETOOL_URL_TESTE`;
  o CI fornece esse serviço e confere a suíte integral sem dispensar suas exigências.
