#!/bin/bash
# MapBiomas pela API da Plataforma (sem Earth Engine) de cada estado assim que o funil dele fecha.
# Retoma de onde parou: estado já baixado não é pedido de novo; município com CSV pronto é pulado.
cd "$(dirname "$0")"
export OGR_GEOJSON_MAX_OBJ_SIZE=0
until ! pgrep -f "raiz_mapbiomas.py PA" >/dev/null; do sleep 60; done
for uf in AC AP RR RO TO MA AM MT GO MS MG BA PI CE RN PB PE AL SE ES RJ SP PR SC RS DF; do
  until grep -q "=== $uf funil fim" fila.log; do sleep 120; done
  echo "=== $uf mapbiomas início $(date -u +%H:%M)"; python3 raiz_mapbiomas.py $uf >> log_mapbiomas_$uf.txt 2>&1; echo "=== $uf mapbiomas fim $(date -u +%H:%M) código $?"
done
