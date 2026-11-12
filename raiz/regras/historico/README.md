# Premissas históricas de restauração

Este registro preserva os bytes originais dos YAMLs usados para interpretar previsões já
publicadas. Não recalcula previsões por imóvel e não substitui a versão antiga pela atual.

`restauracao-2026c+421970fd` corresponde ao commit
[`8eebc6a90bc20bce585520cee81bbebdd1ff93df`](https://github.com/bernardoemmel/Raiz/commit/8eebc6a90bc20bce585520cee81bbebdd1ff93df).
O hash dos arquivos históricos de código e dessa versão de premissas também reproduz
`desenvolvedor-59f38ae40fcd`, registrado nos artefatos originais de RO.
O carregador informa essa reconstrução como `versao_tarefa_referencia`; não confere o
código que produziu os CSVs recebidos pelo consumidor. Essa confirmação requer examinar
o `_versoes.json` correspondente, pois a mesma versão de premissas pode ser usada por
versões diferentes do código.

O manifesto registra o SHA256 integral da regra e do câmbio unidos por `\n--\n`, os hashes
individuais e objetos Git da regra, câmbio e edital. Não existia arquivo de calibração nessa
versão. O carregador fixa o hash do próprio manifesto e confere todos os arquivos antes
de interpretar os YAMLs. Não consulta a rede nem executa código recuperado do Git.

A comparação estática com `59847e89f59b7ebbbd9f9872813431a062f74bc5` confirmou igualdade
das árvores sintáticas de `forma_curva`, `cronograma_lote`, `cenario`, `_normalizar`,
`contrato_para_marcos`, `fator_captura_alvo`, `_sorteios` e `_dois_lados`. A curva, os marcos,
o Monte Carlo e o câmbio são iguais. A nova regra acrescentou carteira, parcelas,
sensibilidade e não permanência, ativando reserva por fazenda no cenário central; por isso
os hashes completos diferem e não são tratados como versões intercambiáveis.

`carregar(versao)` retorna `(regra, proveniencia)` somente para versões cadastradas e
verificadas. Versão desconhecida retorna `None`; falha de integridade gera erro genérico.
O consumidor deve usar os créditos publicados, preservar essa proveniência e gerar apenas
o cronograma agregado. `lote.montar` inclui recálculo econômico por imóvel e não deve ser
usado para esse caminho de exportação histórica.
