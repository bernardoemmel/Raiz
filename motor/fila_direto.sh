#!/bin/bash
# Lê YbYrá e GPW direto dos arquivos públicos (sem Earth Engine) de cada estado assim que o funil dele fecha.
cd "$(dirname "$0")"
export OGR_GEOJSON_MAX_OBJ_SIZE=0
for uf in PA AC AP RR RO TO MA AM MT GO MS MG BA PI CE RN PB PE AL SE ES RJ SP PR SC RS DF; do
  until grep -q "=== $uf funil fim" fila.log; do sleep 120; done
  echo "=== $uf direto início $(date -u +%H:%M)"; python3 raiz_direto.py $uf >> log_direto_$uf.txt 2>&1; echo "=== $uf direto fim $(date -u +%H:%M) código $?"
done
