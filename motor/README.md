# Motor de dados da Raíz

> Publicação atual (12/11/2026): dados completos e históricos por CAR ficam no
> arquivo privado autenticado, configurado por `RAIZ_DADOS_PRIVADOS_URL` e
> `RAIZ_DADOS_PRIVADOS_TOKEN`. O Release público contém somente agregados e
> situação básica do CAR; não publicar camadas detalhadas, vigilância por CAR,
> artifacts ou caches completos no público. Ver [contrato de publicação](../docs/dados-publicados.md).


Funil por imóvel do CAR, município por município, para o Brasil inteiro. Roda sozinho no GitHub Actions e preserva o resultado completo no arquivo privado.
O Release [`dados`](https://github.com/bernardoemmel/raiz/releases/tag/dados), de onde o front baixa, recebe apenas a projeção básica. Ninguém precisa
baixar nem subir nada à mão. O que cada coluna significa está em [`docs/colunas.md`](../docs/colunas.md).

## Painel

Atualizado sozinho a cada publicação (`painel.py`, a partir do `estados.json`). "Feitos" conta os municípios com o
funil pronto, inclusive os que não têm nenhum imóvel no CAR (ex.: Uiramutã, RR, toda dentro de terra indígena). Um estado
está completo quando tem, em todos os municípios, funil, filtros, MapBiomas, direto, TMF e causas da perda e a APP pela
escadinha. Os extras do Earth Engine e as certidões ficam de fora dessa conta (ver abaixo).

<!-- painel:inicio -->
Gerado do `estados.json` de 13/11/2026 17:57 (horário de Brasília). Brasil: 1.481 de 5.571 municípios com o funil pronto; 4 de 27 estados completos.

| Estado | Municípios feitos/total | Situação | Última atualização | Motor |
|---|---|---|---|---|
| PA Pará | 144/144 | falta APP escadinha 63, FLAG 144, caminho da terra 144, ficha 144, desenvolvedor 144 (2 fatias em jobs separados) | 12/11/2026 13:12 | [9365d63](https://github.com/bernardoemmel/Raiz/actions/runs/43230460294) |
| RO Rondônia | 52/52 | completo | 12/11/2026 12:50 | [41f8e22](https://github.com/bernardoemmel/Raiz/actions/runs/43241594895) |
| RR Roraima | 15/15 | completo | 12/11/2026 11:17 | [9365d63](https://github.com/bernardoemmel/Raiz/actions/runs/43230460294) (parte manual) |
| AC Acre | 22/22 | completo | 12/11/2026 11:38 | [9365d63](https://github.com/bernardoemmel/Raiz/actions/runs/43230460294) (parte manual) |
| AP Amapá | 16/16 | completo | 12/11/2026 11:29 | [3537575](https://github.com/bernardoemmel/Raiz/actions/runs/43235780981) (parte manual) |
| TO Tocantins | 101/139 | falta funil 38, MapBiomas 1, direto 1, TMF e causas 1, FLAG 1, caminho da terra 1, ficha 16, desenvolvedor 16; 32 erro(s) na última rodada (2 fatias em jobs separados) | 13/11/2026 17:53 | [e959023](https://github.com/bernardoemmel/Raiz/actions/runs/43502960013) (parte manual) |
| MA Maranhão | 52/217 | falta funil 165, ficha 4, desenvolvedor 4; 171 erro(s) na última rodada (2 fatias em jobs separados) | 13/11/2026 17:55 | [e959023](https://github.com/bernardoemmel/Raiz/actions/runs/43492466362) |
| AM Amazonas | 0/62 | falta funil 62 | — | manual |
| MT Mato Grosso | 12/142 | falta funil 130; 59 erro(s) na última rodada (2 fatias em jobs separados) | 13/11/2026 14:09 | [e959023](https://github.com/bernardoemmel/Raiz/actions/runs/43464184451) |
| GO Goiás | 18/246 | falta funil 228, MapBiomas 1, direto 1, TMF e causas 1, FLAG 1, caminho da terra 1, ficha 1, desenvolvedor 1; 236 erro(s) na última rodada (3 fatias em jobs separados) | 13/11/2026 00:31 | [5e57203](https://github.com/bernardoemmel/Raiz/actions/runs/43244609528) |
| MS Mato Grosso do Sul | 0/79 | falta funil 79 | — | manual |
| MG Minas Gerais | 3/853 | falta funil 850; 746 erro(s) na última rodada (8 fatias em jobs separados) | 12/11/2026 14:42 | [5e57203](https://github.com/bernardoemmel/Raiz/actions/runs/43244609528) |
| BA Bahia | 155/417 | falta funil 262, ficha 3, desenvolvedor 6 (4 fatias em jobs separados) | 12/11/2026 20:55 | manual |
| PI Piauí | 204/224 | falta funil 20, MapBiomas 3, direto 2, TMF e causas 3, FLAG 3, caminho da terra 3, ficha 6, desenvolvedor 6; 4 erro(s) na última rodada (2 fatias em jobs separados) | 13/11/2026 00:03 | [2b6e8af](https://github.com/bernardoemmel/Raiz/actions/runs/43348915128) |
| CE Ceará | 97/184 | falta funil 87, MapBiomas 1, direto 1, TMF e causas 1, FLAG 1, caminho da terra 1, ficha 4, desenvolvedor 6; 2 erro(s) na última rodada (2 fatias em jobs separados) | 12/11/2026 21:39 | [6f49dfc](https://github.com/bernardoemmel/Raiz/actions/runs/43336447278) |
| RN Rio Grande do Norte | 84/167 | falta funil 83; 2 erro(s) na última rodada (2 fatias em jobs separados) | 13/11/2026 00:04 | [cf30625](https://github.com/bernardoemmel/Raiz/actions/runs/43338043811) |
| PB Paraíba | 0/223 | não começou | — | — |
| PE Pernambuco | 0/185 | não começou | — | — |
| AL Alagoas | 0/102 | não começou | — | — |
| SE Sergipe | 0/75 | não começou | — | — |
| ES Espírito Santo | 0/78 | não começou | — | — |
| RJ Rio de Janeiro | 0/92 | não começou | — | — |
| SP São Paulo | 291/645 | falta funil 354, MapBiomas 1, direto 1, TMF e causas 1, FLAG 1, caminho da terra 1, ficha 1, desenvolvedor 1; 41 erro(s) na última rodada (6 fatias em jobs separados) | 13/11/2026 10:33 | [6e69cc0](https://github.com/bernardoemmel/Raiz/actions/runs/43427422930) |
| PR Paraná | 154/399 | falta funil 245, MapBiomas 3, direto 3, TMF e causas 3, FLAG 3, caminho da terra 3, ficha 3, desenvolvedor 3; 24 erro(s) na última rodada (4 fatias em jobs separados) | 13/11/2026 10:50 | [6e69cc0](https://github.com/bernardoemmel/Raiz/actions/runs/43403684811) |
| SC Santa Catarina | 61/295 | falta funil 234, MapBiomas 2, direto 2, TMF e causas 2, FLAG 2, caminho da terra 2, ficha 2, desenvolvedor 2 (3 fatias em jobs separados) | 13/11/2026 12:49 | manual |
| RS Rio Grande do Sul | 0/497 | falta funil 497 (APP a conferir na primeira rodada automática); falha nas fontes obrigatórias; 1 erro(s) na última rodada (5 fatias em jobs separados) | 13/11/2026 12:55 | [1c8a8d7](https://github.com/bernardoemmel/Raiz/actions/runs/43452405013) |
| DF Distrito Federal | 0/1 | não começou | — | — |
<!-- painel:fim -->

## Como roda sozinho

Workflow [`processar-estados.yml`](../.github/workflows/processar-estados.yml), toda segunda-feira às 02:23 (Brasília)
e quando alguém dispara à mão. O trabalho município a município é do **executor do produto** (`raiz executor`, em
[`raiz/executor/`](../raiz/executor/)): ele roda o motor e as tarefas do produto (FLAG, caminho da terra, ficha,
desenvolvedor), guarda uma marca por município com a versão de cada tarefa, retoma de onde parou e publica no Release.
O `rodar_estado.py` organiza a rodada em volta dele:

1. **Planejar** (`rodar_estado.py --planejar`): lê o `estados.json` publicado e escolhe as **unidades** de trabalho.
   Estado com até 120 municípios é uma unidade; estado maior vira **fatias** de até 120 municípios, em faixas de
   longitude (cada job baixa só os blocos da faixa dele), que rodam em jobs separados ao mesmo tempo: MG 8, SP 6, RS 5,
   BA 4, PR 4, SC 3, GO 3 e PA, TO, MA, MT, PI, PB, PE, CE, RN 2 cada (62 unidades no Brasil). Duas filas:
   - **novo**: estado que não começou ou com o funil incompleto. Pega as vagas primeiro, na ordem PA, RO, RR, AC, AP,
     TO, MA, AM, MT, GO, MS, MG, BA, PI, CE, RN, PB, PE, AL, SE, ES, RJ, SP, PR, SC, RS, DF;
   - **manutenção**: funil pronto, mas falta tarefa nova do produto, o código de uma tarefa mudou, o estado é de antes
     do executor (adotar) ou não roda há 6 dias ou mais (o executor refaz só o que mudou nas fontes: CAR, alertas,
     MapBiomas). Só usa as vagas que sobram, e no máximo 4 ao mesmo tempo: nunca segura vaga de estado novo.
   O modo próximo repõe todas as vagas livres; o cron de 15 minutos drena pedidos persistidos e repõe UFs
   incompletas, sem começar manutenção. A admissão CAS inclui motor, lotes e catálogo no teto global de 15.
   São até 15 jobs ao mesmo tempo (o GitHub dá no máximo 20 máquinas ao mesmo
   tempo para o repositório inteiro; 5 ficam livres para o CI dos PRs, o site e o planejamento das rodadas).
2. **Preparar** (`rodar_estado.py --preparar`): baixa uma vez por dia os arquivos nacionais (lista de municípios,
   embargos do Ibama, biomas, geobr, TMF, causas da perda) e guarda no cache comum privado autenticado.
3. **Um job por unidade** (`rodar_estado.py <UF ou fatia, ex. MG-3> --executor`):
   - baixa as fontes do estado (MapBiomas Alerta, os 5 temas do MapBiomas, geobr, TMF, causas) antes de tudo, para a
     assinatura de cada município no executor já nascer com elas;
   - estado publicado antes do executor (sem marcas): roda a APP pela escadinha (`raiz_app.py`) onde ela falta, põe o
     `imoveis_` novo no armazém e só então adota (`raiz executor adotar`), sem refazer o funil;
   - chama `raiz executor rodar --ufs <UF> --lanes 3 --ate-minutos <o que sobra>` (fatia: `--municipios` com os da
     fatia); o executor para de começar municípios no prazo, dá 10 min de folga aos que estão em curso e publica;
   - se houver GeoTIFF do Earth Engine em `extras/`, roda `raiz_extras.py` e põe o resultado no armazém;
   - publica de novo com a rodada (commit, versões, se parou pelo prazo, erros) e atualiza o painel acima.
   Publicar tem duas travas (tags criadas pela API, que só um job consegue criar por vez): a do estado
   (`trava-publicar-<UF>`), dentro da qual o job relê o pacote publicado, junta com o que fez (o que outras fatias do
   mesmo estado já publicaram entra; o que este job gravou fica) e sobe; e a do `estados.json`
   (`trava-publicar-dados`), dentro da qual ele relê o índice e troca só a entrada do estado. Fatia publica no meio da
   rodada de hora em hora (o pacote sobe inteiro), refaz no fim o `resumo_<UF>.csv` do estado inteiro e anota a rodada
   dela em `motor.fatias`.
4. **Prazo de 5h30 por job**: se a unidade parou pelo prazo e avançou, o job dispara o workflow de novo só para ela; se
   terminou, passa a vez ao próximo da fila. Unidade que parou sem avançar nenhum município não se dispara de novo
   (a rodada semanal tenta outra vez).

### Preservação e retomada

Antes do cálculo, o workflow restaura o checkpoint privado da unidade. Ao sair do executor, mesmo com falha de
publicação, salva resultados, marcas, sidecars originais e retratos opacos antes de finalizar metadados e atestações.
O salvamento confere cada pacote por download e hash. Nenhum dado completo é enviado a artifacts públicos.
Uma falha periódica de publicação deixa o cálculo continuar; a falha final continua visível no resultado do job.
A retomada confere bytes, hashes, versões e assinaturas: resultados íntegros são pulados e saídas divergentes
são recalculadas. O checkpoint não valida cientificamente um retrato e não recupera o que nunca foi salvo.
O prazo do executor reserva tempo para esses passos finais; uma perda abrupta do runner antes deles ainda
depende da última publicação/checkpoint concluído.

O painel municipal está documentado em `docs/processamento-por-estado.md`.

### Quando uma fonte recusa o GitHub

SICAR, TerraBrasilis, SIGEF, MapBiomas (API e Alerta), Zenodo e geobr podem limitar pedidos ou ficar fora do ar. Os
scripts esperam e tentam de novo com espera crescente (30 s, 1, 2, 4 e 8 min, ou o tempo que a fonte pedir no
`Retry-After`), escrevem cada tentativa no log do job e seguem para o próximo município; o município que falhou entra
de novo na próxima rodada. Se uma etapa junta 8 erros seguidos, a fonte está fora do ar: a etapa para, as outras seguem,
e ela tenta de novo no fim (depois de 10 e de 30 min, se der tempo). Os erros aparecem no resumo do job, no `estados.json`
(campo `erros`) e no painel. O funil não roda sem o MapBiomas Alerta e sem o MapBiomas (cobertura e desmatamento), porque
sem eles as colunas `problema` e `frente` sairiam erradas sem aviso: fica para a próxima rodada.

### Versão do motor

Cada município tem uma marca no Release (`raiz_controle_<UF>.json`) com a versão de cada tarefa (hash do código de
que ela depende, `raiz/executor/tarefas.py`), a assinatura das fontes do município e o sha256 de cada arquivo; cada
arquivo do pacote leva tarefa, versão e data (`_versoes.json`). O `estados.json` guarda, por estado, as versões das
tarefas (`versoes`), a versão do motor (`motor_versao`) e, no campo `motor`, o commit que rodou, as tarefas adotadas
de antes do executor (`legado`) e a rodada. Mudou o código de uma tarefa: o executor refaz só ela, e só onde a saída
dela muda o que vem depois. O aprendizado compara previsões entre versões por esses campos.

Sem o executor (no computador, `rodar_estado.py <UF>` sem `--executor`), a versão de cada tabela é um hash do código
sem comentários nem docstrings (`raiz_situacao.ETAPAS`), e uma tabela feita com código antigo é apagada e refeita.

### Rodar à mão

No GitHub: Actions, "Processar estados (motor)", "Run workflow". Campos:

- `ufs`: estados ou fatias separados por espaço (ex.: `TO MA` ou `MG-3`; um estado grande vira todas as fatias dele).
  Vazio: o plano automático, com as duas filas.
- `refazer`: tarefas para refazer nesses estados (`funil`, `filtros`, `mapbiomas`, `direto`, `extras_direto`, `flag`,
  `terra`, `ficha`, `desenvolvedor`, `extras` ou `tudo`; várias com vírgula): a marca da tarefa é apagada e o executor
  a refaz. Ex.: uma fonte publicou ano novo. Refazer o funil refaz tudo. Sem `ufs`, vale para todos os publicados.
- `continuacao`: uso interno das continuações automáticas.

No computador (da pasta `motor/`):

```bash
uv sync --all-extras
uv run python rodar_estado.py TO --executor   # como o Actions (sem GH_TOKEN, lê o Release e não publica)
uv run raiz executor plano --uf TO              # o que o executor rodaria em cada município
python rodar_estado.py TO              # só o motor, sem o executor, em saida/TO/
python rodar_estado.py --planejar      # quais estados precisam rodar
python raiz_estado.py PA 1504950       # só o funil de um município
python painel.py                       # atualiza o painel deste README com o estados.json publicado
```

### Insumos opcionais (Release `insumos`)

Arquivos que não vêm de API pública e que o job baixa se existirem no Release `insumos`:

- `raiz_extras2_<UF>*.tif` ou `raiz_extras_<UF>*.tif`: o histórico exportado uma vez do Earth Engine (`gee/`, pasta
  `raiz_extras_v2` do Drive). Sem eles a etapa `extras` é pulada; com eles, roda.
- `projetos_carbono.tar.gz`: mapas dos projetos de carbono já registrados (pasta `projetos_carbono/`), para a frente
  `ja_tem_projeto`.

O MapBiomas Alerta não precisa mais de arquivo: vem do WFS público da plataforma (`maps.alerta.mapbiomas.org`).

## Scripts

| Script | O que faz |
|---|---|
| `rodar_estado.py` | organiza a rodada: planeja, prepara o cache, roda o estado pelo executor (`--executor`) ou só o motor, e continua |
| `raiz_estado.py` | funil principal: CAR (SICAR), embargos (Ibama), PRODES, TI, UC e hidrografia (TerraBrasilis), SIGEF (INCRA), MapBiomas, MapBiomas Alerta; reserva legal, APP (escadinha), frentes e carbono |
| `raiz_filtros.py` | quilombos (INCRA), terras indígenas da FUNAI em todas as fases, unidades de conservação do CNUC |
| `raiz_mapbiomas.py` | MapBiomas (cobertura, desmatamento, fogo, pasto) pela API da Plataforma, sem login |
| `raiz_direto.py` | YbYrá e Global Pasture Watch lidos direto dos arquivos públicos |
| `raiz_extras_direto.py` | JRC TMF 2025 e causas da perda de floresta (WRI/Google DeepMind) |
| `raiz_app.py` | aplica a escadinha da APP a municípios rodados antes dela |
| `raiz_extras.py` | histórico exportado uma vez do Earth Engine (só com os GeoTIFFs em `extras/`) |
| `raiz_situacao.py` | o que cada estado tem e o que falta, versão do código, privacidade das mensagens |
| `publicar_dados.py` | monta os pacotes do motor sozinho e publica no Release `dados` (estado do executor: `raiz executor publicar`) |
| `painel.py` | painel deste README |
| `raiz_ajustes.py`, `mapbiomas_alerta.py` | ajustes de pesquisa e API do Alerta com login (fora da rodada automática) |
| `fila*.sh` | filas antigas para rodar o país num computador só |
