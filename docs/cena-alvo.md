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

## Interesse do dono: filtro e busca de aceite

Cada fazenda tem um **nível de interesse do dono**, que só sobe com registro (data, canal e versão do termo):
`sem_contato` → `contatado` → `interessado` → `aceite_fase1` (pagamento pequeno até o resultado do leilão) →
`contrato_firme`; ou `recusou` / `sem_resposta` (com motivo).

1. **Filtro:** o cliente pode pedir "só fazendas com dono interessado" (ou com aceite). O lote sai só delas, com o
   aviso do quanto falta para a meta.
2. **Busca de aceite (botão "buscar o interesse dos donos"):** com o lote montado, a Raíz contata os donos na ordem
   do lote. Quem recusa ou não responde no prazo sai, o otimizador recalcula e puxa a próxima fazenda (primeiro as de
   reserva, depois novas), e a Raíz contata essa. O ciclo segue **até o grupo com interesse fechar a meta** ou até
   esgotar as opções, quando o cliente recebe o quanto faltou e o que afrouxar no pedido.
3. O cliente acompanha o andamento: % da meta com dono interessado, com aceite e com contrato; quantos contatados,
   quantos recusaram e por quê (sem nome nem CPF).
4. Quem contata: o agente de contato da Raíz (WhatsApp, carta e e-mail, com roteiro e termo LGPD) e, quando precisa de
   visita, parceiro local credenciado com o app da Raíz. Nunca o cliente direto: o contato passa pela Raíz.
5. Cobrança: a conexão por hectare é cobrada sobre o grupo que aceitou.
6. Aprendizado: cada contato guarda o resultado; a chance de aceite por perfil de fazenda (tamanho, caminho da terra,
   região, pagamento oferecido) entra no otimizador, que passa a preferir lotes com mais chance de fechar.

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
| Interesse do dono | qualquer, só interessados, só com aceite |
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
