#!/usr/bin/env bash
# Monta o site público em ./site: o painel na raiz do site e a ficha do produtor em produtor/.
# É o mesmo build nos dois lugares, para o que passa no CI ser o que vai ao ar:
#   - workflow "Publicar o site": depois de baixar os dados do Release e as geometrias, grava os dados no site;
#   - CI de todo PR: com dados fictícios isolados, confere instalação, build e navegação real pelo Playwright.
# RAIZ_DOMINIO publica na raiz; sem domínio, GITHUB_REPOSITORY define o caminho do Pages.
# No build local sem essas variáveis, a base é /. RAIZ_BASE permite testar outro subcaminho.
set -euo pipefail
cd "$(dirname "$0")/../.."
configuracao=$(node front/scripts/configurar-publicacao.mjs --ambiente)
mapfile -t publicacao <<< "$configuracao"
export RAIZ_BASE="${publicacao[0]}"
export RAIZ_SITE_URL="${publicacao[1]}"
export RAIZ_DOMINIO="${publicacao[2]:-}"

echo "::group::Dependências travadas (npm ci)"
(cd front/globo && npm ci --no-audit --no-fund)
(cd front/produtor && npm ci --no-audit --no-fund)
echo "::endgroup::"

if [ "${RAIZ_BUILD_DADOS:-1}" != "0" ]; then
  node front/scripts/baixar-calendario.mjs
fi

echo "::group::Build do painel"
(cd front/globo && npm run build)
echo "::endgroup::"

echo "::group::Build da ficha do produtor (lê os dados do painel, em ../)"
(cd front/produtor && RAIZ_BUILD_DADOS=0 VITE_RAIZ_DADOS_BASE=../ npm run build)
echo "::endgroup::"

rm -rf site
cp -r front/globo/dist site
cp -r front/produtor/dist site/produtor
touch site/.nojekyll
node front/scripts/configurar-publicacao.mjs --cname site/CNAME
# O Pages limita o site a 1 GB. Folga para metadados e variações da próxima rodada.
bytes_site=$(du -sb site | cut -f1)
if [ "$bytes_site" -gt 950000000 ]; then
  echo "::error::Site com $bytes_site bytes: excedeu 950 MB. Mover as geometrias para PMTiles por estado antes de publicar."
  exit 1
fi
echo "Tamanho do site: $(du -sh site | cut -f1), $(find site -type f | wc -l) arquivos"
