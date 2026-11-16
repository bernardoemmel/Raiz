# Registro fechado de restauração 2026b

Os três YAMLs desta pasta são os bytes originais do commit
[`deec7a776378056509b2cd37e0894f4d00922b84`](https://github.com/bernardoemmel/Raiz/commit/deec7a776378056509b2cd37e0894f4d00922b84).
A regra, os cenários separados e o câmbio, nessa ordem e unidos por `\n--\n`, produzem
`dbc2776aee416750bf0665599421640101ba3aed46386bb15a703b4ccf787dd4`.
O rótulo inclui as versões dos dois primeiros arquivos:
`restauracao-2026b+cenarios-2026b+dbc2776a`.

O manifesto fixa os hashes SHA256 integrais e objetos Git de cada YAML, dos arquivos
de código `restauracao.py`, `restauracao_geo.py` e `executor/tarefas.py`, e das árvores
sintáticas das funções relevantes. O hash do manifesto é fixado no carregador.
Não havia calibração nem arquivo de edital nessa versão. O carregador conserva essa
ausência: não acrescenta regras de lote, incerteza global de captura ou edital atuais.

## Alcance da prova de origem

A auditoria de 12/11/2026 examinou todos os 525 commits alcançáveis pelas 19 referências
locais naquele momento, com `git rev-list --all`, sob HEAD
`56a6354a610e91d1526baef9cf91f78294c88f14`. Os 23 commits cujo hash de premissas corresponde
a esta versão estão enumerados no manifesto. Todos tinham os mesmos três YAMLs, os mesmos
três arquivos de código e nenhuma calibração ou edital. Essa identidade do código completo
abrange a curva, a captura e seus chamadores; não depende de comparar apenas uma função.
Os hashes de AST foram calculados com Python 3.12.14, sem executar módulos históricos.

Essa prova cobre o retrato local auditado. Não cobre código sem commit, referências não
obtidas ou commits posteriores. O hash das premissas não inclui o código Python. Por isso,
o consumidor também precisa conferir a tarefa `desenvolvedor-4e142d4bfca2` no `_versoes.json`
do artefato original. O manifesto documenta a fórmula e o hash integral dessa tarefa:
`4e142d4bfca2df0af9cc24d332c1984e4c4eed7f6be165ac267c60dea3f39750`.

## Contrato da reconstrução

`carregar(versao)` verifica os bytes e retorna a regra no formato original, com os cenários
separados, calibração vazia e câmbio histórico. A proveniência identifica o perfil
`separado_2026b`, o código, a curva e a tarefa de referência. O cenário `central_r11` usa
somente os campos históricos: reserva de 12%, contrato de 25 anos, horizonte de 40 anos,
marcos nos anos 7, 12, 17, 22 e 25 e PTAX de 5,5606 em 11/11/2026. Os descontos históricos
de linha de base, vazamento e incerteza são parâmetros distintos da reserva.

`forma_curva_2026b(regra)` aceita apenas a regra canônica integral. A implementação fechada
interpola os pontos (2, 0), (7, 13,44) e (14, 30,29), depois calcula o declínio linear que
completa 588,8 até o ano 40 e normaliza a soma para 1. Os anos 0, 1 e 2 são zero; a cauda
é decrescente e positiva. A fração acumulada até o ano 25 é `1075639/1377792`.
Não se pode passar esses YAMLs à função atual: a curva de 2026c possui outro algoritmo.

A forma não recalcula créditos por imóvel, custos, quantis, multas ou probabilidades.
Distribuir um P50 publicado preserva o total publicado, mas não recupera sua precisão
anterior ao arredondamento. Aplicar essa forma aos créditos exige ainda verificar a
compatibilidade da origem, dos descontos constantes no tempo e do teto de captura.
O limite físico até o ano 25 pressupõe pesos de métodos não negativos, com soma 1, e
ausência de calibração; o código histórico não assegura essa condição para toda entrada
arbitrária. O registro isoladamente não prova as condições dos dados recebidos.

O adaptador CADT confere as áreas publicadas: exige números finitos e não negativos,
total positivo quando há crédito positivo e soma dos três métodos compatível com a
área total até 0,0002 ha, tolerância dos quatro arredondamentos a quatro casas.
Esse teste detecta inconsistências observáveis, mas não prova o sinal de um valor
original que tenha sido arredondado a zero.

Para os totais positivos, a prova de que o teto não foi atingido até o ano 25 vem de
duas colunas publicadas: P50 por hectare do contrato e do horizonte de 40 anos.
Como ambas foram arredondadas a uma casa, a diferença estritamente maior que 0,1
prova que o acumulado no ano 40 supera o do ano 25. Se o teto fosse atingido até 25,
ambos seriam iguais, pois o fator líquido é constante. Diferença inconclusiva ou
valor ausente gera diagnóstico, sem inventar a trajetória. O cronograma distribui
o total P50 publicado pela curva identificada; não recupera a precisão anterior
ao arredondamento nem as trajetórias individuais não publicadas.

O carregamento e a curva do registro de 2026c mantêm os mesmos resultados; seu manifesto
permanece idêntico. O exportador CADT 1.3.0 preserva o total literal publicado também
nessa versão. Nenhuma versão histórica substitui as salvaguardas atuais de seleção
e comercialização.
