#!/usr/bin/env bash
set -euo pipefail

CFG=".vscode/sftp.json"
if [[ ! -f "$CFG" ]]; then
  echo "ERR: $CFG not found" >&2
  exit 2
fi

read_json() {
  python3 - "$1" <<'PY'
import json,sys
key=sys.argv[1]
with open('.vscode/sftp.json','r') as f:
    d=json.load(f)
print(d.get(key,''))
PY
}

HOST=$(read_json host)
USER=$(read_json username)
PASS=$(read_json password)
REMOTE=$(read_json remotePath)

if [[ -z "$HOST" || -z "$USER" || -z "$PASS" || -z "$REMOTE" ]]; then
  echo "ERR: missing FTP config" >&2
  exit 3
fi

DEST="$REMOTE/maxicourses_test"

upload_file(){
  local src="$1" dst_rel="$2"
  local enc
  enc=$(python3 - "$dst_rel" <<'PY'
import urllib.parse,sys
print(urllib.parse.quote(sys.argv[1]))
PY
  )
  local url="ftp://$HOST$DEST/$enc"
  echo "UPLOAD $src -> $url"
  curl -sS --ftp-create-dirs --user "$USER:$PASS" -T "$src" "$url"
}

upload_file maxicourses_test/index.html index.html
upload_file maxicourses_test/results.json results.json

# logos
for f in maxicourses-web/logos/*; do
  [[ -f "$f" ]] || continue
  base=$(basename "$f")
  upload_file "$f" "logos/$base"
done

echo "DEPLOY_DONE http://www.maxicourses.fr/maxicourses_test/"
