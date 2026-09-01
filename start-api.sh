#!/usr/bin/env bash
# Sobe só a API, desacoplada do shell que chamou. Existe porque a API iniciada
# dentro de um bloco de comando morre junto com ele, e a demo perde o backend no
# meio de uma captura.
cd "$(dirname "$0")/backend"
nohup venv/bin/uvicorn main:app --host 127.0.0.1 --port 8400 \
  > "${TMPDIR:-/tmp}/trilho-api.log" 2>&1 &
echo "api pid $!"
