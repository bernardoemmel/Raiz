#!/bin/bash
# Fila nacional: um estado por vez, 3 municípios ao mesmo tempo dentro do estado; depois do funil, camadas extras do estado.
cd "$(dirname "$0")"
export OGR_GEOJSON_MAX_OBJ_SIZE=0 LANES=3
for uf in PA AC AP RR RO TO MA AM MT GO MS MG BA PI CE RN PB PE AL SE ES RJ SP PR SC RS DF; do
  echo "=== $uf início $(date -u +%H:%M)"; python3 raiz_estado.py $uf >> log_$uf.txt 2>&1; echo "=== $uf funil fim $(date -u +%H:%M) código $?"
  if ls extras/raiz_extras*_${uf}*.tif >/dev/null 2>&1; then python3 raiz_extras.py $uf >> log_extras_$uf.txt 2>&1; echo "=== $uf extras fim $(date -u +%H:%M) código $?"; fi
done
