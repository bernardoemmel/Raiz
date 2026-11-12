# Passagem — Lote e números

## Entrega de 12/11/2026: cálculo e salvaguardas da rodada 11

Área: `raiz/lote.py`, `raiz/lote_relatorio.py`, `raiz/restauracao*.py`, `raiz/regras/`, testes e documentação.
Sem alteração na API, no MCP ou no front. O workflow novo é a infraestrutura necessária para rodar o pedido no Actions.

- Modelo `restauracao-2026d`: reserva contra reversão nunca abaixo de 20%; inclui hash do código e premissas.
  O ICVCM 9.4(a)(5)(i) prevê essa alternativa; 9.4(a)(5)(ii) também permite ajuste proporcional ao risco.
  A Raíz adota o piso conservador solicitado. Não é uma afirmação de piso universal obrigatório em qualquer padrão.
- Preço mínimo por fazenda para TIR de 12% e 15%, projeto e alavancada, dívida pelo ICSD; corrigida participação do
  dono no período de duas fases. Fluxo do lote e preço por fazenda são conferidos separadamente.
- Três alternativas do mesmo solver: barata, segura e compacta. A compacta não reaplica bônus genérico de vazamento
  sobre créditos que já foram calculados líquidos. Pequenas continuam candidatas, sem corte por tamanho.
- Sobreposição jurisdicional confirmada bloqueia seleção; situação desconhecida permanece potencial, sem liberar
  venda. Camada opcional `jurisdicional_<mun>.csv` e função espacial `cruzar_jurisdicional` com fonte/vigência.
  Lei 15.042, art. 43 §§6,7,11,13: falta comprovar exclusão e período para não contar duas vezes.
- Território tradicional exige CLPI custeada pelo desenvolvedor e partilha comprovada: mínimo 50% para remoção,
  70% para REDD+ de mercado (art. 47). Ausência de consentimento não é autorização.
- Decisões e risco: JSONL com critério textual, versão e ID estável; revisão humana por protocolo persistente
  em SQLite (`pedir_revisao_humana`). A revisão não libera crédito automaticamente. A API para esses pedidos
  não foi alterada, conforme divisão de trabalho.
- Falta de dado de pasto não gera crédito sobre a área livre inteira: situação `pendente_pasto`, sem afirmar que
  a fazenda não tem potencial. Não confundir informação ausente com área zero observada.
- O lote recusa mistura de previsões antigas com fluxos do modelo atual. Fixtures históricas permanecem no git;
  o teste do lote recalcula uma cópia temporária antes de comparar.

## Execução e publicação

`.github/workflows/lote-para.yml`, comando `python -m raiz.restauracao_rodada`: congela os IDs e hashes dos pacotes
`raiz_PA.tar.gz` e `raiz_geo_PA.tar.gz` do Release `dados`, distribui 144 municípios por 15 jobs, confere versões e
cobertura, monta as três opções e publica pacotes imutáveis por execução. O ponteiro `lote_PA_central_r11.json` sobe
por último. Não substitui os pacotes originais do motor e não grava dados grandes no git.

Inspeção inicial: 144 municípios e 345.870 imóveis no pacote publicado; sem tabelas de desenvolvedor e terra,
APP pela escadinha presente em 81 municípios. Usa somente dados congelados; não executa downloads geográficos novos.
Piloto de Nova Esperança do Piriá: 880 imóveis reais calculados, três opções e todos os arquivos gerados localmente.
Execução integral/publicação: **pendente de rodar o workflow depois do merge do código**. Esta passagem será atualizada
com URL da execução, hashes e números quando a publicação terminar.

## Comparação com o real

O snapshot publicado de Nova Esperança ainda coincide com a exportação antiga: 222.694 tCO2/ano e 40.325,22 ha de
pasto. O documento `docs/teste-real-2026-11-12.md` relata a coleta atualizada com 209.708 tCO2/ano e 37.736 ha.
São fontes/coleções distintas, não medições de crescimento realizado. Não aplicar um fator de 5,8% à captura.
O relatório identifica a fonte efetivamente usada, compara por CAR e guarda hashes; o registro de previsões é
imutável por modelo e entradas. A publicação de uma coleta mais recente permanece dependente do fluxo de dados.

## Resposta ecológica e limite pendente

O arquivo de cada opção `ecologia_PA.json` traz 3, 5, 10 e 15 anos por fazenda, com fontes, unidade, versão e incerteza.
Não há inventário local na base. Densidade futura e riqueza de espécies ficam **não estimadas**, não zero.
O módulo aceita projeção local documentada com faixa; não fabrica quantis.

Referência separada: SMA 32/2014, Anexo I (São Paulo), regenerantes de altura >50 cm e CAP <15 cm: densidade adequada
>200/>1.000/>2.000/>2.500 indivíduos/ha e riqueza >3/>10/>20/>25 espécies aos 3/5/10/15 anos. Isso não equivale a
árvores adultas por hectare nem a previsão para o Pará. Embrapa informa 1.667 ou 2.500 mudas/ha no plantio inicial,
sem sustentar sobrevivência futura nem riqueza por fazenda. O item de previsão ecológica continua **parcial** até
haver inventário e projeção local verificável.

## Validação

Testes específicos de reserva, preço, salvaguardas, três opções, comparação, persistência e workflow.
Ruff global conferido. A contagem final de testes e links do CI serão registrados na entrega da execução integral.
