# Camada estadual das regras (E2 passo 5)

Cada estado pode ter regra mais rígida que a federal ou um programa próprio de regularização (PRA). A Raíz guarda
essas regras em `raiz/regras/parametros/estadual/<UF>.yaml`, no mesmo formato da tabela federal, com três campos a
mais (padrão do aides-velo): **nível** (estadual), **área de validade** (a UF inteira ou uma zona, como as zonas de
consolidação do ZEE) e **norma**. Uma regra estadual em vigor vem antes da federal na sua UF, zona e vigência; regra
pendente nunca entra em laudo.

Quando uma regra estadual sair de pendente, ela precisa entrar também nas regras em Catala
(`raiz/regras/catala/`) e nos testes de conformidade; o teste `test_tabela_real_sem_regra_estadual_ativa` falha para
lembrar disso.

## Situação em 12/11/2026

| UF | Regra | Norma | O que falta |
|---|---|---|---|
| PI | Reserva legal de 30% no Cerrado (federal: 20%) | Lei estadual 5.699/2007, que alterou a Lei 5.178/2000 (achada por busca; a Embrapa descreve como 20% federal + 10% estadual) | ler o texto consolidado (o portal legislacao.pi.gov.br não respondeu a este servidor), achar o artigo e a data de início e confirmar que segue em vigor |
| PA | Redução da reserva a 50% para regularizar área consolidada de floresta, nas zonas do ZEE (Lei 12.651, art. 13, I) | ZEE da Zona Leste e Calha Norte e ZEE da Zona Oeste | as leis estaduais do ZEE, a camada geográfica das zonas onde vale e a vigência |
| PA | PRA estadual | decreto do PRA do Pará | o que muda em relação à regra federal (prazos, escadinha, compensação) |
| MT | PRA estadual | Lei Complementar 592/2017 (alterada pela LC 745/2022), Decretos 1.031/2017, 1.491/2018 e 1.199/2021 | ler os artigos de reserva legal; o Decreto 1.199/2021 parece reduzir a reserva a 50% só para recompor em município com mais da metade em UC; regra da transição Cerrado/Amazônia |
| SP | PRA estadual e art. 68 (percentual da lei da época por data de abertura) | candidata: Lei estadual 15.684/2015 (não confirmada) | confirmar a lei, a regra do art. 68 e o que está suspenso por decisão judicial |

Fontes da busca: [Meio News, "Reserva legal nos cerrados será de 30% no Piauí"](https://www.meionews.com/noticias/reserva-legal-nos-cerrados-sera-de-30-no-piaui-34893),
[Embrapa sobre os imóveis do Piauí](https://www.embrapa.br/en/busca-de-noticias/-/noticia/46570274/mais-de-60-da-area-dos-imoveis-rurais-do-piaui-sao-destinados-a-preservacao-ambiental),
[Legislação do Piauí](http://legislacao.pi.gov.br/legislacao/default/ato/13386),
[LC 592/2017 de MT](https://www.normasbrasil.com.br/norma/lei-complementar-592-2017-mt_344078.html),
[Decreto 1.199/2021 de MT](https://www.legisweb.com.br/legislacao/?id=424198).
