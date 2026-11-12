#!/usr/bin/env bash
# Monta o site público em ./site: o painel na raiz do site e a ficha do produtor em produtor/.
# É o mesmo build nos dois lugares, para o que passa no CI ser o que vai ao ar:
#   - workflow "Publicar o site": depois de baixar os dados do Release e as geometrias, grava os dados no site;
#   - CI de todo PR: com RAIZ_BUILD_DADOS=0 (sem dados), só confere que instala (npm ci) e compila.
# RAIZ_BASE é o caminho do site (no GitHub Pages, /<repositório>/).
set -euo pipefail
cd "$(dirname "$0")/../.."
base="${RAIZ_BASE:-/Raiz/}"

echo "::group::Dependências travadas (npm ci)"
(cd front/globo && npm ci --no-audit --no-fund)
(cd front/produtor && npm ci --no-audit --no-fund)
echo "::endgroup::"

echo "::group::Build do painel"
(cd front/globo && RAIZ_BASE="$base" npm run build)
echo "::endgroup::"

echo "::group::Build da ficha do produtor (lê os dados do painel, em ../)"
(cd front/produtor && RAIZ_BUILD_DADOS=0 VITE_RAIZ_DADOS_BASE=../ npm run build)
echo "::endgroup::"

rm -rf site
cp -r front/globo/dist site
cp -r front/produtor/dist site/produtor
touch site/.nojekyll
echo "Tamanho do site: $(du -sh site | cut -f1), $(find site -type f | wc -l) arquivos"
