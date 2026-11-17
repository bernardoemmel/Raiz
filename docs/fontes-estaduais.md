# Fontes estaduais na triagem

Cada imóvel triado e cada lote montado cruzam, além das fontes nacionais (`docs/restricoes-nacionais.md`), as
camadas que os Estados publicam: embargos e autos estaduais, unidades de conservação estaduais e municipais,
restauração e PSA já registrados, obrigações de recuperar (TCRA, PRAD), terras devolutas, territórios
tradicionais e bloqueios de matrícula por tribunal. O resultado sai por imóvel com o mesmo vocabulário das
restrições nacionais:

| status | o que acontece no lote |
|---|---|
| `exclusao` | sai do lote (bloqueio na oferta; motivo vai para a decisão explicada, LGPD art. 20) |
| `ressalva` | fica no lote, marcado com o motivo; entra no checklist do lote |
| `livre` | todas as fontes restritivas da UF cobriram o imóvel e nada cruzou |
| `nao_verificado` | faltou fonte (fora do ar, bloqueada fora do Brasil, sem camada pública); nunca vira livre |

## Onde está

- Catálogo, uma entrada por camada: `raiz/estaduais/fontes/<UF>.yaml` (órgão, endereço, efeito, critério, LGPD,
  resultado do teste de acesso e alternativa quando não há download).
- Bloqueios de matrícula por tribunal: `raiz/estaduais/matriculas.yaml`.
- Coleta: `raiz/estaduais/coleta.py` (`python -m raiz.estaduais coletar --saida PASTA --ufs SP,MG`).
- Cruzamento por imóvel: `raiz/estaduais/cruzamento.py` → `estaduais_<mun>.csv`
  (`python -m raiz.estaduais recalcular --pasta SAIDA --municipios 3106200`).
- Regras e textos dos motivos: `raiz/regras/padroes/fontes_estaduais.yaml`.
- Coleta semanal: `.github/workflows/coletar-estaduais.yml` (quartas, 06h17), publica no Release `insumos`.
- Testes: `testes/test_fontes_estaduais.py`.

## Critério comum

- "Passa do limiar" = sobreposição de pelo menos **1 ha** ou **5% do imóvel** (imóvel pequeno conta pela fração;
  ninguém sai por tamanho). Abaixo de **0,1 ha** é ruído de contorno.
- Camada com efeito de **exclusão** (embargo estadual, UC de proteção integral, território quilombola, grilagem
  apontada pelo órgão de terras): passa do limiar = exclusão; só na borda = ressalva `<motivo>_borda`; ponto
  (sem polígono) = ressalva `<motivo>_ponto`, porque o ponto não mede área.
- Camada com efeito de **ressalva** (autos, UC de uso sustentável, RPPN, restauração ou PSA já registrados,
  TCRA/PRAD, títulos estaduais): ponto dentro do imóvel ou polígono acima do limiar.
- Camada **informativa** (áreas prioritárias para restauração, terra já legitimada): não muda o status; vai em
  `estadual_informacoes` e ajuda a vender a restauração.
- Auto de **Flora/desmate nos últimos 5 anos** vira motivo próprio (`auto_estadual_flora_recente`).
- Fonte sem camada pública ou bloqueada vai para `estaduais_nao_verificadas` e para o checklist
  `estadual_conferir` (o que a pessoa precisa validar à mão).

## Por que restauração e PSA já registrados viram ressalva

A Raíz vende restauração adicional. Área que o Estado já registra como restaurada, em restauração ou recebendo
PSA tem risco de dupla contagem; área com obrigação de recuperar (TCRA da CETESB, PRAD, plantio compensatório,
acordo com o MP, decisão judicial) não é adicional. O desenvolvedor vê a área sobreposta (`estadual_ressalva_ha`)
e o motivo, e decide.

## LGPD

- Nome, CPF, CNPJ e campos de pessoa são **apagados na entrada** (`descartar` de cada fonte + detector de colunas
  pessoais de `raiz/privacidade.py`). Texto livre passa por máscara de CPF/CNPJ.
- Antes de gravar, a coleta confere que nenhum CPF ou CNPJ ficou nos arquivos (`conferir_sem_documento`); se
  ficou, apaga tudo e falha.
- Achados: GO publica CPF mascarado nos embargos e autos, mas a camada de imóveis do PSA expõe CPF sem máscara
  (`created_by`); MG publica nome e CPF/CNPJ do autuado nos embargos; ES publica nome do requerente do
  Reflorestar e do proprietário na legitimação de terras. Todos apagados na entrada.
- `estaduais_<mun>.csv` é privado (não entra na publicação aberta); o agregado por município pode ir a público.

## Situação por UF (testado em 17/11/2026 desta nuvem, fora do Brasil)

Primeira coleta no GitHub Actions (17/11/2026): ES 59.131 feições, GO 75.335, MG 1.485.667 (1,44 milhão são as
prioridades de restauração), MS 6.154, PR 135.274, SP 617.767 (sem as UCs, que falharam na contagem do servidor e voltam na próxima coleta). Nenhum CPF ou CNPJ nos arquivos. Fonte `parcial`
marca o que veio, mas não libera ninguém (o imóvel fica `nao_verificado` se nada cruzar).

### SP — DataGEO (WFS aberto)

| fonte | efeito | critério |
|---|---|---|
| SARE, projetos em execução (10.288) | ressalva | voluntário = restauração já em curso; exigência CETESB, MP, judicial ou multa = restauração obrigatória (não adicional). Traz o código do CAR. |
| Painel Verde, restauração por ano | ressalva | restauração registrada pelo Estado |
| TCRA (termos de compromisso de recuperação) | ressalva | área a recuperar é obrigação |
| Autos de infração ambiental (AIA) por ano | ressalva | Flora recente = motivo próprio |
| UCs estaduais de proteção integral / uso sustentável (SIAP) | exclusão / ressalva | |
| Programa Nascentes, áreas prioritárias (Res. SEMIL 02/2024) | informativo | |

O `/geoserver/ows` geral do DataGEO responde "WFS desativado"; o espaço `datageo` (`/geoserver/datageo/wfs`)
funciona. O site do SARE (`sare.ambiente.sp.gov.br`) tem certificado errado, mas os dados estão no DataGEO.

### MG — IDE-Sisema (WFS aberto)

Servidor certo: `geoserver.meioambiente.mg.gov.br/IDE/ows` (o `idesisema.../geoserver` dá 404).
Embargos do Sisema (11.470 polígonos, exclusão), UCs estaduais e municipais (exclusão se proteção integral),
RPPN (ressalva), terras quilombolas estaduais (exclusão), restauração e plantios do Tratado da Mata Atlântica
(ressalva), imóveis em UC oferecidos para compensação (ressalva: destino é virar terra pública), rios de
preservação permanente (Lei 15.082/2004) e áreas de proteção especial (ressalva), prioridades de restauração
(informativo).

### GO — SIGA-GO (WFS aberto)

O SIEG (`sieg.go.gov.br`) recusa esta nuvem; as camadas de fiscalização da SEMAD estão no SIGA-GO
(`siga.meioambiente.go.gov.br/geoserver`). Embargos estaduais (21.726 polígonos + 1.600 pontos; desembargos
tirados pelo número do processo), autos (31.657 + 8.590), PSA Cerrado em Pé, PRADs e plantios compensatórios,
UCs estaduais, municipais e RPPN estaduais, imóveis para compensação.

A camada de imóveis inscritos no PSA (`vw_psa_imovel`) quebra no próprio servidor (geometria inválida: "Must have
at least 2 spatial dimensions") e corta a resposta no meio; a fonte fica `parcial` com as áreas autorizadas
(`psa_area_autorizada`). Alternativa: pedir à SEMAD a correção da geometria ou o arquivo por LAI.

### MS — PIN-MS (ArcGIS aberto)

PIN-MS é ArcGIS Enterprise (`www.pinms.ms.gov.br/arcgis/rest/services`). Embargos do IMASUL (4.128 polígonos,
com o código do CAR-MS), autos (1.691 pontos), UCs (132), terras devolutas tituladas pela AGRAER 2014–2024 (127,
ressalva: conferir cláusulas do título), comunidades quilombolas e aldeias (pontos; ressalva a até 3 km).
Terras devolutas ainda não tituladas não têm camada pública: pedir à AGRAER por LAI.

### PR — geoserver.pr.gov.br (WFS aberto)

Autos do IAT (140.773 pontos desde 1993; insubsistentes fora; Flora recente e termo de embargo = motivos
próprios) e supressões autorizadas (SINAFLOR). O IAT não publica polígono de embargo nem terras devolutas
(acervo do antigo ITCG): fica no checklist e o pedido é por LAI.

### ES — GeoBases (WFS aberto, EPSG:31984)

Reflorestar, áreas apoiadas (18.548, PSA e restauração já pagos: ressalva), legitimação de terras devolutas do
IDAF (33.333; "Grilagem" ou "Anulado por decisão judicial" = exclusão, legitimação em aberto = ressalva,
"Legítimo" = informação), fiscalização do IDAF 2018–2024 (só com autuação), UCs estaduais do IEMA, plantios de
nativas cadastrados.

### BA — bloqueada fora do Brasil

GeoBahia/SEIA (fundo e fecho de pasto, embargos e UCs do INEMA) e CDA (terras devolutas) recusam esta nuvem e
também o runner do GitHub (ambos fora do Brasil). Até rodar do Brasil, os imóveis da BA ficam `nao_verificado`
nessas fontes, com checklist. Bloqueios de matrícula do TJBA (Formosa do Rio Preto, matrículas 726/727 e
derivadas; Provimento Conjunto CGJ/CCI 08/2021 no oeste baiano) entram como ressalva nos municípios atingidos.

### PI — bloqueada fora do Brasil

INTERPI, portal geográfico do Estado e o site do TJPI recusam esta nuvem. Bloqueio de matrículas da
Corregedoria do TJPI (fev/2012, comarcas de Avelino Lopes, Gilbués e Parnaguá, mais de 500 mil ha) e o bloqueio
da Vara Agrária de Bom Jesus (Serra das Confusões) entram como ressalva nesses municípios. A reserva legal de 30%
no cerrado piauiense continua pendente em `docs/regras-estaduais.md`.

## Amazônia Legal (PA, RO, MT, MA, AM, AC, AP, RR, TO)

Em toda UF da Amazônia entra, automática, a camada **floresta pública estadual não destinada** do CNFP 2025 do
SFB (tipo B, governo estadual): é onde aparecem as glebas arrecadadas e devolutas dos institutos de terras
(ITERPA, ITERMA, INTERMAT, ITERTINS) e as glebas que a União transferiu a AP e RR. Sobreposição acima do limiar
= ressalva `gleba_estadual` (posse em terra do estado; caminho é a regularização estadual). O CNFP abre de fora
do Brasil; os sites dos institutos, quase nunca.

Duas junções novas, usadas aqui e disponíveis para qualquer UF:

- **pelo número do CAR** (`campo_cod_imovel`): quando o órgão já ligou o dado ao recibo do CAR, vale o número e
  não o desenho (PRA de RO, LDI do PA). A área cruzada é a que o órgão informa (`campo_ha`); sem ela, conta o
  imóvel inteiro. `juncao: cod_imovel_ou_geometria` usa o CAR quando há e a geometria no resto.
- **arquivo por URL** (`tipo: arquivo`, GeoJSON, shapefile zipado, KML), para portais que publicam o arquivo
  sem WFS.

### PA — SEMAS aberta, ITERPA fechado

| fonte | efeito | critério |
|---|---|---|
| Lista de Desmatamento Ilegal (LDI, Decreto 838/2013): 5.128 áreas com recibo do CAR + 1.265 sem CAR | exclusão | desmate ilegal ligado ao CAR acima do limiar (pelo "Desmate em CAR" que a SEMAS informa); abaixo = `_borda`; área sem CAR com ponto dentro do imóvel = `_ponto` (ressalva). Recompor é obrigação do dono, não crédito. |
| Territórios quilombolas inscritos no CAR (Portal Análises do CAR, 60) | exclusão | mesmo critério do território quilombola das outras UFs |
| Territórios pesqueiros por portaria (15) | ressalva | consulta às comunidades antes de restaurar margens |
| Servidões ambientais no CAR (2.988) | ressalva | área já compensa reserva de outro imóvel; não se vende de novo |
| Glebas estaduais (CNFP 2025) | ressalva | ver acima |
| ITERPA (SICARF) | checklist | `iterpa.pa.gov.br` não abre daqui; alternativa CNFP + LAI |
| Embargos da SEMAS fora da LDI | checklist | mapa público sem download |
| Matrícula (TJPA e CNJ) | ressalva acima de 2.500 ha + checklist de todo imóvel | ver abaixo |

**LGPD na LDI.** O CSV "com CAR" traz a razão social e o CPF/CNPJ do proprietário. As duas colunas são apagadas
na leitura (antes de qualquer gravação) e a coleta confere que nenhum documento sobrou. O recibo do CAR é público.

**Matrícula no Pará.** Não há lista pública das matrículas bloqueadas (Provimento 13/2006-CJCI) nem das ~5.500
canceladas pelo CNJ (PP 0001943-67.2009, 2010). A regra fica em `raiz/estaduais/matriculas.yaml`
(`tjpa_matriculas_acima_do_limite`): todo imóvel do PA leva o item do checklist; acima de 2.500 ha (o menor
limite) vira ressalva na triagem, sem sair do lote. Com a certidão de inteiro teor (só com autorização do dono),
`raiz.estaduais.matricula.avaliar(uf, aberta_em, area_ha)` compara com o limite da época: 10.000 ha de 1934 a
08/11/1964, 3.000 ha até 04/10/1988 (EC 10/1964) e 2.500 ha depois (CF/1988, art. 188 §1º). Acima do limite =
"suspeita". Pendente: ler o texto do provimento e a situação atual do PP no CNJ (parte teve efeito suspenso no
STF para quem não foi ouvido).

### RO — Geoportal da SEDAM (WFS aberto, 408 camadas)

`geoportal.sedam.ro.gov.br/geoserver/ows`. Embargos estaduais ativos (5.659, exclusão), áreas autuadas (8.079,
ressalva), UCs estaduais (49; proteção integral = exclusão, uso sustentável = ressalva; inclui as que a LC
999/2018 revogou e a Justiça restabeleceu), zonas de amortecimento (ressalva), ZSEE 2ª aproximação
(informativo: a zona 1 permite recompor a reserva a 50%), servidões ambientais aprovadas (ressalva), termos do
PRA pelo número do CAR (798, ressalva: recomposição já é obrigação), área bloqueada das usinas do Madeira
(exclusão) e glebas estaduais do CNFP. O mesmo servidor espelha o CAR de AC, AM e MT (`comrar:sicar_imoveis_*`),
o CNFP e as camadas do INCRA, úteis como reserva quando a fonte original cair.

### MT, TO, AM, AC, AP, RR — bloqueadas fora do Brasil

Todo `*.mt.gov.br` (SEMA, SIMCAR, INTERMAT), `*.to.gov.br` (NATURATINS, ITERTINS, geoportal da SEPLAN), SEMA-AM,
IPAAM, SDS, `car.ac.gov.br`, SEMA-AP/IMAP e o governo de RR fecham a conexão desta nuvem ("connection reset" ou
túnel recusado). As fontes ficam no catálogo com `acesso: bloqueado_fora_brasil` e alternativa: até rodar do
Brasil, os imóveis dessas UFs ficam `nao_verificado` nelas e o checklist pede a conferência (embargo estadual,
CAR estadual do SIMCAR, terra devoluta, gleba transferida). O CNFP estadual entra automático em todas.

- **AM**: os projetos REDD+ em UCs estaduais já entram pela camada de terra comprometida (Verra e bases
  secundárias); fica o item de conferir o programa estadual (Lei 4.266/2015).
- **AC**: o estado inteiro está no programa jurisdicional (SISA, ISA Carbono): item do checklist de todo imóvel
  (crédito de projeto precisa de aninhamento). O ZEE só tem PDFs no repositório da SEMA-AC: pedir o shapefile.

### MA — SEMA aberta sem camada útil; ITERMA e ZEE fechados

A SEMA-MA abre, mas só publica as bases para retificar o CAR (UCs estaduais com botão de download dinâmico).
ITERMA, IMESC e o portal do ZEE fecham a conexão. Fica CNFP estadual automático + checklist.

## Rodar do Brasil (BA, PI e as UFs da Amazônia)

O runner do GitHub Actions fica fora do Brasil. Em qualquer máquina com IP brasileiro e o repositório:

```
uv run python -m raiz.estaduais coletar --saida estaduais_br --ufs BA,PI,MT,TO,AM,AC,AP,RR,MA,PA
```

Antes, preencher `camada` das fontes bloqueadas com os nomes do GetCapabilities (o arquivo marca
`a_confirmar_do_brasil`) e trocar `acesso` para `aberto`. Depois subir `estaduais_*` no Release `insumos`
(`gh release upload insumos estaduais_br/estaduais_* --clobber`).

## Como roda

- `coletar-estaduais.yml` coleta e publica `estaduais_<fonte>.parquet` + `estaduais_cobertura.json` no Release
  `insumos` (coleta parcial de algumas UFs se junta à cobertura anterior).
- `processar-estados.yml` baixa `estaduais_*` para `motor/cache/estaduais`; a tarefa `estaduais` do executor (folha,
  depende só do funil) grava `estaduais_<mun>.csv`. Coleta nova ou catálogo novo refaz só esta tarefa.
- Na oferta, `estadual_status = exclusao` vira bloqueio (a decisão explicada cita o motivo); a ressalva segue marcada
  e o checklist do lote ganha o item `fontes_estaduais` com as ressalvas, o que não foi verificado e o que conferir à mão.
- UF ainda sem catálogo fica `nao_verificado` com `estadual_sem_catalogo` no checklist (nunca `livre`).
- Os municípios **não** foram recalculados agora: entram no próximo processamento
  (`python -m raiz.estaduais recalcular` para adiantar).
