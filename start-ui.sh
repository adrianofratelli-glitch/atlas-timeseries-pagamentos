#!/usr/bin/env bash
# Sobe só o frontend, desacoplado do shell que chamou. Mesma razão do start-api.sh.
cd "$(dirname "$0")/frontend"
nohup npm run preview > "${TMPDIR:-/tmp}/trilho-ui.log" 2>&1 &
echo "ui pid $!"
