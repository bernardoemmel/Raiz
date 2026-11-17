# Vegetação e relevo na triagem

Três fontes nacionais entram na triagem de cada imóvel e chegam sozinhas ao lote: o **Mapa de Vegetação do IBGE**
(com a área da **Lei da Mata Atlântica**), o **TerraClass** e o **ANADEM**. Elas corrigem a reserva legal, separam
pasto sujo de regeneração e medem a APP de declividade e de topo de morro. Nada aqui tira a fazenda do lote: reserva a
recompor e APP aberta são oportunidade de restauração. Cada imóvel recebe um status:

| status | o que acontece no lote |
|---|---|
| `ressalva` | fica no lote, marcado, com o motivo; o checklist do lote (`vegetacao_relevo`) conta as ressalvas |
| `livre` | vegetação e relevo cobriram o imóvel e nada marcou |
| `nao_verificado` | faltou vegetação ou relevo; ausência de dado nunca vira terra livre |

Código: `raiz/ambiental/` (`vegetacao.py`, `relevo.py`, `terraclass.py`, `coleta.py`, `status.py`), tarefa
`ambiental` do executor (folha do grafo, depende do funil e do MapBiomas), regras em
`raiz/regras/padroes/ambiental.yaml`. Colunas em `docs/colunas.md` (`ambiental_<mun>.csv`).

## O erro que foi corrigido na reserva legal

O motor (`motor/raiz_estado.py`, `pct_rl`) escolhia o índice pelo **bioma no ponto central** do imóvel. A lei não fala
de bioma: o art. 12 da Lei 12.651/2012 dá, na Amazônia Legal, 80% em área de **florestas**, 35% em área de
**cerrado** e 20% em **campos gerais**, e o §2º manda somar cada parte do imóvel com o seu índice. Daí três erros:

1. **Savana dentro do bioma Amazônia** (lavrado de Roraima, cerrados do Amapá, campinas): o motor dava 80%.
   Boa Vista (RR), 2.958 imóveis: todos com 80% no motor; pela vegetação, média de 36,7% (2.906 imóveis com
   ressalva `rl_vegetacao_diverge`). A área aberta além da reserva sobe em 84 mil ha no município.
2. **Floresta estacional dentro do bioma Cerrado** (Tocantins, norte de Mato Grosso): o motor dava 35%. Abreulândia
   (TO), 551 imóveis: 84 mudam de índice e 35 ficam com contato floresta x savana (`rl_transicao`).
3. **Maranhão a leste do meridiano de 44º**: fora da Amazônia Legal (Lei Complementar 124/2007, art. 2º), reserva de
   20%. O motor tratava o Maranhão inteiro como Amazônia Legal. Agora a parte do imóvel a leste de 44º pesa 20%.

Além do índice, a **base** muda onde o imóvel é savana ou campo: o PRODES Amazônia que o motor usa marca savana como
"não floresta" e não acompanha o desmatamento dela. Onde a maior parte do imóvel não é floresta e há MapBiomas do
imóvel, a base é o imóvel inteiro e o remanescente é tudo que não é pasto, lavoura ou silvicultura
(`rl_base_fonte = mapbiomas`); nos demais, as contas do motor (`rl_base_fonte = prodes`).

O desenvolvedor (`raiz/restauracao.py`, `area_restauravel`) passa a usar `alem_RL_vegetacao_ha` quando a tarefa já
rodou no município; senão continua com `alem_RL_ha` do motor. O funil não foi mexido: municípios prontos não refazem
o funil, só a tarefa `ambiental` e o desenvolvedor no próximo processamento.

## O que cada fonte filtra e o critério

"Passa do limiar" = a área marcada tem pelo menos **1 ha** ou **5% do imóvel** (imóvel pequeno conta pela fração;
ninguém sai por tamanho).

| fonte | o que mede | ressalva |
|---|---|---|
| Mapa de Vegetação do IBGE 1:250 000 (versão 2026) | ha de floresta, cerrado, campos e transição dentro da Amazônia Legal (`rl_*_ha`), fora dela, índice ponderado (`pct_RL_vegetacao`), déficit e área além da reserva recalculados | índice difere do motor em 5 pontos ou mais (`rl_vegetacao_diverge`); contato floresta x savana passa do limiar (`rl_transicao`, usa 80% até o órgão estadual confirmar); parte no Maranhão a leste de 44º (`fora_amazonia_legal_maranhao`) |
| Área da Lei da Mata Atlântica (Lei 11.428/2006, Decreto 6.660/2008) | `lei_mata_atlantica_ha` | passa do limiar (`lei_mata_atlantica`): secundária em estágio médio ou avançado não pode ser suprimida |
| TerraClass (INPE/Embrapa) | pasto sujo (pastagem arbustiva/arbórea), pasto limpo, vegetação secundária | pasto sujo passa do limiar (`pasto_sujo`: mais barato, mas a linha de base dinâmica pode descontar); secundária passa do limiar (`regeneracao_existente`) |
| ANADEM v1 (relevo, 30 m) | APP de declividade (> 45º, art. 4º, V), de topo de morro (art. 4º, IX) e a parte aberta pelo MapBiomas | APP de relevo aberta passa do limiar (`app_relevo_aberta`: conferir uso consolidado antes de 2008, art. 63); relevo só no Copernicus (`relevo_sem_anadem`) |

### Como cada polígono do IBGE vira classe

Área natural usa a vegetação que está lá (`leg_uveg`); área antropizada usa a vegetação pretérita (`veg_pretet`,
região fitoecológica). Floresta: ombrófilas (D, A, M) e estacionais (F, C, H). Cerrado: savana (S) e savana-estépica
(T). Campos: estepe (E), formações pioneiras herbáceas (P), refúgios (r), e os subtipos gramíneo-lenhosos (Sg, Tg, Lg).
Campinarana: florestada (Ld) é floresta, arborizada e arbustiva (La, Lb) cerrado. Contato que junta floresta e
outra vegetação é transição; só florestas, floresta; sem floresta, a mais protetiva. Água fica fora da conta.

### Topo de morro

Pela lei: morro com altura mínima de 100 m e inclinação média maior que 25º; a APP é o terço de cima, acima da curva
de 2/3 da altura contada da base (planície, espelho d'água ou ponto de sela mais próximo). O cálculo é uma inundação
de cima para baixo com união de conjuntos: cada cume começa um conjunto; quando dois se tocam, a célula é o ponto de
sela do conjunto de cume mais baixo. Blocos de 0,25º com borda de 0,05º de contexto; morro que não fecha dentro do
bloco usa a cota mais baixa do domínio como base. Testado em morros sintéticos (cone de 800 m: APP exata do terço de
cima) e em blocos reais da Serra do Mar (80 a 840 ha de topo de morro por bloco de ~150 mil ha). A regra de 2012 é
estrita (a inclinação média conta o morro inteiro até a sela): em áreas planas da Amazônia o topo de morro quase não
aparece, como esperado (Parauapebas, PA: 0 ha nos 2.194 imóveis; declividade > 45º em poucos).

## De onde vêm os dados e o que ficou pendente

| fonte | acesso | situação |
|---|---|---|
| IBGE vegetação | `geoftp.ibge.gov.br/.../escala_250_mil/versao_2026/vege_area.zip`, sem chave | coletada pelo `coletar-ambiental.yml` (dia 3 de cada mês) e publicada no Release `insumos` |
| Lei da Mata Atlântica | o IBGE publica o mapa oficial só em **PDF** (`lei11428_mata_atlantica.pdf`) | **aproximação** pelo próprio mapa de vegetação: nos 17 estados do mapa, as formações do art. 2º (ombrófilas, estacionais, mangue e restinga, refúgios) e os contatos com elas. Alternativa: pedir o vetor oficial ao IBGE pela LAI |
| ANADEM | `metadados.snirh.gov.br/files/anadem_v1_tiles/anadem_v1_<zona><faixa>.tif`, GeoTIFF em blocos | lido por janela direto do servidor (só os blocos que tocam os imóveis, ~5 a 40 s por bloco). Reserva: Copernicus GLO-30 (com a copa, marcado) |
| TerraClass | o portal (`terraclass.gov.br/download-de-dados`) só entrega o arquivo numa sessão do navegador: sem link direto, sem API pública, e o catálogo do INPE (`data.inpe.br/geonetwork`) respondeu 502 | **pendente**: código pronto (`terraclass.py`, lê qualquer `terraclass_<bioma>_<ano>.tif` com a legenda ao lado, casando as classes pelo nome). Basta um link estável em `ambiental.yaml` (`terraclass.urls`) para a coleta baixar sozinha. Próximo passo: pedir ao INPE/Embrapa o link direto ou o GeoServer do TerraClass. Até lá a fonte aparece em `ambiental_nao_verificadas` (não impede o "livre") e o MapBiomas (vigor da pastagem) segue como aproximação |
| Página do Bot Agro com os links | pede login no Cursor | não deu para abrir daqui; as fontes acima foram achadas nas páginas oficiais |

## Como roda

- `coletar-ambiental.yml` coleta e publica no Release `insumos`. `processar-estados.yml` baixa para
  `motor/cache/ambiental`.
- A tarefa `ambiental` é folha (depende do funil e do MapBiomas): coleta nova ou regra nova refaz só ela e o
  desenvolvedor. Os municípios **não** foram recalculados agora; entram no próximo processamento ou com
  `raiz ambiental recalcular [--ufs RR] [--municipios 1400100]`.
- `RAIZ_AMBIENTAL_RELEVO=0` desliga o relevo (máquina sem rede): o imóvel fica `nao_verificado` nele.
- Sem dado pessoal: são mapas de vegetação, uso e relevo. `ambiental_<mun>.csv` não entra na publicação aberta.
