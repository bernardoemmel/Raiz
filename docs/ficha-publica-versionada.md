# Ficha pública básica datada

A ficha atual `/p/{codigo}` oferece um link datado depois do aceite vigente do produtor. O endereço é
`/p/{codigo}/v/{AAAA-MM-DD}-r{rodada_id}-{sha256}`. O mesmo endereço com `.md`, ou com `Accept: text/markdown`,
entrega a representação Markdown. O código curto continua sendo sorteado; o endereço não contém o CAR.

O conteúdo básico é congelado na tabela `negocio.ficha_publica_versao`. A lista de campos é fechada:
código curto, município, UF, área do polígono do CAR, situação básica, rodada, data de corte e fonte. O hash é
calculado somente sobre esses campos. A data em que a versão foi registrada também aparece na página,
separada da data de corte: registrar hoje uma rodada antiga não significa que a página existia naquela data.

Cada versão usa a linha histórica de `funil.resultado_imovel` e a data da respectiva `funil.rodada`.
Não usa município, área ou outros atributos do cadastro atual para completar lacunas do passado.
Município e UF históricos precisam corresponder ao catálogo IBGE versionado; texto livre, divergência e
campos ausentes ficam não informados. A situação básica vem da foto de `funil.etapa_rodada`, gravada por
`carga._fotografar_etapas` na carga daquela rodada. Não se recalcula o passado com as regras do motor atual.
As etapas cadastro e sem_problema correspondem a com pendência e não apto; as etapas aptas reconhecidas,
inclusive o antigo nome com_matricula, correspondem a apto. Foto ausente ou etapa desconhecida produz
“Ainda não conferida”, nunca zero ou aprovação implícita. Insumos privados não são consultados para a tradução.

O conteúdo de uma versão não aceita UPDATE ou DELETE. Correções exigem outra rodada. As versões não dependem
da retenção dos resultados privados de origem. A página antiga avisa quando existe uma rodada posterior,
comparando primeiro a data de corte e depois o id da rodada; carregar hoje um arquivo mais antigo não o torna
a versão mais recente. O aviso pode mudar, mas os fatos e o identificador da versão consultada permanecem.

A publicação datada exige `negocio.aceite.estado = 'aceito'` em **toda consulta**. Recusa, cancelamento,
revisão, retorno ao andamento ou remoção do aceite bloqueiam inclusive links emitidos antes. Essa tabela
atualmente não define uma data de expiração; não se reutiliza a validade de login, reserva ou Pix para simular
um prazo de consentimento. Caso o contrato de aceite passe a ter prazo, ele deve ser verificado no mesmo portão.
As respostas usam `Cache-Control: private, no-store`, inclusive para cartões, vídeos e imagem da ficha atual,
para que o navegador volte a consultar a autorização. Uma cópia já baixada não pode ser recolhida pelo servidor.
Se o aceite mudar entre a primeira leitura da ficha atual e a revalidação para o link datado, a resposta
falha fechada com 404, sem renderizar CAR ou imagem com a autorização antiga.

A versão datada não contém nome, CPF, contato, CAR completo, geometria, satélite, hectares elegíveis,
carbono, receita, TIR ou números da ficha paga. Não aponta uma imagem Open Graph da ficha atual, pois uma
imagem mutável não comprova o retrato antigo. A ficha atual preserva sua regra anterior de CAR/satélite somente
após o aceite; o número compartilhável de hectares passa a ser exclusivamente a área do CAR. Cartões e vídeos
recebem uma lista positiva de campos, sem propagação automática de colunas novas.

A API autenticada e o histórico privado de compromissos/fichas são contratos separados. Este recurso não
abre essa área. Os testes em `testes/test_publico_versoes.py` cobrem conteúdo congelado, hash básico, catálogo,
revogação, caminhos inválidos, retenção, cronologia e equivalência entre HTML e Markdown.
