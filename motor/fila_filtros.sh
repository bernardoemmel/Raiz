#!/bin/bash
# Roda os filtros territoriais (quilombo, TI FUNAI, CNUC) de cada estado assim que o funil dele fecha na fila.sh.
cd "$(dirname "$0")"
export OGR_GEOJSON_MAX_OBJ_SIZE=0
for uf in PA AC AP RR RO TO MA AM MT GO MS MG BA PI CE RN PB PE AL SE ES RJ SP PR SC RS DF; do
  until grep -q "=== $uf funil fim" fila.log; do sleep 120; done
  echo "=== $uf filtros início $(date -u +%H:%M)"; python3 raiz_filtros.py $uf >> log_filtros_$uf.txt 2>&1; echo "=== $uf filtros fim $(date -u +%H:%M) código $?"
done
