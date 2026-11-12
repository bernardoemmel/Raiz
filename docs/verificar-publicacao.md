# Verificar os Releases publicados

Em um checkout do repositório, com Python 3.12+, `uv`, Git e GitHub CLI no `PATH`:

```sh
uv run --locked --extra metadados python -m scripts.verificar_release_dados --escopo ambos
```

Forneça `GH_TOKEN` no ambiente. Para outro arquivo privado, use também
`RAIZ_DADOS_PRIVADOS_URL` e `RAIZ_DADOS_PRIVADOS_TOKEN`, conforme o contrato de
publicação. O destino privado precisa ser um repositório privado ou um Release
em rascunho. O `gh` instalado precisa oferecer `attestation verify`,
`--signer-workflow` e `--deny-self-hosted-runners`; `--gh` permite indicar outro
executável. A política aceita somente os workflows `publicar-metadados.yml` e
`processar-estados.yml` de `bernardoemmel/Raiz`, com runners hospedados. Subjects
privados devem ter o formato `privado-sha256-<SHA256 dos bytes>`.

`--cache DIRETORIO` e `--relatorio ARQUIVO` controlam as saídas locais. Por padrão,
ficam em `$XDG_CACHE_HOME/raiz/verificacao-release`, ou
`~/.cache/raiz/verificacao-release`; o relatório se chama `relatorio.json`.
O cache privado contém os produtos completos: mantenha-o fora do Git e não
publique seus arquivos. `--arquivos-locais DIRETORIO` reutiliza downloads
existentes somente depois de conferir o hash. Os relatórios registram nomes de
assets, contagens, hashes e códigos de erro; não registram linhas por imóvel,
tokens nem respostas brutas do GitHub CLI.

O verificador usa somente GET nas APIs dos Releases, sem publicar, reparar,
reservar jobs ou alterar Actions. Confere os bytes, o contrato de todos os
produtos públicos, as fichas Croissant 1.1/schema.org Dataset, os CSV descritos,
os quantis e suas versões/configurações, os vínculos de proveniência, o cronograma
CAD Trust e as assinaturas. Arquivos privados de infraestrutura e históricos
seguem o filtro `arquivos_produto` do publicador: entram no inventário de
estabilidade, mas não são baixados nem precisam de ficha. Infraestrutura no canal
público é recusada. O pacote hubverse recebe conferência de hash e ficha; seus
arquivos internos não passam por uma segunda validação semântica.

Os códigos de saída são: **0**, verificação completa; **1**, erro ou mudança
observada; **2**, conferência de conteúdo sem assinaturas, solicitada por
`--sem-atestacao`. No último caso `verificacao_completa` permanece falsa. Para
validar a publicação, exija também `integridade_ok`, `snapshot_estavel` e
`snapshot_final_estavel` verdadeiros nos canais solicitados.

Execute após a conclusão natural dos escritores antigos. O script compara
inventários completos, IDs dos Releases e visibilidade antes/depois de cada
canal, e reconfere ambos ao final. Isso detecta mudanças observadas durante a
leitura; a API não fornece uma transação atômica entre Releases nem impede uma
escrita após a última consulta. Se houver concorrência, espere a rodada terminar
e execute novamente. A verificação não recalcula os cenários nem prova sua
correção científica. Preservar dados anteriores ao preenchimento do catálogo
exige um inventário de referência capturado imediatamente antes dessa operação;
este comando não substitui essa comparação histórica.
