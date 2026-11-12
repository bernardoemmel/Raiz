# Dados do motor publicados (Release `dados`)

Os dados grandes nunca entram no main. O caminho é sempre automático:

1. O motor roda por estado e grava em `saida/<UF>/` (CSV por município e `geo_<cod>.parquet`).
2. `python motor/publicar_dados.py saida dados-entrada [UF ...]` monta um pacote por estado
   (`raiz_<UF>.tar.gz` com os CSV e `raiz_geo_<UF>.tar.gz` com os polígonos) e o `estados.json`.
   Confere antes que nenhum CSV tem coluna de nome, CPF, CNPJ ou contato, e só refaz o estado que mudou.
   Pacote acima de 90 MB vai em partes (`.part00`, `.part01`...).
3. Commit de `dados-entrada/` num branch de trabalho (`git add -f dados-entrada`) e push.
   O workflow `.github/workflows/publicar-dados.yml` junta as partes e sobe tudo no Release `dados`
   (https://github.com/bernardoemmel/raiz/releases/tag/dados), `estados.json` por último.
4. No commit seguinte, `git rm -r dados-entrada` (os pacotes ficam só no Release). O PR entra no main com
   squash, então o main nunca recebe os pacotes.
5. O front baixa sozinho: `npm run dev` roda antes `front/scripts/baixar-dados.mjs`, que lê o `estados.json`
   publicado e baixa só os estados novos ou mudados para `dados/estados/<UF>/` (fora do git).
   `npm run dados -- --geo` também baixa os polígonos. `RAIZ_SEM_DOWNLOAD=1` pula o download.

`estados.json`, por estado: `municipios` feitos, `total_ibge`, `completo`, contagem por tabela
(`imoveis`, `direto`, `filtros`, `extras`, `extras_direto`, `mapbiomas`, `certidoes`), `versao` (sha256),
`tamanho`, `url`, `atualizado_em` e `geo` (polígonos).

São dados de fontes públicas (CAR, MapBiomas, INPE, FUNAI, INCRA, ICMBio), sem nome, CPF ou CNPJ.

## Release `vigilancia`

A vigilância diária (`raiz/vigilancia/`, workflow `.github/workflows/vigilancia.yml`) lê os polígonos daqui e publica
no Release `vigilancia` (https://github.com/bernardoemmel/raiz/releases/tag/vigilancia): alertas de imóvel por mês
(`alertas_AAAA-MM.parquet`), espelho dos embargos do Ibama, situação das fontes e rodadas, abertos; projetos,
eventos de perda, marcações e rascunhos de relatório num pacote cifrado (`privado.tar.gz.cifrado`, chave
`RAIZ_VIGILANCIA_CHAVE`). `vigilancia.json` (manifesto) sobe por último. Detalhes em `raiz/vigilancia/README.md`.
