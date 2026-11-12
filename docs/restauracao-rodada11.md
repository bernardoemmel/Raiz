# Valor para quem restaura: rodada 11 unificada (cenário central_r11)

> Atualização de 12/11/2026: os resultados numéricos abaixo são históricos da
> rodada anterior, cujo cenário usava reserva de 12%. A política vigente passa a
> exigir pelo menos 20% em todas as fazendas e cenários. Não usar esses números
> como resultado do novo lote. O workflow `Recalcular lote do Pará` processará os
> 144 municípios no GitHub Actions, com pacotes/commit congelados, medições
> geográficas preservadas e publicação
> imutável no Release `dados`. Os resultados serão registrados após sua conclusão.


Resultado da rodada 11 depois de juntar as duas implementações (esta e a da branch claude/premissas-rodada11) num só
arquivo de premissas, raiz/regras/padroes/restauracao.yaml (regras, cenários, Monte Carlo, aluguel do Censo, renda do
gado e lote), e num só cálculo, raiz/restauracao.py (12/11/2026). As premissas antigas seguem no cenário
`otimista_fundador`, que ainda reproduz a TIR de ~30%.

## O que veio de cada lado

| Ponto | Fica | De onde |
|---|---|---|
| Forma da curva | pontos oficiais da URTX (Anexo 20) em linha reta, escalados para o total do método | outra branch |
| Total de 40 anos | 588,8 t/ha no plantio, 442,8 na regeneração, 515,8 na semeadura, limitado ao teto do bioma | as duas |
| Incerteza da captura | P10 de 0,6 e P90 de 1,3 do P50, comum ao lote | outra branch |
| Custo | SFB no P50; P10 e P90 publicados (Altamira, Systemica, Instituto Escolhas) | outra branch |
| Marcos | último marco a 100% sem tolerância; rescisão por multa de 20% ou atraso acima de 180 dias | outra branch |
| Multa e rescisão | medidas no lote inteiro (`cronograma_lote`), fora do fluxo da fazenda | outra branch, no motor daqui |
| Dívida | Fundo Clima pelo ICSD 1,3, juros da carência no saldo | esta |
| Dono | 15% do crédito + piso de R$ 24/ha (Inesc); duas fases a R$ 2/ha por mês | outra branch |
| Aluguel de referência | Censo 2017 por município, estado ou Brasil | as duas |
| Renda do gado | venda de bovinos por ha de pasto (Censo 2017, SIDRA 6910 e 6881) corrigida pelo IPCA | nova |
| Vazamento | vizinha a até 15 km que recebe o gado zera o vazamento (VMD0054) | outra branch |
| Método | os métodos disputam a fazenda e vence o menor preço de equilíbrio | as duas |
| Lote | otimizador dos pedidos, reserva pela chance de 90%, fluxo do lote pela soma das fazendas | esta |
| Checklist do edital | 62 itens de edital_profloresta.yaml | outra branch |

## Fazenda de referência (100 ha no leste do Pará, Amazônia, US$ 55)

| | Plantio total | Regeneração assistida |
|---|---|---|
| Custo (SFB) | R$ 15.830 + R$ 3.544 nos anos 1 e 2 (P10 R$ 14.500, P90 R$ 24.800) | R$ 4.230 + R$ 800 (P10 R$ 2.430, P90 R$ 6.096) |
| Captura em 40 anos | 588,8 t/ha (no teto da Amazônia) | 442,8 t/ha |
| Linha de base usada | 10% (piso; medida no YbYrá abaixo de 1%) | 19,7% (medida) |
| Crédito líquido até o ano 25 | 258 t/ha | 173 t/ha |
| TIR do projeto (P50), PTAX de R$ 5,56 | 5,4% | 10,5% |
| TIR com Fundo Clima (P50), PTAX de R$ 5,56 | 5,8% | 13,5% |
| TIR com Fundo Clima (P50), câmbio de R$ 5,40 | 5,5% | 13,2% |
| Preço que zera o VPL a 9,2% (PTAX) | US$ 92 | US$ 48 |

A US$ 74 (central_r11_74, R$ 5,40) o plantio sobe para 9,1% e a regeneração para 17,1%. Sem venda depois do contrato
(so_contrato_25) o plantio cai para 3,7% e a regeneração para 12,8%. No estresse (linha de base e vazamento de 40%,
35% financiado, 20% ao dono) o plantio perde dinheiro (TIR do projeto de −1,6%) e a regeneração fica em 2,1%.

O plantio total fica abaixo dos 7 a 9% da referência do fundador: a curva oficial entrega pouco até o ano 7, o
último marco pede 100% e o dono tem piso. A outra sessão chegou a 6,0%. O teste
`test_plantio_da_7_a_9_pct_no_central_r11` fica marcado como falha esperada até o fundador decidir a premissa.

## Nova Esperança do Piriá (1504950), dado real

870 imóveis com área para restaurar, 47.768 ha: 543 em semeadura direta, 305 em regeneração assistida e 22 em
plantio. TIR com Fundo Clima, mediana: plantio 4,4%, regeneração 12,0%, semeadura 8,3%. Preço de equilíbrio,
mediana: plantio US$ 104, regeneração US$ 54, semeadura US$ 74. 10,1 milhões de créditos líquidos até o ano 25; 402
fazendas com TIR acima da WACC e 157 que o preço de US$ 55 paga. Vazamento: 34 fazendas com vizinha de mitigação.

Lote do ProFloresta+ só com Nova Esperança (a amostra do CI): fecha os marcos no P50 com 28 titulares, mas a terra
pronta (42 fazendas com matrícula a conferir) não dá a reserva para 90% de chance; com a posse em titulação e o
assentamento destravados, fecha com reserva (201 fazendas, custo médio de US$ 34 por crédito, TIR do lote de 8,4%).

## Reserva de não permanência por fazenda (E3 passo 4)

A reserva de cada fazenda sobe com a perda esperada em 40 anos por fogo (MapBiomas Fogo, com a queima de manejo do
pasto acabando na área restaurada e aceiro e brigada) e por derrubada da vegetação secundária no município (MapBiomas
desmatamento, com contrato averbado e monitoramento), mais 2% de risco interno e externo; nunca fica abaixo dos 12% do
cenário. A fazenda de referência fica nos 12%. Em Nova Esperança: reserva média de 14,9% (mediana 12%, máxima 39,7%);
TIR com Fundo Clima, mediana: plantio 1,4%, regeneração 11,8%, semeadura 7,8% (o plantio cai mais porque a regra de
pontos manda para o plantio o pasto com fogo frequente); 9,8 milhões de créditos líquidos até o ano 25.

## Pagamento ao dono

- São Félix (aluguel do Censo Agro 2017 de R$ 532/ha/ano): o aluguel fixo derruba a TIR do projeto.
- Resto do Pará (R$ 212/ha/ano): o aluguel fixo pode sair mais barato que 15% do crédito + piso, mas o dono não divide
  o risco da captura. A ficha mostra os dois números e diz qual é o caso.
- Renda do gado na mesma área: em Nova Esperança, R$ 187/ha/ano de venda de bois (bruto, corrigido pelo IPCA) e cerca
  de R$ 5/ha/ano de sobra com a margem de referência da CNA (2,7%). A folha do dono mostra os três números.

## O que vale conferir

- Custo do SFB: o R$ 15.830,71 do plantio e o R$ 4.229,88 da condução, no Relatório de Avaliação
  Econômico-Financeira Referencial da Flona do Bom Futuro (Tabelas 37 a 42), já somam os anos 1 a 3 (implantação e
  duas manutenções). Os R$ 3.544 e R$ 800 da rodada 11 entram por cima, lidos como total dos anos 1 e 2.
- O modelo do SFB usa WACC real de 10,97%, linha de base de 7,5 a 10%, vazamento de 20% e reserva de 20%.
- Margem do gado: 2,7% é a expectativa da recria e engorda no Pará (CNA, jul/2024); a fazenda modelo de Paragominas
  teve margem bem maior em 2022. A folha cita a fonte e pede para o dono comparar com as próprias contas.
