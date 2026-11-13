# Município novo na malha nacional

A publicação diária parou porque Boa Esperança do Norte (`5101837`) já tinha 406
desenhos no Release, mas ainda não constava na malha de 5.570 municípios do
TerraBrasilis. O [run 43478574515](https://github.com/bernardoemmel/Raiz/actions/runs/43478574515)
recusou corretamente publicar essa cobertura incompleta.

A correção detecta os códigos publicados ausentes e atualiza a **UF inteira** pela
edição mais recente da Malha Municipal Digital do IBGE. Assim, o novo município
entra junto com as divisas atualizadas dos municípios que cederam seu território.
Não há exceção de código para esse município nem lista fixa de UFs a atualizar.

A prova real usou o [ZIP oficial de Mato Grosso de 2025](https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2025/UFs/MT/MT_Municipios_2025.zip),
com 142 feições em SIRGAS 2000. A malha foi transformada para WGS84 e generalizada
para visualização. A [nota técnica de 2025](https://www.ibge.gov.br/biblioteca/visualizacao/livros/liv102268.pdf),
página 9, declara termos compatíveis com CC BY 4.0, inclusive uso comercial, e
exige identificar as adaptações. Fonte, ano, hash e aviso de generalização são
publicados por UF; os outros estados não recebem a data da edição de MT.

| Conferência | Resultado |
|---|---|
| Códigos nacionais únicos | 5.570 → 5.571 |
| Municípios de Mato Grosso | 141 → 142 |
| Novo município × Sorriso/Nova Ubiratã | Interseção zero após a generalização |
| Feições das outras UFs | Idênticas às do snapshot anterior |
| Tempo da prova geográfica local | 5,54 s; não é medição do site |
| ZIP oficial | 9.476.597 bytes, SHA-256 em [origem.json](origem.json) |

Os ZIPs e seus hashes ficam em cache. Uma retomada reaplica a edição conferida sem
rede; só procura outra edição se faltarem códigos nela. A atualização preserva os
ZIPs anteriores, os CARs e as bases PMTiles. Recortes municipais comprimidos antigos
também são atualizados. O build continua recusando uma malha incompleta ou de hash
divergente.

O índice público ganha somente `malhas`, um mapa por UF de `{fonte, ano, sha256}`.
O contrato recusa campos extras e não admite URLs livres ou informações individuais.
Nenhum ZIP, cache ou arquivo pago é acrescentado ao site.

[Relatório real](relatorio.json) · [Prova de retomada sem rede](retomada.json).
A correção passou em 27 testes Python e 37 testes de frontend focados, TypeScript
e Ruff. O CI integrado e a publicação efetiva são conferidos separadamente no PR.
