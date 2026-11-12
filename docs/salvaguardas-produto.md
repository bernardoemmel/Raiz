# Salvaguardas de restauração e decisão automática

A política Raíz usa reserva contra reversão de **pelo menos 20%** em qualquer cenário, mesmo sem série de fogo e
mesmo quando o simulador recebe um percentual menor. Risco calculado ou cenário acima disso eleva a reserva. O piso
está em `nao_permanencia.piso`, a versão é `restauracao-2026d` e o cálculo mantém 20% como mínimo mesmo se a configuração
for reduzida. Créditos e TIR anteriores precisam de recálculo; resultados da versão anterior não mudam retroativamente.

Esse é o piso conservador escolhido pela Raíz. O [ICVCM, critério 9.4](https://icvcm.org/wp-content/uploads/2024/02/CCP-Section-4-V1.1-FINAL-15May24.pdf)
admite reserva coletiva de 20% **ou** quantidade proporcional ao risco comprovado. Não significa que toda metodologia
ou todo programa jurisdicional imponha 20% (REDD+ jurisdicional possui critério próprio 9.5).

## Sobreposição com REDD+ jurisdicional

`geo.redd_programa` recebe polígonos em EPSG:4674, UF, período contábil, URL da fonte e hash/data da evidência. Cada
identificador é imutável e representa um programa/período. O cruzamento usa a interseção dos polígonos reais em
PostGIS, com área em hectares; não usa apenas sede municipal ou centroide. A API oferece a camada GeoJSON em
`GET /salvaguardas/redd.geojson` para uma sessão da empresa.

A [Lei 15.042, art. 43](https://www2.camara.leg.br/legin/fed/lei/2024/lei-15042-11-dezembro-2024-796690-normaatualizada-pl.html)
exige conciliação com o programa jurisdicional e comunicação de exclusão ao CONAREDD+, para evitar dupla contagem.
Uma sobreposição identificada sem evidência da comunicação **por programa/período** impede originação no lote.
A camada identifica períodos passados e futuros para conferência; não produz nem vende resultados futuros do programa.

Tabela vazia significa `nao_verificado`. Para declarar ausência, a equipe precisa atestar a cobertura da UF com
hash/data e validade de até um ano em `geo.redd_cobertura`. A ausência de geometria também fica não verificada.
Estimativas preliminares continuam visíveis; a reserva aguarda a conferência documental e territorial. Não há
polígonos nem atestados inventados ou pré-aprovados no repositório.

Rotas internas (token operacional):

- `POST /salvaguardas/programas`: cadastro imutável do polígono e período;
- `POST /salvaguardas/cobertura`: atestado de cobertura da UF, com validade;
- `POST /salvaguardas/imoveis/{cod_imovel}`: evidência estruturada da verificação e protocolos de exclusão.

A oferta refaz a avaliação na leitura; inserir evidência não exige esperar outra carga do município. As funções
`avaliar()` e `exigir_para_reserva()` distinguem pré-estimativa de reserva. O mapa continua mostrando fazendas pequenas;
não há corte de área mínima nesta regra.

## Território tradicional

A marcação vem dos dados territoriais, hectares de TI/quilombo ou da verificação humana. Uma declaração posterior
não apaga uma sobreposição já identificada. Para avançar, são exigidos consulta livre, prévia e informada, consentimento
explícito, data anterior ao início previsto, cláusula contratual da participação, conta específica e gestão participativa.
O [art. 47](https://www2.camara.leg.br/legin/fed/lei/2024/lei-15042-11-dezembro-2024-796690-normaatualizada-pl.html)
assegura **50% ou mais dos créditos para remoção**, e **70% ou mais para REDD+ de mercado**. Os documentos e a identidade
dos participantes ficam em cofre privado; a API guarda somente hash e data. A consulta é custeada pelo desenvolvedor.
A comprovação dessas condições não substitui titularidade, anuência ou outras proibições territoriais: as travas
existentes de terra indígena/tradicional continuam valendo.

## Revisão humana

A [LGPD, art. 20](https://www2.camara.leg.br/legin/fed/lei/2018/lei-13709-14-agosto-2018-787077-normaatualizada-pl.html)
assegura solicitação de revisão e informações sobre critérios. A revisão **por pessoa** é compromisso explícito da Raíz.
Os itens do lote e a avaliação territorial apontam a rota `POST /pedidos/{pedido_id}/revisoes`, com código do imóvel e
motivo fechado (`exclusao_automatica`, `nota_de_risco` ou `salvaguarda`). O pedido deve pertencer à empresa autenticada.
O detalhe exige a mesma liberação da ficha (sinal pago e contrato, conta não bloqueada), e o imóvel deve constar
na sugestão atual ou no grupo persistido do pedido, inclusive quando marcado como fora do grupo. Uma fazenda reservada
por outra empresa não revela detalhes nem pelo histórico de revisões. Não há ainda registro dos candidatos descartados
antes de gerar uma sugestão: esses códigos não podem abrir uma revisão pela API até existir vínculo comprovável com
a decisão do pedido.

O protocolo guarda critérios e versão naquele instante, aceita repetição sem duplicar a solicitação pendente e pode
ser acompanhado em `GET /pedidos/{pedido_id}/revisoes`.

A resolução interna exige, além do token operacional, `X-Revisao-Humana` igual a `RAIZ_REVISAO_HUMANA_TOKEN`, credencial
separada entregue somente ao backoffice humano. O corpo inclui identificador opaco do revisor, decisão e hash/data da
evidência. O cliente recebe resultado e datas, nunca identidade do revisor. A decisão pode manter, pedir correção dos
dados ou pedir recálculo; **não** remove bloqueios legais nem altera silenciosamente o lote. A equipe executa a correção
ou o recálculo com as evidências pertinentes. Agentes não devem receber a credencial humana.

Testes cobrem piso independente do cenário, sobreposição real, exclusão de outro período recusada, ausência de dados,
participação de 50%/70%, CLPI, isolamento entre empresas e rejeição de resolução com credencial só de serviço.
