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

A comparação estática foi refeita com a main
`78e13f7babcbc46d368e291b2a5c74431120d60b`: as árvores sintáticas de `forma_curva`,
`cronograma_lote`, `contrato_para_marcos`, `fator_captura_alvo`, `_sorteios` e `_dois_lados`
continuam iguais às históricas. Não executamos código recuperado do Git para comparar.

O construtor atual `restauracao._ler` passou a incluir o código no hash. Por isso, este
registro interpreta diretamente os YAMLs já verificados e recompõe a versão pelo algoritmo
histórico, que unia somente regra e câmbio. A normalização atual também impõe reserva mínima
de 20%; `cenario("central_r11", regra)` mantém os 12% documentados na previsão histórica.
Todos os campos do cenário central já estão declarados nos dados preservados: o adaptador
somente ordena marcos, converte tipos e aplica a PTAX histórica, sem importar defaults atuais.
Ele aceita apenas o cenário central de uma regra idêntica ao registro canônico.

Carteira, parcelas, sensibilidade, não permanência e outras regras posteriores não são
introduzidas nos dados históricos. O modelo ecológico usa versão e hash próprios; não
faz parte desta versão de restauração. As versões históricas e atuais não são tratadas
como intercambiáveis, e recuperar a curva não libera venda nem contorna as salvaguardas
atuais aplicadas à seleção do lote.

`carregar(versao)` retorna `(regra, proveniencia)` somente para versões cadastradas e
verificadas. Versão desconhecida retorna `None`; falha de integridade gera erro genérico.
O consumidor deve usar os créditos publicados, preservar essa proveniência e gerar apenas
o cronograma agregado. `lote.montar` inclui recálculo econômico por imóvel e não deve ser
usado para esse caminho de exportação histórica.
