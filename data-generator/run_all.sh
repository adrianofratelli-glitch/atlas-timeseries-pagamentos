#!/usr/bin/env bash
# Carga completa. Idempotente nos ativos; as leituras são a exceção — coleção time
# series não tem _id controlado pelo cliente, logo não tem upsert, e recarregar é
# sempre --drop.
#
#   bash data-generator/run_all.sh                 # 20k medidores, 30 dias
#   METERS=5000 DAYS=7 bash data-generator/run_all.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY=.venv/bin/python
METERS="${METERS:-20000}"
DAYS="${DAYS:-30}"

echo "== ativos (${METERS} medidores)"
$PY data-generator/generate_assets.py --meters "$METERS" --drop

echo "== leituras (${DAYS} dias) — a carga longa"
$PY data-generator/generate_readings.py --days "$DAYS" --collection readings \
    --variant span1d --drop

echo "== amostra de comparação (1 dia, coleção normal)"
$PY data-generator/generate_readings.py --days 1 --collection readings_flat --flat --drop

echo "== índices"
if command -v mongosh >/dev/null 2>&1; then
  set -a; . ./.env; set +a
  mongosh "$MONGODB_URI" schema/indexes.js
else
  echo "mongosh não encontrado — rode: mongosh \"\$MONGODB_URI\" schema/indexes.js"
fi
