# Motor de dados da Raíz

Funil por imóvel do CAR, município por município, para o Brasil inteiro. Roda sozinho no GitHub Actions e publica no
Release [`dados`](https://github.com/bernardoemmel/raiz/releases/tag/dados), de onde o front baixa. Ninguém precisa
baixar nem subir nada à mão. O que cada coluna significa está em [`docs/colunas.md`](../docs/colunas.md).

## Painel

Atualizado sozinho a cada publicação (`painel.py`, a partir do `estados.json`). "Feitos" conta os municípios com o
funil pronto, inclusive os que não têm nenhum imóvel no CAR (ex.: Uiramutã, RR, toda dentro de terra indígena). Um estado
está completo quando tem, em todos os municípios, funil, filtros, MapBiomas, direto, TMF e causas da perda e a APP pela
escadinha. Os extras do Earth Engine e as certidões ficam de fora dessa conta (ver abaixo).

<!-- painel:inicio -->
Gerado do `estados.json` de 12/11/2026 11:50 (horário de Brasília). Brasil: 262 de 5.571 municípios com o funil pronto; 4 de 27 estados completos.

| Estado | Municípios feitos/total | Situação | Última atualização | Motor |
|---|---|---|---|---|
| PA Pará | 144/144 | completo (APP a conferir na primeira rodada automática) | 12/11/2026 07:52 | manual |
| RO Rondônia | 52/52 | completo | 12/11/2026 11:50 | [9365d63](https://github.com/bernardoemmel/Raiz/actions/runs/43230460294) (parte manual) |
| RR Roraima | 15/15 | completo | 12/11/2026 11:17 | [9365d63](https://github.com/bernardoemmel/Raiz/actions/runs/43230460294) (parte manual) |
| AC Acre | 22/22 | completo | 12/11/2026 11:38 | [9365d63](https://github.com/bernardoemmel/Raiz/actions/runs/43230460294) (parte manual) |
| AP Amapá | 16/16 | completo | 12/11/2026 11:29 | [3537575](https://github.com/bernardoemmel/Raiz/actions/runs/43235780981) (parte manual) |
| TO Tocantins | 13/139 | falta funil 126, TMF e causas 1, FLAG 1, caminho da terra 1, ficha 4, desenvolvedor 4 | 12/11/2026 11:50 | manual |
| MA Maranhão | 0/217 | não começou | — | — |
| AM Amazonas | 0/62 | não começou | — | — |
| MT Mato Grosso | 0/142 | não começou | — | — |
| GO Goiás | 0/246 | não começou | — | — |
| MS Mato Grosso do Sul | 0/79 | não começou | — | — |
| MG Minas Gerais | 0/853 | não começou | — | — |
| BA Bahia | 0/417 | não começou | — | — |
| PI Piauí | 0/224 | não começou | — | — |
| CE Ceará | 0/184 | não começou | — | — |
| RN Rio Grande do Norte | 0/167 | não começou | — | — |
| PB Paraíba | 0/223 | não começou | — | — |
| PE Pernambuco | 0/185 | não começou | — | — |
| AL Alagoas | 0/102 | não começou | — | — |
| SE Sergipe | 0/75 | não começou | — | — |
| ES Espírito Santo | 0/78 | não começou | — | — |
| RJ Rio de Janeiro | 0/92 | não começou | — | — |
| SP São Paulo | 0/645 | não começou | — | — |
| PR Paraná | 0/399 | não começou | — | — |
| SC Santa Catarina | 0/295 | não começou | — | — |
| RS Rio Grande do Sul | 0/497 | não começou | — | — |
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
   São até 18 jobs ao mesmo tempo, somando todas as rodadas do workflow (o GitHub dá 20 a repositório público; 2 ficam
   para o planejamento das rodadas e o CI).
2. **Preparar** (`rodar_estado.py --preparar`): baixa uma vez por dia os arquivos nacionais (lista de municípios,
   embargos do Ibama, biomas, geobr, TMF, causas da perda) e guarda no cache comum do Actions.
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
