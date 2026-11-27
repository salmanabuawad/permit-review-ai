#!/usr/bin/env bash
#
# Release the Permit360 public website to permit.kortexd.com — run ONLY after the release is approved.
#
#   DEPLOY_HOST=root@185.229.226.37 bash website/deploy/deploy.sh          build + upload + switch
#   DEPLOY_HOST=... bash website/deploy/deploy.sh --no-switch              upload only (preview on the server)
#
# Builds website/dist, runs the static checks, uploads a new release folder, switches the "current" symlink,
# tests nginx and reloads it, and keeps the last five releases. The nginx site itself is installed once by hand
# (see website/deploy/README.md); this script never edits nginx configuration or DNS.
set -euo pipefail

HOST=${DEPLOY_HOST:?set DEPLOY_HOST=user@server}
WEB_ROOT=${WEB_ROOT:-/var/www/permit.kortexd.com}
STAMP=$(date -u +%Y%m%d%H%M%S)
ROOT=$(git rev-parse --show-toplevel)
PY=${PY:-$ROOT/.venv/bin/python}

"$PY" "$ROOT/website/build.py" --base https://permit.kortexd.com --app https://permit360.kortexd.com
python3 "$ROOT/website/tests/check_site.py" --base https://permit.kortexd.com

ssh "$HOST" "mkdir -p $WEB_ROOT/releases/$STAMP"
rsync -az --delete --chown=root:root --chmod=D755,F644 "$ROOT/website/dist/" "$HOST:$WEB_ROOT/releases/$STAMP/"
echo "uploaded release $STAMP"

if [[ ${1:-} != --no-switch ]]; then
  ssh "$HOST" "ln -sfn $WEB_ROOT/releases/$STAMP $WEB_ROOT/current && nginx -t && systemctl reload nginx && ls -1dt $WEB_ROOT/releases/* | tail -n +6 | xargs -r rm -rf"
  echo "switched: https://permit.kortexd.com/ → $STAMP"
fi
