# Lotes privados por estado, bioma e Brasil

O catálogo conserva previsões por imóvel e sua versão original. Uma consulta escolhe três opções sobre a
cobertura compatível disponível; não recalcula todos os municípios. Ausência de município ou previsão antiga
não significa oferta zero. A meta, a reserva e os marcos precisam ser lidos junto da cobertura.

## Atualização e pedido

O workflow `lote-nacional.yml` recebe conclusão bem-sucedida do processamento dos estados, reconcilia a cada
duas horas e aceita disparo manual com UFs, bioma ou Brasil e um JSON `CamposPedido`. Checkout sempre da
`main`, inclusive em `workflow_run`. Reserva uma cota na fila CAS de quinze antes dos dados; se estiver cheia,
espera conclusão natural, sem cancelar os estados. Não usa artifacts nem caches públicos.

A atualização congela base e geometria sob a trava estadual, verifica a proveniência e publica cópias imutáveis.
O índice muda só para municípios cujos arquivos ou regras mudaram. Cada UF concluída tem checkpoint recuperável;
interrupção posterior não refaz as anteriores. O ponteiro `lote_nacional_atual.json` é promovido depois de
conferir os arquivos publicados por leitura, tamanho e SHA-256. Um snapshot imutável precede cada troca.

Para o Pará, o histórico integral conferido de 144 municípios permanece enquanto o arquivo canônico não tiver
as 144 tabelas de previsão do mesmo modelo. Isso preserva as dez fatias antigas e as cinco retomadas; indexar e
consultar não chama o cálculo municipal. Outros estados com previsões incompatíveis entram em pedido incremental
de manutenção pelo workflow existente, uma vez por versão da fonte, sem apagar tabelas.

Exemplos no ambiente autenticado do arquivo privado:

```bash
uv run python -m raiz.restauracao_nacional_rodada --consultar --uf PA
uv run python -m raiz.restauracao_nacional_rodada --consultar --bioma Cerrado
uv run python -m raiz.restauracao_nacional_rodada --consultar --brasil --pedido pedido.json
```

Sem recorte explícito, a automação publica cada UF disponível, os seis biomas e Brasil. Um pedido por UF inteira
ou Brasil não herda o filtro Amazônia do formulário legado. Preço ou dívida diferentes das previsões exigem
reavaliar a oferta; o programa recusa reutilizar a TIR original como se fosse sensibilidade.

## Seleção, incerteza e diligência

Pequenas vizinhas formam grupos indivisíveis, inclusive atravessando limites municipais/estaduais. Não há piso
de área: áreas positivas menores que 1 ha e que 0,05 ha permanecem. Sem localização confiável, o imóvel continua
com agrupamento pendente; coordenada de sede municipal não prova vizinhança. Contiguidade exige evidência de
polígonos, nunca soma de áreas de pontos.

A seleção usa busca limitada: começa com 128 grupos, amplia até 3.000 e limita cada solver a 15 segundos.
A opção compacta procura vizinhanças em até 32 âncoras, além do custo por grupo. Não promete ótimo global.
Restrições de distância e número de donos são conferidas incluindo reservas e fallback. O diâmetro informado
é um limite superior da bola geográfica, não distância medida entre polígonos.

Os quantis de crédito da carteira usam a aproximação normal assimétrica com fator comum explicitamente
registrado, distinta da soma dos quantis marginais. O P50 legado de TIR é caminho central, não mediana dos
sorteios. O fluxo agregado reutiliza o cálculo financeiro existente e apenas entradas congeladas das selecionadas:
não calcula média de TIR, não paga preço contratado ao excedente e preserva dívida, multas e marcos.

O pacote privado tem CSV/Parquet das três opções, resultado JSON portátil, decisões revisáveis e diagnóstico
JSON/CSV/Markdown/HTML das travas para metas de créditos. Preço do cenário, custo médio, TIR mediana entre
fazendas e terra documentada versus pendente são grandezas distintas. O relatório não autentica títulos nem
libera venda. Pacotes incluem versão financeira, versão do seletor, hashes das entradas e identidade do pedido.

## Medições de escala

Medições em 12/11/2026 (Brasília), Linux, cgroup de quatro CPUs. Os resultados financeiros e vínculos a imóveis
continuam no arquivo privado; abaixo há somente cobertura e desempenho computacional.

| Base | Imóveis | Três opções + auditoria | RSS máximo | Limite da medição |
|---|---:|---:|---:|---|
| Sintética, 80% pequenas | 7.000.000 | 66,67 s | 2.383 MiB | Sem coleta, previsão municipal ou recomposição financeira |
| Real, 786 municípios/13 UFs | 1.530.808 | 22,77 s | 1.137 MiB | Inclui verificação dos índices e fluxo financeiro das selecionadas; sem baixar/indexar fontes |

Seletor medido: `lote-nacional-1+16896488fb3d`; modelo financeiro `restauracao-2026d+a84f9789`.
A guarda posterior que recusa preço/dívida incompatíveis também vale para cronograma livre; não altera os
resultados centrais medidos. O índice real tem 1.100.628 previsões compatíveis, 346.010 antigas e 84.170 ausentes.
Oito UFs requerem manutenção (AC, AP, GO, MA, MG, RO, RR, TO); a disponibilidade municipal também é parcial.
A primeira construção do índice levou 24,58 minutos; é uma atualização de dados, não latência da consulta.

Reprodutor sintético, em diretório novo para impedir resultado em cache:

```bash
uv run python -m raiz.restauracao_benchmark --linhas 7000000 --misto --destino /caminho/privado/benchmark
```

O arquivo `benchmark.json` registra versão, identidade do catálogo, tempos, memória, cota de CPU e diagnósticos
da busca. A base sintética não comprova cobertura do Brasil nem qualidade científica das previsões.

Repetição após integração R12 (13/11/2026 UTC): sete milhões de imóveis, 80%
pequenos, três seleções e auditoria em **67,43 s (1,12 min)**; preparo do índice
sintético 10,71 s; pico 2.386 MiB. Seletor `lote-nacional-1+63098e6a63a3`, índice
`oferta-nacional-1+f6f4b19196b9`, modelo `restauracao-2026d+490ab152`.
Execução em cgroup de quatro CPUs, com testes Python concorrentes no ambiente;
não mede coleta, previsões municipais nem recomposição financeira. O resultado
completo está em `/tmp/raiz-benchmark-nacional-r12/benchmark.json` até a publicação.
