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
6. O plugin do Vite (`front/compartilhado/vite-dados.ts` e `pasta-dados.ts`) lê `dados/estados/` sozinho quando
   existe (ou a pasta de `RAIZ_DADOS`); sem ela, a amostra. O mapa do Brasil diz, por estado, o que o `estados.json`
   baixado diz (completo, incompleto com a contagem, ainda não processado), sem recontar.

`estados.json`, por estado: `municipios` feitos, `total_ibge`, `completo`, contagem por tabela
(`imoveis`, `direto`, `filtros`, `extras`, `extras_direto`, `mapbiomas`, `certidoes`), `versao` (sha256),
`tamanho`, `url`, `atualizado_em` e `geo` (polígonos).

São dados de fontes públicas (CAR, MapBiomas, INPE, FUNAI, INCRA, ICMBio), sem nome, CPF ou CNPJ.
