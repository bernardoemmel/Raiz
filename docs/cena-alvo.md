# Cena-alvo da Raíz: "eu preciso de 1 milhão de créditos"

Todo chat que constrói a Raíz confere se o seu trabalho aproxima esta cena. Se não aproxima, explicar por quê.

## A cena

1. O cliente (desenvolvedor de restauração, empresa com meta FLAG, frigorífico, fundo ou banco) entra na **área logada**.
2. Faz um **pedido**: "preciso de uma área que entregue 1 milhão de créditos líquidos, no Pará, na Amazônia,
   no cronograma do ProFloresta+, com custo de até US$ X por crédito".
3. Em menos de 1 minuto, o **mapa mostra o melhor agrupamento de fazendas** que atende o pedido, com 3 opções lado a lado:
   - **mais barata** (menor custo líquido por crédito);
   - **mais segura** (menos risco de terra e mais chance de cumprir os marcos);
   - **mais compacta** (fazendas vizinhas, logística e vazamento menores).
4. Cada opção mostra: créditos líquidos P10/P50/P90, hectares, número de fazendas (pequenas agrupadas, nunca descartadas),
   modo de restauração por fazenda, TIR, custo por crédito, pico de caixa, chance de cumprir cada marco e multa esperada,
   mistura do caminho da terra (matrícula conferida, posse em titulação, assentamento, concessão) e **fazendas de reserva**
   (10 a 20% a mais, para quando um dono não aceitar).
5. O cliente troca uma fazenda à mão, salva o pedido e clica em **"pedir contato com os donos"**.
6. A Raíz aborda os donos, colhe o aceite e cobra a conexão por hectare. O pedido salvo vira **alerta**: quando surge
   fazenda que melhora o lote, ou quando uma do lote tem desmatamento, embargo ou matrícula cancelada, o cliente é avisado.

## O pedido (campos)

| Campo | Exemplos |
|---|---|
| Meta | créditos líquidos (t CO2e) **ou** hectares **ou** toneladas FLAG por ano |
| Cronograma | ProFloresta+ (12% no ano 7 ... 100% no ano 25), livre, ou datas próprias |
| Onde | estado, município, bioma, raio de uma planta ou fábrica, polígono desenhado no mapa, só fornecedores da cadeia (FLAG) |
| Dinheiro | custo máximo por crédito, TIR mínima, preço de venda, parte do financiamento |
| Métodos aceitos | regeneração assistida, semeadura direta, plantio total, agrofloresta/cacau, silvipastoril (FLAG) |
| Terra aceita | níveis de risco do caminho da terra (ex.: só matrícula conferida e concessão; ou também posse em titulação) |
| Forma do lote | distância máxima entre fazendas, número máximo de donos, área mínima contígua |
| Exclusões | embargo, terra indígena, UC de proteção integral, sobreposição com projeto de carbono existente |

## Como escolher o lote

- Cada fazenda já tem, no motor e no produto: crédito líquido por modo, custo, TIR, caminho da terra e risco.
- Otimização com solver aberto (OR-Tools, Apache 2.0, ou HiGHS, MIT): escolher fazendas que somam a meta pelo menor custo
  líquido por crédito, respeitando as restrições do pedido; a forma do lote entra como agrupamento espacial
  (vizinhança e distância entre fazendas) e o vazamento cai a zero quando há fazenda vizinha de mitigação no lote.
- A faixa P10/P90 sai de simulação (custo, captura, linha de base, aceite do dono).
- As 3 opções são o mesmo solver com pesos diferentes (custo, risco, compacidade).

## Aprendizado

Guardar cada pedido, cada lote sugerido (com a versão do modelo e das premissas) e o que aconteceu depois: quais donos
aceitaram, quais fazendas fecharam, custo e captura reais. Isso calibra o aceite esperado, o custo e a escolha do lote.

## Regras

Nunca descartar fazenda por tamanho. A ficha mostra dados da terra, nunca nome, CPF ou contato do dono: o contato passa pela Raíz.
