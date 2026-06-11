#!/usr/bin/env bash
set -euo pipefail

target="${1:-omni-sandbox}"
mkdir -p "$target"
cd "$target"

if [ ! -d .git ]; then
  git init >/dev/null
fi

cat > package.json <<'JSON'
{
  "name": "omni-sandbox",
  "version": "0.0.0",
  "private": true,
  "packageManager": "pnpm@10.0.0",
  "scripts": {
    "test": "node test.js",
    "build": "node build.js"
  }
}
JSON

cat > test.js <<'JS'
console.log("sandbox test ok");
JS

cat > build.js <<'JS'
console.log("sandbox build ok");
JS

cat > CLAUDE.md <<'MD'
# OmniMemory Sandbox

Use this disposable repository for OmniMemory hook and transcript spikes.
MD

cat > .gitignore <<'GITIGNORE'
.omni/generated/
node_modules/
GITIGNORE

git add package.json test.js build.js CLAUDE.md .gitignore >/dev/null
git -c user.name='Omni Sandbox' -c user.email='omni-sandbox@local.invalid' commit -m 'sandbox init' >/dev/null 2>&1 || true

printf '%s\n' "$PWD"
