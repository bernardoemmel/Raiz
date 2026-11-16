# Cartão do modelo Raíz

Versão deste cartão: 12/11/2026. Responsável: projeto Raíz, mantido no
[repositório público](https://github.com/bernardoemmel/Raiz).
Estrutura baseada em Mitchell et al., *Model Cards for Model Reporting* (2019).

A Raíz combina regras explícitas, cruzamentos geográficos e simulações para localizar áreas, comparar alternativas
de restauração e montar lotes de fazendas. As saídas são estimativas para planejamento e verificação posterior.
Toneladas simuladas não são créditos emitidos; a presença de uma metodologia ou de um formato de registro não
comprova certificação, titularidade ou aprovação de um projeto.

## 1. Identificação e funcionamento

Este cartão cobre quatro componentes. Não há um único modelo estatístico treinado que responda por todas as saídas.

| Componente | Método e saída | Identificação da versão |
|---|---|---|
| Funil por imóvel | Interseções do CAR com desmatamento, embargos, territórios, SIGEF e uso da terra; regras de RL e APP; estimativa de área restaurável e carbono bruto. Saída principal: `imoveis_<mun>.csv`. | Versão da tarefa e commit do motor; versão nomeada das regras federais. |
| Valor para quem restaura | Escolha entre regeneração assistida, semeadura e plantio; custos, captura, linha de base, descontos e fluxo de caixa por cenário. Saída: `desenvolvedor_<mun>.csv`. | `restauracao_versao`, `restauracao_cenario` e versão da tarefa. |
| FLAG | Partilha de áreas entre restauração e sistemas produtivos com árvores; remoções estimadas para silvipastoril e agrofloresta de cacau. Saída: `flag_<mun>.csv`. | `flag_regra_versao`, versão da tarefa e versão da transformação probabilística. |
| Caminho da terra | Regras de classificação entre matrícula, posse em titulação, assentamento, concessão, terra pública sem destinação e território tradicional; risco baixo, médio ou alto com motivo. Saída: `terra_<mun>.csv`. | `terra_regra_versao` e versão da tarefa. |

As regras de referência estão em
[`restauracao.yaml`](https://github.com/bernardoemmel/Raiz/blob/main/raiz/regras/padroes/restauracao.yaml),
[`ghg_lsr.yaml`](https://github.com/bernardoemmel/Raiz/blob/main/raiz/regras/padroes/ghg_lsr.yaml) e
[`caminho_terra.yaml`](https://github.com/bernardoemmel/Raiz/blob/main/raiz/regras/padroes/caminho_terra.yaml).
Os nomes de referência atuais são `restauracao-2026d`, `ghg-lsr-1.1` e `caminho-terra-2026a`;
o hash registrado no arquivo identifica a versão efetivamente usada. Uma atualização do código não altera a
proveniência de uma previsão antiga.

A restauração `2026d` inclui código e premissas na versão e adota reserva contra reversão de no mínimo **20%**,
uma política conservadora da Raíz. Previsões históricas `2026c` usavam piso de **12%**; permanecem identificadas
com sua regra original. A exportação de metadados ou cronogramas não converte esses créditos para a regra nova.

## 2. Uso pretendido e usuários

Uso pretendido: triagem territorial, comparação de cenários, orçamento preliminar, identificação do que precisa ser
medido ou regularizado e composição de grupos de fazendas para análise por desenvolvedores, compradores e técnicos.
O pedido de lote permite comparar custo, risco e proximidade, respeitando as condições do pedido.

Pequenas propriedades não são descartadas por tamanho: podem ser agrupadas. Ausência de matrícula é apresentada
como caminho de regularização e risco; posse não é denominada propriedade. A elegibilidade para um edital ou
operação específica pode limitar o lote contratado, sem apagar o imóvel do inventário territorial.

As saídas, isoladamente, não substituem inventário de campo, orçamento contratado, análise do CAR pelo órgão
competente, certidão atual e análise jurídica, consentimento do titular ou verificação independente. A Raíz não
declara que um projeto está registrado na Verra ou no CAD Trust por exportar seus dados nesses vocabulários.

## 3. Dados, cobertura e tratamento

O contrato de colunas está em
[`docs/colunas.md`](https://github.com/bernardoemmel/Raiz/blob/main/docs/colunas.md);
as fontes e sinais de atualização, no
[`manifesto da coleta`](https://github.com/bernardoemmel/Raiz/blob/main/raiz/coleta/manifesto.yaml).

| Grupo | Fontes e uso |
|---|---|
| Cadastro e território | SICAR/CAR, SIGEF/INCRA, Ibama, FUNAI, CNUC, quilombos e Cadastro Nacional de Florestas Públicas/SFB: geometria, restrições e evidências sobre a terra. |
| Cobertura e mudanças | MapBiomas, MapBiomas Alerta, PRODES/DETER, YbYrá-BR, JRC TMF, Global Pasture Watch e causas da perda de floresta WRI: uso da terra, desmatamento, regeneração, pasto e histórico de perturbação. |
| Condições locais | Copernicus DEM, CHIRPS, SoilGrids e OpenStreetMap: relevo, chuva, solo e acesso, quando disponíveis. |
| Premissas econômicas e de carbono | Tabelas de custos, curvas de captura, editais, literatura e dados públicos referenciados no YAML; parâmetros de cenário, câmbio e eventuais fatores de calibração. |

As coleções e datas das fontes são diferentes. A cobertura da projeção básica pública vem de
[`estados.json`](https://github.com/bernardoemmel/Raiz/releases/download/dados/estados.json), incluindo municípios
pendentes e etapas incompletas. O manifesto completo, as versões por arquivo e os resultados detalhados ficam no
armazenamento privado. Um estado publicado pode estar parcialmente processado. Ausência de observação,
falha de uma fonte e ausência real de uma restrição são situações diferentes.

O CAR é declaratório e seus polígonos podem se sobrepor. Uma parcela no SIGEF e o número de matrícula são evidências
para conferência, não prova automática de cadeia dominial válida. Limitações de resolução, datas de observação e
cobertura podem afetar mais os imóveis pequenos e áreas com menos informação. A hidrografia usada pelo motor não
representa todos os cursos d'água; estimativas de APP precisam de conferência local.

Não existe, para este conjunto de regras e simuladores, uma divisão única de treino, validação e teste equivalente
à de um modelo supervisionado. Parte dos números é premissa informada por fontes; fatores podem ser recalibrados
com resultados reais no módulo de aprendizado. `restauracao_faltou` identifica entradas que foram substituídas por
premissas neutras ou padrões. A existência dessa substituição não elimina a incerteza do dado ausente.

## 4. Quantis e interpretação das saídas

No formato hubverse, `output_type="quantile"` e `output_type_id` igual a `0.1`, `0.5` ou `0.9` identificam os três
pontos exportados no armazenamento privado. `location` é o código do imóvel; `target` distingue a grandeza e sua unidade. O `model_id` tem a
forma `raiz-<tarefa>_<hash>`; os metadados preservam `model_version` e as versões de origem.

`reference_date` é a data de execução registrada nos metadados do arquivo de origem. Não é, por si só, a data de
corte histórica de todas as imagens e cadastros utilizados. Não usar a data de publicação do Release como se fosse
uma nova previsão. Arquivos antigos sem data ou versão confiável devem ser identificados como incompletos na
exportação, sem atribuição retroativa da versão atual.

**Desenvolvedor.** Custos e captura têm faixas de entrada descritas nas premissas. Para créditos líquidos, VPL, TIR e
pico de capital, P10 e P90 são percentis da simulação. A configuração de referência usa 400 sorteios e semente 2026;
custo e captura são sorteados de forma independente em uma normal de dois lados, truncada em zero. A mesma semente
é reutilizada entre imóveis. O valor chamado P50 nos arquivos existentes é o resultado determinístico das entradas
centrais, e não necessariamente a mediana empírica dos 400 resultados. Portanto, esses três valores não demonstram,
por si só, uma distribuição preditiva calibrada. Valores cruzados ou não finitos exigem diagnóstico; ordenar a faixa
silenciosamente ocultaria o problema.

**FLAG.** As colunas legadas de mínimo, central e máximo são limites e referência provisórios, não percentis
observados. A exportação probabilística explicita uma distribuição triangular a priori com esses limites e o
central como moda; P10/P50/P90 são calculados dessa distribuição. É uma hipótese operacional versionada, sem
calibração empírica. O novo P50 pode diferir do central legado. A transformação não constitui evidência de que 80%
das remoções reais cairão entre P10 e P90.

**Lote.** A faixa da carteira usa um fator comum de erro e uma parcela própria de cada imóvel. Na configuração de
referência, 60% da variância é comum; são 8.192 amostras com sequência de Sobol para o fator comum e semente
20261112. Essa correlação é premissa a calibrar. A soma direta dos P10/P90 individuais também é mostrada como cenário
em que todas as fazendas erram juntas. O P50 do lote é a soma dos valores centrais. Nenhuma dessas alternativas
garante a diversificação real da carteira. “P90 de excedência”, usado em certos referenciais de reservas, corresponde
ao P10 probabilístico: a convenção deve ser identificada antes da comparação.

Unidades e horizonte precisam acompanhar cada alvo: hectare, tCO2 por hectare por ano, tCO2 no contrato, reais por
hectare e percentual não são intercambiáveis. Os valores do modelo dependem do cenário econômico e dos períodos de
captura. Estimativas anuais de um cronograma correspondem a incrementos; os marcos acumulados não devem ser somados
como se fossem emissões anuais independentes.

O exportador CAD Trust usa o cenário ProFloresta+ `central_r11` e a curva de captura do lote. Arredonda os
acumulados e calcula a diferença entre anos, preservando o total inteiro e conferindo os marcos. O início padrão
do cenário no Actions é **01/01/2027**, uma hipótese configurável em `RAIZ_CADT_INICIO_CENARIO`, sem afirmar data
contratada de implantação. `Listed` significa listagem no catálogo de cenários da Raíz. Ausência de área elegível,
cronograma ou premissas válidas gera diagnóstico, sem inventar um projeto.
CSV do desenvolvedor sem versão/cenário, com versões misturadas ou sem uma regra correspondente verificável impede
o projeto estadual, mesmo que os números pareçam compatíveis. A versão histórica `restauracao-2026c+421970fd` foi
recuperada do commit `8eebc6a90bc20bce585520cee81bbebdd1ff93df`; o registro fechado confere hashes integrais da regra,
do câmbio e do edital. O construtor histórico preserva o cenário com reserva base de 12%, sem aplicar o
normalizador atual de 20% aos créditos já publicados. O cronograma conserva o P50 e a curva originais, enquanto
a seleção usa o otimizador e as salvaguardas atuais. A identidade do projeto inclui as versões do código do lote,
do cenário de seleção e das salvaguardas; a versão científica da fonte permanece separada.

Sobreposição jurisdicional confirmada e CLPI recusada bloqueiam a seleção também nesse caminho histórico.
Informação desconhecida mantém uma pendência de diligência, sem liberar venda. O envelope CADT declara a
comercialização pendente; não publica decisões por imóvel. Não recalcula os fluxos individuais nem atribui a
versão nova a uma previsão antiga. Outras versões precisam de registro verificável; não são inferidas por prefixo.

Para `restauracao-2026b+cenarios-2026b+dbc2776a`, o registro do commit
`deec7a776378056509b2cd37e0894f4d00922b84` preserva a curva com cauda decrescente após o ano 14 e a reserva histórica
de 12%. O hash dos três YAMLs, os hashes do código original e a tarefa `desenvolvedor-4e142d4bfca2` identificam
esse perfil. Cada arquivo de origem deve ter a tarefa original e SHA-256 compatível; um carimbo de adoção atual
não basta. A seleção de carteira usa a política atual identificada separadamente, sem reaplicar reservas ou
descontos aos créditos antigos. O método `cronograma-deterministico-2026b-1` distribui somente o P50 já publicado
pela curva histórica até o ano 25, conservando o total. Ele não recupera probabilidades históricas do lote, multas
ou fluxos individuais. Método e política de seleção entram na identidade CAD Trust; os parâmetros modernos não
são acrescentados aos YAMLs históricos.
O adaptador confere as áreas publicadas com tolerância de 0,0002 ha pelos arredondamentos e exige que
o P50 por hectare do horizonte de 40 anos supere o do contrato de 25 anos por mais de 0,1. Essa diferença
comprova que o teto de captura não foi atingido até o ano 25; casos inconclusivos geram diagnóstico.
O cronograma não recupera a precisão anterior ao arredondamento nem trajetórias individuais não publicadas.

O exportador CADT `raiz-cadt-cenarios-1.3.0` usa o total literal `credito_liquido_tco2_contrato` em todas as
versões suportadas. O total por fazenda e o P50 por hectare foram arredondados separadamente; multiplicar a
coluna por hectare pela área poderia alterar os créditos publicados. Total ausente, não finito, negativo,
fracionário ou sem correspondência única gera diagnóstico. Uma UF sem caminho fundiário elegível conserva
a proveniência resolvida e as contagens de seleção, mas não recebe um cronograma fictício.

## 5. Avaliação e métricas

O repositório contém testes de contratos, regressão e propriedades: por exemplo, 72 casos de referência do Pará
para as regras federais, comparação entre Catala e cálculo vetorizado, conservação de áreas, partilha FLAG/crédito,
fluxos financeiros, versões e composição de lotes. Esses testes verificam consistência do software e da regra
implementada. Não medem acerto em campo nem substituem validação jurídica externa.

O [módulo de avaliação](https://github.com/bernardoemmel/Raiz/blob/main/raiz/aprendizado/acerto.py) implementa WIS,
erro absoluto e cobertura do intervalo P10–P90; para outros tipos de previsão, também erro quadrático, Brier,
log score e acerto categórico. Métrica implementada não significa resultado de desempenho obtido.

Este cartão não publica valores empíricos de WIS, cobertura de 80%, erro de captura, custo ou classificação da terra:
não foi fornecido aqui um conjunto independente de gabaritos com amostra, período e resultados verificáveis.
Também não há, neste cartão, comparação de desempenho por UF, bioma, porte, caminho da terra ou método. A avaliação
operacional deve informar número de previsões maturadas, número com gabarito, período, versão, origem do gabarito e
os recortes, preservando a privacidade. A cobertura nominal de 80% é uma hipótese a avaliar, não uma taxa de acerto
comprovada.

## 6. Limites, efeitos e decisões humanas

As faixas não incluem automaticamente toda incerteza de cadastro, legalidade, adicionalidade, titularidade, preço,
aceite do dono, permanência, cronograma ou mudança regulatória. O crédito líquido é uma simulação dos descontos
implementados, não uma emissão validada. A adoção de VM0047 no cálculo não demonstra cumprimento de todos os seus
requisitos. Os estados “baixo”, “médio” e “alto” do caminho da terra são classes de regra, não probabilidades
calibradas de perda ou disputa.

A regra FLAG separa remoções nos sistemas produtivos com árvores das áreas de restauração e compensação. As
toneladas FLAG não se somam às de crédito como um único ativo; a mesma área não deve ser contada duas vezes. A regra
GHG LSR v1.1 registra adoção em 12/11/2026 e vigência em 01/01/2027 no YAML. Elegibilidade efetiva exige rastreio,
medição, tratamento de perdas e definição do direito de reportar, conforme o padrão aplicável.

Terras indígenas e territórios tradicionais não são estoque disponível para originação comercial com terceiros.
O caminho da terra preserva a identificação desses territórios e as condições de consulta e direitos registradas
na regra. Uma estimativa favorável de carbono ou renda não autoriza contato, negociação ou intervenção na área.

Priorizar apenas custo ou disponibilidade de dados pode favorecer imóveis maiores ou regiões melhor documentadas.
O agrupamento de pequenas propriedades e a apresentação de dados faltantes são controles do produto; seus efeitos
precisam ser acompanhados nos resultados reais, inclusive por porte e região.

## 7. Privacidade, licenças e proveniência

O Release público `dados` contém somente situação básica por CAR, geometria sem atributos pagos e agregados
municipais permitidos, com supressão de grupos pequenos. Quantis P10/P50/P90, TIR, detalhes da terra, dados do hubverse
(inclusive listas de CARs em `tasks.json`), diagnósticos e cronogramas CAD Trust ficam no armazenamento privado.
As fichas Croissant e seus catálogos seguem o mesmo escopo dos arquivos descritos. O cartão metodológico pode ser
público porque não contém resultados individuais ou agregados privados.

Nome, CPF, CNPJ e contato do dono não integram esses artefatos. CPF/CNPJ são mascarados onde o tratamento é
necessário. O código do CAR é uma chave geográfica pública e não torna o conjunto anônimo; retirar identificadores
pessoais também não torna públicos os resultados pagos ou privados.

O destino privado atual é um Release não publicado (`dados-privados`), que deve permanecer em rascunho. As URIs
`release-github://dono/repositorio/tag/arquivo` das fichas privadas são identificadores lógicos sem credenciais.
O servidor autorizado resolve o asset pela API autenticada e confere sua privacidade antes do acesso. O leitor
Croissant recebe um arquivo local autorizado; essas URIs não prometem download público nem autenticação nativa
do leitor. Fichas públicas apontam somente para os bytes da projeção básica no Release público.

Licenças e atribuições de fontes e bibliotecas estão em
[`NOTICE.md`](https://github.com/bernardoemmel/Raiz/blob/main/NOTICE.md). A licença de redistribuição dos dados
derivados da Raíz ainda não foi definida; este cartão não concede uma licença nova. Licença de software, ficha
Croissant e acesso público ao Release não substituem os termos das fontes. Há fontes com termos a conferir no
manifesto; a referência Heinrich et al. 2021, marcada CC BY-NC no NOTICE, permanece fora de treino. Essa restrição
não é resolvida pela publicação de metadados.

Cada pacote estadual completo privado inclui `_versoes.json` com tarefa, versão, data e SHA-256 dos arquivos quando
disponíveis; a projeção pública não contém esse controle. Cada `estados.json` identifica somente seu escopo de
publicação; fichas Croissant descrevem arquivos e campos do mesmo destino. SHA-256 identifica
bytes. Uma attestation do GitHub Actions, quando existente e verificada, vincula o artefato à execução que o
publicou; não certifica a veracidade científica, a qualidade dos dados ou a conformidade de um projeto de carbono.

## 8. Manutenção e atualização

As previsões devem ser conservadas com sua versão para comparação posterior com o resultado real. Alterações de
premissas, calibração, código ou fontes devem gerar nova identificação apropriada e recálculo das tarefas afetadas.
Resultados antigos não devem receber retrospectivamente a versão nova. A versão científica da linha, a versão da
tarefa, o cenário e o commit têm papéis distintos e devem ser consultados em conjunto.

Os assets públicos básicos e os canônicos completos privados são retratos atuais e podem ser substituídos.
No armazenamento privado, `modelos.json` conserva a descrição das versões já exportadas; isso não equivale a um
arquivo histórico de todos os valores previstos.
A conservação longitudinal para aprender com resultados reais pertence ao armazenamento de previsões do módulo
de aprendizado. Para reproduzir um retrato público, conservar seus arquivos, checksums e atestação.

Atualizar este cartão quando mudarem dados, distribuição de incerteza, critérios de terra, uso pretendido ou
evidências de desempenho. Ao publicar métricas, registrar amostra e limitações em vez de extrapolar os testes de
software para o Brasil inteiro. Correções e questões técnicas podem ser registradas no
[repositório da Raíz](https://github.com/bernardoemmel/Raiz/issues).
