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
Gerado do `estados.json` de 12/11/2026 08:01 (horário de Brasília). Brasil: 256 de 5.571 municípios com o funil pronto; 0 de 27 estados completos.

| Estado | Municípios feitos/total | Situação | Última atualização | Motor |
|---|---|---|---|---|
| PA Pará | 144/144 | completo (APP a conferir na primeira rodada automática) | 12/11/2026 07:52 | manual |
| RO Rondônia | 52/52 | falta MapBiomas 52, direto 36 (APP a conferir na primeira rodada automática) | 12/11/2026 08:01 | manual |
| RR Roraima | 14/15 | falta funil 1 (APP a conferir na primeira rodada automática) | 12/11/2026 07:52 | manual |
| AC Acre | 22/22 | completo (APP a conferir na primeira rodada automática) | 12/11/2026 07:52 | manual |
| AP Amapá | 16/16 | completo (APP a conferir na primeira rodada automática) | 12/11/2026 07:52 | manual |
| TO Tocantins | 8/139 | falta funil 131, filtros 8, MapBiomas 8, direto 8, TMF e causas 8 (APP a conferir na primeira rodada automática) | 12/11/2026 08:01 | manual |
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
e quando alguém dispara à mão:

1. **Planejar** (`rodar_estado.py --planejar`): lê o `estados.json` publicado e escolhe os estados que precisam rodar,
   nesta ordem: PA, RO, RR, AC, AP (completar o que já está publicado), TO, MA, AM, MT (resto da Amazônia Legal), GO, MS,
   MG, BA, PI, CE, RN, PB, PE, AL, SE, ES, RJ, SP, PR, SC, RS, DF. Entra quem não começou, quem está incompleto, quem foi
   publicado antes da automação (para conferir o que falta e gravar a versão) e quem tem tabela feita com código antigo.
2. **Preparar** (`rodar_estado.py --preparar`): baixa uma vez por dia os arquivos nacionais (lista de municípios,
   embargos do Ibama, biomas, geobr, TMF, causas da perda) e guarda no cache comum do Actions.
3. **Um job por estado**, até 4 ao mesmo tempo. Cada um: instala o `requirements.txt`, recupera o cache (comum e do
   estado: blocos do TerraBrasilis, MapBiomas, Alerta), baixa do Release o que já está publicado do estado para
   `saida/<UF>/` (os scripts pulam o município pronto, então retoma de onde parou) e roda `rodar_estado.py <UF>`, que
   chama, nesta ordem: `raiz_estado.py`, `raiz_filtros.py`, `raiz_mapbiomas.py`, `raiz_direto.py`,
   `raiz_extras_direto.py`, `raiz_app.py` e, se houver GeoTIFF em `extras/`, `raiz_extras.py`.
   Variáveis: `OGR_GEOJSON_MAX_OBJ_SIZE=0`, `LANES=3`.
4. **Prazo de 5h30 por job**: às 5h05 a etapa em curso para (cada arquivo é gravado de uma vez, nada fica pela metade),
   o job publica o que fez e dispara o próprio workflow de novo só para aquele estado, até completar. Se uma rodada inteira
   não terminar nenhum município novo, para de se disparar (a rodada semanal tenta de novo).
5. **Publicar** (`publicar_dados.py motor/saida dados-entrada <UF> --subir`): sobe `raiz_<UF>.tar.gz` e
   `raiz_geo_<UF>.tar.gz` direto no Release e, por último, regrava o `estados.json` relendo a versão publicada, dentro
   de uma trava (tag `trava-publicar-dados`), para dois estados que terminam juntos não apagarem a entrada um do outro.
   Depois atualiza o painel acima.

### Quando uma fonte recusa o GitHub

SICAR, TerraBrasilis, SIGEF, MapBiomas (API e Alerta), Zenodo e geobr podem limitar pedidos ou ficar fora do ar. Os
scripts esperam e tentam de novo com espera crescente (30 s, 1, 2, 4 e 8 min, ou o tempo que a fonte pedir no
`Retry-After`), escrevem cada tentativa no log do job e seguem para o próximo município; o município que falhou entra
de novo na próxima rodada. Se uma etapa junta 8 erros seguidos, a fonte está fora do ar: a etapa para, as outras seguem,
e ela tenta de novo no fim (depois de 10 e de 30 min, se der tempo). Os erros aparecem no resumo do job, no `estados.json`
(campo `erros`) e no painel. O funil não roda sem o MapBiomas Alerta e sem o MapBiomas (cobertura e desmatamento), porque
sem eles as colunas `problema` e `frente` sairiam erradas sem aviso: fica para a próxima rodada.

### Versão do motor

Cada tabela guarda no `estados.json` (campo `motor`) o commit que rodou e um hash do código de que ela depende
(`raiz_situacao.ETAPAS`), sem comentários nem docstrings. Se o código de uma tabela mudar, a próxima rodada apaga essa
tabela no estado e refaz; mudar só comentário ou texto de ajuda não refaz nada. Mudar o `raiz_estado.py` refaz tudo,
porque ele grava os polígonos dos imóveis que as outras tabelas usam. Tabelas publicadas antes da automação são
adotadas como estão e ficam marcadas em `motor.legado`. O aprendizado usa o commit e o hash para comparar previsões
entre versões.

### Rodar à mão

No GitHub: Actions, "Processar estados (motor)", "Run workflow". Campos:

- `ufs`: estados separados por espaço (ex.: `TO MA`). Vazio: o plano automático.
- `refazer`: tabelas para apagar e refazer nesses estados (`funil`, `filtros`, `mapbiomas`, `direto`, `extras_direto`,
  `extras` ou `tudo`; várias com vírgula). Ex.: uma fonte publicou ano novo. Refazer o funil refaz tudo.
- `continuacao`: uso interno das continuações automáticas.

No computador (da pasta `motor/`):

```bash
pip install -r ../requirements.txt
python rodar_estado.py TO              # o que falta em Tocantins, na ordem das etapas
python rodar_estado.py --planejar      # quais estados precisam rodar
python raiz_estado.py PA 1504950       # só o funil de um município
python publicar_dados.py saida dados-entrada TO --subir   # publica (precisa do gh com acesso ao repositório)
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
| `rodar_estado.py` | roda um estado inteiro, etapa por etapa, dentro do prazo; planeja, prepara o cache e continua |
| `raiz_estado.py` | funil principal: CAR (SICAR), embargos (Ibama), PRODES, TI, UC e hidrografia (TerraBrasilis), SIGEF (INCRA), MapBiomas, MapBiomas Alerta; reserva legal, APP (escadinha), frentes e carbono |
| `raiz_filtros.py` | quilombos (INCRA), terras indígenas da FUNAI em todas as fases, unidades de conservação do CNUC |
| `raiz_mapbiomas.py` | MapBiomas (cobertura, desmatamento, fogo, pasto) pela API da Plataforma, sem login |
| `raiz_direto.py` | YbYrá e Global Pasture Watch lidos direto dos arquivos públicos |
| `raiz_extras_direto.py` | JRC TMF 2025 e causas da perda de floresta (WRI/Google DeepMind) |
| `raiz_app.py` | aplica a escadinha da APP a municípios rodados antes dela |
| `raiz_extras.py` | histórico exportado uma vez do Earth Engine (só com os GeoTIFFs em `extras/`) |
| `raiz_situacao.py` | o que cada estado tem e o que falta, versão do código, privacidade das mensagens |
| `publicar_dados.py` | monta os pacotes e publica no Release `dados` |
| `painel.py` | painel deste README |
| `raiz_ajustes.py`, `mapbiomas_alerta.py` | ajustes de pesquisa e API do Alerta com login (fora da rodada automática) |
| `fila*.sh` | filas antigas para rodar o país num computador só |
