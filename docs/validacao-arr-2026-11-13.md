# Validação ARR Brasil — fontes, reconciliação e limite da curva

O comparador agora conserva cada confrontação com versão do modelo, hash das
entradas e da fonte, período, base contábil e motivo de incomparabilidade. Não
aplica fator automaticamente. Fontes e fatos numéricos estão em
`raiz/regras/padroes/arr_referencias_2026.json`; os documentos completos não
integram o repositório.

## Universo e emissão efetiva

[Berkeley VROD v2026-08](https://gspp.berkeley.edu/berkeley-carbon-trading-project/offsets-database),
com corte em 31/08/2026 e licença **CC BY 4.0**, contém 65 projetos brasileiros
Afforestation/Reforestation, dos quais 58 VCS. Oito VCS têm emissão positiva,
somando 2.402.547 VCUs. Os 58 incluem projetos em pipeline; não são todos
registrados. Zero emissão não prova remoção zero.

Atribuição: Pamela Quartson, Barbara K Haya, Tyler Bernard, Aline Abayo, Xinyun
Rong, Ivy S So, Micah Elias (2026), *Voluntary Registry Offsets Database
v2026-08*, Berkeley Carbon Trading Project, University of California, Berkeley.

O extrato de 78 linhas reconcilia 42 períodos com os totais do consolidado. A
regra Berkeley usa `Total Vintage Quantity` histórico deduplicado por projeto,
início, fim e quantidade. Somente quando o total falta usa `Units`, deduplicado
por serial. Somar `Units` cegamente subestimaria Pratigi: 2.024 em vez de 4.573.
Não se mistura ano de emissão com idade da vegetação.

## Monitoramentos conferidos

Obtivemos os MR, relatórios de verificação, PDD e planilhas pelos botões públicos
do registro, em navegador anônimo. Nenhum login foi usado. Os IDs e SHA-256 dos
documentos estão no arquivo de referências. As licenças abertas dos documentos
não foram identificadas: registramos fatos numéricos e referências, sem
redistribuir PDFs, planilhas ou dados pessoais.

| Projeto/instância | Período completo | Área monitorada (ha) | Bruto (tCO₂e) | Baseline (tCO₂e) | Adicional antes do buffer | Emitível após buffer histórico de 12% |
|---|---|---:|---:|---:|---:|---:|
| [3743/PAI001](https://registry.verra.org/verra/public/program/VCS/projects/3743) | 04/10/2022–15/06/2025 | 342,2731 | 10.383,3691 | 1.437,0764 | 8.946,2927 | 7.872,7376 |
| [3743/PAI002](https://registry.verra.org/verra/public/program/VCS/projects/3743) | 10/06/2023–15/06/2025 | 1.278,5355 | 36.515,6056 | 3.556,4069 | 32.959,1988 | 29.004,0949 |
| [3772/PAI001](https://registry.verra.org/verra/public/program/VCS/projects/3772) | 28/09/2023–31/05/2025 | 7.183,3236 | 128.049,5446 | 31.117,6215 | 96.931,9231 | 85.300,0923 |

Esses totais são resultados da contabilização verificada, combinando inventário,
equações e parâmetros; não equivalem a medição direta de todos os pools. Não
houve dedução adicional de vazamento ou emissões operacionais nessas planilhas.

No 3743, 36.877 VCUs emitidos reconciliam com os valores precisos. O vintage
2023 incorpora a compensação de aproximadamente −445,8 VCUs de 2022; não se
deve interpretar cada linha anual como incremento medido naquele ano.

No 3772, o cadastro público consultado em **13/11/2026** mostra **85.300 emitidos,
20.026 ativos e 65.274 aposentados**. O buffer público é 11.631. Os 65.274 do
Berkeley de agosto permanecem preservados com aquele corte; não substituem a
emissão atual. A diferença se concentra no vintage 2025, mas a data/causa da
mudança não foi inferida. O MR e a emissão atual reconciliam em 85.300 por
arredondamento. A diferença entre emitível e emitido nunca calibra crescimento.

## Correções da comparação

- As tabelas ex ante versus realizado do MR 3743 comparam previsão já líquida
  de baseline com realizado bruto. O comparador usa 8.946,2927 e 32.959,1988
  antes do buffer, não 10.383,3691 e 36.515,6056. Mesmo assim, áreas, estratos e
  implantação mudaram entre PDD e monitoramento: a razão documental não é fator
  de produtividade do RAIZ.
- Nas três planilhas, os resultados anuais são **rateios do total monitorado
  por dias**, não inventários anuais independentes. Não usar vintages para
  ajustar a forma anual da curva.
- A reserva histórica de 12% permanece histórica. A política prospectiva do
  RAIZ de no mínimo 20% é outro cenário; comparação de crédito líquido com
  reservas diferentes é bloqueada.
- VCS665 e URTX/VCS5709 já informam premissas do motor. O comparador os marca
  como desenvolvimento, mesmo se forem indevidamente rotulados como validação.

## Confrontação do motor e pendências precisas

A versão examinada é `restauracao-2026d+a84f9789`. A curva central começa com
fluxo zero nos primeiros dois anos. No 3772, o período completo desde setembro
de 2023 até maio de 2025 cabe nesse intervalo e tem remoção adicional positiva.
O diagnóstico registra essa **incompatibilidade temporal de escopo**. Não
transforma o resultado em previsão pareada nem fator: as áreas têm estoque
inicial, regenerantes, estratos de idades distintas e pools incluindo arbustos
de adubação. O RAIZ agrega raízes, serapilheira e solo, mas não discrimina esses
componentes e sua evolução como as planilhas dos projetos.

As três confrontações ficam `incomparavel`, com previsão pareada pendente. Para
produzir uma comparação que aceite calibração faltam datas/áreas de implantação
por coorte, mapeamento dos métodos e harmonização de estoque inicial, pools e
deduções. A janela de implantação do 3772 vai além do corte do MR e inclui área
ainda não implementada; não preencher as datas silenciosamente.

A carta de 30/10/2026 do 3743 solicita retirada prospectiva das duas instâncias
a partir de 16/06/2025, condicionada à avaliação do desvio. Não invalida
automaticamente o período monitorado; impede presumir que essas instâncias
continuarão na mesma série futura. Nenhum dado pessoal da carta foi copiado.

Calibração só depois de pareamento compatível e avaliação em projetos separados
dos usados no desenvolvimento. Não confundir vários vintages de um projeto com
várias observações independentes. Nenhum coeficiente de captura foi alterado.

## Reprodução

```bash
uv run python -m raiz.restauracao_validacao_arr referencias /caminho/privado/comparacoes-arr
uv run python -m raiz.restauracao_validacao_arr normalizar-verra linhas-issuances.json periodos.json
uv run python -m raiz.restauracao_validacao_arr comparar previsao.json observacao.json /caminho/privado/comparacoes-arr
```

O primeiro comando registra três confrontações, um diagnóstico e uma reconciliação
dos dois cortes do registro com a versão atual do motor. Cada conteúdo tem um arquivo identificado por SHA-256; repetição
idêntica reutiliza o registro, mudança de modelo/entrada gera outro, adulteração
é rejeitada. Nunca sobrescreve uma comparação anterior. O módulo não faz
requisições remotas, não escreve calibração e não modifica API, MCP ou front.

Verificação: testes de normalização histórica, seriais repetidos/conflitantes,
quantidades inválidas, emissão parcial, equivalência contábil, incompatibilidade
de área/período/coortes/pools, reserva histórica, independência, pequenas áreas,
versões e histórico imutável. A normalização também foi conferida no extrato
Berkeley real.
